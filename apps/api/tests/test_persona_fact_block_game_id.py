"""Failing-first tests for issue #218: `game_id` is published to clients but
never reaches the narrator or the grounding check.

#218 added a required `game_id: int` (`games.id`, a nine-digit CFBD number)
to `OpponentResultOut`, `HeadToHeadMeetingOut` and
`CommonOpponentMeetingOut` so apps/web can key its game lists on it. The
persona fact block must stay byte-identical to what it was before #218, for
the same reason #183 kept the Elo ledger out: any number in the fact block
enters grounding's accepted-number set, quietly licensing the narrator to
quote figures nobody decided it should narrate. So `api.persona.service`'s
`team_case_fact_block_json` / `comparison_fact_block_json` exclude `game_id`
from every per-game record, so the excluded block equals the pre-#218 block
and `PROMPT_VERSION` does not move. (When #218 landed the cache key did not
cover the fact block, so that byte equality was also what kept every cached
narration valid; since #145 the key hashes the block, so the equality is
purely about what Claude and the grounding check see.)

Every block here is the real one the service hands Claude, built the way the
routes build it from the committed `cfb_verdict_fixture.sqlite3`. Where
`game_id` lives, and which fixture block exercises each spot (measured):

* `TeamCaseOut.games` / `quality_wins` / `worst_loss`: 2005 Texas has 13
  games (two of them against Colorado, `games.id` 252880251 and 253370251)
  and 4 quality wins under keener (3 under elo) but, at 13-0, no
  `worst_loss`; 2005 USC (12-1) has one, the Rose Bowl.
* `ComparisonResultOut.team_a/team_b.quality_wins/worst_loss` and
  `head_to_head.meetings`: Texas vs USC 2005 has one meeting (260040030) and
  no common opponents; USC's side carries the `worst_loss`.
* `common_opponents[*].team_a_meetings/team_b_meetings`: Texas vs Colorado
  2005 shares four opponents (Missouri, Oklahoma State, Kansas, Texas A&M),
  one meeting per side each, and its head-to-head has both Colorado games.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from cfb_strength.db.connection import get_conn
from cfb_strength.evidence.proof import build_comparison, build_team_case
from fastapi.testclient import TestClient

from api.deps import get_narration_cache, get_narrator
from api.main import app
from api.models import ComparisonResultOut, Method, TeamCaseOut
from api.persona.cache import InMemoryNarrationCache
from api.persona.service import comparison_fact_block_json, team_case_fact_block_json

FIXTURE_DB = Path(__file__).parent / "fixtures" / "cfb_verdict_fixture.sqlite3"

# The block Claude saw before #218 left `elo_ledger` out (#183) and nothing
# else; dumping with only that exclusion and then stripping `game_id`
# recursively is therefore exactly the pre-#218 block.
_PRE_218_EXCLUDE_TEAM_CASE: dict[str, bool] = {"elo_ledger": True}
_PRE_218_EXCLUDE_COMPARISON: dict[str, dict[str, bool]] = {
    "team_a": {"elo_ledger": True},
    "team_b": {"elo_ledger": True},
}

# A `games.id` in the committed CFB fixture is nine digits; no other fact-block
# number is that long (scores, weeks, ranks, years, team ids are all shorter),
# so its absence from the raw text is a second, representation-level check.
_NINE_DIGITS = re.compile(r"(?<![\d.])\d{9}(?![\d.])")


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = get_conn(FIXTURE_DB, read_only=True)
    try:
        yield connection
    finally:
        connection.close()


def _team_case(conn: sqlite3.Connection, team: str, method: Method) -> TeamCaseOut:
    return TeamCaseOut.from_dataclass(build_team_case(conn, 2005, team, method=method, sport="cfb"))


def _comparison(conn: sqlite3.Connection, team_a: str, team_b: str) -> ComparisonResultOut:
    return ComparisonResultOut.from_dataclass(
        build_comparison(conn, 2005, team_a, team_b, method="keener", sport="cfb")
    )


def _keys(value: Any) -> Iterator[str]:
    """Every key anywhere in a parsed JSON document."""
    if isinstance(value, dict):
        for key, nested in value.items():
            yield key
            yield from _keys(nested)
    elif isinstance(value, list):
        for item in value:
            yield from _keys(item)


def _strip_game_id(value: Any) -> Any:
    """`value` with every `game_id` key removed, at any depth, order kept."""
    if isinstance(value, dict):
        return {k: _strip_game_id(v) for k, v in value.items() if k != "game_id"}
    if isinstance(value, list):
        return [_strip_game_id(item) for item in value]
    return value


# In pydantic's compact JSON each per-game record starts `{"game_id":NNN,`:
# the field is declared first on all three models and is never the last one.
_GAME_ID_MEMBER = re.compile(r'"game_id":\d+,')


def _strip_game_id_text(dumped: str) -> str:
    """`dumped` with every `"game_id":NNN,` member cut out of the raw text,
    so the result is comparable byte for byte with a pydantic dump (a
    `json.loads`/`json.dumps` round trip would reformat floats:
    pydantic writes `0.000057931121516963224`, `json` writes `5.79e-05`).
    Asserts the textual cut removed exactly the keys a structural walk finds,
    so the comparison cannot pass by stripping too little."""
    structural = sum(1 for key in _keys(json.loads(dumped)) if key == "game_id")
    stripped, cut = _GAME_ID_MEMBER.subn("", dumped)
    assert cut == structural and cut > 0, (cut, structural)
    assert "game_id" not in set(_keys(json.loads(stripped)))
    assert json.loads(stripped) == _strip_game_id(json.loads(dumped))
    return stripped


# ---------------------------------------------------------------------------
# (a) team-case blocks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["keener", "elo"])
def test_team_case_fact_block_has_no_game_id_anywhere(
    conn: sqlite3.Connection, method: Method
) -> None:
    case = _team_case(conn, "Texas", method)
    assert case.games and case.quality_wins  # the lists being checked are non-empty
    assert all(g.game_id > 0 for g in case.games)  # the model does carry it

    block = team_case_fact_block_json(case)
    parsed = json.loads(block)

    assert "game_id" not in set(_keys(parsed))
    assert _NINE_DIGITS.search(block) is None
    assert "elo_ledger" not in parsed  # #183's exclusion is intact


def test_team_case_fact_block_keeps_the_games_with_their_other_fields(
    conn: sqlite3.Connection,
) -> None:
    parsed = json.loads(team_case_fact_block_json(_team_case(conn, "Texas", "keener")))

    assert len(parsed["games"]) == 13
    assert len(parsed["quality_wins"]) == 4
    assert parsed["worst_loss"] is None
    colorado = [g for g in parsed["games"] if g["opponent_name"] == "Colorado"]
    assert len(colorado) == 2
    for game in parsed["games"] + parsed["quality_wins"]:
        assert set(game) == {
            "opponent_team_id",
            "opponent_name",
            "opponent_rank",
            "opponent_rating",
            "result",
            "team_score",
            "opponent_score",
            "week",
            "season_type",
            "neutral_site",
        }


def test_team_case_fact_block_worst_loss_has_no_game_id(conn: sqlite3.Connection) -> None:
    """2005 USC's block is the one with a `worst_loss` (Texas, 38-41)."""
    case = _team_case(conn, "USC", "keener")
    assert case.worst_loss is not None and case.worst_loss.game_id == 260040030

    parsed = json.loads(team_case_fact_block_json(case))

    assert parsed["worst_loss"]["opponent_name"] == "Texas"
    assert "game_id" not in parsed["worst_loss"]
    assert "game_id" not in set(_keys(parsed))


