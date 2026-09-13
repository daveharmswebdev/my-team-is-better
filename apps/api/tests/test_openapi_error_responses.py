"""`/openapi.json` advertises the mapped engine-error responses, with the
wire shape the handlers really send (issue #111, epic #113).

`api.errors` maps typed engine exceptions to HTTP responses with app-level
exception handlers. Because routes never raise or catch them themselves,
FastAPI cannot see them, so nothing reaches `/openapi.json` unless a route
declares it by hand. Before #111 nothing was declared: a generated client saw
only 200 and the default 422, and had no idea a verdict route can 404 or 400.

**Scope: an "error kind" here means an app-level exception handler.** That is
every entry in `app.exception_handlers` except FastAPI/Starlette's own
defaults. Errors a route produces any other way, such as
`raise HTTPException(409)` or a documented 503, are not derived or required.
A route may still declare such a status in `responses=`, and the checks leave
it alone as long as that status's declared schema accepts none of the engine
handlers' example responses. What stays forbidden is advertising an engine
envelope on a route that cannot reach it.

Each test guards against a different way this goes wrong:

1. **Every route declares the engine error kinds it can reach, and no
   others.** Nothing here lists which routes raise what. The check covers
   every `APIRoute` FastAPI serves, including routes mounted through
   `include_router`. For each one it works out the reachable kinds from code
   (see "How the derivation works" below). Each handler is then run on an
   example exception. A reachable kind's real response must validate against
   the route's advertised schema at the status the handler returned. An
   unreachable kind's response must not be accepted there. Any other
   declared error status must not accept any engine example response. Any
   declared 422 must include FastAPI's `HTTPValidationError`, because
   declaring a 422 replaces FastAPI's default one. So a route that calls
   `build_team_case` without `responses=`, or declares the wrong set, turns
   this red.

   **How the derivation works.** It starts from the endpoint and each
   FastAPI dependency callable (following `Dependant.dependencies`), each
   passed through `inspect.unwrap`. For each function, it reads the names
   its code references (`co_names`, plus those of nested code objects such
   as comprehensions and lambdas) and looks each one up in that function's
   `__globals__`:

   * an exception class that is a subclass of a handled kind counts as
     reachable;
   * a plain function (`types.FunctionType`) whose `__module__` is in
     `api.*` or `cfb_strength.*` is recursed into, by the same rules;
   * a module or non-exception class from those packages is also tried as
     the owner of an attribute. Each other name in the SAME code object's
     `co_names` is looked up on it (`getattr` for a module,
     `inspect.getattr_static` for a class, with classmethod/staticmethod
     unwrapped). The result counts only if it is itself a handled exception
     class or an own-package `FunctionType`. A module or class reached
     through an attribute is not explored further, and a class's `__init__`
     or `__call__` is never followed.

   So `proof.build_team_case(...)` and `TeamCaseOut.from_dataclass(...)`
   are followed, and so is a module-level helper function that calls the
   engine.

   **Known limits.** It follows names, not execution. It does NOT see:

   * a service injected via `Depends` and called as a method
     (`svc: Svc = Depends(get_svc); svc.run()`), which is the same shape as
     today's `Narrator` dependency;
   * a method called on a module-level instance;
   * a constructor whose `__init__` calls the engine;
   * a module-level `functools.partial`;
   * a closure, or a decorator that does not set `__wrapped__`;
   * dotted access such as `cfb_strength.evidence.proof.build_team_case(...)`;
   * a class used as a dependency (`Depends(SomeClass)`);
   * callables passed in as arguments, `getattr` with computed names, and
     third-party code calling back into ours.

   It also over-approximates: a referenced exception counts even if it is
   only caught. So a route that catches an engine exception must still
   advertise it. There is no suppression hook yet. Both the limits above and
   this gap are tracked in #135.

   A backstop covers the verdict router only. `test_error_derivation_is_not_vacuous`
   requires every `/api/verdict/*` operation to be derived as raising, unless
   it is listed in `NON_RAISING_VERDICT_ROUTES`. A verdict route that reaches
   the engine by a path the walk misses therefore still fails there. A route
   outside `/api/verdict/` that does so is not caught.
2. **Does the advertised schema match the wire?** Each error is triggered
   for real through the HTTP stack, against the committed fixture db, and the
   JSON that comes back is validated with `jsonschema` against the schema
   `/openapi.json` publishes for that route and status. `$ref`s are resolved
   against `components/schemas`. So declaring the bare `*ErrorBody` instead
   of its `{"detail": ...}` envelope fails here. The exact envelope
   components on today's three verdict routes are also pinned by name.
3. **Is every handler declared somewhere?** The handler set is read from
   `app.exception_handlers`, not a list here. Each handler is run on an
   example exception, and some route's declared schema must accept its real
   response. A handler with no example here fails. This check is
   shape-based: a new exception that reuses an existing envelope passes as
   soon as its example exists. Check 1 is what ties each kind to the routes
   that can actually raise it.
4. **The `HTTPValidationError` stand-in publishes FastAPI's schema.** In the
   real app FastAPI overwrites that component with its own dict, because
   `/api/years` and `/api/teams` still use the default 422. So checks 1-3
   never see the stand-in's output. An app with only the verdict router has
   no default 422 anywhere, so it publishes the stand-in, and that output is
   compared against FastAPI's definitions.
"""

