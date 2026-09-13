"""Runtime tests pinning `method` to `cfb_strength.contracts.Method` on every
surface that accepts one: each value the alias lists is accepted, and
anything else is a 422 located at `method`.

Why this is a bug worth a test file rather than input hygiene: `method` was
an unvalidated `str`, so a typo did not fail -- it succeeded, emptily.
`GET /api/years?method=nonsense&sport=cfb` returned `200 {"years": []}`,
which is byte-identical to the answer for a real method whose seasons have
not been ingested yet. `/api/years` is what populates the web year picker,
so the user-visible symptom of a typo'd method was an empty year dropdown
that looked exactly like a data-coverage problem, with nothing anywhere
saying otherwise. 422 makes the two cases distinguishable.

Both directions are pinned deliberately:

- An unknown method is rejected on all five surfaces (three verdict routes,
  two catalog routes). Constraining only the verdict models would be worse
  than constraining neither, since the catalog routes are the ones feeding
  the picker.
- Every registered method is *accepted* on all five, `elo_career` included,
  even though the fixture has no rows computed under it.

**Where the valid values come from (#112).** `REGISTERED_METHODS` is
`typing.get_args(cfb_strength.contracts.Method)`, the same alias `api.models`
re-exports. apps/api still may not import `cfb_strength.ratings`
(docs/ARCHITECTURE.md §2, checked by `apps/api/.importlinter`), so it never
reads `compute_ratings.METHODS` itself. The contract alias is what makes
that boundary free. What is checked where:

- here: runtime behavior. Every alias value gets past validation on all
  five surfaces, and an unknown value is a 422 at `method`;
- `tests/test_openapi_vocabularies.py`: that apps/api does not redeclare
  the vocabulary, that every `method` published in /openapi.json as an
  input carries exactly the alias's enum, and that the committed
  `openapi-vocabularies.json` is current. The response field
  `TeamCaseOut.method` is still a plain `str`, on an explicit allowlist
  there;
- packages/cfb-engine's `tests/test_contract_vocabularies.py`: that the
  alias equals `compute_ratings.METHODS` (and the Elo configs).

Because the values are derived, nothing here would notice the alias itself
losing a method (narrowing to keener-only, say, while Elo is a shipped,
credited method). That is the engine test's job.

422-shape note: `AmbiguousTeamError` also maps to 422 (see `api.errors`), so
these tests assert on the *shape* of the body rather than the status alone.
FastAPI's request-validation 422 carries `detail` as a **list** of error
objects located at the offending field, whereas the app's typed-exception
handlers carry `detail` as a single dict. Asserting the field location is
what makes "422 because `method` is invalid" distinguishable from "422 for
some unrelated reason".
"""

from __future__ import annotations

from typing import get_args

import pytest
from cfb_strength.contracts import Method
from fastapi.testclient import TestClient

# Every value the contract's `Method` alias admits -- derived, not mirrored.
REGISTERED_METHODS: tuple[str, ...] = get_args(Method)

BAD_METHOD = "nonsense"

VERDICT_ROUTES: tuple[tuple[str, dict[str, object]], ...] = (
    ("/api/verdict/champion", {"year": 2005}),
    ("/api/verdict/team-case", {"year": 2005, "team": "Texas"}),
    ("/api/verdict/compare", {"year": 2005, "team_a": "Texas", "team_b": "USC"}),
)

CATALOG_ROUTES: tuple[tuple[str, dict[str, int]], ...] = (
    ("/api/years", {}),
    ("/api/teams", {"year": 2005}),
)


def _assert_rejected_for_method(response_status: int, detail: object) -> None:
    """A request-validation 422 whose complaint is located at `method`."""
    assert response_status == 422
    assert isinstance(detail, list), f"expected a validation-error list, got {detail!r}"
    locations = [error.get("loc", ()) for error in detail]
    assert any("method" in tuple(loc) for loc in locations), (
        f"expected a validation error located at `method`, got {locations!r}"
    )


# ---------------------------------------------------------------------------
# an unknown method is rejected, not silently answered with nothing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path,payload", VERDICT_ROUTES, ids=lambda v: str(v))
def test_verdict_route_rejects_unknown_method(
    client: TestClient, path: str, payload: dict[str, object]
) -> None:
    response = client.post(path, json={**payload, "method": BAD_METHOD})

    _assert_rejected_for_method(response.status_code, response.json().get("detail"))


@pytest.mark.parametrize("path,params", CATALOG_ROUTES, ids=lambda v: str(v))
def test_catalog_route_rejects_unknown_method(
    client: TestClient, path: str, params: dict[str, int]
) -> None:
    response = client.get(path, params={**params, "method": BAD_METHOD})

    _assert_rejected_for_method(response.status_code, response.json().get("detail"))


def test_teams_rejects_unknown_method_even_without_a_year(client: TestClient) -> None:
    """`method` only *narrows* `/api/teams` when `year` is given (the
    unscoped list joins no ratings rows at all), so it would have been easy
    to validate it in one case and not the other. Both are validated: a
    method that does not exist is rejected regardless of whether it would
    have changed the answer.
    """
    response = client.get("/api/teams", params={"method": BAD_METHOD})

    _assert_rejected_for_method(response.status_code, response.json().get("detail"))


def test_years_typo_is_no_longer_indistinguishable_from_an_uningested_season(
    client: TestClient,
) -> None:
    """The exact regression this change exists for: a typo'd method used to
    return the same `200 {"years": []}` an un-ingested sport returns."""
    typo = client.get("/api/years", params={"method": "keneer", "sport": "cfb"})

    assert typo.status_code == 422
    assert typo.json() != {"years": []}


# ---------------------------------------------------------------------------
# every registered method is accepted on every surface
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", REGISTERED_METHODS)
@pytest.mark.parametrize("path,payload", VERDICT_ROUTES, ids=lambda v: str(v))
def test_verdict_route_accepts_every_registered_method(
    client: TestClient, path: str, payload: dict[str, object], method: str
) -> None:
    response = client.post(path, json={**payload, "method": method})

    assert response.status_code != 422, response.json()


@pytest.mark.parametrize("method", REGISTERED_METHODS)
@pytest.mark.parametrize("path,params", CATALOG_ROUTES, ids=lambda v: str(v))
def test_catalog_route_accepts_every_registered_method(
    client: TestClient, path: str, params: dict[str, int], method: str
) -> None:
    response = client.get(path, params={**params, "method": method})

    assert response.status_code == 200, response.json()


@pytest.mark.parametrize("method", REGISTERED_METHODS)
def test_years_accepts_every_registered_method(client: TestClient, method: str) -> None:
    """Schema-level acceptance for all three registered methods, including
    `elo_career`, which deliberately has **no rows in the fixture**: its
    offseason mean reversion counts *elapsed* years, and the fixture's
    seasons (2001/2005/2013) are non-contiguous by design, so baking it
    would produce numbers that model nothing (issue #98). Accepting the
    method and returning an empty year list is the correct behavior for a
    real-but-uncomputed method -- which is precisely the case a typo must
    no longer be able to impersonate.
    """
    response = client.get("/api/years", params={"method": method})

    assert response.status_code == 200
    assert isinstance(response.json()["years"], list)
