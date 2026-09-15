"""`GET /api/players/{player_id}` (issue #296): a player's career by season,
published faithfully from `cfb_strength.players.get_player_career`, on the
committed fixture's real NFL 1999 + 2023 slice.

Kurt Warner's 1999 is the anchor. His regular season carries the one
completed game in the slice with no player stat lines at all
(1999_01_BAL_STL), so `games_without_stat_lines` is 1 there and 0 in the
postseason: the disclosure a career page must show rather than silently
undercount. The numbers are measured on the regenerated fixture and agree
with the engine's full-build checks (4044 yds, 38 TD, 13-3-0).

An unknown id is the typed `unknown_player` 404, echoing what was asked,
including an id no SQLite INTEGER can hold (the same "echo what was sent,
don't 500" rule #189 set for years). `sport=cfb` is a 422, not a 404: the
id may be a real NFL player, and CFB has no player stats to look in.
"""

from __future__ import annotations

from typing import Any

import pytest
from cfb_strength.players import get_player_career
from fastapi.testclient import TestClient
from fixtures.player_api_fixture import engine_json, fixture_conn

KURT_WARNER = 2044124519
PATRICK_MAHOMES = 2319407936
BROCK_PURDY = 2134524419

WARNER_1999_REGULAR_STATS = {
    "completions": 297,
    "attempts": 455,
    "passing_yards": 4044,
    "passing_tds": 38,
    "passing_interceptions": 11,
    "sacks_suffered": 26,
    "sack_yards_lost": -176,
    "carries": 22,
    "rushing_yards": 93,
    "rushing_tds": 1,
}
WARNER_1999_POSTSEASON_STATS = {
    "completions": 77,
    "attempts": 121,
    "passing_yards": 1063,
    "passing_tds": 8,
    "passing_interceptions": 4,
    "sacks_suffered": 4,
    "sack_yards_lost": -24,
    "carries": 6,
    "rushing_yards": 3,
    "rushing_tds": 0,
}


def _career(client: TestClient, player_id: int, **params: str | int) -> Any:
    response = client.get(f"/api/players/{player_id}", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_warner_1999_lines_disclose_the_game_without_stat_lines(client: TestClient) -> None:
    body = _career(client, KURT_WARNER)

    assert set(body) == {
        "sport",
        "player_id",
        "display_name",
        "position",
        "seasons",
        "regular_season",
        "postseason",
    }
    assert (body["sport"], body["player_id"], body["display_name"], body["position"]) == (
        "nfl",
        KURT_WARNER,
        "Kurt Warner",
        "QB",
    )
    assert body["seasons"] == [
        {
            "season": 1999,
            "season_type": "regular",
            "teams": ["St. Louis Rams"],
            "games": 15,
            "record": {"wins": 13, "losses": 3, "ties": 0, "starts": 16},
            "stats": WARNER_1999_REGULAR_STATS,
            "games_without_stat_lines": 1,
        },
        {
            "season": 1999,
            "season_type": "postseason",
            "teams": ["St. Louis Rams"],
            "games": 3,
            "record": {"wins": 3, "losses": 0, "ties": 0, "starts": 3},
            "stats": WARNER_1999_POSTSEASON_STATS,
            "games_without_stat_lines": 0,
        },
    ]


def test_warner_regular_and_postseason_totals(client: TestClient) -> None:
    body = _career(client, KURT_WARNER)

    assert body["regular_season"] == {
        "season_type": "regular",
        "seasons": 1,
        "games": 15,
        "record": {"wins": 13, "losses": 3, "ties": 0, "starts": 16},
        "stats": WARNER_1999_REGULAR_STATS,
    }
    assert body["postseason"] == {
        "season_type": "postseason",
        "seasons": 1,
        "games": 3,
        "record": {"wins": 3, "losses": 0, "ties": 0, "starts": 3},
        "stats": WARNER_1999_POSTSEASON_STATS,
    }


@pytest.mark.parametrize(
    "player_id,teams,postseason_starts",
    [
        (PATRICK_MAHOMES, ["Kansas City Chiefs"], 4),
        (BROCK_PURDY, ["San Francisco 49ers"], 3),
    ],
)
def test_teams_and_postseason_starts(
    client: TestClient, player_id: int, teams: list[str], postseason_starts: int
) -> None:
    body = _career(client, player_id)

    assert [(s["season"], s["season_type"], s["teams"]) for s in body["seasons"]] == [
        (2023, "regular", teams),
        (2023, "postseason", teams),
    ]
    assert body["postseason"]["record"]["starts"] == postseason_starts


@pytest.mark.parametrize("player_id", [KURT_WARNER, PATRICK_MAHOMES, BROCK_PURDY])
def test_career_is_the_engines_career_field_for_field(client: TestClient, player_id: int) -> None:
    body = _career(client, player_id)

    with fixture_conn() as conn:
        assert body == engine_json(get_player_career(conn, sport="nfl", player_id=player_id))


def test_sport_defaults_to_nfl(client: TestClient) -> None:
    assert _career(client, KURT_WARNER) == _career(client, KURT_WARNER, sport="nfl")


# ---------------------------------------------------------------------------
# errors
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("player_id", [1, -5, 2**63, -(2**63) - 1])
def test_unknown_player_is_a_typed_404_echoing_the_request(
    client: TestClient, player_id: int
) -> None:
    response = client.get(f"/api/players/{player_id}")

    assert response.status_code == 404, response.text
    assert response.json() == {
        "detail": {"error": "unknown_player", "player_id": player_id, "sport": "nfl"}
    }


@pytest.mark.parametrize("sport", ["cfb", "basketball"])
def test_a_non_nfl_sport_is_a_422_at_sport_even_for_a_real_player(
    client: TestClient, sport: str
) -> None:
    response = client.get(f"/api/players/{KURT_WARNER}", params={"sport": sport})

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert isinstance(detail, list)
    assert any("sport" in tuple(error.get("loc", ())) for error in detail), detail


def test_a_non_integer_id_is_a_422(client: TestClient) -> None:
    response = client.get("/api/players/warner")

    assert response.status_code == 422
