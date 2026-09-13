"""NFL golden-dataset regression coverage (issue #61) -- the NFL equivalent
of `test_golden_dataset_regressions.py`'s CFB oracle years, so `validator`
has something concrete to certify NFL rankings against.

Fixture provenance
------------------
`tests/fixtures/nfl_regression.sqlite3` is generated the same way as the
CFB fixture, by `tests/fixtures/build_regression_fixtures.py` (issue #110;
its docstring has the regeneration command). `ingest.nflverse.ingest_season
.ingest_one` ingests real, cache-first nflverse data (`data/raw/nfl/games.csv`
/ `teams.csv`, live fetches disabled) for the whole ingest window into a
fresh current-schema db, which is then pruned to season IN (1999, 2004,
2013, 2022): those seasons' games, every `teams` row they reference (35 --
32 franchises plus three relocation variants: STL/LA Rams, SD/LA Chargers,
OAK/LV Raiders), every `team_season` row for those team/year pairs, and
those seasons' `ingestion_log` rows. #110 regenerated it at the current
schema; its games, teams and team_season content is unchanged from the
earlier hand-built fixture. It carries NO `ratings` rows -- every test below runs the real
`compute_and_store` / `KeenerRating.rate()` pipeline against these real
games itself, exactly like the CFB fixture, so a regression in the
algorithm re-fails these tests instead of silently passing against a
canned answer.

Why these four years specifically
-----------------------------------
nflverse's `games.csv` only goes back to 1999 (`ingest.nflverse.ingest_season
.MIN_YEAR`), so the CFB oracle's pre-1999 candidates (e.g. the 1972 perfect
Dolphins) aren't reachable here -- these four were chosen from the
1999-2025 window specifically because each is a genuinely undisputed
"best team" season, avoiding known-contested years the way
`apps/api/src/api/config.py`'s `CONTESTED_YEARS` flags contested CFB years
(e.g. 2007's undefeated-in-the-regular-season-but-lost-the-Super-Bowl
Patriots, or 2015's Panthers, are deliberately excluded from this set):

- 1999 St. Louis Rams (16-3 including playoffs): the "Greatest Show on
  Turf" -- Super Bowl XXXIV champion, beat the also-undefeated-in-the-
  regular-season-caliber Tennessee Titans 23-16 in the title game itself.
- 2004 New England Patriots (17-2): beat the 15-1 Pittsburgh Steelers
  41-27 in the AFC Championship (the Steelers' only loss with Ben
  Roethlisberger starting that season) en route to the Super Bowl title --
  a genuine quality win over the season's other elite team, not just a
  better record.
- 2013 Seattle Seahawks (16-3): the "Legion of Boom" defense, blew out the
  record-setting-offense 13-3 Denver Broncos 43-8 in Super Bowl XLVIII.
- 2022 Kansas City Chiefs (17-3): beat the also-14-3 Philadelphia Eagles
  38-35 in Super Bowl LVII.

If any of these four tests fail, do not "fix" them by loosening the
assertion -- report it. Per CLAUDE.md's routing table, "algorithm disagrees
with golden dataset" is a coordinator-direct judgment call, not something
any spoke edits around.
"""

from __future__ import annotations

import sqlite3

import pytest

from cfb_strength.evidence.proof import build_comparison, build_team_case
from cfb_strength.ratings.compute_ratings import compute_and_store


def _top_n(conn: sqlite3.Connection, year: int, n: int = 5) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT r.rank AS rank, t.school AS school, r.wins AS wins, r.losses AS losses
        FROM ratings r JOIN teams t ON t.id = r.team_id
        WHERE r.year = ? AND r.method = 'keener' AND r.sport = 'nfl'
        ORDER BY r.rank ASC LIMIT ?
        """,
        (year, n),
    ).fetchall()


def test_1999_rams_ranked_first_the_greatest_show_on_turf(
    nfl_regression_conn: sqlite3.Connection,
) -> None:
    """The 1999 St. Louis Rams -- undisputed Super Bowl XXXIV champion --
    must rank #1."""
    count = compute_and_store(nfl_regression_conn, 1999, "keener", sport="nfl")
    assert count > 0

    top5 = _top_n(nfl_regression_conn, 1999)
    assert top5[0]["school"] == "St. Louis Rams"
    assert top5[0]["wins"] == 16
    assert top5[0]["losses"] == 3


