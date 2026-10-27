"""Failing-first tests for issue #454: a Roman numeral typed into team prose.

The QB check rejects "Super Bowl XXXIV" (#451, D3), but the team check had no
Roman-numeral rule, so "they won Super Bowl LI" passed on a team block that
holds no Super Bowl and no numbered event at all. A Roman numeral is a number,
and every number must come from a claim placeholder.

Both directions are pinned on real blocks: the committed CFB fixture (2005
Texas) and the NFL sport fixture (2023 Kilo Kings vs Lima Lions). The rule
must not fire on legitimate team prose: every team name and alias in the CFB
fixture catalog (which holds real numeral-letter aliases, "MCM" for McMurry
and "LIV" for Livingstone) and the NFL fixture catalogs, ordinary football
abbreviations ("DL", "OL") and the pronoun "I".
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest
from fixtures.claim_blocks import (
    KILO_KINGS,
    assert_an_error_says,
    catalog_of,
    cfb_catalog,
    cfb_team_case_block,
    game_claim,
    nfl_tie_comparison_block,
    rejected,
    rendered,
    submit,
)
from fixtures.sport_fixture import make_sport_fixture_db
from fixtures.team_catalog_fixture import make_team_catalog_fixture_db

from api.persona.claims import GROUNDING_VERSION
from api.repositories.teams import TeamRecord

ROMAN_FEEDBACK = (
    "a Roman numeral is a number, and the FACT BLOCK holds no Super Bowls or numbered games"
)


@pytest.fixture(scope="module")
def catalog() -> tuple[TeamRecord, ...]:
    return cfb_catalog()


@pytest.fixture(scope="module")
def texas_2005() -> str:
    return cfb_team_case_block(2005, "Texas")


@pytest.fixture(scope="module")
def sport_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return make_sport_fixture_db(tmp_path_factory.mktemp("roman_sport"))


@pytest.fixture(scope="module")
def kilo_lima(sport_db: Path) -> str:
    return nfl_tie_comparison_block(sport_db)


@pytest.fixture(scope="module")
def nfl_catalog(sport_db: Path) -> tuple[TeamRecord, ...]:
    return catalog_of(sport_db, "nfl")


@pytest.fixture(scope="module")
def relocation_catalog(tmp_path_factory: pytest.TempPathFactory) -> tuple[TeamRecord, ...]:
    """The real NFL franchise names (Oakland / Las Vegas Raiders and the
    rest) plus CFB rows with populated aliases, from `/api/teams`' fixture."""
    db = make_team_catalog_fixture_db(tmp_path_factory.mktemp("roman_catalog"))
    return catalog_of(db, "nfl") + catalog_of(db, "cfb")


def _texas_score() -> dict[str, object]:
    return game_claim("g1", "game_score", "Texas", "Ohio State", "W")


def _roman_errors(errors: Sequence[str]) -> list[str]:
    return [error for error in errors if "Roman numeral" in error]


def test_fixture_facts_these_tests_rely_on(catalog: tuple[TeamRecord, ...]) -> None:
    """The CFB catalog holds aliases that are valid Roman numerals, so the
    false-positive probe below is not vacuous."""
    aliases = {record.name: record.aliases for record in catalog}
    assert "MCM" in aliases["McMurry"]
    assert "LIV" in aliases["Livingstone"]


# ---------------------------------------------------------------------------
# a Roman numeral typed in team prose is rejected
# ---------------------------------------------------------------------------

_CFB_ROMAN_CASES = [
    ("Texas beat Ohio State {g1} and played like it won Super Bowl LI.", "LI"),
    ("Texas beat Ohio State {g1}, a Super Bowl XXXIV kind of night.", "XXXIV"),
    ("Texas beat Ohio State {g1}. That defense was XL.", "XL"),
]


@pytest.mark.parametrize(("text", "numeral"), _CFB_ROMAN_CASES)
def test_the_same_prose_without_the_numeral_passes(
    texas_2005: str, catalog: tuple[TeamRecord, ...], text: str, numeral: str
) -> None:
    """Each rejection below is the numeral's alone: the rest is valid prose."""
    plain = text.replace(f" {numeral}", "")
    rendered(plain, [_texas_score()], texas_2005, catalog)


@pytest.mark.parametrize(("text", "numeral"), _CFB_ROMAN_CASES)
def test_a_roman_numeral_in_team_prose_is_rejected(
    texas_2005: str, catalog: tuple[TeamRecord, ...], text: str, numeral: str
) -> None:
    errors = rejected(text, [_texas_score()], texas_2005, catalog)
    assert errors == (
        f'the prose types the Roman numeral "{numeral}"; {ROMAN_FEEDBACK}, so leave it out',
    ), errors


