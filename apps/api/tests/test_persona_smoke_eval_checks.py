"""Offline unit tests for the persona smoke eval's judge, properties and
measurements (issues #109 and #293).

`test_persona_smoke_eval.py`'s real-key tests are skipped wherever
`ANTHROPIC_API_KEY` is unset, CI included, so on their own nothing CI runs
would ever exercise what that eval relies on. This module runs in the normal
`pytest -q` step: no API key, no network, never a Claude call. It tests
`tests/fixtures/persona_eval.py` on the production fact blocks built from the
committed fixture (`tests/fixtures/claim_blocks.py`), with recorded
`submit_narration` calls written by hand:

- **The judge** (§8 properties 2 and 5). Since #293 the eval judges grounding
  with the production claim validator, `api.persona.claims.check_and_render`,
  re-run over every recorded tool call against the fact block that call
  carried. These tests pin both directions: a valid call whose rendering is
  the served text passes, and a rejected call, a missing tool call, served
  text that differs from the rendering, and the fallback text are each
  flagged. The planted-invalid canary is rejected on every golden year's
  real champion fact block, which is what keeps the live eval from going
  vacuous if the validator ever stops rejecting things.
- **Properties 1, 3 and 4** (correct #1 named, length, banned words): their
  legitimate and violating probes.
- **The measurements**, which never fail a live test: the timing/venue
  detector (it flags each phrase known from #291's live runs and #200's spike,
  and nothing on raw text whose only when/where content is placeholders), the
  ambiguous-when flag, the lowercase block-team rejection classifier, and the
  arithmetic of the run summary, including a run with no narrations.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from fastapi.testclient import TestClient
from fixtures.claim_blocks import cfb_catalog, cfb_team_case_block
from fixtures.narrator_fake import FakeNarrator
from fixtures.persona_eval import (
    MAX_CHARACTERS,
    EvalSummary,
    JudgedCall,
    Judgement,
    NarrationRecord,
    RecordedCall,
    RecordingNarrator,
    ServedBy,
    TimingVenueFlag,
    ambiguous_when_sentences,
    banned_hits,
    build_record,
    fact_block_from_user_turn,
    format_record,
    format_summary,
    is_lowercase_block_team_error,
    judge_narration,
    judge_planted_invalid,
    length_violations,
    named_team_violations,
    section_8_violations,
    sentence_count,
    summarize,
    timing_venue_flags,
)
from test_persona_smoke_eval import (
    EXPECTED_KEENER_NUMBER_ONE,
    TEAM_CASE_TEAM,
    TEAM_CASE_YEAR,
)

from api.config import PROMPT_VERSION
from api.models import TeamCaseOut
from api.persona.claims import GROUNDING_VERSION, check_and_render
from api.persona.claude_client import NarratorReply, tool_reply
from api.persona.fallback import team_case_fallback_text
from api.persona.prompt import build_user_message
from api.persona.service import team_case_fact_block_json
from api.repositories.teams import TeamRecord

TEXAS = "Texas"
TEXAS_YEAR = 2005

# The persona prompt's own GOOD example (persona-v11) on the real 2005 Texas block.
GOOD_TEXAS_INPUT: dict[str, object] = {
    "text": (
        "Look at {rec} in {yr}: they ran the table, and they went through USC — USC! — "
        "{g1} {w1} to prove it. That's not luck, that's a machine."
    ),
    "claims": [
        {"id": "rec", "kind": "record", "team": "Texas"},
        {"id": "yr", "kind": "year"},
        {"id": "g1", "kind": "game_score", "team": "Texas", "opponent": "USC", "result": "W"},
        {"id": "w1", "kind": "when", "team": "Texas", "opponent": "USC", "result": "W"},
    ],
}
GOOD_TEXAS_RENDERED = (
    "Look at Texas 13-0 in 2005: they ran the table, and they went through USC — USC! — "
    "41-38 in the postseason to prove it. That's not luck, that's a machine."
)
TYPED_DIGIT_INPUT: dict[str, object] = {"text": "Texas went 13-0 in 2005.", "claims": []}

# #291 round 2's served 2013 Florida State narration (issue #293's evidence
# comment): Clemson was regular-season week 8, only Auburn was postseason.
FSU_AMBIGUOUS_INPUT: dict[str, object] = {
    "text": (
        "Florida State went {rec} in {yr}. They took down Clemson {g1} and Auburn {g2} {w1}, "
        "and nobody touched them."
    ),
    "claims": [
        {"id": "rec", "kind": "record", "team": "Florida State"},
        {"id": "yr", "kind": "year"},
        {
            "id": "g1",
            "kind": "game_score",
            "team": "Florida State",
            "opponent": "Clemson",
            "result": "W",
        },
        {
            "id": "g2",
            "kind": "game_score",
            "team": "Florida State",
            "opponent": "Auburn",
            "result": "W",
        },
        {"id": "w1", "kind": "when", "team": "Florida State", "opponent": "Auburn", "result": "W"},
    ],
}


@pytest.fixture(scope="module")
def catalog() -> tuple[TeamRecord, ...]:
    return cfb_catalog()


@pytest.fixture(scope="module")
def texas_block() -> str:
    return cfb_team_case_block(TEXAS_YEAR, TEXAS)


def _case(client: TestClient, year: int) -> TeamCaseOut:
    response = client.post("/api/verdict/champion", json={"year": year})
    assert response.status_code == 200, response.text
    return TeamCaseOut.model_validate(response.json()["evidence"])


def _catalog_names(client: TestClient) -> list[str]:
    response = client.get("/api/teams", params={"sport": "cfb"})
    assert response.status_code == 200, response.text
    names: list[str] = response.json()["teams"]
    return names


def _call(tool_input: object | None, block: str) -> RecordedCall:
    return RecordedCall(
        tool_input=tool_input,
        fact_block_json=block,
        stop_reason="tool_use" if tool_input is not None else "end_turn",
    )


def _labelled(violations: Sequence[str], label: str) -> list[str]:
    return [violation for violation in violations if violation.startswith(label)]


# ---------------------------------------------------------------------------
# the judge (properties 2 and 5)
# ---------------------------------------------------------------------------


def test_the_good_example_renders_as_pinned(
    texas_block: str, catalog: tuple[TeamRecord, ...]
) -> None:
    outcome = check_and_render(GOOD_TEXAS_INPUT, texas_block, catalog)
    assert outcome.errors == ()
    assert outcome.text == GOOD_TEXAS_RENDERED


def test_judge_accepts_a_valid_call_whose_rendering_is_the_served_text(
    texas_block: str, catalog: tuple[TeamRecord, ...]
) -> None:
    judgement = judge_narration(
        served_text=GOOD_TEXAS_RENDERED,
        calls=[_call(GOOD_TEXAS_INPUT, texas_block)],
        catalog=catalog,
        fallback_text="the fallback",
    )
    assert judgement.violations == ()
    assert judgement.served_by == "first"
    assert judgement.served_attempt is judgement.attempts[0]


def test_judge_accepts_the_retry_after_a_rejected_first_call(
    texas_block: str, catalog: tuple[TeamRecord, ...]
) -> None:
    judgement = judge_narration(
        served_text=GOOD_TEXAS_RENDERED,
        calls=[_call(TYPED_DIGIT_INPUT, texas_block), _call(GOOD_TEXAS_INPUT, texas_block)],
        catalog=catalog,
        fallback_text="the fallback",
    )
    assert judgement.violations == ()
    assert judgement.served_by == "retry"
    assert judgement.attempts[0].errors
    assert judgement.attempts[0].text is None


def test_judge_flags_a_rejected_call_served_as_its_raw_text(
    texas_block: str, catalog: tuple[TeamRecord, ...]
) -> None:
    judgement = judge_narration(
        served_text="Texas went 13-0 in 2005.",
        calls=[_call(TYPED_DIGIT_INPUT, texas_block)],
        catalog=catalog,
        fallback_text="the fallback",
    )
    assert _labelled(judgement.violations, "grounded")
    assert _labelled(judgement.violations, "not-fallback")
    assert judgement.served_by == "untraceable"
    assert judgement.served_attempt is None
    assert "types the number" in " ".join(judgement.violations)


def test_judge_flags_a_claim_the_block_does_not_back(
    texas_block: str, catalog: tuple[TeamRecord, ...]
) -> None:
    # A fabrication with no typed number: Texas beat USC 41-38, so a claim
    # that Texas lost it is rejected, and so is the text it would have served.
    fabricated: dict[str, object] = {
        "text": "Texas lost to USC {g1}.",
        "claims": [
            {"id": "g1", "kind": "game_score", "team": "Texas", "opponent": "USC", "result": "L"}
        ],
    }
    judgement = judge_narration(
        served_text="Texas lost to USC 41-38.",
        calls=[_call(fabricated, texas_block)],
        catalog=catalog,
        fallback_text="the fallback",
    )
    grounded = _labelled(judgement.violations, "grounded")
    assert grounded and "not L" in grounded[0]
    assert judgement.served_by == "untraceable"


def test_judge_flags_a_missing_tool_call(texas_block: str, catalog: tuple[TeamRecord, ...]) -> None:
    judgement = judge_narration(
        served_text="Texas ran the table.",
        calls=[_call(None, texas_block)],
        catalog=catalog,
        fallback_text="the fallback",
    )
    grounded = _labelled(judgement.violations, "grounded")
    assert grounded
    assert "no submit_narration call" in grounded[0]
    assert judgement.attempts[0].errors
    assert judgement.served_by == "untraceable"


def test_judge_flags_served_text_that_differs_from_the_rendering(
    texas_block: str, catalog: tuple[TeamRecord, ...]
) -> None:
    judgement = judge_narration(
        served_text=GOOD_TEXAS_RENDERED + " Nobody close.",
        calls=[_call(GOOD_TEXAS_INPUT, texas_block)],
        catalog=catalog,
        fallback_text="the fallback",
    )
    assert _labelled(judgement.violations, "grounded")
    assert judgement.served_by == "untraceable"


def test_judge_flags_the_raw_placeholder_text_of_a_valid_call(
    texas_block: str, catalog: tuple[TeamRecord, ...]
) -> None:
    raw = GOOD_TEXAS_INPUT["text"]
    assert isinstance(raw, str)
    judgement = judge_narration(
        served_text=raw,
        calls=[_call(GOOD_TEXAS_INPUT, texas_block)],
        catalog=catalog,
        fallback_text="the fallback",
    )
    assert _labelled(judgement.violations, "grounded")


def test_judge_flags_the_fallback_text(
    client: TestClient, texas_block: str, catalog: tuple[TeamRecord, ...]
) -> None:
    fallback = team_case_fallback_text(_case(client, TEXAS_YEAR))
    judgement = judge_narration(
        served_text=fallback,
        calls=[_call(TYPED_DIGIT_INPUT, texas_block), _call(None, texas_block)],
        catalog=catalog,
        fallback_text=fallback,
    )
    not_fallback = _labelled(judgement.violations, "not-fallback")
    assert not_fallback
    assert "fallback" in not_fallback[0]
    assert _labelled(judgement.violations, "grounded")
    assert judgement.served_by == "fallback"


def test_judge_flags_the_fallback_text_even_beside_a_valid_call(
    texas_block: str, catalog: tuple[TeamRecord, ...]
) -> None:
    judgement = judge_narration(
        served_text=GOOD_TEXAS_RENDERED,
        calls=[_call(GOOD_TEXAS_INPUT, texas_block)],
        catalog=catalog,
        fallback_text=GOOD_TEXAS_RENDERED,
    )
    assert _labelled(judgement.violations, "not-fallback")
    assert judgement.served_by == "fallback"


def test_judge_flags_a_served_retry_when_the_first_call_re_checks_valid(
    texas_block: str, catalog: tuple[TeamRecord, ...]
) -> None:
    # Production serves the first valid call and never makes a second one, so
    # this shape means the eval's re-check disagrees with production's check.
    other: dict[str, object] = {
        "text": "Texas ran the table in {yr}.",
        "claims": [{"id": "yr", "kind": "year"}],
    }
    judgement = judge_narration(
        served_text=GOOD_TEXAS_RENDERED,
        calls=[_call(other, texas_block), _call(GOOD_TEXAS_INPUT, texas_block)],
        catalog=catalog,
        fallback_text="the fallback",
    )
    grounded = _labelled(judgement.violations, "grounded")
    assert grounded and "call 1" in grounded[0]


def test_judge_flags_a_narration_with_no_recorded_call(catalog: tuple[TeamRecord, ...]) -> None:
    judgement = judge_narration(
        served_text="Texas ran the table.", calls=[], catalog=catalog, fallback_text="the fallback"
    )
    assert _labelled(judgement.violations, "grounded")
    assert judgement.served_by == "untraceable"


@pytest.mark.parametrize(("year", "team"), sorted(EXPECTED_KEENER_NUMBER_ONE.items()))
def test_the_planted_invalid_canary_is_rejected_on_every_champion_block(
    client: TestClient, catalog: tuple[TeamRecord, ...], year: int, team: str
) -> None:
    block = cfb_team_case_block(year, team)
    judgement = judge_planted_invalid(
        block, catalog, fallback_text=team_case_fallback_text(_case(client, year))
    )
    assert _labelled(judgement.violations, "grounded")
    assert judgement.served_by == "untraceable"
    (attempt,) = judgement.attempts
    assert attempt.text is None
    # The canary is rejected for its typed number and nothing else, so it
    # tracks exactly the rule that keeps a figure out of the prose.
    assert attempt.errors
    assert all("types the number" in error for error in attempt.errors), attempt.errors


@pytest.mark.parametrize(("year", "team"), sorted(EXPECTED_KEENER_NUMBER_ONE.items()))
def test_the_champion_route_narrates_the_block_the_canary_runs_on(
    client: TestClient, year: int, team: str
) -> None:
    # The live eval runs the canary on `cfb_team_case_block` before spending a
    # Claude call; this pins that block to the one the route narrates.
    assert team_case_fact_block_json(_case(client, year)) == cfb_team_case_block(year, team)


def test_the_team_case_route_narrates_the_block_the_canary_runs_on(client: TestClient) -> None:
    response = client.post(
        "/api/verdict/team-case", json={"year": TEAM_CASE_YEAR, "team": TEAM_CASE_TEAM}
    )
    assert response.status_code == 200, response.text
    case = TeamCaseOut.model_validate(response.json()["evidence"])
    assert team_case_fact_block_json(case) == cfb_team_case_block(TEAM_CASE_YEAR, TEAM_CASE_TEAM)


# ---------------------------------------------------------------------------
# recording
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("contested", [False, True])
def test_fact_block_from_user_turn_round_trips(texas_block: str, contested: bool) -> None:
    turn = build_user_message(texas_block, contested=contested)
    assert fact_block_from_user_turn(turn) == texas_block


def test_fact_block_from_user_turn_rejects_a_changed_turn_shape(texas_block: str) -> None:
    with pytest.raises(ValueError):
        fact_block_from_user_turn("FACTS:\n" + texas_block)


def test_recording_narrator_records_each_call_and_the_block_it_carried(
    texas_block: str,
) -> None:
    no_call = NarratorReply(tool_call=None, assistant_content=(), stop_reason="end_turn")
    inner = FakeNarrator([no_call, tool_reply(GOOD_TEXAS_INPUT)])
    recorder = RecordingNarrator(inner)
    first_turn = build_user_message(texas_block, contested=False)
    assert (
        recorder.submit(system="s", messages=[{"role": "user", "content": first_turn}]) is no_call
    )
    recorder.submit(
        system="s",
        messages=[
            {"role": "user", "content": first_turn},
            {"role": "user", "content": "Rejected"},
        ],
    )
    calls = recorder.recorded_calls()
    assert [call.tool_input for call in calls] == [None, GOOD_TEXAS_INPUT]
    assert [call.fact_block_json for call in calls] == [texas_block, texas_block]
    assert [call.stop_reason for call in calls] == ["end_turn", "tool_use"]
    assert calls[1].raw_text == GOOD_TEXAS_INPUT["text"]
    assert calls[0].raw_text is None
    assert [messages[0]["content"] for messages in recorder.messages] == [first_turn, first_turn]


# ---------------------------------------------------------------------------
# property 1: correct #1 named
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("team", "text"),
    [
        (
            "Texas",
            "Texas Tech ran the table in 2005 and nobody could touch them. That's a machine.",
        ),
        ("Miami", "Miami (OH) went 12-0 in 2001 and nobody could touch them."),
        ("Alabama", "Alabama State went 13-1 in 2017. That's a machine."),
    ],
)
def test_property_1_rejects_a_longer_team_name_containing_the_number_one(
    client: TestClient, team: str, text: str
) -> None:
    assert _labelled(named_team_violations(text, team, _catalog_names(client)), "correct-#1")


def test_property_1_accepts_the_number_one_alongside_a_homograph(client: TestClient) -> None:
    text = "Texas went 13-0 in 2005 and handled Texas Tech 52-17. That's a machine."
    assert named_team_violations(text, "Texas", _catalog_names(client)) == []


def test_property_1_flags_the_wrong_team_as_number_one(
    client: TestClient, texas_block: str, catalog: tuple[TeamRecord, ...]
) -> None:
    judgement = judge_narration(
        served_text=GOOD_TEXAS_RENDERED,
        calls=[_call(GOOD_TEXAS_INPUT, texas_block)],
        catalog=catalog,
        fallback_text="the fallback",
    )
    violations = section_8_violations(
        served_text=GOOD_TEXAS_RENDERED,
        expected_team="Ohio State",
        evidence_team="Texas",
        catalog_names=_catalog_names(client),
        judgement=judgement,
    )
    assert len(_labelled(violations, "correct-#1")) == 2


# ---------------------------------------------------------------------------
# legitimate narrations pass every property
# ---------------------------------------------------------------------------

LEGITIMATE_CALLS = [
    pytest.param(2005, "Texas", GOOD_TEXAS_INPUT, id="2005-texas-prompt-good-example"),
    pytest.param(2013, "Florida State", FSU_AMBIGUOUS_INPUT, id="2013-fsu-ambiguous-when-is-legal"),
    pytest.param(
        2017,
        "Alabama",
        {
            "text": (
                "Look, I know the human polls had some drama about this one, but the numbers "
                "don't lie: Alabama went {rec} in {yr}, rated {rt}. Yeah, they took one on the "
                "chin when Auburn beat them {g1}, and Sonny Dykes would tip his cap. I cannot "
                "believe how good that team was."
            ),
            "claims": [
                {"id": "rec", "kind": "record", "team": "Alabama"},
                {"id": "yr", "kind": "year"},
                {"id": "rt", "kind": "rating", "team": "Alabama"},
                {
                    "id": "g1",
                    "kind": "game_score",
                    "team": "Auburn",
                    "opponent": "Alabama",
                    "result": "W",
                },
            ],
        },
        id="2017-alabama-homograph-name-and-bar-talk",
    ),
]


@pytest.mark.parametrize(("year", "team", "tool_input"), LEGITIMATE_CALLS)
def test_a_legitimate_narration_passes_every_property(
    client: TestClient,
    catalog: tuple[TeamRecord, ...],
    year: int,
    team: str,
    tool_input: dict[str, object],
) -> None:
    block = cfb_team_case_block(year, team)
    outcome = check_and_render(tool_input, block, catalog)
    assert outcome.errors == ()
    assert outcome.text is not None
    judgement = judge_narration(
        served_text=outcome.text,
        calls=[_call(tool_input, block)],
        catalog=catalog,
        fallback_text=team_case_fallback_text(_case(client, year)),
    )
    violations = section_8_violations(
        served_text=outcome.text,
        expected_team=team,
        evidence_team=team,
        catalog_names=_catalog_names(client),
        judgement=judgement,
    )
    assert violations == ()


# ---------------------------------------------------------------------------
# property 3: length, and the sentence counter
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
    assert sentence_count(text) == expected


def test_four_real_sentences_starting_no_1_are_within_the_length_bound() -> None:
    text = "No. 1 Texas went 13-0 in 2005. They beat USC 41-38. That's a machine. Nobody close."
    assert length_violations(text) == []


def test_the_real_2017_served_narration_is_within_the_length_bound() -> None:
    # Served verbatim by the real narrator in round 2 of the #109 runs.
    text = (
        "Look, I know the human polls had some drama about this one, but the numbers "
        "don't lie — Alabama's your #1 in 2017 with that 13-1 record and a rating of "
        "4.84. Yeah, they took one on the chin to Auburn 14-26, but then they went out "
        "and demolished the postseason: beat Clemson 24-6 and snuck past Georgia 26-23 "
        "in the championship game to prove they belonged on top. That's not a fluke, "
        "that's a team that shows up when it matters most."
    )
    assert length_violations(text) == []


def test_five_sentences_are_over_the_length_bound() -> None:
    violations = length_violations("Texas went 13-0 in 2005. " * 5)
    assert _labelled(violations, "length")


def test_too_many_characters_are_over_the_length_bound() -> None:
    violations = length_violations("Texas " * (MAX_CHARACTERS // 6 + 1) + "ran the table.")
    assert _labelled(violations, "length")


# ---------------------------------------------------------------------------
# property 4: banned words -- real hits, no false positives on bar talk or names
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
    assert banned_hits(text) == []


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
    assert banned_hits(text), text


def test_no_catalog_team_name_is_a_banned_word(client: TestClient) -> None:
    assert [name for name in _catalog_names(client) if banned_hits(name)] == []


# ---------------------------------------------------------------------------
# measurement (a): the timing/venue detector
# ---------------------------------------------------------------------------


def _phrases(raw_text: str) -> list[str]:
    return [flag.phrase.casefold() for flag in timing_venue_flags(raw_text)]


@pytest.mark.parametrize(
    ("raw_text", "phrase"),
    [
        # #291 round 2, 2003 LSU, placed after the postseason
        (
            "{rk} LSU beat Oklahoma {g1} {w1}, then went out and dominated everybody else.",
            "then",
        ),
        (
            "{rk} LSU beat Oklahoma {g1} {w1}, then went out and dominated everybody else.",
            "everybody else",
        ),
        # issue #293's example words, from spike #200
        ("Texas opened with Louisiana {g1} and never looked back.", "opened"),
        ("The opener against Louisiana went {g1}.", "opener"),
        ("They capped it off by beating USC {g1}.", "capped"),
        ("The finale was a {g1} rout.", "finale"),
        ("They beat Rice {g1}, then Missouri {g2}.", "then"),
        ("They beat Clemson {g1} at Clemson.", "at clemson"),
        ("Going into Auburn territory is never easy, and they lost {g1}.", "territory"),
        # the brief's list
        ("They won {g1} on the road.", "on the road"),
        ("They won {g1} at home.", "at home"),
        ("A road win over Oregon {g1} settled it.", "road win"),
        ("A road loss to Texas {g1} stung.", "road loss"),
        ("They beat Louisiana {g1} to start the season.", "to start the season"),
        ("They beat Colorado {g1} to close the season.", "to close the season"),
        ("They beat Colorado {g1} to end the season.", "to end the season"),
        ("They were perfect down the stretch.", "down the stretch"),
        ("Early in the season they beat Ohio State {g1}.", "early in the season"),
        ("Late in the season they beat Kansas {g1}.", "late in the season"),
        ("By week eleven they were rolling.", "week"),
        ("They won the bowl {g1}.", "bowl"),
        ("They won the Rose Bowl {g1}.", "bowl"),
        ("The postseason was theirs, {g1} over USC.", "postseason"),
        ("The regular season was spotless.", "regular season"),
        ("They beat USC {g1} at a neutral site.", "neutral site"),
        # a placeholder removed from between the words still leaves the phrase
        ("They won at {rk} Georgia {g1}.", "at georgia"),
        ("They walked into Georgia's house and won {g1}.", "'s house"),
    ],
)
def test_detector_flags_known_timing_and_venue_phrases(raw_text: str, phrase: str) -> None:
    assert any(phrase in found for found in _phrases(raw_text)), (raw_text, _phrases(raw_text))


def test_detector_labels_timing_and_venue() -> None:
    flags = timing_venue_flags("They won at Clemson {g1}, then rolled.")
    assert TimingVenueFlag(kind="venue", phrase="at Clemson") in flags
    assert TimingVenueFlag(kind="timing", phrase="then") in flags


@pytest.mark.parametrize(
    "raw_text",
    [
        "Auburn beat Alabama {g1} {w1}.",
        "Texas went {rec} in {yr} and went through USC {g1} {w1} {s1}. That's a machine.",
        "They took down Clemson {g1} and Auburn {g2} {w1}, and nobody touched them.",
        "Look, the numbers don't lie: {rk} Alabama went {rec}, rated {rt}.",
    ],
)
def test_detector_flags_nothing_when_placeholders_carry_the_when_and_where(raw_text: str) -> None:
    assert timing_venue_flags(raw_text) == ()


def test_detector_would_flag_the_rendered_phrases_so_it_runs_on_the_raw_text(
    catalog: tuple[TeamRecord, ...],
) -> None:
    block = cfb_team_case_block(2013, "Florida State")
    rendered = check_and_render(FSU_AMBIGUOUS_INPUT, block, catalog).text
    assert rendered is not None and "in the postseason" in rendered
    raw = FSU_AMBIGUOUS_INPUT["text"]
    assert isinstance(raw, str)
    assert timing_venue_flags(raw) == ()
    assert timing_venue_flags(rendered) != ()


# ---------------------------------------------------------------------------
# measurement (b): ambiguous when
# ---------------------------------------------------------------------------


def test_ambiguous_when_fires_on_two_scores_and_one_when_in_a_sentence() -> None:
    assert ambiguous_when_sentences(FSU_AMBIGUOUS_INPUT) == (
        "They took down Clemson {g1} and Auburn {g2} {w1}, and nobody touched them.",
    )


def _game(claim_id: str, kind: str, opponent: str, **extra: object) -> dict[str, object]:
    return {
        "id": claim_id,
        "kind": kind,
        "team": "Florida State",
        "opponent": opponent,
        "result": "W",
        **extra,
    }


@pytest.mark.parametrize(
    "tool_input",
    [
        # one score, one when
        {
            "text": "They beat Auburn {g1} {w1}.",
            "claims": [_game("g1", "game_score", "Auburn"), _game("w1", "when", "Auburn")],
        },
        # two scores, no when or where
        {
            "text": "They beat Clemson {g1} and Auburn {g2}.",
            "claims": [_game("g1", "game_score", "Clemson"), _game("g2", "game_score", "Auburn")],
        },
        # the when sits in its own sentence
        {
            "text": "They beat Clemson {g1} and Auburn {g2}. The Auburn game came {w1}.",
            "claims": [
                _game("g1", "game_score", "Clemson"),
                _game("g2", "game_score", "Auburn"),
                _game("w1", "when", "Auburn"),
            ],
        },
        # malformed input never raises
        "not a dict",
        {"text": 7, "claims": []},
        {"text": "They beat Auburn {g1} {w1}.", "claims": "nope"},
        {"text": "They beat Clemson {g1} and Auburn {g2} {w1}.", "claims": [[], {"id": ["x"]}]},
    ],
)
def test_ambiguous_when_does_not_fire_otherwise(tool_input: object) -> None:
    assert ambiguous_when_sentences(tool_input) == ()


def test_ambiguous_when_also_fires_for_a_where() -> None:
    tool_input = {
        "text": "They beat Clemson {g1} and Auburn {g2} {s1}.",
        "claims": [
            _game("g1", "game_score", "Clemson"),
            _game("g2", "game_score", "Auburn"),
            _game("s1", "where", "Auburn"),
        ],
    }
    assert len(ambiguous_when_sentences(tool_input)) == 1


# ---------------------------------------------------------------------------
# measurement (d): the lowercase block-team rejection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        ('"rice" must be written exactly as the fact block spells it: "Rice"', True),
        (
            '"virginia tech" must be written exactly as the fact block spells it: "Virginia Tech"',
            True,
        ),
        ('"texas a&m" must be written exactly as the fact block spells it: "Texas A&M"', True),
        ('"TEXAS" must be written exactly as the fact block spells it: "Texas"', False),
        ('"Texas" must be written exactly as the fact block spells it: "TEXAS"', False),
        (
            '"Bama" is another name for Alabama; write the team\'s name as the fact block '
            'spells it: "Alabama"',
            False,
        ),
        (
            '"Longhorns" is a nickname for Texas; write the team\'s name as the fact block '
            'spells it: "Texas"',
            False,
        ),
        ('"alabama" is not a team in the fact block; its teams are: Texas', False),
    ],
)
def test_lowercase_block_team_error_classifier(error: str, expected: bool) -> None:
    assert is_lowercase_block_team_error(error) is expected


def test_the_classifier_reads_the_validators_real_error(
    texas_block: str, catalog: tuple[TeamRecord, ...]
) -> None:
    outcome = check_and_render(
        {"text": "They ate rice before they beat Rice.", "claims": []}, texas_block, catalog
    )
    assert [is_lowercase_block_team_error(error) for error in outcome.errors] == [True]


# ---------------------------------------------------------------------------
# records, measurements (c) and (e), and the summary
# ---------------------------------------------------------------------------


def _attempt(
    tool_input: object | None, *, errors: tuple[str, ...] = (), text: str | None = None
) -> JudgedCall:
    return JudgedCall(call=RecordedCall(tool_input, "{}", "tool_use"), errors=errors, text=text)


LOWERCASE_ERROR = '"rice" must be written exactly as the fact block spells it: "Rice"'
TYPED_ERROR = 'the prose types the number "13-0"; every number must come from a claim placeholder.'


def _record(
    served_by: ServedBy,
    attempts: Sequence[JudgedCall],
    served_text: str,
) -> NarrationRecord:
    served_attempt = next((a for a in attempts if a.text == served_text), None)
    judgement = Judgement(
        served_text=served_text,
        attempts=tuple(attempts),
        served_by=served_by,
        served_attempt=served_attempt,
        violations=(),
    )
    return build_record("hand-built", judgement)


def _hand_built_records() -> list[NarrationRecord]:
    return [
        # first try, four sentences, a "then" and an "at Clemson" in its raw text
        _record(
            "first",
            [
                _attempt(
                    {"text": "They won at Clemson {g1}, then rolled. A. B. C.", "claims": []},
                    text="They won at Clemson 1-0, then rolled. A. B. C.",
                )
            ],
            "They won at Clemson 1-0, then rolled. A. B. C.",
        ),
        # retry after a lowercase rejection; the served call is ambiguous-when
        _record(
            "retry",
            [
                _attempt({"text": "rice", "claims": []}, errors=(LOWERCASE_ERROR, TYPED_ERROR)),
                _attempt(FSU_AMBIGUOUS_INPUT, text="Rendered FSU. Two."),
            ],
            "Rendered FSU. Two.",
        ),
        # fallback after two rejections, one of them lowercase; five sentences,
        # which the length rate does not count because the narrator didn't serve it
        _record(
            "fallback",
            [
                _attempt({"text": "x", "claims": []}, errors=(TYPED_ERROR,)),
                _attempt({"text": "y", "claims": []}, errors=(LOWERCASE_ERROR,)),
            ],
            "One. Two. Three. Four. Five.",
        ),
        # first try, clean
        _record(
            "first",
            [_attempt({"text": "Clean {g1}.", "claims": []}, text="Clean 1-0.")],
            "Clean 1-0.",
        ),
    ]


def test_build_record_measures_the_served_call() -> None:
    first, retry, fallback, clean = _hand_built_records()
    assert [flag.kind for flag in first.timing_venue] == ["venue", "timing"]
    assert first.sentences == 4
    assert first.over_prompt_length is True
    assert first.ambiguous_when == ()
    assert retry.ambiguous_when != ()
    assert retry.timing_venue == ()
    assert retry.lowercase_rejections == 1
    assert fallback.lowercase_rejections == 1
    assert fallback.timing_venue == ()
    assert fallback.over_prompt_length is False
    assert clean.timing_venue == () and clean.over_prompt_length is False


def test_summary_arithmetic_on_hand_built_records() -> None:
    summary = summarize(_hand_built_records())
    assert summary == EvalSummary(
        narrations=4,
        served_first=2,
        served_retry=1,
        served_fallback=1,
        served_untraceable=0,
        claude_calls=6,
        narrator_served=3,
        timing_venue_narrations=1,
        timing_flags=1,
        venue_flags=1,
        ambiguous_when_narrations=1,
        over_prompt_length=1,
        lowercase_rejections=2,
    )
    assert summary.timing_venue_rate == pytest.approx(1 / 3)
    assert summary.ambiguous_when_rate == pytest.approx(1 / 3)
    assert summary.over_prompt_length_rate == pytest.approx(1 / 3)
    assert summary.lowercase_rejection_rate == pytest.approx(2 / 6)
    assert summary.fallback_rate == pytest.approx(1 / 4)
    assert summary.first_try_rate == pytest.approx(2 / 4)


def test_summary_of_no_narrations_has_no_rates() -> None:
    summary = summarize([])
    assert summary.narrations == 0 and summary.claude_calls == 0
    assert summary.timing_venue_rate is None
    assert summary.ambiguous_when_rate is None
    assert summary.over_prompt_length_rate is None
    assert summary.lowercase_rejection_rate is None
    assert summary.fallback_rate is None
    assert summary.first_try_rate is None
    line = format_summary(
        summary, prompt_version=PROMPT_VERSION, grounding_version=GROUNDING_VERSION
    )
    assert "n/a" in line


def test_the_summary_line_names_both_versions_and_the_counts() -> None:
    line = format_summary(
        summarize(_hand_built_records()),
        prompt_version=PROMPT_VERSION,
        grounding_version=GROUNDING_VERSION,
    )
    assert "persona-v11" in line and "claims-v1" in line
    assert "first=2" in line and "retry=1" in line and "fallback=1" in line
    assert "claude_calls=6" in line
    assert "1/3" in line and "2/6" in line


def test_format_record_never_raises_on_any_served_by() -> None:
    for record in _hand_built_records():
        assert record.label in format_record(record)
