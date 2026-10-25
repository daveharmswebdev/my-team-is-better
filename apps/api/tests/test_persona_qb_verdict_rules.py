"""Round 3 of issue #451: the QB narration can't render a wrong or missing
verdict, a figure next to the wrong player, or a third player.

One regression test per blocking review item, on the exact inputs the
independent review (R1-R4) and the prompt-engineer (P1-P3) found rendering,
plus the coordinator's decisions: the verdict goes through claims only (D1:
`winner` takes measure "both"; a conclusive narration needs `winner` both or
career + peak; every narration needs a `year`; a typed name + win verb +
measure is checked against the verdict), the extra hedge and speculation
probes (D2), and Roman numerals on the QB path (D3). The false-positive suite
at the end must keep passing: ordinary on-voice sentences, including the
gate's own example.

Blocks are real fixture blocks (`tests/fixtures/qb_blocks.py`): Kurt Warner
beats Steve McNair on both measures (career 2.25 to 0.60); Warner vs Randall
Cunningham is inconclusive; `split_block` is Warner/McNair with McNair's peak
raised so the two split.
"""

from __future__ import annotations

import re

import pytest
from cfb_strength.players import get_qb_score
from fixtures.player_api_fixture import fixture_conn
from fixtures.qb_blocks import (
    KURT_WARNER,
    PEYTON_MANNING,
    RANDALL_CUNNINGHAM,
    STEVE_MCNAIR,
    assert_an_error_says,
    qb_block,
    qb_rejected,
    qb_rendered,
    qb_rendered_verdict,
    split_block,
)

from api.persona.qb_prompt import build_qb_system_prompt

YEAR: dict[str, object] = {"id": "yr", "kind": "year"}


def _wm() -> str:
    return qb_block(KURT_WARNER, STEVE_MCNAIR)


def _inconclusive() -> str:
    return qb_block(KURT_WARNER, RANDALL_CUNNINGHAM)


def winner(claim_id: str, measure: str) -> dict[str, object]:
    return {"id": claim_id, "kind": "winner", "measure": measure}


# ---------------------------------------------------------------------------
# R1: a wrong winner in prose
# ---------------------------------------------------------------------------


def test_r1_a_loser_typed_as_the_winner_of_both_is_rejected() -> None:
    errors = qb_rejected(_wm(), "McNair takes the career and the peak, counting since {yr}.", YEAR)
    assert_an_error_says(errors, "McNair", "the career goes to Warner")


def test_r1_a_loser_typed_as_the_winner_beside_a_winner_claim_is_rejected() -> None:
    errors = qb_rejected(
        _wm(),
        "McNair takes the career, not Warner, and {w} has to watch, counting since {yr}.",
        winner("w", "both"),
        YEAR,
    )
    assert_an_error_says(errors, "McNair", "the career goes to Warner")


def test_r1_a_winner_typed_on_an_inconclusive_block_is_rejected() -> None:
    errors = qb_rejected(_inconclusive(), "Warner takes the career since {yr}.", YEAR)
    assert_an_error_says(errors, "Warner", "inconclusive")


def test_r1_the_object_of_a_win_verb_is_not_its_subject() -> None:
    errors = qb_rejected(
        _wm(), "McNair beats Warner on the career, since {yr}.", winner("w", "both"), YEAR
    )
    assert_an_error_says(errors, "McNair", "the career goes to Warner")


# ---------------------------------------------------------------------------
# R2, R3: a figure beside the wrong player
# ---------------------------------------------------------------------------


def test_r2_a_margin_beside_the_loser_is_rejected() -> None:
    errors = qb_rejected(
        _wm(),
        "McNair is ahead by {m} since {yr}.",
        {"id": "m", "kind": "margin", "measure": "career", "player": "Warner"},
        YEAR,
    )
    # Since #457 a margin is checked through the verdict backstop, not as an
    # attributed figure: "McNair trails by {m}" is true.
    assert_an_error_says(errors, "McNair", "the career goes to Warner")


