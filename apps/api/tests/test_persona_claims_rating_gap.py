"""Failing-first tests for #291 round 2 (founder decision 3, 2026-09-15): the
`rating_gap` claim kind.

Round 1's live run served "That's Texas 1933 points of rating difference": a
rating used as a gap (the real 2005 Texas-Oklahoma Elo gap is 218). A
`rating_gap {team, opponent}` claim prints the gap between the two compared
teams' ratings as the site displays them: `display_value` of each, subtracted,
printed at the method's decimals, with no team names. It is valid only on a
comparison, between its two compared teams, with `team` the higher-rated.

Measured on the fixtures: 2013 Florida State 4.57 vs Michigan State 4.28
(keener) -> "0.29"; 2005 Texas 1933 vs Oklahoma 1715 (elo) -> "218"; NFL 2023
Lima Lions 350.00 vs Kilo Kings 250.00 (keener) -> "100.00". On those three the
difference of the displayed values equals the displayed raw difference, so a
synthetic Elo pair (1933.4 and 1714.6, derived from the real Texas-Oklahoma
block) pins the displayed-difference rule: "218", never "219".
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from fixtures.claim_blocks import (
    KILO_KINGS,
    LIMA_LIONS,
    assert_an_error_says,
    catalog_of,
    cfb_catalog,
    cfb_comparison_block,
    cfb_team_case_block,
    nfl_tie_comparison_block,
    rejected,
    rendered,
)
from fixtures.sport_fixture import make_sport_fixture_db

from api.persona.claims import tool_schema
from api.rating_display import display_value
from api.repositories.teams import TeamRecord


@pytest.fixture(scope="module")
def catalog() -> tuple[TeamRecord, ...]:
    return cfb_catalog()


@pytest.fixture(scope="module")
def fsu_msu_2013() -> str:
    return cfb_comparison_block(2013, "Florida State", "Michigan State")


@pytest.fixture(scope="module")
def texas_oklahoma_2005_elo() -> str:
    return cfb_comparison_block(2005, "Texas", "Oklahoma", method="elo")


def _gap(team: str, opponent: str) -> dict[str, object]:
    return {"id": "gap", "kind": "rating_gap", "team": team, "opponent": opponent}


def _with_ratings(block: str, team_a: float, team_b: float) -> str:
    """`block` with its two compared teams' ratings replaced."""
    data = json.loads(block)
    data["team_a"]["rating"] = team_a
    data["team_b"]["rating"] = team_b
    return json.dumps(data)


def test_block_facts_these_tests_rely_on(
    fsu_msu_2013: str, texas_oklahoma_2005_elo: str, catalog: tuple[TeamRecord, ...]
) -> None:
    ratings: list[dict[str, object]] = [
        {"id": "a", "kind": "rating", "team": "Florida State"},
        {"id": "b", "kind": "rating", "team": "Michigan State"},
    ]
    assert rendered("{a}, {b}", ratings, fsu_msu_2013, catalog) == (
        "Florida State 4.57, Michigan State 4.28"
    )
    ratings = [
        {"id": "a", "kind": "rating", "team": "Texas"},
        {"id": "b", "kind": "rating", "team": "Oklahoma"},
    ]
    assert rendered("{a}, {b}", ratings, texas_oklahoma_2005_elo, catalog) == (
        "Texas 1933, Oklahoma 1715"
    )
    data = json.loads(texas_oklahoma_2005_elo)
    assert (data["team_a"]["team_name"], data["team_b"]["team_name"]) == ("Texas", "Oklahoma")
    assert "Texas Tech" in {common["opponent_name"] for common in data["common_opponents"]}


@pytest.mark.parametrize(
    ("block_name", "team", "opponent", "expected"),
    [
        ("fsu_msu_2013", "Florida State", "Michigan State", "0.29"),
        ("texas_oklahoma_2005_elo", "Texas", "Oklahoma", "218"),
    ],
)
def test_rating_gap_prints_the_gap_between_the_displayed_ratings(
    request: pytest.FixtureRequest,
    catalog: tuple[TeamRecord, ...],
    block_name: str,
    team: str,
    opponent: str,
    expected: str,
) -> None:
    block: str = request.getfixturevalue(block_name)
    assert rendered("A gap of {gap}.", [_gap(team, opponent)], block, catalog) == (
        f"A gap of {expected}."
    )


def test_rating_gap_on_the_nfl_comparison(tmp_path: Path) -> None:
    db = make_sport_fixture_db(tmp_path)
    block = nfl_tie_comparison_block(db)
    nfl_catalog = catalog_of(db, "nfl")
    claims: list[dict[str, object]] = [
        {"id": "a", "kind": "rating", "team": LIMA_LIONS},
        {"id": "b", "kind": "rating", "team": KILO_KINGS},
        _gap(LIMA_LIONS, KILO_KINGS),
    ]
    assert rendered("{a} to {b}, a gap of {gap}.", claims, block, nfl_catalog) == (
        "Lima Lions 350.00 to Kilo Kings 250.00, a gap of 100.00."
    )


def test_rating_gap_is_the_difference_of_the_displayed_ratings_not_the_raw_difference(
    texas_oklahoma_2005_elo: str, catalog: tuple[TeamRecord, ...]
) -> None:
    block = _with_ratings(texas_oklahoma_2005_elo, 1933.4, 1714.6)
    claims: list[dict[str, object]] = [
        {"id": "a", "kind": "rating", "team": "Texas"},
        {"id": "b", "kind": "rating", "team": "Oklahoma"},
        _gap("Texas", "Oklahoma"),
    ]
    # The premise: the raw difference, displayed, would read one point more.
    assert display_value(Decimal("1933.4") - Decimal("1714.6"), "elo") == "219"
    assert rendered("{a} to {b}, a gap of {gap}.", claims, block, catalog) == (
        "Texas 1933 to Oklahoma 1715, a gap of 218."
    )


