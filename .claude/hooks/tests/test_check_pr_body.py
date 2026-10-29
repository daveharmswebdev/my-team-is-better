"""`check_pr_body.py` fails a PR whose description lacks /ship's verification record (#374).

PR #366 merged with an empty description. The checker needs the three /ship headings and
an issue link (or an explicit `No issue: <reason>` line). CI runs it with plain `python3`,
so these tests also run it as a subprocess with no `uv` and no third-party packages.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import check_pr_body as cpb

SCRIPT = Path(cpb.__file__).resolve()
SAMPLES = Path(__file__).resolve().parent / "fixtures" / "pr_bodies"

SHIP_BODY = """\
## Why
PR #366 merged with an empty description.

## What changed
- A checker for the PR body.

## Verification (re-run by the coordinator, not only the spoke)
- `pytest -q .claude/hooks/tests` — 300 passed

## Delegation record
contract_gaps: none
brief_defects: none
Findings filed: none

<details><summary>Validated returns and review rounds</summary>

```json
{"status": "success"}
```
</details>

Closes #374

🤖 Generated with [Claude Code](https://claude.com/claude-code)
"""

ISSUE = "issue link"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the script as CI does: a bare interpreter, isolated from site and cwd."""
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT), *args], capture_output=True, text=True
    )


def without(body: str, line: str) -> str:
    assert body.count(line + "\n") == 1, line
    return body.replace(line + "\n", "")


# --- the rule ------------------------------------------------------------------------


def test_a_full_ship_body_passes() -> None:
    assert cpb.missing_pieces(SHIP_BODY) == []


@pytest.mark.parametrize(
    ("line", "heading"),
    [
        ("## Why", "## Why"),
        ("## What changed", "## What changed"),
        ("## Verification (re-run by the coordinator, not only the spoke)", "## Verification"),
    ],
)
def test_each_missing_heading_fails_and_is_named(line: str, heading: str) -> None:
    pieces = cpb.missing_pieces(without(SHIP_BODY, line))
    assert len(pieces) == 1
    assert heading in pieces[0]


@pytest.mark.parametrize("body", [None, "", "   \n\n", "\r\n"])
def test_an_empty_or_null_body_names_all_four(body: str | None) -> None:
    pieces = cpb.missing_pieces(body)
    assert len(pieces) == 4
    text = "\n".join(pieces)
    for heading in ("## Why", "## What changed", "## Verification"):
        assert heading in text
    assert ISSUE in pieces[3]


def test_a_missing_issue_link_fails() -> None:
    pieces = cpb.missing_pieces(without(SHIP_BODY, "Closes #374"))
    assert len(pieces) == 1
    assert ISSUE in pieces[0]


@pytest.mark.parametrize(
    "line",
    [
        "Closes #374",
        "closes #374",
        "Fixes #374",
        "FIXED #374",
        "Resolves #374",
        "resolved: #374",
        "Part of #443. Closes #448",
        "Closes daveharmswebdev/my-team-is-better#374",
        "Closes https://github.com/daveharmswebdev/my-team-is-better/issues/374",
        "Part of #185.",
        "Refs #484 (step 1 of 2; the held board stays open)",
        "No issue: a one-line docs fix the coordinator made inline",
        "no issue: docs only",
    ],
)
def test_an_issue_link_or_marker_is_accepted(line: str) -> None:
    body = SHIP_BODY.replace("Closes #374", line)
    assert cpb.missing_pieces(body) == []


@pytest.mark.parametrize(
    "line",
    [
        "No issue:",
        "No issue:   ",
        "No issue",
        "Closes #",
        "Closes 374",
        "Encloses #374",
        "This touches the part of #185 that was left over",
        "Prefixes #374",
        "`Closes #374` goes at the end",
    ],
)
def test_a_bare_marker_or_a_near_miss_is_not_an_issue_link(line: str) -> None:
    body = SHIP_BODY.replace("Closes #374", line)
    pieces = cpb.missing_pieces(body)
    assert len(pieces) == 1
    assert ISSUE in pieces[0]


def test_an_empty_no_issue_marker_says_it_needs_a_reason() -> None:
    pieces = cpb.missing_pieces(SHIP_BODY.replace("Closes #374", "No issue:"))
    assert "reason" in pieces[0]


@pytest.mark.parametrize(
    "line",
    [
        "### Why",
        "# Why",
        "Why",
        "##Why",
        " ## Why",
        "## Whyever",
        "Explaining ## Why in prose",
        "**Why**",
    ],
)
def test_a_heading_lookalike_does_not_count(line: str) -> None:
    body = SHIP_BODY.replace("## Why\n", line + "\n")
    pieces = cpb.missing_pieces(body)
    assert len(pieces) == 1
    assert "## Why" in pieces[0]


@pytest.mark.parametrize(
    "line",
    ["## Why", "## Why it matters", "## Why:", "## why", "## Why ##", "## Why\t(founder report)"],
)
def test_a_heading_with_trailing_text_counts(line: str) -> None:
    body = SHIP_BODY.replace("## Why\n", line + "\n")
    assert cpb.missing_pieces(body) == []


def test_crlf_line_endings_pass() -> None:
    assert cpb.missing_pieces(SHIP_BODY.replace("\n", "\r\n")) == []


