"""Issue #341: a `PlayerStats` widening announces its blast radius.

Many player tests assert over the *whole* stat field set (a loop over
`fields(PlayerStats)`, or `row.stats == PlayerStats()`), so a new column is
covered without anyone naming it. That is the right pattern, but it also
means a widening silently changes what those tests assert: on #313 two of
them quietly became characterizations of a MAX-vs-SUM bug (#334), and a
search for the new column names could not find the second one.

So every column's rules are pinned here, by name: its DDL type on both stat
tables and how a season (and a career) combines its game rows. A widening
fails this file once, listing the columns whose rules need stating, and the
failure message lists every contract-derived assertion site to re-check,
found by scanning for both shapes rather than remembered.
"""

from __future__ import annotations

import dataclasses
import re
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from cfb_strength.contracts import PLAYER_STAT_MAX_FIELDS, PlayerStats
from cfb_strength.db.connection import ensure_schema, get_conn

STAT_TABLES = ("player_game_stats", "player_season_stats")

# column -> (DDL type, season aggregation). Edit this only after re-checking
# the sites the failure message lists.
PINNED_RULES: dict[str, tuple[str, str]] = {
    "completions": ("INTEGER", "sum"),
    "attempts": ("INTEGER", "sum"),
    "passing_yards": ("INTEGER", "sum"),
    "passing_tds": ("INTEGER", "sum"),
    "passing_interceptions": ("INTEGER", "sum"),
    "sacks_suffered": ("INTEGER", "sum"),
    "sack_yards_lost": ("INTEGER", "sum"),
    "carries": ("INTEGER", "sum"),
    "rushing_yards": ("INTEGER", "sum"),
    "rushing_tds": ("INTEGER", "sum"),
    "rushing_first_downs": ("INTEGER", "sum"),
    "rushing_fumbles_lost": ("INTEGER", "sum"),
    "receptions": ("INTEGER", "sum"),
    "targets": ("INTEGER", "sum"),
    "receiving_yards": ("INTEGER", "sum"),
    "receiving_tds": ("INTEGER", "sum"),
    "receiving_first_downs": ("INTEGER", "sum"),
    "receiving_fumbles_lost": ("INTEGER", "sum"),
    "fg_made": ("INTEGER", "sum"),
    "fg_att": ("INTEGER", "sum"),
    "fg_long": ("INTEGER", "max"),
    "fg_made_0_19": ("INTEGER", "sum"),
    "fg_made_20_29": ("INTEGER", "sum"),
    "fg_made_30_39": ("INTEGER", "sum"),
    "fg_made_40_49": ("INTEGER", "sum"),
    "fg_made_50_59": ("INTEGER", "sum"),
    "fg_made_60_": ("INTEGER", "sum"),
    "pat_made": ("INTEGER", "sum"),
    "pat_att": ("INTEGER", "sum"),
    "pt_att": ("INTEGER", "sum"),
    "pt_yards": ("INTEGER", "sum"),
    "pt_net_yards": ("INTEGER", "sum"),
    "pt_long": ("INTEGER", "max"),
    "pt_inside_20": ("INTEGER", "sum"),
    "def_interceptions": ("INTEGER", "sum"),
    "def_sacks": ("REAL", "sum"),
    "def_fumbles_forced": ("INTEGER", "sum"),
    "def_tackles_solo": ("INTEGER", "sum"),
    "def_pass_defended": ("INTEGER", "sum"),
    "passing_epa": ("REAL", "sum"),
    "rushing_epa": ("REAL", "sum"),
    "receiving_epa": ("REAL", "sum"),
}

# The Python annotation each DDL type pairs with.
PYTHON_TYPE_FOR_DDL = {"INTEGER": "int | None", "REAL": "float | None"}

