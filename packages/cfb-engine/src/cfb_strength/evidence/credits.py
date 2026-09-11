"""Static attribution data: methodology citation + data source credit.

This is the single source of truth for the project's attribution copy --
`mcp_server/server.py`'s `credits_resource()` and, via a direct Python
import, `apps/api`'s credits endpoint both build on `get_credits()` rather
than each keeping their own copy (ARCHITECTURE §4.5 / PRD §5.6). No db
access is required; the content is static.
"""

from __future__ import annotations

from cfb_strength.contracts import Credits, DataSourceCredit, MethodologyCredit


def get_credits() -> Credits:
    """Return the project's static attribution data.

    Covers the methodology this engine implements (Keener's method) and the
    data source game results are ingested from (CollegeFootballData.com).
    """
    return Credits(
        methodology=MethodologyCredit(
            name="Keener's method",
            citation=(
                'J. P. Keener, "The Perron-Frobenius Theorem and the Ranking of '
                'Football Teams," SIAM Review, 35(1), 1993.'
            ),
            url="https://dl.acm.org/doi/10.1137/1035004",
            summary=(
                "A team's rating depends recursively on the strength of the teams "
                "it beat, whose strength depends on the strength of their "
                "opponents -- the same Perron-Frobenius eigenvector idea behind "
                "PageRank, applied to a win graph. This server computes stock "
                "Keener with win/loss as the dominant signal; margin of victory "
                "is not weighted."
            ),
        ),
        data_source=DataSourceCredit(
            name="CollegeFootballData.com (CFBD)",
            url="https://collegefootballdata.com",
            note=(
                "All game results are ingested from the CFBD API. This project "
                "performs no independent data collection and claims no "
                "ownership of the underlying game data."
            ),
        ),
    )
