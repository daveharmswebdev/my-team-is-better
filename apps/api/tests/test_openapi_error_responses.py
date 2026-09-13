"""`/openapi.json` advertises the mapped engine-error responses, with the
wire shape the handlers really send (issue #111, epic #113).

`api.errors` maps four typed engine exceptions to HTTP responses at the app
level. Because routes never raise or catch them themselves, FastAPI cannot
see them, so nothing reached `/openapi.json` unless it was declared by hand.
Before #111 nothing was declared: a generated client saw only 200 and the
default 422, and had no idea that a verdict route can 404 or 400.

Each test here guards against a different way this goes wrong:

1. **What is advertised.** Each verdict route lists exactly the envelopes its
   engine call can raise. The 404 is a *union* (two different bodies share
   it). The 422 advertises BOTH FastAPI's `HTTPValidationError` and
   `ambiguous_team`, because declaring a 422 replaces FastAPI's default one
   and would otherwise quietly drop request-validation errors from the docs.
   Routes that raise none of the four advertise none of the four.
2. **Does the advertised schema match the wire (the non-vacuous part)?**
   Each error is triggered for real through the HTTP stack, against the
   committed fixture db, and the JSON that comes back is validated with
   `jsonschema` against the schema `/openapi.json` publishes for that route
   and status, with `$ref`s resolved against `components/schemas`. So
   declaring the bare `*ErrorBody` instead of its `{"detail": ...}` envelope
   fails here even though the component name "looks right".
3. **Does a new handler get declared?** The set of handlers is read from
   `app.exception_handlers`, not from a list in this file. Every
   non-framework handler is called on an example exception, and its real
   response has to validate against the declared schema of at least one
   route at the status it actually returned. A fifth handler that nobody
   declared, or that has no example below, turns this red.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Iterator
from typing import Any

import pytest
from cfb_strength.contracts import (
    AmbiguousTeamError,
    SameTeamComparisonError,
    UnknownTeamError,
    UnknownYearError,
)
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError, WebSocketRequestValidationError
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import Response

UNKNOWN_YEAR = "UnknownYearErrorResponse"
UNKNOWN_TEAM = "UnknownTeamErrorResponse"
AMBIGUOUS_TEAM = "AmbiguousTeamErrorResponse"
SAME_TEAM = "SameTeamComparisonErrorResponse"
HTTP_VALIDATION = "HTTPValidationError"

# Every component that describes one of the four engine errors, envelope or
# bare body. Routes that cannot raise them must not reference any of these.
ENGINE_ERROR_COMPONENTS = frozenset(
    {
        UNKNOWN_YEAR,
        UNKNOWN_TEAM,
        AMBIGUOUS_TEAM,
        SAME_TEAM,
        "UnknownYearErrorBody",
        "UnknownTeamErrorBody",
        "AmbiguousTeamErrorBody",
        "SameTeamComparisonErrorBody",
    }
)

# Route -> status -> the exact set of schemas its response is a union of.
# Taken from the raise sites in `cfb_strength.evidence.proof`:
# `resolve_team` runs `_require_year` (unknown_year), then raises
# ambiguous_team or unknown_team. `build_team_case` goes through
# `resolve_team`, and `build_comparison` goes through it and can also raise
# same_team_comparison.
_TEAM_CASE_ERRORS: dict[str, frozenset[str]] = {
    "404": frozenset({UNKNOWN_YEAR, UNKNOWN_TEAM}),
    "422": frozenset({HTTP_VALIDATION, AMBIGUOUS_TEAM}),
}
EXPECTED_ERROR_RESPONSES: dict[tuple[str, str], dict[str, frozenset[str]]] = {
    ("/api/verdict/champion", "post"): _TEAM_CASE_ERRORS,
    ("/api/verdict/team-case", "post"): _TEAM_CASE_ERRORS,
    ("/api/verdict/compare", "post"): {
        **_TEAM_CASE_ERRORS,
        "400": frozenset({SAME_TEAM}),
    },
}

# FastAPI/Starlette register these on every app. They are not engine errors.
FRAMEWORK_DEFAULT_HANDLERS: frozenset[Any] = frozenset(
    {StarletteHTTPException, RequestValidationError, WebSocketRequestValidationError}
)

# One example per engine exception, so its handler can be run directly. A
# handler with no entry here fails the completeness test on purpose: add the
# example AND declare the response on the routes that can raise it.
EXAMPLE_EXCEPTIONS: dict[type[BaseException], BaseException] = {
    UnknownYearError: UnknownYearError(1999, [2001, 2005, 2013]),
    UnknownTeamError: UnknownTeamError("Zzyzx Polytechnic", 2005, "cfb"),
    AmbiguousTeamError: AmbiguousTeamError("State", ["Ohio State", "Penn State"]),
    SameTeamComparisonError: SameTeamComparisonError("Texas"),
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _app() -> FastAPI:
    from api.main import app

    return app


def _openapi() -> dict[str, Any]:
    return _app().openapi()


def _operations(openapi: dict[str, Any]) -> Iterator[tuple[str, str, dict[str, Any]]]:
    for path, item in openapi["paths"].items():
        for method, operation in item.items():
            yield path, method, operation


def _json_schema(response: dict[str, Any]) -> dict[str, Any]:
    schema: dict[str, Any] = response["content"]["application/json"]["schema"]
    return schema


def _ref_name(ref: str) -> str:
    prefix = "#/components/schemas/"
    assert ref.startswith(prefix), f"unexpected $ref {ref!r}"
    return ref[len(prefix) :]


def _union_members(schema: dict[str, Any]) -> list[str]:
    """The component names a response schema is a union of: one `$ref`,
    or an `anyOf`/`oneOf` in which every member is a `$ref`."""
    if "$ref" in schema:
        return [_ref_name(schema["$ref"])]
    members = schema.get("anyOf", schema.get("oneOf"))
    assert members is not None, f"expected a $ref or a union of $refs, got {schema!r}"
    names = []
    for member in members:
        assert "$ref" in member, f"union member is not a $ref: {member!r}"
        names.append(_ref_name(member["$ref"]))
    return names


def _all_refs(node: Any) -> set[str]:
    if isinstance(node, dict):
        found = {_ref_name(node["$ref"])} if isinstance(node.get("$ref"), str) else set()
        for value in node.values():
            found |= _all_refs(value)
        return found
    if isinstance(node, list):
        return set().union(*(_all_refs(item) for item in node)) if node else set()
    return set()


def _validator(openapi: dict[str, Any], schema: dict[str, Any]) -> Draft202012Validator:
    """OpenAPI 3.1 schemas are JSON Schema 2020-12. The components are put on
    the root document, so `#/components/schemas/...` refs resolve exactly as
    they do in `/openapi.json`, and an unresolvable ref raises, not passes."""
    root = {**schema, "components": openapi["components"]}
    Draft202012Validator.check_schema(root)
    return Draft202012Validator(root)


def _advertised_schema(
    openapi: dict[str, Any], path: str, method: str, status: str
) -> dict[str, Any]:
    responses = openapi["paths"][path][method]["responses"]
    assert status in responses, (
        f"{method.upper()} {path} returns {status} at runtime but /openapi.json does "
        f"not advertise it (advertised: {sorted(responses)})"
    )
    return _json_schema(responses[status])


# ---------------------------------------------------------------------------
# 1. what is advertised, per route and status
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "route", sorted(EXPECTED_ERROR_RESPONSES), ids=lambda r: f"{r[1].upper()} {r[0]}"
)
def test_verdict_route_advertises_exactly_its_engine_errors(route: tuple[str, str]) -> None:
    path, method = route
    openapi = _openapi()
    responses = openapi["paths"][path][method]["responses"]
    expected = EXPECTED_ERROR_RESPONSES[route]

    error_statuses = {status for status in responses if not status.startswith("2")}
    assert error_statuses == set(expected)

    for status, expected_members in expected.items():
        members = _union_members(_json_schema(responses[status]))
        assert sorted(members) == sorted(expected_members), (
            f"{method.upper()} {path} {status}: advertised {members}, "
            f"expected {sorted(expected_members)}"
        )
        for name in members:
            assert name in openapi["components"]["schemas"], f"dangling $ref to {name}"


def test_routes_that_cannot_raise_engine_errors_advertise_none() -> None:
    """Every other operation, found from the schema rather than listed here
    (today: /api/years, /api/teams, /api/credits and /health), advertises no
    400/404 and references none of the engine-error components. Where it
    has a 422, that 422 is FastAPI's request-validation error and nothing
    else."""
    openapi = _openapi()
    others = [
        (path, method, operation)
        for path, method, operation in _operations(openapi)
        if (path, method) not in EXPECTED_ERROR_RESPONSES
    ]
    paths = {path for path, _, _ in others}
    assert {"/api/years", "/api/teams", "/api/credits", "/health"} <= paths

    for path, method, operation in others:
        responses = operation["responses"]
        assert set(responses) <= {"200", "422"}, f"{method.upper()} {path}: {sorted(responses)}"
        leaked = _all_refs(responses) & ENGINE_ERROR_COMPONENTS
        assert not leaked, f"{method.upper()} {path} advertises engine errors: {leaked}"
        if "422" in responses:
            assert _union_members(_json_schema(responses["422"])) == [HTTP_VALIDATION]


# ---------------------------------------------------------------------------
# 2. runtime conformance: real responses validate against what is advertised
# ---------------------------------------------------------------------------

RUNTIME_CASES: list[tuple[str, dict[str, object], int, str | None]] = [
    ("/api/verdict/champion", {"year": 1999}, 404, "unknown_year"),
    ("/api/verdict/team-case", {"year": 1999, "team": "Texas"}, 404, "unknown_year"),
    (
        "/api/verdict/compare",
        {"year": 1999, "team_a": "Texas", "team_b": "USC"},
        404,
        "unknown_year",
    ),
    ("/api/verdict/team-case", {"year": 2005, "team": "Gonzaga"}, 404, "unknown_team"),
    (
        "/api/verdict/compare",
        {"year": 2005, "team_a": "Zzyzx Polytechnic", "team_b": "Texas"},
        404,
        "unknown_team",
    ),
    ("/api/verdict/team-case", {"year": 2005, "team": "State"}, 422, "ambiguous_team"),
    (
        "/api/verdict/compare",
        {"year": 2005, "team_a": "State", "team_b": "Texas"},
        422,
        "ambiguous_team",
    ),
    (
        "/api/verdict/compare",
        {"year": 2005, "team_a": "Texas", "team_b": "Texas"},
        400,
        "same_team_comparison",
    ),
    # Real request-validation 422s (an unregistered method, #104) must still
    # validate against the same 422 schema that now also carries
    # ambiguous_team. `None` means "FastAPI's own validation body".
    ("/api/verdict/champion", {"year": 2005, "method": "nope"}, 422, None),
    ("/api/verdict/team-case", {"year": 2005, "team": "Texas", "method": "nope"}, 422, None),
    (
        "/api/verdict/compare",
        {"year": 2005, "team_a": "Texas", "team_b": "USC", "method": "nope"},
        422,
        None,
    ),
]


@pytest.mark.parametrize(
    "path,payload,status,error",
    RUNTIME_CASES,
    ids=[f"{p.rsplit('/', 1)[-1]}-{s}-{e or 'request_validation'}" for p, _, s, e in RUNTIME_CASES],
)
def test_real_error_response_validates_against_advertised_schema(
    client: TestClient,
    path: str,
    payload: dict[str, object],
    status: int,
    error: str | None,
) -> None:
    response = client.post(path, json=payload)

    # First make sure the trigger really produced the error this case is
    # about. Otherwise a schema check that passes proves nothing.
    assert response.status_code == status, response.text
    body = response.json()
    if error is None:
        assert isinstance(body["detail"], list) and body["detail"], body
    else:
        assert body["detail"]["error"] == error, body

    openapi = _openapi()
    schema = _advertised_schema(openapi, path, "post", str(status))
    errors = sorted(_validator(openapi, schema).iter_errors(body), key=str)
    assert not errors, (
        f"POST {path} {status}: the real response does not match the advertised schema\n"
        f"body: {body}\nschema: {schema}\nerrors: {[e.message for e in errors]}"
    )

    # And the union is informative: exactly one member accepts this body.
    accepting = [
        name
        for name in _union_members(schema)
        if _validator(openapi, {"$ref": f"#/components/schemas/{name}"}).is_valid(body)
    ]
    assert len(accepting) == 1, f"POST {path} {status}: members accepting body: {accepting}"


# ---------------------------------------------------------------------------
# 3. completeness: every registered engine-error handler is declared somewhere
# ---------------------------------------------------------------------------

_Handler = Callable[[Request, Any], Response | Awaitable[Response]]


def _engine_error_handlers(app: FastAPI) -> dict[Any, _Handler]:
    return {
        key: handler
        for key, handler in app.exception_handlers.items()
        if key not in FRAMEWORK_DEFAULT_HANDLERS
    }


def _run_handler(handler: _Handler, exc: BaseException) -> Response:
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    result = handler(request, exc)
    assert isinstance(result, Response), (
        f"{handler!r} is async; extend this test to await it before relying on it"
    )
    return result


def test_every_engine_error_handler_is_declared_on_some_route() -> None:
    app = _app()
    handlers = _engine_error_handlers(app)
    # A floor, not the source of truth: if this set ever came back empty the
    # loop below would pass vacuously.
    assert set(EXAMPLE_EXCEPTIONS) <= set(handlers)

    openapi = _openapi()
    problems: list[str] = []
    for key, handler in handlers.items():
        example = EXAMPLE_EXCEPTIONS.get(key)
        if example is None:
            problems.append(
                f"handler for {key!r} has no example in EXAMPLE_EXCEPTIONS, so nothing "
                "proves its response is declared in /openapi.json. Add one, and declare "
                "its response on every route that can raise it."
            )
            continue
        response = _run_handler(handler, example)
        status = str(response.status_code)
        body = json.loads(bytes(response.body))
        declared_on = [
            f"{method.upper()} {path}"
            for path, method, operation in _operations(openapi)
            if status in operation["responses"]
            and "content" in operation["responses"][status]
            and _validator(openapi, _json_schema(operation["responses"][status])).is_valid(body)
        ]
        if not declared_on:
            problems.append(
                f"handler for {key.__name__} returns {status} {body}, and no route "
                "declares a response schema that accepts it"
            )

    assert not problems, "\n".join(problems)
