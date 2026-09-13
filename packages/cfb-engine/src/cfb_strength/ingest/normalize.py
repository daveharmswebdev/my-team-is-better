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


def is_unreported_result(raw: dict[str, Any]) -> bool:
    """True when CFBD marks a game completed but never reported its score (issue #128).

    Such a record is `completed`, `0-0`, and has empty or missing
    `homeLineScores` and `awayLineScores`. It is not a scoreless tie. NCAA
    football has had no ties since overtime arrived in 1996, and every
    reader downstream would otherwise rate and list it as one.

    The rule, and the cached-data evidence for each clause. Checked against
    every record in `data/raw/*_{regular,postseason}.json` for 1998-2025,
    after `dedupe_game_records`:

      * `0-0`. There are 31 completed `0-0` records, all regular season:
        6 in 2022, 8 in 2023, 12 in 2024 and 5 in 2025. Every one is an
        FCS/II/III (or unclassified) game, and none involves an FBS team.
      * No line scores. All 31 have empty line scores on both sides. No
        completed `0-0` record has line scores, so a `0-0` that did carry
        them would be a reported result and is left alone.
      * Line scores alone are NOT the signal. About 2,500 completed games
        with real scores have no line scores. 168 of those are real shutouts
        (Lyon 0 - Texas Lutheran 49, `401674665`), and they keep their
        scores.
      * `0-0` specifically, not any equal score. Only two completed records
        have an equal nonzero score, and both are real ties that stay ties.
        `401675587`, Florida Memorial 28 - Clark Atlanta 28 (2024-09-14),
        was suspended at halftime for weather and recorded 28-28, and it has
        line scores. `401777266`, Rowan 17 - Case Western Reserve 17
        (2025-09-06), ended by mutual agreement after lightning delays and
        the NCAA counts it as a tie. It has NO line scores, so an equal
        score with no line scores is not enough on its own.
      * `completed`. A `0-0` game that isn't completed is simply unplayed,
        which `completed` already says.

    No classification or sport exception applies. The clauses above are
    the whole rule.
    """
    return (
        bool(raw.get("completed"))
        and raw.get("homePoints") == 0
        and raw.get("awayPoints") == 0
        and not raw.get("homeLineScores")
        and not raw.get("awayLineScores")
    )


def normalize_game(raw: dict[str, Any], *, season: int, season_type: str) -> GameRow:
    """Convert one raw CFBD `/games` record into a `GameRow`.

    `season`/`season_type` are passed in from the caller (the year/season-type
    the batch was fetched for) and used as a fallback if the raw record is
    somehow missing them, but the raw record's own values are preferred when
    present.

    An unreported result (see `is_unreported_result`) gets `None` for both
    scores. `completed` stays exactly as CFBD reports it, and `raw_json`
    still holds the original `0-0` record. Every reader skips a completed
    game with null scores, so ratings, W-L-T records and evidence receipts
    all drop it together.
    """
    unreported = is_unreported_result(raw)
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
        home_points=None if unreported else raw.get("homePoints"),
        away_points=None if unreported else raw.get("awayPoints"),
        home_conference=raw.get("homeConference"),
        away_conference=raw.get("awayConference"),
        home_classification=raw.get("homeClassification"),
        away_classification=raw.get("awayClassification"),
        venue=raw.get("venue"),
        raw_json=json.dumps(raw, sort_keys=True),
    )


_DuplicateKey = tuple[object, str, object, object, object, object]


