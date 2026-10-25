"""The QB narration's pipeline and cache (issue #451): `narrate_qb_comparison`
goes through the same `narrate_checked` loop as the team verdicts (budget,
two attempts, retry feedback, fallback) and its own cache key.

The key is per ordered pair and covers `QB_SCORE_VERSION`, the QB prompt
version, the QB grounding version and the fact block, so a refit of the
score, a prompt change or a tightened check each misses. The fallback is
never cached, a cache hit makes no narrator call and spends no budget, and a
cache outage degrades to an uncached narration. Real fixture evidence,
`InMemoryNarrationCache`, a `FakeNarrator`: no Postgres, no Claude.
"""

from __future__ import annotations

import psycopg
import pytest
from fixtures.narrator_fake import FakeNarrator
from fixtures.qb_blocks import (
    KURT_WARNER,
    PEYTON_MANNING,
    RANDALL_CUNNINGHAM,
    STEVE_MCNAIR,
    TOMMY_DEVITO,
    nfl_player_names,
    qb_block,
    qb_evidence,
)

from api.config import PROMPT_VERSION, QB_PROMPT_VERSION
from api.models import NarrationOut, QbVerdictEvidenceOut
from api.persona import service
from api.persona.budget import RollingWindowCallBudget, UnlimitedCallBudget
from api.persona.cache import CachedNarration, InMemoryNarrationCache, qb_cache_key
from api.persona.fallback import qb_comparison_fallback_text
from api.persona.qb_claims import QB_GROUNDING_VERSION
from api.persona.qb_prompt import build_qb_system_prompt
from api.persona.service import narrate_qb_comparison, qb_fact_block_json

ACCEPTED: dict[str, object] = {
    "text": "{w} takes the career by {m}, counting since {yr}.",
    "claims": [
        {"id": "w", "kind": "winner", "measure": "career"},
        {"id": "m", "kind": "margin", "measure": "career", "player": "Warner"},
        {"id": "yr", "kind": "year"},
    ],
}
ACCEPTED_TEXT = "Warner takes the career by 1.65, counting since 1999."
REJECTED = "Warner wins by 987654."


def _evidence() -> QbVerdictEvidenceOut:
    return qb_evidence(KURT_WARNER, STEVE_MCNAIR)


def _ask(
    cache: InMemoryNarrationCache,
    narrator: FakeNarrator,
    *,
    evidence: QbVerdictEvidenceOut | None = None,
    budget: RollingWindowCallBudget | UnlimitedCallBudget | None = None,
) -> NarrationOut:
    return narrate_qb_comparison(
        evidence or _evidence(),
        player_names=nfl_player_names(),
        cache=cache,
        narrator=narrator,
        budget=budget or UnlimitedCallBudget(),
    )


def _key(**overrides: object) -> str:
    evidence = _evidence()
    arguments: dict[str, object] = {
        "sport": "nfl",
        "a": KURT_WARNER,
        "b": STEVE_MCNAIR,
        "qb_score_version": evidence.qb_score.version,
        "prompt_version": QB_PROMPT_VERSION,
        "fact_block_json": qb_fact_block_json(evidence),
        "grounding_version": QB_GROUNDING_VERSION,
    }
    arguments.update(overrides)
    return qb_cache_key(**arguments)  # type: ignore[arg-type]  # test-built kwargs


# ---------------------------------------------------------------------------
# the key
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "override",
    [
        {"qb_score_version": "2"},
        {"prompt_version": QB_PROMPT_VERSION + "-next"},
        {"grounding_version": QB_GROUNDING_VERSION + "-tightened"},
        {"fact_block_json": qb_block(KURT_WARNER, PEYTON_MANNING)},
        {"a": STEVE_MCNAIR, "b": KURT_WARNER},
    ],
    ids=["qb-score-version", "qb-prompt-version", "qb-grounding-version", "block", "order"],
)
def test_the_key_changes_with_each_input(override: dict[str, object]) -> None:
    assert _key(**override) != _key()


def test_the_qb_prompt_version_is_its_own_and_the_team_one_is_unchanged() -> None:
    assert PROMPT_VERSION == "persona-v13"
    assert QB_PROMPT_VERSION != PROMPT_VERSION
    assert QB_PROMPT_VERSION.startswith("qb-")


def test_the_service_writes_under_the_documented_key() -> None:
    cache = InMemoryNarrationCache()
    _ask(cache, FakeNarrator([ACCEPTED]))
    assert cache.get(_key()) == CachedNarration(text=ACCEPTED_TEXT, contested=False)


def test_a_qb_score_version_bump_misses(monkeypatch: pytest.MonkeyPatch) -> None:
    cache = InMemoryNarrationCache()
    _ask(cache, FakeNarrator([ACCEPTED]))
    monkeypatch.setattr(service, "QB_SCORE_VERSION", "refit")
    narrator = FakeNarrator([ACCEPTED])
    assert _ask(cache, narrator).cached is False
    assert len(narrator.calls) == 1


def test_a_qb_prompt_version_bump_misses(monkeypatch: pytest.MonkeyPatch) -> None:
    cache = InMemoryNarrationCache()
    _ask(cache, FakeNarrator([ACCEPTED]))
    monkeypatch.setattr(service, "QB_PROMPT_VERSION", QB_PROMPT_VERSION + "-next")
    narrator = FakeNarrator([ACCEPTED])
    assert _ask(cache, narrator).cached is False
    assert len(narrator.calls) == 1


# ---------------------------------------------------------------------------
# hits, misses and the fallback
# ---------------------------------------------------------------------------


