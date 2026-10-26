"""Offline unit tests for the eval harness's QB narrator, model choice and
cost (issue #463, which includes #455).

None of them makes a Claude call: narrators are `FakeNarrator`s, graders are
fakes returning hand-built `Grade`s, and the environment the safety checks
read is a plain mapping handed to `main`.

What they pin:

- the QB dataset: its ids, each built from `tests/fixtures/qb_blocks.py`'s
  real blocks, and each case's margin bands (the three production-shaped
  cases' bands are the ones their ids name);
- the four QB code graders on hand-written passing and failing texts, and a
  served fallback scoring N/A on the three that read the accepted call;
- the cost arithmetic on hand-computed usage, per model, cache tokens
  included, and the `--dry-run` worst-case dollar estimate;
- `--narrator`, `--model` and `--effort`: the refusals (exit 2) and the dry
  run;
- a QB run end to end through production's QB path (the served text is
  `check_and_render_qb`'s rendering; a twice-rejected one is the fallback),
  with usage and cost in records.jsonl and the narrator, model and effort in
  the report header.
"""

from __future__ import annotations

import dataclasses
import io
import json
from pathlib import Path
from typing import Any

import pytest
from fixtures.narrator_fake import ACCEPTED_NARRATION, FakeNarrator, NarratorCall, Scripted
from fixtures.qb_blocks import (
    DONOVAN_MCNABB,
    KURT_WARNER,
    RANDALL_CUNNINGHAM,
    RUSSELL_WILSON,
    STEVE_MCNAIR,
    TOMMY_DEVITO,
    TREVOR_LAWRENCE,
    qb_block,
    split_block,
)
from persona_eval_harness.cli import main
from persona_eval_harness.cost import (
    PRICES,
    call_cost_usd,
    estimate_tokens,
    worst_case_narration_usd,
)
from persona_eval_harness.grader import Grade
from persona_eval_harness.qb_dataset import QB_CASE_SPECS, QbEvalCase, build_qb_dataset
from persona_eval_harness.qb_graders import (
    HEDGE_PHRASES,
    MARGIN_WORDING,
    QbGrades,
    grade_qb,
)
from persona_eval_harness.variants import parse_variant, parse_variants

from api.persona.claude_client import NarratorReply, TokenUsage, tool_reply
from api.persona.qb_claims import qb_margin_band
from api.persona.qb_prompt import build_qb_system_prompt

NO_ENV_FILE = Path("/nonexistent/persona-eval-harness/.env")
NOT_A_KEY = "test-placeholder-not-a-key"

SWEEP = "qb-warner-mcnair-sweep"
DECISIVE = "qb-brady-flacco-decisive"
CLEAR = "qb-herbert-mayfield-clear"

ACCEPTED_SWEEP: dict[str, object] = {
    "text": "{w} takes the career and the peak, the career by {m}, counting since {yr}.",
    "claims": [
        {"id": "w", "kind": "winner", "measure": "both"},
        {"id": "m", "kind": "margin", "measure": "career", "player": "Warner"},
        {"id": "yr", "kind": "year"},
    ],
}
ACCEPTED_SWEEP_TEXT = (
    "Warner takes the career and the peak, the career by 1.65, counting since 1999."
)

WINNER_BOTH_AND_YEAR: dict[str, object] = {
    "text": "{w} takes both, counting since {y}.",
    "claims": [{"id": "w", "kind": "winner", "measure": "both"}, {"id": "y", "kind": "year"}],
}


@pytest.fixture(scope="module")
def qb_cases() -> dict[str, QbEvalCase]:
    return {case.id: case for case in build_qb_dataset()}


# ---------------------------------------------------------------------------
# the QB dataset
# ---------------------------------------------------------------------------


def test_the_qb_dataset_ids() -> None:
    assert [spec.id for spec in QB_CASE_SPECS] == [
        "qb-warner-mcnair-sweep",
        "qb-warner-mcnair-split",
        "qb-mcnabb-warner-one-cut-off",
        "qb-cunningham-devito-inconclusive",
        "qb-wilson-lawrence-printed-equal",
        "qb-brady-manning-split",
        "qb-herbert-mayfield-clear",
        "qb-brady-flacco-decisive",
    ]


