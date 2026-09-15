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

import time

import pytest
from fixtures.claim_blocks import (
    assert_an_error_says,
    cfb_catalog,
    cfb_comparison_block,
    cfb_team_case_block,
    rejected,
    rendered,
    submit,
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


@pytest.fixture(scope="module")
def virginia_2017() -> str:
    return cfb_team_case_block(2017, "Virginia")


@pytest.fixture(scope="module")
def fsu_msu_2013() -> str:
    return cfb_comparison_block(2013, "Florida State", "Michigan State")


@pytest.fixture(scope="module")
def texas_usc_2005() -> str:
    return cfb_comparison_block(2005, "Texas", "USC")


def test_catalog_facts_these_tests_rely_on(catalog: tuple[TeamRecord, ...]) -> None:
    by_name = {record.name: record for record in catalog}
    assert len(catalog) == 451
    assert by_name["Alabama"].mascot == "Crimson Tide"
    assert "ALA" in by_name["Alabama"].aliases
    assert by_name["Texas"].mascot == "Longhorns"
    assert "FSU" in by_name["Florida State"].aliases
    assert "UGA" in by_name["Georgia"].aliases
    assert {"West Virginia", "Virginia", "Texas A&M", "Texas", "LSU"} <= set(by_name)
    # English words the round-2 probes lean on: schools, mascots, aliases.
    assert {"Pace", "Assumption"} <= set(by_name)
    assert by_name["Hofstra"].mascot == "Pride"
    assert by_name["Cornell"].mascot == "Big Red"
    assert by_name["Dartmouth"].mascot == "Big Green"
    assert by_name["Tulane"].mascot == "Green Wave"
    assert "ME" in by_name["Maine"].aliases
    assert "UK" in by_name["Kentucky"].aliases


def test_block_facts_these_tests_rely_on(
    alabama_2017: str, texas_2005: str, virginia_2017: str, fsu_msu_2013: str
) -> None:
    for block in (alabama_2017, texas_2005):
        assert '"Maine"' not in block and '"Kentucky"' not in block
        assert '"Hofstra"' not in block and '"Cornell"' not in block
        assert '"Pace"' not in block and '"Assumption"' not in block
    assert '"Alabama"' not in texas_2005
    assert '"Virginia"' in virginia_2017 and '"West Virginia"' not in virginia_2017
    assert '"Florida State"' in fsu_msu_2013


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


@pytest.mark.parametrize(
    "record",
    ["one-and-oh", "one-oh", "oh-and-one", "thirteen and oh", "twelve and one", "one and twelve"],
)
def test_a_number_word_record_is_rejected(
    alabama_2017: str, catalog: tuple[TeamRecord, ...], record: str
) -> None:
    errors = rejected(f"They went {record} that year.", [], alabama_2017, catalog)
    assert_an_error_says(errors, f'"{record}"', "spells out the number")


@pytest.mark.parametrize(
    "text",
    [
        "Oh and one more thing: Auburn got lucky.",
        # Accepted gap (coordinator decision B2 on #290 round 3): when both sides
        # are oh, one or zero, only a hyphen-joined form counts as a record.
        "They went one and oh.",
    ],
)
def test_oh_and_one_joined_by_a_plain_and_is_prose(
    alabama_2017: str, catalog: tuple[TeamRecord, ...], text: str
) -> None:
    assert rendered(text, [], alabama_2017, catalog) == text


_DIGIT_HEAVY = (
    "1 " * 10_000,
    ("Alabama 13-1 over Auburn, then two more and 9 " * 500)[:20_000],
)


@pytest.mark.parametrize("text", _DIGIT_HEAVY, ids=["bare-digits", "names-digits-and-words"])
def test_a_twenty_thousand_character_digit_heavy_text_is_checked_in_under_two_seconds(
    alabama_2017: str, catalog: tuple[TeamRecord, ...], text: str
) -> None:
    # Round 3 measured 78 s for "1 " * 10000: every error re-scanned the whole
    # sentence for team names. The bound is generous so CI never flakes.
    assert len(text) == 20_000
    submit("Warm the catalog caches.", [], alabama_2017, catalog)
    started = time.perf_counter()
    outcome = submit(text, [], alabama_2017, catalog)
    elapsed = time.perf_counter() - started
    assert outcome.errors
    assert outcome.text is None
    assert elapsed < 2.0, f"took {elapsed:.2f} s"


# ---------------------------------------------------------------------------
# team references
# ---------------------------------------------------------------------------


def test_a_team_the_block_does_not_hold_is_rejected_listing_the_blocks_teams(
    texas_2005: str, catalog: tuple[TeamRecord, ...]
) -> None:
    errors = rejected("Alabama wasn't even in this.", [], texas_2005, catalog)
    assert_an_error_says(errors, '"Alabama"', "Texas", "USC", "Ohio State")


def test_a_shouted_team_the_block_does_not_hold_is_rejected(
    texas_2005: str, catalog: tuple[TeamRecord, ...]
) -> None:
    errors = rejected("ALABAMA wasn't even in this.", [], texas_2005, catalog)
    assert_an_error_says(errors, '"ALABAMA"', "not a team in the fact block")


def test_a_lowercase_team_the_block_does_not_hold_is_accepted_by_founder_decision(
    texas_2005: str, catalog: tuple[TeamRecord, ...]
) -> None:
    """Founder decision on #290, 2026-09-15: a catalog name for a team the block
    does not mention is a team reference only when its first letter is
    uppercase, with no English-word exemption list. So lowercase "alabama" on a
    block without Alabama is prose, the price of "the pace" and "the
    assumption" passing (an accepted gap)."""
    text = "alabama wasn't even in this."
    assert rendered(text, [], texas_2005, catalog) == text


@pytest.mark.parametrize("text", ["They set the pace all year.", "That's the assumption."])
@pytest.mark.parametrize("block_name", ["alabama_2017", "texas_2005"])
def test_a_lowercase_school_name_that_is_an_english_word_is_prose(
    request: pytest.FixtureRequest,
    catalog: tuple[TeamRecord, ...],
    block_name: str,
    text: str,
) -> None:
    # Pace and Assumption are catalog schools; neither is in these blocks.
    block: str = request.getfixturevalue(block_name)
    assert rendered(text, [], block, catalog) == text


def test_a_lowercase_longer_name_outside_the_block_does_not_hide_a_block_team(
    virginia_2017: str, catalog: tuple[TeamRecord, ...]
) -> None:
    # West Virginia is not in the block, so lowercase "west virginia" is no team
    # reference and does not shadow the block's Virginia inside it: that
    # "virginia" is a misspelling of a block team.
    errors = rejected("Nobody from west virginia cared.", [], virginia_2017, catalog)
    assert_an_error_says(errors, '"virginia"', 'exactly as the fact block spells it: "Virginia"')
    assert not any("west virginia" in error.casefold() for error in errors), errors


def test_a_capitalized_longer_name_outside_the_block_still_wins_over_a_block_team(
    virginia_2017: str, catalog: tuple[TeamRecord, ...]
) -> None:
    errors = rejected("West Virginia never came up.", [], virginia_2017, catalog)
    assert_an_error_says(errors, '"West Virginia"', "not a team in the fact block")
    assert len(errors) == 1, errors


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


def test_an_alias_of_a_block_team_on_a_comparison_is_rejected(
    fsu_msu_2013: str, catalog: tuple[TeamRecord, ...]
) -> None:
    errors = rejected("FSU was never in doubt.", [], fsu_msu_2013, catalog)
    assert_an_error_says(errors, '"FSU"', '"Florida State"')


def test_an_alias_of_a_team_outside_the_block_is_prose(
    usc_2005: str, catalog: tuple[TeamRecord, ...]
) -> None:
    """Coordinator decision 4 on #290 round 2: only an alias of a team the block
    mentions is a team reference. Georgia is not in the 2005 USC block, so
    "UGA" here is ignored (round 1 rejected it)."""
    assert rendered("UGA fans agree.", [], usc_2005, catalog) == "UGA fans agree."


@pytest.mark.parametrize("text", ["Don't tell ME that.", "the UK crowd"])
@pytest.mark.parametrize("block_name", ["alabama_2017", "texas_2005"])
def test_a_capital_letter_alias_of_a_team_outside_the_block_is_prose(
    request: pytest.FixtureRequest,
    catalog: tuple[TeamRecord, ...],
    block_name: str,
    text: str,
) -> None:
    # ME is Maine's alias and UK is Kentucky's; neither is in these blocks.
    block: str = request.getfixturevalue(block_name)
    assert rendered(text, [], block, catalog) == text


@pytest.mark.parametrize(
    ("block_name", "text", "needles"),
    [
        ("alabama_2017", "The Tide rolled.", ('"Tide"', "Alabama")),
        ("alabama_2017", "That was the Tide's year.", ('"Tide"', "Alabama")),
        ("alabama_2017", "The Crimson Tide rolled.", ('"Crimson Tide"', "Alabama")),
        ("alabama_2017", "Nobody stops the Crimson Tide.", ('"Crimson Tide"', "Alabama")),
        # a multi-word mascot needs no "the"
        ("alabama_2017", "Crimson Tide fans were loud.", ('"Crimson Tide"', "Alabama")),
        ("alabama_2017", "Alabama Crimson Tide football.", ('"Crimson Tide"', "Alabama")),
        ("alabama_2017", "Even Green Wave fans knew.", ('"Green Wave"', "Tulane")),
        ("texas_2005", "The Longhorns ran the table.", ('"Longhorns"', "Texas")),
        ("texas_2005", "Nobody stopped the Longhorns defense.", ('"Longhorns"', "Texas")),
        ("texas_2005", "Texas Longhorns ran the table.", ('"Longhorns"', '"Texas"')),
        ("usc_2005", "The Longhorns ran the table.", ('"Longhorns"', "Texas")),
        ("usc_2005", "Those Texas Longhorns were good.", ('"Longhorns"', '"Texas"')),
        ("alabama_2017", "Hats off to the Pride.", ('"Pride"', "Hofstra")),
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
    "text",
    [
        "Pride goes before the fall.",
        "Red flags everywhere.",
        "Green light for the offense.",
        "Cardinal sins, all of them.",
        # Known gap (coordinator decision 3 on #290 round 2): a single-word
        # mascot with neither "the" nor a team name before it is not caught.
        "Longhorns fans were loud.",
    ],
)
@pytest.mark.parametrize("block_name", ["alabama_2017", "texas_2005"])
def test_a_single_word_mascot_without_the_or_a_team_name_before_it_is_prose(
    request: pytest.FixtureRequest,
    catalog: tuple[TeamRecord, ...],
    block_name: str,
    text: str,
) -> None:
    block: str = request.getfixturevalue(block_name)
    assert rendered(text, [], block, catalog) == text


def test_a_mascot_after_a_rank_placeholder_is_rejected(
    usc_2005: str, catalog: tuple[TeamRecord, ...]
) -> None:
    # {k} prints "No. 1 Texas", so "{k} Longhorns" reads "No. 1 Texas Longhorns".
    claim: dict[str, object] = {"id": "k", "kind": "rank", "team": "Texas"}
    errors = rejected("Then {k} Longhorns showed up.", [claim], usc_2005, catalog)
    assert_an_error_says(errors, '"Longhorns"', "Texas")


@pytest.mark.parametrize(
    ("text", "token", "phrase"),
    [
        ("Big Ten teams never came up.", "Ten", "Big Ten"),
        ("That Big 12 slate was soft.", "12", "Big 12"),
        ("The Big Twelve was weak.", "Twelve", "Big Twelve"),
        ("Pac-12 fans can argue.", "12", "Pac-12"),
        ("Pac-10 fans can argue.", "10", "Pac-10"),
        ("They pulled away in the second half.", "second", "second half"),
        ("It was over by the third quarter.", "third", "third quarter"),
        ("A fourth quarter comeback.", "fourth", "fourth quarter"),
    ],
)
def test_a_conference_or_game_phase_is_rejected_saying_the_block_holds_no_such_detail(
    alabama_2017: str, catalog: tuple[TeamRecord, ...], text: str, token: str, phrase: str
) -> None:
    errors = rejected(text, [], alabama_2017, catalog)
    assert_an_error_says(
        errors,
        f'"{token}"',
        f'"{phrase}"',
        "FACT BLOCK holds no conference or in-game detail",
        "leave it out",
    )


def test_an_ordinal_outside_a_game_phase_keeps_the_rank_wording(
    alabama_2017: str, catalog: tuple[TeamRecord, ...]
) -> None:
    errors = rejected("They finished second in the league.", [], alabama_2017, catalog)
    assert_an_error_says(errors, '"second"', "a rank must come from a rank claim")
    assert not any("conference" in error for error in errors), errors


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


_ALABAMA_RECORD: dict[str, object] = {"id": "r", "kind": "record", "team": "Alabama"}


@pytest.mark.parametrize(
    ("text", "claim"),
    [
        # parenthetical: would render "Alabama (Alabama 13-1) rolled."
        ("Alabama ({r}) rolled.", _ALABAMA_RECORD),
        ("They beat Georgia ({k}).", {"id": "k", "kind": "rank", "team": "Georgia"}),
        ("Alabama ({t}) is the pick.", {"id": "t", "kind": "rating", "team": "Alabama"}),
        ("[{r}] Alabama rolled.", _ALABAMA_RECORD),
        # possessive: would render "Alabama's Alabama 13-1 says it all."
        ("Alabama's {r} says it all.", _ALABAMA_RECORD),
        ("Alabama’s {r} says it all.", _ALABAMA_RECORD),
        # commas, colons, semicolons, dashes and quotes, in either order
        ("Alabama, {r}, rolled.", _ALABAMA_RECORD),
        ("{r}, Alabama rolled.", _ALABAMA_RECORD),
        ("Alabama: {r}.", _ALABAMA_RECORD),
        ("{r}; Alabama rolled.", _ALABAMA_RECORD),
        ("Alabama - {r}.", _ALABAMA_RECORD),
        ("Alabama – {r}.", _ALABAMA_RECORD),
        ("Alabama—{r}.", _ALABAMA_RECORD),
        ('"Alabama" {r}.', _ALABAMA_RECORD),
        ("'Alabama' {r}.", _ALABAMA_RECORD),
        ("“Alabama” {r}.", _ALABAMA_RECORD),
        ("‘Alabama’ {r}.", _ALABAMA_RECORD),
    ],
)
def test_the_name_typed_beside_its_own_placeholder_across_punctuation_is_rejected(
    alabama_2017: str, catalog: tuple[TeamRecord, ...], text: str, claim: dict[str, object]
) -> None:
    errors = rejected(text, [claim], alabama_2017, catalog)
    assert_an_error_says(errors, "{" + str(claim["id"]) + "}", "already prints", str(claim["team"]))


def test_both_names_typed_beside_their_own_placeholders_on_a_comparison_are_rejected(
    texas_usc_2005: str, catalog: tuple[TeamRecord, ...]
) -> None:
    claims: list[dict[str, object]] = [
        {"id": "a", "kind": "record", "team": "Texas"},
        {"id": "b", "kind": "record", "team": "USC"},
    ]
    errors = rejected("Texas ({a}) beat USC ({b}).", claims, texas_usc_2005, catalog)
    assert_an_error_says(errors, "{a}", "already prints", '"Texas"')
    assert_an_error_says(errors, "{b}", "already prints", '"USC"')


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # a sentence end breaks adjacency
        ("Alabama rolled. {r} says it all.", "Alabama rolled. Alabama 13-1 says it all."),
        ("They beat Alabama! {r} was no fluke.", "They beat Alabama! Alabama 13-1 was no fluke."),
        ("Was it Alabama? {r} says so.", "Was it Alabama? Alabama 13-1 says so."),
        # a different team beside the placeholder is never a duplicate
        ("Auburn ({r}) is not the story.", "Auburn (Alabama 13-1) is not the story."),
        ("Georgia's {r} line is wrong.", "Georgia's Alabama 13-1 line is wrong."),
    ],
)
def test_a_name_beside_a_placeholder_across_a_sentence_end_or_for_another_team_is_accepted(
    alabama_2017: str, catalog: tuple[TeamRecord, ...], text: str, expected: str
) -> None:
    assert rendered(text, [_ALABAMA_RECORD], alabama_2017, catalog) == expected


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
