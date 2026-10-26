"""Round B of #463 (with #462): the two-tier margin vocabulary, honoured
"not" negations of margin words, and a comma-clause conditional before "a
different story", one test per required sentence, on real fixture blocks.

The founder's two tiers (2026-10-26):

* mild runaway words ("not close", "pulls away", "comfortably", "with room
  to spare") fit a clear OR a decisive margin;
* hard runaway words ("runs away", "a blowout", "laps him", ...) fit a
  decisive margin only;
* photo-finish words stay close-only.

Blocks (`tests/fixtures/qb_blocks.py`, the harness's production-shaped
cases, names Warner/McNair, Warner wins both unless noted):

* Herbert/Mayfield: career 2.1171 vs -0.7880 (+2.91 clear), peak 0.4393 vs
  0.2644 (+0.18 clear). The live miss of 2026-10-25: "not close" rejected.
* Brady/Flacco: career 18.1914 vs -4.4199 (+22.61 decisive), peak 1.7261 vs
  0.1280 (+1.60 decisive).
* Brady/Manning (Warner/McNair): career 18.1914 vs 18.0904 (+0.10 close,
  Warner), peak 1.7261 vs 1.7704 (0.04 close, McNair).
* Manning/Warner: the same live figures with Peyton Manning as a, so
  "Manning" is the peak winner, as in #462's sentences.
* Warner/McNair as the fixture has it: career 1.65 clear, peak 0.33 clear.
"""

from __future__ import annotations

import json
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
from persona_eval_harness.qb_graders import MARGIN_WORDING

YEAR: dict[str, object] = {"id": "yr", "kind": "year"}
W_BOTH: dict[str, object] = {"id": "w", "kind": "winner", "measure": "both"}
W_CAREER: dict[str, object] = {"id": "w", "kind": "winner", "measure": "career"}
W_PEAK: dict[str, object] = {"id": "w", "kind": "winner", "measure": "peak"}


def _herbert_mayfield() -> str:
    return rescored_block(
        KURT_WARNER, STEVE_MCNAIR, career=(2.1171, -0.7880), peak=(0.4393, 0.2644)
    )


def _brady_flacco() -> str:
    return rescored_block(
        KURT_WARNER, STEVE_MCNAIR, career=(18.1914, -4.4199), peak=(1.7261, 0.1280)
    )


def _brady_manning() -> str:
    return rescored_block(
        KURT_WARNER, STEVE_MCNAIR, career=(18.1914, 18.0904), peak=(1.7261, 1.7704)
    )


def _manning_warner() -> str:
    return rescored_block(PEYTON_MANNING, KURT_WARNER, career=(18.09, 18.19), peak=(1.77, 1.73))


def _wm() -> str:
    return qb_block(KURT_WARNER, STEVE_MCNAIR)


def _bands(block: str) -> tuple[object, object]:
    score = json.loads(block)["qb_score"]
    return score["career_band"], score["peak_band"]


def test_the_blocks_have_the_bands_they_claim() -> None:
    assert _bands(_herbert_mayfield()) == ("clear", "clear")
    assert _bands(_brady_flacco()) == ("decisive", "decisive")
    assert _bands(_brady_manning()) == ("close", "close")
    assert _bands(_manning_warner()) == ("close", "close")
    assert _bands(_wm()) == ("clear", "clear")


def _with_verdict(text: str, claim: dict[str, object]) -> tuple[str, list[dict[str, object]]]:
    """`text` with a year line, and the other measure's winner when `claim`
    names only one, so the narration holds its verdict claims."""
    tail = " Counting since {yr}."
    claims: list[dict[str, object]] = [claim, YEAR]
    if claim["measure"] != "both":
        other = "peak" if claim["measure"] == "career" else "career"
        tail = f" {{o}} takes the {other}.{tail}"
        claims.append({"id": "o", "kind": "winner", "measure": other})
    return text + tail, claims


def _full(block: str, text: str, claim: dict[str, object]) -> str:
    full, claims = _with_verdict(text, claim)
    return qb_rendered(block, full, *claims)


def _full_rejected(block: str, text: str, claim: dict[str, object]) -> tuple[str, ...]:
    full, claims = _with_verdict(text, claim)
    return qb_rejected(block, full, *claims)


# ---------------------------------------------------------------------------
# (2) the two tiers: Herbert/Mayfield, clear on both
# ---------------------------------------------------------------------------


def test_hm_not_close_is_accepted_on_a_clear_sweep() -> None:
    rendered = _full(_herbert_mayfield(), "{w} takes both, and it's not close.", W_BOTH)
    assert rendered.startswith("Warner takes both, and it's not close.")


def test_hm_pulls_away_is_accepted_on_a_clear_career() -> None:
    rendered = _full(_herbert_mayfield(), "{w} pulls away on the career.", W_CAREER)
    assert rendered.startswith("Warner pulls away on the career.")


def test_hm_runs_away_is_rejected_on_a_clear_career() -> None:
    errors = _full_rejected(_herbert_mayfield(), "{w} runs away with the career.", W_CAREER)
    assert_an_error_says(errors, '"runs away"', "the career margin is 2.91, a clear one")
    # The error names the tier and the bands it fits.
    assert_an_error_says(errors, "hard runaway", "decisive margin only")


def test_hm_a_photo_finish_is_rejected_on_a_clear_peak() -> None:
    errors = _full_rejected(_herbert_mayfield(), "{w} takes the peak, a photo finish.", W_PEAK)
    assert_an_error_says(errors, '"photo finish"', "the peak margin is 0.18, a clear one")