# Assertions that range over the whole field set, directly or through a
# name derived from it. A column-name grep cannot find these (#341).
CONTRACT_DERIVED_SHAPES = re.compile(
    r"fields\(PlayerStats\)"
    r"|PlayerStats\.__dataclass_fields__"
    r"|== PlayerStats\(\)"
    r"|\bmodel_fields\b"
    r"|\b(?:STAT_COLUMNS|STAT_NAMES|PUBLISHED_STAT_NAMES|STAT_FIELDS)\b"
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SCANNED_TEST_DIRS = (
    REPO_ROOT / "packages" / "cfb-engine" / "tests",
    REPO_ROOT / "apps" / "api" / "tests",
)


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    c = get_conn(tmp_path / "rules.sqlite3")
    ensure_schema(c)
    try:
        yield c
    finally:
        c.close()


def contract_derived_sites() -> list[str]:
    """Every `file:line` in the engine and api test suites whose assertion
    ranges over the whole `PlayerStats` field set."""
    this_file = Path(__file__).resolve()
    sites = []
    for root in SCANNED_TEST_DIRS:
        for path in sorted(root.rglob("*.py")):
            if path.resolve() == this_file:
                continue
            for number, line in enumerate(path.read_text().splitlines(), start=1):
                if CONTRACT_DERIVED_SHAPES.search(line):
                    sites.append(f"{path.relative_to(REPO_ROOT)}:{number}")
    return sites


def actual_rules(conn: sqlite3.Connection) -> dict[str, tuple[str, str]]:
    ddl = {
        table: {row["name"]: row["type"] for row in conn.execute(f"PRAGMA table_info({table})")}
        for table in STAT_TABLES
    }
    rules = {}
    for f in dataclasses.fields(PlayerStats):
        game_type, season_type = (ddl[table].get(f.name, "missing") for table in STAT_TABLES)
        ddl_type = game_type if game_type == season_type else f"{game_type}/{season_type}"
        aggregation = "max" if f.name in PLAYER_STAT_MAX_FIELDS else "sum"
        rules[f.name] = (ddl_type, aggregation)
    return rules


def drift_report(pinned: dict[str, tuple[str, str]], actual: dict[str, tuple[str, str]]) -> str:
    new = [f"{name} {actual[name]}" for name in actual if name not in pinned]
    removed = [name for name in pinned if name not in actual]
    changed = [
        f"{name} {pinned[name]} -> {actual[name]}"
        for name in actual
        if name in pinned and pinned[name] != actual[name]
    ]
    sites = contract_derived_sites()
    return "\n".join(
        [
            "PlayerStats' column rules changed (#341). State each column's rules in",
            "PINNED_RULES, then re-check what these whole-field-set assertions now assert:",
            f"  new: {new or 'none'}",
            f"  removed: {removed or 'none'}",
            f"  changed: {changed or 'none'}",
            f"  contract-derived assertion sites ({len(sites)}):",
            *(f"    {site}" for site in sites),
        ]
    )


def test_every_stat_column_has_pinned_rules(conn: sqlite3.Connection) -> None:
    actual = actual_rules(conn)
    assert actual == PINNED_RULES, drift_report(PINNED_RULES, actual)


def test_each_column_python_type_matches_its_ddl_type(conn: sqlite3.Connection) -> None:
    """A REAL column must be a float in the contract and an INTEGER one an
    int: the ingest parses by the annotation, and a mismatch would either
    reject a fractional value or store one in an INTEGER column."""
    rules = actual_rules(conn)
    mismatched = {
        f.name: (str(f.type), rules[f.name][0])
        for f in dataclasses.fields(PlayerStats)
        if PYTHON_TYPE_FOR_DDL.get(rules[f.name][0]) != str(f.type)
    }
    assert not mismatched, f"annotation vs DDL type: {mismatched}"


def test_the_site_scan_finds_both_shapes() -> None:
    """The report is only useful if the scan sees both shapes that slipped
    past a column-name grep on #313/#334: the field loop and the
    whole-object comparison."""
    sites = contract_derived_sites()
    assert any("test_players_career.py" in s for s in sites)
    shapes = {
        "loop": False,
        "whole_object": False,
    }
    for site in sites:
        path, number = site.rsplit(":", 1)
        line = (REPO_ROOT / path).read_text().splitlines()[int(number) - 1]
        shapes["loop"] |= "fields(PlayerStats)" in line
        shapes["whole_object"] |= "== PlayerStats()" in line
    assert shapes == {"loop": True, "whole_object": True}


def test_the_drift_report_names_a_new_column_and_the_sites() -> None:
    actual = {**PINNED_RULES, "def_qb_hits": ("INTEGER", "sum")}
    report = drift_report(PINNED_RULES, actual)
    assert "new: [\"def_qb_hits ('INTEGER', 'sum')\"]" in report
    assert "test_players_career.py" in report
