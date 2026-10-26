"""#464 and #462: the QB check's narrow fixes, one test per shape.

Rejected (#464, both served in #463's eval baseline):

1. A margin presented as a player's score: a winner placeholder or a typed
   name followed directly by "at" / "with" / a bare comma or space and then
   a margin placeholder ("{wc} at {mc} over the whole body of work" renders
   "Warner at 22.61", and 22.61 is the margin).
2. A lone score after "<name or winner placeholder> to" ("{wc} to {sc}"
   renders "Warner to McNair 0.60", a scoreline with one number).

Accepted (#462, each rejected before this round):

3. An opening clause about his best / peak / top seasons is no clause about
   the missing seasons, so "a different story" after it is a split, not
   speculation.
4. "Neither man runs away with it." on a close block: "neither" negates.
5. The winner backstop never reads across a sentence break ("Warner takes
   the career. On the peak, ...").

Also caught (#462 comment from #456):

6. Past-tense "took" / "won" are win verbs for the backstop.

Blocks: the real Warner/McNair fixture block (Warner sweeps, career 2.25 vs
0.60), and real fixture blocks rescored to live figures as in
`test_persona_qb_463_r3.py`: Brady/Flacco-shaped (Warner sweeps, decisive,
career margin 22.61) and Brady/Manning-shaped (split and close: Warner the
career by 0.10, McNair the peak by 0.04).
"""

from __future__ import annotations

import pytest
from fixtures.narrator_fake import FakeNarrator
from fixtures.qb_blocks import (
    KURT_WARNER,
    STEVE_MCNAIR,
    assert_an_error_says,
    nfl_player_names,
    qb_block,
    qb_evidence,
    qb_rejected,
    qb_rendered,
    qb_rendered_verdict,
    rescored_block,
)

from api.config import QB_NARRATOR_MODEL, QB_PROMPT_VERSION
from api.persona.budget import UnlimitedCallBudget
from api.persona.cache import CachedNarration, InMemoryNarrationCache, qb_cache_key
from api.persona.qb_claims import QB_GROUNDING_VERSION
from api.persona.service import narrate_qb_comparison, qb_fact_block_json

YEAR: dict[str, object] = {"id": "yr", "kind": "year"}
W_BOTH: dict[str, object] = {"id": "w", "kind": "winner", "measure": "both"}
W_CAREER: dict[str, object] = {"id": "wc", "kind": "winner", "measure": "career"}
C_CAREER: dict[str, object] = {"id": "c", "kind": "winner", "measure": "career"}
P_PEAK: dict[str, object] = {"id": "p", "kind": "winner", "measure": "peak"}
M_CAREER: dict[str, object] = {
    "id": "mc",
    "kind": "margin",
    "measure": "career",
    "player": "Warner",
}
S_MCNAIR: dict[str, object] = {"id": "sc", "kind": "score", "measure": "career", "player": "McNair"}
S_WARNER: dict[str, object] = {"id": "sw", "kind": "score", "measure": "career", "player": "Warner"}


def _wm() -> str:
    """Warner/McNair as the fixture has it: Warner sweeps, clear on both."""
    return qb_block(KURT_WARNER, STEVE_MCNAIR)


def _brady_flacco() -> str:
    """Decisive on both, Warner sweeps: career 18.19 vs -4.42 (margin 22.61)."""
    return rescored_block(
        KURT_WARNER, STEVE_MCNAIR, career=(18.1914, -4.4199), peak=(1.7261, 0.1280)
    )


def _brady_manning() -> str:
    """Close on both, split: Warner the career, McNair the peak."""
    return rescored_block(
        KURT_WARNER, STEVE_MCNAIR, career=(18.1914, 18.0904), peak=(1.7261, 1.7704)
    )


def _used(text: str, *claims: dict[str, object]) -> tuple[dict[str, object], ...]:
    """The claims whose placeholder `text` uses, so an unused one is no error."""
    return tuple(claim for claim in claims if f"{{{claim['id']}}}" in text)


def _blocks() -> list[str]:
    return [_brady_flacco(), _wm()]


