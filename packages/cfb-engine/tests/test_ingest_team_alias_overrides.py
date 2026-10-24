"""Coverage for the committed team-alias supplement (issue #417).

CFBD's `/teams` gives "UF" to Findlay (id 2224, D-II, in our `teams` table
from 2021 on) and gives Florida (id 57) only `["FLA", "Florida"]`, so "UF"
never reached Florida. `data/raw/team_alias_overrides.json` adds and removes
aliases by CFBD team id: Florida gains "UF", Findlay loses it.
`enrich_team_aliases` applies both on the id join, keeping CFBD's ordering.

Every test reads real data: the committed overrides file, the committed
`data/raw/teams.json` `/teams` payload, and the committed `/games` caches
(2019 for the golden-year path, 2021-2025 for the years Findlay plays in).
Nothing makes a live call.
"""

from __future__ import annotations

import dataclasses
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
    AliasOverride,
    TeamAliasOverrideError,
    apply_team_alias_overrides,
    load_team_alias_overrides,
)
from cfb_strength.ratings.compute_ratings import compute_and_store

COMMITTED_RAW_DIR = PROJECT_ROOT / "data" / "raw"
FLORIDA = 57
FINDLAY = 2224
FINDLAY_YEARS = (2021, 2022, 2023, 2024, 2025)
SOURCE = Path("team_alias_overrides.json")


def _committed_teams() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = json.loads((COMMITTED_RAW_DIR / "teams.json").read_text())
    return records


def _override(
    team_id: int, add: tuple[str, ...] = (), remove: tuple[str, ...] = ()
) -> dict[int, AliasOverride]:
    return {team_id: AliasOverride(team_id=team_id, add=add, remove=remove, source=SOURCE)}


@pytest.fixture
def cfbd_by_id() -> dict[int, TeamRow]:
    return team_rows_by_cfbd_id(_committed_teams())


def _write_overrides(tmp_path: Path, document: object) -> Path:
    path = tmp_path / "team_alias_overrides.json"
    path.write_text(json.dumps(document))
    return path


def _uf_owners(conn: sqlite3.Connection) -> list[int]:
    owners = []
    for row in conn.execute("SELECT id, alternate_names FROM teams WHERE sport = 'cfb'"):
        names = json.loads(row["alternate_names"]) if row["alternate_names"] else []
        if any(name.strip().casefold() == "uf" for name in names):
            owners.append(row["id"])
    return owners


# --- the committed file -------------------------------------------------------


def test_committed_file_is_exactly_florida_plus_uf_and_findlay_minus_uf() -> None:
    """Two entries, on purpose: any further one needs its own evidence (#417)."""
    assert TEAM_ALIAS_OVERRIDES_PATH == COMMITTED_RAW_DIR / "team_alias_overrides.json"
    overrides = load_team_alias_overrides()
    assert {tid: (o.add, o.remove) for tid, o in overrides.items()} == {
        FLORIDA: (("UF",), ()),
        FINDLAY: ((), ("UF",)),
    }
    assert all(o.source == TEAM_ALIAS_OVERRIDES_PATH for o in overrides.values())


def test_committed_payload_is_the_premise(cfbd_by_id: dict[int, TeamRow]) -> None:
    """Why the entries exist: CFBD gives "UF" to Findlay alone."""
    assert cfbd_by_id[FLORIDA].school == "Florida"
    assert cfbd_by_id[FLORIDA].alternate_names == ("FLA", "Florida")
    assert cfbd_by_id[FINDLAY].school == "Findlay"
    assert cfbd_by_id[FINDLAY].alternate_names == ("UF", "Findlay")
    owners = [tid for tid, row in cfbd_by_id.items() if "UF" in row.alternate_names]
    assert owners == [FINDLAY]


# --- the merge ----------------------------------------------------------------


def test_florida_gets_uf_after_cfbds_own_aliases(cfbd_by_id: dict[int, TeamRow]) -> None:
    merged = apply_team_alias_overrides(cfbd_by_id, load_team_alias_overrides())
    assert merged[FLORIDA].alternate_names == ("FLA", "Florida", "UF")
    # Only alternate_names changes.
    assert merged[FLORIDA].school == "Florida"
    assert merged[FLORIDA].mascot == cfbd_by_id[FLORIDA].mascot


def test_findlay_loses_uf_and_keeps_findlay(cfbd_by_id: dict[int, TeamRow]) -> None:
    merged = apply_team_alias_overrides(cfbd_by_id, load_team_alias_overrides())
    assert merged[FINDLAY].alternate_names == ("Findlay",)
    assert merged[FINDLAY].school == "Findlay"
    assert merged[FINDLAY].mascot == cfbd_by_id[FINDLAY].mascot


def test_after_the_committed_overrides_only_florida_carries_uf(
    cfbd_by_id: dict[int, TeamRow],
) -> None:
    merged = apply_team_alias_overrides(cfbd_by_id, load_team_alias_overrides())
    owners = [
        tid for tid, row in merged.items() if any(n.casefold() == "uf" for n in row.alternate_names)
    ]
    assert owners == [FLORIDA]


def test_every_id_absent_from_the_overrides_is_unchanged(
    cfbd_by_id: dict[int, TeamRow],
) -> None:
    merged = apply_team_alias_overrides(cfbd_by_id, load_team_alias_overrides())
    assert merged.keys() == cfbd_by_id.keys()
    changed = sorted(tid for tid in cfbd_by_id if merged[tid] != cfbd_by_id[tid])
    assert changed == [FLORIDA, FINDLAY]