from __future__ import annotations

import inspect
import json
import types
from collections.abc import Awaitable, Callable, Collection, Iterator
from typing import Any

import pytest
from cfb_strength.contracts import (
    AmbiguousTeamError,
    SameTeamComparisonError,
    UnknownTeamError,
    UnknownYearError,
)
from fastapi import FastAPI, routing
from fastapi.dependencies.models import Dependant
from fastapi.exceptions import RequestValidationError, WebSocketRequestValidationError
from fastapi.openapi.utils import (
    validation_error_definition,
    validation_error_response_definition,
)
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

# Every component that describes one of today's engine errors, envelope or
# bare body. Used only by the by-name pin on today's verdict routes (check 2).
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

# Exact envelope components pinned on today's three verdict routes (check 2).
# Hand-verified against the raise sites in `cfb_strength.evidence.proof`:
# `resolve_team` runs `_require_year` (unknown_year), then raises
# ambiguous_team or unknown_team. `build_team_case` goes through
# `resolve_team`, and `build_comparison` goes through it and can also raise
# same_team_comparison.
_TEAM_CASE_COMPONENTS: dict[str, frozenset[str]] = {
    "404": frozenset({UNKNOWN_YEAR, UNKNOWN_TEAM}),
    "422": frozenset({HTTP_VALIDATION, AMBIGUOUS_TEAM}),
}
VERDICT_ROUTE_COMPONENTS: dict[tuple[str, str], dict[str, frozenset[str]]] = {
    ("/api/verdict/champion", "post"): _TEAM_CASE_COMPONENTS,
    ("/api/verdict/team-case", "post"): _TEAM_CASE_COMPONENTS,
    ("/api/verdict/compare", "post"): {
        **_TEAM_CASE_COMPONENTS,
        "400": frozenset({SAME_TEAM}),
    },
}

# The same facts expressed as exception kinds. This is the derivation's
# floor, not its source: every route in the app is checked by derivation,
# and this only proves the derivation gets today's routes right.
_TEAM_CASE_KINDS: frozenset[type[BaseException]] = frozenset(
    {UnknownYearError, UnknownTeamError, AmbiguousTeamError}
)
KNOWN_ROUTE_KINDS: dict[tuple[str, str], frozenset[type[BaseException]]] = {
    ("/api/verdict/champion", "post"): _TEAM_CASE_KINDS,
    ("/api/verdict/team-case", "post"): _TEAM_CASE_KINDS,
    ("/api/verdict/compare", "post"): _TEAM_CASE_KINDS | {SameTeamComparisonError},
    ("/api/years", "get"): frozenset(),
    ("/api/teams", "get"): frozenset(),
    ("/api/credits", "get"): frozenset(),
    ("/health", "get"): frozenset(),
}