def test_a_roman_numeral_is_rejected_on_an_nfl_block(
    kilo_lima: str, nfl_catalog: tuple[TeamRecord, ...]
) -> None:
    claims: list[dict[str, object]] = [{"id": "k", "kind": "record", "team": KILO_KINGS}]
    rendered("{k} is a real team.", claims, kilo_lima, nfl_catalog)
    errors = rejected("{k} is a Super Bowl LI team.", claims, kilo_lima, nfl_catalog)
    assert_an_error_says(errors, '"LI"', ROMAN_FEEDBACK)


def test_each_numeral_is_reported_once(texas_2005: str, catalog: tuple[TeamRecord, ...]) -> None:
    errors = rejected(
        "Texas beat Ohio State {g1}. Super Bowl LI, Super Bowl XXXIV.",
        [_texas_score()],
        texas_2005,
        catalog,
    )
    assert _roman_errors(errors) == [
        f'the prose types the Roman numeral "LI"; {ROMAN_FEEDBACK}, so leave it out',
        f'the prose types the Roman numeral "XXXIV"; {ROMAN_FEEDBACK}, so leave it out',
    ], errors


# ---------------------------------------------------------------------------
# false positives: legitimate team prose keeps passing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("word", ["DL", "OL", "DC", "MD", "CD", "DID", "LIVID", "CIVIL"])
def test_capitals_that_are_no_game_number_pass(
    texas_2005: str, catalog: tuple[TeamRecord, ...], word: str
) -> None:
    text = f"Texas beat Ohio State {{g1}} and the {word} folks loved it."
    rendered(text, [_texas_score()], texas_2005, catalog)


def test_the_pronoun_i_passes(texas_2005: str, catalog: tuple[TeamRecord, ...]) -> None:
    text = "I said it before: Texas beat Ohio State {g1}, and I stand by it."
    rendered(text, [_texas_score()], texas_2005, catalog)


def _forms(records: Sequence[TeamRecord]) -> list[str]:
    return sorted({form for r in records for form in (r.name, *r.aliases) if form.strip()})


def _assert_no_roman_error_on_any_form(
    records: Sequence[TeamRecord], block: str, claims: list[dict[str, object]], lead: str
) -> None:
    """Every team name and alias, typed in the prose, raises no Roman-numeral
    error. Other errors (a team outside the block, an alias in place of the
    block's spelling) are other rules' business."""
    flagged = {}
    for form in _forms(records):
        outcome = submit(
            f"{lead} Folks still talk about {form} around here.", claims, block, records
        )
        found = _roman_errors(outcome.errors)
        if found:
            flagged[form] = found
    assert flagged == {}


def test_every_cfb_catalog_name_and_alias_passes_the_numeral_rule(
    texas_2005: str, catalog: tuple[TeamRecord, ...]
) -> None:
    assert {"MCM", "LIV"} <= set(_forms(catalog))
    _assert_no_roman_error_on_any_form(
        catalog, texas_2005, [_texas_score()], "Texas beat Ohio State {g1}."
    )


def test_every_nfl_fixture_name_and_alias_passes_the_numeral_rule(
    kilo_lima: str,
    nfl_catalog: tuple[TeamRecord, ...],
    relocation_catalog: tuple[TeamRecord, ...],
) -> None:
    claims: list[dict[str, object]] = [{"id": "k", "kind": "record", "team": KILO_KINGS}]
    _assert_no_roman_error_on_any_form(nfl_catalog, kilo_lima, claims, "{k} is a real team.")
    _assert_no_roman_error_on_any_form(
        nfl_catalog + relocation_catalog, kilo_lima, claims, "{k} is a real team."
    )


def test_a_block_teams_own_numeral_alias_passes(
    texas_2005: str, catalog: tuple[TeamRecord, ...]
) -> None:
    """A hypothetical block team whose alias is all numeral letters: typed in
    the prose, it is that team's name, not a game number."""
    with_alias = tuple(
        TeamRecord(name=r.name, mascot=r.mascot, aliases=(*r.aliases, "XL"))
        if r.name == "Texas"
        else r
        for r in catalog
    )
    outcome = submit(
        "Texas beat Ohio State {g1}. XL fans loved it.", [_texas_score()], texas_2005, with_alias
    )
    assert _roman_errors(outcome.errors) == [], outcome.errors


def test_the_grounding_version_moved_for_the_roman_numeral_rule() -> None:
    """A narration accepted under claims-v5 can be rejected now, so cached
    ones must miss."""
    assert GROUNDING_VERSION == "claims-v6"
