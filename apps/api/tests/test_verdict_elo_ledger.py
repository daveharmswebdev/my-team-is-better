"""Issue #183: an Elo rating ships with its shown work, the `elo_ledger`.

The engine records every game's Elo update while it computes a
season-isolated Elo rating and stores it (`elo_ledger_steps`,
`elo_ledger_configs`). `cfb_strength.evidence.proof` reads it back onto
`TeamCase.elo_ledger` / `ComparisonTeamSummary.elo_ledger`. This file pins
the API seam over that data, through the HTTP layer and against the real,
regenerated `cfb_verdict_fixture.sqlite3`:

- **The chain is exact after the JSON round-trip.** Python floats serialize
  to JSON by shortest repr and parse back bit for bit, so the engine's exact
  identities (`rating_after == rating_before + shift`, each step starting
  where the last ended, the last step landing on the rating) still hold with
  `==` on the client side. A mapping slip in `EloGameStepOut.from_dataclass`
  (say, `shift` read from `rating_gap`) breaks them.
- **An independent calculator.** The Elo formulas are re-derived below in
  plain `math`, deliberately without importing `cfb_strength.ratings`
  (which apps/api's tests do not import). Each step's `win_expectancy`,
  `mov_multiplier` and `shift` must come out of its own fields and the
  ledger's constants. That is what makes the hover panel checkable rather
  than decorative.
- **Absence is `null`, not an empty ledger.** Keener has a `rating_breakdown`
  instead, and `elo_career` records no ledger (#183 leaves career offseason
  reversion out of scope), so both serve `elo_ledger: null`.
- **The narrator never sees it.** The persona fact block stays byte-identical
  to before #183: ledger figures are not narrated (#175's open question), so
  they must not reach the prompt or grounding's accepted-number set.
- **The published schema.** `apps/web` builds against `EloLedgerOut` /
  `EloGameStepOut` from `/openapi.json`, in exactly the field order below.
"""

from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from cfb_strength.db.connection import get_conn
from fastapi.testclient import TestClient
from fixtures.method_fixture import TEAM_A, TEAM_B, YEAR, make_method_fixture_db
from pydantic.main import IncEx

from api.deps import get_db_conn, get_narration_cache, get_narrator
from api.main import app
from api.models import ComparisonResultOut, TeamCaseOut
from api.persona.cache import InMemoryNarrationCache

FIXTURE_DB = Path(__file__).parent / "fixtures" / "cfb_verdict_fixture.sqlite3"

LEDGER_FIELDS = ["starting_rating", "k", "hfa", "scale", "mov_scale", "mov_autocorr", "steps"]
STEP_FIELDS = [
    "game_number",
    "week",
    "season_type",
    "start_date",
    "opponent_team_id",
    "opponent_name",
    "venue",
    "team_points",
    "opponent_points",
    "result",
    "rating_before",
    "opponent_rating_before",
    "home_field_adjustment",
    "rating_gap",
    "win_expectancy",
    "mov_multiplier",
    "shift",
    "rating_after",
]
RESULT_SCORE = {"W": 1.0, "T": 0.5, "L": 0.0}
TOLERANCE = 1e-9


class _RecordingNarrator:
    """Grounds on the first try (no numbers, no team names) and records the
    messages it was handed, so the fact block can be read back out."""

    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []

    def complete(self, *, system: str, messages: list[dict[str, str]]) -> str:
        self.calls.append([dict(m) for m in messages])
        return "Solid case, no notes."


def _team_case(client: TestClient, team: str, method: str) -> Any:
    response = client.post(
        "/api/verdict/team-case", json={"year": 2005, "team": team, "method": method}
    )
    assert response.status_code == 200, response.json()
    return response.json()["evidence"]


def _compare(client: TestClient, method: str) -> Any:
    response = client.post(
        "/api/verdict/compare",
        json={"year": 2005, "team_a": "Texas", "team_b": "USC", "method": method},
    )
    assert response.status_code == 200, response.json()
    return response.json()["evidence"]


