"""`GET /api/players/compare` (issue #301): two players' careers and their
head-to-head record as QB starters, published faithfully from
`cfb_strength.players.get_player_comparison` on the committed fixture's real
NFL 1999 + 2023 slice.

Kurt Warner and Steve McNair are the anchor: they started against each other
twice in 1999, once in the regular season (a Titans win) and once in Super
Bowl XXXIV (a Rams win), so both head-to-heads are non-empty and swapping
`a` and `b` swaps wins and losses. Every number below is measured on the
fixture, so a faithful copy of a wrong engine answer still fails here.

Warner against Scott Mitchell is the null case: their 1999 week-1 game is
the one completed game in the slice with no player stat lines at all, so
both `a_stats` and `b_stats` are JSON `null` (never zeros, never an omitted
key), and they never met in the postseason. Brett Favre has no postseason
career in the slice, so his `postseason` is `null`.

The API adds no logic: no tally, no winner, nothing compared between `a`
and `b`. What it adds is the HTTP boundary only: `a == b` is a
request-validation 422 at `b`, an unknown or out-of-range id is the typed
`unknown_player` 404 echoing that id (`a` checked before `b`), and
`sport=cfb` is a 422. `compare` must never be parsed as a `player_id`.
"""

from __future__ import annotations

from typing import Any

import pytest
from cfb_strength.players import get_player_comparison
from fastapi.testclient import TestClient
from fixtures.player_api_fixture import engine_json, fixture_conn, stats_body

COMPARE = "/api/players/compare"

KURT_WARNER = 2044124519
STEVE_MCNAIR = 2385180619
SCOTT_MITCHELL = 2330103075
BRETT_FAVRE = 2003442211

SQLITE_INTEGER_MAX = 2**63 - 1

COMPARISON_KEYS = {"sport", "a", "b", "regular_season_head_to_head", "postseason_head_to_head"}
HEAD_TO_HEAD_KEYS = {"season_type", "record", "games"}
GAME_KEYS = {
    "season",
    "season_type",
    "week",
    "start_date",
    "source_id",
    "a_team",
    "b_team",
    "a_points",
    "b_points",
    "a_stats",
    "b_stats",
}


# One side of each measured game: (team, points, stats). Named, not
# positional: `PlayerStats` is append-only (34 fields since #313) and these
# are quarterback starts, so every stat not named here -- receiving, kicking,
# punting -- is None rather than a zero. `sack_yards_lost` is positive since
# #298; it was negative in these same four games before.
_WARNER_REGULAR = (
    "St. Louis Rams",
    21,
    stats_body(
        completions=29,
        attempts=46,
        passing_yards=328,
        passing_tds=3,
        passing_interceptions=0,
        sacks_suffered=6,
        sack_yards_lost=41,
        carries=2,
        rushing_yards=22,
        rushing_tds=0,
    ),
)
_MCNAIR_REGULAR = (
    "Tennessee Titans",
    24,
    stats_body(
        completions=13,
        attempts=29,
        passing_yards=186,
        passing_tds=2,
        passing_interceptions=0,
        sacks_suffered=1,
        sack_yards_lost=8,
        carries=12,
        rushing_yards=36,
        rushing_tds=1,
    ),
)
_WARNER_POSTSEASON = (
    "St. Louis Rams",
    23,
    stats_body(
        completions=24,
        attempts=45,
        passing_yards=414,
        passing_tds=2,
        passing_interceptions=0,
        sacks_suffered=2,
        sack_yards_lost=7,
        carries=1,
        rushing_yards=1,
        rushing_tds=0,
    ),
)
_MCNAIR_POSTSEASON = (
    "Tennessee Titans",
    16,
    stats_body(
        completions=22,
        attempts=36,
        passing_yards=214,
        passing_tds=0,
        passing_interceptions=0,
        sacks_suffered=1,
        sack_yards_lost=6,
        carries=8,
        rushing_yards=64,
        rushing_tds=0,
    ),
)

Side = tuple[str, int, dict[str, int | None]]


def _game(
    meta: dict[str, Any],
    a: Side,
    b: Side,
) -> dict[str, Any]:
    return {
        **meta,
        "a_team": a[0],
        "b_team": b[0],
        "a_points": a[1],
        "b_points": b[1],
        "a_stats": a[2],
        "b_stats": b[2],
    }


_REGULAR_META = {
    "season": 1999,
    "season_type": "regular",
    "week": 8,
    "start_date": "1999-10-31",
    "source_id": "1999_08_STL_TEN",
}
_POSTSEASON_META = {
    "season": 1999,
    "season_type": "postseason",
    "week": 21,
    "start_date": "2000-01-30",
    "source_id": "1999_21_STL_TEN",
}


def _record(wins: int, losses: int, ties: int) -> dict[str, int]:
    return {"wins": wins, "losses": losses, "ties": ties, "starts": wins + losses + ties}


