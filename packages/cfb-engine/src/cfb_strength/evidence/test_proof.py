"""Tests for evidence/proof.py: TeamCase/ComparisonResult construction against
a throwaway sqlite db built from the real schema.sql (mirrors
ratings/test_compute_ratings.py's fixture style -- see that file's own
comment on why a real schema-built db is used instead of a hand-rolled mock).

Issue #58 (sprint 2 NFL support): every `teams`/`games`/`ratings`/
`rating_breakdowns` row now carries a `sport` column (#51), and
`ratings/compute_ratings.py` was already fixed (#57) to scope every query by
it -- this file proves `evidence/proof.py` got the same fix, since it reads
those same four tables directly via SQL (the db is the integration boundary
between `evidence` and `ratings`/`ingest`, not a Python import).
"""

from __future__ import annotations

import dataclasses
import sqlite3
import typing
from pathlib import Path

import pytest

from cfb_strength.contracts import (
    AmbiguousTeamError,
    EloGameStep,
    EloLedger,
    Method,
    SameTeamComparisonError,
    Sport,
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

YEAR = 2023
METHOD = "keener"


# ---------------------------------------------------------------------------
# fixture helpers (mirrors ratings/test_compute_ratings.py's _insert_* style)
# ---------------------------------------------------------------------------


def _make_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "test.sqlite3"
    conn = get_conn(db_path)
    ensure_schema(conn)
    conn.close()
    return db_path


def _insert_team(
    conn: sqlite3.Connection,
    team_id: int,
    school: str,
    classification: str | None = None,
    sport: str = "cfb",
) -> None:
    conn.execute(
        "INSERT INTO teams (id, school, classification, sport) VALUES (?, ?, ?, ?)",
        (team_id, school, classification, sport),
    )


def _insert_game(
    conn: sqlite3.Connection,
    game_id: int,
    year: int,
    home_id: int,
    away_id: int,
    home_team: str,
    away_team: str,
    home_points: int | None,
    away_points: int | None,
    week: int = 1,
    season_type: str = "regular",
    completed: bool = True,
    sport: str = "cfb",
    neutral_site: bool = False,
) -> None:
    conn.execute(
        """
        INSERT INTO games (
            id, season, week, season_type, start_date, neutral_site, completed,
            home_team_id, away_team_id, home_team, away_team,
            home_points, away_points, home_conference, away_conference, venue, raw_json, sport
        ) VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, '{}', ?)
        """,
        (
            game_id,
            year,
            week,
            season_type,
            1 if neutral_site else 0,
            1 if completed else 0,
            home_id,
            away_id,
            home_team,
            away_team,
            home_points,
            away_points,
            sport,
        ),
    )


def _insert_rating(
    conn: sqlite3.Connection,
    year: int,
    method: str,
    team_id: int,
    rating: float,
    rank: int,
    wins: int,
    losses: int,
    sport: str = "cfb",
    ties: int = 0,
) -> None:
    conn.execute(
        """
        INSERT INTO ratings (
            year, method, team_id, rating, rank, wins, losses, ties, computed_at, sport
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'test', ?)
        """,
        (year, method, team_id, rating, rank, wins, losses, ties, sport),
    )


def _insert_breakdown(
    conn: sqlite3.Connection,
    year: int,
    method: str,
    team_id: int,
    opponent_team_id: int | None,
    games_played: int | None,
    wins: int | None,
    losses: int | None,
    credit: float | None,
    contribution: float,
    sport: str = "cfb",
) -> None:
    conn.execute(
        """
        INSERT INTO rating_breakdowns (
            year, method, team_id, opponent_team_id, games_played, wins, losses,
            credit, contribution, computed_at, sport
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'test', ?)
        """,
        (year, method, team_id, opponent_team_id, games_played, wins, losses, credit, contribution, sport),
    )


def _build_fixture(conn: sqlite3.Connection) -> None:
    """A 3-team win cycle for CFB (ids 1-3, classification='fbs') and an
    analogous 3-team cycle for NFL (ids 101-103, classification=None,
    per #51's real NFL-ingest behavior), both under `YEAR`/`METHOD` -- the
    exact "same year value, different sport" scenario #57 already fixed for
    compute_ratings.py. Plus one deliberately name-colliding pair (id 4 "Wildcats"
    CFB vs id 104 "Wildcats" NFL) to make a sport-filter regression in
    `resolve_team`'s candidate pool directly observable: without the `sport`
    filter, resolving "Wildcats" for either sport would be ambiguous (2
    candidates); with it, each resolves uniquely.
    """
    # --- CFB: teams 1-3, a win cycle 1 > 2 > 3 > 1 (mirrors
    # ratings/test_compute_ratings.py's fixture cycle) ---
    cfb_names = {1: "Alpha State", 2: "Bravo Tech", 3: "Charlie U"}
    for tid, name in cfb_names.items():
        _insert_team(conn, tid, name, classification="fbs", sport="cfb")
    _insert_game(conn, 1, YEAR, 1, 2, cfb_names[1], cfb_names[2], 30, 10, sport="cfb")
    _insert_game(conn, 2, YEAR, 2, 3, cfb_names[2], cfb_names[3], 20, 17, sport="cfb")
    _insert_game(conn, 3, YEAR, 3, 1, cfb_names[3], cfb_names[1], 3, 40, sport="cfb")
    _insert_rating(conn, YEAR, METHOD, 1, 1.5, 1, 2, 0, sport="cfb")
    _insert_rating(conn, YEAR, METHOD, 2, 1.0, 2, 1, 1, sport="cfb")
    _insert_rating(conn, YEAR, METHOD, 3, 0.5, 3, 0, 2, sport="cfb")
    for tid in (1, 2, 3):
        _insert_breakdown(conn, YEAR, METHOD, tid, None, None, None, None, None, 0.1, sport="cfb")
    _insert_breakdown(conn, YEAR, METHOD, 1, 2, 1, 1, 0, 0.6, 0.9, sport="cfb")
    _insert_breakdown(conn, YEAR, METHOD, 1, 3, 1, 1, 0, 0.6, 0.5, sport="cfb")

    # --- NFL: teams 101-103, an analogous win cycle -- disjoint ids per
    # #51's surrogate-id minting, classification=None (no FBS/FCS concept) ---
    nfl_names = {101: "Delta Squad", 102: "Echo Corp", 103: "Foxtrot Ltd"}
    for tid, name in nfl_names.items():
        _insert_team(conn, tid, name, classification=None, sport="nfl")
    _insert_game(conn, 101, YEAR, 101, 102, nfl_names[101], nfl_names[102], 24, 20, sport="nfl")
    _insert_game(conn, 102, YEAR, 102, 103, nfl_names[102], nfl_names[103], 27, 3, sport="nfl")
    _insert_game(conn, 103, YEAR, 103, 101, nfl_names[103], nfl_names[101], 14, 31, sport="nfl")
    _insert_rating(conn, YEAR, METHOD, 101, 1.4, 1, 2, 0, sport="nfl")
    _insert_rating(conn, YEAR, METHOD, 102, 0.9, 2, 1, 1, sport="nfl")
    _insert_rating(conn, YEAR, METHOD, 103, 0.4, 3, 0, 2, sport="nfl")
    for tid in (101, 102, 103):
        _insert_breakdown(conn, YEAR, METHOD, tid, None, None, None, None, None, 0.1, sport="nfl")

    # NFL-only rating for a year CFB has no rows for, so list_available_years
    # scoped by sport can be distinguished from an unfiltered DISTINCT year.
    _insert_team(conn, 105, "Golf United", classification=None, sport="nfl")
    _insert_rating(conn, 2024, METHOD, 105, 0.2, 1, 1, 0, sport="nfl")

    # --- Name-colliding pair across sports, same year/method, no games
    # needed (build_team_case only requires a ratings row to exist) ---
    _insert_team(conn, 4, "Wildcats", classification="fbs", sport="cfb")
    _insert_rating(conn, YEAR, METHOD, 4, 0.3, 4, 0, 0, sport="cfb")
    _insert_breakdown(conn, YEAR, METHOD, 4, None, None, None, None, None, 0.1, sport="cfb")

    _insert_team(conn, 104, "Wildcats", classification=None, sport="nfl")
    _insert_rating(conn, YEAR, METHOD, 104, 0.3, 4, 0, 0, sport="nfl")
    _insert_breakdown(conn, YEAR, METHOD, 104, None, None, None, None, None, 0.1, sport="nfl")

    # --- Issue #100: a rated NFL team whose name looks superficially close
    # to a query that names a *CFB* school ("Texas" vs "Houston Texans"). It
    # is neither an exact match, nor a substring either direction ("texas" is
    # not inside "houston texans" -- "texan" is), nor close enough for the
    # 0.6-cutoff fuzzy stage, so "Texas" under sport="nfl" is a genuine
    # zero-match query even though a same-sport lookalike is rated.
    _insert_team(conn, 106, "Houston Texans", classification=None, sport="nfl")
    _insert_rating(conn, YEAR, METHOD, 106, 0.2, 5, 0, 0, sport="nfl")
    _insert_breakdown(conn, YEAR, METHOD, 106, None, None, None, None, None, 0.1, sport="nfl")


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    db_path = _make_db(tmp_path)
    c = get_conn(db_path)
    _build_fixture(c)
    c.commit()
    return c


# ---------------------------------------------------------------------------
# (a) NFL end-to-end
# ---------------------------------------------------------------------------


def test_list_available_years_nfl(conn: sqlite3.Connection) -> None:
    assert list_available_years(conn, METHOD, sport="nfl") == [YEAR, 2024]


def test_resolve_team_nfl(conn: sqlite3.Connection) -> None:
    assert resolve_team(conn, YEAR, "Delta Squad", method=METHOD, sport="nfl") == 101


def test_build_team_case_nfl(conn: sqlite3.Connection) -> None:
    case = build_team_case(conn, YEAR, "Delta Squad", method=METHOD, sport="nfl")
    assert case.team_id == 101
    assert case.team_name == "Delta Squad"
    assert case.rank == 1
    assert case.wins == 2
    assert case.losses == 0
    # classification=NULL for NFL must not raise or otherwise break the case.
    assert len(case.games) == 2


def test_build_comparison_nfl(conn: sqlite3.Connection) -> None:
    comparison = build_comparison(conn, YEAR, "Delta Squad", "Echo Corp", method=METHOD, sport="nfl")
    assert comparison.team_a.team_id == 101
    assert comparison.team_b.team_id == 102
    assert comparison.head_to_head.played is True


# ---------------------------------------------------------------------------
# (b) CFB end-to-end -- confirms unchanged behavior with real classification
# ---------------------------------------------------------------------------


def test_list_available_years_cfb(conn: sqlite3.Connection) -> None:
    assert list_available_years(conn, METHOD, sport="cfb") == [YEAR]


def test_list_available_years_default_sport_is_cfb(conn: sqlite3.Connection) -> None:
    """No pre-#58 call site ever passed `sport` -- the default must keep
    producing the same result as an explicit sport='cfb' call."""
    assert list_available_years(conn, METHOD) == list_available_years(conn, METHOD, sport="cfb")


def test_resolve_team_cfb(conn: sqlite3.Connection) -> None:
    assert resolve_team(conn, YEAR, "Alpha State", method=METHOD, sport="cfb") == 1


def test_resolve_team_default_sport_is_cfb(conn: sqlite3.Connection) -> None:
    assert resolve_team(conn, YEAR, "Alpha State", method=METHOD) == 1


def test_build_team_case_cfb(conn: sqlite3.Connection) -> None:
    case = build_team_case(conn, YEAR, "Alpha State", method=METHOD, sport="cfb")
    assert case.team_id == 1
    assert case.team_name == "Alpha State"
    assert case.rank == 1
    assert case.wins == 2
    assert case.losses == 0
    assert len(case.games) == 2


def test_build_team_case_default_sport_is_cfb(conn: sqlite3.Connection) -> None:
    default_case = build_team_case(conn, YEAR, "Alpha State", method=METHOD)
    explicit_case = build_team_case(conn, YEAR, "Alpha State", method=METHOD, sport="cfb")
    assert default_case == explicit_case


def test_build_comparison_cfb(conn: sqlite3.Connection) -> None:
    comparison = build_comparison(conn, YEAR, "Alpha State", "Bravo Tech", method=METHOD, sport="cfb")
    assert comparison.team_a.team_id == 1
    assert comparison.team_b.team_id == 2
    assert comparison.head_to_head.played is True


def test_build_comparison_default_sport_is_cfb(conn: sqlite3.Connection) -> None:
    default = build_comparison(conn, YEAR, "Alpha State", "Bravo Tech", method=METHOD)
    explicit = build_comparison(conn, YEAR, "Alpha State", "Bravo Tech", method=METHOD, sport="cfb")
    assert default == explicit


# ---------------------------------------------------------------------------
# (c) cross-sport regression -- CFB and NFL rows sharing the same year/method,
# including a deliberately name-colliding team ("Wildcats") in both sports.
# ---------------------------------------------------------------------------


def test_resolve_team_does_not_bleed_across_sports_on_name_collision(
    conn: sqlite3.Connection,
) -> None:
    """Both sports have a team named "Wildcats" for the same year/method.
    Without a sport filter, resolve_team's exact-match stage would find 2
    candidates and raise AmbiguousTeamError for *both* calls below. With the
    filter, each resolves uniquely to its own sport's team_id."""
    assert resolve_team(conn, YEAR, "Wildcats", method=METHOD, sport="cfb") == 4
    assert resolve_team(conn, YEAR, "Wildcats", method=METHOD, sport="nfl") == 104


def test_build_team_case_does_not_bleed_across_sports_on_name_collision(
    conn: sqlite3.Connection,
) -> None:
    cfb_case = build_team_case(conn, YEAR, "Wildcats", method=METHOD, sport="cfb")
    nfl_case = build_team_case(conn, YEAR, "Wildcats", method=METHOD, sport="nfl")
    assert cfb_case.team_id == 4
    assert nfl_case.team_id == 104


def test_list_available_years_does_not_bleed_nfl_only_year_into_cfb(
    conn: sqlite3.Connection,
) -> None:
    cfb_years = list_available_years(conn, METHOD, sport="cfb")
    nfl_years = list_available_years(conn, METHOD, sport="nfl")
    assert 2024 not in cfb_years
    assert 2024 in nfl_years


def test_build_comparison_cross_sport_common_opponent_pool_stays_scoped(
    conn: sqlite3.Connection,
) -> None:
    """Alpha State and Bravo Tech share one real CFB common opponent
    (Charlie U) -- that entry must survive. But no NFL team_id (101-105) may
    ever appear, proving `build_comparison`'s CFB-scoped call doesn't pull
    NFL rows into `_ratings_map`/`_team_games` and quietly attribute an NFL
    opponent's rank/rating to a CFB matchup."""
    comparison = build_comparison(conn, YEAR, "Alpha State", "Bravo Tech", method=METHOD, sport="cfb")
    assert [c.opponent_team_id for c in comparison.common_opponents] == [3]
    nfl_ids = {101, 102, 103, 104, 105}
    assert all(c.opponent_team_id not in nfl_ids for c in comparison.common_opponents)


def test_resolve_team_unknown_year_still_raises_when_only_other_sport_has_it(
    conn: sqlite3.Connection,
) -> None:
    """Year 2024 has ratings only for sport='nfl' -- a cfb-scoped call for
    that year must still raise UnknownYearError, not silently succeed by
    picking up the nfl rows."""
    with pytest.raises(UnknownYearError):
        resolve_team(conn, 2024, "Alpha State", method=METHOD, sport="cfb")


def test_same_team_comparison_error_still_raised_within_one_sport(
    conn: sqlite3.Connection,
) -> None:
    with pytest.raises(SameTeamComparisonError):
        build_comparison(conn, YEAR, "Alpha State", "Alpha State", method=METHOD, sport="cfb")


def test_ambiguous_team_error_within_a_single_sport_still_raised(
    conn: sqlite3.Connection,
) -> None:
    # "Foxtrot" substring-matches only one NFL team -- unique, no error.
    assert resolve_team(conn, YEAR, "Foxtrot", method=METHOD, sport="nfl") == 103


# ---------------------------------------------------------------------------
# (d) issue #100 -- zero matches is UnknownTeamError, never AmbiguousTeamError
# ---------------------------------------------------------------------------


def test_zero_match_query_raises_unknown_team_error(conn: sqlite3.Connection) -> None:
    """"Texas" names a CFB school; under sport="nfl" nothing matches at any
    stage. Before #100 this raised AmbiguousTeamError(query, []) -- "which of
    these did you mean?" with nothing under it."""
    with pytest.raises(UnknownTeamError) as exc_info:
        resolve_team(conn, YEAR, "Texas", method=METHOD, sport="nfl")
    assert exc_info.value.query == "Texas"
    assert exc_info.value.year == YEAR
    assert exc_info.value.sport == "nfl"


def test_zero_match_query_is_not_an_ambiguous_team_error(conn: sqlite3.Connection) -> None:
    """UnknownTeamError subclasses ValueError, not AmbiguousTeamError -- a
    caller that only catches AmbiguousTeamError must not swallow this."""
    assert not issubclass(UnknownTeamError, AmbiguousTeamError)
    with pytest.raises(UnknownTeamError):
        resolve_team(conn, YEAR, "Texas", method=METHOD, sport="nfl")


def test_unknown_team_error_carries_no_suggestion_list(
    conn: sqlite3.Connection,
) -> None:
    """contracts.py: UnknownTeamError deliberately carries only query/year/
    sport. "Texas" under sport="nfl" is the strongest case for a near-miss
    list that exists in this fixture -- a rated lookalike ("Houston Texans")
    sits right there in the same year and sport -- and the error still must
    not offer it, because someone typing "Texas" wants the other league.
    Consumers render a plain not-found state instead.
    """
    with pytest.raises(UnknownTeamError) as exc_info:
        resolve_team(conn, YEAR, "Texas", method=METHOD, sport="nfl")
    error = exc_info.value
    assert not hasattr(error, "suggestions")
    assert error.query == "Texas"
    assert error.year == YEAR
    assert error.sport == "nfl"
    # The lookalike is genuinely rated for this year/sport -- so this test
    # fails if a suggestion pass is ever reintroduced, not because the name
    # is absent from the candidate pool.
    assert resolve_team(conn, YEAR, "Houston Texans", method=METHOD, sport="nfl") == 106


def test_zero_match_query_with_no_lookalike_at_all_is_unknown_team_error(
    conn: sqlite3.Connection,
) -> None:
    """"Zebra" has no counterpart of any kind in the CFB rated set -- still
    UnknownTeamError, emphatically not a crash or an AmbiguousTeamError."""
    with pytest.raises(UnknownTeamError) as exc_info:
        resolve_team(conn, YEAR, "Zebra", method=METHOD, sport="cfb")
    assert exc_info.value.query == "Zebra"
    assert exc_info.value.year == YEAR
    assert exc_info.value.sport == "cfb"


def test_unknown_team_propagates_through_build_team_case_and_comparison(
    conn: sqlite3.Connection,
) -> None:
    with pytest.raises(UnknownTeamError):
        build_team_case(conn, YEAR, "Zebra", method=METHOD, sport="cfb")
    with pytest.raises(UnknownTeamError):
        build_comparison(conn, YEAR, "Alpha State", "Zebra", method=METHOD, sport="cfb")


def test_ambiguous_team_error_never_carries_empty_candidates(
    conn: sqlite3.Connection,
) -> None:
    """Module-wide invariant (contracts.py: `candidates` is always non-empty
    -- "too many matches", never "none"). Sweeps exact-, substring-,
    fuzzy-stage and zero-match queries across both sports."""
    queries = [
        "Alpha State",
        "alpha state",
        "  Alpha State  ",
        "Alpha",
        "a",
        "State",
        "Tech",
        "Wildcats",
        "Foxtrot",
        "Delta Squad",
        "Texas",
        "Zebra",
        "Qqqqqqqqqq",
        "",
    ]
    raised_at_least_one = False
    for sport in ("cfb", "nfl"):
        for query in queries:
            try:
                resolve_team(conn, YEAR, query, method=METHOD, sport=sport)
            except AmbiguousTeamError as e:
                raised_at_least_one = True
                assert e.candidates, f"empty candidates for {query!r} (sport={sport})"
            except UnknownTeamError:
                pass
    assert raised_at_least_one, "expected at least one genuinely ambiguous query in the sweep"


# ---------------------------------------------------------------------------
# (e) issue #83 -- a completed game with equal scores is a tie ("T"), in every
# sport, and is never dropped from the receipts
# ---------------------------------------------------------------------------

TIE_YEAR = 2019


def _build_tie_fixture(conn: sqlite3.Connection, sport: str) -> None:
    """Three teams in their own year, so the shared fixture above is
    untouched:

      week 1  Juliet Draws 17, India Ties 17     (tie)
      week 2  India Ties 10, Kilo Beats 20       (India loses)
      week 3  Juliet Draws 21, Kilo Beats 7      (Juliet wins)

    Juliet is ranked #1, so a tie against it is exactly the case that must
    not be mistaken for a quality win. Ids are offset per sport.
    """
    base = 10 if sport == "cfb" else 110
    india, juliet, kilo = base + 1, base + 2, base + 3
    for tid, name in ((india, "India Ties"), (juliet, "Juliet Draws"), (kilo, "Kilo Beats")):
        _insert_team(conn, tid, name, sport=sport)
    _insert_game(conn, base + 1, TIE_YEAR, juliet, india, "Juliet Draws", "India Ties", 17, 17, week=1, sport=sport)
    _insert_game(conn, base + 2, TIE_YEAR, india, kilo, "India Ties", "Kilo Beats", 10, 20, week=2, sport=sport)
    _insert_game(conn, base + 3, TIE_YEAR, juliet, kilo, "Juliet Draws", "Kilo Beats", 21, 7, week=3, sport=sport)
    _insert_rating(conn, TIE_YEAR, METHOD, juliet, 1.2, 1, 1, 0, sport=sport, ties=1)
    _insert_rating(conn, TIE_YEAR, METHOD, kilo, 0.9, 2, 1, 1, sport=sport)
    _insert_rating(conn, TIE_YEAR, METHOD, india, 0.4, 3, 0, 1, sport=sport, ties=1)
    conn.commit()


@pytest.mark.parametrize("sport", ["cfb", "nfl"])
def test_build_team_case_lists_an_equal_score_game_as_a_tie(
    conn: sqlite3.Connection, sport: Sport
) -> None:
    _build_tie_fixture(conn, sport)

    case = build_team_case(conn, TIE_YEAR, "India Ties", method=METHOD, sport=sport)

    assert (case.wins, case.losses, case.ties) == (0, 1, 1)
    assert [(g.opponent_name, g.result, g.team_score, g.opponent_score) for g in case.games] == [
        ("Juliet Draws", "T", 17, 17),
        ("Kilo Beats", "L", 10, 20),
    ]


@pytest.mark.parametrize("sport", ["cfb", "nfl"])
def test_tie_is_never_a_quality_win_or_worst_loss(
    conn: sqlite3.Connection, sport: Sport
) -> None:
    _build_tie_fixture(conn, sport)

    # India tied the #1 team and lost to #2: the tie against #1 is neither a
    # quality win nor the worst loss, even though #1 is the best-ranked
    # opponent on the schedule.
    india = build_team_case(conn, TIE_YEAR, "India Ties", method=METHOD, sport=sport)
    assert india.quality_wins == []
    assert india.worst_loss is not None
    assert (india.worst_loss.result, india.worst_loss.opponent_name) == ("L", "Kilo Beats")

    # Juliet tied the #3 team and beat #2: only the win is a quality win, and
    # with no loss there is no worst loss at all -- the tie does not fill it.
    juliet = build_team_case(conn, TIE_YEAR, "Juliet Draws", method=METHOD, sport=sport)
    assert [(g.result, g.opponent_name) for g in juliet.quality_wins] == [("W", "Kilo Beats")]
    assert juliet.worst_loss is None
    assert juliet.ties == 1


def test_completed_game_with_null_scores_is_still_skipped(conn: sqlite3.Connection) -> None:
    _build_tie_fixture(conn, "cfb")
    _insert_game(conn, 19, TIE_YEAR, 11, 13, "India Ties", "Kilo Beats", None, None, week=4)
    conn.commit()

    case = build_team_case(conn, TIE_YEAR, "India Ties", method=METHOD, sport="cfb")
    assert len(case.games) == 2


def test_cfb_completed_zero_zero_row_is_reported_as_a_tie(conn: sqlite3.Connection) -> None:
    """One definition in every sport (contracts.TeamRating). CFB's completed
    0-0 "unreported" rows are bad data, handled at ingest by nulling their
    scores (#128); a 0-0 row that does reach the evidence layer is a tie, with
    no sport exception carved out here."""
    _insert_team(conn, 21, "Lima Unreported", sport="cfb")
    _insert_team(conn, 22, "Mike Unreported", sport="cfb")
    _insert_game(conn, 21, TIE_YEAR, 21, 22, "Lima Unreported", "Mike Unreported", 0, 0)
    _insert_rating(conn, TIE_YEAR, METHOD, 21, 0.5, 1, 0, 0, sport="cfb", ties=1)
    _insert_rating(conn, TIE_YEAR, METHOD, 22, 0.5, 2, 0, 0, sport="cfb", ties=1)
    conn.commit()

    case = build_team_case(conn, TIE_YEAR, "Lima Unreported", method=METHOD, sport="cfb")
    assert [(g.result, g.team_score, g.opponent_score) for g in case.games] == [("T", 0, 0)]
    assert case.ties == 1


@pytest.mark.parametrize("sport", ["cfb", "nfl"])
def test_build_comparison_common_opponent_reports_a_tie(
    conn: sqlite3.Connection, sport: Sport
) -> None:
    _build_tie_fixture(conn, sport)

    # India is the common opponent: Juliet tied it, Kilo beat it.
    comparison = build_comparison(
        conn, TIE_YEAR, "Juliet Draws", "Kilo Beats", method=METHOD, sport=sport
    )
    assert [
        (
            c.opponent_name,
            [(m.result, m.team_score, m.opponent_score) for m in c.team_a_meetings],
            [(m.result, m.team_score, m.opponent_score) for m in c.team_b_meetings],
        )
        for c in comparison.common_opponents
    ] == [("India Ties", [("T", 17, 17)], [("W", 20, 10)])]
    assert (comparison.team_a.wins, comparison.team_a.losses, comparison.team_a.ties) == (1, 0, 1)
    assert comparison.team_b.ties == 0
    assert (
        "vs common opponent India Ties (rank 3): Juliet Draws went T 17-17 (week 1); "
        "Kilo Beats went W 20-10 (week 2)."
        in comparison.verdict
    )


# ---------------------------------------------------------------------------
# (e2) issue #130 -- a common opponent carries EVERY meeting per side, in
# chronological order, never just the last one
# ---------------------------------------------------------------------------

REMATCH_YEAR = 2018


def _build_rematch_fixture(conn: sqlite3.Connection, sport: str) -> None:
    """Three teams in their own year. Oscar meets the shared opponent
    (Papa) three times -- twice in the regular season and once more in the
    postseason -- while Quebec meets Papa once:

      regular week 9   Oscar Twice 24, Papa Shared 27      (Oscar loses)
      regular week 3   Papa Shared 10, Quebec Once 13      (Quebec wins)
      regular week 2   Papa Shared 20, Oscar Twice 21      (Oscar wins)
      postseason wk 1  Papa Shared 14, Oscar Twice 14      (tie)

    Rows are inserted out of order on purpose, and the postseason meeting
    has the lowest week number, so an implementation that keeps insertion
    order or sorts by bare week gets the list wrong. Ids offset per sport.
    """
    base = 30 if sport == "cfb" else 130
    oscar, papa, quebec = base + 1, base + 2, base + 3
    for tid, name in ((oscar, "Oscar Twice"), (papa, "Papa Shared"), (quebec, "Quebec Once")):
        _insert_team(conn, tid, name, sport=sport)
    _insert_game(conn, base + 1, REMATCH_YEAR, oscar, papa, "Oscar Twice", "Papa Shared", 24, 27, week=9, sport=sport)
    _insert_game(conn, base + 2, REMATCH_YEAR, papa, quebec, "Papa Shared", "Quebec Once", 10, 13, week=3, sport=sport)
    _insert_game(conn, base + 3, REMATCH_YEAR, papa, oscar, "Papa Shared", "Oscar Twice", 20, 21, week=2, sport=sport)
    _insert_game(
        conn, base + 4, REMATCH_YEAR, papa, oscar, "Papa Shared", "Oscar Twice", 14, 14,
        week=1, season_type="postseason", sport=sport,
    )
    _insert_rating(conn, REMATCH_YEAR, METHOD, quebec, 1.3, 1, 1, 0, sport=sport)
    _insert_rating(conn, REMATCH_YEAR, METHOD, papa, 1.0, 2, 1, 2, sport=sport, ties=1)
    _insert_rating(conn, REMATCH_YEAR, METHOD, oscar, 0.7, 3, 1, 1, sport=sport, ties=1)
    conn.commit()


@pytest.mark.parametrize("sport", ["cfb", "nfl"])
def test_build_comparison_common_opponent_lists_every_meeting_chronologically(
    conn: sqlite3.Connection, sport: Sport
) -> None:
    _build_rematch_fixture(conn, sport)

    comparison = build_comparison(
        conn, REMATCH_YEAR, "Oscar Twice", "Quebec Once", method=METHOD, sport=sport
    )

    assert [c.opponent_name for c in comparison.common_opponents] == ["Papa Shared"]
    papa = comparison.common_opponents[0]
    assert len(papa.team_a_meetings) == 3
    assert len(papa.team_b_meetings) == 1
    # Regular season by week, then postseason -- the postseason tie sorts
    # last despite its week number being the smallest.
    assert [
        (m.result, m.team_score, m.opponent_score, m.week, m.season_type)
        for m in papa.team_a_meetings
    ] == [
        ("W", 21, 20, 2, "regular"),
        ("L", 24, 27, 9, "regular"),
        ("T", 14, 14, 1, "postseason"),
    ]
    assert [
        (m.result, m.team_score, m.opponent_score, m.week, m.season_type)
        for m in papa.team_b_meetings
    ] == [("W", 13, 10, 3, "regular")]

    # Swapping the sides swaps the lists.
    swapped = build_comparison(
        conn, REMATCH_YEAR, "Quebec Once", "Oscar Twice", method=METHOD, sport=sport
    )
    assert swapped.common_opponents[0].team_a_meetings == papa.team_b_meetings
    assert swapped.common_opponents[0].team_b_meetings == papa.team_a_meetings


@pytest.mark.parametrize("sport", ["cfb", "nfl"])
def test_verdict_states_every_meeting_against_a_common_opponent(
    conn: sqlite3.Connection, sport: Sport
) -> None:
    """A two-meeting common opponent used to read as one result ("went L").
    Each meeting's result letter and team-perspective score pair must appear."""
    _build_rematch_fixture(conn, sport)

    comparison = build_comparison(
        conn, REMATCH_YEAR, "Oscar Twice", "Quebec Once", method=METHOD, sport=sport
    )

    assert (
        "vs common opponent Papa Shared (rank 2): "
        "Oscar Twice went W 21-20 (week 2), L 24-27 (week 9), T 14-14 (postseason week 1); "
        "Quebec Once went W 13-10 (week 3)."
    ) in comparison.verdict
    for pair in ("21-20", "24-27", "14-14", "13-10"):
        assert pair in comparison.verdict
    # Never the opponent-perspective pair.
    assert "20-21" not in comparison.verdict
    assert "27-24" not in comparison.verdict


@pytest.mark.parametrize("sport", ["cfb", "nfl"])
def test_verdict_describes_a_tied_head_to_head_meeting(
    conn: sqlite3.Connection, sport: Sport
) -> None:
    """`head_to_head` already modeled the tie (winner=None); the verdict only
    had a sentence for a winner, so it said nothing about the meeting."""
    _build_tie_fixture(conn, sport)

    comparison = build_comparison(
        conn, TIE_YEAR, "India Ties", "Juliet Draws", method=METHOD, sport=sport
    )
    assert [m.winner for m in comparison.head_to_head.meetings] == [None]
    assert comparison.verdict.startswith(
        "India Ties and Juliet Draws tied head-to-head 17-17 "
        "(Juliet Draws vs India Ties, week 1)."
    )
    assert "did not play each other" not in comparison.verdict


def test_verdict_for_a_decided_head_to_head_is_unchanged(conn: sqlite3.Connection) -> None:
    """Regression guard for existing CFB prose: no tie, same wording as
    before #83."""
    comparison = build_comparison(conn, YEAR, "Alpha State", "Bravo Tech", method=METHOD, sport="cfb")
    assert comparison.verdict.startswith(
        "Alpha State beat Bravo Tech head-to-head 30-10 (Alpha State vs Bravo Tech, week 1). "
        "vs common opponent Charlie U (rank 3): Alpha State went W 40-3 (week 1); "
        "Bravo Tech went W 20-17 (week 1)."
    )
    assert "tied" not in comparison.verdict


# ---------------------------------------------------------------------------
# issue #122 -- a decided head-to-head sentence states the winner's points
# first, whoever was home and whether or not the site was neutral
# ---------------------------------------------------------------------------

H2H_YEAR = 2021


def _build_winner_first_fixture(conn: sqlite3.Connection, sport: str) -> None:
    """Three separate pairs in their own year, so each comparison has exactly
    one meeting and the shared fixture above is untouched:

      week 5  Home Losers 17, Road Winners 24          (away team wins)
      week 6  Home Winners 35, Visiting Losers 14      (home team wins)
      week 7  Nominal Host 8, Nominal Visitor 43       (neutral site, nominal away wins)

    Ids are offset per sport.
    """
    base = 40 if sport == "cfb" else 140
    teams = (
        (base, "Home Losers"),
        (base + 1, "Road Winners"),
        (base + 2, "Home Winners"),
        (base + 3, "Visiting Losers"),
        (base + 4, "Nominal Host"),
        (base + 5, "Nominal Visitor"),
    )
    for rank, (tid, name) in enumerate(teams, start=1):
        _insert_team(conn, tid, name, sport=sport)
        _insert_rating(conn, H2H_YEAR, METHOD, tid, 1.0 - rank / 10, rank, 1, 1, sport=sport)
    _insert_game(conn, base + 1, H2H_YEAR, base, base + 1, "Home Losers", "Road Winners", 17, 24, week=5, sport=sport)
    _insert_game(
        conn, base + 2, H2H_YEAR, base + 2, base + 3, "Home Winners", "Visiting Losers", 35, 14, week=6, sport=sport
    )
    _insert_game(
        conn, base + 3, H2H_YEAR, base + 4, base + 5, "Nominal Host", "Nominal Visitor", 8, 43,
        week=7, sport=sport, neutral_site=True,
    )
    conn.commit()


_WINNER_FIRST_CASES = [
    pytest.param(
        "Road Winners",
        "Home Losers",
        "Road Winners beat Home Losers head-to-head 24-17 (Home Losers vs Road Winners, week 5).",
        False,
        id="away-winner",
    ),
    pytest.param(
        "Home Winners",
        "Visiting Losers",
        "Home Winners beat Visiting Losers head-to-head 35-14 (Home Winners vs Visiting Losers, week 6).",
        False,
        id="home-winner",
    ),
    pytest.param(
        "Nominal Visitor",
        "Nominal Host",
        "Nominal Visitor beat Nominal Host head-to-head 43-8 (Nominal Host vs Nominal Visitor, week 7).",
        True,
        id="neutral-site-nominal-away-winner",
    ),
]


@pytest.mark.parametrize("winner_side", ["team_a", "team_b"])
@pytest.mark.parametrize(("winner", "loser", "expected", "neutral_site"), _WINNER_FIRST_CASES)
@pytest.mark.parametrize("sport", ["cfb", "nfl"])
def test_decided_head_to_head_states_the_winners_points_first(
    conn: sqlite3.Connection,
    sport: Sport,
    winner: str,
    loser: str,
    expected: str,
    neutral_site: bool,
    winner_side: str,
) -> None:
    """The score after "X beat Y" reads as X's points first. Before #122 it was
    always home-away, so every road win read backwards ("beat ... 17-24").
    Both decided branches are covered: the winner as team_a and as team_b."""
    _build_winner_first_fixture(conn, sport)
    team_a, team_b = (winner, loser) if winner_side == "team_a" else (loser, winner)

    comparison = build_comparison(conn, H2H_YEAR, team_a, team_b, method=METHOD, sport=sport)

    [meeting] = comparison.head_to_head.meetings
    assert meeting.winner == winner
    assert meeting.neutral_site is neutral_site
    assert comparison.verdict.startswith(expected + " ")


# ---------------------------------------------------------------------------
# (f) issue #95 -- the verdict's rating format is a per-method decision
# ---------------------------------------------------------------------------

# The fixed opening of the Alpha State / Bravo Tech verdict. Only the closing
# "rates higher overall" sentence depends on the method.
_ALPHA_BRAVO_PREFIX = (
    "Alpha State beat Bravo Tech head-to-head 30-10 (Alpha State vs Bravo Tech, week 1). "
    "vs common opponent Charlie U (rank 3): Alpha State went W 40-3 (week 1); "
    "Bravo Tech went W 20-17 (week 1). "
)


def _insert_cfb_cycle_ratings(
    conn: sqlite3.Connection, method: str, ratings: tuple[float, float, float]
) -> None:
    """Rate the CFB win cycle (ids 1-3, ranks 1-3) under `method`, with no
    `rating_breakdowns` rows -- the shape Elo really stores (PR #93)."""
    for rank, (team_id, rating) in enumerate(zip((1, 2, 3), ratings, strict=True), start=1):
        _insert_rating(conn, YEAR, method, team_id, rating, rank, 1, 1, sport="cfb")
    conn.commit()


def test_verdict_rating_formats_cover_exactly_the_registered_methods() -> None:
    """The format is a checked decision for every registered method. Adding a
    method to `contracts.Method` without choosing its verdict precision turns
    this red, so it can never silently inherit Keener's `.6f`. Order included,
    matching tests/test_contract_vocabularies.py's convention for the alias."""
    assert tuple(proof.VERDICT_RATING_FORMATS) == typing.get_args(Method)


def test_keener_verdict_text_is_byte_identical(conn: sqlite3.Connection) -> None:
    """Exact full string, pinned from the pre-#95 output. Keener's six decimal
    places suit its sum-to-1 eigenvector and must not move."""
    comparison = build_comparison(conn, YEAR, "Alpha State", "Bravo Tech", method="keener")
    assert comparison.verdict == (
        _ALPHA_BRAVO_PREFIX + "Alpha State rates higher overall (1.500000 vs 1.000000, rank 1 vs 2)."
    )


@pytest.mark.parametrize("method", ["elo", "elo_career"])
def test_elo_verdict_uses_one_decimal_place(conn: sqlite3.Connection, method: str) -> None:
    """Elo lives around 1100-2000. `.6f` printed `1523.456789`, false
    precision nobody reads. One decimal place separates most neighbouring
    teams. It can't separate every pair (near-ties are #149)."""
    _insert_cfb_cycle_ratings(conn, method, (1523.456789, 1498.04, 1400.0))

    comparison = build_comparison(conn, YEAR, "Alpha State", "Bravo Tech", method=method)

    assert comparison.verdict == (
        _ALPHA_BRAVO_PREFIX + "Alpha State rates higher overall (1523.5 vs 1498.0, rank 1 vs 2)."
    )


@pytest.mark.parametrize("method", typing.get_args(Method))
def test_verdict_precision_is_read_from_the_format_table(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch, method: Method
) -> None:
    """The table is the single source of the verdict's precision. Checking
    that its keys and values are right proves nothing if the verdict computes
    a precision some other way (from the method's name, or the rating's
    magnitude) that happens to agree today. A precision no method uses must
    come straight through."""
    if method != "keener":  # the shared fixture already rates the cycle under keener
        _insert_cfb_cycle_ratings(conn, method, (1523.456789, 1498.04, 1400.0))
    team_a = build_team_case(conn, YEAR, "Alpha State", method=method)
    team_b = build_team_case(conn, YEAR, "Bravo Tech", method=method)

    monkeypatch.setitem(proof.VERDICT_RATING_FORMATS, method, ".3f")
    comparison = build_comparison(conn, YEAR, "Alpha State", "Bravo Tech", method=method)

    assert comparison.verdict == (
        _ALPHA_BRAVO_PREFIX + "Alpha State rates higher overall "
        f"({team_a.rating:.3f} vs {team_b.rating:.3f}, rank 1 vs 2)."
    )


def test_unregistered_method_verdict_raises_instead_of_falling_back(
    conn: sqlite3.Connection,
) -> None:
    """Rows for a method with no registered format are reachable: a database
    written by a newer or experimental engine. The verdict must refuse to
    guess a precision rather than silently printing `.6f`."""
    _insert_cfb_cycle_ratings(conn, "glicko", (1523.456789, 1498.04, 1400.0))

    with pytest.raises(ValueError, match="glicko"):
        build_comparison(conn, YEAR, "Alpha State", "Bravo Tech", method="glicko")

    # Scoped to the verdict's number formatting: the rest of the evidence
    # surface does no formatting and is unchanged for such a method.
    assert build_team_case(conn, YEAR, "Alpha State", method="glicko").rating == 1523.456789


# ---------------------------------------------------------------------------
# (g) issue #183 -- the Elo ledger is read back from elo_ledger_steps /
# elo_ledger_configs, exactly as stored, scoped to (year, method, sport, team)
# ---------------------------------------------------------------------------

# Deliberately non-round, all-distinct values so a swapped or rounded field
# cannot pass an equality check by coincidence.
_ELO_CONFIG = {
    "starting_rating": 1500.125,
    "k": 20.5,
    "hfa": 55.25,
    "scale": 400.75,
    "mov_scale": 2.2,
    "mov_autocorr": 0.001,
}


def _insert_ledger_config(
    conn: sqlite3.Connection,
    year: int,
    method: str,
    sport: str,
    starting_rating: float,
    k: float,
    hfa: float,
    scale: float,
    mov_scale: float,
    mov_autocorr: float,
) -> None:
    conn.execute(
        """
        INSERT INTO elo_ledger_configs (
            year, method, sport, starting_rating, k, hfa, scale, mov_scale,
            mov_autocorr, computed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'test')
        """,
        (year, method, sport, starting_rating, k, hfa, scale, mov_scale, mov_autocorr),
    )


def _insert_ledger_step(
    conn: sqlite3.Connection,
    year: int,
    method: str,
    sport: str,
    team_id: int,
    step: EloGameStep,
) -> None:
    """Store `step` for `team_id`. `step.opponent_name` is not stored -- the
    table has no such column; the evidence layer resolves it from `teams`."""
    conn.execute(
        """
        INSERT INTO elo_ledger_steps (
            year, method, sport, team_id, game_number, week, season_type,
            start_date, opponent_team_id, venue, team_points, opponent_points,
            result, rating_before, opponent_rating_before, home_field_adjustment,
            rating_gap, win_expectancy, mov_multiplier, shift, rating_after,
            computed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'test')
        """,
        (
            year,
            method,
            sport,
            team_id,
            step.game_number,
            step.week,
            step.season_type,
            step.start_date,
            step.opponent_team_id,
            step.venue,
            step.team_points,
            step.opponent_points,
            step.result,
            step.rating_before,
            step.opponent_rating_before,
            step.home_field_adjustment,
            step.rating_gap,
            step.win_expectancy,
            step.mov_multiplier,
            step.shift,
            step.rating_after,
        ),
    )


# Alpha State (id 1): beat Bravo Tech at home, then won at Charlie U in the
# postseason. Values are stand-ins, not a real walk -- this layer copies what
# is stored and must not recompute or validate the arithmetic.
_ALPHA_STEP_1 = EloGameStep(
    game_number=1,
    opponent_team_id=2,
    venue="home",
    team_points=30,
    opponent_points=10,
    result="W",
    rating_before=1500.125,
    opponent_rating_before=1499.0625,
    home_field_adjustment=55.25,
    rating_gap=56.3125,
    win_expectancy=0.580123456789,
    mov_multiplier=1.87654321,
    shift=16.1234567891,
    rating_after=1516.2484567891,
    week=1,
    season_type="regular",
    start_date="2023-09-02T16:00:00.000Z",
    opponent_name="Bravo Tech",
)
_ALPHA_STEP_2 = EloGameStep(
    game_number=2,
    opponent_team_id=3,
    venue="away",
    team_points=40,
    opponent_points=3,
    result="W",
    rating_before=1516.2484567891,
    opponent_rating_before=1483.9876,
    home_field_adjustment=-55.25,
    rating_gap=-22.9891432109,
    win_expectancy=0.467012345678,
    mov_multiplier=2.3456789012,
    shift=25.6543210987,
    rating_after=1541.9027778878,
    week=None,
    season_type="postseason",
    start_date=None,
    opponent_name="Charlie U",
)
# Bravo Tech (id 2), for the comparison test: lost at Alpha, beat Charlie on
# a neutral field.
_BRAVO_STEP_1 = EloGameStep(
    game_number=1,
    opponent_team_id=1,
    venue="away",
    team_points=10,
    opponent_points=30,
    result="L",
    rating_before=1499.0625,
    opponent_rating_before=1500.125,
    home_field_adjustment=-55.25,
    rating_gap=-56.3125,
    win_expectancy=0.419876543211,
    mov_multiplier=1.87654321,
    shift=-16.1234567891,
    rating_after=1482.9390432109,
    week=1,
    season_type="regular",
    start_date="2023-09-02T16:00:00.000Z",
    opponent_name="Alpha State",
)
_BRAVO_STEP_2 = EloGameStep(
    game_number=2,
    opponent_team_id=3,
    venue="neutral",
    team_points=20,
    opponent_points=17,
    result="W",
    rating_before=1482.9390432109,
    opponent_rating_before=1483.9876,
    home_field_adjustment=0.0,
    rating_gap=-1.0485567891,
    win_expectancy=0.498490000001,
    mov_multiplier=0.9876543,
    shift=10.3123456789,
    rating_after=1493.2513888898,
    week=2,
    season_type="regular",
    start_date="2023-09-09T19:30:00.000Z",
    opponent_name="Charlie U",
)


def _insert_elo_ledger_fixture(conn: sqlite3.Connection) -> None:
    """Elo ratings for the CFB cycle plus a ledger for Alpha State and Bravo
    Tech. Alpha's steps are inserted in reverse game_number order, so row
    order and game order disagree."""
    _insert_cfb_cycle_ratings(conn, "elo", (1541.9027778878, 1493.2513888898, 1400.0))
    _insert_ledger_config(conn, YEAR, "elo", "cfb", **_ELO_CONFIG)
    _insert_ledger_step(conn, YEAR, "elo", "cfb", 1, _ALPHA_STEP_2)
    _insert_ledger_step(conn, YEAR, "elo", "cfb", 1, _ALPHA_STEP_1)
    _insert_ledger_step(conn, YEAR, "elo", "cfb", 2, _BRAVO_STEP_1)
    _insert_ledger_step(conn, YEAR, "elo", "cfb", 2, _BRAVO_STEP_2)
    conn.commit()


def _expected_ledger(*steps: EloGameStep) -> EloLedger:
    return EloLedger(**_ELO_CONFIG, steps=list(steps))


def test_elo_case_ledger_is_ordered_resolved_and_copied_exactly(
    conn: sqlite3.Connection,
) -> None:
    """(a) Steps come back in game_number order despite reverse insertion,
    every opponent_name is resolved from `teams`, the constants are the config
    row's, and every stored field is equal to what was inserted -- including
    NULL week / start_date and a non-regular season_type."""
    _insert_elo_ledger_fixture(conn)

    case = build_team_case(conn, YEAR, "Alpha State", method="elo", sport="cfb")

    assert case.elo_ledger is not None
    assert [s.game_number for s in case.elo_ledger.steps] == [1, 2]
    assert [s.opponent_name for s in case.elo_ledger.steps] == ["Bravo Tech", "Charlie U"]
    assert case.elo_ledger == _expected_ledger(_ALPHA_STEP_1, _ALPHA_STEP_2)


def test_keener_case_has_no_elo_ledger_even_when_elo_ledger_rows_exist(
    conn: sqlite3.Connection,
) -> None:
    """(b) Keener writes no ledger. Elo ledger rows for the same team, year
    and sport must not leak into a keener case."""
    _insert_elo_ledger_fixture(conn)

    case = build_team_case(conn, YEAR, "Alpha State", method="keener", sport="cfb")

    assert case.elo_ledger is None


def test_elo_ratings_without_any_ledger_rows_give_no_ledger(
    conn: sqlite3.Connection,
) -> None:
    """(b) A db whose elo ratings predate #183 has no rows in either ledger
    table: that is "no ledger", not a corrupt db."""
    _insert_cfb_cycle_ratings(conn, "elo", (1523.456789, 1498.04, 1400.0))

    case = build_team_case(conn, YEAR, "Alpha State", method="elo", sport="cfb")

    assert case.elo_ledger is None


def test_build_comparison_carries_each_teams_own_ledger(conn: sqlite3.Connection) -> None:
    """(c) ComparisonTeamSummary.elo_ledger is the same ledger as that team's
    TeamCase.elo_ledger, for both sides, and neither side gets the other's."""
    _insert_elo_ledger_fixture(conn)

    comparison = build_comparison(conn, YEAR, "Alpha State", "Bravo Tech", method="elo", sport="cfb")

    assert comparison.team_a.elo_ledger == _expected_ledger(_ALPHA_STEP_1, _ALPHA_STEP_2)
    assert comparison.team_b.elo_ledger == _expected_ledger(_BRAVO_STEP_1, _BRAVO_STEP_2)


def test_keener_comparison_carries_no_ledgers(conn: sqlite3.Connection) -> None:
    comparison = build_comparison(conn, YEAR, "Alpha State", "Bravo Tech", method="keener")
    assert comparison.team_a.elo_ledger is None
    assert comparison.team_b.elo_ledger is None


def test_ledger_steps_without_a_config_row_raise_naming_the_config_table(
    conn: sqlite3.Connection,
) -> None:
    """(d) Steps with no config row: the constants are missing. Inventing
    them (or dropping the ledger) would misreport a corrupt db."""
    _insert_cfb_cycle_ratings(conn, "elo", (1541.9027778878, 1493.2513888898, 1400.0))
    _insert_ledger_step(conn, YEAR, "elo", "cfb", 1, _ALPHA_STEP_1)
    conn.commit()

    with pytest.raises(ValueError, match="elo_ledger_configs"):
        build_team_case(conn, YEAR, "Alpha State", method="elo", sport="cfb")


def test_config_row_without_steps_for_this_team_raises_naming_the_steps_table(
    conn: sqlite3.Connection,
) -> None:
    """(d) A config row says a ledger was written for this (year, method,
    sport), so every rated team must have steps. Charlie U (id 3) is rated but
    has none, while its neighbours do."""
    _insert_elo_ledger_fixture(conn)

    with pytest.raises(ValueError, match="elo_ledger_steps"):
        build_team_case(conn, YEAR, "Charlie U", method="elo", sport="cfb")


def test_ledger_step_with_an_opponent_missing_from_teams_raises(
    conn: sqlite3.Connection,
) -> None:
    """A step whose opponent has no `teams` row is a corrupt db (the column
    references teams(id)). It must not be silently dropped from the ledger or
    shown with a blank name."""
    _insert_elo_ledger_fixture(conn)
    conn.execute("PRAGMA foreign_keys = OFF")
    orphan = dataclasses.replace(_ALPHA_STEP_2, game_number=3, opponent_team_id=999)
    _insert_ledger_step(conn, YEAR, "elo", "cfb", 1, orphan)
    conn.commit()

    with pytest.raises(ValueError, match="teams"):
        build_team_case(conn, YEAR, "Alpha State", method="elo", sport="cfb")


@pytest.mark.parametrize(
    ("decoy_year", "decoy_method", "decoy_sport", "decoy_team_id"),
    [
        (YEAR, "elo", "cfb", 3),  # another team
        (YEAR - 1, "elo", "cfb", 1),  # another year
        (YEAR, "elo_career", "cfb", 1),  # another method
        (YEAR, "elo", "nfl", 1),  # another sport
    ],
    ids=["other-team", "other-year", "other-method", "other-sport"],
)
def test_ledger_rows_outside_the_cases_scope_never_appear(
    conn: sqlite3.Connection,
    decoy_year: int,
    decoy_method: str,
    decoy_sport: str,
    decoy_team_id: int,
) -> None:
    """(e) One decoy step (game_number 3, so it would extend the real ledger
    rather than collide with it) plus a decoy config with different constants,
    keyed one dimension away from Alpha State's (YEAR, elo, cfb) ledger."""
    _insert_elo_ledger_fixture(conn)
    decoy_step = dataclasses.replace(_ALPHA_STEP_2, game_number=3, shift=-999.0, opponent_team_id=2)
    _insert_ledger_step(conn, decoy_year, decoy_method, decoy_sport, decoy_team_id, decoy_step)
    if (decoy_year, decoy_method, decoy_sport) != (YEAR, "elo", "cfb"):
        _insert_ledger_config(
            conn, decoy_year, decoy_method, decoy_sport, **{k: v + 1 for k, v in _ELO_CONFIG.items()}
        )
    conn.commit()

    case = build_team_case(conn, YEAR, "Alpha State", method="elo", sport="cfb")

    assert case.elo_ledger == _expected_ledger(_ALPHA_STEP_1, _ALPHA_STEP_2)