def _fixture_ledger_config(year: int, method: str) -> dict[str, float]:
    conn = get_conn(FIXTURE_DB, read_only=True)
    try:
        row = conn.execute(
            """
            SELECT starting_rating, k, hfa, scale, mov_scale, mov_autocorr
            FROM elo_ledger_configs WHERE year = ? AND method = ? AND sport = 'cfb'
            """,
            (year, method),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, f"no elo_ledger_configs row for {year}/{method}"
    return {key: float(row[key]) for key in row.keys()}


def _assert_chain_is_exact(ledger: dict[str, Any], rating: float) -> None:
    steps = ledger["steps"]
    assert steps, "an elo-rated team must have at least one ledger step"
    assert [s["game_number"] for s in steps] == list(range(1, len(steps) + 1))
    assert steps[0]["rating_before"] == ledger["starting_rating"]
    for earlier, later in zip(steps, steps[1:], strict=False):
        assert later["rating_before"] == earlier["rating_after"], later["game_number"]
    for step in steps:
        assert step["rating_after"] == step["rating_before"] + step["shift"], step["game_number"]
    assert steps[-1]["rating_after"] == rating


def _assert_steps_recompute(ledger: dict[str, Any]) -> None:
    """The independent calculator: plain math, not `cfb_strength.ratings`."""
    k = ledger["k"]
    scale = ledger["scale"]
    mov_scale = ledger["mov_scale"]
    mov_autocorr = ledger["mov_autocorr"]
    for step in ledger["steps"]:
        label = f"game {step['game_number']}"
        gap = step["rating_gap"]
        result_score = RESULT_SCORE[step["result"]]

        win_expectancy = 1.0 / (math.pow(10.0, -gap / scale) + 1.0)
        assert step["win_expectancy"] == pytest.approx(win_expectancy, abs=TOLERANCE), label

        margin = step["team_points"] - step["opponent_points"]
        if step["result"] == "T":
            denom = 1.0
        else:
            winner_gap = gap if step["result"] == "W" else -gap
            denom = max(winner_gap * mov_autocorr + mov_scale, mov_scale / 2)
        mov = math.log(max(abs(margin), 1) + 1) * (mov_scale / denom)
        assert step["mov_multiplier"] == pytest.approx(mov, abs=TOLERANCE), label

        shift = k * step["mov_multiplier"] * (result_score - step["win_expectancy"])
        assert step["shift"] == pytest.approx(shift, abs=TOLERANCE), label

        # And the step's result agrees with its own score.
        expected_result = "W" if margin > 0 else "L" if margin < 0 else "T"
        assert step["result"] == expected_result, label


# ---------------------------------------------------------------------------
# the elo team case
# ---------------------------------------------------------------------------


def test_elo_team_case_ledger_chain_lands_on_the_rating(client: TestClient) -> None:
    body = _team_case(client, "Texas", "elo")
    ledger = body["elo_ledger"]

    assert ledger is not None
    assert list(ledger) == LEDGER_FIELDS
    assert all(list(step) == STEP_FIELDS for step in ledger["steps"])
    assert len(ledger["steps"]) == body["wins"] + body["losses"] + body["ties"]
    _assert_chain_is_exact(ledger, body["rating"])


def test_elo_team_case_ledger_constants_match_the_stored_config(client: TestClient) -> None:
    ledger = _team_case(client, "Texas", "elo")["elo_ledger"]

    assert {key: ledger[key] for key in LEDGER_FIELDS[:-1]} == _fixture_ledger_config(2005, "elo")


def test_elo_team_case_ledger_names_every_opponent(client: TestClient) -> None:
    body = _team_case(client, "Texas", "elo")
    steps = body["elo_ledger"]["steps"]

    assert all(step["opponent_name"] for step in steps)
    assert {s["opponent_team_id"] for s in steps} == {g["opponent_team_id"] for g in body["games"]}
    usc = [s for s in steps if s["opponent_name"] == "USC"]
    assert len(usc) == 1
    assert (usc[0]["team_points"], usc[0]["opponent_points"], usc[0]["result"]) == (41, 38, "W")
    assert usc[0]["venue"] == "neutral"


def test_elo_team_case_ledger_steps_recompute_from_their_own_fields(client: TestClient) -> None:
    _assert_steps_recompute(_team_case(client, "Texas", "elo")["elo_ledger"])


def test_elo_champion_carries_the_ledger(client: TestClient) -> None:
    response = client.post("/api/verdict/champion", json={"year": 2005, "method": "elo"})
    assert response.status_code == 200, response.json()
    body = response.json()["evidence"]

    assert body["elo_ledger"] is not None
    _assert_chain_is_exact(body["elo_ledger"], body["rating"])


# ---------------------------------------------------------------------------
# the comparison, and the methods with no ledger
# ---------------------------------------------------------------------------


def test_elo_compare_gives_each_team_its_own_ledger(client: TestClient) -> None:
    comparison = _compare(client, "elo")
    team_a = comparison["team_a"]
    team_b = comparison["team_b"]

    for team in (team_a, team_b):
        ledger = team["elo_ledger"]
        assert ledger is not None, team["team_name"]
        assert list(ledger) == LEDGER_FIELDS
        assert len(ledger["steps"]) == team["wins"] + team["losses"] + team["ties"]
        _assert_chain_is_exact(ledger, team["rating"])
        _assert_steps_recompute(ledger)

    # Each team's own path, not one ledger copied onto both sides.
    assert team_a["elo_ledger"]["steps"] != team_b["elo_ledger"]["steps"]
    assert team_a["elo_ledger"] == _team_case(client, "Texas", "elo")["elo_ledger"]
    assert team_b["elo_ledger"] == _team_case(client, "USC", "elo")["elo_ledger"]


def test_keener_verdicts_have_no_ledger(client: TestClient) -> None:
    assert _team_case(client, "Texas", "keener")["elo_ledger"] is None
    champion = client.post("/api/verdict/champion", json={"year": 2005}).json()["evidence"]
    assert champion["elo_ledger"] is None
    comparison = _compare(client, "keener")
    assert comparison["team_a"]["elo_ledger"] is None
    assert comparison["team_b"]["elo_ledger"] is None


@pytest.fixture
def method_client(tmp_path: Path) -> Iterator[TestClient]:
    """The committed fixture bakes no `elo_career` (issue #98), so an
    `elo_career` request against it is a 404 that says nothing about the
    ledger. `fixtures/method_fixture.py` rates every registered method."""
    db_path = make_method_fixture_db(tmp_path)

    def _override() -> Iterator[sqlite3.Connection]:
        conn = get_conn(db_path, read_only=True)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db_conn] = _override
    app.dependency_overrides[get_narration_cache] = lambda: InMemoryNarrationCache()
    app.dependency_overrides[get_narrator] = lambda: _RecordingNarrator()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db_conn, None)
        app.dependency_overrides.pop(get_narration_cache, None)
        app.dependency_overrides.pop(get_narrator, None)


