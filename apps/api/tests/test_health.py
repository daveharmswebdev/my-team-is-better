"""Failing-first test for GET /health.

Written before apps/api/src/api/main.py existed, per CLAUDE.md's TDD rule.
"""

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_health_returns_200_ok_json() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
