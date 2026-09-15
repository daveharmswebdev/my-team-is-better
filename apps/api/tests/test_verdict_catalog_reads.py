"""Issue #245: a verdict request reads the team catalog once.

Before #245 each verdict route read the sport's catalog twice on a cold
cache: `resolve_user_team` ran `list_team_records(conn, sport)` to
canonicalise `user_team`, and `api.persona.service._cached_narration` ran
`list_all_team_names(conn, sport)` for the grounding universe. Both are the
same universe (every `teams.school` for the sport), so the route now reads
the catalog once, hands the records to `resolve_user_team`, and passes the
derived names into the persona layer through an explicit `known_team_names`
argument. The persona layer no longer holds a connection at all.

What is measured: the statements the request's own `sqlite3.Connection`
runs, recorded with `set_trace_callback`. A "catalog read" is a scan of the
`teams` table -- the `FROM teams` of `list_all_team_names` and
`list_team_records` -- as opposed to the evidence layer's per-row
`SELECT school FROM teams WHERE id = ?` lookups and `_resolve_champion_name`'s
`JOIN teams`, which are not catalog reads and are not counted. Measured at
the #245 base: 2 catalog reads per route with a `user_team`, 1 without
(`resolve_user_team` returned before querying). The bar is exactly 1 in
both cases: never 2, and never 0 without `user_team` either, because the
grounding universe still needs the catalog.

The equivalence the plumbing rests on is asserted directly: the names
derived from `list_team_records(conn, sport)` equal
`list_all_team_names(conn, sport)` as a set, for cfb on the committed
verdict fixture and for nfl on the sport fixture. If that ever diverged,
passing the derived list to grounding would narrow (or widen) the universe
silently, so the test is the tripwire.
"""

from __future__ import annotations

import inspect
import re
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from cfb_strength.db.connection import get_conn
from cfb_strength.evidence.proof import build_comparison, build_team_case
from fastapi.testclient import TestClient
from fixtures.sport_fixture import make_sport_fixture_db

from api.deps import get_db_conn, get_narration_cache, get_narrator
from api.main import app
from api.models import ComparisonResultOut, TeamCaseOut
from api.persona import service
from api.persona.cache import InMemoryNarrationCache
from api.persona.narrate import NarrationResult
from api.persona.service import narrate_comparison, narrate_team_case
from api.repositories.teams import list_all_team_names, list_team_records
from api.verdict import catalog_names

FIXTURE_DB = Path(__file__).parent / "fixtures" / "cfb_verdict_fixture.sqlite3"

# A scan of the `teams` table. The evidence layer's per-row lookups
# (`... FROM teams WHERE id = 1`) are excluded by the second pattern.
_TEAMS_SCAN = re.compile(r"\bFROM\s+teams\b", re.IGNORECASE)
_ROW_LOOKUP = re.compile(r"\bWHERE\s+id\s*=", re.IGNORECASE)


def catalog_reads(statements: list[str]) -> list[str]:
    """The statements in `statements` that read the team catalog."""
    return [s for s in statements if _TEAMS_SCAN.search(s) and not _ROW_LOOKUP.search(s)]


class _RecordingNarrator:
    """Grounded against any fact block (no numbers, no team names); records
    how many times it was asked, so a test can prove the request really went
    through the cache-miss path where the grounding universe is needed."""

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, *, system: str, messages: list[dict[str, str]]) -> str:
        self.calls += 1
        return "Solid case, no notes."


class _Traced:
    """A TestClient whose every request's connection appends the SQL it runs
    to `statements` (expanded, so bound parameters are inlined)."""

    def __init__(self, client: TestClient, statements: list[str], narrator: _RecordingNarrator):
        self.client = client
        self.statements = statements
        self.narrator = narrator


def _traced_client(db_path: Path) -> Iterator[_Traced]:
    statements: list[str] = []
    narrator = _RecordingNarrator()

    def _override() -> Iterator[sqlite3.Connection]:
        conn = get_conn(db_path, read_only=True)
        conn.set_trace_callback(statements.append)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db_conn] = _override
    app.dependency_overrides[get_narration_cache] = lambda: InMemoryNarrationCache()
    app.dependency_overrides[get_narrator] = lambda: narrator
    try:
        yield _Traced(TestClient(app), statements, narrator)
    finally:
        app.dependency_overrides.pop(get_db_conn, None)
        app.dependency_overrides.pop(get_narration_cache, None)
        app.dependency_overrides.pop(get_narrator, None)


@pytest.fixture
def traced(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[_Traced]:
    """Traced client against the committed CFB fixture, or against a fresh
    sport fixture when the test is parametrized with `db="sport"`."""
    which = getattr(request, "param", "cfb")
    db_path = FIXTURE_DB if which == "cfb" else make_sport_fixture_db(tmp_path)
    yield from _traced_client(db_path)


# 2005 against the committed CFB fixture: Texas is #1, USC #2.
ROUTES: list[tuple[str, dict[str, Any]]] = [
    ("/api/verdict/champion", {"year": 2005}),
    ("/api/verdict/team-case", {"year": 2005, "team": "USC"}),
    ("/api/verdict/compare", {"year": 2005, "team_a": "Texas", "team_b": "USC"}),
]
ROUTE_IDS = ["champion", "team-case", "compare"]


# ---------------------------------------------------------------------------
# (a) with a user_team, one catalog read per request on a cold cache
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("path", "body"), ROUTES, ids=ROUTE_IDS)
def test_a_request_with_a_user_team_reads_the_catalog_once(
    traced: _Traced, path: str, body: dict[str, Any]
) -> None:
    response = traced.client.post(path, json={**body, "user_team": "Texas"})

    assert response.status_code == 200, response.text
    assert traced.narrator.calls == 1, "cold cache: the request must have narrated"
    reads = catalog_reads(traced.statements)
    assert len(reads) == 1, f"{len(reads)} catalog reads:\n" + "\n---\n".join(reads)


