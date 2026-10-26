"""Share pages escape every interpolated value for its context (issue #185).

A third party writes a share link's query, and the page puts text derived
from it in three contexts: HTML text (`<title>`, the fallback link),
HTML attributes (every meta `content`, the link's `href`) and a JS string
(`location.replace(...)`). Validation already keeps markup out of a team
value, so these probes go further and assume a hostile value reached the
page anyway: a catalog name, a player name or `PUBLIC_WEB_URL` carrying
markup. Each page is parsed with `html.parser` and must have exactly the
expected elements, with every meta content equal to the intended string.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from fixtures.share_page import (
    GENERIC_DESCRIPTION,
    GENERIC_TITLE,
    WEB,
    assert_share_page,
    parse_share_page,
)

import api.share

PROBES = [
    "<script>alert(1)</script>",
    '"><img src=x onerror=alert(1)>',
    "</script><script>alert(1)</script>",
    "javascript:alert(1)",
    "<!-- x",
    'it\'s & "that"',
]


def _html(client: TestClient, path: str, query: str) -> str:
    response = client.get(f"{path}?{query}")
    assert response.status_code == 200
    return response.text


def test_a_real_catalog_name_with_an_ampersand_is_escaped(client: TestClient) -> None:
    params = [
        ("q", "team_case"),
        ("sport", "cfb"),
        ("year", "2005"),
        ("engine", "keener"),
        ("team", "Texas A&M"),
    ]
    html = _html(client, "/api/share", urlencode(params))
    assert_share_page(
        html,
        title="The case for Texas A&M, 2005",
        description="How good was Texas A&M in 2005? The numbers make the case.",
        target=f"{WEB}/?{urlencode(params)}",
    )
    assert "A&M," not in html  # the raw ampersand never reaches the markup


@pytest.mark.parametrize("probe", PROBES)
def test_hostile_catalog_name_is_escaped_everywhere(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, probe: str
) -> None:
    """If the catalog ever resolved a name to markup, it would still be text."""
    monkeypatch.setattr(api.share, "resolve_user_team", lambda records, team: probe)
    params = [
        ("q", "team_case"),
        ("sport", "cfb"),
        ("year", "2005"),
        ("engine", "keener"),
        ("team", "Texas"),
    ]
    assert_share_page(
        _html(client, "/api/share", urlencode(params)),
        title=f"The case for {probe}, 2005",
        description=f"How good was {probe} in 2005? The numbers make the case.",
        target=f"{WEB}/?{urlencode(params)}",
    )


@pytest.mark.parametrize("probe", PROBES)
def test_hostile_player_name_is_escaped_everywhere(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, probe: str
) -> None:
    def fake_career(conn: Any, *, sport: str, player_id: int) -> SimpleNamespace:
        return SimpleNamespace(display_name=f"{probe}{player_id}", group="QB")

    monkeypatch.setattr(api.share, "get_player_career", fake_career)
    assert_share_page(
        _html(client, "/api/share/nfl/compare", "a=1&b=2"),
        title=f"{probe}1 vs. {probe}2",
        description="Two quarterbacks, one era-adjusted score. The numbers settle it.",
        target=f"{WEB}/nfl/compare?a=1&b=2",
    )


@pytest.mark.parametrize("probe", PROBES)
def test_hostile_public_web_url_stays_inside_its_attribute_and_string(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, probe: str
) -> None:
    """The redirect target is the one value in the JS string; even a
    misconfigured origin can't close the script or the attribute."""
    origin = f"https://x.test/{probe}"
    monkeypatch.setattr(api.share, "PUBLIC_WEB_URL", origin)
    assert_share_page(
        _html(client, "/api/share/nfl/compare", "a=x"),
        title=GENERIC_TITLE,
        description=GENERIC_DESCRIPTION,
        target=f"{origin}/nfl/compare",
    )


@pytest.mark.parametrize("probe", PROBES)
@pytest.mark.parametrize("key", ["q", "sport", "year", "engine", "team", "a", "b", "for"])
def test_probe_in_any_query_param_never_leaves_public_web_url(
    client: TestClient, probe: str, key: str
) -> None:
    base = {
        "q": "compare",
        "sport": "cfb",
        "year": "2005",
        "engine": "keener",
        "a": "Texas",
        "b": "Ohio State",
    }
    html = _html(client, "/api/share", urlencode({**base, key: probe}))
    page = parse_share_page(html)
    target = page.metas["og:url"]
    assert target == f"{WEB}/" or target.startswith(f"{WEB}/?")
    assert_share_page(
        html,
        title=page.title,
        description=page.metas["og:description"],
        target=target,
    )
    assert "<script>alert" not in html and "onerror" not in html.replace("onerror%3D", "")
