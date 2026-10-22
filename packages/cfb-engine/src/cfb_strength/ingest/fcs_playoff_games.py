"""The curated list of FCS (I-AA) playoff games (issue #379).

CFBD files most FCS playoff games as season_type 'regular': the 2013 first
round sits in regular week 14, and in most seasons every round before the
semifinals is 'regular' (2023 is the exception: CFBD files its whole bracket
as postseason). Its `notes` mark only part of the bracket (none at all in
2016-2018, and the semifinals and final are unmarked before 2022), so no
field of the record says which games are playoff games.

The label is data, not a rule, the same pattern as #343's neutral-site
overrides and #300's title games. `data/raw/cfbd_fcs_playoff_games.json`
lists every FCS playoff game in the committed cache by CFBD id, with the
season, CFBD's season type, the home/away team names exactly as CFBD
reports them, the bracket round and a provenance note. Its `seasons` block
records, for each season 1998-2025, the bracket size and whether the cache
holds the whole bracket (and if not, what is missing). No notes regex,
date, week or classification rule decides anything at ingest time: only the
listed ids change.

`apply_fcs_playoff_games` runs in `ingest_one` on the normalized rows of
one deduped batch. It sets `season_type='postseason'` on each listed game
CFBD files as 'regular' and logs one INFO line per change; a listed game
CFBD already files as postseason is left as it is. `week`, every other
column and `raw_json` keep CFBD's values, so the correction shows up as a
diff between `raw_json` and the row. It raises `FcsPlayoffGameError`, never
silently skips, when

  * an entry for this batch's season and season type names an id the
    deduped batch doesn't hold,
  * a listed id appears in a batch of a different season or season type, or
  * the record's home/away teams differ from the entry's,

and `load_fcs_playoff_games` raises on a duplicate id or a malformed entry.

Like the other curated lists, the file is committed, reviewed data rather
than cache, so its path is fixed to the package's `data/raw/` and doesn't
follow `CFB_DATA_DIR`.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cfb_strength.config import PROJECT_ROOT, SEASON_TYPES
from cfb_strength.contracts import GameRow

logger = logging.getLogger(__name__)

FCS_PLAYOFF_GAMES_PATH = PROJECT_ROOT / "data" / "raw" / "cfbd_fcs_playoff_games.json"

POSTSEASON = "postseason"

ROUNDS = ("first round", "second round", "quarterfinal", "semifinal", "final")

_ENTRY_FIELDS = frozenset(
    {"id", "season", "season_type", "home_team", "away_team", "round", "source"}
)


class FcsPlayoffGameError(ValueError):
    """An FCS playoff entry is malformed, duplicated, or doesn't match the
    CFBD record it names."""


@dataclass(frozen=True)
class FcsPlayoffGame:
    game_id: int
    season: int
    season_type: str
    home_team: str
    away_team: str
    round: str
    source: str

    def describe(self) -> str:
        teams = f"{self.away_team} at {self.home_team}"
        return f"{self.game_id} ({self.season} {self.season_type}, {teams}, {self.round})"


def _nonempty_str(entry: dict[str, Any], field: str, where: str) -> str:
    value = entry[field]
    if not isinstance(value, str) or not value.strip():
        raise FcsPlayoffGameError(f"{where}: {field} must be a non-empty string, got {value!r}")
    return value


def _int(entry: dict[str, Any], field: str, where: str) -> int:
    value = entry[field]
    if not isinstance(value, int) or isinstance(value, bool):
        raise FcsPlayoffGameError(f"{where}: {field} must be an integer, got {value!r}")
    return value


def _parse_entry(entry: object, index: int) -> FcsPlayoffGame:
    where = f"FCS playoff entry {index}"
    if not isinstance(entry, dict):
        raise FcsPlayoffGameError(f"{where}: expected an object, got {entry!r}")
    if "id" in entry:
        where = f"{where} (id {entry['id']})"
    missing = _ENTRY_FIELDS - entry.keys()
    if missing:
        raise FcsPlayoffGameError(f"{where}: missing field(s) {', '.join(sorted(missing))}")
    unknown = entry.keys() - _ENTRY_FIELDS
    if unknown:
        raise FcsPlayoffGameError(f"{where}: unknown field(s) {', '.join(sorted(unknown))}")
    season_type = _nonempty_str(entry, "season_type", where)
    if season_type not in SEASON_TYPES:
        raise FcsPlayoffGameError(
            f"{where}: season_type must be one of {SEASON_TYPES}, got {season_type!r}"
        )
    round_ = _nonempty_str(entry, "round", where)
    if round_ not in ROUNDS:
        raise FcsPlayoffGameError(f"{where}: round must be one of {ROUNDS}, got {round_!r}")
    return FcsPlayoffGame(
        game_id=_int(entry, "id", where),
        season=_int(entry, "season", where),
        season_type=season_type,
        home_team=_nonempty_str(entry, "home_team", where),
        away_team=_nonempty_str(entry, "away_team", where),
        round=round_,
        source=_nonempty_str(entry, "source", where),
    )


def _index_by_id(games: Iterable[FcsPlayoffGame]) -> dict[int, FcsPlayoffGame]:
    by_id: dict[int, FcsPlayoffGame] = {}
    for game in games:
        if game.game_id in by_id:
            raise FcsPlayoffGameError(f"duplicate FCS playoff entry for game id {game.game_id}")
        by_id[game.game_id] = game
    return by_id


def load_fcs_playoff_games(
    path: Path = FCS_PLAYOFF_GAMES_PATH,
) -> tuple[FcsPlayoffGame, ...]:
    """Read and validate the list's `games`. Raises on a malformed entry or
    a duplicate id. The `seasons` block is documentation for reviewers and
    the data tests; ingest doesn't read it."""
    document = json.loads(path.read_text())
    if not isinstance(document, dict) or not isinstance(document.get("games"), list):
        raise FcsPlayoffGameError(f"{path}: expected an object with a 'games' list")
    games = tuple(_parse_entry(entry, i) for i, entry in enumerate(document["games"]))
    _index_by_id(games)
    return games


