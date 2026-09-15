"""Cache-first client for nflverse's plain-CSV release assets.

Data credit: both files below come from the `nflverse/nflverse-data` GitHub
release assets. The `games.csv` schedule data was originally compiled and
maintained by Lee Sharpe (`nflscrapR`/`nflfastR`'s schedule file, later
folded into nflverse) before nflverse took over publishing it -- see
`README.md`'s credits section for the full citation. `teams_colors_logos.csv`
is nflverse's own team-metadata release.

Deliberately not `nfl_data_py`: that package pins `pandas==1.5.3`, which
would downgrade this workspace's `numpy` from 2.5.3 to 1.26.4 (the
`ratings/keener.py` eigenvector code depends on numpy) -- too invasive a
dependency change for issue #51's slice. These are just CSV files at stable
URLs, so plain `requests` + stdlib `csv` is enough; no new dependency.

Cache-first, mirroring `ingest/client.py`'s style: every call checks
`data/raw/nfl/{games,teams}.csv` before touching the network. Unlike the
CFBD path (one cache file per year/season-type), nflverse publishes each of
these as a single file covering its *entire* history (1999-2026) -- there is
no per-year asset -- so the whole file is cached whole and callers filter to
the seasons they want at the normalize layer.

Player stats (issue #289): the cache is a projection, not the raw file
---------------------------------------------------------------------
`players.csv` and one `stats_player_week_<year>.csv` per season (1999 on)
are also nflverse release assets, but they are cached *projected*, because
the raw weekly files are 7-8.5 MB each (about 200 MB for 1999-2025) and
carry some 150 columns this project doesn't use:

* `data/raw/nfl/stats_player_week_<year>.csv` keeps only
  `STATS_PLAYER_WEEK_CACHE_COLUMNS` (ids, week, season type, game, teams and
  the ten `contracts.PlayerStats` columns), and only rows where at least one
  of those ten is non-empty and non-zero (`player_normalize.has_any_stat`).
  About 2,100-2,500 of 17,000-19,500 rows a season, ~180-215 KB.
* `data/raw/nfl/players.csv` keeps only `PLAYERS_CACHE_COLUMNS`.

So the cache holds nothing a new stat could be read from. Adding a stat means
widening `PlayerStats` (and the tables), which widens the projection through
`STAT_FIELDS`, and then refetching every season with `--force`; a new
`players.csv` column means adding it to `PLAYERS_CACHE_COLUMNS` and the same
refetch. Never fetch nflverse's season-level `stats_player_reg/post/regpost`
files: season rows are derived from the weekly lines.
"""

from __future__ import annotations

import csv
import io
import os
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path

import requests

from cfb_strength.config import RAW_DIR
from cfb_strength.ingest.nflverse.player_normalize import STAT_FIELDS, has_any_stat

_RELEASES = "https://github.com/nflverse/nflverse-data/releases/download"
GAMES_URL = f"{_RELEASES}/schedules/games.csv"
TEAMS_URL = f"{_RELEASES}/teams/teams_colors_logos.csv"
PLAYERS_URL = f"{_RELEASES}/players/players.csv"
_TIMEOUT_SECONDS = 60

STATS_PLAYER_WEEK_CACHE_COLUMNS: tuple[str, ...] = (
    "player_id",
    "player_display_name",
    "position",
    "season",
    "week",
    "season_type",
    "game_id",
    "team",
    "opponent_team",
    *STAT_FIELDS,
)
PLAYERS_CACHE_COLUMNS: tuple[str, ...] = (
    "gsis_id",
    "display_name",
    "position",
    "birth_date",
    "pfr_id",
    "espn_id",
)


class NflverseClientError(RuntimeError):
    """Raised when an nflverse CSV asset cannot be fetched or parsed."""


def games_cache_path(raw_dir: Path = RAW_DIR) -> Path:
    return raw_dir / "nfl" / "games.csv"


def teams_cache_path(raw_dir: Path = RAW_DIR) -> Path:
    return raw_dir / "nfl" / "teams.csv"


def players_cache_path(raw_dir: Path = RAW_DIR) -> Path:
    return raw_dir / "nfl" / "players.csv"


def stats_player_week_cache_path(year: int, raw_dir: Path = RAW_DIR) -> Path:
    return raw_dir / "nfl" / f"stats_player_week_{year}.csv"


def stats_player_week_url(year: int) -> str:
    return f"{_RELEASES}/stats_player/stats_player_week_{year}.csv"


def _fetch_csv_live(url: str) -> str:
    try:
        resp = requests.get(url, timeout=_TIMEOUT_SECONDS)
    except requests.RequestException as e:
        raise NflverseClientError(f"could not reach nflverse asset at {url}: {e}") from e
    if resp.status_code != 200:
        raise NflverseClientError(
            f"nflverse asset {url} returned HTTP {resp.status_code}: {resp.text[:500]}"
        )
    return resp.text


