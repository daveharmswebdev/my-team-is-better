"""A per-process cap on Claude calls per rolling minute (issue #236).

Before this, a script could POST cache-missing verdicts as fast as it liked
and each one cost up to two Claude calls. `api.persona.narrate` now asks a
`CallBudget` for one unit before every `Narrator.submit`, the grounding retry
included. A refused unit means no call: `narrate` serves the templated
fallback, which the service returns with `cached=False` and never caches,
exactly as it does after a Claude transport error (issue #65). A cache hit
never reaches `narrate`, so it costs nothing and is served while the budget
is spent.

`RollingWindowCallBudget` keeps the timestamps of the units spent in the last
`window_seconds` and refuses once there are `limit` of them; each unit comes
back `window_seconds` after it was spent, so the budget recovers on its own
with no reset job. A refused request spends nothing, so hammering an
exhausted budget doesn't push its recovery further out. It is one in-memory
counter per process (`api.deps.get_call_budget`), which bounds spend because
Render runs the API as a single process. Not per client: one heavy user can
spend the budget for everyone, who then get the fallback until it recovers.
Per-IP keying or a shared store would be a later step.

The routes run as sync handlers on FastAPI's threadpool, so the counter is
guarded by a lock.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Protocol


class CallBudget(Protocol):
    """Grants or refuses one Claude call."""

    def try_acquire(self) -> bool:
        """Spend one unit and return `True`, or return `False` and spend
        nothing when none is left."""
        ...


class RollingWindowCallBudget:
    """At most `limit` units in any `window_seconds`. `clock` is a monotonic
    clock in seconds, injectable for tests. A `limit` of 0 refuses every
    call."""

    def __init__(
        self,
        limit: int,
        *,
        window_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if limit < 0:
            raise ValueError(f"call budget limit must be >= 0, got {limit}")
        if window_seconds <= 0:
            raise ValueError(f"call budget window must be > 0 seconds, got {window_seconds}")
        self.limit = limit
        self.window_seconds = window_seconds
        self._clock = clock
        self._spent: deque[float] = deque()
        self._lock = threading.Lock()

    def try_acquire(self) -> bool:
        with self._lock:
            now = self._clock()
            while self._spent and now - self._spent[0] >= self.window_seconds:
                self._spent.popleft()
            if len(self._spent) >= self.limit:
                return False
            self._spent.append(now)
            return True


class UnlimitedCallBudget:
    """Never refuses. For `APP_TEST_MODE`, whose `StubNarrator` costs
    nothing, and for callers that bound calls themselves (the persona eval
    harness has its own `--max-calls` cap)."""

    def try_acquire(self) -> bool:
        return True
