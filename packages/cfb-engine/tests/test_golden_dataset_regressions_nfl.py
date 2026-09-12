"""NFL golden-dataset regression coverage (issue #61) -- the NFL equivalent
of `test_golden_dataset_regressions.py`'s CFB oracle years, so `validator`
has something concrete to certify NFL rankings against.

Fixture provenance
------------------
`tests/fixtures/nfl_regression.sqlite3` was built the same way as the CFB
fixture: `cfb_strength.ingest.nflverse.ingest_season.main()` ingested real,
cache-first nflverse data (`data/raw/nfl/games.csv` / `teams.csv`, never a
live fetch) for season IN (1999, 2004, 2013, 2022), then every `teams` row
referenced by those seasons' games (35 -- 32 franchises plus three
relocation variants: STL/LA Rams, SD/LA Chargers, OAK/LV Raiders) and every
`team_season` row for those team/year pairs was extracted into this
fixture. It carries NO `ratings` rows -- every test below runs the real
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

from cfb_strength.evidence.proof import build_team_case
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