def _compare(client: TestClient, **params: str | int) -> Any:
    response = client.get(COMPARE, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _validation_locs(response: Any) -> list[tuple[str, ...]]:
    detail = response.json()["detail"]
    assert isinstance(detail, list) and detail, detail
    return [tuple(error["loc"]) for error in detail]


# ---------------------------------------------------------------------------
# the Warner / McNair head-to-head, both ways round
# ---------------------------------------------------------------------------


def test_warner_vs_mcnair_head_to_head(client: TestClient) -> None:
    body = _compare(client, a=KURT_WARNER, b=STEVE_MCNAIR)

    assert body["sport"] == "nfl"
    assert body["regular_season_head_to_head"] == {
        "season_type": "regular",
        "record": _record(0, 1, 0),
        "games": [_game(_REGULAR_META, _WARNER_REGULAR, _MCNAIR_REGULAR)],
    }
    assert body["postseason_head_to_head"] == {
        "season_type": "postseason",
        "record": _record(1, 0, 0),
        "games": [_game(_POSTSEASON_META, _WARNER_POSTSEASON, _MCNAIR_POSTSEASON)],
    }


def test_swapping_a_and_b_swaps_the_sides_and_the_record(client: TestClient) -> None:
    body = _compare(client, a=STEVE_MCNAIR, b=KURT_WARNER)

    assert body["regular_season_head_to_head"] == {
        "season_type": "regular",
        "record": _record(1, 0, 0),
        "games": [_game(_REGULAR_META, _MCNAIR_REGULAR, _WARNER_REGULAR)],
    }
    assert body["postseason_head_to_head"] == {
        "season_type": "postseason",
        "record": _record(0, 1, 0),
        "games": [_game(_POSTSEASON_META, _MCNAIR_POSTSEASON, _WARNER_POSTSEASON)],
    }


def test_careers_carry_the_measured_totals(client: TestClient) -> None:
    body = _compare(client, a=KURT_WARNER, b=STEVE_MCNAIR)

    def summary(totals: dict[str, Any]) -> tuple[int | None, ...]:
        stats = totals["stats"]
        return (
            totals["games"],
            stats["passing_yards"],
            stats["passing_tds"],
            stats["passing_interceptions"],
            stats["completions"],
            stats["attempts"],
        )

    assert (body["a"]["player_id"], body["a"]["display_name"]) == (KURT_WARNER, "Kurt Warner")
    assert (body["b"]["player_id"], body["b"]["display_name"]) == (STEVE_MCNAIR, "Steve McNair")
    assert summary(body["a"]["regular_season"]) == (15, 4044, 38, 11, 297, 455)
    assert summary(body["a"]["postseason"])[:3] == (3, 1063, 8)
    assert summary(body["b"]["regular_season"]) == (11, 2179, 12, 8, 187, 331)
    assert summary(body["b"]["postseason"])[:3] == (4, 514, 1)


@pytest.mark.parametrize("a,b", [(KURT_WARNER, STEVE_MCNAIR), (STEVE_MCNAIR, KURT_WARNER)])
def test_a_and_b_equal_the_career_route(client: TestClient, a: int, b: int) -> None:
    body = _compare(client, a=a, b=b)

    for side, player_id in (("a", a), ("b", b)):
        career = client.get(f"/api/players/{player_id}")
        assert career.status_code == 200, career.text
        assert body[side] == career.json()


# ---------------------------------------------------------------------------
# faithful to the engine, nulls included
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "a,b",
    [
        (KURT_WARNER, STEVE_MCNAIR),
        (STEVE_MCNAIR, KURT_WARNER),
        (KURT_WARNER, SCOTT_MITCHELL),
        (BRETT_FAVRE, KURT_WARNER),
    ],
)
def test_comparison_is_the_engines_comparison_field_for_field(
    client: TestClient, a: int, b: int
) -> None:
    body = _compare(client, a=a, b=b)

    assert set(body) == COMPARISON_KEYS
    for key in ("regular_season_head_to_head", "postseason_head_to_head"):
        assert set(body[key]) == HEAD_TO_HEAD_KEYS
        for game in body[key]["games"]:
            assert set(game) == GAME_KEYS
    with fixture_conn() as conn:
        assert body == engine_json(get_player_comparison(conn, sport="nfl", a=a, b=b))


def test_a_game_without_stat_lines_publishes_null_stats(client: TestClient) -> None:
    body = _compare(client, a=KURT_WARNER, b=SCOTT_MITCHELL)

    assert body["regular_season_head_to_head"] == {
        "season_type": "regular",
        "record": _record(1, 0, 0),
        "games": [
            {
                "season": 1999,
                "season_type": "regular",
                "week": 1,
                "start_date": "1999-09-12",
                "source_id": "1999_01_BAL_STL",
                "a_team": "St. Louis Rams",
                "b_team": "Baltimore Ravens",
                "a_points": 27,
                "b_points": 10,
                "a_stats": None,
                "b_stats": None,
            }
        ],
    }
    assert body["postseason_head_to_head"] == {
        "season_type": "postseason",
        "record": _record(0, 0, 0),
        "games": [],
    }