def test_elo_career_verdicts_have_no_ledger(method_client: TestClient) -> None:
    case = method_client.post(
        "/api/verdict/team-case", json={"year": YEAR, "team": TEAM_A, "method": "elo_career"}
    )
    assert case.status_code == 200, case.json()
    assert "elo_ledger" in case.json()["evidence"]
    assert case.json()["evidence"]["elo_ledger"] is None

    compare = method_client.post(
        "/api/verdict/compare",
        json={"year": YEAR, "team_a": TEAM_A, "team_b": TEAM_B, "method": "elo_career"},
    )
    assert compare.status_code == 200, compare.json()
    evidence = compare.json()["evidence"]
    assert "elo_ledger" in evidence["team_a"] and evidence["team_a"]["elo_ledger"] is None
    assert "elo_ledger" in evidence["team_b"] and evidence["team_b"]["elo_ledger"] is None


# ---------------------------------------------------------------------------
# the narrator's fact block
# ---------------------------------------------------------------------------


def _fact_block(narrator: _RecordingNarrator) -> str:
    assert len(narrator.calls) == 1
    content = narrator.calls[0][0]["content"]
    prefix = "FACT BLOCK (JSON):\n"
    assert content.startswith(prefix)
    return content[len(prefix) : content.rindex("\n\ncontested: ")]


def _keys_at_any_depth(value: Any) -> set[str]:
    if isinstance(value, dict):
        keys = set(value)
        for child in value.values():
            keys |= _keys_at_any_depth(child)
        return keys
    if isinstance(value, list):
        found: set[str] = set()
        for child in value:
            found |= _keys_at_any_depth(child)
        return found
    return set()


def _without_game_id(value: Any) -> Any:
    """`value` with every `game_id` key (#218) dropped at any depth, order kept."""
    if isinstance(value, dict):
        return {k: _without_game_id(v) for k, v in value.items() if k != "game_id"}
    if isinstance(value, list):
        return [_without_game_id(child) for child in value]
    return value