def test_rating_gap_prints_no_team_name_and_is_not_a_name_kind(
    texas_oklahoma_2005_elo: str, catalog: tuple[TeamRecord, ...]
) -> None:
    # "Texas" typed right after it is no "already prints the name" error.
    assert rendered(
        "It's {gap} Texas points clear of Oklahoma.",
        [_gap("Texas", "Oklahoma")],
        texas_oklahoma_2005_elo,
        catalog,
    ) == ("It's 218 Texas points clear of Oklahoma.")


def test_rating_gap_with_the_lower_rated_team_first_is_rejected_saying_who_rates_higher(
    fsu_msu_2013: str, catalog: tuple[TeamRecord, ...]
) -> None:
    errors = rejected(
        "A gap of {gap}.", [_gap("Michigan State", "Florida State")], fsu_msu_2013, catalog
    )
    assert len(errors) == 1, errors
    assert_an_error_says(
        errors, "Florida State rates higher", "Florida State 4.57", "Michigan State 4.28"
    )


def test_rating_gap_between_equal_displayed_ratings_is_rejected(
    texas_oklahoma_2005_elo: str, catalog: tuple[TeamRecord, ...]
) -> None:
    # 1933.4 and 1932.6 both display as 1933, though the raw ratings differ.
    block = _with_ratings(texas_oklahoma_2005_elo, 1933.4, 1932.6)
    for team, opponent in (("Texas", "Oklahoma"), ("Oklahoma", "Texas")):
        errors = rejected("A gap of {gap}.", [_gap(team, opponent)], block, catalog)
        assert len(errors) == 1, errors
        assert_an_error_says(errors, "print the same rating", "1933", "no gap", "a hair higher")


def test_rating_gap_on_a_team_case_is_rejected_saying_it_needs_a_comparison(
    catalog: tuple[TeamRecord, ...],
) -> None:
    block = cfb_team_case_block(2017, "Alabama")
    errors = rejected("A gap of {gap}.", [_gap("Alabama", "Georgia")], block, catalog)
    assert len(errors) == 1, errors
    assert_an_error_says(errors, '"gap"', "rating gap needs a comparison")


@pytest.mark.parametrize(
    ("team", "opponent"),
    [
        # a common opponent
        ("Texas", "Texas Tech"),
        ("Texas Tech", "Oklahoma"),
        # a team the block doesn't hold
        ("Texas", "Alabama"),
        # the same team twice
        ("Texas", "Texas"),
        # a compared team spelled another way
        ("texas", "Oklahoma"),
    ],
)
def test_rating_gap_on_any_other_team_is_rejected_naming_the_two_it_can_use(
    texas_oklahoma_2005_elo: str, catalog: tuple[TeamRecord, ...], team: str, opponent: str
) -> None:
    errors = rejected("A gap of {gap}.", [_gap(team, opponent)], texas_oklahoma_2005_elo, catalog)
    assert len(errors) == 1, errors
    assert_an_error_says(errors, '"gap"', "Texas and Oklahoma")


@pytest.mark.parametrize("missing", ["team", "opponent"])
def test_rating_gap_needs_both_teams(
    texas_oklahoma_2005_elo: str, catalog: tuple[TeamRecord, ...], missing: str
) -> None:
    claim = _gap("Texas", "Oklahoma")
    del claim[missing]
    errors = rejected("A gap of {gap}.", [claim], texas_oklahoma_2005_elo, catalog)
    assert_an_error_says(errors, '"gap"', f'needs "{missing}"')


@pytest.mark.parametrize("key", ["result", "week", "of"])
def test_rating_gap_takes_only_team_and_opponent(
    texas_oklahoma_2005_elo: str, catalog: tuple[TeamRecord, ...], key: str
) -> None:
    claim = {**_gap("Texas", "Oklahoma"), key: "W" if key == "result" else 1}
    errors = rejected("A gap of {gap}.", [claim], texas_oklahoma_2005_elo, catalog)
    assert_an_error_says(errors, f'does not take "{key}"', "id, kind, team, opponent")


def test_rating_gap_counts_toward_the_claim_cap(
    texas_oklahoma_2005_elo: str, catalog: tuple[TeamRecord, ...]
) -> None:
    claims: list[dict[str, object]] = [
        {"id": "ra", "kind": "record", "team": "Texas"},
        {"id": "rb", "kind": "record", "team": "Oklahoma"},
        {"id": "ta", "kind": "rating", "team": "Texas"},
        {"id": "tb", "kind": "rating", "team": "Oklahoma"},
        {"id": "ka", "kind": "rank", "team": "Texas"},
        {"id": "kb", "kind": "rank", "team": "Oklahoma"},
        {"id": "yr", "kind": "year"},
        {"id": "pa", "kind": "win_pct", "team": "Texas"},
    ]
    text = "{ra} {rb} {ta} {tb} {ka} {kb} {yr} {pa}. A gap of {gap}."
    assert rendered(text.replace(" A gap of {gap}.", ""), claims, texas_oklahoma_2005_elo, catalog)
    errors = rejected(text, [*claims, _gap("Texas", "Oklahoma")], texas_oklahoma_2005_elo, catalog)
    assert errors == (
        "submit_narration has 9 claims, over the limit of 8; keep only the figures that make "
        "the case",
    )


def test_rating_gap_is_in_the_tool_schema() -> None:
    claim_schema = tool_schema()["input_schema"]["properties"]["claims"]["items"]
    assert "rating_gap" in claim_schema["properties"]["kind"]["enum"]
    assert "rating_gap" in claim_schema["properties"]["kind"]["description"]
