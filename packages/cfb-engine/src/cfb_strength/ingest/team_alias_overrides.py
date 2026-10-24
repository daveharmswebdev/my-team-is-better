"""A committed supplement to CFBD's team aliases (issue #417).

CFBD's `/teams` payload gives "UF" to Findlay (id 2224, a D-II school our
`teams` table holds from 2021 on) and gives Florida (id 57) only
`["FLA", "Florida"]`, so the everyday name for the Gators never reached them.
The lookup stays data-driven (#411), so the fix is data on our side of
ingest: `data/raw/team_alias_overrides.json` maps a CFBD team id (a decimal
string) to the aliases to add to and remove from CFBD's own, plus one
`"$comment"` string saying why each entry exists. An entry is either

  * a list of alias strings, meaning add them (the original #417 shape), or
  * an object with an `"add"` list, a `"remove"` list, or both.

`apply_team_alias_overrides` runs inside `enrich_team_aliases`, on the
`team_rows_by_cfbd_id` join (#418). For each listed id it first drops the
removed aliases from CFBD's list, then appends each added alias that isn't
already there, all compared case-insensitively and trimmed, so CFBD's
ordering and spelling are otherwise untouched. An id the `/teams` payload
lacks is logged and dropped: enrichment only UPDATEs teams the `/games`
ingest found, and there is no CFBD record to edit.

It fails loudly, never silently:

  * `load_team_alias_overrides` raises `TeamAliasOverrideError`, naming the
    file, for any shape but the above, including an entry that adds and
    removes the same alias;
  * `apply_team_alias_overrides` raises it, naming the file and the id, when
    an entry removes an alias CFBD's record for that id doesn't carry. Such an
    entry would otherwise sit in the file doing nothing once CFBD changes.

Like the neutral-site overrides (#343), this is committed, reviewed data,
not cache, so its path is fixed to the package's `data/raw/` and doesn't
follow `CFB_DATA_DIR`.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from cfb_strength.config import PROJECT_ROOT
from cfb_strength.contracts import TeamRow

logger = logging.getLogger(__name__)

TEAM_ALIAS_OVERRIDES_PATH = PROJECT_ROOT / "data" / "raw" / "team_alias_overrides.json"

_COMMENT_KEY = "$comment"
_ENTRY_KEYS = frozenset({"add", "remove"})


class TeamAliasOverrideError(ValueError):
    """The team-alias overrides file is malformed, or an entry no longer
    matches CFBD's record for its id."""


@dataclass(frozen=True)
class AliasOverride:
    """One entry of the overrides file: aliases to add to, and remove from,
    CFBD's own for `team_id`. `source` is the file it came from, so a later
    mismatch with CFBD's data can name it."""

    team_id: int
    add: tuple[str, ...]
    remove: tuple[str, ...]
    source: Path


def _fold(alias: str) -> str:
    return alias.strip().casefold()


def _parse_id(key: str, path: Path) -> int:
    if not key.isascii() or not key.isdigit() or int(key) <= 0:
        raise TeamAliasOverrideError(
            f"{path}: key {key!r} is not a CFBD team id (a positive decimal integer string)"
        )
    return int(key)


def _parse_aliases(value: object, where: str, path: Path) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise TeamAliasOverrideError(
            f"{path}: {where} must be a list of alias strings, got {value!r}"
        )
    aliases: list[str] = []
    for alias in value:
        if not isinstance(alias, str) or not alias.strip():
            raise TeamAliasOverrideError(f"{path}: {where} holds {alias!r}, not a non-empty string")
        aliases.append(alias.strip())
    return tuple(aliases)


def _parse_entry(team_id: int, key: str, value: object, path: Path) -> AliasOverride:
    where = f"entry {key!r}"
    add: tuple[str, ...]
    remove: tuple[str, ...]
    if isinstance(value, list):
        add, remove = _parse_aliases(value, where, path), ()
    elif isinstance(value, dict):
        unknown = sorted(str(k) for k in value.keys() - _ENTRY_KEYS)
        if unknown:
            raise TeamAliasOverrideError(
                f"{path}: {where} has unknown key(s) {', '.join(unknown)}; "
                "expected 'add' and/or 'remove'"
            )
        add = _parse_aliases(value.get("add", []), f"{where} 'add'", path)
        remove = _parse_aliases(value.get("remove", []), f"{where} 'remove'", path)
    else:
        raise TeamAliasOverrideError(
            f"{path}: {where} must be a list of alias strings or an object with "
            f"'add'/'remove' lists, got {value!r}"
        )
    if not add and not remove:
        raise TeamAliasOverrideError(f"{path}: {where} is empty: nothing to add or remove")
    both = sorted({_fold(a) for a in add} & {_fold(r) for r in remove})
    if both:
        raise TeamAliasOverrideError(
            f"{path}: entry for CFBD team id {team_id} both adds and removes {', '.join(both)}"
        )
    return AliasOverride(team_id=team_id, add=add, remove=remove, source=path)


def load_team_alias_overrides(
    path: Path = TEAM_ALIAS_OVERRIDES_PATH,
) -> dict[int, AliasOverride]:
    """Read and validate the overrides file, keyed by CFBD team id."""
    try:
        document = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise TeamAliasOverrideError(f"{path}: not valid JSON ({e})") from e
    if not isinstance(document, dict):
        raise TeamAliasOverrideError(
            f"{path}: expected an object of CFBD team id -> alias override, "
            f"got {type(document).__name__}"
        )
    overrides: dict[int, AliasOverride] = {}
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
        overrides[team_id] = _parse_entry(team_id, key, value, path)
    return overrides


def merge_alias_names(cfbd: tuple[str, ...], extra: tuple[str, ...]) -> tuple[str, ...]:
    """CFBD's aliases unchanged, then each extra alias not already present
    (compared case-insensitively, trimmed)."""
    merged = list(cfbd)
    seen = {_fold(alias) for alias in cfbd}
    for alias in extra:
        name = alias.strip()
        folded = _fold(name)
        if not name or folded in seen:
            continue
        seen.add(folded)
        merged.append(name)
    return tuple(merged)


def remove_alias_names(row: TeamRow, override: AliasOverride) -> tuple[str, ...]:
    """`row`'s aliases without the override's removals. Raises if CFBD's
    record doesn't carry one of them."""
    present = {_fold(alias) for alias in row.alternate_names}
    absent = [alias for alias in override.remove if _fold(alias) not in present]
    if absent:
        raise TeamAliasOverrideError(
            f"{override.source}: entry for CFBD team id {override.team_id} removes "
            f"{', '.join(repr(a) for a in absent)}, but CFBD's /teams record for "
            f"{row.school} carries {list(row.alternate_names)!r}; update or delete the entry"
        )
    removed = {_fold(alias) for alias in override.remove}
    return tuple(alias for alias in row.alternate_names if _fold(alias) not in removed)


def apply_team_alias_overrides(
    by_id: Mapping[int, TeamRow], overrides: Mapping[int, AliasOverride]
) -> dict[int, TeamRow]:
    """Return a copy of `by_id` with each overridden id's aliases edited:
    removals first, then additions."""
    merged = dict(by_id)
    for team_id, override in overrides.items():
        row = merged.get(team_id)
        if row is None:
            logger.warning(
                "team-alias override for CFBD id %d dropped: the /teams payload has no such id",
                team_id,
            )
            continue
        kept = remove_alias_names(row, override)
        names = merge_alias_names(kept, override.add)
        if names != row.alternate_names:
            merged[team_id] = dataclasses.replace(row, alternate_names=names)
    return merged