VERDICT_PREFIX = "/api/verdict/"

# Deliberate rule (the verdict-router backstop in the module docstring): every
# /api/verdict/* operation must be derived as reaching the engine. A verdict
# route that genuinely raises no engine error goes here, as (path, method),
# with a comment saying why. Keep this list reviewed: an entry here switches
# the backstop off for that route.
NON_RAISING_VERDICT_ROUTES: frozenset[tuple[str, str]] = frozenset()

# FastAPI/Starlette register these on every app. They are not engine errors,
# and errors produced without an app-level handler are out of scope
# (module docstring).
FRAMEWORK_DEFAULT_HANDLERS: frozenset[Any] = frozenset(
    {StarletteHTTPException, RequestValidationError, WebSocketRequestValidationError}
)

# One example per handled exception, so its handler can be run directly. A
# handler with no entry here fails on purpose: add the example AND declare the
# response on the routes that can raise it.
EXAMPLE_EXCEPTIONS: dict[type[BaseException], BaseException] = {
    UnknownYearError: UnknownYearError(1999, [2001, 2005, 2013]),
    UnknownTeamError: UnknownTeamError("Zzyzx Polytechnic", 2005, "cfb"),
    AmbiguousTeamError: AmbiguousTeamError("State", ["Ohio State", "Penn State"]),
    SameTeamComparisonError: SameTeamComparisonError("Texas"),
}

# Only code in these top-level packages is followed by the derivation.
OWN_PACKAGES = frozenset({"api", "cfb_strength"})


# ---------------------------------------------------------------------------
# helpers: schema
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


def _top_level_refs(schema: dict[str, Any]) -> set[str]:
    """Like `_union_members`, but tolerant of schemas that are not a union of
    `$ref`s (e.g. a route's own inline error schema): non-`$ref` members are
    ignored."""
    members = [schema] if "$ref" in schema else schema.get("anyOf", schema.get("oneOf", []))
    return {
        _ref_name(member["$ref"])
        for member in members
        if isinstance(member, dict) and isinstance(member.get("$ref"), str)
    }


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


def _accepts(openapi: dict[str, Any], responses: dict[str, Any], status: str, body: Any) -> bool:
    response = responses.get(status)
    if response is None or "application/json" not in response.get("content", {}):
        return False
    return _validator(openapi, _json_schema(response)).is_valid(body)


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
# helpers: handlers
# ---------------------------------------------------------------------------

_Handler = Callable[[Request, Any], Response | Awaitable[Response]]


def _engine_error_handlers(app: FastAPI) -> dict[Any, _Handler]:
    return {
        key: handler
        for key, handler in app.exception_handlers.items()
        if key not in FRAMEWORK_DEFAULT_HANDLERS
    }


def _handled_exception_types(app: FastAPI) -> list[type[BaseException]]:
    return [
        key
        for key in _engine_error_handlers(app)
        if isinstance(key, type) and issubclass(key, BaseException)
    ]


def _run_handler(handler: _Handler, exc: BaseException) -> Response:
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    result = handler(request, exc)
    assert isinstance(result, Response), (
        f"{handler!r} is async; extend this test to await it before relying on it"
    )
    return result


def _example_response(app: FastAPI, kind: type[BaseException]) -> tuple[str, Any]:
    response = _run_handler(app.exception_handlers[kind], EXAMPLE_EXCEPTIONS[kind])
    return str(response.status_code), json.loads(bytes(response.body))


# ---------------------------------------------------------------------------
# helpers: deriving which error kinds a route can reach (module docstring, 1)
# ---------------------------------------------------------------------------


def _is_own(obj: object) -> bool:
    module = obj.__name__ if isinstance(obj, types.ModuleType) else getattr(obj, "__module__", None)
    return isinstance(module, str) and module.split(".")[0] in OWN_PACKAGES


def _code_names(code: types.CodeType) -> Iterator[str]:
    yield from code.co_names
    for const in code.co_consts:
        if isinstance(const, types.CodeType):
            yield from _code_names(const)


