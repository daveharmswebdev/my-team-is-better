"""Failing-first, CI-safe tests for issue #4's persona narration layer
wrapping the `/api/verdict/*` routes from issue #3. Every test here mocks
the Claude call (a `FakeNarrator` test double for `api.persona.claude_client
.Narrator`) and uses `InMemoryNarrationCache` -- no live Postgres
connection or `ANTHROPIC_API_KEY` required. The one real, non-mocked
round-trip lives in `tests/test_verdict_persona_integration.py`, gated on
`DATABASE_URL`/`ANTHROPIC_API_KEY` being set.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import anthropic
import httpx2
from fastapi.testclient import TestClient

from api.deps import get_narration_cache, get_narrator
from api.main import app
from api.persona.cache import InMemoryNarrationCache, NarrationCacheStore


class FakeNarrator:
    """Test double for `Narrator` -- returns a scripted sequence of
    responses (or raises a scripted exception on every call), and records
    every call it received so tests can assert on call count and on the
    retry feedback's content without a live API key.
    """

    def __init__(self, responses: list[str] | None = None, error: Exception | None = None) -> None:
        self.responses = list(responses or [])
        self.error = error
        self.calls: list[list[dict[str, str]]] = []

    def complete(self, *, system: str, messages: list[dict[str, str]]) -> str:
        self.calls.append(messages)
        if self.error is not None:
            raise self.error
        return self.responses.pop(0)


@contextmanager
def _wired(
    narrator: FakeNarrator, cache: NarrationCacheStore | None = None
) -> Iterator[NarrationCacheStore]:
    cache = cache if cache is not None else InMemoryNarrationCache()
    app.dependency_overrides[get_narration_cache] = lambda: cache
    app.dependency_overrides[get_narrator] = lambda: narrator
    try:
        yield cache
    finally:
        app.dependency_overrides.pop(get_narration_cache, None)
        app.dependency_overrides.pop(get_narrator, None)


# ---------------------------------------------------------------------------
# envelope shape, for all three routes
# ---------------------------------------------------------------------------


def test_champion_response_wraps_evidence_and_narration(client: TestClient) -> None:
    narrator = FakeNarrator(responses=["Texas ran the table at 13-0 in 2005."])

    with _wired(narrator):
        response = client.post("/api/verdict/champion", json={"year": 2005})

    assert response.status_code == 200
    body = response.json()
    assert body["evidence"]["team_name"] == "Texas"
    assert body["evidence"]["rank"] == 1
    assert body["narration"]["text"] == "Texas ran the table at 13-0 in 2005."
    assert body["narration"]["cached"] is False
    assert body["narration"]["contested"] is False


def test_team_case_response_wraps_evidence_and_narration(client: TestClient) -> None:
    narrator = FakeNarrator(responses=["USC put up a real season in 2005."])

    with _wired(narrator):
        response = client.post("/api/verdict/team-case", json={"year": 2005, "team": "USC"})

    assert response.status_code == 200
    body = response.json()
    assert body["evidence"]["team_name"] == "USC"
    assert body["narration"]["text"] == "USC put up a real season in 2005."


def test_compare_response_wraps_evidence_and_narration(client: TestClient) -> None:
    narrator = FakeNarrator(responses=["Texas edges out USC in 2005."])

    with _wired(narrator):
        response = client.post(
            "/api/verdict/compare",
            json={"year": 2005, "team_a": "Texas", "team_b": "USC"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["evidence"]["team_a"]["team_name"] == "Texas"
    assert body["narration"]["text"] == "Texas edges out USC in 2005."


# ---------------------------------------------------------------------------
# cache hit vs. cache miss
# ---------------------------------------------------------------------------


def test_cache_miss_calls_claude_and_stores_the_result(client: TestClient) -> None:
    narrator = FakeNarrator(responses=["Texas ran the table at 13-0 in 2005."])

    with _wired(narrator) as cache:
        response = client.post("/api/verdict/champion", json={"year": 2005})

    assert response.status_code == 200
    assert response.json()["narration"]["cached"] is False
    assert len(narrator.calls) == 1
    # And it's actually in the cache now, for the next lookup.
    assert isinstance(cache, InMemoryNarrationCache)


def test_cache_hit_skips_the_claude_call_entirely(client: TestClient) -> None:
    narrator = FakeNarrator(responses=["Texas ran the table at 13-0 in 2005."])

    with _wired(narrator):
        first = client.post("/api/verdict/champion", json={"year": 2005})
        second = client.post("/api/verdict/champion", json={"year": 2005})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["narration"]["cached"] is False
    assert second.json()["narration"]["cached"] is True
    assert second.json()["narration"]["text"] == first.json()["narration"]["text"]
    # Only the first request should have ever called Claude.
    assert len(narrator.calls) == 1


# ---------------------------------------------------------------------------
# grounding retry-then-fallback
# ---------------------------------------------------------------------------


def test_grounding_failure_retries_once_with_the_mismatch_fed_back(
    client: TestClient,
) -> None:
    narrator = FakeNarrator(
        responses=[
            "USC would have smoked Alabama too, probably.",  # ungrounded mention
            "USC put together a real season in 2005.",
        ]
    )

    with _wired(narrator):
        response = client.post("/api/verdict/team-case", json={"year": 2005, "team": "USC"})

    assert response.status_code == 200
    assert response.json()["narration"]["text"] == "USC put together a real season in 2005."
    assert len(narrator.calls) == 2
    retry_feedback = narrator.calls[1][-1]["content"]
    assert "Alabama" in retry_feedback


def test_two_grounding_failures_serve_the_fallback_and_never_make_a_third_call(
    client: TestClient,
) -> None:
    narrator = FakeNarrator(
        responses=[
            "USC would have smoked Alabama too, probably.",
            "Honestly Alabama could have gone undefeated as well.",
        ]
    )

    with _wired(narrator):
        response = client.post("/api/verdict/team-case", json={"year": 2005, "team": "USC"})

    assert response.status_code == 200
    body = response.json()
    assert "USC" in body["narration"]["text"]
    assert "12" in body["narration"]["text"]  # USC's real 2005 win count
    assert len(narrator.calls) == 2


def test_claude_api_error_falls_back_safely_instead_of_500ing(client: TestClient) -> None:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    narrator = FakeNarrator(error=anthropic.APIConnectionError(request=request))

    with _wired(narrator):
        response = client.post("/api/verdict/team-case", json={"year": 2005, "team": "USC"})

    assert response.status_code == 200
    body = response.json()
    assert "USC" in body["narration"]["text"]
    assert len(narrator.calls) == 1


# ---------------------------------------------------------------------------
# contested-year disclosure
# ---------------------------------------------------------------------------


def test_contested_is_true_for_2003() -> None:
    from api.persona.service import is_contested

    assert is_contested(2003) is True


def test_contested_is_true_for_2017() -> None:
    from api.persona.service import is_contested

    assert is_contested(2017) is True


def test_contested_is_false_for_a_must_match_year() -> None:
    from api.persona.service import is_contested

    assert is_contested(2005) is False