def test_r3_an_attributed_figure_follows_a_name_across_a_sentence_break() -> None:
    errors = qb_rejected(
        _wm(),
        "Warner? His career started in {cs}, counting since {yr}.",
        {"id": "cs", "kind": "career_start", "player": "McNair"},
        YEAR,
    )
    assert_an_error_says(errors, "{cs}", "Steve McNair's figure", "Kurt Warner")


# ---------------------------------------------------------------------------
# R4: a possessive third player
# ---------------------------------------------------------------------------


def test_r4_a_possessive_third_player_is_rejected() -> None:
    errors = qb_rejected(_wm(), "Warner had Marshall Faulk's pal behind him.")
    assert_an_error_says(errors, "Marshall Faulk", "not a player in this fact block")


# ---------------------------------------------------------------------------
# P1, P2: the prompt holds no real figures and no real pair's facts
# ---------------------------------------------------------------------------


def _fixture_score_prints() -> set[str]:
    printed: set[str] = set()
    with fixture_conn() as conn:
        ids = [
            row[0]
            for row in conn.execute(
                "SELECT id FROM players WHERE sport = 'nfl' AND position = 'QB'"
            ).fetchall()
        ]
        for player_id in ids:
            score = get_qb_score(conn, sport="nfl", player_id=player_id)
            for value in (score.career, score.peak):
                if value is not None:
                    printed.add(f"{value:.2f}")
    return printed


def test_p1_the_prompt_types_no_real_fixture_score() -> None:
    prompt = build_qb_system_prompt()
    figures = set(re.findall(r"-?\d+\.\d\d", prompt))
    assert figures, "the examples should still show what a printed score looks like"
    assert not figures & _fixture_score_prints(), figures & _fixture_score_prints()
    assert "2.25" not in prompt and "0.60" not in prompt


def test_p1_p2_the_prompt_names_no_real_fixture_quarterback() -> None:
    prompt = build_qb_system_prompt()
    for name in ("Warner", "McNair", "Manning", "Cunningham", "DeVito"):
        assert name not in prompt, name


def test_p2_the_cut_off_line_is_a_form_that_applies_only_when_cut_off() -> None:
    prompt = build_qb_system_prompt()
    assert "<his name>'s first year isn't in the books" in prompt
    line = prompt[
        prompt.index("<his name>'s first year") - 400 : prompt.index("<his name>'s first year")
    ]
    assert "cut_off_before" in line


# ---------------------------------------------------------------------------
# P3: a sentence opener is never a misspelled name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Meaning the math has spoken.",
        "Warned you.",
        "Warmer than a July doubleheader.",
        "Stove's hot tonight.",
    ],
)
def test_p3_a_sentence_opener_near_a_name_is_prose(text: str) -> None:
    assert qb_rendered_verdict(_wm(), text) == text


# ---------------------------------------------------------------------------
# D1: the verdict goes through claims
# ---------------------------------------------------------------------------


def test_d1_winner_both_prints_the_sweepers_name() -> None:
    assert qb_rendered(_wm(), "{w} takes both, since {yr}.", winner("w", "both"), YEAR) == (
        "Warner takes both, since 1999."
    )


def test_d1_winner_both_on_a_split_is_rejected() -> None:
    errors = qb_rejected(split_block(), "{w} takes both, since {yr}.", winner("w", "both"), YEAR)
    assert_an_error_says(errors, "split", "Warner", "McNair")


def test_d1_a_missing_year_is_rejected_saying_what_to_add() -> None:
    errors = qb_rejected(_wm(), "{w} takes both.", winner("w", "both"))
    assert_an_error_says(errors, "year claim", "1999")


def test_d1_a_missing_year_is_rejected_on_an_inconclusive_block_too() -> None:
    errors = qb_rejected(_inconclusive(), "Cunningham never qualified, so it's inconclusive.")
    assert_an_error_says(errors, "year claim")


