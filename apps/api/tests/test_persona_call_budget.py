"""Issue #236: a per-process cap on Claude calls per rolling minute.

A script hammering the verdict routes with cache-missing requests used to
force up to two Claude calls per request, unbounded. Now every narrator call
(the first and the grounding retry alike) takes one unit from a rolling
60-second budget (`api.persona.budget.RollingWindowCallBudget`, sized by
`api.config.CLAUDE_CALLS_PER_MINUTE`). With the budget spent, a cache-missing
verdict makes no call and is served exactly the way a Claude outage is
(issue #65): 200, the templated fallback, `cached=False`, nothing written. A
cache hit takes nothing from the budget and is still served.

Every test here injects its own budget with a fake clock and a
`FakeNarrator`; nothing calls Claude or sleeps.
"""

from __future__ import annotations

import importlib
import logging
import sys
from collections.abc import Iterator
from types import ModuleType

import pytest
from fastapi.testclient import TestClient
from fixtures.claim_blocks import cfb_catalog, cfb_team_case_block
from fixtures.narrator_fake import ACCEPTED_NARRATION, FakeNarrator

import api
from api.models import ComparisonResultOut, TeamCaseOut
from api.persona.budget import CallBudget, RollingWindowCallBudget, UnlimitedCallBudget
from api.persona.cache import InMemoryNarrationCache
from api.persona.fallback import comparison_fallback_text, team_case_fallback_text
from api.persona.narrate import NarrationResult, narrate

# A number typed into the prose instead of claimed: rejected every time.
REJECTED = "They won that one by 987654 points."
FALLBACK_TEXT = "The templated fallback."


class FakeClock:
    """A monotonic clock the test moves by hand."""

    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _budget(limit: int, clock: FakeClock) -> RollingWindowCallBudget:
    return RollingWindowCallBudget(limit, window_seconds=60.0, clock=clock)


# ---------------------------------------------------------------------------
# the budget itself
# ---------------------------------------------------------------------------


def test_budget_allows_exactly_its_limit_within_the_window() -> None:
    clock = FakeClock()
    budget = _budget(3, clock)

    assert [budget.try_acquire() for _ in range(4)] == [True, True, True, False]


def test_budget_recovers_once_the_window_has_passed() -> None:
    clock = FakeClock()
    budget = _budget(2, clock)
    assert budget.try_acquire() and budget.try_acquire()
    assert not budget.try_acquire()

    clock.advance(59.9)
    assert not budget.try_acquire()

    clock.advance(0.1)
    assert budget.try_acquire()


def test_budget_window_is_rolling_not_fixed() -> None:
    """A unit comes back 60 seconds after *it* was spent, not at the top of
    some fixed minute: two spent at t=0 and one at t=30 free up separately."""
    clock = FakeClock()
    budget = _budget(3, clock)
    assert budget.try_acquire() and budget.try_acquire()
    clock.advance(30)
    assert budget.try_acquire()
    assert not budget.try_acquire()

    clock.advance(30)  # t=60: the two t=0 units are back, the t=30 one isn't
    assert budget.try_acquire() and budget.try_acquire()
    assert not budget.try_acquire()

    clock.advance(30)  # t=90: the t=30 unit is back
    assert budget.try_acquire()
    assert not budget.try_acquire()


def test_a_refused_request_does_not_spend_a_unit() -> None:
    """Hammering while exhausted must not push recovery further out."""
    clock = FakeClock()
    budget = _budget(1, clock)
    assert budget.try_acquire()
    for _ in range(50):
        clock.advance(1)
        assert not budget.try_acquire()

    clock.advance(10)  # t=60 from the one spent unit
    assert budget.try_acquire()


def test_a_zero_budget_refuses_every_call() -> None:
    budget = _budget(0, FakeClock())

    assert not budget.try_acquire()


@pytest.mark.parametrize("limit", [-1, -20])
def test_a_negative_limit_is_rejected(limit: int) -> None:
    with pytest.raises(ValueError, match="limit"):
        RollingWindowCallBudget(limit)


def test_unlimited_budget_never_refuses() -> None:
    budget = UnlimitedCallBudget()

    assert all(budget.try_acquire() for _ in range(1_000))


# ---------------------------------------------------------------------------
# narrate(): every call takes a unit, the retry included
# ---------------------------------------------------------------------------


def _narrate(narrator: FakeNarrator, budget: CallBudget) -> NarrationResult:
    return narrate(
        fact_block_json=cfb_team_case_block(2005, "Texas"),
        user_team=None,
        contested=False,
        catalog=cfb_catalog(),
        narrator=narrator,
        fallback_text=FALLBACK_TEXT,
        budget=budget,
    )


