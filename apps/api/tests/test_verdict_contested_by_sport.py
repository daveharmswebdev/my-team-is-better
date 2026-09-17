"""Issue #151: the persona's `contested` flag depends on the league, not just
the year.

`api.config.CONTESTED_YEARS` used to be a bare CFB set, so every NFL verdict
for 2003 or 2017 came back `narration.contested: true` and the narrator was
told the season was disputed. Covered here, through the real HTTP layer:

- every route (champion, team-case, compare) for both leagues across a
  contested CFB year (2003, 2017) and an uncontested one (2005): both the
  response flag and the `contested:` line the narrator was actually given;
- every `Sport` has an explicit entry, so a new league must state its
  contested years (possibly none);
- cache rows written before the fix: a row whose `contested` disagrees with
  the freshly computed flag is a miss and is overwritten; a row that agrees
  is served as a hit.

The expected flags are written out by hand, never read from `api.config`,
so this file is the oracle the config is checked against.

No committed fixture has NFL rows in a contested CFB year (the verdict
fixture is CFB-only, the sport fixture is 2023), so each test builds
`tests/fixtures/sport_fixture.py`'s both-leagues db in the season it needs.
Every narrator is a fake and every cache is in memory: no Claude, no Postgres.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, get_args

import pytest
from cfb_strength.db.connection import get_conn
from cfb_strength.evidence.proof import build_comparison, build_team_case
from fastapi.testclient import TestClient
from fixtures.narrator_fake import FakeNarrator
from fixtures.sport_fixture import make_sport_fixture_db

from api.config import CONTESTED_YEARS, PROMPT_VERSION
from api.deps import get_db_conn, get_narration_cache, get_narrator
from api.main import app
from api.models import ComparisonResultOut, Sport, TeamCaseOut
from api.persona.cache import CachedNarration, InMemoryNarrationCache, cache_key
from api.persona.claims import GROUNDING_VERSION
from api.persona.service import comparison_fact_block_json, team_case_fact_block_json

if TYPE_CHECKING:
    pass

# No numbers and no team names: grounded against any fact block.
NARRATION = "Solid case, no notes."
STALE_NARRATION = "Look, the polls and the math never settled this one."

# Per league, per route: the request body (minus year/sport) and the resolved
# canonical team name(s) the cache key is built from.
ROUTE_TEAMS: dict[Sport, dict[str, tuple[dict[str, str], tuple[str, ...]]]] = {
    "cfb": {
        "champion": ({}, ("Alpha State",)),
        "team-case": ({"team": "Bravo Tech"}, ("Bravo Tech",)),
        "compare": (
            {"team_a": "Alpha State", "team_b": "Bravo Tech"},
            ("Alpha State", "Bravo Tech"),
        ),
    },
    "nfl": {
        "champion": ({}, ("Delta Squad",)),
        "team-case": ({"team": "Echo Corp"}, ("Echo Corp",)),
        "compare": ({"team_a": "Delta Squad", "team_b": "Echo Corp"}, ("Delta Squad", "Echo Corp")),
    },
}
ROUTES = ["champion", "team-case", "compare"]
QUESTION_TYPES = {"champion": "champion", "team-case": "team_case", "compare": "compare"}

# (sport, year) -> contested, by hand. Only CFB has disputed seasons.
EXPECTED_CONTESTED: list[tuple[Sport, int, bool]] = [
    ("cfb", 2003, True),
    ("cfb", 2017, True),
    ("cfb", 2005, False),
    ("nfl", 2003, False),
    ("nfl", 2017, False),
    ("nfl", 2005, False),
]


def contested_seen(narrator: FakeNarrator) -> list[bool]:
    """The `contested:` value each call's user message carried (the trailing
    line `build_user_message` appends after the fact block)."""
    seen: list[bool] = []
    for call in narrator.calls:
        content = call.user_texts[0]
        flag = content[content.rindex("\n\ncontested: ") + len("\n\ncontested: ") :]
        assert flag in {"true", "false"}, f"unexpected contested line: {flag!r}"
        seen.append(flag == "true")
    return seen


@contextmanager
def _client(
    db: Path, cache: InMemoryNarrationCache, narrator: FakeNarrator
) -> Iterator[TestClient]:
    def _conn() -> Iterator[sqlite3.Connection]:
        conn = get_conn(db, read_only=True)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db_conn] = _conn
    app.dependency_overrides[get_narration_cache] = lambda: cache
    app.dependency_overrides[get_narrator] = lambda: narrator
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db_conn, None)
        app.dependency_overrides.pop(get_narration_cache, None)
        app.dependency_overrides.pop(get_narrator, None)


def _post(client: TestClient, route: str, sport: Sport, year: int) -> dict[str, Any]:
    body, _ = ROUTE_TEAMS[sport][route]
    response = client.post(f"/api/verdict/{route}", json={"year": year, "sport": sport, **body})
    assert response.status_code == 200, response.text
    narration: dict[str, Any] = response.json()["narration"]
    return narration


def _fact_block_json(db: Path, route: str, sport: Sport, year: int) -> str:
    """The fact block the route narrates for this request, built from the
    same db the way the route builds it (issue #145): the champion route
    resolves the rank-1 team first, which `ROUTE_TEAMS` already names."""
    _, teams = ROUTE_TEAMS[sport][route]
    conn = get_conn(db, read_only=True)
    try:
        if route == "compare":
            comparison = ComparisonResultOut.from_dataclass(
                build_comparison(conn, year, teams[0], teams[1], method="keener", sport=sport)
            )
            return comparison_fact_block_json(comparison)
        case = TeamCaseOut.from_dataclass(
            build_team_case(conn, year, teams[0], method="keener", sport=sport)
        )
        return team_case_fact_block_json(case)
    finally:
        conn.close()


def _key(db: Path, route: str, sport: Sport, year: int) -> str:
    _, teams = ROUTE_TEAMS[sport][route]
    return cache_key(
        question_type=QUESTION_TYPES[route],
        year=year,
        teams=teams,
        user_team=None,
        method="keener",
        sport=sport,
        prompt_version=PROMPT_VERSION,
        fact_block_json=_fact_block_json(db, route, sport, year),
        grounding_version=GROUNDING_VERSION,
    )


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize(("sport", "year", "expected"), EXPECTED_CONTESTED)
def test_contested_flag_is_per_league_in_the_response_and_the_prompt(
    tmp_path: Path, route: str, sport: Sport, year: int, expected: bool
) -> None:
    narrator = FakeNarrator()
    cache = InMemoryNarrationCache()

    with _client(make_sport_fixture_db(tmp_path, year=year), cache, narrator) as client:
        narration = _post(client, route, sport, year)

    assert narration["contested"] is expected
    assert narration["cached"] is False
    assert contested_seen(narrator) == [expected]


def test_every_league_states_its_contested_years() -> None:
    """A new `Sport` must come with its own `CONTESTED_YEARS` entry (possibly
    empty), rather than inheriting another league's disputed seasons."""
    assert set(CONTESTED_YEARS) == set(get_args(Sport))


@pytest.mark.parametrize("route", ROUTES)
def test_stale_contested_cache_row_is_a_miss_and_is_overwritten(tmp_path: Path, route: str) -> None:
    """A row cached before #151 for NFL 2003 says `contested=True`, and its
    text was narrated under that wrong flag. It must not be served: narrate
    again with the right flag and overwrite the row."""
    db = make_sport_fixture_db(tmp_path, year=2003)
    key = _key(db, route, "nfl", 2003)
    cache = InMemoryNarrationCache()
    cache.set(key, CachedNarration(text=STALE_NARRATION, contested=True))
    narrator = FakeNarrator()

    with _client(db, cache, narrator) as client:
        narration = _post(client, route, "nfl", 2003)

    assert narration == {"text": NARRATION, "contested": False, "cached": False}
    assert contested_seen(narrator) == [False]
    assert cache.get(key) == CachedNarration(text=NARRATION, contested=False)


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize(("sport", "contested"), [("nfl", False), ("cfb", True)])
def test_cache_row_with_the_right_contested_flag_is_still_a_hit(
    tmp_path: Path, route: str, sport: Sport, contested: bool
) -> None:
    db = make_sport_fixture_db(tmp_path, year=2003)
    key = _key(db, route, sport, 2003)
    cache = InMemoryNarrationCache()
    cache.set(key, CachedNarration(text=STALE_NARRATION, contested=contested))
    narrator = FakeNarrator()

    with _client(db, cache, narrator) as client:
        narration = _post(client, route, sport, 2003)

    assert narration == {"text": STALE_NARRATION, "contested": contested, "cached": True}
    assert contested_seen(narrator) == []
    assert cache.get(key) == CachedNarration(text=STALE_NARRATION, contested=contested)
