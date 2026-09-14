"""Throwaway sqlite db builder for `/api/teams`' year-scoping and
mascot/alias payload tests (GitHub issue #78, epic #76).

Neither existing fixture can cover this issue:

* `cfb_verdict_fixture.sqlite3` (committed, real-engine-computed) has real
  CFB ratings for the seven golden seasons and 451 real team names --
  perfect for the "an unrated opponent disappears once `?year=` is
  supplied" half, and used directly for that -- but it has no NFL rows at
  all. Since #110 it does carry real CFBD mascots/aliases (#77), but only in
  their real shapes, so it can't pin the `'[]'` storage shape this module
  hand-builds.
* `sport_fixture.py` has NFL rows, but a single year (2023, plus one 2024
  NFL row) and no relocated franchises -- so it can't express the bug this
  issue is about: the nflverse ingest mints one `teams` row per historical
  `team_abbr`, so "Oakland Raiders" and "Las Vegas Raiders" are two
  separate rows whose ratings live in disjoint year ranges. Extending it
  in place would also break its own tests, which pin exact year lists
  (`test_catalog_sport.py`).

So this module builds a third, purpose-built db: two seasons (2010 and
2024) either side of three real NFL relocations, plus CFB rows carrying
populated `mascot`/`alternate_names` values in all three of their real
shapes (a real JSON array, `'[]'`, and `NULL`).

Only `teams` and `ratings` are populated -- `/api/teams` reads nothing
else, and no `TeamCase` is ever built from this db (that's what
`sport_fixture.py` / the committed fixture are for).

Not part of the pytest suite itself (doesn't match `test_*.py`) -- imported
by `tests/conftest.py`'s `team_catalog_client` fixture and by
`test_catalog_team_details.py`.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from cfb_strength.db.connection import ensure_schema, get_conn

METHOD = "keener"
OLD_YEAR = 2010
NEW_YEAR = 2024
UNINGESTED_YEAR = 1997

# (id, school, mascot, alternate_names, sport, years rated)
#
# CFB rows exercise all three `alternate_names` storage shapes -- a real
# JSON array, the empty array `'[]'`, and `NULL` -- since the API must
# decode the first and treat the other two identically as "no aliases".
# NFL rows all carry `mascot = NULL` (their `school` already contains city
# *and* nickname) and are split across the relocation boundary.
TEAM_ROWS: tuple[tuple[int, str, str | None, str | None, str, tuple[int, ...]], ...] = (
    (1, "Texas", "Longhorns", '["TEX", "Texas Longhorns"]', "cfb", (OLD_YEAR, NEW_YEAR)),
    (2, "Ohio State", "Buckeyes", '["OSU"]', "cfb", (OLD_YEAR, NEW_YEAR)),
    # mascot present, aliases stored as an explicitly empty JSON array
    (3, "Empty Alias Tech", "Zeroes", "[]", "cfb", (OLD_YEAR,)),
    # both columns NULL -- the state every row in a not-yet-#77-ingested db
    # is in, and a legitimate permanent state for a team CFBD has no mascot
    # for
    (4, "Null Alias State", None, None, "cfb", (OLD_YEAR,)),
    # never rated in any year: the FCS/D2/D3 opponent universe that makes
    # the unscoped CFB list ~6x longer than any single season's
    (5, "Never Rated College", "Ghosts", '["NRC"]', "cfb", ()),
    (6, "Also Never Rated A&M", None, None, "cfb", ()),
    (7, "Also Never Rated Poly", None, "[]", "cfb", ()),
    (8, "Recent Expansion U", "Newcomers", '["REU"]', "cfb", (NEW_YEAR,)),
    (101, "Oakland Raiders", None, None, "nfl", (OLD_YEAR,)),
    (102, "Las Vegas Raiders", None, None, "nfl", (NEW_YEAR,)),
    (103, "San Diego Chargers", None, None, "nfl", (OLD_YEAR,)),
    (104, "Los Angeles Chargers", None, None, "nfl", (NEW_YEAR,)),
    (105, "St. Louis Rams", None, None, "nfl", (OLD_YEAR,)),
    (106, "Los Angeles Rams", None, None, "nfl", (NEW_YEAR,)),
    (107, "New England Patriots", None, None, "nfl", (OLD_YEAR, NEW_YEAR)),
)

# Franchises whose two halves must never both be offered for one season.
RELOCATED_PAIRS: tuple[tuple[str, str], ...] = (
    ("Oakland Raiders", "Las Vegas Raiders"),
    ("San Diego Chargers", "Los Angeles Chargers"),
    ("St. Louis Rams", "Los Angeles Rams"),
)


def build_team_catalog_fixture(conn: sqlite3.Connection) -> None:
    """Populate `conn` (an already-`ensure_schema`'d connection) from
    `TEAM_ROWS`."""
    for team_id, school, mascot, alternate_names, sport, years in TEAM_ROWS:
        conn.execute(
            """
            INSERT INTO teams (id, school, classification, sport, mascot, alternate_names)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (team_id, school, "fbs" if sport == "cfb" else None, sport, mascot, alternate_names),
        )
        for year in years:
            # `rank`/`rating` are unread by `/api/teams` (it only cares
            # whether a ratings row exists at all) -- `team_id` just keeps
            # them distinct within a year rather than meaningful.
            conn.execute(
                """
                INSERT INTO ratings (
                    year, method, team_id, rating, rank, wins, losses, computed_at, sport
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'test', ?)
                """,
                (year, METHOD, team_id, 1.0, team_id, 1, 0, sport),
            )


def make_team_catalog_fixture_db(tmp_path: Path) -> Path:
    """Build a fresh schema-only db at `tmp_path / "team_catalog.sqlite3"`,
    populate it via `build_team_catalog_fixture`, and return its path."""
    db_path = tmp_path / "team_catalog.sqlite3"
    conn = get_conn(db_path)
    ensure_schema(conn)
    build_team_catalog_fixture(conn)
    conn.commit()
    conn.close()
    return db_path
