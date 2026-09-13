"""Throwaway sqlite db with ratings under every registered `Method` (issue #152).

`cfb_verdict_fixture.sqlite3` bakes `keener` and `elo` only; `elo_career` is
deliberately absent there because its reversion over non-contiguous seasons
would model nothing (see `build_fixture.py`, issue #98). A test that proves
the compare envelope echoes *each* method therefore can't run on it for
`elo_career`, and skipping that parametrization would be exactly the silent
gap this fixture exists to avoid.

This is a plumbing fixture, not a ratings fixture: the rows are hand-written,
one set per value of `typing.get_args(Method)` (so a newly registered method
gets rows automatically), and no test should read meaning into the numbers --
in particular, not whether one method ranks the teams the same way as
another. The ratings deliberately differ per method only so each method's
rows are distinguishable in the db. No `rating_breakdowns` rows are written;
an empty breakdown is the shape the engine already serves for Elo.

Not part of the pytest suite itself (doesn't match `test_*.py`) -- imported by
`test_verdict_compare_method.py`.
"""

from __future__ import annotations

from pathlib import Path
from typing import get_args

from cfb_strength.contracts import Method
from cfb_strength.db.connection import ensure_schema, get_conn

from fixtures.sport_fixture import _insert_game, _insert_rating, _insert_team

YEAR = 2023
TEAM_A = "Alpha State"
TEAM_B = "Bravo Tech"
_TEAMS = {1: TEAM_A, 2: TEAM_B, 3: "Charlie U"}
METHODS: tuple[Method, ...] = get_args(Method)


def make_method_fixture_db(tmp_path: Path) -> Path:
    """Build a fresh db at `tmp_path / "method_fixture.sqlite3"` holding a
    3-team CFB season rated under every registered method; return its path."""
    db_path = tmp_path / "method_fixture.sqlite3"
    conn = get_conn(db_path)
    ensure_schema(conn)

    for team_id, name in _TEAMS.items():
        _insert_team(conn, team_id, name, classification="fbs")
    _insert_game(conn, 1, YEAR, 1, 2, _TEAMS[1], _TEAMS[2], 30, 10)
    _insert_game(conn, 2, YEAR, 2, 3, _TEAMS[2], _TEAMS[3], 20, 17, week=2)
    _insert_game(conn, 3, YEAR, 1, 3, _TEAMS[1], _TEAMS[3], 40, 3, week=3)

    for offset, method in enumerate(METHODS):
        _insert_rating(conn, YEAR, method, 1, 3.0 + offset, 1, 2, 0)
        _insert_rating(conn, YEAR, method, 2, 2.0 + offset, 2, 1, 1)
        _insert_rating(conn, YEAR, method, 3, 1.0 + offset, 3, 0, 2)

    conn.commit()
    conn.close()
    return db_path
