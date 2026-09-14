"""Golden-dataset regression coverage: the Keener #1 for every one of the
PRD's seven golden CFB years, plus the two real bugs this project's build
history hit -- see CLAUDE.md's "Take 1 summary" and the ratings-agent
narrative in `src/cfb_strength/ratings/keener.py`'s module docstring.

Fixture provenance
------------------
`tests/fixtures/cfb_regression.sqlite3` is generated, not hand-extracted, by
`tests/fixtures/build_regression_fixtures.py` (issue #110; its docstring
has the regeneration command). That script runs the real CFBD ingest path
(`ingest_season.ingest_one` for every season in the ingest window, then
`enrich_team_aliases`) cache-first against the committed `data/raw/`, with
live fetches disabled outright, into a fresh current-schema db. It then
prunes to season IN (2001, 2003, 2004, 2005, 2013, 2017, 2019): those
seasons' `games`, the `teams` they reference (mascot and alternate_names
included), the `team_season` rows for those team/season pairs, and those
seasons' `ingestion_log` rows. It deliberately carries NO `ratings` rows.
Every test below runs the real `compute_and_store` / `KeenerRating.rate()`
pipeline against these real games itself, so a regression in the algorithm
re-fails these tests instead of silently passing against a canned answer.
This mirrors how `validator` checks the golden dataset against a
doctor-verified full database, against a small, committed, hermetic slice
of the same real data. Keener and elo rate each season in isolation, so the
slice changes no rating (verified for #110 against a full db, top 25 to
1e-12). `tests/test_regression_fixtures_regenerate_identically.py` fails
unless the committed fixture's rows and schema equal a fresh regeneration
from the committed cache, so a changed score or a missing game can't sit
under these tests unnoticed. `tests/test_regression_fixtures_currency.py`
separately runs `cfb doctor`'s schema and season-type coverage check.

The seven golden years
----------------------
Must match (`MUST_MATCH`): 2001 Miami 12-0, 2004 USC 13-0, 2005 Texas 13-0,
2013 Florida State 14-0, 2019 LSU 15-0.

Contested (`CONTESTED`): 2003 LSU 13-1 and 2017 Alabama 13-1. These are
contested seasons (2003 split its title between LSU and USC; 2017 left
13-0 UCF claiming one beside Alabama). The values pinned here are the
evidenced answer this engine computed on a `cfb doctor`-verified full
database when #110 added them. They are regression anchors for the
*computed* answer, so an unexplained change to it is noticed. They are NOT
claims about who "really" was the best team in either season. If a
deliberate algorithm change moves one, that is a coordinator decision to
re-pin with evidence (validator.md: report the evidenced answer, don't force
an outcome), never a test to loosen.

Why the three older named regressions
-------------------------------------
- 2005 is the original take-1 regression case: an early margin-of-victory
  credit formula ranked USC (12-1, lost the Rose Bowl 41-38) above Texas
  (13-0, won it).
- 2001 and 2013 are the schedule-length confound found later in *this*
  build: without normalizing a team's outgoing credit row by its own
  games-played count, undefeated 12-0 Miami (FL) lost #1 to two-loss,
  13-game Tennessee in 2001, and undefeated 14-0 Florida State lost #1 (in
  fact dropped to #2) behind three-loss Stanford in 2013 -- purely because
  the other team played more games, not because of anything in the
  head-to-head/common-opponent evidence.

If any of these tests fail, do not "fix" them by loosening the assertion --
report it. These are exactly the classes of ranking-correctness bug
CLAUDE.md reserves for the coordinator to debug directly (see "Known risk" /
routing table), not something test-writer or any other spoke edits around.
"""

from __future__ import annotations

import sqlite3

import pytest

from cfb_strength.evidence.proof import build_team_case
from cfb_strength.ratings.compute_ratings import compute_and_store

# (school, wins, losses) of the Keener #1. Written out by hand on purpose:
# the expected answers must not be read from the fixture under test.
MUST_MATCH: dict[int, tuple[str, int, int]] = {
    2001: ("Miami", 12, 0),
    2004: ("USC", 13, 0),
    2005: ("Texas", 13, 0),
    2013: ("Florida State", 14, 0),
    2019: ("LSU", 15, 0),
}
# Contested seasons: regression anchors for the computed answer, not claims
# about who was best. See the module docstring.
CONTESTED: dict[int, tuple[str, int, int]] = {
    2003: ("LSU", 13, 1),
    2017: ("Alabama", 13, 1),
}
GOLDEN_YEARS: tuple[int, ...] = tuple(sorted({**MUST_MATCH, **CONTESTED}))
# (school, losses) of the Keener #1 and #2, for the one golden year the
# best-record sanity net below cannot hold: in 2017 the computed #1, 13-1
# Alabama, ranks above 13-0 UCF, which is exactly what makes 2017 contested.
# Pinned exactly rather than skipped, so a change to either team still fails.
# Only a contested year may appear here.
BEST_RECORD_EXCEPTIONS: dict[int, tuple[tuple[str, int], tuple[str, int]]] = {
    2017: (("Alabama", 1), ("UCF", 0)),
}


