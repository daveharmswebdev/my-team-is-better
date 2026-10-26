"""`GET /api/share`: a verdict share link's preview page (issue #185).

The web's share link (`apps/web/src/pages/HomePage/shareLink.ts`, #184)
holds the question, never the answer. A link-preview scraper runs no JS, so
the SPA's static tags describe every link the same way. This route answers
the same query with a small page whose Open Graph and Twitter tags describe
the question asked, then redirects a human to the SPA with that question.

The text comes from the query and the db's team catalog only: never the
narrator, never a verdict. Team names are the canonical catalog names
(`api.verdict.resolve_user_team`), so `OSU` previews as Ohio State. A link
the web would reject (`fromShareSearch` returns null) is a 200 with the
generic site tags and a redirect to `/`; a valid link whose team doesn't
resolve keeps its redirect and falls back to the generic text only.

Teams come from the committed fixture db: Ohio State (alias `OSU`), Texas
(no alias needed), and the NFL's Atlanta Falcons and Carolina Panthers.
"""

from __future__ import annotations

from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from fixtures.share_page import (
    GENERIC_DESCRIPTION,
    GENERIC_TITLE,
    WEB,
    assert_share_page,
)

SHARE = "/api/share"
CFB_2005_CHAMPION = (
    "The 2005 college football season, ranked by the math. See who comes out on top."
)


def _get(client: TestClient, params: list[tuple[str, str]] | str) -> str:
    query = params if isinstance(params, str) else urlencode(params)
    response = client.get(f"{SHARE}?{query}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "public, max-age=300"
    return response.text


def _web(params: list[tuple[str, str]]) -> str:
    return f"{WEB}/?{urlencode(params)}"


# ---------------------------------------------------------------------------
# champion
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("sport", "label"), [("cfb", "college football"), ("nfl", "NFL")])
def test_champion_link_describes_the_season(client: TestClient, sport: str, label: str) -> None:
    params = [("q", "champion"), ("sport", sport), ("year", "2005"), ("engine", "keener")]
    assert_share_page(
        _get(client, params),
        title=f"Best {label} team of 2005",
        description=f"The 2005 {label} season, ranked by the math. See who comes out on top.",
        target=_web(params),
    )


def test_champion_link_ignores_for_entirely(client: TestClient) -> None:
    """`for` on a champion link is neither validated nor carried (#198):
    even a value the web would reject leaves the link valid."""
    params = [("q", "champion"), ("sport", "cfb"), ("year", "2005"), ("engine", "elo")]
    assert_share_page(
        _get(client, [*params, ("for", "<not a team>")]),
        title="Best college football team of 2005",
        description=CFB_2005_CHAMPION,
        target=_web(params),
    )


def test_values_are_trimmed_and_reordered(client: TestClient) -> None:
    """Every value is trimmed, and the redirect re-serializes the validated
    params in the web's own order whatever order the link used."""
    html = _get(client, "engine=+keener+&year=%202005%20&sport=cfb&q=champion")
    assert_share_page(
        html,
        title="Best college football team of 2005",
        description=CFB_2005_CHAMPION,
        target=f"{WEB}/?q=champion&sport=cfb&year=2005&engine=keener",
    )


def test_duplicate_params_use_the_first_value_like_urlsearchparams(client: TestClient) -> None:
    html = _get(client, "q=champion&sport=nfl&sport=cfb&year=2005&engine=keener")
    assert_share_page(
        html,
        title="Best NFL team of 2005",
        description="The 2005 NFL season, ranked by the math. See who comes out on top.",
        target=f"{WEB}/?q=champion&sport=nfl&year=2005&engine=keener",
    )


# ---------------------------------------------------------------------------
# team_case
# ---------------------------------------------------------------------------


def test_team_case_uses_the_canonical_name_for_an_alias(client: TestClient) -> None:
    params = [
        ("q", "team_case"),
        ("sport", "cfb"),
        ("year", "2005"),
        ("engine", "keener"),
        ("team", "OSU"),
    ]
    assert_share_page(
        _get(client, params),
        title="The case for Ohio State, 2005",
        description="How good was Ohio State in 2005? The numbers make the case.",
        target=_web(params),
    )


def test_team_case_folds_case_to_the_canonical_name(client: TestClient) -> None:
    params = [
        ("q", "team_case"),
        ("sport", "nfl"),
        ("year", "2023"),
        ("engine", "elo"),
        ("team", "atlanta falcons"),
    ]
    assert_share_page(
        _get(client, params),
        title="The case for Atlanta Falcons, 2023",
        description="How good was Atlanta Falcons in 2023? The numbers make the case.",
        target=_web(params),
    )


def test_team_case_carries_for_but_never_shows_it(client: TestClient) -> None:
    params = [
        ("q", "team_case"),
        ("sport", "cfb"),
        ("year", "2005"),
        ("engine", "keener"),
        ("team", "Texas"),
        ("for", "Ohio State"),
    ]
    html = _get(client, params)
    assert_share_page(
        html,
        title="The case for Texas, 2005",
        description="How good was Texas in 2005? The numbers make the case.",
        target=_web(params),
    )
    assert "Ohio State" not in html.split("<body>")[0].replace(_web(params), "")


def test_team_case_unknown_team_keeps_its_redirect_with_generic_text(
    client: TestClient,
) -> None:
    params = [
        ("q", "team_case"),
        ("sport", "cfb"),
        ("year", "2005"),
        ("engine", "keener"),
        ("team", "Narnia State"),
    ]
    assert_share_page(
        _get(client, params),
        title=GENERIC_TITLE,
        description=GENERIC_DESCRIPTION,
        target=_web(params),
    )


