"""Dollars: what each recorded call cost, and a worst case before a run
(issue #463).

**The price table** is per million tokens, input / output, for the three
narrator models and the grader, as published when #463 was written. Cache
writes cost 1.25x the input rate (5-minute writes) and cache reads 0.1x;
`input_tokens` in the API's usage is the uncached input only, so the three
input counts never overlap. `claude-haiku-5-5` has two rate cards chosen by
prompt length: $0.10 / $0.50 up to 100K prompt tokens (every narration here
is far below that), $0.50 / $2.50 past it. Update the table, not the
arithmetic, when a price changes.

**The worst case** (`--dry-run`) is priced from `max_tokens`, since nothing
has been called yet: each narration is a first call that spends the whole
narrator `max_tokens`, a retry that replays all of it plus the longest
feedback `api.persona.narrate` sends (`MAX_FEEDBACK_CHARS`) and spends it
again, and a grader call that spends `GRADER_MAX_TOKENS`. Input tokens are
estimated from characters at `WORST_CASE_CHARS_PER_TOKEN`, an overestimate
for English prose and JSON alike (about 4 and 3 characters a token), and
no cache discount is assumed. A real run costs a small fraction of it.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from api.persona.claude_client import HAIKU_4_5, HAIKU_5_5, SONNET_5_5, TokenUsage
from api.persona.narrate import MAX_FEEDBACK_CHARS
from persona_eval_harness.grader import GRADER_MAX_TOKENS, GRADER_MODEL

PER_MILLION: Final = 1_000_000
CACHE_WRITE_MULTIPLIER: Final = 1.25
CACHE_READ_MULTIPLIER: Final = 0.1
WORST_CASE_CHARS_PER_TOKEN: Final = 2.5


@dataclass(frozen=True)
class Price:
    """Dollars per million tokens."""

    input: float
    output: float


PRICES: Final[Mapping[str, Price]] = {
    HAIKU_4_5: Price(input=1.0, output=5.0),
    HAIKU_5_5: Price(input=0.10, output=0.50),
    SONNET_5_5: Price(input=2.0, output=10.0),
    GRADER_MODEL: Price(input=5.0, output=25.0),
}

# A model whose rate rises past a prompt length: (prompt tokens up to which
# `PRICES` applies, the price beyond it).
LONG_PROMPT_PRICES: Final[Mapping[str, tuple[int, Price]]] = {
    HAIKU_5_5: (100_000, Price(input=0.50, output=2.50)),
}


def price_for(model: str, prompt_tokens: int) -> Price:
    if model not in PRICES:
        raise ValueError(f"no price for {model!r}; the priced models are {sorted(PRICES)}")
    long = LONG_PROMPT_PRICES.get(model)
    if long is not None and prompt_tokens > long[0]:
        return long[1]
    return PRICES[model]


def call_cost_usd(model: str, usage: TokenUsage) -> float:
    """One call's dollars on `model`."""
    prompt_tokens = (
        usage.input_tokens + usage.cache_creation_input_tokens + usage.cache_read_input_tokens
    )
    price = price_for(model, prompt_tokens)
    input_cost = price.input * (
        usage.input_tokens
        + CACHE_WRITE_MULTIPLIER * usage.cache_creation_input_tokens
        + CACHE_READ_MULTIPLIER * usage.cache_read_input_tokens
    )
    return (input_cost + price.output * usage.output_tokens) / PER_MILLION


def calls_cost_usd(model: str, usages: tuple[TokenUsage | None, ...]) -> float | None:
    """The sum over `usages`, or None when any call carried no usage (a fake
    narrator's reply, or a call that raised): a partial sum would read as a
    cheap narration."""
    if any(usage is None for usage in usages):
        return None
    return sum(call_cost_usd(model, usage) for usage in usages if usage is not None)


def estimate_tokens(chars: int) -> int:
    """A worst-case token count for `chars` characters."""
    return math.ceil(chars / WORST_CASE_CHARS_PER_TOKEN)


def _uncached(input_tokens: int, output_tokens: int) -> TokenUsage:
    return TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )


def worst_case_narration_usd(
    *,
    narrator_model: str,
    narrator_max_tokens: int,
    narrator_input_chars: int,
    grader_input_chars: int,
) -> tuple[float, float]:
    """The most one narration can cost, (narrator, grader): a first call and
    a retry each spending `narrator_max_tokens`, and one grader call spending
    `GRADER_MAX_TOKENS` (module docstring)."""
    first_input = estimate_tokens(narrator_input_chars)
    retry_input = first_input + narrator_max_tokens + estimate_tokens(MAX_FEEDBACK_CHARS)
    narrator = call_cost_usd(
        narrator_model, _uncached(first_input, narrator_max_tokens)
    ) + call_cost_usd(narrator_model, _uncached(retry_input, narrator_max_tokens))
    grader = call_cost_usd(
        GRADER_MODEL, _uncached(estimate_tokens(grader_input_chars), GRADER_MAX_TOKENS)
    )
    return narrator, grader
