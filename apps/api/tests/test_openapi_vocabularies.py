"""`sport`, `method` and `group` are named once, in `cfb_strength.contracts`,
and the API publishes exactly that vocabulary (issues #112, #436; epics #113,
#372).

`group` is the players API's `PlayerPositionGroup` (#433). It is checked the
same way as the other two below, and is also published under two other
property names (`a_group`/`b_group`, via
`api.openapi_vocabularies.ALIASED_PROPERTIES`).

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

CONTRACT_ALIASES: dict[str, Any] = {
    "sport": contracts.Sport,
    "method": contracts.Method,
    "group": contracts.PlayerPositionGroup,
}

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
        # Issue #296: the player read layer. Its routes accept only the
        # leagues with player stats at runtime (a 422 otherwise), but the
        # published enum is still the contract's whole `Sport`.
        "GET /api/players/leaders query parameter 'sport'",
        "GET /api/players/{player_id} query parameter 'sport'",
        "#/components/schemas/PlayerLeadersOut/properties/sport",
        "#/components/schemas/PlayerCareerOut/properties/sport",
        "#/components/schemas/UnknownPlayerErrorBody/properties/sport",
        # Issue #301: comparison and search, the same runtime-narrowed `sport`.
        "GET /api/players/compare query parameter 'sport'",
        "GET /api/players/search query parameter 'sport'",
        "#/components/schemas/PlayerComparisonOut/properties/sport",
        "#/components/schemas/PlayerSearchOut/properties/sport",
    ),
    "method": (
        *(f"#/components/schemas/{model}/properties/method" for model in _VERDICT_REQUESTS),
        # Issue #152: the compare verdict's evidence names the method that answered it.
        "#/components/schemas/ComparisonResultOut/properties/method",
        # Issue #155: each envelope's other-method ranks name their method.
        "#/components/schemas/MethodRankOut/properties/method",
        "GET /api/years query parameter 'method'",
        "GET /api/teams query parameter 'method'",
    ),
    # Issue #433: the players API's position group, on search and careers,
    # and both players' groups on the not-comparable error body.
    "group": (
        "GET /api/players/search query parameter 'group'",
        "#/components/schemas/PlayerSearchOut/properties/group",
        "#/components/schemas/PlayerSearchRowOut/properties/group",
        "#/components/schemas/PlayerCareerOut/properties/group",
        "#/components/schemas/PlayersNotComparableErrorBody/properties/a_group",
        "#/components/schemas/PlayersNotComparableErrorBody/properties/b_group",
    ),
}

# Enums equal to a vocabulary that the walk does not reach, each with its
# reason. `test_every_vocabulary_enum_in_the_schema_is_walked` fails on any
# other one, and on an entry here that the walk starts reaching.
UNWALKED_ENUMS: dict[str, str] = {
    "components/schemas/MethodologyCreditOut/properties/methods/items": (
        "a list of methods: the walk neither matches `methods` nor follows `items`"
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
    names = {"Sport", "Method", "PlayerPositionGroup"}
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
                "Req": {
                    "properties": {
                        "sport": schema,
                        "method": {"enum": ["keener"]},
                        "group": {"enum": ["QB"]},
                    }
                },
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


def test_an_aliased_property_counts_as_its_vocabulary_at_its_own_location() -> None:
    from api.openapi_vocabularies import find_occurrences, vocabulary_problems

    doc = _doc(
        components={
            "schemas": {
                "Err": {
                    "properties": {
                        "a_group": {"anyOf": [{"enum": ["QB", "RB"]}, {"type": "null"}]},
                        "b_group": {"enum": ["RB", "QB"]},
                    }
                }
            }
        }
    )

    found = {(o.name, o.location) for o in find_occurrences(doc)}
    problems = vocabulary_problems(doc, unconstrained={})

    assert ("group", "#/components/schemas/Err/properties/a_group") in found, found
    assert ("group", "#/components/schemas/Err/properties/b_group") in found, found
    assert any("disagreeing" in p and "a_group" in p and "b_group" in p for p in problems), problems


def _vocabulary_enums(node: Any, tokens: tuple[str, ...] = ()) -> list[tuple[str, tuple[str, ...]]]:
    """`(vocabulary, tokens)` for every enum under `node` equal to a contract
    alias. Tokens, not a joined path: path keys like `/api/years` contain `/`."""
    by_values = {tuple(get_args(alias)): name for name, alias in CONTRACT_ALIASES.items()}
    found: list[tuple[str, tuple[str, ...]]] = []
    if isinstance(node, dict):
        enum = node.get("enum")
        if isinstance(enum, list) and tuple(enum) in by_values:
            found.append((by_values[tuple(enum)], tokens))
        for key, child in node.items():
            found.extend(_vocabulary_enums(child, (*tokens, str(key))))
    elif isinstance(node, list):
        for index, child in enumerate(node):
            found.extend(_vocabulary_enums(child, (*tokens, str(index))))
    return found


def test_every_vocabulary_enum_in_the_schema_is_walked() -> None:
    """The reverse of the floor: an enum equal to `Sport`/`Method`/
    `PlayerPositionGroup` under a property name the walk doesn't match (a new
    `c_group`, say) would otherwise go unchecked and unpublished."""
    from api.openapi_vocabularies import find_occurrences

    openapi = _live_openapi()
    walked = {(o.name, o.location) for o in find_occurrences(openapi)}

    def walked_location(tokens: tuple[str, ...]) -> str | None:
        """The location the walk would report: the operation parameter, or
        the nearest enclosing property."""
        if len(tokens) > 4 and tokens[0] == "paths" and tokens[3] == "parameters":
            parameter = openapi["paths"][tokens[1]][tokens[2]]["parameters"][int(tokens[4])]
            return (
                f"{tokens[2].upper()} {tokens[1]} {parameter['in']} parameter '{parameter['name']}'"
            )
        for i in range(len(tokens) - 1, 0, -1):
            if tokens[i - 1] == "properties":
                return "#/" + "/".join(tokens[: i + 1])
        return None

    enums = [
        (name, "/".join(tokens), walked_location(tokens))
        for name, tokens in _vocabulary_enums(openapi)
    ]
    unwalked = sorted(
        f"{name} at {path}"
        for name, path, location in enums
        if path not in UNWALKED_ENUMS and (name, location) not in walked
    )
    stale = sorted(
        set(UNWALKED_ENUMS)
        - {path for name, path, location in enums if (name, location) not in walked}
    )

    assert len(enums) > len(UNWALKED_ENUMS), enums
    assert unwalked == [], (
        "these enums equal a published vocabulary, but the OpenAPI walk does not see "
        "them; add the property to ALIASED_PROPERTIES:\n  " + "\n  ".join(unwalked)
    )
    assert stale == [], f"stale UNWALKED_ENUMS entries (gone, or now walked): {stale}"
