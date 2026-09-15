"""Failing-first tests for issue #172: a rated year with no rank-1 row
answers a distinct, mapped `missing_champion` 500 from /champion, never a
422 `ambiguous_team` for a query the user never typed.

Before this change `_resolve_champion_name` returned `None` when the rank-1
query found nothing, and `champion()` fell through to
`build_team_case(conn, year, "")`, on the theory that a missing champion
only ever meant "no ratings at all for that year" (which the engine's
`_require_year` maps to `unknown_year`). That theory breaks the moment a
year has ratings rows but no `rank = 1` among them: the empty query then
reaches `resolve_team`, which matches every rated team and raises
`AmbiguousTeamError("", [every team])`, so the client saw a 422 "did you
mean:" listing the whole season under a query of `""`.

The engine has no champion concept (the rank-1 query is this app's own,
replicated from the MCP surface by design, see `api.verdict`), so the
error is API-local: `api.errors.MissingChampionError`, mapped to 500 with
body `{"detail": {"error": "missing_champion", "year", "method", "sport"}}`
and declared on the champion route only. It is a data-integrity fault in the
db, not a client mistake, hence 500; the web already renders a generic
server-error line for that status and needs no change.

The reproduction is the one from the issue: a copy of the committed fixture
db with `DELETE FROM ratings WHERE year = 2004 AND method = 'keener' AND
rank = 1 AND sport = 'cfb'`, built in `tmp_path` and wired through the same
`get_db_conn` override the shared `client` fixture uses. Only that one row
goes: elo's 2004 rank-1 row and every other keener row stay, so the same db
proves the blast radius (b, c below) as well as the fault (a).
"""

from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from cfb_strength.db.connection import get_conn
from conftest import FIXTURE_DB, _StubNarrator
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

CHAMPION = "/api/verdict/champion"
TEAM_CASE = "/api/verdict/team-case"
COMPARE = "/api/verdict/compare"

MISSING_CHAMPION_RESPONSE = "MissingChampionErrorResponse"


def _delete_rank_one(db: Path, *, year: int, method: str, sport: str) -> int:
    conn = sqlite3.connect(db)
    try:
        cursor = conn.execute(
            "DELETE FROM ratings WHERE year = ? AND method = ? AND rank = 1 AND sport = ?",
            (year, method, sport),
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


@pytest.fixture
def headless_2004_db(tmp_path: Path) -> Path:
    """A copy of the committed fixture with 2004 keener's rank-1 row deleted
    and nothing else touched."""
    db = tmp_path / "headless_2004.sqlite3"
    shutil.copy(FIXTURE_DB, db)
    deleted = _delete_rank_one(db, year=2004, method="keener", sport="cfb")
    # Premise: the committed fixture really has exactly one such row, so the
    # delete removes the champion and only the champion. Zero would mean the
    # tests below pass for the wrong reason; two would mean a tie the app
    # never breaks.
    assert deleted == 1, f"expected to delete one rank-1 row, deleted {deleted}"
    return db


@pytest.fixture
def headless_client(headless_2004_db: Path) -> Iterator[TestClient]:
    """Same wiring as conftest's `client`, against the mutated copy."""
    from api.deps import get_db_conn, get_narration_cache, get_narrator
    from api.main import app
    from api.persona.cache import InMemoryNarrationCache

    def _override() -> Iterator[sqlite3.Connection]:
        conn = get_conn(headless_2004_db, read_only=True)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db_conn] = _override
    app.dependency_overrides[get_narration_cache] = lambda: InMemoryNarrationCache()
    app.dependency_overrides[get_narrator] = lambda: _StubNarrator()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db_conn, None)
        app.dependency_overrides.pop(get_narration_cache, None)
        app.dependency_overrides.pop(get_narrator, None)


def _openapi(client: TestClient) -> dict[str, Any]:
    response = client.get("/openapi.json")
    assert response.status_code == 200, response.text
    openapi: dict[str, Any] = response.json()
    return openapi


def _response_schema(openapi: dict[str, Any], path: str, status: str) -> dict[str, Any]:
    responses = openapi["paths"][path]["post"]["responses"]
    assert status in responses, f"POST {path} advertises {sorted(responses)}, no {status}"
    schema: dict[str, Any] = responses[status]["content"]["application/json"]["schema"]
    return schema