def _referenced_objects(fn: types.FunctionType) -> Iterator[object]:
    names = list(_code_names(fn.__code__))
    for name in names:
        obj = fn.__globals__.get(name)
        if obj is None:
            continue
        yield obj
        # `proof.build_team_case(...)` / `TeamCaseOut.from_dataclass(...)`:
        # the attribute name is in the same co_names, so try each of those
        # names as an attribute of our own modules and (non-exception)
        # classes. One level only (module docstring, "How the derivation works").
        is_exception = isinstance(obj, type) and issubclass(obj, BaseException)
        if _is_own(obj) and not is_exception and isinstance(obj, types.ModuleType | type):
            for attr in names:
                if isinstance(obj, types.ModuleType):
                    value = getattr(obj, attr, None)
                else:
                    value = inspect.getattr_static(obj, attr, None)
                if isinstance(value, classmethod | staticmethod):
                    value = value.__func__
                if value is not None:
                    yield value


def _reachable_error_kinds(
    fn: Callable[..., Any],
    handled: Collection[type[BaseException]],
    _seen: set[types.CodeType] | None = None,
    _trail: tuple[str, ...] = (),
) -> dict[type[BaseException], str]:
    """Handled exception kind -> the call trail it was found through."""
    seen = set() if _seen is None else _seen
    fn = inspect.unwrap(fn)
    if not isinstance(fn, types.FunctionType) or fn.__code__ in seen:
        return {}
    seen.add(fn.__code__)
    trail = (*_trail, fn.__qualname__)
    found: dict[type[BaseException], str] = {}
    for obj in _referenced_objects(fn):
        if isinstance(obj, type) and issubclass(obj, BaseException):
            for kind in handled:
                if issubclass(obj, kind):
                    found.setdefault(kind, " > ".join(trail))
        elif isinstance(obj, types.FunctionType) and _is_own(obj):
            for kind, via in _reachable_error_kinds(obj, handled, seen, trail).items():
                found.setdefault(kind, via)
    return found


def _dependency_calls(dependant: Dependant) -> Iterator[Callable[..., Any]]:
    for dependency in dependant.dependencies:
        if dependency.call is not None:
            yield dependency.call
        yield from _dependency_calls(dependency)


def _routes(app: FastAPI) -> Iterator[tuple[str, str, routing.APIRoute]]:
    """Every (path, method, route) FastAPI serves, including routes mounted
    through `include_router`, found the same way `get_openapi` finds them."""
    for context in routing.iter_route_contexts(app.routes):
        route = context.original_route
        if isinstance(route, routing.APIRoute):
            assert context.path_format is not None
            for method in sorted(context.methods or ()):
                yield context.path_format, method.lower(), route


def _route_error_kinds(
    route: routing.APIRoute, handled: Collection[type[BaseException]]
) -> dict[type[BaseException], str]:
    seen: set[types.CodeType] = set()
    found = _reachable_error_kinds(route.endpoint, handled, seen)
    for call in _dependency_calls(route.dependant):
        for kind, via in _reachable_error_kinds(call, handled, seen, ("dependency",)).items():
            found.setdefault(kind, via)
    return found


# ---------------------------------------------------------------------------
# 1. every route declares exactly the error kinds it can reach
# ---------------------------------------------------------------------------


