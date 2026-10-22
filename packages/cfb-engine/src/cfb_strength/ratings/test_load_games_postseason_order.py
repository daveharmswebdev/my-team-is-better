"""Issue #379: the rating walk replays a postseason in date order.

CFBD numbers relabelled FCS playoff rounds weeks 13-16 but files the FCS
semifinals and final as postseason week 1, so ordering the postseason by
week replays the final before the second round. Inside the postseason
`_load_games` orders by `start_date` first; the regular season keeps its
week-first order.
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from cfb_strength.db.connection import ensure_schema, get_conn
from cfb_strength.ratings.compute_ratings import _load_games
from cfb_strength.ratings.elo import ELO_CONFIGS, EloRating

_FIXTURES_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures"


def _make_conn(tmp_path: Path) -> sqlite3.Connection:
    conn = get_conn(tmp_path / "order.sqlite3")
    ensure_schema(conn)
    for tid in (1, 2, 3, 4):
        conn.execute(
            "INSERT INTO teams (id, school, classification, sport) VALUES (?, ?, NULL, 'cfb')",
            (tid, f"Team {tid}"),
        )
    return conn


def _insert(
    conn: sqlite3.Connection,
    game_id: int,
    week: int | None,
    season_type: str,
    start_date: str | None,
    home_id: int = 1,
    away_id: int = 2,
) -> None:
    conn.execute(
        """
        INSERT INTO games (
            id, season, week, season_type, start_date, neutral_site, completed,
            home_team_id, away_team_id, home_team, away_team,
            home_points, away_points, home_conference, away_conference, venue, raw_json, sport
        ) VALUES (?, 2019, ?, ?, ?, 0, 1, ?, ?, ?, ?, 21, 14, NULL, NULL, NULL, '{}', 'cfb')
        """,
        (
            game_id,
            week,
            season_type,
            start_date,
            home_id,
            away_id,
            f"Team {home_id}",
            f"Team {away_id}",
        ),
    )


def _keys(conn: sqlite3.Connection) -> list[tuple[str, int | None, str | None]]:
    return [(g.season_type, g.week, g.start_date) for g in _load_games(conn, 2019, "cfb")]


def test_postseason_is_replayed_in_date_order_not_week_order(tmp_path: Path) -> None:
    conn = _make_conn(tmp_path)
    # Inserted with the low ids on the later games, so `id` can't be what
    # orders them correctly.
    _insert(conn, 1, 1, "postseason", "2020-01-11T17:00:00.000Z")  # final
    _insert(conn, 2, 1, "postseason", "2019-12-21T19:00:00.000Z")  # semifinal
    _insert(conn, 3, 16, "postseason", "2019-12-14T17:00:00.000Z")  # quarterfinal
    _insert(conn, 4, 15, "postseason", "2019-12-07T20:30:00.000Z")  # second round
    _insert(conn, 5, 13, "regular", "2019-11-23T20:00:00.000Z")
    conn.commit()

    assert _keys(conn) == [
        ("regular", 13, "2019-11-23T20:00:00.000Z"),
        ("postseason", 15, "2019-12-07T20:30:00.000Z"),
        ("postseason", 16, "2019-12-14T17:00:00.000Z"),
        ("postseason", 1, "2019-12-21T19:00:00.000Z"),
        ("postseason", 1, "2020-01-11T17:00:00.000Z"),
    ]
    conn.close()


def test_regular_season_order_is_still_week_first(tmp_path: Path) -> None:
    """A regular-season game keeps its week order even when its date says
    otherwise (a rescheduled game CFBD keeps in its original week)."""
    conn = _make_conn(tmp_path)
    _insert(conn, 1, 2, "regular", "2019-09-07T19:00:00.000Z")
    _insert(conn, 2, 1, "regular", "2019-12-07T19:00:00.000Z")
    _insert(conn, 3, None, "regular", "2019-08-24T19:00:00.000Z")
    _insert(conn, 4, 1, "regular", "2019-08-31T19:00:00.000Z", home_id=3, away_id=4)
    _insert(conn, 5, 1, "postseason", "2019-11-30T19:00:00.000Z")
    conn.commit()

    assert _keys(conn) == [
        ("regular", 1, "2019-08-31T19:00:00.000Z"),
        ("regular", 1, "2019-12-07T19:00:00.000Z"),
        ("regular", 2, "2019-09-07T19:00:00.000Z"),
        ("regular", None, "2019-08-24T19:00:00.000Z"),
        # The postseason still follows the whole regular season.
        ("postseason", 1, "2019-11-30T19:00:00.000Z"),
    ]
    conn.close()


def test_postseason_unknowns_sort_last_and_order_is_total(tmp_path: Path) -> None:
    """An undated postseason game goes after the dated ones; among equal
    dates, week then id break the tie, so repeated loads are identical."""
    conn = _make_conn(tmp_path)
    _insert(conn, 1, None, "postseason", None)
    _insert(conn, 2, 2, "postseason", None)
    _insert(conn, 3, 1, "postseason", None)
    _insert(conn, 4, 1, "postseason", "2019-12-21T19:00:00.000Z")
    _insert(conn, 5, None, "postseason", "2019-12-21T19:00:00.000Z")
    _insert(conn, 6, 15, "postseason", "2019-12-21T19:00:00.000Z")
    conn.commit()

    first = _load_games(conn, 2019, "cfb")
    assert first == _load_games(conn, 2019, "cfb")
    assert _keys(conn) == [
        ("postseason", 1, "2019-12-21T19:00:00.000Z"),
        ("postseason", 15, "2019-12-21T19:00:00.000Z"),
        ("postseason", None, "2019-12-21T19:00:00.000Z"),
        ("postseason", 1, None),
        ("postseason", 2, None),
        ("postseason", None, None),
    ]
    conn.close()


def test_2019_north_dakota_state_elo_ledger_is_in_date_order(tmp_path: Path) -> None:
    """The regression fixture's 2019 NDSU: second round (postseason week 15,
    Dec 7) and quarterfinal (week 16, Dec 14) come before the semifinal
    (week 1, Dec 21) and final (week 1, Jan 11) in its Elo ledger."""
    dest = tmp_path / "cfb_regression.sqlite3"
    shutil.copy(_FIXTURES_DIR / "cfb_regression.sqlite3", dest)
    conn = get_conn(dest)
    ndsu = conn.execute(
        "SELECT id FROM teams WHERE school = 'North Dakota State' AND sport = 'cfb'"
    ).fetchone()["id"]
    games = _load_games(conn, 2019, "cfb")
    conn.close()

    ledger = EloRating(ELO_CONFIGS["cfb"]).rate(games)[ndsu].elo_ledger
    assert ledger is not None
    dates = [step.start_date for step in ledger.steps if step.start_date is not None]
    assert len(dates) == len(ledger.steps) == 16
    assert dates == sorted(dates)
    assert [(s.season_type, s.week) for s in ledger.steps][-4:] == [
        ("postseason", 15),
        ("postseason", 16),
        ("postseason", 1),
        ("postseason", 1),
    ]
