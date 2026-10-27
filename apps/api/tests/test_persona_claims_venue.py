"""Failing-first tests for issue #388: a game's venue typed into the prose.

A `where` claim states a venue ("at home", "on the road", "at a neutral
site"), and since #349 only on a game whose fact-block row has
`venue_reliable` true. Before this, the prose could say the same thing by hand
-- "Texas beat Ohio State {g1} on the road." -- and pass, even on a row whose
venue the block marks unreliable, and even when the venue it typed was false.
#382 closed the same hole for a game's timing; this mirrors it for venue.

Both directions are pinned on real blocks from the committed CFB fixture
(`tests/fixtures/claim_blocks.py`): the listed venue phrases typed by hand are
rejected with feedback that points at the `where` claim, a `where` placeholder
that renders the same words is accepted, and ordinary bar-stool idioms built
on "road", "home" and "away" keep passing.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fixtures.claim_blocks import (
    assert_an_error_says,
    cfb_catalog,
    cfb_team_case_block,
    game_claim,
    rejected,
    rendered,
)

from api.persona.claims import GROUNDING_VERSION
from api.repositories.teams import TeamRecord


@pytest.fixture(scope="module")
def catalog() -> tuple[TeamRecord, ...]:
    return cfb_catalog()


@pytest.fixture(scope="module")
def texas_2005() -> str:
    return cfb_team_case_block(2005, "Texas")


@pytest.fixture(scope="module")
def auburn_2013() -> str:
    return cfb_team_case_block(2013, "Auburn")


def _games(block: str, opponent: str) -> list[dict[str, Any]]:
    return [g for g in json.loads(block)["games"] if g["opponent_name"] == opponent]


def _texas_score() -> dict[str, object]:
    return game_claim("g1", "game_score", "Texas", "Ohio State", "W")


def test_fixture_facts_these_tests_rely_on(texas_2005: str, auburn_2013: str) -> None:
    # The issue's probe: Texas won at Ohio State in 2005, a row whose venue
    # the block marks unreliable, so no `where` claim may state it.
    assert [
        (g["result"], g["venue"], g["venue_reliable"]) for g in _games(texas_2005, "Ohio State")
    ] == [("W", "away", False)]
    # A reliable road game: Auburn lost at LSU in 2013.
    assert [(g["result"], g["venue"], g["venue_reliable"]) for g in _games(auburn_2013, "LSU")] == [
        ("L", "away", True)
    ]


# ---------------------------------------------------------------------------
# a venue typed by hand is rejected, pointing at the `where` claim
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "phrase"),
    [
        ("Texas beat Ohio State {g1} on the road.", "on the road"),
        # The false variant: Texas played that game away.
        ("Texas beat Ohio State {g1} at home.", "at home"),
        ("Texas beat Ohio State {g1} at a neutral site.", "neutral site"),
        ("Texas beat Ohio State {g1}, a road win if there ever was one.", "road win"),
        ("Texas beat Ohio State {g1} in front of the home crowd.", "home crowd"),
        ("Texas beat Ohio State {g1}. Road wins like that count.", "Road wins"),
        ("Texas beat Ohio State {g1} in a home game.", "home game"),
        ("Texas beat Ohio State {g1} with the home-field edge gone.", "home-field"),
        ("Texas beat Ohio State {g1} far away from home.", "away from home"),
        ("Texas beat Ohio State {g1} in an away game.", "away game"),
        ("Texas beat Ohio State {g1} on a neutral field.", "neutral field"),
    ],
)
def test_a_venue_typed_in_the_prose_is_rejected_pointing_at_the_where_claim(
    texas_2005: str, catalog: tuple[TeamRecord, ...], text: str, phrase: str
) -> None:
    errors = rejected(text, [_texas_score()], texas_2005, catalog)
    assert_an_error_says(
        errors,
        "the prose types the venue",
        phrase,
        "`where` claim",
        "venue_reliable true",
        "leave the venue out",
    )


def test_a_venue_typed_beside_a_rejected_where_claim_is_rejected_too(
    texas_2005: str, catalog: tuple[TeamRecord, ...]
) -> None:
    """The retry that #349's rejection invites: the claim is dropped for an
    unreliable row, and the model types the venue in its place."""
    errors = rejected("Texas won {g1} on the road.", [_texas_score()], texas_2005, catalog)
    assert len(errors) == 1, errors
    assert errors[0].startswith('the prose types the venue "on the road"; '), errors


# ---------------------------------------------------------------------------
# a `where` placeholder renders the same words and passes
# ---------------------------------------------------------------------------


def test_a_where_placeholder_that_prints_on_the_road_is_accepted(
    auburn_2013: str, catalog: tuple[TeamRecord, ...]
) -> None:
    out = rendered(
        "Auburn lost to LSU {g1} {v}.",
        [
            game_claim("g1", "game_score", "Auburn", "LSU", "L"),
            game_claim("v", "where", "Auburn", "LSU", "L"),
        ],
        auburn_2013,
        catalog,
    )
    assert out.endswith(" on the road."), out


def test_a_where_placeholder_that_prints_at_home_is_accepted(
    auburn_2013: str, catalog: tuple[TeamRecord, ...]
) -> None:
    (georgia,) = _games(auburn_2013, "Georgia")
    assert (georgia["venue"], georgia["venue_reliable"]) == ("home", True)
    out = rendered(
        "Auburn beat Georgia {v}.",
        [game_claim("v", "where", "Auburn", "Georgia", georgia["result"])],
        auburn_2013,
        catalog,
    )
    assert out == "Auburn beat Georgia at home.", out


# ---------------------------------------------------------------------------
# ordinary bar-stool prose built on road/home/away still passes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Texas was on the road to a title.",
        "Texas was on the road to the title all year.",
        "Vince Young brought it home.",
        "Texas was cruising down the home stretch.",
        "Nobody's home in that secondary.",
        "It was a long road back for Ohio State.",
        "Ohio State hit a roadblock.",
        "Texas hit a home run with that hire.",
        "You could tell right away.",
        "Texas played away from the ball all night.",
        "Texas looked right at home against everybody.",
        "Texas felt at home on that stage.",
        "Ohio State never got on the road back.",
        "Away they went.",
        "That one was a home-grown roster.",
    ],
)
def test_bar_stool_road_home_and_away_idioms_pass(
    texas_2005: str, catalog: tuple[TeamRecord, ...], text: str
) -> None:
    assert rendered(text, [], texas_2005, catalog) == text


# ---------------------------------------------------------------------------
# round 2 (#388 review): the bare phrases count only in a game sentence
# ---------------------------------------------------------------------------
#
# Rule A: a compound venue phrase ("a road win", "the home crowd", "away from
# home", "neutral site") is rejected anywhere in the prose. Rule B: the bare
# phrases "on the road" and "at home" are rejected only in a sentence that
# refers to a game -- one holding a game_score, margin, when or where
# placeholder, or a result verb ("beat", "won", "lost", "edged", ...) -- and
# there with no idiom exemptions.


@pytest.mark.parametrize(
    "text",
    [
        # Round 1 let these through on its "back" / "ahead" exemptions.
        "Texas beat Ohio State {g1} on the road back in September.",
        "Texas beat Ohio State {g1} on the road ahead of conference play.",
        # A result verb alone makes it a game sentence.
        "Texas edged Ohio State on the road.",
        "Texas won at home all year.",
        # A game placeholder alone makes it a game sentence, with no verb.
        "Texas over Ohio State {g1} on the road was the whole season.",
    ],
)
def test_a_bare_venue_phrase_in_a_game_sentence_is_rejected_with_no_exemptions(
    texas_2005: str, catalog: tuple[TeamRecord, ...], text: str
) -> None:
    claims = [_texas_score()] if "{g1}" in text else []
    errors = rejected(text, claims, texas_2005, catalog)
    assert_an_error_says(errors, "the prose types the venue", "`where` claim")


@pytest.mark.parametrize(
    "text",
    [
        # The reviewer's false positives: no game in the sentence.
        "Young looked at home in the pocket.",
        "Ohio State fans were sitting at home in January.",
        "Ohio State stayed at home for bowl season.",
        "Texas fans watching at home knew it.",
        "Texas played like a team at home on any field.",
        "Texas was on the road to Pasadena.",
        "He was out on the road recruiting.",
    ],
)
def test_a_bare_venue_phrase_outside_a_game_sentence_passes(
    texas_2005: str, catalog: tuple[TeamRecord, ...], text: str
) -> None:
    assert rendered(text, [], texas_2005, catalog) == text


def test_a_bare_venue_phrase_beside_a_game_sentence_passes(
    texas_2005: str, catalog: tuple[TeamRecord, ...]
) -> None:
    """Only the sentence holding the phrase counts: a game in the sentence
    before doesn't make "at home" in this one a venue."""
    text = "Texas beat Ohio State {g1}. Young looked at home in the pocket."
    out = rendered(text, [_texas_score()], texas_2005, catalog)
    assert out.endswith(" Young looked at home in the pocket."), out


