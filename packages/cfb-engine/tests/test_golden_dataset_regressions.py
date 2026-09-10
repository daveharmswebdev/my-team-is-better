"""Golden-dataset regression coverage for the two real bugs this project's
build history hit -- see CLAUDE.md's "Take 1 summary" and the ratings-agent
narrative in `src/cfb_strength/ratings/keener.py`'s module docstring.

Fixture provenance
------------------
`tests/fixtures/cfb_regression.sqlite3` was built once from the real,
fully-ingested `data/cfb.sqlite3` build artifact (never committed, never
read by these tests) by extracting every `games` row for season IN
(2001, 2005, 2013), every `teams` row referenced by those games (378 teams),
and every `team_season` row for those team/year pairs (782 rows). It
deliberately carries NO `ratings` rows -- every test below runs the real
`compute_and_store` / `KeenerRating.rate()` pipeline against these real
games itself, so a regression in the algorithm re-fails these tests instead
of silently passing against a canned answer. This mirrors exactly how
`validator` checks the golden dataset against the live database, just
against a small, committed, hermetic slice of the same real data.

Why these three years specifically
-----------------------------------
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

If any of these three tests fail, do not "fix" them by loosening the
assertion -- report it. These are exactly the classes of ranking-
correctness bug CLAUDE.md reserves for the coordinator to debug directly
(see "Known risk" / routing table), not something test-writer or any other
spoke edits around.
"""

from __future__ import annotations

import sqlite3

import pytest

from cfb_strength.evidence.proof import build_team_case
from cfb_strength.ratings.compute_ratings import compute_and_store


def _top_n(conn: sqlite3.Connection, year: int, n: int = 5) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT r.rank AS rank, t.school AS school, r.wins AS wins, r.losses AS losses
        FROM ratings r JOIN teams t ON t.id = r.team_id
        WHERE r.year = ? AND r.method = 'keener'
        ORDER BY r.rank ASC LIMIT ?
        """,
        (year, n),
    ).fetchall()


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


@pytest.mark.parametrize("year", [2001, 2005, 2013])
def test_champion_is_undefeated_or_best_recorded_in_all_three_golden_years(
    regression_conn: sqlite3.Connection, year: int
) -> None:
    """Cross-check: none of these three golden years' #1 team should have
    more losses than the team immediately behind it in the fixture -- a
    coarse sanity net independent of the exact-name assertions above, in
    case a future change reshuffles win totals without breaking the named
    assertions (e.g. a data refresh)."""
    compute_and_store(regression_conn, year, "keener")
    top2 = _top_n(regression_conn, year, n=2)
    assert len(top2) == 2
    assert top2[0]["losses"] <= top2[1]["losses"]
