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
- **Every category, every sort.** `category` ('passing' | 'rushing', #312)
  picks the board, and omitting `sort` echoes that category's default. The
  (category, sort) pairs are read from the engine's own
  `PLAYER_LEADER_SORTS_BY_CATEGORY`, never a list copied into apps/api. A
  sort from another category is a 422 at `sort` naming that category's
  sorts, never the engine's `ValueError` surfacing as a 500.
- **A board ranks a stat, not a position.** QBs appear on the rushing board
  on merit, sharing ranks with running backs.
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
from cfb_strength.contracts import (
    PLAYER_LEADER_SORTS_BY_CATEGORY,
    PlayerLeaderCategory,
    PlayerLeaderSort,
    PlayerSeasonType,
)
from cfb_strength.players import get_player_career, get_player_leaders
from fastapi.testclient import TestClient
from fixtures.player_api_fixture import (
    client_for_db,
    engine_json,
    fixture_conn,
    make_player_db_with_null_stat,
)

LEADERS = "/api/players/leaders"

SEASON_TYPES: tuple[PlayerSeasonType, ...] = get_args(PlayerSeasonType)
CATEGORIES: tuple[PlayerLeaderCategory, ...] = get_args(PlayerLeaderCategory)

# (category, sort) pairs from the engine's own map (#312). Iterating
# `get_args(PlayerLeaderSort)` instead would ask the passing board for a
# rushing sort -- which is now exactly the 422 case below, not a board.
CATEGORY_SORTS: tuple[tuple[PlayerLeaderCategory, PlayerLeaderSort], ...] = tuple(
    (category, sort)
    for category, sorts in PLAYER_LEADER_SORTS_BY_CATEGORY.items()
    for sort in sorts
)

# Measured on the committed fixture (NFL 1999 + 2023): passing #296, rushing
# #312. Qualifying is per (category, season_type), with no minimum.
REGULAR_QUALIFYING = 204
POSTSEASON_QUALIFYING = 30
REGULAR_RUSHING_QUALIFYING = 653
POSTSEASON_RUSHING_QUALIFYING = 114
QUALIFYING: dict[tuple[str, str], int] = {
    ("passing", "regular"): REGULAR_QUALIFYING,
    ("passing", "postseason"): POSTSEASON_QUALIFYING,
    ("rushing", "regular"): REGULAR_RUSHING_QUALIFYING,
    ("rushing", "postseason"): POSTSEASON_RUSHING_QUALIFYING,
}

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


# The ten stats the API publishes today, written out rather than derived.
# `contracts.PlayerStats` has carried 34 columns since #313; `PlayerStatsOut`
# still exposes only these, and widening it is #314 (receiving) and #315
# (kicking and punting). Deriving this list from the response model would
# make the assertion below tautological -- see the comment there.
PUBLISHED_STATS_TODAY: tuple[str, ...] = (
    "completions",
    "attempts",
    "passing_yards",
    "passing_tds",
    "passing_interceptions",
    "sacks_suffered",
    "sack_yards_lost",
    "carries",
    "rushing_yards",
    "rushing_tds",
)


def test_default_leaders_are_regular_season_passing_yards_page_one(client: TestClient) -> None:
    body = _get(client)

    keys = ("sport", "category", "season_type", "sort", "limit", "offset", "total")
    assert {k: body[k] for k in keys} == {
        "sport": "nfl",
        # #312: the default board is still the passing one, now said out loud.
        "category": "passing",
        "season_type": "regular",
        "sort": "passing_yards",
        "limit": 50,
        "offset": 0,
        "total": REGULAR_QUALIFYING,
    }
    assert set(body) == {*keys, "rows"}
    assert len(body["rows"]) == 50
    for row in body["rows"]:
        assert set(row) == ROW_KEYS
        assert set(row["record"]) == {"wins", "losses", "ties", "starts"}
        # Pinned literally rather than compared to `PUBLISHED_STAT_NAMES`.
        # That constant is `tuple(PlayerStatsOut.model_fields)`, and this body
        # is serialized by FastAPI from that same model, so the two move
        # together by construction and the assertion could never fail
        # (#313 review). A literal is the only version of this check that can.
        # It is meant to go red when #314/#315 widen what the API publishes.
        assert set(row["stats"]) == set(PUBLISHED_STATS_TODAY)

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


# (season_type, sort) -> the literal top rows measured on the fixture. The
# passing entries are #296's, unchanged; the rushing ones are #312's.
TOP_ROWS: dict[tuple[str, str], list[tuple[int, str]]] = {
    ("regular", "passing_yards"): [(1, "Tua Tagovailoa"), (2, "Jared Goff")],
    ("regular", "passing_tds"): [(1, "Kurt Warner"), (2, "Dak Prescott")],
    ("regular", "wins"): [(1, "Kurt Warner"), (1, "Lamar Jackson")],
    ("postseason", "passing_yards"): [(1, "Kurt Warner"), (2, "Patrick Mahomes")],
    ("postseason", "passing_tds"): [(1, "Kurt Warner"), (2, "Jeff George")],
    ("postseason", "wins"): [(1, "Patrick Mahomes"), (2, "Kurt Warner")],
    ("regular", "rushing_yards"): [(1, "Edgerrin James"), (2, "Curtis Martin")],
    ("regular", "rushing_tds"): [(1, "Raheem Mostert"), (2, "Stephen Davis")],
    ("regular", "carries"): [(1, "Edgerrin James"), (2, "Curtis Martin")],
    ("postseason", "rushing_yards"): [(1, "Eddie George"), (2, "Isiah Pacheco")],
    ("postseason", "rushing_tds"): [(1, "Christian McCaffrey"), (2, "Aaron Jones")],
    ("postseason", "carries"): [(1, "Eddie George"), (2, "Isiah Pacheco")],
}


@pytest.mark.parametrize("category,sort", CATEGORY_SORTS)
@pytest.mark.parametrize("season_type", SEASON_TYPES)
def test_every_category_sort_and_season_type_is_the_engines_board(
    client: TestClient, season_type: str, category: str, sort: str
) -> None:
    body = _get(client, category=category, season_type=season_type, sort=sort)

    assert (body["category"], body["season_type"], body["sort"]) == (category, season_type, sort)
    assert body["total"] == QUALIFYING[(category, season_type)]
    assert [(r["rank"], r["display_name"]) for r in body["rows"][:2]] == TOP_ROWS[
        (season_type, sort)
    ]
    assert body == _expected(category=category, season_type=season_type, sort=sort)


# ---------------------------------------------------------------------------
# the rushing board (#312)
# ---------------------------------------------------------------------------

# Measured on the committed fixture through `get_player_leaders`: each row's
# rank, name and the sort value itself, so a faithful copy of a wrong engine
# answer still fails here. The tied runs are listed in full.
RUSHING_TOP: dict[tuple[str, str], list[tuple[int, str, int]]] = {
    ("regular", "rushing_yards"): [
        (1, "Edgerrin James", 1553),
        (2, "Curtis Martin", 1464),
        (3, "Christian McCaffrey", 1459),
    ],
    ("regular", "rushing_tds"): [
        (1, "Raheem Mostert", 18),
        (2, "Stephen Davis", 17),
        (3, "Jalen Hurts", 15),
        (3, "Josh Allen", 15),
    ],
    ("regular", "carries"): [
        (1, "Edgerrin James", 369),
        (2, "Curtis Martin", 367),
        (3, "Emmitt Smith", 329),
    ],
    ("postseason", "rushing_yards"): [
        (1, "Eddie George", 449),
        (2, "Isiah Pacheco", 313),
        (3, "Christian McCaffrey", 268),
    ],
    ("postseason", "rushing_tds"): [
        (1, "Christian McCaffrey", 4),
        (2, "Aaron Jones", 3),
        (2, "Eddie George", 3),
        (2, "Isiah Pacheco", 3),
        (2, "Jahmyr Gibbs", 3),
        (2, "Josh Allen", 3),
        (2, "Steve McNair", 3),
    ],
    ("postseason", "carries"): [
        (1, "Eddie George", 108),
        (2, "Isiah Pacheco", 81),
        (3, "Christian McCaffrey", 59),
    ],
}


@pytest.mark.parametrize("season_type,sort", sorted(RUSHING_TOP))
def test_rushing_boards_show_the_measured_leaders(
    client: TestClient, season_type: str, sort: str
) -> None:
    expected = RUSHING_TOP[(season_type, sort)]
    body = _get(client, category="rushing", season_type=season_type, sort=sort, limit=len(expected))

    assert [(r["rank"], r["display_name"], r["stats"][sort]) for r in body["rows"]] == expected


def test_rushing_with_no_sort_echoes_the_categorys_default(client: TestClient) -> None:
    body = _get(client, category="rushing")

    assert (body["category"], body["sort"], body["season_type"]) == (
        "rushing",
        "rushing_yards",
        "regular",
    )
    assert body["total"] == REGULAR_RUSHING_QUALIFYING
    assert body == _expected(category="rushing")
    assert body == _get(client, category="rushing", sort="rushing_yards")


def test_rushing_ranks_a_stat_not_a_position_ties_included(client: TestClient) -> None:
    """Two QBs tie for third on regular-season rushing TDs. Both carry rank 3,
    the next row is 5, and neither is filtered out for playing quarterback."""
    rows = _get(client, category="rushing", sort="rushing_tds", limit=5)["rows"]

    assert [
        (r["rank"], r["display_name"], r["position"], r["stats"]["rushing_tds"]) for r in rows
    ] == [
        (1, "Raheem Mostert", "RB", 18),
        (2, "Stephen Davis", "RB", 17),
        (3, "Jalen Hurts", "QB", 15),
        (3, "Josh Allen", "QB", 15),
        (5, "Christian McCaffrey", "RB", 14),
    ]


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


@pytest.mark.parametrize("category", CATEGORIES)
@pytest.mark.parametrize("season_type", SEASON_TYPES)
def test_leaders_rows_equal_the_career_endpoints_totals(
    client: TestClient, season_type: str, category: str
) -> None:
    rows = _get(client, category=category, season_type=season_type, limit=10)["rows"]
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
        # #312: a sort belongs to exactly one category, so a sort from another
        # one is request validation, not the engine's ValueError as a 500.
        # With no `category` this is a rushing sort on the passing board.
        ({"sort": "rushing_yards"}, "sort"),
        ({"category": "rushing", "sort": "wins"}, "sort"),
        ({"category": "rushing", "sort": "passing_yards"}, "sort"),
        ({"category": "passing", "sort": "carries"}, "sort"),
        ({"category": "receiving"}, "category"),
        ({"season_type": "combined"}, "season_type"),
    ],
    ids=lambda v: str(v),
)
def test_invalid_query_is_a_422_at_that_field(
    client: TestClient, params: dict[str, str | int], field: str
) -> None:
    response = client.get(LEADERS, params=params)

    _assert_422_at(response.status_code, response.json(), field)


