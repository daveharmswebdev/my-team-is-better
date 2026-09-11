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
        team_a=ComparisonTeamSummaryOut(
            team_id=1,
            team_name="Texas",
            rank=1,
            rating=0.95,
            wins=13,
            losses=0,
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
