"""Issue #83: a tie (a completed game with equal scores) carried end to end
through `/api/verdict/*`.

The engine reports `result == "T"` and `ties` (see `cfb_strength.contracts`);
these tests pin that `apps/api` passes both through the response models, the
persona fact block, and the fallback narration without turning a tie into a
loss, a win, or a 500. Uses `sport_client`'s synthetic NFL tie cluster (see
`tests/fixtures/sport_fixture.py`'s `build_tie_cluster`).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import anthropic
import httpx2
from fastapi.testclient import TestClient
from fixtures.sport_fixture import (
    TIE_OPPONENT,
    TIE_RIVAL,
    TIE_TEAM,
    TIE_WIN_OPPONENT,
    YEAR,
)

from api.deps import get_narration_cache, get_narrator
from api.main import app
from api.persona.cache import InMemoryNarrationCache


class _RecordingNarrator:
    """Returns scripted responses (or raises `error` on every call), and
    records every system prompt and message list it was handed."""

    def __init__(self, responses: list[str] | None = None, error: Exception | None = None) -> None:
        self.responses = list(responses or [])
        self.error = error
        self.calls: list[list[dict[str, str]]] = []

    def complete(self, *, system: str, messages: list[dict[str, str]]) -> str:
        self.calls.append([dict(m) for m in messages])
        if self.error is not None:
            raise self.error
        return self.responses.pop(0)


@contextmanager
def _wired(narrator: _RecordingNarrator) -> Iterator[None]:
    app.dependency_overrides[get_narration_cache] = lambda: InMemoryNarrationCache()
    app.dependency_overrides[get_narrator] = lambda: narrator
    try:
        yield
    finally:
        # `sport_client`'s own teardown pops these too; restoring its stub
        # isn't needed because each test gets a fresh client.
        app.dependency_overrides.pop(get_narration_cache, None)
        app.dependency_overrides.pop(get_narrator, None)


def _fact_block(user_message: str) -> Any:
    """The JSON between `build_user_message`'s FACT BLOCK header and its
    trailing `contested:` line."""
    header = "FACT BLOCK (JSON):\n"
    body = user_message[user_message.index(header) + len(header) :]
    return json.loads(body[: body.rindex("\n\ncontested:")])


def _team_case(client: TestClient) -> Any:
    response = client.post(
        "/api/verdict/team-case",
        json={"year": YEAR, "team": TIE_TEAM, "sport": "nfl"},
    )
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# evidence
# ---------------------------------------------------------------------------


def test_team_case_carries_the_tie_as_a_tie(sport_client: TestClient) -> None:
    evidence = _team_case(sport_client)["evidence"]

    assert evidence["wins"] == 1
    assert evidence["losses"] == 1
    assert evidence["ties"] == 1

    tied = [g for g in evidence["games"] if g["result"] == "T"]
    assert len(tied) == 1
    (tie,) = tied
    assert tie["opponent_name"] == TIE_OPPONENT
    assert (tie["team_score"], tie["opponent_score"]) == (17, 17)

    # Mike Mustangs is rank 8: a tie mistaken for a win would be a quality
    # win, and mistaken for a loss would out-rank the real loss (rank 5).
    assert all(g["result"] == "W" for g in evidence["quality_wins"])
    assert [g["opponent_name"] for g in evidence["quality_wins"]] == [TIE_WIN_OPPONENT]
    assert evidence["worst_loss"]["opponent_name"] == TIE_RIVAL
    assert evidence["worst_loss"]["result"] == "L"


def test_comparison_reports_a_tied_common_opponent_as_t(sport_client: TestClient) -> None:
    response = sport_client.post(
        "/api/verdict/compare",
        json={"year": YEAR, "team_a": TIE_TEAM, "team_b": TIE_RIVAL, "sport": "nfl"},
    )

    assert response.status_code == 200, response.text
    evidence = response.json()["evidence"]
    assert evidence["team_a"]["ties"] == 1
    assert evidence["team_b"]["ties"] == 0

    (common,) = evidence["common_opponents"]
    assert common["opponent_name"] == TIE_OPPONENT
    assert common["team_a_result"] == "T"
    assert (common["team_a_score"], common["team_a_opponent_score"]) == (17, 17)
    assert common["team_b_result"] == "W"


def test_openapi_schema_carries_ties_and_the_t_result() -> None:
    schemas = TestClient(app).get("/openapi.json").json()["components"]["schemas"]

    assert "ties" in schemas["TeamCaseOut"]["required"]
    assert "ties" in schemas["ComparisonTeamSummaryOut"]["required"]
    assert schemas["OpponentResultOut"]["properties"]["result"]["enum"] == ["W", "L", "T"]
    for field in ("team_a_result", "team_b_result"):
        assert schemas["CommonOpponentOut"]["properties"][field]["enum"] == ["W", "L", "T"]


# ---------------------------------------------------------------------------
# persona: fact block, grounding, fallback
# ---------------------------------------------------------------------------


def test_fact_block_given_to_claude_describes_the_tie_as_a_tie(
    sport_client: TestClient,
) -> None:
    narrator = _RecordingNarrator(responses=[f"{TIE_TEAM} went 1-1-1 in {YEAR}."])

    with _wired(narrator):
        body = _team_case(sport_client)

    facts = _fact_block(narrator.calls[0][0]["content"])
    assert facts["ties"] == 1
    results = {g["opponent_name"]: g["result"] for g in facts["games"]}
    assert results[TIE_OPPONENT] == "T"
    assert facts["worst_loss"]["opponent_name"] != TIE_OPPONENT

    # The W-L-T record grounds on the first try: served verbatim, one call.
    assert body["narration"]["text"] == f"{TIE_TEAM} went 1-1-1 in {YEAR}."
    assert len(narrator.calls) == 1


def test_fallback_narration_for_a_tied_team_states_its_w_l_t_record(
    sport_client: TestClient,
) -> None:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    narrator = _RecordingNarrator(error=anthropic.APIConnectionError(request=request))

    with _wired(narrator):
        body = _team_case(sport_client)

    assert f"{TIE_TEAM} finished 1-1-1 in {YEAR}" in body["narration"]["text"]