def _ref_names(schema: dict[str, Any]) -> set[str]:
    members = [schema] if "$ref" in schema else schema.get("anyOf", schema.get("oneOf", []))
    prefix = "#/components/schemas/"
    return {member["$ref"][len(prefix) :] for member in members if "$ref" in member}


# --- (a) the fault: rated year, no rank-1 row -------------------------------


def test_champion_with_rated_year_but_no_rank_one_answers_missing_champion_500(
    headless_client: TestClient,
) -> None:
    response = headless_client.post(CHAMPION, json={"year": 2004})

    assert response.status_code == 500, response.text
    detail = response.json()["detail"]
    assert detail["error"] == "missing_champion", detail
    assert detail["year"] == 2004
    assert detail["method"] == "keener"
    assert detail["sport"] == "cfb"
    # The old symptom: an ambiguous_team body listing every rated team as a
    # candidate for the empty query the fall-through sent to resolve_team.
    assert "candidates" not in detail, detail
    assert "query" not in detail, detail


def test_missing_champion_body_names_the_requested_method_and_sport(
    headless_client: TestClient,
) -> None:
    """The body is built from the request, so it is exactly the four fields
    and nothing else -- `user_team` in particular never leaks into it."""
    response = headless_client.post(
        CHAMPION, json={"year": 2004, "method": "keener", "sport": "cfb", "user_team": "USC"}
    )

    assert response.status_code == 500, response.text
    assert response.json()["detail"] == {
        "error": "missing_champion",
        "year": 2004,
        "method": "keener",
        "sport": "cfb",
    }


# --- (b), (c): the blast radius is one (year, method, sport) ---------------


def test_champion_for_the_other_method_of_the_same_year_is_unaffected(
    headless_client: TestClient,
) -> None:
    response = headless_client.post(CHAMPION, json={"year": 2004, "method": "elo"})

    assert response.status_code == 200, response.text
    assert response.json()["evidence"]["team_name"] == "USC"


def test_team_case_for_the_same_year_and_method_is_unaffected(
    headless_client: TestClient,
) -> None:
    """Auburn, not USC: the deleted rank-1 row IS USC's 2004 keener rating,
    so USC itself is no longer a rated team for that year/method (the
    engine then fuzzy-matches "USC" to UCF, which is its business, not this
    route's). Auburn is the rank-2 row and still there."""
    response = headless_client.post(TEAM_CASE, json={"year": 2004, "team": "Auburn"})

    assert response.status_code == 200, response.text
    assert response.json()["evidence"]["team_name"] == "Auburn"
    assert response.json()["evidence"]["rank"] == 2


def test_champion_for_another_rated_year_is_unaffected(headless_client: TestClient) -> None:
    response = headless_client.post(CHAMPION, json={"year": 2005})

    assert response.status_code == 200, response.text


# --- (d): a year with no ratings at all is still unknown_year ---------------


def test_champion_for_an_unrated_year_still_answers_unknown_year_404(
    headless_client: TestClient,
) -> None:
    response = headless_client.post(CHAMPION, json={"year": 2002})

    assert response.status_code == 404, response.text
    detail = response.json()["detail"]
    assert detail["error"] == "unknown_year", detail
    assert detail["year"] == 2002
    # 2004 is still a rated year for keener: only its rank-1 row went, and
    # `available_years` is "years with ratings", not "years with a champion".
    assert detail["available_years"] == [2001, 2003, 2004, 2005, 2013, 2017, 2019]


# --- (e): /openapi.json documents it, on the champion route only ------------


def test_openapi_declares_missing_champion_500_on_the_champion_route_only(
    headless_client: TestClient,
) -> None:
    openapi = _openapi(headless_client)

    assert _ref_names(_response_schema(openapi, CHAMPION, "500")) == {MISSING_CHAMPION_RESPONSE}
    assert MISSING_CHAMPION_RESPONSE in openapi["components"]["schemas"]

    for path in (TEAM_CASE, COMPARE):
        assert "500" not in openapi["paths"][path]["post"]["responses"], path


def test_real_missing_champion_response_matches_the_advertised_schema(
    headless_client: TestClient,
) -> None:
    response = headless_client.post(CHAMPION, json={"year": 2004})
    assert response.status_code == 500, response.text
    body = response.json()

    openapi = _openapi(headless_client)
    schema = _response_schema(openapi, CHAMPION, "500")
    root = {**schema, "components": openapi["components"]}
    errors = [e.message for e in Draft202012Validator(root).iter_errors(body)]
    assert not errors, f"body {body} does not match {schema}: {errors}"
