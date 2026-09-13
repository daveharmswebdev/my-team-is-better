"""Maps `cfb_strength.contracts`' typed engine exceptions to HTTP responses
(Architecture Brief §4.4 -- the HTTP-response half only; in-character
persona copy for these is issue #4's job, not this one's).

| Engine exception          | HTTP behavior                                 |
|----------------------------|-----------------------------------------------|
| `UnknownYearError`         | 404, body includes `available_years`          |
| `UnknownTeamError`         | 404, body echoes `query`/`year`/`sport`       |
| `AmbiguousTeamError`       | 422, body includes `candidates` (never empty) |
| `SameTeamComparisonError`  | 400                                           |

Registered once on the app (`api.main`) rather than caught per-route, so
there is exactly one place this mapping is spelled out:
`ENGINE_ERROR_RESPONSES` below. The handlers take their status codes from it,
and so do the `/openapi.json` declarations.

Why declarations are needed at all (issue #111): routes never raise or catch
these exceptions themselves, so FastAPI cannot see them. Unless a route
declares them in `responses=`, `/openapi.json` shows only 200 and the default
422. `openapi_error_responses` builds those declarations from the table, and
`api.verdict`'s routes use the two prebuilt sets below. Two FastAPI details it
handles, both easy to get wrong:

* Several errors can share a status (404 is `unknown_year` OR
  `unknown_team`), so each status is declared as a union of envelopes.
* A route that declares its own 422 LOSES FastAPI's default 422
  (`HTTPValidationError`), which is what documents request-validation
  failures like an unregistered `method` (#104). So any 422 declared here
  always includes `HTTPValidationError` alongside `ambiguous_team`.

tests/test_openapi_error_responses.py checks all of this against real
responses. It also fails if a handler is registered here that no route
declares.

`UnknownTeamError` is 404 and not 422 on purpose (issue #100): it is the
same "you asked about a thing we have no data for" case as
`UnknownYearError`, not a "your input was one of several things" case. 422
stays reserved for `ambiguous_team`, whose `candidates` is always non-empty
-- before #100 the engine raised `AmbiguousTeamError` with an empty
candidate list for a zero-match query, so a genuine not-found reached the
client as a 422 "did you mean:" prompt with nothing to pick.
"""

from __future__ import annotations

import copy
import operator
from dataclasses import dataclass
from functools import reduce
from http import HTTPStatus
from typing import Any

from cfb_strength.contracts import (
    AmbiguousTeamError,
    SameTeamComparisonError,
    UnknownTeamError,
    UnknownYearError,
)
from fastapi import FastAPI, Request
from fastapi.openapi.utils import (
    validation_error_definition,
    validation_error_response_definition,
)
from fastapi.responses import JSONResponse
from pydantic import BaseModel, GetJsonSchemaHandler
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import CoreSchema

from api.models import (
    AmbiguousTeamErrorBody,
    AmbiguousTeamErrorResponse,
    SameTeamComparisonErrorBody,
    SameTeamComparisonErrorResponse,
    UnknownTeamErrorBody,
    UnknownTeamErrorResponse,
    UnknownYearErrorBody,
    UnknownYearErrorResponse,
)


@dataclass(frozen=True)
class MappedError:
    status_code: int
    response_model: type[BaseModel]


