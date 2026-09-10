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

Provenance: starts from `packages/cfb-engine/tests/fixtures/cfb_regression.sqlite3`
(committed, real 2001/2005/2013 CFBD game data, no precomputed ratings), then
bakes in real keener ratings for those same three years so `apps/api`'s test
suite has real, non-mocked evidentiary data to hit through the HTTP layer --
including the 2005 Texas-over-USC golden-dataset case.
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from cfb_strength.db.connection import get_conn
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


def build() -> None:
    if not SOURCE_FIXTURE.exists():
        raise FileNotFoundError(f"source fixture not found: {SOURCE_FIXTURE}")

    if OUTPUT_FIXTURE.exists():
        OUTPUT_FIXTURE.unlink()
    shutil.copy(SOURCE_FIXTURE, OUTPUT_FIXTURE)

    conn: sqlite3.Connection = get_conn(OUTPUT_FIXTURE)
    try:
        for year in YEARS:
            count = compute_and_store(conn, year, "keener")
            print(f"computed {count} keener ratings for {year}")

        champion = conn.execute(
            """
            SELECT t.school AS school, r.wins AS wins, r.losses AS losses
            FROM ratings r JOIN teams t ON t.id = r.team_id
            WHERE r.year = 2005 AND r.method = 'keener' AND r.rank = 1
            """
        ).fetchone()
        if champion is None or champion["school"] != "Texas":
            raise AssertionError(f"expected 2005 keener champion to be Texas, got {champion}")
        record = f"{champion['wins']}-{champion['losses']}"
        print(f"confirmed 2005 champion: {champion['school']} ({record})")
    finally:
        conn.close()

    print(f"wrote {OUTPUT_FIXTURE}")


if __name__ == "__main__":
    build()
