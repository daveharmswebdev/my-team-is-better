"""Normalize nflverse's weekly player stats into the player contract rows
(issue #289, epic #288).

Pure functions, no database and no network: `ingest_players.py` loads the
season's games from the db and the projected cache files through
`client.py`, and hands them to `build_player_season`, which returns every
row to write plus the season's report.

The rules, in the order a stat line meets them:

1. Row filter (`has_any_stat`, applied when the cache is written): a row is
   kept only if at least one `PlayerStats` column is non-empty and non-zero,
   judged on the cell as nflverse publishes it (before the sign flip of
   rule 8). Filtering on attempts/carries alone would drop real lines (2024
   Josh Downs: 13 rushing yards on 0 carries), and since issue #313 widened
   the columns to 34 the filter also keeps receiving, kicking and punting
   lines -- which is why refetching with `--force` roughly quadrupled the
   cached rows a season.
2. Game: the stat `game_id` must be a `games.source_id` of the season, and
   its REG/POST must agree with that game's `season_type`. Either failing
   raises, naming the game_id and player_id.
3. Named skips, reported and never raised: a row with an empty `team`
   (measured: one, 1999 Steve Bono), and a row with no usable player
   identity -- an empty `player_id` (nflverse's team-level 'Team' lines,
   measured four in 2001/2003), or a player missing from `players.csv` with
   no name on any stat row or schedule line (measured one, 1999
   00-0005532). A `PlayerRow` needs a name, and a line with no player can't
   belong to any career.
4. Team: the stat `team` is the franchise's *current* abbreviation (LV for
   1999 Oakland), so it resolves to the game side whose `teams.csv`
   franchise `team_id` equals its own, never by abbreviation equality.
   Anything else unresolvable raises.
5. Player: the id is `mint_surrogate_id("nfl_player", gsis_id)`. A player in
   `players.csv` takes its name, position and birth date there, with
   source ids gsis, pfr and espn (when non-empty). A player missing from it
   is built from its stat row's name and position (or, for a listed QB with
   no line, the schedule's QB name) with only a gsis source id, and counted.
   A player is written only if a stored line or starter references them.
6. Season rows: per (player, season_type), the sum of the game rows --
   except `contracts.PLAYER_STAT_MAX_FIELDS` (`fg_long`, `pt_long`), which
   take the MAX of the game rows, because a "long" doesn't add up (#313).
   games = the line count; team_id = the one team, else None; a stat is None
   only if it is None on every line.
7. Starters: for each completed game and side, the schedule's listed QB if
   the side has no lines at all or the listed QB has a line for that side
   (`nflverse_schedule`); otherwise that side's player with the most
   attempts, then carries, then lowest gsis id (`derived_most_attempts`);
   if nobody on the side attempted a pass, no starter, reported.
8. Signs (#298): `SOURCE_NEGATED_FIELDS` names the columns nflverse
   publishes with the opposite sign to the one the contract stores. Only
   `sack_yards_lost` is flipped, from nflverse's negative to the positive
   an official stat line reads; net yardage that is genuinely negative
   (`rushing_yards`, `receiving_yards`, `pt_net_yards`) is stored as
   published.
"""

from __future__ import annotations

import dataclasses
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from cfb_strength.contracts import (
    PLAYER_STAT_MAX_FIELDS,
    GameStarterRow,
    PlayerGameStatRow,
    PlayerRow,
    PlayerSeasonStatRow,
    PlayerSeasonType,
    PlayerSourceIdRow,
    PlayerStats,
)
from cfb_strength.ingest.nflverse.normalize import mint_surrogate_id

STAT_FIELDS: tuple[str, ...] = tuple(f.name for f in dataclasses.fields(PlayerStats))
"""Every `PlayerStats` column, in contract order (34 since issue #313
widened them from the ten passing/rushing ones to receiving, kicking and
punting). nflverse's weekly file uses exactly these names, so widening the
contract widens the cache projection and this parse together."""