def test_the_fixture_cases_are_the_real_fixture_blocks(qb_cases: dict[str, QbEvalCase]) -> None:
    assert qb_cases["qb-warner-mcnair-sweep"].fact_block_json == qb_block(KURT_WARNER, STEVE_MCNAIR)
    assert qb_cases["qb-warner-mcnair-split"].fact_block_json == split_block()
    assert qb_cases["qb-mcnabb-warner-one-cut-off"].fact_block_json == qb_block(
        DONOVAN_MCNABB, KURT_WARNER
    )
    assert qb_cases["qb-cunningham-devito-inconclusive"].fact_block_json == qb_block(
        RANDALL_CUNNINGHAM, TOMMY_DEVITO
    )
    assert qb_cases["qb-wilson-lawrence-printed-equal"].fact_block_json == qb_block(
        RUSSELL_WILSON, TREVOR_LAWRENCE
    )


def _bands(case: QbEvalCase) -> tuple[str | None, str | None]:
    score = case.evidence.qb_score
    career = qb_margin_band("career", score.career_winner, score.a.career, score.b.career)
    peak = qb_margin_band("peak", score.peak_winner, score.a.peak, score.b.peak)
    return career, peak


def test_each_case_has_the_bands_its_spec_states(qb_cases: dict[str, QbEvalCase]) -> None:
    for spec in QB_CASE_SPECS:
        case = qb_cases[spec.id]
        assert _bands(case) == (spec.career_band, spec.peak_band), spec.id
        block = json.loads(case.fact_block_json)["qb_score"]
        assert (block["career_band"], block["peak_band"]) == (spec.career_band, spec.peak_band)


def test_the_production_shaped_cases_have_the_bands_their_ids_name(
    qb_cases: dict[str, QbEvalCase],
) -> None:
    assert _bands(qb_cases["qb-brady-manning-split"]) == ("close", "close")
    assert _bands(qb_cases["qb-herbert-mayfield-clear"]) == ("clear", "clear")
    assert _bands(qb_cases["qb-brady-flacco-decisive"]) == ("decisive", "decisive")
    split = json.loads(qb_cases["qb-brady-manning-split"].fact_block_json)["qb_score"]
    assert (split["career_winner"], split["peak_winner"]) == ("a", "b")
    clear = json.loads(qb_cases["qb-herbert-mayfield-clear"].fact_block_json)["qb_score"]
    assert round(clear["career_margin"], 3) == 2.905
    assert round(clear["peak_margin"], 3) == 0.175


def test_the_one_cut_off_and_inconclusive_cases_are_what_they_say(
    qb_cases: dict[str, QbEvalCase],
) -> None:
    cut_off = json.loads(qb_cases["qb-mcnabb-warner-one-cut-off"].fact_block_json)
    flags = [cut_off[side]["coverage"]["cut_off_before"] for side in ("a", "b")]
    assert flags == [False, True]
    inconclusive = json.loads(qb_cases["qb-cunningham-devito-inconclusive"].fact_block_json)
    assert inconclusive["qb_score"]["inconclusive"] is not None


# ---------------------------------------------------------------------------
# the QB code graders
# ---------------------------------------------------------------------------


def _grade(case: QbEvalCase, text: str, served_input: object | None) -> QbGrades:
    return grade_qb(
        served_text=text, served_input=served_input, fact_block_json=case.fact_block_json
    )


def test_the_word_lists_live_in_one_table() -> None:
    assert set(MARGIN_WORDING) == {"photo_finish", "mild_runaway", "hard_runaway"}
    assert MARGIN_WORDING["photo_finish"].allowed_bands == frozenset({"close"})
    assert MARGIN_WORDING["mild_runaway"].allowed_bands == frozenset({"clear", "decisive"})
    assert MARGIN_WORDING["hard_runaway"].allowed_bands == frozenset({"decisive"})
    assert "not close" in MARGIN_WORDING["mild_runaway"].words
    assert "blowout" in MARGIN_WORDING["hard_runaway"].words
    assert "by a nose" in MARGIN_WORDING["photo_finish"].words
    assert "too close to call" in HEDGE_PHRASES


def test_a_clean_narration_passes_all_four(qb_cases: dict[str, QbEvalCase]) -> None:
    grades = _grade(
        qb_cases[CLEAR],
        "Warner takes both, and it's not close, counting since 1999.",
        WINNER_BOTH_AND_YEAR,
    )
    assert grades == QbGrades(
        no_hedge=True,
        year_present=True,
        winners_named=True,
        margin_wording=True,
        hedge_hits=(),
        margin_violations=(),
    )