def test_an_exhausted_budget_makes_no_call_and_serves_the_fallback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    narrator = FakeNarrator()

    with caplog.at_level(logging.WARNING, logger="api.persona.narrate"):
        result = _narrate(narrator, _budget(0, FakeClock()))

    assert result == NarrationResult(text=FALLBACK_TEXT, is_fallback=True)
    assert narrator.calls == []
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "budget" in warnings[0].getMessage()


def test_the_grounding_retry_takes_a_second_unit() -> None:
    clock = FakeClock()
    budget = _budget(2, clock)
    narrator = FakeNarrator([REJECTED, ACCEPTED_NARRATION])

    result = _narrate(narrator, budget)

    assert result == NarrationResult(text=ACCEPTED_NARRATION, is_fallback=False)
    assert len(narrator.calls) == 2
    assert not budget.try_acquire()


def test_a_retry_past_the_budget_serves_the_fallback_not_the_ungrounded_first_attempt(
    caplog: pytest.LogCaptureFixture,
) -> None:
    narrator = FakeNarrator([REJECTED, ACCEPTED_NARRATION])

    with caplog.at_level(logging.WARNING, logger="api.persona.narrate"):
        result = _narrate(narrator, _budget(1, FakeClock()))

    assert result == NarrationResult(text=FALLBACK_TEXT, is_fallback=True)
    assert len(narrator.calls) == 1
    assert narrator.pending == 1
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "budget" in warnings[0].getMessage()


def test_an_accepted_first_call_takes_one_unit() -> None:
    budget = _budget(2, FakeClock())
    narrator = FakeNarrator()

    assert _narrate(narrator, budget).is_fallback is False
    assert budget.try_acquire()
    assert not budget.try_acquire()


# ---------------------------------------------------------------------------
# the three verdict routes
# ---------------------------------------------------------------------------

ROUTES: dict[str, tuple[str, dict[str, object]]] = {
    "champion": ("/api/verdict/champion", {"year": 2005}),
    "team-case": ("/api/verdict/team-case", {"year": 2005, "team": "USC"}),
    "compare": ("/api/verdict/compare", {"year": 2005, "team_a": "Texas", "team_b": "USC"}),
}
# Three different cache keys for the same evidence: `user_team` is part of
# the key, and it does not change the fallback text.
USER_TEAMS: tuple[str | None, ...] = (None, "Texas", "USC")


class BudgetWiring:
    def __init__(self, client: TestClient, budget_limit: int) -> None:
        self.client = client
        self.clock = FakeClock()
        self.budget = _budget(budget_limit, self.clock)
        self.cache = InMemoryNarrationCache()
        self.narrator = FakeNarrator()

    def post(self, route: str, user_team: str | None) -> dict[str, object]:
        path, body = ROUTES[route]
        response = self.client.post(path, json={**body, "user_team": user_team})
        assert response.status_code == 200, response.text
        payload = response.json()
        assert isinstance(payload, dict)
        return payload


@pytest.fixture
def wiring(client: TestClient) -> Iterator[BudgetWiring]:
    from api.deps import get_call_budget, get_narration_cache, get_narrator
    from api.main import app

    wired = BudgetWiring(client, budget_limit=2)
    app.dependency_overrides[get_call_budget] = lambda: wired.budget
    app.dependency_overrides[get_narration_cache] = lambda: wired.cache
    app.dependency_overrides[get_narrator] = lambda: wired.narrator
    yield wired


def _narration(payload: dict[str, object]) -> dict[str, object]:
    narration = payload["narration"]
    assert isinstance(narration, dict)
    return narration


def _fallback_text(route: str, payload: dict[str, object]) -> str:
    if route == "compare":
        return comparison_fallback_text(ComparisonResultOut.model_validate(payload["evidence"]))
    return team_case_fallback_text(TeamCaseOut.model_validate(payload["evidence"]))


@pytest.mark.parametrize("route", list(ROUTES))
def test_route_serves_the_fallback_without_a_call_once_the_budget_is_spent(
    route: str, wiring: BudgetWiring, caplog: pytest.LogCaptureFixture
) -> None:
    first = wiring.post(route, USER_TEAMS[0])
    second = wiring.post(route, USER_TEAMS[1])
    assert first["narration"] == {"text": ACCEPTED_NARRATION, "contested": False, "cached": False}
    assert second["narration"] == first["narration"]
    assert len(wiring.narrator.calls) == 2

    with caplog.at_level(logging.WARNING, logger="api.persona.narrate"):
        degraded = wiring.post(route, USER_TEAMS[2])

    assert degraded["narration"] == {
        "text": _fallback_text(route, degraded),
        "contested": False,
        "cached": False,
    }
    assert degraded["narration"] != first["narration"]
    assert len(wiring.narrator.calls) == 2
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1