def test_1999_rams_case_cites_the_super_bowl_win_over_titans(
    nfl_regression_conn: sqlite3.Connection,
) -> None:
    """The sufficiency rubric requires the evidence layer to cite the Super
    Bowl win, unprompted, when asked about the greatest team of 1999."""
    compute_and_store(nfl_regression_conn, 1999, "keener", sport="nfl")

    case = build_team_case(nfl_regression_conn, 1999, "St. Louis Rams", method="keener", sport="nfl")
    assert case.rank == 1

    titans_wins = [g for g in case.quality_wins if g.opponent_name == "Tennessee Titans"]
    assert len(titans_wins) == 1, (
        f"expected exactly one quality win over Tennessee Titans in the Rams' "
        f"1999 case, got {[g.opponent_name for g in case.quality_wins]}"
    )
    super_bowl = titans_wins[0]
    assert (super_bowl.team_score, super_bowl.opponent_score) == (23, 16)


def test_2004_patriots_ranked_first_over_steelers(
    nfl_regression_conn: sqlite3.Connection,
) -> None:
    """The 2004 New England Patriots must rank #1 -- ahead of the 15-1
    Pittsburgh Steelers, whose only loss that season was to New England in
    the AFC Championship."""
    count = compute_and_store(nfl_regression_conn, 2004, "keener", sport="nfl")
    assert count > 0

    top5 = _top_n(nfl_regression_conn, 2004)
    assert top5[0]["school"] == "New England Patriots"
    assert top5[0]["wins"] == 17
    assert top5[0]["losses"] == 2

    schools_in_order = [row["school"] for row in top5]
    assert schools_in_order.index("New England Patriots") < schools_in_order.index(
        "Pittsburgh Steelers"
    )


def test_2004_patriots_case_cites_the_afc_championship_win_over_steelers(
    nfl_regression_conn: sqlite3.Connection,
) -> None:
    compute_and_store(nfl_regression_conn, 2004, "keener", sport="nfl")

    case = build_team_case(
        nfl_regression_conn, 2004, "New England Patriots", method="keener", sport="nfl"
    )
    assert case.rank == 1

    steelers_wins = [g for g in case.quality_wins if g.opponent_name == "Pittsburgh Steelers"]
    assert len(steelers_wins) == 1
    afc_championship = steelers_wins[0]
    assert (afc_championship.team_score, afc_championship.opponent_score) == (41, 27)


def test_2013_seahawks_ranked_first_the_legion_of_boom(
    nfl_regression_conn: sqlite3.Connection,
) -> None:
    """The 2013 Seattle Seahawks -- Super Bowl XLVIII champion -- must rank
    #1."""
    count = compute_and_store(nfl_regression_conn, 2013, "keener", sport="nfl")
    assert count > 0

    top5 = _top_n(nfl_regression_conn, 2013)
    assert top5[0]["school"] == "Seattle Seahawks"
    assert top5[0]["wins"] == 16
    assert top5[0]["losses"] == 3


def test_2013_seahawks_case_cites_the_super_bowl_blowout_over_broncos(
    nfl_regression_conn: sqlite3.Connection,
) -> None:
    compute_and_store(nfl_regression_conn, 2013, "keener", sport="nfl")

    case = build_team_case(
        nfl_regression_conn, 2013, "Seattle Seahawks", method="keener", sport="nfl"
    )
    assert case.rank == 1

    broncos_wins = [g for g in case.quality_wins if g.opponent_name == "Denver Broncos"]
    assert len(broncos_wins) == 1
    super_bowl = broncos_wins[0]
    assert (super_bowl.team_score, super_bowl.opponent_score) == (43, 8)


