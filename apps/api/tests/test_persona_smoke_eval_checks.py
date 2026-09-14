"""Offline unit tests for the persona smoke eval's check functions (issue #109).

`test_persona_smoke_eval.py`'s real-key test is skipped wherever
`ANTHROPIC_API_KEY` is unset, CI included, so on its own nothing CI runs would
ever exercise the checks that eval relies on. This module runs in the normal
`pytest -q` step: no API key, no network. It calls `_section_8_violations` and
its helpers against the real champion fact blocks built from the committed
fixture (through the shared `client` fixture and its stub narrator), with
synthetic narrations: one per property that must be flagged, and legitimate
ones that must pass.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from test_persona_smoke_eval import (
    _banned_hits,
    _section_8_violations,
    _sentence_count,
)

from api.models import TeamCaseOut
from api.persona.fallback import team_case_fallback_text


def _case(client: TestClient, year: int) -> TeamCaseOut:
    response = client.post("/api/verdict/champion", json={"year": year})
    assert response.status_code == 200, response.text
    return TeamCaseOut.model_validate(response.json()["evidence"])


def _catalog(client: TestClient) -> list[str]:
    response = client.get("/api/teams", params={"sport": "cfb"})
    assert response.status_code == 200, response.text
    names: list[str] = response.json()["teams"]
    return names


def _violations(
    client: TestClient, year: int, text: str, *, model_outputs: list[str] | None = None
) -> list[str]:
    """A narration that the narrator itself produced, unless `model_outputs`
    says otherwise."""
    outputs = [text] if model_outputs is None else model_outputs
    return _section_8_violations(
        year=year,
        text=text,
        case=_case(client, year),
        catalog=_catalog(client),
        claude_calls=len(outputs),
        model_outputs=outputs,
    )


def _labelled(violations: list[str], label: str) -> list[str]:
    return [violation for violation in violations if violation.startswith(label)]


# ---------------------------------------------------------------------------
# legitimate narrations pass every check
# ---------------------------------------------------------------------------

LEGITIMATE = [
    pytest.param(
        2005,
        "No. 1 Texas went 13-0 in 2005 vs. everybody, and that 5.04 rating says it all. "
        "They beat USC 41-38 and Texas Tech 52-17. I cannot believe how good that was. "
        "That's a machine.",
        id="2005-no1-vs-display-rating-homograph-opponent",
    ),
    pytest.param(
        2019,
        "No. 1 LSU went 15-0 in 2019 with a Keener rating of 4.78, or 0.0048 before the "
        "site scales it. Sonny Dykes would tip his cap. That's a machine.",
        id="2019-display-and-rounded-rating-coach-surname",
    ),
    pytest.param(
        2003,
        "LSU went 13-1 in 2003, and yeah, Florida got them 7-19. St. Louis can argue all "
        "it wants, but the numbers don't lie.",
        id="2003-st-abbreviation-loss-score",
    ),
    pytest.param(
        2017,
        # Served verbatim by the real narrator in round 2 of the #109 runs.
        "Look, I know the human polls had some drama about this one, but the numbers "
        "don't lie — Alabama's your #1 in 2017 with that 13-1 record and a rating of "
        "4.84. Yeah, they took one on the chin to Auburn 14-26, but then they went out "
        "and demolished the postseason: beat Clemson 24-6 and snuck past Georgia 26-23 "
        "in the championship game to prove they belonged on top. That's not a fluke, "
        "that's a team that shows up when it matters most.",
        id="2017-real-served-narration",
    ),
]


@pytest.mark.parametrize(("year", "text"), LEGITIMATE)
def test_legitimate_narration_passes_every_check(client: TestClient, year: int, text: str) -> None:
    assert _violations(client, year, text) == []


# ---------------------------------------------------------------------------
# B1: check 1 must not accept a team whose name merely contains the #1's
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("year", "text"),
    [
        (2005, "Texas Tech ran the table in 2005 and nobody could touch them. That's a machine."),
        (2001, "Miami (OH) went 12-0 in 2001 and nobody could touch them."),
        (2017, "Alabama State went 13-1 in 2017. That's a machine."),
    ],
)
def test_check_1_rejects_a_longer_team_name_containing_the_number_one(
    client: TestClient, year: int, text: str
) -> None:
    assert _labelled(_violations(client, year, text), "correct-#1"), text


def test_check_1_accepts_the_number_one_alongside_a_homograph(client: TestClient) -> None:
    text = "Texas went 13-0 in 2005 and handled Texas Tech 52-17. That's a machine."
    assert _violations(client, 2005, text) == []


# ---------------------------------------------------------------------------
# B2: check 5 is structural -- the served text must be a narrator output
# ---------------------------------------------------------------------------


def test_exact_fallback_text_is_flagged(client: TestClient) -> None:
    fallback = team_case_fallback_text(_case(client, 2005))
    violations = _labelled(
        _violations(client, 2005, fallback, model_outputs=["Texas went 13-0 in 2005."]),
        "not-fallback",
    )
    assert violations
    assert "#107" in violations[0]
    assert "matches team_case_fallback_text: True" in violations[0]


def test_a_drifted_fallback_that_no_narrator_produced_is_flagged(client: TestClient) -> None:
    drifted = team_case_fallback_text(_case(client, 2005)).replace("speak for", "speak loudly for")
    violations = _labelled(
        _violations(client, 2005, drifted, model_outputs=["Texas went 13-0 in 2005."]),
        "not-fallback",
    )
    assert violations
    assert "matches team_case_fallback_text: False" in violations[0]


def test_served_text_from_the_retry_is_a_narrator_output(client: TestClient) -> None:
    retry = "Texas went 13-0 in 2005. That's a machine."
    violations = _violations(client, 2005, retry, model_outputs=["Texas went 99-0.", retry])
    assert violations == []


# ---------------------------------------------------------------------------
# B3: the sentence splitter
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("No. 1 Texas went 13-0 in 2005. That's a machine.", 2),
        ("Texas went 13-0 in 2005 vs. USC and all. That's a machine.", 2),
        ("Texas went 13-0 in 2005. St. John's could not. That's a machine.", 3),
        ("They filled U.S. Bank Stadium. That's a machine.", 2),
        ("Texas... 13-0 in 2005. That's a machine.", 2),
        ("Texas went through USC -- USC! -- 41-38 in 2005. That's a machine.", 2),
        ("Texas went 13-0 in 2005. They beat USC 41-38! Who's next? Nobody.", 4),
        ("", 0),
    ],
)
def test_sentence_count(text: str, expected: int) -> None:
    assert _sentence_count(text) == expected


def test_four_real_sentences_starting_no_1_are_within_the_length_bound(
    client: TestClient,
) -> None:
    text = "No. 1 Texas went 13-0 in 2005. They beat USC 41-38. That's a machine. Nobody close."
    assert _labelled(_violations(client, 2005, text), "length") == []


def test_five_sentences_are_over_the_length_bound(client: TestClient) -> None:
    text = "Texas went 13-0 in 2005. " * 5
    assert _labelled(_violations(client, 2005, text), "length")


# ---------------------------------------------------------------------------
# B4: banned words -- real hits, no false positives on bar talk or names
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "I cannot believe Texas went 13-0",
        "Sonny Dykes had no answer",
        "Kike Hernandez was in the stands",
        "a cocky, spicy, hell of a season",
        "damn good",
        "Scunthorpe, Hancock and Spicer",
        "I can't root against them",
    ],
)
def test_banned_words_do_not_flag_ordinary_talk_or_names(text: str) -> None:
    assert _banned_hits(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "As an AI, I don't have a team.",
        "I'm just an AI.",
        "I’m an AI.",
        "I am an AI.",
        "As a large language model",
        "I cannot help with that.",
        "I cannot provide opinions.",
        "I'm not able to pick a side.",
        "that was bullshit",
        "fucking",
        "motherfucker",
        "shitty",
        "bitch",
        "asshole",
        "bastard",
        "faggot",
        "retard",
        "nigger",
        "tranny",
        "wetback",
        "spic",
        "kike",
        "dyke",
    ],
)
def test_banned_words_flag_profanity_slurs_and_ai_disclaimers(text: str) -> None:
    assert _banned_hits(text), text


def test_no_catalog_team_name_is_a_banned_word(client: TestClient) -> None:
    assert [name for name in _catalog(client) if _banned_hits(name)] == []


# ---------------------------------------------------------------------------
# 2a / 2b / 2c grounding
# ---------------------------------------------------------------------------


def test_2a_flags_a_rating_one_hundredth_off_its_display(client: TestClient) -> None:
    text = "LSU went 15-0 in 2019 with a Keener rating of 4.79. That's a machine."
    violations = _labelled(_violations(client, 2019, text), "grounded: numbers")
    assert violations and "4.79" in violations[0]


def test_2b_flags_a_real_team_that_is_not_in_the_fact_block(client: TestClient) -> None:
    text = "Texas went 13-0 in 2005 and made Oregon look slow. That's a machine."
    violations = _labelled(_violations(client, 2005, text), "grounded: teams")
    assert violations and "Oregon" in violations[0]


def test_2c_flags_a_score_from_a_different_game(client: TestClient) -> None:
    # 42-25 is LSU-Clemson 2019. Both numbers are 2005 fact-block tokens, so
    # only the score check can catch it.
    text = "Texas went 13-0 in 2005 and beat USC 42-25. That's a machine."
    violations = _violations(client, 2005, text)
    assert _labelled(violations, "grounded: numbers") == []
    scores = _labelled(violations, "grounded: scores/records")
    assert scores and "42-25" in scores[0]


@pytest.mark.parametrize(
    ("year", "text", "claim"),
    [
        (2005, "Texas went 0-13 in 2005. That's a machine.", "0-13"),
        (2003, "LSU went 1-13 in 2003. That's a machine.", "1-13"),
        (2005, "Texas went 0-13-0 in 2005. That's a machine.", "0-13-0"),
    ],
)
def test_n1_2c_flags_a_reversed_record(
    client: TestClient, year: int, text: str, claim: str
) -> None:
    scores = _labelled(_violations(client, year, text), "grounded: scores/records")
    assert scores and claim in scores[0]


def test_2c_leaves_game_score_order_to_production(client: TestClient) -> None:
    # Score order is production's rule-5 relational check (#26); this smoke
    # check only asks whether the game happened.
    text = "Texas went 13-0 in 2005 and beat USC 38-41. That's a machine."
    assert _labelled(_violations(client, 2005, text), "grounded: scores/records") == []
