"""Failing-first test for `/api/credits` (GitHub issue #29/#30, updated for
#59's `Credits.data_sources` list rename and for the Elo engine's
`Credits.methodologies` list rename).

Like `/api/years` and `/api/teams`, this is a plain evidence-catalog read --
no persona/narration envelope, no db connection at all (`get_credits()`
takes no arguments and touches no database). The expected body is taken
directly from `cfb_strength.evidence.credits.get_credits()`'s actual return
value rather than retyped from memory, so this test breaks if that single
source of truth ever changes -- which is the point (ARCHITECTURE §4.5: no
hardcoded duplicate copy of the citation text in apps/api).

Two singular-to-plural contract renames are pinned here. `Credits.data_source`
became `Credits.data_sources` in PR #67, so both CollegeFootballData.com (CFB)
and nflverse/Lee Sharpe (NFL) must show up. `Credits.methodology` became
`Credits.methodologies` when the Elo engine landed (PR #93), so both Keener's
method and Elo must show up, in that order.

The Keener/Elo assertions below are deliberately *content* assertions, not
just shape ones: PRD §5.6 makes crediting the people whose work this is built
on an explicit product requirement, so a future change that quietly drops the
second methodology -- or drops Arpad Elo's or FiveThirtyEight's name out of
it -- must fail a test rather than merely change a payload.

Issue #144 adds `methods` to each methodology entry: the registered rating
methods that citation covers, copied from the engine's
`MethodologyCredit.methods` tuple into a JSON array. The About page keys its
article anchors on `methods[0]` (`keener`, `elo`), so the wire shape is
pinned here per entry, and the union across the response must equal the
engine's whole `Method` vocabulary -- the engine's own
tests/test_evidence_credits.py guarantees every registered method is
covered by exactly one credit, and this file checks the API doesn't lose
that on the way out. The OpenAPI check at the bottom is what `apps/web`'s
generated `MethodologyCredit.methods: Method[]` type rests on: `methods`
must be required (no default that could silently publish `[]`) and its
items must carry the `Method` enum rather than a bare string.
"""

from __future__ import annotations

from typing import Any, get_args

from cfb_strength.contracts import Method
from cfb_strength.evidence.credits import get_credits
from fastapi.testclient import TestClient


def test_credits_endpoint_returns_real_attribution_data(client: TestClient) -> None:
    response = client.get("/api/credits")

    assert response.status_code == 200
    body = response.json()

    credits = get_credits()
    assert body == {
        "methodologies": [
            {
                "name": methodology.name,
                "citation": methodology.citation,
                "url": methodology.url,
                "summary": methodology.summary,
                "methods": list(methodology.methods),
            }
            for methodology in credits.methodologies
        ],
        "data_sources": [
            {
                "id": data_source.id,
                "name": data_source.name,
                "url": data_source.url,
                "note": data_source.note,
            }
            for data_source in credits.data_sources
        ],
    }


def test_credits_endpoint_publishes_each_data_source_id_in_order(client: TestClient) -> None:
    """Issue #296: a page showing one source's data (the player pages show
    nflverse player stats) picks that source's credit by `id`, never by a
    display name that could be reworded. Pinned literally, in
    `get_credits()`'s order, so a renamed or dropped id fails here."""
    response = client.get("/api/credits")

    assert response.status_code == 200
    ids = [entry["id"] for entry in response.json()["data_sources"]]
    assert ids == ["cfbd", "nflverse_games", "nflverse_player_stats"]
    assert ids == [data_source.id for data_source in get_credits().data_sources]


def test_openapi_publishes_data_source_id_as_required() -> None:
    from api.main import app

    schema = app.openapi()["components"]["schemas"]["DataSourceCreditOut"]

    assert "id" in schema["required"], schema.get("required")
    assert schema["properties"]["id"]["type"] == "string"


def test_credits_endpoint_lists_both_keener_and_elo_in_order(client: TestClient) -> None:
    """Both rating methods this engine implements are credited, Keener
    first then Elo -- the order `get_credits()` returns them in, which is
    the order the About page renders.

    Pinned against literal names rather than only against
    `get_credits()`'s own output: a whole-payload equality check passes
    happily if a methodology is deleted from the source of truth, and
    silently dropping an attribution is exactly the regression PRD §5.6
    exists to prevent.
    """
    response = client.get("/api/credits")

    assert response.status_code == 200
    methodologies = response.json()["methodologies"]

    assert [entry["name"] for entry in methodologies] == ["Keener's method", "Elo"]

    credits = get_credits()
    assert [entry["name"] for entry in methodologies] == [
        methodology.name for methodology in credits.methodologies
    ]