def test_a_miss_narrates_and_caches_and_a_hit_spends_nothing() -> None:
    cache = InMemoryNarrationCache()
    first = _ask(cache, FakeNarrator([ACCEPTED]))
    assert first == NarrationOut(text=ACCEPTED_TEXT, contested=False, cached=False)

    # A spent budget: a hit must not need a unit, and must not call.
    spent = RollingWindowCallBudget(0)
    narrator = FakeNarrator([])
    hit = _ask(cache, narrator, budget=spent)
    assert hit == NarrationOut(text=ACCEPTED_TEXT, contested=False, cached=True)
    assert narrator.calls == []


def test_two_rejections_serve_the_fallback_uncached() -> None:
    cache = InMemoryNarrationCache()
    narrator = FakeNarrator([REJECTED, REJECTED])
    result = _ask(cache, narrator)
    assert result == NarrationOut(
        text=qb_comparison_fallback_text(_evidence()), contested=False, cached=False
    )
    assert cache.get(_key()) is None
    # The retry carried the validator's feedback, naming what the block holds.
    feedback = narrator.calls[1].retry_feedback
    assert feedback is not None
    assert "987654" in feedback and "Kurt Warner career 2.25" in feedback
    # The next request asks again.
    again = FakeNarrator([ACCEPTED])
    assert _ask(cache, again).cached is False
    assert len(again.calls) == 1


def test_a_rejection_then_an_accepted_retry_is_served_and_cached() -> None:
    cache = InMemoryNarrationCache()
    narrator = FakeNarrator([REJECTED, ACCEPTED])
    assert _ask(cache, narrator).text == ACCEPTED_TEXT
    assert cache.get(_key()) is not None


def test_a_spent_budget_serves_the_fallback_without_a_call() -> None:
    cache = InMemoryNarrationCache()
    narrator = FakeNarrator([])
    result = _ask(cache, narrator, budget=RollingWindowCallBudget(0))
    assert result.text == qb_comparison_fallback_text(_evidence())
    assert narrator.calls == []
    assert cache.get(_key()) is None


def test_a_legacy_fallback_row_is_a_miss() -> None:
    cache = InMemoryNarrationCache()
    cache.set(
        _key(), CachedNarration(text=qb_comparison_fallback_text(_evidence()), contested=False)
    )
    narrator = FakeNarrator([ACCEPTED])
    assert _ask(cache, narrator).text == ACCEPTED_TEXT
    assert len(narrator.calls) == 1


class _BrokenCache:
    def get(self, key: str) -> CachedNarration | None:
        raise psycopg.OperationalError("down")

    def set(self, key: str, narration: CachedNarration) -> None:
        raise psycopg.OperationalError("down")


def test_a_cache_outage_narrates_uncached() -> None:
    result = narrate_qb_comparison(
        _evidence(),
        player_names=nfl_player_names(),
        cache=_BrokenCache(),
        narrator=FakeNarrator([ACCEPTED]),
        budget=UnlimitedCallBudget(),
    )
    assert result == NarrationOut(text=ACCEPTED_TEXT, contested=False, cached=False)


def test_the_narrator_gets_the_qb_prompt_and_the_qb_block() -> None:
    narrator = FakeNarrator([ACCEPTED])
    _ask(InMemoryNarrationCache(), narrator)
    (call,) = narrator.calls
    assert call.system == build_qb_system_prompt()
    assert qb_fact_block_json(_evidence()) in call.user_texts[0]


# ---------------------------------------------------------------------------
# the fallback: a pure template of the block, in voice
# ---------------------------------------------------------------------------


def test_the_fallback_for_one_winner_of_both() -> None:
    assert qb_comparison_fallback_text(_evidence()) == (
        "Kurt Warner takes the career and the peak on the QB score, counting since 1999. "
        "Kurt Warner's and Steve McNair's careers began before 1999, and those seasons "
        "aren't in the books. My mouth's a little tied up right now, but the numbers speak "
        "for themselves."
    )


def test_the_fallback_for_split_winners_names_both() -> None:
    evidence = _evidence()
    split = evidence.model_copy(
        update={"qb_score": evidence.qb_score.model_copy(update={"peak_winner": "b"})}
    )
    assert qb_comparison_fallback_text(split) == (
        "Kurt Warner takes the career and Steve McNair takes the peak on the QB score, "
        "counting since 1999. Kurt Warner's and Steve McNair's careers began before 1999, "
        "and those seasons aren't in the books. My mouth's a little tied up right now, but "
        "the numbers speak for themselves."
    )


def test_the_fallback_when_one_side_does_not_qualify() -> None:
    assert qb_comparison_fallback_text(qb_evidence(TOMMY_DEVITO, KURT_WARNER)) == (
        "Tommy DeVito doesn't have a qualifying season on the QB score, counting since "
        "1999, so it's inconclusive: no winner to call. Kurt Warner's career began before "
        "1999, and those seasons aren't in the books. My mouth's a little tied up right "
        "now, but the numbers speak for themselves."
    )


def test_the_fallback_when_neither_side_qualifies() -> None:
    assert qb_comparison_fallback_text(qb_evidence(RANDALL_CUNNINGHAM, TOMMY_DEVITO)) == (
        "Neither Randall Cunningham nor Tommy DeVito has a qualifying season on the QB "
        "score, counting since 1999, so it's inconclusive: no winner to call. Randall "
        "Cunningham's career began before 1999, and those seasons aren't in the books. My "
        "mouth's a little tied up right now, but the numbers speak for themselves."
    )