@pytest.mark.parametrize("route", list(ROUTES))
def test_route_serves_a_cache_hit_while_the_budget_is_spent(
    route: str, wiring: BudgetWiring
) -> None:
    wiring.post(route, USER_TEAMS[0])
    wiring.post(route, USER_TEAMS[1])
    assert _narration(wiring.post(route, USER_TEAMS[2]))["cached"] is False

    hit = wiring.post(route, USER_TEAMS[0])

    assert hit["narration"] == {"text": ACCEPTED_NARRATION, "contested": False, "cached": True}
    assert len(wiring.narrator.calls) == 2


@pytest.mark.parametrize("route", list(ROUTES))
def test_route_degraded_response_is_not_cached_and_the_budget_recovers(
    route: str, wiring: BudgetWiring
) -> None:
    wiring.post(route, USER_TEAMS[0])
    wiring.post(route, USER_TEAMS[1])
    degraded = wiring.post(route, USER_TEAMS[2])
    assert _narration(degraded)["text"] == _fallback_text(route, degraded)
    assert len(wiring.cache._store) == 2

    wiring.clock.advance(60)
    recovered = wiring.post(route, USER_TEAMS[2])

    assert recovered["narration"] == {
        "text": ACCEPTED_NARRATION,
        "contested": False,
        "cached": False,
    }
    assert len(wiring.narrator.calls) == 3
    assert len(wiring.cache._store) == 3


# ---------------------------------------------------------------------------
# config and wiring
# ---------------------------------------------------------------------------


def _restore_module(name: str, saved: ModuleType | None) -> None:
    """Put `saved` back in `sys.modules` and on the `api` package (see
    `tests/test_deps.py`'s helper of the same name for why both)."""
    attr = name.rpartition(".")[2]
    if saved is not None:
        sys.modules[name] = saved
        setattr(api, attr, saved)
    else:
        sys.modules.pop(name, None)
        if hasattr(api, attr):
            delattr(api, attr)


@pytest.fixture
def fresh_modules(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("MY_TEAM_IS_BETTER_API_ENV_FILE", "/nonexistent/.env")
    saved_config = sys.modules.get("api.config")
    saved_deps = sys.modules.get("api.deps")
    sys.modules.pop("api.config", None)
    sys.modules.pop("api.deps", None)
    yield
    _restore_module("api.config", saved_config)
    _restore_module("api.deps", saved_deps)


def test_calls_per_minute_has_a_default(
    monkeypatch: pytest.MonkeyPatch, fresh_modules: None
) -> None:
    monkeypatch.delenv("CLAUDE_CALLS_PER_MINUTE", raising=False)

    config = importlib.import_module("api.config")

    assert config.CLAUDE_CALLS_PER_MINUTE == 20


@pytest.mark.parametrize(("raw", "expected"), [("5", 5), (" 40 ", 40), ("0", 0)])
def test_calls_per_minute_reads_the_environment(
    monkeypatch: pytest.MonkeyPatch, fresh_modules: None, raw: str, expected: int
) -> None:
    monkeypatch.setenv("CLAUDE_CALLS_PER_MINUTE", raw)

    config = importlib.import_module("api.config")

    assert config.CLAUDE_CALLS_PER_MINUTE == expected


@pytest.mark.parametrize("raw", ["", "abc", "-1", "1.5", "ten"])
def test_an_invalid_calls_per_minute_fails_at_config_load(
    monkeypatch: pytest.MonkeyPatch, fresh_modules: None, raw: str
) -> None:
    monkeypatch.setenv("CLAUDE_CALLS_PER_MINUTE", raw)

    with pytest.raises(ValueError, match="CLAUDE_CALLS_PER_MINUTE"):
        importlib.import_module("api.config")


def test_production_budget_is_one_per_process_and_sized_from_config(
    monkeypatch: pytest.MonkeyPatch, fresh_modules: None
) -> None:
    monkeypatch.delenv("APP_TEST_MODE", raising=False)
    monkeypatch.setenv("CLAUDE_CALLS_PER_MINUTE", "7")

    deps = importlib.import_module("api.deps")

    budget = deps.get_call_budget()
    assert budget is deps.get_call_budget()
    assert isinstance(budget, RollingWindowCallBudget)
    assert budget.limit == 7
    assert budget.window_seconds == 60.0


def test_test_mode_budget_is_unlimited(
    monkeypatch: pytest.MonkeyPatch, fresh_modules: None
) -> None:
    """A booted e2e uvicorn (`APP_TEST_MODE=1`) narrates through the free
    `StubNarrator`; a cap there would only make the e2e suite flaky."""
    monkeypatch.setenv("APP_TEST_MODE", "1")

    deps = importlib.import_module("api.deps")

    assert isinstance(deps.get_call_budget(), UnlimitedCallBudget)
