"""Round 3 of #457: the independent review's round-2 findings R2-1 to R2-4
and the fold-in, one test per evidence sentence, on real fixture blocks.

* Warner/McNair: Warner wins both (career 1.65 clear, peak 0.33 clear).
* "decisive": Warner/McNair rescored to career 12.0-0.5, peak 1.3-0.2.
* "Brady/Manning": Manning/Warner rescored to the live figures, peak 0.04
  close (Manning), career 0.10 close (Warner as "Brady").
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
WB: dict[str, object] = {"id": "wb", "kind": "winner", "measure": "both"}
MARGIN: dict[str, object] = {"id": "m", "kind": "margin", "measure": "career", "player": "Warner"}


def _wm() -> str:
    return qb_block(KURT_WARNER, STEVE_MCNAIR)


def _decisive() -> str:
    return rescored_block(KURT_WARNER, STEVE_MCNAIR, career=(12.0, 0.5), peak=(1.3, 0.2))


def _brady_manning() -> str:
    return rescored_block(PEYTON_MANNING, KURT_WARNER, career=(18.09, 18.19), peak=(1.77, 1.73))


# ---------------------------------------------------------------------------
# R2-1: a negator must govern the phrase
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "No doubt Manning runs away with the peak.",
        "There's no question he runs away with the peak.",
        "No surprise Manning runs away with the peak.",
        "Nobody's surprised Manning runs away with the peak.",
        "No joke Manning runs away with the peak.",
    ],
)
def test_r2_1_an_idiom_negates_no_runaway(text: str) -> None:
    errors = qb_rejected(_brady_manning(), text)
    assert_an_error_says(errors, "the peak margin is 0.04, a close one", "no runaway words")


def test_r2_1_no_lie_negates_no_photo_finish() -> None:
    errors = qb_rejected(_decisive(), "No lie Warner squeaks by on the career.")
    assert_an_error_says(errors, "the career margin is 11.50", "no photo-finish words")


@pytest.mark.parametrize(
    "text",
    [
        "It's no photo finish.",
        "This was no squeaker.",
        "No photo finish here: Warner runs away with it.",
        "Forget by a nose, Warner runs away with the career.",
    ],
)
def test_r2_1_a_governing_negator_still_passes_on_decisive(text: str) -> None:
    assert qb_rendered_verdict(_decisive(), text) == text


def test_r2_1_doesnt_run_away_still_passes_on_close() -> None:
    text = "Manning doesn't run away with the peak, he takes it by a nose."
    assert qb_rendered_verdict(_brady_manning(), text) == text


# ---------------------------------------------------------------------------
# R2-2: missing-season speculation is rejected again; only the listener
# shape "if you had <name>," is exempt
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,claims",
    [
        ("If we had his whole career, McNair might look better.", []),
        ("If they counted his whole career, it'd look different.", []),
        ("If the books had everything, McNair looks better.", []),
        ("If we had all of it, McNair looks better.", []),
        ("If we had the full picture, McNair looks better.", []),
        (
            "If they counted his {cs} season, McNair looks better.",
            [{"id": "cs", "kind": "career_start", "player": "McNair"}],
        ),
    ],
)
def test_r2_2_if_the_data_had_more_is_speculation(
    text: str, claims: list[dict[str, object]]
) -> None:
    assert_an_error_says(qb_rejected(_wm(), text, *claims), "missing seasons")


def test_r2_2_if_you_had_a_player_is_still_prose() -> None:
    text = "If you had McNair, you'd be crying now."
    assert qb_rendered_verdict(_wm(), text) == text


# ---------------------------------------------------------------------------
# R2-3: ", and" carries the imperative conditional too
# ---------------------------------------------------------------------------


def test_r2_3_a_comma_and_after_an_imperative_is_still_a_conditional() -> None:
    errors = qb_rejected(_wm(), "Give McNair his Houston seasons, and it's a different story.")
    assert_an_error_says(errors, "different story", "missing seasons")


def test_r2_3_a_comma_and_after_a_statement_is_not() -> None:
    text = "Warner takes both with something left over, and McNair's a different story."
    assert qb_rendered_verdict(_wm(), text) == text


# ---------------------------------------------------------------------------
# R2-4: a trail word counts only in the margin's own clause
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "McNair went down swinging, but he's ahead by {m}.",
        "McNair lost some games, sure, but he's up by {m}.",
    ],
)
def test_r2_4_a_trail_word_in_an_earlier_clause_does_not_count(text: str) -> None:
    errors = qb_rejected(_wm(), text, MARGIN, WB, YEAR)
    assert_an_error_says(errors, "{m}", "Kurt Warner's figure", "Steve McNair")


# ---------------------------------------------------------------------------
# fold-in: the passive and a post-margin "short"/"behind" are trail shapes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,shown",
    [
        ("McNair gets beat by {m} on the career.", "McNair gets beat by 1.65 on the career."),
        ("McNair falls {m} short on the career.", "McNair falls 1.65 short on the career."),
        ("McNair finishes {m} behind.", "McNair finishes 1.65 behind."),
    ],
)
def test_fold_in_the_loser_described_as_losing_by_the_margin_passes(text: str, shown: str) -> None:
    rendered = qb_rendered(_wm(), f"{text} Since {{yr}}, {{wb}} takes both.", MARGIN, WB, YEAR)
    assert rendered == f"{shown} Since 1999, Warner takes both."


def test_fold_in_ahead_after_the_margin_is_still_the_loser_ahead() -> None:
    errors = qb_rejected(_wm(), "McNair finishes {m} ahead.", MARGIN, WB, YEAR)
    assert_an_error_says(errors, "{m}", "Kurt Warner's figure")
