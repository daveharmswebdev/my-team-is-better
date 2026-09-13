"""Failing-first tests for issue #162: a display rounding of a *rating* is
grounded; every other rounding or derived figure is not (#108 stays open).

Every fact block here is the real one `api.persona.service` hands Claude,
built the same way the routes build it (`build_team_case`/`build_comparison`
-> `TeamCaseOut`/`ComparisonResultOut.from_dataclass(...).model_dump_json()`)
against the committed `cfb_verdict_fixture.sqlite3`. None are hand-typed JSON.

Fields named exactly `rating` in those real blocks (inspected for 2005 Texas
and USC under both `keener` and `elo`; identical key layout under both
methods):

* champion (`TeamCaseOut`): `rating` (top level) -- one value.
* team-case (`TeamCaseOut`): `rating` (top level) -- one value.
* compare (`ComparisonResultOut`): `team_a.rating`, `team_b.rating` -- two.

Fields named exactly `opponent_rating` are deliberately given the same
allowance (a real team's rating, restated): `games[].opponent_rating`,
`quality_wins[].opponent_rating`, `worst_loss.opponent_rating`.

Other floats present in those blocks that are deliberately NOT given the
rounding allowance: `rating_breakdown.residual_contribution`,
`rating_breakdown.entries[].credit` / `.contribution` (keener only -- Elo
blocks carry an empty `entries` list), and compare's `rating_diff` -- all
derived arithmetic (#108).

Real values these tests lean on, all pinned in
`test_fixture_values_these_tests_rely_on` so a regenerated fixture fails
loudly instead of silently changing what the other tests prove:

* Elo 2005 Texas `1933.1932908945062`: rounds to `1933` / `1933.2`. At one
  decimal, truncation (`1933.1`) differs from half-away-from-zero rounding.
* Elo 2005 USC `1891.8303466707475`: rounds to `1892`, truncates to `1891`.
* Keener 2005 Texas `0.005044108672990355`: rounds to `0.005` / `0.0050`.
* Keener 2005 USC `0.004736299273644764`: rounds to `0.005` / `0.00474`,
  truncates to `0.00473` at five decimals (at three, `0.004` is also the
  rounding of several opponents' `opponent_rating`s in USC's block).
* Elo compare `rating_diff` `41.36294422375863` (rounds to `41.4`); keener
  compare `rating_diff` `0.0003078093993455905` (rounds to `0.0003`).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from cfb_strength.db.connection import get_conn
from cfb_strength.evidence.proof import build_comparison, build_team_case
from fastapi.testclient import TestClient

from api.deps import get_narration_cache, get_narrator, list_all_team_names
from api.main import app
from api.models import ComparisonResultOut, TeamCaseOut
from api.persona.cache import InMemoryNarrationCache
from api.persona.grounding import find_ungrounded_tokens

FIXTURE_DB = Path(__file__).parent / "fixtures" / "cfb_verdict_fixture.sqlite3"


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = get_conn(FIXTURE_DB, read_only=True)
    try:
        yield connection
    finally:
        connection.close()


def _team_case_block(conn: sqlite3.Connection, team: str, method: str, year: int = 2005) -> str:
    case = build_team_case(conn, year, team, method=method, sport="cfb")
    return TeamCaseOut.from_dataclass(case).model_dump_json()


def _compare_block(conn: sqlite3.Connection, method: str) -> str:
    comparison = build_comparison(conn, 2005, "Texas", "USC", method=method, sport="cfb")
    return ComparisonResultOut.from_dataclass(comparison).model_dump_json()


def _check(conn: sqlite3.Connection, response: str, fact_block: str) -> list[str]:
    return find_ungrounded_tokens(response, fact_block, list_all_team_names(conn, "cfb"))


def test_fixture_values_these_tests_rely_on(conn: sqlite3.Connection) -> None:
    elo_texas = _team_case_block(conn, "Texas", "elo")
    elo_usc = _team_case_block(conn, "USC", "elo")
    keener_texas = _team_case_block(conn, "Texas", "keener")
    keener_usc = _team_case_block(conn, "USC", "keener")
    elo_compare = _compare_block(conn, "elo")
    keener_compare = _compare_block(conn, "keener")

    assert '"rating":1933.1932908945062' in elo_texas
    assert '"rating":1891.8303466707475' in elo_usc
    assert '"rating":0.005044108672990355' in keener_texas
    assert '"rating":0.004736299273644764' in keener_usc
    assert '"rating_diff":41.36294422375863' in elo_compare
    assert '"rating_diff":0.0003078093993455905' in keener_compare
    # USC's Elo rating sits in Texas's champion block only as an
    # `opponent_rating` (the scoping test below relies on that).
    assert '"opponent_rating":1891.8303466707475' in elo_texas
    assert '"rating":1891.8303466707475' not in elo_texas


# ---------------------------------------------------------------------------
# accepted: a rating rounded to fewer decimals, grouped or not
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "response",
    [
        "Elo rates Texas at 1933, and that's the whole argument.",
        "Elo rates Texas at 1933.2, and that's the whole argument.",
        "Elo rates Texas at 1,933, and that's the whole argument.",
        "Elo rates Texas at 1933.19, and that's the whole argument.",
        # The exact, unrounded literal is still grounded by plain membership.
        "Elo rates Texas at 1933.1932908945062, and that's the whole argument.",
    ],
)
def test_elo_rating_rounded_to_fewer_decimals_is_grounded(
    conn: sqlite3.Connection, response: str
) -> None:
    assert _check(conn, response, _team_case_block(conn, "Texas", "elo")) == []


def test_elo_rating_rounded_up_at_zero_decimals_is_grounded(conn: sqlite3.Connection) -> None:
    # 1891.83 -> 1892: half-away-from-zero rounding, not truncation.
    response = "Elo has USC at 1892 even with that loss."

    assert _check(conn, response, _team_case_block(conn, "USC", "elo")) == []


@pytest.mark.parametrize(
    ("team", "response"),
    [
        ("Texas", "Keener rates Texas at 0.005, top of the pile."),
        ("Texas", "Keener rates Texas at 0.0050, top of the pile."),
        ("Texas", "Keener rates Texas at 0.00504, top of the pile."),
        # 0.004736... rounds *up* to 0.005 at three decimals.
        ("USC", "Keener rates USC at 0.005, right there with anybody."),
    ],
)
def test_keener_rating_rounded_to_fewer_decimals_is_grounded(
    conn: sqlite3.Connection, team: str, response: str
) -> None:
    assert _check(conn, response, _team_case_block(conn, team, "keener")) == []


def test_both_compare_ratings_rounded_and_grouped_are_grounded(conn: sqlite3.Connection) -> None:
    response = "Elo has Texas at 1,933 and USC at 1892, and Texas beat USC 41-38 to settle it."

    assert _check(conn, response, _compare_block(conn, "elo")) == []


def test_keener_compare_ratings_rounded_are_grounded(conn: sqlite3.Connection) -> None:
    response = "Keener has Texas at 0.0050 and USC at 0.0047, and Texas beat USC 41-38."

    assert _check(conn, response, _compare_block(conn, "keener")) == []


def test_grouped_rating_does_not_break_record_and_score_tokens(conn: sqlite3.Connection) -> None:
    response = "Texas went 13-0, beat USC 41-38, and Elo has them at 1,933."

    assert _check(conn, response, _team_case_block(conn, "Texas", "elo")) == []


# ---------------------------------------------------------------------------
# rejected: anything that isn't the half-away-from-zero rounding of a `rating`
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("team", "method", "response", "flagged"),
    [
        # Off by one from the correct rounding.
        ("Texas", "elo", "Elo rates Texas at 1934.", "1934"),
        # Whole-number fabrication.
        ("Texas", "elo", "Elo rates Texas at 1900.", "1900"),
        # Truncation, where it differs from rounding (all real fixture values).
        ("Texas", "elo", "Elo rates Texas at 1933.1.", "1933.1"),
        ("USC", "elo", "Elo rates USC at 1891.", "1891"),
        # Five decimals, not three: at three, several USC opponents'
        # `opponent_rating`s legitimately round to 0.004, so a 0.004 claim
        # can't separate truncation from rounding in this block.
        ("USC", "keener", "Keener rates USC at 0.00473.", "0.00473"),
        # Right integer, wrong precision claim: 1933.19 to one decimal is 1933.2.
        ("Texas", "elo", "Elo rates Texas at 1933.0.", "1933.0"),
    ],
)
def test_number_that_is_not_the_rounding_of_a_rating_is_flagged(
    conn: sqlite3.Connection, team: str, method: str, response: str, flagged: str
) -> None:
    assert flagged in _check(conn, response, _team_case_block(conn, team, method))


def test_grouped_number_that_is_not_a_rounded_rating_is_flagged_in_grouped_form(
    conn: sqlite3.Connection,
) -> None:
    mismatches = _check(conn, "Elo rates Texas at 1,934.", _team_case_block(conn, "Texas", "elo"))

    assert "1,934" in mismatches
    assert "934" not in mismatches


@pytest.mark.parametrize(
    ("method", "response", "flagged"),
    [
        ("elo", "Texas leads USC by 41.4 rating points.", "41.4"),
        ("keener", "Texas leads USC by 0.0003 in the ratings.", "0.0003"),
    ],
)
def test_rounding_of_rating_diff_is_still_flagged(
    conn: sqlite3.Connection, method: str, response: str, flagged: str
) -> None:
    """`rating_diff` is a float in the same fact block, but it is derived
    arithmetic (#108), not a rating -- its rounding is not grounded."""
    assert flagged in _check(conn, response, _compare_block(conn, method))


def test_rounded_opponent_rating_is_grounded(conn: sqlite3.Connection) -> None:
    """Deliberately included (coordinator, #162): an `opponent_rating` is a
    real team's rating, restated -- not arithmetic. In Texas's champion block
    USC's Elo rating (1891.83) exists only as an `opponent_rating`, so without
    it #162's own example sentence would still fall back."""
    fact_block = _team_case_block(conn, "Texas", "elo")

    assert _check(conn, "Elo rates Texas at 1933 and USC at 1892.", fact_block) == []


def test_truncated_opponent_rating_is_still_flagged(conn: sqlite3.Connection) -> None:
    """The same half-away-from-zero rule applies to `opponent_rating`."""
    mismatches = _check(conn, "Elo rates USC at 1891.", _team_case_block(conn, "Texas", "elo"))

    assert "1891" in mismatches


@pytest.mark.parametrize("method", ["keener", "elo"])
def test_winning_percentage_from_an_even_record_is_still_flagged(
    conn: sqlite3.Connection, method: str
) -> None:
    """#108 is unchanged: `.500` derived from a real 6-6 record (2001 Kansas
    State) is arithmetic, not a rounding of a rating."""
    fact_block = _team_case_block(conn, "Kansas State", method, year=2001)
    assert '"wins":6,"losses":6' in fact_block

    mismatches = _check(conn, "Kansas State went 6-6, a .500 team.", fact_block)

    assert "500" in mismatches


# ---------------------------------------------------------------------------
# end to end: the rounded Elo rating is accepted on the first narrator call
# ---------------------------------------------------------------------------


class _ScriptedNarrator:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[list[dict[str, str]]] = []

    def complete(self, *, system: str, messages: list[dict[str, str]]) -> str:
        self.calls.append(messages)
        return self.responses.pop(0)


@pytest.mark.parametrize(
    ("route", "payload", "response"),
    [
        (
            "/api/verdict/compare",
            {"year": 2005, "team_a": "Texas", "team_b": "USC", "method": "elo"},
            "Elo has Texas at 1,933 and USC at 1892, and Texas beat USC 41-38 to prove it.",
        ),
        (
            "/api/verdict/champion",
            {"year": 2005, "method": "elo"},
            "Elo rates Texas at 1933 after a 13-0 run, and nobody's arguing.",
        ),
    ],
)
def test_rounded_elo_rating_narration_is_served_on_the_first_call(
    client: TestClient, route: str, payload: dict[str, object], response: str
) -> None:
    narrator = _ScriptedNarrator([response])
    app.dependency_overrides[get_narration_cache] = lambda: InMemoryNarrationCache()
    app.dependency_overrides[get_narrator] = lambda: narrator
    try:
        http_response = client.post(route, json=payload)
    finally:
        app.dependency_overrides.pop(get_narration_cache, None)
        app.dependency_overrides.pop(get_narrator, None)

    assert http_response.status_code == 200, http_response.json()
    assert http_response.json()["narration"]["text"] == response
    assert len(narrator.calls) == 1
