"""issue #4's one real, non-mocked integration test: an actual Postgres
round-trip against `DATABASE_URL` and an actual Claude API call against
`ANTHROPIC_API_KEY`, both read from `apps/api/.env` -- mirrors issue #3's
real-engine golden-dataset test pattern, applied to the persona layer.

Gated with `pytest.mark.skipif` on those two env vars being unset, so this
auto-skips in CI (which has neither, by design -- see CLAUDE.md/issue #4's
negative scope) and actually runs locally (which has both, via
`apps/api/.env`). Confirms the full real stack, with no dependency
overrides at all: `ensure_schema` against a real Postgres connection, the
production `get_narration_cache`/`get_narrator` wiring, a real
`claude-haiku-4-5` call, and that calling the same request twice results in
a cache hit the second time.
"""

from __future__ import annotations

import psycopg
import pytest
from fastapi.testclient import TestClient

from api.config import ANTHROPIC_API_KEY, DATABASE_URL, PROMPT_VERSION
from api.deps import get_narration_cache, get_narrator
from api.main import app
from api.persona.cache import cache_key, ensure_schema

pytestmark = pytest.mark.skipif(
    not DATABASE_URL or not ANTHROPIC_API_KEY,
    reason="requires a real DATABASE_URL and ANTHROPIC_API_KEY (see apps/api/.env)",
)


def test_repeated_champion_request_is_a_cache_hit_on_the_second_call(
    client: TestClient,
) -> None:
    assert DATABASE_URL is not None  # narrows for mypy; already skipped otherwise

    # The shared `client` fixture (conftest.py) overrides these two with
    # CI-safe fakes by default -- pop both so this test exercises the real
    # production wiring (real Postgres, real Claude) instead.
    app.dependency_overrides.pop(get_narration_cache, None)
    app.dependency_overrides.pop(get_narrator, None)

    with psycopg.connect(DATABASE_URL) as conn:
        ensure_schema(conn)
        # 2005's champion (Texas, per the fixture db) with the request's
        # defaults (method="keener", user_team=None) -- the exact cache key
        # `api.persona.service.narrate_team_case` will compute for this
        # request. Deleted up front so this test proves a genuine
        # miss-then-hit sequence, not a leftover row from a prior local run.
        key = cache_key(
            question_type="champion",
            year=2005,
            teams=("Texas",),
            user_team=None,
            method="keener",
            prompt_version=PROMPT_VERSION,
        )
        conn.execute("DELETE FROM persona_cache WHERE cache_key = %s", (key,))
        conn.commit()

    first = client.post("/api/verdict/champion", json={"year": 2005})
    second = client.post("/api/verdict/champion", json={"year": 2005})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["narration"]["cached"] is False
    assert second.json()["narration"]["cached"] is True
    assert second.json()["narration"]["text"] == first.json()["narration"]["text"]
    assert first.json()["narration"]["text"]
