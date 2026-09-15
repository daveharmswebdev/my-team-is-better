"""Issue #65: `api.persona.service` must never cache the templated fallback.

A fallback (a Claude transport error, or two rejected submissions) is served
to the user with `cached=False` and not written to the cache, so the next
identical request asks the narrator again. A legacy cache row whose text is
exactly this request's fallback text (written before the fix) is treated as a
miss, and a later successful narration overwrites it.

Both service entry points (`narrate_team_case`, `narrate_comparison`) are
exercised against real evidence from the committed fixture, with
`InMemoryNarrationCache` and a scripted narrator: no Postgres, no Claude.
Since issue #291 the narrator submits typed-claim tool calls, and what may be
served or cached is decided by `api.persona.claims`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import anthropic
import httpx2
import pytest
from anthropic.types import MessageParam
from cfb_strength.db.connection import get_conn
from cfb_strength.evidence.proof import build_comparison, build_team_case

from api.config import PROMPT_VERSION
from api.models import ComparisonResultOut, NarrationOut, TeamCaseOut
from api.persona.cache import CachedNarration, InMemoryNarrationCache, cache_key
from api.persona.claims import GROUNDING_VERSION
from api.persona.claude_client import NarratorReply, tool_reply
from api.persona.fallback import comparison_fallback_text, team_case_fallback_text
from api.persona.service import (
    comparison_fact_block_json,
    narrate_comparison,
    narrate_team_case,
    team_case_fact_block_json,
)
from api.repositories.teams import list_team_records

FIXTURE_DB = Path(__file__).parent / "fixtures" / "cfb_verdict_fixture.sqlite3"

ROUTES = ["team_case", "compare"]

# No numbers, no team names, no claims: accepted against any fact block.
REAL_NARRATION = "Solid case, no notes."
# A number typed into the prose instead of claimed: rejected every time.
REJECTED_NARRATION = "They won that one by 987654 points."


class _ScriptedNarrator:
    def __init__(self, responses: list[str] | None = None, error: Exception | None = None) -> None:
        self.responses = list(responses or [])
        self.error = error
        self.calls: list[list[MessageParam]] = []

    def submit(self, *, system: str, messages: list[MessageParam]) -> NarratorReply:
        self.calls.append(messages)
        if self.error is not None:
            raise self.error
        return tool_reply({"text": self.responses.pop(0), "claims": []})


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = get_conn(FIXTURE_DB, read_only=True)
    try:
        yield connection
    finally:
        connection.close()


def _case(conn: sqlite3.Connection) -> TeamCaseOut:
    return TeamCaseOut.from_dataclass(
        build_team_case(conn, 2005, "Texas", method="keener", sport="cfb")
    )


def _comparison(conn: sqlite3.Connection) -> ComparisonResultOut:
    return ComparisonResultOut.from_dataclass(
        build_comparison(conn, 2005, "Texas", "USC", method="keener", sport="cfb")
    )


def _ask(
    route: str,
    conn: sqlite3.Connection,
    cache: InMemoryNarrationCache,
    narrator: _ScriptedNarrator,
) -> NarrationOut:
    # The catalog the route reads once for `user_team` (issues #245, #291).
    catalog = list_team_records(conn, "cfb")
    if route == "team_case":
        return narrate_team_case(
            _case(conn),
            user_team=None,
            question_type="team_case",
            method="keener",
            sport="cfb",
            catalog=catalog,
            cache=cache,
            narrator=narrator,
        )
    return narrate_comparison(
        _comparison(conn),
        user_team=None,
        method="keener",
        sport="cfb",
        catalog=catalog,
        cache=cache,
        narrator=narrator,
    )


def _key(route: str, conn: sqlite3.Connection) -> str:
    # The fact block is the service's own (issue #145), built from the same
    # evidence `_ask` narrates.
    if route == "team_case":
        return cache_key(
            question_type="team_case",
            year=2005,
            teams=("Texas",),
            user_team=None,
            method="keener",
            sport="cfb",
            prompt_version=PROMPT_VERSION,
            fact_block_json=team_case_fact_block_json(_case(conn)),
            grounding_version=GROUNDING_VERSION,
        )
    return cache_key(
        question_type="compare",
        year=2005,
        teams=("Texas", "USC"),
        user_team=None,
        method="keener",
        sport="cfb",
        prompt_version=PROMPT_VERSION,
        fact_block_json=comparison_fact_block_json(_comparison(conn)),
        grounding_version=GROUNDING_VERSION,
    )


def _fallback_text(route: str, conn: sqlite3.Connection) -> str:
    if route == "team_case":
        return team_case_fallback_text(_case(conn))
    return comparison_fallback_text(_comparison(conn))


@pytest.mark.parametrize("route", ROUTES)
def test_real_narration_is_cached_under_the_expected_key(
    route: str, conn: sqlite3.Connection
) -> None:
    """Guards `_key`: without it, the "not cached" assertions below could
    pass vacuously by looking up the wrong key."""
    cache = InMemoryNarrationCache()
    narrator = _ScriptedNarrator([REAL_NARRATION])

    out = _ask(route, conn, cache, narrator)

    assert out == NarrationOut(text=REAL_NARRATION, contested=False, cached=False)
    assert cache.get(_key(route, conn)) == CachedNarration(text=REAL_NARRATION, contested=False)


@pytest.mark.parametrize("route", ROUTES)
def test_rejected_submission_fallback_is_served_uncached_and_not_stored(
    route: str, conn: sqlite3.Connection
) -> None:
    cache = InMemoryNarrationCache()
    narrator = _ScriptedNarrator([REJECTED_NARRATION, REJECTED_NARRATION])

    out = _ask(route, conn, cache, narrator)

    assert out == NarrationOut(text=_fallback_text(route, conn), contested=False, cached=False)
    assert len(narrator.calls) == 2
    assert cache.get(_key(route, conn)) is None


@pytest.mark.parametrize("route", ROUTES)
def test_transport_error_fallback_is_served_uncached_and_not_stored(
    route: str, conn: sqlite3.Connection
) -> None:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    cache = InMemoryNarrationCache()
    narrator = _ScriptedNarrator(error=anthropic.APIConnectionError(request=request))

    out = _ask(route, conn, cache, narrator)

    assert out == NarrationOut(text=_fallback_text(route, conn), contested=False, cached=False)
    assert cache.get(_key(route, conn)) is None


@pytest.mark.parametrize("route", ROUTES)
def test_request_after_a_fallback_asks_the_narrator_again(
    route: str, conn: sqlite3.Connection
) -> None:
    """The second request must reach the narrator because nothing was
    cached, not merely because the legacy fallback-row miss (tested below)
    happens to catch a fallback that was wrongly cached. Hence the empty-cache
    check between the two requests."""
    cache = InMemoryNarrationCache()
    narrator = _ScriptedNarrator([REJECTED_NARRATION, REJECTED_NARRATION, REAL_NARRATION])

    first = _ask(route, conn, cache, narrator)

    assert first == NarrationOut(text=_fallback_text(route, conn), contested=False, cached=False)
    assert cache.get(_key(route, conn)) is None

    second = _ask(route, conn, cache, narrator)

    assert second == NarrationOut(text=REAL_NARRATION, contested=False, cached=False)
    assert len(narrator.calls) == 3
    assert cache.get(_key(route, conn)) == CachedNarration(text=REAL_NARRATION, contested=False)


@pytest.mark.parametrize("route", ROUTES)
def test_legacy_cached_fallback_is_a_miss_and_is_overwritten_by_a_real_narration(
    route: str, conn: sqlite3.Connection
) -> None:
    cache = InMemoryNarrationCache()
    cache.set(_key(route, conn), CachedNarration(text=_fallback_text(route, conn), contested=False))
    narrator = _ScriptedNarrator([REAL_NARRATION])

    first = _ask(route, conn, cache, narrator)

    assert first == NarrationOut(text=REAL_NARRATION, contested=False, cached=False)
    assert len(narrator.calls) == 1
    assert cache.get(_key(route, conn)) == CachedNarration(text=REAL_NARRATION, contested=False)

    second = _ask(route, conn, cache, narrator)

    assert second == NarrationOut(text=REAL_NARRATION, contested=False, cached=True)
    assert len(narrator.calls) == 1


@pytest.mark.parametrize("route", ROUTES)
def test_legacy_cached_fallback_that_fails_again_is_served_uncached(
    route: str, conn: sqlite3.Connection
) -> None:
    """The accepted #65 trade-off: a key that keeps being rejected costs up
    to two narrator calls per request instead of being pinned to the fallback."""
    fallback = _fallback_text(route, conn)
    cache = InMemoryNarrationCache()
    cache.set(_key(route, conn), CachedNarration(text=fallback, contested=False))
    narrator = _ScriptedNarrator([REJECTED_NARRATION, REJECTED_NARRATION])

    out = _ask(route, conn, cache, narrator)

    assert out == NarrationOut(text=fallback, contested=False, cached=False)
    assert len(narrator.calls) == 2


@pytest.mark.parametrize("route", ROUTES)
def test_real_cached_narration_is_still_served_without_a_narrator_call(
    route: str, conn: sqlite3.Connection
) -> None:
    cache = InMemoryNarrationCache()
    cache.set(
        _key(route, conn), CachedNarration(text="A real, earlier narration.", contested=False)
    )
    narrator = _ScriptedNarrator([])

    out = _ask(route, conn, cache, narrator)

    assert out == NarrationOut(text="A real, earlier narration.", contested=False, cached=True)
    assert narrator.calls == []
