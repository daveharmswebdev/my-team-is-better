"""Issue #457: what #451's final review left open in the QB narration check.

One test per probe the issue quotes, on the real Warner/McNair fixture block
(Warner wins both measures: career 2.25 to 0.60, peak 0.45 to 0.12). The
false rejections are ordinary on-voice sentences that must render; the
wrong-winner shapes are prose that contradicts a correct `{wb}` claim beside
it and must be rejected. Each fix tightens the matcher (where a sentence
starts, a negator before a speculation verb, a whole-word Roman numeral),
never an existing rejection: the true positives here stay rejected.
"""

from __future__ import annotations

import pytest
from fixtures.qb_blocks import (
    KURT_WARNER,
    STEVE_MCNAIR,
    assert_an_error_says,
    qb_block,
    qb_rejected,
    qb_rendered,
    qb_rendered_verdict,
)

YEAR: dict[str, object] = {"id": "yr", "kind": "year"}
WB: dict[str, object] = {"id": "wb", "kind": "winner", "measure": "both"}
WILL_LEVIS = 2459892344


def _wm() -> str:
    return qb_block(KURT_WARNER, STEVE_MCNAIR)


def _margin(measure: str = "career") -> dict[str, object]:
    return {"id": "m", "kind": "margin", "measure": measure, "player": "Warner"}


# ---------------------------------------------------------------------------
# 1. the sentence-opener exemption covers every sentence, not just the first
# ---------------------------------------------------------------------------


def test_a_word_that_opens_a_later_sentence_is_prose() -> None:
    assert qb_rendered(_wm(), "{wb} takes both since {yr}. Warned you.", WB, YEAR) == (
        "Warner takes both since 1999. Warned you."
    )


@pytest.mark.parametrize("opener", ["Meaning", "Warned", "Warmer", "Stove's"])
def test_every_p3_opener_is_prose_after_a_sentence_break(opener: str) -> None:
    text = f"Here it is. {opener} the math has spoken."
    assert qb_rendered_verdict(_wm(), text) == text


def test_a_first_name_that_opens_a_later_sentence_is_prose() -> None:
    block = qb_block(WILL_LEVIS, KURT_WARNER)
    rendered = qb_rendered(block, "{wb} takes both since {yr}. Will anybody argue?", WB, YEAR)
    assert rendered == "Warner takes both since 1999. Will anybody argue?"


def test_a_misspelling_inside_a_later_sentence_is_still_rejected() -> None:
    errors = qb_rejected(_wm(), "{wb} takes both since {yr}. Look, Warnr is the guy.", WB, YEAR)
    assert_an_error_says(errors, '"Warnr"', "did you mean")


# ---------------------------------------------------------------------------
# 2. a margin prints no name and is checked through the verdict backstop
# ---------------------------------------------------------------------------


def test_the_winner_beating_the_loser_by_a_margin_passes() -> None:
    rendered = qb_rendered(
        _wm(), "{wb} beats McNair by {m} on the career, since {yr}.", WB, _margin(), YEAR
    )
    assert rendered == "Warner beats McNair by 1.65 on the career, since 1999."


def test_the_loser_trailing_by_a_margin_passes() -> None:
    assert qb_rendered_verdict(_wm(), "McNair trails by {m}.", _margin()) == (
        "McNair trails by 1.65."
    )


@pytest.mark.parametrize("measure", ["career", "peak"])
def test_the_loser_ahead_by_the_margin_is_still_rejected(measure: str) -> None:
    errors = qb_rejected(_wm(), "McNair is ahead by {m}.", _margin(measure), WB, YEAR)
    assert_an_error_says(errors, "McNair", f"the {measure} goes to Warner")


# ---------------------------------------------------------------------------
# 3. a Roman numeral is a whole, non-empty word
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("word", ["DID", "MILD", "LIVID", "CIVIL", "LCD", "DC", "MD"])
def test_capitals_that_are_no_roman_numeral_are_prose(word: str) -> None:
    text = f"The McNair fans went {word} about it."
    assert qb_rendered_verdict(_wm(), text) == text


@pytest.mark.parametrize("numeral", ["XXXIV", "XL", "IV", "LIX", "MCMXCIX"])
def test_a_real_roman_numeral_is_still_rejected(numeral: str) -> None:
    errors = qb_rejected(_wm(), f"Warner won Super Bowl {numeral}, sure.")
    assert_an_error_says(errors, f'"{numeral}"', "Roman numeral")


def test_no_roman_numeral_error_is_ever_empty() -> None:
    errors = qb_rejected(_wm(), "DID he? MILD, LIVID, CIVIL, LCD. Super Bowl XXXIV.")
    assert not any('Roman numeral ""' in error for error in errors), errors


# ---------------------------------------------------------------------------
# 4. speculation: a negator and the idiom pass, a conditional is still caught
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Warner owns this one, and nothing would change that.",
        "That might change your mind.",
        "Warner is the guy. McNair's a different story.",
        "No amount of whining could change it.",
    ],
)
def test_ordinary_sentences_near_speculation_words_pass(text: str) -> None:
    assert qb_rendered_verdict(_wm(), text) == text


@pytest.mark.parametrize(
    "text",
    [
        "Count the early years and it'd be a different story.",
        "It would be a different story for McNair.",
        "It's a different story if McNair gets his rookie year.",
        "It's a different story with his rookie year.",
        "With his early stuff it's a different story.",
        "Those early years could easily swing it.",
        "Nobody knows, but his early years could swing it.",
        "Count his rookie year and it might flip.",
    ],
)
def test_speculation_is_still_rejected(text: str) -> None:
    assert_an_error_says(qb_rejected(_wm(), text), "missing seasons")


# ---------------------------------------------------------------------------
# wrong-winner shapes the backstop didn't see, beside a correct {wb} claim
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "shape",
    [
        "McNair is the career winner.",
        "McNair's the career winner.",
        "The career goes to McNair.",
        "McNair takes it: career and peak.",
        "McNair? He takes the career.",
    ],
)
def test_a_wrong_winner_shape_beside_a_correct_claim_is_rejected(shape: str) -> None:
    errors = qb_rejected(_wm(), f"{{wb}} takes both since {{yr}}. {shape}", WB, YEAR)
    assert_an_error_says(errors, "McNair", "the career goes to Warner")


@pytest.mark.parametrize(
    "shape",
    [
        "Warner is the career winner.",
        "The career goes to Warner.",
        "Warner takes it: career and peak.",
        "Warner? He takes the career.",
        "The career goes to {wb}, no argument.",
    ],
)
def test_the_same_shapes_naming_the_right_winner_pass(shape: str) -> None:
    rendered = qb_rendered(_wm(), f"Since {{yr}}, {{wb}} takes both. {shape}", WB, YEAR)
    assert rendered.startswith("Since 1999, Warner takes both. ")
