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
    assert {"year": 2005, "methods": ["keener"]} in result["seasons"]


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
