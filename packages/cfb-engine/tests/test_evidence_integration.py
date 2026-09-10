"""Integration coverage for `cfb_strength.evidence.proof` against real
fixture data: exception behavior (`AmbiguousTeamError`, `UnknownYearError`,
`SameTeamComparisonError`) and the head-to-head evidence shape
`build_comparison` produces for the 2005 Texas/USC case.

Uses `regression_conn` (a writable copy of tests/fixtures/cfb_regression.sqlite3)
with ratings freshly computed by the real `compute_and_store` pipeline --
never a canned `ratings` table, and never the live `data/cfb.sqlite3`.
"""

from __future__ import annotations

import sqlite3

import pytest

from cfb_strength.contracts import (
    AmbiguousTeamError,
    ComparisonResult,
    SameTeamComparisonError,
    TeamCase,
    UnknownYearError,
)
from cfb_strength.evidence.proof import (
    build_comparison,
    build_team_case,
    list_available_years,
    resolve_team,
)
from cfb_strength.ratings.compute_ratings import compute_and_store


@pytest.fixture
def rated_conn(regression_conn: sqlite3.Connection) -> sqlite3.Connection:
    """regression_conn with 2005 ratings computed via the real pipeline."""
    compute_and_store(regression_conn, 2005, "keener")
    return regression_conn


def test_list_available_years_reflects_what_was_computed(rated_conn: sqlite3.Connection) -> None:
    years = list_available_years(rated_conn, "keener")
    assert years == [2005]


def test_unknown_year_raises_with_available_years_listed(rated_conn: sqlite3.Connection) -> None:
    with pytest.raises(UnknownYearError) as exc_info:
        resolve_team(rated_conn, 1999, "Texas", method="keener")
    assert exc_info.value.year == 1999
    assert exc_info.value.available_years == [2005]


def test_unknown_year_raises_for_build_team_case_too(rated_conn: sqlite3.Connection) -> None:
    with pytest.raises(UnknownYearError):
        build_team_case(rated_conn, 2099, "Texas", method="keener")


def test_ambiguous_team_query_raises_with_candidates(rated_conn: sqlite3.Connection) -> None:
    # "Texas" is an exact unique match, but a bare substring like "State"
    # matches many rated 2005 teams (Ohio State, Penn State, Florida State,
    # Michigan State, ...) and must be reported as ambiguous rather than
    # silently picking one.
    with pytest.raises(AmbiguousTeamError) as exc_info:
        resolve_team(rated_conn, 2005, "State", method="keener")
    assert exc_info.value.query == "State"
    assert len(exc_info.value.candidates) > 1


def test_same_team_comparison_raises(rated_conn: sqlite3.Connection) -> None:
    with pytest.raises(SameTeamComparisonError) as exc_info:
        build_comparison(rated_conn, 2005, "Texas", "Texas", method="keener")
    assert exc_info.value.team_name == "Texas"


def test_same_team_comparison_raises_even_via_different_query_strings(
    rated_conn: sqlite3.Connection,
) -> None:
    # Both queries resolve to the same team_id even though the strings
    # differ in case/whitespace -- the check is on resolved id, not on
    # literal query equality.
    with pytest.raises(SameTeamComparisonError):
        build_comparison(rated_conn, 2005, "texas", "  Texas  ", method="keener")


def test_resolve_team_exact_match_is_case_and_whitespace_insensitive(
    rated_conn: sqlite3.Connection,
) -> None:
    lower = resolve_team(rated_conn, 2005, "texas", method="keener")
    padded = resolve_team(rated_conn, 2005, "  Texas  ", method="keener")
    assert lower == padded


def test_build_team_case_returns_teamcase_dataclass(rated_conn: sqlite3.Connection) -> None:
    case = build_team_case(rated_conn, 2005, "Texas", method="keener")
    assert isinstance(case, TeamCase)
    assert case.team_name == "Texas"
    assert case.year == 2005
    assert case.method == "keener"


def test_build_comparison_texas_vs_usc_cites_head_to_head_rose_bowl(
    rated_conn: sqlite3.Connection,
) -> None:
    """The sufficiency rubric requires the MCP layer to cite the USC win
    unprompted for "greatest team of 2005" -- this checks the evidence layer
    actually produces that citation in build_comparison's head_to_head shape
    (get_champion/get_team_season go through build_team_case, checked
    separately in test_golden_dataset_regressions.py; this checks the other
    evidence entry point, build_comparison, gets the same real game right)."""
    comparison = build_comparison(rated_conn, 2005, "Texas", "USC", method="keener")
    assert isinstance(comparison, ComparisonResult)

    assert comparison.head_to_head["played"] is True
    meetings = comparison.head_to_head["meetings"]
    assert len(meetings) == 1
    meeting = meetings[0]
    assert meeting["home_team"] == "Texas"
    assert meeting["away_team"] == "USC"
    assert meeting["home_points"] == 41
    assert meeting["away_points"] == 38
    assert meeting["winner"] == "Texas"
    assert meeting["neutral_site"] is True

    assert "Texas" in comparison.verdict
    assert "USC" in comparison.verdict
    assert comparison.rating_diff > 0  # Texas rates strictly higher than USC