SOURCE_NEGATED_FIELDS: frozenset[str] = frozenset({"sack_yards_lost"})
"""Columns nflverse publishes with the opposite sign to the one
`contracts.PlayerStats` stores (#298): yardage a player *lost* is stored
positive, so Brady 2007 reads 21 sacks for 128 yards. The flip is `-value`,
not `abs(value)` -- measured over 1999-2025, nflverse's `sack_yards_lost` is
negative or zero on every row, so a positive one would mean the source
changed convention, and that should fail loudly downstream rather than be
silently absorbed. Every other column (including net yardage like
`rushing_yards`, genuinely negative on 4,603 rows) keeps the source's
sign."""

SEASON_ROW_SOURCE = "nflverse"
STARTER_FROM_SCHEDULE = "nflverse_schedule"
STARTER_DERIVED = "derived_most_attempts"
STARTER_SOURCES: tuple[str, ...] = (STARTER_FROM_SCHEDULE, STARTER_DERIVED)
STARTER_POSITION = "QB"

Side = Literal["home", "away"]
SIDES: tuple[Side, Side] = ("home", "away")
SkipReason = Literal["empty_team", "no_player_identity"]

_PLAYER_NAMESPACE = "nfl_player"
_STAT_SEASON_TYPES: dict[str, PlayerSeasonType] = {"REG": "regular", "POST": "postseason"}
_EMPTY_CELLS = ("", "NA")


def player_id_for(gsis_id: str) -> int:
    return mint_surrogate_id(_PLAYER_NAMESPACE, gsis_id)


# --- cells ------------------------------------------------------------------


def _is_nonzero(cell: str) -> bool:
    value = cell.strip()
    if value in _EMPTY_CELLS:
        return False
    try:
        return float(value) != 0
    except ValueError:
        # Not a number: keep the row, so `parse_stats` rejects it loudly at
        # ingest instead of the cache silently dropping it.
        return True


def has_any_stat(row: Mapping[str, str]) -> bool:
    """Rule 1's cache row filter: any `PlayerStats` column non-empty and
    non-zero. The filter runs on the *source's* cells, before
    `SOURCE_NEGATED_FIELDS` flips any sign, so a value counts whichever way
    round it is published: a sacked quarterback's `sack_yards_lost` (-7 in
    the file, 7 stored) keeps its row, as does a receiver's -3 yard
    reception."""
    return any(_is_nonzero(row.get(name, "")) for name in STAT_FIELDS)


def _parse_stat(row: Mapping[str, str], name: str) -> int | None:
    value = row[name].strip()
    if value in _EMPTY_CELLS:
        return None
    try:
        parsed = int(value)
    except ValueError as e:
        raise ValueError(
            f"stat column {name!r} holds {value!r}, not a whole number "
            f"(game_id={row.get('game_id')!r} player_id={row.get('player_id')!r})"
        ) from e
    return -parsed if name in SOURCE_NEGATED_FIELDS else parsed


def parse_stats(row: Mapping[str, str]) -> PlayerStats:
    """A stat row's `STAT_FIELDS` columns, in the stored sign convention; an
    empty cell is None, never 0. A column the row doesn't have raises
    `KeyError`, which is the point: a season nflverse publishes without one
    must fail loudly, not read as an era that didn't track the stat."""
    return PlayerStats(**{name: _parse_stat(row, name) for name in STAT_FIELDS})


def player_season_type(value: str) -> PlayerSeasonType:
    """nflverse's REG/POST, translated to the stored vocabulary."""
    try:
        return _STAT_SEASON_TYPES[value]
    except KeyError as e:
        raise ValueError(
            f"unrecognized nflverse stat season_type {value!r}; expected 'REG' or 'POST'"
        ) from e


# --- games and teams --------------------------------------------------------