def test_error_derivation_is_not_vacuous() -> None:
    """The derivation reproduces today's hand-verified route matrix, and
    every `/api/verdict/*` operation is derived as raising unless it is in
    `NON_RAISING_VERDICT_ROUTES` (the verdict-router backstop in the module
    docstring). Routes outside `/api/verdict/` are not part of the backstop."""
    app = _app()
    handled = _handled_exception_types(app)
    derived = {
        (path, method): frozenset(_route_error_kinds(route, handled))
        for path, method, route in _routes(app)
    }

    for route_key, expected in KNOWN_ROUTE_KINDS.items():
        assert route_key in derived, f"{route_key} is no longer served"
        assert derived[route_key] == expected, (
            f"{route_key}: derived {sorted(k.__name__ for k in derived[route_key])}, "
            f"expected {sorted(k.__name__ for k in expected)}"
        )

    verdict_operations = {key for key in derived if key[0].startswith(VERDICT_PREFIX)}
    stale = NON_RAISING_VERDICT_ROUTES - verdict_operations
    assert not stale, f"NON_RAISING_VERDICT_ROUTES lists routes that are not served: {stale}"

    raising_verdict_operations = {key for key in verdict_operations if derived[key]}
    unexplained = sorted(
        verdict_operations - raising_verdict_operations - NON_RAISING_VERDICT_ROUTES
    )
    assert not unexplained, (
        f"These {VERDICT_PREFIX}* operations are derived as reaching no engine error: "
        f"{unexplained}. Every verdict route is expected to reach the engine, and this "
        "check is the backstop for call paths the derivation cannot follow (module "
        "docstring, 'Known limits'). Usually it means the route calls the engine by "
        "such a path, and its responses= is going unchecked by "
        "test_every_route_advertises_exactly_the_engine_errors_it_can_raise. In that "
        "case declare the matching set from api.errors and add RUNTIME_CASES entries "
        "that trigger each error for real. If the route genuinely raises no engine "
        "error, add it to NON_RAISING_VERDICT_ROUTES with a comment saying why."
    )


def test_every_route_advertises_exactly_the_engine_errors_it_can_raise() -> None:
    app = _app()
    openapi = _openapi()
    handled = _handled_exception_types(app)
    problems = [
        f"handler for {kind.__name__} has no example in EXAMPLE_EXCEPTIONS; add one, "
        "and declare its response on every route that can raise it"
        for kind in handled
        if kind not in EXAMPLE_EXCEPTIONS
    ]
    examples = {
        kind: _example_response(app, kind) for kind in handled if kind in EXAMPLE_EXCEPTIONS
    }

    checked = 0
    for path, method, route in _routes(app):
        operation = openapi["paths"].get(path, {}).get(method)
        if operation is None:  # include_in_schema=False: nothing to advertise
            continue
        checked += 1
        label = f"{method.upper()} {path}"
        responses = operation["responses"]
        reachable = _route_error_kinds(route, handled)
        reachable_statuses: set[str] = set()

        for kind, (status, body) in examples.items():
            accepted = _accepts(openapi, responses, status, body)
            if kind in reachable:
                reachable_statuses.add(status)
                if not accepted:
                    problems.append(
                        f"{label} can raise {kind.__name__} (via {reachable[kind]}), whose "
                        f"handler returns {status} {body}, but it advertises no {status} "
                        "schema that accepts it -- add it to the route's responses="
                    )
            elif accepted:
                problems.append(
                    f"{label} advertises {kind.__name__} at {status}, but nothing it "
                    "calls can raise it"
                )

        # Any other declared error status (e.g. a route's own HTTPException
        # 409, or a documented 503) is out of scope and allowed, as long as
        # its schema accepts no engine example response (module docstring).
        for status in sorted(responses):
            if status.startswith("2") or status in reachable_statuses:
                continue
            engine_bodies = sorted(
                kind.__name__
                for kind, (_, body) in examples.items()
                if _accepts(openapi, responses, status, body)
            )
            if engine_bodies:
                problems.append(
                    f"{label} advertises {status} with a schema that accepts engine error "
                    f"responses {engine_bodies}, but no engine error it can reach returns {status}"
                )

        response_422 = responses.get("422")
        if (
            response_422 is not None
            and "application/json" in response_422.get("content", {})
            and HTTP_VALIDATION not in _top_level_refs(_json_schema(response_422))
        ):
            problems.append(
                f"{label} declares a 422 without {HTTP_VALIDATION}, which drops FastAPI's "
                "request-validation error from its docs"
            )

    assert checked >= len(KNOWN_ROUTE_KINDS)
    assert not problems, "\n".join(problems)


