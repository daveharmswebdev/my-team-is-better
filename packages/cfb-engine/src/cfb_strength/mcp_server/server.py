"""MCP server exposing recursive-SOS ranking data and evidence as tools.

This module composes two things read-only:
  - `cfb_strength.db.connection.get_conn` (shared infra) for simple listing
    queries (`list_seasons`, `get_rankings`) that don't need the evidence
    layer's per-team reasoning.
  - `cfb_strength.evidence.proof` (evidence-agent's module) for anything that
    needs a team's full case or a two-team comparison.

Every tool opens its own connection with `mode=ro` and closes it before
returning -- this server never writes to the database under any
circumstance. Every tool catches its own exceptions and returns a
JSON-serializable `{"error": ...}` dict rather than raising across the MCP
boundary, so a malformed request (bad year, ambiguous team name) surfaces as
data the calling LLM can read and react to, not a protocol-level failure.

The database holds BOTH leagues (college football and the NFL) in the same
tables, and `ratings`' UNIQUE(year, method, team_id) deliberately excludes
`sport`. So every tool takes a `sport` argument (default "cfb", so pre-NFL
clients are unchanged), every direct query against `ratings` is scoped by
it, and it is threaded into every evidence call. An unscoped query here does
not fail -- it silently blends the leagues (issue #86).

Static, parameter-free catalog data (which seasons/methods exist, the full
team list, methodology/data-source attribution) is exposed as MCP
**resources**, not tools -- a client can read these once and hold them as
context instead of the model spending a tool call to "discover" data that
never changes per-request. `list_seasons`/`get_rankings` stay as tools too
(for clients that only support tool calls); the `seasons` resource shares
the exact same query helper so there is one source of truth, not two.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from typing import Any, Literal

from cfb_strength.config import DB_PATH
from cfb_strength.contracts import (
    AmbiguousTeamError,
    SameTeamComparisonError,
    # `Sport` is a Literal, so the generated MCP tool schema still advertises
    # the valid leagues to the calling model -- now from the one contract
    # alias instead of a local copy (#112).
    Sport,
    UnknownTeamError,
    UnknownYearError,
)
from cfb_strength.db.connection import get_conn
from cfb_strength.evidence.credits import get_credits
from cfb_strength.evidence.proof import build_comparison, build_team_case, list_available_years

from mcp.server.mcpserver import MCPServer

mcp: MCPServer = MCPServer(
    "cfb-strength",
    instructions=(
        "Recursive strength-of-schedule rankings for TWO leagues: college "
        "football (sport='cfb') and the NFL (sport='nfl'). Every ranking tool "
        "takes a `sport` argument that selects the league; it defaults to "
        "'cfb', so pass sport='nfl' for any NFL question. Years and team "
        "names are per league -- a year loaded for one sport may be missing "
        "for the other. Read resource://cfb-strength/seasons (one entry per "
        "sport and year) and resource://cfb-strength/teams (each team tagged "
        "with its sport) for the catalog instead of guessing valid inputs, "
        "and resource://cfb-strength/credits for the methodology citation and "
        "per-sport data source -- cite both whenever you present a ranking as "
        "fact. Use get_rankings for a top-N leaderboard, get_team_season for "
        "one team's full resume, compare_teams for head-to-head evidence "
        "between two named teams, and get_champion as a shortcut for 'who was "
        "#1' with the same evidence shape as get_team_season."
    ),
)


def _get_conn() -> sqlite3.Connection:
    """Open a read-only connection to the project sqlite db. Never writes."""
    return get_conn(DB_PATH, read_only=True)


def _unknown_year(e: UnknownYearError, sport: str) -> dict[str, Any]:
    return {
        "error": "unknown_year",
        "year": e.year,
        "sport": sport,
        "available_years": e.available_years,
    }


def _season_catalog(conn: sqlite3.Connection) -> dict[str, Any]:
    """Every (sport, year, method) combination that has computed ratings,
    one entry per (sport, year), ordered by sport then year. Shared by the
    `list_seasons` tool and the `seasons` resource so there's exactly one
    query for this, not two drifting copies.
    """
    rows = conn.execute(
        "SELECT DISTINCT sport, year, method FROM ratings ORDER BY sport, year, method"
    ).fetchall()

    seasons: dict[tuple[str, int], list[str]] = {}
    for row in rows:
        seasons.setdefault((str(row["sport"]), int(row["year"])), []).append(str(row["method"]))

    return {
        "seasons": [
            {"sport": sport, "year": year, "methods": sorted(methods)}
            for (sport, year), methods in sorted(seasons.items())
        ]
    }


@mcp.tool()
def list_seasons() -> dict[str, Any]:
    """List every season that has computed ratings, one entry per
    (sport, year): `{"sport": "cfb" | "nfl", "year": ..., "methods": [...]}`.
    Call this FIRST when you're unsure which seasons/methods are actually
    loaded for a league -- it tells you what valid `year`/`method`/`sport`
    inputs to get_rankings, get_team_season, compare_teams, and get_champion
    look like. A year present for one sport may be absent for the other. It
    returns no team-level data itself. Prefer reading
    resource://cfb-strength/seasons directly if your client supports
    resources; this tool exists for clients that only support tool calls.
    """
    try:
        conn = _get_conn()
        try:
            return _season_catalog(conn)
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001 -- must never raise across the MCP boundary
        return {"error": str(e)}


@mcp.resource(
    "resource://cfb-strength/seasons",
    name="seasons",
    description=(
        "Catalog of every season with computed ratings, one entry per "
        "(sport, year) with its methods -- sport is 'cfb' (college football) "
        "or 'nfl'. Read this once to know what sport/year/method inputs are "
        "valid elsewhere, instead of spending a tool call to discover it."
    ),
    mime_type="application/json",
)
def seasons_resource() -> dict[str, Any]:
    conn = _get_conn()
    try:
        return _season_catalog(conn)
    finally:
        conn.close()


@mcp.resource(
    "resource://cfb-strength/teams",
    name="teams",
    description=(
        "Full catalog of every team in the database, across both leagues "
        "(id, school/team name, classification, sport -- 'cfb' or 'nfl'). "
        "Static reference data -- read this to resolve or spell-check a team "
        "name, and to see which league it belongs to, before calling a tool "
        "instead of guessing."
    ),
    mime_type="application/json",
)
def teams_resource() -> dict[str, Any]:
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT id, school, classification, sport FROM teams ORDER BY school"
        ).fetchall()
    finally:
        conn.close()
    return {
        "count": len(rows),
        "teams": [
            {
                "team_id": int(row["id"]),
                "school": row["school"],
                "classification": row["classification"],
                "sport": row["sport"],
            }
            for row in rows
        ],
    }


@mcp.resource(
    "resource://cfb-strength/credits",
    name="credits",
    description=(
        "Attribution for the ranking methodologies and the underlying game "
        "data. Read this before presenting a ranking as fact -- cite the "
        "method that produced it (the `method` field on every ranking tool; "
        "`methodologies` here is a LIST, one entry per method this server "
        "implements) and the data source for its sport, rather than "
        "presenting either as this server's own analysis or data collection."
    ),
    mime_type="application/json",
)
def credits_resource() -> dict[str, Any]:
    return dataclasses.asdict(get_credits())


@mcp.tool()
def get_rankings(
    year: int, top_n: int = 25, method: str = "keener", sport: Sport = "cfb"
) -> dict[str, Any]:
    """Return the top-N ranked teams for one league's season, ordered by
    rank ascending. `sport` selects the league: "cfb" (college football, the
    default) or "nfl". Use this for leaderboard-style requests spanning MANY
    teams ("show me the top 10 of 2005", "who's ranked around #15"). For
    deep evidence on a SINGLE named team's full resume (schedule, quality
    wins, worst loss) use get_team_season instead -- this tool returns only
    rank, rating and the win-loss-tie record (`wins`, `losses`, `ties`; a
    tie is a completed game with equal scores), no game-by-game detail. For
    the #1 team specifically with full evidence, use get_champion.
    """
    try:
        conn = _get_conn()
        try:
            exists = conn.execute(
                "SELECT 1 FROM ratings WHERE year = ? AND method = ? AND sport = ? LIMIT 1",
                (year, method, sport),
            ).fetchone()
            if exists is None:
                raise UnknownYearError(year, list_available_years(conn, method, sport=sport))

            rows = conn.execute(
                """
                SELECT r.rank AS rank, r.rating AS rating, r.wins AS wins,
                       r.losses AS losses, r.ties AS ties,
                       r.team_id AS team_id, t.school AS school
                FROM ratings r
                JOIN teams t ON t.id = r.team_id
                WHERE r.year = ? AND r.method = ? AND r.sport = ?
                ORDER BY r.rank ASC
                LIMIT ?
                """,
                (year, method, sport, top_n),
            ).fetchall()
        finally:
            conn.close()

        return {
            "year": year,
            "method": method,
            "sport": sport,
            "count": len(rows),
            "rankings": [
                {
                    "rank": int(row["rank"]),
                    "team_id": int(row["team_id"]),
                    "team_name": row["school"],
                    "rating": float(row["rating"]),
                    "wins": int(row["wins"]),
                    "losses": int(row["losses"]),
                    "ties": int(row["ties"]),
                }
                for row in rows
            ],
        }
    except UnknownYearError as e:
        return _unknown_year(e, sport)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


@mcp.tool()
def get_team_season(
    year: int, team: str, method: str = "keener", sport: Sport = "cfb"
) -> dict[str, Any]:
    """Return ONE team's full evidentiary case for a season: its rank,
    rating, win-loss-tie record, every completed game (with the opponent's rank
    at that snapshot), its quality wins (vs top-25 opponents), and its worst
    loss. `sport` selects the league the team is looked up in: "cfb"
    (college football, the default) or "nfl" -- pass sport="nfl" for an NFL
    team, or it will come back as unknown_team. Use this when the request
    names a SINGLE team ("how good was Texas in 2005?", "what's Ohio State's
    resume?"). If the request instead compares TWO named teams head-to-head,
    use compare_teams. If the request is "who is #1" rather than a named
    team, use get_champion.
    """
    try:
        conn = _get_conn()
        try:
            case = build_team_case(conn, year, team, method=method, sport=sport)
        finally:
            conn.close()
        return dataclasses.asdict(case)
    except AmbiguousTeamError as e:
        return {"error": "ambiguous_team", "query": e.query, "candidates": e.candidates}
    except UnknownTeamError as e:
        # Distinct from ambiguous_team on purpose (issue #100): zero matches is
        # not "which of these did you mean". Deliberately carries no suggestion
        # list -- see contracts.UnknownTeamError for why a fuzzy one cannot work.
        return {"error": "unknown_team", "query": e.query, "year": e.year, "sport": e.sport}
    except UnknownYearError as e:
        return _unknown_year(e, sport)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


@mcp.tool()
def compare_teams(
    year: int, team_a: str, team_b: str, method: str = "keener", sport: Sport = "cfb"
) -> dict[str, Any]:
    """Compare exactly TWO named teams from the same league for a season:
    whether they played head-to-head (and who won), every opponent they both
    played (common opponents) with each side's result, the rating gap
    between them, and a plain-language verdict citing that evidence. `sport`
    selects the league: "cfb" (college football, the default) or "nfl";
    both teams must be in it. Use this for "who's better, X or Y?" or "did X
    deserve to be ranked above Y?" questions naming two teams. For a single
    team's own resume (no comparison), use get_team_season instead.
    """
    try:
        conn = _get_conn()
        try:
            comparison = build_comparison(conn, year, team_a, team_b, method=method, sport=sport)
        finally:
            conn.close()
        return dataclasses.asdict(comparison)
    except SameTeamComparisonError as e:
        return {"error": "same_team_comparison", "team": e.team_name}
    except AmbiguousTeamError as e:
        return {"error": "ambiguous_team", "query": e.query, "candidates": e.candidates}
    except UnknownTeamError as e:
        # Distinct from ambiguous_team on purpose (issue #100): zero matches is
        # not "which of these did you mean". Deliberately carries no suggestion
        # list -- see contracts.UnknownTeamError for why a fuzzy one cannot work.
        return {"error": "unknown_team", "query": e.query, "year": e.year, "sport": e.sport}
    except UnknownYearError as e:
        return _unknown_year(e, sport)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


@mcp.tool()
def get_champion(year: int, method: str = "keener", sport: Sport = "cfb") -> dict[str, Any]:
    """Convenience lookup for "who was the best/greatest team in <year>?":
    resolves the #1-ranked team for one league's season and returns its FULL
    evidentiary case (same shape as get_team_season -- schedule, quality
    wins, worst loss) in one call, instead of requiring get_rankings followed
    by a separate get_team_season lookup. `sport` selects the league: "cfb"
    (college football, the default) or "nfl" -- the two leagues each have
    their own #1 for the same year. If you already know which team you care
    about, use get_team_season directly; for a two-team question use
    compare_teams.
    """
    try:
        conn = _get_conn()
        try:
            row = conn.execute(
                """
                SELECT t.school AS school
                FROM ratings r
                JOIN teams t ON t.id = r.team_id
                WHERE r.year = ? AND r.method = ? AND r.sport = ? AND r.rank = 1
                """,
                (year, method, sport),
            ).fetchone()
            if row is None:
                raise UnknownYearError(year, list_available_years(conn, method, sport=sport))
            case = build_team_case(conn, year, str(row["school"]), method=method, sport=sport)
        finally:
            conn.close()
        return dataclasses.asdict(case)
    except AmbiguousTeamError as e:
        return {"error": "ambiguous_team", "query": e.query, "candidates": e.candidates}
    except UnknownTeamError as e:
        # Distinct from ambiguous_team on purpose (issue #100): zero matches is
        # not "which of these did you mean". Deliberately carries no suggestion
        # list -- see contracts.UnknownTeamError for why a fuzzy one cannot work.
        return {"error": "unknown_team", "query": e.query, "year": e.year, "sport": e.sport}
    except UnknownYearError as e:
        return _unknown_year(e, sport)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


def main() -> None:
    """Start the MCP server on the stdio transport."""
    mcp.run()


if __name__ == "__main__":
    main()
