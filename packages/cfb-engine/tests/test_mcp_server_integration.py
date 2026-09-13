"""Integration coverage for `cfb_strength.mcp_server.server`: call the MCP
tool functions directly (the `@mcp.tool()` decorator returns the original
function unchanged, so they're plain callables in-process -- verified
against this project's `mcp` dependency version before relying on it here)
end-to-end against a real fixture database, confirming each returns a
`dict` with no raised exception for both a valid and an invalid input.

`mcp_server.server` opens its own read-only connection via a module-level
`DB_PATH` constant read at call time inside `_get_conn()`; tests here
monkeypatch that module attribute to point at a writable copy of the
regression fixture (ratings computed fresh via the real pipeline first,
since the server never writes and requires ratings to already exist).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from cfb_strength.db.connection import get_conn
from cfb_strength.ratings.compute_ratings import compute_and_store


@pytest.fixture
def mcp_fixture_db(regression_db: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Compute 2005 ratings for real on the fixture, then point
    mcp_server.server's DB_PATH at it so every tool function under test
    reads real, freshly-computed data through a read-only connection (as
    production does)."""
    conn: sqlite3.Connection = get_conn(regression_db)
    compute_and_store(conn, 2005, "keener")
    conn.close()

    import cfb_strength.mcp_server.server as server_module

    monkeypatch.setattr(server_module, "DB_PATH", regression_db)
    return regression_db


def test_list_seasons_returns_dict_with_computed_year(mcp_fixture_db: Path) -> None:
    from cfb_strength.mcp_server.server import list_seasons

    result = list_seasons()
    assert isinstance(result, dict)
    assert "error" not in result
    assert {"sport": "cfb", "year": 2005, "methods": ["keener"]} in result["seasons"]


def test_get_rankings_valid_year_returns_dict_with_texas_first(mcp_fixture_db: Path) -> None:
    from cfb_strength.mcp_server.server import get_rankings

    result = get_rankings(year=2005, top_n=5)
    assert isinstance(result, dict)
    assert "error" not in result
    assert result["rankings"][0]["team_name"] == "Texas"
    assert result["rankings"][0]["rank"] == 1


def test_get_rankings_unknown_year_returns_error_dict_not_exception(mcp_fixture_db: Path) -> None:
    from cfb_strength.mcp_server.server import get_rankings

    result = get_rankings(year=1999, top_n=5)
    assert isinstance(result, dict)
    assert result["error"] == "unknown_year"
    assert result["year"] == 1999
    assert result["available_years"] == [2005]


def test_get_champion_2005_cites_usc_rose_bowl_win_unprompted(mcp_fixture_db: Path) -> None:
    """The sufficiency rubric's explicit end-to-end check: asking the MCP
    server "who was the greatest team in 2005?" (get_champion) must cite the
    USC win as evidence, unprompted -- i.e. it must show up in the returned
    quality_wins without the caller having asked about USC specifically."""
    from cfb_strength.mcp_server.server import get_champion

    result = get_champion(year=2005)
    assert isinstance(result, dict)
    assert "error" not in result
    assert result["team_name"] == "Texas"
    assert result["rank"] == 1

    quality_wins = result["quality_wins"]
    usc_citations = [w for w in quality_wins if w["opponent_name"] == "USC"]
    assert len(usc_citations) == 1
    assert usc_citations[0]["team_score"] == 41
    assert usc_citations[0]["opponent_score"] == 38


def test_get_champion_invalid_year_returns_error_dict_not_exception(mcp_fixture_db: Path) -> None:
    from cfb_strength.mcp_server.server import get_champion

    result = get_champion(year=1776)
    assert isinstance(result, dict)
    assert result["error"] == "unknown_year"


def test_get_team_season_valid_team_returns_dict(mcp_fixture_db: Path) -> None:
    from cfb_strength.mcp_server.server import get_team_season

    result = get_team_season(year=2005, team="Texas")
    assert isinstance(result, dict)
    assert "error" not in result
    assert result["team_name"] == "Texas"
    assert result["wins"] == 13
    assert result["losses"] == 0


def test_get_team_season_ambiguous_team_returns_error_dict_not_exception(
    mcp_fixture_db: Path,
) -> None:
    from cfb_strength.mcp_server.server import get_team_season

    result = get_team_season(year=2005, team="State")
    assert isinstance(result, dict)
    assert result["error"] == "ambiguous_team"
    assert result["query"] == "State"
    assert len(result["candidates"]) > 1


