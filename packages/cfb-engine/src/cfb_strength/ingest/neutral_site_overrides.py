"""Curated corrections to CFBD's `neutralSite` flag (issue #343).

CFBD's `/games` data stores `neutralSite: false` for neutral-site games in
1998-2007. Measured over the committed cache, FBS-vs-FBS regular-season
neutral flags are 0 in every year 1998-2003 and 2005-2007 (8 in 2004, all
ESPN duplicate copies), against 13-26 every year from 2008. So conference
title games, Red River, Florida-Georgia and Army-Navy from those years are
stored as home games.

The correction is data, not a rule. `data/raw/cfbd_neutral_site_overrides.json`
lists each game by CFBD id, with the season, season type and home/away team
names exactly as CFBD reports them, the corrected venue and a source. No
date, venue-name, conference or year heuristic is involved: only the listed
ids change, and every other game is stored exactly as CFBD reports it.

`apply_neutral_site_overrides` runs in `ingest_one` on the normalized rows
of one deduped batch. It sets `neutral_site=True` and the override venue on
each listed game, logs one INFO line per applied override, and leaves
`raw_json` holding CFBD's original record, so the correction shows up as a
diff between `raw_json` and the row. It raises `NeutralSiteOverrideError`,
never silently skips, when

  * an entry for this batch's season and season type names an id the
    deduped batch doesn't hold,
  * a listed id appears in a batch of a different season or season type, or
  * the record's home/away teams differ from the entry's,

and `load_neutral_site_overrides` raises on a duplicate id or a malformed
entry.

The file sits beside the CFBD cache it corrects, but it is committed,
reviewed data rather than cache, so its path is fixed to the package's
`data/raw/` and doesn't follow `CFB_DATA_DIR`.
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

NEUTRAL_SITE_OVERRIDES_PATH = PROJECT_ROOT / "data" / "raw" / "cfbd_neutral_site_overrides.json"

_ENTRY_FIELDS = frozenset(
    {"id", "season", "season_type", "home_team", "away_team", "neutral_site", "venue", "source"}
)


class NeutralSiteOverrideError(ValueError):
    """An override entry is malformed, duplicated, or doesn't match the
    CFBD record it names."""


@dataclass(frozen=True)
class NeutralSiteOverride:
    game_id: int
    season: int
    season_type: str
    home_team: str
    away_team: str
    venue: str
    source: str

    def describe(self) -> str:
        teams = f"{self.away_team} at {self.home_team}"
        return f"{self.game_id} ({self.season} {self.season_type}, {teams})"


def _nonempty_str(entry: dict[str, Any], field: str, where: str) -> str:
    value = entry[field]
    if not isinstance(value, str) or not value.strip():
        raise NeutralSiteOverrideError(
            f"{where}: {field} must be a non-empty string, got {value!r}"
        )
    return value


def _int(entry: dict[str, Any], field: str, where: str) -> int:
    value = entry[field]
    if not isinstance(value, int) or isinstance(value, bool):
        raise NeutralSiteOverrideError(f"{where}: {field} must be an integer, got {value!r}")
    return value


def _parse_entry(entry: object, index: int) -> NeutralSiteOverride:
    where = f"override entry {index}"
    if not isinstance(entry, dict):
        raise NeutralSiteOverrideError(f"{where}: expected an object, got {entry!r}")
    if "id" in entry:
        where = f"{where} (id {entry['id']})"
    missing = _ENTRY_FIELDS - entry.keys()
    if missing:
        raise NeutralSiteOverrideError(f"{where}: missing field(s) {', '.join(sorted(missing))}")
    unknown = entry.keys() - _ENTRY_FIELDS
    if unknown:
        raise NeutralSiteOverrideError(f"{where}: unknown field(s) {', '.join(sorted(unknown))}")
    if entry["neutral_site"] is not True:
        raise NeutralSiteOverrideError(
            f"{where}: neutral_site must be true, got {entry['neutral_site']!r}"
        )
    season_type = _nonempty_str(entry, "season_type", where)
    if season_type not in SEASON_TYPES:
        raise NeutralSiteOverrideError(
            f"{where}: season_type must be one of {SEASON_TYPES}, got {season_type!r}"
        )
    return NeutralSiteOverride(
        game_id=_int(entry, "id", where),
        season=_int(entry, "season", where),
        season_type=season_type,
        home_team=_nonempty_str(entry, "home_team", where),
        away_team=_nonempty_str(entry, "away_team", where),
        venue=_nonempty_str(entry, "venue", where),
        source=_nonempty_str(entry, "source", where),
    )


def _index_by_id(overrides: Iterable[NeutralSiteOverride]) -> dict[int, NeutralSiteOverride]:
    by_id: dict[int, NeutralSiteOverride] = {}
    for override in overrides:
        if override.game_id in by_id:
            raise NeutralSiteOverrideError(
                f"duplicate neutral-site override for game id {override.game_id}"
            )
        by_id[override.game_id] = override
    return by_id


def load_neutral_site_overrides(
    path: Path = NEUTRAL_SITE_OVERRIDES_PATH,
) -> tuple[NeutralSiteOverride, ...]:
    """Read and validate the override file. Raises on a malformed entry or
    a duplicate id."""
    document = json.loads(path.read_text())
    if not isinstance(document, dict) or not isinstance(document.get("overrides"), list):
        raise NeutralSiteOverrideError(f"{path}: expected an object with an 'overrides' list")
    overrides = tuple(_parse_entry(entry, i) for i, entry in enumerate(document["overrides"]))
    _index_by_id(overrides)
    return overrides


def apply_neutral_site_overrides(
    rows: Sequence[GameRow],
    *,
    season: int,
    season_type: str,
    overrides: Iterable[NeutralSiteOverride],
) -> list[GameRow]:
    """Return `rows` with every listed game set neutral at its override
    venue. `rows` must be one deduped (season, season_type) batch."""
    by_id = _index_by_id(overrides)

    present = {row.id for row in rows}
    missing = [
        o.describe()
        for o in by_id.values()
        if (o.season, o.season_type) == (season, season_type) and o.game_id not in present
    ]
    if missing:
        raise NeutralSiteOverrideError(
            f"neutral-site override(s) not found in the deduped {season} {season_type} "
            f"payload: {'; '.join(missing)}"
        )

    corrected: list[GameRow] = []
    for row in rows:
        override = by_id.get(row.id)
        if override is None:
            corrected.append(row)
            continue
        if (override.season, override.season_type) != (season, season_type) or (
            row.season != override.season
        ):
            raise NeutralSiteOverrideError(
                f"neutral-site override {override.describe()} matched game {row.id} in the "
                f"{season} {season_type} payload (record season {row.season})"
            )
        if (row.home_team, row.away_team) != (override.home_team, override.away_team):
            raise NeutralSiteOverrideError(
                f"neutral-site override {override.describe()} doesn't match CFBD's record: "
                f"{row.away_team} at {row.home_team}"
            )
        logger.info(
            "neutral-site override %s: neutral_site %s -> True, venue %r -> %r (%s)",
            override.describe(),
            row.neutral_site,
            row.venue,
            override.venue,
            override.source,
        )
        corrected.append(dataclasses.replace(row, neutral_site=True, venue=override.venue))
    return corrected
