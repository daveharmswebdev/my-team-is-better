"""Position groups over HTTP (issue #433, epic #372 step 2): the players API
compares like with like.

Founder decisions (#372, 2026-10-20): a player's group comes from his
`players.position` label through the engine's `contracts.position_group`
(QB; RB, with FB; WR; TE; every other label, and a NULL one, has none).

- `/api/players/search` takes an optional `group` and echoes it; each row
  says which group its player is in.
- A career page (and so each side of a comparison) says it too.
- `/api/players/compare` refuses a pair from different groups, or one where
  either player has no group, with a 400 `players_not_comparable` naming
  both groups. A mixed-group shared link is refused, never shown. The
  existing checks come first: `a == b` is a 422 at `b`, then the first
  unknown id is a 404.

Every id and label below is measured on the committed fixture.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

SEARCH = "/api/players/search"
COMPARE = "/api/players/compare"

KURT_WARNER = 2044124519  # QB
STEVE_MCNAIR = 2385180619  # QB
EDDIE_GEORGE = 2464876093  # RB
MARSHALL_FAULK = 2252790861  # RB
ISAAC_BRUCE = 2485311210  # WR
FRANK_WYCHECK = 2230939598  # TE
JEFF_WILKINS = 2050106967  # K: no group
JEVON_KEARSE = 2147848504  # DE: no group

GROUPS = ("QB", "RB", "WR", "TE")


def _ok(client: TestClient, url: str, **params: str | int) -> Any:
    response = client.get(url, params=params)
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


def test_search_by_group_keeps_only_that_group_fullbacks_included(client: TestClient) -> None:
    body = _ok(client, SEARCH, q="rob", group="RB", limit=20)

    assert body["group"] == "RB"
    positions = [row["position"] for row in body["rows"]]
    assert positions and set(positions) == {"RB", "FB"}, positions
    assert all(row["group"] == "RB" for row in body["rows"])
    # Filtered before the limit: Robert Holcombe (FB) is outside the
    # unfiltered top 20 for 'rob' but inside the RB-filtered one.
    unfiltered = _ok(client, SEARCH, q="rob", limit=20)
    assert "Robert Holcombe" not in [row["display_name"] for row in unfiltered["rows"]]
    assert "Robert Holcombe" in [row["display_name"] for row in body["rows"]]


def test_an_unfiltered_search_echoes_a_null_group_and_labels_every_row(
    client: TestClient,
) -> None:
    body = _ok(client, SEARCH, q="rob", limit=20)

    assert body["group"] is None
    by_position = {row["position"]: row["group"] for row in body["rows"]}
    assert by_position["RB"] == "RB"
    assert by_position["FB"] == "RB"
    assert by_position["WR"] == "WR"
    assert by_position["LB"] is None
    assert by_position["P"] is None


@pytest.mark.parametrize("group", GROUPS)
def test_every_group_filters_to_itself(client: TestClient, group: str) -> None:
    body = _ok(client, SEARCH, q="an", group=group, limit=20)

    assert body["group"] == group
    assert body["rows"], group
    assert {row["group"] for row in body["rows"]} == {group}


@pytest.mark.parametrize("group", ["K", "rb", "FB", "", "OL"])
def test_an_unknown_group_is_a_422_at_group(client: TestClient, group: str) -> None:
    response = client.get(SEARCH, params={"q": "rob", "group": group})

    assert response.status_code == 422, response.text
    assert [tuple(e["loc"]) for e in response.json()["detail"]] == [("query", "group")]


# ---------------------------------------------------------------------------
# career pages
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "player_id,group",
    [
        (KURT_WARNER, "QB"),
        (EDDIE_GEORGE, "RB"),
        (ISAAC_BRUCE, "WR"),
        (FRANK_WYCHECK, "TE"),
        (JEFF_WILKINS, None),
        (JEVON_KEARSE, None),
    ],
)
def test_a_career_page_carries_its_group(
    client: TestClient, player_id: int, group: str | None
) -> None:
    body = _ok(client, f"/api/players/{player_id}")

    assert "group" in body
    assert body["group"] == group


# ---------------------------------------------------------------------------
# compare
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "a,b,group",
    [
        (KURT_WARNER, STEVE_MCNAIR, "QB"),
        (EDDIE_GEORGE, MARSHALL_FAULK, "RB"),
    ],
)
def test_a_same_group_pair_compares(client: TestClient, a: int, b: int, group: str) -> None:
    body = _ok(client, COMPARE, a=a, b=b)

    assert body["a"]["group"] == body["b"]["group"] == group


@pytest.mark.parametrize(
    "a,b,a_group,b_group",
    [
        (KURT_WARNER, EDDIE_GEORGE, "QB", "RB"),
        (EDDIE_GEORGE, ISAAC_BRUCE, "RB", "WR"),
        (FRANK_WYCHECK, ISAAC_BRUCE, "TE", "WR"),
        (KURT_WARNER, JEFF_WILKINS, "QB", None),
        (JEFF_WILKINS, KURT_WARNER, None, "QB"),
        # Neither has a group: two "nothings" are not a group (K vs DE, and
        # the same label on both sides is no exception).
        (JEFF_WILKINS, JEVON_KEARSE, None, None),
    ],
)
def test_a_pair_outside_one_group_is_a_400_naming_both_groups(
    client: TestClient, a: int, b: int, a_group: str | None, b_group: str | None
) -> None:
    response = client.get(COMPARE, params={"a": a, "b": b})

    assert response.status_code == 400, response.text
    assert response.json() == {
        "detail": {"error": "players_not_comparable", "a_group": a_group, "b_group": b_group}
    }


def test_two_players_who_share_a_groupless_label_are_still_refused(
    client: TestClient,
) -> None:
    """Two kickers: the same label, still no group, still a 400."""
    kickers = _ok(client, "/api/players/leaders", category="kicking", limit=2)["rows"]
    a, b = (row["player_id"] for row in kickers)
    assert [row["position"] for row in kickers] == ["K", "K"]

    response = client.get(COMPARE, params={"a": a, "b": b})

    assert response.status_code == 400, response.text
    assert response.json()["detail"] == {
        "error": "players_not_comparable",
        "a_group": None,
        "b_group": None,
    }


def test_the_same_player_twice_is_still_a_422_even_without_a_group(
    client: TestClient,
) -> None:
    response = client.get(COMPARE, params={"a": JEFF_WILKINS, "b": JEFF_WILKINS})

    assert response.status_code == 422, response.text
    assert [tuple(e["loc"]) for e in response.json()["detail"]] == [("query", "b")]


@pytest.mark.parametrize(
    "a,b,echoed",
    [(1, JEFF_WILKINS, 1), (JEFF_WILKINS, 1, 1), (KURT_WARNER, 2, 2), (1, KURT_WARNER, 1)],
)
def test_an_unknown_id_is_still_a_404_before_any_group_check(
    client: TestClient, a: int, b: int, echoed: int
) -> None:
    response = client.get(COMPARE, params={"a": a, "b": b})

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == {
        "error": "unknown_player",
        "player_id": echoed,
        "sport": "nfl",
    }


# ---------------------------------------------------------------------------
# /openapi.json
# ---------------------------------------------------------------------------


def _group_enum(openapi: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    """The non-null branch's enum of a `PlayerPositionGroup | None`."""
    branches = schema.get("anyOf", [schema])
    enums = []
    for branch in branches:
        if "$ref" in branch:
            branch = openapi["components"]["schemas"][branch["$ref"].rsplit("/", 1)[1]]
        if branch.get("type") == "null":
            continue
        enums.append(branch["enum"])
    assert len(enums) == 1, schema
    return list(enums[0])


def test_group_publishes_as_the_four_value_enum(client: TestClient) -> None:
    openapi = client.get("/openapi.json").json()
    schemas = openapi["components"]["schemas"]

    params = {p["name"]: p for p in openapi["paths"][SEARCH]["get"]["parameters"]}
    assert params["group"]["required"] is False
    assert _group_enum(openapi, params["group"]["schema"]) == list(GROUPS)
    for model in ("PlayerSearchOut", "PlayerSearchRowOut", "PlayerCareerOut"):
        assert "group" in schemas[model]["required"], model
        assert _group_enum(openapi, schemas[model]["properties"]["group"]) == list(GROUPS)
    body = schemas["PlayersNotComparableErrorBody"]
    for field in ("a_group", "b_group"):
        assert _group_enum(openapi, body["properties"][field]) == list(GROUPS)


def test_compare_publishes_its_400(client: TestClient) -> None:
    openapi = client.get("/openapi.json").json()
    responses = openapi["paths"][COMPARE]["get"]["responses"]

    schema = responses["400"]["content"]["application/json"]["schema"]
    assert schema == {"$ref": "#/components/schemas/PlayersNotComparableErrorResponse"}
