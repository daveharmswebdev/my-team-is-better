"""Failing-first tests for CORS support (issue #13).

Two things under test:

1. `api.main.app` actually carries `CORSMiddleware` wired to the default
   allowed-origins list, so a browser request from the Vite dev server
   (`http://localhost:5173`) gets back an `access-control-allow-origin`
   header instead of being rejected before this API's response body is ever
   seen.
2. `api.config.CORS_ALLOWED_ORIGINS` parses a comma-separated
   `CORS_ALLOWED_ORIGINS` env var when set, overriding the
   `http://localhost:5173`-only default -- mirroring `test_config.py`'s
   monkeypatch-then-reimport pattern for `DATABASE_URL`/`ANTHROPIC_API_KEY`.
"""

from __future__ import annotations

import importlib
import sys

import pytest
from fastapi.testclient import TestClient


def _reimport_config() -> object:
    sys.modules.pop("api.config", None)
    return importlib.import_module("api.config")


def test_health_request_from_default_dev_origin_gets_cors_header() -> None:
    from api.main import app

    client = TestClient(app)

    response = client.get("/health", headers={"Origin": "http://localhost:5173"})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_health_request_from_disallowed_origin_gets_no_cors_header() -> None:
    from api.main import app

    client = TestClient(app)

    response = client.get("/health", headers={"Origin": "http://evil.example.com"})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_config_defaults_cors_allowed_origins_to_localhost_5173(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
    monkeypatch.setenv("MY_TEAM_IS_BETTER_API_ENV_FILE", "/nonexistent/.env")

    config = _reimport_config()

    assert config.CORS_ALLOWED_ORIGINS == ["http://localhost:5173"]  # type: ignore[attr-defined]


def test_config_cors_allowed_origins_env_var_overrides_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "CORS_ALLOWED_ORIGINS",
        "https://my-team-is-better-web.onrender.com,http://localhost:5173",
    )

    config = _reimport_config()

    assert config.CORS_ALLOWED_ORIGINS == [  # type: ignore[attr-defined]
        "https://my-team-is-better-web.onrender.com",
        "http://localhost:5173",
    ]
