"""Share pages never reach the narrator or Claude (issue #185).

A link preview is fetched by every chat app a link is pasted into, so it
must cost nothing and never depend on Claude. Every narrator and cache
dependency is overridden to raise, the Claude client's constructor and
`create` raise too, and every route shape must still answer 200.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import NoReturn

import pytest
from fastapi.testclient import TestClient

ROUTE_SHAPES = [
    "/api/share?q=champion&sport=cfb&year=2005&engine=keener",
    "/api/share?q=champion&sport=nfl&year=2023&engine=elo&for=Texas",
    "/api/share?q=team_case&sport=cfb&year=2005&engine=keener&team=OSU&for=Texas",
    "/api/share?q=team_case&sport=cfb&year=2005&engine=keener&team=Narnia",
    "/api/share?q=compare&sport=cfb&year=2005&engine=elo&a=Texas&b=OSU",
    "/api/share?q=compare&sport=nfl&year=2023&engine=keener&a=Atlanta%20Falcons&b=Carolina%20Panthers",
    "/api/share?q=nope",
    "/api/share",
    "/api/share/nfl/compare?a=2003442211&b=2017631641",
    "/api/share/nfl/compare?a=2003442211&b=2000863434",
    "/api/share/nfl/compare?a=1&b=2",
    "/api/share/nfl/compare?a=x",
    "/api/share/nfl/compare",
]


def _boom(*args: object, **kwargs: object) -> NoReturn:
    raise AssertionError("a share page reached the narrator, its cache or Claude")


def _boom_dependency() -> NoReturn:
    """`_boom` with no parameters: FastAPI would read `*args`/`**kwargs` on
    a dependency as required query parameters and 422 before calling it."""
    _boom()


@pytest.fixture
def no_narrator_client(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    import anthropic

    from api import players, verdict
    from api.deps import (
        get_narration_cache,
        get_narrator,
        get_qb_narration_cache,
        get_qb_narrator,
    )
    from api.main import app
    from api.persona import claude_client, service

    for dependency in (get_narrator, get_narration_cache, get_qb_narrator, get_qb_narration_cache):
        app.dependency_overrides[dependency] = _boom_dependency
    monkeypatch.setattr(claude_client.ClaudeNarrator, "__init__", _boom)
    monkeypatch.setattr(claude_client.ClaudeNarrator, "submit", _boom)
    monkeypatch.setattr(anthropic, "Anthropic", _boom)
    for name in ("narrate_team_case", "narrate_comparison", "narrate_qb_comparison"):
        monkeypatch.setattr(service, name, _boom)
    monkeypatch.setattr(verdict, "narrate_team_case", _boom)
    monkeypatch.setattr(verdict, "narrate_comparison", _boom)
    monkeypatch.setattr(players, "narrate_qb_comparison", _boom)
    try:
        yield client
    finally:
        for dependency in (get_qb_narrator, get_qb_narration_cache):
            app.dependency_overrides.pop(dependency, None)


@pytest.mark.parametrize("path", ROUTE_SHAPES)
def test_every_share_route_shape_answers_without_the_narrator(
    no_narrator_client: TestClient, path: str
) -> None:
    response = no_narrator_client.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_the_guard_is_live(no_narrator_client: TestClient) -> None:
    """Sanity: the same overrides do break a route that narrates, so the
    200s above aren't vacuous."""
    with pytest.raises(AssertionError, match="reached the narrator"):
        no_narrator_client.post("/api/verdict/team-case", json={"team": "Texas", "year": 2005})