@pytest.mark.parametrize(
    "text",
    [
        "Honestly it's too close to call.",
        "A toss-up, really.",
        "Call it a toss up.",
        "They're basically even.",
        "Flip a coin flip.",
        "This could go either way.",
        "Hard to say who wins.",
        "Dead even, folks.",
    ],
)
def test_a_hedge_fails_no_hedge(qb_cases: dict[str, QbEvalCase], text: str) -> None:
    grades = _grade(qb_cases[CLEAR], text, WINNER_BOTH_AND_YEAR)
    assert grades.no_hedge is False
    assert grades.hedge_hits


def test_a_missing_year_claim_fails_year_present(qb_cases: dict[str, QbEvalCase]) -> None:
    served = {
        "text": "{w} takes both.",
        "claims": [{"id": "w", "kind": "winner", "measure": "both"}],
    }
    assert _grade(qb_cases[CLEAR], "Warner takes both.", served).year_present is False


def test_winners_named_per_measure(qb_cases: dict[str, QbEvalCase]) -> None:
    split = qb_cases["qb-brady-manning-split"]
    career_only = {
        "text": "{c} takes the career, counting since {y}.",
        "claims": [{"id": "c", "kind": "winner", "measure": "career"}, {"id": "y", "kind": "year"}],
    }
    both_measures = {
        "text": "{c} the career, {p} the peak, since {y}.",
        "claims": [
            {"id": "c", "kind": "winner", "measure": "career"},
            {"id": "p", "kind": "winner", "measure": "peak"},
            {"id": "y", "kind": "year"},
        ],
    }
    assert _grade(split, "x", career_only).winners_named is False
    assert _grade(split, "x", both_measures).winners_named is True
    assert _grade(qb_cases[CLEAR], "x", WINNER_BOTH_AND_YEAR).winners_named is True
    # No measure has a winner: nothing to name, so not applicable.
    inconclusive = qb_cases["qb-cunningham-devito-inconclusive"]
    year_only = {"text": "Since {y}.", "claims": [{"id": "y", "kind": "year"}]}
    assert _grade(inconclusive, "x", year_only).winners_named is None


def test_mild_runaway_words_pass_on_a_clear_margin(qb_cases: dict[str, QbEvalCase]) -> None:
    for text in ("It's not close.", "Warner pulls away.", "Comfortably.", "With room to spare."):
        assert _grade(qb_cases[CLEAR], text, WINNER_BOTH_AND_YEAR).margin_wording is True, text


def test_hard_runaway_words_fail_on_a_clear_margin(qb_cases: dict[str, QbEvalCase]) -> None:
    grades = _grade(qb_cases[CLEAR], "Warner wins it in a blowout.", WINNER_BOTH_AND_YEAR)
    assert grades.margin_wording is False
    assert any("blowout" in violation for violation in grades.margin_violations)


def test_hard_runaway_words_pass_on_a_decisive_margin(qb_cases: dict[str, QbEvalCase]) -> None:
    for text in ("A blowout.", "Warner runs away with it.", "No contest.", "He laps him."):
        assert _grade(qb_cases[DECISIVE], text, WINNER_BOTH_AND_YEAR).margin_wording is True, text


def test_photo_finish_words_fail_when_no_measure_is_close(qb_cases: dict[str, QbEvalCase]) -> None:
    grades = _grade(qb_cases[DECISIVE], "Warner wins by a nose.", WINNER_BOTH_AND_YEAR)
    assert grades.margin_wording is False
    assert grades.margin_violations


def test_photo_finish_words_pass_when_some_measure_is_close(
    qb_cases: dict[str, QbEvalCase],
) -> None:
    split = qb_cases["qb-warner-mcnair-split"]  # career clear, peak close
    assert _grade(split, "McNair takes the peak by a nose.", WINNER_BOTH_AND_YEAR).margin_wording
    # ...but a mild runaway word still fits its clear career, and a hard one doesn't.
    assert _grade(split, "Warner pulls away on the career.", WINNER_BOTH_AND_YEAR).margin_wording
    assert not _grade(split, "A landslide career.", WINNER_BOTH_AND_YEAR).margin_wording


