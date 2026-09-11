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
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

import requests

from cfb_strength.config import RAW_DIR

GAMES_URL = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"
TEAMS_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/teams/teams_colors_logos.csv"
)
_TIMEOUT_SECONDS = 60


class NflverseClientError(RuntimeError):
    """Raised when an nflverse CSV asset cannot be fetched or parsed."""


def games_cache_path(raw_dir: Path = RAW_DIR) -> Path:
    return raw_dir / "nfl" / "games.csv"


def teams_cache_path(raw_dir: Path = RAW_DIR) -> Path:
    return raw_dir / "nfl" / "teams.csv"


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
