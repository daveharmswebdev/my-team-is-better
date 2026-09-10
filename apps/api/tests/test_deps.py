"""Failing-first test for `api.deps.list_all_team_names` (GitHub issue #13).

Promoted out of `api.persona.service._all_team_names` (issue #4's grounding-
check helper) so both the persona grounding check and the new `/api/teams`
route call the same `SELECT DISTINCT school FROM teams` query -- see
`test_catalog.py` for the route-level coverage, and
`test_verdict_persona.py`'s existing grounding-mismatch tests (unchanged)
for proof the persona side still works correctly post-promotion.
"""

from __future__ import annotations

from pathlib import Path

from cfb_strength.db.connection import get_conn

from api.deps import list_all_team_names

FIXTURE_DB = Path(__file__).parent / "fixtures" / "cfb_verdict_fixture.sqlite3"


def test_list_all_team_names_returns_real_teams_from_the_db() -> None:
    conn = get_conn(FIXTURE_DB, read_only=True)
    try:
        names = list_all_team_names(conn)
    finally:
        conn.close()

    assert "Texas" in names
    assert "USC" in names
    assert "Alabama" in names
