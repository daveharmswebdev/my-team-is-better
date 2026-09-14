"""Failing-first tests for `/api/years` and `/api/teams` (GitHub issue #13).

Both routes are plain evidence-catalog reads -- no persona/narration layer,
no MCP -- so unlike `test_verdict.py`'s `{"evidence": ..., "narration": ...}`
envelope, these responses are unwrapped: `{"years": [...]}` /
`{"teams": [...]}` directly.

Both tests go through the actual HTTP endpoint (`TestClient`) against the
committed, real-engine-computed fixture db
(`tests/fixtures/cfb_verdict_fixture.sqlite3`), which has real keener
ratings for the seven golden seasons (2001, 2003, 2004, 2005, 2013, 2017,
2019) and the real `teams` table (including "Texas",
the 2005 champion used throughout `test_verdict.py`) -- not a mocked or
hand-written list.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_years_endpoint_default_method_returns_real_ascending_years(
    client: TestClient,
) -> None:
    response = client.get("/api/years")

    assert response.status_code == 200
    body = response.json()
    assert body == {"years": [2001, 2003, 2004, 2005, 2013, 2017, 2019]}


def test_years_endpoint_explicit_keener_method_matches_default(
    client: TestClient,
) -> None:
    response = client.get("/api/years", params={"method": "keener"})

    assert response.status_code == 200
    body = response.json()
    assert body == {"years": [2001, 2003, 2004, 2005, 2013, 2017, 2019]}
    # ascending, matching `list_available_years`'s own contract
    assert body["years"] == sorted(body["years"])


def test_teams_endpoint_returns_real_team_names(client: TestClient) -> None:
    response = client.get("/api/teams")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["teams"], list)
    assert "Texas" in body["teams"]
    assert "USC" in body["teams"]
