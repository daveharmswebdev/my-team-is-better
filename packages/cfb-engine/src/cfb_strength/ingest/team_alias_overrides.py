"""A committed supplement to CFBD's team aliases (issue #417).

CFBD's `/teams` payload gives "UF" only to Findlay (id 2224, a D-II school no
golden season rates) and gives Florida (id 57) `["FLA", "Florida"]`, so the
everyday name for the Gators never reached them. The lookup stays
data-driven (#411), so the fix is data on our side of ingest:
`data/raw/team_alias_overrides.json` maps a CFBD team id (a decimal string)
to a list of extra aliases, plus one `"$comment"` string saying why each
entry exists.

`apply_team_alias_overrides` runs inside `enrich_team_aliases`, on the
`team_rows_by_cfbd_id` join (#418). Each listed id gets its extra aliases
appended after CFBD's own, skipping any that match an alias already there
case-insensitively, so CFBD's ordering and spelling are untouched. An id the
`/teams` payload lacks is logged and dropped: enrichment only UPDATEs teams
the `/games` ingest found, and there is no CFBD record to merge onto.

`load_team_alias_overrides` raises `TeamAliasOverrideError`, naming the
file, for anything but that exact shape. A malformed file never reads as
"no overrides".

Like the neutral-site overrides (#343), this is committed, reviewed data,
not cache, so its path is fixed to the package's `data/raw/` and doesn't
follow `CFB_DATA_DIR`.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from collections.abc import Mapping
from pathlib import Path

from cfb_strength.config import PROJECT_ROOT
from cfb_strength.contracts import TeamRow

logger = logging.getLogger(__name__)

TEAM_ALIAS_OVERRIDES_PATH = PROJECT_ROOT / "data" / "raw" / "team_alias_overrides.json"

_COMMENT_KEY = "$comment"


class TeamAliasOverrideError(ValueError):
    """The team-alias overrides file is not valid JSON or not the expected shape."""


def _parse_id(key: str, path: Path) -> int:
    if not key.isascii() or not key.isdigit() or int(key) <= 0:
        raise TeamAliasOverrideError(
            f"{path}: key {key!r} is not a CFBD team id (a positive decimal integer string)"
        )
    return int(key)


def _parse_aliases(value: object, key: str, path: Path) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise TeamAliasOverrideError(
            f"{path}: entry {key!r} must be a list of alias strings, got {value!r}"
        )
    if not value:
        raise TeamAliasOverrideError(f"{path}: entry {key!r} is an empty list")
    aliases: list[str] = []
    for alias in value:
        if not isinstance(alias, str) or not alias.strip():
            raise TeamAliasOverrideError(
                f"{path}: entry {key!r} holds {alias!r}, not a non-empty string"
            )
        aliases.append(alias.strip())
    return tuple(aliases)


def load_team_alias_overrides(
    path: Path = TEAM_ALIAS_OVERRIDES_PATH,
) -> dict[int, tuple[str, ...]]:
    """Read and validate the overrides file: CFBD team id -> extra aliases."""
    try:
        document = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise TeamAliasOverrideError(f"{path}: not valid JSON ({e})") from e
    if not isinstance(document, dict):
        raise TeamAliasOverrideError(
            f"{path}: expected an object of CFBD team id -> alias list, "
            f"got {type(document).__name__}"
        )
    overrides: dict[int, tuple[str, ...]] = {}
    for key, value in document.items():
        if key.startswith("$"):
            if key != _COMMENT_KEY:
                raise TeamAliasOverrideError(
                    f"{path}: unknown key {key!r}; the only non-id key is {_COMMENT_KEY!r}"
                )
            if not isinstance(value, str):
                raise TeamAliasOverrideError(f"{path}: {_COMMENT_KEY!r} must be a string")
            continue
        team_id = _parse_id(key, path)
        if team_id in overrides:
            raise TeamAliasOverrideError(f"{path}: duplicate entry for CFBD team id {team_id}")
        overrides[team_id] = _parse_aliases(value, key, path)
    return overrides


def merge_alias_names(cfbd: tuple[str, ...], extra: tuple[str, ...]) -> tuple[str, ...]:
    """CFBD's aliases unchanged, then each extra alias not already present
    (compared case-insensitively, trimmed)."""
    merged = list(cfbd)
    seen = {alias.strip().casefold() for alias in cfbd}
    for alias in extra:
        name = alias.strip()
        folded = name.casefold()
        if not name or folded in seen:
            continue
        seen.add(folded)
        merged.append(name)
    return tuple(merged)


def apply_team_alias_overrides(
    by_id: Mapping[int, TeamRow], overrides: Mapping[int, tuple[str, ...]]
) -> dict[int, TeamRow]:
    """Return a copy of `by_id` with each overridden id's aliases merged in."""
    merged = dict(by_id)
    for team_id, extra in overrides.items():
        row = merged.get(team_id)
        if row is None:
            logger.warning(
                "team-alias override for CFBD id %d dropped: the /teams payload has no such id",
                team_id,
            )
            continue
        names = merge_alias_names(row.alternate_names, extra)
        if names != row.alternate_names:
            merged[team_id] = dataclasses.replace(row, alternate_names=names)
    return merged
