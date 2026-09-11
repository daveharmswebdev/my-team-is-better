"""Normalize raw nflverse `games.csv` / `teams_colors_logos.csv` rows into
`GameRow`/`TeamRow` contract objects.

`games.csv` columns (confirmed by fetching the live file):

    game_id, season, game_type, week, gameday, weekday, gametime, away_team,
    away_score, home_team, home_score, location, result, total, overtime,
    old_game_id, gsis, nfl_detail_id, pfr, pff, espn, ftn, away_rest,
    home_rest, away_moneyline, home_moneyline, spread_line, away_spread_odds,
    home_spread_odds, total_line, under_odds, over_odds, div_game, roof,
    surface, temp, wind, away_qb_id, home_qb_id, away_qb_name, home_qb_name,
    away_coach, home_coach, referee, stadium_id, stadium

Confirmed `game_type` values across the whole file: {"REG", "WC", "DIV",
"CON", "SB"} -- no preseason rows exist in this file. Confirmed `location`
values: {"Home", "Neutral"}.

`teams_colors_logos.csv` columns used here: `team_abbr`, `team_name`,
`team_conf` (of the full column set, only these three matter for
normalization -- see client.py's docstring for the rest, and its
attribution note for nflverse/Lee Sharpe credit).

Surrogate id minting: nflverse's natural keys are strings (team
abbreviations; a composite `game_id` like "2023_01_KC_DET"), which must
become synthetic integers that can never collide with CFBD's real ids
(up to ~401,845,330 for games, ~1,000,899 for teams) and must be
deterministic across runs so the existing `INSERT ... ON CONFLICT(id) DO
UPDATE` upsert pattern gives idempotent re-ingest for free. This is an exact,
load-bearing spec (see ingest_season.py's use of it) -- not an
implementation detail to improvise differently.
"""

from __future__ import annotations

import hashlib
import json
from typing import TypedDict

from cfb_strength.contracts import GameRow, TeamRow

_NAMESPACE_BASE = {"nfl_team": 1_000_000_000, "nfl_game": 1_500_000_000}
_NAMESPACE_SPAN = 500_000_000

_REGULAR_GAME_TYPE = "REG"
_POSTSEASON_GAME_TYPES = {"WC", "DIV", "CON", "SB"}


class TeamDesc(TypedDict):
    team_name: str
    team_conf: str


TeamLookup = dict[str, TeamDesc]


def mint_surrogate_id(namespace: str, source_id: str) -> int:
    """Deterministic surrogate integer id for an nflverse string natural key.

    Same `(namespace, source_id)` always produces the same id -- required
    for idempotent re-ingest via the `ON CONFLICT(id) DO UPDATE` upsert
    pattern already used by the CFBD path.
    """
    digest = hashlib.sha256(f"{namespace}:{source_id}".encode()).digest()
    offset = int.from_bytes(digest[:6], "big") % _NAMESPACE_SPAN
    return _NAMESPACE_BASE[namespace] + offset


def build_team_lookup(team_rows: list[dict[str, str]]) -> TeamLookup:
    """Index raw `teams_colors_logos.csv` rows by `team_abbr`."""
    lookup: TeamLookup = {}
    for row in team_rows:
        lookup[row["team_abbr"]] = {
            "team_name": row["team_name"],
            "team_conf": row["team_conf"],
        }
    return lookup


def _season_type(game_type: str) -> str:
    if game_type == _REGULAR_GAME_TYPE:
        return "regular"
    if game_type in _POSTSEASON_GAME_TYPES:
        return "postseason"
    raise ValueError(
        f"unrecognized nflverse game_type {game_type!r}; expected "
        f"{_REGULAR_GAME_TYPE!r} or one of {sorted(_POSTSEASON_GAME_TYPES)}"
    )


def _team_desc(lookup: TeamLookup, abbr: str) -> TeamDesc:
    try:
        return lookup[abbr]
    except KeyError as e:
        raise ValueError(
            f"no team-desc entry for nflverse team_abbr {abbr!r} in teams_colors_logos.csv"
        ) from e


def normalize_game(raw: dict[str, str], team_lookup: TeamLookup) -> GameRow:
    """Convert one raw nflverse `games.csv` record into a `GameRow`."""
    home_abbr, away_abbr = raw["home_team"], raw["away_team"]
    home_desc, away_desc = _team_desc(team_lookup, home_abbr), _team_desc(team_lookup, away_abbr)

    home_score, away_score = raw["home_score"], raw["away_score"]
    completed = bool(home_score) and bool(away_score)

    return GameRow(
        id=mint_surrogate_id("nfl_game", raw["game_id"]),
        season=int(raw["season"]),
        week=int(raw["week"]) if raw.get("week") else None,
        season_type=_season_type(raw["game_type"]),
        start_date=raw.get("gameday") or None,
        neutral_site=raw.get("location") == "Neutral",
        completed=completed,
        home_team_id=mint_surrogate_id("nfl_team", home_abbr),
        away_team_id=mint_surrogate_id("nfl_team", away_abbr),
        home_team=home_desc["team_name"],
        away_team=away_desc["team_name"],
        home_points=int(home_score) if home_score else None,
        away_points=int(away_score) if away_score else None,
        home_conference=home_desc["team_conf"],
        away_conference=away_desc["team_conf"],
        home_classification=None,
        away_classification=None,
        venue=raw.get("stadium") or None,
        raw_json=json.dumps(raw, sort_keys=True),
        sport="nfl",
        source_id=raw["game_id"],
    )


def team_rows_from_games(raw_games: list[dict[str, str]], team_lookup: TeamLookup) -> list[TeamRow]:
    """Derive one `TeamRow` per distinct team_abbr appearing (home or away)
    across a batch of raw nflverse game records."""
    abbrs: set[str] = set()
    for raw in raw_games:
        abbrs.add(raw["home_team"])
        abbrs.add(raw["away_team"])

    rows: list[TeamRow] = []
    for abbr in sorted(abbrs):
        desc = _team_desc(team_lookup, abbr)
        rows.append(
            TeamRow(
                id=mint_surrogate_id("nfl_team", abbr),
                school=desc["team_name"],
                classification=None,
                conference=desc["team_conf"],
                sport="nfl",
                source_id=abbr,
            )
        )
    return rows