# ---------------------------------------------------------------------------
# 1. a margin presented as a player's score (#464)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("block", ["brady_flacco", "wm"])
@pytest.mark.parametrize(
    "text",
    [
        # The production narration from #464, on the eval's decisive block.
        "{w} takes both, {wc} at {mc} over the whole body of work, counting since {yr}.",
        "{w} takes both, {wc} with {mc} over the whole body of work, counting since {yr}.",
        "{w} takes both: {wc}, {mc} over the whole body of work, counting since {yr}.",
        "{w} takes both, {wc} {mc} over the whole body of work, counting since {yr}.",
        "{w} takes both, Warner at {mc} over the whole body of work, counting since {yr}.",
        "{w} takes both, Kurt Warner with {mc} on the career, counting since {yr}.",
    ],
)
def test_a_margin_right_after_a_player_is_rejected(block: str, text: str) -> None:
    shown = _brady_flacco() if block == "brady_flacco" else _wm()
    errors = qb_rejected(shown, text, *_used(text, W_BOTH, W_CAREER, M_CAREER, YEAR))
    assert_an_error_says(errors, "{mc} is a margin", "as if it were his score")


def test_the_production_margin_shape_is_named_in_the_feedback() -> None:
    errors = qb_rejected(
        _brady_flacco(),
        "{w} takes both, {wc} at {mc} over the whole body of work, counting since {yr}.",
        W_BOTH,
        W_CAREER,
        M_CAREER,
        YEAR,
    )
    assert_an_error_says(errors, '"by"')


@pytest.mark.parametrize(
    "text",
    [
        "{w} takes both, the career by {mc}, counting since {yr}.",
        "{w} takes both, {wc} by {mc} over the whole body of work, counting since {yr}.",
        "{w} takes both, and {wc} wins it by {mc}, counting since {yr}.",
        "{w} takes both, {wc} ahead by {mc}, counting since {yr}.",
    ],
)
def test_a_margin_with_by_still_passes(text: str) -> None:
    for block in _blocks():
        assert qb_rendered(block, text, *_used(text, W_BOTH, W_CAREER, M_CAREER, YEAR))


@pytest.mark.parametrize(
    "text",
    [
        "Warner wins it with room to spare.",
        "Warner at quarterback was the better player.",
    ],
)
def test_at_or_with_and_no_margin_after_it_passes(text: str) -> None:
    assert qb_rendered_verdict(_brady_flacco(), text) == text


# ---------------------------------------------------------------------------
# 2. a lone score after "<player> to" (#464)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        # The production narration from #464, on the real fixture block.
        "{w} takes both, {wc} to {sc} over the whole body of work, counting since {yr}.",
        "{w} takes both, Warner to {sc} over the whole body of work, counting since {yr}.",
        "{w} takes both, {wc} to {sw} on the career, counting since {yr}.",
    ],
)
def test_a_lone_score_after_player_to_is_rejected(text: str) -> None:
    for block in _blocks():
        errors = qb_rejected(block, text, *_used(text, W_BOTH, W_CAREER, S_MCNAIR, S_WARNER, YEAR))
        assert_an_error_says(errors, "is one player's score", "scoreline")


def test_a_full_scoreline_still_passes() -> None:
    text = "{w} takes both. On the career it's {sw} to {sc}, counting since {yr}."
    rendered = qb_rendered(_wm(), text, W_BOTH, S_WARNER, S_MCNAIR, YEAR)
    assert "Warner 2.25 to McNair 0.60" in rendered


def test_player_to_without_a_score_passes() -> None:
    text = "Warner to McNair is no contest."
    assert qb_rendered_verdict(_brady_flacco(), text) == text


# ---------------------------------------------------------------------------
# 3. an opener about his best seasons is no speculation (#462)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "seasons", ["his best seasons", "his peak years", "his top years", "his early peak"]
)
def test_an_opener_about_his_best_seasons_is_accepted(seasons: str) -> None:
    text = (
        f"{{c}} takes the career by a nose. If you look at {seasons}, it's a different "
        "story: {p} squeaks by. Counting since {yr}."
    )
    rendered = qb_rendered(_brady_manning(), text, C_CAREER, P_PEAK, YEAR)
    assert f"If you look at {seasons}, it's a different story: McNair squeaks by." in rendered


