"""Failing-first tests for `api.persona.grounding` (issue #4 / Architecture
Brief §4.3): every number-like token and known-team-name mention in the
persona's response must be a subset of what's in the fact block.
"""

from __future__ import annotations

from api.persona.grounding import find_ungrounded_tokens

FACT_BLOCK = (
    '{"team_name": "Texas", "year": 2005, "wins": 13, "losses": 0, "rank": 1, '
    '"quality_wins": [{"opponent_name": "USC", "team_score": 41, '
    '"opponent_score": 38}]}'
)
KNOWN_TEAMS = ["Texas", "USC", "Alabama", "Oklahoma"]


def test_fully_grounded_response_has_no_mismatches() -> None:
    response = "Texas ran the table at 13-0 in 2005 and beat USC 41-38."

    assert find_ungrounded_tokens(response, FACT_BLOCK, KNOWN_TEAMS) == []


def test_invented_number_is_flagged() -> None:
    # "14" doesn't appear anywhere in FACT_BLOCK's number tokens
    # (2005, 13, 0, 1, 41, 38) -- a clean fabrication to catch.
    response = "Texas went 13-0 and stomped USC by 14 points, easy."

    mismatches = find_ungrounded_tokens(response, FACT_BLOCK, KNOWN_TEAMS)

    assert "14" in mismatches


def test_mentioned_team_not_in_fact_block_is_flagged() -> None:
    response = "Texas would have smoked Alabama too, probably."

    mismatches = find_ungrounded_tokens(response, FACT_BLOCK, KNOWN_TEAMS)

    assert "Alabama" in mismatches


def test_team_mentioned_and_present_in_fact_block_is_not_flagged() -> None:
    response = "Texas beat USC, plain and simple."

    mismatches = find_ungrounded_tokens(response, FACT_BLOCK, KNOWN_TEAMS)

    assert mismatches == []


def test_number_present_in_fact_block_is_not_flagged() -> None:
    response = "That 2005 Texas team went 13-0, ranked #1, with a 41-38 win over USC."

    mismatches = find_ungrounded_tokens(response, FACT_BLOCK, KNOWN_TEAMS)

    assert mismatches == []
