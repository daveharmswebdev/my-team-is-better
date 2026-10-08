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
- **Every category, every sort.** `category` ('passing' | 'rushing' |
  'receiving', #312, #314) picks the board, and omitting `sort` echoes that category's default. The
  (category, sort) pairs are read from the engine's own
  `PLAYER_LEADER_SORTS_BY_CATEGORY`, never a list copied into apps/api. A
  sort from another category is a 422 at `sort` naming that category's
  sorts, never the engine's `ValueError` surfacing as a 500.
- **A board ranks a stat, not a position.** QBs appear on the rushing board
  on merit, sharing ranks with running backs; a tight end leads the
  postseason receiving board.
- **Qualifying is the engine's.** The receiving board takes anyone with a
  target *or* a reception (#345), so a targeted player with no catch is on
  it, ranked, with `receptions` 0 -- apps/api filters nothing out.
- **The published stat keys are a literal.** Sixteen names, in order, so
  dropping or adding a `PlayerStatsOut` field goes red.
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
# #312, receiving #314. Qualifying is per (category, season_type), with no
# minimum.
REGULAR_QUALIFYING = 204
POSTSEASON_QUALIFYING = 30
REGULAR_RUSHING_QUALIFYING = 653
POSTSEASON_RUSHING_QUALIFYING = 114
REGULAR_RECEIVING_QUALIFYING = 926
POSTSEASON_RECEIVING_QUALIFYING = 224
QUALIFYING: dict[tuple[str, str], int] = {
    ("passing", "regular"): REGULAR_QUALIFYING,
    ("passing", "postseason"): POSTSEASON_QUALIFYING,
    ("rushing", "regular"): REGULAR_RUSHING_QUALIFYING,
    ("rushing", "postseason"): POSTSEASON_RUSHING_QUALIFYING,
    ("receiving", "regular"): REGULAR_RECEIVING_QUALIFYING,
    ("receiving", "postseason"): POSTSEASON_RECEIVING_QUALIFYING,
}

TUA_TAGOVAILOA = 2186969283
KURT_WARNER = 2044124519
PATRICK_MAHOMES = 2319407936
TRAVIS_HOMER = 2053081896
MARVIN_HARRISON = 2009851825

RECEIVING_STATS = (
    "receptions",
    "targets",
    "receiving_yards",
    "receiving_tds",
    "receiving_first_downs",
    "receiving_fumbles_lost",
)

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


def _get_career(client: TestClient, player_id: int) -> Any:
    response = client.get(f"/api/players/{player_id}")
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# shape and order
# ---------------------------------------------------------------------------


# The sixteen stats the API publishes, written out rather than derived: the
# original ten plus #314's six receiving stats, in `PlayerStatsOut`'s order.
# `contracts.PlayerStats` has carried 34 columns since #313; kicking and
# punting are #315. Deriving this list from the response model would make
# every assertion on it tautological -- see `test_published_stat_keys_are_pinned`.
PUBLISHED_STATS: tuple[str, ...] = (
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
    "receptions",
    "targets",
    "receiving_yards",
    "receiving_tds",
    "receiving_first_downs",
    "receiving_fumbles_lost",
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
        # Pinned literally (and in order), never compared to
        # `PUBLISHED_STAT_NAMES`: see `test_published_stat_keys_are_pinned`.
        assert list(row["stats"]) == list(PUBLISHED_STATS)

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
# passing entries are #296's, unchanged; the rushing ones are #312's; the
# receiving ones are #314's.
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
    ("regular", "receiving_yards"): [(1, "Tyreek Hill"), (2, "CeeDee Lamb")],
    ("regular", "receiving_tds"): [(1, "Cris Carter"), (1, "Mike Evans")],
    ("regular", "receptions"): [(1, "CeeDee Lamb"), (2, "Amon-Ra St. Brown")],
    ("postseason", "receiving_yards"): [(1, "Travis Kelce"), (2, "Isaac Bruce")],
    ("postseason", "receiving_tds"): [(1, "Jake Ferguson"), (1, "Randy Moss")],
    ("postseason", "receptions"): [(1, "Travis Kelce"), (2, "Rashee Rice")],
}


def test_published_stat_keys_are_pinned(client: TestClient) -> None:
    """Every stats object a player endpoint serves has exactly these sixteen
    keys, in this order: on a leaders row of every board, and on a career
    season line and its totals.

    The expectation is the literal `PUBLISHED_STATS`, never
    `PUBLISHED_STAT_NAMES`: that constant is `tuple(PlayerStatsOut.model_fields)`
    and these bodies are serialized from that same model, so the two move
    together by construction and a comparison between them could never fail
    (#313 and #338 reviews). Dropping or adding a field must go red here.
    """
    assert len(PUBLISHED_STATS) == len(set(PUBLISHED_STATS)) == 16
    stats_objects: list[Any] = []
    for category in CATEGORIES:
        stats_objects += [r["stats"] for r in _get(client, category=category, limit=3)["rows"]]
    career = _get_career(client, KURT_WARNER)
    stats_objects += [line["stats"] for line in career["seasons"]]
    stats_objects += [career["regular_season"]["stats"], career["postseason"]["stats"]]

    assert len(stats_objects) == 3 * len(CATEGORIES) + 4
    for stats in stats_objects:
        assert list(stats) == list(PUBLISHED_STATS)


@pytest.mark.parametrize("category,sort", CATEGORY_SORTS)
@pytest.mark.parametrize("season_type", SEASON_TYPES)
def test_every_category_sort_and_season_type_is_the_engines_board(
    client: TestClient,
    season_type: PlayerSeasonType,
    category: PlayerLeaderCategory,
    sort: PlayerLeaderSort,
) -> None:
    body = _get(client, category=category, season_type=season_type, sort=sort)

    assert (body["category"], body["season_type"], body["sort"]) == (category, season_type, sort)
    assert body["total"] == QUALIFYING[(category, season_type)]
    assert [(r["rank"], r["display_name"]) for r in body["rows"][:2]] == TOP_ROWS[
        (season_type, sort)
    ]
    assert body == _expected(category=category, season_type=season_type, sort=sort)

    # `_expected` projects the engine's stats onto what `PlayerStatsOut`
    # publishes, so on its own it would follow a dropped field silently.
    # Every literal published stat must also equal the engine's, row by row.
    with fixture_conn() as conn:
        engine = get_player_leaders(
            conn, sport="nfl", category=category, season_type=season_type, sort=sort
        )
    assert len(engine.rows) == len(body["rows"])
    for row, engine_row in zip(body["rows"], engine.rows, strict=True):
        assert row["stats"] == {name: getattr(engine_row.stats, name) for name in PUBLISHED_STATS}


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


# ---------------------------------------------------------------------------
# the receiving board (#314)
# ---------------------------------------------------------------------------

# Measured on the committed fixture through `get_player_leaders`: rank, name,
# position and the sort value, tied runs in full. Ranked by stat, not
# position: tight ends lead the postseason boards.
RECEIVING_TOP: dict[tuple[str, str], list[tuple[int, str, str, int]]] = {
    ("regular", "receiving_yards"): [
        (1, "Tyreek Hill", "WR", 1799),
        (2, "CeeDee Lamb", "WR", 1749),
        (3, "Marvin Harrison", "WR", 1663),
    ],
    ("regular", "receiving_tds"): [
        (1, "Cris Carter", "WR", 13),
        (1, "Mike Evans", "WR", 13),
        (1, "Tyreek Hill", "WR", 13),
        (4, "CeeDee Lamb", "WR", 12),
    ],
    ("regular", "receptions"): [
        (1, "CeeDee Lamb", "WR", 135),
        (2, "Amon-Ra St. Brown", "WR", 119),
        (2, "Tyreek Hill", "WR", 119),
        (4, "Jimmy Smith", "WR", 116),
    ],
    ("postseason", "receiving_yards"): [
        (1, "Travis Kelce", "TE", 355),
        (2, "Isaac Bruce", "WR", 317),
        (3, "Randy Moss", "WR", 315),
    ],
    ("postseason", "receiving_tds"): [
        (1, "Jake Ferguson", "TE", 3),
        (1, "Randy Moss", "WR", 3),
        (1, "Travis Kelce", "TE", 3),
        (4, "Cris Carter", "WR", 2),
    ],
    ("postseason", "receptions"): [
        (1, "Travis Kelce", "TE", 32),
        (2, "Rashee Rice", "WR", 26),
        (3, "Amon-Ra St. Brown", "WR", 22),
    ],
}


@pytest.mark.parametrize("season_type,sort", sorted(RECEIVING_TOP))
def test_receiving_boards_show_the_measured_leaders(
    client: TestClient, season_type: str, sort: str
) -> None:
    expected = RECEIVING_TOP[(season_type, sort)]
    body = _get(
        client, category="receiving", season_type=season_type, sort=sort, limit=len(expected)
    )

    assert body["total"] == QUALIFYING[("receiving", season_type)]
    assert [
        (r["rank"], r["display_name"], r["position"], r["stats"][sort]) for r in body["rows"]
    ] == expected


def test_receiving_with_no_sort_echoes_the_categorys_default(client: TestClient) -> None:
    body = _get(client, category="receiving")

    assert (body["category"], body["sort"], body["season_type"]) == (
        "receiving",
        "receiving_yards",
        "regular",
    )
    assert body["total"] == REGULAR_RECEIVING_QUALIFYING
    assert body == _expected(category="receiving")
    assert body == _get(client, category="receiving", sort="receiving_yards")


def test_a_receiving_row_publishes_the_whole_receiving_line(client: TestClient) -> None:
    """Marvin Harrison's 1999 (193 targets, 115 catches, 1663 yards, 12 TD),
    third on the regular-season yards board, with every receiving stat."""
    third = _get(client, category="receiving", limit=1, offset=2)["rows"][0]

    assert (third["rank"], third["player_id"], third["display_name"]) == (
        3,
        MARVIN_HARRISON,
        "Marvin Harrison",
    )
    assert {name: third["stats"][name] for name in RECEIVING_STATS} == {
        "receptions": 115,
        "targets": 193,
        "receiving_yards": 1663,
        "receiving_tds": 12,
        "receiving_first_downs": 79,
        "receiving_fumbles_lost": 1,
    }


def test_a_targeted_player_with_no_catch_is_ranked_with_zero_receptions(
    client: TestClient,
) -> None:
    """Qualifying is `targets > 0 OR receptions > 0`, the engine's rule
    (#345): Travis Homer's 2023 (1 target, 0 catches) is on the board, sharing
    last place on receptions, with `receptions` 0 -- not null, not unranked,
    not filtered out."""
    body = _get(client, category="receiving", sort="receptions", limit=100, offset=880)
    homer = [r for r in body["rows"] if r["player_id"] == TRAVIS_HOMER]

    assert len(homer) == 1
    row = homer[0]
    assert (row["display_name"], row["position"]) == ("Travis Homer", "RB")
    assert (row["stats"]["receptions"], row["stats"]["targets"]) == (0, 1)
    assert row["rank"] == 885
    assert body["rows"][-1]["rank"] == 885
    assert body == _expected(category="receiving", sort="receptions", limit=100, offset=880)


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


def test_a_null_receiving_stat_stays_null_and_unranked(tmp_path: Path) -> None:
    """No fixture season row has a NULL receiving stat, so the copy NULLs
    Marvin Harrison's 1999 receiving yards: he drops from third to the end
    of the yards board, unranked, `null` and never 0; ranked as usual on
    receptions; and his career line says `null` too."""
    db = make_player_db_with_null_stat(
        tmp_path,
        player_id=MARVIN_HARRISON,
        season=1999,
        season_type="regular",
        stat="receiving_yards",
    )
    last_offset = REGULAR_RECEIVING_QUALIFYING - 1

    with client_for_db(db) as nulled:
        by_yards = nulled.get(
            LEADERS, params={"category": "receiving", "limit": 1, "offset": last_offset}
        )
        by_catches = nulled.get(
            LEADERS, params={"category": "receiving", "sort": "receptions", "limit": 5}
        )
        career = nulled.get(f"/api/players/{MARVIN_HARRISON}")

    assert by_yards.status_code == by_catches.status_code == career.status_code == 200
    last = by_yards.json()["rows"][0]
    assert (last["player_id"], last["rank"]) == (MARVIN_HARRISON, None)
    assert "receiving_yards" in last["stats"] and last["stats"]["receiving_yards"] is None
    assert last["stats"]["receptions"] == 115

    harrison = [r for r in by_catches.json()["rows"] if r["player_id"] == MARVIN_HARRISON]
    assert [(r["rank"], r["stats"]["receiving_yards"]) for r in harrison] == [(5, None)]

    assert career.json()["regular_season"]["stats"]["receiving_yards"] is None

    with fixture_conn(db) as conn:
        assert by_yards.json() == engine_json(
            get_player_leaders(conn, sport="nfl", category="receiving", limit=1, offset=last_offset)
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
        # #314: receiving is a board now, and its sorts are its own.
        ({"category": "receiving", "sort": "carries"}, "sort"),
        ({"category": "receiving", "sort": "passing_yards"}, "sort"),
        ({"category": "rushing", "sort": "receptions"}, "sort"),
        ({"category": "passing", "sort": "receiving_yards"}, "sort"),
        # `targets` qualifies a receiver but is deliberately not a sort.
        ({"category": "receiving", "sort": "targets"}, "sort"),
        ({"category": "kicking"}, "category"),
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
    ("receiving", "carries"),
    ("receiving", "wins"),
    ("rushing", "receptions"),
    ("passing", "receiving_tds"),
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
