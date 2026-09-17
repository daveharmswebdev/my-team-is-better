"""Failing-first tests for `/api/teams`' optional `?year=` scoping
(GitHub issue #78, epic #76).

Before this issue `/api/teams` took only `sport`, so the team list was
identical for every year: `?sport=nfl` offered *both* halves of every NFL
relocation (a 2010 question was offered "Las Vegas Raiders", which has no
2010 data), and `?sport=cfb` offered the entire 788-name FBS/FCS/D2/D3
opponent universe the games ingest has ever seen, most of it unrated in any
given season.

Two fixtures are used deliberately:

* `client` (the committed, real-engine-computed `cfb_verdict_fixture.sqlite3`)
  for the CFB half -- 451 real team names, of which only 117 to 130 have a
  real keener rating in any one of its seven seasons (2001: 117, 2003: 117,
  2004: 119, 2005: 119, 2013: 125, 2017: 130, 2019: 130). That ratio *is* the
  bug, so the test asserts against real data rather than a hand-built
  stand-in.
* `team_catalog_client` (`tests/fixtures/team_catalog_fixture.py`) for the
  NFL relocation half, which needs two seasons either side of a franchise
  move -- see that module's docstring for why neither existing fixture has
  them.

The last two tests in this file pin issue #78's one real trap: the shared
`api.repositories.teams.list_all_team_names` helper (in `api.deps` until
#209) has a *second* caller, the persona
grounding check, which needs the full unscoped team-name universe. If
year-scoping had been pushed down into that shared helper, the grounding
check would stop recognizing legitimately-mentioned unrated opponents as
team names at all.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from cfb_strength.db.connection import get_conn
from fastapi.testclient import TestClient
from fixtures.narrator_fake import FakeNarrator
from fixtures.team_catalog_fixture import NEW_YEAR, OLD_YEAR, RELOCATED_PAIRS, UNINGESTED_YEAR

if TYPE_CHECKING:
    pass

FIXTURE_DB = Path(__file__).parent / "fixtures" / "cfb_verdict_fixture.sqlite3"


def _pre_issue_78_team_names(db_path: Path, sport: str) -> list[str]:
    """Exactly the query `/api/teams` ran before this issue, order included
    -- the byte-for-byte baseline a client that never sends `year` must keep
    seeing."""
    conn = get_conn(db_path, read_only=True)
    try:
        rows = conn.execute(
            "SELECT DISTINCT school FROM teams WHERE sport = ?", (sport,)
        ).fetchall()
        return [str(row["school"]) for row in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# no `year` -> today's exact behavior, unchanged
# ---------------------------------------------------------------------------


def test_teams_without_year_returns_full_sport_list(client: TestClient) -> None:
    """A client that never sends `year` sees no change whatsoever -- same
    names, same order as the pre-#78 query (mirrors how `sport` was
    introduced in issue #59)."""
    response = client.get("/api/teams")

    assert response.status_code == 200
    assert response.json()["teams"] == _pre_issue_78_team_names(FIXTURE_DB, "cfb")


def test_teams_without_year_returns_full_sport_list_for_nfl(
    team_catalog_client: TestClient, tmp_path: Path
) -> None:
    """The unscoped NFL list still offers both halves of every relocation --
    that's the pre-existing behavior, and it is exactly what `?year=` (not
    the default) is for."""
    teams = team_catalog_client.get("/api/teams", params={"sport": "nfl"}).json()["teams"]

    assert teams == _pre_issue_78_team_names(tmp_path / "team_catalog.sqlite3", "nfl")
    for old_name, new_name in RELOCATED_PAIRS:
        assert old_name in teams
        assert new_name in teams


# ---------------------------------------------------------------------------
# `year` -> scoped to teams with a ratings row for that year/sport/method
# ---------------------------------------------------------------------------


def test_teams_with_year_excludes_relocated_franchise(
    team_catalog_client: TestClient,
) -> None:
    old_season = team_catalog_client.get(
        "/api/teams", params={"sport": "nfl", "year": OLD_YEAR}
    ).json()["teams"]
    new_season = team_catalog_client.get(
        "/api/teams", params={"sport": "nfl", "year": NEW_YEAR}
    ).json()["teams"]

    assert "San Diego Chargers" in old_season
    assert "Los Angeles Chargers" not in old_season
    assert "Las Vegas Raiders" not in old_season

    # the mirror image
    assert "Los Angeles Chargers" in new_season
    assert "San Diego Chargers" not in new_season
    assert "Oakland Raiders" not in new_season

    # every franchise appears as exactly one of its two names per season
    for old_name, new_name in RELOCATED_PAIRS:
        assert [old_name in old_season, new_name in old_season] == [True, False]
        assert [old_name in new_season, new_name in new_season] == [False, True]

    # a franchise that never moved is offered in both seasons
    assert "New England Patriots" in old_season
    assert "New England Patriots" in new_season


def test_teams_with_year_scopes_cfb_to_rated_teams(client: TestClient) -> None:
    """Real data: 451 CFB names in the db, only 119 of them rated in 2005."""
    unscoped = client.get("/api/teams", params={"sport": "cfb"}).json()["teams"]
    scoped = client.get("/api/teams", params={"sport": "cfb", "year": 2005}).json()["teams"]

    assert len(unscoped) == 451
    assert len(scoped) == 119
    assert "Texas" in scoped
    assert "USC" in scoped
    # a real D2 opponent the games ingest has seen but which has no rating
    # in any season -- the whole reason this issue exists
    assert "Abilene Christian" in unscoped
    assert "Abilene Christian" not in scoped


