"""Shared helpers for the player endpoint tests (issue #296).

Not a test module. Imported by the four `tests/test_players_*_endpoint.py`
modules and by `tests/test_players_widened_stats.py`; it imports only the
engine modules apps/api is permitted (`cfb_strength.players`, `db`,
`contracts`), never `ratings` or `ingest`.

- `engine_json` is what "faithful to the engine dataclasses, field for
  field" means as a value: every dataclass field under its own name, with
  `StarterRecord.starts` (a property, so absent from `dataclasses.asdict`)
  added as the one derived field the API publishes. Comparing a response
  body to it checks names, nesting, order of rows and every number at once.
  Its one narrowing is `PlayerStats`, which since #313 carries 24 stats the
  API does not publish yet (`published_stats` below).
- `PUBLISHED_STAT_NAMES` / `published_stats` / `stats_body` are the seam
  between the 34-field engine contract and the 10 fields `PlayerStatsOut`
  publishes (#314 and #315 close that gap). All three read the published
  set off the response model, so widening the API widens them with it and
  no expectation has to be rewritten by hand.
- `make_player_db_with_null_stat` copies the committed fixture and NULLs
  one real season row's stat. No 1999-2025 nflverse row is NULL (the
  contract says so, and the committed fixture has none), so "a None stat
  stays null in JSON, never 0" can only be exercised on a copy.
- `client_for_db` points the app's db dependency at such a copy. The player
  routes use no narrator or cache, so nothing else is overridden.
"""

from __future__ import annotations

import dataclasses
import shutil
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from cfb_strength.contracts import PlayerSeasonType, PlayerStats, StarterRecord
from cfb_strength.db.connection import get_conn
from fastapi.testclient import TestClient

from api.models import PlayerStatsOut

FIXTURE_DB = Path(__file__).resolve().parent / "cfb_verdict_fixture.sqlite3"

# Every stat the engine contract carries (34 since issue #313)...
STAT_NAMES: tuple[str, ...] = tuple(field.name for field in dataclasses.fields(PlayerStats))
# ...and the subset the API publishes, read off the response model rather
# than repeated here, so that #314/#315 widening `PlayerStatsOut` widens
# these helpers with it and no call site has to be edited.
PUBLISHED_STAT_NAMES: tuple[str, ...] = tuple(PlayerStatsOut.model_fields)

_UNPUBLISHED = set(PUBLISHED_STAT_NAMES) - set(STAT_NAMES)
if _UNPUBLISHED:
    raise AssertionError(f"PlayerStatsOut publishes non-contract stats: {sorted(_UNPUBLISHED)}")


def published_stats(stats: PlayerStats) -> dict[str, int | None]:
    """The engine's stats projected onto what the API publishes today.

    `PlayerStats` has carried receiving, kicking and punting since #313, but
    `PlayerStatsOut` deliberately still exposes only the original ten fields
    -- publishing the rest is #314 and #315. So "faithful to the engine,
    field for field" means: every *published* field equals the engine's value
    under its own name. The projection is derived from the response model, so
    a field added there is checked against the engine automatically, and a
    field silently dropped from it is caught by `PUBLISHED_STAT_NAMES`'
    consumers rather than passing unnoticed.
    """
    return {name: getattr(stats, name) for name in PUBLISHED_STAT_NAMES}


def stats_body(**values: int) -> dict[str, int | None]:
    """An expected `PlayerStatsOut` body, named rather than positional.

    Every published stat not named is `None` -- *not applicable*, never 0.
    The four head-to-head games this is used for are quarterback starts, so
    every kicking and punting column is genuinely None rather than a zero
    that would read as "he attempted a field goal and missed".

    Naming rather than positioning is what makes this survive the next
    widening: `PlayerStats` is append-only, so a positional helper silently
    re-binds every value when a field is inserted, and needs a new argument
    at every call site when one is appended.

    A name that is not a stat at all, or one the API does not publish yet,
    is a `ValueError` -- an expectation for a field no response carries can
    only ever be dead weight.
    """
    for name in values:
        if name not in STAT_NAMES:
            raise ValueError(f"{name!r} is not a PlayerStats field")
        if name not in PUBLISHED_STAT_NAMES:
            raise ValueError(
                f"{name!r} is a PlayerStats field the API does not publish yet (#314/#315)"
            )
    return {name: values.get(name) for name in PUBLISHED_STAT_NAMES}


def engine_json(value: object) -> Any:
    """The JSON an engine player-read-layer value must publish as."""
    if isinstance(value, StarterRecord):
        return {
            "wins": value.wins,
            "losses": value.losses,
            "ties": value.ties,
            "starts": value.starts,
        }
    if isinstance(value, PlayerStats):
        return published_stats(value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: engine_json(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, list):
        return [engine_json(item) for item in value]
    return value


@contextmanager
def fixture_conn(db: Path = FIXTURE_DB) -> Iterator[sqlite3.Connection]:
    conn = get_conn(db, read_only=True)
    try:
        yield conn
    finally:
        conn.close()


def make_player_db_with_null_stat(
    tmp_path: Path,
    *,
    player_id: int,
    season: int,
    season_type: PlayerSeasonType,
    stat: str,
) -> Path:
    """A copy of the committed fixture with exactly one real
    `player_season_stats` value set to NULL."""
    if stat not in STAT_NAMES:
        raise ValueError(f"{stat!r} is not a PlayerStats field")
    db = tmp_path / "players_null_stat.sqlite3"
    shutil.copy(FIXTURE_DB, db)
    conn = sqlite3.connect(db)
    try:
        with conn:
            updated = conn.execute(
                f"UPDATE player_season_stats SET {stat} = NULL "
                "WHERE player_id = ? AND season = ? AND season_type = ? AND sport = 'nfl'",
                (player_id, season, season_type),
            ).rowcount
    finally:
        conn.close()
    if updated != 1:
        raise AssertionError(f"expected to NULL one season row, updated {updated}")
    return db


@contextmanager
def client_for_db(db: Path) -> Iterator[TestClient]:
    from api.deps import get_db_conn
    from api.main import app

    def _override() -> Iterator[sqlite3.Connection]:
        conn = get_conn(db, read_only=True)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db_conn] = _override
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db_conn, None)
