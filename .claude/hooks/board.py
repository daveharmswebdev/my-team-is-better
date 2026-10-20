# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Put an issue on the project board and set its Kind, Priority and Status.

The board (github.com/users/daveharmswebdev/projects/4) is the founder's view of the
tracker: the Product view shows Bug, Feature and Epic items, and Engineering items stay
in their own view. `/triage` files with `--kind Engineering --priority P3` unless a user
of the site would notice the problem. P0 and P1 are the founder's call, so they need
`--founder-approved`.

    uv run .claude/hooks/board.py 412 --kind Bug --priority P2
    uv run .claude/hooks/board.py 412 --status "In Progress"
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable, Sequence
from typing import Any

OWNER = "daveharmswebdev"
PROJECT = "4"
KINDS = ("Bug", "Feature", "Epic", "Engineering")
PRIORITIES = ("P0", "P1", "P2", "P3")
STATUSES = ("Needs founder", "Todo", "In Progress", "Done")
FOUNDER_PRIORITIES = frozenset({"P0", "P1"})

Gh = Callable[[Sequence[str]], str]


def run_gh(args: Sequence[str]) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def _option_ids(fields: dict[str, Any], wanted: dict[str, str]) -> dict[str, str]:
    """Map each wanted {field name: option name} to {field id: option id}, or exit."""
    by_name = {f["name"]: f for f in fields["fields"] if "options" in f}
    out = {}
    for field, option in wanted.items():
        if field not in by_name:
            sys.exit(f"board.py: the board has no {field!r} field")
        ids = [o["id"] for o in by_name[field]["options"] if o["name"] == option]
        if not ids:
            sys.exit(f"board.py: the board's {field!r} field has no option {option!r}")
        out[by_name[field]["id"]] = ids[0]
    return out


def main(argv: list[str] | None = None, gh: Gh = run_gh) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("issue", type=int)
    parser.add_argument("--kind", choices=KINDS)
    parser.add_argument("--priority", choices=PRIORITIES)
    parser.add_argument("--status", choices=STATUSES)
    parser.add_argument("--founder-approved", action="store_true")
    args = parser.parse_args(argv)

    if args.priority in FOUNDER_PRIORITIES and not args.founder_approved:
        sys.exit(f"board.py: {args.priority} is the founder's call; pass --founder-approved")
    wanted = {"Kind": args.kind, "Priority": args.priority, "Status": args.status}
    if args.kind and not args.status:
        wanted["Status"] = "Todo"
    wanted = {k: v for k, v in wanted.items() if v}
    if not wanted:
        parser.error("nothing to set: pass --kind/--priority and/or --status")

    project_id = json.loads(gh(["project", "view", PROJECT, "--owner", OWNER, "--format", "json"]))[
        "id"
    ]
    fields = json.loads(
        gh(["project", "field-list", PROJECT, "--owner", OWNER, "--format", "json"])
    )
    edits = _option_ids(fields, wanted)

    url = json.loads(gh(["issue", "view", str(args.issue), "--json", "url"]))["url"]
    item = json.loads(
        gh(["project", "item-add", PROJECT, "--owner", OWNER, "--url", url, "--format", "json"])
    )["id"]
    for field_id, option_id in edits.items():
        gh(
            [
                "project",
                "item-edit",
                "--id",
                item,
                "--project-id",
                project_id,
                "--field-id",
                field_id,
                "--single-select-option-id",
                option_id,
            ]
        )
    print(f"#{args.issue}: " + ", ".join(f"{k}={v}" for k, v in wanted.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
