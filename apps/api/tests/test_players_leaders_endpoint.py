"""`GET /api/players/leaders` (issue #296): a thin, faithful publication of
`cfb_strength.players.get_player_leaders` over the committed fixture's real
NFL 1999 + 2023 slice (`tests/fixtures/build_fixture.py`).

What is pinned, and why each matters to the leaders page apps/web builds:

- **Faithful.** Every response body equals the engine's own result for the
  same arguments, field for field (`engine_json`), plus `record.starts`.
  The API recomputes nothing: no re-sorting, no re-ranking, no 0-filling.
- **Real numbers.** Top rows are also pinned literally, measured on the
  regenerated fixture, so a faithful copy of a wrong engine answer still
  fails here.
- **Ranks are the engine's.** Competition ranking over the whole qualifying
  population (1, 2, 2, 4), including across a page boundary.
- **Null stays null.** A stat the source did not record is JSON `null`,
  never 0, and its row is unranked and last.
- **Bad input is a 422, never a 500 and never an empty 200.** In particular
  `sport=cfb`: there are no CFB player stats, and an empty 200 would look
  exactly like an unloaded db.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, get_args

import pytest
from cfb_strength.contracts import PlayerLeaderSort, PlayerSeasonType
from cfb_strength.players import get_player_career, get_player_leaders
from fastapi.testclient import TestClient
from fixtures.player_api_fixture import (
    STAT_NAMES,
    client_for_db,
    engine_json,
    fixture_conn,
    make_player_db_with_null_stat,
)

LEADERS = "/api/players/leaders"

SORTS: tuple[PlayerLeaderSort, ...] = get_args(PlayerLeaderSort)
SEASON_TYPES: tuple[PlayerSeasonType, ...] = get_args(PlayerSeasonType)

# Measured on the regenerated fixture (NFL 1999 + 2023, #296).
REGULAR_QUALIFYING = 204
POSTSEASON_QUALIFYING = 30

TUA_TAGOVAILOA = 2186969283
KURT_WARNER = 2044124519
PATRICK_MAHOMES = 2319407936

ROW_KEYS = {
    "rank",
    "player_id",
    "display_name",
    "position",
    "first_season",
    "last_season",
    "games",
    "record",
    "stats",
}


def _expected(**kwargs: Any) -> Any:
    with fixture_conn() as conn:
        return engine_json(get_player_leaders(conn, sport="nfl", **kwargs))


def _get(client: TestClient, **params: str | int) -> Any:
    response = client.get(LEADERS, params=params)
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# shape and order
# ---------------------------------------------------------------------------


def test_default_leaders_are_regular_season_passing_yards_page_one(client: TestClient) -> None:
    body = _get(client)

    assert {k: body[k] for k in ("sport", "season_type", "sort", "limit", "offset", "total")} == {
        "sport": "nfl",
        "season_type": "regular",
        "sort": "passing_yards",
        "limit": 50,
        "offset": 0,
        "total": REGULAR_QUALIFYING,
    }
    assert set(body) == {"sport", "season_type", "sort", "limit", "offset", "total", "rows"}
    assert len(body["rows"]) == 50
    for row in body["rows"]:
        assert set(row) == ROW_KEYS
        assert set(row["record"]) == {"wins", "losses", "ties", "starts"}
        assert set(row["stats"]) == set(STAT_NAMES)

    top = [
        (r["rank"], r["display_name"], r["stats"]["passing_yards"], r["stats"]["passing_tds"])
        for r in body["rows"][:5]
    ]
    assert top == [
        (1, "Tua Tagovailoa", 4624, 29),
        (2, "Jared Goff", 4575, 30),
        (3, "Dak Prescott", 4516, 36),
        (4, "Steve Beuerlein", 4436, 36),
        (5, "Josh Allen", 4306, 29),
    ]
    first = body["rows"][0]
    assert first["player_id"] == TUA_TAGOVAILOA
    assert (first["position"], first["first_season"], first["last_season"], first["games"]) == (
        "QB",
        2023,
        2023,
        17,
    )
    assert first["record"] == {"wins": 11, "losses": 6, "ties": 0, "starts": 17}

    assert body == _expected()


# (season_type, sort) -> the literal top rows measured on the fixture.
TOP_ROWS: dict[tuple[str, str], list[tuple[int, str]]] = {
    ("regular", "passing_yards"): [(1, "Tua Tagovailoa"), (2, "Jared Goff")],
    ("regular", "passing_tds"): [(1, "Kurt Warner"), (2, "Dak Prescott")],
    ("regular", "wins"): [(1, "Kurt Warner"), (1, "Lamar Jackson")],
    ("postseason", "passing_yards"): [(1, "Kurt Warner"), (2, "Patrick Mahomes")],
    ("postseason", "passing_tds"): [(1, "Kurt Warner"), (2, "Jeff George")],
    ("postseason", "wins"): [(1, "Patrick Mahomes"), (2, "Kurt Warner")],
}


@pytest.mark.parametrize("sort", SORTS)
@pytest.mark.parametrize("season_type", SEASON_TYPES)
def test_every_sort_and_season_type_is_the_engines_board(
    client: TestClient, season_type: str, sort: str
) -> None:
    body = _get(client, season_type=season_type, sort=sort)

    assert (body["season_type"], body["sort"]) == (season_type, sort)
    assert body["total"] == (
        REGULAR_QUALIFYING if season_type == "regular" else POSTSEASON_QUALIFYING
    )
    assert [(r["rank"], r["display_name"]) for r in body["rows"][:2]] == TOP_ROWS[
        (season_type, sort)
    ]
    assert body == _expected(season_type=season_type, sort=sort)


def test_postseason_starts_are_published(client: TestClient) -> None:
    rows = _get(client, season_type="postseason", sort="wins", limit=4)["rows"]

    assert [(r["display_name"], r["record"]["starts"]) for r in rows[:3]] == [
        ("Patrick Mahomes", 4),
        ("Kurt Warner", 3),
        ("Steve McNair", 4),
    ]
    for row in rows:
        record = row["record"]
        assert record["starts"] == record["wins"] + record["losses"] + record["ties"]


# ---------------------------------------------------------------------------
# paging
# ---------------------------------------------------------------------------


def test_pages_concatenate_to_the_larger_page_with_a_constant_total(client: TestClient) -> None:
    first = _get(client, limit=10, offset=0)
    second = _get(client, limit=10, offset=10)
    both = _get(client, limit=20, offset=0)

    assert first["total"] == second["total"] == both["total"] == REGULAR_QUALIFYING
    assert (first["limit"], first["offset"], second["offset"]) == (10, 0, 10)
    assert first["rows"] + second["rows"] == both["rows"]


def test_the_last_page_is_short_and_past_the_end_is_empty(client: TestClient) -> None:
    last = _get(client, limit=10, offset=200)
    past = _get(client, limit=10, offset=REGULAR_QUALIFYING)

    assert len(last["rows"]) == REGULAR_QUALIFYING - 200
    assert past["rows"] == []
    assert past["total"] == REGULAR_QUALIFYING
    assert last == _expected(limit=10, offset=200)


def test_max_limit_is_accepted(client: TestClient) -> None:
    body = _get(client, limit=100)

    assert len(body["rows"]) == 100
    assert body == _expected(limit=100)


# ---------------------------------------------------------------------------
# ranks and nulls come from the engine, untouched
# ---------------------------------------------------------------------------


def test_rank_ties_are_passed_through(client: TestClient) -> None:
    tds = _get(client, sort="passing_tds", limit=4)["rows"]
    assert [(r["rank"], r["display_name"], r["stats"]["passing_tds"]) for r in tds] == [
        (1, "Kurt Warner", 38),
        (2, "Dak Prescott", 36),
        (2, "Steve Beuerlein", 36),
        (4, "Jordan Love", 32),
    ]

    wins = _get(client, sort="wins", limit=6)["rows"]
    assert [r["rank"] for r in wins] == [1, 1, 1, 1, 5, 5]


def test_a_tie_across_a_page_boundary_keeps_its_population_rank(client: TestClient) -> None:
    """A one-row page holding the second of two tied players still says 2:
    the rank is over the whole qualifying population, not the page."""
    second = _get(client, sort="passing_tds", limit=1, offset=1)["rows"]
    third = _get(client, sort="passing_tds", limit=1, offset=2)["rows"]

    assert [(r["rank"], r["display_name"]) for r in second + third] == [
        (2, "Dak Prescott"),
        (2, "Steve Beuerlein"),
    ]


def test_a_null_stat_stays_null_and_unranked_on_both_endpoints(tmp_path: Path) -> None:
    db = make_player_db_with_null_stat(
        tmp_path,
        player_id=TUA_TAGOVAILOA,
        season=2023,
        season_type="regular",
        stat="passing_yards",
    )

    with client_for_db(db) as nulled:
        by_yards = nulled.get(LEADERS, params={"limit": 10, "offset": 200})
        by_tds = nulled.get(LEADERS, params={"sort": "passing_tds", "limit": 100})
        career = nulled.get(f"/api/players/{TUA_TAGOVAILOA}")

    assert by_yards.status_code == by_tds.status_code == career.status_code == 200
    last = by_yards.json()["rows"][-1]
    assert last["player_id"] == TUA_TAGOVAILOA
    assert last["rank"] is None
    assert "passing_yards" in last["stats"] and last["stats"]["passing_yards"] is None
    assert last["stats"]["passing_tds"] == 29
    assert by_yards.json()["total"] == REGULAR_QUALIFYING

    tua_by_tds = next(r for r in by_tds.json()["rows"] if r["player_id"] == TUA_TAGOVAILOA)
    assert isinstance(tua_by_tds["rank"], int)
    assert tua_by_tds["stats"]["passing_yards"] is None

    line = career.json()["seasons"][0]
    assert (line["season"], line["season_type"]) == (2023, "regular")
    assert line["stats"]["passing_yards"] is None
    assert career.json()["regular_season"]["stats"]["passing_yards"] is None

    with fixture_conn(db) as conn:
        assert by_yards.json() == engine_json(
            get_player_leaders(conn, sport="nfl", limit=10, offset=200)
        )
        assert career.json() == engine_json(
            get_player_career(conn, sport="nfl", player_id=TUA_TAGOVAILOA)
        )


# ---------------------------------------------------------------------------
# the seam: a leaders row is that player's career totals
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("season_type", SEASON_TYPES)
def test_leaders_rows_equal_the_career_endpoints_totals(
    client: TestClient, season_type: str
) -> None:
    rows = _get(client, season_type=season_type, limit=10)["rows"]
    assert rows

    for row in rows:
        career = client.get(f"/api/players/{row['player_id']}")
        assert career.status_code == 200, career.text
        key = "regular_season" if season_type == "regular" else "postseason"
        totals = career.json()[key]
        assert totals is not None, row["display_name"]
        assert (totals["games"], totals["record"], totals["stats"]) == (
            row["games"],
            row["record"],
            row["stats"],
        ), row["display_name"]


# ---------------------------------------------------------------------------
# bad input: 422 at the offending field
# ---------------------------------------------------------------------------


def _assert_422_at(response_status: int, body: Any, field: str) -> None:
    assert response_status == 422, body
    detail = body.get("detail")
    assert isinstance(detail, list) and detail, body
    assert any(field in tuple(error.get("loc", ())) for error in detail), detail


@pytest.mark.parametrize(
    "params,field",
    [
        ({"limit": 0}, "limit"),
        ({"limit": 101}, "limit"),
        ({"limit": -1}, "limit"),
        ({"offset": -1}, "offset"),
        # #296 review: past SQLite's signed 64-bit INTEGER, sqlite3 raises an
        # unmapped OverflowError (a 500) unless the bound stops it here.
        ({"offset": 2**63}, "offset"),
        ({"offset": 2**64}, "offset"),
        ({"sport": "cfb"}, "sport"),
        ({"sport": "basketball"}, "sport"),
        ({"sort": "rushing_yards"}, "sort"),
        ({"season_type": "combined"}, "season_type"),
    ],
    ids=lambda v: str(v),
)
def test_invalid_query_is_a_422_at_that_field(
    client: TestClient, params: dict[str, str | int], field: str
) -> None:
    response = client.get(LEADERS, params=params)

    _assert_422_at(response.status_code, response.json(), field)


def test_largest_sqlite_offset_is_an_empty_page_not_an_error(client: TestClient) -> None:
    body = _get(client, offset=2**63 - 1)

    assert body["offset"] == 2**63 - 1
    assert body["rows"] == []


def test_cfb_is_never_an_empty_200(client: TestClient) -> None:
    response = client.get(LEADERS, params={"sport": "cfb"})

    assert response.status_code == 422
    assert "rows" not in response.json()
