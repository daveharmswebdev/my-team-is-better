"""Round 3 of #463: two review findings on round B's checker.

1. The opening-clause rule for "a different story" (#462) fires only when
   the opening clause is about the missing seasons (it names seasons, years,
   a rookie year, an early or earlier career, a team stint, or the time
   before the data). Any other "if"/"with" opener ("If you look at the
   peak, it's a different story") is a true split narration.
2. "not just a blowout" asserts a blowout: "just" is no filler between a
   negator and a margin word.

Blocks as in `test_persona_qb_463_tiers.py` (real fixture blocks rescored to
the live figures); Warner/McNair names throughout.
"""

from __future__ import annotations

import pytest
from fixtures.qb_blocks import (
    KURT_WARNER,
    PEYTON_MANNING,
    STEVE_MCNAIR,
    assert_an_error_says,
    qb_block,
    qb_rejected,
    qb_rendered,
    qb_rendered_verdict,
    rescored_block,
)

YEAR: dict[str, object] = {"id": "yr", "kind": "year"}
W_BOTH: dict[str, object] = {"id": "w", "kind": "winner", "measure": "both"}
C_CAREER: dict[str, object] = {"id": "c", "kind": "winner", "measure": "career"}
P_PEAK: dict[str, object] = {"id": "p", "kind": "winner", "measure": "peak"}


def _herbert_mayfield() -> str:
    """Clear on both (career +2.91, peak +0.18), Warner sweeps."""
    return rescored_block(
        KURT_WARNER, STEVE_MCNAIR, career=(2.1171, -0.7880), peak=(0.4393, 0.2644)
    )


def _brady_flacco() -> str:
    """Decisive on both, Warner sweeps."""
    return rescored_block(
        KURT_WARNER, STEVE_MCNAIR, career=(18.1914, -4.4199), peak=(1.7261, 0.1280)
    )


def _brady_manning() -> str:
    """Close on both, split: Warner the career, McNair the peak."""
    return rescored_block(
        KURT_WARNER, STEVE_MCNAIR, career=(18.1914, 18.0904), peak=(1.7261, 1.7704)
    )


def _manning_warner() -> str:
    return rescored_block(PEYTON_MANNING, KURT_WARNER, career=(18.09, 18.19), peak=(1.77, 1.73))


def _wm() -> str:
    """Warner/McNair as the fixture has it: clear on both."""
    return qb_block(KURT_WARNER, STEVE_MCNAIR)


# ---------------------------------------------------------------------------
# BLOCKING 1: an opener that isn't about the missing seasons
# ---------------------------------------------------------------------------


def test_split_block_if_you_look_at_the_peak_is_accepted() -> None:
    text = (
        "{c} takes the career by a nose. If you look at the peak, it's a different "
        "story: {p} squeaks by. Counting since {yr}."
    )
    rendered = qb_rendered(_brady_manning(), text, C_CAREER, P_PEAK, YEAR)
    assert "If you look at the peak, it's a different story: McNair squeaks by." in rendered


@pytest.mark.parametrize(
    "text",
    [
        "With the peak, it's a different story.",
        "With that said, McNair's a different story.",
        "If we're being honest, McNair's a different story.",
        "Counting the peak, it's a different story.",
        "With the career settled, the peak is a different story.",
        "Give Warner the career; the peak's a different story.",
        "Add it up and the career is Warner's; the peak's a different story.",
    ],
)
def test_an_opener_off_the_missing_seasons_is_no_speculation(text: str) -> None:
    assert qb_rendered_verdict(_wm(), text) == text


@pytest.mark.parametrize(
    "text",
    [
        "If you count his Houston years, it's a different story.",
        "With his Houston years in, it's a different story.",
        "Count his Houston years, and it's a different story.",
        "Give him his early years back and it's a different story.",
        "If you count his rookie year, it's a different story.",
        "With his early career, it's a different story.",
        "If you go back before the data, it's a different story.",
        "With his Houston seasons, it's a different story.",
    ],
)
def test_an_opener_about_the_missing_seasons_is_still_speculation(text: str) -> None:
    assert_an_error_says(qb_rejected(_wm(), text), "different story", "missing seasons")


def test_with_room_to_spare_is_still_the_next_topic() -> None:
    text = "With room to spare, Warner takes both, and McNair's a different story."
    assert qb_rendered_verdict(_wm(), text) == text


# ---------------------------------------------------------------------------
# BLOCKING 2: "not just a blowout" asserts a blowout
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("opener", ["It's not just a blowout.", "It isn't just a blowout."])
def test_not_just_a_blowout_is_rejected_on_a_clear_sweep(opener: str) -> None:
    errors = qb_rejected(
        _herbert_mayfield(), f"{opener} {{w}} takes both, counting since {{yr}}.", W_BOTH, YEAR
    )
    assert_an_error_says(errors, '"blowout"', "a clear one")


def test_not_a_photo_finish_still_passes_on_a_decisive_margin() -> None:
    text = "It's not a photo finish."
    assert qb_rendered_verdict(_brady_flacco(), text) == text


@pytest.mark.parametrize("text", ["It's not a blowout.", "Manning did not run away with the peak."])
def test_a_negated_hard_word_still_passes_on_a_close_margin(text: str) -> None:
    assert qb_rendered_verdict(_manning_warner(), text) == text


@pytest.mark.parametrize(
    "text", ["Warner did not run away with the career.", "This was never a blowout."]
)
def test_a_negated_hard_word_still_passes_on_a_clear_margin(text: str) -> None:
    assert qb_rendered_verdict(_wm(), text) == text
