"""Failing-first tests for issue #165: a rating quoted the way the site
displays it is grounded, scaled by the fact block's own `method`.

apps/web shows a Keener rating scaled and rounded to fixed decimals (2005
Texas `0.005044108672990355` is shown as `5.04`); the scale is
`api.rating_display.RATING_DISPLAY`. A narration repeating the on-screen
number must not fall back.

Every fact block here is the real one `api.persona.service` hands Claude,
built the way the routes build it (`build_team_case`/`build_comparison` ->
`TeamCaseOut`/`ComparisonResultOut.from_dataclass(...)` -> the service's own
`team_case_fact_block_json`/`comparison_fact_block_json`, which leave out
`elo_ledger`, #183) against the committed `cfb_verdict_fixture.sqlite3`. The one derived block
(method removed) is constructed from a real one.

Where `method` sits in the real fact blocks of all three shapes (inspected,
and pinned in `test_fixture_values_these_tests_rely_on`):

* champion: `TeamCaseOut.method`, top level (the champion route returns a
  `TeamCaseOut` for the #1 team).
* team-case: `TeamCaseOut.method`, top level.
* compare: `ComparisonResultOut.method`, top level (issue #152); the nested
  `team_a`/`team_b` carry no `method` of their own.

Real values these tests lean on (2005, keener unless noted):

* Texas `rating` `0.005044108672990355` -> `5.04`; USC `0.004736299273644764`
  -> `4.74`. In Texas's block USC appears only as an `opponent_rating`.
* Texas's `opponent_rating` for Oklahoma `0.0041587932077007525` -> `4.16`.
* Compare `rating_diff` `0.0003078093993455905`: at display precision
  `0.31`; the difference of the two displayed ratings is `0.30`. Both are
  derived (#108) and stay rejected.
* Texas's breakdown `credit` for Colorado `0.10527379400260754` -> `105.27`
  scaled, and its `contribution` `0.0003862939524065964` -> `0.39` scaled.
  Both derived, both rejected.
* Elo Texas `rating` `1933.1932908945062`: Keener's scale would show it as
  `1933193.29`, which an Elo block must not accept.

None of the wrong-answer tokens used below ("5.05", "50.4", "504", "5.0",
"5.040", "0.30", "0.31", "105.27", "0.39", "1933193.29") is a number literal
in its block; that is asserted too, so each rejection is proved against the
display rule rather than being trivially absent.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from cfb_strength.db.connection import get_conn
from cfb_strength.evidence.proof import build_comparison, build_team_case
from fastapi.testclient import TestClient

from api.deps import get_narration_cache, get_narrator, list_all_team_names
from api.main import app
from api.models import ComparisonResultOut, TeamCaseOut
from api.persona.cache import InMemoryNarrationCache
from api.persona.grounding import find_ungrounded_tokens
from api.persona.service import comparison_fact_block_json, team_case_fact_block_json

FIXTURE_DB = Path(__file__).parent / "fixtures" / "cfb_verdict_fixture.sqlite3"
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = get_conn(FIXTURE_DB, read_only=True)
    try:
        yield connection
    finally:
        connection.close()


def _team_case_block(conn: sqlite3.Connection, team: str, method: str, year: int = 2005) -> str:
    case = build_team_case(conn, year, team, method=method, sport="cfb")
    return team_case_fact_block_json(TeamCaseOut.from_dataclass(case))


def _champion_block(conn: sqlite3.Connection, method: str, year: int = 2005) -> str:
    row = conn.execute(
        "SELECT t.school AS school FROM ratings r JOIN teams t ON t.id = r.team_id "
        "WHERE r.year = ? AND r.method = ? AND r.rank = 1 AND r.sport = 'cfb'",
        (year, method),
    ).fetchone()
    return _team_case_block(conn, str(row["school"]), method, year)


def _compare_block(conn: sqlite3.Connection, method: str) -> str:
    comparison = build_comparison(conn, 2005, "Texas", "USC", method=method, sport="cfb")
    return comparison_fact_block_json(ComparisonResultOut.from_dataclass(comparison))


def _check(conn: sqlite3.Connection, response: str, fact_block: str) -> list[str]:
    return find_ungrounded_tokens(response, fact_block, list_all_team_names(conn, "cfb"))


def _literals(fact_block: str) -> set[str]:
    return set(_NUMBER_RE.findall(fact_block))


def test_fixture_values_these_tests_rely_on(conn: sqlite3.Connection) -> None:
    champion = _champion_block(conn, "keener")
    keener_usc = _team_case_block(conn, "USC", "keener")
    keener_compare = _compare_block(conn, "keener")
    elo_texas = _team_case_block(conn, "Texas", "elo")

    # `method` is top level in all three shapes.
    assert json.loads(champion)["method"] == "keener"
    assert json.loads(champion)["team_name"] == "Texas"
    assert json.loads(keener_usc)["method"] == "keener"
    assert json.loads(keener_compare)["method"] == "keener"
    assert "method" not in json.loads(keener_compare)["team_a"]
    assert json.loads(elo_texas)["method"] == "elo"

    assert '"rating":0.005044108672990355' in champion
    assert '"rating":0.004736299273644764' in keener_usc
    assert '"opponent_rating":0.004736299273644764' in champion
    assert '"rating":0.004736299273644764' not in champion
    assert '"opponent_name":"Oklahoma"' in champion
    assert '"opponent_rating":0.0041587932077007525' in champion
    assert '"rating_diff":0.0003078093993455905' in keener_compare
    assert '"credit":0.10527379400260754' in champion
    assert '"contribution":0.0003862939524065964' in champion
    assert '"rating":1933.1932908945062' in elo_texas

    for token in ("5.04", "4.74", "4.16", "5.05", "50.4", "504", "5.0", "5.040", "105.27", "0.39"):
        assert token not in _literals(champion), token
    for token in ("5.04", "4.74", "0.30", "0.31"):
        assert token not in _literals(keener_compare), token
    assert "1933193.29" not in _literals(elo_texas)


# ---------------------------------------------------------------------------
# accepted: a rating or opponent_rating exactly as the card shows it
# ---------------------------------------------------------------------------


def test_keener_champion_rating_at_display_value_is_grounded(conn: sqlite3.Connection) -> None:
    response = "Keener rates Texas at 5.04, and nobody's arguing."

    assert _check(conn, response, _champion_block(conn, "keener")) == []


def test_keener_team_case_rating_at_display_value_is_grounded(conn: sqlite3.Connection) -> None:
    response = "Keener has USC at 4.74 even with that loss."

    assert _check(conn, response, _team_case_block(conn, "USC", "keener")) == []


def test_keener_compare_ratings_at_display_value_are_grounded(conn: sqlite3.Connection) -> None:
    response = "Keener has Texas at 5.04 and USC at 4.74, and Texas beat USC 41-38."

    assert _check(conn, response, _compare_block(conn, "keener")) == []


def test_keener_opponent_rating_at_display_value_is_grounded(conn: sqlite3.Connection) -> None:
    response = "Texas beat Oklahoma 45-12, and Keener had Oklahoma at 4.16."

    assert _check(conn, response, _champion_block(conn, "keener")) == []


# ---------------------------------------------------------------------------
# rejected: anything that is not a rating at exactly the display value
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("response", "flagged"),
    [
        # Wrong value at display precision.
        ("Keener rates Texas at 5.05.", "5.05"),
        # Wrong scale.
        ("Keener rates Texas at 50.4.", "50.4"),
        ("Keener rates Texas at 504.", "504"),
        # Right scale, wrong precision: fewer and more places than the card.
        ("Keener rates Texas at 5.0.", "5.0"),
        ("Keener rates Texas at 5.040.", "5.040"),
    ],
)
def test_keener_rating_not_at_display_value_is_flagged(
    conn: sqlite3.Connection, response: str, flagged: str
) -> None:
    assert flagged in _check(conn, response, _champion_block(conn, "keener"))


@pytest.mark.parametrize(
    ("response", "flagged"),
    [
        # `rating_diff` at display precision.
        ("Texas leads USC by 0.31 in Keener.", "0.31"),
        # The difference of the two displayed ratings (5.04 - 4.74).
        ("Texas leads USC by 0.30 in Keener.", "0.30"),
    ],
)
def test_keener_rating_diff_at_display_precision_is_flagged(
    conn: sqlite3.Connection, response: str, flagged: str
) -> None:
    assert flagged in _check(conn, response, _compare_block(conn, "keener"))


@pytest.mark.parametrize(
    ("response", "flagged"),
    [
        ("Texas banked 105.27 of credit against Colorado.", "105.27"),
        ("Colorado added 0.39 to Texas's rating.", "0.39"),
    ],
)
def test_keener_breakdown_figures_at_display_scale_are_flagged(
    conn: sqlite3.Connection, response: str, flagged: str
) -> None:
    assert flagged in _check(conn, response, _champion_block(conn, "keener"))


def test_elo_block_does_not_accept_keener_scaled_rating(conn: sqlite3.Connection) -> None:
    """The fact block's own `method` picks the scale: an Elo rating shown the
    way Keener's is shown is not what the card displays for Elo."""
    mismatches = _check(
        conn, "Elo rates Texas at 1933193.29.", _team_case_block(conn, "Texas", "elo")
    )

    assert "1933193.29" in mismatches


