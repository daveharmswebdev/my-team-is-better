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
import sqlite3
import typing
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
from cfb_strength.db.connection import ensure_schema
from cfb_strength.evidence.proof import (
    build_comparison,
    build_team_case,
    list_available_years,
    resolve_team,
)
from cfb_strength.ratings.compute_ratings import compute_and_store


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
