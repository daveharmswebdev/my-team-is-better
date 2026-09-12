"""Normalize raw CFBD `/games` and `/teams` JSON records into
`GameRow`/`TeamRow` contract objects.

Field names below are taken verbatim from the CFBD OpenAPI spec's `Game`
schema (confirmed live against https://api.collegefootballdata.com/api-docs.json
on 2026-09-09, and cross-checked against the cached responses in data/raw/):

    id, season, week, seasonType, startDate, startTimeTBD, completed,
    neutralSite, conferenceGame, attendance, venueId, venue,
    homeId, homeTeam, homeConference, homeClassification, homePoints,
    homeLineScores, homePostgameWinProbability, homePregameElo, homePostgameElo,
    awayId, awayTeam, awayConference, awayClassification, awayPoints,
    awayLineScores, awayPostgameWinProbability, awayPregameElo, awayPostgameElo,
    excitementIndex, highlights, notes, playoff

`homeClassification`/`awayClassification` are one of the CFBD
`DivisionClassification` enum values: "fbs", "fcs", "ii", "ii/iii", "iii".

The `/teams` half (added for issue #77 / epic #76) uses these fields of the
`Team` response schema, confirmed against a real live call on 2026-09-12 (the
full record also carries color/alternateColor/logos/twitter/location/division,
none of which this project needs):

    id, school, mascot, abbreviation, alternateNames, classification,
    conference

`mascot` is null for 998 of the 1933 records the year-independent call returns,
but only one of those (Cal State Northridge) is a school our `/games` ingest
actually stored -- the rest are teams we never see. `alternateNames` is a list
of strings holding both abbreviations and alternate spellings (Texas ->
["TEX", "Texas"], NC State -> ["North Carolina St.", "NCSU", "NC State"]), and
`abbreviation` is a separate scalar that is usually *also* present inside it,
hence the dedupe in `_alias_names`.

NOTE for the coordinator: `GameRow` carries `home_classification` /
`away_classification`, but `db/schema.sql`'s `games` table has no columns for
them -- only `team_season.classification` does. That's intentional here: this
module still populates those two `GameRow` fields (so nothing about the raw
response is dropped from the in-memory contract object), but `ingest_season.py`
only persists them into `team_season`, not into the `games` table, since the
table simply has no column to hold them. Flagging this in case it's not what
was intended -- see RETURN for the full note.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from cfb_strength.contracts import GameRow, TeamRow


def normalize_game(raw: dict[str, Any], *, season: int, season_type: str) -> GameRow:
    """Convert one raw CFBD `/games` record into a `GameRow`.

    `season`/`season_type` are passed in from the caller (the year/season-type
    the batch was fetched for) and used as a fallback if the raw record is
    somehow missing them, but the raw record's own values are preferred when
    present.
    """
    return GameRow(
        id=raw["id"],
        season=raw.get("season", season),
        week=raw.get("week"),
        season_type=raw.get("seasonType", season_type),
        start_date=raw.get("startDate"),
        neutral_site=bool(raw.get("neutralSite", False)),
        completed=bool(raw.get("completed", False)),
        home_team_id=raw["homeId"],
        away_team_id=raw["awayId"],
        home_team=raw["homeTeam"],
        away_team=raw["awayTeam"],
        home_points=raw.get("homePoints"),
        away_points=raw.get("awayPoints"),
        home_conference=raw.get("homeConference"),
        away_conference=raw.get("awayConference"),
        home_classification=raw.get("homeClassification"),
        away_classification=raw.get("awayClassification"),
        venue=raw.get("venue"),
        raw_json=json.dumps(raw, sort_keys=True),
    )


def team_rows_from_game(raw: dict[str, Any]) -> list[TeamRow]:
    """Derive `TeamRow`s for the home and away side of one raw game record.

    CFBD's cached `/games` payloads carry per-game classification/conference
    for each side, which is enough to build `teams` and `team_season` without
    a separate `/teams` API call (and therefore without spending any live API
    calls on a normal, fully-cached ingestion run).
    """
    rows: list[TeamRow] = []
    home_id = raw.get("homeId")
    if home_id is not None:
        rows.append(
            TeamRow(
                id=home_id,
                school=raw.get("homeTeam") or "",
                classification=raw.get("homeClassification"),
                conference=raw.get("homeConference"),
            )
        )
    away_id = raw.get("awayId")
    if away_id is not None:
        rows.append(
            TeamRow(
                id=away_id,
                school=raw.get("awayTeam") or "",
                classification=raw.get("awayClassification"),
                conference=raw.get("awayConference"),
            )
        )
    return rows


def _alias_names(raw: dict[str, Any]) -> tuple[str, ...]:
    """CFBD's `alternateNames` plus its `abbreviation` scalar, deduped.

    Order-preserving (`alternateNames` first, then `abbreviation` if it isn't
    already in there) so a later alias search gets CFBD's own ordering, and
    deduped so it can't rank the same string twice -- `abbreviation` usually
    repeats an entry of `alternateNames` ("TEX", "NCSU"), and a few records
    repeat themselves outright (USC's `alternateNames` is `["USC", "USC"]`).
    """
    names: list[str] = []
    seen: set[str] = set()
    alternate = raw.get("alternateNames") or []
    for candidate in [*alternate, raw.get("abbreviation")]:
        if not isinstance(candidate, str):
            continue
        name = candidate.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return tuple(names)


def team_row_from_cfbd_team(raw: dict[str, Any]) -> TeamRow:
    """Convert one raw CFBD `/teams` record into a `TeamRow`.

    `school` is copied through verbatim and is the join key onto the
    `/games`-derived rows already in the `teams` table -- it matches
    byte-for-byte, accents included ("San José State"), so no fuzzy matching
    is needed or wanted here. It is also the canonical identity string the
    rest of the project keys on, so enrichment never rewrites it; `mascot` and
    `alternate_names` are display/search metadata layered on top.
    """
    mascot = raw.get("mascot")
    if isinstance(mascot, str):
        mascot = mascot.strip() or None
    return TeamRow(
        id=raw["id"],
        school=raw["school"],
        classification=raw.get("classification"),
        conference=raw.get("conference"),
        mascot=mascot,
        alternate_names=_alias_names(raw),
    )


def _alias_richness(row: TeamRow) -> tuple[int, int]:
    """Sort key for picking between duplicate records of the same school:
    having a mascot dominates, then having more aliases."""
    return (1 if row.mascot else 0, len(row.alternate_names))


def team_rows_from_cfbd_teams(records: Iterable[dict[str, Any]]) -> dict[str, TeamRow]:
    """Collapse a raw `/teams` payload into one `TeamRow` per `school`.

    42 of the schools our `/games` ingest stored have MORE THAN ONE record in
    the `/teams` payload under the same `school` string, and the duplicate is
    usually a stub with `mascot: null` and no aliases -- sometimes listed
    *first* (e.g. Albany State: `(None, None)` then `("Golden Rams", "ABSU")`).
    Taking `records[0]`, or building a naive `{school: record}` dict, would
    therefore silently drop the mascot for roughly half of them. This prefers
    the record that actually has a mascot, so the result does not depend on
    payload order.
    """
    best: dict[str, TeamRow] = {}
    for raw in records:
        school = raw.get("school")
        if not isinstance(school, str) or not school:
            continue
        row = team_row_from_cfbd_team(raw)
        incumbent = best.get(school)
        if incumbent is None or _alias_richness(row) > _alias_richness(incumbent):
            best[school] = row
    return best
