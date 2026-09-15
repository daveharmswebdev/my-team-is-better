"""Thin CFBD `/games` and `/teams` client with a load-or-fetch cache.

Field names used against the live API (`year`, `seasonType` query params; the
`Game` response schema's `homeId`/`awayId`/`homeClassification`/etc.) were
confirmed against https://api.collegefootballdata.com/api-docs.json before
writing this module -- see normalize.py's docstring for the confirmed field
list.

Also serves the `/teams` endpoint (issue #77), whose response carries the
mascot/alias metadata the `/games` payload has no field for.

Cache-first: every `/games` call checks `data/raw/{year}_{season_type}.json`,
and the single `/teams` call checks `data/raw/teams.json`, before touching the
network. A normal ingestion run over already-cached years makes zero live API
calls.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests

from cfb_strength.config import CFBD_API_KEY, CFBD_BASE_URL, RAW_DIR

GAMES_ENDPOINT = "/games"
TEAMS_ENDPOINT = "/teams"
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
        raise CFBDClientError(f"Could not reach CFBD API for {year} {season_type}: {e}") from e
    if resp.status_code != 200:
        raise CFBDClientError(
            f"CFBD API returned HTTP {resp.status_code} for {year} {season_type}: {resp.text[:500]}"
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


def teams_cache_path(raw_dir: Path = RAW_DIR) -> Path:
    """One year-independent cache file for the whole project.

    Deliberately NOT `teams_{year}.json`. Verified against the live API on
    2026-09-12: `/teams?year=...` returns only the teams CFBD considers active
    that season (244 for 1998, 258 for 2010, 687 for 2016), and the union
    across six sampled years still covered only 704 of the 788 CFB teams our
    `/games` ingest has stored -- while a single call with no `year` param
    returns 1933 records and covers all of them with zero misses. So this is
    one file and one lifetime API call, not 28 of them.
    """
    return raw_dir / "teams.json"


def _fetch_teams_live() -> list[dict[str, Any]]:
    if not CFBD_API_KEY:
        raise CFBDClientError(
            "CFBD_API_KEY is not set (checked environment and .env); cannot "
            "fetch live team/alias data, and no cache file exists for it "
            "either."
        )
    url = f"{CFBD_BASE_URL}{TEAMS_ENDPOINT}"
    headers = {"Authorization": f"Bearer {CFBD_API_KEY}", "Accept": "application/json"}
    try:
        resp = requests.get(url, params={}, headers=headers, timeout=_TIMEOUT_SECONDS)
    except requests.RequestException as e:
        raise CFBDClientError(f"Could not reach CFBD API for {TEAMS_ENDPOINT}: {e}") from e
    if resp.status_code != 200:
        raise CFBDClientError(
            f"CFBD API returned HTTP {resp.status_code} for {TEAMS_ENDPOINT}: {resp.text[:500]}"
        )
    try:
        data = resp.json()
    except ValueError as e:
        raise CFBDClientError(f"CFBD API returned non-JSON response for {TEAMS_ENDPOINT}") from e
    if not isinstance(data, list):
        raise CFBDClientError(
            f"Unexpected CFBD {TEAMS_ENDPOINT} response shape: expected a list, "
            f"got {type(data).__name__}"
        )
    return data


def get_teams(
    *,
    force: bool = False,
    raw_dir: Path = RAW_DIR,
) -> tuple[list[dict[str, Any]], bool]:
    """Load-or-fetch the raw `/teams` response.

    Same contract as `get_games`: returns `(teams, fetched_live)`, reads
    `data/raw/teams.json` if it exists and `force` is False, otherwise makes a
    live API call and writes the result back to that cache path (creating
    `raw_dir` if needed). No `year` argument on purpose -- see
    `teams_cache_path`.
    """
    path = teams_cache_path(raw_dir)
    if path.exists() and not force:
        with path.open() as f:
            teams: list[dict[str, Any]] = json.load(f)
        return teams, False

    teams = _fetch_teams_live()
    raw_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(teams, indent=2))
    return teams, True
