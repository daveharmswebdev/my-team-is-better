"""Failing-first tests for issue #280: a stale database -- one built before
the #183 Elo ledger, so it lacks `elo_ledger_configs`/`elo_ledger_steps` --
answers every verdict route with a declared 503 JSON envelope, never
Starlette's bodiless plain-text 500.

The engine already detects the condition: `cfb_strength.evidence.proof.
_elo_ledger` checks both tables exist before it queries either and raises
`StaleDatabaseError` (issue #192), reachable through `build_team_case` and
`build_comparison`. Before #280 nothing in `api.errors` mapped it, so it fell
through to Starlette's default 500 with a `text/plain` "Internal Server
Error" body.

The decision recorded on #280: the wire body is exactly
`{"detail": {"error": "stale_database"}}`. The exception's message names the
missing tables and the operator fix (rebuild the ratings), which is the
operator's business, not the visitor's, so it goes to the error log and
never into the response. 503, because nothing about the request was wrong
and a rebuild/redeploy fixes it.

The reproduction is real, not a monkeypatched raise: a copy of the committed
fixture db with both ledger tables dropped, wired through the same
`get_db_conn` override the shared `client` fixture uses.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from cfb_strength.db.connection import get_conn
from conftest import FIXTURE_DB
from fastapi.testclient import TestClient
from fixtures.narrator_fake import FakeNarrator
from jsonschema import Draft202012Validator

LEDGER_TABLES = ("elo_ledger_configs", "elo_ledger_steps")
STALE_DATABASE_RESPONSE = "StaleDatabaseErrorResponse"

# Every verdict route reaches `build_team_case` or `build_comparison`, and
# the ledger is read for every method, keener included (the engine's
# `StaleDatabaseError` docstring), so each one fails on a stale db.
VERDICT_REQUESTS: list[tuple[str, dict[str, Any]]] = [
    ("/api/verdict/champion", {"year": 2004}),
    ("/api/verdict/team-case", {"year": 2004, "team": "Auburn"}),
    ("/api/verdict/compare", {"year": 2004, "team_a": "USC", "team_b": "Auburn"}),
    ("/api/verdict/team-case", {"year": 2004, "team": "Auburn", "method": "elo"}),
]


@pytest.fixture
def stale_db(tmp_path: Path) -> Path:
    """A copy of the committed fixture with the two #183 ledger tables
    dropped and nothing else touched."""
    db = tmp_path / "stale.sqlite3"
    shutil.copy(FIXTURE_DB, db)
    conn = sqlite3.connect(db)
    try:
        present = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN (?, ?)",
                LEDGER_TABLES,
            )
        }
        # Premise: the committed fixture has both tables, so dropping them is
        # what makes it stale. Otherwise every test below would be testing a
        # db that was already stale for some other reason.
        assert present == set(LEDGER_TABLES), present
        for table in LEDGER_TABLES:
            conn.execute(f"DROP TABLE {table}")
        conn.commit()
    finally:
        conn.close()
    return db


@pytest.fixture
def stale_client(stale_db: Path) -> Iterator[TestClient]:
    """Same wiring as conftest's `client`, against the stale copy.
    `raise_server_exceptions=False` so an unmapped exception comes back as
    the 500 a real client would see, instead of being re-raised into the
    test."""
    from api.deps import get_db_conn, get_narration_cache, get_narrator
    from api.main import app
    from api.persona.cache import InMemoryNarrationCache

    def _override() -> Iterator[sqlite3.Connection]:
        conn = get_conn(stale_db, read_only=True)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db_conn] = _override
    app.dependency_overrides[get_narration_cache] = lambda: InMemoryNarrationCache()
    app.dependency_overrides[get_narrator] = lambda: FakeNarrator()
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.pop(get_db_conn, None)
        app.dependency_overrides.pop(get_narration_cache, None)
        app.dependency_overrides.pop(get_narrator, None)


@pytest.mark.parametrize(("path", "payload"), VERDICT_REQUESTS)
def test_stale_database_answers_a_declared_503_with_no_operator_detail(
    stale_client: TestClient,
    caplog: pytest.LogCaptureFixture,
    path: str,
    payload: dict[str, Any],
) -> None:
    with caplog.at_level(logging.ERROR, logger="api.errors"):
        response = stale_client.post(path, json=payload)

    assert response.status_code == 503, response.text
    assert response.headers["content-type"].startswith("application/json"), response.headers
    assert response.json() == {"detail": {"error": "stale_database"}}
    # The operator message stays off the wire.
    for table in LEDGER_TABLES:
        assert table not in response.text, response.text
    assert "cfb rate" not in response.text, response.text

    # ...and goes to the error log, where the operator will look.
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR and r.name == "api.errors"]
    assert errors, "the stale-database handler logged nothing at error level"
    logged = "\n".join(r.getMessage() for r in errors)
    for table in LEDGER_TABLES:
        assert table in logged, logged


def _openapi(client: TestClient) -> dict[str, Any]:
    response = client.get("/openapi.json")
    assert response.status_code == 200, response.text
    openapi: dict[str, Any] = response.json()
    return openapi


@pytest.mark.parametrize(("path", "payload"), VERDICT_REQUESTS)
def test_real_stale_database_response_matches_the_advertised_503_schema(
    stale_client: TestClient, path: str, payload: dict[str, Any]
) -> None:
    response = stale_client.post(path, json=payload)
    assert response.status_code == 503, response.text
    body = response.json()

    openapi = _openapi(stale_client)
    responses = openapi["paths"][path]["post"]["responses"]
    assert "503" in responses, f"POST {path} advertises {sorted(responses)}, no 503"
    schema = responses["503"]["content"]["application/json"]["schema"]
    assert schema == {"$ref": f"#/components/schemas/{STALE_DATABASE_RESPONSE}"}, schema
    root = {**schema, "components": openapi["components"]}
    errors = [e.message for e in Draft202012Validator(root).iter_errors(body)]
    assert not errors, f"body {body} does not match {schema}: {errors}"


# ---------------------------------------------------------------------------
# Issue #423: a db missing a late-added *column* (here `ratings.sport`, #51)
# is stale too, and every route that reads the ratings/teams tables says so
# as the same declared 503. Before #423 three routes ran their own query on a
# late-added name before anything checked the schema:
#
# * POST /api/verdict/champion -- `_resolve_champion_name`'s `r.sport = ?`
#   query raised a bare `sqlite3.OperationalError` (a 500);
# * GET /api/years -- the engine's `list_available_years` now raises
#   `StaleDatabaseError`, which the route did not declare;
# * GET /api/teams -- `list_team_records` reads `teams.sport`,
#   `teams.alternate_names` and (with `year`) `ratings.sport`, so it either
#   raised `OperationalError` or answered 200 from a db that every verdict
#   route refuses.
# ---------------------------------------------------------------------------

STALE_COLUMN = ("ratings", "sport")


def _drop_column(db_path: Path, table: str, column: str) -> None:
    """Rebuild `table` without `column` (SQLite's documented recipe, as in
    packages/cfb-engine/tests/test_evidence_stale_columns.py)."""
    conn = sqlite3.connect(db_path)
    try:
        kept = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
        # Premise: the committed fixture has the column, so dropping it is
        # what makes the copy stale.
        assert column in kept, f"{table}.{column} is not in the fixture's schema"
        kept.remove(column)
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(f"CREATE TABLE {table}_stale AS SELECT {', '.join(kept)} FROM {table}")
        conn.execute(f"DROP TABLE {table}")
        conn.execute(f"ALTER TABLE {table}_stale RENAME TO {table}")
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def stale_column_client(tmp_path: Path) -> Iterator[TestClient]:
    """`stale_client`'s wiring against a copy of the fixture with only
    `ratings.sport` removed: both ledger tables are still present."""
    from api.deps import get_db_conn, get_narration_cache, get_narrator
    from api.main import app
    from api.persona.cache import InMemoryNarrationCache

    db = tmp_path / "stale_column.sqlite3"
    shutil.copy(FIXTURE_DB, db)
    _drop_column(db, *STALE_COLUMN)

    def _override() -> Iterator[sqlite3.Connection]:
        conn = get_conn(db, read_only=True)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db_conn] = _override
    app.dependency_overrides[get_narration_cache] = lambda: InMemoryNarrationCache()
    app.dependency_overrides[get_narrator] = lambda: FakeNarrator()
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.pop(get_db_conn, None)
        app.dependency_overrides.pop(get_narration_cache, None)
        app.dependency_overrides.pop(get_narrator, None)


# (http method, path, query params for a GET or the json body for a POST)
STALE_COLUMN_REQUESTS: list[tuple[str, str, dict[str, Any]]] = [
    ("post", "/api/verdict/champion", {"year": 2004}),
    ("post", "/api/verdict/team-case", {"year": 2004, "team": "Auburn"}),
    ("post", "/api/verdict/compare", {"year": 2004, "team_a": "USC", "team_b": "Auburn"}),
    ("get", "/api/years", {}),
    ("get", "/api/years", {"method": "elo", "sport": "nfl"}),
    ("get", "/api/teams", {}),
    ("get", "/api/teams", {"year": 2004}),
    ("get", "/api/teams", {"sport": "nfl", "year": 2004, "method": "elo"}),
]


def _send(client: TestClient, method: str, path: str, data: dict[str, Any]) -> Any:
    if method == "post":
        return client.post(path, json=data)
    return client.get(path, params=data)


@pytest.mark.parametrize(("method", "path", "data"), STALE_COLUMN_REQUESTS)
def test_missing_late_added_column_answers_the_declared_stale_database_503(
    stale_column_client: TestClient,
    caplog: pytest.LogCaptureFixture,
    method: str,
    path: str,
    data: dict[str, Any],
) -> None:
    with caplog.at_level(logging.ERROR, logger="api.errors"):
        response = _send(stale_column_client, method, path, data)

    assert response.status_code == 503, response.text
    assert response.headers["content-type"].startswith("application/json"), response.headers
    assert response.json() == {"detail": {"error": "stale_database"}}
    missing = ".".join(STALE_COLUMN)
    assert missing not in response.text, response.text

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR and r.name == "api.errors"]
    assert errors, "the stale-database handler logged nothing at error level"
    assert missing in "\n".join(r.getMessage() for r in errors)

    openapi = _openapi(stale_column_client)
    responses = openapi["paths"][path][method]["responses"]
    assert "503" in responses, f"{method.upper()} {path} advertises {sorted(responses)}, no 503"
    schema = responses["503"]["content"]["application/json"]["schema"]
    assert schema == {"$ref": f"#/components/schemas/{STALE_DATABASE_RESPONSE}"}, schema
    root = {**schema, "components": openapi["components"]}
    body = response.json()
    problems = [e.message for e in Draft202012Validator(root).iter_errors(body)]
    assert not problems, f"body {body} does not match {schema}: {problems}"
