"""Post-generation grounding check (issue #4 / Architecture Brief §4.3).

Every number-like token and known-team-name mention in the persona's
generated response must be a subset of what's already in the fact block
(the exact evidence JSON given to Claude) -- nothing invented, nothing
rounded differently. `find_ungrounded_tokens` extracts both kinds of token
from the response and returns whichever are *not* also present in the fact
block, so the caller (`api.persona.narrate`) can retry with that specific
feedback.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

# No leading `-?`: records and scores in this domain (e.g. "13-0", "41-38")
# use a hyphen as a separator, not a negative sign, and treating it as one
# would misparse "13-0" as the tokens "13" and "-0" instead of "13" and "0".
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


def find_ungrounded_tokens(
    response_text: str, fact_block_json: str, known_team_names: Iterable[str]
) -> list[str]:
    """Return the sorted, de-duplicated set of number-like tokens and
    known-team-name mentions in `response_text` that do not also appear in
    `fact_block_json`. An empty list means the response is fully grounded.
    """
    response_numbers = set(_NUMBER_RE.findall(response_text))
    fact_numbers = set(_NUMBER_RE.findall(fact_block_json))
    ungrounded_numbers = response_numbers - fact_numbers

    names = [name for name in known_team_names if name]
    mentioned_teams = {name for name in names if name in response_text}
    fact_teams = {name for name in names if name in fact_block_json}
    ungrounded_teams = mentioned_teams - fact_teams

    return sorted(ungrounded_numbers | ungrounded_teams)
