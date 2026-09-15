"""Tests for the franchise-relocation lineage table.

The table is a hand-maintained constant, so the thing worth testing is not
that it round-trips but that its *premise* holds: that the two abbreviations
in each pair are strictly non-overlapping in the underlying data. That
premise is what makes "key the Elo state by the lineage root, but emit the
id that actually played the target season" unambiguous. It is checked here
against the committed nflverse cache (`data/raw/nfl/games.csv`) rather than
against a live download, so a future edit that introduced an overlapping
pair would fail in CI rather than silently double-count a franchise.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from cfb_strength.ratings.franchise_lineage import FRANCHISE_LINEAGE

_GAMES_CSV = Path(__file__).resolve().parents[3] / "data" / "raw" / "nfl" / "games.csv"


def _seasons_by_abbreviation() -> dict[str, set[int]]:
    seasons: dict[str, set[int]] = {}
    with _GAMES_CSV.open(newline="") as handle:
        for row in csv.DictReader(handle):
            season = int(row["season"])
            for key in ("home_team", "away_team"):
                seasons.setdefault(row[key], set()).add(season)
    return seasons


def test_games_cache_is_present_for_this_assertion() -> None:
    assert _GAMES_CSV.is_file(), f"missing committed nflverse cache: {_GAMES_CSV}"


def test_nfl_lineage_pairs_are_strictly_non_overlapping() -> None:
    """The load-bearing premise: at most one member of a lineage can appear
    in any single season, so "the id that played the target season" is
    always unique."""
    seasons = _seasons_by_abbreviation()
    for predecessor, successor in FRANCHISE_LINEAGE["nfl"].items():
        assert predecessor in seasons, f"unknown abbreviation {predecessor!r}"
        assert successor in seasons, f"unknown abbreviation {successor!r}"
        assert not seasons[predecessor] & seasons[successor], (
            f"{predecessor} and {successor} share season(s) "
            f"{sorted(seasons[predecessor] & seasons[successor])}"
        )
        # And the direction is predecessor-then-successor, not the reverse.
        assert max(seasons[predecessor]) < min(seasons[successor])


@pytest.mark.parametrize(
    ("predecessor", "successor"),
    [("STL", "LA"), ("SD", "LAC"), ("OAK", "LV")],
)
def test_the_three_known_relocations_are_mapped(predecessor: str, successor: str) -> None:
    assert FRANCHISE_LINEAGE["nfl"][predecessor] == successor


def test_nfl_lineage_has_no_chains_or_cycles() -> None:
    """Every value must be a terminal id (not itself a key), which is what
    keeps the map a single hop today. The Elo walk resolves chains anyway,
    but a chain appearing here should be a deliberate edit."""
    lineage = FRANCHISE_LINEAGE["nfl"]
    for successor in lineage.values():
        assert successor not in lineage


def test_cfb_lineage_is_empty() -> None:
    """CFB teams do not relocate the way pro franchises do, and CFB `teams`
    rows have `source_id IS NULL` anyway -- there is nothing to key on."""
    assert FRANCHISE_LINEAGE["cfb"] == {}


def test_only_the_two_supported_sports_are_present() -> None:
    assert sorted(FRANCHISE_LINEAGE) == ["cfb", "nfl"]
