"""One-off generator for `cfb_verdict_fixture.sqlite3`.

NOT part of the pytest suite (doesn't match `test_*.py`, not collected) and
NOT imported by anything under `apps/api/src` or `apps/api/tests/test_*.py`.
It exists purely so a human/agent can regenerate the committed fixture by
running it directly:

    uv run --project packages/cfb-engine python apps/api/tests/fixtures/build_fixture.py

This is the *only* place in `apps/api/` that imports `cfb_strength.ratings`
(`compute_and_store`) -- everything else in this app (route code and the
actual pytest suite) only ever opens the pre-baked output db this script
produces, via `get_conn`, which keeps the "no ratings/ingest import in
app/test runtime" rule intact for every file pytest actually collects.

That exception is sanctioned, and it is *structural* rather than suppressed:
`apps/api/.importlinter` (issue #54) forbids `api -> cfb_strength.ratings`,
and this file is not part of the `api` package, so it is not in that graph
and needs no ignore rule. Verified both ways -- the contract stays KEPT with
this import here, and copying this same file into `src/api/` reports
`api._sabotage_fixture -> cfb_strength.ratings.compute_ratings (l.47)`
BROKEN. So the rule to respect is: a build/generator script that reaches for
`ratings` or `ingest` belongs here, never under `src/api/`. Do not "fix" a
future violation by adding an ignore directive to `.importlinter`.

Provenance: starts from `packages/cfb-engine/tests/fixtures/cfb_regression.sqlite3`
(committed, real 2001/2005/2013 CFBD game data, no precomputed ratings), then
bakes in real ratings for those same three years so `apps/api`'s test suite
has real, non-mocked evidentiary data to hit through the HTTP layer --
including the 2005 Texas-over-USC golden-dataset case.

Two methods are baked, `keener` and `elo`, for each of the three years. Elo
was added when `method` became a validated Literal: `elo` is a shipped,
credited method, and with keener-only rows no test could tell "Elo works
end-to-end through the API" from "Elo is silently returning nothing". The
two methods live side by side in the same `ratings`/`rating_breakdowns`
tables, scoped by the `method` column, so every pre-existing keener
assertion is untouched by the addition.

`elo_career` is deliberately NOT baked. Its offseason mean reversion fires
once per *elapsed* year, and these three seasons are non-contiguous on
purpose (2001, 2005, 2013), so it would apply 4 and then 8 reversions for
gaps that are an artifact of which seasons this fixture happens to carry,
not of real football calendars. The resulting ratings would model nothing
and would be actively misleading to assert against. Tracked as issue #98;
`method="elo_career"` is still accepted by the API (it is a registered
method) and correctly returns nothing here.
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from cfb_strength.db.connection import ensure_schema, get_conn
from cfb_strength.ratings.compute_ratings import compute_and_store

THIS_DIR = Path(__file__).parent
SOURCE_FIXTURE = (
    THIS_DIR.parent.parent.parent.parent
    / "packages"
    / "cfb-engine"
    / "tests"
    / "fixtures"
    / "cfb_regression.sqlite3"
)
OUTPUT_FIXTURE = THIS_DIR / "cfb_verdict_fixture.sqlite3"

YEARS = (2001, 2005, 2013)
# See the module docstring for why `elo_career` is excluded.
METHODS = ("keener", "elo")


def _record(wins: int, losses: int, ties: int) -> str:
    """W-L-T when ties > 0, W-L otherwise -- the engine's record rule (#83)."""
    return f"{wins}-{losses}-{ties}" if ties else f"{wins}-{losses}"


def build() -> None:
    if not SOURCE_FIXTURE.exists():
        raise FileNotFoundError(f"source fixture not found: {SOURCE_FIXTURE}")

    if OUTPUT_FIXTURE.exists():
        OUTPUT_FIXTURE.unlink()
    shutil.copy(SOURCE_FIXTURE, OUTPUT_FIXTURE)

    conn: sqlite3.Connection = get_conn(OUTPUT_FIXTURE)
    try:
        # SOURCE_FIXTURE predates #51's `sport` column (schema.sql's
        # CREATE TABLE IF NOT EXISTS is a no-op against it, and get_conn
        # alone applies no migration) -- bring the copy up to the current
        # schema in place before writing ratings, or compute_and_store's
        # sport-aware INSERTs below fail with "no such column: sport".
        ensure_schema(conn)
        for method in METHODS:
            for year in YEARS:
                count = compute_and_store(conn, year, method)
                if count == 0:
                    raise AssertionError(f"{method} produced no ratings for {year}")
                print(f"computed {count} {method} ratings for {year}")

        # The golden-dataset anchor: 2005 Texas is an undisputed champion, and
        # `test_verdict.py` asserts on it by name. Checked here so a bad
        # regeneration fails loudly at build time rather than as a puzzling
        # assertion error in an unrelated test run later.
        champion = conn.execute(
            """
            SELECT t.school AS school, r.wins AS wins, r.losses AS losses,
                   r.ties AS ties
            FROM ratings r JOIN teams t ON t.id = r.team_id
            WHERE r.year = 2005 AND r.method = 'keener' AND r.rank = 1
            """
        ).fetchone()
        if champion is None or champion["school"] != "Texas":
            raise AssertionError(f"expected 2005 keener champion to be Texas, got {champion}")
        record = _record(champion["wins"], champion["losses"], champion["ties"])
        print(f"confirmed 2005 champion: {champion['school']} ({record})")

        # No equivalent hardcoded expectation for Elo. The CFB Elo constants
        # are an uncalibrated first pass (see the Elo credit in
        # `evidence/credits.py`), so pinning a specific #1 here would assert
        # a tuning artifact as if it were a result. Report it instead, so a
        # regeneration that changes it is visible in the diff of this
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
        # asserted -- this CFB data may contain 0-0 rows for unreported
        # small-school games, which count as ties until ingest drops them
        # (#128), so a nonzero count here is expected, not a build failure.
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
    finally:
        conn.close()

    print(f"wrote {OUTPUT_FIXTURE}")


if __name__ == "__main__":
    build()