# ---------------------------------------------------------------------------
# (b) without a user_team the grounding universe still needs exactly one
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("path", "body"), ROUTES, ids=ROUTE_IDS)
def test_a_request_without_a_user_team_still_reads_the_catalog_exactly_once(
    traced: _Traced, path: str, body: dict[str, Any]
) -> None:
    response = traced.client.post(path, json=body)

    assert response.status_code == 200, response.text
    assert traced.narrator.calls == 1, "cold cache: the request must have narrated"
    reads = catalog_reads(traced.statements)
    assert len(reads) == 1, f"{len(reads)} catalog reads:\n" + "\n---\n".join(reads)


def test_the_traced_statements_include_the_evidence_queries(traced: _Traced) -> None:
    """The trace is real: excluding row lookups from `catalog_reads` must not
    be excluding everything. A team-case request reaches the evidence layer,
    whose per-opponent `teams` lookups appear in the trace."""
    traced.client.post("/api/verdict/team-case", json={"year": 2005, "team": "USC"})

    scans = [s for s in traced.statements if _TEAMS_SCAN.search(s)]
    assert len(scans) > len(catalog_reads(traced.statements))


# ---------------------------------------------------------------------------
# (c) the derived names ARE the grounding universe, on both sports
# ---------------------------------------------------------------------------


def _sport_db(tmp_path: Path) -> Path:
    return make_sport_fixture_db(tmp_path)


@pytest.mark.parametrize(
    ("db", "sport"),
    [("cfb", "cfb"), ("sport", "nfl"), ("sport", "cfb")],
    ids=["verdict-fixture-cfb", "sport-fixture-nfl", "sport-fixture-cfb"],
)
def test_names_derived_from_the_records_equal_list_all_team_names(
    tmp_path: Path, db: str, sport: str
) -> None:
    db_path = FIXTURE_DB if db == "cfb" else _sport_db(tmp_path)
    conn = get_conn(db_path, read_only=True)
    try:
        derived = catalog_names(list_team_records(conn, sport))
        universe = list_all_team_names(conn, sport)
    finally:
        conn.close()

    assert derived, "an empty catalog would make the equality vacuous"
    assert set(derived) == set(universe)
    assert len(derived) == len(set(derived)), "the derived list carries no duplicate names"


# ---------------------------------------------------------------------------
# (d) an explicit known_team_names reaches narrate() unchanged
# ---------------------------------------------------------------------------


class _NarrateRecorder:
    def __init__(self) -> None:
        self.kwargs: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> NarrationResult:
        self.kwargs.append(kwargs)
        return NarrationResult(text="Solid case, no notes.", is_fallback=False)


def test_narrate_team_case_hands_narrate_exactly_the_given_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = get_conn(FIXTURE_DB, read_only=True)
    try:
        case = TeamCaseOut.from_dataclass(
            build_team_case(conn, 2005, "Texas", method="keener", sport="cfb")
        )
    finally:
        conn.close()
    recorder = _NarrateRecorder()
    monkeypatch.setattr(service, "narrate", recorder)
    names = ["Only", "These", "Names"]

    narrate_team_case(
        case,
        user_team=None,
        question_type="team_case",
        method="keener",
        sport="cfb",
        known_team_names=names,
        cache=InMemoryNarrationCache(),
        narrator=_RecordingNarrator(),
    )

    assert [call["known_team_names"] for call in recorder.kwargs] == [names]


def test_narrate_comparison_hands_narrate_exactly_the_given_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = get_conn(FIXTURE_DB, read_only=True)
    try:
        comparison = ComparisonResultOut.from_dataclass(
            build_comparison(conn, 2005, "Texas", "USC", method="keener", sport="cfb")
        )
    finally:
        conn.close()
    recorder = _NarrateRecorder()
    monkeypatch.setattr(service, "narrate", recorder)
    names = ["Only", "These", "Names"]

    narrate_comparison(
        comparison,
        user_team=None,
        method="keener",
        sport="cfb",
        known_team_names=names,
        cache=InMemoryNarrationCache(),
        narrator=_RecordingNarrator(),
    )

    assert [call["known_team_names"] for call in recorder.kwargs] == [names]


# ---------------------------------------------------------------------------
# (e) the persona layer holds no connection and names no catalog query
# ---------------------------------------------------------------------------


def test_the_persona_service_has_no_connection_to_query_the_catalog_with() -> None:
    """The structural half of the guarantee: with no `conn` parameter and no
    catalog query in its namespace, `api.persona.service` cannot issue the
    second read again without changing its signature -- and a route passing
    the names it already derived is the only way the universe gets in."""
    for query in ("list_all_team_names", "list_team_records"):
        assert not hasattr(service, query), f"api.persona.service still names {query}"
    for fn in (narrate_team_case, narrate_comparison):
        parameters = inspect.signature(fn).parameters
        assert "conn" not in parameters, f"{fn.__name__} still takes a connection"
        assert "known_team_names" in parameters
