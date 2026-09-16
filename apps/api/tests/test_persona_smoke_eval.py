"""Architecture Brief §8's persona smoke eval, as a test (issues #109, #293).

For each of the seven CFB golden years this posts `POST /api/verdict/champion
{"year": Y}`, and for 2005 USC (12-1, its one loss to Texas) `POST
/api/verdict/team-case`, through the real app, with:

- the **production narrator**, resolved by calling `api.deps.get_narrator()`
  itself (so a `ClaudeNarrator` calling the real `claude-haiku-4-5`), wrapped
  only in a pass-through `RecordingNarrator` that records every call;
- the committed seven-year fixture db and an `InMemoryNarrationCache`, both
  from the shared `client` fixture (tests/conftest.py).

**The canary comes first.** Before any Claude call, each test runs the judge
on a planted invalid submission for its own fact block (the team and a typed
record, no claims) and asserts it is rejected. The judge below is the
production validator, so without the canary a validator or judge that stopped
rejecting anything would make every property-2 check pass silently.
`test_persona_smoke_eval_checks.py` pins that the canary's fact block is the
one the route narrates.

Then it asserts §8's properties on the served narration, all reported
together:

1. **Correct #1 named.** The evidence's `team_name` is the expected team, and
   the narration names it as itself (leftmost-longest, so "Texas Tech" never
   counts as naming "Texas").
2. **Grounded, by the production validator.** Every recorded
   `submit_narration` call is re-checked with
   `api.persona.claims.check_and_render` against the fact block that call
   carried and the fixture's CFB catalog, and a valid call's rendering must be
   exactly the served text. The eval has no number matcher of its own any
   more: the old one disagreed with production in both directions (#293), and
   loss order needs no check now that the renderer prints every score
   winner-first.
3. **Length bounded.** 1-4 sentences, at most 700 characters.
4. **No banned-word hits.** Profanity and slurs as exact word forms, plus real
   AI disclaimers.
5. **Served by the narrator, not the fallback.** The served text is never the
   templated fallback, and never text the eval can't trace to a recorded valid
   call.

**Measurements that never fail a test** (founder decision C on #199), printed
per narration and as rates in one summary line at the end of the module's run:
timing/venue wording the narrator typed itself (over the raw tool-call text
with its placeholders removed), a when/where that reads as covering two games,
served narrations over the prompt's three sentences, rejections for a
lowercase block team ("rice" for Rice), and first / retry / fallback counts
with total Claude calls. The summary names `PROMPT_VERSION` and
`GROUNDING_VERSION`. The judge, the properties and the measurements live in
`tests/fixtures/persona_eval.py`, unit-tested offline, in CI, by
`tests/test_persona_smoke_eval_checks.py`.

**Key.** Gated on `ANTHROPIC_API_KEY` alone, as `api.config` resolves it: from
the environment, or through `load_dotenv` from `apps/api/.env` (or the file
named by `MY_TEAM_IS_BETTER_API_ENV_FILE`), which never overrides a variable
already set. CI has no such secret by decision (#203), so the CI step reports
these tests skipped.

**Postgres.** `api.main` imports `DATABASE_URL`, and its lifespan connects to
Postgres when it is set. This eval does not reach Postgres, for two reasons:
the `client` fixture overrides the narration cache with an
`InMemoryNarrationCache`, and the `TestClient` is not used as a context
manager, so the lifespan never runs. Keep `DATABASE_URL` unset anyway. Run it
from `apps/api` with the key exported and `-s` to see the per-narration lines
and the summary:

    env -u DATABASE_URL -u MY_TEAM_IS_BETTER_API_ENV_FILE \\
        uv run pytest -q -rs -s tests/test_persona_smoke_eval.py
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from fixtures.claim_blocks import cfb_catalog, cfb_team_case_block
from fixtures.persona_eval import (
    NarrationRecord,
    RecordingNarrator,
    build_record,
    contested_disclosure_words,
    format_record,
    format_summary,
    judge_narration,
    judge_planted_invalid,
    section_8_violations,
    summarize,
)

from api.config import ANTHROPIC_API_KEY, PROMPT_VERSION
from api.deps import get_narrator
from api.main import app
from api.models import TeamCaseOut
from api.persona.claims import GROUNDING_VERSION
from api.persona.claude_client import MODEL, ClaudeNarrator
from api.persona.fallback import team_case_fallback_text
from api.persona.prompt import build_user_message
from api.persona.service import team_case_fact_block_json

# The Keener #1 per golden year, as the PRD's golden dataset and the fixture
# db both have it (2003 and 2017 are the contested seasons).
EXPECTED_KEENER_NUMBER_ONE: dict[int, str] = {
    2001: "Miami",
    2003: "LSU",
    2004: "USC",
    2005: "Texas",
    2013: "Florida State",
    2017: "Alabama",
    2019: "LSU",
}

# The CFB entry of `api.config.CONTESTED_YEARS`, restated rather than imported
# so a change to that set shows up here as a red eval instead of silently
# moving the target. This eval is CFB-only; contested years are per league
# (#151), and the NFL entry is covered by test_verdict_contested_by_sport.py.
EXPECTED_CONTESTED_YEARS = {2003, 2017}

# The team case with a loss (issue #228): 2005 USC, 12-1, whose one loss is
# 38-41 to Texas in the postseason. Pinned against the fixture in the test
# itself, so a fixture change fails loudly rather than quietly changing what
# the eval narrates.
TEAM_CASE_YEAR = 2005
TEAM_CASE_TEAM = "USC"
TEAM_CASE_LOSSES = [("Texas", 38, 41)]

_NO_KEY = pytest.mark.skipif(
    not ANTHROPIC_API_KEY,
    reason=(
        "persona smoke eval requires ANTHROPIC_API_KEY (it makes real "
        f"{MODEL} calls); unset, so skipped"
    ),
)


@pytest.fixture(scope="module")
def eval_records() -> Iterator[list[NarrationRecord]]:
    """Every narration this module's run judged, for the one summary line
    printed at the end. A skipped test never requests it."""
    records: list[NarrationRecord] = []
    yield records
    print(
        format_summary(
            summarize(records),
            prompt_version=PROMPT_VERSION,
            grounding_version=GROUNDING_VERSION,
        )
    )


def _assert_the_judge_rejects_the_planted_submission(fact_block_json: str) -> None:
    judgement = judge_planted_invalid(
        fact_block_json, cfb_catalog(), fallback_text="(the canary has no fallback)"
    )
    assert any(v.startswith("grounded:") for v in judgement.violations), (
        "the judge accepted a planted invalid submission (a typed number, no claims), so "
        f"property 2 would be vacuous; violations: {judgement.violations!r}"
    )


def _recording_production_narrator() -> RecordingNarrator:
    """The production narrator, wrapped in a recorder and installed as the
    app's narrator for this test. `client` (conftest.py) already wires the
    fixture db and a fresh InMemoryNarrationCache per request; only the
    narrator is swapped, and the fixture's teardown pops this override."""
    production_narrator = get_narrator()
    assert isinstance(production_narrator, ClaudeNarrator), (
        "get_narrator() did not resolve the production ClaudeNarrator "
        f"(got {type(production_narrator).__name__}); is APP_TEST_MODE set?"
    )
    recorder = RecordingNarrator(production_narrator)
    app.dependency_overrides[get_narrator] = lambda: recorder
    return recorder


