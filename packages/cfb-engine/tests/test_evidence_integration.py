"""Integration coverage for `cfb_strength.evidence.proof` against real
fixture data: exception behavior (`AmbiguousTeamError`, `UnknownYearError`,
`SameTeamComparisonError`) and the head-to-head evidence shape
`build_comparison` produces for the 2005 Texas/USC case.

Uses `regression_conn` (a writable copy of tests/fixtures/cfb_regression.sqlite3)
with ratings freshly computed by the real `compute_and_store` pipeline --
never a canned `ratings` table, and never the live `data/cfb.sqlite3`.

The sections at the bottom (issue #95) run the same evidence surface under
every registered rating method, for both leagues (`nfl_regression_conn`
too), and prove that one database holding two methods' rows never mixes
them.
"""

from __future__ import annotations

import itertools
import shutil
import sqlite3
import typing
from collections import Counter
from dataclasses import dataclass

import pytest

from cfb_strength.contracts import (
    AmbiguousTeamError,
    CommonOpponent,
    CommonOpponentMeeting,
    ComparisonResult,
    ComparisonTeamSummary,
    Method,
    SameTeamComparisonError,
    Sport,
    TeamCase,
    UnknownTeamError,
    UnknownYearError,
)
from cfb_strength.db.connection import ensure_schema, get_conn
from cfb_strength.evidence import proof
from cfb_strength.evidence.proof import (
    build_comparison,
    build_team_case,
    list_available_years,
    resolve_team,
)
from cfb_strength.ratings.compute_ratings import compute_and_store
from tests.conftest import NFL_REGRESSION_FIXTURE_DB, REGRESSION_FIXTURE_DB


@pytest.fixture
def rated_conn(regression_conn: sqlite3.Connection) -> sqlite3.Connection:
    """regression_conn with 2005 ratings computed via the real pipeline."""
    compute_and_store(regression_conn, 2005, "keener")
    return regression_conn


def test_list_available_years_reflects_what_was_computed(rated_conn: sqlite3.Connection) -> None:
    years = list_available_years(rated_conn, "keener")
    assert years == [2005]


def test_unknown_year_raises_with_available_years_listed(rated_conn: sqlite3.Connection) -> None:
    with pytest.raises(UnknownYearError) as exc_info:
        resolve_team(rated_conn, 1999, "Texas", method="keener")
    assert exc_info.value.year == 1999
    assert exc_info.value.available_years == [2005]


def test_unknown_year_raises_for_build_team_case_too(rated_conn: sqlite3.Connection) -> None:
    with pytest.raises(UnknownYearError):
        build_team_case(rated_conn, 2099, "Texas", method="keener")


def test_ambiguous_team_query_raises_with_candidates(rated_conn: sqlite3.Connection) -> None:
    # "Texas" is an exact unique match, but a bare substring like "State"
    # matches many rated 2005 teams (Ohio State, Penn State, Florida State,
    # Michigan State, ...) and must be reported as ambiguous rather than
    # silently picking one.
    with pytest.raises(AmbiguousTeamError) as exc_info:
        resolve_team(rated_conn, 2005, "State", method="keener")
    assert exc_info.value.query == "State"
    assert len(exc_info.value.candidates) > 1


def test_same_team_comparison_raises(rated_conn: sqlite3.Connection) -> None:
    with pytest.raises(SameTeamComparisonError) as exc_info:
        build_comparison(rated_conn, 2005, "Texas", "Texas", method="keener")
    assert exc_info.value.team_name == "Texas"


def test_same_team_comparison_raises_even_via_different_query_strings(
    rated_conn: sqlite3.Connection,
) -> None:
    # Both queries resolve to the same team_id even though the strings
    # differ in case/whitespace -- the check is on resolved id, not on
    # literal query equality.
    with pytest.raises(SameTeamComparisonError):
        build_comparison(rated_conn, 2005, "texas", "  Texas  ", method="keener")


def test_resolve_team_exact_match_is_case_and_whitespace_insensitive(
    rated_conn: sqlite3.Connection,
) -> None:
    lower = resolve_team(rated_conn, 2005, "texas", method="keener")
    padded = resolve_team(rated_conn, 2005, "  Texas  ", method="keener")
    assert lower == padded


def test_build_team_case_returns_teamcase_dataclass(rated_conn: sqlite3.Connection) -> None:
    case = build_team_case(rated_conn, 2005, "Texas", method="keener")
    assert isinstance(case, TeamCase)
    assert case.team_name == "Texas"
    assert case.year == 2005
    assert case.method == "keener"


def test_build_comparison_texas_vs_usc_cites_head_to_head_rose_bowl(
    rated_conn: sqlite3.Connection,
) -> None:
    """The sufficiency rubric requires the MCP layer to cite the USC win
    unprompted for "greatest team of 2005" -- this checks the evidence layer
    actually produces that citation in build_comparison's head_to_head shape
    (get_champion/get_team_season go through build_team_case, checked
    separately in test_golden_dataset_regressions.py; this checks the other
    evidence entry point, build_comparison, gets the same real game right)."""
    comparison = build_comparison(rated_conn, 2005, "Texas", "USC", method="keener")
    assert isinstance(comparison, ComparisonResult)

    assert comparison.head_to_head.played is True
    meetings = comparison.head_to_head.meetings
    assert len(meetings) == 1
    meeting = meetings[0]
    assert meeting.home_team == "Texas"
    assert meeting.away_team == "USC"
    assert meeting.home_points == 41
    assert meeting.away_points == 38
    assert meeting.winner == "Texas"
    assert meeting.neutral_site is True

    assert "Texas" in comparison.verdict
    assert "USC" in comparison.verdict
    assert comparison.rating_diff > 0  # Texas rates strictly higher than USC


def test_build_comparison_team_summaries_and_common_opponents_are_typed(
    rated_conn: sqlite3.Connection,
) -> None:
    """Issue #21: `team_a`/`team_b`/`common_opponents` used to be untyped
    `dict[str, object]`, forcing `apps/web` to render a raw generic dump
    instead of a curated summary. This locks in that they are now real
    dataclasses with attribute access, not dicts."""
    comparison = build_comparison(rated_conn, 2005, "Texas", "USC", method="keener")

    assert isinstance(comparison.team_a, ComparisonTeamSummary)
    assert isinstance(comparison.team_b, ComparisonTeamSummary)
    assert comparison.team_a.team_name == "Texas"
    assert comparison.team_a.rank >= 1
    assert isinstance(comparison.team_a.rating, float)
    assert comparison.team_a.wins >= 0

    # Texas and USC both played common opponents in the 2005 season
    # (e.g. conference/OOC overlap) -- assert the shape, not specific teams.
    assert comparison.team_a.ties >= 0
    assert comparison.team_b.ties >= 0
    for opponent in comparison.common_opponents:
        assert isinstance(opponent, CommonOpponent)
        assert isinstance(opponent.opponent_name, str)
        # Issue #130: every meeting per side, never just the last one.
        assert isinstance(opponent.team_a_meetings, list)
        assert isinstance(opponent.team_b_meetings, list)
        assert opponent.team_a_meetings and opponent.team_b_meetings
        for meeting in opponent.team_a_meetings + opponent.team_b_meetings:
            assert isinstance(meeting, CommonOpponentMeeting)
            assert meeting.result in ("W", "L", "T")
            assert isinstance(meeting.team_score, int)
            assert isinstance(meeting.opponent_score, int)
            assert meeting.week is None or isinstance(meeting.week, int)
            assert isinstance(meeting.season_type, str)


def test_build_team_case_record_matches_its_listed_games(
    rated_conn: sqlite3.Connection,
) -> None:
    """Issue #83: `TeamCase` reads wins/losses/ties from the `ratings` row,
    and `games` lists every completed game, ties included -- so the record
    and the receipts can never disagree about how many games were played.
    Checked for every team rated in 2005, not just Texas."""
    teams = [
        r["school"]
        for r in rated_conn.execute(
            "SELECT t.school FROM ratings r JOIN teams t ON t.id = r.team_id "
            "WHERE r.year = 2005 AND r.method = 'keener' AND r.sport = 'cfb'"
        ).fetchall()
    ]
    assert teams
    for school in teams:
        case = build_team_case(rated_conn, 2005, school, method="keener")
        assert len(case.games) == case.wins + case.losses + case.ties, school
        assert case.ties == sum(1 for g in case.games if g.result == "T"), school


def test_build_team_case_rating_breakdown_has_entries_for_real_opponents(
    rated_conn: sqlite3.Connection,
) -> None:
    """Issue #31: TeamCase.rating_breakdown surfaces the per-opponent credit
    decomposition computed and persisted by compute_and_store."""
    case = build_team_case(rated_conn, 2005, "Texas", method="keener")

    assert case.rating_breakdown.entries, "Texas played games in 2005; expected breakdown entries"

    schedule_opponent_ids = {o.opponent_team_id for o in case.games}
    schedule_names_by_id = {o.opponent_team_id: o.opponent_name for o in case.games}
    for entry in case.rating_breakdown.entries:
        assert entry.opponent_team_id in schedule_opponent_ids
        # Issue #31 follow-up: OpponentCredit.opponent_name must be resolved
        # to the opponent's real school name (same teams-table join
        # _opponent_result already does for OpponentResult), not left at its
        # contracts.py default of "".
        assert entry.opponent_name
        assert entry.opponent_name == schedule_names_by_id[entry.opponent_team_id]


def test_build_team_case_rating_breakdown_reconstructs_rating(
    rated_conn: sqlite3.Connection,
) -> None:
    """The decomposition is exact by construction upstream: entries'
    contributions plus the residual must sum back to the team's rating."""
    case = build_team_case(rated_conn, 2005, "Texas", method="keener")

    total = sum(e.contribution for e in case.rating_breakdown.entries)
    total += case.rating_breakdown.residual_contribution

    assert total == pytest.approx(case.rating, abs=1e-6)


def test_build_comparison_team_summaries_have_rating_breakdowns(
    rated_conn: sqlite3.Connection,
) -> None:
    """build_comparison's ComparisonTeamSummary (via _case_summary) must
    carry the same rating_breakdown as build_team_case, not just
    build_team_case's own return value."""
    comparison = build_comparison(rated_conn, 2005, "Texas", "USC", method="keener")

    for summary in (comparison.team_a, comparison.team_b):
        assert summary.rating_breakdown.entries
        total = sum(e.contribution for e in summary.rating_breakdown.entries)
        total += summary.rating_breakdown.residual_contribution
        assert total == pytest.approx(summary.rating, abs=1e-6)


