"""Shared helpers for the player endpoint tests (issue #296).

Not a test module. Imported by `tests/test_players_leaders_endpoint.py` and
`tests/test_players_career_endpoint.py`; it imports only the engine modules
apps/api is permitted (`cfb_strength.players`, `db`, `contracts`), never
`ratings` or `ingest`.

- `engine_json` is what "faithful to the engine dataclasses, field for
  field" means as a value: every dataclass field under its own name, with
  `StarterRecord.starts` (a property, so absent from `dataclasses.asdict`)
  added as the one derived field the API publishes. Comparing a response
  body to it checks names, nesting, order of rows and every number at once.
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

FIXTURE_DB = Path(__file__).resolve().parent / "cfb_verdict_fixture.sqlite3"

STAT_NAMES: tuple[str, ...] = tuple(field.name for field in dataclasses.fields(PlayerStats))


def engine_json(value: object) -> Any:
    """The JSON an engine player-read-layer value must publish as."""
    if isinstance(value, StarterRecord):
        return {
            "wins": value.wins,
            "losses": value.losses,
            "ties": value.ties,
            "starts": value.starts,
        }
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
