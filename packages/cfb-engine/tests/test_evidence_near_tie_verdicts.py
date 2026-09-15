"""Issue #149 -- a verdict never names a leader beside two identical numbers.

`VERDICT_RATING_FORMATS` prints keener to six places and Elo to one, and no
fixed precision rules out a printed dead heat: two ratings that differ but
round to the same string. The founder's decision (#149, option 2) keeps the
precision and changes the wording. When the ratings differ but print
identically the leader clause reads "rates a hair higher overall"; when they
print differently it stays "rates higher overall", byte for byte.

These tests enumerate the REAL near-tie pairs in the regression fixtures
rather than a synthetic one, so they can't pass vacuously: both fixtures are
rated under every method with the real pipeline (the committed fixtures hold
no `ratings` rows), and every ordered pair whose ratings differ but print
identically is compared. The colocated unit twin in evidence/test_proof.py
covers the same sentence on a hand-built cycle.
"""

from __future__ import annotations

import itertools
import sqlite3
import typing
from dataclasses import dataclass

import pytest

from cfb_strength.contracts import Method, Sport
from cfb_strength.db.connection import ensure_schema
from cfb_strength.evidence.proof import VERDICT_RATING_FORMATS, build_comparison
from cfb_strength.ratings.compute_ratings import compute_and_store

METHODS: tuple[str, ...] = typing.get_args(Method)
SPORTS: tuple[str, ...] = typing.get_args(Sport)

# Written out by hand rather than read from proof.py, so the sentence under
# test is pinned by the test and not by the code it checks.
VERDICT_DECIMALS: dict[str, int] = {"keener": 6, "elo": 1, "elo_career": 1}

CONN_FIXTURES: dict[str, str] = {"cfb": "regression_conn", "nfl": "nfl_regression_conn"}

# Measured on the committed fixtures at 2db75a6 (coordinator and this suite
# agree): ordered (team_a, team_b) pairs within one (year, sport, method)
# whose ratings differ but print identically. Exact-equal pairs: none.
#   cfb: keener 56, elo 20, elo_career 8
#   nfl: keener 0, elo 0, elo_career 2
# Only the per-method non-emptiness is asserted (see
# test_every_method_has_a_real_near_tie_to_prove_against); the counts are
# documentation, since a ratings change could legitimately move them.


@dataclass(frozen=True)
class NearTiePair:
    year: int
    team_a: str
    team_b: str
    rating_a: float
    rating_b: float
    rank_a: int
    rank_b: int
    printed: str  # the one string both ratings format to


@dataclass(frozen=True)
class RatedFixture:
    conn: sqlite3.Connection
    sport: Sport
    seasons: list[int]


@pytest.fixture(params=SPORTS, ids=list(SPORTS))
def rated_fixture(request: pytest.FixtureRequest) -> RatedFixture:
    """One league's regression fixture with every registered method rated for
    every season it holds, via the real pipeline."""
    sport = typing.cast(Sport, request.param)
    conn: sqlite3.Connection = request.getfixturevalue(CONN_FIXTURES[sport])
    ensure_schema(conn)
    seasons = [
        int(row["season"])
        for row in conn.execute(
            "SELECT DISTINCT season FROM games WHERE sport = ? ORDER BY season", (sport,)
        )
    ]
    assert seasons, sport
    for method in METHODS:
        for year in seasons:
            compute_and_store(conn, year, method, sport=sport)
    return RatedFixture(conn, sport, seasons)


def _rated_rows(conn: sqlite3.Connection, year: int, method: str, sport: str) -> list[sqlite3.Row]:
    rows = conn.execute(
        "SELECT t.school AS school, r.rating AS rating, r.rank AS rank "
        "FROM ratings r JOIN teams t ON t.id = r.team_id "
        "WHERE r.year = ? AND r.method = ? AND r.sport = ? "
        "ORDER BY r.rank, t.school",
        (year, method, sport),
    ).fetchall()
    assert rows, (year, method, sport)
    return rows


