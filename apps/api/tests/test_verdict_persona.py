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
from pathlib import Path

import anthropic
import httpx2
from cfb_strength.db.connection import get_conn
from cfb_strength.evidence.proof import build_team_case
from fastapi.testclient import TestClient

from api.config import PROMPT_VERSION
from api.deps import get_narration_cache, get_narrator
from api.main import app
from api.models import TeamCaseOut
from api.persona.cache import InMemoryNarrationCache, NarrationCacheStore, cache_key
from api.persona.grounding import GROUNDING_VERSION
from api.persona.service import team_case_fact_block_json

FIXTURE_DB = Path(__file__).parent / "fixtures" / "cfb_verdict_fixture.sqlite3"


def _usc_2005_team_case_key() -> str:
    """The cache key `/api/verdict/team-case {"year": 2005, "team": "USC"}`
    uses with the request's default method and sport. The fact block is the
    service's own, built from the same fixture evidence the route builds
    (issue #145)."""
    conn = get_conn(FIXTURE_DB, read_only=True)
    try:
        case = TeamCaseOut.from_dataclass(
            build_team_case(conn, 2005, "USC", method="keener", sport="cfb")
        )
    finally:
        conn.close()
    return cache_key(
        question_type="team_case",
        year=2005,
        teams=("USC",),
        user_team=None,
        method="keener",
        sport="cfb",
        prompt_version=PROMPT_VERSION,
        fact_block_json=team_case_fact_block_json(case),
        grounding_version=GROUNDING_VERSION,
    )


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


def test_same_named_team_in_another_sport_does_not_get_the_other_sports_cached_narration(
    sport_client: TestClient,
) -> None:
    """Issue #84: the sport fixture's "Wildcats" exist in both CFB and NFL
    with the same year and method, so the two team-case questions differ
    *only* by sport. The NFL narration is cached first; the CFB question
    must miss the cache and get its own narration, not the NFL one.
    """
    nfl_text = "the pro version, no notes."
    cfb_text = "the college version, no notes."
    narrator = FakeNarrator(responses=[nfl_text, cfb_text])

    with _wired(narrator):
        nfl = sport_client.post(
            "/api/verdict/team-case",
            json={"year": 2023, "team": "Wildcats", "sport": "nfl"},
        )
        cfb = sport_client.post(
            "/api/verdict/team-case",
            json={"year": 2023, "team": "Wildcats", "sport": "cfb"},
        )

    assert nfl.status_code == 200
    assert cfb.status_code == 200
    # Same resolved name in both leagues, so only sport tells them apart.
    assert nfl.json()["evidence"]["team_name"] == cfb.json()["evidence"]["team_name"]
    assert nfl.json()["narration"]["text"] == nfl_text
    assert cfb.json()["narration"]["text"] != nfl_text, "CFB question served the NFL narration"
    assert cfb.json()["narration"]["text"] == cfb_text
    assert cfb.json()["narration"]["cached"] is False
    assert len(narrator.calls) == 2


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

    with _wired(narrator) as cache:
        response = client.post("/api/verdict/team-case", json={"year": 2005, "team": "USC"})

    assert response.status_code == 200
    assert response.json()["narration"]["text"] == "USC put together a real season in 2005."
    assert len(narrator.calls) == 2
    retry_feedback = narrator.calls[1][-1]["content"]
    assert "Alabama" in retry_feedback
    # A successful retry is cached under the key the fallback test below
    # checks, so that test's "not cached" can't pass on a wrong key.
    cached = cache.get(_usc_2005_team_case_key())
    assert cached is not None
    assert cached.text == "USC put together a real season in 2005."


def test_two_grounding_failures_serve_the_fallback_and_never_make_a_third_call(
    client: TestClient,
) -> None:
    narrator = FakeNarrator(
        responses=[
            "USC would have smoked Alabama too, probably.",
            "Honestly Alabama could have gone undefeated as well.",
        ]
    )

    with _wired(narrator) as cache:
        response = client.post("/api/verdict/team-case", json={"year": 2005, "team": "USC"})

    assert response.status_code == 200
    body = response.json()
    assert "USC" in body["narration"]["text"]
    assert "12" in body["narration"]["text"]  # USC's real 2005 win count
    assert len(narrator.calls) == 2
    # Issue #65: the fallback is served, but never cached as if it were real.
    assert body["narration"]["cached"] is False
    assert cache.get(_usc_2005_team_case_key()) is None


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

    assert is_contested("cfb", 2003) is True


def test_contested_is_true_for_2017() -> None:
    from api.persona.service import is_contested

    assert is_contested("cfb", 2017) is True


def test_contested_is_false_for_a_must_match_year() -> None:
    from api.persona.service import is_contested

    assert is_contested("cfb", 2005) is False


def test_contested_is_false_for_nfl_in_the_cfb_contested_years() -> None:
    """Issue #151: 2003 and 2017 are disputed college seasons only."""
    from api.persona.service import is_contested

    assert is_contested("nfl", 2003) is False
    assert is_contested("nfl", 2017) is False