@pytest.mark.parametrize(
    "text",
    [
        "{w} takes both comfortably.",
        "{w} takes both with room to spare.",
        "{w} takes both, and it isn't even close.",
        "{w} pulled away on both.",
    ],
)
def test_hm_every_mild_word_is_accepted_on_a_clear_sweep(text: str) -> None:
    _full(_herbert_mayfield(), text, W_BOTH)


# ---------------------------------------------------------------------------
# (2) Brady/Flacco: decisive on both, every tier but photo-finish fits
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,claim",
    [
        ("{w} takes both, and it's not close.", W_BOTH),
        ("{w} pulls away on the career.", W_CAREER),
        ("{w} takes both, a blowout.", W_BOTH),
    ],
)
def test_bf_mild_and_hard_words_are_accepted_on_a_decisive_sweep(
    text: str, claim: dict[str, object]
) -> None:
    rendered = _full(_brady_flacco(), text, claim)
    assert rendered.startswith(text.replace("{w}", "Warner"))


# ---------------------------------------------------------------------------
# (2) Brady/Manning: close on both, split
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,phrase",
    [
        ("{w} takes the career, and it's not close.", '"not close"'),
        ("{w} takes the career comfortably.", '"comfortably"'),
    ],
)
def test_bm_mild_words_are_rejected_on_a_close_margin(text: str, phrase: str) -> None:
    errors = _full_rejected(_brady_manning(), text, W_CAREER)
    assert_an_error_says(errors, phrase, "the career margin is 0.10, a close one")
    assert_an_error_says(errors, "mild runaway", "clear or a decisive margin")


def test_bm_by_a_nose_is_accepted_on_a_close_career() -> None:
    rendered = _full(_brady_manning(), "{w} takes the career by a nose.", W_CAREER)
    assert rendered.startswith("Warner takes the career by a nose.")


# ---------------------------------------------------------------------------
# (3a, #462) a negated margin word is a true sentence
# ---------------------------------------------------------------------------


def test_3a_not_a_photo_finish_on_a_decisive_margin() -> None:
    text = "It's not a photo finish."
    assert qb_rendered_verdict(_brady_flacco(), text) == text


@pytest.mark.parametrize("text", ["It's not a blowout.", "Manning did not run away with the peak."])
def test_3a_a_negated_hard_word_on_a_close_margin(text: str) -> None:
    assert qb_rendered_verdict(_manning_warner(), text) == text


def test_3a_did_not_run_away_on_a_clear_career() -> None:
    text = "Warner did not run away with the career."
    assert qb_rendered_verdict(_wm(), text) == text


@pytest.mark.parametrize("block", [_manning_warner, _wm], ids=["close", "clear"])
def test_3a_never_a_blowout_still_passes(block: Callable[[], str]) -> None:
    text = "This was never a blowout."
    assert qb_rendered_verdict(block(), text) == text


@pytest.mark.parametrize("block", [_manning_warner, _wm], ids=["close", "clear"])
def test_3a_no_doubt_he_runs_away_is_still_a_runaway(block: Callable[[], str]) -> None:
    errors = qb_rejected(block(), "No doubt Warner runs away with it.")
    assert_an_error_says(errors, '"runs away"', "no runaway words")


# ---------------------------------------------------------------------------
# (3b, #462) a conditional in the clause before "a different story"
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "If you count his Houston years, it's a different story.",
        "With his Houston years in, it's a different story.",
        "Count his Houston years, and it's a different story.",
    ],
)
def test_3b_a_conditional_before_a_different_story_is_speculation(text: str) -> None:
    errors = qb_rejected(_wm(), text)
    assert_an_error_says(errors, "missing seasons")


def test_3b_if_you_count_alone_is_speculation() -> None:
    errors = qb_rejected(_wm(), "If you count his Houston years, McNair is right there.")
    assert_an_error_says(errors, '"If you count"', "missing seasons")


@pytest.mark.parametrize(
    "text",
    [
        "McNair's a different story.",
        # The cue clause must be the one right before the phrase's clause:
        # here "with room to spare" belongs to Warner's win, and McNair's a
        # different story is the next topic.
        "With room to spare, Warner takes both, and McNair's a different story.",
    ],
)
def test_3b_the_next_topic_is_no_speculation(text: str) -> None:
    assert qb_rendered_verdict(_wm(), text) == text


# ---------------------------------------------------------------------------
# the eval harness's word table agrees with the checker on every word it holds
# ---------------------------------------------------------------------------

_BAND_BLOCKS: dict[str, Callable[[], str]] = {
    "close": _brady_manning,
    "clear": _herbert_mayfield,
    "decisive": _brady_flacco,
}


@pytest.mark.parametrize(
    "tier,word",
    [(tier, word) for tier, spec in MARGIN_WORDING.items() for word in spec.words],
)
@pytest.mark.parametrize("band", ["close", "clear", "decisive"])
def test_the_harness_tiers_agree_with_the_checker(tier: str, word: str, band: str) -> None:
    text = f"Look, {word}, on both."
    block = _BAND_BLOCKS[band]()
    if band in MARGIN_WORDING[tier].allowed_bands:
        assert qb_rendered_verdict(block, text) == text
    else:
        assert_an_error_says(qb_rejected(block, text), f"a {band} one")