@pytest.fixture
def recording_client(client: TestClient) -> Iterator[tuple[TestClient, _RecordingNarrator]]:
    narrator = _RecordingNarrator()
    app.dependency_overrides[get_narrator] = lambda: narrator
    yield client, narrator


def test_team_case_fact_block_excludes_the_ledger(
    recording_client: tuple[TestClient, _RecordingNarrator],
) -> None:
    client, narrator = recording_client
    evidence = _team_case(client, "Texas", "elo")
    assert evidence["elo_ledger"] is not None  # otherwise this test proves nothing

    fact_block = _fact_block(narrator)

    assert "elo_ledger" not in _keys_at_any_depth(json.loads(fact_block))
    # Since #218 the response also carries each game's `game_id`, which the
    # fact block leaves out too (`tests/test_persona_fact_block_game_id.py`);
    # this exclusion is spelled out here, independently of the service's own.
    expected = TeamCaseOut.model_validate(evidence).model_dump_json(
        exclude={
            "elo_ledger": True,
            "games": {"__all__": {"game_id"}},
            "quality_wins": {"__all__": {"game_id"}},
            "worst_loss": {"game_id"},
        }
    )
    assert fact_block == expected
    assert json.loads(fact_block) == _without_game_id(
        {k: v for k, v in evidence.items() if k != "elo_ledger"}
    )


def test_comparison_fact_block_excludes_both_ledgers(
    recording_client: tuple[TestClient, _RecordingNarrator],
) -> None:
    client, narrator = recording_client
    evidence = _compare(client, "elo")
    assert evidence["team_a"]["elo_ledger"] is not None
    assert evidence["team_b"]["elo_ledger"] is not None

    fact_block = _fact_block(narrator)

    assert "elo_ledger" not in _keys_at_any_depth(json.loads(fact_block))
    # `game_id` (#218) is left out alongside the ledgers; see the team-case test.
    side_exclude: dict[str, IncEx | bool] = {
        "elo_ledger": True,
        "quality_wins": {"__all__": {"game_id"}},
        "worst_loss": {"game_id"},
    }
    expected = ComparisonResultOut.model_validate(evidence).model_dump_json(
        exclude={
            "team_a": side_exclude,
            "team_b": side_exclude,
            "head_to_head": {"meetings": {"__all__": {"game_id"}}},
            "common_opponents": {
                "__all__": {
                    "team_a_meetings": {"__all__": {"game_id"}},
                    "team_b_meetings": {"__all__": {"game_id"}},
                }
            },
        }
    )
    assert fact_block == expected
    stripped = dict(evidence)
    for side in ("team_a", "team_b"):
        stripped[side] = {k: v for k, v in evidence[side].items() if k != "elo_ledger"}
    assert json.loads(fact_block) == _without_game_id(stripped)


# ---------------------------------------------------------------------------
# the published schema
# ---------------------------------------------------------------------------


def _nullable_ref(prop: dict[str, Any]) -> set[str]:
    return {option.get("$ref") or option.get("type") for option in prop["anyOf"]}


def test_openapi_publishes_the_ledger_models() -> None:
    schemas = app.openapi()["components"]["schemas"]

    ledger = schemas["EloLedgerOut"]
    assert list(ledger["properties"]) == LEDGER_FIELDS
    assert set(ledger["required"]) == set(LEDGER_FIELDS)
    assert ledger["properties"]["steps"]["items"] == {"$ref": "#/components/schemas/EloGameStepOut"}

    step = schemas["EloGameStepOut"]
    assert list(step["properties"]) == STEP_FIELDS
    assert set(step["required"]) == set(STEP_FIELDS)
    assert step["properties"]["venue"]["enum"] == ["home", "away", "neutral"]
    assert step["properties"]["result"]["enum"] == ["W", "L", "T"]
    assert _nullable_ref(step["properties"]["week"]) == {"integer", "null"}
    assert _nullable_ref(step["properties"]["start_date"]) == {"string", "null"}

    for owner in ("TeamCaseOut", "ComparisonTeamSummaryOut"):
        properties = schemas[owner]["properties"]
        names = list(properties)
        assert names[names.index("rating_breakdown") + 1] == "elo_ledger", owner
        assert _nullable_ref(properties["elo_ledger"]) == {
            "#/components/schemas/EloLedgerOut",
            "null",
        }, owner
        assert "elo_ledger" in schemas[owner]["required"], owner
