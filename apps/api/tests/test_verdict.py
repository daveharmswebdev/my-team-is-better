"""Failing-first tests for the /api/verdict endpoints (GitHub issue #3).

Written before api/verdict.py existed, per CLAUDE.md's TDD rule. Covers the
three PRD §5.1 structured question types plus the three typed-exception ->
HTTP mappings from Architecture Brief §4.4. The 2005-champion-is-Texas test
is also this issue's required real-engine integration test: it goes through
the actual HTTP endpoint (TestClient), against the committed, real-engine
-computed fixture db (tests/fixtures/cfb_verdict_fixture.sqlite3) -- not a
mocked/handwritten evidence dataclass.

Issue #4 wrapped these routes' response in a `{"evidence": ..., "narration":
...}` envelope -- the assertions below read `body["evidence"][...]` rather
than `body[...]` to match (an expected, in-scope update to this file, since
issue #4's brief is the one that changed the response shape; error-path
tests are untouched, since typed-exception responses were never wrapped).
The `client` fixture (see conftest.py) wires a stub persona narrator + an
in-memory cache by default, so these tests never call the real Claude API.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_champion_endpoint_returns_2005_texas_full_case(client: TestClient) -> None:
    response = client.post("/api/verdict/champion", json={"year": 2005})

    assert response.status_code == 200
    body = response.json()["evidence"]
    assert body["year"] == 2005
    assert body["method"] == "keener"
    assert body["team_name"] == "Texas"
    assert body["rank"] == 1
    assert body["wins"] == 13
    assert body["losses"] == 0
    assert isinstance(body["games"], list) and len(body["games"]) > 0
    usc_wins = [g for g in body["quality_wins"] if g["opponent_name"] == "USC"]
    assert len(usc_wins) == 1
    assert usc_wins[0]["team_score"] == 41
    assert usc_wins[0]["opponent_score"] == 38


def test_team_case_endpoint_returns_named_team_case(client: TestClient) -> None:
    response = client.post("/api/verdict/team-case", json={"year": 2005, "team": "USC"})

    assert response.status_code == 200
    body = response.json()["evidence"]
    assert body["team_name"] == "USC"
    assert body["year"] == 2005
    assert body["wins"] == 12
    assert body["losses"] == 1
    assert body["worst_loss"] is not None


def test_compare_endpoint_returns_comparison_of_two_named_teams(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/verdict/compare",
        json={"year": 2005, "team_a": "Texas", "team_b": "USC"},
    )

    assert response.status_code == 200
    body = response.json()["evidence"]
    assert body["year"] == 2005
    assert body["team_a"]["team_name"] == "Texas"
    assert body["team_b"]["team_name"] == "USC"
    assert body["head_to_head"]["played"] is True
    assert isinstance(body["common_opponents"], list)
    assert isinstance(body["verdict"], str) and body["verdict"]


def test_unknown_year_returns_404_with_available_years(client: TestClient) -> None:
    response = client.post("/api/verdict/champion", json={"year": 1999})

    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["error"] == "unknown_year"
    assert detail["year"] == 1999
    assert 2005 in detail["available_years"]


def test_ambiguous_team_returns_422_with_candidates(client: TestClient) -> None:
    response = client.post("/api/verdict/team-case", json={"year": 2005, "team": "State"})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["error"] == "ambiguous_team"
    assert detail["query"] == "State"
    assert len(detail["candidates"]) > 1


def test_same_team_comparison_returns_400(client: TestClient) -> None:
    response = client.post(
        "/api/verdict/compare",
        json={"year": 2005, "team_a": "Texas", "team_b": "Texas"},
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["error"] == "same_team_comparison"
    assert detail["team_name"] == "Texas"
