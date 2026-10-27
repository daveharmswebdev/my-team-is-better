"""The EPA leader boards and the two EPA sums at the API (issue #347).

The engine ranks passing on `epa_per_dropback` (`passing_epa / (attempts +
sacks_suffered)`) and rushing on `epa_per_carry` (`rushing_epa / carries`),
each gated by a career minimum in that season type
(`PLAYER_LEADER_EPA_PER_DROPBACK_MIN_DROPBACKS`, 1500 / 225, and
`PLAYER_LEADER_EPA_PER_CARRY_MIN_CARRIES`, 750 / 110). Like `fg_pct`, the
ratio is not a published field: every `PlayerStatsOut` publishes the
unrounded sums `passing_epa` and `rushing_epa` and a client divides.
`receiving_epa` is never published (#484: NULL for 2003-2008, so a career
sum would cover tracked seasons only).

The committed fixture holds NFL 1999 and 2023 only, so no career reaches
either minimum there and both boards are a correct `total` 0 (pinned in
`test_players_leaders_endpoint.py`). The boards are checked non-empty here
on `make_player_db_with_scaled_volume`'s copy: every season row's
dropbacks, carries and the two EPA sums multiplied by ten, so real careers
clear the minimums with their own EPA ratios unchanged. What is pinned:

- **Faithful.** Every page equals the engine's own board, rank, total and
  order included, and the totals and top rows are literal (measured on the
  scaled copy), so a faithful copy of a wrong engine answer still fails.
- **A client can rebuild the order.** The ratio derived from each row's
  published stats sorts the rows exactly as the board does, and the
  published rank is the competition rank of that ratio.
- **The minimum is the engine's.** A player just below it is absent (and
  still on the category's other boards); a player exactly at it is present.
- **The sums are published raw.** On the real fixture, a leaders row, a
  career season line and the career totals carry `passing_epa` and
  `rushing_epa` as the engine computes them, unrounded, and `null` stays
  `null`.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from cfb_strength.contracts import (
    PLAYER_LEADER_EPA_PER_CARRY_MIN_CARRIES,
    PLAYER_LEADER_EPA_PER_DROPBACK_MIN_DROPBACKS,
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
    make_player_db_with_scaled_volume,
)

LEADERS = "/api/players/leaders"
SCALE = 10

KURT_WARNER = 2044124519
MATTHEW_STAFFORD = 2497952128
ERIK_KRAMER = 2391601189
DAMON_HUARD = 2343107346
ROBERT_HOLCOMBE = 2057107937
D_ANDRE_SWIFT = 2182765296
PATRICK_MAHOMES = 2319407936
CLYDE_EDWARDS_HELAIRE = 2220554129

# (category, sort, season_type) -> (total, top rows), measured on the
# scaled copy through `get_player_leaders`.
BOARDS: dict[
    tuple[PlayerLeaderCategory, PlayerLeaderSort, PlayerSeasonType],
    tuple[int, list[tuple[int, str]]],
] = {
    ("passing", "epa_per_dropback", "regular"): (
        89,
        [(1, "Kurt Warner"), (2, "Brock Purdy"), (3, "Peyton Manning"), (4, "Tua Tagovailoa")],
    ),
    ("passing", "epa_per_dropback", "postseason"): (
        26,
        [(1, "Matthew Stafford"), (2, "Jordan Love"), (3, "Kurt Warner"), (4, "Jeff George")],
    ),
    ("rushing", "epa_per_carry", "regular"): (
        115,
        [(1, "Josh Allen"), (2, "De'Von Achane"), (3, "Russell Wilson"), (4, "Justin Fields")],
    ),
    ("rushing", "epa_per_carry", "postseason"): (
        39,
        [(1, "Josh Allen"), (2, "Lamar Jackson"), (3, "Steve McNair"), (4, "James Stewart")],
    ),
}


def _minimum(sort: PlayerLeaderSort, season_type: PlayerSeasonType) -> int:
    if sort == "epa_per_dropback":
        return PLAYER_LEADER_EPA_PER_DROPBACK_MIN_DROPBACKS[season_type]
    return PLAYER_LEADER_EPA_PER_CARRY_MIN_CARRIES[season_type]


def _volume(sort: PlayerLeaderSort, stats: Any) -> int:
    if sort == "epa_per_dropback":
        return int(stats["attempts"]) + int(stats["sacks_suffered"])
    return int(stats["carries"])


def _client_ratio(sort: PlayerLeaderSort, stats: Any) -> float:
    """What a client computes from the published stats, as for `fg_pct`."""
    epa = stats["passing_epa"] if sort == "epa_per_dropback" else stats["rushing_epa"]
    assert isinstance(epa, float), stats
    return epa / _volume(sort, stats)


@pytest.fixture(scope="module")
def scaled_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return make_player_db_with_scaled_volume(tmp_path_factory.mktemp("epa"), factor=SCALE)


@pytest.fixture
def scaled(scaled_db: Path) -> Iterator[TestClient]:
    with client_for_db(scaled_db) as client:
        yield client


def _board(
    client: TestClient,
    category: PlayerLeaderCategory,
    sort: PlayerLeaderSort | None,
    season_type: PlayerSeasonType,
) -> list[Any]:
    """Every page of one board, each checked against the engine's page."""
    rows: list[Any] = []
    offset = 0
    total: int | None = None
    while total is None or offset < total:
        params: dict[str, str | int] = {
            "category": category,
            "season_type": season_type,
            "limit": 100,
            "offset": offset,
        }
        if sort is not None:
            params["sort"] = sort
        response = client.get(LEADERS, params=params)
        assert response.status_code == 200, response.text
        body = response.json()
        total = body["total"]
        rows += body["rows"]
        offset += 100
    return rows


