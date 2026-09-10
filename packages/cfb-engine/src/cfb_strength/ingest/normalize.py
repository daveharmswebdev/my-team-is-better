"""Normalize raw CFBD `/games` JSON records into `GameRow`/`TeamRow` contract
objects.

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