@pytest.mark.parametrize(
    "text",
    [
        "If his rookie year isn't in the books, it's a different story.",
        "If you look at his Houston years, it's a different story.",
        "If you look at his early career, it's a different story.",
        "If you look at his first few seasons, it's a different story.",
        "If you go back before the data, it's a different story.",
        "If you add his missing years, it's a different story.",
    ],
)
def test_an_opener_about_the_missing_seasons_is_still_speculation(text: str) -> None:
    assert_an_error_says(qb_rejected(_wm(), text), "different story", "missing seasons")


# ---------------------------------------------------------------------------
# 4. "neither" negates a margin word (#462)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Neither man runs away with it.",
        "Neither one pulls away.",
        "Neither of them runs away with it.",
    ],
)
def test_neither_negates_a_runaway_on_a_close_block(text: str) -> None:
    assert qb_rendered_verdict(_brady_manning(), text) == text


def test_a_runaway_without_neither_is_still_rejected_on_a_close_block() -> None:
    errors = qb_rejected(_brady_manning(), "Warner runs away with the career.")
    assert_an_error_says(errors, '"runs away"', "a close one")


# ---------------------------------------------------------------------------
# 5. the backstop never reads across a sentence break (#462)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Warner takes the career. On the peak, it's a different story.",
        "Warner takes the career. The peak is McNair's.",
    ],
)
def test_the_backstop_stops_at_the_sentence_break(text: str) -> None:
    assert qb_rendered_verdict(_brady_manning(), text) == text


def test_the_backstop_still_reads_its_own_sentence() -> None:
    errors = qb_rejected(_brady_manning(), "Warner takes the peak. McNair is fine.")
    assert_an_error_says(errors, "Warner takes ... peak")


# ---------------------------------------------------------------------------
# 6. "took" and "won" are win verbs (#462 comment from #456)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("block", "text", "said"),
    [
        ("wm", "McNair took the career.", "McNair took ... career"),
        ("wm", "McNair won the peak.", "McNair won ... peak"),
        ("split", "McNair took the career.", "McNair took ... career"),
        ("split", "Warner won the peak.", "Warner won ... peak"),
    ],
)
def test_took_and_won_contradicting_the_verdict_are_rejected(
    block: str, text: str, said: str
) -> None:
    shown = _wm() if block == "wm" else _brady_manning()
    assert_an_error_says(qb_rejected(shown, text), said)


@pytest.mark.parametrize(
    "text",
    [
        "Warner took the career.",
        "McNair won the peak.",
        "McNair's won-loss mark says nothing about the career.",
    ],
)
def test_took_and_won_for_the_real_winner_pass(text: str) -> None:
    assert qb_rendered_verdict(_brady_manning(), text) == text


# ---------------------------------------------------------------------------
# the cache: a narration written under the old rules misses
# ---------------------------------------------------------------------------


def test_a_narration_cached_under_qb_claims_v3_is_not_served() -> None:
    # "Warner at 1.65" passed qb-claims-v3 and may sit in the cache (#464).
    assert QB_GROUNDING_VERSION == "qb-claims-v4"
    evidence = qb_evidence(KURT_WARNER, STEVE_MCNAIR)
    old_key = qb_cache_key(
        sport="nfl",
        a=KURT_WARNER,
        b=STEVE_MCNAIR,
        qb_score_version=evidence.qb_score.version,
        prompt_version=QB_PROMPT_VERSION,
        fact_block_json=qb_fact_block_json(evidence),
        grounding_version="qb-claims-v3",
        model=QB_NARRATOR_MODEL,
    )
    cache = InMemoryNarrationCache()
    cache.set(old_key, CachedNarration(text="Warner takes both, Warner at 1.65.", contested=False))
    narrator = FakeNarrator(
        [
            {
                "text": "{w} takes both, the career by {mc}, counting since {yr}.",
                "claims": [W_BOTH, M_CAREER, YEAR],
            }
        ]
    )
    result = narrate_qb_comparison(
        evidence,
        player_names=nfl_player_names(),
        cache=cache,
        narrator=narrator,
        budget=UnlimitedCallBudget(),
    )
    assert result.cached is False
    assert result.text == "Warner takes both, the career by 1.65, counting since 1999."
    assert len(narrator.calls) == 1