def test_2022_chiefs_ranked_first_over_eagles(
    nfl_regression_conn: sqlite3.Connection,
) -> None:
    """The 2022 Kansas City Chiefs -- Super Bowl LVII champion -- must rank
    #1, ahead of the also-14-3 Philadelphia Eagles they beat in that game."""
    count = compute_and_store(nfl_regression_conn, 2022, "keener", sport="nfl")
    assert count > 0

    top5 = _top_n(nfl_regression_conn, 2022)
    assert top5[0]["school"] == "Kansas City Chiefs"
    assert top5[0]["wins"] == 17
    assert top5[0]["losses"] == 3

    schools_in_order = [row["school"] for row in top5]
    assert schools_in_order.index("Kansas City Chiefs") < schools_in_order.index(
        "Philadelphia Eagles"
    )


def test_2022_chiefs_case_cites_the_super_bowl_win_over_eagles(
    nfl_regression_conn: sqlite3.Connection,
) -> None:
    compute_and_store(nfl_regression_conn, 2022, "keener", sport="nfl")

    case = build_team_case(
        nfl_regression_conn, 2022, "Kansas City Chiefs", method="keener", sport="nfl"
    )
    assert case.rank == 1

    eagles_wins = [g for g in case.quality_wins if g.opponent_name == "Philadelphia Eagles"]
    assert len(eagles_wins) == 1
    super_bowl = eagles_wins[0]
    assert (super_bowl.team_score, super_bowl.opponent_score) == (38, 35)


# ---------------------------------------------------------------------------
# Issue #83: real NFL ties are part of the stored record.
#
# Before #83 every rating method counted an equal-score game as neither a win
# nor a loss and `ratings` had no column for a tie, so the tie vanished from
# every displayed record.
# ---------------------------------------------------------------------------


def _stored_record(
    conn: sqlite3.Connection, year: int, method: str, school: str
) -> tuple[int, int, int]:
    row = conn.execute(
        """
        SELECT r.wins AS wins, r.losses AS losses, r.ties AS ties
        FROM ratings r JOIN teams t ON t.id = r.team_id
        WHERE r.year = ? AND r.method = ? AND r.sport = 'nfl' AND t.school = ?
        """,
        (year, method, school),
    ).fetchone()
    assert row is not None, f"no {method} rating row for {school} {year}"
    return (row["wins"], row["losses"], row["ties"])


@pytest.mark.parametrize("method", ["keener", "elo"])
def test_2013_packers_vikings_tie_is_in_both_stored_records(
    nfl_regression_conn: sqlite3.Connection, method: str
) -> None:
    """2013 week 12: Green Bay 26, Minnesota 26 (OT), a real tie.

    The stored record counts every completed game loaded for the season,
    postseason included. Green Bay also lost its wild-card game, so it is
    8-8-1 here, not its 8-7-1 regular-season record; Minnesota is 5-10-1.
    """
    compute_and_store(nfl_regression_conn, 2013, method, sport="nfl")
    assert _stored_record(nfl_regression_conn, 2013, method, "Green Bay Packers") == (8, 8, 1)
    assert _stored_record(nfl_regression_conn, 2013, method, "Minnesota Vikings") == (5, 10, 1)


def _loaded_games_per_team(conn: sqlite3.Connection, year: int, sport: str) -> dict[int, int]:
    """Completed games per team, with exactly `_load_games`' predicates."""
    rows = conn.execute(
        """
        SELECT team_id, COUNT(*) AS n FROM (
            SELECT home_team_id AS team_id FROM games
            WHERE season = ? AND sport = ? AND completed = 1
              AND home_points IS NOT NULL AND away_points IS NOT NULL
            UNION ALL
            SELECT away_team_id AS team_id FROM games
            WHERE season = ? AND sport = ? AND completed = 1
              AND home_points IS NOT NULL AND away_points IS NOT NULL
        ) GROUP BY team_id
        """,
        (year, sport, year, sport),
    ).fetchall()
    return {row["team_id"]: row["n"] for row in rows}


