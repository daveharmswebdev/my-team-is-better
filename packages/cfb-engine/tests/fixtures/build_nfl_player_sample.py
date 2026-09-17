"""Regenerate `tests/fixtures/raw_nfl_player_sample/nfl/` from the committed
projected cache (issue #313).

    cd packages/cfb-engine
    uv run python tests/fixtures/build_nfl_player_sample.py

`--out-dir DIR` writes the cut somewhere else instead, which is how
`tests/test_ingest_nflverse_players_integration.py` checks that the
committed cut is exactly what these rules produce.

Why a script and not a hand cut: the cut is a projection of the cache, so
every time the cache changes shape the cut has to be made again the same
way. It was hand-made for issue #289 and reproduced here byte-for-byte from
the pre-#313 cache before being applied to the widened one; the next
widening (#317's defensive columns) can just rerun it.

The rules, which are also what
`test_ingest_nflverse_players_integration.py`'s docstring describes:

* every line of the seasons' sampled teams -- 1999 LA (St. Louis) and IND,
  2004 IND and NE, 2013 DEN and NO, 2022 KC and TB. A starter is decided
  per side from that side's own lines, so keeping every line of a team
  reproduces that team's full-season starters and totals exactly;
* plus every line of a few named games: 1999_09_PHI_CAR (Steve Bono's
  empty-team row), 1999_15_NO_BAL (an unknown player with no name),
  2001_11_GB_DET (a team-level row with no player id) and the four 2022
  games nflverse lists the wrong starter for;
* `players.csv` rows for every player those lines reference, plus every QB
  the schedule lists in the four fixture seasons (a listed starter needs a
  name even when he has no stat line).

Not part of the pytest suite: the filename doesn't match `test_*.py`, so it
is never collected, and nothing under `src/` imports it.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from cfb_strength.config import RAW_DIR
from cfb_strength.ingest.nflverse.client import games_cache_path, stats_player_week_cache_path

FIXTURES_DIR = Path(__file__).resolve().parent
SAMPLE_DIR = FIXTURES_DIR / "raw_nfl_player_sample" / "nfl"

SAMPLE_TEAMS: dict[int, frozenset[str]] = {
    1999: frozenset({"LA", "IND"}),
    2001: frozenset(),
    2004: frozenset({"IND", "NE"}),
    2013: frozenset({"DEN", "NO"}),
    2022: frozenset({"KC", "TB"}),
}
SAMPLE_GAMES: dict[int, frozenset[str]] = {
    1999: frozenset({"1999_09_PHI_CAR", "1999_15_NO_BAL"}),
    2001: frozenset({"2001_11_GB_DET"}),
    2004: frozenset(),
    2013: frozenset(),
    2022: frozenset({"2022_08_LV_NO", "2022_11_CAR_BAL", "2022_11_PHI_IND", "2022_15_PIT_CAR"}),
}
# The seasons whose games the fixture db holds, so whose listed QBs need a
# players.csv row even without a stat line.
QB_SEASONS = (1999, 2004, 2013, 2022)


def _read(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        return rows, list(reader.fieldnames or [])


def _write(path: Path, fieldnames: Sequence[str], rows: Iterable[Mapping[str, str]]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(fieldnames), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def build(out_dir: Path, raw_dir: Path = RAW_DIR) -> Path:
    """Write the whole cut into `out_dir` and return it."""
    out_dir.mkdir(parents=True, exist_ok=True)
    referenced: set[str] = set()
    for season in sorted(SAMPLE_TEAMS):
        rows, fieldnames = _read(stats_player_week_cache_path(season, raw_dir))
        keep = [
            row
            for row in rows
            if row["team"] in SAMPLE_TEAMS[season] or row["game_id"] in SAMPLE_GAMES[season]
        ]
        if not keep:
            raise RuntimeError(f"{season}: the cut is empty; did the cache columns change?")
        referenced |= {row["player_id"] for row in keep if row["player_id"]}
        _write(out_dir / f"stats_player_week_{season}.csv", fieldnames, keep)
        print(f"{season}: {len(keep)} of {len(rows)} cached rows")

    games, _ = _read(games_cache_path(raw_dir))
    for game in games:
        if int(game["season"]) in QB_SEASONS:
            referenced |= {game["home_qb_id"], game["away_qb_id"]} - {""}

    players, player_fields = _read(raw_dir / "nfl" / "players.csv")
    keep_players = [p for p in players if p["gsis_id"] in referenced]
    _write(out_dir / "players.csv", player_fields, keep_players)
    print(f"players: {len(keep_players)} of {len(players)} cached rows")
    return out_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Recut tests/fixtures/raw_nfl_player_sample/ from the committed cache."
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=SAMPLE_DIR,
        help="where to write the cut (default: tests/fixtures/raw_nfl_player_sample/nfl).",
    )
    args = parser.parse_args(argv)
    build(args.out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
