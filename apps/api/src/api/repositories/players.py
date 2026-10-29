"""The player-name universe for the QB narration's claim check (issue #451).

`api.persona.qb_claims.check_and_render_qb` rejects a third player's full
name typed into a QB narration ("Marshall Faulk" in Warner vs McNair), and
needs every player name in the sport to recognise one. This is that query,
every distinct player name for the sport with no season or position filter:
the route reads it on its own connection and hands the names to the persona
layer, which never queries (`apps/api/.importlinter`'s layers contract keeps
this module below `api.persona` and `api.deps`).

The `players` table is the engine's (`cfb_strength.db`'s schema, read-only
here); the QB verdict route only reaches this after the engine has already
read that table for both players.
"""

from __future__ import annotations

import sqlite3


def list_player_names(conn: sqlite3.Connection, sport: str) -> frozenset[str]:
    """Every distinct player `display_name` in the db for `sport`, any
    position, any season."""
    rows = conn.execute(
        "SELECT DISTINCT display_name FROM players WHERE sport = ?", (sport,)
    ).fetchall()
    return frozenset(str(row[0]) for row in rows)