@pytest.mark.parametrize(
    ("text", "phrase"),
    [
        ("That was a road win for the ages.", "road win"),
        ("The home crowd never quit on Texas.", "home crowd"),
        ("Road trips never bothered Texas.", "Road trips"),
        ("Texas played every away game like a final.", "away game"),
        ("Texas was a long way away from home all fall.", "away from home"),
        ("Texas liked a neutral site.", "neutral site"),
        ("Texas fans packed the home stadium.", "home stadium"),
    ],
)
def test_a_compound_venue_phrase_is_rejected_with_no_game_in_the_sentence(
    texas_2005: str, catalog: tuple[TeamRecord, ...], text: str, phrase: str
) -> None:
    errors = rejected(text, [], texas_2005, catalog)
    assert_an_error_says(errors, "the prose types the venue", phrase, "`where` claim")


def test_a_where_placeholder_in_a_game_sentence_passes(
    auburn_2013: str, catalog: tuple[TeamRecord, ...]
) -> None:
    out = rendered(
        "Auburn lost to LSU {g1} {v}, and that is the whole story.",
        [
            game_claim("g1", "game_score", "Auburn", "LSU", "L"),
            game_claim("v", "where", "Auburn", "LSU", "L"),
        ],
        auburn_2013,
        catalog,
    )
    assert " on the road, and that" in out, out