@dataclass(frozen=True)
class GameInfo:
    """What the player ingest needs of one `games` row: its stored ids,
    season type and score, plus the side abbreviations and listed QBs from
    its `raw_json` (the full nflverse `games.csv` record)."""

    id: int
    source_id: str
    season_type: str
    home_abbr: str
    away_abbr: str
    home_team_id: int
    away_team_id: int
    home_points: int | None
    away_points: int | None
    home_qb_id: str
    away_qb_id: str
    home_qb_name: str
    away_qb_name: str

    @property
    def completed(self) -> bool:
        return self.home_points is not None and self.away_points is not None

    def abbr(self, side: Side) -> str:
        return self.home_abbr if side == "home" else self.away_abbr

    def team_id(self, side: Side) -> int:
        return self.home_team_id if side == "home" else self.away_team_id

    def qb_id(self, side: Side) -> str:
        return self.home_qb_id if side == "home" else self.away_qb_id

    def qb_name(self, side: Side) -> str:
        return self.home_qb_name if side == "home" else self.away_qb_name


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)


def game_info(row: Mapping[str, Any]) -> GameInfo:
    """Build a `GameInfo` from a `games` row (or `GameRow` fields): `id`,
    `source_id`, `season_type`, `home_team_id`, `away_team_id`,
    `home_points`, `away_points`, `raw_json`."""
    raw = json.loads(str(row["raw_json"]))
    return GameInfo(
        id=int(row["id"]),
        source_id=str(row["source_id"]),
        season_type=str(row["season_type"]),
        home_abbr=str(raw["home_team"]),
        away_abbr=str(raw["away_team"]),
        home_team_id=int(row["home_team_id"]),
        away_team_id=int(row["away_team_id"]),
        home_points=_optional_int(row["home_points"]),
        away_points=_optional_int(row["away_points"]),
        home_qb_id=str(raw.get("home_qb_id") or ""),
        away_qb_id=str(raw.get("away_qb_id") or ""),
        home_qb_name=str(raw.get("home_qb_name") or ""),
        away_qb_name=str(raw.get("away_qb_name") or ""),
    )


def build_franchise_lookup(team_rows: Iterable[Mapping[str, str]]) -> dict[str, str]:
    """`team_abbr` -> franchise `team_id` from nflverse's `teams.csv`, where
    every abbreviation a franchise has used shares one id (OAK = LV = 2520)."""
    lookup: dict[str, str] = {}
    for row in team_rows:
        if not row["team_id"]:
            raise ValueError(f"teams.csv row {row['team_abbr']!r} has no franchise team_id")
        lookup[row["team_abbr"]] = row["team_id"]
    return lookup


def resolve_side(team: str, game: GameInfo, franchise: Mapping[str, str]) -> Side:
    """The side of `game` a stat line's `team` played for, by franchise id."""
    franchise_id = franchise.get(team)
    if franchise_id is None:
        raise ValueError(
            f"stat team {team!r} has no franchise id in teams.csv (game {game.source_id})"
        )
    sides = [side for side in SIDES if franchise.get(game.abbr(side)) == franchise_id]
    if len(sides) != 1:
        raise ValueError(
            f"stat team {team!r} (franchise {franchise_id}) matches {len(sides)} sides of "
            f"game {game.source_id} ({game.away_abbr} at {game.home_abbr})"
        )
    return sides[0]


# --- players ----------------------------------------------------------------


@dataclass(frozen=True)
class RosterEntry:
    """One projected `players.csv` row."""

    gsis_id: str
    display_name: str
    position: str | None
    birth_date: str | None
    pfr_id: str | None
    espn_id: str | None


