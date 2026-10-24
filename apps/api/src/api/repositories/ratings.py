"""Issue #155's one query: where the other rating methods rank a team.

A verdict is answered by one method (`payload.method`). The envelope also
carries, for the team(s) it is about, the `ratings.rank` of every other
registered method that rated that team that season, so the web can show a
second-opinion rank beside the answer. This is that lookup.

It sits beside `api.repositories.teams` for the same reason that module
exists: a plain SQL read the routes need, with nothing to do with DI or the
persona layer. Like the champion query in `api.verdict`, it reads the
`ratings` table directly; the evidence layer has no "rank of this team under
another method" function, and none is needed for one indexed SELECT.

The caller has already run `build_team_case`/`build_comparison`, which check
the schema (`require_current_schema`), so a stale db never reaches this.
"""

from __future__ import annotations

import sqlite3
from typing import get_args

from api.models import Method, MethodRankOut, Sport

_METHOD_ORDER: tuple[Method, ...] = get_args(Method)


def other_method_ranks(
    conn: sqlite3.Connection, *, year: int, sport: Sport, team_id: int, method: Method
) -> list[MethodRankOut]:
    """One `MethodRankOut` per method in `Method`'s declared order, except
    `method` (the one answering the verdict), that has a `ratings` row for
    `year`/`sport`/`team_id`. A method with no row is left out, so the list
    may be empty. `rank` is `ratings.rank` exactly."""
    rows = conn.execute(
        """
        SELECT method, rank FROM ratings
        WHERE year = ? AND sport = ? AND team_id = ? AND method != ?
        """,
        (year, sport, team_id, method),
    ).fetchall()
    ranks = {str(row["method"]): int(row["rank"]) for row in rows}
    return [
        MethodRankOut(method=other, rank=ranks[other]) for other in _METHOD_ORDER if other in ranks
    ]
