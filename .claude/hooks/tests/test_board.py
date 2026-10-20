"""`board.py` puts an issue on the project board with its Kind, Priority and Status."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import pytest

import board

FIELDS: dict[str, Any] = {
    "fields": [
        {"id": "F_TITLE", "name": "Title", "type": "ProjectV2Field"},
        {
            "id": "F_STATUS",
            "name": "Status",
            "options": [
                {"id": "s_founder", "name": "Needs founder"},
                {"id": "s_todo", "name": "Todo"},
                {"id": "s_prog", "name": "In Progress"},
            ],
        },
        {
            "id": "F_PRI",
            "name": "Priority",
            "options": [{"id": f"p{n}", "name": f"P{n}"} for n in range(4)],
        },
        {
            "id": "F_KIND",
            "name": "Kind",
            "options": [
                {"id": "k_bug", "name": "Bug"},
                {"id": "k_feat", "name": "Feature"},
                {"id": "k_epic", "name": "Epic"},
                {"id": "k_eng", "name": "Engineering"},
            ],
        },
    ]
}


class FakeGh:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, args: Sequence[str]) -> str:
        self.calls.append(list(args))
        if args[:2] == ["project", "view"]:
            return json.dumps({"id": "PVT_X"})
        if args[:2] == ["project", "field-list"]:
            return json.dumps(FIELDS)
        if args[:2] == ["issue", "view"]:
            return json.dumps({"url": "https://github.com/o/r/issues/42"})
        if args[:2] == ["project", "item-add"]:
            return json.dumps({"id": "ITEM_42"})
        return ""

    def edits(self) -> dict[str, str]:
        out = {}
        for call in self.calls:
            if call[:2] == ["project", "item-edit"]:
                assert call[call.index("--id") + 1] == "ITEM_42"
                assert call[call.index("--project-id") + 1] == "PVT_X"
                out[call[call.index("--field-id") + 1]] = call[
                    call.index("--single-select-option-id") + 1
                ]
        return out


def test_sets_kind_priority_and_default_status() -> None:
    gh = FakeGh()
    board.main(["42", "--kind", "Engineering", "--priority", "P3"], gh=gh)
    assert gh.edits() == {"F_KIND": "k_eng", "F_PRI": "p3", "F_STATUS": "s_todo"}


def test_status_can_be_set_explicitly() -> None:
    gh = FakeGh()
    board.main(["42", "--kind", "Bug", "--priority", "P2", "--status", "In Progress"], gh=gh)
    assert gh.edits()["F_STATUS"] == "s_prog"


def test_status_only_update_leaves_kind_and_priority_alone() -> None:
    gh = FakeGh()
    board.main(["42", "--status", "In Progress"], gh=gh)
    assert gh.edits() == {"F_STATUS": "s_prog"}


@pytest.mark.parametrize("priority", ["P0", "P1"])
def test_p0_and_p1_need_the_founder(priority: str) -> None:
    with pytest.raises(SystemExit):
        board.main(["42", "--kind", "Bug", "--priority", priority], gh=FakeGh())
    gh = FakeGh()
    board.main(["42", "--kind", "Bug", "--priority", priority, "--founder-approved"], gh=gh)
    assert gh.edits()["F_PRI"] == f"p{priority[1]}"


def test_an_option_the_board_lacks_fails_before_any_edit() -> None:
    gh = FakeGh()
    stale = {"fields": [f for f in FIELDS["fields"] if f["name"] != "Kind"]}
    gh_calls = gh

    def no_kind(args: Sequence[str]) -> str:
        if args[:2] == ["project", "field-list"]:
            return json.dumps(stale)
        return gh_calls(args)

    with pytest.raises(SystemExit):
        board.main(["42", "--kind", "Bug", "--priority", "P2"], gh=no_kind)
    assert not gh.edits()
    assert not any(c[:2] == ["project", "item-add"] for c in gh.calls)
