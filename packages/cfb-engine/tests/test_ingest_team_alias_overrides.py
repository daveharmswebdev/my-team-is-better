"""Coverage for the committed team-alias supplement (issue #417).

CFBD's `/teams` gives "UF" to Findlay (id 2224, D-II, never rated) and gives
Florida (id 57) only `["FLA", "Florida"]`, so "UF" never reached Florida.
`data/raw/team_alias_overrides.json` adds aliases by CFBD team id, and
`enrich_team_aliases` merges them after CFBD's own, deduped
case-insensitively, so CFBD's ordering is untouched.

Every test reads real data: the committed overrides file, the committed
`data/raw/teams.json` `/teams` payload, and the committed 2019 `/games`
cache. Nothing makes a live call.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from cfb_strength.config import PROJECT_ROOT, SEASON_TYPES
from cfb_strength.contracts import TeamRow
from cfb_strength.db.connection import ensure_schema, get_conn
from cfb_strength.evidence.proof import resolve_team
from cfb_strength.ingest.ingest_season import enrich_team_aliases, ingest_one
from cfb_strength.ingest.normalize import team_rows_by_cfbd_id
from cfb_strength.ingest.team_alias_overrides import (
    TEAM_ALIAS_OVERRIDES_PATH,
    TeamAliasOverrideError,
    apply_team_alias_overrides,
    load_team_alias_overrides,
)
from cfb_strength.ratings.compute_ratings import compute_and_store

COMMITTED_RAW_DIR = PROJECT_ROOT / "data" / "raw"
FLORIDA = 57
FINDLAY = 2224


def _committed_teams() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = json.loads((COMMITTED_RAW_DIR / "teams.json").read_text())
    return records


@pytest.fixture
def cfbd_by_id() -> dict[int, TeamRow]:
    return team_rows_by_cfbd_id(_committed_teams())


def _write_overrides(tmp_path: Path, document: object) -> Path:
    path = tmp_path / "team_alias_overrides.json"
    path.write_text(json.dumps(document))
    return path


# --- the committed file -------------------------------------------------------


def test_committed_file_is_exactly_florida_uf() -> None:
    """One entry, on purpose: any further entry needs its own evidence (#417)."""
    assert TEAM_ALIAS_OVERRIDES_PATH == COMMITTED_RAW_DIR / "team_alias_overrides.json"
    assert load_team_alias_overrides() == {FLORIDA: ("UF",)}


def test_committed_payload_is_the_premise(cfbd_by_id: dict[int, TeamRow]) -> None:
    """Why the entry exists: CFBD gives "UF" to Findlay alone."""
    assert cfbd_by_id[FLORIDA].school == "Florida"
    assert cfbd_by_id[FLORIDA].alternate_names == ("FLA", "Florida")
    assert cfbd_by_id[FINDLAY].school == "Findlay"
    assert "UF" in cfbd_by_id[FINDLAY].alternate_names


# --- the merge ----------------------------------------------------------------


def test_florida_gets_uf_after_cfbds_own_aliases(cfbd_by_id: dict[int, TeamRow]) -> None:
    merged = apply_team_alias_overrides(cfbd_by_id, load_team_alias_overrides())
    assert merged[FLORIDA].alternate_names == ("FLA", "Florida", "UF")
    # Only alternate_names changes.
    assert merged[FLORIDA].school == "Florida"
    assert merged[FLORIDA].mascot == cfbd_by_id[FLORIDA].mascot


def test_every_id_absent_from_the_overrides_is_unchanged(
    cfbd_by_id: dict[int, TeamRow],
) -> None:
    merged = apply_team_alias_overrides(cfbd_by_id, load_team_alias_overrides())
    assert merged.keys() == cfbd_by_id.keys()
    changed = [tid for tid in cfbd_by_id if merged[tid] != cfbd_by_id[tid]]
    assert changed == [FLORIDA]
    # Findlay keeps its own "UF": the supplement adds, never removes.
    assert merged[FINDLAY] == cfbd_by_id[FINDLAY]


def test_merge_dedupes_case_insensitively_keeping_cfbds_spelling(
    cfbd_by_id: dict[int, TeamRow],
) -> None:
    merged = apply_team_alias_overrides(cfbd_by_id, {FLORIDA: ("fla", " FLORIDA ", "UF", "uf")})
    assert merged[FLORIDA].alternate_names == ("FLA", "Florida", "UF")


def test_merge_does_not_mutate_its_input(cfbd_by_id: dict[int, TeamRow]) -> None:
    before = dict(cfbd_by_id)
    apply_team_alias_overrides(cfbd_by_id, {FLORIDA: ("UF",)})
    assert cfbd_by_id == before


def test_an_override_for_an_id_the_payload_lacks_writes_nothing(
    cfbd_by_id: dict[int, TeamRow],
) -> None:
    """There is no TeamRow to merge onto, and enrichment only UPDATEs teams
    the `/games` ingest found, so the entry is dropped (and logged)."""
    missing_id = max(cfbd_by_id) + 1
    merged = apply_team_alias_overrides(cfbd_by_id, {missing_id: ("ZZ",)})
    assert merged == cfbd_by_id


# --- malformed files fail loudly, naming the file -----------------------------


@pytest.mark.parametrize(
    ("document", "complaint"),
    [
        ({"57": "UF"}, "list"),
        ({"57": ["UF", 7]}, "string"),
        ({"57": ["UF", "  "]}, "string"),
        ({"57": []}, "empty"),
        ({"Florida": ["UF"]}, "CFBD team id"),
        ({"-57": ["UF"]}, "CFBD team id"),
        ({"$note": "why"}, "$note"),
        ({"$comment": 1, "57": ["UF"]}, "$comment"),
        ([["57", "UF"]], "object"),
        ({"57": ["UF"], "057": ["UF"]}, "duplicate"),
    ],
)
def test_a_malformed_overrides_file_raises_naming_the_file(
    tmp_path: Path, document: object, complaint: str
) -> None:
    path = _write_overrides(tmp_path, document)
    with pytest.raises(TeamAliasOverrideError) as excinfo:
        load_team_alias_overrides(path)
    assert str(path) in str(excinfo.value)
    assert complaint in str(excinfo.value)


def test_a_file_that_is_not_json_raises_naming_the_file(tmp_path: Path) -> None:
    path = tmp_path / "team_alias_overrides.json"
    path.write_text('{"57": ["UF"],')
    with pytest.raises(TeamAliasOverrideError, match="team_alias_overrides.json"):
        load_team_alias_overrides(path)


def test_enrichment_raises_on_a_malformed_file_instead_of_skipping_it(tmp_path: Path) -> None:
    conn = get_conn(tmp_path / "db.sqlite3")
    try:
        ensure_schema(conn)
        bad = _write_overrides(tmp_path, {"57": "UF"})
        with pytest.raises(TeamAliasOverrideError, match=str(bad)):
            enrich_team_aliases(conn, raw_dir=COMMITTED_RAW_DIR, alias_overrides_path=bad)
    finally:
        conn.close()


# --- end to end: real ingest path into a db, then the engine's lookup ---------


@pytest.fixture
def ingested_2019(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    """2019 through `ingest_one` from the committed cache, then the once-per-
    run alias enrichment with the committed overrides, then keener ratings."""
    conn = get_conn(tmp_path / "cfb.sqlite3")
    try:
        ensure_schema(conn)
        for season_type in SEASON_TYPES:
            assert ingest_one(conn, 2019, season_type).fetched_live is False
        assert enrich_team_aliases(conn, raw_dir=COMMITTED_RAW_DIR).fetched_live is False
        compute_and_store(conn, 2019, "keener")
        yield conn
    finally:
        conn.close()


def test_ingest_stores_uf_in_floridas_alternate_names(ingested_2019: sqlite3.Connection) -> None:
    row = ingested_2019.execute(
        "SELECT school, alternate_names FROM teams WHERE id = ? AND sport = 'cfb'", (FLORIDA,)
    ).fetchone()
    assert row["school"] == "Florida"
    assert json.loads(row["alternate_names"]) == ["FLA", "Florida", "UF"]


@pytest.mark.parametrize("query", ["UF", "uf", " UF "])
def test_uf_resolves_to_florida_through_the_engines_lookup(
    ingested_2019: sqlite3.Connection, query: str
) -> None:
    assert resolve_team(ingested_2019, 2019, query, method="keener") == FLORIDA


def test_florida_and_fla_still_resolve_to_florida(ingested_2019: sqlite3.Connection) -> None:
    for query in ("Florida", "FLA"):
        assert resolve_team(ingested_2019, 2019, query, method="keener") == FLORIDA