def test_words_are_matched_whole(qb_cases: dict[str, QbEvalCase]) -> None:
    # "route" is not "rout", "lapse" is not "laps".
    text = "He ran the route without a lapse."
    assert _grade(qb_cases[CLEAR], text, WINNER_BOTH_AND_YEAR).margin_wording is True


def test_a_served_fallback_is_na_on_the_three_call_graders(qb_cases: dict[str, QbEvalCase]) -> None:
    grades = _grade(qb_cases[CLEAR], qb_cases[CLEAR].fallback_text, None)
    assert grades.year_present is None
    assert grades.winners_named is None
    assert grades.margin_wording is None
    assert grades.no_hedge is True


# ---------------------------------------------------------------------------
# cost
# ---------------------------------------------------------------------------

USAGE = TokenUsage(
    input_tokens=1000,
    output_tokens=200,
    cache_creation_input_tokens=400,
    cache_read_input_tokens=2000,
)


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        # (1000 x in + 400 x 1.25 in + 2000 x 0.1 in + 200 x out) / 1e6
        ("claude-haiku-4-5", (1000 * 1 + 400 * 1.25 + 2000 * 0.1 + 200 * 5) / 1e6),  # 0.0027
        ("claude-haiku-5-5", (1000 * 0.1 + 400 * 0.125 + 2000 * 0.01 + 200 * 0.5) / 1e6),
        ("claude-sonnet-5-5", (1000 * 2 + 400 * 2.5 + 2000 * 0.2 + 200 * 10) / 1e6),  # 0.0054
        ("claude-opus-5", (1000 * 5 + 400 * 6.25 + 2000 * 0.5 + 200 * 25) / 1e6),  # 0.0135
    ],
)
def test_call_cost_on_a_hand_computed_usage(model: str, expected: float) -> None:
    assert call_cost_usd(model, USAGE) == pytest.approx(expected)


def test_the_hand_computed_figures() -> None:
    assert call_cost_usd("claude-haiku-4-5", USAGE) == pytest.approx(0.0027)
    assert call_cost_usd("claude-haiku-5-5", USAGE) == pytest.approx(0.00027)
    assert call_cost_usd("claude-sonnet-5-5", USAGE) == pytest.approx(0.0054)
    assert call_cost_usd("claude-opus-5", USAGE) == pytest.approx(0.0135)


def test_haiku_5_5_over_100k_prompt_tokens_is_on_the_long_rate_card() -> None:
    long_prompt = TokenUsage(
        input_tokens=90_000,
        output_tokens=1000,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=20_000,
    )
    expected = (90_000 * 0.5 + 20_000 * 0.05 + 1000 * 2.5) / 1e6
    assert call_cost_usd("claude-haiku-5-5", long_prompt) == pytest.approx(expected)


def test_every_narrator_model_and_the_grader_are_priced() -> None:
    assert set(PRICES) == {
        "claude-haiku-4-5",
        "claude-haiku-5-5",
        "claude-sonnet-5-5",
        "claude-opus-5",
    }


def test_the_worst_case_estimate_per_narration() -> None:
    assert estimate_tokens(2500) == 1000
    assert estimate_tokens(1) == 1
    narrator, grader = worst_case_narration_usd(
        narrator_model="claude-haiku-4-5",
        narrator_max_tokens=1200,
        narrator_input_chars=2500,  # 1000 tokens
        grader_input_chars=5000,  # 2000 tokens
    )
    # call 1: 1000 in + 1200 out; the retry replays up to 1200 more and up to
    # 8000 chars (3200 tokens) of feedback: 5400 in + 1200 out.
    assert narrator == pytest.approx((1000 * 1 + 1200 * 5 + 5400 * 1 + 1200 * 5) / 1e6)
    # the grader: 2000 in + 16000 out on Opus 5
    assert grader == pytest.approx((2000 * 5 + 16000 * 25) / 1e6)


# ---------------------------------------------------------------------------
# variants
# ---------------------------------------------------------------------------


def test_the_qb_baseline_is_the_production_qb_prompt() -> None:
    (variant,) = parse_variants(["baseline"], narrator="qb")
    assert variant.build_system_prompt(None) == build_qb_system_prompt()
    assert variant.source == "api.persona.qb_prompt.build_qb_system_prompt"


