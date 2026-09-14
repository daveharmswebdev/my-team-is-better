"""The ownership map is the one source for who may edit what.

`.claude/ownership.json` feeds the edit-scope hook, the brief validator and the
return validator. These tests pin its matching rules and keep it in step with
`.claude/agents/*.md` and CLAUDE.md's Roles table (the #105 class: an agent named in
one place and missing from another).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from ownership import AgentEntry, Ownership, load_ownership, path_matches, scope_within

CLAUDE_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = CLAUDE_DIR.parent


@pytest.mark.parametrize(
    ("rel_path", "pattern", "expected"),
    [
        ("apps/api/src/api/main.py", "apps/api/**", True),
        ("apps/api/README.md", "apps/api/**", True),
        ("apps/apiary/main.py", "apps/api/**", False),
        ("apps/web/src/App.tsx", "apps/api/**", False),
        (
            "packages/cfb-engine/tests/test_mcp_server_integration.py",
            "packages/cfb-engine/tests/test_mcp_server_integration.py",
            True,
        ),
        (
            "packages/cfb-engine/tests/test_evidence_integration.py",
            "packages/cfb-engine/tests/test_mcp_server_integration.py",
            False,
        ),
        ("apps/web/src/App.tsx", "apps/web/src/*.tsx", True),
        ("apps/web/src/pages/HomePage.tsx", "apps/web/src/*.tsx", False),
        ("apps/web/src/pages/HomePage.test.tsx", "apps/web/**/*.test.tsx", True),
    ],
)
def test_path_matches(rel_path: str, pattern: str, expected: bool) -> None:
    assert path_matches(rel_path, pattern) is expected


@pytest.mark.parametrize(
    ("scope", "owns", "expected"),
    [
        ("apps/api/src/api/persona/**", ["apps/api/**"], True),
        ("apps/api/**", ["apps/api/**"], True),
        ("apps/api/src/api/verdict.py", ["apps/api/**"], True),
        ("apps/**", ["apps/api/**"], False),
        ("apps/web/src/App.tsx", ["apps/api/**"], False),
        (
            "packages/cfb-engine/tests/test_mcp_server_integration.py",
            ["packages/cfb-engine/tests/test_mcp_server_integration.py"],
            True,
        ),
        (
            "packages/cfb-engine/tests/*.py",
            ["packages/cfb-engine/tests/test_mcp_server_integration.py"],
            False,
        ),
    ],
)
def test_scope_within(scope: str, owns: list[str], expected: bool) -> None:
    assert scope_within(scope, owns) is expected


def test_agent_entry_allows_only_owned_paths() -> None:
    entry = AgentEntry(kind="implementation", owns=("apps/api/**",))
    assert entry.allows("apps/api/src/api/main.py")
    assert not entry.allows("apps/web/src/App.tsx")
    assert not AgentEntry(kind="read-only", owns=()).allows("README.md")


def _definition_names() -> dict[str, Path]:
    names: dict[str, Path] = {}
    for path in sorted((CLAUDE_DIR / "agents").glob("*.md")):
        match = re.search(r"^name:\s*(\S+)\s*$", path.read_text(), re.MULTILINE)
        assert match, f"{path} has no `name:` in its frontmatter"
        names[match.group(1)] = path
    return names


def _frontmatter(path: Path) -> str:
    text = path.read_text()
    assert text.startswith("---\n"), f"{path} has no frontmatter"
    return text.split("---\n", 2)[1]


@pytest.fixture(scope="module")
def real_ownership() -> Ownership:
    return load_ownership()


def test_every_agent_definition_is_in_the_ownership_map_and_vice_versa(
    real_ownership: Ownership,
) -> None:
    assert set(_definition_names()) == set(real_ownership.agents)


def test_every_agent_preloads_the_spoke_protocol(real_ownership: Ownership) -> None:
    assert (CLAUDE_DIR / "skills" / "spoke-protocol" / "SKILL.md").is_file()
    for name, path in _definition_names().items():
        frontmatter = _frontmatter(path)
        assert re.search(
            r"^skills:\s*\n(\s+- .+\n)*\s+- spoke-protocol\s*$", frontmatter, re.MULTILINE
        ), (
            f"{name} must list spoke-protocol under `skills:` so the return contract is "
            "in its context without being copied into its body"
        )


def test_read_only_agents_own_nothing_and_have_no_edit_tools(real_ownership: Ownership) -> None:
    definitions = _definition_names()
    for name, entry in real_ownership.agents.items():
        tools_line = re.search(r"^tools:\s*(.+)$", _frontmatter(definitions[name]), re.MULTILINE)
        assert tools_line, f"{name} must declare `tools:` explicitly"
        tools = {tool.strip() for tool in tools_line.group(1).split(",")}
        if entry.kind == "read-only":
            assert entry.owns == ()
            assert not tools & {"Edit", "Write", "NotebookEdit"}, name
        else:
            assert entry.owns, f"implementation agent {name} owns nothing"


def test_claude_md_roles_table_names_only_mapped_agents(real_ownership: Ownership) -> None:
    claude_md = (REPO_ROOT / "CLAUDE.md").read_text()
    rows = re.findall(r"^\| `([a-z-]+)` \|", claude_md, re.MULTILINE)
    assert rows, "CLAUDE.md's Roles table has no agent rows"
    assert len(rows) == len(set(rows)), "an agent appears twice in the Roles table"
    assert set(rows) == set(real_ownership.agents), (
        "CLAUDE.md's Roles table and .claude/ownership.json must name the same agents"
    )


def test_edit_scope_mode_is_a_known_value(real_ownership: Ownership) -> None:
    assert real_ownership.edit_scope_mode in {"warn", "block"}
