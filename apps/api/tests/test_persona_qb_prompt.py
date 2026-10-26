"""The QB narrator's prompt (issue #451) agrees with its claim check, and a
few more of the check's edges on real fixture blocks.

Every GOOD example in the prompt must render through `check_and_render_qb`
on a block matching its case, and every REJECTED example must be rejected
for each reason it lists that the check can see: an example the validator
disagrees with would teach the narrator to fail. The examples use two
made-up quarterbacks (Ace Mercer, Buck Holloway), so their blocks are real
fixture blocks with the names, short names and cut-off flags replaced: the
sweep is Warner/McNair, the split is `split_evidence` (Warner's career,
McNair's peak) and the inconclusive one is Warner/Cunningham.
"""

from __future__ import annotations

import json
import re

from fixtures.qb_blocks import (
    KURT_WARNER,
    RANDALL_CUNNINGHAM,
    STEVE_MCNAIR,
    assert_an_error_says,
    nfl_player_names,
    qb_block,
    qb_evidence,
    qb_rejected,
    qb_rendered,
    qb_rendered_verdict,
    rescored_evidence,
    split_evidence,
)

from api.models import QbVerdictEvidenceOut, QbVerdictPlayerOut
from api.persona.prompt import build_system_prompt
from api.persona.qb_claims import check_and_render_qb
from api.persona.qb_prompt import build_qb_system_prompt, build_qb_user_message
from api.persona.service import qb_fact_block_json

WILL_LEVIS = 2459892344


def _tagged(tag: str, case: str) -> str:
    prompt = build_qb_system_prompt()
    match = re.search(rf'<{tag} case="{re.escape(case)}">(.*?)</{tag}>', prompt, re.DOTALL)
    assert match, f"no {tag} {case!r} in the QB prompt"
    return match.group(1)


def _text(tag: str, case: str) -> str:
    match = re.search(r"<text>(.*?)</text>", _tagged(tag, case), re.DOTALL)
    assert match
    # The prompt wraps the example at 80 columns; the narration it teaches is
    # one line.
    return " ".join(match.group(1).split())


def _why(tag: str, case: str) -> str:
    match = re.search(r"<why>(.*?)</why>", _tagged(tag, case), re.DOTALL)
    assert match
    return " ".join(match.group(1).split())


def _renamed(
    player: QbVerdictPlayerOut, name: str, short: str, cut_off: bool
) -> QbVerdictPlayerOut:
    coverage = player.coverage.model_copy(update={"cut_off_before": cut_off, "cut_off": cut_off})
    return player.model_copy(
        update={"display_name": name, "short_name": short, "coverage": coverage}
    )


def _fictional(evidence: QbVerdictEvidenceOut, *, cut_off: tuple[bool, bool]) -> str:
    """`evidence` with player a as Ace Mercer and b as Buck Holloway."""
    a = _renamed(evidence.a, "Ace Mercer", "Mercer", cut_off[0])
    b = _renamed(evidence.b, "Buck Holloway", "Holloway", cut_off[1])
    return qb_fact_block_json(evidence.model_copy(update={"a": a, "b": b}))


def _check(block: str, text: str, *claims: dict[str, object]) -> tuple[str | None, tuple[str, ...]]:
    outcome = check_and_render_qb({"text": text, "claims": list(claims)}, block, nfl_player_names())
    return outcome.text, outcome.errors


YEAR: dict[str, object] = {"id": "yr", "kind": "year"}


def test_the_examples_name_no_real_player() -> None:
    for name in ("Ace Mercer", "Buck Holloway"):
        assert name not in nfl_player_names()


def test_the_sweep_example_renders() -> None:
    block = _fictional(qb_evidence(KURT_WARNER, STEVE_MCNAIR), cut_off=(False, False))
    text, errors = _check(
        block,
        _text("good_example", "sweep"),
        {"id": "w", "kind": "winner", "measure": "both"},
        {"id": "sa", "kind": "score", "player": "Mercer", "measure": "career"},
        {"id": "sb", "kind": "score", "player": "Holloway", "measure": "career"},
        YEAR,
    )
    assert errors == ()
    assert text is not None and text.startswith("Mercer takes both, the career and the peak, ")


_SPLIT_CLAIMS: tuple[dict[str, object], ...] = (
    {"id": "wc", "kind": "winner", "measure": "career"},
    {"id": "mc", "kind": "margin", "measure": "career", "player": "Mercer"},
    {"id": "wp", "kind": "winner", "measure": "peak"},
    YEAR,
)


def _close_split() -> QbVerdictEvidenceOut:
    # The example's case since #457: a close career (1.00 to 0.60, 0.40), so
    # its "photo finish" fits; Holloway takes the peak.
    return rescored_evidence(KURT_WARNER, STEVE_MCNAIR, career=(1.0, 0.6), peak=(0.45, 0.5))