@pytest.mark.parametrize(
    "text",
    [
        # Rule B has no idiom exemptions, so an idiom in a game sentence costs
        # one retry. Accepted (coordinator decision on #388 round 2).
        "Texas beat Ohio State {g1} on the road to Pasadena.",
        "Texas beat Ohio State {g1} and looked right at home.",
    ],
)
def test_accepted_cost_an_idiom_in_a_game_sentence_is_rejected(
    texas_2005: str, catalog: tuple[TeamRecord, ...], text: str
) -> None:
    errors = rejected(text, [_texas_score()], texas_2005, catalog)
    assert_an_error_says(errors, "the prose types the venue")


def test_accepted_cost_a_venue_in_the_sentence_after_the_game_passes(
    texas_2005: str, catalog: tuple[TeamRecord, ...]
) -> None:
    """Cross-sentence venue is out of scope for #388: the sentence holding
    "on the road" has no game reference of its own. The smoke eval's broader
    detector still sees it."""
    text = "They beat Ohio State {g1}. They did it on the road."
    out = rendered(text, [_texas_score()], texas_2005, catalog)
    assert out.endswith(" They did it on the road."), out


def test_the_grounding_version_moved_for_the_venue_check() -> None:
    """A narration accepted under claims-v4 can be rejected now, so cached
    ones must miss."""
    assert GROUNDING_VERSION == "claims-v6"
