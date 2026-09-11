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
    ComparisonTeamSummary,
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

    assert comparison.head_to_head.played is True
    meetings = comparison.head_to_head.meetings
    assert len(meetings) == 1
    meeting = meetings[0]
    assert meeting.home_team == "Texas"
    assert meeting.away_team == "USC"
    assert meeting.home_points == 41
    assert meeting.away_points == 38
    assert meeting.winner == "Texas"
    assert meeting.neutral_site is True

    assert "Texas" in comparison.verdict
    assert "USC" in comparison.verdict
    assert comparison.rating_diff > 0  # Texas rates strictly higher than USC


def test_build_comparison_team_summaries_and_common_opponents_are_typed(
    rated_conn: sqlite3.Connection,
) -> None:
    """Issue #21: `team_a`/`team_b`/`common_opponents` used to be untyped
    `dict[str, object]`, forcing `apps/web` to render a raw generic dump
    instead of a curated summary. This locks in that they are now real
    dataclasses with attribute access, not dicts."""
    comparison = build_comparison(rated_conn, 2005, "Texas", "USC", method="keener")

    assert isinstance(comparison.team_a, ComparisonTeamSummary)
    assert isinstance(comparison.team_b, ComparisonTeamSummary)
    assert comparison.team_a.team_name == "Texas"
    assert comparison.team_a.rank >= 1
    assert isinstance(comparison.team_a.rating, float)
    assert comparison.team_a.wins >= 0

    # Texas and USC both played common opponents in the 2005 season
    # (e.g. conference/OOC overlap) -- assert the shape, not specific teams.
    for opponent in comparison.common_opponents:
        assert opponent.team_a_result in ("W", "L")
        assert opponent.team_b_result in ("W", "L")
        assert isinstance(opponent.opponent_name, str)


def test_build_team_case_rating_breakdown_has_entries_for_real_opponents(
    rated_conn: sqlite3.Connection,
) -> None:
    """Issue #31: TeamCase.rating_breakdown surfaces the per-opponent credit
    decomposition computed and persisted by compute_and_store."""
    case = build_team_case(rated_conn, 2005, "Texas", method="keener")

    assert case.rating_breakdown.entries, "Texas played games in 2005; expected breakdown entries"

    schedule_opponent_ids = {o.opponent_team_id for o in case.games}
    schedule_names_by_id = {o.opponent_team_id: o.opponent_name for o in case.games}
    for entry in case.rating_breakdown.entries:
        assert entry.opponent_team_id in schedule_opponent_ids
        # Issue #31 follow-up: OpponentCredit.opponent_name must be resolved
        # to the opponent's real school name (same teams-table join
        # _opponent_result already does for OpponentResult), not left at its
        # contracts.py default of "".
        assert entry.opponent_name
        assert entry.opponent_name == schedule_names_by_id[entry.opponent_team_id]


def test_build_team_case_rating_breakdown_reconstructs_rating(
    rated_conn: sqlite3.Connection,
) -> None:
    """The decomposition is exact by construction upstream: entries'
    contributions plus the residual must sum back to the team's rating."""
    case = build_team_case(rated_conn, 2005, "Texas", method="keener")

    total = sum(e.contribution for e in case.rating_breakdown.entries)
    total += case.rating_breakdown.residual_contribution

    assert total == pytest.approx(case.rating, abs=1e-6)


def test_build_comparison_team_summaries_have_rating_breakdowns(
    rated_conn: sqlite3.Connection,
) -> None:
    """build_comparison's ComparisonTeamSummary (via _case_summary) must
    carry the same rating_breakdown as build_team_case, not just
    build_team_case's own return value."""
    comparison = build_comparison(rated_conn, 2005, "Texas", "USC", method="keener")

    for summary in (comparison.team_a, comparison.team_b):
        assert summary.rating_breakdown.entries
        total = sum(e.contribution for e in summary.rating_breakdown.entries)
        total += summary.rating_breakdown.residual_contribution
        assert total == pytest.approx(summary.rating, abs=1e-6)


def test_rating_breakdown_degrades_gracefully_with_no_rows(
    rated_conn: sqlite3.Connection,
) -> None:
    """A team rated but with no rating_breakdowns rows (e.g. a fixture db
    predating this table, or an id with no persisted breakdown) should
    produce an empty RatingBreakdown rather than raising."""
    from cfb_strength.evidence.proof import _rating_breakdown

    breakdown = _rating_breakdown(rated_conn, 2005, "keener", team_id=-1)
    assert breakdown.entries == []
    assert breakdown.residual_contribution == 0.0
