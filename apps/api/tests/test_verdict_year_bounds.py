"""Failing-first tests for issue #189: an out-of-range `year` on any verdict
route answers the mapped `unknown_year` 404, never a 500.

Before this change `{"year": 100000000000000000000}` on /champion reached
sqlite3 in `_resolve_champion_name` and raised `OverflowError: Python int
too large to convert to SQLite INTEGER`, which no handler maps, so the route
answered 500. (Measured at the red run: /team-case and /compare already
answered the 404, because the engine's `_require_year` compares `year not
in years` in Python before any SQL binds the year -- they get the same
up-front check anyway, so the bound is one rule in one place rather than
an accident of query order.) The coordinator chose to map the bad year to
the existing `unknown_year` 404 rather than add a request-validation 422:
the web's `isVerdictErrorBody` guard already renders `unknown_year` with
its `available_years`, whereas a 422 collapses to a generic error line.

The bound is a 4-digit season year, 1000..9999 inclusive -- the same shape
the share-link parser (#184) accepts -- checked once, in a helper every
route calls before any SQL runs. `year` stays a plain `int` on the request
models so the body echo (`UnknownYearErrorBody.year`) carries the value as
sent, including the 21-digit one.

`available_years` must be the *real* list for the request's method and
sport (`cfb_strength.evidence.proof.list_available_years`), not a
placeholder: the web renders it as the "try one of these" list. On
`tests/fixtures/cfb_verdict_fixture.sqlite3` keener and elo are each rated
for exactly the seven golden seasons; `test_fixture_premise_seven_rated_years`
pins that so a fixture rebuild cannot silently invalidate the expectations
below.
"""

from __future__ import annotations

# `httpx2`, not `httpx`: starlette's `TestClient` prefers `httpx2` when both
# are installed, so that is the `Response` type it returns (see
# tests/test_deps_threading.py).
import httpx2
import pytest
from cfb_strength.db.connection import get_conn
from cfb_strength.evidence.proof import list_available_years
from conftest import FIXTURE_DB
from fastapi.testclient import TestClient

GOLDEN_YEARS = [2001, 2003, 2004, 2005, 2013, 2017, 2019]

OVERFLOWING_YEAR = 100000000000000000000  # > SQLite INTEGER (signed 64-bit)

# Each route with the smallest valid body it needs. The team names are real
# 2005 fixture teams, so with a *valid* year each body answers 200 -- the
# 404 below is the year check, not a failed team lookup.
ROUTES: list[tuple[str, dict[str, object]]] = [
    ("/api/verdict/champion", {}),
    ("/api/verdict/team-case", {"team": "USC"}),
    ("/api/verdict/compare", {"team_a": "USC", "team_b": "Texas"}),
]
ROUTE_IDS = ["champion", "team-case", "compare"]


def _assert_unknown_year(response: httpx2.Response, *, year: int, available: list[int]) -> None:
    assert response.status_code == 404, response.text
    detail = response.json()["detail"]
    assert detail["error"] == "unknown_year"
    assert detail["year"] == year
    assert detail["available_years"] == available


@pytest.mark.parametrize("method", ["keener", "elo"])
def test_fixture_premise_seven_rated_years(method: str) -> None:
    """The measured premise the expectations below rest on."""
    conn = get_conn(FIXTURE_DB, read_only=True)
    try:
        assert list_available_years(conn, method, "cfb") == GOLDEN_YEARS
    finally:
        conn.close()


@pytest.mark.parametrize(("path", "extra"), ROUTES, ids=ROUTE_IDS)
def test_overflowing_year_is_unknown_year_not_500(
    client: TestClient, path: str, extra: dict[str, object]
) -> None:
    response = client.post(path, json={"year": OVERFLOWING_YEAR, "sport": "cfb", **extra})

    _assert_unknown_year(response, year=OVERFLOWING_YEAR, available=GOLDEN_YEARS)


@pytest.mark.parametrize("year", [0, -1], ids=["zero", "negative"])
@pytest.mark.parametrize(("path", "extra"), ROUTES, ids=ROUTE_IDS)
def test_non_positive_year_is_unknown_year(
    client: TestClient, path: str, extra: dict[str, object], year: int
) -> None:
    response = client.post(path, json={"year": year, **extra})

    _assert_unknown_year(response, year=year, available=GOLDEN_YEARS)


@pytest.mark.parametrize("year", [999, 10000], ids=["below-4-digits", "above-4-digits"])
@pytest.mark.parametrize(("path", "extra"), ROUTES, ids=ROUTE_IDS)
def test_year_just_outside_four_digits_is_unknown_year(
    client: TestClient, path: str, extra: dict[str, object], year: int
) -> None:
    """The bound is exactly 4 digits: 999 and 10000 are out, matching the
    share-link parser (#184) that requires exactly four."""
    response = client.post(path, json={"year": year, **extra})

    _assert_unknown_year(response, year=year, available=GOLDEN_YEARS)


@pytest.mark.parametrize(("path", "extra"), ROUTES, ids=ROUTE_IDS)
def test_overflowing_year_with_elo_lists_elo_years(
    client: TestClient, path: str, extra: dict[str, object]
) -> None:
    """`available_years` is looked up for the request's method, not a
    keener default."""
    response = client.post(path, json={"year": OVERFLOWING_YEAR, "method": "elo", **extra})

    _assert_unknown_year(response, year=OVERFLOWING_YEAR, available=GOLDEN_YEARS)