def test_d1_a_conclusive_narration_with_no_winner_claim_is_rejected() -> None:
    errors = qb_rejected(_wm(), "Big night for the math, since {yr}.", YEAR)
    assert_an_error_says(errors, "winner claim", "both", "Warner")


def test_d1_a_split_with_only_one_winner_claim_is_rejected() -> None:
    errors = qb_rejected(
        split_block(), "{wc} takes the career, since {yr}.", winner("wc", "career"), YEAR
    )
    assert_an_error_says(errors, "winner claim", "peak", "McNair")


def test_d1_a_split_with_both_winner_claims_renders() -> None:
    rendered = qb_rendered(
        split_block(),
        "{wc} takes the career and {wp} grabs the peak, since {yr}.",
        winner("wc", "career"),
        winner("wp", "peak"),
        YEAR,
    )
    assert rendered == "Warner takes the career and McNair grabs the peak, since 1999."


def test_d1_the_backstop_checks_a_split_per_measure() -> None:
    errors = qb_rejected(
        split_block(),
        "Warner takes the peak, {wc} the career and {wp} the peak, since {yr}.",
        winner("wc", "career"),
        winner("wp", "peak"),
        YEAR,
    )
    assert_an_error_says(errors, "the peak goes to McNair")


# ---------------------------------------------------------------------------
# D2: more hedges and speculation; D3: Roman numerals
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,needle",
    [
        ("Those early years could easily swing it.", "missing seasons"),
        ("Count his rookie year and it might flip.", "missing seasons"),
        ("With his early stuff it's a different story.", "missing seasons"),
        ("Give McNair his early years back and see.", "missing seasons"),
        ("You can't separate them.", "always a winner"),
        ("There's no separating these two.", "always a winner"),
        ("It's even steven.", "always a winner"),
    ],
)
def test_d2_more_hedges_and_speculation_are_rejected(text: str, needle: str) -> None:
    assert_an_error_says(qb_rejected(_wm(), text), needle)


def test_d3_a_roman_numeral_is_rejected_on_the_qb_path() -> None:
    errors = qb_rejected(_wm(), "Warner won Super Bowl XXXIV, sure.")
    assert_an_error_says(errors, '"XXXIV"', "Roman numeral")


# ---------------------------------------------------------------------------
# false positives: these must keep passing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "First off, the math is the math.",
        "No one at this bar is arguing.",
        "Warner by half a step, no more.",
        "Nobody beats Warner on the career, and McNair knows it.",
        "Warner beats McNair on the career, plain and simple.",
        "I said it before and I'll say it again.",
    ],
)
def test_ordinary_on_voice_sentences_pass(text: str) -> None:
    claims = [YEAR] if "{yr}" in text else []
    rendered = qb_rendered_verdict(_wm(), text, *claims)
    assert rendered == text.replace("{yr}", "1999")


@pytest.mark.parametrize(
    "text",
    [
        "Manning takes the career by a nose.",
        "Manning takes the career by a nose, and the books only open in {yr}.",
    ],
)
def test_by_a_nose_passes_on_a_close_career(text: str) -> None:
    # Moved off Warner/McNair (a clear 1.65 career margin) by #457: "by a
    # nose" fits a close margin only. Manning/McNair's career is 0.83, close.
    claims = [YEAR] if "{yr}" in text else []
    rendered = qb_rendered_verdict(qb_block(PEYTON_MANNING, STEVE_MCNAIR), text, *claims)
    assert rendered == text.replace("{yr}", "1999")


def test_a_correct_split_sentence_passes() -> None:
    rendered = qb_rendered(
        split_block(),
        "Warner takes the career, McNair takes the peak, and {wc} and {wp} both get a "
        "trophy, since {yr}.",
        winner("wc", "career"),
        winner("wp", "peak"),
        YEAR,
    )
    assert rendered.startswith("Warner takes the career, McNair takes the peak")
