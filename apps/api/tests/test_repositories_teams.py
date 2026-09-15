"""`api.repositories.teams` (issue #209): the two team-name queries, moved
out of `api.deps` so the persona layer stops importing the FastAPI wiring.

`list_all_team_names` (issue #13) was promoted out of
`api.persona.service._all_team_names` (issue #4's grounding-check helper) so
both the persona grounding check and the `/api/teams` route call the same
`SELECT DISTINCT school FROM teams` query -- see `test_catalog.py` and
`test_catalog_teams_year.py` for the route-level coverage of its sibling
`list_team_records`, and `test_verdict_persona.py`'s grounding-mismatch tests
(unchanged) for proof the persona side still works post-move. The behaviour
tests below are the ones `test_deps.py` held while the query lived there.

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
from api.repositories.teams import TeamRecord, list_all_team_names, list_team_records

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


def test_list_all_team_names_default_sport_is_cfb() -> None:
    """No pre-#59 call site ever passed `sport` -- the default must keep
    producing the same result as an explicit sport='cfb' call."""
    conn = get_conn(FIXTURE_DB, read_only=True)
    try:
        assert list_all_team_names(conn) == list_all_team_names(conn, sport="cfb")
    finally:
        conn.close()


def test_list_all_team_names_scopes_by_sport(tmp_path: Path) -> None:
    """Issue #59: a CFB/NFL name collision ("Wildcats" in both sports, same
    year/method) must not cross-contaminate either sport's "known team
    names" universe -- the grounding check's precondition."""
    from fixtures.sport_fixture import make_sport_fixture_db

    db_path = make_sport_fixture_db(tmp_path)
    conn = get_conn(db_path, read_only=True)
    try:
        cfb_names = list_all_team_names(conn, sport="cfb")
        nfl_names = list_all_team_names(conn, sport="nfl")
    finally:
        conn.close()

    assert "Alpha State" in cfb_names
    assert "Delta Squad" not in cfb_names
    assert "Delta Squad" in nfl_names
    assert "Alpha State" not in nfl_names
    assert cfb_names.count("Wildcats") == 1
    assert nfl_names.count("Wildcats") == 1


def test_list_team_records_without_year_matches_list_all_team_names() -> None:
    """The move must not change either query: with no `year`,
    `list_team_records` still yields exactly the names `list_all_team_names`
    does, in the same order (the pre-#78 `DISTINCT school` list)."""
    conn = get_conn(FIXTURE_DB, read_only=True)
    try:
        records = list_team_records(conn)
        names = list_all_team_names(conn)
    finally:
        conn.close()

    assert [record.name for record in records] == names
    assert all(isinstance(record, TeamRecord) for record in records)


def test_deps_keeps_only_the_dependency_injection_callables() -> None:
    """`api.deps` is the FastAPI wiring and nothing else after #209: the
    queries left, and no re-export brings them back for old import paths."""
    for moved in ("list_all_team_names", "list_team_records", "TeamRecord", "_decode_aliases"):
        assert not hasattr(api.deps, moved), f"api.deps still exposes {moved}"
    assert callable(api.deps.get_db_conn)
    assert callable(api.deps.get_narration_cache)
    assert callable(api.deps.get_narrator)


def test_persona_service_does_not_bind_deps() -> None:
    """Belt to the contract's braces: the service module's namespace holds
    the repository's query, and nothing defined in `api.deps`."""
    import api.persona.service as service

    namespace = vars(service)
    assert namespace["list_all_team_names"] is list_all_team_names
    bound_from_deps = [
        name
        for name, value in namespace.items()
        if getattr(value, "__module__", None) == "api.deps"
    ]
    assert bound_from_deps == []
