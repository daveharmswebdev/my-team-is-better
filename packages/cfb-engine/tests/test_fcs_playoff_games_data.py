"""Issue #379: the committed FCS playoff list against the committed cache.

`data/raw/cfbd_fcs_playoff_games.json` is reviewed data. These tests check
it by structure, not by hand: every listed id is one FCS-vs-FCS record in
its season's deduped cache, every season 1998-2025 is accounted for, and
each season the list calls complete is a whole single-elimination bracket
(games = teams - 1, the right number of games per round, every winner in
exactly one next-round game, no team after its loss, rounds in date order).
A season the cache holds only part of is declared incomplete with a reason,
and its games still satisfy every check that doesn't need the missing
rounds.

The notes markers CFBD uses for some playoff games are a cross-check here
(every marked game is listed), never how ingest decides.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from cfb_strength.ingest.conference_championships import load_conference_championships
from cfb_strength.ingest.fcs_playoff_games import (
    FCS_PLAYOFF_GAMES_PATH,
    FcsPlayoffGame,
    load_fcs_playoff_games,
)
from cfb_strength.ingest.normalize import dedupe_game_records

ENGINE_DIR = Path(__file__).resolve().parents[1]
COMMITTED_RAW_DIR = ENGINE_DIR / "data" / "raw"
SEASONS = range(1998, 2026)

ROUNDS = ("first round", "second round", "quarterfinal", "semifinal", "final")
# Games per round, by bracket size (teams). A 20-team bracket gives 12 teams
# a first-round bye, a 24-team bracket 8; a 16-team bracket has no second round.
ROUND_COUNTS: dict[int, dict[str, int]] = {
    16: {"first round": 8, "quarterfinal": 4, "semifinal": 2, "final": 1},
    20: {"first round": 4, "second round": 8, "quarterfinal": 4, "semifinal": 2, "final": 1},
    24: {"first round": 8, "second round": 8, "quarterfinal": 4, "semifinal": 2, "final": 1},
}

COMPLETE_SEASONS = {2014, 2015, 2016, 2017, 2018, 2019, 2021, 2022, 2023, 2024, 2025}

# Listed games per season, measured from the committed cache. Every season
# not named here lists none (1998-2003: no FCS playoff game is in the cache).
LISTED_PER_SEASON = {
    2004: 8,
    2005: 12,
    2006: 12,
    2007: 12,
    2008: 8,
    2009: 12,
    2010: 12,
    2011: 12,
    2012: 11,
    2013: 11,
    **{season: 23 for season in COMPLETE_SEASONS},
    2020: 4,
}

PLAYOFF_MARKER = re.compile(
    r"IAA PLAYOFFS|NCAA DIVISI?ON I FOOTBALL CHAMPIONSHIP|^FCS CHAMPIONSHIP", re.IGNORECASE
)


def _bracket_teams(season: int) -> int:
    if 2010 <= season <= 2012:
        return 20
    if season >= 2013 and season != 2020:
        return 24
    return 16  # 1998-2009, and the spring-2021 bracket of the 2020 season


@dataclass(frozen=True)
class Played:
    entry: FcsPlayoffGame
    date: str
    winner: str
    loser: str


def _payloads(season: int) -> dict[str, list[dict[str, Any]]]:
    return {
        season_type: dedupe_game_records(
            json.loads((COMMITTED_RAW_DIR / f"{season}_{season_type}.json").read_text())
        )
        for season_type in ("regular", "postseason")
    }


def _document() -> dict[str, Any]:
    document: dict[str, Any] = json.loads(FCS_PLAYOFF_GAMES_PATH.read_text())
    return document


def _played(season: int) -> list[Played]:
    by_id = {record["id"]: record for records in _payloads(season).values() for record in records}
    played = []
    for entry in load_fcs_playoff_games():
        if entry.season != season:
            continue
        record = by_id[entry.game_id]
        home, away = record["homePoints"], record["awayPoints"]
        assert home is not None and away is not None and home != away, entry
        winner, loser = (
            (record["homeTeam"], record["awayTeam"])
            if home > away
            else (record["awayTeam"], record["homeTeam"])
        )
        played.append(Played(entry, record["startDate"], winner, loser))
    return played


def _by_round(played: list[Played]) -> dict[str, list[Played]]:
    return {r: [p for p in played if p.entry.round == r] for r in ROUNDS}


# ---------------------------------------------------------------------------
# every entry is one real FCS-vs-FCS record
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("season", SEASONS)
def test_every_entry_matches_one_fcs_record_in_its_season(season: int) -> None:
    payloads = _payloads(season)
    title_games = {c.game_id for c in load_conference_championships()}
    for entry in load_fcs_playoff_games():
        if entry.season != season:
            continue
        matches = [
            (season_type, record)
            for season_type, records in payloads.items()
            for record in records
            if record["id"] == entry.game_id
        ]
        assert len(matches) == 1, entry
        season_type, record = matches[0]
        assert season_type == entry.season_type, entry
        assert record["season"] == entry.season, entry
        assert (record["homeTeam"], record["awayTeam"]) == (entry.home_team, entry.away_team)
        assert (record["homeClassification"], record["awayClassification"]) == ("fcs", "fcs")
        notes = record.get("notes") or ""
        assert not re.search(r"DIVISION III? CHAMPIONSHIP|CELEBRATION|SWAC", notes, re.I), entry
        assert entry.game_id not in title_games, entry
        assert entry.source.startswith("CFBD notes"), entry


@pytest.mark.parametrize("season", SEASONS)
def test_every_notes_marked_playoff_game_is_listed(season: int) -> None:
    listed = {g.game_id for g in load_fcs_playoff_games() if g.season == season}
    for records in _payloads(season).values():
        for record in records:
            if PLAYOFF_MARKER.search(record.get("notes") or ""):
                assert record["id"] in listed, record["id"]


# ---------------------------------------------------------------------------
# per-season counts and the season block
# ---------------------------------------------------------------------------


def test_the_season_block_accounts_for_every_season_once() -> None:
    seasons = _document()["seasons"]
    assert [s["season"] for s in seasons] == list(SEASONS)
    for s in seasons:
        assert s["bracket_teams"] == _bracket_teams(s["season"]), s
        assert s["complete"] is (s["season"] in COMPLETE_SEASONS), s
        assert isinstance(s["note"], str) and s["note"].strip(), s


def test_listed_count_per_season() -> None:
    counts = Counter(g.season for g in load_fcs_playoff_games())
    assert dict(counts) == LISTED_PER_SEASON
    for season in COMPLETE_SEASONS:
        assert counts[season] == _bracket_teams(season) - 1, season
    for season in set(SEASONS) - COMPLETE_SEASONS:
        assert counts[season] < _bracket_teams(season) - 1, season


# ---------------------------------------------------------------------------
# bracket structure
# ---------------------------------------------------------------------------


def _check_partial_structure(season: int, played: list[Played]) -> None:
    """What holds for any slice of a single-elimination bracket."""
    expected = ROUND_COUNTS[_bracket_teams(season)]
    by_round = _by_round(played)
    for r in ROUNDS:
        assert len(by_round[r]) <= expected.get(r, 0), (season, r)
        teams = [t for p in by_round[r] for t in (p.winner, p.loser)]
        assert len(teams) == len(set(teams)), (season, r, "a team plays twice in one round")
    present = [r for r in ROUNDS if by_round[r]]
    for earlier, later in zip(present, present[1:], strict=False):
        assert max(p.date for p in by_round[earlier]) < min(p.date for p in by_round[later])
    for p in played:
        after = [q for q in played if q.date > p.date]
        assert all(p.loser not in (q.winner, q.loser) for q in after), (season, p.entry)
    ordered = [r for r in ROUNDS if r in expected]
    for earlier, later in zip(ordered, ordered[1:], strict=False):
        earlier_teams = {t for p in by_round[earlier] for t in (p.winner, p.loser)}
        winners = {p.winner for p in by_round[earlier]}
        for p in by_round[later]:
            for team in (p.winner, p.loser):
                if team in earlier_teams:
                    assert team in winners, (season, p.entry)


@pytest.mark.parametrize("season", sorted(COMPLETE_SEASONS))
def test_a_complete_season_is_a_whole_bracket(season: int) -> None:
    played = _played(season)
    teams = _bracket_teams(season)
    expected = ROUND_COUNTS[teams]
    by_round = _by_round(played)

    assert len(played) == teams - 1
    assert {r: len(ps) for r, ps in by_round.items() if r in expected} == expected
    assert all(not by_round[r] for r in ROUNDS if r not in expected)
    assert len({t for p in played for t in (p.winner, p.loser)}) == teams
    _check_partial_structure(season, played)

    ordered = [r for r in ROUNDS if r in expected]
    seen: set[str] = set()
    for earlier, later in zip(ordered, ordered[1:], strict=False):
        seen |= {t for p in by_round[earlier] for t in (p.winner, p.loser)}
        later_teams = [t for p in by_round[later] for t in (p.winner, p.loser)]
        for p in by_round[earlier]:
            assert later_teams.count(p.winner) == 1, (season, p.entry)
        for team in later_teams:
            # From the quarterfinals on, every team won the round before.
            # Only the second round adds teams: the first-round byes.
            winners = {p.winner for p in by_round[earlier]}
            if later != "second round":
                assert team in winners, (season, later, team)
            elif team not in winners:
                assert team not in seen, (season, team)
    (final,) = by_round["final"]
    assert all(final.winner not in (p.loser,) for p in played)


@pytest.mark.parametrize("season", sorted(set(SEASONS) - COMPLETE_SEASONS))
def test_an_incomplete_season_is_a_consistent_slice_of_its_bracket(season: int) -> None:
    _check_partial_structure(season, _played(season))
