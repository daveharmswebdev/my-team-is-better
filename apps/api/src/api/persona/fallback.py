"""Templated fallback lines (issue #4, coordinator-authored voice, used
only after 2 failed grounding attempts, or after a Claude API error).
Filled only from fields already in the evidence dataclass -- never
generated text -- so these are safe by construction.
"""

from __future__ import annotations

from api.models import ComparisonResultOut, QbVerdictEvidenceOut, QbVerdictPlayerOut, TeamCaseOut


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


_TIED_UP = "My mouth's a little tied up right now, but the numbers speak for themselves."


def qb_comparison_fallback_text(evidence: QbVerdictEvidenceOut) -> str:
    """The QB verdict's fallback (issue #451): a pure template of the
    evidence, in the same voice, that names the career winner and the peak
    winner (or says it's inconclusive and who didn't qualify), says the score
    counts since the data's first season, and says whose career began before
    it. Display names only, never a number but that season."""
    score = evidence.qb_score
    players = {"a": evidence.a, "b": evidence.b}
    since = (
        f"counting since {evidence.data_first_season}"
        if evidence.data_first_season is not None
        else "counting the seasons in the books"
    )
    if score.inconclusive is not None:
        if score.inconclusive == "neither_has_qualifying_season":
            verdict = (
                f"Neither {evidence.a.display_name} nor {evidence.b.display_name} has a "
                f"qualifying season on the QB score, {since}"
            )
        else:
            missing = evidence.a if score.inconclusive == "a_no_qualifying_season" else evidence.b
            verdict = (
                f"{missing.display_name} doesn't have a qualifying season on the QB score, {since}"
            )
        verdict += ", so it's inconclusive: no winner to call."
    else:
        career = _taker(players, score.career_winner, "career")
        peak = _taker(players, score.peak_winner, "peak")
        if score.career_winner is not None and score.career_winner == score.peak_winner:
            verdict = (
                f"{players[score.career_winner].display_name} takes the career and the peak on "
                f"the QB score, {since}."
            )
        else:
            verdict = f"{career} and {peak} on the QB score, {since}."
    cut_off = [p.display_name for p in (evidence.a, evidence.b) if p.coverage.cut_off_before]
    sentences = [verdict]
    if cut_off and evidence.data_first_season is not None:
        whose = (
            f"{cut_off[0]}'s career began"
            if len(cut_off) == 1
            else f"{cut_off[0]}'s and {cut_off[1]}'s careers began"
        )
        sentences.append(
            f"{whose} before {evidence.data_first_season}, and those seasons aren't in the books."
        )
    sentences.append(_TIED_UP)
    return " ".join(sentences)


def _taker(players: dict[str, QbVerdictPlayerOut], winner: str | None, measure: str) -> str:
    if winner is None:
        return f"nobody takes the {measure}, the two come out exactly level"
    return f"{players[winner].display_name} takes the {measure}"
