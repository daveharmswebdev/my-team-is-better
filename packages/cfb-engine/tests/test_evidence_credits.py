"""Coverage for `cfb_strength.evidence.credits.get_credits`: the static
attribution data (methodology citation + data source credit) relocated here
from `mcp_server/server.py`'s `credits_resource()` inline dict, per
ARCHITECTURE §4.5 / PRD §5.6 -- this is the single source of truth both
mcp_server and apps/api import from.
"""

from __future__ import annotations

import typing
from collections import Counter

from cfb_strength.contracts import Credits, DataSourceCredit, Method, MethodologyCredit
from cfb_strength.evidence.credits import get_credits
from cfb_strength.ratings import compute_ratings

# The engine's closed method vocabulary and the registry it is checked against
# (tests/test_contract_vocabularies.py already pins the two equal). The
# import-linter contracts govern src/, not tests/, so importing
# compute_ratings here is fine; evidence/credits.py itself must not.
METHODS: tuple[str, ...] = typing.get_args(Method)


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


def test_elo_credit_expects_the_methods_to_differ_without_playing_it_up() -> None:
    """Epic #147's neutrality rule, worded by the founder on #167: a split
    between the engines is neither a goal nor a defect. The credit used to
    call disagreement "the interesting part", which plays it up; it now says
    only that two methods should be expected to rank teams differently at
    times. Pinned because it is a product rule, not phrasing."""
    summary = _methodology_by_name("Elo").summary
    assert "interesting part" not in summary
    assert "disagree" not in summary
    assert "two different methods will naturally rank teams differently from time to time" in (
        summary
    )


def _data_source_by_name(name_fragment: str) -> DataSourceCredit:
    matches = [source for source in get_credits().data_sources if name_fragment in source.name]
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


# ---------------------------------------------------------------------------
# issue #144: every registered rating method is covered by exactly one credit
# ---------------------------------------------------------------------------
#
# `MethodologyCredit.methods` exists so the credits can be checked against the
# engine's method registry instead of trusting a hand-kept list. The invariant
# is on the union, because the mapping is not 1:1 by name (`elo` and
# `elo_career` share one Elo citation). Every comparison below is against a
# registry the engine actually uses at runtime -- `get_args(Method)` and
# `compute_ratings.METHODS` -- never against a second hand-written copy of the
# method list, which would only prove the test agrees with itself.


def _covered_methods() -> list[str]:
    return [method for credit in get_credits().methodologies for method in credit.methods]


def test_no_methodology_credit_has_an_empty_methods_tuple() -> None:
    """A credit covering nothing would be unreachable from every method and
    would have no `methods[0]` to serve as its downstream id."""
    for credit in get_credits().methodologies:
        assert credit.methods, f"{credit.name!r} covers no rating method"


def test_methodology_credits_cover_exactly_the_method_alias() -> None:
    """A method added to `contracts.Method` without a credit turns this red;
    so does a credit naming a method the alias lacks."""
    assert set(_covered_methods()) == set(METHODS), (
        "the methodology credits and contracts.Method disagree: every rating "
        "method needs a citation, and every citation must cover a real method"
    )


def test_methodology_credits_cover_exactly_the_registered_rating_methods() -> None:
    """The same invariant against the runtime registry, so a method registered
    in `compute_ratings.METHODS` (and therefore rateable from the CLI) can't be
    served without attribution."""
    assert set(_covered_methods()) == set(compute_ratings.METHODS), (
        "the methodology credits and compute_ratings.METHODS disagree: every "
        "registered rating method needs a citation"
    )


def test_every_method_named_by_a_credit_is_registered() -> None:
    """Per-credit direction of the invariant: a credit that names an
    unregistered method (a typo, or a method that was removed) fails on its
    own name, not just as a set difference."""
    for credit in get_credits().methodologies:
        for method in credit.methods:
            assert method in compute_ratings.METHODS, (
                f"{credit.name!r} names {method!r}, which is not a registered rating method"
            )


def test_each_method_appears_in_exactly_one_credit() -> None:
    counts = Counter(_covered_methods())
    duplicated = sorted(method for method, n in counts.items() if n > 1)
    assert not duplicated, f"methods covered by more than one credit: {duplicated}"
    for method in METHODS:
        assert counts[method] == 1, f"{method!r} is covered by {counts[method]} credits, not 1"


def test_keener_credit_covers_keener_only() -> None:
    assert _methodology_by_name("Keener's method").methods == ("keener",)


def test_elo_credit_covers_elo_then_elo_career() -> None:
    """Order is asserted: `methods[0]` is the credit's stable id downstream
    (the About page's `/about#elo` anchor), so `elo` must come first and the
    career variant, which shares the citation, second."""
    assert _methodology_by_name("Elo").methods == ("elo", "elo_career")


def test_credit_ids_are_unique_across_credits() -> None:
    """`methods[0]` values are the downstream ids (`keener`, `elo`); two
    credits sharing one would collide on the About page anchors."""
    ids = [credit.methods[0] for credit in get_credits().methodologies]
    assert len(set(ids)) == len(ids), f"duplicate credit ids: {ids}"
    assert ids == ["keener", "elo"]