def test_a_qb_variant_file_exposes_build_qb_system_prompt(tmp_path: Path) -> None:
    good = tmp_path / "good.py"
    good.write_text("def build_qb_system_prompt():\n    return 'QB CANDIDATE'\n")
    assert parse_variant(f"cand={good}", narrator="qb").build_system_prompt(None) == "QB CANDIDATE"
    team_style = tmp_path / "team.py"
    team_style.write_text("def build_system_prompt(user_team):\n    return 'TEAM'\n")
    with pytest.raises(ValueError, match="build_qb_system_prompt"):
        parse_variant(f"cand={team_style}", narrator="qb")
    with pytest.raises(ValueError, match="reserved"):
        parse_variant(f"baseline={good}", narrator="qb")
    with pytest.raises(ValueError, match="degraded"):
        parse_variant("degraded", narrator="qb")


# ---------------------------------------------------------------------------
# the command line
# ---------------------------------------------------------------------------


def _main(argv: list[str], **kwargs: Any) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    kwargs.setdefault("environ", {"ANTHROPIC_API_KEY": NOT_A_KEY})
    kwargs.setdefault("narrator", FakeNarrator())
    code = main(argv, env_file=NO_ENV_FILE, out=out, err=err, **kwargs)
    return code, out.getvalue(), err.getvalue()


@pytest.mark.parametrize(
    "argv",
    [
        ["--dry-run", "--model", "claude-opus-5"],
        ["--dry-run", "--model", "claude-haiku-4-5-20251001"],
        ["--dry-run", "--effort", "high"],  # the default model is claude-haiku-4-5
        ["--dry-run", "--model", "claude-haiku-4-5", "--effort", "low"],
        ["--dry-run", "--model", "claude-sonnet-5-5", "--effort", "max"],
        ["--dry-run", "--narrator", "nfl"],
        ["--dry-run", "--narrator", "qb", "--variant", "degraded"],
        ["--dry-run", "--narrator", "qb", "--case", "cfb-2005-champion"],
    ],
)
def test_bad_narrator_model_or_effort_is_refused(argv: list[str]) -> None:
    code, out, err = _main(argv)
    assert code == 2, (out, err)
    assert "refused" in err


@pytest.mark.parametrize(
    ("model", "effort"),
    [("claude-haiku-4-5", "n/a"), ("claude-haiku-5-5", "medium"), ("claude-sonnet-5-5", "medium")],
)
def test_a_qb_dry_run_prints_the_dataset_calls_and_dollars(model: str, effort: str) -> None:
    code, out, _ = _main(
        ["--dry-run", "--narrator", "qb", "--model", model, "--samples", "3", "--max-calls", "400"],
        environ={},
    )
    assert code == 0
    for spec in QB_CASE_SPECS:
        assert spec.id in out
    assert f"narrator qb · model {model} · effort {effort}" in out
    assert "8 cases x 3 samples x 1 variants x 3 = 72" in out
    assert "worst-case dollars" in out


def test_the_effort_override_shows_in_the_dry_run() -> None:
    code, out, _ = _main(
        ["--dry-run", "--narrator", "qb", "--model", "claude-sonnet-5-5", "--effort", "high"],
        environ={},
    )
    assert code == 0
    assert "effort high" in out


def test_the_team_dry_run_defaults_to_the_production_team_model() -> None:
    code, out, _ = _main(["--dry-run"], environ={})
    assert code == 0
    assert "narrator team · model claude-haiku-4-5 · effort n/a" in out
    assert "worst-case dollars" in out


# ---------------------------------------------------------------------------
# a QB run end to end
# ---------------------------------------------------------------------------

NARRATOR_USAGE = TokenUsage(
    input_tokens=1000, output_tokens=200, cache_creation_input_tokens=0, cache_read_input_tokens=0
)
GRADER_USAGE = TokenUsage(
    input_tokens=2000, output_tokens=500, cache_creation_input_tokens=0, cache_read_input_tokens=0
)


class _UsageGrader:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool, str]] = []

    def grade(self, *, fact_block_json: str, contested: bool, narration: str) -> Grade:
        self.calls.append((fact_block_json, contested, narration))
        return Grade(
            score=7,
            strengths=(),
            weaknesses=(),
            contradictions=(),
            reasoning="fine",
            ungraded_reason=None,
            stop_reason="end_turn",
            raw_text="",
            usage=GRADER_USAGE,
        )


def _with_usage(reply: NarratorReply) -> NarratorReply:
    return dataclasses.replace(reply, usage=NARRATOR_USAGE)