# ---------------------------------------------------------------------------
# (b) comparison blocks
# ---------------------------------------------------------------------------


def test_comparison_fact_block_texas_usc_has_no_game_id_anywhere(
    conn: sqlite3.Connection,
) -> None:
    comparison = _comparison(conn, "Texas", "USC")
    assert [m.game_id for m in comparison.head_to_head.meetings] == [260040030]
    assert comparison.team_a.quality_wins and comparison.team_b.worst_loss is not None

    block = comparison_fact_block_json(comparison)
    parsed = json.loads(block)

    assert "game_id" not in set(_keys(parsed))
    assert _NINE_DIGITS.search(block) is None
    assert parsed["head_to_head"]["played"] is True
    (meeting,) = parsed["head_to_head"]["meetings"]
    assert set(meeting) == {
        "week",
        "season_type",
        "neutral_site",
        "home_team",
        "away_team",
        "home_points",
        "away_points",
        "winner",
    }
    assert len(parsed["team_a"]["quality_wins"]) == 4
    assert parsed["team_b"]["worst_loss"]["opponent_name"] == "Texas"
    assert "game_id" not in parsed["team_b"]["worst_loss"]
    for side in ("team_a", "team_b"):
        assert "elo_ledger" not in parsed[side]


def test_comparison_fact_block_texas_colorado_common_opponents_have_no_game_id(
    conn: sqlite3.Connection,
) -> None:
    comparison = _comparison(conn, "Texas", "Colorado")
    assert {c.opponent_name for c in comparison.common_opponents} == {
        "Missouri",
        "Oklahoma State",
        "Kansas",
        "Texas A&M",
    }
    assert [m.game_id for m in comparison.head_to_head.meetings] == [252880251, 253370251]

    block = comparison_fact_block_json(comparison)
    parsed = json.loads(block)

    assert "game_id" not in set(_keys(parsed))
    assert _NINE_DIGITS.search(block) is None
    assert len(parsed["common_opponents"]) == 4
    assert len(parsed["head_to_head"]["meetings"]) == 2
    for common in parsed["common_opponents"]:
        for side in ("team_a_meetings", "team_b_meetings"):
            assert common[side], (common["opponent_name"], side)
            for meeting in common[side]:
                assert set(meeting) == {
                    "result",
                    "team_score",
                    "opponent_score",
                    "week",
                    "season_type",
                }


