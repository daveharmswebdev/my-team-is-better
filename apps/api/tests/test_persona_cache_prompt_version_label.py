"""Every `persona_cache` row records the prompt that wrote it (issue #447).

`purge-narrations --prompt-version qb-persona-v3` is only useful if QB rows
say `qb-persona-v3`. Before #447 the app built one `PostgresNarrationCache`
labelled `PROMPT_VERSION`, so QB narrations were stored as `persona-v13`.
Now the QB route's store comes from `api.deps.get_qb_narration_cache`, which
relabels the production Postgres store with `QB_PROMPT_VERSION` and passes
any other store (a test's in-memory fake, the disabled store) through.

These run the real routes against a real `PostgresNarrationCache` whose
`psycopg.connect` is replaced by a fake connection that records each INSERT's
parameters: no Postgres, no Claude call (the narrator is the `FakeNarrator`).
The cache keys themselves are untouched; `test_persona_cache_key_fact_block.py`
pins them.
"""

from __future__ import annotations

from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from fixtures.narrator_fake import FakeNarrator
from fixtures.qb_blocks import KURT_WARNER, STEVE_MCNAIR

import api.deps as deps_module
from api.config import PROMPT_VERSION, QB_PROMPT_VERSION
from api.deps import get_narration_cache, get_narrator, get_qb_narration_cache
from api.main import app
from api.persona.cache import (
    CachedNarration,
    DisabledNarrationCache,
    InMemoryNarrationCache,
    PostgresNarrationCache,
)

FAKE_DSN = "postgresql://cache.invalid/persona"


class _RecordingConn:
    """A psycopg-shaped connection: every SELECT misses, every INSERT's
    parameters are recorded."""

    def __init__(self, inserts: list[tuple[Any, ...]]) -> None:
        self._inserts = inserts

    def __enter__(self) -> _RecordingConn:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, query: str, params: tuple[Any, ...]) -> _RecordingConn:
        if "INSERT INTO persona_cache" in query:
            self._inserts.append(params)
        return self

    def fetchone(self) -> None:
        return None

    def commit(self) -> None:
        return None


def _written_versions(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, ...]]:
    inserts: list[tuple[Any, ...]] = []
    monkeypatch.setattr(psycopg, "connect", lambda *a, **k: _RecordingConn(inserts))
    return inserts


def _wire_production_store(narrator: FakeNarrator) -> None:
    store = PostgresNarrationCache(FAKE_DSN, prompt_version=PROMPT_VERSION)
    app.dependency_overrides[get_narration_cache] = lambda: store
    app.dependency_overrides[get_narrator] = lambda: narrator


def test_a_qb_narration_is_stored_under_the_qb_prompt_version(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    inserts = _written_versions(monkeypatch)
    _wire_production_store(
        FakeNarrator(
            always={
                "text": "{w} takes both, and the books only open in {yr}.",
                "claims": [
                    {"id": "w", "kind": "winner", "measure": "both"},
                    {"id": "yr", "kind": "year"},
                ],
            }
        )
    )

    response = client.post(
        "/api/players/compare/verdict", json={"a": KURT_WARNER, "b": STEVE_MCNAIR}
    )

    assert response.status_code == 200, response.text
    assert response.json()["narration"]["cached"] is False
    assert [params[3] for params in inserts] == [QB_PROMPT_VERSION]


def test_a_team_narration_is_stored_under_the_team_prompt_version(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    inserts = _written_versions(monkeypatch)
    _wire_production_store(FakeNarrator())

    response = client.post("/api/verdict/champion", json={"year": 2005})

    assert response.status_code == 200, response.text
    assert [params[3] for params in inserts] == [PROMPT_VERSION]


def test_the_production_stores_are_labelled_by_their_own_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(deps_module, "APP_TEST_MODE", False)
    monkeypatch.setattr(deps_module, "DATABASE_URL", FAKE_DSN)
    inserts = _written_versions(monkeypatch)

    team = deps_module.get_narration_cache()
    qb = get_qb_narration_cache(team)

    team.set("team-key", CachedNarration(text="t", contested=False))
    qb.set("qb-key", CachedNarration(text="q", contested=False))

    assert [(params[0], params[3]) for params in inserts] == [
        ("team-key", PROMPT_VERSION),
        ("qb-key", QB_PROMPT_VERSION),
    ]
    # Relabelling builds a second store; the team one keeps its own label.
    assert qb is not team


def test_any_other_store_is_passed_through_to_the_qb_route() -> None:
    memory = InMemoryNarrationCache()
    disabled = DisabledNarrationCache()

    assert get_qb_narration_cache(memory) is memory
    assert get_qb_narration_cache(disabled) is disabled
