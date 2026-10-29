"""`main`'s GitHub ruleset lives in `.github/rulesets/main.json`; keep it in step with CI.

A required check is matched by the job's display name. Rename a job without updating the
ruleset and every PR waits forever on a check that never reports; add a job without
listing it and that job stops gating merges. Jobs count from every workflow file, not
only ci.yml: a separate workflow (the PR-body check, #374) gates merges the same way.
The JSON is applied to GitHub by hand (CLAUDE.md), so this test pins the file, not the
live ruleset.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
RULESET_JSON = REPO_ROOT / ".github" / "rulesets" / "main.json"


def _job_names(workflow: Path) -> list[str]:
    """Each job's `name:` (or its id when unnamed), without a YAML dependency."""
    parts = workflow.read_text().split("\njobs:\n", 1)
    assert len(parts) == 2, f"{workflow.name} has no top-level `jobs:` block"
    names: list[str] = []
    for job in re.split(r"^(?=  [\w-]+:\s*$)", parts[1], flags=re.MULTILINE):
        header = re.match(r"  ([\w-]+):\s*$", job, re.MULTILINE)
        if not header:
            continue
        name = re.search(r"^    name:\s*(.+?)\s*$", job, re.MULTILINE)
        names.append(name.group(1).strip("\"'") if name else header.group(1))
    return names


def _workflows(workflows_dir: Path) -> list[Path]:
    """Every workflow file GitHub runs: `*.yml` and `*.yaml` directly in the directory."""
    found = sorted([*workflows_dir.glob("*.yml"), *workflows_dir.glob("*.yaml")])
    assert found, f"no workflow files in {workflows_dir}"
    return found


def _ci_check_names(workflows_dir: Path = WORKFLOWS_DIR) -> set[str]:
    """The job names across every workflow file: each one can be a required check."""
    return {name for workflow in _workflows(workflows_dir) for name in _job_names(workflow)}


def _ruleset() -> dict[str, Any]:
    ruleset: dict[str, Any] = json.loads(RULESET_JSON.read_text())
    return ruleset


def _rule(rule_type: str) -> dict[str, Any]:
    rules = [rule for rule in _ruleset()["rules"] if rule["type"] == rule_type]
    assert len(rules) == 1, f"ruleset needs exactly one {rule_type} rule"
    rule: dict[str, Any] = rules[0]
    return rule


def test_ci_yml_parses_to_its_jobs() -> None:
    names = _ci_check_names()
    assert "e2e (Playwright, apps/api + apps/web)" in names
    assert len(names) >= 5


def test_required_checks_are_exactly_the_ci_jobs() -> None:
    checks = _rule("required_status_checks")["parameters"]["required_status_checks"]
    contexts = [check["context"] for check in checks]
    assert len(contexts) == len(set(contexts)), "a required check is listed twice"
    assert set(contexts) == _ci_check_names(), (
        "the job names across .github/workflows/*.yml and .github/rulesets/main.json's "
        "required checks must match; "
        "update the JSON and apply it to GitHub (CLAUDE.md) in the same PR"
    )


def test_ruleset_protects_main_with_no_bypass() -> None:
    ruleset = _ruleset()
    assert ruleset["enforcement"] == "active"
    assert ruleset["conditions"]["ref_name"]["include"] == ["~DEFAULT_BRANCH"]
    assert ruleset["bypass_actors"] == []
    for rule_type in ("deletion", "non_fast_forward", "pull_request"):
        _rule(rule_type)


CI_STUB = """\
name: CI
on:
  pull_request:
jobs:
  engine:
    name: cfb-engine (pytest)
    runs-on: ubuntu-latest
    steps:
      - name: not a job name
        run: true
  bare-id:
    runs-on: ubuntu-latest
"""

PR_BODY_STUB = """\
name: PR body
on:
  pull_request:
    types: [opened, edited, synchronize, reopened]
jobs:
  pr-body:
    name: "pr-body (/ship verification record)"
    runs-on: ubuntu-latest
    steps:
      - run: python3 .claude/hooks/check_pr_body.py "$GITHUB_EVENT_PATH"
"""


def test_a_job_in_a_second_workflow_file_is_counted(tmp_path: Path) -> None:
    (tmp_path / "ci.yml").write_text(CI_STUB)
    assert _ci_check_names(tmp_path) == {"cfb-engine (pytest)", "bare-id"}
    (tmp_path / "pr-body.yml").write_text(PR_BODY_STUB)
    assert _ci_check_names(tmp_path) == {
        "cfb-engine (pytest)",
        "bare-id",
        "pr-body (/ship verification record)",
    }
    (tmp_path / "other.yaml").write_text(PR_BODY_STUB.replace("  pr-body:", "  other:", 1))
    (tmp_path / "notes.txt").write_text(CI_STUB.replace("bare-id", "ignored"))
    assert _ci_check_names(tmp_path) == {
        "cfb-engine (pytest)",
        "bare-id",
        "pr-body (/ship verification record)",
    }


def test_a_workflow_without_jobs_is_an_error_not_an_empty_set(tmp_path: Path) -> None:
    (tmp_path / "ci.yml").write_text("name: CI\non: push\n")
    with pytest.raises(AssertionError, match="no top-level"):
        _ci_check_names(tmp_path)


def test_an_empty_workflows_dir_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match="no workflow"):
        _ci_check_names(tmp_path)


def test_no_job_name_repeats_across_workflow_files() -> None:
    """Two jobs with one name would let either one satisfy the required check."""
    names = [name for wf in _workflows(WORKFLOWS_DIR) for name in _job_names(wf)]
    assert len(names) == len(set(names)), sorted(names)