def test_build_team_case_rating_breakdown_entries_have_explanations(
    rated_conn: sqlite3.Connection,
) -> None:
    """Issue #37: OpponentCredit.explanation is populated from the real
    per-game scores, not left at contracts.py's default of ''."""
    case = build_team_case(rated_conn, 2005, "Texas", method="keener")

    assert case.rating_breakdown.entries, "Texas played games in 2005; expected breakdown entries"
    for entry in case.rating_breakdown.entries:
        assert entry.explanation, (
            f"expected a non-empty explanation for opponent {entry.opponent_name!r}"
        )

    # Pick one opponent Texas actually played once, and check the
    # explanation cites that game's real score as a substring -- without
    # hardcoding the exact sentence, since this delegation doesn't control
    # the golden-fixture wording, only the template.
    single_game_opponent = next(e for e in case.rating_breakdown.entries if e.games_played == 1)
    matching_game = next(
        g for g in case.games if g.opponent_team_id == single_game_opponent.opponent_team_id
    )
    expected_score = f"{matching_game.team_score}-{matching_game.opponent_score}"
    assert expected_score in single_game_opponent.explanation


def test_rating_breakdown_degrades_gracefully_with_no_rows(
    rated_conn: sqlite3.Connection,
) -> None:
    """A team rated but with no rating_breakdowns rows (e.g. a fixture db
    predating this table, or an id with no persisted breakdown) should
    produce an empty RatingBreakdown rather than raising."""
    from cfb_strength.evidence.proof import _rating_breakdown

    breakdown = _rating_breakdown(rated_conn, 2005, "keener", team_id=-1, games=[], sport="cfb")
    assert breakdown.entries == []
    assert breakdown.residual_contribution == 0.0


# ---------------------------------------------------------------------------
# issue #100 -- zero matches against the real 2005 rated set
# ---------------------------------------------------------------------------


def test_unrated_team_raises_unknown_team_error_not_ambiguous(
    rated_conn: sqlite3.Connection,
) -> None:
    """ "Abilene Christian" is a real school that has no 2005 keener rating in
    this fixture -- a zero-match query, which used to come back as
    AmbiguousTeamError with an empty candidate list."""
    with pytest.raises(UnknownTeamError) as exc_info:
        resolve_team(rated_conn, 2005, "Abilene Christian", method="keener")
    assert exc_info.value.query == "Abilene Christian"
    assert exc_info.value.year == 2005
    assert exc_info.value.sport == "cfb"


def test_unknown_team_error_carries_no_suggestion_list(
    rated_conn: sqlite3.Connection,
) -> None:
    """contracts.py: UnknownTeamError deliberately carries only query/year/
    sport, against the real 2005 rated set. The earlier near-miss pass could
    not work here -- "Abilene Christian" has no plausible 2005 counterpart,
    and the closest names by ratio ("Michigan", "Minnesota", "Ole Miss") are
    pure noise that would read as a broken product.
    """
    with pytest.raises(UnknownTeamError) as exc_info:
        resolve_team(rated_conn, 2005, "Abilene Christian", method="keener")
    error = exc_info.value
    assert not hasattr(error, "suggestions")
    assert error.query == "Abilene Christian"
    assert error.year == 2005
    assert error.sport == "cfb"


def test_unknown_team_error_for_a_wholly_invented_name(
    rated_conn: sqlite3.Connection,
) -> None:
    """A name resembling nothing in the rated set is the same error, with the
    same shape -- no crash, no AmbiguousTeamError, no suggestion list."""
    with pytest.raises(UnknownTeamError) as exc_info:
        resolve_team(rated_conn, 2005, "Zzyzx Polytechnic", method="keener")
    error = exc_info.value
    assert not hasattr(error, "suggestions")
    assert error.query == "Zzyzx Polytechnic"
    assert error.year == 2005
    assert error.sport == "cfb"


def test_unknown_team_propagates_through_build_team_case(
    rated_conn: sqlite3.Connection,
) -> None:
    with pytest.raises(UnknownTeamError):
        build_team_case(rated_conn, 2005, "Zzyzx Polytechnic", method="keener")


def test_ambiguous_team_error_never_carries_empty_candidates(
    rated_conn: sqlite3.Connection,
) -> None:
    """Invariant from contracts.py, swept against the real rated set:
    AmbiguousTeamError means "too many", never "none"."""
    queries = [
        "Texas",
        "State",
        "Southern",
        "Tech",
        "A&M",
        "Abilene Christian",
        "Zzyzx Polytechnic",
    ]
    raised_at_least_one = False
    for query in queries:
        try:
            resolve_team(rated_conn, 2005, query, method="keener")
        except AmbiguousTeamError as e:
            raised_at_least_one = True
            assert e.candidates, f"empty candidates for {query!r}"
        except UnknownTeamError:
            pass
    # Without this sentinel the sweep silently degrades to a no-op if the
    # fixture is ever regenerated thinner (mirrors the colocated unit twin).
    assert raised_at_least_one, "expected at least one genuinely ambiguous query in the sweep"


# ---------------------------------------------------------------------------
# issue #123 -- the fuzzy stage never silently turns an unknown name into a
# different real team
# ---------------------------------------------------------------------------


def test_invented_name_with_one_weak_lookalike_asks_instead_of_resolving(
    rated_conn: sqlite3.Connection,
) -> None:
    """ "Zzyzx Tech" scores exactly 0.6 against "Texas Tech" and nothing else
    reaches 0.6. Before #123 that lone weak match resolved silently; now it
    is a "did you mean Texas Tech?" -- a one-candidate AmbiguousTeamError."""
    with pytest.raises(AmbiguousTeamError) as exc_info:
        resolve_team(rated_conn, 2005, "Zzyzx Tech", method="keener")
    assert exc_info.value.query == "Zzyzx Tech"
    assert exc_info.value.candidates == ["Texas Tech"]


@pytest.mark.parametrize("query", ["Alabma", "alabma", "ALABMA"])
def test_a_real_typo_resolves_in_any_case(rated_conn: sqlite3.Connection, query: str) -> None:
    """The fuzzy score includes the lowercased ratio: "alabma" scores 0.9231
    against "alabama" whatever the caller's casing."""
    alabama = resolve_team(rated_conn, 2005, "Alabama", method="keener")
    assert resolve_team(rated_conn, 2005, query, method="keener") == alabama


def test_invented_name_with_several_weak_lookalikes_asks(
    rated_conn: sqlite3.Connection,
) -> None:
    """ "Qwerty State" scores 0.727 against "kent state" and lower against
    several other "... State" schools: nothing reaches 0.8, so it asks."""
    with pytest.raises(AmbiguousTeamError) as exc_info:
        resolve_team(rated_conn, 2005, "Qwerty State", method="keener")
    assert "Kent State" in exc_info.value.candidates
    assert len(exc_info.value.candidates) > 1


def test_invented_name_with_no_lookalike_is_unknown(rated_conn: sqlite3.Connection) -> None:
    with pytest.raises(UnknownTeamError):
        resolve_team(rated_conn, 2005, "Nonexistent U", method="keener")


def test_fuzzy_resolve_cutoff_is_0_8() -> None:
    assert proof.FUZZY_RESOLVE_CUTOFF == 0.8
    assert proof.FUZZY_MATCH_CUTOFF == 0.6


def test_lone_fuzzy_match_just_under_the_resolve_cutoff_asks(
    rated_conn: sqlite3.Connection,
) -> None:
    """ "Clrdo" scores 0.7692 against "colorado" and nothing else in the 2005
    rated set reaches 0.6: a single candidate under 0.8 asks."""
    with pytest.raises(AmbiguousTeamError) as exc_info:
        resolve_team(rated_conn, 2005, "Clrdo", method="keener")
    assert exc_info.value.candidates == ["Colorado"]


def test_lone_fuzzy_match_at_the_resolve_cutoff_resolves(
    rated_conn: sqlite3.Connection,
) -> None:
    """ "Wscnsn" scores exactly 0.8 against "wisconsin" and nothing else
    reaches 0.6: the bar is inclusive, so it resolves."""
    wisconsin = resolve_team(rated_conn, 2005, "Wisconsin", method="keener")
    assert resolve_team(rated_conn, 2005, "Wscnsn", method="keener") == wisconsin


def test_strong_fuzzy_match_resolves_despite_weaker_candidates(
    rated_conn: sqlite3.Connection,
) -> None:
    """ "Mchgan" scores 0.857 against "michigan" and 0.6 against "michigan
    state": one name at >= 0.8 and no other one there still resolves."""
    michigan = resolve_team(rated_conn, 2005, "Michigan", method="keener")
    assert resolve_team(rated_conn, 2005, "Mchgan", method="keener") == michigan


def test_known_but_unrated_school_is_unknown_not_a_lookalike(
    regression_conn: sqlite3.Connection,
) -> None:
    """ "North Dakota State" is in `teams` but has no 2019 keener rating in
    the regression fixture. Before #123 the fuzzy stage resolved it to
    Colorado State; an exact name match on an unrated team of this sport is
    UnknownTeamError, before any looser stage runs."""
    compute_and_store(regression_conn, 2019, "keener")
    with pytest.raises(UnknownTeamError) as exc_info:
        resolve_team(regression_conn, 2019, "North Dakota State", method="keener")
    assert exc_info.value.query == "North Dakota State"
    assert exc_info.value.year == 2019
    assert exc_info.value.sport == "cfb"


def test_known_school_whose_rating_row_is_missing_is_unknown(
    regression_conn: sqlite3.Connection,
) -> None:
    """With USC's 2004 keener row gone, "USC" (and "usc") used to fuzzy-match
    UCF. A known school without a rating that season is UnknownTeamError."""
    compute_and_store(regression_conn, 2004, "keener")
    usc_id = resolve_team(regression_conn, 2004, "USC", method="keener")
    regression_conn.execute(
        "DELETE FROM rating_breakdowns WHERE year = 2004 AND method = 'keener' "
        "AND sport = 'cfb' AND team_id = ?",
        (usc_id,),
    )
    regression_conn.execute(
        "DELETE FROM ratings WHERE year = 2004 AND method = 'keener' "
        "AND sport = 'cfb' AND team_id = ?",
        (usc_id,),
    )
    for query in ("USC", "usc", "  USC "):
        with pytest.raises(UnknownTeamError):
            resolve_team(regression_conn, 2004, query, method="keener")


def test_fuzzy_runner_up_cutoff_is_0_75() -> None:
    assert proof.FUZZY_RUNNER_UP_CUTOFF == 0.75


def test_typo_that_scores_well_only_case_sensitively_still_resolves(
    rated_conn: sqlite3.Connection,
) -> None:
    """ "Maimi" scores 0.8 against "Miami" case-sensitively but only 0.6 once
    both are lowercased (difflib's greedy longest block differs on
    "maimi"/"miami"). A name scores the better of the two, so the typo
    resolves; lowercase-only scoring made it UnknownTeamError (#123 round 2)."""
    miami = resolve_team(rated_conn, 2005, "Miami", method="keener")
    assert resolve_team(rated_conn, 2005, "Maimi", method="keener") == miami


