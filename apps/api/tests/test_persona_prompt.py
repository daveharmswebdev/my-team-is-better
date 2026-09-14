"""Failing-first tests for `api.persona.prompt` (issue #4).

The persona system prompt text is coordinator-authored and verbatim per
this project's CLAUDE.md routing rules on persona voice/tone -- these tests
pin the load-bearing rules/phrases (grounding rules 1-4, the PG-13
constraint, the worked examples) rather than diffing the whole string, so a
future accidental rewrite of the *voice* fails loudly without this test
suite being brittle to incidental whitespace changes.
"""

from __future__ import annotations



from api.persona.prompt import build_system_prompt, build_user_message


def test_prompt_with_user_team_names_them_as_the_persona_s_team() -> None:
    prompt = build_system_prompt("Texas")

    assert "Texas" in prompt
    assert "rooting hard" in prompt


def test_prompt_without_user_team_has_no_placeholder_left_unfilled() -> None:
    prompt = build_system_prompt(None)

    assert "{user_team}" not in prompt
    assert "loud hype man for whoever" in prompt


def test_prompt_carries_the_non_negotiable_grounding_rules_verbatim() -> None:
    prompt = build_system_prompt("Texas")

    assert "MUST appear in the" in prompt
    assert "FACT BLOCK" in prompt
    assert "Never contradict or hedge on who the FACT BLOCK says is ranked #1" in prompt
    assert "PG-13 rivalry trash talk" in prompt
    assert "No slurs, no profanity" in prompt
    assert "Two or three sentences" in prompt


_RULE_1_WITH_RATING_ROUNDING = (
    "1. Every team name, record, score, and number you say MUST appear in the\n"
    "   FACT BLOCK. Never invent, round, or guess at a stat that isn't there.\n"
    "   Ratings are the only exception: a `rating` or `opponent_rating` may be\n"
    "   rounded to fewer decimal places (an Elo rating of 1933.19 can be said\n"
    "   as 1933).\n"
)


def test_rule_1_permits_rounding_ratings_and_nothing_else() -> None:
    # issue #162: the grounding checker accepts a rounded `rating` or
    # `opponent_rating`, so the prompt has to say so -- and only for those
    # two ratings, not any stat.
    for user_team in ("Texas", None):
        prompt = build_system_prompt(user_team)

        assert _RULE_1_WITH_RATING_ROUNDING in prompt
        assert "round differently" not in prompt


def test_rule_1_does_not_ask_the_narrator_to_compute_a_display_value() -> None:
    # issue #180: persona-v5 told the narrator how the site displays a Keener
    # rating (x1000 to 2 decimals, with a worked example). claude-haiku-4-5
    # then did that arithmetic itself and got it wrong ("5.47" for LSU 2003's
    # 4.73) on the first attempt and on the retry, so grounding served the
    # fallback. Rule 1 now goes straight from #162's rounding exception to
    # rule 2, and no scaled figure or worked display example is left in the
    # prompt. Grounding still accepts a correctly quoted display value (#165).
    for user_team in ("Texas", None):
        prompt = build_system_prompt(user_team)

        assert "   as 1933).\n2. Never contradict" in prompt
        assert "the way the site displays it" not in prompt
        assert "multiplied by" not in prompt
        assert "5.04" not in prompt
        assert "0.005044" not in prompt


def test_prompt_includes_the_worked_examples() -> None:
    prompt = build_system_prompt("Texas")

    assert "13-0 and had the guts to go through USC" in prompt
    assert "invents a loss that never happened" in prompt


def test_prompt_pins_the_score_order_convention() -> None:
    # issue #26: the relational grounding check can only verify score order
    # if the persona is instructed to always state `team_score` before
    # `opponent_score` -- this rule is what makes that checkable.
    prompt = build_system_prompt("Texas")

    assert "`team_score` number first" in prompt
    assert "A swapped order is exactly as wrong as an invented" in prompt


def test_user_message_embeds_fact_block_json_verbatim() -> None:
    fact_block_json = '{"team_name": "Texas", "year": 2005}'

    message = build_user_message(fact_block_json, contested=False)

    assert fact_block_json in message


def test_user_message_discloses_contested_true() -> None:
    message = build_user_message("{}", contested=True)

    assert "contested" in message.lower()
    assert "true" in message.lower()


def test_user_message_discloses_contested_false() -> None:
    message = build_user_message("{}", contested=False)

    assert "false" in message.lower()