@pytest.mark.parametrize("category,sort,season_type", sorted(BOARDS))
def test_an_epa_board_is_the_engines_and_a_client_can_rebuild_its_order(
    scaled: TestClient,
    scaled_db: Path,
    category: PlayerLeaderCategory,
    sort: PlayerLeaderSort,
    season_type: PlayerSeasonType,
) -> None:
    total, top = BOARDS[(category, sort, season_type)]

    first = scaled.get(
        LEADERS, params={"category": category, "sort": sort, "season_type": season_type}
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert (body["category"], body["sort"], body["season_type"], body["total"]) == (
        category,
        sort,
        season_type,
        total,
    )
    assert [(r["rank"], r["display_name"]) for r in body["rows"][: len(top)]] == top
    with fixture_conn(scaled_db) as conn:
        assert body == engine_json(
            get_player_leaders(
                conn, sport="nfl", category=category, sort=sort, season_type=season_type
            )
        )
        for offset in range(0, total, 100):
            page = scaled.get(
                LEADERS,
                params={
                    "category": category,
                    "sort": sort,
                    "season_type": season_type,
                    "limit": 100,
                    "offset": offset,
                },
            ).json()
            assert page == engine_json(
                get_player_leaders(
                    conn,
                    sport="nfl",
                    category=category,
                    sort=sort,
                    season_type=season_type,
                    limit=100,
                    offset=offset,
                )
            )

    rows = _board(scaled, category, sort, season_type)
    assert len(rows) == total
    for row in rows:
        assert _volume(sort, row["stats"]) >= _minimum(sort, season_type)
        assert "receiving_epa" not in row["stats"]
    ratios = [_client_ratio(sort, row["stats"]) for row in rows]
    assert ratios == sorted(ratios, reverse=True)
    assert [row["rank"] for row in rows] == [
        1 + sum(other > ratio for other in ratios) for ratio in ratios
    ]


@pytest.mark.parametrize(
    "category,sort,season_type,below,below_volume,at",
    [
        ("passing", "epa_per_dropback", "regular", ERIK_KRAMER, 1480, None),
        ("passing", "epa_per_dropback", "postseason", DAMON_HUARD, 190, None),
        ("rushing", "epa_per_carry", "regular", ROBERT_HOLCOMBE, 740, PATRICK_MAHOMES),
        ("rushing", "epa_per_carry", "postseason", D_ANDRE_SWIFT, 100, CLYDE_EDWARDS_HELAIRE),
    ],
)
def test_the_minimum_is_the_engines_below_absent_at_present(
    scaled: TestClient,
    category: PlayerLeaderCategory,
    sort: PlayerLeaderSort,
    season_type: PlayerSeasonType,
    below: int,
    below_volume: int,
    at: int | None,
) -> None:
    """Measured on the scaled copy: Erik Kramer has 1480 regular dropbacks,
    Damon Huard 190 postseason, Robert Holcombe 740 regular carries and
    D'Andre Swift 100 postseason, each the busiest player under the minimum
    (no qualifying player sits between them and it); Patrick
    Mahomes has exactly 750 regular carries and Clyde Edwards-Helaire
    exactly 110 postseason. The one under is off the EPA board, and out of
    its total, but still on the category's default board."""
    minimum = _minimum(sort, season_type)
    everyone = {r["player_id"]: r for r in _board(scaled, category, None, season_type)}
    epa_board = {r["player_id"] for r in _board(scaled, category, sort, season_type)}

    assert _volume(sort, everyone[below]["stats"]) == below_volume < minimum
    assert (
        max(v for r in everyone.values() if (v := _volume(sort, r["stats"])) < minimum)
        == below_volume
    )
    assert below not in epa_board
    if at is not None:
        assert _volume(sort, everyone[at]["stats"]) == minimum
        assert at in epa_board


def test_a_null_epa_sum_reaches_json_as_null(scaled: TestClient) -> None:
    """Matthew Stafford leads the scaled postseason passing EPA board with
    no postseason carry, so his `rushing_epa` is JSON `null`, never 0."""
    response = scaled.get(
        LEADERS,
        params={
            "category": "passing",
            "sort": "epa_per_dropback",
            "season_type": "postseason",
            "limit": 1,
        },
    )
    assert response.status_code == 200, response.text
    assert '"rushing_epa":null' in response.text
    (row,) = response.json()["rows"]
    assert row["player_id"] == MATTHEW_STAFFORD
    assert (row["stats"]["carries"], row["stats"]["rushing_epa"]) == (0, None)
    assert isinstance(row["stats"]["passing_epa"], float)


# ---------------------------------------------------------------------------
# the sums on the real fixture: leaders row, career season line and totals
# ---------------------------------------------------------------------------


def test_the_epa_sums_are_published_unrounded_everywhere(client: TestClient) -> None:
    """Kurt Warner's 1999 regular season carries the stored, unrounded
    `passing_epa` 163.010521898648 (pinned at the db by
    `test_players_widened_stats.py`); his career totals and his row on the
    passing board carry the engine's career sums, both EPA keys present."""
    career = client.get(f"/api/players/{KURT_WARNER}")
    assert career.status_code == 200, career.text
    body = career.json()
    (line,) = (
        line["stats"]
        for line in body["seasons"]
        if line["season"] == 1999 and line["season_type"] == "regular"
    )
    assert line["passing_epa"] == pytest.approx(163.010521898648, abs=1e-9)
    assert isinstance(line["rushing_epa"], float)

    with fixture_conn() as conn:
        engine = get_player_career(conn, sport="nfl", player_id=KURT_WARNER)
        board = get_player_leaders(conn, sport="nfl", category="passing", sort="passing_tds")
    assert engine.regular_season is not None and engine.postseason is not None
    totals = body["regular_season"]["stats"]
    assert (totals["passing_epa"], totals["rushing_epa"]) == (
        engine.regular_season.stats.passing_epa,
        engine.regular_season.stats.rushing_epa,
    )
    assert body["postseason"]["stats"]["passing_epa"] == engine.postseason.stats.passing_epa
    assert totals["passing_epa"] is not None and totals["rushing_epa"] is not None

    leaders = client.get(LEADERS, params={"category": "passing", "sort": "passing_tds"})
    assert leaders.status_code == 200, leaders.text
    (warner,) = (r for r in leaders.json()["rows"] if r["player_id"] == KURT_WARNER)
    (engine_warner,) = (r for r in board.rows if r.player_id == KURT_WARNER)
    assert (warner["stats"]["passing_epa"], warner["stats"]["rushing_epa"]) == (
        engine_warner.stats.passing_epa,
        engine_warner.stats.rushing_epa,
    )
    assert warner["stats"]["passing_epa"] == totals["passing_epa"]
    for stats in (line, totals, warner["stats"]):
        assert "receiving_epa" not in stats
