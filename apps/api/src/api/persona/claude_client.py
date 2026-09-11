"""Thin, synchronous wrapper around the `anthropic` SDK for issue #4's
persona narration call.

`Narrator` is the seam tests mock -- every CI-safe unit test injects a fake
implementing this `Protocol` instead of `ClaudeNarrator`, so the test suite
never hits the real Anthropic API. `ClaudeNarrator` is the real
implementation, used in production and in the one gated integration test.

`StubNarrator` (issue #39's groundwork) is a production-code counterpart to
the private `_StubNarrator` test double in `apps/api/tests/conftest.py`: a
real booted `uvicorn` process (not pytest) needs to construct a `Narrator`
too, when `APP_TEST_MODE=1` (see `api.deps.get_narrator`), so this can't
live test-only. It always returns a fixed string with no numbers and no
proper-noun team names, so it always passes the grounding check in
`api.persona.grounding` regardless of the fact block, and never needs a
retry.
"""

from __future__ import annotations

from typing import Protocol

import anthropic

# Exact model id per issue #4's brief -- verified against the current model
# catalog this session, no date suffix.
MODEL = "claude-haiku-4-5"

# Deliberately small: the persona narration is 2-3 sentences by design, no
# reason to allow a runaway generation.
MAX_TOKENS = 400


class Narrator(Protocol):
    def complete(self, *, system: str, messages: list[dict[str, str]]) -> str: ...


class ClaudeNarrator:
    """Synchronous by design -- the `/api/verdict/*` routes are sync `def`
    FastAPI routes (FastAPI dispatches them onto a threadpool), so a
    blocking SDK call here is consistent with the existing pattern; no
    reason to introduce async just for this one call. `thinking` is
    intentionally omitted (Haiku 4.5 needs no extended thinking for a
    short narration task; omitting it is the documented default of no
    thinking).
    """

    def __init__(self, client: anthropic.Anthropic | None = None) -> None:
        # No explicit key -- resolves ANTHROPIC_API_KEY from the real
        # environment the normal way (issue #4's brief: never read the raw
        # value out of `.env` and pass it around by hand).
        self._client = client or anthropic.Anthropic()

    def complete(self, *, system: str, messages: list[dict[str, str]]) -> str:
        response = self._client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=messages,  # type: ignore[arg-type]
        )
        text_parts = [block.text for block in response.content if block.type == "text"]
        return "".join(text_parts).strip()


class StubNarrator:
    """`APP_TEST_MODE=1` production stand-in for `ClaudeNarrator` -- never
    calls the real Anthropic API, never needs `ANTHROPIC_API_KEY`.
    """

    def complete(self, *, system: str, messages: list[dict[str, str]]) -> str:
        return "Solid case, no notes."
