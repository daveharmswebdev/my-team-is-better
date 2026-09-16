"""The harness dataset: spike #200's 11 fact blocks.

Each case is built the way its `/api/verdict` route builds it: the engine's
`build_team_case` / `build_comparison`, then `TeamCaseOut.from_dataclass` /
`ComparisonResultOut.from_dataclass`, then `api.persona.service`'s own
`team_case_fact_block_json` / `comparison_fact_block_json`, `is_contested`,
the `api.persona.fallback` text and the sport's `list_team_records` catalog.
`tests/test_persona_eval_harness.py` pins every block, contested flag,
fallback text and system prompt to what the route actually hands the
narrator, through the conftest `client` / `sport_client` fixtures.

Sources: the committed `tests/fixtures/cfb_verdict_fixture.sqlite3` for the
ten CFB cases, and `tests/fixtures/sport_fixture.make_sport_fixture_db`
(built in a temporary directory, removed afterwards) for the NFL comparison.
`user_team` is `None` for every case: every verdict route defaults it so.
"""

from __future__ import annotations

import sqlite3
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from cfb_strength.db.connection import get_conn
from cfb_strength.evidence.proof import build_comparison, build_team_case
from fixtures.sport_fixture import make_sport_fixture_db

from api.models import ComparisonResultOut, Method, Sport, TeamCaseOut
from api.persona.fallback import comparison_fallback_text, team_case_fallback_text
from api.persona.service import (
    comparison_fact_block_json,
    is_contested,
    team_case_fact_block_json,
)
from api.repositories.teams import TeamRecord, list_team_records

CFB_FIXTURE_DB = Path(__file__).resolve().parents[1] / "fixtures" / "cfb_verdict_fixture.sqlite3"

CaseKind = Literal["champion", "team_case", "compare"]

_ROUTES: dict[CaseKind, str] = {
    "champion": "/api/verdict/champion",
    "team_case": "/api/verdict/team-case",
    "compare": "/api/verdict/compare",
}


@dataclass(frozen=True)
class CaseSpec:
    """One dataset case before its fact block is built. `teams` is the
    champion (for a champion case, as the fixture ranks it), the team, or
    team_a and team_b."""

    id: str
    kind: CaseKind
    sport: Sport
    year: int
    method: Method
    teams: tuple[str, ...]

    @property
    def route(self) -> str:
        return _ROUTES[self.kind]

    @property
    def request_body(self) -> dict[str, object]:
        """The route's request body for this case, with no `user_team`."""
        body: dict[str, object] = {"year": self.year, "method": self.method, "sport": self.sport}
        if self.kind == "team_case":
            body["team"] = self.teams[0]
        elif self.kind == "compare":
            body["team_a"], body["team_b"] = self.teams
        return body

    @property
    def expected_team(self) -> str | None:
        """The team §8 property 1 expects the narration to name: the champion
        or the team-case team. A comparison has none."""
        return None if self.kind == "compare" else self.teams[0]


def _champion(year: int, team: str) -> CaseSpec:
    return CaseSpec(f"cfb-{year}-champion", "champion", "cfb", year, "keener", (team,))


CASE_SPECS: tuple[CaseSpec, ...] = (
    _champion(2001, "Miami"),
    _champion(2003, "LSU"),
    _champion(2004, "USC"),
    _champion(2005, "Texas"),
    _champion(2013, "Florida State"),
    _champion(2017, "Alabama"),
    _champion(2019, "LSU"),
    CaseSpec("cfb-2005-usc-team-case", "team_case", "cfb", 2005, "keener", ("USC",)),
    CaseSpec(
        "cfb-2013-fsu-msu-compare-keener",
        "compare",
        "cfb",
        2013,
        "keener",
        ("Florida State", "Michigan State"),
    ),
    CaseSpec(
        "cfb-2005-texas-oklahoma-compare-elo", "compare", "cfb", 2005, "elo", ("Texas", "Oklahoma")
    ),
    CaseSpec(
        "nfl-2023-kilo-lima-compare-keener",
        "compare",
        "nfl",
        2023,
        "keener",
        ("Kilo Kings", "Lima Lions"),
    ),
)


@dataclass(frozen=True)
class EvalCase:
    """A case ready to narrate: exactly what production's service would pass
    `narrate()` for it."""

    spec: CaseSpec
    fact_block_json: str
    contested: bool
    fallback_text: str
    catalog: tuple[TeamRecord, ...]
    user_team: str | None = None

    @property
    def id(self) -> str:
        return self.spec.id


def _build_case(conn: sqlite3.Connection, spec: CaseSpec) -> EvalCase:
    if spec.kind == "compare":
        team_a, team_b = spec.teams
        comparison = ComparisonResultOut.from_dataclass(
            build_comparison(conn, spec.year, team_a, team_b, method=spec.method, sport=spec.sport)
        )
        fact_block_json = comparison_fact_block_json(comparison)
        fallback_text = comparison_fallback_text(comparison)
    else:
        case = TeamCaseOut.from_dataclass(
            build_team_case(conn, spec.year, spec.teams[0], method=spec.method, sport=spec.sport)
        )
        fact_block_json = team_case_fact_block_json(case)
        fallback_text = team_case_fallback_text(case)
    return EvalCase(
        spec=spec,
        fact_block_json=fact_block_json,
        contested=is_contested(spec.sport, spec.year),
        fallback_text=fallback_text,
        catalog=tuple(list_team_records(conn, spec.sport)),
    )


def _build_from(db: Path, specs: Sequence[CaseSpec]) -> dict[str, EvalCase]:
    conn = get_conn(db, read_only=True)
    try:
        return {spec.id: _build_case(conn, spec) for spec in specs}
    finally:
        conn.close()


def build_dataset(specs: Sequence[CaseSpec] = CASE_SPECS) -> tuple[EvalCase, ...]:
    """Every case in `specs`, in order. Reads sqlite only; never Postgres."""
    built = _build_from(CFB_FIXTURE_DB, [spec for spec in specs if spec.sport == "cfb"])
    nfl_specs = [spec for spec in specs if spec.sport == "nfl"]
    if nfl_specs:
        with tempfile.TemporaryDirectory(prefix="persona-eval-harness-") as tmp:
            built.update(_build_from(make_sport_fixture_db(Path(tmp)), nfl_specs))
    return tuple(built[spec.id] for spec in specs)