def test_get_team_season_unknown_team_returns_unknown_team_not_ambiguous(
    mcp_fixture_db: Path,
) -> None:
    """Issue #100: a query matching *zero* rated teams used to come back as
    `ambiguous_team` with an empty candidate list, which told the calling
    LLM "did you mean one of these" and then offered none. Claude is the
    second consumer of this dead end, after the browser."""
    from cfb_strength.mcp_server.server import get_team_season

    result = get_team_season(year=2005, team="Abilene Christian")
    assert isinstance(result, dict)
    assert result["error"] == "unknown_team"
    assert result["query"] == "Abilene Christian"
    assert result["year"] == 2005
    assert "candidates" not in result


def test_compare_teams_unknown_team_returns_unknown_team(mcp_fixture_db: Path) -> None:
    """The mapping is per-tool, not app-wide as it is in apps/api, so each
    tool needs its own coverage or one can silently regress alone."""
    from cfb_strength.mcp_server.server import compare_teams

    result = compare_teams(year=2005, team_a="Texas", team_b="Abilene Christian")
    assert isinstance(result, dict)
    assert result["error"] == "unknown_team"
    assert result["query"] == "Abilene Christian"


def test_unknown_team_and_ambiguous_team_stay_distinct(mcp_fixture_db: Path) -> None:
    """The whole point of #100: the two errors must not collapse back into
    one. "State" matches many rated teams, "Abilene Christian" matches none,
    and they must report differently -- with `ambiguous_team` never carrying
    an empty candidate list."""
    from cfb_strength.mcp_server.server import get_team_season

    ambiguous = get_team_season(year=2005, team="State")
    unknown = get_team_season(year=2005, team="Abilene Christian")

    assert ambiguous["error"] == "ambiguous_team"
    assert len(ambiguous["candidates"]) > 1
    assert unknown["error"] == "unknown_team"
    assert ambiguous["error"] != unknown["error"]


def test_compare_teams_valid_pair_returns_dict_citing_head_to_head(mcp_fixture_db: Path) -> None:
    from cfb_strength.mcp_server.server import compare_teams

    result = compare_teams(year=2005, team_a="Texas", team_b="USC")
    assert isinstance(result, dict)
    assert "error" not in result
    assert result["head_to_head"]["played"] is True
    assert result["head_to_head"]["meetings"][0]["winner"] == "Texas"


def test_compare_teams_same_team_returns_error_dict_not_exception(mcp_fixture_db: Path) -> None:
    from cfb_strength.mcp_server.server import compare_teams

    result = compare_teams(year=2005, team_a="Texas", team_b="Texas")
    assert isinstance(result, dict)
    assert result["error"] == "same_team_comparison"
    assert result["team"] == "Texas"


# ---------------------------------------------------------------------------
# Issue #86: sport support. Everything below runs against ONE db holding both
# leagues for the SAME year (2013 is in both committed fixtures), which is
# what production looks like and what exposes unscoped queries: `ratings`'
# UNIQUE(year, method, team_id) deliberately excludes `sport`, so a query
# scoped only by year/method silently blends CFB and NFL rows.
# ---------------------------------------------------------------------------

BOTH_LEAGUES_YEAR = 2013


