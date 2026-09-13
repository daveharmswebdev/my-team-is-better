"""Umbrella CLI for cfb-strength: `cfb ingest`, `cfb rate`, `cfb serve`,
`cfb doctor`.

This module only dispatches to entry points owned by other modules
(`ingest.ingest_season.main`, `ingest.nflverse.ingest_season.main`,
`ratings.compute_ratings.main`, `mcp_server.server.main`,
`ingest.currency.main`) -- it contains no
ingestion, rating, or evidence logic of its own. Imports are deferred into
each branch so that, e.g., `cfb ingest --years 2005` doesn't pay the cost of
importing the MCP SDK.

`ingest --sport` (added for issue #51) dispatches through
`INGEST_ENTRY_POINTS` to one of the independent per-league orchestration
modules -- see `.importlinter`'s
`no-nflverse-import-of-cfbd / no-cfbd-import-of-nflverse` contract, which forbids those two modules
importing each other. `--sport` is stripped out of `rest` here (both target
mains have their own, unrelated argparse parsers and know nothing about
`--sport`) before the remaining args are passed through unchanged, so
`cfb ingest --years 2005` (no `--sport`) behaves identically to before this
change.

The league and method lists in `USAGE` are built from
`cfb_strength.contracts`' `Sport`/`Method` aliases (issue #112).
`INGEST_ENTRY_POINTS`' keys are written out by hand, one per league with its
own ingest stack, and tests/test_contract_vocabularies.py fails if they and
the alias disagree.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import get_args

from cfb_strength.contracts import Method, Sport

_SPORT_CHOICES = ",".join(get_args(Sport))
_METHOD_CHOICES = ",".join(get_args(Method))

IngestMain = Callable[[list[str]], int]


def _cfb_ingest_main() -> IngestMain:
    from cfb_strength.ingest.ingest_season import main

    return main


def _nfl_ingest_main() -> IngestMain:
    from cfb_strength.ingest.nflverse.ingest_season import main

    return main


# League -> loader for that league's ingest entry point. Loaders rather than
# the imported functions themselves, so each league's ingest stack is only
# imported when it is selected (see the module docstring). They are typed
# imports rather than importlib lookups on purpose: mypy --strict checks each
# target `main`'s signature against `IngestMain`, so a `main` that grows a
# required argument fails type-checking here instead of crashing at runtime.
INGEST_ENTRY_POINTS: dict[str, Callable[[], IngestMain]] = {
    "cfb": _cfb_ingest_main,
    "nfl": _nfl_ingest_main,
}

USAGE = f"""\
usage: cfb <command> [args]

commands:
  ingest --years YEARS [--sport {{{_SPORT_CHOICES}}}] [--force] [--season-types TYPES] [--db-path PATH]
      Fetch and store game/team data for one or more seasons. --sport
      defaults to "cfb" (CFBD); "nfl" ingests nflverse data instead.

  rate --years YEARS [--method {{{_METHOD_CHOICES}}}] [--sport {{{_SPORT_CHOICES}}}]
      Compute and store team ratings for one or more seasons.
      --method defaults to "keener" (eigenvector strength-of-schedule; the
      golden-dataset-validated default). "elo" rates each season in
      isolation; "elo_career" carries ratings across seasons with offseason
      mean reversion. --sport defaults to "cfb" and mirrors `ingest --sport`.

  serve
      Start the MCP server (stdio transport) exposing ranking/evidence tools.

  doctor [--db-path PATH] [--raw-dir PATH]
      Read-only check that the db's data is current: schema, every league
      ({_SPORT_CHOICES}) ingested, no season behind the committed raw cache,
      every method ({_METHOD_CHOICES}) rated, CFB mascots enriched. Exits 0
      only when it is; never migrates or writes the db.

Run 'cfb <command> --help' for command-specific options.
"""


def _split_out_sport_flag(rest: list[str]) -> tuple[str, list[str]]:
    """Pull `--sport VALUE` / `--sport=VALUE` out of `ingest`'s args.

    Returns `(sport, remaining_args)`. Defaults to "cfb" when absent, since
    neither target orchestration module's own argparse parser knows about
    `--sport` -- it's a dispatch-only concern of this CLI layer.
    """
    sport = "cfb"
    remaining: list[str] = []
    i = 0
    while i < len(rest):
        arg = rest[i]
        if arg == "--sport":
            if i + 1 >= len(rest):
                raise ValueError("--sport requires a value")
            sport = rest[i + 1]
            i += 2
            continue
        if arg.startswith("--sport="):
            sport = arg.split("=", 1)[1]
            i += 1
            continue
        remaining.append(arg)
        i += 1
    return sport, remaining


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv

    if not args:
        print(USAGE, file=sys.stderr)
        return 2

    command, rest = args[0], args[1:]

    if command in ("-h", "--help"):
        print(USAGE)
        return 0

    if command == "ingest":
        try:
            sport, ingest_args = _split_out_sport_flag(rest)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2

        load_ingest_main = INGEST_ENTRY_POINTS.get(sport)
        if load_ingest_main is None:
            expected = " or ".join(repr(s) for s in INGEST_ENTRY_POINTS)
            print(f"error: unknown --sport {sport!r}, expected {expected}\n", file=sys.stderr)
            return 2

        return load_ingest_main()(ingest_args)

    if command == "rate":
        from cfb_strength.ratings.compute_ratings import main as rate_main

        return rate_main(rest)

    if command == "serve":
        from cfb_strength.mcp_server.server import main as serve_main

        serve_main()
        return 0

    if command == "doctor":
        from cfb_strength.ingest.currency import main as doctor_main

        return doctor_main(rest)

    print(f"error: unknown command {command!r}\n", file=sys.stderr)
    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
