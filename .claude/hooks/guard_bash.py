# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""PreToolUse hook (Bash): block pushes to main and use of the shared git stash.

Applies to every session and subagent. `main` can't be protected by GitHub on this
private repo (CLAUDE.md), and the stash stack is shared by every worktree, so a bare
`git stash pop` can take another running session's changes.

Threat model: an accidental command written out literally, including behind shell
keywords (`then`, `do`), wrappers (`timeout`, `nohup`, `env`) and after heredocs. A
command assembled at runtime (eval, variables, aliases) is out of scope.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

PROTECTED_BRANCHES = frozenset({"main", "master"})

_SEPARATORS = "();&|\n"
_PREFIX_WORDS = frozenset(
    {"!", "{", "builtin", "command", "do", "elif", "else", "env", "exec", "if", "nohup"}
    | {"sudo", "then", "time", "until", "while"}
)
_GIT_OPTIONS_WITH_VALUE = frozenset(
    {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
)
_PUSH_OPTIONS_WITH_VALUE = frozenset({"-o", "--push-option", "--receive-pack", "--exec"})
_CREATE_BRANCH_FLAGS = ("-c", "-C", "-b", "-B", "--create", "--force-create")
_HEREDOC = re.compile(r"(?<!<)<<(?!<)(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")

PUSH_REASON = (
    "Blocked: this pushes to {branch}. main is protected by process on this repo: "
    "changes reach it only through a pull request with green CI (CLAUDE.md). Push a "
    "feature branch and open a pull request instead."
)
STASH_REASON = (
    "Blocked: `{command}`. The stash stack is shared by every worktree and running "
    "session in this repo, so this can take or destroy someone else's changes. Prefer "
    'a temporary WIP commit. If you must stash: `git stash push -u -m "<unique-tag>"`, '
    "capture its sha with `git stash list --format='%H %gs'`, restore with "
    "`git stash apply <sha>`, then drop that entry by its stash@{{n}}."
)


def _strip_heredoc_bodies(command: str) -> str:
    """Drop heredoc bodies: they are data (commit messages, file contents), not commands."""
    kept: list[str] = []
    pending: list[tuple[str, bool]] = []
    for line in command.split("\n"):
        if pending:
            delimiter, tabs_allowed = pending[0]
            if (line.lstrip("\t") if tabs_allowed else line) == delimiter:
                pending.pop(0)
            continue
        kept.append(line)
        pending.extend((m.group(3), m.group(1) == "-") for m in _HEREDOC.finditer(line))
    return "\n".join(kept)


def _tokenize(text: str) -> list[list[str]] | None:
    """Split into simple commands on ; & | ( ) and newlines; None on unbalanced quotes."""
    lexer = shlex.shlex(text, posix=True, punctuation_chars=_SEPARATORS + "<>")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    commands: list[list[str]] = [[]]
    try:
        for token in lexer:
            if token and all(char in _SEPARATORS for char in token):
                commands.append([])
            else:
                commands[-1].append(token)
    except ValueError:
        return None
    return [c for c in commands if c]


def _simple_commands(command: str) -> list[list[str]]:
    text = _strip_heredoc_bodies(command)
    whole = _tokenize(text)
    if whole is not None:
        return whole
    commands: list[list[str]] = []  # unbalanced quotes somewhere: best effort, line by line
    for line in text.split("\n"):
        commands.extend(_tokenize(line) or [])
    return commands


def _is_assignment(token: str) -> bool:
    name, sep, _ = token.partition("=")
    return bool(sep) and name.isidentifier()


def _strip_prefixes(tokens: list[str]) -> list[str]:
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in _PREFIX_WORDS or _is_assignment(token):
            index += 1
        elif token == "timeout":
            index += 1
            while index < len(tokens) and tokens[index].startswith("-"):
                index += 1
            index += 1  # the duration
        else:
            break
    return tokens[index:]


def _git_subcommand(tokens: list[str]) -> tuple[str, list[str]] | None:
    tokens = _strip_prefixes(tokens)
    if not tokens or Path(tokens[0]).name != "git":
        return None
    index = 1
    while index < len(tokens) and tokens[index].startswith("-"):
        index += 2 if tokens[index] in _GIT_OPTIONS_WITH_VALUE else 1
    if index >= len(tokens):
        return None
    return tokens[index], tokens[index + 1 :]


def _branch_after_switch(args: list[str], branch: str | None) -> str | None:
    if "--" in args:  # `git checkout -- <file>` restores files; the branch is unchanged
        return branch
    for flag in _CREATE_BRANCH_FLAGS:
        if flag in args:
            position = args.index(flag) + 1
            return args[position] if position < len(args) else None
    positional = [arg for arg in args if not arg.startswith("-")]
    return positional[0] if positional else branch


def _push_reason(args: list[str], current_branch: str | None) -> str | None:
    positional: list[str] = []
    remote_given_as_option = False
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in ("--mirror", "--all"):
            return PUSH_REASON.format(branch=f"every branch ({arg}), including main")
        if arg == "--repo":
            remote_given_as_option = True
            index += 2
            continue
        if arg.startswith("--repo="):
            remote_given_as_option = True
        elif arg in _PUSH_OPTIONS_WITH_VALUE:
            index += 2
            continue
        elif not arg.startswith("-"):
            positional.append(arg)
        index += 1
    refspecs = positional if remote_given_as_option else positional[1:]
    destinations: list[str | None] = []
    if not refspecs:
        destinations.append(current_branch)
    else:
        for spec in refspecs:
            spec = spec.lstrip("+")
            destination = spec.split(":", 1)[1] if ":" in spec else spec
            if destination == "HEAD":
                destination = current_branch or "HEAD"
            destinations.append(destination.removeprefix("refs/heads/"))
    for target in destinations:
        if target in PROTECTED_BRANCHES:
            return PUSH_REASON.format(branch=target)
    return None


def _stash_blocked(args: list[str]) -> bool:
    if not args:
        return True
    action = args[0]
    if action in ("pop", "clear"):
        return True
    if action == "drop":
        return len(args) < 2
    if action == "save":
        return not any(not arg.startswith("-") for arg in args[1:])
    if action == "push" or action.startswith("-"):
        options = args[1:] if action == "push" else args
        return not any(
            arg in ("-m", "--message") or arg.startswith("--message=") for arg in options
        )
    return False


def check_command(command: str, current_branch: str | None) -> str | None:
    """The reason to block `command`, or None to let it run."""
    branch = current_branch
    for tokens in _simple_commands(command):
        parsed = _git_subcommand(tokens)
        if parsed is None:
            continue
        subcommand, args = parsed
        if subcommand in ("switch", "checkout"):
            branch = _branch_after_switch(args, branch)
        elif subcommand == "push":
            reason = _push_reason(args, branch)
            if reason:
                return reason
        elif subcommand == "stash" and _stash_blocked(args):
            return STASH_REASON.format(command=" ".join(["git", subcommand, *args]))
    return None


def _current_branch(cwd: str | None) -> str | None:
    result = subprocess.run(
        ["git", "-C", cwd or ".", "symbolic-ref", "--quiet", "--short", "HEAD"],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() or None if result.returncode == 0 else None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        command = (payload.get("tool_input") or {}).get("command")
        if not isinstance(command, str):
            return 0
        reason = check_command(command, current_branch=_current_branch(payload.get("cwd")))
    except Exception as error:  # a broken guard must not stop every command
        print(f"guard_bash: {error!r}", file=sys.stderr)
        return 0
    if reason is not None:
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": reason,
                    }
                }
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