@pytest.fixture
def both_leagues_db(
    regression_db: Path, nfl_regression_db: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """The CFB regression fixture with the NFL fixture's teams/team_season/
    games merged in, then real 2013 ratings computed for both sports.

    Team ids can't collide: CFBD's native ids top out near 1e6, nflverse's
    minted surrogates start above 1e9 (see ingest/nflverse/).

    NFL ratings are computed FIRST on purpose. The unscoped
    `WHERE year = ? AND method = ? AND rank = 1` lookup in get_champion walks
    idx_ratings_year_method in rowid order, so with NFL rows inserted first
    it deterministically picks the NFL #1 for a CFB caller. Computing CFB
    first would make that bug pass by insertion-order luck.
    """
    from cfb_strength.db.connection import ensure_schema

    conn: sqlite3.Connection = get_conn(regression_db)
    try:
        # The committed CFB fixture predates #51's `sport` columns.
        ensure_schema(conn)
        conn.execute("ATTACH DATABASE ? AS nfl", (str(nfl_regression_db),))
        conn.execute(
            "INSERT INTO teams (id, school, classification, sport, source_id) "
            "SELECT id, school, classification, sport, source_id FROM nfl.teams"
        )
        conn.execute(
            "INSERT INTO team_season (team_id, year, conference, classification, sport) "
            "SELECT team_id, year, conference, classification, sport FROM nfl.team_season"
        )
        game_cols = (
            "id, season, week, season_type, start_date, neutral_site, completed, "
            "home_team_id, away_team_id, home_team, away_team, home_points, away_points, "
            "home_conference, away_conference, venue, raw_json, sport, source_id"
        )
        conn.execute(f"INSERT INTO games ({game_cols}) SELECT {game_cols} FROM nfl.games")
        conn.commit()
        conn.execute("DETACH DATABASE nfl")

        assert compute_and_store(conn, BOTH_LEAGUES_YEAR, "keener", sport="nfl") > 0
        assert compute_and_store(conn, BOTH_LEAGUES_YEAR, "keener", sport="cfb") > 0
    finally:
        conn.close()

    import cfb_strength.mcp_server.server as server_module

    monkeypatch.setattr(server_module, "DB_PATH", regression_db)
    return regression_db


def _nfl_schools(db: Path) -> set[str]:
    conn = get_conn(db, read_only=True)
    try:
        rows = conn.execute("SELECT school FROM teams WHERE sport = 'nfl'").fetchall()
    finally:
        conn.close()
    return {str(r["school"]) for r in rows}


# --- red proofs: wrong answers on the default (cfb) path, no new kwargs ------


def test_get_rankings_default_sport_excludes_nfl_teams_in_shared_year(
    both_leagues_db: Path,
) -> None:
    from cfb_strength.mcp_server.server import get_rankings

    result = get_rankings(year=BOTH_LEAGUES_YEAR, top_n=10)
    assert "error" not in result

    ranks = [r["rank"] for r in result["rankings"]]
    assert ranks == list(range(1, 11)), f"duplicate/out-of-order ranks: {ranks}"

    bleed = {r["team_name"] for r in result["rankings"]} & _nfl_schools(both_leagues_db)
    assert bleed == set(), f"NFL teams in a CFB leaderboard: {sorted(bleed)}"
    assert result["rankings"][0]["team_name"] == "Florida State"


def test_list_seasons_reports_shared_year_separately_per_sport(both_leagues_db: Path) -> None:
    from cfb_strength.mcp_server.server import list_seasons

    result = list_seasons()
    assert "error" not in result

    shared = [s for s in result["seasons"] if s["year"] == BOTH_LEAGUES_YEAR]
    assert len(shared) == 2, f"expected one entry per sport for {BOTH_LEAGUES_YEAR}: {shared}"
    assert {"sport": "cfb", "year": BOTH_LEAGUES_YEAR, "methods": ["keener"]} in shared
    assert {"sport": "nfl", "year": BOTH_LEAGUES_YEAR, "methods": ["keener"]} in shared


def test_get_champion_default_sport_returns_cfb_number_one_in_shared_year(
    both_leagues_db: Path,
) -> None:
    from cfb_strength.mcp_server.server import get_champion

    result = get_champion(year=BOTH_LEAGUES_YEAR)
    assert result.get("team_name") == "Florida State", f"got {result}"
    assert result["rank"] == 1


# --- per-tool NFL coverage (sport="nfl") -------------------------------------


def test_get_champion_nfl_returns_nfl_number_one_in_shared_year(both_leagues_db: Path) -> None:
    from cfb_strength.mcp_server.server import get_champion

    result = get_champion(year=BOTH_LEAGUES_YEAR, sport="nfl")
    assert result.get("team_name") == "Seattle Seahawks", f"got {result}"
    assert result["rank"] == 1


def test_get_rankings_nfl_returns_only_nfl_teams(both_leagues_db: Path) -> None:
    from cfb_strength.mcp_server.server import get_rankings

    result = get_rankings(year=BOTH_LEAGUES_YEAR, top_n=40, sport="nfl")
    assert "error" not in result
    assert result["sport"] == "nfl"
    names = [r["team_name"] for r in result["rankings"]]
    assert set(names) <= _nfl_schools(both_leagues_db)
    assert len(names) == 32
    assert [r["rank"] for r in result["rankings"]] == list(range(1, 33))
    assert names[0] == "Seattle Seahawks"


def test_get_rankings_nfl_reports_ties_matching_get_team_season(both_leagues_db: Path) -> None:
    """Issue #83: the 2013 Packers-Vikings 26-26 tie. get_team_season (a
    dataclasses.asdict of TeamCase) already carries `ties`, but get_rankings
    hand-builds its entries and used to drop it, so the same Packers read
    8-8 on the leaderboard and 8-8-1 on their own resume. `.get("ties")` so
    the unfixed server fails on the value, not a KeyError."""
    from cfb_strength.mcp_server.server import get_rankings, get_team_season

    result = get_rankings(year=BOTH_LEAGUES_YEAR, top_n=32, sport="nfl")
    assert "error" not in result, result
    by_name = {r["team_name"]: r for r in result["rankings"]}

    def record(name: str) -> tuple[object, object, object]:
        entry = by_name[name]
        return (entry["wins"], entry["losses"], entry.get("ties"))

    assert record("Green Bay Packers") == (8, 8, 1)
    assert record("Minnesota Vikings") == (5, 10, 1)

    for entry in result["rankings"]:
        case = get_team_season(year=BOTH_LEAGUES_YEAR, team=entry["team_name"], sport="nfl")
        assert "error" not in case, case
        assert (entry["wins"], entry["losses"], entry.get("ties")) == (
            case["wins"],
            case["losses"],
            case["ties"],
        ), entry["team_name"]


def test_get_team_season_nfl_returns_nfl_case(both_leagues_db: Path) -> None:
    from cfb_strength.mcp_server.server import get_team_season

    result = get_team_season(year=BOTH_LEAGUES_YEAR, team="Seattle Seahawks", sport="nfl")
    assert "error" not in result, result
    assert result["team_name"] == "Seattle Seahawks"
    assert result["wins"] == 16
    assert result["losses"] == 3


def test_compare_teams_nfl_returns_nfl_comparison(both_leagues_db: Path) -> None:
    from cfb_strength.mcp_server.server import compare_teams

    result = compare_teams(
        year=BOTH_LEAGUES_YEAR,
        team_a="Seattle Seahawks",
        team_b="Denver Broncos",
        sport="nfl",
    )
    assert "error" not in result, result
    assert result["head_to_head"]["played"] is True
    assert result["head_to_head"]["meetings"][0]["winner"] == "Seattle Seahawks"


def test_get_rankings_nfl_unknown_year_carries_sport(both_leagues_db: Path) -> None:
    """2005 has CFB ratings but no NFL ratings: an NFL caller must get
    unknown_year listing NFL's years, not CFB's 2005 leaderboard."""
    from cfb_strength.mcp_server.server import get_rankings

    result = get_rankings(year=2005, sport="nfl")
    assert result["error"] == "unknown_year"
    assert result["year"] == 2005
    assert result["sport"] == "nfl"
    assert result["available_years"] == [BOTH_LEAGUES_YEAR]


@pytest.mark.parametrize("tool_name", ["get_team_season", "get_champion", "compare_teams"])
def test_nfl_unknown_year_carries_sport_per_tool(both_leagues_db: Path, tool_name: str) -> None:
    import cfb_strength.mcp_server.server as server_module

    calls = {
        "get_team_season": lambda: server_module.get_team_season(
            year=1999, team="St. Louis Rams", sport="nfl"
        ),
        "get_champion": lambda: server_module.get_champion(year=1999, sport="nfl"),
        "compare_teams": lambda: server_module.compare_teams(
            year=1999, team_a="St. Louis Rams", team_b="Tennessee Titans", sport="nfl"
        ),
    }
    result = calls[tool_name]()
    assert result["error"] == "unknown_year", result
    assert result["year"] == 1999
    assert result["sport"] == "nfl"
    assert result["available_years"] == [BOTH_LEAGUES_YEAR]


def test_get_team_season_nfl_unknown_team_carries_sport(both_leagues_db: Path) -> None:
    """A CFB school under sport="nfl" is unknown_team for the NFL, even
    though it is rated in the same year in the other league."""
    from cfb_strength.mcp_server.server import get_team_season

    result = get_team_season(year=BOTH_LEAGUES_YEAR, team="Florida State", sport="nfl")
    assert result["error"] == "unknown_team"
    assert result["query"] == "Florida State"
    assert result["sport"] == "nfl"


def test_compare_teams_nfl_unknown_team_carries_sport(both_leagues_db: Path) -> None:
    from cfb_strength.mcp_server.server import compare_teams

    result = compare_teams(
        year=BOTH_LEAGUES_YEAR, team_a="Seattle Seahawks", team_b="Florida State", sport="nfl"
    )
    assert result["error"] == "unknown_team"
    assert result["query"] == "Florida State"
    assert result["sport"] == "nfl"


def test_teams_resource_entries_carry_sport(both_leagues_db: Path) -> None:
    from cfb_strength.mcp_server.server import teams_resource

    result = teams_resource()
    by_school = {t["school"]: t for t in result["teams"]}
    assert by_school["Florida State"]["sport"] == "cfb"
    assert by_school["Seattle Seahawks"]["sport"] == "nfl"
    assert all(t["sport"] in ("cfb", "nfl") for t in result["teams"])


def test_seasons_resource_matches_list_seasons_tool(both_leagues_db: Path) -> None:
    from cfb_strength.mcp_server.server import list_seasons, seasons_resource

    catalog = seasons_resource()
    assert catalog == list_seasons()
    keys = [(s["sport"], s["year"]) for s in catalog["seasons"]]
    assert keys == sorted(keys)
