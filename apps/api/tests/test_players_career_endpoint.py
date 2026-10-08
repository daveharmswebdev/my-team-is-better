"""`GET /api/players/{player_id}` (issue #296): a player's career by season,
published faithfully from `cfb_strength.players.get_player_career`, on the
committed fixture's real NFL 1999 + 2023 slice.

Kurt Warner's 1999 is the anchor. His regular season carries the one
completed game in the slice with no player stat lines at all
(1999_01_BAL_STL), so `games_without_stat_lines` is 1 there and 0 in the
postseason: the disclosure a career page must show rather than silently
undercount. The numbers are measured on the regenerated fixture and agree
with the engine's full-build checks (4044 yds, 38 TD, 13-3-0).

Marvin Harrison's 1999 is the receiving anchor (#314): 193 targets, 115
catches, 1663 yards, 12 TD, his real line, published on the season line.

Brandon Aubrey's and Thomas Morstead's 2023 are the kicking and punting
anchors (#315). A specialist's line carries the other specialty's counts as
recorded zeros and its maximum (`fg_long` / `pt_long`) as null, never 0.

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
MARVIN_HARRISON = 2009851825
BRANDON_AUBREY = 2050278267
THOMAS_MORSTEAD = 2219362247

NO_RECEIVING = {
    "receptions": 0,
    "targets": 0,
    "receiving_yards": 0,
    "receiving_tds": 0,
    "receiving_first_downs": 0,
    "receiving_fumbles_lost": 0,
}

# A non-kicker's kicking and punting line (#315): the counts are the source's
# recorded zeros, and the two career maxima are null -- he has no longest
# field goal or punt, and 0 would read as a zero-yard one.
NO_KICKING_OR_PUNTING = {
    "fg_made": 0,
    "fg_att": 0,
    "fg_long": None,
    "fg_made_50_59": 0,
    "fg_made_60_": 0,
    "pat_made": 0,
    "pat_att": 0,
    "pt_att": 0,
    "pt_yards": 0,
    "pt_net_yards": 0,
    "pt_long": None,
    "pt_inside_20": 0,
}

WARNER_1999_REGULAR_STATS = {
    "completions": 297,
    "attempts": 455,
    "passing_yards": 4044,
    "passing_tds": 38,
    "passing_interceptions": 11,
    "sacks_suffered": 26,
    "sack_yards_lost": 176,
    "carries": 22,
    "rushing_yards": 93,
    "rushing_tds": 1,
    # A quarterback's receiving line is the source's recorded zeros (#314),
    # not null: nflverse records 0, and the API publishes what it records.
    **NO_RECEIVING,
    **NO_KICKING_OR_PUNTING,
}
WARNER_1999_POSTSEASON_STATS = {
    "completions": 77,
    "attempts": 121,
    "passing_yards": 1063,
    "passing_tds": 8,
    "passing_interceptions": 4,
    "sacks_suffered": 4,
    "sack_yards_lost": 24,
    "carries": 6,
    "rushing_yards": 3,
    "rushing_tds": 0,
    **NO_RECEIVING,
    **NO_KICKING_OR_PUNTING,
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


def test_harrison_1999_publishes_his_receiving_line(client: TestClient) -> None:
    """Marvin Harrison's real 1999 (#314): 193 targets, 115 catches, 1663
    yards, 12 TD in the regular season, measured on the fixture. A receiver
    is the anchor here because a quarterback's receiving line is all zeros,
    which a field that silently published 0 would also satisfy."""
    body = _career(client, MARVIN_HARRISON)

    assert (body["display_name"], body["position"]) == ("Marvin Harrison", "WR")
    regular = [
        line
        for line in body["seasons"]
        if (line["season"], line["season_type"]) == (1999, "regular")
    ]
    assert len(regular) == 1
    stats = regular[0]["stats"]
    assert {name: stats[name] for name in NO_RECEIVING} == {
        "receptions": 115,
        "targets": 193,
        "receiving_yards": 1663,
        "receiving_tds": 12,
        "receiving_first_downs": 79,
        "receiving_fumbles_lost": 1,
    }
    assert {name: stats[name] for name in ("passing_yards", "carries", "rushing_yards")} == {
        "passing_yards": 0,
        "carries": 1,
        "rushing_yards": 4,
    }
    postseason = body["postseason"]["stats"]
    assert (postseason["targets"], postseason["receptions"], postseason["receiving_yards"]) == (
        18,
        5,
        65,
    )


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


def _regular_line(body: Any, season: int) -> Any:
    lines = [
        line
        for line in body["seasons"]
        if (line["season"], line["season_type"]) == (season, "regular")
    ]
    assert len(lines) == 1, lines
    return lines[0]["stats"]


def test_aubrey_2023_publishes_his_kicking_line(client: TestClient) -> None:
    """Brandon Aubrey's real 2023 (#315): 36 of 38, long 60, nine from 50-59
    and one from 60+, 49 of 52 PATs. He never punted: punting counts 0,
    `pt_long` null."""
    body = _career(client, BRANDON_AUBREY)

    assert (body["display_name"], body["position"]) == ("Brandon Aubrey", "K")
    stats = _regular_line(body, 2023)
    assert {name: stats[name] for name in NO_KICKING_OR_PUNTING} == {
        "fg_made": 36,
        "fg_att": 38,
        "fg_long": 60,
        "fg_made_50_59": 9,
        "fg_made_60_": 1,
        "pat_made": 49,
        "pat_att": 52,
        "pt_att": 0,
        "pt_yards": 0,
        "pt_net_yards": 0,
        "pt_long": None,
        "pt_inside_20": 0,
    }
    totals = body["regular_season"]["stats"]
    assert (totals["fg_made"], totals["fg_att"], totals["fg_long"], totals["pt_long"]) == (
        36,
        38,
        60,
        None,
    )


def test_morstead_2023_publishes_his_punting_line(client: TestClient) -> None:
    """Thomas Morstead's real 2023 (#315): 99 punts, 4,831 yards, 4,136 net,
    long 62, 36 inside the 20. No field goal: `fg_long` null."""
    body = _career(client, THOMAS_MORSTEAD)

    assert (body["display_name"], body["position"]) == ("Thomas Morstead", "P")
    stats = _regular_line(body, 2023)
    assert {name: stats[name] for name in NO_KICKING_OR_PUNTING} == {
        "fg_made": 0,
        "fg_att": 0,
        "fg_long": None,
        "fg_made_50_59": 0,
        "fg_made_60_": 0,
        "pat_made": 0,
        "pat_att": 0,
        "pt_att": 99,
        "pt_yards": 4831,
        "pt_net_yards": 4136,
        "pt_long": 62,
        "pt_inside_20": 36,
    }


@pytest.mark.parametrize(
    "player_id",
    [KURT_WARNER, PATRICK_MAHOMES, BROCK_PURDY, MARVIN_HARRISON, BRANDON_AUBREY, THOMAS_MORSTEAD],
)
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
