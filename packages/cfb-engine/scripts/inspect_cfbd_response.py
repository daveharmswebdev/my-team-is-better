#!/usr/bin/env python3
"""Ad hoc inspector for a raw CFBD API response.

Standalone dev tool used to eyeball real field names/shapes (casing,
nullability, nesting) before writing normalization code in
`src/cfb_strength/ingest/normalize.py`. Not imported by any package code.

Usage (run with `uv run` so `cfb_strength` resolves):

    uv run python scripts/inspect_cfbd_response.py --games --year 2005 --season-type regular
    uv run python scripts/inspect_cfbd_response.py --games --year 2005 --season-type regular --live
    uv run python scripts/inspect_cfbd_response.py --teams --year 2005

`--games` is cache-first (reads data/raw/{year}_{season_type}.json unless
`--live` is passed, matching the same load-or-fetch behavior as the real
ingestion path). `--teams` always calls the live API (no local cache exists
for /teams) and requires CFBD_API_KEY to be set in the environment or .env.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import requests

from cfb_strength.config import CFBD_API_KEY, CFBD_BASE_URL
from cfb_strength.ingest.client import get_games


def _fetch_teams_live(year: int | None) -> list[dict[str, Any]]:
    if not CFBD_API_KEY:
        raise SystemExit("CFBD_API_KEY is not set; cannot fetch /teams live.")
    params: dict[str, Any] = {}
    if year is not None:
        params["year"] = year
    headers = {"Authorization": f"Bearer {CFBD_API_KEY}", "Accept": "application/json"}
    resp = requests.get(f"{CFBD_BASE_URL}/teams", params=params, headers=headers, timeout=30)
    resp.raise_for_status()
    data: list[dict[str, Any]] = resp.json()
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--games", action="store_true", help="Inspect a /games response")
    group.add_argument("--teams", action="store_true", help="Inspect a /teams response (always live)")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument(
        "--season-type",
        choices=["regular", "postseason"],
        default="regular",
        help="Only used with --games",
    )
    parser.add_argument(
        "--live", action="store_true", help="Force a live API call instead of the on-disk cache"
    )
    parser.add_argument("--n", type=int, default=1, help="Number of sample records to print")
    args = parser.parse_args(argv)

    if args.games:
        games, fetched_live = get_games(args.year, args.season_type, force=args.live)
        print(f"# {len(games)} games ({'live fetch' if fetched_live else 'from on-disk cache'})")
        for g in games[: args.n]:
            print(json.dumps(g, indent=2, sort_keys=True))
        if games:
            print("# field names:", sorted(games[0].keys()))
    else:
        teams = _fetch_teams_live(args.year)
        print(f"# {len(teams)} teams (live fetch)")
        for t in teams[: args.n]:
            print(json.dumps(t, indent=2, sort_keys=True))
        if teams:
            print("# field names:", sorted(teams[0].keys()))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
