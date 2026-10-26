"""Developer commands run by hand against the app's Postgres (issue #447).

    uv run python -m api.admin purge-narrations --prompt-version qb-persona-v3 --dry-run

`purge-narrations` deletes rows from the persona narration cache
(`persona_cache`, `api.persona.cache`) in whatever database `DATABASE_URL`
names: production from a laptop, or from a Render shell. The cache keys are
sha256 digests, so a row can't be picked by team or player; the selectors are
what each row records in the clear:

- `--prompt-version V` (repeatable): rows written under prompt `V`. Team
  narrations carry `api.config.PROMPT_VERSION`, QB narrations
  `QB_PROMPT_VERSION` (`api.deps.get_qb_narration_cache`).
- `--older-than DAYS`: rows written more than DAYS days ago. With
  `--prompt-version`, both must hold.
- `--all`: every row. Asks for the word `purge` to be typed unless `--yes`
  is passed.

With no selector it refuses and prints usage. `--dry-run` counts and deletes
nothing. Both print counts per prompt version.

Deliberately a command and not an HTTP endpoint: a purge route would be
attack surface for a one-person dev tool. A database error is a one-line
message and exit status 1, never a traceback; the DSN is never printed.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from typing import Any

import psycopg

from api.persona.cache import CONNECT_TIMEOUT_SECONDS

# The word `--all` asks to be typed before it deletes anything.
CONFIRM_WORD = "purge"

# Both selectors are always sent; a NULL one matches every row, so `--all`
# is the same statement with neither set.
_WHERE = """
    (%(prompt_versions)s::text[] IS NULL
        OR prompt_version = ANY(%(prompt_versions)s::text[]))
    AND (%(older_than_days)s::integer IS NULL
        OR created_at < now() - make_interval(days => %(older_than_days)s::integer))
"""
COUNT_SQL = (
    "SELECT prompt_version, count(*) FROM persona_cache WHERE"
    + _WHERE
    + "GROUP BY prompt_version ORDER BY prompt_version"
)
DELETE_SQL = "DELETE FROM persona_cache WHERE" + _WHERE + "RETURNING prompt_version"

Connect = Callable[..., Any]
Confirm = Callable[[str], str]


def _psycopg_connect(dsn: str, **kwargs: Any) -> Any:
    return psycopg.connect(dsn, **kwargs)


def _non_negative_days(value: str) -> int:
    try:
        days = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a whole number of days: {value!r}") from None
    if days < 0:
        raise argparse.ArgumentTypeError(f"days can't be negative: {value}")
    return days


def _parsers() -> tuple[argparse.ArgumentParser, argparse.ArgumentParser]:
    """The command-line parser and its `purge-narrations` subparser."""
    parser = argparse.ArgumentParser(
        prog="python -m api.admin", description="Developer commands for apps/api."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    purge = commands.add_parser(
        "purge-narrations",
        help="delete cached narrations from persona_cache",
        description=(
            "Delete cached narrations from persona_cache in DATABASE_URL. "
            "Pick rows with --all, --prompt-version or --older-than."
        ),
    )
    purge.add_argument("--all", action="store_true", help="every cached narration")
    purge.add_argument(
        "--prompt-version",
        action="append",
        metavar="V",
        dest="prompt_versions",
        help="narrations written under prompt V (repeatable)",
    )
    purge.add_argument(
        "--older-than",
        type=_non_negative_days,
        metavar="DAYS",
        dest="older_than_days",
        help="narrations written more than DAYS days ago",
    )
    purge.add_argument(
        "--dry-run", action="store_true", help="print what would be deleted; delete nothing"
    )
    purge.add_argument("--yes", action="store_true", help="skip --all's typed confirmation")
    return parser, purge


def _report(verb: str, counts: Counter[str]) -> str:
    total = sum(counts.values())
    noun = "narration" if total == 1 else "narrations"
    lines = [f"{verb} {total} {noun}:"]
    lines += [f"  {version}: {counts[version]}" for version in sorted(counts)]
    return "\n".join(lines)


def _purge(
    args: argparse.Namespace,
    usage: Callable[[], None],
    *,
    database_url: str | None,
    connect: Connect,
    confirm: Confirm,
) -> int:
    narrowed = args.prompt_versions is not None or args.older_than_days is not None
    if not args.all and not narrowed:
        usage()
        print("purge-narrations: pick --all, --prompt-version or --older-than", file=sys.stderr)
        return 2
    if args.all and narrowed:
        usage()
        print(
            "purge-narrations: --all can't be combined with --prompt-version or --older-than",
            file=sys.stderr,
        )
        return 2
    if not database_url:
        print("purge-narrations: DATABASE_URL is not set; nothing deleted", file=sys.stderr)
        return 1

    params = {
        "prompt_versions": args.prompt_versions,
        "older_than_days": args.older_than_days,
    }
    try:
        with connect(database_url, connect_timeout=CONNECT_TIMEOUT_SECONDS) as conn:
            if args.dry_run or (args.all and not args.yes):
                rows = conn.execute(COUNT_SQL, params).fetchall()
                counts: Counter[str] = Counter({str(v): int(n) for v, n in rows})
                if not counts:
                    print("No narrations match; nothing deleted.")
                    return 0
                if args.dry_run:
                    print(_report("Would delete", counts))
                    return 0
                print(_report("--all matches", counts))
                try:
                    answer = confirm(f"Type {CONFIRM_WORD!r} to delete them all: ")
                except EOFError:
                    answer = ""
                if answer.strip() != CONFIRM_WORD:
                    print("Not confirmed; nothing deleted.", file=sys.stderr)
                    return 1
            deleted = conn.execute(DELETE_SQL, params).fetchall()
            conn.commit()
    except psycopg.Error as exc:
        message = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
        print(f"purge-narrations: database error: {message}", file=sys.stderr)
        return 1

    deleted_counts = Counter(str(row[0]) for row in deleted)
    if not deleted_counts:
        print("No narrations match; nothing deleted.")
    else:
        print(_report("Deleted", deleted_counts))
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    database_url: str | None = None,
    connect: Connect = _psycopg_connect,
    confirm: Confirm = input,
) -> int:
    """Run one admin command; returns the exit status. `database_url`
    defaults to `api.config.DATABASE_URL` when called from the command line
    (`__main__` below); tests pass a fake `connect`."""
    parser, purge_parser = _parsers()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # argparse's own usage errors
        return exc.code if isinstance(exc.code, int) else 2
    if args.command == "purge-narrations":
        return _purge(
            args,
            lambda: purge_parser.print_usage(sys.stderr),
            database_url=database_url,
            connect=connect,
            confirm=confirm,
        )
    parser.print_usage(sys.stderr)  # pragma: no cover - argparse requires a command
    return 2  # pragma: no cover


if __name__ == "__main__":
    from api.config import DATABASE_URL

    sys.exit(main(database_url=DATABASE_URL))
