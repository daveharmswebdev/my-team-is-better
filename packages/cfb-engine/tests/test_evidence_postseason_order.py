"""Issue #379: evidence lists postseason games in true chronological order.

CFBD gives relabelled FCS playoff rounds weeks 13-16 but files the FCS
semifinals and final as postseason week 1, so ordering the postseason by
`week` replays the last two rounds first. Inside the postseason, evidence
orders by `start_date` before `week` -- the same key list as the ratings
walk (`compute_ratings`), so what is displayed matches what was replayed.
Regular-season order is unchanged (week first).

Covers both of `proof.py`'s ordered game queries: `_team_games` (through
`TeamCase.games`) and the head-to-head query in `build_comparison`.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from cfb_strength.db.connection import ensure_schema, get_conn
from cfb_strength.evidence.proof import build_comparison, build_team_case


def test_2019_north_dakota_state_postseason_games_are_in_date_order(
    regression_conn: sqlite3.Connection,
) -> None:
    # The committed fixture stores NDSU's 2019 FCS playoff run as postseason
    # R2 (wk 15, 2019-12-07), QF (wk 16, 12-14), SF (wk 1, 12-21) and the
    # final (wk 1, 2020-01-11). Ordered by week, SF and final came first.
    # No rating method rates FCS teams, so this test copy gets a hand-written
    # `ratings` row for NDSU (id 2449); evidence only needs the team rated to
    # resolve it, and the game rows under test are the fixture's real ones.
    regression_conn.execute(
        """
        INSERT INTO ratings (
            year, method, team_id, rating, rank, wins, losses, ties, computed_at, sport
        ) VALUES (2019, 'keener', 2449, 1.0, 1, 16, 0, 0, 'test', 'cfb')
        """
    )
    regression_conn.commit()
    case = build_team_case(regression_conn, 2019, "North Dakota State", method="keener")

    post = [g for g in case.games if g.season_type != "regular"]
    assert [(g.game_id, g.week, g.opponent_name) for g in post] == [
        (401187313, 15, "Nicholls"),
        (401188396, 16, "Illinois State"),
        (401189293, 1, "Montana State"),
        (401198013, 1, "James Madison"),
    ]

    # Regular season still comes first, in week order.
    regular = [g for g in case.games if g.season_type == "regular"]
    assert case.games[: len(regular)] == regular
    weeks = [g.week for g in regular]
    assert weeks == sorted(w for w in weeks if w is not None)


YEAR = 2030
METHOD = "keener"


def _insert_game(
    conn: sqlite3.Connection,
    game_id: int,
    week: int,
    season_type: str,
    start_date: str,
    home_id: int,
    away_id: int,
    home_points: int,
    away_points: int,
) -> None:
    names = {1: "Alpha State", 2: "Bravo Tech"}
    conn.execute(
        """
        INSERT INTO games (
            id, season, week, season_type, start_date, neutral_site, completed,
            home_team_id, away_team_id, home_team, away_team,
            home_points, away_points, home_conference, away_conference, venue,
            raw_json, sport
        ) VALUES (?, ?, ?, ?, ?, 1, 1, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, '{}', 'cfb')
        """,
        (
            game_id,
            YEAR,
            week,
            season_type,
            start_date,
            home_id,
            away_id,
            names[home_id],
            names[away_id],
            home_points,
            away_points,
        ),
    )


def test_head_to_head_postseason_meetings_are_listed_by_date(tmp_path: Path) -> None:
    conn = get_conn(tmp_path / "h2h.sqlite3")
    try:
        ensure_schema(conn)
        for tid, school in ((1, "Alpha State"), (2, "Bravo Tech")):
            conn.execute(
                "INSERT INTO teams (id, school, classification, sport) VALUES (?, ?, 'fcs', 'cfb')",
                (tid, school),
            )
        # Regular-season meeting, then two postseason meetings whose week
        # labels run against the calendar (wk 16 on 12-14, wk 1 on 12-21).
        # Ids are inserted so that neither id nor week order is date order.
        _insert_game(conn, 30, 5, "regular", "2030-10-01T18:00:00.000Z", 1, 2, 21, 14)
        _insert_game(conn, 10, 1, "postseason", "2030-12-21T18:00:00.000Z", 2, 1, 28, 24)
        _insert_game(conn, 20, 16, "postseason", "2030-12-14T18:00:00.000Z", 1, 2, 17, 10)
        for tid, rating, rank, wins, losses in ((1, 1.0, 1, 2, 1), (2, 0.5, 2, 1, 2)):
            conn.execute(
                """
                INSERT INTO ratings (
                    year, method, team_id, rating, rank, wins, losses, ties,
                    computed_at, sport
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 'test', 'cfb')
                """,
                (YEAR, METHOD, tid, rating, rank, wins, losses),
            )
        conn.commit()

        result = build_comparison(conn, YEAR, "Alpha State", "Bravo Tech", method=METHOD)
        assert [(m.game_id, m.week, m.season_type) for m in result.head_to_head.meetings] == [
            (30, 5, "regular"),
            (20, 16, "postseason"),
            (10, 1, "postseason"),
        ]

        case = build_team_case(conn, YEAR, "Alpha State", method=METHOD)
        assert [g.game_id for g in case.games] == [30, 20, 10]
    finally:
        conn.close()
