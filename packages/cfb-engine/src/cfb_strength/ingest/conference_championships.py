"""The curated list of FBS conference title games (issue #300).

CFBD files conference title games as season_type 'regular' from 2001 on (in
1998-2000 they sit in the postseason payload), and its `notes` field names
them only from 2022: every FBS title game 2001-2021 has `notes: null`. So
no field of the record says which games are title games, and a schedule
rule ("the last same-conference game of the season") is wrong in both
directions. Measured over the committed cache, it picks Army-Navy as the
2024 and 2025 American title game, rescheduled games (2001 Auburn-LSU, 2001
C-USA Southern Miss-TCU, Pac-10 late games), Big East games and Big 12
2011-2016 games, and misses 2020's title games played the same weekend as
rescheduled ones.

The flag is data, not a rule, the same pattern as #343's neutral-site
overrides. `data/raw/cfbd_conference_championships.json` lists each title
game by CFBD id, with the season, season type and home/away team names
exactly as CFBD reports them, CFBD's conference name and a source. No date,
week, venue, notes or conference heuristic decides the flag at ingest time:
only the listed ids get `conference_championship=True`. `season_type` is
never changed, and `raw_json` keeps CFBD's original record.

`apply_conference_championships` runs in `ingest_one` on the normalized
rows of one deduped batch, logs one INFO line per flagged game, and raises
`ConferenceChampionshipError`, never silently skips, when

  * an entry for this batch's season and season type names an id the
    deduped batch doesn't hold,
  * a listed id appears in a batch of a different season or season type, or
  * the record's home/away teams differ from the entry's,

and `load_conference_championships` raises on a duplicate id or a malformed
entry.

Like the override file, the list is committed, reviewed data rather than
cache, so its path is fixed to the package's `data/raw/` and doesn't follow
`CFB_DATA_DIR`.
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

CONFERENCE_CHAMPIONSHIPS_PATH = PROJECT_ROOT / "data" / "raw" / "cfbd_conference_championships.json"

_ENTRY_FIELDS = frozenset(
    {"id", "season", "season_type", "home_team", "away_team", "conference", "source"}
)


class ConferenceChampionshipError(ValueError):
    """A title-game entry is malformed, duplicated, or doesn't match the
    CFBD record it names."""


@dataclass(frozen=True)
class ConferenceChampionship:
    game_id: int
    season: int
    season_type: str
    home_team: str
    away_team: str
    conference: str
    source: str

    def describe(self) -> str:
        teams = f"{self.away_team} at {self.home_team}"
        return f"{self.game_id} ({self.season} {self.season_type}, {teams})"


def _nonempty_str(entry: dict[str, Any], field: str, where: str) -> str:
    value = entry[field]
    if not isinstance(value, str) or not value.strip():
        raise ConferenceChampionshipError(
            f"{where}: {field} must be a non-empty string, got {value!r}"
        )
    return value


def _int(entry: dict[str, Any], field: str, where: str) -> int:
    value = entry[field]
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConferenceChampionshipError(f"{where}: {field} must be an integer, got {value!r}")
    return value


def _parse_entry(entry: object, index: int) -> ConferenceChampionship:
    where = f"conference championship entry {index}"
    if not isinstance(entry, dict):
        raise ConferenceChampionshipError(f"{where}: expected an object, got {entry!r}")
    if "id" in entry:
        where = f"{where} (id {entry['id']})"
    missing = _ENTRY_FIELDS - entry.keys()
    if missing:
        raise ConferenceChampionshipError(f"{where}: missing field(s) {', '.join(sorted(missing))}")
    unknown = entry.keys() - _ENTRY_FIELDS
    if unknown:
        raise ConferenceChampionshipError(f"{where}: unknown field(s) {', '.join(sorted(unknown))}")
    season_type = _nonempty_str(entry, "season_type", where)
    if season_type not in SEASON_TYPES:
        raise ConferenceChampionshipError(
            f"{where}: season_type must be one of {SEASON_TYPES}, got {season_type!r}"
        )
    return ConferenceChampionship(
        game_id=_int(entry, "id", where),
        season=_int(entry, "season", where),
        season_type=season_type,
        home_team=_nonempty_str(entry, "home_team", where),
        away_team=_nonempty_str(entry, "away_team", where),
        conference=_nonempty_str(entry, "conference", where),
        source=_nonempty_str(entry, "source", where),
    )


def _index_by_id(
    championships: Iterable[ConferenceChampionship],
) -> dict[int, ConferenceChampionship]:
    by_id: dict[int, ConferenceChampionship] = {}
    for championship in championships:
        if championship.game_id in by_id:
            raise ConferenceChampionshipError(
                f"duplicate conference championship entry for game id {championship.game_id}"
            )
        by_id[championship.game_id] = championship
    return by_id


def load_conference_championships(
    path: Path = CONFERENCE_CHAMPIONSHIPS_PATH,
) -> tuple[ConferenceChampionship, ...]:
    """Read and validate the list. Raises on a malformed entry or a
    duplicate id."""
    document = json.loads(path.read_text())
    if not isinstance(document, dict) or not isinstance(document.get("championships"), list):
        raise ConferenceChampionshipError(f"{path}: expected an object with a 'championships' list")
    championships = tuple(
        _parse_entry(entry, i) for i, entry in enumerate(document["championships"])
    )
    _index_by_id(championships)
    return championships


def apply_conference_championships(
    rows: Sequence[GameRow],
    *,
    season: int,
    season_type: str,
    championships: Iterable[ConferenceChampionship],
) -> list[GameRow]:
    """Return `rows` with every listed game flagged
    `conference_championship=True`. `rows` must be one deduped
    (season, season_type) batch."""
    by_id = _index_by_id(championships)

    present = {row.id for row in rows}
    missing = [
        c.describe()
        for c in by_id.values()
        if (c.season, c.season_type) == (season, season_type) and c.game_id not in present
    ]
    if missing:
        raise ConferenceChampionshipError(
            f"conference championship(s) not found in the deduped {season} {season_type} "
            f"payload: {'; '.join(missing)}"
        )

    flagged: list[GameRow] = []
    for row in rows:
        championship = by_id.get(row.id)
        if championship is None:
            flagged.append(row)
            continue
        if (championship.season, championship.season_type) != (season, season_type) or (
            row.season != championship.season
        ):
            raise ConferenceChampionshipError(
                f"conference championship {championship.describe()} matched game {row.id} in "
                f"the {season} {season_type} payload (record season {row.season})"
            )
        if (row.home_team, row.away_team) != (championship.home_team, championship.away_team):
            raise ConferenceChampionshipError(
                f"conference championship {championship.describe()} doesn't match CFBD's "
                f"record: {row.away_team} at {row.home_team}"
            )
        logger.info(
            "conference championship %s: %s title game, season_type stays %r (%s)",
            championship.describe(),
            championship.conference,
            row.season_type,
            championship.source,
        )
        flagged.append(dataclasses.replace(row, conference_championship=True))
    return flagged
