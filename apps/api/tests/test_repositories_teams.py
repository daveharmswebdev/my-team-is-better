"""`api.repositories.teams` (issue #209): the team catalog query, moved out
of `api.deps` so the persona layer stops importing the FastAPI wiring.

`list_team_records` (issue #78) is the one team query left: the `/api/teams`
route reads it, and every verdict route reads it once (issue #245) and hands
the records to the typed-claim validator as its team universe (issue #291).
Its year-free, names-only sibling (issue #13), the old lexical grounding
check's "known team names" universe, lost its last production caller with
#291 and was deleted by issue #336, along with the tests that pinned its own
behaviour. Sport scoping of the unscoped catalog is covered at
the route by `test_catalog_sport.py`, and the year filter by `test_catalog.py`
and `test_catalog_teams_year.py`.

The last two tests pin the move itself: `api.deps` keeps only the three
dependency-injection callables and re-exports nothing, so a consumer cannot
quietly go back to importing a query from the DI module. The contract that
keeps `api.persona` from importing `api.deps` at all is the `layers` contract
in `.importlinter` (checked by `uv run lint-imports`, not by pytest).
"""

from __future__ import annotations

from pathlib import Path

from cfb_strength.db.connection import get_conn

import api.deps
from api.repositories.teams import TeamRecord, list_team_records

FIXTURE_DB = Path(__file__).parent / "fixtures" / "cfb_verdict_fixture.sqlite3"


def test_list_team_records_without_year_matches_the_distinct_school_list() -> None:
    """With no `year`, `list_team_records` yields exactly the pre-#78
    `SELECT DISTINCT school FROM teams WHERE sport = ?` names, in the same
    order. The oracle is that query, inline, so it can't share a bug with the
    function under test."""
    conn = get_conn(FIXTURE_DB, read_only=True)
    try:
        records = list_team_records(conn)
        rows = conn.execute("SELECT DISTINCT school FROM teams WHERE sport = ?", ("cfb",))
        names = [str(row["school"]) for row in rows.fetchall()]
    finally:
        conn.close()

    assert names, "the oracle query found no teams; the comparison would be vacuous"

    assert [record.name for record in records] == names
    assert all(isinstance(record, TeamRecord) for record in records)


def test_deps_keeps_only_the_dependency_injection_callables() -> None:
    """`api.deps` is the FastAPI wiring and nothing else after #209: the
    queries left, and no re-export brings them back for old import paths."""
    for moved in ("list_team_records", "TeamRecord", "_decode_aliases"):
        assert not hasattr(api.deps, moved), f"api.deps still exposes {moved}"
    assert callable(api.deps.get_db_conn)
    assert callable(api.deps.get_narration_cache)
    assert callable(api.deps.get_narrator)


def test_persona_service_does_not_bind_deps() -> None:
    """Belt to the contract's braces: nothing defined in `api.deps` is bound
    in the service module's namespace. (Since issue #245 the route reads
    the catalog itself and passes it in, so the service binds no query at
    all -- see `test_verdict_catalog_reads.py`.)"""
    import api.persona.service as service

    namespace = vars(service)
    assert "list_team_records" not in namespace
    bound_from_deps = [
        name
        for name, value in namespace.items()
        if getattr(value, "__module__", None) == "api.deps"
    ]
    assert bound_from_deps == []
