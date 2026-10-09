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
  Its one narrowing is `PlayerStats`, which since #354 carries 42 stats, 14
  of which the API does not publish (`UNPUBLISHED_STATS` below):
  `rushing_first_downs`, `rushing_fumbles_lost`, the four 0-49 yard
  field-goal buckets left out on purpose by #315, and #354's five defensive
  and three EPA columns (stored in the fixture, published by #317 and #347).
- `PUBLISHED_STAT_NAMES` / `published_stats` / `stats_body` are the seam
  between the 42-field engine contract and the 28 fields `PlayerStatsOut`
  publishes (the original ten, #314's six receiving stats and #315's twelve
  kicking and punting stats). All three read the published set off the response
  model, so widening the API widens them with it and no expectation has to
  be rewritten by hand. The flip side: a field *dropped* from the model
  drops out of these too, so the helpers alone cannot catch it. That is
  `PUBLISHED_STATS`' job, a literal list.
- `make_player_db_with_null_stat` copies the committed fixture and NULLs
  one real season row's stat. No 1999-2025 nflverse row is NULL *for the
  stats this helper targets* -- that was true of all ten columns before
  #313, and is still true of the passing and rushing ones it NULLs. It is
  no longer true of the contract as a whole: `fg_long` and `pt_long` are
  legitimately NULL for anyone who never kicked or punted (`fg_long` is
  NULL on 3,886 of the committed fixture's 3,987 season rows since #354
  added defensive players), and an EPA column is NULL for a player with no
  play of that kind. So "a None stat
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

# Every stat the engine contract carries (42 since issue #354)...
STAT_NAMES: tuple[str, ...] = tuple(field.name for field in dataclasses.fields(PlayerStats))
# ...and the subset the API publishes (28 since #315), read off the response
# model rather than repeated here, so that widening `PlayerStatsOut` widens
# these helpers with it and no call site has to be edited.
PUBLISHED_STAT_NAMES: tuple[str, ...] = tuple(PlayerStatsOut.model_fields)

# The twenty-eight stats the API publishes, written out rather than derived:
# the original ten, #314's six receiving stats and #315's twelve kicking and
# punting stats, in `PlayerStatsOut`'s order. `contracts.PlayerStats` has
# carried 42 columns since #354; the fourteen it carries and the API does not
# publish are `UNPUBLISHED_STATS` below. Deriving this list from the response
# model would make every assertion on it tautological -- see
# `test_players_leaders_endpoint.test_published_stat_keys_are_pinned`. It
# lives here, not in one test module, because two modules compare response
# bodies to it: the leaders tests and the #354 "stored, not published" check
# in `test_players_widened_stats.py`.
PUBLISHED_STATS: tuple[str, ...] = (
    "completions",
    "attempts",
    "passing_yards",
    "passing_tds",
    "passing_interceptions",
    "sacks_suffered",
    "sack_yards_lost",
    "carries",
    "rushing_yards",
    "rushing_tds",
    "receptions",
    "targets",
    "receiving_yards",
    "receiving_tds",
    "receiving_first_downs",
    "receiving_fumbles_lost",
    "fg_made",
    "fg_att",
    "fg_long",
    "fg_made_50_59",
    "fg_made_60_",
    "pat_made",
    "pat_att",
    "pt_att",
    "pt_yards",
    "pt_net_yards",
    "pt_long",
    "pt_inside_20",
)

# The contract stats the API deliberately leaves out, in contract order,
# also a literal: `rushing_first_downs` and `rushing_fumbles_lost` (#313,
# never published), the 0-49 yard field-goal buckets (#315, left out on
# purpose), and #354's five defensive and three EPA columns (publishing is
# #317 for defense and #347 for EPA).
UNPUBLISHED_RUSHING_STATS: tuple[str, ...] = ("rushing_first_downs", "rushing_fumbles_lost")
UNPUBLISHED_FG_BUCKETS: tuple[str, ...] = (
    "fg_made_0_19",
    "fg_made_20_29",
    "fg_made_30_39",
    "fg_made_40_49",
)
DEFENSE_STATS: tuple[str, ...] = (
    "def_interceptions",
    "def_sacks",
    "def_fumbles_forced",
    "def_tackles_solo",
    "def_pass_defended",
)
EPA_STATS: tuple[str, ...] = ("passing_epa", "rushing_epa", "receiving_epa")
UNPUBLISHED_STATS: tuple[str, ...] = (
    *UNPUBLISHED_RUSHING_STATS,
    *UNPUBLISHED_FG_BUCKETS,
    *DEFENSE_STATS,
    *EPA_STATS,
)

_UNPUBLISHED = set(PUBLISHED_STAT_NAMES) - set(STAT_NAMES)
if _UNPUBLISHED:
    raise AssertionError(f"PlayerStatsOut publishes non-contract stats: {sorted(_UNPUBLISHED)}")


def published_stats(stats: PlayerStats) -> dict[str, int | None]:
    """The engine's stats projected onto what the API publishes today.

    `PlayerStats` has carried receiving, kicking and punting since #313;
    `PlayerStatsOut` publishes the original ten fields, the six receiving
    ones (#314) and twelve kicking and punting ones (#315). So "faithful to
    the engine, field for field" means: every *published* field equals the
    engine's value under its own name. The projection is derived from the
    response model, so a field added there is checked against the engine
    automatically. A field silently dropped from it would drop out of this
    projection too; the literal `PUBLISHED_STATS` above is what catches
    that.
    """
    return {name: getattr(stats, name) for name in PUBLISHED_STAT_NAMES}


def stats_body(**values: int) -> dict[str, int | None]:
    """An expected `PlayerStatsOut` body, named rather than positional.

    Every published stat not named is `None` -- *not applicable*, never 0.
    The four head-to-head games this is used for are quarterback starts.
    Their receiving, kicking and punting counts are recorded zeros (nflverse
    writes 0 there), so the caller names them. `fg_long` and `pt_long` are
    maxima of nothing for a quarterback, so they stay unnamed and None --
    a 0 would read as "his longest field goal was zero yards".

    Naming rather than positioning is what makes this survive the next
    widening: `PlayerStats` is append-only, so a positional helper silently
    re-binds every value when a field is inserted, and needs a new argument
    at every call site when one is appended.

    A name that is not a stat at all, or one the API does not publish, is a
    `ValueError` -- an expectation for a field no response carries can
    only ever be dead weight.
    """
    for name in values:
        if name not in STAT_NAMES:
            raise ValueError(f"{name!r} is not a PlayerStats field")
        if name not in PUBLISHED_STAT_NAMES:
            raise ValueError(f"{name!r} is a PlayerStats field the API does not publish")
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
