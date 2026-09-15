"""Unit tests for `explain_credit` -- issue #37's deterministic
plain-English-plus-real-numbers "why this credit" line.

Every expected string here is verified by hand against
`cfb_strength.credit_math.single_game_credit`, the single source of truth
both the rating computation and this explanation call into -- see
`credit_explain.py`'s module docstring.
"""

from __future__ import annotations

from cfb_strength.credit_math import single_game_credit
from cfb_strength.evidence.credit_explain import explain_credit


def test_empty_games_returns_empty_string() -> None:
    assert explain_credit([]) == ""


def test_single_win_capped() -> None:
    assert explain_credit([(45, 3)]) == (
        "Ran them off the field, 45-3 — 94% of the points, capped at 85% so "
        "blowouts don't count extra past that. That earns the flat 0.60 every "
        "win banks, plus a 0.10 margin bonus for the lopsided score."
    )


def test_single_win_close() -> None:
    assert explain_credit([(24, 21)]) == (
        "Snuck out a 24-21 win — 53% of the points, barely above even. That's "
        "the flat 0.60 every win banks, plus just a 0.01 margin bonus."
    )


def test_single_win_comfortable() -> None:
    assert explain_credit([(30, 17)]) == (
        "Beat them, 30-17 — 64% of the points. That's the flat 0.60 every win "
        "banks, plus a 0.04 margin bonus for the margin."
    )


def test_single_loss_capped() -> None:
    assert explain_credit([(3, 52)]) == (
        "Got run over, 3-52 — 5% of the points, clamped at the 15% floor. "
        "Still banks the flat 0.05 every loss keeps, nobody walks away with "
        "zero, but no margin bonus at that end of the scale."
    )


def test_single_loss_close() -> None:
    assert explain_credit([(21, 24)]) == (
        "Lost a close one, 21-24 — 47% of the points, nearly even. Still "
        "banks the flat 0.05 every loss keeps, plus a 0.09 margin bonus for "
        "keeping it competitive."
    )


def test_single_loss_comfortable() -> None:
    assert explain_credit([(17, 30)]) == (
        "Lost, 17-30 — 36% of the points. Banks the flat 0.05 every loss "
        "keeps, plus a 0.06 margin bonus."
    )


def test_two_wins_bonuses_differ_names_bigger_game() -> None:
    assert explain_credit([(24, 17), (38, 13)]) == (
        "Swept them twice, 24-17 and 38-13 — the flat 0.60 win baseline both "
        "times, but the second game's bigger share (75% vs. 59%) earned a "
        "bigger margin bonus (0.07 vs. 0.03)."
    )


def test_two_losses_bonuses_differ_names_bigger_game() -> None:
    # (10, 20) -> raw_share = 1/3 -> pct 33; (20, 24) -> raw_share ~ 0.4545 -> pct 45
    # Compute bonuses directly rather than guessing, per the brief's instruction.
    g1 = (10, 20)
    g2 = (20, 24)
    c1 = single_game_credit(*g1)
    c2 = single_game_credit(*g2)
    assert c1.bonus != c2.bonus
    pct1 = round(c1.raw_share * 100)
    pct2 = round(c2.raw_share * 100)

    bigger_word = "first" if c1.bonus > c2.bonus else "second"
    pct_bigger, pct_smaller = (pct1, pct2) if c1.bonus > c2.bonus else (pct2, pct1)
    bonus_bigger, bonus_smaller = (
        (c1.bonus, c2.bonus) if c1.bonus > c2.bonus else (c2.bonus, c1.bonus)
    )

    expected = (
        f"Lost to them twice, {g1[0]}-{g1[1]} and {g2[0]}-{g2[1]} — the flat "
        f"0.05 loss baseline both times, but the {bigger_word} game's bigger "
        f"share ({pct_bigger}% vs. {pct_smaller}%) earned a bigger margin "
        f"bonus ({bonus_bigger:.2f} vs. {bonus_smaller:.2f})."
    )
    assert explain_credit([g1, g2]) == expected


