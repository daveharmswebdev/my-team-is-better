"""The team catalog query, shared by every verdict route's grounding input
and the `/api/teams` route. Moved here from `api.deps` by issue #209 so the
persona layer stops importing the FastAPI dependency wiring to reach a query.

`list_team_records` (issue #78) began as the `/api/teams` route's own query:
the teams a user can ask about, with display metadata, optionally narrowed to
one season's rated teams. Since issue #245 each verdict route also reads it
once per request, with no `year`, and since issue #291 hands those records to
the persona layer as `catalog`, the typed-claim validator's team universe
(names, mascots and aliases). That universe must stay unscoped: a narration
mentioning a real-but-unrated opponent must still be recognized as a team
mention and checked against the fact block, so narrowing it would either flag
legitimate opponents or silently accept invented ones. Only the `/api/teams`
route ever passes `year`.

Issue #59 scopes it by `sport` (default "cfb", matching every other call
site's default): CFB and NFL can share a team name (e.g. "Wildcats"), so an
unscoped catalog would let a same-named team from the other sport
contaminate a case that was never about that team.

Before #291 the lexical grounding check read a separate, year-free
names-only query (issue #13) for its "known team names"; it lost its last
caller with #291 and issue #336 deleted it.

It takes an already-open `sqlite3.Connection`: opening one is
`api.deps.get_db_conn`'s job (the FastAPI seam onto
`cfb_strength.db.connection.get_conn`), and this module never imports
`api.deps` -- see the `layers` contract in `apps/api/.importlinter`.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from cfb_strength.evidence.proof import require_current_schema


@dataclass(frozen=True)
class TeamRecord:
    """One selectable team: its canonical name plus the display/search
    metadata epic #76 added to `teams`.

    `name` is `teams.school` verbatim -- the string the client submits back
    and the one the verdict lookup, the persona grounding check, the golden
    dataset, and every cached narration key are keyed on. `mascot` is NULL
    for every NFL row (their `school` already carries city *and* nickname)
    and for any CFB team CFBD has no mascot for. `aliases` is the decoded
    `teams.alternate_names` JSON array, empty when the column is NULL or
    '[]' (both mean "no aliases known").
    """

    name: str
    mascot: str | None
    aliases: tuple[str, ...]


_TEAM_RECORD_COLUMNS = "t.school AS school, t.mascot AS mascot, t.alternate_names AS aliases_json"

# Ordered by `teams.id`, which is the rowid -- i.e. the same order an
# unordered full table scan already produced pre-#78, made explicit so the
# no-`year` response stays byte-identical (order included) rather than
# depending on the query planner.
_ALL_TEAM_RECORDS_SQL = f"""
SELECT {_TEAM_RECORD_COLUMNS}
FROM teams t
WHERE t.sport = ?
ORDER BY t.id
"""

# `ratings.sport` is filtered too, not just `teams.sport`: the join is on
# `team_id` alone, and a rating row carries its own sport, so checking both
# keeps the two columns from ever disagreeing about what a year means.
_RATED_TEAM_RECORDS_SQL = f"""
SELECT {_TEAM_RECORD_COLUMNS}
FROM teams t
JOIN ratings r ON r.team_id = t.id
WHERE t.sport = ? AND r.year = ? AND r.method = ? AND r.sport = ?
ORDER BY t.id
"""


def _decode_aliases(raw: object) -> tuple[str, ...]:
    """Decode a `teams.alternate_names` value into a tuple of alias
    strings. NULL, '[]', and anything that isn't a JSON array of strings
    all decode to empty -- this is display/search metadata populated by an
    ingest path `apps/api` doesn't own, so a malformed value degrades to
    "no aliases" rather than 500-ing a picker-population request.
    """
    if not isinstance(raw, str) or not raw.strip():
        return ()
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return ()
    if not isinstance(decoded, list):
        return ()
    return tuple(alias for alias in decoded if isinstance(alias, str) and alias)


def list_team_records(
    conn: sqlite3.Connection,
    sport: str = "cfb",
    year: int | None = None,
    method: str = "keener",
) -> list[TeamRecord]:
    """Selectable teams for `sport`, with display metadata -- the
    `/api/teams` route's query and, with no `year`, every verdict route's
    grounding catalog (see the module docstring).

    With `year`, restricted to teams holding a `ratings` row for that
    `year`/`sport`/`method`: without it the nflverse ingest's one-row-per-
    historical-`team_abbr` model offers both halves of every relocation
    ("Las Vegas Raiders" for a 2010 question), and the CFB list offers the
    entire FBS/FCS/D2/D3 opponent universe the games ingest has ever seen.
    A year with no ratings at all is an empty list, not an error.

    Without `year`, this is exactly the pre-#78 `SELECT DISTINCT school FROM
    teams WHERE sport = ?` list, same names in the same order -- a client
    that never sends `year` sees no change.

    Runs the engine's `require_current_schema` first (issue #423): both
    queries read late-added columns (`teams.sport`, `teams.alternate_names`,
    and `ratings.sport` with `year`), so a stale db raises
    `StaleDatabaseError` (the API's 503 `stale_database`) rather than a bare
    `sqlite3.OperationalError`, and is refused here exactly as every verdict
    route refuses it, even when the columns this query reads happen to exist.
    """
    require_current_schema(conn)
    if year is None:
        rows = conn.execute(_ALL_TEAM_RECORDS_SQL, (sport,)).fetchall()
    else:
        rows = conn.execute(_RATED_TEAM_RECORDS_SQL, (sport, year, method, sport)).fetchall()

    # Dedupe by name, first row wins -- preserves the pre-#78 query's
    # `DISTINCT school` semantics now that two more columns are selected
    # (two `teams` rows sharing a `school` within one sport must still
    # produce one entry, not two).
    records: dict[str, TeamRecord] = {}
    for row in rows:
        name = str(row["school"])
        if name in records:
            continue
        mascot = row["mascot"]
        records[name] = TeamRecord(
            name=name,
            mascot=str(mascot) if mascot is not None else None,
            aliases=_decode_aliases(row["aliases_json"]),
        )
    return list(records.values())
