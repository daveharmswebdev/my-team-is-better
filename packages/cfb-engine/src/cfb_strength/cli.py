"""Umbrella CLI for cfb-strength: `cfb ingest`, `cfb rate`, `cfb serve`.

This module only dispatches to entry points owned by other modules
(`ingest.ingest_season.main`, `ratings.compute_ratings.main`,
`mcp_server.server.main`) -- it contains no ingestion, rating, or evidence
logic of its own. Imports are deferred into each branch so that, e.g.,
`cfb ingest --years 2005` doesn't pay the cost of importing the MCP SDK.
"""

from __future__ import annotations

import sys

USAGE = """\
usage: cfb <command> [args]

commands:
  ingest --years YEARS [--force] [--season-types TYPES] [--db-path PATH]
      Fetch and store CFBD game/team data for one or more seasons.

  rate --years YEARS [--method METHOD]
      Compute and store team ratings for one or more seasons (default method: keener).

  serve
      Start the MCP server (stdio transport) exposing ranking/evidence tools.

Run 'cfb <command> --help' for command-specific options.
"""


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
        from cfb_strength.ingest.ingest_season import main as ingest_main

        return ingest_main(rest)

    if command == "rate":
        from cfb_strength.ratings.compute_ratings import main as rate_main

        return rate_main(rest)

    if command == "serve":
        from cfb_strength.mcp_server.server import main as serve_main

        serve_main()
        return 0

    print(f"error: unknown command {command!r}\n", file=sys.stderr)
    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
