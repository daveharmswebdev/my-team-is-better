"""Round 2 of #457: the independent review's blocking findings B1-B6 and the
folded-in P1, one test per evidence sentence, on real fixture blocks.

* Warner/McNair: Warner wins both (career 1.65 clear, peak 0.33 clear).
* Manning/McNair: Manning wins both (career 0.83 close, peak 0.17 clear).
* "decisive": Warner/McNair rescored to career 12.0-0.5, peak 1.3-0.2.
* "career decisive, peak clear": career 12.0-0.5, peak 0.6-0.2 (0.40).
* "career decisive, peak close": career 12.0-0.5, peak 0.30-0.25 (0.05).
"""

from __future__ import annotations

from collections.abc import Callable

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


def _mm() -> str:
    return qb_block(PEYTON_MANNING, STEVE_MCNAIR)


def _decisive() -> str:
    return rescored_block(KURT_WARNER, STEVE_MCNAIR, career=(12.0, 0.5), peak=(1.3, 0.2))


def _career_decisive_peak_clear() -> str:
    return rescored_block(KURT_WARNER, STEVE_MCNAIR, career=(12.0, 0.5), peak=(0.6, 0.2))


def _career_decisive_peak_close() -> str:
    return rescored_block(KURT_WARNER, STEVE_MCNAIR, career=(12.0, 0.5), peak=(0.30, 0.25))


# ---------------------------------------------------------------------------
# B1: a margin beside the loser is the wrong winner again
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "McNair's ahead by {m}.",
        "McNair by {m} on the career.",
        "McNair is up by {m}.",
        "McNair, by {m}.",
        "McNair finishes {m} ahead.",
        "McNair is {m} better on the career.",
    ],
)
def test_b1_a_margin_beside_the_loser_is_rejected(text: str) -> None:
    errors = qb_rejected(_wm(), text, MARGIN, WB, YEAR)
    assert_an_error_says(errors, "{m}", "Kurt Warner's figure", "Steve McNair")


@pytest.mark.parametrize(
    "text,shown",
    [
        ("{wb} beats McNair by {m} on the career.", "Warner beats McNair by 1.65 on the career."),
        ("Warner tops McNair by {m} on the career.", "Warner tops McNair by 1.65 on the career."),
        ("Warner over McNair by {m}.", "Warner over McNair by 1.65."),
        ("McNair trails by {m}.", "McNair trails by 1.65."),
        ("McNair is behind by {m}.", "McNair is behind by 1.65."),
        ("McNair comes up short by {m}.", "McNair comes up short by 1.65."),
    ],
)
def test_b1_a_margin_after_a_trail_or_object_verb_passes(text: str, shown: str) -> None:
    rendered = qb_rendered(_wm(), f"{text} Since {{yr}}, {{wb}} takes both.", MARGIN, WB, YEAR)
    assert rendered == f"{shown} Since 1999, Warner takes both."


# ---------------------------------------------------------------------------
# B2: a phrase binds to its own verb phrase
# ---------------------------------------------------------------------------


def test_b2_a_coordinated_verb_starts_a_new_attribution() -> None:
    text = "Warner runs away with the career and takes the peak."
    assert qb_rendered_verdict(_career_decisive_peak_clear(), text) == text


def test_b2_each_coordinated_verb_phrase_takes_its_own_band() -> None:
    text = "Warner runs away with the career and takes the peak by a nose."
    assert qb_rendered_verdict(_career_decisive_peak_close(), text) == text


def test_b2_a_shared_object_still_covers_both_measures() -> None:
    errors = qb_rejected(
        _career_decisive_peak_clear(), "Warner runs away with the career and the peak."
    )
    assert_an_error_says(errors, "the peak margin is 0.40, a clear one", "no runaway words")


# ---------------------------------------------------------------------------
# B3: "can't close the gap" is the verb, not "not close"
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("block", [_wm, _mm, _decisive], ids=["clear", "close", "decisive"])
@pytest.mark.parametrize(
    "text",
    [
        "McNair can't close the gap on the career.",
        "McNair couldn't close it out.",
        "It's not close to done, folks: the score is the score.",
    ],
)
def test_b3_the_verb_close_is_no_runaway_word(text: str, block: Callable[[], str]) -> None:
    assert qb_rendered_verdict(block(), text) == text


@pytest.mark.parametrize("text", ["It isn't close.", "It wasn't even close.", "Not close."])
def test_b3_the_adjective_close_is_still_runaway_on_a_clear_margin(text: str) -> None:
    assert_an_error_says(qb_rejected(_wm(), text), "no runaway words")