def _pydantic_expected(options: tuple[str, ...]) -> str:
    """How pydantic renders a `literal_error`'s `ctx.expected` -- verified
    against this endpoint's own `season_type` and `sport` errors. Only the
    rendering is spelled out here; the options themselves come from the
    engine's `PLAYER_LEADER_SORTS_BY_CATEGORY`."""
    if len(options) == 1:
        return repr(options[0])
    return ", ".join(repr(option) for option in options[:-1]) + f" or {options[-1]!r}"


CROSS_CATEGORY_SORTS: list[tuple[PlayerLeaderCategory, str]] = [
    ("rushing", "wins"),
    ("rushing", "passing_yards"),
    ("passing", "carries"),
    ("passing", "rushing_yards"),
]


@pytest.mark.parametrize("category,sort", CROSS_CATEGORY_SORTS)
def test_a_sort_from_another_category_is_a_422_naming_that_categorys_sorts(
    client: TestClient, category: PlayerLeaderCategory, sort: str
) -> None:
    """Pydantic's own `literal_error` shape, located at `sort` -- the same
    thing `sport=cfb` produces -- so a client handles it like any other bad
    value instead of meeting a 500 from the engine's ValueError."""
    response = client.get(LEADERS, params={"category": category, "sort": sort})

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert isinstance(detail, list) and len(detail) == 1, detail
    expected = _pydantic_expected(PLAYER_LEADER_SORTS_BY_CATEGORY[category])
    assert detail[0] == {
        "type": "literal_error",
        "loc": ["query", "sort"],
        "msg": f"Input should be {expected}",
        "input": sort,
        "ctx": {"expected": expected},
    }
    # The message names this category's sorts, and only those.
    assert sort not in expected


def test_largest_sqlite_offset_is_an_empty_page_not_an_error(client: TestClient) -> None:
    body = _get(client, offset=2**63 - 1)

    assert body["offset"] == 2**63 - 1
    assert body["rows"] == []


def test_cfb_is_never_an_empty_200(client: TestClient) -> None:
    response = client.get(LEADERS, params={"sport": "cfb"})

    assert response.status_code == 422
    assert "rows" not in response.json()