def test_all_lowercase_typo_that_scores_weakly_asks(rated_conn: sqlite3.Connection) -> None:
    """ "maimi" scores 0.6 against "Miami" as typed (0.4 lowercased) and
    nothing else reaches 0.6: a one-candidate "did you mean Miami?", where
    lowercase-only scoring made it UnknownTeamError."""
    with pytest.raises(AmbiguousTeamError) as exc_info:
        resolve_team(rated_conn, 2005, "maimi", method="keener")
    assert exc_info.value.candidates == ["Miami"]


def test_strong_top_match_with_a_close_runner_up_asks(
    regression_conn: sqlite3.Connection,
) -> None:
    """ "TUSA" (2013) scores 0.889 against Tulsa but 0.75 against UTSA: a
    runner-up at >= FUZZY_RUNNER_UP_CUTOFF means the top name isn't a safe
    guess, so it asks with both listed."""
    compute_and_store(regression_conn, 2013, "keener")
    with pytest.raises(AmbiguousTeamError) as exc_info:
        resolve_team(regression_conn, 2013, "TUSA", method="keener")
    assert "Tulsa" in exc_info.value.candidates
    assert "UTSA" in exc_info.value.candidates
    assert exc_info.value.candidates == sorted(exc_info.value.candidates)


def test_runner_up_at_the_cutoff_asks(rated_conn: sqlite3.Connection) -> None:
    """ "Olkahoma State" scores 0.9286 against Oklahoma State and exactly
    0.75 against Ohio State: the runner-up bar is inclusive, so it asks."""
    with pytest.raises(AmbiguousTeamError) as exc_info:
        resolve_team(rated_conn, 2005, "Olkahoma State", method="keener")
    assert "Oklahoma State" in exc_info.value.candidates
    assert "Ohio State" in exc_info.value.candidates


def test_runner_up_just_under_the_cutoff_resolves(rated_conn: sqlite3.Connection) -> None:
    """ "Oklaoma State" scores 0.963 against Oklahoma State and 0.7407
    against Colorado State, the best of the rest: it resolves."""
    oklahoma_state = resolve_team(rated_conn, 2005, "Oklahoma State", method="keener")
    assert resolve_team(rated_conn, 2005, "Oklaoma State", method="keener") == oklahoma_state


# ---------------------------------------------------------------------------
# issue #393 -- a common abbreviation of one school never silently resolves to
# a different real school (measured on base: every "<X> St." below resolved
# to <X>, and "Miami OH" to Miami)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "intended"),
    [
        ("Ohio St.", "Ohio State"),
        ("Ohio St", "Ohio State"),
        ("Michigan St.", "Michigan State"),
        ("Kansas St.", "Kansas State"),
        ("Kansas St", "Kansas State"),
        ("Florida St.", "Florida State"),
        ("Oklahoma St.", "Oklahoma State"),
        ("Iowa St.", "Iowa State"),
        ("Washington St.", "Washington State"),
        ("Arizona St.", "Arizona State"),
        ("Miami OH", "Miami (OH)"),
        ("Miami(OH)", "Miami (OH)"),
        ("OhioState", "Ohio State"),
    ],
)
@pytest.mark.parametrize("year", [2003, 2005])
def test_abbreviation_resolves_to_the_intended_school(
    regression_conn: sqlite3.Connection, year: int, query: str, intended: str
) -> None:
    compute_and_store(regression_conn, year, "keener")
    expected = resolve_team(regression_conn, year, intended, method="keener")
    assert resolve_team(regression_conn, year, query, method="keener") == expected


def test_texas_st_is_texas_state_never_texas(regression_conn: sqlite3.Connection) -> None:
    """Texas State is rated in 2019 (FBS) but only a known, unrated `teams`
    row in 2005 (FCS). "Texas St." is Texas State, or UnknownTeamError, and
    never Texas."""
    compute_and_store(regression_conn, 2019, "keener")
    texas_state = resolve_team(regression_conn, 2019, "Texas State", method="keener")
    assert resolve_team(regression_conn, 2019, "Texas St.", method="keener") == texas_state
    compute_and_store(regression_conn, 2005, "keener")
    with pytest.raises(UnknownTeamError):
        resolve_team(regression_conn, 2005, "Texas St.", method="keener")


@pytest.mark.parametrize(
    ("year", "query", "wrong"),
    [
        (2005, "Wichita St.", "Michigan State"),
        (2005, "West St.", "Kent State"),
        (2005, "East St.", "Kent State"),
        (2005, "New St.", "NC State"),
        (2005, "SE St.", "Boise State"),
        (2019, "Wichita St.", "Michigan State"),
    ],
)
def test_state_abbreviation_never_fuzzy_resolves_to_another_state_school(
    regression_conn: sqlite3.Connection, year: int, query: str, wrong: str
) -> None:
    """#393 round 2, measured by the reviewer: fuzzy-matching the expanded
    "<X> State" resolved each of these to a different real school."""
    compute_and_store(regression_conn, year, "keener")
    wrong_id = resolve_team(regression_conn, year, wrong, method="keener")
    try:
        team_id = resolve_team(regression_conn, year, query, method="keener")
    except (AmbiguousTeamError, UnknownTeamError):
        return
    assert team_id != wrong_id, f"{query!r} resolved silently to {wrong!r}"
    pytest.fail(f"{query!r} resolved silently to team_id {team_id}")


def test_mich_st_asks_with_only_michigan_state(rated_conn: sqlite3.Connection) -> None:
    with pytest.raises(AmbiguousTeamError) as exc_info:
        resolve_team(rated_conn, 2005, "Mich St.", method="keener")
    assert exc_info.value.candidates == ["Michigan State"]


def test_pittsburgh_st_is_not_the_steelers(nfl_regression_conn: sqlite3.Connection) -> None:
    compute_and_store(nfl_regression_conn, 2022, "keener", sport="nfl")
    with pytest.raises(AmbiguousTeamError) as exc_info:
        resolve_team(nfl_regression_conn, 2022, "Pittsburgh St.", method="keener", sport="nfl")
    assert exc_info.value.candidates == ["Pittsburgh Steelers"]


def test_miami_with_a_trailing_word_asks_instead_of_answering_miami(
    rated_conn: sqlite3.Connection,
) -> None:
    """ "Miami FL" contains the rated "Miami" with more than punctuation
    around it: a guess, so it asks with Miami listed."""
    with pytest.raises(AmbiguousTeamError) as exc_info:
        resolve_team(rated_conn, 2005, "Miami FL", method="keener")
    assert "Miami" in exc_info.value.candidates


# ---------------------------------------------------------------------------
# issue #398 -- the fuzzy stage never answers with a different school because
# the query and the name share a common word (" State", "St", a city prefix).
# Every wrong case below was measured resolving silently on 54236e5.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def rated_398_conns(
    tmp_path_factory: pytest.TempPathFactory,
) -> typing.Iterator[dict[str, sqlite3.Connection]]:
    """Copies of both regression fixtures, rated for CFB 2005/2019 and NFL
    2022 by the real pipeline, shared by this section's cases (each case
    only reads, so one rating run per module is enough)."""
    out = tmp_path_factory.mktemp("issue_398")
    conns: dict[str, sqlite3.Connection] = {}
    for sport, src in (("cfb", REGRESSION_FIXTURE_DB), ("nfl", NFL_REGRESSION_FIXTURE_DB)):
        dest = out / src.name
        shutil.copy(src, dest)
        conns[sport] = get_conn(dest)
    compute_and_store(conns["cfb"], 2005, "keener")
    compute_and_store(conns["cfb"], 2019, "keener")
    compute_and_store(conns["nfl"], 2022, "keener", sport="nfl")
    yield conns
    for c in conns.values():
        c.close()


@pytest.mark.parametrize(
    ("sport", "year", "query", "wrong"),
    [
        ("cfb", 2005, "Wichita State", "Michigan State"),
        ("cfb", 2005, "West State", "Kent State"),
        ("cfb", 2005, "New State", "NC State"),
        ("cfb", 2005, "SE State", "Boise State"),
        ("cfb", 2005, "The State", "Utah State"),
        ("cfb", 2005, "Northeastern St", "Northwestern"),
        ("cfb", 2005, "Southern St", "Southern Miss"),
        ("cfb", 2005, "Southern St.", "Southern Miss"),
        ("cfb", 2019, "Wichita State", "Michigan State"),
        ("cfb", 2019, "Northeastern St", "Northwestern"),
        ("cfb", 2019, "Southern St", "Southern Miss"),
        ("cfb", 2019, "Southern St.", "Southern Miss"),
        ("nfl", 2022, "Pittsburgh St", "Pittsburgh Steelers"),
        ("nfl", 2022, "Pittsburgh State", "Pittsburgh Steelers"),
        ("nfl", 2022, "Indianapolis St", "Indianapolis Colts"),
        ("nfl", 2022, "Indianapolis St.", "Indianapolis Colts"),
        ("nfl", 2022, "Jacksonville St", "Jacksonville Jaguars"),
    ],
)
def test_a_shared_common_word_never_fuzzy_resolves_to_another_school(
    rated_398_conns: dict[str, sqlite3.Connection],
    sport: Sport,
    year: int,
    query: str,
    wrong: str,
) -> None:
    """None of these queries names a rated team; each scored >= 0.8 against
    a different school only through the word they share ("State", or the
    city of an NFL "City Nickname"). It asks or is unknown, never an
    answer."""
    conn = rated_398_conns[sport]
    try:
        team_id = resolve_team(conn, year, query, method="keener", sport=sport)
    except (AmbiguousTeamError, UnknownTeamError):
        return
    name = conn.execute("SELECT school FROM teams WHERE id = ?", (team_id,)).fetchone()[0]
    pytest.fail(f"{query!r} resolved silently to {name!r} (measured on base: {wrong!r})")


@pytest.mark.parametrize(
    ("sport", "year", "query", "intended"),
    [
        ("cfb", 2005, "Alabma", "Alabama"),
        ("cfb", 2005, "Michgan State", "Michigan State"),
        ("cfb", 2005, "Oklaoma State", "Oklahoma State"),
        ("cfb", 2005, "Kent Stae", "Kent State"),
        ("cfb", 2005, "Kemt State", "Kent State"),
        ("cfb", 2005, "Bal State", "Ball State"),
        ("cfb", 2005, "Penn Sate", "Penn State"),
        ("cfb", 2005, "Boise Stat", "Boise State"),
        ("cfb", 2005, "Mississippi Stte", "Mississippi State"),
        ("cfb", 2005, "Bostn College", "Boston College"),
        ("cfb", 2005, "Boston Colege", "Boston College"),
        ("cfb", 2005, "Georga Tech", "Georgia Tech"),
        ("cfb", 2005, "Wscnsn", "Wisconsin"),
        ("cfb", 2019, "Michgan State", "Michigan State"),
        ("nfl", 2022, "Pittsburgh Steelrs", "Pittsburgh Steelers"),
        ("nfl", 2022, "Pittsburg Steelers", "Pittsburgh Steelers"),
        ("nfl", 2022, "Indianaplis Colts", "Indianapolis Colts"),
        ("nfl", 2022, "Jacksonvile Jaguars", "Jacksonville Jaguars"),
        ("nfl", 2022, "Kansas Cty Chiefs", "Kansas City Chiefs"),
        ("nfl", 2022, "Green Bay Packrs", "Green Bay Packers"),
        ("nfl", 2022, "New York Jest", "New York Jets"),
        ("nfl", 2022, "Dallas Cowbys", "Dallas Cowboys"),
    ],
)
def test_real_typos_still_fuzzy_resolve_after_398(
    rated_398_conns: dict[str, sqlite3.Connection],
    sport: Sport,
    year: int,
    query: str,
    intended: str,
) -> None:
    """Each of these resolved to the intended team on base (54236e5); the
    #398 guard must not turn them into questions."""
    conn = rated_398_conns[sport]
    expected = resolve_team(conn, year, intended, method="keener", sport=sport)
    assert resolve_team(conn, year, query, method="keener", sport=sport) == expected


