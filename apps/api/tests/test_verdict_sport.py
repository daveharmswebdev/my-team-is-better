"""Failing-first tests for `sport` threading through `/api/verdict/*`
(GitHub issue #59).

Uses the `sport_client` fixture (see conftest.py / tests/fixtures/
sport_fixture.py) rather than the committed `cfb_verdict_fixture.sqlite3`,
since that fixture predates NFL support and has no `sport='nfl'` rows.
`sport_fixture.py`'s data also includes a cross-sport "Wildcats" name
collision (a CFB team and an NFL team sharing the same name, same
year/method) -- the edge case the brief calls out for
`list_all_team_names`/the persona grounding check's "known team names"
universe -- exercised here via `/api/verdict/team-case` for each sport.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

YEAR = 2023


def test_champion_defaults_to_cfb_when_sport_omitted(sport_client: TestClient) -> None:
    response = sport_client.post("/api/verdict/champion", json={"year": YEAR})

    assert response.status_code == 200
    body = response.json()["evidence"]
    assert body["team_name"] == "Alpha State"


def test_champion_explicit_cfb_matches_default(sport_client: TestClient) -> None:
    response = sport_client.post("/api/verdict/champion", json={"year": YEAR, "sport": "cfb"})

    assert response.status_code == 200
    assert response.json()["evidence"]["team_name"] == "Alpha State"


def test_champion_nfl_returns_nfl_champion(sport_client: TestClient) -> None:
    response = sport_client.post("/api/verdict/champion", json={"year": YEAR, "sport": "nfl"})

    assert response.status_code == 200
    body = response.json()["evidence"]
    assert body["team_name"] == "Delta Squad"
    assert body["wins"] == 2
    assert body["losses"] == 0


def test_team_case_nfl_resolves_nfl_team(sport_client: TestClient) -> None:
    response = sport_client.post(
        "/api/verdict/team-case",
        json={"year": YEAR, "team": "Echo Corp", "sport": "nfl"},
    )

    assert response.status_code == 200
    body = response.json()["evidence"]
    assert body["team_name"] == "Echo Corp"
    assert body["wins"] == 1
    assert body["losses"] == 1


def test_team_case_collision_name_resolves_within_requested_sport(
    sport_client: TestClient,
) -> None:
    """The name-colliding "Wildcats" pair: requesting sport='cfb' must
    resolve the CFB Wildcats, and sport='nfl' must resolve the NFL Wildcats
    -- not raise AmbiguousTeamError, and not cross-contaminate."""
    cfb_response = sport_client.post(
        "/api/verdict/team-case",
        json={"year": YEAR, "team": "Wildcats", "sport": "cfb"},
    )
    nfl_response = sport_client.post(
        "/api/verdict/team-case",
        json={"year": YEAR, "team": "Wildcats", "sport": "nfl"},
    )

    assert cfb_response.status_code == 200
    assert nfl_response.status_code == 200
    assert cfb_response.json()["evidence"]["team_id"] == 4
    assert nfl_response.json()["evidence"]["team_id"] == 104


def test_compare_nfl_returns_comparison_of_two_nfl_teams(sport_client: TestClient) -> None:
    response = sport_client.post(
        "/api/verdict/compare",
        json={"year": YEAR, "team_a": "Delta Squad", "team_b": "Echo Corp", "sport": "nfl"},
    )

    assert response.status_code == 200
    body = response.json()["evidence"]
    assert body["team_a"]["team_name"] == "Delta Squad"
    assert body["team_b"]["team_name"] == "Echo Corp"
    assert body["head_to_head"]["played"] is True


def test_compare_defaults_to_cfb_when_sport_omitted(sport_client: TestClient) -> None:
    response = sport_client.post(
        "/api/verdict/compare",
        json={"year": YEAR, "team_a": "Alpha State", "team_b": "Bravo Tech"},
    )

    assert response.status_code == 200
    body = response.json()["evidence"]
    assert body["team_a"]["team_name"] == "Alpha State"
    assert body["team_b"]["team_name"] == "Bravo Tech"


def test_unknown_year_for_nfl_reports_nfl_available_years(sport_client: TestClient) -> None:
    """2024 has an nfl-only rating row in the fixture (Golf United) -- an
    unknown CFB year for that same value must still 404 with the CFB
    available-years list, not accidentally leak the NFL list or vice versa.
    """
    response = sport_client.post("/api/verdict/champion", json={"year": 2024, "sport": "cfb"})

    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["error"] == "unknown_year"
    assert detail["available_years"] == [YEAR]
