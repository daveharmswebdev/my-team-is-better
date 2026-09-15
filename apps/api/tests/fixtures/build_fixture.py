"""One-off generator for `cfb_verdict_fixture.sqlite3`.

NOT part of the pytest suite (doesn't match `test_*.py`, not collected) and
NOT imported by anything under `apps/api/src` or `apps/api/tests/test_*.py`.
It exists purely so a human/agent can regenerate the committed fixture by
running it directly, from the repo root:

    uv run --project packages/cfb-engine python apps/api/tests/fixtures/build_fixture.py

`--source`, `--output` and `--raw-dir` override the three paths below (for a
scratch build or a sabotage check); the defaults are the committed files.
The NFL slice is always ingested from the committed cache, whatever
`--raw-dir` says (see "The NFL player slice" below).

This is the *only* place in `apps/api/` that imports `cfb_strength.ratings`
(`compute_and_store`) or `cfb_strength.ingest` (`currency.check_currency`,
the `cfb doctor` check, and the nflverse games and player ingests) --
everything else in this app (route code and the actual pytest suite) only
ever opens the pre-baked output db this script produces, via `get_conn`,
which keeps the "no ratings/ingest import in app/test runtime" rule intact
for every file pytest actually collects.

That exception is sanctioned, and it is *structural* rather than suppressed:
`apps/api/.importlinter` (issue #54) forbids `api -> cfb_strength.ratings`
and `api -> cfb_strength.ingest`, and this file is not part of the `api`
package, so it is not in that graph and needs no ignore rule. Verified both
ways when #54 landed -- the contract stays KEPT with this import here, and
copying this same file into `src/api/` reported
`api._sabotage_fixture -> cfb_strength.ratings.compute_ratings` BROKEN.
So the rule to respect is: a build/generator script that reaches for
`ratings` or `ingest` belongs here, never under `src/api/`. Do not "fix" a
future violation by adding an ignore directive to `.importlinter`.

Provenance
----------
Starts from `packages/cfb-engine/tests/fixtures/cfb_regression.sqlite3`, which
`packages/cfb-engine/tests/fixtures/build_regression_fixtures.py` builds
through the real, cache-first ingest at the current schema (issue #110): CFB
seasons 2001, 2003, 2004, 2005, 2013, 2017 and 2019 -- the PRD's seven golden
years -- with real `teams.mascot` / `teams.alternate_names` from the committed
CFBD `/teams` cache, and no ratings. Regenerate this fixture whenever that one
is regenerated. This script then bakes in real ratings for those same seven
years so `apps/api`'s test suite has real, non-mocked evidentiary data to hit
through the HTTP layer, including the 2005 Texas-over-USC golden-dataset case
and all seven years' champions (`tests/test_verdict_golden_years.py`, the
ground issue #109's persona smoke eval stands on).

The NFL player slice (issue #296)
---------------------------------
It also ingests a small real NFL slice, `NFL_YEARS` = 1999 and 2023, so the
player endpoints (`/api/players/leaders`, `/api/players/{player_id}`) are
exercised on real data by pytest and by the Playwright e2e run, which boots
the API on this same file. The two seasons are chosen for what they cover:
1999 has Kurt Warner's 1999_01_BAL_STL, a completed game with no player stat
lines at all (`games_without_stat_lines`); 2023 is a modern season with
playoffs. The slice goes through the real cache-first ingest in the order
render.yaml runs it -- the nflverse games ingest (`cfb ingest --sport nfl`),
then the player ingest (`cfb ingest-players --sport nfl`) -- by calling those
two entry points' `main` with `--db-path` pointed at the build. Both read
`config.RAW_DIR`, so the build refuses to run unless that is the committed
cache, and every live nflverse fetch is replaced by a function that raises
for the duration.

No NFL ratings are stored (`NFL_RATED_METHODS` is empty): nothing the player
endpoints read needs them, and rating two non-contiguous NFL seasons would
have the same `elo_career` problem as the CFB seasons below. So `/api/years`
and the verdict routes still answer `sport=nfl` exactly as before (no rated
years), while `/api/teams?sport=nfl` without a year now lists the teams those
two seasons' games name.

Because the source is current-schema, `ensure_schema` must be a no-op on it.
The build runs it with `StaleDatabaseWarning` raised as an error. If that
warning fires, the engine fixture is stale and must be rebuilt first. It is a
failure, never something to suppress or migrate past.

Two currency checks bracket the build: `cfb_strength.ingest.currency
.check_currency` (what `cfb doctor` runs), against the committed
`packages/cfb-engine/data/raw`. The first runs on the source, before anything
is written; the second on the finished output. A fixture is a deliberate
season slice, so it can never pass the doctor outright. Exactly the findings
`.claude/agents/validator.md` waives for a slice are allowed, and each only
for the reason the slice gives:

- `season_behind_cache`: only for seasons the fixture omits, per league --
  CFB seasons outside `YEARS`, NFL seasons outside `NFL_YEARS` (on the
  source, which carries no NFL yet, every NFL season).
- `season_missing_ratings`: for CFB, on the source every method for exactly
  the seven seasons (the source stores no ratings), on the output only the
  methods deliberately not baked (`elo_career`, below). For NFL, only on the
  output, for exactly `NFL_YEARS`, and only because `NFL_RATED_METHODS` is
  empty.
- `league_has_no_games`: only for NFL, and only on the source.

On top of the findings, the per-league report must show exactly the slice:
CFB game seasons `YEARS`, NFL game seasons `NFL_YEARS` (none on the source),
the rated seasons each method is expected to have, and player stats for
exactly `NFL_YEARS` in NFL and none in CFB. `season_missing_player_stats` is
never waived: the NFL slice must carry player stats for both its seasons.
Anything else fails the build: `schema_not_current`, `no_cfb_mascots` (a
source built without the #77 alias enrichment -- the old pre-#110 fixture had
none), `raw_cache_*`, `cache_past_max_year`, `season_missing_elo_ledger` and
`season_missing_player_stats`.

What that bracket does NOT check: it compares (season, season_type) *pairs*
against the cache, never individual games. A source missing some games inside
a golden season -- even a title game -- still has that season's regular and
postseason pairs, so it passes both currency checks. The only build-time
guard against that is the Keener golden check below (the #1 school and its
record for each golden year), and it catches a missing game only when the
game moves a #1 or that #1's record. A missing game that changes neither
passes the whole build. Completeness of the games inside a season is the
engine fixture generator's job (`build_regression_fixtures.py` ingests every
cached game), not something this script verifies. For the NFL slice the
ingest reads every cached game of both seasons itself.

Two methods are baked, `keener` and `elo`, for each of the seven years. Elo
was added when `method` became a validated Literal: `elo` is a shipped,
credited method, and with keener-only rows no test could tell "Elo works
end-to-end through the API" from "Elo is silently returning nothing". The
two methods live side by side in the same `ratings`/`rating_breakdowns`
tables, scoped by the `method` column, so every keener assertion is untouched
by the addition.

`elo_career` is deliberately NOT baked. Its offseason mean reversion fires
once per *elapsed* year, and these seven seasons are non-contiguous (2001,
2003-2005, 2013, 2017, 2019), so it would apply reversions for the 2005->2013,
2013->2017 and 2017->2019 gaps that are an artifact of which seasons this
fixture happens to carry, not of real football calendars. The resulting
ratings would model nothing and would be actively misleading to assert
against. Tracked as issue #98; `method="elo_career"` is still accepted by the
API (it is a registered method) and correctly returns nothing here.

Issue #183: `elo` also records an Elo ledger (`elo_ledger_steps`,
`elo_ledger_configs`), the shown work the API serves as `elo_ledger`.
`check_elo_ledgers` fails the build unless every elo-rated team has ledger
steps, a config row, and a final `rating_after` equal to its rating -- so a
fixture whose ledger writer skipped a team, or whose chain drifted from the
rating, never gets committed for the API tests to trust.

Determinism: `compute_and_store` stamps `computed_at` with the wall clock in
every table it writes, and the nflverse games ingest stamps
`ingestion_log.fetched_at` the same way. Those are the only run-dependent
values the build writes (the player ingest mints ids from the source's own
ids), listed in `STAMPED_COLUMNS`. The build overwrites each with
`FIXTURE_COMPUTED_AT` -- the same placeholder the engine fixture already
carries in `fetched_at` -- and VACUUMs, so rerunning on an unchanged source,
cache and engine produces a byte-identical file (with the same SQLite build).
Nothing in `apps/api` or `apps/web` reads either column.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sqlite3
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import NoReturn

from cfb_strength import config
from cfb_strength.contracts import Method, Sport
from cfb_strength.db.connection import StaleDatabaseWarning, ensure_schema, get_conn
from cfb_strength.ingest.currency import check_currency
from cfb_strength.ingest.nflverse import client as nflverse_client
from cfb_strength.ingest.nflverse import ingest_players as nflverse_players
from cfb_strength.ingest.nflverse import ingest_season as nflverse_games
from cfb_strength.ratings.compute_ratings import compute_and_store

THIS_DIR = Path(__file__).resolve().parent
ENGINE_DIR = THIS_DIR.parents[3] / "packages" / "cfb-engine"
SOURCE_FIXTURE = ENGINE_DIR / "tests" / "fixtures" / "cfb_regression.sqlite3"
# The committed cache, named explicitly rather than via `config.RAW_DIR`,
# which `CFB_DATA_DIR` can point somewhere else.
COMMITTED_RAW_DIR = ENGINE_DIR / "data" / "raw"
OUTPUT_FIXTURE = THIS_DIR / "cfb_verdict_fixture.sqlite3"

YEARS: tuple[int, ...] = (2001, 2003, 2004, 2005, 2013, 2017, 2019)
# See the module docstring for why `elo_career` is excluded.
METHODS: tuple[Method, ...] = ("keener", "elo")

# The NFL player slice (issue #296); see "The NFL player slice" above.
NFL_YEARS: tuple[int, ...] = (1999, 2023)
# Deliberately empty: the NFL slice stores games and player stats, no ratings.
NFL_RATED_METHODS: tuple[Method, ...] = ()

# A fixed placeholder, not a real computation time. See "Determinism" above.
FIXTURE_COMPUTED_AT = "1970-01-01T00:00:00+00:00"

# year -> (Keener #1 school, wins, losses, contested). The same pins as the
# engine's `test_golden_dataset_regressions.py`. For the two contested years
# the pinned team is the answer the engine computes, not a claim that it is
# the right champion.
KEENER_CHAMPIONS: dict[int, tuple[str, int, int, bool]] = {
    2001: ("Miami", 12, 0, False),
    2003: ("LSU", 13, 1, True),
    2004: ("USC", 13, 0, False),
    2005: ("Texas", 13, 0, False),
    2013: ("Florida State", 14, 0, False),
    2017: ("Alabama", 13, 1, True),
    2019: ("LSU", 15, 0, False),
}

WAIVABLE_FOR_A_SLICE = frozenset(
    {"season_behind_cache", "season_missing_ratings", "league_has_no_games"}
)

# The baked methods that record an Elo ledger (issue #183). Keener has a
# `rating_breakdown` instead; `elo_career` records none and is not baked.
LEDGER_METHODS: tuple[Method, ...] = ("elo",)

# Every (table, column) the build writes with the wall clock. See "Determinism".
STAMPED_COLUMNS: tuple[tuple[str, str], ...] = (
    ("ratings", "computed_at"),
    ("rating_breakdowns", "computed_at"),
    ("elo_ledger_steps", "computed_at"),
    ("elo_ledger_configs", "computed_at"),
    ("ingestion_log", "fetched_at"),
)


def check_elo_ledgers(conn: sqlite3.Connection) -> None:
    """Fail unless every team rated by a `LEDGER_METHODS` method, in every
    baked year, has an Elo ledger whose chain lands on its rating (#183).

    Checked per rated team rather than per stored step, so a team the writer
    skipped entirely is caught, not only a short one: it must have ledger
    steps, a config row for its (year, method), and a final step (highest
    `game_number`) whose `rating_after` equals its `ratings.rating` exactly.
    Exactly, because the engine's final `rating_after` *is* the rating (the
    walk's own addition) and both are stored from that one float."""
    placeholders = ", ".join("?" for _ in LEDGER_METHODS)
    rows = conn.execute(
        f"""
        SELECT r.year AS year, r.method AS method, t.school AS school,
               r.rating AS rating,
               (SELECT COUNT(*) FROM elo_ledger_steps s
                 WHERE s.year = r.year AND s.method = r.method
                   AND s.sport = r.sport AND s.team_id = r.team_id) AS steps,
               (SELECT s.rating_after FROM elo_ledger_steps s
                 WHERE s.year = r.year AND s.method = r.method
                   AND s.sport = r.sport AND s.team_id = r.team_id
                 ORDER BY s.game_number DESC LIMIT 1) AS final_rating_after,
               EXISTS (SELECT 1 FROM elo_ledger_configs c
                 WHERE c.year = r.year AND c.method = r.method
                   AND c.sport = r.sport) AS has_config
        FROM ratings r JOIN teams t ON t.id = r.team_id
        WHERE r.method IN ({placeholders})
        ORDER BY r.method, r.year, r.rank
        """,
        LEDGER_METHODS,
    ).fetchall()
    if not rows:
        raise AssertionError(f"no ratings rows at all for ledger methods {LEDGER_METHODS}")

    broken: list[str] = []
    for row in rows:
        where = f"{row['year']} {row['method']} {row['school']}"
        if row["steps"] == 0:
            broken.append(f"{where}: no elo_ledger_steps rows")
        elif not row["has_config"]:
            broken.append(f"{where}: no elo_ledger_configs row")
        elif row["final_rating_after"] != row["rating"]:
            broken.append(
                f"{where}: final rating_after {row['final_rating_after']!r} "
                f"!= rating {row['rating']!r}"
            )
    if broken:
        raise AssertionError(
            f"{len(broken)} of {len(rows)} ledger-method ratings have no ledger landing on "
            "their rating (issue #183):\n  - " + "\n  - ".join(broken)
        )
    print(f"elo ledger check passed: {len(rows)} ratings, each with a ledger ending on its rating")


def _record(wins: int, losses: int, ties: int) -> str:
    """W-L-T when ties > 0, W-L otherwise -- the engine's record rule (#83)."""
    return f"{wins}-{losses}-{ties}" if ties else f"{wins}-{losses}"


def check_slice_currency(
    db_path: Path,
    raw_dir: Path,
    *,
    rated_methods: tuple[Method, ...],
    nfl_seasons: tuple[int, ...],
) -> None:
    """Fail unless `db_path`'s only `cfb doctor` findings are the ones a slice
    explains: CFB seasons `YEARS` rated for exactly `rated_methods`, plus NFL
    seasons `nfl_seasons` (empty before the NFL slice is ingested) with player
    stats and no ratings. See the module docstring for the rules."""
    report = check_currency(db_path, raw_dir)
    slices: dict[Sport, tuple[int, ...]] = {"cfb": YEARS, "nfl": nfl_seasons}
    league_rated_methods: dict[Sport, tuple[Method, ...]] = {
        "cfb": rated_methods,
        "nfl": NFL_RATED_METHODS,
    }
    unexplained: list[str] = []

    for problem in report.problems:
        explained = False
        sliced = slices.get(problem.sport) if problem.sport is not None else None
        if sliced is None:
            explained = False
        elif problem.code == "league_has_no_games":
            explained = problem.sport == "nfl" and not sliced
        elif problem.code == "season_behind_cache":
            explained = not set(problem.seasons) & set(sliced)
        elif problem.code == "season_missing_ratings":
            if problem.sport == "cfb":
                explained = problem.seasons == YEARS
            else:
                explained = not NFL_RATED_METHODS and bool(sliced) and problem.seasons == sliced
        if problem.code not in WAIVABLE_FOR_A_SLICE or not explained:
            unexplained.append(f"{problem.code}: {problem.message}")

    for league in report.leagues:
        expected_games = slices.get(league.sport, ())
        if league.game_seasons != expected_games:
            unexplained.append(
                f"{league.sport} game seasons are {league.game_seasons}, expected {expected_games}"
            )
        methods = league_rated_methods.get(league.sport, ())
        for method, rated in league.rated_seasons.items():
            expected = expected_games if method in methods else ()
            if rated != expected:
                unexplained.append(
                    f"{league.sport} {method} rated seasons are {rated}, expected {expected}"
                )
        expected_players = nfl_seasons if league.sport == "nfl" else ()
        if league.player_stat_seasons != expected_players:
            unexplained.append(
                f"{league.sport} player-stat seasons are {league.player_stat_seasons}, "
                f"expected {expected_players}"
            )

    if unexplained:
        raise AssertionError(
            f"{db_path} is not a current slice of the committed cache {raw_dir} "
            "(`cfb doctor` findings a season slice does not explain):\n  - "
            + "\n  - ".join(unexplained)
        )
    print(
        f"currency check passed for {db_path.name} (rated: {', '.join(rated_methods) or 'none'}; "
        f"nfl slice: {', '.join(map(str, nfl_seasons)) or 'none'}); "
        f"waived slice findings: {sorted({p.code for p in report.problems})}"
    )


def _refuse_live_fetch(*args: object, **kwargs: object) -> NoReturn:
    raise RuntimeError(
        "build_fixture.py never fetches live data: the committed cache under "
        f"{COMMITTED_RAW_DIR} is missing something the NFL ingest asked for"
    )


@contextmanager
def _nflverse_live_fetch_disabled() -> Iterator[None]:
    """Replace the nflverse client's one network call for the block. Every
    `get_*` function looks `_fetch_csv_live` up as a module global at call
    time, which is what `build_regression_fixtures.py` relies on too."""
    original = getattr(nflverse_client, "_fetch_csv_live", None)
    if not callable(original):
        raise RuntimeError(
            "refusing to build: nflverse client._fetch_csv_live is gone (renamed?), so live "
            "fetching cannot be disabled"
        )
    nflverse_client._fetch_csv_live = _refuse_live_fetch
    try:
        yield
    finally:
        nflverse_client._fetch_csv_live = original


def ingest_nfl_slice(db_path: Path) -> None:
    """The NFL slice through the real ingest entry points, in render.yaml's
    order: games, then player stats. Each `main` opens its own connection on
    `db_path`, so no connection of this script's may be open meanwhile."""
    # Both entry points read `config.RAW_DIR` and take no raw-dir argument.
    if config.RAW_DIR.resolve() != COMMITTED_RAW_DIR.resolve():
        raise RuntimeError(
            f"config.RAW_DIR is {config.RAW_DIR}, not the committed cache {COMMITTED_RAW_DIR}; "
            "unset CFB_DATA_DIR and rerun"
        )
    years = ",".join(str(year) for year in NFL_YEARS)
    with _nflverse_live_fetch_disabled():
        for name, entry_point in (
            ("cfb ingest --sport nfl", nflverse_games.main),
            ("cfb ingest-players --sport nfl", nflverse_players.main),
        ):
            status = entry_point(["--years", years, "--db-path", str(db_path)])
            if status != 0:
                raise AssertionError(f"`{name} --years {years}` exited {status}")

    conn = get_conn(db_path)
    try:
        counts = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table} WHERE sport = 'nfl'").fetchone()[0]
            for table in (
                "games",
                "players",
                "player_season_stats",
                "player_game_stats",
                "game_starters",
            )
        }
    finally:
        conn.close()
    print(f"nfl slice {years}: " + " ".join(f"{t}={n}" for t, n in counts.items()))