@pytest.mark.parametrize("method", ["keener", "elo"])
@pytest.mark.parametrize("year", [1999, 2004, 2013, 2022])
def test_record_sums_to_completed_games_for_every_nfl_team(
    nfl_regression_conn: sqlite3.Connection, year: int, method: str
) -> None:
    """`TeamRating`'s invariant: `wins + losses + ties` equals the team's
    completed games in the season, for every stored team."""
    compute_and_store(nfl_regression_conn, year, method, sport="nfl")
    expected = _loaded_games_per_team(nfl_regression_conn, year, "nfl")
    rows = nfl_regression_conn.execute(
        "SELECT team_id, wins, losses, ties FROM ratings "
        "WHERE year = ? AND method = ? AND sport = 'nfl'",
        (year, method),
    ).fetchall()
    assert rows
    actual = {r["team_id"]: r["wins"] + r["losses"] + r["ties"] for r in rows}
    assert actual == {team_id: expected[team_id] for team_id in actual}


# ---------------------------------------------------------------------------
# Issue #83, evidence layer: the same real tie in the receipts.
#
# Before #83 `evidence/proof.py:_opponent_result` returned None for any equal
# score, so the 2013 Packers-Vikings 26-26 tie was missing from the Packers'
# `games`, from every common-opponent pairing, from the per-opponent credit
# explanation, and from the verdict prose -- while `head_to_head` alone
# reported it (winner=None).
#
# Verified directly from the fixture's `games` table before writing these:
#   week  8  Minnesota Vikings 31, Green Bay Packers 44
#   week  9  Green Bay Packers 20, Chicago Bears 27
#   week  2  Chicago Bears 31, Minnesota Vikings 30
#   week 12  Green Bay Packers 26, Minnesota Vikings 26   <- the tie
#   week 13  Minnesota Vikings 23, Chicago Bears 20
#   week 17  Chicago Bears 28, Green Bay Packers 33
# It is the fixture's only 2013 tie.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["keener", "elo"])
def test_2013_packers_case_lists_the_vikings_tie(
    nfl_regression_conn: sqlite3.Connection, method: str
) -> None:
    compute_and_store(nfl_regression_conn, 2013, method, sport="nfl")

    case = build_team_case(
        nfl_regression_conn, 2013, "Green Bay Packers", method=method, sport="nfl"
    )

    assert (case.wins, case.losses, case.ties) == (8, 8, 1)
    assert len(case.games) == 17
    assert len(case.games) == case.wins + case.losses + case.ties

    ties = [g for g in case.games if g.result == "T"]
    assert len(ties) == 1
    tie = ties[0]
    assert tie.opponent_name == "Minnesota Vikings"
    assert (tie.team_score, tie.opponent_score) == (26, 26)
    assert tie.week == 12


@pytest.mark.parametrize("method", ["keener", "elo"])
def test_2013_vikings_tie_is_never_a_quality_win_or_worst_loss(
    nfl_regression_conn: sqlite3.Connection, method: str
) -> None:
    compute_and_store(nfl_regression_conn, 2013, method, sport="nfl")

    for school in ("Green Bay Packers", "Minnesota Vikings"):
        case = build_team_case(nfl_regression_conn, 2013, school, method=method, sport="nfl")
        assert any(g.result == "T" for g in case.games), school
        assert all(g.result == "W" for g in case.quality_wins), school
        assert case.worst_loss is not None
        assert case.worst_loss.result == "L", school


@pytest.mark.parametrize("method", ["keener", "elo"])
def test_2013_vikings_case_record_includes_the_tie(
    nfl_regression_conn: sqlite3.Connection, method: str
) -> None:
    compute_and_store(nfl_regression_conn, 2013, method, sport="nfl")

    case = build_team_case(
        nfl_regression_conn, 2013, "Minnesota Vikings", method=method, sport="nfl"
    )

    assert (case.wins, case.losses, case.ties) == (5, 10, 1)
    assert len(case.games) == 16
    assert [g.opponent_name for g in case.games if g.result == "T"] == ["Green Bay Packers"]