# ---------------------------------------------------------------------------
# issue #403 -- a short query inside a longer name is not that name. A lone
# substring hit resolved "Tula" to Tulane (Tulsa meant) and "SU" to LSU (SMU
# meant). Every case below was measured resolving to `wrong` on cef4ade, in
# #398's one-edit typo sweep of every rated name.
# ---------------------------------------------------------------------------

_SHORT_TYPOS_403 = (
    ("Tula", "Tulane", "Tulsa"),
    ("ULA", "Tulane", "UCLA"),
    ("UF", "Buffalo", "UCF"),
    ("AUB", "Auburn", "UAB"),
    ("UB", "Auburn", "UAB"),
    ("SU", "LSU", "SMU"),
    ("Ary", "Maryland", "Army"),
    ("Due", "Purdue", "Duke"),
    ("Rce", "Air Force", "Rice"),
)


@pytest.mark.parametrize(
    ("sport", "year", "query", "wrong", "intended"),
    [("cfb", year, *case) for year in (2005, 2019) for case in _SHORT_TYPOS_403]
    + [("cfb", 2005, "TUC", "Kentucky", "TCU")],
)
def test_a_short_typo_inside_a_longer_name_never_resolves_to_it(
    rated_398_conns: dict[str, sqlite3.Connection],
    sport: Sport,
    year: int,
    query: str,
    wrong: str,
    intended: str,
) -> None:
    """The query is a one-edit typo of `intended` that also sits inside
    `wrong`'s name. It resolves to the intended school or asks with it
    offered; it never answers `wrong`."""
    conn = rated_398_conns[sport]
    expected = resolve_team(conn, year, intended, method="keener", sport=sport)
    try:
        team_id = resolve_team(conn, year, query, method="keener", sport=sport)
    except AmbiguousTeamError as e:
        assert intended in e.candidates, f"{query!r} asks without {intended!r}: {e.candidates}"
        return
    name = conn.execute("SELECT school FROM teams WHERE id = ?", (team_id,)).fetchone()[0]
    assert team_id == expected, f"{query!r} resolved silently to {name!r} (base: {wrong!r})"


@pytest.mark.parametrize(
    ("sport", "year", "query", "intended"),
    [
        ("cfb", 2019, "Michigan St", "Michigan State"),
        ("cfb", 2019, "Texas A&M", "Texas A&M"),
        ("cfb", 2019, "Texas AM", "Texas A&M"),
        ("cfb", 2019, "A&M", "Texas A&M"),
        ("cfb", 2019, "Penn", "Penn State"),
        ("cfb", 2019, "Boise", "Boise State"),
        ("cfb", 2019, "Notre", "Notre Dame"),
        ("cfb", 2019, "Wake", "Wake Forest"),
        ("cfb", 2019, "Coastal", "Coastal Carolina"),
        ("cfb", 2019, "Bowling", "Bowling Green"),
        ("cfb", 2019, "Western Mich", "Western Michigan"),
        ("cfb", 2019, "Minn", "Minnesota"),
        ("cfb", 2019, "Wisc", "Wisconsin"),
        ("cfb", 2019, "Neb", "Nebraska"),
        ("cfb", 2019, "Pitt", "Pittsburgh"),
        ("cfb", 2005, "Alab", "Alabama"),
        ("nfl", 2022, "Steelers", "Pittsburgh Steelers"),
        ("nfl", 2022, "Colts", "Indianapolis Colts"),
        ("nfl", 2022, "Packers", "Green Bay Packers"),
        ("nfl", 2022, "49ers", "San Francisco 49ers"),
        ("nfl", 2022, "Pittsburgh", "Pittsburgh Steelers"),
        ("nfl", 2022, "Green Bay", "Green Bay Packers"),
        ("nfl", 2022, "Vegas", "Las Vegas Raiders"),
        ("nfl", 2022, "Tampa", "Tampa Bay Buccaneers"),
        ("nfl", 2022, "Kansas City", "Kansas City Chiefs"),
    ],
)
def test_word_aligned_partials_still_resolve_after_403(
    rated_398_conns: dict[str, sqlite3.Connection],
    sport: Sport,
    year: int,
    query: str,
    intended: str,
) -> None:
    """Each resolved to `intended` on cef4ade: the query starts on a word of
    exactly one rated name and is no one-edit typo of another, so #403 keeps
    it an answer."""
    conn = rated_398_conns[sport]
    expected = resolve_team(conn, year, intended, method="keener", sport=sport)
    assert resolve_team(conn, year, query, method="keener", sport=sport) == expected


# ---------------------------------------------------------------------------
# issue #95 -- Keener's verdict text, pinned exactly against real ratings
# ---------------------------------------------------------------------------


def test_keener_texas_usc_verdict_text_is_byte_identical(
    rated_conn: sqlite3.Connection,
) -> None:
    """Pinned from the pre-#95 output. Giving Elo its own precision must not
    move a single byte of Keener's verdict (both ratings sit well clear of a
    sixth-decimal rounding boundary, so this is stable, not lucky)."""
    comparison = build_comparison(rated_conn, 2005, "Texas", "USC", method="keener")
    assert comparison.verdict == (
        "Texas beat USC head-to-head 41-38 (Texas vs USC, week 1). "
        "Texas rates higher overall (0.005044 vs 0.004736, rank 1 vs 2)."
    )


# ---------------------------------------------------------------------------
# issue #95 -- the whole evidence surface, under every method, in both leagues
#
# Before #95 nothing in this package called the evidence layer with a method
# other than keener. Its correctness under Elo rested on a code comment in
# compute_ratings._store_breakdowns. Everything below computes real ratings
# with the real pipeline, for every (method, league) pair.
# ---------------------------------------------------------------------------

METHODS: tuple[str, ...] = typing.get_args(Method)
SPORTS: tuple[str, ...] = typing.get_args(Sport)


@dataclass(frozen=True)
class LeagueSample:
    conn_fixture: str  # the conftest fixture holding this league's games
    year: int
    team: str
    opponent: str  # met `team` in `year`, so there is a head-to-head to report


LEAGUE_SAMPLES: dict[str, LeagueSample] = {
    "cfb": LeagueSample("regression_conn", 2005, "Texas", "USC"),
    # Two meetings, one of them a 26-26 tie: the harder head-to-head shape.
    "nfl": LeagueSample("nfl_regression_conn", 2013, "Green Bay Packers", "Minnesota Vikings"),
}

# Per-method expectations, written out by hand ON PURPOSE rather than read
# from proof.py: a test that took its expected precision from the table under
# test could never notice that table being wrong. Each table is keyed exactly
# by `Method` (checked below), so a newly registered method must state all
# three before any parametrized test here can pass.
RATING_SCALES: dict[str, tuple[float, float]] = {
    # Open intervals, deliberately loose. A band doesn't check that a rating is
    # plausible for its method, only which scale it is on, so a keener read
    # that picked up an Elo row (or the reverse) lands outside its band. That
    # only works if bands on different scales don't overlap. Methods on one
    # scale share one band. test_rating_bands_are_identical_or_disjoint checks
    # both.
    #
    # A sum-to-1 eigenvector: every rating is a small positive fraction.
    "keener": (0.0, 1.0),
    # Seeded at 1500. The fixtures' real spread is about 1130-1990 (CFB) and
    # 1290-1770 (NFL).
    "elo": (500.0, 2500.0),
    "elo_career": (500.0, 2500.0),
}
HAS_BREAKDOWN: dict[str, bool] = {"keener": True, "elo": False, "elo_career": False}
VERDICT_DECIMALS: dict[str, int] = {"keener": 6, "elo": 1, "elo_career": 1}


def test_per_method_expectations_cover_exactly_the_registered_vocabularies() -> None:
    for table in (RATING_SCALES, HAS_BREAKDOWN, VERDICT_DECIMALS):
        assert tuple(table) == METHODS
    assert tuple(LEAGUE_SAMPLES) == SPORTS
    # The decoy method in `rated_league` needs a second registered method.
    assert len(METHODS) > 1


def test_rating_bands_are_identical_or_disjoint() -> None:
    """Loosening a band until it overlaps another scale's band turns this red.
    Without it, a band could grow wide enough to accept the wrong scale and
    every test using it would still pass."""
    assert len(set(RATING_SCALES.values())) > 1, "a single shared band can't separate scales"
    for a, b in itertools.combinations(METHODS, 2):
        (low_a, high_a), (low_b, high_b) = RATING_SCALES[a], RATING_SCALES[b]
        assert (low_a, high_a) == (low_b, high_b) or high_a <= low_b or high_b <= low_a, (a, b)


def _on_scale(method: str, rating: float) -> bool:
    low, high = RATING_SCALES[method]
    return low < rating < high


def _stored_ratings_by_team(
    conn: sqlite3.Connection, year: int, method: str, sport: str
) -> dict[int, tuple[float, int]]:
    """team_id -> (rating, rank) for every team `method` rated, straight from SQL."""
    return {
        int(row["team_id"]): (float(row["rating"]), int(row["rank"]))
        for row in conn.execute(
            "SELECT team_id, rating, rank FROM ratings WHERE year = ? AND method = ? AND sport = ?",
            (year, method, sport),
        )
    }


def _stored_rating(
    conn: sqlite3.Connection, year: int, method: str, sport: str, school: str
) -> sqlite3.Row:
    """The ratings row for one team, read straight from SQL -- the ground
    truth the evidence layer's own queries are checked against."""
    row = conn.execute(
        "SELECT r.team_id, r.rating, r.rank FROM ratings r JOIN teams t ON t.id = r.team_id "
        "WHERE r.year = ? AND r.method = ? AND r.sport = ? AND t.school = ?",
        (year, method, sport, school),
    ).fetchone()
    assert row is not None, f"no {method}/{sport} rating stored for {school} in {year}"
    return row


