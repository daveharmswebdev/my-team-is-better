"""Failing-first tests for `/api/teams`' additive `team_details` payload
(GitHub issue #78, epic #76).

`teams.mascot` / `teams.alternate_names` landed in the engine's schema for
this epic; surfacing them lets a later `apps/web` combobox display
"Texas - Longhorns" (and match on "TEX") while still submitting the
canonical "Texas".

The shape is deliberately **additive**: `TeamsOut.teams` stays
`list[str]`, byte-identical to before, and `team_details` is a parallel
array. `apps/web`'s consumer lands in a separate PR and a separate
production deploy, and its `TeamsOut` type currently declares
`teams: string[]` and renders `value={name}` straight from it -- changing
`teams`' element type would render `[object Object]` in the live picker for
the whole window between the two merges.

`name` is the canonical, submitted value and must stay byte-identical to
`teams.school`: the verdict lookup, the persona grounding check, the golden
dataset, and every cached narration key are keyed on that exact string.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from cfb_strength.db.connection import get_conn
from fastapi.testclient import TestClient
from fixtures.team_catalog_fixture import OLD_YEAR

FIXTURE_DB = Path(__file__).parent / "fixtures" / "cfb_verdict_fixture.sqlite3"


def _details_by_name(body: dict[str, object]) -> dict[str, dict[str, object]]:
    details = body["team_details"]
    assert isinstance(details, list)
    return {str(detail["name"]): detail for detail in details}


def test_teams_payload_carries_mascot(team_catalog_client: TestClient) -> None:
    body = team_catalog_client.get("/api/teams", params={"year": OLD_YEAR}).json()
    details = _details_by_name(body)

    assert details["Texas"] == {
        "name": "Texas",
        "mascot": "Longhorns",
        "aliases": ["TEX", "Texas Longhorns"],
    }
    assert details["Ohio State"] == {
        "name": "Ohio State",
        "mascot": "Buckeyes",
        "aliases": ["OSU"],
    }


def test_team_detail_name_is_byte_identical_to_teams_school(
    team_catalog_client: TestClient, tmp_path: Path
) -> None:
    """`name` is what the client submits back -- it must be the raw
    `teams.school` string from the db, not a display-joined variant."""
    body = team_catalog_client.get("/api/teams").json()

    conn: sqlite3.Connection = get_conn(tmp_path / "team_catalog.sqlite3", read_only=True)
    try:
        schools = {
            str(row["school"])
            for row in conn.execute("SELECT school FROM teams WHERE sport = 'cfb'")
        }
    finally:
        conn.close()

    assert set(_details_by_name(body)) == schools
    # and specifically: no mascot smuggled into the canonical name
    assert "Texas" in schools
    assert all("Longhorns" not in name for name in schools)


def test_nfl_teams_payload_has_null_mascot(team_catalog_client: TestClient) -> None:
    """Every NFL row carries `mascot: null` -- "New England Patriots"
    already contains both city and nickname, so there is no mascot to
    add."""
    body = team_catalog_client.get("/api/teams", params={"sport": "nfl"}).json()
    details = _details_by_name(body)

    assert details["New England Patriots"] == {
        "name": "New England Patriots",
        "mascot": None,
        "aliases": [],
    }
    assert all(detail["mascot"] is None for detail in details.values())


def test_null_and_empty_alternate_names_decode_to_empty_list(
    team_catalog_client: TestClient,
) -> None:
    """`NULL` and `'[]'` both mean "no aliases known" -- neither may become
    `None`, a literal `"[]"` string, or a crash."""
    details = _details_by_name(
        team_catalog_client.get("/api/teams", params={"year": OLD_YEAR}).json()
    )

    assert details["Null Alias State"] == {
        "name": "Null Alias State",
        "mascot": None,
        "aliases": [],
    }
    assert details["Empty Alias Tech"] == {
        "name": "Empty Alias Tech",
        "mascot": "Zeroes",
        "aliases": [],
    }


def test_real_fixture_serves_real_mascots_and_unpopulated_columns_alike(
    client: TestClient,
) -> None:
    """The committed real-data fixture carries the CFBD `/teams` enrichment
    (#77) since #110 rebuilt it: 450 of its 451 CFB teams have a mascot.
    The one that doesn't, Cal State Northridge (CFBD has no mascot for it),
    has both columns NULL -- and that must still be a perfectly ordinary
    detail, not an error, exactly like a real team with a mascot."""
    response = client.get("/api/teams")

    assert response.status_code == 200
    details = _details_by_name(response.json())
    assert details["Texas"] == {
        "name": "Texas",
        "mascot": "Longhorns",
        "aliases": ["TEX", "Texas"],
    }
    assert details["Cal State Northridge"] == {
        "name": "Cal State Northridge",
        "mascot": None,
        "aliases": [],
    }
    assert len(details) == 451
    assert [name for name, detail in details.items() if detail["mascot"] is None] == [
        "Cal State Northridge"
    ]


def test_teams_and_team_details_stay_aligned(
    client: TestClient, team_catalog_client: TestClient
) -> None:
    """Both arrays come from one query, so they must stay in the same order
    and cover the same set -- a web consumer is allowed to zip them by
    index."""
    responses = [
        client.get("/api/teams"),
        client.get("/api/teams", params={"year": 2005}),
        team_catalog_client.get("/api/teams", params={"sport": "nfl"}),
        team_catalog_client.get("/api/teams", params={"sport": "nfl", "year": OLD_YEAR}),
        team_catalog_client.get("/api/teams", params={"year": OLD_YEAR}),
    ]

    for response in responses:
        assert response.status_code == 200
        body = response.json()
        names = [detail["name"] for detail in body["team_details"]]
        assert names == body["teams"]
        assert set(names) == set(body["teams"])
        assert len(names) == len(body["teams"])
        assert len(set(names)) == len(names), "no duplicate team names in either array"


def test_aliases_are_decoded_json_not_raw_strings(team_catalog_client: TestClient) -> None:
    """Guards the specific regression of forwarding the stored column
    verbatim: the db holds a JSON *string*, the API must serve a JSON
    array."""
    details = _details_by_name(
        team_catalog_client.get("/api/teams", params={"year": OLD_YEAR}).json()
    )
    aliases = details["Texas"]["aliases"]

    assert isinstance(aliases, list)
    assert all(isinstance(alias, str) for alias in aliases)
    # i.e. the stored JSON *string* was never forwarded verbatim
    assert aliases == json.loads('["TEX", "Texas Longhorns"]')