def _top_n(conn: sqlite3.Connection, year: int, n: int = 5) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT r.rank AS rank, t.school AS school, r.wins AS wins, r.losses AS losses,
               r.ties AS ties
        FROM ratings r JOIN teams t ON t.id = r.team_id
        WHERE r.year = ? AND r.method = 'keener'
        ORDER BY r.rank ASC LIMIT ?
        """,
        (year, n),
    ).fetchall()


def _assert_keener_number_one(
    conn: sqlite3.Connection, year: int, expected: tuple[str, int, int]
) -> None:
    count = compute_and_store(conn, year, "keener")
    # A season missing from the fixture writes zero rows. It must fail here,
    # never skip, or dropping a golden year would pass silently.
    assert count > 0, f"the fixture holds no rateable {year} games"

    school, wins, losses = expected
    top = _top_n(conn, year, n=3)
    actual = [(row["school"], row["wins"], row["losses"], row["ties"]) for row in top]
    assert actual[0] == (school, wins, losses, 0), f"{year} keener top 3: {actual}"


def test_golden_years_are_the_prds_seven() -> None:
    assert GOLDEN_YEARS == (2001, 2003, 2004, 2005, 2013, 2017, 2019)
    assert not set(MUST_MATCH) & set(CONTESTED)
    assert set(BEST_RECORD_EXCEPTIONS) <= set(CONTESTED)


@pytest.mark.parametrize("year", sorted(MUST_MATCH))
def test_must_match_year_keener_number_one_and_record(
    regression_conn: sqlite3.Connection, year: int
) -> None:
    """The golden dataset's must-match entries: the Keener #1 is this team
    with this record, including ties (none)."""
    _assert_keener_number_one(regression_conn, year, MUST_MATCH[year])


@pytest.mark.parametrize("year", sorted(CONTESTED))
def test_contested_year_keener_number_one_is_the_pinned_computed_answer(
    regression_conn: sqlite3.Connection, year: int
) -> None:
    """2003 and 2017 are contested years. This pins the answer the engine
    computed on a doctor-verified full database (LSU 13-1, Alabama 13-1) as
    a regression anchor for the computed answer, not a claim about who
    "really" was best. A change here needs evidence and a coordinator
    decision, not a loosened assertion."""
    _assert_keener_number_one(regression_conn, year, CONTESTED[year])


def test_2001_miami_undefeated_ranked_first_despite_playing_fewer_games(
    regression_conn: sqlite3.Connection,
) -> None:
    """Regression for the games-played-normalization bug.

    Pre-fix, this ranked 11-2 Tennessee (13 games) above 12-0 Miami (FL)
    (12 games) purely because Tennessee's un-normalized outgoing credit row
    summed to more total weight by virtue of playing one extra game. The
    fix (dividing each team's raw credit row by its own games-played count
    before the eigenvector solve -- see keener.py) makes undefeated Miami
    #1 again, which is what actually happened on the field in 2001.
    """
    count = compute_and_store(regression_conn, 2001, "keener")
    assert count > 0

    top5 = _top_n(regression_conn, 2001)
    assert top5[0]["school"] == "Miami"
    assert top5[0]["wins"] == 12
    assert top5[0]["losses"] == 0

    # The specific team this bug promoted above Miami pre-fix should not be
    # ranked ahead of it now.
    schools_in_order = [row["school"] for row in top5]
    assert schools_in_order.index("Miami") < schools_in_order.index("Tennessee")


def test_2013_florida_state_undefeated_ranked_first_despite_playing_fewer_games(
    regression_conn: sqlite3.Connection,
) -> None:
    """Regression for the same games-played-normalization bug, on the second
    golden year it broke: pre-fix, 3-loss Stanford (more games played)
    displaced undefeated 14-0 Florida State from the top of the (FBS-only
    displayed) ranking.
    """
    count = compute_and_store(regression_conn, 2013, "keener")
    assert count > 0

    top5 = _top_n(regression_conn, 2013)
    assert top5[0]["school"] == "Florida State"
    assert top5[0]["wins"] == 14
    assert top5[0]["losses"] == 0

    schools_in_order = [row["school"] for row in top5]
    if "Stanford" in schools_in_order:
        assert schools_in_order.index("Florida State") < schools_in_order.index("Stanford")


def test_2005_texas_ranked_first_over_usc_the_original_take1_regression_case(
    regression_conn: sqlite3.Connection,
) -> None:
    """The original take-1 bug: a margin-of-victory-dominant credit formula
    ranked USC (12-1, lost the Rose Bowl 41-38) above Texas (13-0, won it),
    because USC's average blowout margin across the season was higher even
    though Texas beat USC head-to-head. The shipped formula is win/loss-
    dominant (BASE_WIN always exceeds the maximum possible loss credit --
    see keener.py), so Texas must rank #1 and USC #2 here.
    """
    count = compute_and_store(regression_conn, 2005, "keener")
    assert count > 0

    top5 = _top_n(regression_conn, 2005)
    assert top5[0]["school"] == "Texas"
    assert top5[0]["wins"] == 13
    assert top5[0]["losses"] == 0
    assert top5[1]["school"] == "USC"
    assert top5[1]["wins"] == 12
    assert top5[1]["losses"] == 1


def test_2005_texas_case_cites_the_rose_bowl_win_over_usc(
    regression_conn: sqlite3.Connection,
) -> None:
    """The sufficiency rubric requires the MCP server to cite the USC win,
    unprompted, when asked about the greatest team of 2005. That evidence
    comes from `build_team_case`'s `quality_wins` list -- assert the Rose
    Bowl game (41-38 over USC) is actually present there with the real
    score, not just that Texas is ranked #1.
    """
    compute_and_store(regression_conn, 2005, "keener")

    case = build_team_case(regression_conn, 2005, "Texas", method="keener")
    assert case.rank == 1
    assert case.wins == 13 and case.losses == 0

    usc_wins = [g for g in case.quality_wins if g.opponent_name == "USC"]
    assert len(usc_wins) == 1, (
        f"expected exactly one quality win over USC in Texas's 2005 case, "
        f"got {[g.opponent_name for g in case.quality_wins]}"
    )
    rose_bowl = usc_wins[0]
    assert rose_bowl.result == "W"
    assert rose_bowl.team_score == 41
    assert rose_bowl.opponent_score == 38
    assert rose_bowl.season_type == "postseason"
    assert rose_bowl.neutral_site is True


@pytest.mark.parametrize("year", GOLDEN_YEARS)
def test_champion_is_undefeated_or_best_recorded_in_every_golden_year(
    regression_conn: sqlite3.Connection, year: int
) -> None:
    """Cross-check: no golden year's #1 team should have more losses than
    the team immediately behind it in the fixture -- a coarse sanity net
    independent of the exact-name assertions above, in case a future change
    reshuffles win totals without breaking the named assertions (e.g. a data
    refresh). The contested years in `BEST_RECORD_EXCEPTIONS` assert their
    exact computed #1 and #2 instead."""
    compute_and_store(regression_conn, year, "keener")
    top2 = _top_n(regression_conn, year, n=2)
    assert len(top2) == 2
    if year in BEST_RECORD_EXCEPTIONS:
        assert tuple((row["school"], row["losses"]) for row in top2) == BEST_RECORD_EXCEPTIONS[year]
    else:
        assert top2[0]["losses"] <= top2[1]["losses"]