def _catalog_team_names(client: TestClient) -> list[str]:
    response = client.get("/api/teams", params={"sport": "cfb"})
    assert response.status_code == 200, response.text
    names: list[str] = response.json()["teams"]
    assert names, "the fixture db's CFB team catalog is empty"
    return names


def _judge_served_narration(
    *,
    client: TestClient,
    label: str,
    body: dict[str, Any],
    recorder: RecordingNarrator,
    expected_team: str,
    records: list[NarrationRecord],
) -> tuple[str, ...]:
    """Record, print and judge one served narration; returns its §8
    violations. The record and its printout are measurements only."""
    case = TeamCaseOut.model_validate(body["evidence"])
    narration = body["narration"]
    text: str = narration["text"]
    fact_block_json = team_case_fact_block_json(case)

    # The fact block judged against must be the one the model was given, on
    # every call, or property 2 would be checking the wrong thing.
    assert recorder.messages, (
        "no narrator call completed (a transport error on the first call serves the fallback); "
        f"served text: {text!r}"
    )
    assert recorder.messages[0][0]["content"] == build_user_message(
        fact_block_json, contested=narration["contested"]
    ), "reconstructed fact block differs from the one sent to the narrator"
    calls = recorder.recorded_calls()
    assert all(call.fact_block_json == fact_block_json for call in calls)
    assert narration["cached"] is False

    judgement = judge_narration(
        served_text=text,
        calls=calls,
        catalog=cfb_catalog(),
        fallback_text=team_case_fallback_text(case),
    )
    record = build_record(label, judgement)
    records.append(record)
    printout = format_record(record)
    if narration["contested"]:
        disclosure = contested_disclosure_words(text)
        printout += f"\n[persona-eval] {label} contested disclosure_words={disclosure or 'none'}"
    print(printout)

    return section_8_violations(
        served_text=text,
        expected_team=expected_team,
        evidence_team=case.team_name,
        catalog_names=_catalog_team_names(client),
        judgement=judgement,
    )


