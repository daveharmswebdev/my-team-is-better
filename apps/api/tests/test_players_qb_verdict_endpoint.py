"""`POST /api/players/compare/verdict` (issue #451, epic #439 step 2): two
quarterbacks' QB-score comparison with a narration, `{evidence, narration}`.

`evidence.qb_score` is exactly `GET /api/players/compare`'s `qb_score` for the
same pair, plus the context the narrator may cite (each QB's coverage,
starter records and short name, and the pair's head-to-head). The gates are
compare's: `a == b` is a 422 at `b`, an unknown player is the typed 404, and
a pair that isn't two quarterbacks is a 400 `players_not_comparable` (two
RBs included: comparable on /compare, but not by the QB score).

The narrator is the conftest's `FakeNarrator` (through `get_narrator`, which
`get_qb_narrator` passes a fake through untouched), so nothing here calls
Claude.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from fixtures.narrator_fake import ACCEPTED_NARRATION, FakeNarrator
from fixtures.qb_blocks import (
    EDGERRIN_JAMES,
    KURT_WARNER,
    MARSHALL_FAULK,
    RANDALL_CUNNINGHAM,
    STEVE_MCNAIR,
)

from api.persona.cache import InMemoryNarrationCache

VERDICT = "/api/players/compare/verdict"
COMPARE = "/api/players/compare"


@pytest.fixture
def narrator(client: TestClient) -> Iterator[FakeNarrator]:
    from api.deps import get_narrator
    from api.main import app

    fake = FakeNarrator(
        always={
            "text": "{w} takes the career, and the books only open in {yr}.",
            "claims": [
                {"id": "w", "kind": "winner", "measure": "career"},
                {"id": "yr", "kind": "year"},
            ],
        }
    )
    app.dependency_overrides[get_narrator] = lambda: fake
    yield fake


def test_a_qb_pair_gets_the_score_and_a_narration(
    client: TestClient, narrator: FakeNarrator
) -> None:
    response = client.post(VERDICT, json={"a": KURT_WARNER, "b": STEVE_MCNAIR})

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"evidence", "narration"}
    compare = client.get(COMPARE, params={"a": KURT_WARNER, "b": STEVE_MCNAIR}).json()
    assert body["evidence"]["qb_score"] == compare["qb_score"]
    assert body["evidence"]["a"]["display_name"] == "Kurt Warner"
    assert body["evidence"]["a"]["coverage"] == compare["a"]["coverage"]
    assert (
        body["evidence"]["a"]["regular_season_record"] == compare["a"]["regular_season"]["record"]
    )
    assert (
        body["evidence"]["regular_season_head_to_head"]
        == (compare["regular_season_head_to_head"]["record"])
    )
    assert body["narration"] == {
        "text": "Warner takes the career, and the books only open in 1999.",
        "contested": False,
        "cached": False,
    }
    # The narrator was given the NFL QB prompt and the QB fact block.
    (call,) = narrator.calls
    assert "quarterback" in call.system
    assert '"qb_score"' in call.user_texts[0]


def test_the_default_narrator_answer_is_served_too(client: TestClient) -> None:
    response = client.post(VERDICT, json={"a": KURT_WARNER, "b": STEVE_MCNAIR, "sport": "nfl"})
    assert response.status_code == 200, response.text
    assert response.json()["narration"]["text"] == ACCEPTED_NARRATION


def test_a_second_request_is_served_from_the_cache(client: TestClient) -> None:
    from api.deps import get_narration_cache, get_narrator
    from api.main import app

    cache = InMemoryNarrationCache()
    fake = FakeNarrator()
    app.dependency_overrides[get_narration_cache] = lambda: cache
    app.dependency_overrides[get_narrator] = lambda: fake

    first = client.post(VERDICT, json={"a": KURT_WARNER, "b": STEVE_MCNAIR}).json()
    second = client.post(VERDICT, json={"a": KURT_WARNER, "b": STEVE_MCNAIR}).json()

    assert first["narration"]["cached"] is False
    assert second["narration"]["cached"] is True
    assert len(fake.calls) == 1


def test_an_inconclusive_pair_is_still_a_200(client: TestClient, narrator: FakeNarrator) -> None:
    response = client.post(VERDICT, json={"a": KURT_WARNER, "b": RANDALL_CUNNINGHAM})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["evidence"]["qb_score"]["inconclusive"] == "b_no_qualifying_season"
    # The scripted narration names a winner, which an inconclusive block
    # rejects twice: the in-voice fallback is served, uncached.
    assert body["narration"]["cached"] is False
    assert "inconclusive" in body["narration"]["text"].lower()
    assert len(narrator.calls) == 2


@pytest.mark.parametrize(
    "a,b,groups",
    [(MARSHALL_FAULK, EDGERRIN_JAMES, ("RB", "RB")), (KURT_WARNER, MARSHALL_FAULK, ("QB", "RB"))],
    ids=["two-rbs", "qb-and-rb"],
)
def test_a_pair_that_is_not_two_quarterbacks_is_a_400(
    client: TestClient, a: int, b: int, groups: tuple[str, str]
) -> None:
    response = client.post(VERDICT, json={"a": a, "b": b})
    assert response.status_code == 400, response.text
    assert response.json() == {
        "detail": {"error": "players_not_comparable", "a_group": groups[0], "b_group": groups[1]}
    }


def test_the_same_player_twice_is_a_422_at_b(client: TestClient) -> None:
    response = client.post(VERDICT, json={"a": KURT_WARNER, "b": KURT_WARNER})
    assert response.status_code == 422, response.text
    (error,) = response.json()["detail"]
    assert error["loc"] == ["body", "b"]


@pytest.mark.parametrize(
    "a,b,unknown",
    [(1, KURT_WARNER, 1), (KURT_WARNER, 2, 2), (2**63, KURT_WARNER, 2**63)],
    ids=["a", "b", "out-of-range"],
)
def test_an_unknown_player_is_the_typed_404(
    client: TestClient, a: int, b: int, unknown: int
) -> None:
    response = client.post(VERDICT, json={"a": a, "b": b})
    assert response.status_code == 404, response.text
    assert response.json() == {
        "detail": {"error": "unknown_player", "player_id": unknown, "sport": "nfl"}
    }


def test_a_league_without_player_stats_is_a_422_at_sport(client: TestClient) -> None:
    response = client.post(VERDICT, json={"a": KURT_WARNER, "b": STEVE_MCNAIR, "sport": "cfb"})
    assert response.status_code == 422, response.text
    (error,) = response.json()["detail"]
    assert error["loc"] == ["body", "sport"]


def test_an_unknown_body_field_is_a_422(client: TestClient) -> None:
    response = client.post(VERDICT, json={"a": KURT_WARNER, "b": STEVE_MCNAIR, "user_team": "Rams"})
    assert response.status_code == 422, response.text
