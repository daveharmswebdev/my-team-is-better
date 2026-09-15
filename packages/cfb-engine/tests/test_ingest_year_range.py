"""Coverage for issue #9: the ingest range extends from 2000-2023 to the
product's 1998-2025 target (PRD §5.2, Architecture Brief §3.1).

Runs the real `main()` CLI entry point against the committed `data/raw/`
cache (1998/1999/2024/2025 were freshly fetched live from CFBD and committed
as part of closing this issue -- see `data/raw/{1998,1999,2024,2025}_*.json`)
into a fresh temp db, so this is a real ingest-and-check, not a mock of the
completeness heuristic.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from cfb_strength.db.connection import get_conn
from cfb_strength.ingest.ingest_season import MAX_YEAR, MIN_YEAR, main


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "range_test.sqlite3"


def test_min_and_max_year_match_product_target() -> None:
    assert MIN_YEAR == 1998
    assert MAX_YEAR == 2025


def test_new_boundary_years_ingest_with_ok_status(db_path: Path) -> None:
    exit_code = main(["--years", "1998,1999,2024,2025", "--db-path", str(db_path)])
    assert exit_code == 0

    conn: sqlite3.Connection = get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT year, season_type, status FROM ingestion_log ORDER BY year, season_type"
        ).fetchall()
    finally:
        conn.close()

    statuses = {(r["year"], r["season_type"]): r["status"] for r in rows}
    for year in (1998, 1999, 2024, 2025):
        for season_type in ("regular", "postseason"):
            assert statuses[(year, season_type)] == "ok", (
                f"{year} {season_type} was not status=ok: {statuses}"
            )


def test_years_outside_the_new_range_are_still_skipped(
    db_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(["--years", "1997,1998,2025,2026", "--db-path", str(db_path)])
    assert exit_code == 0

    stderr = capsys.readouterr().err
    assert "1997" in stderr
    assert "2026" in stderr

    conn: sqlite3.Connection = get_conn(db_path)
    try:
        years = {
            r["year"] for r in conn.execute("SELECT DISTINCT year FROM ingestion_log").fetchall()
        }
    finally:
        conn.close()
    assert years == {1998, 2025}