# ---------------------------------------------------------------------------
# 2. runtime conformance: real responses validate against what is advertised
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "route", sorted(VERDICT_ROUTE_COMPONENTS), ids=lambda r: f"{r[1].upper()} {r[0]}"
)
def test_verdict_route_advertises_exactly_its_envelope_components(
    route: tuple[str, str],
) -> None:
    """Pins the engine statuses by component name. Other error statuses a
    route documents for itself are allowed, but must not reference any
    engine-error component."""
    path, method = route
    openapi = _openapi()
    responses = openapi["paths"][path][method]["responses"]
    expected = VERDICT_ROUTE_COMPONENTS[route]

    error_statuses = {status for status in responses if not status.startswith("2")}
    assert set(expected) <= error_statuses, (
        f"{method.upper()} {path}: advertises {sorted(error_statuses)}, "
        f"missing {sorted(set(expected) - error_statuses)}"
    )

    for status, expected_members in expected.items():
        members = _union_members(_json_schema(responses[status]))
        assert sorted(members) == sorted(expected_members), (
            f"{method.upper()} {path} {status}: advertised {members}, "
            f"expected {sorted(expected_members)}"
        )
        for name in members:
            assert name in openapi["components"]["schemas"], f"dangling $ref to {name}"

    for status in sorted(error_statuses - set(expected)):
        leaked = _all_refs(responses[status]) & ENGINE_ERROR_COMPONENTS
        assert not leaked, f"{method.upper()} {path} {status} references engine errors: {leaked}"


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
# 3. every registered engine-error handler is declared somewhere
# ---------------------------------------------------------------------------


def test_every_engine_error_handler_is_declared_on_some_route() -> None:
    """Shape-based (module docstring, 3): some route's declared schema must
    accept the handler's real response. It does not tie the kind to the
    routes that raise it. `test_every_route_advertises_exactly_the_engine_errors_it_can_raise`
    does that."""
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
            if _accepts(openapi, operation["responses"], status, body)
        ]
        if not declared_on:
            problems.append(
                f"handler for {key.__name__} returns {status} {body}, and no route "
                "declares a response schema that accepts it"
            )

    assert not problems, "\n".join(problems)


# ---------------------------------------------------------------------------
# 4. the HTTPValidationError stand-in publishes FastAPI's own schema
# ---------------------------------------------------------------------------


def test_validation_error_stand_ins_publish_fastapis_own_schema() -> None:
    """`api.errors.HTTPValidationError`/`ValidationError` exist so a declared
    422 can list request-validation errors. In the real app FastAPI
    overwrites both components with its own dicts, because some routes still
    use the default 422, so `/openapi.json` never shows the stand-ins'
    output. An app with only the verdict router has no default 422, so what
    it publishes IS the stand-ins' output. Operations with no 422 at all
    (no parameters) are fine: FastAPI only overwrites for a default 422."""
    from api.verdict import router

    verdict_only = FastAPI()
    verdict_only.include_router(router)
    openapi = verdict_only.openapi()

    # Precondition, or this test proves nothing: no operation kept FastAPI's
    # default 422 (a lone $ref), and at least one declares a 422 union.
    declared_422 = []
    for path, method, operation in _operations(openapi):
        response_422 = operation["responses"].get("422")
        if response_422 is None:
            continue
        members = _top_level_refs(_json_schema(response_422))
        assert len(members) > 1, (
            f"{method.upper()} {path} kept FastAPI's default 422 (advertised {sorted(members)}). "
            "FastAPI then overwrites the stand-in components with its own, so this test "
            "would compare FastAPI against itself. Declare the route's 422 with one of "
            "api.errors' prebuilt responses."
        )
        declared_422.append(f"{method.upper()} {path}")
    assert declared_422, (
        "no verdict route declares a 422, so the stand-ins are never published and "
        "this test has nothing to check"
    )

    schemas = openapi["components"]["schemas"]
    assert schemas.get(HTTP_VALIDATION) == validation_error_response_definition
    assert schemas.get("ValidationError") == validation_error_definition
