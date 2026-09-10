"""Maps `cfb_strength.contracts`' typed engine exceptions to HTTP responses
(Architecture Brief §4.4 -- the HTTP-response half only; in-character
persona copy for these is issue #4's job, not this one's).

| Engine exception          | HTTP behavior                                |
|----------------------------|----------------------------------------------|
| `UnknownYearError`         | 404, body includes `available_years`         |
| `AmbiguousTeamError`       | 422, body includes `candidates`               |
| `SameTeamComparisonError`  | 400                                           |

Registered once on the app (`api.main`) rather than caught per-route, so
there is exactly one place this mapping is spelled out.
"""

from __future__ import annotations

from cfb_strength.contracts import (
    AmbiguousTeamError,
    SameTeamComparisonError,
    UnknownYearError,
)
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from api.models import (
    AmbiguousTeamErrorBody,
    SameTeamComparisonErrorBody,
    UnknownYearErrorBody,
)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(UnknownYearError)
    def _unknown_year(request: Request, exc: UnknownYearError) -> JSONResponse:
        body = UnknownYearErrorBody(year=exc.year, available_years=exc.available_years)
        return JSONResponse(status_code=404, content={"detail": body.model_dump()})

    @app.exception_handler(AmbiguousTeamError)
    def _ambiguous_team(request: Request, exc: AmbiguousTeamError) -> JSONResponse:
        body = AmbiguousTeamErrorBody(query=exc.query, candidates=exc.candidates)
        return JSONResponse(status_code=422, content={"detail": body.model_dump()})

    @app.exception_handler(SameTeamComparisonError)
    def _same_team_comparison(request: Request, exc: SameTeamComparisonError) -> JSONResponse:
        body = SameTeamComparisonErrorBody(team_name=exc.team_name)
        return JSONResponse(status_code=400, content={"detail": body.model_dump()})
