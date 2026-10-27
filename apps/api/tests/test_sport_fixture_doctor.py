"""The hand-built sport fixture passes `cfb doctor` as a slice (issue #254).

`tests/fixtures/sport_fixture.py`'s db is the only apps/api fixture with NFL
ratings, so it is what a validator verifies NFL Elo and grounding against.
`.claude/agents/validator.md` only trusts a fixture whose doctor findings are
the waivable slice findings (`season_behind_cache` for omitted batches,
`season_missing_ratings` / `season_missing_player_stats` for the fixture's own
seasons under what it deliberately leaves out, `league_has_no_games`).
Anything else -- `no_cfb_mascots`, `season_missing_elo_ledger`,
`schema_not_current` -- blocks verification of every league in it.

The waivers are not re-implemented here: `build_fixture.py` already enforces
them on the committed verdict fixture, and its `--check-db/--slice` mode runs
that same check on this db against `sport_fixture.doctor_slice`. It runs as a
subprocess because the doctor lives in `cfb_strength.ingest`, which the test
suite does not import (see `conftest.py`); `build_fixture.py` is the one
sanctioned importer (docs/ARCHITECTURE.md §2).

2003 is checked as well as the default season because #151's
contested-by-sport tests build the fixture there.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from fixtures.sport_fixture import YEAR, doctor_slice, make_sport_fixture_db

BUILD_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "build_fixture.py"


def _check(db: Path, slice_spec: dict[str, dict[str, object]]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(BUILD_FIXTURE),
            "--check-db",
            str(db),
            "--slice",
            json.dumps(slice_spec),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


@pytest.mark.parametrize("year", [YEAR, 2003])
def test_sport_fixture_has_only_waivable_doctor_findings(tmp_path: Path, year: int) -> None:
    result = _check(make_sport_fixture_db(tmp_path, year), doctor_slice(year))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "currency check passed" in result.stdout


def test_every_cfb_team_has_a_mascot(tmp_path: Path) -> None:
    # The doctor's `no_cfb_mascots` fires only when *none* of the CFB teams
    # has one, so the doctor test above stays green if a single mascot is
    # dropped. A real ingest's #77 enrichment gives every CFB team CFBD lists
    # a mascot; held per team here so the fixture keeps matching that.
    conn = sqlite3.connect(make_sport_fixture_db(tmp_path))
    try:
        rows = conn.execute("SELECT school, mascot FROM teams WHERE sport = 'cfb'").fetchall()
    finally:
        conn.close()
    assert rows
    assert [school for school, mascot in rows if not mascot] == []


def test_a_slice_that_misdescribes_the_fixture_fails(tmp_path: Path) -> None:
    # Guards the check itself: claiming elo_career ratings the fixture
    # doesn't store must be reported, not waived.
    db = make_sport_fixture_db(tmp_path)
    wrong = doctor_slice(YEAR)
    rated = wrong["cfb"]["rated"]
    assert isinstance(rated, dict)
    rated["elo_career"] = [YEAR]
    result = _check(db, wrong)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "cfb elo_career rated seasons are (), expected (2023,)" in result.stderr


@pytest.mark.parametrize("year", [YEAR, 2003])
def test_sport_fixture_elo_rows_match_the_engine(tmp_path: Path, year: int) -> None:
    # `sport_fixture.build_elo` is a hand copy of the engine's Elo walk (the
    # suite may not import `cfb_strength.ratings`). `build_fixture.py
    # --check-elo-parity` re-rates a copy of the db with the engine's own
    # `compute_and_store(..., "elo")` and compares the ratings, ledger steps
    # and ledger configs exactly, so an engine retune or a drifted copy turns
    # this red instead of leaving the fixture on stale numbers (#254).
    db = make_sport_fixture_db(tmp_path, year)
    result = subprocess.run(
        [sys.executable, str(BUILD_FIXTURE), "--check-elo-parity", str(db)],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "elo parity passed" in result.stdout