def build_roster(player_rows: Iterable[Mapping[str, str]]) -> dict[str, RosterEntry]:
    roster: dict[str, RosterEntry] = {}
    for row in player_rows:
        gsis_id = row["gsis_id"]
        if not gsis_id:
            continue
        if gsis_id in roster:
            raise ValueError(f"players.csv lists gsis_id {gsis_id!r} more than once")
        roster[gsis_id] = RosterEntry(
            gsis_id=gsis_id,
            display_name=row["display_name"],
            position=row["position"] or None,
            birth_date=row["birth_date"] or None,
            pfr_id=row["pfr_id"] or None,
            espn_id=row["espn_id"] or None,
        )
    return roster


# --- the season build -------------------------------------------------------


@dataclass(frozen=True)
class SkippedStatRow:
    reason: SkipReason
    game_id: str
    player_id: str
    player_name: str


@dataclass(frozen=True)
class DerivedStarter:
    """A side whose listed QB had no line while teammates did."""

    game_id: str
    side: Side
    listed_player_id: str
    listed_player_name: str
    starter_player_id: str
    starter_player_name: str
    attempts: int


@dataclass(frozen=True)
class PlayerSeasonReport:
    season: int
    stat_lines: int
    season_rows: int
    players_written: int
    players_without_roster_entry: tuple[str, ...]
    starters_by_source: dict[str, int]
    skipped: tuple[SkippedStatRow, ...]
    games_without_stat_lines: tuple[str, ...]
    sides_without_starter: tuple[tuple[str, Side], ...]
    derived_starters: tuple[DerivedStarter, ...]


@dataclass(frozen=True)
class SeasonBuild:
    players: tuple[PlayerRow, ...]
    source_ids: tuple[PlayerSourceIdRow, ...]
    game_stats: tuple[PlayerGameStatRow, ...]
    season_stats: tuple[PlayerSeasonStatRow, ...]
    starters: tuple[GameStarterRow, ...]
    report: PlayerSeasonReport


@dataclass(frozen=True)
class _Line:
    gsis_id: str
    game: GameInfo
    side: Side
    season_type: PlayerSeasonType
    stats: PlayerStats


@dataclass(frozen=True)
class _Identity:
    display_name: str
    position: str | None
    birth_date: str | None
    entry: RosterEntry | None


class _Identities:
    """Where a player's name comes from: `players.csv`, else the first named
    stat row, else the schedule's QB name."""

    def __init__(
        self,
        roster: Mapping[str, RosterEntry],
        stat_rows: Sequence[Mapping[str, str]],
        games: Sequence[GameInfo],
    ) -> None:
        self._roster = roster
        self._stat_names: dict[str, str] = {}
        self._stat_positions: dict[str, str] = {}
        for row in stat_rows:
            gsis_id = row["player_id"]
            if row["player_display_name"]:
                self._stat_names.setdefault(gsis_id, row["player_display_name"])
            if row["position"]:
                self._stat_positions.setdefault(gsis_id, row["position"])
        self._qb_names: dict[str, str] = {}
        for game in games:
            for side in SIDES:
                if game.qb_id(side) and game.qb_name(side):
                    self._qb_names.setdefault(game.qb_id(side), game.qb_name(side))

    def get(self, gsis_id: str) -> _Identity | None:
        entry = self._roster.get(gsis_id)
        name = (
            (entry.display_name if entry else "")
            or self._stat_names.get(gsis_id, "")
            or self._qb_names.get(gsis_id, "")
        )
        if not name:
            return None
        if entry is not None:
            return _Identity(name, entry.position, entry.birth_date, entry)
        return _Identity(name, self._stat_positions.get(gsis_id), None, None)


def _where(row: Mapping[str, str]) -> str:
    return f"stat line game_id={row['game_id']!r} player_id={row['player_id']!r}"


def _aggregate_stats(lines: Sequence[_Line]) -> PlayerStats:
    """Rule 6's season aggregate: the sum of the game rows, except for
    `contracts.PLAYER_STAT_MAX_FIELDS` (`fg_long`, `pt_long`), which take
    the MAX -- summing a kicker's 16 game-longs would report a season long
    of several hundred yards. A stat None on every line stays None."""
    totals: dict[str, int | None] = {}
    for name in STAT_FIELDS:
        present = [v for v in (getattr(line.stats, name) for line in lines) if v is not None]
        if not present:
            totals[name] = None
        elif name in PLAYER_STAT_MAX_FIELDS:
            totals[name] = max(present)
        else:
            totals[name] = sum(present)
    return PlayerStats(**totals)