def test_a_qb_run_narrates_through_production_and_records_grades_and_cost(
    tmp_path: Path, qb_cases: dict[str, QbEvalCase]
) -> None:
    sweep_block = qb_cases[SWEEP].fact_block_json

    def reply_for(call: NarratorCall) -> Scripted:
        if sweep_block in call.user_texts[0]:
            return _with_usage(tool_reply(ACCEPTED_SWEEP))
        return _with_usage(tool_reply({"text": ACCEPTED_NARRATION, "claims": []}))

    narrator = FakeNarrator(reply_for=reply_for)
    grader = _UsageGrader()
    out_dir = tmp_path / "out"
    code, _, err = _main(
        [
            "--narrator",
            "qb",
            "--case",
            SWEEP,
            "--case",
            DECISIVE,
            "--max-calls",
            "6",
            "--out",
            str(out_dir),
        ],
        narrator=narrator,
        grader=grader,
    )
    assert code == 0, err
    # sweep: accepted first; decisive: claimless, rejected twice, the fallback
    assert len(narrator.calls) == 3 and len(grader.calls) == 2
    assert all(call.system == build_qb_system_prompt() for call in narrator.calls)

    sweep, decisive = (
        json.loads(line) for line in (out_dir / "records.jsonl").read_text().splitlines()
    )
    assert sweep["served_by"] == "first"
    assert sweep["served_text"] == ACCEPTED_SWEEP_TEXT
    assert sweep["narrator"] == "qb"
    assert sweep["narrator_model"] == "claude-haiku-4-5"
    assert sweep["qb_grades"] == {
        "no_hedge": True,
        "year_present": True,
        "winners_named": True,
        "margin_wording": True,
        "hedge_hits": [],
        "margin_violations": [],
    }
    assert sweep["usage"]["narrator"] == [dataclasses.asdict(NARRATOR_USAGE)]
    assert sweep["usage"]["grader"] == dataclasses.asdict(GRADER_USAGE)
    narrator_usd = (1000 * 1 + 200 * 5) / 1e6  # 0.002 on claude-haiku-4-5
    grader_usd = (2000 * 5 + 500 * 25) / 1e6  # 0.0225 on claude-opus-5
    assert sweep["cost_usd"]["narrator"] == pytest.approx(narrator_usd)
    assert sweep["cost_usd"]["total"] == pytest.approx(narrator_usd + grader_usd)

    assert decisive["served_by"] == "fallback"
    assert decisive["served_text"] == qb_cases[DECISIVE].fallback_text
    assert decisive["qb_grades"]["year_present"] is None
    assert decisive["qb_grades"]["margin_wording"] is None
    assert decisive["cost_usd"]["narrator"] == pytest.approx(2 * narrator_usd)

    report = json.loads((out_dir / "report.json").read_text())
    assert report["narrator"] == "qb"
    assert report["narrator_model"] == "claude-haiku-4-5"
    assert report["effort"] is None
    assert report["prompt_version"].startswith("qb-")
    metrics = report["variants"][0]["metrics"]
    assert metrics["first_try_rate"]["value"] == 0.5
    assert metrics["fallback_rate"]["value"] == 0.5
    assert metrics["qb_year_present_rate"]["value"] == 1.0
    assert metrics["qb_no_hedge_rate"]["value"] == 1.0
    assert metrics["usd_per_narration_narrator"]["value"] == pytest.approx(1.5 * narrator_usd)
    assert metrics["usd_per_narration_total"]["value"] == pytest.approx(
        1.5 * narrator_usd + grader_usd
    )
    assert "timing_venue_rate" not in metrics
    markdown = (out_dir / "report.md").read_text()
    assert "narrator: qb · model: claude-haiku-4-5 · effort: n/a" in markdown


def test_narration_cost_is_none_when_a_call_carries_no_usage(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    code, _, _ = _main(
        ["--narrator", "qb", "--case", SWEEP, "--max-calls", "3", "--out", str(out_dir)],
        narrator=FakeNarrator(reply_for=lambda call: tool_reply(ACCEPTED_SWEEP)),
        grader=_UsageGrader(),
    )
    assert code == 0
    (record,) = (json.loads(line) for line in (out_dir / "records.jsonl").read_text().splitlines())
    assert record["cost_usd"] == {"narrator": None, "total": None}
