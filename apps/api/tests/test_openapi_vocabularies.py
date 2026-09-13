"""`sport` and `method` are named once, in `cfb_strength.contracts`, and the
API publishes exactly that vocabulary (issue #112, epic #113).

`Sport` and `Method` are the engine's contract aliases. The engine's own
`tests/test_contract_vocabularies.py` ties them to what the engine actually
runs (`METHODS`, `ELO_CONFIGS`, the CLI dispatch, argparse's `--sport`
choices). This file ties the API to the aliases and publishes the result for
`apps/web`, in four links:

1. **No local copy.** `api.models.Sport`/`Method` are the contract aliases,
   and nothing under `src/api/` redeclares either vocabulary. An `is` check
   alone cannot prove that: `typing` caches `Literal[...]` subscriptions, so
   a hand-written `Literal["cfb", "nfl"]` with the same values *is* the
   contract's object (verified). So the check also reads `src/api/`'s source
   and fails on any module-level binding of `Sport`/`Method` that isn't the
   import, or on any `Literal[...]` naming a vocabulary value.

2. **Published schema == contract.** Every `sport`/`method` property or
   parameter in `app.openapi()` must carry an enum. All the enums for one
   name must agree, order included, and must equal `typing.get_args` of the
   alias. The walk is `api.openapi_vocabularies.find_occurrences`. A floor
   (`REQUIRED_LOCATIONS`, written out independently of that module) keeps
   the walk from passing by finding nothing.

3. **Enum-less fields fail, by location.** The one tolerated exception is
   `api.openapi_vocabularies.UNCONSTRAINED_LOCATIONS`, which says why. An
   entry there that stops matching an enum-less field is itself a failure,
   so the allowlist can't outlive its reason.

4. **The committed file is current.** `apps/api/openapi-vocabularies.json`
   is what `apps/web` is checked against. It must be byte-identical to what
   extraction from the live `app.openapi()` produces; on mismatch the
   message prints the regenerate command.

Not checked here: that runtime validation rejects bad values and accepts
every valid one. `test_sport_validation.py` and `test_method_validation.py`
do that, taking their valid values from the same aliases.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, get_args

import pytest
from cfb_strength import contracts

import api.models

API_ROOT = Path(__file__).resolve().parents[1]
SRC_API = API_ROOT / "src" / "api"
VOCABULARY_FILE = API_ROOT / "openapi-vocabularies.json"
REGENERATE_COMMAND = (
    "cd apps/api && uv run python -m api.openapi_vocabularies > openapi-vocabularies.json"
)

CONTRACT_ALIASES: dict[str, Any] = {"sport": contracts.Sport, "method": contracts.Method}

# The floor. Written out by hand, deliberately NOT derived from the walker or
# its constants: if `find_occurrences` stops finding things (a misspelled
# field name, a skipped schema section), these go missing and the test fails.
_VERDICT_REQUESTS = ("ChampionRequest", "TeamCaseRequest", "ComparisonRequest")
REQUIRED_LOCATIONS: dict[str, tuple[str, ...]] = {
    "sport": (
        *(f"#/components/schemas/{model}/properties/sport" for model in _VERDICT_REQUESTS),
        "#/components/schemas/UnknownTeamErrorBody/properties/sport",
        "GET /api/years query parameter 'sport'",
        "GET /api/teams query parameter 'sport'",
    ),
    "method": (
        *(f"#/components/schemas/{model}/properties/method" for model in _VERDICT_REQUESTS),
        # Issue #152: the compare verdict's evidence names the method that answered it.
        "#/components/schemas/ComparisonResultOut/properties/method",
        "GET /api/years query parameter 'method'",
        "GET /api/teams query parameter 'method'",
    ),
}


def _live_openapi() -> dict[str, Any]:
    from api.main import app

    return app.openapi()


# ---------------------------------------------------------------------------
# 1. no local copy
# ---------------------------------------------------------------------------


def test_models_aliases_are_the_contract_aliases() -> None:
    assert api.models.Sport is contracts.Sport
    assert api.models.Method is contracts.Method


# Where a module under src/api/ may import a name `Sport`/`Method` from: the
# contract itself, or `api.models`' re-export of it.
_ALLOWED_ALIAS_SOURCES = frozenset({"cfb_strength.contracts", "api.models"})


def _vocabulary_values() -> set[str]:
    return {value for alias in CONTRACT_ALIASES.values() for value in get_args(alias)}


def _redeclarations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    found: list[str] = []
    names = {"Sport", "Method"}
    for node in tree.body:
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign | ast.TypeAlias):
            targets = [node.target] if isinstance(node, ast.AnnAssign) else [node.name]
        elif isinstance(node, ast.ImportFrom) and node.module not in _ALLOWED_ALIAS_SOURCES:
            found.extend(
                f"{path.name}:{node.lineno} binds {alias.asname or alias.name} by importing "
                f"{alias.name} from {node.module}"
                for alias in node.names
                if (alias.asname or alias.name) in names
            )
        for target in targets:
            if isinstance(target, ast.Name) and target.id in names:
                found.append(f"{path.name}:{node.lineno} binds {target.id} locally")
    values = _vocabulary_values()
    for sub in ast.walk(tree):
        if not (isinstance(sub, ast.Subscript) and _is_literal(sub.value)):
            continue
        members = sub.slice.elts if isinstance(sub.slice, ast.Tuple) else [sub.slice]
        hits = [m.value for m in members if isinstance(m, ast.Constant) and m.value in values]
        if hits:
            found.append(f"{path.name}:{sub.lineno} spells out Literal[...] with {hits!r}")
    return found


def _is_literal(node: ast.expr) -> bool:
    return (isinstance(node, ast.Name) and node.id == "Literal") or (
        isinstance(node, ast.Attribute) and node.attr == "Literal"
    )


def test_no_module_under_src_api_redeclares_either_vocabulary() -> None:
    found = [hit for path in sorted(SRC_API.rglob("*.py")) for hit in _redeclarations(path)]

    assert found == [], (
        "apps/api must take Sport/Method from cfb_strength.contracts (re-exported by "
        "api.models), never spell the vocabulary out itself:\n  " + "\n  ".join(found)
    )


def test_redeclaration_scan_is_not_vacuous(tmp_path: Path) -> None:
    """The scan must see the exact sabotage `is` cannot: a local literal
    with the same values."""
    sample = tmp_path / "models.py"
    sample.write_text(
        "from typing import Literal\n"
        'Sport = Literal["cfb", "nfl"]\n'
        'def f(method: Literal["elo"]) -> None: ...\n'
    )

    found = _redeclarations(sample)

    assert any("binds Sport locally" in hit for hit in found), found
    assert any("'elo'" in hit for hit in found), found


# ---------------------------------------------------------------------------
# 2 + 3. published schema == contract, and enum-less fields fail by location
# ---------------------------------------------------------------------------


def test_walk_finds_at_least_the_known_surfaces() -> None:
    from api.openapi_vocabularies import find_occurrences

    found = {(o.name, o.location) for o in find_occurrences(_live_openapi())}
    missing = [
        f"{name} at {location}"
        for name, locations in REQUIRED_LOCATIONS.items()
        for location in locations
        if (name, location) not in found
    ]

    assert missing == [], (
        "the OpenAPI walk did not find these known sport/method surfaces, so it "
        "cannot be trusted to have checked anything:\n  "
        + "\n  ".join(missing)
        + f"\nfound: {sorted(found)!r}"
    )


def test_every_published_sport_and_method_carries_an_enum_that_agrees() -> None:
    from api.openapi_vocabularies import vocabulary_problems

    problems = vocabulary_problems(_live_openapi())

    assert problems == [], "\n".join(problems)


def test_published_vocabularies_equal_the_contract_aliases() -> None:
    from api.openapi_vocabularies import extract_vocabularies

    published = extract_vocabularies(_live_openapi())

    assert published == {name: list(get_args(alias)) for name, alias in CONTRACT_ALIASES.items()}


def _doc(**paths_and_components: Any) -> dict[str, Any]:
    return {"openapi": "3.1.0", "paths": {}, "components": {"schemas": {}}, **paths_and_components}


_SPORT_ENUM = {"type": "string", "enum": ["cfb", "nfl"]}


def test_an_enum_less_parameter_is_reported_by_location() -> None:
    from api.openapi_vocabularies import vocabulary_problems

    doc = _doc(
        paths={
            "/api/years": {
                "get": {
                    "parameters": [{"name": "sport", "in": "query", "schema": {"type": "string"}}]
                }
            }
        },
        components={"schemas": {"Req": {"properties": {"sport": _SPORT_ENUM}}}},
    )

    problems = vocabulary_problems(doc, unconstrained={})

    assert any(
        "GET /api/years query parameter 'sport'" in p and "no enum" in p for p in problems
    ), problems


@pytest.mark.parametrize(
    "schema",
    [
        {"anyOf": [_SPORT_ENUM, {"type": "null"}]},
        {"allOf": [{"$ref": "#/components/schemas/SportEnum"}]},
        {"$ref": "#/components/schemas/SportEnum"},
    ],
    ids=["anyOf-nullable", "allOf-ref", "ref"],
)
def test_enums_behind_indirection_are_seen(schema: dict[str, Any]) -> None:
    from api.openapi_vocabularies import extract_vocabularies, vocabulary_problems

    doc = _doc(
        components={
            "schemas": {
                "SportEnum": _SPORT_ENUM,
                "Req": {"properties": {"sport": schema, "method": {"enum": ["keener"]}}},
            }
        }
    )

    assert vocabulary_problems(doc, unconstrained={}) == []
    assert extract_vocabularies(doc, unconstrained={})["sport"] == ["cfb", "nfl"]


def test_disagreeing_enums_for_one_name_are_reported_with_both_locations() -> None:
    from api.openapi_vocabularies import vocabulary_problems

    doc = _doc(
        components={
            "schemas": {
                "A": {"properties": {"sport": _SPORT_ENUM, "method": {"enum": ["keener"]}}},
                "B": {"properties": {"sport": {"enum": ["nfl", "cfb"]}}},
            }
        }
    )

    problems = vocabulary_problems(doc, unconstrained={})

    assert any(
        "disagreeing" in p
        and "#/components/schemas/A/properties/sport" in p
        and "#/components/schemas/B/properties/sport" in p
        for p in problems
    ), problems


def test_a_nullable_branch_without_an_enum_is_still_enum_less() -> None:
    from api.openapi_vocabularies import vocabulary_problems

    doc = _doc(
        components={
            "schemas": {
                "A": {
                    "properties": {
                        "sport": {"anyOf": [_SPORT_ENUM, {"type": "string"}]},
                        "method": {"enum": ["keener"]},
                    }
                }
            }
        }
    )

    problems = vocabulary_problems(doc, unconstrained={})

    assert any(
        "#/components/schemas/A/properties/sport" in p and "no enum" in p for p in problems
    ), problems


def test_a_stale_allowlist_entry_is_reported() -> None:
    from api.openapi_vocabularies import vocabulary_problems

    doc = _doc(components={"schemas": {"A": {"properties": {"sport": _SPORT_ENUM}}}})
    location = "#/components/schemas/A/properties/sport"

    problems = vocabulary_problems(doc, unconstrained={("sport", location): "was enum-less"})

    assert any(location in p and "stale" in p for p in problems), problems


# ---------------------------------------------------------------------------
# 4. the committed file is current
# ---------------------------------------------------------------------------


def test_committed_vocabulary_file_matches_the_live_schema() -> None:
    from api.openapi_vocabularies import extract_vocabularies, render

    expected = render(extract_vocabularies(_live_openapi()))
    committed_bytes = VOCABULARY_FILE.read_bytes() if VOCABULARY_FILE.exists() else b"<missing>"
    committed = committed_bytes.decode(errors="replace")

    assert committed_bytes == expected.encode(), (
        f"{VOCABULARY_FILE.name} is stale: it is what apps/web is checked against, and it "
        f"no longer matches what the API publishes. Regenerate it with:\n\n"
        f"    {REGENERATE_COMMAND}\n\n"
        f"committed:\n{committed}\nlive:\n{expected}"
    )


def test_rendered_format_is_fixed() -> None:
    from api.openapi_vocabularies import render

    assert render({"sport": ["cfb", "nfl"], "method": ["keener", "elo"]}) == (
        '{\n  "method": [\n    "keener",\n    "elo"\n  ],\n'
        '  "sport": [\n    "cfb",\n    "nfl"\n  ]\n}\n'
    )