@dataclass(frozen=True)
class RatedLeague:
    conn: sqlite3.Connection
    method: str
    sport: Sport
    sample: LeagueSample
    computed_years: list[int]
    decoy_method: str
    decoy_year: int


@pytest.fixture(
    params=[(method, sport) for method in METHODS for sport in SPORTS],
    ids=[f"{method}-{sport}" for method in METHODS for sport in SPORTS],
)
def rated_league(request: pytest.FixtureRequest) -> RatedLeague:
    """One league's fixture with `method` computed for every season but the
    last, and a DIFFERENT method (the decoy) computed for the last season and
    for the sample year.

    The decoy in the last season gives list_available_years' exclusion check
    its meaning. The decoy in the sample year means every read below runs
    beside another method's rows for the same season. That is only one other
    method, though, read in whatever order SQLite happens to scan, so this
    fixture does not prove isolation. The isolation section at the bottom of
    this file carries that weight: it stores every method for one season and
    runs each test in both scan orders.

    Every (method, league) pair is representable, including elo_career. Both
    fixtures hold non-contiguous seasons (CFB 2001/2003/2004/2005/2013/2017/
    2019, NFL 1999/2004/2013/2022), so elo_career
    replays only those and reverts ratings across the missing years. Its values
    therefore differ from a full-database run, which is a question for the
    ratings suite. What this suite tests is the evidence layer reading back
    whatever was stored, and that is fully represented.
    """
    method, sport = request.param
    sample = LEAGUE_SAMPLES[sport]
    conn: sqlite3.Connection = request.getfixturevalue(sample.conn_fixture)
    # A no-op on the committed fixtures, which are at the current schema
    # (#110). A stale one fails here, at setup, on the StaleDatabaseWarning
    # gate, instead of on a missing column in the query below.
    ensure_schema(conn)

    seasons = [
        int(row["season"])
        for row in conn.execute(
            "SELECT DISTINCT season FROM games WHERE sport = ? ORDER BY season", (sport,)
        )
    ]
    computed_years, decoy_year = seasons[:-1], seasons[-1]
    assert sample.year in computed_years

    for year in computed_years:
        compute_and_store(conn, year, method, sport=sport)
    decoy_method = METHODS[(METHODS.index(method) + 1) % len(METHODS)]
    for year in (sample.year, decoy_year):
        compute_and_store(conn, year, decoy_method, sport=sport)

    return RatedLeague(conn, method, sport, sample, computed_years, decoy_method, decoy_year)


def test_list_available_years_is_exactly_this_methods_seasons(rated_league: RatedLeague) -> None:
    r = rated_league
    assert list_available_years(r.conn, r.method, r.sport) == r.computed_years
    # The decoy's last season really is stored, so its absence above means something.
    assert list_available_years(r.conn, r.decoy_method, r.sport) == [r.sample.year, r.decoy_year]


def test_resolve_team_resolves_under_every_method(rated_league: RatedLeague) -> None:
    r = rated_league
    ids = r.conn.execute(
        "SELECT id FROM teams WHERE school = ? AND sport = ?", (r.sample.team, r.sport)
    ).fetchall()
    assert len(ids) == 1
    for query in (r.sample.team, f"  {r.sample.team.lower()}  "):
        assert (
            resolve_team(r.conn, r.sample.year, query, method=r.method, sport=r.sport)
            == ids[0]["id"]
        )


def test_build_team_case_is_coherent_under_every_method(rated_league: RatedLeague) -> None:
    r = rated_league
    case = build_team_case(r.conn, r.sample.year, r.sample.team, method=r.method, sport=r.sport)
    stored = _stored_rating(r.conn, r.sample.year, r.method, r.sport, r.sample.team)

    assert case.method == r.method
    assert (case.year, case.team_name, case.team_id) == (
        r.sample.year,
        r.sample.team,
        stored["team_id"],
    )
    assert _on_scale(r.method, case.rating), case.rating
    assert (case.rating, case.rank) == (stored["rating"], stored["rank"])

    results = [g.result for g in case.games]
    assert (case.wins, case.losses, case.ties) == (
        results.count("W"),
        results.count("L"),
        results.count("T"),
    )
    assert len(case.games) == case.wins + case.losses + case.ties

    stored_opponents = _stored_ratings_by_team(r.conn, r.sample.year, r.method, r.sport)
    for game in case.games:
        assert (game.opponent_rating, game.opponent_rank) == stored_opponents.get(
            game.opponent_team_id, (None, None)
        ), game.opponent_name
    rated_opponents = [g for g in case.games if g.opponent_rating is not None]
    assert rated_opponents
    for game in rated_opponents:
        assert game.opponent_rating is not None
        assert _on_scale(r.method, game.opponent_rating), (game.opponent_name, game.opponent_rating)


def test_rating_breakdown_matches_what_the_method_decomposes(rated_league: RatedLeague) -> None:
    r = rated_league
    breakdown = build_team_case(
        r.conn, r.sample.year, r.sample.team, method=r.method, sport=r.sport
    ).rating_breakdown
    if HAS_BREAKDOWN[r.method]:
        assert breakdown.entries
    else:
        # Elo writes no rating_breakdowns rows at all (PR #93), not even the
        # residual row. That must read back as an empty breakdown, not raise.
        assert breakdown.entries == []
        assert breakdown.residual_contribution == 0.0


def test_build_comparison_is_coherent_under_every_method(rated_league: RatedLeague) -> None:
    r = rated_league
    s = r.sample
    comparison = build_comparison(
        r.conn, s.year, s.team, s.opponent, method=r.method, sport=r.sport
    )
    a, b = comparison.team_a, comparison.team_b

    assert comparison.year == s.year
    assert (a.team_name, b.team_name) == (s.team, s.opponent)
    for summary in (a, b):
        stored = _stored_rating(r.conn, s.year, r.method, r.sport, summary.team_name)
        assert (summary.rating, summary.rank) == (stored["rating"], stored["rank"])
        assert _on_scale(r.method, summary.rating), summary.rating
        assert bool(summary.rating_breakdown.entries) is HAS_BREAKDOWN[r.method]

    assert comparison.rating_diff == a.rating - b.rating
    assert comparison.rating_diff != 0

    assert comparison.head_to_head.played is True
    assert comparison.head_to_head.meetings
    for meeting in comparison.head_to_head.meetings:
        assert {meeting.home_team, meeting.away_team} == {s.team, s.opponent}

    assert s.team in comparison.verdict
    assert s.opponent in comparison.verdict
    leader = s.team if comparison.rating_diff > 0 else s.opponent
    d = VERDICT_DECIMALS[r.method]
    assert comparison.verdict.endswith(
        f"{leader} rates higher overall ({a.rating:.{d}f} vs {b.rating:.{d}f}, "
        f"rank {a.rank} vs {b.rank})."
    ), comparison.verdict


def test_build_comparison_says_which_method_answered_it(rated_league: RatedLeague) -> None:
    """Issue #152: a compare verdict names the rating method behind it, and
    that is the method requested -- the same one both underlying team cases
    were built under -- never a default, and never the decoy method whose
    rows sit beside it in the sample year."""
    r = rated_league
    s = r.sample
    comparison = build_comparison(
        r.conn, s.year, s.team, s.opponent, method=r.method, sport=r.sport
    )
    case_a = build_team_case(r.conn, s.year, s.team, method=r.method, sport=r.sport)
    case_b = build_team_case(r.conn, s.year, s.opponent, method=r.method, sport=r.sport)

    assert comparison.method == r.method
    assert comparison.method == case_a.method == case_b.method
    assert comparison.method != r.decoy_method


# ---------------------------------------------------------------------------
# issue #95 -- method isolation: every registered method's rows in one season
#
# Production computes every method for every season, so the isolation db
# stores all of them for ISOLATION_YEAR. Every rating query in proof.py
# filters by `method = ?`: list_available_years, _rated_teams (resolve_team's
# candidates), build_team_case's own rating lookup, _ratings_map (opponent
# ranks/ratings) and _rating_breakdown. TOGETHER, the tests below fail if any
# one of those filters is dropped, or loosened to a prefix match that lets an
# `elo` request also read `elo_career` rows. No single test covers every site;
# each docstring names the ones it guards.
#
# Scan order is part of it. None of those queries has an ORDER BY, and SQLite
# returns their rows in idx_ratings_year_method order, where `elo` sorts
# before `elo_career`. A prefix-matching rating lookup therefore still hands
# an `elo` request its own row first, while _ratings_map's last-wins dict
# ends on `elo_career`'s. So every test here runs twice: once in index order,
# and once under PRAGMA reverse_unordered_selects.
# ---------------------------------------------------------------------------

ISOLATION_YEAR = 2005
ISOLATION_SEASONS = (2001, 2005, 2013)  # every season ISOLATION_YEARS stores any method for
# Every method is stored for ISOLATION_YEAR. Outside it, each method lacks a
# season, and methods whose names share a prefix lack different ones.
ISOLATION_YEARS: dict[str, tuple[int, ...]] = {
    "keener": (2005, 2013),
    "elo": (2001, 2005),
    "elo_career": (2005, 2013),
}


@pytest.fixture(params=["index-order", "reversed"])
def isolation_conn(
    request: pytest.FixtureRequest, regression_conn: sqlite3.Connection
) -> sqlite3.Connection:
    conn = regression_conn
    # A method missing from the table would be isolated from nothing.
    assert tuple(ISOLATION_YEARS) == METHODS
    assert all(ISOLATION_YEAR in years for years in ISOLATION_YEARS.values())
    for method, years in ISOLATION_YEARS.items():
        for year in years:
            compute_and_store(conn, year, method)

    # The pragma must really reverse this db's unordered scans, or the
    # "reversed" run would silently repeat the other one.
    scan = "SELECT id FROM ratings WHERE year = ? AND sport = 'cfb'"
    conn.execute("PRAGMA reverse_unordered_selects = OFF")
    in_index_order = [row["id"] for row in conn.execute(scan, (ISOLATION_YEAR,))]
    conn.execute("PRAGMA reverse_unordered_selects = ON")
    reversed_order = [row["id"] for row in conn.execute(scan, (ISOLATION_YEAR,))]
    assert len(in_index_order) > 1
    assert reversed_order == in_index_order[::-1]

    if request.param == "index-order":
        conn.execute("PRAGMA reverse_unordered_selects = OFF")
    return conn


def _methods_stored_differently(conn: sqlite3.Connection, school: str) -> dict[str, sqlite3.Row]:
    """Each method's stored row for `school`, after checking the precondition
    that no two methods stored the same rating. If two did, a test that read
    the wrong method's row could still pass."""
    stored = {m: _stored_rating(conn, ISOLATION_YEAR, m, "cfb", school) for m in METHODS}
    for a, b in itertools.combinations(METHODS, 2):
        assert stored[a]["rating"] != stored[b]["rating"], (school, a, b)
    return stored


