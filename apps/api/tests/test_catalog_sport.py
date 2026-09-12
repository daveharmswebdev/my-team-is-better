"""Failing-first tests for `sport` scoping on `/api/years` and `/api/teams`
(GitHub issue #59). See `test_catalog.py` for the pre-existing default-sport
(`cfb`) coverage against the real `cfb_verdict_fixture.sqlite3` -- these use
`sport_client` (tests/fixtures/sport_fixture.py) instead, since that fixture
has no NFL rows.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_years_endpoint_default_sport_is_cfb(sport_client: TestClient) -> None:
    response = sport_client.get("/api/years")

    assert response.status_code == 200
    assert response.json() == {"years": [2023]}


def test_years_endpoint_explicit_cfb_matches_default(sport_client: TestClient) -> None:
    response = sport_client.get("/api/years", params={"sport": "cfb"})

    assert response.status_code == 200
    assert response.json() == {"years": [2023]}


def test_years_endpoint_nfl_returns_nfl_years(sport_client: TestClient) -> None:
    response = sport_client.get("/api/years", params={"sport": "nfl"})

    assert response.status_code == 200
    assert response.json() == {"years": [2023, 2024]}


def test_teams_endpoint_default_sport_is_cfb(sport_client: TestClient) -> None:
    response = sport_client.get("/api/teams")

    assert response.status_code == 200
    teams = response.json()["teams"]
    assert "Alpha State" in teams
    assert "Delta Squad" not in teams


def test_teams_endpoint_nfl_scopes_to_nfl_teams(sport_client: TestClient) -> None:
    response = sport_client.get("/api/teams", params={"sport": "nfl"})

    assert response.status_code == 200
    teams = response.json()["teams"]
    assert "Delta Squad" in teams
    assert "Alpha State" not in teams


def test_teams_endpoint_collision_name_appears_once_per_sport(
    sport_client: TestClient,
) -> None:
    """ "Wildcats" exists in both sports -- each sport-scoped list must
    contain it exactly once, not leak the other sport's row in."""
    cfb_teams = sport_client.get("/api/teams", params={"sport": "cfb"}).json()["teams"]
    nfl_teams = sport_client.get("/api/teams", params={"sport": "nfl"}).json()["teams"]

    assert cfb_teams.count("Wildcats") == 1
    assert nfl_teams.count("Wildcats") == 1