def test_a_career_without_a_postseason_publishes_null(client: TestClient) -> None:
    body = _compare(client, a=BRETT_FAVRE, b=KURT_WARNER)

    assert "postseason" in body["a"]
    assert body["a"]["postseason"] is None
    assert body["a"]["regular_season"] is not None


def test_sport_defaults_to_nfl(client: TestClient) -> None:
    assert _compare(client, a=KURT_WARNER, b=STEVE_MCNAIR) == _compare(
        client, a=KURT_WARNER, b=STEVE_MCNAIR, sport="nfl"
    )


# ---------------------------------------------------------------------------
# route matching: `compare` is never a player_id
# ---------------------------------------------------------------------------


def test_compare_reaches_its_own_route_not_the_career_route(client: TestClient) -> None:
    response = client.get(COMPARE)

    assert response.status_code == 422, response.text
    assert sorted(_validation_locs(response)) == [("query", "a"), ("query", "b")]


def test_the_career_route_still_answers_for_an_id(client: TestClient) -> None:
    response = client.get(f"/api/players/{KURT_WARNER}")

    assert response.status_code == 200, response.text
    assert response.json()["display_name"] == "Kurt Warner"


# ---------------------------------------------------------------------------
# errors
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("player_id", [KURT_WARNER, 1, SQLITE_INTEGER_MAX + 1])
def test_the_same_player_twice_is_a_422_at_b(client: TestClient, player_id: int) -> None:
    response = client.get(COMPARE, params={"a": player_id, "b": player_id})

    assert response.status_code == 422, response.text
    assert _validation_locs(response) == [("query", "b")]


@pytest.mark.parametrize(
    "params,loc",
    [
        ({"b": STEVE_MCNAIR}, ("query", "a")),
        ({"a": KURT_WARNER}, ("query", "b")),
        ({"a": "warner", "b": STEVE_MCNAIR}, ("query", "a")),
        ({"a": KURT_WARNER, "b": "1.5"}, ("query", "b")),
    ],
    ids=["missing-a", "missing-b", "non-integer-a", "non-integer-b"],
)
def test_a_missing_or_non_integer_id_is_a_422(
    client: TestClient, params: dict[str, str | int], loc: tuple[str, str]
) -> None:
    response = client.get(COMPARE, params=params)

    assert response.status_code == 422, response.text
    assert loc in _validation_locs(response)


@pytest.mark.parametrize(
    "a,b,echoed",
    [
        (1, STEVE_MCNAIR, 1),
        (1, 2, 1),
        (KURT_WARNER, 2, 2),
        # An id no SQLite INTEGER can hold never reaches sqlite3 (#296's rule).
        (SQLITE_INTEGER_MAX + 1, STEVE_MCNAIR, SQLITE_INTEGER_MAX + 1),
        (KURT_WARNER, -(2**63) - 1, -(2**63) - 1),
        (SQLITE_INTEGER_MAX + 1, 2, SQLITE_INTEGER_MAX + 1),
    ],
    ids=[
        "unknown-a",
        "both-unknown-a-first",
        "unknown-b-known-a",
        "a-past-sqlite-range",
        "b-past-sqlite-range",
        "a-past-range-before-unknown-b",
    ],
)
def test_an_unknown_player_is_a_typed_404_echoing_that_id(
    client: TestClient, a: int, b: int, echoed: int
) -> None:
    response = client.get(COMPARE, params={"a": a, "b": b})

    assert response.status_code == 404, response.text
    assert response.json() == {
        "detail": {"error": "unknown_player", "player_id": echoed, "sport": "nfl"}
    }


@pytest.mark.parametrize("sport", ["cfb", "basketball"])
def test_a_non_nfl_sport_is_a_422_at_sport(client: TestClient, sport: str) -> None:
    response = client.get(COMPARE, params={"a": KURT_WARNER, "b": STEVE_MCNAIR, "sport": sport})

    assert response.status_code == 422, response.text
    assert ("query", "sport") in _validation_locs(response)


# ---------------------------------------------------------------------------
# /openapi.json
# ---------------------------------------------------------------------------


def test_openapi_documents_the_route_and_its_unknown_player_404(client: TestClient) -> None:
    openapi = client.get("/openapi.json").json()
    operation = openapi["paths"][COMPARE]["get"]

    ok = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert ok == {"$ref": "#/components/schemas/PlayerComparisonOut"}
    not_found = operation["responses"]["404"]["content"]["application/json"]["schema"]
    assert not_found == {"$ref": "#/components/schemas/UnknownPlayerErrorResponse"}
    assert {p["name"] for p in operation["parameters"]} == {"a", "b", "sport"}