def test_isolation_list_available_years(isolation_conn: sqlite3.Connection) -> None:
    """Guards list_available_years (and so every _require_year check)."""
    for method, years in ISOLATION_YEARS.items():
        assert list_available_years(isolation_conn, method) == list(years), method


def test_isolation_resolve_team_sees_only_its_methods_rated_teams(
    isolation_conn: sqlite3.Connection,
) -> None:
    """Guards _rated_teams and _require_year. Texas is rated once per method,
    so a candidate pool that also read another method's rows would hold it
    more than once and report "Texas" as ambiguous."""
    conn = isolation_conn
    texas = conn.execute("SELECT id FROM teams WHERE school = 'Texas' AND sport = 'cfb'").fetchone()
    for method, years in ISOLATION_YEARS.items():
        assert resolve_team(conn, ISOLATION_YEAR, "Texas", method=method) == texas["id"], method
        missing = [season for season in ISOLATION_SEASONS if season not in years]
        assert missing, method
        for season in missing:
            with pytest.raises(UnknownYearError):
                resolve_team(conn, season, "Texas", method=method)


@pytest.mark.parametrize("school", ["Penn State", "Ohio State"])
def test_isolation_build_team_case_reads_only_its_own_methods_rows(
    isolation_conn: sqlite3.Connection, school: str
) -> None:
    """Guards build_team_case's rating lookup and _ratings_map, each in the
    scan order where a leaking query meets another method's row where it
    counts, plus _rating_breakdown for keener's real rows."""
    conn = isolation_conn
    stored = _methods_stored_differently(conn, school)

    for method, row in stored.items():
        case = build_team_case(conn, ISOLATION_YEAR, school, method=method)
        assert case.method == method
        assert (case.rating, case.rank) == (row["rating"], row["rank"]), method
        assert _on_scale(method, case.rating), (method, case.rating)

        opponents = _stored_ratings_by_team(conn, ISOLATION_YEAR, method, "cfb")
        for game in case.games:
            assert (game.opponent_rating, game.opponent_rank) == opponents.get(
                game.opponent_team_id, (None, None)
            ), (method, game.opponent_name)

        assert bool(case.rating_breakdown.entries) is HAS_BREAKDOWN[method], method
        if not HAS_BREAKDOWN[method]:
            assert case.rating_breakdown.residual_contribution == 0.0


def test_isolation_breakdown_rows_never_cross_methods(
    isolation_conn: sqlite3.Connection,
) -> None:
    """Guards _rating_breakdown between methods that both have rows.

    Elo methods store no breakdown rows, so on real data a breakdown read
    that leaks from elo_career into elo is invisible: there is nothing to
    leak. This test plants one row under each method that stores none,
    standing in for a later method that does decompose, then checks every
    method reads back exactly its own rows."""
    conn = isolation_conn
    penn_state = _stored_rating(conn, ISOLATION_YEAR, "keener", "cfb", "Penn State")["team_id"]
    ohio_state = _stored_rating(conn, ISOLATION_YEAR, "keener", "cfb", "Ohio State")["team_id"]
    planted = [method for method in METHODS if not HAS_BREAKDOWN[method]]
    assert len(planted) > 1, "nothing to leak between"
    for i, method in enumerate(planted):
        conn.execute(
            "INSERT INTO rating_breakdowns (year, method, team_id, opponent_team_id, "
            "games_played, wins, losses, credit, contribution, computed_at, sport) "
            "VALUES (?, ?, ?, ?, 1, 1, 0, 0.5, ?, 'planted by test', 'cfb')",
            (ISOLATION_YEAR, method, penn_state, ohio_state, 1000.0 + i),
        )
    conn.commit()

    for method in METHODS:
        expected = sorted(
            (int(row["opponent_team_id"]), float(row["contribution"]))
            for row in conn.execute(
                "SELECT opponent_team_id, contribution FROM rating_breakdowns "
                "WHERE year = ? AND method = ? AND team_id = ? AND sport = 'cfb' "
                "AND opponent_team_id IS NOT NULL",
                (ISOLATION_YEAR, method, penn_state),
            )
        )
        assert expected, method
        breakdown = build_team_case(
            conn, ISOLATION_YEAR, "Penn State", method=method
        ).rating_breakdown
        assert (
            sorted((e.opponent_team_id, e.contribution) for e in breakdown.entries) == expected
        ), method


def test_isolation_verdict_follows_the_requested_method(
    isolation_conn: sqlite3.Connection,
) -> None:
    """Guards the whole comparison path. Penn State and Ohio State met in
    2005. Keener and elo order them oppositely, so the closing sentence names
    a different leader. Elo and elo_career order them the same way but store
    different ratings, so the printed numbers differ."""
    conn = isolation_conn
    for school in ("Penn State", "Ohio State"):
        _methods_stored_differently(conn, school)

    for method in METHODS:
        penn_state = _stored_rating(conn, ISOLATION_YEAR, method, "cfb", "Penn State")
        ohio_state = _stored_rating(conn, ISOLATION_YEAR, method, "cfb", "Ohio State")
        comparison = build_comparison(
            conn, ISOLATION_YEAR, "Penn State", "Ohio State", method=method
        )

        assert comparison.head_to_head.played is True
        assert comparison.rating_diff == penn_state["rating"] - ohio_state["rating"]
        leader = "Penn State" if penn_state["rank"] < ohio_state["rank"] else "Ohio State"
        d = VERDICT_DECIMALS[method]
        assert comparison.verdict.endswith(
            f"{leader} rates higher overall "
            f"({penn_state['rating']:.{d}f} vs {ohio_state['rating']:.{d}f}, "
            f"rank {penn_state['rank']} vs {ohio_state['rank']})."
        ), (method, comparison.verdict)

    keener = build_comparison(conn, ISOLATION_YEAR, "Penn State", "Ohio State", method="keener")
    elo = build_comparison(conn, ISOLATION_YEAR, "Penn State", "Ohio State", method="elo")
    assert keener.rating_diff > 0
    assert elo.rating_diff < 0


# ---------------------------------------------------------------------------
# Issue #218: every per-game evidence record carries `games.id`
# ---------------------------------------------------------------------------
#
# A team can meet the same opponent twice in a season (Texas played Colorado
# in 2005's regular season and again in the Big 12 title game; every NFL
# division opponent), so `opponent_team_id` is not a key for a game list.
# The only key is `games.id`, which these tests check is threaded through
# unchanged -- never a constant, never a re-derived value. Ids measured on
# tests/fixtures/cfb_regression.sqlite3 with the sqlite3 CLI (2026-09-14).

TEXAS_COLORADO_2005_GAME_IDS = {
    # regular week 7, Texas 42 Colorado 17, Texas home
    (42, 17): 252880251,
    # regular week 14 (Big 12 title), Colorado 3 Texas 70, Colorado home
    (70, 3): 253370251,
}
TEXAS_USC_2005_ROSE_BOWL_GAME_ID = 260040030


def _game_row(conn: sqlite3.Connection, game_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT home_team_id, away_team_id, season, sport FROM games WHERE id = ?",
        (game_id,),
    ).fetchone()
    assert row is not None, game_id
    return typing.cast(sqlite3.Row, row)


def test_texas_2005_lists_both_colorado_games_with_their_own_game_ids(
    rated_conn: sqlite3.Connection,
) -> None:
    """(a) Two entries for Colorado, each carrying the `games.id` of the game
    it came from -- not the same id twice, not a placeholder."""
    case = build_team_case(rated_conn, 2005, "Texas", method="keener")
    colorado = [g for g in case.games if g.opponent_name == "Colorado"]
    assert len(colorado) == 2
    assert {g.game_id for g in colorado} == set(TEXAS_COLORADO_2005_GAME_IDS.values())
    for g in colorado:
        assert g.game_id == TEXAS_COLORADO_2005_GAME_IDS[(g.team_score, g.opponent_score)], g


def test_every_game_id_in_a_team_case_names_that_teams_game_in_the_games_table(
    rated_conn: sqlite3.Connection,
) -> None:
    """(b) Each record's `game_id` resolves to a 2005 `games` row whose two
    teams are Texas and the record's opponent -- for the schedule, the
    quality wins and the worst loss alike."""
    case = build_team_case(rated_conn, 2005, "Texas", method="keener")
    records = list(case.games) + list(case.quality_wins)
    if case.worst_loss is not None:
        records.append(case.worst_loss)
    assert case.quality_wins  # 2005 Texas beat ranked teams, so this is not vacuous
    for record in records:
        row = _game_row(rated_conn, record.game_id)
        assert row["season"] == 2005, record
        assert row["sport"] == "cfb", record
        assert {row["home_team_id"], row["away_team_id"]} == {
            case.team_id,
            record.opponent_team_id,
        }, record


def test_game_ids_across_a_team_cases_games_are_unique(
    rated_conn: sqlite3.Connection,
) -> None:
    """(c) The point of #218: `game_id` is a usable list key where
    `opponent_team_id` is not (Colorado appears twice)."""
    case = build_team_case(rated_conn, 2005, "Texas", method="keener")
    ids = [g.game_id for g in case.games]
    assert len(ids) == len(set(ids))
    opponents = [g.opponent_team_id for g in case.games]
    assert len(opponents) != len(set(opponents))


def test_head_to_head_meeting_carries_the_games_id(rated_conn: sqlite3.Connection) -> None:
    """(d) The 2005 Rose Bowl, by its `games.id`."""
    comparison = build_comparison(rated_conn, 2005, "Texas", "USC", method="keener")
    assert comparison.head_to_head.meetings[0].game_id == TEXAS_USC_2005_ROSE_BOWL_GAME_ID


def test_head_to_head_rematch_meetings_carry_distinct_game_ids(
    rated_conn: sqlite3.Connection,
) -> None:
    """Texas and Colorado met twice in 2005; the two meetings are the two
    games, in chronological order."""
    comparison = build_comparison(rated_conn, 2005, "Texas", "Colorado", method="keener")
    meetings = comparison.head_to_head.meetings
    assert len(meetings) == 2
    assert [m.game_id for m in meetings] == [252880251, 253370251]
    assert (meetings[0].home_points, meetings[0].away_points) == (42, 17)
    assert (meetings[1].home_points, meetings[1].away_points) == (3, 70)