def test_the_split_example_renders() -> None:
    block = _fictional(_close_split(), cut_off=(False, True))
    assert json.loads(block)["qb_score"]["career_band"] == "close"
    text, errors = _check(
        block, _text("good_example", "split, close, one cut-off career"), *_SPLIT_CLAIMS
    )
    assert errors == ()
    assert text is not None
    assert text.startswith("Mercer takes the career by ")
    assert "Holloway grabs the peak" in text and "starts in 1999" in text


def test_the_split_examples_photo_finish_is_rejected_on_a_clear_career() -> None:
    # The same text on `split_evidence` (Mercer's career by 1.65, a clear
    # margin): the example's words depend on its band.
    block = _fictional(split_evidence(), cut_off=(False, True))
    _, errors = _check(
        block, _text("good_example", "split, close, one cut-off career"), *_SPLIT_CLAIMS
    )
    assert_an_error_says(errors, '"photo finish"', "the career margin is 1.65, a clear one")


def test_the_inconclusive_example_renders() -> None:
    block = _fictional(qb_evidence(KURT_WARNER, RANDALL_CUNNINGHAM), cut_off=(False, False))
    text, errors = _check(
        block,
        _text("good_example", "inconclusive"),
        {"id": "n", "kind": "count", "of": "min_dropbacks"},
        YEAR,
    )
    assert errors == ()
    assert text is not None and "with 224 dropbacks" in text and "from 1999" in text


def test_the_basics_rejected_example_is_rejected_for_each_reason() -> None:
    block = _fictional(qb_evidence(KURT_WARNER, STEVE_MCNAIR), cut_off=(False, True))
    _, errors = _check(block, _text("rejected_example", "basics"))
    assert_an_error_says(errors, '"3.41"')
    assert_an_error_says(errors, '"2.87"')
    assert_an_error_says(errors, "coin flip")
    assert_an_error_says(errors, '"if we had"', "missing seasons")
    assert_an_error_says(errors, "would've flipped", "missing seasons")
    assert_an_error_says(errors, '"Ace"', "Ace Mercer")
    assert_an_error_says(errors, '"second"')
    assert_an_error_says(errors, "winner claim")
    assert_an_error_says(errors, "year claim")
    why = _why("rejected_example", "basics")
    for listed in ('"3.41"', "coin flip", "would've flipped", '"Ace"', '"second"', "`year`"):
        assert listed in why


def test_the_hard_case_rejected_example_is_rejected_for_each_reason_the_check_sees() -> None:
    block = _fictional(split_evidence(), cut_off=(False, True))
    _, errors = _check(
        block,
        _text("rejected_example", "speculation and a W-L rebuttal"),
        {"id": "wp", "kind": "winner", "measure": "peak"},
        {"id": "r", "kind": "record", "player": "Holloway", "season_type": "regular"},
    )
    assert_an_error_says(errors, "Holloway", "the career goes to Mercer")
    assert_an_error_says(errors, "winner claim", "career")
    assert_an_error_says(errors, "give him his early years back", "missing seasons")
    assert_an_error_says(errors, "different story", "missing seasons")
    assert_an_error_says(errors, "year claim")
    # The W-L rebuttal is the prompt's to teach (D2 on #451): the check can't
    # see it, so the example must say so in its own reasons.
    assert "won more where it counts" in _why("rejected_example", "speculation and a W-L rebuttal")


def test_the_examples_carry_no_real_fixture_name() -> None:
    prompt = build_qb_system_prompt()
    assert "Mercer" in prompt and "Holloway" in prompt
    for name in ("Warner", "McNair", "Manning"):
        assert name not in prompt


def test_the_qb_prompt_is_the_nfl_bar_guy_and_the_team_prompt_is_untouched() -> None:
    prompt = build_qb_system_prompt()
    assert prompt.startswith("Your job:")
    assert "NFL" in prompt and "the numbers are the numbers" in prompt
    for banned in ("too close to call", "toss-up", "basically even", "dead heat", "coin flip"):
        assert banned in prompt
    assert "dead level" in prompt and "<fact_block>" in prompt
    assert "college football" in build_system_prompt(None)
    assert "quarterback" not in build_system_prompt(None)


def test_the_user_message_is_the_fact_block_in_tags() -> None:
    block = qb_block(KURT_WARNER, STEVE_MCNAIR)
    assert build_qb_user_message(block) == f"<fact_block>\n{block}\n</fact_block>"


def test_a_first_name_that_opens_a_sentence_is_prose() -> None:
    block = qb_block(WILL_LEVIS, KURT_WARNER)
    rendered = qb_rendered(
        block,
        "Will anybody argue? {w} takes both, since {yr}.",
        {"id": "w", "kind": "winner", "measure": "both"},
        YEAR,
    )
    assert rendered == "Will anybody argue? Warner takes both, since 1999."
    errors = qb_rejected(block, "Look, Will got outplayed.")
    assert_an_error_says(errors, '"Will"', "Will Levis")


def test_a_figure_without_a_name_must_not_follow_the_other_player() -> None:
    errors = qb_rejected(
        qb_block(KURT_WARNER, STEVE_MCNAIR),
        "McNair was already a vet when this one started in {ws}.",
        {"id": "ws", "kind": "career_start", "player": "Warner"},
    )
    assert_an_error_says(errors, "{ws}", "Kurt Warner", "Steve McNair")


