"""Thin CFBD `/games` client with a load-or-fetch cache.

Field names used against the live API (`year`, `seasonType` query params; the
`Game` response schema's `homeId`/`awayId`/`homeClassification`/etc.) were
confirmed against https://api.collegefootballdata.com/api-docs.json before
writing this module -- see normalize.py's docstring for the confirmed field
list.

Cache-first: every call checks `data/raw/{year}_{season_type}.json` before
touching the network. A normal ingestion run over already-cached years makes
zero live API calls.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests

from cfb_strength.config import CFBD_API_KEY, CFBD_BASE_URL, RAW_DIR

GAMES_ENDPOINT = "/games"
_TIMEOUT_SECONDS = 30


class CFBDClientError(RuntimeError):
    """Raised when the CFBD API cannot be reached or returns something unusable."""


def cache_path(year: int, season_type: str, raw_dir: Path = RAW_DIR) -> Path:
    return raw_dir / f"{year}_{season_type}.json"


def _fetch_games_live(year: int, season_type: str) -> list[dict[str, Any]]:
    if not CFBD_API_KEY:
        raise CFBDClientError(
            "CFBD_API_KEY is not set (checked environment and .env); cannot "
            f"fetch live data for {year} {season_type}, and no cache file "
            "exists for it either."
        )
    url = f"{CFBD_BASE_URL}{GAMES_ENDPOINT}"
    params: dict[str, str | int] = {"year": year, "seasonType": season_type}
    headers = {"Authorization": f"Bearer {CFBD_API_KEY}", "Accept": "application/json"}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=_TIMEOUT_SECONDS)
    except requests.RequestException as e:
        raise CFBDClientError(
            f"Could not reach CFBD API for {year} {season_type}: {e}"
        ) from e
    if resp.status_code != 200:
        raise CFBDClientError(
            f"CFBD API returned HTTP {resp.status_code} for {year} {season_type}: "
            f"{resp.text[:500]}"
        )
    try:
        data = resp.json()
    except ValueError as e:
        raise CFBDClientError(
            f"CFBD API returned non-JSON response for {year} {season_type}"
        ) from e
    if not isinstance(data, list):
        raise CFBDClientError(
            f"Unexpected CFBD /games response shape for {year} {season_type}: "
            f"expected a list, got {type(data).__name__}"
        )
    return data


def get_games(
    year: int,
    season_type: str,
    *,
    force: bool = False,
    raw_dir: Path = RAW_DIR,
) -> tuple[list[dict[str, Any]], bool]:
    """Load-or-fetch a raw `/games` response.

    Returns `(games, fetched_live)`. Reads `data/raw/{year}_{season_type}.json`
    if it exists and `force` is False. Otherwise makes a live API call and
    writes the result back to that cache path (creating `raw_dir` if needed).
    """
    path = cache_path(year, season_type, raw_dir)
    if path.exists() and not force:
        with path.open() as f:
            games: list[dict[str, Any]] = json.load(f)
        return games, False

    games = _fetch_games_live(year, season_type)
    raw_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(games, indent=2))
    return games, True
