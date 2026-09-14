"""The delegation contract, checked by code instead of by the coordinator's eyes.

Covers `.claude/schemas/{brief,return}.schema.json` (v2), the semantic rules a JSON
Schema can't express, the brief renderer, and the SubagentStop hook that asks a spoke
to fix an invalid return (retry with the validation errors as feedback) up to a cap.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

import delegation
from ownership import AgentEntry, Ownership

HOOKS_DIR = Path(__file__).resolve().parents[1]
CLAUDE_DIR = HOOKS_DIR.parent
EXAMPLES = CLAUDE_DIR / "schemas" / "examples"

OWNERSHIP = Ownership(
    agents={
        "api-agent": AgentEntry(kind="implementation", owns=("apps/api/**",)),
        "web-agent": AgentEntry(kind="implementation", owns=("apps/web/**",)),
        "ratings-agent": AgentEntry(
            kind="implementation", owns=("packages/cfb-engine/src/cfb_strength/ratings/**",)
        ),
        "validator": AgentEntry(kind="read-only", owns=()),
    },
    edit_scope_mode="warn",
)


def _load(name: str) -> dict[str, Any]:
    data = json.loads((EXAMPLES / name).read_text())
    assert isinstance(data, dict)
    return data


def _success() -> dict[str, Any]:
    return copy.deepcopy(_load("return.api-agent.success.json"))


def _fenced(data: object) -> str:
    return "```json\n" + json.dumps(data, indent=2) + "\n```"


# --- schemas and examples -------------------------------------------------------------


@pytest.mark.parametrize("name", ["brief.schema.json", "return.schema.json"])
def test_schemas_are_valid_draft_2020_12(name: str) -> None:
    Draft202012Validator.check_schema(json.loads((CLAUDE_DIR / "schemas" / name).read_text()))


def test_every_example_validates_with_the_real_ownership_map() -> None:
    real = delegation.load_ownership()
    examples = sorted(EXAMPLES.glob("*.json"))
    assert {p.name.split(".")[0] for p in examples} == {"brief", "return"}
    for path in examples:
        data = json.loads(path.read_text())
        if path.name.startswith("brief."):
            assert delegation.validate_brief(data, real) == [], path.name
        else:
            agent = path.name.split(".")[1]
            result = delegation.validate_return(data, agent_type=agent, ownership=real)
            assert result.errors == [], path.name


# --- extracting the fenced block ------------------------------------------------------


def test_extracts_exactly_one_fenced_json_block() -> None:
    data, errors = delegation.extract_json_block("\n" + _fenced({"status": "success"}) + "\n")
    assert errors == []
    assert data == {"status": "success"}


@pytest.mark.parametrize(
    ("message", "fragment"),
    [
        ("All done, tests pass.", "no fenced"),
        ("Here you go:\n" + _fenced({"status": "success"}), "outside the fence"),
        (_fenced({"a": 1}) + "\n" + _fenced({"b": 2}), "exactly one"),
        ("```json\n{not json}\n```", "not valid JSON"),
    ],
)
def test_rejects_messages_that_are_not_one_clean_block(message: str, fragment: str) -> None:
    data, errors = delegation.extract_json_block(message)
    assert data is None
    assert any(fragment in error for error in errors), errors


# --- return: schema + semantic rules --------------------------------------------------


def _errors(data: object, agent: str = "api-agent") -> list[str]:
    return delegation.validate_return(data, agent_type=agent, ownership=OWNERSHIP).errors


def test_valid_implementation_success() -> None:
    assert _errors(_success()) == []


def test_v1_shaped_return_is_rejected() -> None:
    v1 = {
        "status": "success",
        "summary": "did it",
        "files_changed": [{"path": "apps/api/x.py", "change_type": "modified"}],
        "tests_run": [{"command": "uv run pytest", "result": "pass"}],
        "contract_gaps": [],
    }
    joined = "\n".join(_errors(v1))
    for field in ("agent", "base_sha", "brief_defects", "findings", "phase"):
        assert field in joined


def test_success_with_a_red_run_outside_the_red_phase_is_rejected() -> None:
    data = _success()
    data["tests_run"].append(
        {"command": "uv run mypy --strict src/api tests", "result": "fail", "phase": "gate"}
    )
    assert any("red" in e for e in _errors(data))


def test_tdd_red_run_followed_by_green_is_fine() -> None:
    data = _success()
    assert data["tests_run"][0] == {
        "command": "uv run pytest -q tests/test_persona_cache_outage.py",
        "result": "fail",
        "phase": "red",
    }
    assert _errors(data) == []


def test_implementation_success_needs_a_passing_green_or_gate_run() -> None:
    data = _success()
    data["tests_run"] = [t for t in data["tests_run"] if t["phase"] == "red"]
    assert any("passing" in e for e in _errors(data))


def test_implementation_success_needs_changed_files() -> None:
    data = _success()
    data["files_changed"] = []
    assert any("files_changed" in e for e in _errors(data))


def test_implementation_success_cannot_carry_its_own_blocking_finding() -> None:
    data = _success()
    data["findings"].append(
        {
            "severity": "blocking",
            "category": "rubric",
            "summary": "the rubric's second test still fails",
            "file": "apps/api/tests/test_x.py",
            "line": 12,
            "evidence": "1 failed",
            "owner": "api-agent",
            "tracked_issue": None,
        }
    )
    assert any("rubric-failed" in e for e in _errors(data))


def test_finding_owner_must_be_a_known_agent_or_the_coordinator() -> None:
    data = _success()
    data["findings"][0]["owner"] = "frontend-person"
    assert any("frontend-person" in e for e in _errors(data))


def test_agent_field_must_match_the_agent_that_ran() -> None:
    assert any("web-agent" in e for e in _errors(_success(), agent="web-agent"))


def test_read_only_success_must_show_the_checks_it_ran() -> None:
    data = copy.deepcopy(_load("return.validator.success.json"))
    assert _errors(data, agent="validator") == []
    data["tests_run"] = []
    assert any("tests_run" in e for e in _errors(data, agent="validator"))


def test_read_only_agent_cannot_report_changed_files() -> None:
    data = copy.deepcopy(_load("return.validator.success.json"))
    data["files_changed"] = [{"path": "apps/api/x.py", "change_type": "modified"}]
    assert any("read-only" in e for e in _errors(data, agent="validator"))


def test_files_outside_ownership_are_a_warning_not_an_error() -> None:
    data = _success()
    data["files_changed"].append({"path": "apps/web/src/App.tsx", "change_type": "modified"})
    result = delegation.validate_return(data, agent_type="api-agent", ownership=OWNERSHIP)
    assert result.errors == []
    assert any("apps/web/src/App.tsx" in w for w in result.warnings)


def test_valid_failure() -> None:
    assert _errors(_load("return.web-agent.failure.json"), agent="web-agent") == []


def test_a_spoke_cannot_self_report_malformed_return() -> None:
    data = copy.deepcopy(_load("return.web-agent.failure.json"))
    data["failure_type"] = "malformed-return"
    assert _errors(data, agent="web-agent")


# --- brief ------------------------------------------------------------------------------


def _brief() -> dict[str, Any]:
    return copy.deepcopy(_load("brief.api-agent.json"))


def test_valid_brief() -> None:
    assert delegation.validate_brief(_brief(), OWNERSHIP) == []


def test_brief_scope_must_sit_inside_the_agents_ownership() -> None:
    brief = _brief()
    brief["scope"].append("apps/web/src/lib/api/types.ts")
    assert any(
        "apps/web/src/lib/api/types.ts" in e for e in delegation.validate_brief(brief, OWNERSHIP)
    )


def test_brief_for_unknown_agent_is_rejected() -> None:
    brief = _brief()
    brief["agent"] = "persona-agent"
    assert any("persona-agent" in e for e in delegation.validate_brief(brief, OWNERSHIP))


def test_brief_scratch_dir_must_not_be_the_shared_scratchpad_root() -> None:
    brief = _brief()
    brief["scratch_dir"] = "/private/tmp/claude-501/x/scratchpad"
    assert any("scratch_dir" in e for e in delegation.validate_brief(brief, OWNERSHIP))


def test_read_only_brief_may_scope_the_whole_repo() -> None:
    brief = _brief()
    brief["agent"] = "validator"
    brief["scope"] = ["**"]
    assert delegation.validate_brief(brief, OWNERSHIP) == []


def test_gate_brief_needs_a_threat_model_and_stopping_rule() -> None:
    brief = _brief()
    brief["gate"] = {"threat_model": "accidental erosion", "max_review_rounds": 3}
    errors = delegation.validate_brief(brief, OWNERSHIP)
    assert any("blocking_definition" in e for e in errors)


def test_render_brief_contains_every_section() -> None:
    brief = _brief()
    text = delegation.render_brief(brief)
    for heading in (
        "OBJECTIVE",
        "CONTRACT",
        "SCOPE",
        "NEGATIVE",
        "RUBRIC",
        "BASE",
        "SCRATCH",
        "CONCURRENCY",
    ):
        assert f"## {heading}" in text
    assert brief["base_sha"] in text
    assert brief["scratch_dir"] in text
    assert "## GATE" not in text
    brief["gate"] = {
        "threat_model": "Stops accidental erosion; deliberate evasion must leave a visible trace.",
        "blocking_definition": "An accidental escape, a false positive, or a vacuous check.",
        "out_of_scope": ["eval-built keys"],
        "max_review_rounds": 3,
    }
    assert "## GATE" in delegation.render_brief(brief)


# --- SubagentStop hook ------------------------------------------------------------------


def _stop_payload(
    message: str, agent: str = "api-agent", agent_id: str = "agent_1"
) -> dict[str, Any]:
    return {
        "hook_event_name": "SubagentStop",
        "agent_id": agent_id,
        "agent_type": agent,
        "last_assistant_message": message,
    }


def test_hook_ignores_agents_outside_the_map(tmp_path: Path) -> None:
    out = delegation.subagent_stop(_stop_payload("free text", agent="Explore"), OWNERSHIP, tmp_path)
    assert out is None


def test_hook_passes_a_valid_return_with_a_note_for_the_coordinator(tmp_path: Path) -> None:
    out = delegation.subagent_stop(_stop_payload(_fenced(_success())), OWNERSHIP, tmp_path)
    assert out is not None
    assert "decision" not in out
    assert "validated" in out["systemMessage"]


def test_hook_blocks_an_invalid_return_with_the_errors_as_feedback(tmp_path: Path) -> None:
    data = _success()
    del data["brief_defects"]
    out = delegation.subagent_stop(_stop_payload(_fenced(data)), OWNERSHIP, tmp_path)
    assert out is not None
    assert out["decision"] == "block"
    assert "brief_defects" in out["reason"]
    assert "return.schema.json" in out["reason"]


def test_hook_stops_blocking_after_the_retry_cap(tmp_path: Path) -> None:
    payload = _stop_payload("no json at all", agent_id="agent_stuck")
    for _ in range(delegation.MAX_RETURN_RETRIES):
        out = delegation.subagent_stop(payload, OWNERSHIP, tmp_path)
        assert out is not None and out["decision"] == "block"
    out = delegation.subagent_stop(payload, OWNERSHIP, tmp_path)
    assert out is not None
    assert "decision" not in out
    assert "malformed-return" in out["systemMessage"]


def test_hook_surfaces_scope_warnings_without_blocking(tmp_path: Path) -> None:
    data = _success()
    data["files_changed"].append({"path": "apps/web/src/App.tsx", "change_type": "modified"})
    out = delegation.subagent_stop(_stop_payload(_fenced(data)), OWNERSHIP, tmp_path)
    assert out is not None
    assert "decision" not in out
    assert "apps/web/src/App.tsx" in out["systemMessage"]


# --- CLI ----------------------------------------------------------------------------------


def _cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HOOKS_DIR / "delegation.py"), *args],
        capture_output=True,
        text=True,
    )


def test_cli_render_brief_exits_zero_and_prints_the_prompt() -> None:
    result = _cli("render-brief", str(EXAMPLES / "brief.api-agent.json"))
    assert result.returncode == 0, result.stderr
    assert "## OBJECTIVE" in result.stdout


def test_cli_rejects_an_invalid_brief(tmp_path: Path) -> None:
    brief = _brief()
    brief["scope"] = ["apps/web/**"]
    path = tmp_path / "brief.json"
    path.write_text(json.dumps(brief))
    result = _cli("render-brief", str(path))
    assert result.returncode == 1
    assert "apps/web/**" in result.stderr


def test_cli_validate_return_reads_a_fenced_message(tmp_path: Path) -> None:
    path = tmp_path / "return.md"
    path.write_text(_fenced(_success()))
    result = _cli("validate-return", "--agent", "api-agent", str(path))
    assert result.returncode == 0, result.stderr
