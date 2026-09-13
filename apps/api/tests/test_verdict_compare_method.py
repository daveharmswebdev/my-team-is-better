"""Issue #152 (epic #147 Phase 0): a compare verdict says which rating method
answered it.

The engine's `ComparisonResult` carries `method`, but the API's
`ComparisonResultOut` used to drop it in `from_dataclass`, so neither the
response nor the narrator's fact block could say whether a compare was Keener
or Elo. These tests pin both ends for every registered method:

- the HTTP response's `evidence.method` is the requested method, and
- the JSON handed to the compare narrator names that same method.

Every method runs against `fixtures/method_fixture.py`'s throwaway db, which
has rows for all of `typing.get_args(Method)` -- the committed
`cfb_verdict_fixture.sqlite3` has no `elo_career` rows (issue #98), and a
parametrization that can't run must not be skipped silently. Nothing here
asserts how any method ranks the teams relative to another.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from cfb_strength.db.connection import get_conn
from fastapi.testclient import TestClient
from fixtures.method_fixture import METHODS, TEAM_A, TEAM_B, YEAR, make_method_fixture_db

from api.deps import get_db_conn, get_narration_cache, get_narrator
from api.main import app
from api.persona.cache import InMemoryNarrationCache


class _RecordingNarrator:
    """Always returns a line with no numbers or team names (so it grounds on
    the first try), and records every message list it was handed."""

    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []

    def complete(self, *, system: str, messages: list[dict[str, str]]) -> str:
        self.calls.append([dict(m) for m in messages])
        return "Solid case, no notes."


@pytest.fixture
def narrator() -> _RecordingNarrator:
    return _RecordingNarrator()


@pytest.fixture
def method_client(tmp_path: Path, narrator: _RecordingNarrator) -> Iterator[TestClient]:
    """Same wiring as conftest's `client`, against the every-method db."""
    db_path = make_method_fixture_db(tmp_path)

    def _override() -> Iterator[sqlite3.Connection]:
        conn = get_conn(db_path, read_only=True)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db_conn] = _override
    app.dependency_overrides[get_narration_cache] = lambda: InMemoryNarrationCache()
    app.dependency_overrides[get_narrator] = lambda: narrator
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db_conn, None)
        app.dependency_overrides.pop(get_narration_cache, None)
        app.dependency_overrides.pop(get_narrator, None)


def _compare(client: TestClient, method: str) -> Any:
    response = client.post(
        "/api/verdict/compare",
        json={"year": YEAR, "team_a": TEAM_A, "team_b": TEAM_B, "method": method},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _fact_block_text(user_message: str) -> str:
    """The JSON between `build_user_message`'s FACT BLOCK header and its
    trailing `contested:` line (same seam as `test_verdict_ties.py`)."""
    header = "FACT BLOCK (JSON):\n"
    body = user_message[user_message.index(header) + len(header) :]
    return body[: body.rindex("\n\ncontested:")]


def test_every_registered_method_is_exercised() -> None:
    """The parametrizations below cover the whole contract vocabulary."""
    assert set(METHODS) == {"keener", "elo", "elo_career"}


@pytest.mark.parametrize("method", METHODS)
def test_compare_evidence_names_the_method_that_answered(
    method_client: TestClient, method: str
) -> None:
    evidence = _compare(method_client, method)["evidence"]

    assert evidence["method"] == method


@pytest.mark.parametrize("method", METHODS)
def test_fact_block_given_to_the_compare_narrator_names_the_method(
    method_client: TestClient, narrator: _RecordingNarrator, method: str
) -> None:
    _compare(method_client, method)

    assert len(narrator.calls) == 1
    fact_block = _fact_block_text(narrator.calls[0][0]["content"])
    assert f'"method":"{method}"' in fact_block
    assert json.loads(fact_block)["method"] == method


def test_openapi_publishes_method_as_a_required_compare_evidence_field() -> None:
    schemas = TestClient(app).get("/openapi.json").json()["components"]["schemas"]

    assert "method" in schemas["ComparisonResultOut"]["required"]
