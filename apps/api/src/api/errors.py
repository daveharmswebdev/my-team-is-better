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
there is exactly one place this mapping is spelled out.

`UnknownTeamError` is 404 and not 422 on purpose (issue #100): it is the
same "you asked about a thing we have no data for" case as
`UnknownYearError`, not a "your input was one of several things" case. 422
stays reserved for `ambiguous_team`, whose `candidates` is always non-empty
-- before #100 the engine raised `AmbiguousTeamError` with an empty
candidate list for a zero-match query, so a genuine not-found reached the
client as a 422 "did you mean:" prompt with nothing to pick.
"""

from __future__ import annotations

from cfb_strength.contracts import (
    AmbiguousTeamError,
    SameTeamComparisonError,
    UnknownTeamError,
    UnknownYearError,
)
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from api.models import (
    AmbiguousTeamErrorBody,
    SameTeamComparisonErrorBody,
    UnknownTeamErrorBody,
    UnknownYearErrorBody,
)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(UnknownYearError)
    def _unknown_year(request: Request, exc: UnknownYearError) -> JSONResponse:
        body = UnknownYearErrorBody(year=exc.year, available_years=exc.available_years)
        return JSONResponse(status_code=404, content={"detail": body.model_dump()})

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
        return JSONResponse(status_code=404, content={"detail": body.model_dump()})

    @app.exception_handler(AmbiguousTeamError)
    def _ambiguous_team(request: Request, exc: AmbiguousTeamError) -> JSONResponse:
        body = AmbiguousTeamErrorBody(query=exc.query, candidates=exc.candidates)
        return JSONResponse(status_code=422, content={"detail": body.model_dump()})

    @app.exception_handler(SameTeamComparisonError)
    def _same_team_comparison(request: Request, exc: SameTeamComparisonError) -> JSONResponse:
        body = SameTeamComparisonErrorBody(team_name=exc.team_name)
        return JSONResponse(status_code=400, content={"detail": body.model_dump()})
