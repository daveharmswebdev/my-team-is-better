"""Player coverage (issue #446, epic #443): every players route says how much
of a career the db holds, so a client can write "Emmitt Smith played
1990-2004; these are his last 1 of 15 seasons" and mark no larger number on
a cut-off total.

`coverage` is the engine's `contracts.PlayerCoverage`, published as-is: its
seven fields plus its four derived properties (`career_seasons`,
`cut_off_before`, `cut_off_after`, `cut_off`) as plain JSON keys, the way a
career publishes its derived `group`. The API recomputes nothing; every body
here is compared to the engine's own value (`engine_json`, which adds the
four properties) and to literals measured on the committed fixture.

The fixture's NFL slice is 1999 + 2023, so its data span is 1999-2023:

- Emmitt Smith (1990-2004) has one fixture season, 1999 (regular and
  postseason lines): cut off before, not after.
- Patrick Mahomes (2017-2026) runs past 2023: cut off after, not before.
- Tim Couch (1999-2003) is inside the span: neither, so `cut_off` is false.
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path
from typing import Any

from cfb_strength.players import (
    get_player_career,
    get_player_comparison,
    get_player_leaders,
    search_players,
)
from fastapi.testclient import TestClient
from fixtures.player_api_fixture import FIXTURE_DB, client_for_db, engine_json, fixture_conn

from api.main import app

EMMITT_SMITH = 2249533020
PATRICK_MAHOMES = 2319407936
TIM_COUCH = 2004541545
KURT_WARNER = 2044124519

COVERAGE_KEYS = (
    "career_first_season",
    "career_last_season",
    "data_first_season",
    "data_last_season",
    "covered_first_season",
    "covered_last_season",
    "covered_seasons",
    "career_seasons",
    "cut_off_before",
    "cut_off_after",
    "cut_off",
)

EMMITT_COVERAGE = {
    "career_first_season": 1990,
    "career_last_season": 2004,
    "data_first_season": 1999,
    "data_last_season": 2023,
    "covered_first_season": 1999,
    "covered_last_season": 1999,
    "covered_seasons": 1,
    "career_seasons": 15,
    "cut_off_before": True,
    "cut_off_after": False,
    "cut_off": True,
}
MAHOMES_COVERAGE = {
    "career_first_season": 2017,
    "career_last_season": 2026,
    "data_first_season": 1999,
    "data_last_season": 2023,
    "covered_first_season": 2023,
    "covered_last_season": 2023,
    "covered_seasons": 1,
    "career_seasons": 10,
    "cut_off_before": False,
    "cut_off_after": True,
    "cut_off": True,
}
COUCH_COVERAGE = {
    "career_first_season": 1999,
    "career_last_season": 2003,
    "data_first_season": 1999,
    "data_last_season": 2023,
    "covered_first_season": 1999,
    "covered_last_season": 1999,
    "covered_seasons": 1,
    "career_seasons": 5,
    "cut_off_before": False,
    "cut_off_after": False,
    "cut_off": False,
}


def _ok(client: TestClient, path: str, **params: str | int) -> Any:
    response = client.get(path, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _engine_career_coverage(player_id: int) -> Any:
    with fixture_conn() as conn:
        return engine_json(get_player_career(conn, sport="nfl", player_id=player_id).coverage)


# ---------------------------------------------------------------------------
# the career route
# ---------------------------------------------------------------------------


def test_emmitt_smith_is_cut_off_before_the_data(client: TestClient) -> None:
    """The founder's own example (#443): his fixture lines are his 1999
    seasons, regular and postseason, so one covered season of fifteen."""
    body = _ok(client, f"/api/players/{EMMITT_SMITH}")

    assert body["display_name"] == "Emmitt Smith"
    assert tuple(body["coverage"]) == COVERAGE_KEYS
    assert body["coverage"] == EMMITT_COVERAGE
    assert body["coverage"] == _engine_career_coverage(EMMITT_SMITH)
    assert body["coverage"]["covered_seasons"] == len({line["season"] for line in body["seasons"]})


def test_an_active_career_is_cut_off_after_the_data(client: TestClient) -> None:
    body = _ok(client, f"/api/players/{PATRICK_MAHOMES}")

    assert body["coverage"] == MAHOMES_COVERAGE
    assert body["coverage"] == _engine_career_coverage(PATRICK_MAHOMES)


def test_a_career_inside_the_data_span_is_not_cut_off(client: TestClient) -> None:
    body = _ok(client, f"/api/players/{TIM_COUCH}")

    assert body["coverage"] == COUCH_COVERAGE
    assert body["coverage"] == _engine_career_coverage(TIM_COUCH)


# ---------------------------------------------------------------------------
# the compare route: both sides
# ---------------------------------------------------------------------------


def test_compare_publishes_both_sides_coverage(client: TestClient) -> None:
    """Warner (1998-2009) is cut off before; Couch (1999-2003) is not."""
    body = _ok(client, "/api/players/compare", a=KURT_WARNER, b=TIM_COUCH)

    with fixture_conn() as conn:
        engine = get_player_comparison(conn, sport="nfl", a=KURT_WARNER, b=TIM_COUCH)
    assert body["a"]["coverage"] == engine_json(engine.a.coverage)
    assert body["b"]["coverage"] == engine_json(engine.b.coverage)
    assert (body["a"]["coverage"]["cut_off_before"], body["a"]["coverage"]["cut_off"]) == (
        True,
        True,
    )
    assert body["a"]["coverage"]["career_first_season"] == 1998
    assert body["b"]["coverage"] == COUCH_COVERAGE


# ---------------------------------------------------------------------------
# the leaders route: rows and the data span
# ---------------------------------------------------------------------------


def test_leaders_rows_carry_the_engines_coverage_and_the_board_its_span(
    client: TestClient,
) -> None:
    body = _ok(client, "/api/players/leaders", category="rushing", limit=100)

    with fixture_conn() as conn:
        engine = get_player_leaders(conn, sport="nfl", category="rushing", limit=100)
    assert (body["data_first_season"], body["data_last_season"]) == (1999, 2023)
    assert (body["data_first_season"], body["data_last_season"]) == (
        engine.data_first_season,
        engine.data_last_season,
    )
    assert [row["coverage"] for row in body["rows"]] == [
        engine_json(row.coverage) for row in engine.rows
    ]
    emmitt = next(row for row in body["rows"] if row["player_id"] == EMMITT_SMITH)
    assert emmitt["coverage"] == EMMITT_COVERAGE


def test_an_empty_board_still_carries_the_data_span(client: TestClient) -> None:
    """No fixture kicker reaches the `fg_pct` attempts minimum: no rows, but
    the board can still say "since 1999"."""
    body = _ok(client, "/api/players/leaders", category="kicking", sort="fg_pct")

    assert (body["total"], body["rows"]) == (0, [])
    assert (body["data_first_season"], body["data_last_season"]) == (1999, 2023)


def test_a_db_with_no_stat_rows_publishes_a_null_span(tmp_path: Path) -> None:
    db = tmp_path / "no_stats.sqlite3"
    shutil.copy(FIXTURE_DB, db)
    conn = sqlite3.connect(db)
    try:
        with conn:
            conn.execute("DELETE FROM player_season_stats")
    finally:
        conn.close()

    with client_for_db(db) as client:
        body = _ok(client, "/api/players/leaders")
    # The passing board still qualifies QBs on their starts alone, so it has
    # rows; with no span, no row can claim to be cut off.
    assert body["rows"]
    assert (body["data_first_season"], body["data_last_season"]) == (None, None)
    for row in body["rows"]:
        coverage = row["coverage"]
        assert (coverage["data_first_season"], coverage["data_last_season"]) == (None, None)
        assert (coverage["cut_off_before"], coverage["cut_off_after"], coverage["cut_off"]) == (
            False,
            False,
            False,
        )


# ---------------------------------------------------------------------------
# the search route
# ---------------------------------------------------------------------------


def test_search_rows_carry_the_engines_coverage(client: TestClient) -> None:
    body = _ok(client, "/api/players/search", q="emmitt")

    with fixture_conn() as conn:
        engine = search_players(conn, sport="nfl", query="emmitt")
    assert [row["coverage"] for row in body["rows"]] == [
        engine_json(row.coverage) for row in engine.rows
    ]
    emmitt = next(row for row in body["rows"] if row["player_id"] == EMMITT_SMITH)
    assert emmitt["coverage"] == EMMITT_COVERAGE
    assert (emmitt["first_season"], emmitt["last_season"]) == (1999, 1999)


def test_a_search_row_inside_the_span_is_not_cut_off(client: TestClient) -> None:
    body = _ok(client, "/api/players/search", q="tim couch")

    couch = next(row for row in body["rows"] if row["player_id"] == TIM_COUCH)
    assert couch["coverage"] == COUCH_COVERAGE


# ---------------------------------------------------------------------------
# the schema a client and the narrator read
# ---------------------------------------------------------------------------


def test_openapi_describes_every_coverage_field() -> None:
    schemas = app.openapi()["components"]["schemas"]

    coverage = schemas["PlayerCoverageOut"]
    assert tuple(coverage["properties"]) == COVERAGE_KEYS
    assert set(coverage["required"]) == set(COVERAGE_KEYS)
    for name, prop in coverage["properties"].items():
        assert prop.get("description", "").strip(), f"PlayerCoverageOut.{name} has no description"

    for model in ("PlayerCareerOut", "PlayerLeaderRowOut", "PlayerSearchRowOut"):
        prop = schemas[model]["properties"]["coverage"]
        assert "coverage" in schemas[model]["required"], model
        assert prop.get("description", "").strip(), f"{model}.coverage has no description"
    for name in ("data_first_season", "data_last_season"):
        prop = schemas["PlayerLeadersOut"]["properties"][name]
        assert name in schemas["PlayerLeadersOut"]["required"], name
        assert prop.get("description", "").strip(), f"PlayerLeadersOut.{name} has no description"
