"""Issue #379: the API fixture stores FCS playoff games as postseason.

CFBD files most FCS (I-AA) playoff games as season_type 'regular' (the 2019
second round is "regular week 15"). Since #379 the engine's ingest stores the
curated list of them (`data/raw/cfbd_fcs_playoff_games.json`) as
'postseason', and `cfb_verdict_fixture.sqlite3` was rebuilt from that ingest.

The fixture rates only FBS teams, so no team case or comparison the API
serves contains one of these games, and none of its ratings or Elo ledgers
moved in the rebuild. These tests therefore pin the stored rows themselves,
with North Dakota State's 2019 title run as the worked case: CFBD's week 15
and 16 games are postseason now, alongside the semifinal and final CFBD
already filed as postseason "week 1".
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest
from cfb_strength.db.connection import get_conn
from fixtures.claim_blocks import CFB_FIXTURE_DB

NDSU_2019_PLAYOFFS = [
    # (game id, start_date, opponent, week as CFBD numbers it)
    (401187313, "2019-12-07T20:30:00.000Z", "Nicholls", 15),
    (401188396, "2019-12-14T17:00:00.000Z", "Illinois State", 16),
    (401189293, "2019-12-21T19:00:00.000Z", "Montana State", 1),
    (401198013, "2020-01-11T17:00:00.000Z", "James Madison", 1),
]


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = get_conn(CFB_FIXTURE_DB, read_only=True)
    try:
        yield connection
    finally:
        connection.close()


def test_ndsu_vs_nicholls_2019_is_postseason(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT season, week, season_type, home_team, away_team, home_points, away_points "
        "FROM games WHERE id = 401187313"
    ).fetchone()
    assert tuple(row) == (2019, 15, "postseason", "North Dakota State", "Nicholls", 37, 13)


def test_ndsu_2019_season_ends_with_four_postseason_games(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT g.id, g.start_date,"
        " CASE WHEN g.home_team_id = t.id THEN g.away_team ELSE g.home_team END,"
        " g.week, g.season_type"
        " FROM games g JOIN teams t ON t.school = 'North Dakota State'"
        " WHERE g.sport = 'cfb' AND g.season = 2019 AND t.id IN (g.home_team_id, g.away_team_id)"
        " ORDER BY g.start_date"
    ).fetchall()
    assert [r["season_type"] for r in rows] == ["regular"] * 12 + ["postseason"] * 4
    assert [tuple(r)[:4] for r in rows[-4:]] == NDSU_2019_PLAYOFFS


def test_no_fcs_team_is_rated(conn: sqlite3.Connection) -> None:
    """Why the rebuild left every rating and ledger row unchanged: the teams
    whose games were refiled are not rated, so no served payload holds them."""
    rated = conn.execute(
        "SELECT count(*) FROM ratings r JOIN teams t ON t.id = r.team_id"
        " WHERE t.school IN ('North Dakota State', 'Nicholls', 'James Madison')"
    ).fetchone()[0]
    assert rated == 0