def test_merge_dedupes_case_insensitively_keeping_cfbds_spelling(
    cfbd_by_id: dict[int, TeamRow],
) -> None:
    merged = apply_team_alias_overrides(
        cfbd_by_id, _override(FLORIDA, add=("fla", " FLORIDA ", "UF", "uf"))
    )
    assert merged[FLORIDA].alternate_names == ("FLA", "Florida", "UF")


def test_removal_matches_case_insensitively(cfbd_by_id: dict[int, TeamRow]) -> None:
    merged = apply_team_alias_overrides(cfbd_by_id, _override(FINDLAY, remove=(" uf ",)))
    assert merged[FINDLAY].alternate_names == ("Findlay",)


def test_merge_does_not_mutate_its_input(cfbd_by_id: dict[int, TeamRow]) -> None:
    before = dict(cfbd_by_id)
    apply_team_alias_overrides(cfbd_by_id, load_team_alias_overrides())
    assert cfbd_by_id == before


def test_an_override_for_an_id_the_payload_lacks_writes_nothing(
    cfbd_by_id: dict[int, TeamRow],
) -> None:
    """There is no TeamRow to merge onto, and enrichment only UPDATEs teams
    the `/games` ingest found, so the entry is dropped (and logged)."""
    missing_id = max(cfbd_by_id) + 1
    merged = apply_team_alias_overrides(cfbd_by_id, _override(missing_id, add=("ZZ",)))
    assert merged == cfbd_by_id
    merged = apply_team_alias_overrides(cfbd_by_id, _override(missing_id, remove=("ZZ",)))
    assert merged == cfbd_by_id


def test_removing_an_alias_cfbd_doesnt_carry_raises_naming_file_and_id(
    cfbd_by_id: dict[int, TeamRow],
) -> None:
    """So a removal can't sit in the file doing nothing once CFBD changes."""
    with pytest.raises(TeamAliasOverrideError) as excinfo:
        apply_team_alias_overrides(cfbd_by_id, _override(FLORIDA, remove=("UF",)))
    message = str(excinfo.value)
    assert str(SOURCE) in message
    assert str(FLORIDA) in message
    assert "'UF'" in message


def test_committed_findlay_removal_goes_stale_loudly_if_cfbd_drops_uf(
    cfbd_by_id: dict[int, TeamRow],
) -> None:
    stale = dict(cfbd_by_id)
    stale[FINDLAY] = dataclasses.replace(stale[FINDLAY], alternate_names=("Findlay",))
    with pytest.raises(TeamAliasOverrideError, match=str(TEAM_ALIAS_OVERRIDES_PATH)):
        apply_team_alias_overrides(stale, load_team_alias_overrides())


# --- the loader: shapes accepted, malformed files fail loudly ------------------


def test_plain_list_and_add_remove_object_both_load(tmp_path: Path) -> None:
    path = _write_overrides(
        tmp_path,
        {
            "$comment": "why",
            "57": ["UF"],
            "58": {"add": ["A1"]},
            "59": {"remove": ["R1"]},
            "60": {"add": ["A2"], "remove": ["R2"]},
        },
    )
    loaded = load_team_alias_overrides(path)
    assert {tid: (o.add, o.remove) for tid, o in loaded.items()} == {
        57: (("UF",), ()),
        58: (("A1",), ()),
        59: ((), ("R1",)),
        60: (("A2",), ("R2",)),
    }
    assert all(o.source == path for o in loaded.values())


@pytest.mark.parametrize(
    ("document", "complaint"),
    [
        ({"57": "UF"}, "list"),
        ({"57": ["UF", 7]}, "string"),
        ({"57": ["UF", "  "]}, "string"),
        ({"57": []}, "empty"),
        ({"57": {}}, "empty"),
        ({"57": {"add": [], "remove": []}}, "empty"),
        ({"57": {"add": "UF"}}, "list"),
        ({"57": {"remove": [3]}}, "string"),
        ({"57": {"add": ["UF"], "rename": ["X"]}}, "rename"),
        ({"57": {"add": ["UF"], "remove": ["uf"]}}, "both"),
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


def test_adding_and_removing_the_same_alias_names_the_id(tmp_path: Path) -> None:
    path = _write_overrides(tmp_path, {"2224": {"add": ["UF"], "remove": ["UF"]}})
    with pytest.raises(TeamAliasOverrideError, match="2224"):
        load_team_alias_overrides(path)


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


@pytest.fixture(scope="module")
def ingested_findlay_years(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[sqlite3.Connection]:
    """2021-2025, every season Findlay plays in the committed cache, through
    the real path with the committed overrides."""
    conn = get_conn(tmp_path_factory.mktemp("findlay") / "cfb.sqlite3")
    try:
        ensure_schema(conn)
        for year in FINDLAY_YEARS:
            for season_type in SEASON_TYPES:
                assert ingest_one(conn, year, season_type).fetched_live is False
        assert enrich_team_aliases(conn, raw_dir=COMMITTED_RAW_DIR).fetched_live is False
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


def test_findlay_is_really_in_the_2021_to_2025_db(
    ingested_findlay_years: sqlite3.Connection,
) -> None:
    seasons = [
        r[0]
        for r in ingested_findlay_years.execute(
            "SELECT year FROM team_season WHERE team_id = ? ORDER BY year", (FINDLAY,)
        )
    ]
    assert seasons == list(FINDLAY_YEARS)


def test_in_findlays_years_only_florida_carries_uf_and_findlay_keeps_findlay(
    ingested_findlay_years: sqlite3.Connection,
) -> None:
    assert _uf_owners(ingested_findlay_years) == [FLORIDA]
    row = ingested_findlay_years.execute(
        "SELECT school, alternate_names FROM teams WHERE id = ?", (FINDLAY,)
    ).fetchone()
    assert row["school"] == "Findlay"
    assert json.loads(row["alternate_names"]) == ["Findlay"]