def test_two_wins_equal_bonus() -> None:
    # Same points-share (14-7 doubled to 28-14) produces the same raw_share,
    # hence the same bonus, for both games.
    g1 = (14, 7)
    g2 = (28, 14)
    c1 = single_game_credit(*g1)
    c2 = single_game_credit(*g2)
    assert c1.raw_share == c2.raw_share
    assert c1.bonus == c2.bonus

    expected = (
        f"Swept them twice, {g1[0]}-{g1[1]} and {g2[0]}-{g2[1]} — the flat "
        f"0.60 win baseline both times, with the same {c1.bonus:.2f} margin "
        "bonus each game."
    )
    assert explain_credit([g1, g2]) == expected


def test_two_losses_equal_bonus() -> None:
    g1 = (7, 14)
    g2 = (14, 28)
    c1 = single_game_credit(*g1)
    c2 = single_game_credit(*g2)
    assert c1.raw_share == c2.raw_share
    assert c1.bonus == c2.bonus

    expected = (
        f"Lost to them twice, {g1[0]}-{g1[1]} and {g2[0]}-{g2[1]} — the flat "
        f"0.05 loss baseline both times, with the same {c1.bonus:.2f} margin "
        "bonus each game."
    )
    assert explain_credit([g1, g2]) == expected


def test_mixed_record_two_games_falls_back_to_mechanical_listing() -> None:
    g1 = (30, 10)  # win
    g2 = (10, 30)  # loss
    c1 = single_game_credit(*g1)
    c2 = single_game_credit(*g2)

    expected = (
        "Played them 2 times (1-1) — "
        f"{g1[0]}-{g1[1]} ({c1.base:.2f} + {c1.bonus:.2f}); "
        f"{g2[0]}-{g2[1]} ({c2.base:.2f} + {c2.bonus:.2f})."
    )
    assert explain_credit([g1, g2]) == expected


def test_single_tie_is_worded_as_a_tie() -> None:
    """Issue #83: before, a tie fell through to the loss branch ("Lost a
    close one, 26-26 ... the flat 0.05 every loss keeps"), which is wrong on
    both counts -- single_game_credit scores a tie at a flat 0.50."""
    c = single_game_credit(26, 26)
    assert (c.base, c.bonus) == (0.5, 0.0)
    assert explain_credit([(26, 26)]) == (
        "Tied them, 26-26 — 50% of the points. A tie banks a flat 0.50, "
        "with no margin bonus either way."
    )


def test_two_ties_are_worded_as_ties() -> None:
    assert explain_credit([(20, 20), (17, 17)]) == (
        "Tied them twice, 20-20 and 17-17 — the flat 0.50 tie baseline both "
        "times, with the same 0.00 margin bonus each game."
    )


def test_win_and_tie_record_is_w_l_t() -> None:
    """The fallback's record string reads W-L-T once a tie is in it. The
    2013 Packers-Vikings pair (44-31, then 26-26) is the real case."""
    games = [(44, 31), (26, 26)]
    c1, c2 = (single_game_credit(*g) for g in games)
    assert explain_credit(games) == (
        "Played them 2 times (1-0-1) — "
        f"44-31 ({c1.base:.2f} + {c1.bonus:.2f}); "
        f"26-26 ({c2.base:.2f} + {c2.bonus:.2f})."
    )


def test_record_without_a_tie_stays_w_l() -> None:
    """Ties == 0 keeps the pre-#83 "(W-L)" string, so no CFB copy changes."""
    games = [(30, 10), (10, 30), (21, 14)]
    assert explain_credit(games).startswith("Played them 3 times (2-1) — ")
    assert "-0)" not in explain_credit(games).split(" — ")[0]


def test_three_games_falls_back_to_mechanical_listing() -> None:
    games = [(30, 10), (20, 21), (14, 7)]
    creds = [single_game_credit(*g) for g in games]
    wins = sum(1 for pf, pa in games if pf > pa)
    losses = sum(1 for pf, pa in games if pf < pa)

    parts = "; ".join(
        f"{pf}-{pa} ({c.base:.2f} + {c.bonus:.2f})" for (pf, pa), c in zip(games, creds)
    )
    expected = f"Played them {len(games)} times ({wins}-{losses}) — {parts}."
    assert explain_credit(games) == expected
