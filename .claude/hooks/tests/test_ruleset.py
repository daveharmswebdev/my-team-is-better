"""`main`'s GitHub ruleset lives in `.github/rulesets/main.json`; keep it in step with CI.

A required check is matched by the job's display name. Rename a job in ci.yml without
updating the ruleset and every PR waits forever on a check that never reports; add a job
without listing it and that job stops gating merges. The JSON is applied to GitHub by
hand (CLAUDE.md), so this test pins the file, not the live ruleset.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
CI_YML = REPO_ROOT / ".github" / "workflows" / "ci.yml"
RULESET_JSON = REPO_ROOT / ".github" / "rulesets" / "main.json"


def _ci_check_names() -> set[str]:
    """Each job's `name:` (or its id when unnamed), without a YAML dependency."""
    jobs_block = CI_YML.read_text().split("\njobs:\n", 1)[1]
    names: set[str] = set()
    for job in re.split(r"^(?=  [\w-]+:\s*$)", jobs_block, flags=re.MULTILINE):
        header = re.match(r"  ([\w-]+):\s*$", job, re.MULTILINE)
        if not header:
            continue
        name = re.search(r"^    name:\s*(.+?)\s*$", job, re.MULTILINE)
        names.add(name.group(1).strip("\"'") if name else header.group(1))
    return names


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
        "ci.yml's job names and .github/rulesets/main.json's required checks must match; "
        "update the JSON and apply it to GitHub (CLAUDE.md) in the same PR"
    )


def test_ruleset_protects_main_with_no_bypass() -> None:
    ruleset = _ruleset()
    assert ruleset["enforcement"] == "active"
    assert ruleset["conditions"]["ref_name"]["include"] == ["~DEFAULT_BRANCH"]
    assert ruleset["bypass_actors"] == []
    for rule_type in ("deletion", "non_fast_forward", "pull_request"):
        _rule(rule_type)
