"""Unit coverage for `cfb_strength.ingest.nflverse.normalize`: real nflverse
CSV rows -> `GameRow`/`TeamRow` contract objects.

Fixtures: `tests/fixtures/raw_nfl_games_sample.csv` (7 real records extracted
once from the committed `data/raw/nfl/games.csv` cache -- never re-derived
synthetically):

  1. `2023_04_ATL_JAX` -- an ordinary REG-season game, but at a neutral
     site (Wembley Stadium, London) -- exercises `neutral_site` on a
     non-postseason game.
  2. `2023_19_CLE_HOU` (WC), `2023_20_HOU_BAL` (DIV), `2023_21_KC_BAL` (CON),
     `2023_22_SF_KC` (SB) -- one game from each 2023-season postseason round.
     The Super Bowl row is also neutral-site (Allegiant Stadium, a
     predetermined venue rather than either participant's home).
  3. `2024_01_BAL_KC`, `2025_01_DAL_PHI` -- one ordinary regular-season game
     from each of the other two in-scope seasons.

`tests/fixtures/raw_nfl_teams_sample.csv` is the full (36-row)
`teams_colors_logos.csv` cache -- small enough to commit whole rather than
trim, and it's exactly the file `build_team_lookup` is meant to index.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from cfb_strength.ingest.nflverse.normalize import (
    TeamLookup,
    build_team_lookup,
    mint_surrogate_id,
    normalize_game,
    team_rows_from_games,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
GAMES_SAMPLE = FIXTURES_DIR / "raw_nfl_games_sample.csv"
TEAMS_SAMPLE = FIXTURES_DIR / "raw_nfl_teams_sample.csv"


def _load_games() -> list[dict[str, str]]:
    with GAMES_SAMPLE.open(newline="") as f:
        return list(csv.DictReader(f))


def _load_team_lookup() -> TeamLookup:
    with TEAMS_SAMPLE.open(newline="") as f:
        team_rows = list(csv.DictReader(f))
    return build_team_lookup(team_rows)


def _by_id(games: list[dict[str, str]], game_id: str) -> dict[str, str]:
    return next(g for g in games if g["game_id"] == game_id)


def test_fixture_has_the_seven_expected_real_games() -> None:
    games = _load_games()
    assert len(games) == 7
    ids = {g["game_id"] for g in games}
    assert ids == {
        "2023_04_ATL_JAX",
        "2023_19_CLE_HOU",
        "2023_20_HOU_BAL",
        "2023_21_KC_BAL",
        "2023_22_SF_KC",
        "2024_01_BAL_KC",
        "2025_01_DAL_PHI",
    }


def test_mint_surrogate_id_is_deterministic_and_namespaced() -> None:
    id_a = mint_surrogate_id("nfl_team", "KC")
    id_b = mint_surrogate_id("nfl_team", "KC")
    assert id_a == id_b
    assert 1_000_000_000 <= id_a < 1_500_000_000

    game_id_a = mint_surrogate_id("nfl_game", "2023_01_KC_DET")
    game_id_b = mint_surrogate_id("nfl_game", "2023_01_KC_DET")
    assert game_id_a == game_id_b
    assert 1_500_000_000 <= game_id_a < 2_000_000_000

    # Different namespaces for the same string never collide by construction
    # (disjoint base ranges), and different source ids essentially never
    # collide within one namespace at this data volume.
    assert mint_surrogate_id("nfl_team", "KC") != mint_surrogate_id("nfl_game", "KC")


def test_normalize_game_ordinary_regular_season_neutral_site() -> None:
    games = _load_games()
    lookup = _load_team_lookup()
    raw = _by_id(games, "2023_04_ATL_JAX")

    row = normalize_game(raw, lookup)

    assert row.id == mint_surrogate_id("nfl_game", "2023_04_ATL_JAX")
    assert row.season == 2023
    assert row.week == 4
    assert row.season_type == "regular"
    assert row.start_date == "2023-10-01"
    assert row.neutral_site is True
    assert row.completed is True
    assert row.home_team == "Jacksonville Jaguars"
    assert row.away_team == "Atlanta Falcons"
    assert row.home_team_id == mint_surrogate_id("nfl_team", "JAX")
    assert row.away_team_id == mint_surrogate_id("nfl_team", "ATL")
    assert row.home_points == 23
    assert row.away_points == 7
    assert row.home_conference == "AFC"
    assert row.away_conference == "NFC"
    assert row.home_classification is None
    assert row.away_classification is None
    assert row.venue == "Wembley Stadium"
    assert row.sport == "nfl"
    assert row.source_id == "2023_04_ATL_JAX"
    # raw_json round-trips the full original record (sorted-key JSON dump).
    assert json.loads(row.raw_json)["game_id"] == "2023_04_ATL_JAX"


@pytest.mark.parametrize(
    "game_id,expected_season_type",
    [
        ("2023_19_CLE_HOU", "postseason"),  # WC
        ("2023_20_HOU_BAL", "postseason"),  # DIV
        ("2023_21_KC_BAL", "postseason"),  # CON
        ("2023_22_SF_KC", "postseason"),  # SB
        ("2024_01_BAL_KC", "regular"),
        ("2025_01_DAL_PHI", "regular"),
    ],
)
def test_normalize_game_maps_game_type_to_season_type(
    game_id: str, expected_season_type: str
) -> None:
    games = _load_games()
    lookup = _load_team_lookup()
    raw = _by_id(games, game_id)

    row = normalize_game(raw, lookup)

    assert row.season_type == expected_season_type


def test_normalize_game_super_bowl_is_neutral_site_with_correct_scores() -> None:
    games = _load_games()
    lookup = _load_team_lookup()
    raw = _by_id(games, "2023_22_SF_KC")

    row = normalize_game(raw, lookup)

    assert row.neutral_site is True
    assert row.home_team == "Kansas City Chiefs"
    assert row.away_team == "San Francisco 49ers"
    assert row.home_points == 25
    assert row.away_points == 22
    assert row.venue == "Allegiant Stadium"


def test_normalize_game_raises_on_unrecognized_game_type() -> None:
    games = _load_games()
    lookup = _load_team_lookup()
    raw = dict(_by_id(games, "2024_01_BAL_KC"))
    raw["game_type"] = "PRE"

    with pytest.raises(ValueError, match="game_type"):
        normalize_game(raw, lookup)


def test_team_rows_from_games_derives_distinct_teams_across_batch() -> None:
    games = _load_games()
    lookup = _load_team_lookup()

    rows = team_rows_from_games(games, lookup)

    abbrs = {r.source_id for r in rows}
    assert abbrs == {"ATL", "JAX", "CLE", "HOU", "BAL", "KC", "SF", "PHI", "DAL"}
    for r in rows:
        assert r.sport == "nfl"
        assert r.classification is None
        assert r.id == mint_surrogate_id("nfl_team", r.source_id or "")

    kc = next(r for r in rows if r.source_id == "KC")
    assert kc.school == "Kansas City Chiefs"
    assert kc.conference == "AFC"