def _near_tie_pairs(fixture: RatedFixture, method: str) -> list[NearTiePair]:
    """Every ordered pair in one league and method whose stored ratings differ
    but print identically at the method's format. Compares the formatted
    strings, never a float epsilon: the printed string is what the reader
    sees, so it is the only definition of "looks tied" that matters."""
    decimals = VERDICT_DECIMALS[method]
    pairs: list[NearTiePair] = []
    for year in fixture.seasons:
        rows = _rated_rows(fixture.conn, year, method, fixture.sport)
        for a, b in itertools.permutations(rows, 2):
            rating_a, rating_b = float(a["rating"]), float(b["rating"])
            printed_a, printed_b = f"{rating_a:.{decimals}f}", f"{rating_b:.{decimals}f}"
            if rating_a != rating_b and printed_a == printed_b:
                pairs.append(
                    NearTiePair(
                        year,
                        str(a["school"]),
                        str(b["school"]),
                        rating_a,
                        rating_b,
                        int(a["rank"]),
                        int(b["rank"]),
                        printed_a,
                    )
                )
    return pairs


def _leader_clause(
    leader: str, printed_a: str, printed_b: str, rank_a: int, rank_b: int, *, near_tie: bool
) -> str:
    hedge = "a hair " if near_tie else ""
    return (
        f"{leader} rates {hedge}higher overall ({printed_a} vs {printed_b}, "
        f"rank {rank_a} vs {rank_b})."
    )


def test_hand_written_decimals_cover_exactly_the_registered_methods() -> None:
    assert tuple(VERDICT_DECIMALS) == METHODS
    assert tuple(VERDICT_RATING_FORMATS) == METHODS
    assert tuple(CONN_FIXTURES) == SPORTS


def test_every_method_has_a_real_near_tie_to_prove_against(
    regression_conn: sqlite3.Connection, nfl_regression_conn: sqlite3.Connection
) -> None:
    """The sentinel that keeps the sweep below from passing vacuously: across
    both leagues, every registered method has at least one real near-tie in
    the committed fixtures (CFB alone carries them for every method today).
    If a ratings change ever empties one, this goes red and the method needs
    a new real example, not a synthetic one."""
    fixtures: list[RatedFixture] = []
    for sport, conn in (("cfb", regression_conn), ("nfl", nfl_regression_conn)):
        ensure_schema(conn)
        seasons = [
            int(row["season"])
            for row in conn.execute(
                "SELECT DISTINCT season FROM games WHERE sport = ? ORDER BY season", (sport,)
            )
        ]
        for method in METHODS:
            for year in seasons:
                compute_and_store(conn, year, method, sport=sport)
        fixtures.append(RatedFixture(conn, typing.cast(Sport, sport), seasons))

    for method in METHODS:
        pairs = [pair for fixture in fixtures for pair in _near_tie_pairs(fixture, method)]
        assert pairs, f"no real near-tie pair in either fixture for {method}"
        # Never an exact tie: the fixtures hold none, so every pair here really
        # is a near-tie and the leader clause (not "effectively tied") applies.
        assert all(pair.rating_a != pair.rating_b for pair in pairs)


@pytest.mark.parametrize("method", METHODS)
def test_every_real_near_tie_uses_the_near_tie_wording(
    rated_fixture: RatedFixture, method: str
) -> None:
    """Every ordered near-tie pair in the fixture, both directions, under
    `method`: the verdict's last sentence names the exact-rating leader with
    "rates a hair higher overall", prints the two identical numbers at the
    method's format, and states both ranks in argument order. Who leads is
    still decided by the exact `rating_diff`, never by the printed strings."""
    fixture = rated_fixture
    pairs = _near_tie_pairs(fixture, method)
    if not pairs:
        pytest.skip(f"no near-tie pair in the {fixture.sport} fixture for {method}")

    for pair in pairs:
        comparison = build_comparison(
            fixture.conn, pair.year, pair.team_a, pair.team_b, method=method, sport=fixture.sport
        )
        assert comparison.rating_diff == pair.rating_a - pair.rating_b
        assert comparison.rating_diff != 0
        leader = pair.team_a if comparison.rating_diff > 0 else pair.team_b
        expected = _leader_clause(
            leader, pair.printed, pair.printed, pair.rank_a, pair.rank_b, near_tie=True
        )
        assert comparison.verdict.endswith(" " + expected), (pair, comparison.verdict)
        # The hedge is the only change: the un-hedged clause must not appear.
        assert " rates higher overall " not in comparison.verdict, (pair, comparison.verdict)


