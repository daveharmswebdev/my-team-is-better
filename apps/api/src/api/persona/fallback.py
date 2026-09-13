"""Templated fallback lines (issue #4, coordinator-authored voice, used
only after 2 failed grounding attempts, or after a Claude API error).
Filled only from fields already in the evidence dataclass -- never
generated text -- so these are safe by construction.
"""

from __future__ import annotations

from api.models import ComparisonResultOut, TeamCaseOut


def _record(wins: int, losses: int, ties: int) -> str:
    """W-L-T once a tie is in the record, plain W-L otherwise (issue #83) --
    the engine's own record rule, so a tied team reads "6-9-1" here exactly as
    it does in the evidence prose, and a tie-less one still reads "13-0"."""
    return f"{wins}-{losses}-{ties}" if ties else f"{wins}-{losses}"


def team_case_fallback_text(case: TeamCaseOut) -> str:
    return (
        f"{case.team_name} finished {_record(case.wins, case.losses, case.ties)} "
        f"in {case.year}, ranked #{case.rank} -- you can see the full case below. "
        "My mouth's a little tied up right now, but the numbers speak for themselves."
    )


def comparison_fallback_text(comparison: ComparisonResultOut) -> str:
    """Compare-route analogue of `team_case_fallback_text` -- issue #4's
    brief leaves the exact wording for two teams to this implementation,
    kept terse and in the same fallback spirit.
    """
    team_a = comparison.team_a
    team_b = comparison.team_b
    return (
        f"{team_a.team_name} went {_record(team_a.wins, team_a.losses, team_a.ties)} and "
        f"{team_b.team_name} went {_record(team_b.wins, team_b.losses, team_b.ties)} in "
        f"{comparison.year} -- you can see the full breakdown below. My "
        "mouth's a little tied up right now, but the numbers speak for "
        "themselves."
    )
