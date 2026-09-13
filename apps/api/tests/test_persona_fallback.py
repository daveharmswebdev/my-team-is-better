"""Failing-first tests for `api.persona.fallback`'s templated fallback
lines (issue #4, used only after 2 failed grounding attempts). Filled only
from fields already in the evidence dataclass -- never generated text --
so these are checked against real `TeamCaseOut`/`ComparisonResultOut`
instances, not hand-typed strings.
"""

from __future__ import annotations

from api.models import (
    ComparisonResultOut,
    ComparisonTeamSummaryOut,
    HeadToHeadOut,
    RatingBreakdownOut,
    TeamCaseOut,
)
from api.persona.fallback import comparison_fallback_text, team_case_fallback_text


def _team_case(**overrides: object) -> TeamCaseOut:
    base: dict[str, object] = {
        "year": 2005,
        "method": "keener",
        "team_id": 1,
        "team_name": "Texas",
        "rank": 1,
        "rating": 0.95,
        "wins": 13,
        "losses": 0,
        "ties": 0,
        "rating_breakdown": RatingBreakdownOut(entries=[], residual_contribution=0.0),
        "games": [],
        "quality_wins": [],
        "worst_loss": None,
    }
    base.update(overrides)
    return TeamCaseOut(**base)  # type: ignore[arg-type]


def test_team_case_fallback_uses_only_evidence_fields() -> None:
    case = _team_case(team_name="Texas", year=2005, wins=13, losses=0, rank=1)

    text = team_case_fallback_text(case)

    assert "Texas" in text
    assert "13" in text and "0" in text
    assert "2005" in text
    assert "#1" in text
    assert "numbers speak for themselves" in text


def test_comparison_fallback_uses_only_evidence_fields() -> None:
    comparison = ComparisonResultOut(
        year=2005,
        method="keener",
        team_a=ComparisonTeamSummaryOut(
            team_id=1,
            team_name="Texas",
            rank=1,
            rating=0.95,
            wins=13,
            losses=0,
            ties=0,
            rating_breakdown=RatingBreakdownOut(entries=[], residual_contribution=0.0),
            quality_wins=[],
            worst_loss=None,
        ),
        team_b=ComparisonTeamSummaryOut(
            team_id=2,
            team_name="USC",
            rank=2,
            rating=0.9,
            wins=12,
            losses=1,
            ties=0,
            rating_breakdown=RatingBreakdownOut(entries=[], residual_contribution=0.0),
            quality_wins=[],
            worst_loss=None,
        ),
        head_to_head=HeadToHeadOut(played=True, meetings=[]),
        common_opponents=[],
        rating_diff=0.05,
        verdict="Texas rates higher.",
    )

    text = comparison_fallback_text(comparison)

    assert "Texas" in text and "USC" in text
    assert "13" in text and "12" in text
    assert "2005" in text


# ---------------------------------------------------------------------------
# issue #83: a tie is part of the record. W-L-T once ties > 0, and exactly
# the old W-L text when there are none (the engine's own record rule).
# ---------------------------------------------------------------------------


def _summary(**overrides: object) -> ComparisonTeamSummaryOut:
    base: dict[str, object] = {
        "team_id": 1,
        "team_name": "Texas",
        "rank": 1,
        "rating": 0.95,
        "wins": 13,
        "losses": 0,
        "ties": 0,
        "rating_breakdown": RatingBreakdownOut(entries=[], residual_contribution=0.0),
        "quality_wins": [],
        "worst_loss": None,
    }
    base.update(overrides)
    return ComparisonTeamSummaryOut(**base)  # type: ignore[arg-type]


def _comparison(
    team_a: ComparisonTeamSummaryOut, team_b: ComparisonTeamSummaryOut, year: int
) -> ComparisonResultOut:
    return ComparisonResultOut(
        year=year,
        method="keener",
        team_a=team_a,
        team_b=team_b,
        head_to_head=HeadToHeadOut(played=False, meetings=[]),
        common_opponents=[],
        rating_diff=0.05,
        verdict="",
    )


def test_team_case_fallback_states_a_tied_teams_w_l_t_record() -> None:
    case = _team_case(team_name="Cincinnati Bengals", year=2016, wins=6, losses=9, ties=1, rank=20)

    text = team_case_fallback_text(case)

    assert text.startswith("Cincinnati Bengals finished 6-9-1 in 2016, ranked #20")


def test_team_case_fallback_without_ties_is_unchanged() -> None:
    case = _team_case(team_name="Texas", year=2005, wins=13, losses=0, ties=0, rank=1)

    assert team_case_fallback_text(case) == (
        "Texas finished 13-0 in 2005, ranked #1 -- you can see the full case "
        "below. My mouth's a little tied up right now, but the numbers speak "
        "for themselves."
    )


def test_comparison_fallback_states_a_tied_teams_w_l_t_record() -> None:
    comparison = _comparison(
        _summary(team_name="Green Bay Packers", wins=8, losses=7, ties=1),
        _summary(team_id=2, team_name="Minnesota Vikings", wins=5, losses=10, ties=1),
        2013,
    )

    text = comparison_fallback_text(comparison)

    assert text.startswith("Green Bay Packers went 8-7-1 and Minnesota Vikings went 5-10-1 in 2013")


def test_comparison_fallback_mixes_w_l_t_and_w_l_per_team() -> None:
    comparison = _comparison(
        _summary(team_name="Green Bay Packers", wins=8, losses=7, ties=1),
        _summary(team_id=2, team_name="Chicago Bears", wins=8, losses=8, ties=0),
        2013,
    )

    text = comparison_fallback_text(comparison)

    assert text.startswith("Green Bay Packers went 8-7-1 and Chicago Bears went 8-8 in 2013")


def test_comparison_fallback_without_ties_is_unchanged() -> None:
    comparison = _comparison(
        _summary(),
        _summary(team_id=2, team_name="USC", rank=2, rating=0.9, wins=12, losses=1),
        2005,
    )

    assert comparison_fallback_text(comparison) == (
        "Texas went 13-0 and USC went 12-1 in 2005 -- you can see the full "
        "breakdown below. My mouth's a little tied up right now, but the "
        "numbers speak for themselves."
    )
