"""Coverage for `cfb_strength.evidence.credits.get_credits`: the static
attribution data (methodology citation + data source credit) relocated here
from `mcp_server/server.py`'s `credits_resource()` inline dict, per
ARCHITECTURE §4.5 / PRD §5.6 -- this is the single source of truth both
mcp_server and apps/api import from.
"""

from __future__ import annotations

from cfb_strength.contracts import Credits, DataSourceCredit, MethodologyCredit
from cfb_strength.evidence.credits import get_credits


def test_get_credits_returns_credits_instance() -> None:
    credits = get_credits()
    assert isinstance(credits, Credits)
    assert isinstance(credits.methodology, MethodologyCredit)
    assert isinstance(credits.data_sources, list)
    assert all(isinstance(source, DataSourceCredit) for source in credits.data_sources)


def test_methodology_credit_matches_exact_citation() -> None:
    methodology = get_credits().methodology
    assert methodology.name == "Keener's method"
    assert methodology.citation == (
        'J. P. Keener, "The Perron-Frobenius Theorem and the Ranking of '
        'Football Teams," SIAM Review, 35(1), 1993.'
    )
    assert methodology.url == "https://dl.acm.org/doi/10.1137/1035004"
    assert methodology.summary == (
        "A team's rating depends recursively on the strength of the teams "
        "it beat, whose strength depends on the strength of their "
        "opponents -- the same Perron-Frobenius eigenvector idea behind "
        "PageRank, applied to a win graph. This server computes stock "
        "Keener with win/loss as the dominant signal; margin of victory "
        "is not weighted."
    )


def _data_source_by_name(name_fragment: str) -> DataSourceCredit:
    matches = [
        source for source in get_credits().data_sources if name_fragment in source.name
    ]
    assert len(matches) == 1, f"expected exactly one data source matching {name_fragment!r}"
    return matches[0]


def test_data_sources_contains_exactly_two_entries() -> None:
    assert len(get_credits().data_sources) == 2


def test_cfbd_data_source_credit_matches_exact_text() -> None:
    data_source = _data_source_by_name("CollegeFootballData.com")
    assert data_source.name == "CollegeFootballData.com (CFBD)"
    assert data_source.url == "https://collegefootballdata.com"
    assert data_source.note == (
        "All game results are ingested from the CFBD API. This project "
        "performs no independent data collection and claims no "
        "ownership of the underlying game data."
    )


def test_nflverse_data_source_credit_matches_exact_text() -> None:
    data_source = _data_source_by_name("nflverse")
    assert data_source.name == "nflverse (Lee Sharpe's NFL schedule/game data)"
    assert data_source.url == "https://github.com/nflverse/nflverse-data"
    assert data_source.note == (
        "NFL game results are ingested from nflverse's static CSV release "
        "assets (the schedule data was originally compiled and maintained "
        "by Lee Sharpe before nflverse took over publishing it). This "
        "project performs no independent data collection and claims no "
        "ownership of the underlying game data."
    )


def test_get_credits_is_stable_across_calls() -> None:
    """Static data -- two calls should be equal (frozen dataclasses)."""
    assert get_credits() == get_credits()