def build(
    source: Path = SOURCE_FIXTURE,
    output: Path = OUTPUT_FIXTURE,
    raw_dir: Path = COMMITTED_RAW_DIR,
) -> Path:
    if not source.exists():
        raise FileNotFoundError(f"source fixture not found: {source}")

    # Checked before anything is written: a stale source fails here, loudly,
    # rather than as a puzzling assertion in an unrelated test run later.
    check_slice_currency(source, raw_dir, rated_methods=(), nfl_seasons=())

    # Built beside the output and moved into place only once every check
    # below has passed, so a failed build never leaves a half-built fixture.
    partial = output.with_name(f".{output.name}.partial")
    _remove_partial(partial)
    shutil.copy(source, partial)
    try:
        _bake(partial, raw_dir)
        os.replace(partial, output)
    except BaseException:
        # Nothing gitignores the partial (an ~15 MB file next to the committed
        # fixture), so a failed build must not leave it behind for a
        # `git add -A` to pick up.
        _remove_partial(partial)
        raise

    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    print(f"wrote {output}: {output.stat().st_size} bytes; sha256 {digest}")
    return output


def _remove_partial(partial: Path) -> None:
    for leftover in (partial, *(Path(f"{partial}{s}") for s in ("-journal", "-wal", "-shm"))):
        leftover.unlink(missing_ok=True)