def build_player_season(
    season: int,
    stat_rows: Iterable[Mapping[str, str]],
    games: Sequence[GameInfo],
    franchise: Mapping[str, str],
    roster: Mapping[str, RosterEntry],
) -> SeasonBuild:
    """Every player row one season writes, from its projected stat rows and
    all of its `games` rows. Raises on anything unresolvable except the
    named skips (module docstring)."""
    rows = list(stat_rows)
    games = sorted(games, key=lambda g: g.source_id)
    games_by_source = {g.source_id: g for g in games}
    identities = _Identities(roster, rows, games)

    skipped: list[SkippedStatRow] = []
    lines: list[_Line] = []
    seen: set[tuple[str, int]] = set()
    for row in rows:
        game = games_by_source.get(row["game_id"])
        if game is None:
            raise ValueError(
                f"{_where(row)}: no nfl games row has that source_id in season {season}; "
                "ingest the season's games first"
            )
        try:
            season_type = player_season_type(row["season_type"])
        except ValueError as e:
            raise ValueError(f"{_where(row)}: {e}") from e
        if season_type != game.season_type:
            raise ValueError(
                f"{_where(row)} is {row['season_type']} but that game is {game.season_type}"
            )
        gsis_id = row["player_id"]
        if not gsis_id or identities.get(gsis_id) is None:
            skipped.append(
                SkippedStatRow(
                    "no_player_identity", game.source_id, gsis_id, row["player_display_name"]
                )
            )
            continue
        if not row["team"]:
            skipped.append(
                SkippedStatRow("empty_team", game.source_id, gsis_id, row["player_display_name"])
            )
            continue
        try:
            side = resolve_side(row["team"], game, franchise)
        except ValueError as e:
            raise ValueError(f"{_where(row)}: {e}") from e
        if (gsis_id, game.id) in seen:
            raise ValueError(f"{_where(row)} appears more than once")
        seen.add((gsis_id, game.id))
        lines.append(_Line(gsis_id, game, side, season_type, parse_stats(row)))

    lines.sort(key=lambda line: (line.game.source_id, line.gsis_id))

    # Starters (rule 7).
    by_side: dict[tuple[int, Side], list[_Line]] = defaultdict(list)
    for line in lines:
        by_side[(line.game.id, line.side)].append(line)
    starters: list[tuple[GameInfo, Side, str, str]] = []
    derived: list[DerivedStarter] = []
    sides_without_starter: list[tuple[str, Side]] = []
    for game in games:
        if not game.completed:
            continue
        for side in SIDES:
            listed = game.qb_id(side)
            side_lines = by_side.get((game.id, side), [])
            if listed and (not side_lines or any(ln.gsis_id == listed for ln in side_lines)):
                starters.append((game, side, listed, STARTER_FROM_SCHEDULE))
                continue
            passers = [ln for ln in side_lines if (ln.stats.attempts or 0) > 0]
            if not passers:
                sides_without_starter.append((game.source_id, side))
                continue
            best = min(
                passers,
                key=lambda ln: (-(ln.stats.attempts or 0), -(ln.stats.carries or 0), ln.gsis_id),
            )
            starters.append((game, side, best.gsis_id, STARTER_DERIVED))
            best_identity = identities.get(best.gsis_id)
            assert best_identity is not None  # a stored line always has an identity
            derived.append(
                DerivedStarter(
                    game_id=game.source_id,
                    side=side,
                    listed_player_id=listed,
                    listed_player_name=game.qb_name(side),
                    starter_player_id=best.gsis_id,
                    starter_player_name=best_identity.display_name,
                    attempts=best.stats.attempts or 0,
                )
            )

    # Players (rules 2 and 3): only those a stored line or starter references.
    referenced = sorted({line.gsis_id for line in lines} | {s[2] for s in starters})
    minted: dict[int, str] = {}
    players: list[PlayerRow] = []
    source_ids: list[PlayerSourceIdRow] = []
    without_roster: list[str] = []
    for gsis_id in referenced:
        player_id = player_id_for(gsis_id)
        if minted.setdefault(player_id, gsis_id) != gsis_id:
            raise ValueError(
                f"surrogate id collision: player id {player_id} minted for both gsis "
                f"{minted[player_id]!r} and {gsis_id!r}"
            )
        identity = identities.get(gsis_id)
        if identity is None:
            raise ValueError(
                f"listed starter gsis_id={gsis_id!r} has no name in players.csv, "
                f"the season's stat rows or games.csv"
            )
        players.append(
            PlayerRow(
                id=player_id,
                display_name=identity.display_name,
                position=identity.position,
                birth_date=identity.birth_date,
                sport="nfl",
            )
        )
        source_ids.append(PlayerSourceIdRow(player_id, "gsis", gsis_id))
        if identity.entry is None:
            without_roster.append(gsis_id)
        else:
            if identity.entry.pfr_id:
                source_ids.append(PlayerSourceIdRow(player_id, "pfr", identity.entry.pfr_id))
            if identity.entry.espn_id:
                source_ids.append(PlayerSourceIdRow(player_id, "espn", identity.entry.espn_id))
    players.sort(key=lambda p: p.id)

    game_stats = tuple(
        PlayerGameStatRow(
            player_id=player_id_for(line.gsis_id),
            game_id=line.game.id,
            team_id=line.game.team_id(line.side),
            sport="nfl",
            stats=line.stats,
        )
        for line in lines
    )

    # Season rows (rule 6).
    groups: dict[tuple[str, PlayerSeasonType], list[_Line]] = defaultdict(list)
    for line in lines:
        groups[(line.gsis_id, line.season_type)].append(line)
    season_stats: list[PlayerSeasonStatRow] = []
    for (gsis_id, season_type), group in sorted(groups.items()):
        teams = {line.game.team_id(line.side) for line in group}
        season_stats.append(
            PlayerSeasonStatRow(
                player_id=player_id_for(gsis_id),
                season=season,
                season_type=season_type,
                team_id=next(iter(teams)) if len(teams) == 1 else None,
                games=len(group),
                source=SEASON_ROW_SOURCE,
                sport="nfl",
                stats=_aggregate_stats(group),
            )
        )

    starter_rows = tuple(
        GameStarterRow(
            game_id=game.id,
            team_id=game.team_id(side),
            position=STARTER_POSITION,
            player_id=player_id_for(gsis_id),
            source=source,
            sport="nfl",
        )
        for game, side, gsis_id, source in starters
    )

    games_with_lines = {line.game.id for line in lines}
    report = PlayerSeasonReport(
        season=season,
        stat_lines=len(game_stats),
        season_rows=len(season_stats),
        players_written=len(players),
        players_without_roster_entry=tuple(without_roster),
        starters_by_source={
            source: sum(1 for s in starters if s[3] == source) for source in STARTER_SOURCES
        },
        skipped=tuple(sorted(skipped, key=lambda s: (s.game_id, s.player_id, s.reason))),
        games_without_stat_lines=tuple(g.source_id for g in games if g.id not in games_with_lines),
        sides_without_starter=tuple(sides_without_starter),
        derived_starters=tuple(derived),
    )
    return SeasonBuild(
        players=tuple(players),
        source_ids=tuple(source_ids),
        game_stats=game_stats,
        season_stats=tuple(season_stats),
        starters=starter_rows,
        report=report,
    )