# ---------------------------------------------------------------------------
# B4: a negated extreme is not a use of it
# ---------------------------------------------------------------------------


def test_b4_no_photo_finish_here_passes_on_a_decisive_margin() -> None:
    text = "No photo finish here: Warner runs away with it."
    assert qb_rendered_verdict(_decisive(), text) == text


def test_b4_no_squeaker_passes_on_a_decisive_margin() -> None:
    assert qb_rendered_verdict(_decisive(), "This was no squeaker.") == "This was no squeaker."


def test_b4_forget_by_a_nose_passes_on_a_decisive_margin() -> None:
    text = "Forget by a nose, Warner runs away with the career."
    assert qb_rendered_verdict(_decisive(), text) == text


def test_b4_doesnt_run_away_passes_on_a_close_margin() -> None:
    text = "Manning doesn't run away with the career, but he takes it."
    assert qb_rendered_verdict(_mm(), text) == text


@pytest.mark.parametrize("block", [_wm, _mm], ids=["clear", "close"])
def test_b4_an_unnegated_runaway_on_a_close_or_clear_margin_is_still_rejected(
    block: Callable[[], str],
) -> None:
    errors = qb_rejected(block(), "No, he runs away with the career.")
    assert_an_error_says(errors, "the career margin is", "no runaway words")


# ---------------------------------------------------------------------------
# B5: "a different story" needs its own conditional
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("block", [_wm, _mm, _decisive], ids=["clear", "close", "decisive"])
@pytest.mark.parametrize(
    "text",
    [
        "Warner takes it with room to spare and McNair's a different story.",
        "Warner takes both with something left over, and McNair's a different story.",
    ],
)
def test_b5_an_earlier_with_does_not_make_a_different_story_conditional(
    text: str, block: Callable[[], str]
) -> None:
    assert qb_rendered_verdict(block(), text) == text


@pytest.mark.parametrize(
    "text",
    [
        "Give McNair those years and it's a different story.",
        "Count the early years and it'd be a different story.",
        "With his early stuff it's a different story.",
    ],
)
def test_b5_a_conditional_different_story_is_still_rejected(text: str) -> None:
    assert_an_error_says(qb_rejected(_wm(), text), "different story", "missing seasons")


# ---------------------------------------------------------------------------
# B6: an appositive list of measures is covered by the phrase
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Warner runs away with it, career and peak.",
        "Warner runs away with both, the career and the peak.",
        "Warner runs away with the career, and the peak too.",
        "Warner runs away with the career and the peak.",
    ],
)
def test_b6_a_runaway_over_a_list_of_measures_covers_each(text: str) -> None:
    errors = qb_rejected(_career_decisive_peak_clear(), text)
    assert_an_error_says(errors, "the peak margin is 0.40, a clear one", "no runaway words")


@pytest.mark.parametrize(
    "text",
    [
        "Warner runs away with it, career and peak.",
        "Warner runs away with both, the career and the peak.",
        "Warner runs away with the career, and the peak too.",
    ],
)
def test_b6_the_same_list_passes_when_both_are_decisive(text: str) -> None:
    assert qb_rendered_verdict(_decisive(), text) == text


@pytest.mark.parametrize(
    "text", ["Warner wins the career going away.", "Warner cruises on the career."]
)
def test_the_reviews_runaway_probes_are_runaway_words(text: str) -> None:
    assert_an_error_says(qb_rejected(_wm(), text), "the career margin is 1.65", "no runaway")
    assert qb_rendered_verdict(_decisive(), text) == text


# ---------------------------------------------------------------------------
# P1: "if you had McNair" is about the listener, not the missing seasons
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("block", [_wm, _mm, _decisive], ids=["clear", "close", "decisive"])
def test_p1_if_you_had_a_player_is_prose(block: Callable[[], str]) -> None:
    text = "If you had McNair, you'd be crying now."
    assert qb_rendered_verdict(block(), text) == text


@pytest.mark.parametrize(
    "text",
    [
        "If we had his rookie year it'd look different.",
        "If they counted the early seasons, sure.",
        "If the books had McNair's early years, maybe.",
        "If we included those missing years, who knows.",
        "If you had his first season in there, fine.",
    ],
)
def test_p1_if_the_data_had_the_missing_seasons_is_still_rejected(text: str) -> None:
    assert_an_error_says(qb_rejected(_wm(), text), "missing seasons")
