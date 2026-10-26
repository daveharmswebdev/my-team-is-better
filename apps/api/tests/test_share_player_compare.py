"""`GET /api/share/nfl/compare`: the QB compare link's preview page (#185).

The link is `/nfl/compare?a=<id>&b=<id>`. An id is valid exactly when the web's
`parsePick` (`PlayerComparePage.tsx`) accepts it: ASCII digits only, no
trimming, and a JS safe integer. Names come from the player read path the
`/api/players/{player_id}` route uses, and the QB description is used when
both players are quarterbacks, the same position-group rule that decides
whether `/api/players/compare` carries the QB score.

Players from the committed fixture db: Brett Favre and Drew Bledsoe (QBs),
Alvin Kamara (RB).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from fixtures.share_page import GENERIC_DESCRIPTION, GENERIC_TITLE, WEB, assert_share_page

SHARE = "/api/share/nfl/compare"

BRETT_FAVRE = 2003442211
DREW_BLEDSOE = 2017631641
ALVIN_KAMARA = 2000863434

QB_DESCRIPTION = "Two quarterbacks, one era-adjusted score. The numbers settle it."


def _get(client: TestClient, query: str) -> str:
    response = client.get(f"{SHARE}?{query}" if query else SHARE)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "public, max-age=300"
    return response.text


def test_two_quarterbacks_get_the_qb_score_text(client: TestClient) -> None:
    assert_share_page(
        _get(client, f"a={BRETT_FAVRE}&b={DREW_BLEDSOE}"),
        title="Brett Favre vs. Drew Bledsoe",
        description=QB_DESCRIPTION,
        target=f"{WEB}/nfl/compare?a={BRETT_FAVRE}&b={DREW_BLEDSOE}",
    )


def test_a_non_quarterback_gets_the_plain_text(client: TestClient) -> None:
    assert_share_page(
        _get(client, f"a={BRETT_FAVRE}&b={ALVIN_KAMARA}"),
        title="Brett Favre vs. Alvin Kamara",
        description="Brett Favre or Alvin Kamara? The numbers settle it.",
        target=f"{WEB}/nfl/compare?a={BRETT_FAVRE}&b={ALVIN_KAMARA}",
    )


def test_leading_zeros_are_one_id_as_in_the_web(client: TestClient) -> None:
    """`Number("002003442211")` is the same pick, so the redirect carries
    the canonical integer."""
    assert_share_page(
        _get(client, f"a=00{BRETT_FAVRE}&b={DREW_BLEDSOE}"),
        title="Brett Favre vs. Drew Bledsoe",
        description=QB_DESCRIPTION,
        target=f"{WEB}/nfl/compare?a={BRETT_FAVRE}&b={DREW_BLEDSOE}",
    )


@pytest.mark.parametrize(
    "query",
    [
        "a=1&b=2",
        f"a={BRETT_FAVRE}&b=1",
        f"a=1&b={BRETT_FAVRE}",
        f"a={BRETT_FAVRE}&b={BRETT_FAVRE}",
        f"a={2**53 - 1}&b={BRETT_FAVRE}",
    ],
)
def test_unknown_or_repeated_ids_keep_their_redirect_with_generic_text(
    client: TestClient, query: str
) -> None:
    """A shape-valid pair that names no comparison (an unknown id, or one
    player twice, which the compare route refuses) still opens its page."""
    assert_share_page(
        _get(client, query),
        title=GENERIC_TITLE,
        description=GENERIC_DESCRIPTION,
        target=f"{WEB}/nfl/compare?{query}",
    )


@pytest.mark.parametrize(
    "query",
    [
        "",
        f"a={BRETT_FAVRE}",
        f"b={BRETT_FAVRE}",
        f"a=&b={BRETT_FAVRE}",
        f"a=favre&b={BRETT_FAVRE}",
        f"a=-1&b={BRETT_FAVRE}",
        f"a=1.0&b={BRETT_FAVRE}",
        f"a=%20{BRETT_FAVRE}&b={DREW_BLEDSOE}",
        f"a=%D9%A1&b={BRETT_FAVRE}",  # Arabic-Indic one: not an ASCII digit
        f"a={2**53}&b={BRETT_FAVRE}",  # past Number.MAX_SAFE_INTEGER
        f"a={'9' * 400}&b={BRETT_FAVRE}",
        "a=<script>&b=1",
    ],
)
def test_invalid_ids_get_generic_page_and_compare_home_redirect(
    client: TestClient, query: str
) -> None:
    assert_share_page(
        _get(client, query),
        title=GENERIC_TITLE,
        description=GENERIC_DESCRIPTION,
        target=f"{WEB}/nfl/compare",
    )
