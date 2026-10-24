"""Extract the `sport`/`method`/`group` vocabularies the API publishes in
`/openapi.json`, and write `apps/api/openapi-vocabularies.json` (issues #112,
#436).

That file is what `apps/web`'s own `Sport`/`Method`/`PlayerPositionGroup`
unions are checked against, so it is generated from the live `api.main.app.openapi()`, not from
`typing.get_args` on the aliases. It records what the API actually
advertises. `tests/test_openapi_vocabularies.py` separately proves that this
equals the `cfb_strength.contracts` aliases, and fails when the committed
file is stale.

Regenerate the committed file (from the repo root):

    cd apps/api && uv run python -m api.openapi_vocabularies > openapi-vocabularies.json

If the published schema is inconsistent (a vocabulary field with no
enum, or two enums that disagree), this exits non-zero and lists the
locations on stderr. The shell redirect will already have truncated the file,
and the freshness test then fails on it, so fix the schema and re-run.

Format (fixed, because `apps/web` builds against it): one key per
vocabulary name, keys sorted, each value the published enum in published
order, two-space indent, trailing newline.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

# `group` is the players API's `PlayerPositionGroup` (#433), published so
# apps/web can mirror it (epic #372 step 3, #436).
VOCABULARY_NAMES: Final[tuple[str, ...]] = ("group", "method", "sport")

ALIASED_PROPERTIES: Final[Mapping[str, str]] = {
    # `PlayersNotComparableErrorBody` echoes both players' groups (#433).
    "a_group": "group",
    "b_group": "group",
}
"""Properties whose name is not a vocabulary name but whose value is one,
mapped to that vocabulary. The walk matches property names exactly, so a
field like `a_group` is invisible to it unless it is listed here."""

_PROPERTY_VOCABULARIES: Final[Mapping[str, str]] = {
    **{name: name for name in VOCABULARY_NAMES},
    **ALIASED_PROPERTIES,
}

UNCONSTRAINED_LOCATIONS: Final[Mapping[tuple[str, str], str]] = {
    # A response field, not an input. The engine's `contracts.TeamCase.method`
    # is a plain `str`, and `TeamCaseOut.from_dataclass` copies it straight
    # through. Constraining this field to `Method` would need a `cast` over
    # the engine's type, and would add a response-side validation that can
    # turn into a 500. In practice the value is always the request's
    # already-validated `method`, so the published schema is merely looser
    # than reality, never wrong. Remove this entry once the engine types
    # `TeamCase.method` as `Method` (#139) and this field follows it; the test fails
    # on the entry the moment the field gains an enum.
    ("method", "#/components/schemas/TeamCaseOut/properties/method"): (
        "response echo of the request's method; engine's TeamCase.method is str"
    ),
}
"""`(name, location)` pairs allowed to publish a vocabulary without an
enum, each with its reason. An entry that no longer matches an enum-less
occurrence is reported as a problem, so the allowlist cannot go stale."""

_HTTP_METHODS: Final = frozenset(
    {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
)

Leaf = tuple[str, ...] | None
"""One branch's enum after `$ref`/`anyOf`/`oneOf`/`allOf` are resolved.
`None` means that branch accepts values without an enum."""


class VocabularyError(ValueError):
    """The published schema has no single, consistent vocabulary to extract."""


@dataclass(frozen=True)
class Occurrence:
    """One published vocabulary property or parameter. `name` is the
    vocabulary's name, which differs from the property's own name for an
    `ALIASED_PROPERTIES` field."""

    name: str
    location: str
    leaves: tuple[Leaf, ...]

    @property
    def enum_less(self) -> bool:
        return any(leaf is None for leaf in self.leaves)


def _escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _pointer(tokens: Sequence[str]) -> str:
    return "#/" + "/".join(_escape(token) for token in tokens)


def _resolve(node: Any, doc: Mapping[str, Any]) -> Any:
    """Follow a local `$ref` (only `#/...` refs exist in FastAPI's output)."""
    seen: set[str] = set()
    while isinstance(node, Mapping) and isinstance(node.get("$ref"), str):
        ref: str = node["$ref"]
        if ref in seen or not ref.startswith("#/"):
            return {}
        seen.add(ref)
        target: Any = doc
        for token in ref[2:].split("/"):
            token = token.replace("~1", "/").replace("~0", "~")
            target = target.get(token, {}) if isinstance(target, Mapping) else {}
        node = target
    return node


def _leaves(schema: Any, doc: Mapping[str, Any], depth: int = 0) -> tuple[Leaf, ...]:
    schema = _resolve(schema, doc)
    if depth > 32 or not isinstance(schema, Mapping):
        return (None,)
    if isinstance(schema.get("enum"), list):
        return (tuple(str(value) for value in schema["enum"]),)
    if "const" in schema:
        return ((str(schema["const"]),),)
    for key in ("anyOf", "oneOf", "allOf"):
        branches = schema.get(key)
        if isinstance(branches, list):
            leaves: list[Leaf] = []
            for branch in branches:
                resolved = _resolve(branch, doc)
                # `Sport | None` publishes a null branch; it adds no value.
                if isinstance(resolved, Mapping) and dict(resolved) == {"type": "null"}:
                    continue
                leaves.extend(_leaves(resolved, doc, depth + 1))
            return tuple(leaves) or (None,)
    return (None,)


def _parameter_location(tokens: Sequence[str], parameter: Mapping[str, Any]) -> str:
    where = f"{parameter.get('in', '?')} parameter '{parameter.get('name')}'"
    if len(tokens) == 3 and tokens[0] == "paths" and tokens[2] in _HTTP_METHODS:
        return f"{tokens[2].upper()} {tokens[1]} {where}"
    if len(tokens) == 2 and tokens[0] == "paths":
        return f"{tokens[1]} (every operation) {where}"
    return f"{_pointer([*tokens, 'parameters'])} ({where})"


def find_occurrences(openapi: Mapping[str, Any]) -> list[Occurrence]:
    """Every property or parameter named for a vocabulary (or listed in
    `ALIASED_PROPERTIES`), anywhere in the document: component schemas,
    inline request/response schemas, and path- and operation-level
    parameters (`$ref`'d parameters resolved).

    Locations are JSON pointers for properties (e.g.
    `#/components/schemas/ChampionRequest/properties/sport`) and
    `GET /api/years query parameter 'sport'` for operation parameters.
    """
    found: list[Occurrence] = []

    def walk(node: Any, tokens: list[str]) -> None:
        if isinstance(node, Mapping):
            properties = node.get("properties")
            if isinstance(properties, Mapping):
                for prop, name in _PROPERTY_VOCABULARIES.items():
                    if prop in properties:
                        found.append(
                            Occurrence(
                                name,
                                _pointer([*tokens, "properties", prop]),
                                _leaves(properties[prop], openapi),
                            )
                        )
            parameters = node.get("parameters")
            if isinstance(parameters, list):
                for raw in parameters:
                    parameter = _resolve(raw, openapi)
                    if isinstance(parameter, Mapping) and parameter.get("name") in VOCABULARY_NAMES:
                        found.append(
                            Occurrence(
                                str(parameter["name"]),
                                _parameter_location(tokens, parameter),
                                _leaves(parameter.get("schema"), openapi),
                            )
                        )
            for key, child in node.items():
                walk(child, [*tokens, str(key)])
        elif isinstance(node, list):
            for index, child in enumerate(node):
                walk(child, [*tokens, str(index)])

    walk(openapi, [])
    return found


def vocabulary_problems(
    openapi: Mapping[str, Any],
    unconstrained: Mapping[tuple[str, str], str] = UNCONSTRAINED_LOCATIONS,
) -> list[str]:
    """Everything that stops the published schema having one vocabulary per
    name. An empty list means `extract_vocabularies` will succeed.

    `unconstrained` is only overridden by tests that feed a synthetic
    document, where the live app's allowlist entries would be reported stale.
    """
    occurrences = find_occurrences(openapi)
    problems: list[str] = []

    for name, location in unconstrained:
        matches = [o for o in occurrences if (o.name, o.location) == (name, location)]
        if not matches or not all(o.enum_less for o in matches):
            problems.append(
                f"{location}: stale UNCONSTRAINED_LOCATIONS entry for `{name}` -- it is no "
                "longer an enum-less occurrence; delete the entry"
            )

    for name in VOCABULARY_NAMES:
        named = [o for o in occurrences if o.name == name]
        if not named:
            problems.append(f"`{name}` is not published anywhere in the schema")
            continue
        by_enum: dict[tuple[str, ...], list[str]] = {}
        for occurrence in named:
            if occurrence.enum_less:
                if (name, occurrence.location) not in unconstrained:
                    problems.append(
                        f"{occurrence.location}: `{name}` is published with no enum -- "
                        f"annotate it with the contract alias"
                    )
                continue
            distinct = {leaf for leaf in occurrence.leaves if leaf is not None}
            if len(distinct) > 1:
                problems.append(
                    f"{occurrence.location}: `{name}` publishes {len(distinct)} different "
                    f"enums in one schema: {sorted(distinct)!r}"
                )
            for leaf in distinct:
                by_enum.setdefault(leaf, []).append(occurrence.location)
        if len(by_enum) > 1:
            detail = "; ".join(
                f"{list(enum)!r} at {', '.join(locations)}" for enum, locations in by_enum.items()
            )
            problems.append(f"`{name}` is published with disagreeing enums: {detail}")
        elif not by_enum:
            problems.append(f"`{name}` is published, but never with an enum")
    return problems


def extract_vocabularies(
    openapi: Mapping[str, Any],
    unconstrained: Mapping[tuple[str, str], str] = UNCONSTRAINED_LOCATIONS,
) -> dict[str, list[str]]:
    """`{name: published enum}` for each vocabulary name, or `VocabularyError`
    listing every problem `vocabulary_problems` finds."""
    problems = vocabulary_problems(openapi, unconstrained)
    if problems:
        raise VocabularyError("\n".join(problems))
    vocabularies: dict[str, list[str]] = {}
    for occurrence in find_occurrences(openapi):
        if not occurrence.enum_less:
            leaf = occurrence.leaves[0]
            assert leaf is not None
            vocabularies.setdefault(occurrence.name, list(leaf))
    return dict(sorted(vocabularies.items()))


def render(vocabularies: Mapping[str, Sequence[str]]) -> str:
    """The committed file's exact bytes."""
    return (
        json.dumps({k: list(v) for k, v in vocabularies.items()}, indent=2, sort_keys=True) + "\n"
    )


def main() -> int:
    from api.main import app

    try:
        sys.stdout.write(render(extract_vocabularies(app.openapi())))
    except VocabularyError as exc:
        print(f"openapi-vocabularies: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
