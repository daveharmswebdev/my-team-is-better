# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Fail a PR whose description lacks /ship's verification record (#374).

PR #366 merged with an empty description, and the template in
`.claude/skills/ship/SKILL.md` section 2 was prose nobody checked. CI runs this on every
PR event, including a body edit, with plain `python3` (stdlib only):

    python3 .claude/hooks/check_pr_body.py "$GITHUB_EVENT_PATH"   # in CI
    python3 .claude/hooks/check_pr_body.py --body-file pr-374.md   # before gh pr create

A body passes when it has, outside fenced code blocks:

- the h2 headings `## Why`, `## What changed` and `## Verification` at the start of a
  line. Text may follow (`## Verification (re-run by the coordinator)`), but `### Why`,
  `##Why`, `## Whyever` or `Why` in prose don't count;
- an issue link: a closing keyword (`Closes`, `Fixes`, `Resolves` and GitHub's other
  forms, `#n`, `owner/repo#n` or an issues URL) anywhere in a line, or a line starting
  `Part of #n` or `Refs #n` for one step of an issue that stays open; or else a line
  `No issue: <reason>` with a non-empty reason.

It guards against accidental omission, not evasion: bare headings with nothing under
them pass, but that is visible in the PR itself. Exit 0 prints one `ok` line. A missing
piece exits 1 with one message naming all of them. Input that can't be read (a missing
file, an event without `pull_request.body`) exits 2, never 0.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HEADINGS = ("Why", "What changed", "Verification")
TEMPLATE = '.claude/skills/ship/SKILL.md, section 2 ("The description")'
ISSUE_PIECE = (
    "an issue link ('Closes #<n>'; 'Part of #<n>' or 'Refs #<n>' for one step of an "
    "issue that stays open) or a 'No issue: <reason>' line"
)

_ISSUE_REF = r"(?:#\d+|[\w.-]+/[\w.-]+#\d+|https://github\.com/[\w.-]+/[\w.-]+/issues/\d+)"
_CLOSING = re.compile(
    rf"(?<![\w-])(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?):?\s+{_ISSUE_REF}(?!\w)",
    re.IGNORECASE,
)
_STEP_OF = re.compile(rf"^(?:part\s+of|refs?)\s+{_ISSUE_REF}(?!\w)", re.IGNORECASE)
_NO_ISSUE = re.compile(r"^no issue:(.*)$", re.IGNORECASE)
_FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_CODE_SPAN = re.compile(r"(`+)(?!`).*?(?<!`)\1(?!`)")


class InputError(Exception):
    """The body couldn't be read: the check fails closed (exit 2), never passes."""


def _heading(title: str) -> re.Pattern[str]:
    return re.compile(rf"^## {re.escape(title)}(?![\w])", re.IGNORECASE)


_HEADING_PATTERNS = {title: _heading(title) for title in HEADINGS}


def outside_fences(body: str) -> list[str]:
    """The body's lines that aren't inside a fenced code block (CommonMark fences).

    A fence opens with three or more backticks or tildes (up to three spaces of indent;
    a backtick fence's info string has no backtick) and closes on a line of the same
    character, at least as long, with nothing but whitespace after it. An unclosed fence
    runs to the end, as it renders.
    """
    kept: list[str] = []
    fence: str | None = None
    for line in body.splitlines():
        if fence is None:
            match = _FENCE_OPEN.match(line)
            if match and not (match.group(1)[0] == "`" and "`" in match.group(2)):
                fence = match.group(1)
                continue
            kept.append(line)
        else:
            stripped = line.strip()
            run = len(stripped) - len(stripped.lstrip(fence[0]))
            indent = len(line) - len(line.lstrip(" "))
            if indent <= 3 and run >= len(fence) and stripped == fence[0] * run:
                fence = None
    return kept


def _issue_piece(lines: list[str]) -> str | None:
    """None when the body links an issue or says why it has none; else what's missing."""
    bare_marker = False
    for line in lines:
        prose = _CODE_SPAN.sub("", line)
        if _CLOSING.search(prose) or _STEP_OF.match(prose):
            return None
        marker = _NO_ISSUE.match(line)
        if marker:
            if marker.group(1).strip():
                return None
            bare_marker = True
    if bare_marker:
        return ISSUE_PIECE + " ('No issue:' needs a reason after the colon)"
    return ISSUE_PIECE


def missing_pieces(body: str | None) -> list[str]:
    """Every piece the body lacks, in a fixed order; empty when it passes."""
    lines = outside_fences(body or "")
    missing = [
        f"a '## {title}' heading"
        for title, pattern in _HEADING_PATTERNS.items()
        if not any(pattern.match(line) for line in lines)
    ]
    issue = _issue_piece(lines)
    if issue is not None:
        missing.append(issue)
    return missing


def _body_from_event(path: Path) -> str | None:
    try:
        event = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InputError(f"can't read the event JSON {path}: {exc}") from exc
    pull_request = event.get("pull_request") if isinstance(event, dict) else None
    if not isinstance(pull_request, dict) or "body" not in pull_request:
        raise InputError(f"{path} is not a pull_request event with a body field")
    body = pull_request["body"]
    if body is not None and not isinstance(body, str):
        raise InputError(f"{path}: pull_request.body is {type(body).__name__}, not a string")
    return body


def _body_from_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InputError(f"can't read the body file {path}: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("event", nargs="?", type=Path, help="a GitHub event JSON file")
    source.add_argument("--body-file", type=Path, help="a plain markdown PR body")
    args = parser.parse_args(argv)
    try:
        body = _body_from_file(args.body_file) if args.body_file else _body_from_event(args.event)
    except InputError as exc:
        print(f"check_pr_body: {exc}", file=sys.stderr)
        return 2
    missing = missing_pieces(body)
    if not missing:
        print("check_pr_body: ok, the PR description has /ship's verification record")
        return 0
    lines = "\n".join(f"  - {piece}" for piece in missing)
    print(
        f"check_pr_body: the PR description is missing:\n{lines}\n"
        f"Use the template in {TEMPLATE}, then edit the PR body; this check re-runs on "
        "the edit.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
