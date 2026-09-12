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
    assert isinstance(credits.methodologies, list)
    assert all(isinstance(m, MethodologyCredit) for m in credits.methodologies)
    assert isinstance(credits.data_sources, list)
    assert all(isinstance(source, DataSourceCredit) for source in credits.data_sources)


def _methodology_by_name(name: str) -> MethodologyCredit:
    matches = [m for m in get_credits().methodologies if m.name == name]
    assert len(matches) == 1, f"expected exactly one methodology named {name!r}"
    return matches[0]


def test_methodologies_are_keener_and_elo_in_that_order() -> None:
    """Order is asserted, not incidental: Keener is the golden-dataset-gated
    default and should read first on the About page, with Elo presented as
    the second opinion."""
    assert [m.name for m in get_credits().methodologies] == ["Keener's method", "Elo"]


def test_keener_methodology_credit_matches_exact_citation() -> None:
    methodology = _methodology_by_name("Keener's method")
    assert methodology.citation == (
        'J. P. Keener, "The Perron-Frobenius Theorem and the Ranking '
        'of Football Teams," SIAM Review, 35(1), 1993.'
    )
    assert methodology.url == "https://dl.acm.org/doi/10.1137/1035004"
    # The old summary ended "margin of victory is not weighted" as a flat
    # statement. That was true of the whole server when Keener was the only
    # method and is false now that Elo weights it, so the claim is scoped to
    # this method. Pinned because it is an accuracy fix, not phrasing.
    assert "this method" in methodology.summary
    assert "does not weight margin of victory" in methodology.summary


def test_elo_methodology_credits_arpad_elo_and_fivethirtyeight() -> None:
    """PRD 5.6 makes crediting a product requirement, so the specific names
    are pinned: the originator and the published formulation implemented."""
    methodology = _methodology_by_name("Elo")
    assert "Arpad E. Elo" in methodology.citation
    assert "FiveThirtyEight" in methodology.citation
    assert methodology.url == "https://github.com/fivethirtyeight/nfl-elo-game"
    # Three claims the summary must keep making, each load-bearing: that we
    # wrote it from the published formula rather than vendoring anything,
    # that this method DOES weight margin of victory (the opposite of
    # Keener's line above), and that the college constants are ours and
    # uncalibrated rather than 538's.
    assert "clean-room" in methodology.summary
    assert "blowouts do count" in methodology.summary
    assert "not yet calibrated" in methodology.summary


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