def test_teams_with_year_tracks_the_year_asked_for(client: TestClient) -> None:
    """UTSA joined FBS between the fixture's seasons: rated in 2013, not in
    2001. The scoping must follow the year actually asked for, not merely
    "is this team rated in some season"."""
    teams_2001 = client.get("/api/teams", params={"year": 2001}).json()["teams"]
    teams_2013 = client.get("/api/teams", params={"year": 2013}).json()["teams"]

    assert "UTSA" not in teams_2001
    assert "UTSA" in teams_2013


def test_unknown_year_returns_empty_not_error(
    client: TestClient, team_catalog_client: TestClient
) -> None:
    """An un-ingested year is an empty list with HTTP 200 -- `/api/teams` is
    a picker-population read, not a verdict lookup, so there is nothing to
    4xx about."""
    for response in (
        client.get("/api/teams", params={"year": 1997}),
        team_catalog_client.get("/api/teams", params={"sport": "nfl", "year": UNINGESTED_YEAR}),
    ):
        assert response.status_code == 200
        assert response.json()["teams"] == []
        assert response.json()["team_details"] == []


def test_teams_year_respects_method(team_catalog_client: TestClient) -> None:
    """`method` keeps `/api/years`' existing convention (default "keener"):
    an explicit "keener" matches the default, and a method with no rows
    scopes to nothing rather than falling back to every team."""
    default = team_catalog_client.get("/api/teams", params={"year": OLD_YEAR}).json()["teams"]
    explicit = team_catalog_client.get(
        "/api/teams", params={"year": OLD_YEAR, "method": "keener"}
    ).json()["teams"]
    other = team_catalog_client.get(
        "/api/teams", params={"year": OLD_YEAR, "method": "elo"}
    ).json()["teams"]

    assert default == explicit
    assert default != []
    assert other == []


def test_teams_year_stays_within_its_sport(team_catalog_client: TestClient) -> None:
    """Year scoping joins through `ratings`, which has its own `sport`
    column -- an NFL team rated in 2010 must not leak into the CFB list for
    2010."""
    cfb = team_catalog_client.get("/api/teams", params={"sport": "cfb", "year": OLD_YEAR}).json()
    nfl = team_catalog_client.get("/api/teams", params={"sport": "nfl", "year": OLD_YEAR}).json()

    assert "Texas" in cfb["teams"]
    assert "Oakland Raiders" not in cfb["teams"]
    assert "Oakland Raiders" in nfl["teams"]
    assert "Texas" not in nfl["teams"]


# ---------------------------------------------------------------------------
# THE TRAP: the narration layer's team universe must stay unscoped
# ---------------------------------------------------------------------------


def test_grounding_team_universe_is_still_unscoped(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Behavioral half of the trap: "Abilene Christian" is a real team in
    the db that has no rating in *any* season, so it is in the team catalog
    the claim validator is handed (issue #291; the grounding check's
    known-team-name universe before it) but not in a 2005 Texas fact block.
    Mentioning it must still be caught and trigger the retry.

    If `/api/teams`' new year scoping had been pushed down into the shared
    catalog query, this name would no longer be a known team at all, the
    mention would sail through as an arbitrary capitalized phrase, and there
    would be exactly one Claude call.
    """
    from api.deps import get_narration_cache, get_narrator
    from api.main import app
    from api.persona.cache import InMemoryNarrationCache

    narrator = FakeNarrator(
        [
            "Abilene Christian never showed up on that schedule.",
            "Nobody in the country could hang with them.",
        ]
    )
    monkeypatch.setitem(app.dependency_overrides, get_narrator, lambda: narrator)
    monkeypatch.setitem(
        app.dependency_overrides, get_narration_cache, lambda: InMemoryNarrationCache()
    )

    response = client.post("/api/verdict/team-case", json={"year": 2005, "team": "Texas"})

    assert response.status_code == 200
    assert len(narrator.calls) == 2, "the claim validator did not flag the unrated-team mention"
    feedback = narrator.calls[1].retry_feedback
    assert feedback is not None
    assert "Abilene Christian" in feedback
    assert response.json()["narration"]["text"] == "Nobody in the country could hang with them."


def test_grounding_is_handed_the_whole_unscoped_team_universe(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Structural half of the trap, exercised through the real caller
    (`api.persona.service.narrate_team_case` via the route) rather than by
    re-calling the helper with default args: whatever the route did to
    `/api/teams`, the catalog handed to the narration layer is still every
    CFB team in the db (issue #291: the full records, as `catalog`)."""
    from api.persona.narrate import NarrationResult

    captured: dict[str, Any] = {}

    def _spy_narrate(**kwargs: Any) -> NarrationResult:
        captured.update(kwargs)
        return NarrationResult(text="Solid case, no notes.", is_fallback=False)

    monkeypatch.setattr("api.persona.service.narrate", _spy_narrate)

    response = client.post("/api/verdict/team-case", json={"year": 2005, "team": "Texas"})

    assert response.status_code == 200
    names = [record.name for record in captured["catalog"]]
    assert sorted(names) == sorted(_pre_issue_78_team_names(FIXTURE_DB, "cfb"))
    assert len(names) == 451


def test_list_all_team_names_signature_stays_year_free() -> None:
    """The shared helper keeps its pre-#78 behavior for its grounding
    caller: same call, same full-universe result."""
    from api.repositories.teams import list_all_team_names

    conn: sqlite3.Connection = get_conn(FIXTURE_DB, read_only=True)
    try:
        names = list_all_team_names(conn)
        assert names == list_all_team_names(conn, sport="cfb")
    finally:
        conn.close()

    assert names == _pre_issue_78_team_names(FIXTURE_DB, "cfb")
    assert "Abilene Christian" in names