def _duplicate_key(raw: dict[str, Any]) -> _DuplicateKey | None:
    """What makes two raw records the same real game (issue #125).

    Keyed on team *names*, not ids: the one duplicate pair that matters for
    #91 (FAU 49 - Edward Waters 15, 2004-11-27) reports Edward Waters as
    `1000899` on one copy and `2206` on the other, so an id-keyed match would
    miss it. The *date* part of `startDate` only, because 16 of the 17 cached
    pairs disagree on kickoff time (the low-id 2004 copies carry a
    midnight-Eastern placeholder, `T04:00`/`T05:00Z`). Both scores are in the
    key, so the same two teams meeting twice with different results never
    match. A record without a usable `startDate` is never treated as a
    duplicate of anything (none exist in the 1998-2025 cache).
    """
    start = raw.get("startDate")
    if not isinstance(start, str) or len(start) < 10:
        return None
    return (
        raw.get("season"),
        start[:10],
        raw.get("homeTeam"),
        raw.get("awayTeam"),
        raw.get("homePoints"),
        raw.get("awayPoints"),
    )


def _survivor_preference(raw: dict[str, Any]) -> tuple[int, int, int]:
    """Sort key for which copy of a duplicated game is kept; highest wins.

    The rule, and the cached-data evidence for each tier. Checked against all
    17 duplicate groups in `data/raw/*_{regular,postseason}.json` for
    1998-2025, all of them in regular-season payloads: 15 in 2004, 1 in 2008,
    1 in 2025.

      1. Line scores on both sides. All 15 2004 groups pair a low-id
         `63826`-`63841` record that has empty `homeLineScores` and
         `awayLineScores`, no venue, and a placeholder kickoff time with an
         ESPN-id record (`2425...`-`2433...`) that has quarter-by-quarter line
         scores, a real kickoff time and, for 8 of the 15, the venue. In
         2025, `401833370` has line scores and `401806686` has `null` for
         both. This tier decides 16 of the 17 groups.
      2. CFBD's own pregame Elo. In 2008, `282430099` and `400361387` are
         identical (same line scores, venue, attendance and kickoff) except
         that only `282430099` carries `homePregameElo`/`awayPregameElo`.
         That means CFBD's own Elo pipeline treats it as the canonical copy.
         (In 2004 the placeholder copy sometimes has Elo and the ESPN copy
         does not, which is why this ranks *below* line scores.)
      3. Lowest game id. A final tiebreak that makes the choice total and
         independent of payload order; no cached group reaches it. It is
         not the primary rule, because in 2025 the better record has the
         *higher* id.

    Caveat, not a reason to mix fields across copies: in 2004 the
    surviving ESPN copy sets `neutralSite: true` on 9 of the 15 games where
    the dropped copy says `false`. Some of those look right (Florida A&M -
    Tennessee State at the Georgia Dome), and some look wrong (Texas State
    hosting FAU at its own Bobcat Stadium). The surviving record is written
    as CFBD reports it.
    """
    has_line_scores = bool(raw.get("homeLineScores")) and bool(raw.get("awayLineScores"))
    has_cfbd_elo = raw.get("homePregameElo") is not None or raw.get("awayPregameElo") is not None
    return (int(has_line_scores), int(has_cfbd_elo), -int(raw["id"]))


def dedupe_game_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse raw CFBD `/games` records that describe the same real game.

    CFBD's `/games` payload lists some real games twice under two different
    game ids. `games` is keyed by id, so without this each copy would be
    ingested as a separate completed game and counted twice by every rating
    method, W-L tally and evidence receipt. See `_duplicate_key` for what
    counts as the same game and `_survivor_preference` for which copy is kept
    and why.

    This must run before `team_rows_from_game`, so a team id that appears
    only on a dropped copy (Edward Waters `1000899`) never gets a `teams`
    row. Output preserves the payload position of each game's first
    occurrence, and the survivor does not depend on payload order.
    """
    kept: list[dict[str, Any]] = []
    slot_by_key: dict[_DuplicateKey, int] = {}
    for raw in records:
        key = _duplicate_key(raw)
        if key is None:
            kept.append(raw)
            continue
        slot = slot_by_key.get(key)
        if slot is None:
            slot_by_key[key] = len(kept)
            kept.append(raw)
        elif _survivor_preference(raw) > _survivor_preference(kept[slot]):
            kept[slot] = raw
    return kept


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