@pytest.mark.parametrize("method", ["keener", "elo"])
@pytest.mark.parametrize("year", GOLDEN_YEARS)
def test_record_sums_to_completed_games_for_every_displayed_team(
    regression_conn: sqlite3.Connection, year: int, method: str
) -> None:
    """Issue #83, `TeamRating`'s invariant: `wins + losses + ties` equals the
    team's completed games loaded for the season -- counted over the whole
    win-graph (FCS opponents included), not just FBS-vs-FBS games, for every
    FBS team the display filter keeps. Uses exactly `_load_games`'
    predicates."""
    compute_and_store(regression_conn, year, method)
    expected = {
        row["team_id"]: row["n"]
        for row in regression_conn.execute(
            """
            SELECT team_id, COUNT(*) AS n FROM (
                SELECT home_team_id AS team_id FROM games
                WHERE season = ? AND sport = 'cfb' AND completed = 1
                  AND home_points IS NOT NULL AND away_points IS NOT NULL
                UNION ALL
                SELECT away_team_id AS team_id FROM games
                WHERE season = ? AND sport = 'cfb' AND completed = 1
                  AND home_points IS NOT NULL AND away_points IS NOT NULL
            ) GROUP BY team_id
            """,
            (year, year),
        ).fetchall()
    }
    rows = regression_conn.execute(
        "SELECT team_id, wins, losses, ties FROM ratings "
        "WHERE year = ? AND method = ? AND sport = 'cfb'",
        (year, method),
    ).fetchall()
    assert rows
    actual = {r["team_id"]: r["wins"] + r["losses"] + r["ties"] for r in rows}
    assert actual == {team_id: expected[team_id] for team_id in actual}