# ---------------------------------------------------------------------------
# (c) byte for byte, the block is the pre-#218 block
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("team", "method"), [("Texas", "keener"), ("Texas", "elo"), ("USC", "keener")]
)
def test_team_case_fact_block_is_the_pre_218_block_byte_for_byte(
    conn: sqlite3.Connection, team: str, method: Method
) -> None:
    case = _team_case(conn, team, method)
    pre_218 = _strip_game_id_text(case.model_dump_json(exclude=_PRE_218_EXCLUDE_TEAM_CASE))

    assert team_case_fact_block_json(case) == pre_218


@pytest.mark.parametrize("team_b", ["USC", "Colorado"])
def test_comparison_fact_block_is_the_pre_218_block_byte_for_byte(
    conn: sqlite3.Connection, team_b: str
) -> None:
    comparison = _comparison(conn, "Texas", team_b)
    pre_218 = _strip_game_id_text(comparison.model_dump_json(exclude=_PRE_218_EXCLUDE_COMPARISON))

    assert comparison_fact_block_json(comparison) == pre_218


# ---------------------------------------------------------------------------
# (d) the HTTP response still carries game_id; only the narrator's copy
#     leaves it out
# ---------------------------------------------------------------------------


class _RecordingNarrator:
    """Records every user message it is handed and answers with a line that
    has no numbers and no team names, so grounding always passes."""

    def __init__(self) -> None:
        self.messages: list[str] = []

    def complete(self, *, system: str, messages: list[dict[str, str]]) -> str:
        self.messages.extend(m["content"] for m in messages)
        return "Solid case, no notes."


@contextmanager
def _wired(narrator: _RecordingNarrator) -> Iterator[None]:
    app.dependency_overrides[get_narration_cache] = lambda: InMemoryNarrationCache()
    app.dependency_overrides[get_narrator] = lambda: narrator
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_narration_cache, None)
        app.dependency_overrides.pop(get_narrator, None)


def _fact_block_of(user_message: str) -> Any:
    """The JSON between `build_user_message`'s FACT BLOCK header and its
    trailing `contested:` line."""
    header = "FACT BLOCK (JSON):\n"
    body = user_message[user_message.index(header) + len(header) :]
    return json.loads(body[: body.rindex("\n\ncontested:")])


def test_team_case_response_carries_game_id_but_the_narrator_never_sees_it(
    client: TestClient,
) -> None:
    narrator = _RecordingNarrator()
    with _wired(narrator):
        response = client.post("/api/verdict/team-case", json={"year": 2005, "team": "Texas"})

    assert response.status_code == 200, response.text
    evidence = response.json()["evidence"]
    assert len(evidence["games"]) == 13
    for game in evidence["games"] + evidence["quality_wins"]:
        assert isinstance(game["game_id"], int) and game["game_id"] > 0
    assert sorted(g["game_id"] for g in evidence["games"] if g["opponent_name"] == "Colorado") == [
        252880251,
        253370251,
    ]

    (user_message,) = narrator.messages
    assert "game_id" not in set(_keys(_fact_block_of(user_message)))
    assert _NINE_DIGITS.search(user_message) is None


def test_compare_response_carries_game_id_but_the_narrator_never_sees_it(
    client: TestClient,
) -> None:
    narrator = _RecordingNarrator()
    with _wired(narrator):
        response = client.post(
            "/api/verdict/compare",
            json={"year": 2005, "team_a": "Texas", "team_b": "Colorado"},
        )

    assert response.status_code == 200, response.text
    evidence = response.json()["evidence"]
    assert [m["game_id"] for m in evidence["head_to_head"]["meetings"]] == [252880251, 253370251]
    assert evidence["team_b"]["worst_loss"]["game_id"] > 0
    for common in evidence["common_opponents"]:
        for side in ("team_a_meetings", "team_b_meetings"):
            for meeting in common[side]:
                assert isinstance(meeting["game_id"], int) and meeting["game_id"] > 0

    (user_message,) = narrator.messages
    assert "game_id" not in set(_keys(_fact_block_of(user_message)))
    assert _NINE_DIGITS.search(user_message) is None