def test_common_opponent_meetings_carry_the_game_ids_of_the_sides_own_games(
    rated_conn: sqlite3.Connection,
) -> None:
    """(e) Measured on tests/fixtures/cfb_regression.sqlite3 (2026-09-14):
    2005 Texas and Colorado share four opponents -- Missouri, Oklahoma
    State, Kansas and Texas A&M. (Texas and USC share none, so the Rose
    Bowl comparison cannot exercise this.) Every meeting's `game_id` per side
    is one of that side's `TeamCase.games` ids, the ids within a side's list
    are unique, and the game named is against that common opponent."""
    comparison = build_comparison(rated_conn, 2005, "Texas", "Colorado", method="keener")
    assert {c.opponent_name for c in comparison.common_opponents} == {
        "Missouri",
        "Oklahoma State",
        "Kansas",
        "Texas A&M",
    }
    texas_ids = {g.game_id for g in build_team_case(rated_conn, 2005, "Texas").games}
    colorado_ids = {g.game_id for g in build_team_case(rated_conn, 2005, "Colorado").games}
    for common in comparison.common_opponents:
        sides = ((texas_ids, common.team_a_meetings), (colorado_ids, common.team_b_meetings))
        for side_ids, meetings in sides:
            assert meetings, common.opponent_name
            ids = [m.game_id for m in meetings]
            assert len(ids) == len(set(ids)), common.opponent_name
            for m in meetings:
                assert m.game_id in side_ids, (common.opponent_name, m)
                row = _game_row(rated_conn, m.game_id)
                assert common.opponent_team_id in (row["home_team_id"], row["away_team_id"]), m


# ---------------------------------------------------------------------------
# Issue #300: every per-game evidence record says whether it was a conference
# title game, and whose. CFBD labels title games `season_type='regular'`, so
# without the flag a narrator calls the Big 12 title game "the regular-season
# finale". Read from `games.conference_championship` (ingest's curated list),
# never derived from week, date or conference. Ids measured on
# tests/fixtures/cfb_regression.sqlite3 with the sqlite3 CLI (2026-10-20).
# ---------------------------------------------------------------------------

TEXAS_2005_BIG_12_TITLE_GAME_ID = 253370251  # week 14, Colorado 3 Texas 70
TEXAS_2005_AT_TEXAS_AM_GAME_ID = 253290245  # week 13, the real regular-season finale
TEXAS_2005_COLORADO_REGULAR_GAME_ID = 252880251  # week 7, Texas 42 Colorado 17
AUBURN_GEORGIA_2017_REGULAR_GAME_ID = 400933913  # week 11, Auburn 40 Georgia 17
AUBURN_GEORGIA_2017_SEC_TITLE_GAME_ID = 400955153  # week 14, Auburn 7 Georgia 28


def test_team_case_games_name_the_conference_of_a_title_game_and_none_otherwise(
    rated_conn: sqlite3.Connection,
) -> None:
    """2005 Texas played two late 'regular' games: at Texas A&M in week 13
    (the real regular-season finale) and the Big 12 title game against
    Colorado in week 14. Only the second says 'Big 12'; every other listed
    game says None."""
    case = build_team_case(rated_conn, 2005, "Texas", method="keener")
    by_id = {g.game_id: g for g in case.games}

    title = by_id[TEXAS_2005_BIG_12_TITLE_GAME_ID]
    assert title.title_game_conference == "Big 12"
    assert title.season_type == "regular"  # unchanged: CFBD's label stays
    assert by_id[TEXAS_2005_AT_TEXAS_AM_GAME_ID].title_game_conference is None
    others = [g for g in case.games if g.game_id != TEXAS_2005_BIG_12_TITLE_GAME_ID]
    assert others
    assert all(g.title_game_conference is None for g in others)


def test_quality_wins_and_worst_loss_carry_the_same_title_game_conference(
    rated_conn: sqlite3.Connection,
) -> None:
    """quality_wins and worst_loss are drawn from `games`, so the field agrees
    whichever list a consumer reads."""
    case = build_team_case(rated_conn, 2005, "Texas", method="keener")
    by_id = {g.game_id: g.title_game_conference for g in case.games}
    records = list(case.quality_wins)
    if case.worst_loss is not None:
        records.append(case.worst_loss)
    assert records
    for record in records:
        assert record.title_game_conference == by_id[record.game_id], record


def test_head_to_head_flags_only_the_sec_title_game_of_a_2017_auburn_georgia_rematch(
    regression_conn: sqlite3.Connection,
) -> None:
    """Auburn and Georgia met twice in 2017: week 11 in the regular season and
    week 14 in the SEC title game. Both are `season_type='regular'`; only the
    title game carries 'SEC'."""
    compute_and_store(regression_conn, 2017, "keener")
    comparison = build_comparison(regression_conn, 2017, "Auburn", "Georgia", method="keener")

    meetings = comparison.head_to_head.meetings
    assert [m.game_id for m in meetings] == [
        AUBURN_GEORGIA_2017_REGULAR_GAME_ID,
        AUBURN_GEORGIA_2017_SEC_TITLE_GAME_ID,
    ]
    assert [m.title_game_conference for m in meetings] == [None, "SEC"]
    assert [m.season_type for m in meetings] == ["regular", "regular"]


def test_common_opponent_meeting_that_was_a_title_game_carries_the_conference(
    rated_conn: sqlite3.Connection,
) -> None:
    """2005 Texas and Nebraska share Colorado. Texas met Colorado twice
    (week 7, then the Big 12 title game in week 14); Nebraska once (week 13).
    Each side's meeting copies that side's OpponentResult value."""
    comparison = build_comparison(rated_conn, 2005, "Texas", "Nebraska", method="keener")
    (colorado,) = [c for c in comparison.common_opponents if c.opponent_name == "Colorado"]

    assert [(m.game_id, m.title_game_conference) for m in colorado.team_a_meetings] == [
        (TEXAS_2005_COLORADO_REGULAR_GAME_ID, None),
        (TEXAS_2005_BIG_12_TITLE_GAME_ID, "Big 12"),
    ]
    assert [m.title_game_conference for m in colorado.team_b_meetings] == [None]

    texas_case = build_team_case(rated_conn, 2005, "Texas", method="keener")
    texas = {g.game_id: g.title_game_conference for g in texas_case.games}
    for common in comparison.common_opponents:
        for m in common.team_a_meetings:
            assert m.title_game_conference == texas[m.game_id], (common.opponent_name, m)


def test_every_nfl_evidence_row_has_no_title_game_conference(
    nfl_regression_conn: sqlite3.Connection,
) -> None:
    """The flag is CFB-only (always 0 for NFL rows), so no NFL team case,
    head-to-head meeting or common-opponent meeting names a conference."""
    conn = nfl_regression_conn
    compute_and_store(conn, 2013, "keener", sport="nfl")
    schools = [
        row["school"]
        for row in conn.execute(
            "SELECT t.school FROM ratings r JOIN teams t ON t.id = r.team_id "
            "WHERE r.year = 2013 AND r.method = 'keener' AND r.sport = 'nfl'"
        )
    ]
    assert len(schools) == 32
    for school in schools:
        case = build_team_case(conn, 2013, school, method="keener", sport="nfl")
        assert case.games
        assert all(g.title_game_conference is None for g in case.games), school

    comparison = build_comparison(
        conn, 2013, "Green Bay Packers", "Minnesota Vikings", method="keener", sport="nfl"
    )
    assert comparison.head_to_head.meetings
    assert all(m.title_game_conference is None for m in comparison.head_to_head.meetings)
    assert comparison.common_opponents
    for common in comparison.common_opponents:
        for m in [*common.team_a_meetings, *common.team_b_meetings]:
            assert m.title_game_conference is None, (common.opponent_name, m)


# ---------------------------------------------------------------------------
# Issue #349: `venue_reliable` on every per-game shape evidence builds.
#
# The rule (contracts.py, `OpponentResult.venue_reliable`): a game's venue is
# reliable iff the sport is not CFB, or the season is 2008 or later, or the
# game is one of #359's curated neutral-site overrides -- recognisable as
# `games.neutral_site = 1` while CFBD's own `raw_json` `neutralSite` is false.
# Before 2008 a game CFBD itself flags neutral is NOT reliable (founder, #343).
#
# Real 2005 games, as the committed fixture stores them:
#   253370251  Colorado vs Texas, Big 12 title game at Reliant: override -> True
#   252810251  Texas vs Oklahoma, Red River at the Cotton Bowl: override -> True
#   252530194  Texas at Ohio State, week 2: pre-2008, not an override -> False
#   252880251  Colorado at Texas, week 7: pre-2008, not an override -> False
#   252530248  Houston vs Sam Houston at Robertson, CFBD-flagged neutral -> False
#   260040030  Texas vs USC, Rose Bowl, CFBD-flagged neutral -> False
# ---------------------------------------------------------------------------

BIG12_TITLE_2005 = 253370251
RED_RIVER_2005 = 252810251
TEXAS_AT_OHIO_STATE_2005 = 252530194
COLORADO_AT_TEXAS_2005 = 252880251
HOUSTON_SAM_HOUSTON_2005 = 252530248
ROSE_BOWL_2005 = 260040030


@pytest.fixture
def venue_conn(regression_conn: sqlite3.Connection) -> sqlite3.Connection:
    """The CFB fixture with keener and elo computed for 2005 and 2013."""
    for year in (2005, 2013):
        for method in ("keener", "elo"):
            compute_and_store(regression_conn, year, method)
    return regression_conn


def _reliable_by_game_id(case: TeamCase) -> dict[int, bool]:
    return {g.game_id: g.venue_reliable for g in case.games}


def _reliable_by_step_opponent(case: TeamCase) -> dict[tuple[str, str | None], bool]:
    """(opponent name, start_date) -> the ledger step's venue_reliable."""
    assert case.elo_ledger is not None
    return {(s.opponent_name, s.start_date): s.venue_reliable for s in case.elo_ledger.steps}


def test_fixture_holds_the_measured_override_and_cfbd_flagged_counts(
    venue_conn: sqlite3.Connection,
) -> None:
    """The brief's measured premise: 22 pre-2008 overrides, 662 pre-2008
    games CFBD itself flags neutral. If ingest's override list changes these,
    the expectations below need a second look."""
    overrides, cfbd_flagged = venue_conn.execute(
        """
        SELECT
          SUM(neutral_site = 1 AND NOT json_extract(raw_json, '$.neutralSite')),
          SUM(json_extract(raw_json, '$.neutralSite') = 1)
        FROM games WHERE sport = 'cfb' AND season < 2008
        """
    ).fetchone()
    assert (overrides, cfbd_flagged) == (22, 662)


def test_team_case_games_carry_venue_reliable_per_the_rule(
    venue_conn: sqlite3.Connection,
) -> None:
    texas = _reliable_by_game_id(build_team_case(venue_conn, 2005, "Texas"))
    assert texas[BIG12_TITLE_2005] is True
    assert texas[RED_RIVER_2005] is True
    assert texas[TEXAS_AT_OHIO_STATE_2005] is False
    assert texas[COLORADO_AT_TEXAS_2005] is False
    assert texas[ROSE_BOWL_2005] is False

    colorado = _reliable_by_game_id(build_team_case(venue_conn, 2005, "Colorado"))
    assert colorado[BIG12_TITLE_2005] is True
    assert colorado[COLORADO_AT_TEXAS_2005] is False

    ohio_state = _reliable_by_game_id(build_team_case(venue_conn, 2005, "Ohio State"))
    assert ohio_state[TEXAS_AT_OHIO_STATE_2005] is False

    houston = _reliable_by_game_id(build_team_case(venue_conn, 2005, "Houston"))
    assert houston[HOUSTON_SAM_HOUSTON_2005] is False


