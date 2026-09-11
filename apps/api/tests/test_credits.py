"""Failing-first test for `/api/credits` (GitHub issue #29/#30).

Like `/api/years` and `/api/teams`, this is a plain evidence-catalog read --
no persona/narration envelope, no db connection at all (`get_credits()`
takes no arguments and touches no database). The expected body is taken
directly from `cfb_strength.evidence.credits.get_credits()`'s actual return
value rather than retyped from memory, so this test breaks if that single
source of truth ever changes -- which is the point (ARCHITECTURE §4.5: no
hardcoded duplicate copy of the citation text in apps/api).
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
        "data_source": {
            "name": credits.data_source.name,
            "url": credits.data_source.url,
            "note": credits.data_source.note,
        },
    }
