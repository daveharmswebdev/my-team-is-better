"""Runtime tests pinning `sport` to `cfb_strength.contracts.Sport` on every
surface that accepts one: each value the alias lists is accepted, and
anything else is a 422 located at `sport`.

This is `test_method_validation.py`'s argument applied to the other
free-text discriminator, and it has a second, sharper symptom of its own.

**Unconstrained inbound.** `sport` was a bare `str`, so
`GET /api/years?sport=basketball` answered `200 {"years": []}` -- identical
to a real league whose seasons are not ingested yet, and the same
typo-is-indistinguishable-from-missing-data failure #104 fixed for `method`.

**Unconstrained outbound, which is worse.** `UnknownTeamErrorBody.sport`
was also a bare `str`, while `apps/web` types `sport` as a `Sport` union and
its `isVerdictErrorBody` type guard rejects the *whole body* when `sport` is
neither `cfb` nor `nfl`. A 404 carrying an unrecognised sport therefore did
not render as "we have no rating for that team" -- it failed the guard and
collapsed into a generic network error, which is exactly the dead end issue
#100 exists to remove. The request boundary is where that is prevented: if
nothing but `cfb`/`nfl` can get in, nothing but `cfb`/`nfl` can be echoed
back out, since the error body echoes the request's sport.

**Where the valid values come from (#112).** `REGISTERED_SPORTS` is
`typing.get_args(cfb_strength.contracts.Sport)`, the same alias `api.models`
re-exports, so adding a league to the contract makes these tests require it
on every surface with no edit here. What is checked where:

- here: runtime behavior. Every alias value gets past validation on all
  five surfaces, and an unknown value is a 422 at `sport`;
- `tests/test_openapi_vocabularies.py`: that apps/api does not redeclare
  the vocabulary, that every `sport` published in /openapi.json carries
  exactly the alias's enum, and that the committed
  `openapi-vocabularies.json` apps/web checks against is current;
- packages/cfb-engine's `tests/test_contract_vocabularies.py`: that the
  alias matches the leagues the engine actually ingests and rates.

Because the values are derived, nothing here would notice the alias itself
being narrowed (dropping `nfl`, say). That is the engine test's job.

422-shape note: as in `test_method_validation.py`, FastAPI's
request-validation 422 carries `detail` as a **list** of error objects
located at the offending field, whereas the app's typed-exception handlers
(`api.errors`) carry `detail` as a single dict. Asserting the field location
is what makes "422 because `sport` is invalid" distinguishable from "422 for
some unrelated reason" -- `ambiguous_team` is also a 422.
"""

from __future__ import annotations

from typing import get_args

import pytest
from cfb_strength.contracts import Sport
from fastapi.testclient import TestClient

# Every value the contract's `Sport` alias admits -- derived, not mirrored.
REGISTERED_SPORTS: tuple[str, ...] = get_args(Sport)

BAD_SPORT = "basketball"

VERDICT_ROUTES: tuple[tuple[str, dict[str, object]], ...] = (
    ("/api/verdict/champion", {"year": 2005}),
    ("/api/verdict/team-case", {"year": 2005, "team": "Texas"}),
    ("/api/verdict/compare", {"year": 2005, "team_a": "Texas", "team_b": "USC"}),
)

CATALOG_ROUTES: tuple[tuple[str, dict[str, int]], ...] = (
    ("/api/years", {}),
    ("/api/teams", {"year": 2005}),
)


def _assert_rejected_for_sport(response_status: int, detail: object) -> None:
    """A request-validation 422 whose complaint is located at `sport`."""
    assert response_status == 422
    assert isinstance(detail, list), f"expected a validation-error list, got {detail!r}"
    locations = [error.get("loc", ()) for error in detail]
    assert any("sport" in tuple(loc) for loc in locations), (
        f"expected a validation error located at `sport`, got {locations!r}"
    )


# ---------------------------------------------------------------------------
# an unknown sport is rejected, not silently answered with nothing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path,payload", VERDICT_ROUTES, ids=lambda v: str(v))
def test_verdict_route_rejects_unknown_sport(
    client: TestClient, path: str, payload: dict[str, object]
) -> None:
    response = client.post(path, json={**payload, "sport": BAD_SPORT})

    _assert_rejected_for_sport(response.status_code, response.json().get("detail"))


@pytest.mark.parametrize("path,params", CATALOG_ROUTES, ids=lambda v: str(v))
def test_catalog_route_rejects_unknown_sport(
    client: TestClient, path: str, params: dict[str, int]
) -> None:
    response = client.get(path, params={**params, "sport": BAD_SPORT})

    _assert_rejected_for_sport(response.status_code, response.json().get("detail"))


def test_years_typo_is_no_longer_indistinguishable_from_an_uningested_league(
    client: TestClient,
) -> None:
    """The exact regression this change exists for: a typo'd sport used to
    return the same `200 {"years": []}` an un-ingested league returns."""
    typo = client.get("/api/years", params={"sport": "cbf"})

    assert typo.status_code == 422
    assert typo.json() != {"years": []}


def test_unknown_team_body_can_only_ever_echo_a_recognised_sport(
    client: TestClient,
) -> None:
    """The outbound half, end-to-end through the real engine. `apps/web`'s
    `isVerdictErrorBody` guard rejects a body whose `sport` is outside its
    `Sport` union, turning a mapped 404 into a generic network error. The
    request boundary is what guarantees that cannot happen: an unrecognised
    sport never reaches the engine, so it can never be echoed into the
    error body it would have broken.
    """
    rejected = client.post(
        "/api/verdict/team-case",
        json={"year": 2005, "team": "Zzyzx Polytechnic", "sport": BAD_SPORT},
    )
    assert rejected.status_code == 422, "an unrecognised sport must not reach the engine"

    # ...and the 404 that a *recognised* sport produces still echoes a value
    # inside the union.
    detail = client.post(
        "/api/verdict/team-case",
        json={"year": 2005, "team": "Zzyzx Polytechnic", "sport": "cfb"},
    ).json()["detail"]
    assert detail["sport"] in REGISTERED_SPORTS


# ---------------------------------------------------------------------------
# every registered sport is still accepted -- constraining the field must not
# narrow it to the cfb-only behavior that predates issue #59
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("sport", REGISTERED_SPORTS)
@pytest.mark.parametrize("path,payload", VERDICT_ROUTES, ids=lambda v: str(v))
def test_verdict_route_accepts_every_registered_sport(
    client: TestClient, path: str, payload: dict[str, object], sport: str
) -> None:
    response = client.post(path, json={**payload, "sport": sport})

    assert response.status_code != 422, response.json()


@pytest.mark.parametrize("sport", REGISTERED_SPORTS)
@pytest.mark.parametrize("path,params", CATALOG_ROUTES, ids=lambda v: str(v))
def test_catalog_route_accepts_every_registered_sport(
    client: TestClient, path: str, params: dict[str, int], sport: str
) -> None:
    response = client.get(path, params={**params, "sport": sport})

    assert response.status_code == 200, response.json()
