"""Season-ingestion orchestration: fetch (cache-first) -> normalize -> write to
the sqlite db, for a set of years and season types.

CLI-callable entry point for the coordinator's umbrella CLI:

    def main(argv: list[str] | None = None) -> int

Flags:
    --years YEARS       Required. Accepts a single year ("2005"), a range
                         ("1998-2025", inclusive both ends), a comma-separated
                         list ("2000,2005,2010"), or any comma-separated mix of
                         those ("2000-2005,2010,2015-2020"). Years outside
                         1998-2025 are skipped with a warning (not fetched --
                         that's the full range this project's cache covers,
                         per PRD §5.2's modern/BCS-CFP-era data scope).
    --force             Optional. Bypass the on-disk cache in data/raw/ and
                         re-fetch live from the CFBD API for every requested
                         year/season-type, overwriting the cache file. Also
                         re-fetches data/raw/teams.json for the alias step.
    --season-types      Optional. Comma-separated subset of {"regular",
                         "postseason"}. Defaults to both (config.SEASON_TYPES).
    --db-path           Optional. Override the sqlite db path (defaults to
                         config.DB_PATH / $CFB_DB_PATH).

After the year loop, the run enriches `teams.mascot` /
`teams.alternate_names` from CFBD `/teams` exactly once (issue #77) -- see
`enrich_team_aliases` for why that is once per run and not once per batch.

Returns 0 if every requested year/season-type ingested without a hard error
(individual years can still be logged as "suspect" in `ingestion_log` without
failing the run -- that's a data-completeness signal, not a crash). Returns 1
if no valid years were requested, or if any year/season-type hit a hard error
(network/API/db failure) -- note that ingestion still continues for all other
requested year/season-types in that case (a degraded run, not an aborted one);
check stderr for exactly which batches failed and stdout for which succeeded.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cfb_strength.config import DB_PATH, RAW_DIR, SEASON_TYPES
from cfb_strength.contracts import GameRow, TeamRow
from cfb_strength.db.connection import ensure_schema, get_conn
from cfb_strength.ingest.client import CFBDClientError, get_games, get_teams
from cfb_strength.ingest.normalize import (
    dedupe_game_records,
    normalize_game,
    team_rows_from_cfbd_teams,
    team_rows_from_game,
)

MIN_YEAR = 1998
MAX_YEAR = 2025

# Completeness heuristic: count games where at least one side is FBS
# ("fbs_game_count" below), rather than the raw total games in the response.
# CFBD's /games coverage of FCS/II/III-vs-itself games is inconsistent across
# years (near-zero before ~2019, large majority of the payload by 2022-2023),
# so the raw total is not a stable completeness signal across the full
# 1998-2025 range. The FBS-involving subset is stable year over year (roughly
# 540-890 for regular season, 25-46 for postseason across the cached files --
# confirmed against the full 1998-2025 cache while closing issue #9, not just
# the original 2000-2023 subset), so it's what these floors are calibrated
# against.
REGULAR_FBS_GAME_FLOOR = 500
POSTSEASON_FBS_GAME_FLOOR = 20


@dataclass(frozen=True)
class IngestResult:
    year: int
    season_type: str
    game_count: int
    fbs_game_count: int
    status: str
    fetched_live: bool
    # Raw records collapsed into another record for the same real game
    # (issue #125). `game_count` is the number of games actually written.
    duplicates_dropped: int = 0


@dataclass(frozen=True)
class AliasEnrichmentResult:
    """Outcome of the once-per-run `/teams` alias enrichment."""

    payload_records: int
    schools_with_aliases: int
    rows_updated: int
    fetched_live: bool


def parse_years(spec: str) -> list[int]:
    """Parse "2005", "1998-2025", "2000,2005,2010", or a comma-separated mix."""
    years: set[int] = set()
    for token in spec.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            start_s, _, end_s = token.partition("-")
            start, end = int(start_s.strip()), int(end_s.strip())
            if start > end:
                start, end = end, start
            years.update(range(start, end + 1))
        else:
            years.add(int(token))
    return sorted(years)


def _fbs_game_count(games: list[dict[str, Any]]) -> int:
    return sum(
        1
        for g in games
        if g.get("homeClassification") == "fbs" or g.get("awayClassification") == "fbs"
    )


def _write_teams(conn: Any, team_rows: dict[int, TeamRow], year: int) -> None:
    for tr in team_rows.values():
        conn.execute(
            """
            INSERT INTO teams (id, school, classification)
            VALUES (:id, :school, :classification)
            ON CONFLICT(id) DO UPDATE SET
                school = excluded.school,
                classification = COALESCE(excluded.classification, teams.classification)
            """,
            {"id": tr.id, "school": tr.school, "classification": tr.classification},
        )
        conn.execute(
            """
            INSERT INTO team_season (team_id, year, conference, classification)
            VALUES (:team_id, :year, :conference, :classification)
            ON CONFLICT(team_id, year) DO UPDATE SET
                conference = excluded.conference,
                classification = excluded.classification
            """,
            {
                "team_id": tr.id,
                "year": year,
                "conference": tr.conference,
                "classification": tr.classification,
            },
        )


def _write_games(conn: Any, game_rows: list[GameRow]) -> None:
    for gr in game_rows:
        conn.execute(
            """
            INSERT INTO games (
                id, season, week, season_type, start_date, neutral_site,
                completed, home_team_id, away_team_id, home_team, away_team,
                home_points, away_points, home_conference, away_conference,
                venue, raw_json
            ) VALUES (
                :id, :season, :week, :season_type, :start_date, :neutral_site,
                :completed, :home_team_id, :away_team_id, :home_team, :away_team,
                :home_points, :away_points, :home_conference, :away_conference,
                :venue, :raw_json
            )
            ON CONFLICT(id) DO UPDATE SET
                season = excluded.season,
                week = excluded.week,
                season_type = excluded.season_type,
                start_date = excluded.start_date,
                neutral_site = excluded.neutral_site,
                completed = excluded.completed,
                home_team_id = excluded.home_team_id,
                away_team_id = excluded.away_team_id,
                home_team = excluded.home_team,
                away_team = excluded.away_team,
                home_points = excluded.home_points,
                away_points = excluded.away_points,
                home_conference = excluded.home_conference,
                away_conference = excluded.away_conference,
                venue = excluded.venue,
                raw_json = excluded.raw_json
            """,
            {
                "id": gr.id,
                "season": gr.season,
                "week": gr.week,
                "season_type": gr.season_type,
                "start_date": gr.start_date,
                "neutral_site": gr.neutral_site,
                "completed": gr.completed,
                "home_team_id": gr.home_team_id,
                "away_team_id": gr.away_team_id,
                "home_team": gr.home_team,
                "away_team": gr.away_team,
                "home_points": gr.home_points,
                "away_points": gr.away_points,
                "home_conference": gr.home_conference,
                "away_conference": gr.away_conference,
                "venue": gr.venue,
                "raw_json": gr.raw_json,
            },
        )


def enrich_team_aliases(
    conn: Any, *, force: bool = False, raw_dir: Path = RAW_DIR
) -> AliasEnrichmentResult:
    """Fill in `teams.mascot` / `teams.alternate_names` from CFBD `/teams`.

    Runs ONCE per ingest run, not once per year/season-type: the `/teams`
    payload this reads is fetched with no `year` param and is therefore
    year-independent, so doing it inside `ingest_one` would repeat identical
    work 56 times (28 years x 2 season types) for one identical result.

    This is an *enrichment of teams the `/games` ingest already discovered*,
    not a second source of team rows -- hence a plain UPDATE rather than the
    INSERT ... ON CONFLICT upsert `_write_teams` uses. Inserting all 1933
    `/teams` records would put unrated, never-played teams into the picker's
    universe, and only an UPDATE can structurally guarantee that can't happen.
    Three further consequences of the same choice:

      * `school` is never written, only matched on. It is the canonical
        identity string the verdict lookup, the persona grounding check's
        known-team-names universe, the golden dataset, and every cached
        narration key depend on.
      * teams in our table but absent from `/teams` simply keep
        `mascot = NULL`. Expected (Cal State Northridge is one), never an
        error.
      * `sport = 'cfb'` scopes the match, so a CFB school name can never
        overwrite an NFL row's columns.

    Idempotent by construction: re-running writes the same values to the same
    rows. Raises `CFBDClientError` if there is neither a `data/raw/teams.json`
    cache nor an API key -- the caller handles that the same way it handles a
    failed year batch (report it, keep going).
    """
    teams_raw, fetched_live = get_teams(force=force, raw_dir=raw_dir)
    by_school = team_rows_from_cfbd_teams(teams_raw)

    schools_with_aliases = 0
    rows_updated = 0
    for tr in by_school.values():
        if tr.mascot is None and not tr.alternate_names:
            # Nothing to contribute; skip rather than write NULL/'[]' over
            # whatever a previous run may have learned.
            continue
        schools_with_aliases += 1
        cur = conn.execute(
            """
            UPDATE teams
               SET mascot = COALESCE(:mascot, mascot),
                   alternate_names = COALESCE(:alternate_names, alternate_names)
             WHERE school = :school AND sport = 'cfb'
            """,
            {
                "mascot": tr.mascot,
                "alternate_names": (
                    json.dumps(list(tr.alternate_names), ensure_ascii=False)
                    if tr.alternate_names
                    else None
                ),
                "school": tr.school,
            },
        )
        rows_updated += max(cur.rowcount, 0)
    conn.commit()

    return AliasEnrichmentResult(
        payload_records=len(teams_raw),
        schools_with_aliases=schools_with_aliases,
        rows_updated=rows_updated,
        fetched_live=fetched_live,
    )


def _write_ingestion_log(
    conn: Any, year: int, season_type: str, game_count: int, status: str
) -> None:
    conn.execute(
        """
        INSERT INTO ingestion_log (year, season_type, fetched_at, game_count, status, sport)
        VALUES (:year, :season_type, :fetched_at, :game_count, :status, 'cfb')
        ON CONFLICT(year, season_type, sport) DO UPDATE SET
            fetched_at = excluded.fetched_at,
            game_count = excluded.game_count,
            status = excluded.status
        """,
        {
            "year": year,
            "season_type": season_type,
            "fetched_at": datetime.now(UTC).isoformat(),
            "game_count": game_count,
            "status": status,
        },
    )


def ingest_one(
    conn: Any, year: int, season_type: str, *, force: bool = False
) -> IngestResult:
    """Fetch (cache-first), normalize, and write one year/season-type batch."""
    games_raw, fetched_live = get_games(year, season_type, force=force)

    # Issue #125: CFBD lists some real games twice under two game ids. This
    # collapse happens before anything else reads the batch, so a duplicated
    # game is written once, counted once toward the completeness floor, and
    # can't mint a `teams` row for an id seen only on the dropped copy
    # (Edward Waters `1000899`, #91). See `dedupe_game_records`.
    games = dedupe_game_records(games_raw)

    game_rows = [normalize_game(g, season=year, season_type=season_type) for g in games]

    team_rows: dict[int, TeamRow] = {}
    for g in games:
        for tr in team_rows_from_game(g):
            team_rows[tr.id] = tr

    _write_teams(conn, team_rows, year)
    _write_games(conn, game_rows)

    fbs_count = _fbs_game_count(games)
    floor = REGULAR_FBS_GAME_FLOOR if season_type == "regular" else POSTSEASON_FBS_GAME_FLOOR
    status = "ok" if fbs_count >= floor else "suspect"

    _write_ingestion_log(conn, year, season_type, len(games), status)
    conn.commit()

    return IngestResult(
        year=year,
        season_type=season_type,
        game_count=len(games),
        fbs_game_count=fbs_count,
        status=status,
        fetched_live=fetched_live,
        duplicates_dropped=len(games_raw) - len(games),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ingest-season",
        description="Ingest CFBD game/team data into the project sqlite db.",
    )
    parser.add_argument(
        "--years",
        required=True,
        help='Years to ingest: "2005", "1998-2025", "2000,2005,2010", or a mix.',
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass the on-disk cache and re-fetch live from the CFBD API.",
    )
    parser.add_argument(
        "--season-types",
        default=",".join(SEASON_TYPES),
        help='Comma-separated subset of "regular,postseason". Defaults to both.',
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="Override the sqlite db path (defaults to config.DB_PATH).",
    )
    args = parser.parse_args(argv)

    try:
        requested_years = parse_years(args.years)
    except ValueError as e:
        print(f"error: could not parse --years {args.years!r}: {e}", file=sys.stderr)
        return 1

    years = [y for y in requested_years if MIN_YEAR <= y <= MAX_YEAR]
    skipped_years = [y for y in requested_years if y not in years]
    if skipped_years:
        print(
            f"warning: skipping years outside {MIN_YEAR}-{MAX_YEAR}: {skipped_years}",
            file=sys.stderr,
        )
    if not years:
        print("error: no valid years to ingest after filtering to 1998-2025", file=sys.stderr)
        return 1

    season_types = [s.strip() for s in args.season_types.split(",") if s.strip()]
    unknown_types = [s for s in season_types if s not in SEASON_TYPES]
    if unknown_types:
        print(f"error: unknown season type(s) {unknown_types}, expected {SEASON_TYPES}", file=sys.stderr)
        return 1

    db_path = Path(args.db_path) if args.db_path else DB_PATH
    conn = get_conn(db_path)
    ensure_schema(conn)

    live_calls = 0
    hard_errors: list[str] = []
    results: list[IngestResult] = []

    try:
        for year in years:
            for season_type in season_types:
                try:
                    result = ingest_one(conn, year, season_type, force=args.force)
                except CFBDClientError as e:
                    hard_errors.append(f"{year} {season_type}: {e}")
                    print(f"error: {year} {season_type}: {e}", file=sys.stderr)
                    continue
                results.append(result)
                if result.fetched_live:
                    live_calls += 1
                flag = "" if result.status == "ok" else "  <-- SUSPECT (below completeness floor)"
                dupes = (
                    f"  duplicates_dropped={result.duplicates_dropped}"
                    if result.duplicates_dropped
                    else ""
                )
                print(
                    f"{result.year} {result.season_type:<10} "
                    f"games={result.game_count:<5} fbs_games={result.fbs_game_count:<4} "
                    f"status={result.status}{flag}{dupes}"
                )

        # Once per run, not once per batch -- the /teams payload is
        # year-independent (see enrich_team_aliases).
        try:
            alias_result = enrich_team_aliases(conn, force=args.force)
        except CFBDClientError as e:
            hard_errors.append(f"team aliases: {e}")
            print(f"error: team aliases: {e}", file=sys.stderr)
        else:
            if alias_result.fetched_live:
                live_calls += 1
            source = "live fetch" if alias_result.fetched_live else "cache"
            print(
                f"\nteam aliases   payload={alias_result.payload_records} "
                f"with_aliases={alias_result.schools_with_aliases} "
                f"rows_updated={alias_result.rows_updated} ({source})"
            )
    finally:
        conn.close()

    print(f"\nlive API calls made: {live_calls}")
    if hard_errors:
        print(f"\n{len(hard_errors)} year/season-type batch(es) failed to ingest:", file=sys.stderr)
        for msg in hard_errors:
            print(f"  - {msg}", file=sys.stderr)

    if not results:
        return 1
    if hard_errors:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