def test_the_verdict_tail_helper_renders_on_every_case() -> None:
    for block in (
        qb_block(KURT_WARNER, STEVE_MCNAIR),
        qb_block(KURT_WARNER, RANDALL_CUNNINGHAM),
        qb_fact_block_json(split_evidence()),
    ):
        assert qb_rendered_verdict(block, "Here goes.") == "Here goes."


# ---------------------------------------------------------------------------
# #463 round B: a clear and a decisive margin example, on the bands they claim
# ---------------------------------------------------------------------------

_SWEEP_MARGIN_CLAIMS: tuple[dict[str, object], ...] = (
    {"id": "w", "kind": "winner", "measure": "both"},
    {"id": "mc", "kind": "margin", "measure": "career", "player": "Mercer"},
    {"id": "mp", "kind": "margin", "measure": "peak", "player": "Mercer"},
    YEAR,
)
_CLEAR_CASE = "sweep, clear on both"
_DECISIVE_CASE = "sweep, decisive, one cut-off career"


def _clear_sweep(cut_off: tuple[bool, bool] = (False, False)) -> str:
    # The harness's herbert-mayfield-clear figures: career +2.91, peak +0.18.
    evidence = rescored_evidence(
        KURT_WARNER, STEVE_MCNAIR, career=(2.1171, -0.7880), peak=(0.4393, 0.2644)
    )
    return _fictional(evidence, cut_off=cut_off)


def _decisive_sweep(cut_off: tuple[bool, bool] = (False, True)) -> str:
    # The harness's brady-flacco-decisive figures: career +22.61, peak +1.60.
    evidence = rescored_evidence(
        KURT_WARNER, STEVE_MCNAIR, career=(18.1914, -4.4199), peak=(1.7261, 0.1280)
    )
    return _fictional(evidence, cut_off=cut_off)


def _bands(block: str) -> tuple[object, object]:
    score = json.loads(block)["qb_score"]
    return score["career_band"], score["peak_band"]


def test_the_prompt_holds_every_example_in_order() -> None:
    cases = re.findall(r'<(good|rejected)_example case="([^"]+)">', build_qb_system_prompt())
    assert cases == [
        ("good", "sweep"),
        ("good", "split, close, one cut-off career"),
        ("good", _CLEAR_CASE),
        ("good", _DECISIVE_CASE),
        ("good", "inconclusive"),
        ("rejected", "basics"),
        ("rejected", "speculation and a W-L rebuttal"),
    ]


def test_the_clear_sweep_example_renders_on_a_clear_block() -> None:
    block = _clear_sweep()
    assert _bands(block) == ("clear", "clear")
    text, errors = _check(block, _text("good_example", _CLEAR_CASE), *_SWEEP_MARGIN_CLAIMS)
    assert errors == ()
    assert text is not None
    assert text.startswith("Mercer takes both, the career by 2.91 and the peak by 0.18, and it")
    assert "not close" in text and "pulls away" in text and "from 1999" in text


def test_the_decisive_sweep_example_renders_on_a_decisive_block() -> None:
    block = _decisive_sweep()
    assert _bands(block) == ("decisive", "decisive")
    text, errors = _check(block, _text("good_example", _DECISIVE_CASE), *_SWEEP_MARGIN_CLAIMS)
    assert errors == ()
    assert text is not None
    assert text.startswith("Mercer runs away with it, the career by 22.61 and the peak by 1.60")
    assert "Holloway's first year isn't in the books" in text and "starts in 1999" in text


def test_the_decisive_examples_hard_words_are_rejected_on_a_clear_block() -> None:
    _, errors = _check(
        _clear_sweep((False, True)), _text("good_example", _DECISIVE_CASE), *_SWEEP_MARGIN_CLAIMS
    )
    assert_an_error_says(errors, '"runs away"', "a clear one")
    assert_an_error_says(errors, '"blowout"', "a clear one")


def test_the_clear_examples_mild_words_are_rejected_on_a_close_block() -> None:
    evidence = rescored_evidence(KURT_WARNER, STEVE_MCNAIR, career=(1.0, 0.6), peak=(0.45, 0.4))
    block = _fictional(evidence, cut_off=(False, False))
    assert _bands(block) == ("close", "close")
    _, errors = _check(block, _text("good_example", _CLEAR_CASE), *_SWEEP_MARGIN_CLAIMS)
    assert_an_error_says(errors, '"not close"', "a close one")
    assert_an_error_says(errors, '"pulls away"', "a close one")


def test_the_prompt_states_the_two_runaway_tiers() -> None:
    prompt = " ".join(build_qb_system_prompt().split())
    assert (
        'Mild runaway words ("not close", "pulls away", "comfortably", "with room to spare") '
        "go on a clear or a decisive margin."
    ) in prompt
    assert (
        'Hard runaway words ("runs away with it", "a blowout", "laps him", "no contest", '
        '"a landslide", "a rout") go only on a decisive margin.'
    ) in prompt
