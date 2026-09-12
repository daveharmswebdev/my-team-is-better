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
        # `exc.sport` is re-validated here rather than passed through: the
        # body's `sport` is a `Sport` literal, and `apps/web`'s
        # `isVerdictErrorBody` guard drops the whole body if that field
        # falls outside its union. The request models admit only `cfb`/`nfl`
        # in the first place, so this never rejects in practice -- it is the
        # assertion that keeps the two ends in step.
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
