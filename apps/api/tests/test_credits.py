"""Failing-first test for `/api/credits` (GitHub issue #29/#30, updated for
#59's `Credits.data_sources` list rename and for the Elo engine's
`Credits.methodologies` list rename).

Like `/api/years` and `/api/teams`, this is a plain evidence-catalog read --
no persona/narration envelope, no db connection at all (`get_credits()`
takes no arguments and touches no database). The expected body is taken
directly from `cfb_strength.evidence.credits.get_credits()`'s actual return
value rather than retyped from memory, so this test breaks if that single
source of truth ever changes -- which is the point (ARCHITECTURE §4.5: no
hardcoded duplicate copy of the citation text in apps/api).

Two singular-to-plural contract renames are pinned here. `Credits.data_source`
became `Credits.data_sources` in PR #67, so both CollegeFootballData.com (CFB)
and nflverse/Lee Sharpe (NFL) must show up. `Credits.methodology` became
`Credits.methodologies` when the Elo engine landed (PR #93), so both Keener's
method and Elo must show up, in that order.

The Keener/Elo assertions below are deliberately *content* assertions, not
just shape ones: PRD §5.6 makes crediting the people whose work this is built
on an explicit product requirement, so a future change that quietly drops the
second methodology -- or drops Arpad Elo's or FiveThirtyEight's name out of
it -- must fail a test rather than merely change a payload.
"""

from __future__ import annotations

from cfb_strength.evidence.credits import get_credits
from fastapi.testclient import TestClient


def test_credits_endpoint_returns_real_attribution_data(client: TestClient) -> None:
    response = client.get("/api/credits")

    assert response.status_code == 200
    body = response.json()

    credits = get_credits()
    assert body == {
        "methodologies": [
            {
                "name": methodology.name,
                "citation": methodology.citation,
                "url": methodology.url,
                "summary": methodology.summary,
            }
            for methodology in credits.methodologies
        ],
        "data_sources": [
            {
                "name": data_source.name,
                "url": data_source.url,
                "note": data_source.note,
            }
            for data_source in credits.data_sources
        ],
    }


def test_credits_endpoint_lists_both_keener_and_elo_in_order(client: TestClient) -> None:
    """Both rating methods this engine implements are credited, Keener
    first then Elo -- the order `get_credits()` returns them in, which is
    the order the About page renders.

    Pinned against literal names rather than only against
    `get_credits()`'s own output: a whole-payload equality check passes
    happily if a methodology is deleted from the source of truth, and
    silently dropping an attribution is exactly the regression PRD §5.6
    exists to prevent.
    """
    response = client.get("/api/credits")

    assert response.status_code == 200
    methodologies = response.json()["methodologies"]

    assert [entry["name"] for entry in methodologies] == ["Keener's method", "Elo"]

    credits = get_credits()
    assert [entry["name"] for entry in methodologies] == [
        methodology.name for methodology in credits.methodologies
    ]


def test_credits_endpoint_names_elo_and_fivethirtyeight(client: TestClient) -> None:
    """The Elo entry credits Arpad Elo (who invented the system) and
    FiveThirtyEight (whose published football adaptation this engine
    implements from the formula, clean-room). Both names are a founder
    value, not boilerplate -- see CLAUDE.md's standing attribution
    preference and PRD §5.6.
    """
    response = client.get("/api/credits")

    assert response.status_code == 200
    elo = next(entry for entry in response.json()["methodologies"] if entry["name"] == "Elo")

    attribution_text = f"{elo['citation']} {elo['summary']}"
    assert "Arpad" in attribution_text and "Elo" in attribution_text
    assert "FiveThirtyEight" in attribution_text
    assert elo["url"]


def test_credits_endpoint_lists_both_cfbd_and_nflverse(client: TestClient) -> None:
    """Issue #59: nflverse/Lee Sharpe attribution must be listed alongside
    the existing CollegeFootballData.com entry, matching the standing
    project preference (CLAUDE.md) that original data sources be credited
    prominently in-product, not just in a README.
    """
    response = client.get("/api/credits")

    assert response.status_code == 200
    names = {entry["name"] for entry in response.json()["data_sources"]}

    credits = get_credits()
    assert names == {data_source.name for data_source in credits.data_sources}
    assert any("CollegeFootballData" in name for name in names)
    assert any("nflverse" in name for name in names)
