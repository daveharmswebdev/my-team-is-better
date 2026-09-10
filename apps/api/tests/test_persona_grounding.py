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


# ---------------------------------------------------------------------------
# issue #26: relational (order-aware, opponent-aware) grounding. Individual
# token membership is not enough -- "34", "31", and "Texas" can each appear
# somewhere in the fact block without "Texas 34-31" ever being a true fact.
# ---------------------------------------------------------------------------

VANDY_FACT_BLOCK = (
    '{"team_name": "Vanderbilt", "year": 2025, "wins": 10, "losses": 3, '
    '"rank": 21, "games": [], '
    '"quality_wins": ['
    '{"opponent_name": "Texas", "team_score": 31, "opponent_score": 34, "result": "L"}, '
    '{"opponent_name": "LSU", "team_score": 31, "opponent_score": 24, "result": "W"}, '
    '{"opponent_name": "Tennessee", "team_score": 45, "opponent_score": 24, "result": "W"}'
    '], "worst_loss": null}'
)
VANDY_KNOWN_TEAMS = ["Vanderbilt", "Texas", "LSU", "Tennessee", "Iowa"]


def test_swapped_score_order_for_real_opponent_is_flagged_the_issue_26_regression() -> None:
    # Texas actually lost 31-34 (team_score first); the narration swapped
    # the digit order, which flips the implied result. LSU and Tennessee are
    # both stated correctly right next to Texas's mismatch and must NOT be
    # cross-contaminated by the nearest-neighbor pairing.
    response = (
        "Vanderbilt finished 10-3, and they beat ranked teams like Texas "
        "(34-31), LSU (31-24), and Tennessee (45-24) along the way."
    )

    mismatches = find_ungrounded_tokens(response, VANDY_FACT_BLOCK, VANDY_KNOWN_TEAMS)

    assert "Texas's score should be stated 31-34, not 34-31" in mismatches
    assert not any(m.startswith("LSU") for m in mismatches)
    assert not any(m.startswith("Tennessee") for m in mismatches)


def test_correctly_ordered_multi_game_sentence_is_not_flagged() -> None:
    response = (
        "Vanderbilt finished 10-3, and they beat ranked teams like LSU "
        "(31-24) and Tennessee (45-24), but Texas (31-34) got them."
    )

    mismatches = find_ungrounded_tokens(response, VANDY_FACT_BLOCK, VANDY_KNOWN_TEAMS)

    assert mismatches == []


def test_team_mentioned_with_no_nearby_score_pair_is_not_spuriously_flagged() -> None:
    response = "Vanderbilt had a great year, and honestly Texas gave them all they could handle."

    mismatches = find_ungrounded_tokens(response, VANDY_FACT_BLOCK, VANDY_KNOWN_TEAMS)

    assert mismatches == []


COMPARISON_FACT_BLOCK = (
    '{"year": 2025, '
    '"team_a": {"team_name": "Vanderbilt", "quality_wins": [], "worst_loss": null}, '
    '"team_b": {"team_name": "Texas", "quality_wins": [], "worst_loss": null}, '
    '"head_to_head": {"played": true, "meetings": ['
    '{"home_team": "Texas", "away_team": "Vanderbilt", '
    '"home_points": 34, "away_points": 31, "winner": "Texas"}'
    "]}, "
    '"common_opponents": ['
    '{"opponent_name": "LSU", "team_a_score": 31, "team_a_opponent_score": 24, '
    '"team_b_score": 20, "team_b_opponent_score": 17}'
    '], "rating_diff": 3.1, "verdict": "Texas"}'
)
COMPARISON_KNOWN_TEAMS = ["Vanderbilt", "Texas", "LSU"]


def test_head_to_head_meeting_swapped_order_is_flagged() -> None:
    response = "Texas (31-34) got the better of Vanderbilt in a real slugfest."

    mismatches = find_ungrounded_tokens(response, COMPARISON_FACT_BLOCK, COMPARISON_KNOWN_TEAMS)

    assert "Texas's score should be stated 34-31, not 31-34" in mismatches


def test_head_to_head_meeting_correct_order_is_not_flagged() -> None:
    response = "Texas (34-31) got the better of Vanderbilt in a real slugfest."

    mismatches = find_ungrounded_tokens(response, COMPARISON_FACT_BLOCK, COMPARISON_KNOWN_TEAMS)

    assert mismatches == []


def test_common_opponent_swapped_order_is_flagged() -> None:
    response = "Vanderbilt handled LSU (24-31) as a common opponent, for what it's worth."

    mismatches = find_ungrounded_tokens(response, COMPARISON_FACT_BLOCK, COMPARISON_KNOWN_TEAMS)

    assert "LSU 24-31" in mismatches


def test_common_opponent_correct_order_is_not_flagged() -> None:
    response = "Vanderbilt handled LSU (31-24) as a common opponent, for what it's worth."

    mismatches = find_ungrounded_tokens(response, COMPARISON_FACT_BLOCK, COMPARISON_KNOWN_TEAMS)

    assert mismatches == []


# ---------------------------------------------------------------------------
# issue #26 follow-up: nearest-neighbor-with-a-fixed-window missed realistic
# phrasing where the score isn't textually adjacent to the team name
# (Finding 1), and wrongly flagged the equally common "TeamA beat TeamB
# score" construction where the nearest name is textually close but not who
# the score actually belongs to (Finding 2). Sentence-scoped, parenthetical-
# vs-bare matching (see grounding.py's module docstring) fixes both without
# regressing the original three-team case above.
# ---------------------------------------------------------------------------


def test_swapped_score_far_from_team_name_is_now_flagged_finding_1() -> None:
    # The exact issue #26 bug (a swapped score for a real opponent), just
    # phrased with the score ~70 characters from "Texas" instead of
    # immediately next to it in a parenthetical -- past the old fixed
    # proximity window, so it used to fall through to plain membership
    # checking and go uncaught.
    response = (
        "Vanderbilt handled Texas pretty well for most of the game, but when "
        "the final whistle blew it was 34-31."
    )

    mismatches = find_ungrounded_tokens(response, VANDY_FACT_BLOCK, VANDY_KNOWN_TEAMS)

    assert mismatches != []


def test_team_a_beat_team_b_score_construction_is_not_falsely_flagged_finding_2() -> None:
    # "Texas beat Vanderbilt 34-31" is 100% accurate (Texas's own score, 34,
    # stated first per rule 5) -- but "Vanderbilt" is textually closer to
    # "34-31" than "Texas" is, so naive nearest-neighbor attribution used to
    # check it against Vanderbilt's tuples instead and wrongly flag it.
    response = "Texas beat Vanderbilt 34-31 in a real slugfest."

    mismatches = find_ungrounded_tokens(response, COMPARISON_FACT_BLOCK, COMPARISON_KNOWN_TEAMS)

    assert mismatches == []


def test_relational_mismatch_message_states_the_correct_order_explicitly() -> None:
    # Finding 3: the feedback string for a relational mismatch must name
    # the correct order, not just repeat the wrong one -- otherwise a retry
    # has nothing concrete to self-correct from.
    response = "Texas (31-34) got the better of Vanderbilt in a real slugfest."

    mismatches = find_ungrounded_tokens(response, COMPARISON_FACT_BLOCK, COMPARISON_KNOWN_TEAMS)

    assert any("should be stated 34-31" in m and "not 31-34" in m for m in mismatches)