def test_a_team_is_resolved_against_the_request_sport_only(client: TestClient) -> None:
    """Ohio State is a CFB team; on an NFL link it doesn't resolve."""
    params = [
        ("q", "team_case"),
        ("sport", "nfl"),
        ("year", "2023"),
        ("engine", "keener"),
        ("team", "Ohio State"),
    ]
    assert_share_page(
        _get(client, params),
        title=GENERIC_TITLE,
        description=GENERIC_DESCRIPTION,
        target=_web(params),
    )


# ---------------------------------------------------------------------------
# compare
# ---------------------------------------------------------------------------


def test_compare_link_names_both_canonical_teams(client: TestClient) -> None:
    params = [
        ("q", "compare"),
        ("sport", "cfb"),
        ("year", "2005"),
        ("engine", "elo"),
        ("a", "OSU"),
        ("b", "texas"),
        ("for", "Texas"),
    ]
    html = _get(client, params)
    assert_share_page(
        html,
        title="Ohio State vs. Texas, 2005",
        description="Ohio State or Texas? The numbers settle it.",
        target=_web(params),
    )


def test_nfl_compare_link(client: TestClient) -> None:
    params = [
        ("q", "compare"),
        ("sport", "nfl"),
        ("year", "2023"),
        ("engine", "keener"),
        ("a", "Atlanta Falcons"),
        ("b", "Carolina Panthers"),
    ]
    assert_share_page(
        _get(client, params),
        title="Atlanta Falcons vs. Carolina Panthers, 2023",
        description="Atlanta Falcons or Carolina Panthers? The numbers settle it.",
        target=_web(params),
    )


@pytest.mark.parametrize(
    ("a", "b"), [("Narnia State", "Texas"), ("Texas", "Narnia State"), ("Texas", "texas")]
)
def test_compare_with_an_unresolved_or_repeated_team_gets_generic_text(
    client: TestClient, a: str, b: str
) -> None:
    """Either side unknown, or both sides naming one team (a question the
    verdict refuses), keeps the redirect and falls back to the generic text."""
    params = [
        ("q", "compare"),
        ("sport", "cfb"),
        ("year", "2005"),
        ("engine", "keener"),
        ("a", a),
        ("b", b),
    ]
    assert_share_page(
        _get(client, params),
        title=GENERIC_TITLE,
        description=GENERIC_DESCRIPTION,
        target=_web(params),
    )


# ---------------------------------------------------------------------------
# invalid shapes: 200, generic text, redirect to /
# ---------------------------------------------------------------------------

_VALID_TEAM_CASE = {
    "q": "team_case",
    "sport": "cfb",
    "year": "2005",
    "engine": "keener",
    "team": "Texas",
}

INVALID = {
    "bad sport": {**_VALID_TEAM_CASE, "sport": "nba"},
    "engine not displayed": {**_VALID_TEAM_CASE, "engine": "elo_career"},
    "three-digit year": {**_VALID_TEAM_CASE, "year": "205"},
    "five-digit year": {**_VALID_TEAM_CASE, "year": "20055"},
    "non-ascii digits year": {**_VALID_TEAM_CASE, "year": "٢٠٠٥"},
    "65-char team": {**_VALID_TEAM_CASE, "team": "A" * 65},
    "team with <": {**_VALID_TEAM_CASE, "team": "Tex<as"},
    "team with double quote": {**_VALID_TEAM_CASE, "team": 'Tex"as'},
    "blank team": {**_VALID_TEAM_CASE, "team": "   "},
    "missing team": {k: v for k, v in _VALID_TEAM_CASE.items() if k != "team"},
    "bad for": {**_VALID_TEAM_CASE, "for": "<b>"},
    "unknown q": {**_VALID_TEAM_CASE, "q": "dynasty"},
    "missing q": {k: v for k, v in _VALID_TEAM_CASE.items() if k != "q"},
    "compare missing b": {
        "q": "compare",
        "sport": "cfb",
        "year": "2005",
        "engine": "keener",
        "a": "Texas",
    },
    "empty": {},
}


@pytest.mark.parametrize("params", INVALID.values(), ids=INVALID.keys())
def test_invalid_link_gets_generic_page_and_home_redirect(
    client: TestClient, params: dict[str, str]
) -> None:
    assert_share_page(
        _get(client, list(params.items())),
        title=GENERIC_TITLE,
        description=GENERIC_DESCRIPTION,
        target=f"{WEB}/",
    )


@pytest.mark.parametrize(
    "query",
    [
        "q=%ZZ&sport=%",
        "q=champion&year=" + "9" * 5000,
        "&&&==&q",
        "team=" + "%F0%9F%98%80" * 200,
    ],
)
def test_garbage_never_errors(client: TestClient, query: str) -> None:
    assert_share_page(
        _get(client, query),
        title=GENERIC_TITLE,
        description=GENERIC_DESCRIPTION,
        target=f"{WEB}/",
    )


# ---------------------------------------------------------------------------
# PUBLIC_WEB_URL
# ---------------------------------------------------------------------------


def test_redirect_uses_public_web_url(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    import api.share

    monkeypatch.setattr(api.share, "PUBLIC_WEB_URL", "http://localhost:5173")
    params = [("q", "champion"), ("sport", "cfb"), ("year", "2005"), ("engine", "keener")]
    assert_share_page(
        _get(client, params),
        title="Best college football team of 2005",
        description=CFB_2005_CHAMPION,
        target=f"http://localhost:5173/?{urlencode(params)}",
    )
