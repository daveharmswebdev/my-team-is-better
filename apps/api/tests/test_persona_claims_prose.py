"""Failing-first tests for issue #290: the leftover-text check of
`api.persona.claims` -- what the narrator's prose may say outside its
placeholders.

With every figure printed from a claim, the prose itself must carry none: no
digits, no spelled-out numbers or number-word records, no ordinal ranks, and
every team reference spelled exactly as the fact block spells it (never an
alias like "FSU", a mascot like "the Tide", a different case like "texas", a
team the block doesn't hold, or the name typed again beside a placeholder that
already prints it). Each rejection must say what the block does hold, because
the errors go back to the narrator verbatim as retry feedback.

The other direction matters as much: ordinary bar-stool prose ("the tide
turned", "the one loss", "first things first") must pass, and a team name must
never be found inside a longer one ("West Virginia" is not "Virginia") or
inside an unrelated word.

Blocks and catalog: the real 2017 Alabama, 2005 USC and 2005 Texas blocks and
the committed fixture's 451-team CFB catalog with its real CFBD mascots and
aliases (`tests/fixtures/claim_blocks.py`).
"""

from __future__ import annotations

import pytest
from fixtures.claim_blocks import (
    assert_an_error_says,
    cfb_catalog,
    cfb_team_case_block,
    rejected,
    rendered,
)

from api.repositories.teams import TeamRecord


@pytest.fixture(scope="module")
def catalog() -> tuple[TeamRecord, ...]:
    return cfb_catalog()


@pytest.fixture(scope="module")
def alabama_2017() -> str:
    return cfb_team_case_block(2017, "Alabama")


@pytest.fixture(scope="module")
def usc_2005() -> str:
    return cfb_team_case_block(2005, "USC")


@pytest.fixture(scope="module")
def texas_2005() -> str:
    return cfb_team_case_block(2005, "Texas")


def test_catalog_facts_these_tests_rely_on(catalog: tuple[TeamRecord, ...]) -> None:
    by_name = {record.name: record for record in catalog}
    assert len(catalog) == 451
    assert by_name["Alabama"].mascot == "Crimson Tide"
    assert "ALA" in by_name["Alabama"].aliases
    assert by_name["Texas"].mascot == "Longhorns"
    assert "FSU" in by_name["Florida State"].aliases
    assert "UGA" in by_name["Georgia"].aliases
    assert {"West Virginia", "Virginia", "Texas A&M", "Texas", "LSU"} <= set(by_name)


# ---------------------------------------------------------------------------
# numbers typed into the prose
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("block_name", "text", "needles"),
    [
        (
            "texas_2005",
            "Texas went 13-1 this year and beat USC by two touchdowns.",
            ('"13-1"', "Texas 13-0"),
        ),
        (
            "texas_2005",
            "Texas went 13-1 this year and beat USC by two touchdowns.",
            ('"two"', "Texas 13-0"),
        ),
        ("texas_2005", "Texas beat USC 40-29.", ('"40-29"', "Texas vs USC: W 41-38")),
        # an en dash is still a score
        ("texas_2005", "Texas beat USC 38–41.", ('"38–41"', "Texas vs USC: W 41-38")),
        ("texas_2005", "Texas went thirteen and oh.", ('"thirteen and oh"', "Texas 13-0")),
        ("alabama_2017", "LSU finished 99-0.", ('"99-0"', "Alabama vs LSU: W 24-10")),
        ("texas_2005", "USC was ranked second", ('"second"', "No. 2 USC")),
        ("usc_2005", "USC was ranked second", ('"second"', "No. 2 USC")),
        ("alabama_2017", "They won by 12 points.", ('"12"', "Alabama 13-1")),
        ("alabama_2017", "Rated 4.84 or so.", ('"4.84"',)),
        ("alabama_2017", "Nobody got within twenty of them.", ('"twenty"', "Alabama 13-1")),
        ("alabama_2017", "They finished fifth, not first.", ('"fifth"', "No. 1 Alabama")),
        ("alabama_2017", "A one-and-one stretch.", ('"one-and-one"',)),
        # a non-ASCII decimal digit is still a digit
        ("alabama_2017", "They went ١٣-1.", ("١٣",)),
    ],
)
def test_numbers_in_the_prose_are_rejected_naming_what_the_block_holds(
    request: pytest.FixtureRequest,
    catalog: tuple[TeamRecord, ...],
    block_name: str,
    text: str,
    needles: tuple[str, ...],
) -> None:
    block: str = request.getfixturevalue(block_name)
    assert_an_error_says(rejected(text, [], block, catalog), *needles)