def test_houston_vs_sam_houston_2005_cfbd_flagged_neutral_is_not_reliable(
    venue_conn: sqlite3.Connection,
) -> None:
    """CFBD flags this game neutral although it was at Houston's own Robertson
    Stadium: the reason the pre-2008 flag is not trusted. Neither the listed
    game nor the Elo step (which needs a game lookup) may state it."""
    houston = build_team_case(venue_conn, 2005, "Houston", method="elo")
    game = next(g for g in houston.games if g.game_id == HOUSTON_SAM_HOUSTON_2005)
    assert (game.venue, game.venue_reliable) == ("neutral", False)
    assert houston.elo_ledger is not None
    steps = [s for s in houston.elo_ledger.steps if s.opponent_name == "Sam Houston"]
    assert [(s.venue, s.venue_reliable) for s in steps] == [("neutral", False)]


def test_quality_wins_and_worst_loss_carry_venue_reliable(
    venue_conn: sqlite3.Connection,
) -> None:
    texas = build_team_case(venue_conn, 2005, "Texas")
    wins = {q.game_id: q.venue_reliable for q in texas.quality_wins}
    assert wins[RED_RIVER_2005] is True
    assert wins[TEXAS_AT_OHIO_STATE_2005] is False
    assert wins[ROSE_BOWL_2005] is False

    colorado = build_team_case(venue_conn, 2005, "Colorado")
    assert colorado.worst_loss is not None
    assert colorado.worst_loss.opponent_name == "Iowa State"
    assert colorado.worst_loss.venue_reliable is False

    usc = build_team_case(venue_conn, 2005, "USC")
    assert usc.worst_loss is not None
    assert usc.worst_loss.game_id == ROSE_BOWL_2005
    assert usc.worst_loss.venue_reliable is False


def test_head_to_head_meetings_carry_venue_reliable(venue_conn: sqlite3.Connection) -> None:
    comparison = build_comparison(venue_conn, 2005, "Texas", "Colorado")
    by_id = {m.game_id: m.venue_reliable for m in comparison.head_to_head.meetings}
    assert by_id == {COLORADO_AT_TEXAS_2005: False, BIG12_TITLE_2005: True}


def test_common_opponent_meetings_copy_each_sides_venue_reliable(
    venue_conn: sqlite3.Connection,
) -> None:
    """Colorado and Oklahoma both played Texas: Colorado twice (at Texas, not
    reliable; the Big 12 title game, an override), Oklahoma once (Red River,
    an override)."""
    comparison = build_comparison(venue_conn, 2005, "Colorado", "Oklahoma")
    texas = next(c for c in comparison.common_opponents if c.opponent_name == "Texas")
    assert [(m.game_id, m.venue_reliable) for m in texas.team_a_meetings] == [
        (COLORADO_AT_TEXAS_2005, False),
        (BIG12_TITLE_2005, True),
    ]
    assert [(m.game_id, m.venue_reliable) for m in texas.team_b_meetings] == [
        (RED_RIVER_2005, True),
    ]


def test_elo_ledger_steps_carry_venue_reliable(venue_conn: sqlite3.Connection) -> None:
    """Steps carry no game id. A neutral pre-2008 CFB step is matched to its
    game (override or CFBD-flagged); any other pre-2008 CFB step is not
    reliable without a lookup."""
    texas = build_team_case(venue_conn, 2005, "Texas", method="elo")
    steps = _reliable_by_step_opponent(texas)
    assert steps[("Colorado", "2005-12-03T18:00:00.000Z")] is True  # Big 12 title
    assert steps[("Oklahoma", "2005-10-08T17:00:00.000Z")] is True  # Red River
    assert steps[("Ohio State", "2005-09-11T00:00:00.000Z")] is False
    assert steps[("Colorado", "2005-10-15T19:30:00.000Z")] is False
    assert steps[("USC", "2006-01-05T01:00:00.000Z")] is False  # Rose Bowl

    houston = build_team_case(venue_conn, 2005, "Houston", method="elo")
    assert houston.elo_ledger is not None
    sam_houston = [s for s in houston.elo_ledger.steps if s.opponent_name == "Sam Houston"]
    assert [(s.venue, s.venue_reliable) for s in sam_houston] == [("neutral", False)]


def test_ledger_step_agrees_with_its_listed_game_for_every_2005_team(
    venue_conn: sqlite3.Connection,
) -> None:
    """Every step's venue_reliable equals the same game's OpponentResult value
    (matched on opponent and venue), so the two paths cannot disagree."""
    schools = [
        row["school"]
        for row in venue_conn.execute(
            "SELECT t.school FROM ratings r JOIN teams t ON t.id = r.team_id "
            "WHERE r.year = 2005 AND r.method = 'elo' AND r.sport = 'cfb'"
        )
    ]
    seen = {True: 0, False: 0}
    for school in schools:
        elo_case = build_team_case(venue_conn, 2005, school, method="elo")
        assert elo_case.elo_ledger is not None
        listed = [(g.opponent_team_id, g.venue, g.venue_reliable) for g in elo_case.games]
        stepped = [
            (s.opponent_team_id, s.venue, s.venue_reliable) for s in elo_case.elo_ledger.steps
        ]
        # Every step is one of the listed games (the walk may skip some).
        assert not Counter(stepped) - Counter(listed), school
        for _, _, reliable in stepped:
            seen[reliable] += 1
    assert seen[True] > 0 and seen[False] > 0


def test_cfbd_flagged_neutral_pre_2008_game_is_unreliable_on_every_shape(
    venue_conn: sqlite3.Connection,
) -> None:
    """The 2005 Rose Bowl, which CFBD flags neutral itself, on every shape
    that carries it: both team cases' games, Texas's quality win, USC's worst
    loss, the head-to-head meeting, a common-opponent meeting (Texas vs Notre
    Dame, who both played USC) and both teams' Elo steps."""
    texas = build_team_case(venue_conn, 2005, "Texas")
    usc = build_team_case(venue_conn, 2005, "USC")
    assert _reliable_by_game_id(texas)[ROSE_BOWL_2005] is False
    assert _reliable_by_game_id(usc)[ROSE_BOWL_2005] is False
    rose_win = next(q for q in texas.quality_wins if q.game_id == ROSE_BOWL_2005)
    assert rose_win.venue == "neutral"
    assert rose_win.venue_reliable is False
    assert usc.worst_loss is not None and usc.worst_loss.game_id == ROSE_BOWL_2005
    assert usc.worst_loss.venue_reliable is False

    h2h = build_comparison(venue_conn, 2005, "Texas", "USC").head_to_head.meetings
    assert [(m.game_id, m.neutral_site, m.venue_reliable) for m in h2h] == [
        (ROSE_BOWL_2005, True, False)
    ]

    vs_nd = build_comparison(venue_conn, 2005, "Texas", "Notre Dame")
    common_usc = next(c for c in vs_nd.common_opponents if c.opponent_name == "USC")
    assert [(m.game_id, m.venue_reliable) for m in common_usc.team_a_meetings] == [
        (ROSE_BOWL_2005, False)
    ]

    for school, opponent in (("Texas", "USC"), ("USC", "Texas")):
        case = build_team_case(venue_conn, 2005, school, method="elo")
        assert case.elo_ledger is not None
        rose = [
            s
            for s in case.elo_ledger.steps
            if s.opponent_name == opponent and s.season_type == "postseason"
        ]
        assert [(s.venue, s.venue_reliable) for s in rose] == [("neutral", False)]


def test_every_2013_cfb_shape_is_venue_reliable(venue_conn: sqlite3.Connection) -> None:
    """2008 on, CFBD's flag is trusted: every game, quality win, worst loss
    and ledger step of every rated 2013 team is reliable, neutral or not."""
    schools = [
        row["school"]
        for row in venue_conn.execute(
            "SELECT t.school FROM ratings r JOIN teams t ON t.id = r.team_id "
            "WHERE r.year = 2013 AND r.method = 'elo' AND r.sport = 'cfb'"
        )
    ]
    venues: set[str] = set()
    for school in schools:
        case = build_team_case(venue_conn, 2013, school, method="elo")
        assert all(g.venue_reliable for g in case.games), school
        assert all(q.venue_reliable for q in case.quality_wins), school
        assert case.worst_loss is None or case.worst_loss.venue_reliable, school
        assert case.elo_ledger is not None
        assert all(s.venue_reliable for s in case.elo_ledger.steps), school
        venues.update(g.venue for g in case.games)
    assert venues == {"home", "away", "neutral"}

    comparison = build_comparison(venue_conn, 2013, "Auburn", "Alabama")
    assert comparison.head_to_head.meetings
    assert all(m.venue_reliable for m in comparison.head_to_head.meetings)
    assert comparison.common_opponents
    for common in comparison.common_opponents:
        for m in [*common.team_a_meetings, *common.team_b_meetings]:
            assert m.venue_reliable, (common.opponent_name, m)


def test_every_nfl_shape_is_venue_reliable_in_every_fixture_season(
    nfl_regression_conn: sqlite3.Connection,
) -> None:
    """The rule is CFB-only: NFL games are reliable in every season,
    pre-2008 included, and so is every ledger step and meeting."""
    conn = nfl_regression_conn
    seasons = [
        int(r[0])
        for r in conn.execute("SELECT DISTINCT season FROM games WHERE sport = 'nfl' ORDER BY 1")
    ]
    assert seasons and min(seasons) < 2008
    neutral_seen = 0
    for year in seasons:
        compute_and_store(conn, year, "elo", sport="nfl")
        schools = [
            row["school"]
            for row in conn.execute(
                "SELECT t.school FROM ratings r JOIN teams t ON t.id = r.team_id "
                "WHERE r.year = ? AND r.method = 'elo' AND r.sport = 'nfl'",
                (year,),
            )
        ]
        for school in schools:
            case = build_team_case(conn, year, school, method="elo", sport="nfl")
            assert case.games
            assert all(g.venue_reliable for g in case.games), (year, school)
            assert all(q.venue_reliable for q in case.quality_wins), (year, school)
            assert case.worst_loss is None or case.worst_loss.venue_reliable
            assert case.elo_ledger is not None
            assert all(s.venue_reliable for s in case.elo_ledger.steps), (year, school)
            neutral_seen += sum(g.venue == "neutral" for g in case.games)
    assert neutral_seen > 0

    comparison = build_comparison(
        conn, 2004, "Green Bay Packers", "Minnesota Vikings", method="elo", sport="nfl"
    )
    assert comparison.head_to_head.meetings
    assert all(m.venue_reliable for m in comparison.head_to_head.meetings)
    assert comparison.common_opponents
    for common in comparison.common_opponents:
        for m in [*common.team_a_meetings, *common.team_b_meetings]:
            assert m.venue_reliable, (common.opponent_name, m)