def test_credits_endpoint_names_elo_and_fivethirtyeight(client: TestClient) -> None:
    """The Elo entry credits Arpad Elo (who invented the system) and
    FiveThirtyEight (whose published football adaptation this engine
    implements from the formula, clean-room). Both names are a founder
    value, not boilerplate -- see CLAUDE.md's standing attribution
    preference and PRD §5.6.
    """
    response = client.get("/api/credits")

    assert response.status_code == 200
    elo = next(entry for entry in response.json()["methodologies"] if entry["name"] == "Elo")

    attribution_text = f"{elo['citation']} {elo['summary']}"
    assert "Arpad" in attribution_text and "Elo" in attribution_text
    assert "FiveThirtyEight" in attribution_text
    assert elo["url"]


def test_credits_endpoint_lists_both_cfbd_and_nflverse(client: TestClient) -> None:
    """Issue #59: nflverse/Lee Sharpe attribution must be listed alongside
    the existing CollegeFootballData.com entry, matching the standing
    project preference (CLAUDE.md) that original data sources be credited
    prominently in-product, not just in a README.
    """
    response = client.get("/api/credits")

    assert response.status_code == 200
    names = {entry["name"] for entry in response.json()["data_sources"]}

    credits = get_credits()
    assert names == {data_source.name for data_source in credits.data_sources}
    assert any("CollegeFootballData" in name for name in names)
    assert any("nflverse" in name for name in names)


# ---------------------------------------------------------------------------
# issue #144: each credit names the rating methods it covers
# ---------------------------------------------------------------------------


def _methodologies_by_name(client: TestClient) -> dict[str, dict[str, Any]]:
    response = client.get("/api/credits")
    assert response.status_code == 200
    entries: list[dict[str, Any]] = response.json()["methodologies"]
    return {entry["name"]: entry for entry in entries}


def test_credits_keener_entry_covers_keener_only(client: TestClient) -> None:
    """`methods[0]` is the credit's stable id downstream, so the Keener
    entry's array is pinned literally rather than only against the engine's
    tuple: the About page anchors its Keener article on `"keener"`."""
    methodologies = _methodologies_by_name(client)

    assert methodologies["Keener's method"]["methods"] == ["keener"]


def test_credits_elo_entry_covers_elo_then_elo_career(client: TestClient) -> None:
    """The Elo citation covers both the single-season and career-carryover
    variants, `elo` first so `methods[0]` stays the About page's `elo`
    anchor. Order is the engine tuple's order, published as a JSON array
    (a tuple has no JSON shape of its own)."""
    methodologies = _methodologies_by_name(client)

    assert methodologies["Elo"]["methods"] == ["elo", "elo_career"]


def test_credits_methods_union_is_the_whole_method_vocabulary(client: TestClient) -> None:
    """Every registered method is covered by exactly one credit. The engine
    test guarantees that for `get_credits()`; this guarantees the API
    publishes it intact (no entry dropped, no array truncated) so the About
    page never has a method with no article, or two articles for one."""
    response = client.get("/api/credits")
    assert response.status_code == 200
    published = [
        method for entry in response.json()["methodologies"] for method in entry["methods"]
    ]

    assert set(published) == set(get_args(Method))
    assert len(published) == len(set(published)), f"a method is credited twice: {published!r}"

    credits = get_credits()
    assert published == [m for methodology in credits.methodologies for m in methodology.methods]


def test_openapi_publishes_methods_as_a_required_enum_array() -> None:
    """`apps/web` generates `MethodologyCredit.methods: Method[]` from this
    schema. That needs `methods` to be required (a defaulted field would
    become optional on the TypeScript side and let `[]` slip through
    silently) and its items to carry the `Method` enum, in the contract's
    order, rather than a bare `string`."""
    from api.main import app

    schema = app.openapi()["components"]["schemas"]["MethodologyCreditOut"]

    assert "methods" in schema["required"], schema.get("required")
    methods = schema["properties"]["methods"]
    assert methods["type"] == "array", methods
    assert methods["items"] == {"type": "string", "enum": list(get_args(Method))}, methods