def _parse_csv(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def _get_csv(
    url: str, path: Path, *, force: bool, raw_dir: Path
) -> tuple[list[dict[str, str]], bool]:
    if path.exists() and not force:
        return _parse_csv(path.read_text()), False

    text = _fetch_csv_live(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return _parse_csv(text), True


def get_games(*, force: bool = False, raw_dir: Path = RAW_DIR) -> tuple[list[dict[str, str]], bool]:
    """Load-or-fetch nflverse's whole-history `games.csv`.

    Returns `(rows, fetched_live)`, matching `ingest/client.py`'s
    `(data, fetched_live)` convention. Rows cover every season nflverse has
    published (1999-2026 as of this writing) -- callers filter to the
    seasons they actually want.
    """
    return _get_csv(GAMES_URL, games_cache_path(raw_dir), force=force, raw_dir=raw_dir)


def get_teams(*, force: bool = False, raw_dir: Path = RAW_DIR) -> tuple[list[dict[str, str]], bool]:
    """Load-or-fetch nflverse's `teams_colors_logos.csv` team-metadata file.

    Its `team_abbr` set is a superset of every abbreviation that appears in
    `games.csv` across nflverse's whole history (confirmed against the
    fetched file), so one lookup by `team_abbr` covers every requested
    season without year-specific team resolution.
    """
    return _get_csv(TEAMS_URL, teams_cache_path(raw_dir), force=force, raw_dir=raw_dir)


def _project(
    rows: Iterable[Mapping[str, str]],
    columns: Sequence[str],
    keep: Callable[[Mapping[str, str]], bool] | None = None,
) -> list[dict[str, str]]:
    return [{c: row[c] for c in columns} for row in rows if keep is None or keep(row)]


def project_stats_player_week(rows: Iterable[Mapping[str, str]]) -> list[dict[str, str]]:
    """The weekly stats cache projection: `STATS_PLAYER_WEEK_CACHE_COLUMNS`,
    rows with at least one non-zero stat (module docstring)."""
    return _project(rows, STATS_PLAYER_WEEK_CACHE_COLUMNS, has_any_stat)


def project_players(rows: Iterable[Mapping[str, str]]) -> list[dict[str, str]]:
    """The `players.csv` cache projection: `PLAYERS_CACHE_COLUMNS`, every row."""
    return _project(rows, PLAYERS_CACHE_COLUMNS)


def _get_projected_csv(
    url: str,
    path: Path,
    columns: Sequence[str],
    project: Callable[[Iterable[Mapping[str, str]]], list[dict[str, str]]],
    *,
    force: bool,
) -> tuple[list[dict[str, str]], bool]:
    """Cache-first like `_get_csv`, but what is cached is `project(rows)`.
    The file is written beside the destination and renamed into place, so an
    interrupted fetch never leaves a partial cache that reads as complete."""
    if path.exists() and not force:
        return _parse_csv(path.read_text()), False

    reader = csv.DictReader(io.StringIO(_fetch_csv_live(url)))
    missing = [c for c in columns if c not in (reader.fieldnames or [])]
    if missing:
        raise NflverseClientError(
            f"nflverse asset {url} has no {', '.join(missing)} column(s), which the "
            "cache projection in client.py keeps"
        )
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(columns), lineterminator="\n")
    writer.writeheader()
    writer.writerows(project(reader))
    text = out.getvalue()

    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f".{path.name}.partial")
    partial.write_text(text)
    os.replace(partial, path)
    return _parse_csv(text), True


def get_players(
    *, force: bool = False, raw_dir: Path = RAW_DIR
) -> tuple[list[dict[str, str]], bool]:
    """Load-or-fetch nflverse's projected `players.csv` (every player it
    knows, keyed by `gsis_id`). Returns `(rows, fetched_live)`."""
    return _get_projected_csv(
        PLAYERS_URL,
        players_cache_path(raw_dir),
        PLAYERS_CACHE_COLUMNS,
        project_players,
        force=force,
    )


def get_stats_player_week(
    year: int, *, force: bool = False, raw_dir: Path = RAW_DIR
) -> tuple[list[dict[str, str]], bool]:
    """Load-or-fetch one season's projected weekly player stats (REG and
    POST lines together). Returns `(rows, fetched_live)`."""
    return _get_projected_csv(
        stats_player_week_url(year),
        stats_player_week_cache_path(year, raw_dir),
        STATS_PLAYER_WEEK_CACHE_COLUMNS,
        project_stats_player_week,
        force=force,
    )
