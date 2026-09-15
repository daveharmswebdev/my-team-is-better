"""Real fact blocks and team catalogs for the typed-claim tests (issue #290).

Every block here is the exact string production hands the narrator: the
engine's `build_team_case` / `build_comparison`, then
`TeamCaseOut.from_dataclass` / `ComparisonResultOut.from_dataclass`, then
`api.persona.service`'s own `team_case_fact_block_json` /
`comparison_fact_block_json`. A hand-written block would drift from
production the first time an exclusion map changed.

Three sources:

* the committed `cfb_verdict_fixture.sqlite3` (real CFBD data, real CFBD
  mascots and aliases): 2017 Alabama, 2005 USC and 2005 Texas;
* `sport_fixture.py`'s NFL tie cluster, built fresh: 2023 Kilo Kings vs Lima
  Lions, with a tie and a rematch against the common opponent Mike Mustangs;
* `method_fixture.py`, built fresh: one comparison per registered rating
  method, so a rating claim is rendered under keener, elo and elo_career.

Also the assertion helpers both claim test files share. Not part of the
pytest suite itself (doesn't match `test_*.py`).
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import cache
from pathlib import Path

from cfb_strength.db.connection import get_conn
from cfb_strength.evidence.proof import build_comparison, build_team_case

from api.models import ComparisonResultOut, Method, TeamCaseOut
from api.persona.claims import ClaimOutcome, check_and_render
from api.persona.service import comparison_fact_block_json, team_case_fact_block_json
from api.repositories.teams import TeamRecord, list_team_records

CFB_FIXTURE_DB = Path(__file__).parent / "cfb_verdict_fixture.sqlite3"

NFL_YEAR = 2023
KILO_KINGS = "Kilo Kings"
LIMA_LIONS = "Lima Lions"
MIKE_MUSTANGS = "Mike Mustangs"

METHOD_FIXTURE_YEAR = 2023
ALPHA_STATE = "Alpha State"
BRAVO_TECH = "Bravo Tech"


@cache
def cfb_catalog() -> tuple[TeamRecord, ...]:
    """Every CFB team in the committed fixture, with its mascot and aliases."""
    conn = get_conn(CFB_FIXTURE_DB, read_only=True)
    try:
        return tuple(list_team_records(conn, "cfb"))
    finally:
        conn.close()


@cache
def cfb_team_case_block(year: int, team: str, method: Method = "keener") -> str:
    """The production team-case fact block from the committed CFB fixture."""
    conn = get_conn(CFB_FIXTURE_DB, read_only=True)
    try:
        case = build_team_case(conn, year, team, method=method, sport="cfb")
    finally:
        conn.close()
    return team_case_fact_block_json(TeamCaseOut.from_dataclass(case))


@cache
def cfb_comparison_block(year: int, team_a: str, team_b: str, method: Method = "keener") -> str:
    """The production comparison fact block from the committed CFB fixture."""
    conn = get_conn(CFB_FIXTURE_DB, read_only=True)
    try:
        comparison = build_comparison(conn, year, team_a, team_b, method=method, sport="cfb")
    finally:
        conn.close()
    return comparison_fact_block_json(ComparisonResultOut.from_dataclass(comparison))


def nfl_tie_comparison_block(sport_db: Path) -> str:
    """2023 Kilo Kings vs Lima Lions (keener) from a `make_sport_fixture_db` db."""
    conn = get_conn(sport_db, read_only=True)
    try:
        comparison = build_comparison(
            conn, NFL_YEAR, KILO_KINGS, LIMA_LIONS, method="keener", sport="nfl"
        )
    finally:
        conn.close()
    return comparison_fact_block_json(ComparisonResultOut.from_dataclass(comparison))


def catalog_of(db: Path, sport: str) -> tuple[TeamRecord, ...]:
    """Every team for `sport` in a freshly built fixture db."""
    conn = get_conn(db, read_only=True)
    try:
        return tuple(list_team_records(conn, sport))
    finally:
        conn.close()


def method_comparison_block(method_db: Path, method: Method) -> str:
    """Alpha State vs Bravo Tech under `method`, from a `make_method_fixture_db` db."""
    conn = get_conn(method_db, read_only=True)
    try:
        comparison = build_comparison(
            conn, METHOD_FIXTURE_YEAR, ALPHA_STATE, BRAVO_TECH, method=method, sport="cfb"
        )
    finally:
        conn.close()
    return comparison_fact_block_json(ComparisonResultOut.from_dataclass(comparison))


def submit(
    text: str,
    claims: list[dict[str, object]],
    block: str,
    catalog: Sequence[TeamRecord],
) -> ClaimOutcome:
    """Run one `submit_narration` tool input through the validator."""
    return check_and_render({"text": text, "claims": claims}, block, catalog)


def rendered(
    text: str,
    claims: list[dict[str, object]],
    block: str,
    catalog: Sequence[TeamRecord],
) -> str:
    """The rendered text of a submission that must be accepted."""
    outcome = submit(text, claims, block, catalog)
    assert outcome.errors == (), outcome.errors
    assert outcome.text is not None
    return outcome.text


def rejected(
    text: str,
    claims: list[dict[str, object]],
    block: str,
    catalog: Sequence[TeamRecord],
) -> tuple[str, ...]:
    """The errors of a submission that must be rejected (and so renders nothing)."""
    outcome = submit(text, claims, block, catalog)
    assert outcome.errors, f"accepted, rendered as {outcome.text!r}"
    assert outcome.text is None
    return outcome.errors


def assert_an_error_says(errors: Sequence[str], *needles: str) -> None:
    """One single error message contains every one of `needles`."""
    assert any(all(needle in error for needle in needles) for error in errors), (
        f"no error contains all of {needles!r}: {list(errors)!r}"
    )