@pytest.mark.parametrize("fence", ["```", "~~~", "````markdown", "```md"])
def test_headings_only_inside_a_fenced_block_fail(fence: str) -> None:
    closer = fence[0] * (len(fence) - len(fence.lstrip(fence[0])))
    headings = "## Why\n## What changed\n## Verification\n"
    body = f"See the template:\n\n{fence}\n{headings}{closer}\n\nCloses #374\n"
    pieces = cpb.missing_pieces(body)
    assert len(pieces) == 3
    assert all("##" in piece for piece in pieces)


def test_an_issue_link_only_inside_a_fenced_block_fails() -> None:
    body = SHIP_BODY.replace("Closes #374", "```\nCloses #374\n```")
    pieces = cpb.missing_pieces(body)
    assert len(pieces) == 1
    assert ISSUE in pieces[0]


def test_an_unclosed_fence_hides_everything_after_it() -> None:
    body = "~~~\n" + SHIP_BODY  # SHIP_BODY's own ``` fences can't close a ~~~ one
    assert len(cpb.missing_pieces(body)) == 4


def test_a_shorter_or_different_fence_does_not_close_the_block() -> None:
    body = "````\n```\n~~~\n## Why\n````\n## What changed\n## Verification\nCloses #1\n"
    pieces = cpb.missing_pieces(body)
    assert len(pieces) == 1
    assert "## Why" in pieces[0]


def test_inline_backticks_do_not_open_a_fence() -> None:
    body = "``` not a fence ``` inline\n" + SHIP_BODY
    assert cpb.missing_pieces(body) == []


# --- the sampled real bodies ---------------------------------------------------------


def _samples() -> list[Path]:
    paths = sorted(SAMPLES.glob("pr-*.md"))
    assert len(paths) >= 6, "the committed sample went missing"
    return paths


@pytest.mark.parametrize("path", _samples(), ids=lambda p: p.stem)
def test_a_sampled_real_body_gets_its_recorded_result(path: Path) -> None:
    expected = path.stem.split("-", 2)[2]
    pieces = cpb.missing_pieces(path.read_text())
    if expected == "pass":
        assert pieces == []
    else:
        assert expected == "fail-issue"
        assert len(pieces) == 1, pieces
        assert ISSUE in pieces[0]


# --- inputs and exit codes -----------------------------------------------------------


def write_event(tmp_path: Path, body: str | None) -> Path:
    path = tmp_path / "event.json"
    path.write_text(json.dumps({"action": "edited", "pull_request": {"number": 1, "body": body}}))
    return path


def test_the_event_json_input_passes_a_ship_body(tmp_path: Path) -> None:
    result = run(str(write_event(tmp_path, SHIP_BODY)))
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().count("\n") == 0
    assert "ok" in result.stdout


def test_the_event_json_input_with_a_null_body_fails_naming_all_four(tmp_path: Path) -> None:
    result = run(str(write_event(tmp_path, None)))
    assert result.returncode == 1
    for piece in ("## Why", "## What changed", "## Verification", ISSUE):
        assert piece in result.stderr
    assert ".claude/skills/ship/SKILL.md" in result.stderr
    assert "section 2" in result.stderr


def test_the_body_file_input(tmp_path: Path) -> None:
    good = tmp_path / "good.md"
    good.write_text(SHIP_BODY)
    bad = tmp_path / "bad.md"
    bad.write_text(without(SHIP_BODY, "## What changed"))
    assert run("--body-file", str(good)).returncode == 0
    result = run("--body-file", str(bad))
    assert result.returncode == 1
    assert "## What changed" in result.stderr
    assert "## Why" not in result.stderr


def test_one_failure_message_lists_every_missing_piece(tmp_path: Path) -> None:
    bad = tmp_path / "bad.md"
    bad.write_text("## Why\nsomething\n")
    result = run("--body-file", str(bad))
    assert result.returncode == 1
    for piece in ("## What changed", "## Verification", ISSUE):
        assert piece in result.stderr


@pytest.mark.parametrize(
    "event",
    [
        "not json",
        json.dumps({"push": {}}),
        json.dumps({"pull_request": {"number": 1}}),
        json.dumps({"pull_request": {"body": 7}}),
        json.dumps([1, 2]),
    ],
)
def test_an_unusable_event_fails_rather_than_passing(tmp_path: Path, event: str) -> None:
    path = tmp_path / "event.json"
    path.write_text(event)
    result = run(str(path))
    assert result.returncode != 0
    assert "ok" not in result.stdout


def test_a_missing_input_file_fails(tmp_path: Path) -> None:
    assert run(str(tmp_path / "nope.json")).returncode != 0
    assert run("--body-file", str(tmp_path / "nope.md")).returncode != 0


def test_exactly_one_input_is_required(tmp_path: Path) -> None:
    event = write_event(tmp_path, SHIP_BODY)
    assert run().returncode != 0
    assert run(str(event), "--body-file", str(event)).returncode != 0


def test_main_returns_the_exit_code(tmp_path: Path) -> None:
    assert cpb.main([str(write_event(tmp_path, SHIP_BODY))]) == 0
    assert cpb.main([str(write_event(tmp_path, ""))]) == 1