@pytest.mark.parametrize(
    ("team_a", "team_b", "common_opponent", "a_result", "a_score", "b_result", "b_score"),
    [
        # Green Bay as the common opponent. Each side's pairing keeps the
        # existing choice rule (the last game against that opponent), which
        # for Minnesota is the week-12 tie, not the week-8 loss.
        ("Minnesota Vikings", "Chicago Bears", "Green Bay Packers", "T", (26, 26), "L", (28, 33)),
        # Minnesota as the common opponent.
        ("Green Bay Packers", "Chicago Bears", "Minnesota Vikings", "T", (26, 26), "L", (20, 23)),
    ],
)
def test_2013_common_opponent_reports_the_tie(
    nfl_regression_conn: sqlite3.Connection,
    team_a: str,
    team_b: str,
    common_opponent: str,
    a_result: str,
    a_score: tuple[int, int],
    b_result: str,
    b_score: tuple[int, int],
) -> None:
    compute_and_store(nfl_regression_conn, 2013, "keener", sport="nfl")

    comparison = build_comparison(
        nfl_regression_conn, 2013, team_a, team_b, method="keener", sport="nfl"
    )

    matches = [c for c in comparison.common_opponents if c.opponent_name == common_opponent]
    assert len(matches) == 1
    shared = matches[0]
    assert shared.team_a_result == a_result
    assert (shared.team_a_score, shared.team_a_opponent_score) == a_score
    assert shared.team_b_result == b_result
    assert (shared.team_b_score, shared.team_b_opponent_score) == b_score

    assert comparison.team_a.ties == 1
    assert comparison.team_b.ties == 0


def test_2013_packers_vikings_comparison_verdict_names_the_tie(
    nfl_regression_conn: sqlite3.Connection,
) -> None:
    """`head_to_head` already reported the tie (winner=None), but the verdict
    prose only had sentences for a winner, so the tied meeting was silent."""
    compute_and_store(nfl_regression_conn, 2013, "keener", sport="nfl")

    comparison = build_comparison(
        nfl_regression_conn, 2013, "Green Bay Packers", "Minnesota Vikings",
        method="keener", sport="nfl",
    )

    assert [m.winner for m in comparison.head_to_head.meetings] == ["Green Bay Packers", None]
    assert (comparison.team_a.wins, comparison.team_a.losses, comparison.team_a.ties) == (8, 8, 1)
    assert (comparison.team_b.wins, comparison.team_b.losses, comparison.team_b.ties) == (5, 10, 1)
    assert (
        "Green Bay Packers beat Minnesota Vikings head-to-head 31-44 "
        "(Minnesota Vikings vs Green Bay Packers, week 8)."
    ) in comparison.verdict
    assert (
        "Green Bay Packers and Minnesota Vikings tied head-to-head 26-26 "
        "(Green Bay Packers vs Minnesota Vikings, week 12)."
    ) in comparison.verdict


def test_2013_packers_credit_explanation_counts_the_vikings_tie(
    nfl_regression_conn: sqlite3.Connection,
) -> None:
    """The persisted breakdown row already counted both meetings
    (games_played=2), but the explanation was built from the win alone and
    read as a single 44-31 win."""
    compute_and_store(nfl_regression_conn, 2013, "keener", sport="nfl")

    case = build_team_case(
        nfl_regression_conn, 2013, "Green Bay Packers", method="keener", sport="nfl"
    )

    entry = next(e for e in case.rating_breakdown.entries if e.opponent_name == "Minnesota Vikings")
    assert entry.games_played == 2
    assert entry.explanation.startswith("Played them 2 times (1-0-1) — 44-31 (0.60 + ")
    assert entry.explanation.endswith("; 26-26 (0.50 + 0.00).")
