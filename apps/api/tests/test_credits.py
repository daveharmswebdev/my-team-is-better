"""Failing-first test for `/api/credits` (GitHub issue #29/#30, updated for
#59's `Credits.data_sources` list rename).

Like `/api/years` and `/api/teams`, this is a plain evidence-catalog read --
no persona/narration envelope, no db connection at all (`get_credits()`
takes no arguments and touches no database). The expected body is taken
directly from `cfb_strength.evidence.credits.get_credits()`'s actual return
value rather than retyped from memory, so this test breaks if that single
source of truth ever changes -- which is the point (ARCHITECTURE §4.5: no
hardcoded duplicate copy of the citation text in apps/api).

`Credits.data_source` (singular) became `Credits.data_sources` (a list) in
PR #67, so both entries -- CollegeFootballData.com (CFB) and nflverse/Lee
Sharpe (NFL) -- must show up here, asserted against the real
`get_credits().data_sources` content rather than a hardcoded retyped copy.
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
        "methodology": {
            "name": credits.methodology.name,
            "citation": credits.methodology.citation,
            "url": credits.methodology.url,
            "summary": credits.methodology.summary,
        },
        "data_sources": [
            {
                "name": data_source.name,
                "url": data_source.url,
                "note": data_source.note,
            }
            for data_source in credits.data_sources
        ],
    }


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