def apply_fcs_playoff_games(
    rows: Sequence[GameRow],
    *,
    season: int,
    season_type: str,
    games: Iterable[FcsPlayoffGame],
) -> list[GameRow]:
    """Return `rows` with every listed game's `season_type` set to
    'postseason'. `rows` must be one deduped (season, season_type) batch."""
    by_id = _index_by_id(games)

    present = {row.id for row in rows}
    missing = [
        g.describe()
        for g in by_id.values()
        if (g.season, g.season_type) == (season, season_type) and g.game_id not in present
    ]
    if missing:
        raise FcsPlayoffGameError(
            f"FCS playoff game(s) not found in the deduped {season} {season_type} "
            f"payload: {'; '.join(missing)}"
        )

    relabelled: list[GameRow] = []
    for row in rows:
        game = by_id.get(row.id)
        if game is None:
            relabelled.append(row)
            continue
        if (game.season, game.season_type) != (season, season_type) or row.season != game.season:
            raise FcsPlayoffGameError(
                f"FCS playoff game {game.describe()} matched game {row.id} in the "
                f"{season} {season_type} payload (record season {row.season})"
            )
        if (row.home_team, row.away_team) != (game.home_team, game.away_team):
            raise FcsPlayoffGameError(
                f"FCS playoff game {game.describe()} doesn't match CFBD's record: "
                f"{row.away_team} at {row.home_team}"
            )
        if row.season_type == POSTSEASON:
            relabelled.append(row)
            continue
        logger.info(
            "FCS playoff game %s: season_type %r -> %r, week %s kept (%s)",
            game.describe(),
            row.season_type,
            POSTSEASON,
            row.week,
            game.source,
        )
        relabelled.append(dataclasses.replace(row, season_type=POSTSEASON))
    return relabelled