def test_block_without_method_gets_no_display_allowance(conn: sqlite3.Connection) -> None:
    """Without a `method` there is no scale to apply. #162's rounding still
    applies to the same block."""
    real = _champion_block(conn, "keener")
    data = json.loads(real)
    del data["method"]
    method_less = json.dumps(data, separators=(",", ":"))
    assert '"rating":0.005044108672990355' in method_less

    assert _check(conn, "Keener rates Texas at 5.04.", real) == []
    assert "5.04" in _check(conn, "Keener rates Texas at 5.04.", method_less)
    assert _check(conn, "Keener rates Texas at 0.005.", method_less) == []


def test_block_with_unknown_method_gets_no_display_allowance(conn: sqlite3.Connection) -> None:
    data = json.loads(_champion_block(conn, "keener"))
    data["method"] = "colley"

    assert "5.04" in _check(conn, "Keener rates Texas at 5.04.", json.dumps(data))


# ---------------------------------------------------------------------------
# end to end: a Keener narration quoting the card is served on the first call
# ---------------------------------------------------------------------------


class _ScriptedNarrator:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[list[dict[str, str]]] = []

    def complete(self, *, system: str, messages: list[dict[str, str]]) -> str:
        self.calls.append(messages)
        return self.responses.pop(0)


def test_keener_display_value_narration_is_served_on_the_first_call(client: TestClient) -> None:
    response = "Keener rates Texas at 5.04 after a 13-0 run, and nobody's arguing."
    narrator = _ScriptedNarrator([response])
    app.dependency_overrides[get_narration_cache] = lambda: InMemoryNarrationCache()
    app.dependency_overrides[get_narrator] = lambda: narrator
    try:
        http_response = client.post(
            "/api/verdict/champion", json={"year": 2005, "method": "keener"}
        )
    finally:
        app.dependency_overrides.pop(get_narration_cache, None)
        app.dependency_overrides.pop(get_narrator, None)

    assert http_response.status_code == 200, http_response.json()
    assert http_response.json()["narration"]["text"] == response
    assert len(narrator.calls) == 1