def _require_current_schema(partial: Path) -> None:
    """A no-op on a current-schema source. If it would migrate anything, the
    source is stale: fail, don't migrate past it (issue #97). Runs before the
    NFL ingest, whose entry points call `ensure_schema` themselves and would
    otherwise migrate a stale source silently."""
    conn = get_conn(partial)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", StaleDatabaseWarning)
            ensure_schema(conn)
    finally:
        conn.close()


def _bake(partial: Path, raw_dir: Path) -> None:
    """Ingest the NFL slice into `partial`, rate it in place and run every
    build-time check on it. Raises on any failure; `build` removes the
    partial when it does."""
    _require_current_schema(partial)
    ingest_nfl_slice(partial)

    conn: sqlite3.Connection = get_conn(partial)
    try:
        for method in METHODS:
            for year in YEARS:
                count = compute_and_store(conn, year, method)
                if count == 0:
                    raise AssertionError(f"{method} produced no ratings for {year}")
                print(f"computed {count} {method} ratings for {year}")

        # The golden-dataset anchors: the Keener #1 and record for every
        # golden year, checked here so a bad regeneration fails at build time.
        # `test_verdict.py` asserts 2005 Texas by name and
        # `test_verdict_golden_years.py` asserts all seven through HTTP.
        for year, (school, wins, losses, contested) in KEENER_CHAMPIONS.items():
            champion = conn.execute(
                """
                SELECT t.school AS school, r.wins AS wins, r.losses AS losses,
                       r.ties AS ties
                FROM ratings r JOIN teams t ON t.id = r.team_id
                WHERE r.year = ? AND r.method = 'keener' AND r.rank = 1
                """,
                (year,),
            ).fetchone()
            if champion is None or (
                champion["school"],
                champion["wins"],
                champion["losses"],
                champion["ties"],
            ) != (school, wins, losses, 0):
                found = None if champion is None else dict(champion)
                raise AssertionError(
                    f"expected {year} keener champion {school} ({_record(wins, losses, 0)}), "
                    f"got {found}"
                )
            label = " (contested)" if contested else ""
            print(f"confirmed {year} keener champion{label}: {school} ({_record(wins, losses, 0)})")

        # No equivalent hardcoded expectation for Elo. The CFB Elo constants
        # are an uncalibrated first pass (see the Elo credit in
        # `evidence/credits.py`), so pinning a specific #1 here would assert
        # a tuning artifact as if it were a result -- and neutrality: nothing
        # here asserts that Elo and Keener agree or disagree. Report it
        # instead, so a regeneration that changes it is visible in this
        # script's output rather than silent.
        for year in YEARS:
            top = conn.execute(
                """
                SELECT t.school AS school, r.rating AS rating, r.wins AS wins,
                       r.losses AS losses, r.ties AS ties
                FROM ratings r JOIN teams t ON t.id = r.team_id
                WHERE r.year = ? AND r.method = 'elo' AND r.rank = 1
                """,
                (year,),
            ).fetchone()
            if top is None:
                raise AssertionError(f"no elo rank-1 row for {year}")
            record = _record(top["wins"], top["losses"], top["ties"])
            print(f"elo #1 for {year}: {top['school']} ({record}, rating {top['rating']:.1f})")

        # Issue #83: a completed equal-score game is a tie. Reported, not
        # asserted. CFBD's unreported 0-0 small-school games are stored with
        # NULL scores at ingest (#128) and never count as ties, so a nonzero
        # count here means real ties in the data, not a build failure.
        for method in METHODS:
            tied = conn.execute(
                "SELECT COUNT(*) AS n FROM ratings WHERE method = ? AND ties > 0", (method,)
            ).fetchone()["n"]
            print(f"teams with ties > 0 for {method}: {tied}")

        for method in METHODS:
            counts = {
                table: conn.execute(
                    f"SELECT COUNT(*) AS n FROM {table} WHERE method = ?", (method,)
                ).fetchone()["n"]
                for table in (
                    "ratings",
                    "rating_breakdowns",
                    "elo_ledger_steps",
                    "elo_ledger_configs",
                )
            }
            print(f"row counts for {method}: " + " ".join(f"{t}={n}" for t, n in counts.items()))

        check_elo_ledgers(conn)

        with conn:
            for table, column in STAMPED_COLUMNS:
                conn.execute(f"UPDATE {table} SET {column} = ?", (FIXTURE_COMPUTED_AT,))
        conn.execute("VACUUM")
    finally:
        conn.close()

    check_slice_currency(partial, raw_dir, rated_methods=METHODS, nfl_seasons=NFL_YEARS)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate apps/api's verdict fixture from the engine regression fixture."
    )
    parser.add_argument("--source", type=Path, default=SOURCE_FIXTURE)
    parser.add_argument("--output", type=Path, default=OUTPUT_FIXTURE)
    parser.add_argument("--raw-dir", type=Path, default=COMMITTED_RAW_DIR)
    args = parser.parse_args(argv)
    build(args.source, args.output, args.raw_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
