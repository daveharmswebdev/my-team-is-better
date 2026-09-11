"""Deterministic plain-English-plus-real-numbers "why this credit" copy for
a single opponent's `OpponentCredit.explanation` (issue #37).

Pure function, no db access: every number quoted here comes straight from
`cfb_strength.credit_math.single_game_credit` -- the same function
`ratings/keener.py` uses to compute the actual credit matrix -- so this
explanation can never drift from the number the rating is actually built
from.
"""

from __future__ import annotations

from cfb_strength.credit_math import CreditComponents, single_game_credit

_CLOSE_LOW = 45
_CLOSE_HIGH = 55


def _pct(components: CreditComponents) -> int:
    return round(components.raw_share * 100)


def _score(team_score: int, opponent_score: int) -> str:
    return f"{team_score}-{opponent_score}"


def _explain_single(team_score: int, opponent_score: int) -> str:
    components = single_game_credit(team_score, opponent_score)
    pct = _pct(components)
    score = _score(team_score, opponent_score)
    bonus = f"{components.bonus:.2f}"
    won = team_score > opponent_score

    if won:
        if components.capped:
            return (
                f"Ran them off the field, {score} — {pct}% of the points, capped "
                "at 85% so blowouts don't count extra past that. That earns the "
                f"flat 0.60 every win banks, plus a {bonus} margin bonus for the "
                "lopsided score."
            )
        if _CLOSE_LOW <= pct <= _CLOSE_HIGH:
            return (
                f"Snuck out a {score} win — {pct}% of the points, barely above "
                f"even. That's the flat 0.60 every win banks, plus just a "
                f"{bonus} margin bonus."
            )
        return (
            f"Beat them, {score} — {pct}% of the points. That's the flat 0.60 "
            f"every win banks, plus a {bonus} margin bonus for the margin."
        )

    if components.capped:
        return (
            f"Got run over, {score} — {pct}% of the points, clamped at the 15% "
            "floor. Still banks the flat 0.05 every loss keeps, nobody walks "
            "away with zero, but no margin bonus at that end of the scale."
        )
    if _CLOSE_LOW <= pct <= _CLOSE_HIGH:
        return (
            f"Lost a close one, {score} — {pct}% of the points, nearly even. "
            f"Still banks the flat 0.05 every loss keeps, plus a {bonus} "
            "margin bonus for keeping it competitive."
        )
    return (
        f"Lost, {score} — {pct}% of the points. Banks the flat 0.05 every loss "
        f"keeps, plus a {bonus} margin bonus."
    )


def _explain_pair(games: list[tuple[int, int]], won: bool) -> str:
    (ts1, os1), (ts2, os2) = games
    c1 = single_game_credit(ts1, os1)
    c2 = single_game_credit(ts2, os2)
    s1, s2 = _score(ts1, os1), _score(ts2, os2)
    verb = "Swept" if won else "Lost to"
    base = "0.60 win" if won else "0.05 loss"

    if c1.bonus == c2.bonus:
        return (
            f"{verb} them twice, {s1} and {s2} — the flat {base} baseline both "
            f"times, with the same {c1.bonus:.2f} margin bonus each game."
        )

    if c1.bonus > c2.bonus:
        bigger, smaller = "first", "second"
        pct_bigger, pct_smaller = _pct(c1), _pct(c2)
        bonus_bigger, bonus_smaller = c1.bonus, c2.bonus
    else:
        bigger, smaller = "second", "first"
        pct_bigger, pct_smaller = _pct(c2), _pct(c1)
        bonus_bigger, bonus_smaller = c2.bonus, c1.bonus

    return (
        f"{verb} them twice, {s1} and {s2} — the flat {base} baseline both "
        f"times, but the {bigger} game's bigger share ({pct_bigger}% vs. "
        f"{pct_smaller}%) earned a bigger margin bonus ({bonus_bigger:.2f} "
        f"vs. {bonus_smaller:.2f})."
    )


def _explain_fallback(games: list[tuple[int, int]]) -> str:
    wins = sum(1 for ts, os in games if ts > os)
    losses = sum(1 for ts, os in games if ts < os)
    parts = "; ".join(
        f"{_score(ts, os)} ({single_game_credit(ts, os).base:.2f} + "
        f"{single_game_credit(ts, os).bonus:.2f})"
        for ts, os in games
    )
    return f"Played them {len(games)} times ({wins}-{losses}) — {parts}."


def explain_credit(games: list[tuple[int, int]]) -> str:
    """games: (team_score, opponent_score) tuples for every game this team
    played against one specific opponent this season, in chronological
    order. Precondition: every tuple has team_score != opponent_score (the
    caller filters out ties/data-artifact equal-score rows before calling
    this -- see _opponent_result's existing tie-skip logic in proof.py for
    the precedent). Returns "" if games is empty."""
    if not games:
        return ""

    if len(games) == 1:
        return _explain_single(*games[0])

    if len(games) == 2:
        results = [ts > os for ts, os in games]
        if results[0] == results[1]:
            return _explain_pair(games, won=results[0])

    return _explain_fallback(games)
