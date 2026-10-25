"""Margin size is grounded on the QB path (#457, the coordinator's voice call
of 2026-10-25): any margin still counts as a win, and the words scale with
its size.

Each measure's margin falls in a band, on fixed per-measure thresholds
(career: close < 1.5 <= clear < 7.5 <= decisive; peak: close < 0.15 <=
clear < 0.75 <= decisive). The fact block states the band next to the
margin; runaway words are rejected on a measure that isn't decisive and
photo-finish words on one that isn't close. Blocks are real fixture blocks
(`tests/fixtures/qb_blocks.py`), some rescored to a live pair's figures:

* Russell Wilson vs Trevor Lawrence: both margins print 0.00, close/close.
* Peyton Manning vs Steve McNair: career 1.43-0.60 = 0.83 close, peak
  0.29-0.12 = 0.17 clear.
* Kurt Warner vs Steve McNair: career 1.65 clear, peak 0.33 clear.
* Kurt Warner vs Donovan McNabb: career 4.17 clear, peak 0.83 decisive.
* "Brady vs Manning": Manning/Warner rescored to the live figures (career
  18.19 to 18.09, peak 1.77 to 1.73), so 0.10 close and 0.04 close.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal

import pytest
from fixtures.qb_blocks import (
    DONOVAN_MCNABB,
    KURT_WARNER,
    PEYTON_MANNING,
    RANDALL_CUNNINGHAM,
    RUSSELL_WILSON,
    STEVE_MCNAIR,
    TREVOR_LAWRENCE,
    assert_an_error_says,
    qb_block,
    qb_rejected,
    qb_rendered,
    qb_rendered_verdict,
    rescored_block,
)

from api.persona.qb_claims import MARGIN_BANDS, margin_band
from api.persona.qb_prompt import build_qb_system_prompt

YEAR: dict[str, object] = {"id": "yr", "kind": "year"}


def winner(claim_id: str, measure: str) -> dict[str, object]:
    return {"id": claim_id, "kind": "winner", "measure": measure}


def _close() -> str:
    return qb_block(RUSSELL_WILSON, TREVOR_LAWRENCE)


def _close_career() -> str:
    return qb_block(PEYTON_MANNING, STEVE_MCNAIR)


def _clear() -> str:
    return qb_block(KURT_WARNER, STEVE_MCNAIR)


def _decisive_peak() -> str:
    return qb_block(KURT_WARNER, DONOVAN_MCNABB)


def _decisive() -> str:
    return rescored_block(KURT_WARNER, STEVE_MCNAIR, career=(12.0, 0.5), peak=(1.3, 0.2))


def _brady_manning() -> str:
    # Manning is a here, so "Manning" is the peak winner, Warner (as "Brady")
    # the career winner.
    return rescored_block(PEYTON_MANNING, KURT_WARNER, career=(18.09, 18.19), peak=(1.77, 1.73))


def _bands(block: str) -> tuple[object, object]:
    score = json.loads(block)["qb_score"]
    return score["career_band"], score["peak_band"]


# ---------------------------------------------------------------------------
# the bands
# ---------------------------------------------------------------------------


def test_the_thresholds_are_the_voice_calls() -> None:
    assert MARGIN_BANDS == {
        "career": (Decimal("1.5"), Decimal("7.5")),
        "peak": (Decimal("0.15"), Decimal("0.75")),
    }


@pytest.mark.parametrize(
    "measure,margin,band",
    [
        ("career", "0.00", "close"),
        ("career", "1.49", "close"),
        ("career", "1.50", "clear"),
        ("career", "7.49", "clear"),
        ("career", "7.50", "decisive"),
        ("career", "12.99", "decisive"),
        ("peak", "0.04", "close"),
        ("peak", "0.14", "close"),
        ("peak", "0.15", "clear"),
        ("peak", "0.74", "clear"),
        ("peak", "0.75", "decisive"),
        ("peak", "0.87", "decisive"),
    ],
)
def test_a_band_boundary_belongs_to_the_upper_band(measure: str, margin: str, band: str) -> None:
    assert margin_band(measure, Decimal(margin)) == band


@pytest.mark.parametrize(
    "career,peak,bands",
    [
        ((2.0, 0.5), (0.30, 0.15), ("clear", "clear")),
        ((1.99, 0.5), (0.29, 0.15), ("close", "close")),
        ((8.0, 0.5), (0.90, 0.15), ("decisive", "decisive")),
        ((7.99, 0.5), (0.89, 0.15), ("clear", "clear")),
    ],
)
def test_the_fact_block_bands_the_printed_margin_at_each_boundary(
    career: tuple[float, float], peak: tuple[float, float], bands: tuple[str, str]
) -> None:
    block = rescored_block(KURT_WARNER, STEVE_MCNAIR, career=career, peak=peak)
    assert _bands(block) == bands


@pytest.mark.parametrize(
    "block,bands",
    [
        (_close, ("close", "close")),
        (_close_career, ("close", "clear")),
        (_clear, ("clear", "clear")),
        (_decisive_peak, ("clear", "decisive")),
        (_decisive, ("decisive", "decisive")),
        (_brady_manning, ("close", "close")),
    ],
)
def test_the_fact_block_states_each_measures_band(
    block: Callable[[], str], bands: tuple[str, str]
) -> None:
    assert _bands(block()) == bands


def test_the_band_sits_next_to_the_margin_in_the_fact_block() -> None:
    keys = list(json.loads(_clear())["qb_score"])
    assert keys.index("career_band") == keys.index("career_margin") + 1
    assert keys.index("peak_band") == keys.index("peak_margin") + 1


def test_an_exact_tie_has_no_band() -> None:
    block = rescored_block(KURT_WARNER, STEVE_MCNAIR, career=(1.0, 1.0), peak=(0.3, 0.1))
    assert _bands(block) == (None, "clear")


def test_an_inconclusive_block_has_no_band() -> None:
    assert _bands(qb_block(KURT_WARNER, RANDALL_CUNNINGHAM)) == (None, None)


def test_the_feedback_states_the_band_next_to_the_margin() -> None:
    errors = qb_rejected(_brady_manning(), "Manning had two great years.")
    assert_an_error_says(errors, "career: Warner ahead by 0.10 (close)")
    assert_an_error_says(errors, "peak: Manning ahead by 0.04 (close)")


# ---------------------------------------------------------------------------
# the live narration
# ---------------------------------------------------------------------------


def test_manning_running_away_with_a_four_hundredths_peak_is_rejected() -> None:
    errors = qb_rejected(
        _brady_manning(),
        "{wc} takes the career by a nose, and {wp} runs away with the peak, since {yr}.",
        winner("wc", "career"),
        winner("wp", "peak"),
        YEAR,
    )
    assert_an_error_says(errors, '"runs away"', "the peak margin is 0.04, a close one")


# ---------------------------------------------------------------------------
# runaway words: only on a decisive margin
# ---------------------------------------------------------------------------

RUNAWAY = [
    "Warner runs away with the peak.",
    "Warner ran away with the peak.",
    "It's a blowout on the peak.",
    "Warner blows him out on the peak.",
    "No contest on the peak.",
    "The peak is not close.",
    "Warner laps him on the peak.",
    "The peak is a landslide.",
    "The peak is a rout.",
    "Warner buries him on the peak.",
    "Warner walks away with the peak.",
    "Warner takes the peak in a walk.",
    "Warner takes the peak by a mile.",
]
PHOTO_FINISH = [
    "Warner takes the peak in a photo finish.",
    "Warner takes the peak by a nose.",
    "Warner takes the peak by a hair.",
    "The peak is razor-thin.",
    "The peak is razor thin.",
    "Warner squeaks by on the peak.",
    "Warner barely takes the peak.",
]


def _peak_wp(text: str) -> str:
    return text.replace("Warner", "{wp}")


@pytest.mark.parametrize("text", RUNAWAY)
@pytest.mark.parametrize("block", [_close, _clear], ids=["close", "clear"])
def test_runaway_words_are_rejected_on_a_close_or_clear_margin(
    text: str, block: Callable[[], str]
) -> None:
    errors = qb_rejected(block(), text)
    assert_an_error_says(errors, "the peak margin is", "no runaway words")


@pytest.mark.parametrize("text", RUNAWAY)
def test_runaway_words_pass_on_a_decisive_margin(text: str) -> None:
    assert qb_rendered_verdict(_decisive_peak(), text) == text


@pytest.mark.parametrize("text", PHOTO_FINISH)
@pytest.mark.parametrize("block", [_clear, _decisive], ids=["clear", "decisive"])
def test_photo_finish_words_are_rejected_on_a_clear_or_decisive_margin(
    text: str, block: Callable[[], str]
) -> None:
    errors = qb_rejected(block(), text)
    assert_an_error_says(errors, "the peak margin is", "no photo-finish words")


@pytest.mark.parametrize("text", PHOTO_FINISH)
def test_photo_finish_words_pass_on_a_close_margin(text: str) -> None:
    # Lawrence leads both on the close block.
    text = text.replace("Warner", "Lawrence").replace("McNair", "Wilson")
    assert qb_rendered_verdict(_close(), text) == text


def test_each_phrase_is_checked_against_the_measure_it_names() -> None:
    # Manning/McNair: career close, peak clear.
    rendered = qb_rendered_verdict(_close_career(), "Manning takes the career by a nose.")
    assert rendered == "Manning takes the career by a nose."
    errors = qb_rejected(_close_career(), "Manning takes the peak by a nose.")
    assert_an_error_says(errors, "the peak margin is 0.17, a clear one")
    # Warner/McNabb: career clear, peak decisive.
    assert qb_rendered_verdict(_decisive_peak(), "Warner runs away with the peak.")
    errors = qb_rejected(_decisive_peak(), "Warner runs away with the career.")
    assert_an_error_says(errors, "the career margin is 4.17, a clear one", "no runaway words")


def test_a_phrase_in_its_own_clause_takes_the_sentences_measure() -> None:
    # "a photo finish" is an aside on the career it follows (the prompt's
    # own split example), not on the peak.
    block = rescored_block(KURT_WARNER, STEVE_MCNAIR, career=(1.0, 0.6), peak=(0.1, 0.6))
    rendered = qb_rendered(
        block,
        "{wc} takes the career by {mc}, a photo finish, and {wp} grabs the peak, since {yr}.",
        winner("wc", "career"),
        {"id": "mc", "kind": "margin", "measure": "career", "player": "Warner"},
        winner("wp", "peak"),
        YEAR,
    )
    assert rendered.startswith("Warner takes the career by 0.40, a photo finish, and McNair")


def test_a_measure_named_by_a_placeholder_attributes_the_phrase() -> None:
    errors = qb_rejected(
        _decisive_peak(), "{wc} in a walk, counting since {yr}.", winner("wc", "career"), YEAR
    )
    assert_an_error_says(errors, "the career margin is 4.17")


def test_a_phrase_with_no_measure_is_checked_against_both() -> None:
    # Warner/McNabb: the career (clear) forbids it though the peak allows it.
    errors = qb_rejected(_decisive_peak(), "It's a blowout, plain and simple.")
    assert_an_error_says(errors, "the career margin is 4.17", "no runaway words")
    assert qb_rendered_verdict(_decisive(), "It's a blowout, plain and simple.")
    errors = qb_rejected(_close_career(), "Photo finish, folks.")
    assert_an_error_says(errors, "the peak margin is 0.17", "no photo-finish words")


def test_a_tied_measure_takes_no_margin_words() -> None:
    block = rescored_block(KURT_WARNER, STEVE_MCNAIR, career=(1.0, 1.0), peak=(1.3, 0.2))
    errors = qb_rejected(block, "The career is a photo finish.")
    assert_an_error_says(errors, "the career is dead level")


def test_a_close_margin_is_still_a_win_and_needs_its_winner_claims() -> None:
    errors = qb_rejected(_close(), "A photo finish, since {yr}.", YEAR)
    assert_an_error_says(errors, "winner claim")


# ---------------------------------------------------------------------------
# the prompt says so
# ---------------------------------------------------------------------------


def test_the_prompt_says_the_bands_and_where_close_words_fit() -> None:
    prompt = " ".join(build_qb_system_prompt().split())
    assert "career_band" in prompt and "peak_band" in prompt
    assert "only on a close margin" in prompt
    assert "only on a decisive margin" in prompt
    for word in ("runs away", "blowout", "by a nose", "a photo finish"):
        assert word in prompt, word


def test_the_hedge_feedback_says_close_words_fit_close_margins_only() -> None:
    errors = qb_rejected(_clear(), "It's a toss-up.")
    assert_an_error_says(errors, "always a winner", "close margin only")


# ---------------------------------------------------------------------------
# ordinary on-voice prose uses neither extreme, and passes on every band
# ---------------------------------------------------------------------------

ORDINARY = [
    "The math has spoken, and the math doesn't care about your feelings.",
    "Pull up a stool, because this one's settled.",
    "Efficiency per play against the guys of his own season, that's the whole score.",
    "Cry into your beer if you want, the numbers are the numbers.",
    "I've been saying it since last call.",
    "That's not an opinion, that's arithmetic.",
    "Nobody in this bar is arguing with the scoreboard.",
    "Somebody tell the guy in the corner booth to sit down.",
    "Fans of the other guy can take it up with the math.",
    "Read it and weep, pal.",
    "Order another round and get used to it.",
    "He earned it play by play, and the career and the peak both say so.",
    "Close the tab, this one is done.",
]


@pytest.mark.parametrize("text", ORDINARY)
@pytest.mark.parametrize("block", [_close, _clear, _decisive], ids=["close", "clear", "decisive"])
def test_ordinary_prose_passes_on_every_band(text: str, block: Callable[[], str]) -> None:
    assert qb_rendered_verdict(block(), text) == text
