"""`api.config.PUBLIC_WEB_URL` (issue #185): the web origin a share page
redirects to. It defaults to production's web service and drops a trailing
slash, so `PUBLIC_WEB_URL + "/?..."` never has a double slash."""

from __future__ import annotations

import importlib
import sys
from types import ModuleType

import pytest


def _reimport_config() -> ModuleType:
    sys.modules.pop("api.config", None)
    return importlib.import_module("api.config")


@pytest.fixture(autouse=True)
def _no_env_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_TEAM_IS_BETTER_API_ENV_FILE", "/nonexistent/.env")


def test_public_web_url_defaults_to_production_web(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PUBLIC_WEB_URL", raising=False)
    config = _reimport_config()
    assert config.PUBLIC_WEB_URL == "https://my-team-is-better-web.onrender.com"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("http://localhost:5173", "http://localhost:5173"),
        ("https://example.test/", "https://example.test"),
        ("https://example.test///", "https://example.test"),
    ],
)
def test_public_web_url_reads_env_and_strips_trailing_slash(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: str
) -> None:
    monkeypatch.setenv("PUBLIC_WEB_URL", raw)
    config = _reimport_config()
    assert config.PUBLIC_WEB_URL == expected