@_NO_KEY
@pytest.mark.parametrize("year", sorted(EXPECTED_KEENER_NUMBER_ONE))
def test_champion_narration_meets_the_section_8_properties(
    client: TestClient, year: int, eval_records: list[NarrationRecord]
) -> None:
    expected_team = EXPECTED_KEENER_NUMBER_ONE[year]
    _assert_the_judge_rejects_the_planted_submission(cfb_team_case_block(year, expected_team))
    recorder = _recording_production_narrator()

    response = client.post("/api/verdict/champion", json={"year": year})
    assert response.status_code == 200, response.text
    body = response.json()

    # contested flag: true for exactly 2003 and 2017.
    assert body["narration"]["contested"] is (year in EXPECTED_CONTESTED_YEARS)

    violations = _judge_served_narration(
        client=client,
        label=f"{year} champion",
        body=body,
        recorder=recorder,
        expected_team=expected_team,
        records=eval_records,
    )
    assert not violations, f"{year}: " + "; ".join(violations)


@_NO_KEY
def test_team_case_narration_meets_the_section_8_properties(
    client: TestClient, eval_records: list[NarrationRecord]
) -> None:
    """A team case with a loss (#228), judged like the champions. Loss order
    is no longer checked: the renderer prints every score winner-first."""
    _assert_the_judge_rejects_the_planted_submission(
        cfb_team_case_block(TEAM_CASE_YEAR, TEAM_CASE_TEAM)
    )
    recorder = _recording_production_narrator()

    response = client.post(
        "/api/verdict/team-case", json={"year": TEAM_CASE_YEAR, "team": TEAM_CASE_TEAM}
    )
    assert response.status_code == 200, response.text
    body = response.json()

    case = TeamCaseOut.model_validate(body["evidence"])
    assert [
        (game.opponent_name, game.team_score, game.opponent_score)
        for game in case.games
        if game.result == "L"
    ] == TEAM_CASE_LOSSES, "the fixture's loss changed; this eval's premise no longer holds"

    violations = _judge_served_narration(
        client=client,
        label=f"{TEAM_CASE_YEAR} {TEAM_CASE_TEAM} team case",
        body=body,
        recorder=recorder,
        expected_team=TEAM_CASE_TEAM,
        records=eval_records,
    )
    assert not violations, "; ".join(violations)
