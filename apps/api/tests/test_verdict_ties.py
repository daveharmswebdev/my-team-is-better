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
from fixtures.narrator_fake import FakeNarrator
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


@contextmanager
def _wired(narrator: FakeNarrator) -> Iterator[None]:
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

    assert evidence["wins"] == 2
    assert evidence["losses"] == 1
    assert evidence["ties"] == 1

    tied = [g for g in evidence["games"] if g["result"] == "T"]
    assert len(tied) == 1
    (tie,) = tied
    assert tie["opponent_name"] == TIE_OPPONENT
    assert (tie["team_score"], tie["opponent_score"]) == (17, 17)

    # Mike Mustangs is rank 8: a tie mistaken for a win would be a third
    # quality win (the real rematch win over them is one, #130), and mistaken
    # for a loss would out-rank the real loss (rank 5).
    assert all(g["result"] == "W" for g in evidence["quality_wins"])
    assert [g["opponent_name"] for g in evidence["quality_wins"]] == [
        TIE_OPPONENT,
        TIE_WIN_OPPONENT,
    ]
    assert all(g["team_score"] != g["opponent_score"] for g in evidence["quality_wins"])
    assert evidence["worst_loss"]["opponent_name"] == TIE_RIVAL
    assert evidence["worst_loss"]["result"] == "L"


_OLD_COMMON_OPPONENT_KEYS = (
    "team_a_result",
    "team_a_score",
    "team_a_opponent_score",
    "team_b_result",
    "team_b_score",
    "team_b_opponent_score",
)


def test_comparison_carries_every_meeting_with_a_common_opponent(
    sport_client: TestClient,
) -> None:
    """Issue #130: a side that met the shared opponent twice publishes both
    meetings, chronologically, not just the last one. Kilo Kings tied Mike
    Mustangs in week 2 and beat them in week 4; Lima Lions beat them once."""
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
    assert not any(key in common for key in _OLD_COMMON_OPPONENT_KEYS)

    assert len(common["team_a_meetings"]) == 2
    tie, rematch = common["team_a_meetings"]
    # `game_id` is the fixture's `games.id` for each meeting (#218).
    assert tie == {
        "game_id": 105,
        "result": "T",
        "team_score": 17,
        "opponent_score": 17,
        "week": 2,
        "season_type": "regular",
    }
    assert rematch == {
        "game_id": 108,
        "result": "W",
        "team_score": 31,
        "opponent_score": 14,
        "week": 4,
        "season_type": "regular",
    }

    assert len(common["team_b_meetings"]) == 1
    (only,) = common["team_b_meetings"]
    assert only["result"] == "W"
    assert (only["team_score"], only["opponent_score"]) == (27, 10)


def test_openapi_schema_carries_ties_and_the_t_result() -> None:
    schemas = TestClient(app).get("/openapi.json").json()["components"]["schemas"]

    assert "ties" in schemas["TeamCaseOut"]["required"]
    assert "ties" in schemas["ComparisonTeamSummaryOut"]["required"]
    assert schemas["OpponentResultOut"]["properties"]["result"]["enum"] == ["W", "L", "T"]
    assert schemas["CommonOpponentMeetingOut"]["properties"]["result"]["enum"] == ["W", "L", "T"]
    for field in ("team_a_meetings", "team_b_meetings"):
        assert field in schemas["CommonOpponentOut"]["required"]
    published = schemas["CommonOpponentOut"]["properties"]
    assert not any(key in published for key in _OLD_COMMON_OPPONENT_KEYS)


# ---------------------------------------------------------------------------
# persona: fact block, claims, fallback
# ---------------------------------------------------------------------------


def test_fact_block_given_to_claude_describes_the_tie_as_a_tie(
    sport_client: TestClient,
) -> None:
    narrator = FakeNarrator(
        [
            {
                "text": "Look at {rec} in {yr}.",
                "claims": [
                    {"id": "rec", "kind": "record", "team": TIE_TEAM},
                    {"id": "yr", "kind": "year"},
                ],
            }
        ]
    )

    with _wired(narrator):
        body = _team_case(sport_client)

    facts = _fact_block(narrator.calls[0].user_texts[0])
    assert facts["ties"] == 1
    # Kilo Kings met Mike Mustangs twice (#130); the week-2 tie is still a tie.
    mustangs_results = [g["result"] for g in facts["games"] if g["opponent_name"] == TIE_OPPONENT]
    assert mustangs_results == ["T", "W"]
    assert facts["worst_loss"]["opponent_name"] != TIE_OPPONENT

    # The record claim renders the W-L-T record on the first try: one call.
    assert body["narration"]["text"] == f"Look at {TIE_TEAM} 2-1-1 in {YEAR}."
    assert len(narrator.calls) == 1


def test_fallback_narration_for_a_tied_team_states_its_w_l_t_record(
    sport_client: TestClient,
) -> None:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    narrator = FakeNarrator(always=anthropic.APIConnectionError(request=request))

    with _wired(narrator):
        body = _team_case(sport_client)

    assert f"{TIE_TEAM} finished 2-1-1 in {YEAR}" in body["narration"]["text"]
