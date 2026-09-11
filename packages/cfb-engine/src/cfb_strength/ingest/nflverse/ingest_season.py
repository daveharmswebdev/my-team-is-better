"""NFL season-ingestion orchestration (issue #51): fetch (cache-first,
whole-history CSVs) -> filter to requested seasons -> normalize -> write to
the shared sqlite db, alongside the existing (unmodified) CFBD path.

CLI-callable entry point, wired into the umbrella `cfb` CLI via
`cli.py`'s `--sport nfl` branch:

    def main(argv: list[str] | None = None) -> int

Flags:
    --years YEARS        Required. Same syntax as the CFBD path's --years:
                          a single year ("2024"), a range ("2023-2025",
                          inclusive both ends), a comma-separated list, or
                          any mix. Years outside 1999-2025 are skipped with a
                          warning -- 2026 is deliberately excluded even
                          though nflverse's `games.csv` already carries rows
                          for it: that season is still in progress (per
                          issue #51's scope), so ingesting it now would mint
                          real rows for an incomplete season.
    --force               Optional. Bypass the on-disk cache in
                          data/raw/nfl/ and re-fetch both CSVs live,
                          overwriting the cache files.
    --season-types        Optional. Comma-separated subset of {"regular",
                          "postseason"}. Defaults to both.
    --db-path             Optional. Override the sqlite db path.

Returns 0 if every requested year/season-type ingested without a hard error
(a batch with zero games for a requested year/season-type is logged
`status='suspect'` in `ingestion_log`, not a crash). Returns 1 if no valid
years were requested, or a hard error occurred (network/parse/db failure).

Deliberately independent of `cfb_strength.ingest.ingest_season` (the CFBD
orchestration module) -- `import-linter`'s `no-nflverse-import-of-cfbd / no-cfbd-import-of-nflverse`
contract forbids this package from importing it, so small bits of shared
shape (`--years` range parsing) are duplicated here rather than imported.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cfb_strength.config import DB_PATH, SEASON_TYPES
from cfb_strength.contracts import GameRow, TeamRow
from cfb_strength.db.connection import ensure_schema, get_conn
from cfb_strength.ingest.nflverse.client import NflverseClientError, get_games, get_teams
from cfb_strength.ingest.nflverse.normalize import (
    TeamLookup,
    build_team_lookup,
    normalize_game,
    team_rows_from_games,
)

MIN_YEAR = 1999
MAX_YEAR = 2025

_REGULAR_GAME_TYPES = {"REG"}
_POSTSEASON_GAME_TYPES = {"WC", "DIV", "CON", "SB"}


@dataclass(frozen=True)
class IngestResult:
    year: int
    season_type: str
    game_count: int
    status: str
    fetched_live: bool


def parse_years(spec: str) -> list[int]:
    """Parse "2024", "2023-2025", "2023,2024,2025", or a comma-separated mix.

    Deliberately duplicated (not imported) from
    `cfb_strength.ingest.ingest_season.parse_years` -- see this module's
    docstring for why.
    """
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


def _filter_raw_games(
    all_games_raw: list[dict[str, str]], year: int, season_type: str
) -> list[dict[str, str]]:
    wanted_types = _REGULAR_GAME_TYPES if season_type == "regular" else _POSTSEASON_GAME_TYPES
    return [
        g for g in all_games_raw if g["season"] == str(year) and g["game_type"] in wanted_types
    ]


def _assert_no_surrogate_collisions(rows: list[TeamRow] | list[GameRow]) -> None:
    """Defensive collision guard: two different nflverse source_ids must
    never mint the same surrogate id. Won't fire in practice at this data
    volume, but must be checked, not assumed away (per issue #51's spec)."""
    seen: dict[int, str] = {}
    for r in rows:
        assert r.source_id is not None, f"expected source_id on nflverse row id={r.id}"
        prior = seen.get(r.id)
        if prior is not None and prior != r.source_id:
            raise ValueError(
                f"surrogate id collision: id={r.id} minted for both "
                f"source_id={prior!r} and source_id={r.source_id!r}"
            )
        seen[r.id] = r.source_id


def _write_teams(conn: Any, team_rows: list[TeamRow], year: int) -> None:
    """Write `teams` + `team_season` rows for one year's batch.

    `year` comes from the caller's ingest batch, not from the team-desc data
    itself: nflverse's `teams_colors_logos.csv` is a single current-snapshot
    file with no per-year conference history (unlike CFBD's per-game
    conference field), so the same snapshot conference is written for every
    season in #51's 2023-2025 window. Acceptable here since there's no known
    conference realignment in that window; would need revisiting for a
    wider historical backfill.
    """
    _assert_no_surrogate_collisions(team_rows)
    for tr in team_rows:
        conn.execute(
            """
            INSERT INTO teams (id, school, classification, sport, source_id)
            VALUES (:id, :school, :classification, :sport, :source_id)
            ON CONFLICT(id) DO UPDATE SET
                school = excluded.school,
                classification = COALESCE(excluded.classification, teams.classification),
                sport = excluded.sport,
                source_id = excluded.source_id
            """,
            {
                "id": tr.id,
                "school": tr.school,
                "classification": tr.classification,
                "sport": tr.sport,
                "source_id": tr.source_id,
            },
        )
        conn.execute(
            """
            INSERT INTO team_season (team_id, year, conference, classification, sport)
            VALUES (:team_id, :year, :conference, :classification, :sport)
            ON CONFLICT(team_id, year) DO UPDATE SET
                conference = excluded.conference,
                classification = excluded.classification,
                sport = excluded.sport
            """,
            {
                "team_id": tr.id,
                "year": year,
                "conference": tr.conference,
                "classification": tr.classification,
                "sport": tr.sport,
            },
        )


def _write_games(conn: Any, game_rows: list[GameRow]) -> None:
    _assert_no_surrogate_collisions(game_rows)
    for gr in game_rows:
        conn.execute(
            """
            INSERT INTO games (
                id, season, week, season_type, start_date, neutral_site,
                completed, home_team_id, away_team_id, home_team, away_team,
                home_points, away_points, home_conference, away_conference,
                venue, raw_json, sport, source_id
            ) VALUES (
                :id, :season, :week, :season_type, :start_date, :neutral_site,
                :completed, :home_team_id, :away_team_id, :home_team, :away_team,
                :home_points, :away_points, :home_conference, :away_conference,
                :venue, :raw_json, :sport, :source_id
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
                raw_json = excluded.raw_json,
                sport = excluded.sport,
                source_id = excluded.source_id
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
                "sport": gr.sport,
                "source_id": gr.source_id,
            },
        )


def _write_ingestion_log(
    conn: Any, year: int, season_type: str, game_count: int, status: str
) -> None:
    conn.execute(
        """
        INSERT INTO ingestion_log (year, season_type, fetched_at, game_count, status, sport)
        VALUES (:year, :season_type, :fetched_at, :game_count, :status, 'nfl')
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
    conn: Any,
    year: int,
    season_type: str,
    all_games_raw: list[dict[str, str]],
    team_lookup: TeamLookup,
    *,
    fetched_live: bool = False,
) -> IngestResult:
    """Filter, normalize, and write one year/season-type batch. `all_games_raw`
    is the whole-history `games.csv` rows already loaded by the caller (this
    module fetches that once per `main()` invocation, not once per batch)."""
    raw_batch = _filter_raw_games(all_games_raw, year, season_type)
    game_rows = [normalize_game(g, team_lookup) for g in raw_batch]
    team_rows = team_rows_from_games(raw_batch, team_lookup)

    _write_teams(conn, team_rows, year)
    _write_games(conn, game_rows)

    status = "ok" if len(game_rows) > 0 else "suspect"
    _write_ingestion_log(conn, year, season_type, len(game_rows), status)
    conn.commit()

    return IngestResult(
        year=year,
        season_type=season_type,
        game_count=len(game_rows),
        status=status,
        fetched_live=fetched_live,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ingest-season-nflverse",
        description="Ingest nflverse NFL game/team data into the project sqlite db.",
    )
    parser.add_argument(
        "--years",
        required=True,
        help='Years to ingest: "2024", "2023-2025", "2023,2024,2025", or a mix.',
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass the on-disk cache and re-fetch both CSVs live from nflverse.",
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
            f"warning: skipping years outside {MIN_YEAR}-{MAX_YEAR}: {skipped_years} "
            "(2026 is in progress and explicitly out of scope for issue #51)",
            file=sys.stderr,
        )
    if not years:
        print(f"error: no valid years to ingest after filtering to {MIN_YEAR}-{MAX_YEAR}", file=sys.stderr)
        return 1

    season_types = [s.strip() for s in args.season_types.split(",") if s.strip()]
    unknown_types = [s for s in season_types if s not in SEASON_TYPES]
    if unknown_types:
        print(f"error: unknown season type(s) {unknown_types}, expected {SEASON_TYPES}", file=sys.stderr)
        return 1

    db_path = Path(args.db_path) if args.db_path else DB_PATH

    try:
        games_raw, games_fetched_live = get_games(force=args.force)
        teams_raw, teams_fetched_live = get_teams(force=args.force)
    except NflverseClientError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    team_lookup = build_team_lookup(teams_raw)
    fetched_live = games_fetched_live or teams_fetched_live

    conn = get_conn(db_path)
    ensure_schema(conn)

    hard_errors: list[str] = []
    results: list[IngestResult] = []

    try:
        for year in years:
            for season_type in season_types:
                try:
                    result = ingest_one(
                        conn,
                        year,
                        season_type,
                        games_raw,
                        team_lookup,
                        fetched_live=fetched_live,
                    )
                except (ValueError, KeyError) as e:
                    hard_errors.append(f"{year} {season_type}: {e}")
                    print(f"error: {year} {season_type}: {e}", file=sys.stderr)
                    continue
                results.append(result)
                flag = "" if result.status == "ok" else "  <-- SUSPECT (no games in batch)"
                print(
                    f"{result.year} {result.season_type:<10} "
                    f"games={result.game_count:<5} status={result.status}{flag}"
                )
    finally:
        conn.close()

    print(f"\nlive fetches this run: {'yes' if fetched_live else 'no (cache hit)'}")
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
