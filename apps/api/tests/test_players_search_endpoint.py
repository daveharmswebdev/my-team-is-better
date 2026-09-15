"""`GET /api/players/search` (issue #301): find a player by name, published
faithfully from `cfb_strength.players.search_players` on the committed
fixture's real NFL 1999 + 2023 slice.

The expected rows are measured on the fixture, in the engine's contracted
order (regular-season passing yards descending, None last, then name, then
id), so the API re-sorts nothing and a faithful copy of a wrong engine
answer still fails here.

The HTTP boundary is the only thing this route adds. `q` is required and at
most 100 characters; after stripping it must keep at least
`PLAYER_SEARCH_MIN_QUERY_LENGTH` characters, which the route checks itself
so the engine's `ValueError` can never surface as a 500 (`' a '` is the
case a plain `min_length` misses). `limit` is 1..`PLAYER_SEARCH_MAX_LIMIT`,
`sport=cfb` is a 422, and no match is an honest 200 with no rows. `search`
must never be parsed as a `player_id`.
"""

from __future__ import annotations

from typing import Any

import pytest
from cfb_strength.contracts import PLAYER_SEARCH_MAX_LIMIT
from cfb_strength.players import search_players
from fastapi.testclient import TestClient
from fixtures.player_api_fixture import engine_json, fixture_conn

SEARCH = "/api/players/search"

KURT_WARNER = 2044124519
STEVE_MCNAIR = 2385180619

MEASURED: dict[str, list[str]] = {
    "warner": ["Kurt Warner"],
    "mcnair": ["Steve McNair"],
    "mc": [
        "Steve McNair",
        "Mike Tomczak",
        "Cade McNown",
        "Donovan McNabb",
        "AJ McCarron",
        "Jerick McKinnon",
    ],
    "man": ["Peyton Manning", "Troy Aikman", "Braden Mann", "Michael Pittman"],
}


def _search(client: TestClient, **params: str | int) -> Any:
    response = client.get(SEARCH, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _validation_locs(response: Any) -> list[tuple[str, ...]]:
    detail = response.json()["detail"]
    assert isinstance(detail, list) and detail, detail
    return [tuple(error["loc"]) for error in detail]


# ---------------------------------------------------------------------------
# results
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("q,names", sorted(MEASURED.items()))
def test_measured_results_in_contracted_order(client: TestClient, q: str, names: list[str]) -> None:
    body = _search(client, q=q)

    assert set(body) == {"sport", "query", "limit", "rows"}
    assert (body["sport"], body["query"], body["limit"]) == ("nfl", q, 10)
    assert [row["display_name"] for row in body["rows"]] == names


def test_a_row_carries_the_engines_fields(client: TestClient) -> None:
    body = _search(client, q="mcnair")

    assert body["rows"] == [
        {
            "player_id": STEVE_MCNAIR,
            "display_name": "Steve McNair",
            "position": "QB",
            "first_season": 1999,
            "last_season": 1999,
        }
    ]


@pytest.mark.parametrize(
    "q,limit", [("warner", 10), ("mc", 3), ("man", 20), ("an", 20), ("  Mc ", 5)]
)
def test_search_is_the_engines_search_field_for_field(
    client: TestClient, q: str, limit: int
) -> None:
    body = _search(client, q=q, limit=limit)

    with fixture_conn() as conn:
        assert body == engine_json(search_players(conn, sport="nfl", query=q, limit=limit))


def test_the_query_is_echoed_stripped(client: TestClient) -> None:
    body = _search(client, q="  Warner \t")

    assert body["query"] == "Warner"
    assert [row["player_id"] for row in body["rows"]] == [KURT_WARNER]


def test_limit_caps_the_rows_and_is_echoed(client: TestClient) -> None:
    body = _search(client, q="an", limit=PLAYER_SEARCH_MAX_LIMIT)

    assert body["limit"] == 20
    assert len(body["rows"]) == 20


def test_no_match_is_a_200_with_no_rows(client: TestClient) -> None:
    body = _search(client, q="zzyzx")

    assert body == {"sport": "nfl", "query": "zzyzx", "limit": 10, "rows": []}


def test_a_query_of_exactly_100_characters_is_accepted(client: TestClient) -> None:
    assert _search(client, q="z" * 100)["rows"] == []


def test_sport_defaults_to_nfl(client: TestClient) -> None:
    assert _search(client, q="mc") == _search(client, q="mc", sport="nfl")


# ---------------------------------------------------------------------------
# route matching: `search` is never a player_id
# ---------------------------------------------------------------------------


def test_search_reaches_its_own_route_not_the_career_route(client: TestClient) -> None:
    response = client.get(SEARCH)

    assert response.status_code == 422, response.text
    assert _validation_locs(response) == [("query", "q")]


def test_the_career_route_still_answers_for_an_id(client: TestClient) -> None:
    response = client.get(f"/api/players/{KURT_WARNER}")

    assert response.status_code == 200, response.text
    assert response.json()["display_name"] == "Kurt Warner"


# ---------------------------------------------------------------------------
# errors
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("q", ["", "a", " a ", "   ", "\ta\n", "z "])
def test_a_query_under_two_characters_after_stripping_is_a_422(client: TestClient, q: str) -> None:
    response = client.get(SEARCH, params={"q": q})

    assert response.status_code == 422, response.text
    assert _validation_locs(response) == [("query", "q")]


def test_a_query_over_100_characters_is_a_422(client: TestClient) -> None:
    response = client.get(SEARCH, params={"q": "z" * 101})

    assert response.status_code == 422, response.text
    assert _validation_locs(response) == [("query", "q")]


@pytest.mark.parametrize("limit", [0, -1, PLAYER_SEARCH_MAX_LIMIT + 1, "ten"])
def test_a_limit_out_of_range_is_a_422(client: TestClient, limit: int | str) -> None:
    response = client.get(SEARCH, params={"q": "mc", "limit": limit})

    assert response.status_code == 422, response.text
    assert _validation_locs(response) == [("query", "limit")]


@pytest.mark.parametrize("sport", ["cfb", "basketball"])
def test_a_non_nfl_sport_is_a_422_at_sport(client: TestClient, sport: str) -> None:
    response = client.get(SEARCH, params={"q": "mc", "sport": sport})

    assert response.status_code == 422, response.text
    assert ("query", "sport") in _validation_locs(response)


# ---------------------------------------------------------------------------
# /openapi.json
# ---------------------------------------------------------------------------


def test_openapi_documents_the_route(client: TestClient) -> None:
    openapi = client.get("/openapi.json").json()
    operation = openapi["paths"][SEARCH]["get"]

    ok = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert ok == {"$ref": "#/components/schemas/PlayerSearchOut"}
    assert "404" not in operation["responses"]
    params = {p["name"]: p for p in operation["parameters"]}
    assert set(params) == {"q", "limit", "sport"}
    assert params["q"]["required"] is True
    assert params["q"]["schema"]["maxLength"] == 100
    assert (params["limit"]["schema"]["minimum"], params["limit"]["schema"]["maximum"]) == (1, 20)