ENGINE_ERROR_RESPONSES: dict[type[Exception], MappedError] = {
    UnknownYearError: MappedError(404, UnknownYearErrorResponse),
    UnknownTeamError: MappedError(404, UnknownTeamErrorResponse),
    AmbiguousTeamError: MappedError(422, AmbiguousTeamErrorResponse),
    SameTeamComparisonError: MappedError(400, SameTeamComparisonErrorResponse),
}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(UnknownYearError)
    def _unknown_year(request: Request, exc: UnknownYearError) -> JSONResponse:
        body = UnknownYearErrorBody(year=exc.year, available_years=exc.available_years)
        return JSONResponse(
            status_code=ENGINE_ERROR_RESPONSES[UnknownYearError].status_code,
            content={"detail": body.model_dump()},
        )

    @app.exception_handler(UnknownTeamError)
    def _unknown_team(request: Request, exc: UnknownTeamError) -> JSONResponse:
        # `exc.sport` is checked against the body's `Sport` literal in two
        # ways, and they are not symmetric. Statically since #102: this app
        # now sees the engine's real types, so if `UnknownTeamError.sport` is
        # widened back to `str` (or gains a league `Sport` lacks), mypy fails
        # on this line. The reverse is NOT caught statically: widening
        # `UnknownTeamErrorBody.sport` on this side still type-checks, so that
        # direction rests on pydantic validating the literal at construction.
        # That matters downstream: `apps/web`'s `isVerdictErrorBody` guard
        # drops the *whole body* if this field falls outside its union,
        # collapsing a mapped 404 into a generic one.
        body = UnknownTeamErrorBody(query=exc.query, year=exc.year, sport=exc.sport)
        return JSONResponse(
            status_code=ENGINE_ERROR_RESPONSES[UnknownTeamError].status_code,
            content={"detail": body.model_dump()},
        )

    @app.exception_handler(AmbiguousTeamError)
    def _ambiguous_team(request: Request, exc: AmbiguousTeamError) -> JSONResponse:
        body = AmbiguousTeamErrorBody(query=exc.query, candidates=exc.candidates)
        return JSONResponse(
            status_code=ENGINE_ERROR_RESPONSES[AmbiguousTeamError].status_code,
            content={"detail": body.model_dump()},
        )

    @app.exception_handler(SameTeamComparisonError)
    def _same_team_comparison(request: Request, exc: SameTeamComparisonError) -> JSONResponse:
        body = SameTeamComparisonErrorBody(team_name=exc.team_name)
        return JSONResponse(
            status_code=ENGINE_ERROR_RESPONSES[SameTeamComparisonError].status_code,
            content={"detail": body.model_dump()},
        )


# ---------------------------------------------------------------------------
# /openapi.json declarations
# ---------------------------------------------------------------------------


class ValidationError(BaseModel):
    """Documentation-only stand-in for FastAPI's `ValidationError` schema.
    Never instantiated. Its JSON schema is FastAPI's own definition, copied
    verbatim, so there is no second hand-written copy to drift. The class
    name is load-bearing: it is the component name FastAPI uses too, so this
    model and FastAPI's default 422 publish one component, not two.
    """

    @classmethod
    def __get_pydantic_json_schema__(
        cls, core_schema: CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        return copy.deepcopy(validation_error_definition)


class HTTPValidationError(BaseModel):
    """Documentation-only stand-in for FastAPI's request-validation 422 body,
    so a declared 422 can list it next to `ambiguous_team` (see the module
    docstring). Same rules as `ValidationError` above.
    """

    detail: list[ValidationError]

    @classmethod
    def __get_pydantic_json_schema__(
        cls, core_schema: CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        # Generate (and discard) the default schema so pydantic registers the
        # `ValidationError` definition that FastAPI's schema below refers to.
        handler(core_schema)
        return copy.deepcopy(validation_error_response_definition)


def openapi_error_responses(*errors: type[Exception]) -> dict[int | str, dict[str, Any]]:
    """A route's `responses=` value for the engine errors it can raise: one
    entry per status, whose model is the union of those errors' envelopes.
    A 422 also gets `HTTPValidationError`, because declaring one replaces
    FastAPI's default."""
    by_status: dict[int, list[type[BaseModel]]] = {}
    names: dict[int, list[str]] = {}
    for error in errors:
        mapped = ENGINE_ERROR_RESPONSES[error]
        by_status.setdefault(mapped.status_code, []).append(mapped.response_model)
        names.setdefault(mapped.status_code, []).append(error.__name__)
    if HTTPStatus.UNPROCESSABLE_ENTITY in by_status:
        by_status[HTTPStatus.UNPROCESSABLE_ENTITY].append(HTTPValidationError)
        names[HTTPStatus.UNPROCESSABLE_ENTITY].append("request validation")

    responses: dict[int | str, dict[str, Any]] = {}
    for status in sorted(by_status):
        model: Any = reduce(operator.or_, by_status[status])
        responses[status] = {
            "model": model,
            "description": f"{HTTPStatus(status).phrase}: {', '.join(names[status])}",
        }
    return responses


# `build_team_case` goes through `resolve_team`: `_require_year` raises
# `UnknownYearError`, then no match raises `UnknownTeamError` and several
# matches raise `AmbiguousTeamError`.
TEAM_CASE_ERROR_RESPONSES = openapi_error_responses(
    UnknownYearError, UnknownTeamError, AmbiguousTeamError
)

# `build_comparison` resolves both teams the same way, then raises
# `SameTeamComparisonError` if they are the same team.
COMPARISON_ERROR_RESPONSES = openapi_error_responses(
    UnknownYearError, UnknownTeamError, AmbiguousTeamError, SameTeamComparisonError
)