def test_a_number_inside_a_placeholder_id_is_not_prose(
    alabama_2017: str, catalog: tuple[TeamRecord, ...]
) -> None:
    claim: dict[str, object] = {"id": "k12", "kind": "year"}
    assert rendered("Back in {k12}.", [claim], alabama_2017, catalog) == "Back in 2017."


# ---------------------------------------------------------------------------
# team references
# ---------------------------------------------------------------------------


def test_a_team_the_block_does_not_hold_is_rejected_listing_the_blocks_teams(
    texas_2005: str, catalog: tuple[TeamRecord, ...]
) -> None:
    errors = rejected("alabama wasn't even in this.", [], texas_2005, catalog)
    assert_an_error_says(errors, '"alabama"', "Texas", "USC", "Ohio State")


def test_a_block_team_in_the_wrong_case_is_rejected_with_the_blocks_spelling(
    texas_2005: str, catalog: tuple[TeamRecord, ...]
) -> None:
    errors = rejected("texas ran the table.", [], texas_2005, catalog)
    assert_an_error_says(errors, '"texas"', '"Texas"')


def test_shouting_a_block_team_is_a_spelling_error(
    texas_2005: str, catalog: tuple[TeamRecord, ...]
) -> None:
    assert_an_error_says(rejected("TEXAS!", [], texas_2005, catalog), '"TEXAS"', '"Texas"')


@pytest.mark.parametrize(
    ("text", "needles"),
    [
        ("FSU was never close.", ('"FSU"', '"Florida State"')),
        ("UGA had them sweating.", ('"UGA"', '"Georgia"')),
        ("ALA was the pick.", ('"ALA"', '"Alabama"')),
    ],
)
def test_an_alias_of_a_block_team_is_rejected_with_the_blocks_spelling(
    alabama_2017: str, catalog: tuple[TeamRecord, ...], text: str, needles: tuple[str, ...]
) -> None:
    assert_an_error_says(rejected(text, [], alabama_2017, catalog), *needles)


def test_an_alias_of_a_team_outside_the_block_is_rejected(
    usc_2005: str, catalog: tuple[TeamRecord, ...]
) -> None:
    assert_an_error_says(rejected("UGA fans agree.", [], usc_2005, catalog), '"UGA"', "Georgia")


@pytest.mark.parametrize(
    ("block_name", "text", "needles"),
    [
        ("alabama_2017", "The Tide rolled.", ('"Tide"', "Alabama")),
        ("alabama_2017", "The Crimson Tide rolled.", ('"Crimson Tide"', "Alabama")),
        ("texas_2005", "The Longhorns ran the table.", ('"Longhorns"', "Texas")),
        ("usc_2005", "The Longhorns ran the table.", ('"Longhorns"', "Texas")),
        # a nickname several teams share names the block's own
        ("alabama_2017", "The Tigers got them.", ('"Tigers"', "Auburn", "Clemson", "LSU")),
        ("alabama_2017", "The Seminoles were toast.", ('"Seminoles"', "Florida State")),
    ],
)
def test_a_mascot_is_rejected_naming_the_team(
    request: pytest.FixtureRequest,
    catalog: tuple[TeamRecord, ...],
    block_name: str,
    text: str,
    needles: tuple[str, ...],
) -> None:
    block: str = request.getfixturevalue(block_name)
    assert_an_error_says(rejected(text, [], block, catalog), *needles)