@pytest.mark.parametrize("method", METHODS)
def test_rank_neighbours_print_distinguishable_numbers_or_hedge(
    rated_fixture: RatedFixture, method: str
) -> None:
    """The quality bar, swept over the pairs most likely to collide: every
    rank-adjacent pair in every season. A verdict that names a leader either
    prints two distinguishable numbers with the plain wording, or prints
    identical numbers with the hedge. Never identical numbers beside a plain
    "rates higher", and never the hedge beside distinguishable numbers."""
    fixture = rated_fixture
    decimals = VERDICT_DECIMALS[method]
    plain_seen = hedged_seen = 0
    for year in fixture.seasons:
        rows = _rated_rows(fixture.conn, year, method, fixture.sport)
        for a, b in itertools.pairwise(rows):
            comparison = build_comparison(
                fixture.conn,
                year,
                str(a["school"]),
                str(b["school"]),
                method=method,
                sport=fixture.sport,
            )
            printed_a, printed_b = (
                f"{float(a['rating']):.{decimals}f}",
                f"{float(b['rating']):.{decimals}f}",
            )
            if comparison.rating_diff == 0:
                assert comparison.verdict.endswith(" Ratings are effectively tied.")
                continue
            leader = str(a["school"]) if comparison.rating_diff > 0 else str(b["school"])
            near_tie = printed_a == printed_b
            expected = _leader_clause(
                leader, printed_a, printed_b, int(a["rank"]), int(b["rank"]), near_tie=near_tie
            )
            assert comparison.verdict.endswith(" " + expected), (year, a["school"], b["school"])
            if near_tie:
                hedged_seen += 1
            else:
                plain_seen += 1
    assert plain_seen, "no distinguishable rank-neighbour pair: the sweep proved nothing"
    if fixture.sport == "cfb":
        # Every method has a near-tie among CFB rank neighbours (measured), so
        # the hedged branch is exercised here too, not only in the pair sweep.
        assert hedged_seen, f"no hedged rank-neighbour pair for {method} in cfb"


def test_texas_usc_2005_keener_verdict_is_byte_identical(
    regression_conn: sqlite3.Connection,
) -> None:
    """A pair whose ratings print differently keeps today's wording, byte for
    byte. Pinned from the pre-#149 output (also pinned in
    test_evidence_integration.py; repeated here so this file alone shows both
    branches of the sentence against real data)."""
    ensure_schema(regression_conn)
    compute_and_store(regression_conn, 2005, "keener")
    comparison = build_comparison(regression_conn, 2005, "Texas", "USC", method="keener")
    assert comparison.verdict == (
        "Texas beat USC head-to-head 41-38 (Texas vs USC, week 1). "
        "Texas rates higher overall (0.005044 vs 0.004736, rank 1 vs 2)."
    )


@pytest.mark.parametrize("method", ["elo", "elo_career"])
def test_texas_usc_2005_elo_verdict_keeps_the_plain_wording(
    regression_conn: sqlite3.Connection, method: str
) -> None:
    """Texas and USC print differently under Elo too, so the plain clause is
    unchanged there as well."""
    ensure_schema(regression_conn)
    compute_and_store(regression_conn, 2005, method)
    rows = {
        str(row["school"]): row
        for row in _rated_rows(regression_conn, 2005, method, "cfb")
        if row["school"] in ("Texas", "USC")
    }
    texas, usc = rows["Texas"], rows["USC"]
    printed_texas, printed_usc = f"{float(texas['rating']):.1f}", f"{float(usc['rating']):.1f}"
    assert printed_texas != printed_usc, "premise: Texas/USC 2005 is not a near-tie under Elo"

    comparison = build_comparison(regression_conn, 2005, "Texas", "USC", method=method)
    leader = "Texas" if comparison.rating_diff > 0 else "USC"
    assert comparison.verdict == (
        "Texas beat USC head-to-head 41-38 (Texas vs USC, week 1). "
        + _leader_clause(
            leader, printed_texas, printed_usc, int(texas["rank"]), int(usc["rank"]), near_tie=False
        )
    )
