"""One-off generator for `cfb_verdict_fixture.sqlite3`.

NOT part of the pytest suite (doesn't match `test_*.py`, not collected) and
NOT imported by anything under `apps/api/src` or `apps/api/tests/test_*.py`.
It exists purely so a human/agent can regenerate the committed fixture by
running it directly, from the repo root:

    uv run --project packages/cfb-engine python apps/api/tests/fixtures/build_fixture.py

`--source`, `--output` and `--raw-dir` override the three paths below (for a
scratch build or a sabotage check); the defaults are the committed files.

This is the *only* place in `apps/api/` that imports `cfb_strength.ratings`
(`compute_and_store`) or `cfb_strength.ingest` (`currency.check_currency`,
the `cfb doctor` check) -- everything else in this app (route code and the
actual pytest suite) only ever opens the pre-baked output db this script
produces, via `get_conn`, which keeps the "no ratings/ingest import in
app/test runtime" rule intact for every file pytest actually collects.

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

- `season_behind_cache`: only for seasons the fixture omits. NFL counts too,
  since this fixture carries no NFL at all.
- `season_missing_ratings`: on the source, every method for exactly the seven
  seasons (the source stores no ratings); on the output, only the methods
  deliberately not baked (`elo_career`, below).
- `league_has_no_games`: only for NFL.

Anything else fails the build: `schema_not_current`, `no_cfb_mascots` (a
source built without the #77 alias enrichment -- the old pre-#110 fixture had
none), `raw_cache_*` and `cache_past_max_year`.

What that bracket does NOT check: it compares (season, season_type) *pairs*
against the cache, never individual games. A source missing some games inside
a golden season -- even a title game -- still has that season's regular and
postseason pairs, so it passes both currency checks. The only build-time
guard against that is the Keener golden check below (the #1 school and its
record for each golden year), and it catches a missing game only when the
game moves a #1 or that #1's record. A missing game that changes neither
passes the whole build. Completeness of the games inside a season is the
engine fixture generator's job (`build_regression_fixtures.py` ingests every
cached game), not something this script verifies.

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

Determinism: `compute_and_store` stamps `computed_at` with the wall clock,
the only run-dependent value it writes. The build overwrites it with
`FIXTURE_COMPUTED_AT` and VACUUMs, so rerunning on an unchanged source and
engine produces a byte-identical file (with the same SQLite build). Nothing
in `apps/api` or `apps/web` reads `computed_at`.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sqlite3
import warnings
from pathlib import Path

from cfb_strength.contracts import Method
from cfb_strength.db.connection import StaleDatabaseWarning, ensure_schema, get_conn
from cfb_strength.ingest.currency import check_currency
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


def _record(wins: int, losses: int, ties: int) -> str:
    """W-L-T when ties > 0, W-L otherwise -- the engine's record rule (#83)."""
    return f"{wins}-{losses}-{ties}" if ties else f"{wins}-{losses}"


def check_slice_currency(
    db_path: Path, raw_dir: Path, *, rated_methods: tuple[Method, ...]
) -> None:
    """Fail unless `db_path`'s only `cfb doctor` findings are the ones a
    CFB-only slice of `YEARS`, rated for exactly `rated_methods`, explains.
    See the module docstring for the rules."""
    report = check_currency(db_path, raw_dir)
    years = set(YEARS)
    unexplained: list[str] = []

    for problem in report.problems:
        explained = False
        if problem.code == "league_has_no_games":
            explained = problem.sport != "cfb"
        elif problem.code == "season_behind_cache":
            explained = problem.sport != "cfb" or not set(problem.seasons) & years
        elif problem.code == "season_missing_ratings":
            explained = problem.sport == "cfb" and problem.seasons == YEARS
        if problem.code not in WAIVABLE_FOR_A_SLICE or not explained:
            unexplained.append(f"{problem.code}: {problem.message}")

    for league in report.leagues:
        if league.sport != "cfb":
            if league.game_seasons:
                unexplained.append(f"{league.sport} has games {league.game_seasons}")
            continue
        if league.game_seasons != YEARS:
            unexplained.append(f"cfb game seasons are {league.game_seasons}, expected {YEARS}")
        for method, rated in league.rated_seasons.items():
            expected = YEARS if method in rated_methods else ()
            if rated != expected:
                unexplained.append(f"cfb {method} rated seasons are {rated}, expected {expected}")

    if unexplained:
        raise AssertionError(
            f"{db_path} is not a current slice of the committed cache {raw_dir} "
            "(`cfb doctor` findings a season slice does not explain):\n  - "
            + "\n  - ".join(unexplained)
        )
    print(
        f"currency check passed for {db_path.name} (rated: {', '.join(rated_methods) or 'none'}); "
        f"waived slice findings: {sorted({p.code for p in report.problems})}"
    )


def build(
    source: Path = SOURCE_FIXTURE,
    output: Path = OUTPUT_FIXTURE,
    raw_dir: Path = COMMITTED_RAW_DIR,
) -> Path:
    if not source.exists():
        raise FileNotFoundError(f"source fixture not found: {source}")

    # Checked before anything is written: a stale source fails here, loudly,
    # rather than as a puzzling assertion in an unrelated test run later.
    check_slice_currency(source, raw_dir, rated_methods=())

    # Built beside the output and moved into place only once every check
    # below has passed, so a failed build never leaves a half-built fixture.
    partial = output.with_name(f".{output.name}.partial")
    _remove_partial(partial)
    shutil.copy(source, partial)
    try:
        _bake(partial, raw_dir)
        os.replace(partial, output)
    except BaseException:
        # Nothing gitignores the partial (an ~11 MB file next to the committed
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


def _bake(partial: Path, raw_dir: Path) -> None:
    """Rate `partial` in place and run every build-time check on it. Raises
    on any failure; `build` removes the partial when it does."""
    conn: sqlite3.Connection = get_conn(partial)
    try:
        # A no-op on a current-schema source. If it would migrate anything,
        # the source is stale: fail, don't migrate past it (issue #97).
        with warnings.catch_warnings():
            warnings.simplefilter("error", StaleDatabaseWarning)
            ensure_schema(conn)

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
            ratings_count = conn.execute(
                "SELECT COUNT(*) AS n FROM ratings WHERE method = ?", (method,)
            ).fetchone()["n"]
            breakdown_count = conn.execute(
                "SELECT COUNT(*) AS n FROM rating_breakdowns WHERE method = ?",
                (method,),
            ).fetchone()["n"]
            print(
                f"row counts for {method}: ratings={ratings_count} "
                f"rating_breakdowns={breakdown_count}"
            )

        with conn:
            conn.execute("UPDATE ratings SET computed_at = ?", (FIXTURE_COMPUTED_AT,))
            conn.execute("UPDATE rating_breakdowns SET computed_at = ?", (FIXTURE_COMPUTED_AT,))
        conn.execute("VACUUM")
    finally:
        conn.close()

    check_slice_currency(partial, raw_dir, rated_methods=METHODS)


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