@pytest.mark.parametrize(
    ("text", "claim"),
    [
        ("Alabama beat {k1} Georgia.", {"id": "k1", "kind": "rank", "team": "Georgia"}),
        ("Georgia {k1} was no match.", {"id": "k1", "kind": "rating", "team": "Georgia"}),
        ("{r} Alabama rolled.", {"id": "r", "kind": "record", "team": "Alabama"}),
    ],
)
def test_the_name_typed_beside_a_placeholder_that_prints_it_is_rejected(
    alabama_2017: str, catalog: tuple[TeamRecord, ...], text: str, claim: dict[str, object]
) -> None:
    errors = rejected(text, [claim], alabama_2017, catalog)
    assert_an_error_says(errors, "{" + str(claim["id"]) + "}", "already prints")


def test_a_different_team_beside_a_name_placeholder_is_not_a_duplicate(
    alabama_2017: str, catalog: tuple[TeamRecord, ...]
) -> None:
    claim: dict[str, object] = {"id": "k1", "kind": "rank", "team": "Georgia"}
    assert (
        rendered("Alabama {k1}, and then some.", [claim], alabama_2017, catalog)
        == "Alabama No. 3 Georgia, and then some."
    )


def test_the_longest_name_wins_for_a_team_outside_the_block(
    alabama_2017: str, catalog: tuple[TeamRecord, ...]
) -> None:
    # One mention of West Virginia, never also a phantom Virginia.
    errors = rejected("West Virginia never came up.", [], alabama_2017, catalog)
    assert_an_error_says(errors, '"West Virginia"')
    assert not any('"Virginia"' in error for error in errors), errors


@pytest.mark.parametrize(
    "text",
    [
        # Texas A&M and Florida State are in the block; Texas and Florida are not
        "Texas A&M hung around.",
        "Florida State was the opener.",
    ],
)
def test_the_longest_name_wins_for_a_block_team(
    alabama_2017: str, catalog: tuple[TeamRecord, ...], text: str
) -> None:
    assert rendered(text, [], alabama_2017, catalog) == text


# ---------------------------------------------------------------------------
# ordinary bar-stool prose must pass
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Look, the numbers don't lie.",
        "Alabama had the one loss, and it came against Auburn.",
        "Then the tide turned.",
        "First things first: Georgia was good.",
        "There was a wave of hype and a lot of noise.",
        "That last one hurt.",
        "Clemson and Georgia both found out the hard way.",
        "That price tag was steep, and the armyworms ate the lawn.",
        "Southerners and Texasville folks can argue all night.",
        "Alabama's case isn't close; Auburn's win doesn't change it.",
        "Mercer showed up, which is more than you can say for some.",
        "No one's saying LSU was bad.",
    ],
)
def test_bar_stool_prose_passes(
    alabama_2017: str, catalog: tuple[TeamRecord, ...], text: str
) -> None:
    assert rendered(text, [], alabama_2017, catalog) == text


def test_a_full_narration_renders(alabama_2017: str, catalog: tuple[TeamRecord, ...]) -> None:
    claims: list[dict[str, object]] = [
        {"id": "rec", "kind": "record", "team": "Alabama"},
        {"id": "qw", "kind": "count", "of": "quality_wins", "team": "Alabama"},
        {"id": "uga", "kind": "rank", "team": "Georgia"},
        {"id": "s1", "kind": "game_score", "team": "Alabama", "opponent": "Georgia", "result": "W"},
        {"id": "w1", "kind": "when", "team": "Alabama", "opponent": "Georgia", "result": "W"},
        {
            "id": "iron",
            "kind": "game_score",
            "team": "Alabama",
            "opponent": "Auburn",
            "result": "L",
        },
        {"id": "fin", "kind": "when", "team": "Alabama", "opponent": "Auburn", "result": "L"},
    ]
    text = (
        "Look, {rec} with {qw} quality wins. They beat {uga} {s1} {w1}. "
        "The one loss was {iron} to Auburn {fin}, and the numbers are the numbers."
    )
    assert rendered(text, claims, alabama_2017, catalog) == (
        "Look, Alabama 13-1 with two quality wins. They beat No. 3 Georgia 26-23 in the "
        "postseason. The one loss was 26-14 to Auburn in the regular-season finale, and the "
        "numbers are the numbers."
    )
