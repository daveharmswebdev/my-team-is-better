"""The committed regression fixtures hold exactly what a regeneration from the
committed raw cache holds (issue #110, round 2).

`tests/test_regression_fixtures_currency.py` runs `cfb doctor`'s check, which
compares only the schema and which (season, season_type) batches exist. It
never looks at game content or counts. So a fixture that lost one game, kept
a score the cache has since corrected, or carries an edited `ingestion_log`
row or mascot passes it. This test catches all of those: it runs the
generator's own `build` into `tmp_path` against the committed `data/raw/`,
with live fetches disabled exactly as the generator's CLI disables them, and
compares the logical content of every table and schema object with the
committed file.

What this compares:

* every row of every table (`games`, `teams`, `team_season`, `ingestion_log`,
  and `ratings` / `rating_breakdowns`, which must be empty in both), keyed by
  primary key, with every column's value;
* each table's column list, and every table and index's name and SQL in
  `sqlite_master`.

It never compares bytes. The SQLite header records the writing library's
version, and page layout can differ between SQLite builds, so byte equality
would fail on a correct fixture regenerated elsewhere. Logical equality is
the property the golden tests rely on.

On failure it names each table that differs and its first few differing
keys. The fix is almost always to regenerate:

    cd packages/cfb-engine && uv run python tests/fixtures/build_regression_fixtures.py

and to review the diff that produces. If the committed cache changed on
purpose, the regenerated fixture is the new truth and the golden tests say
whether it moved an answer.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from cfb_strength.db.connection import get_conn
from tests.fixtures import build_regression_fixtures as generator

FIRST_N_KEYS = 5

Key = tuple[object, ...]


@dataclass(frozen=True)
class Table:
    columns: tuple[str, ...]
    key_columns: tuple[str, ...]
    rows: dict[Key, tuple[object, ...]]


def _read_tables(db: Path) -> dict[str, Table]:
    # Read-only and immutable: the committed file is never written, and it
    # is not in WAL mode, so there is no -wal to miss.
    conn = get_conn(db, read_only=True, immutable=True)
    try:
        tables: dict[str, Table] = {}
        schema = conn.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ).fetchall()
        tables["sqlite_master"] = Table(
            columns=("type", "name", "tbl_name", "sql"),
            key_columns=("type", "name"),
            rows={(row[0], row[1]): tuple(row) for row in schema},
        )
        for row in schema:
            if row[0] != "table":
                continue
            name = str(row[1])
            info = conn.execute(f'PRAGMA table_info("{name}")').fetchall()
            columns = tuple(str(col[1]) for col in info)
            pk = tuple(str(col[1]) for col in sorted(info, key=lambda c: c[5]) if col[5] > 0)
            key_columns = pk or ("rowid",)
            key_positions = [columns.index(c) for c in pk]
            select = "SELECT rowid, * FROM" if not pk else "SELECT * FROM"
            rows: dict[Key, tuple[object, ...]] = {}
            for values in conn.execute(f'{select} "{name}"'):
                if pk:
                    rows[tuple(values[i] for i in key_positions)] = tuple(values)
                else:
                    rows[(values[0],)] = tuple(values[1:])
            tables[name] = Table(columns=columns, key_columns=key_columns, rows=rows)
        return tables
    finally:
        conn.close()


def _first(keys: Iterator[Key] | list[Key]) -> str:
    ordered = sorted(keys, key=repr)
    shown = ", ".join(repr(k[0] if len(k) == 1 else k) for k in ordered[:FIRST_N_KEYS])
    more = f" (+{len(ordered) - FIRST_N_KEYS} more)" if len(ordered) > FIRST_N_KEYS else ""
    return shown + more


def _differences(committed: dict[str, Table], regenerated: dict[str, Table]) -> list[str]:
    problems: list[str] = []
    for name in sorted(set(committed) | set(regenerated)):
        if name not in regenerated:
            problems.append(f"{name}: only in the committed fixture")
            continue
        if name not in committed:
            problems.append(f"{name}: missing from the committed fixture")
            continue
        old, new = committed[name], regenerated[name]
        if old.columns != new.columns:
            problems.append(f"{name}: columns differ: committed {old.columns} vs regenerated {new.columns}")
            continue
        key = "/".join(new.key_columns)
        only_old = [k for k in old.rows if k not in new.rows]
        only_new = [k for k in new.rows if k not in old.rows]
        changed = [k for k in old.rows if k in new.rows and old.rows[k] != new.rows[k]]
        if only_old:
            problems.append(
                f"{name}: {len(only_old)} row(s) only in the committed fixture, by {key}: {_first(only_old)}"
            )
        if only_new:
            problems.append(
                f"{name}: {len(only_new)} row(s) missing from the committed fixture, by {key}: "
                f"{_first(only_new)}"
            )
        if changed:
            columns = sorted(
                {
                    new.columns[i]
                    for k in changed
                    for i, (a, b) in enumerate(zip(old.rows[k], new.rows[k], strict=True))
                    if a != b
                }
            )
            problems.append(
                f"{name}: {len(changed)} row(s) differ, by {key}: {_first(changed)}; "
                f"differing columns: {', '.join(columns)}"
            )
    return problems


@pytest.fixture(scope="module")
def regenerated_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out_dir = tmp_path_factory.mktemp("regenerated_fixtures")
    with generator.live_fetches_disabled():
        for spec in generator.FIXTURES.values():
            generator.build(spec, out_dir)
    return out_dir


def test_every_committed_fixture_is_regenerated() -> None:
    assert sorted(generator.FIXTURES) == ["cfb", "nfl"]
    for spec in generator.FIXTURES.values():
        assert (generator.FIXTURES_DIR / spec.filename).is_file(), spec.filename


@pytest.mark.parametrize("league", sorted(generator.FIXTURES))
def test_committed_fixture_matches_a_regeneration_from_the_committed_cache(
    regenerated_dir: Path, league: str
) -> None:
    spec = generator.FIXTURES[league]
    committed = generator.FIXTURES_DIR / spec.filename
    problems = _differences(_read_tables(committed), _read_tables(regenerated_dir / spec.filename))
    if problems:
        pytest.fail(
            f"tests/fixtures/{spec.filename} is not what the generator builds from the committed "
            "cache. Regenerate it (cd packages/cfb-engine && uv run python "
            "tests/fixtures/build_regression_fixtures.py) and review the change.\n  "
            + "\n  ".join(problems),
            pytrace=False,
        )


def test_the_comparison_reports_a_changed_row_a_missing_row_and_a_column(tmp_path: Path) -> None:
    """The differ itself must see each kind of difference, or a green parity
    run means nothing."""

    def make(path: Path, rows: list[tuple[int, str, int]], extra_column: bool = False) -> None:
        conn = sqlite3.connect(path)
        cols = "id INTEGER PRIMARY KEY, school TEXT, points INTEGER" + (", mascot TEXT" if extra_column else "")
        conn.execute(f"CREATE TABLE games ({cols})")
        conn.executemany("INSERT INTO games (id, school, points) VALUES (?, ?, ?)", rows)
        conn.commit()
        conn.close()

    base = [(1, "LSU", 42), (2, "Clemson", 25), (3, "Ohio State", 29)]
    make(tmp_path / "a.sqlite3", base)
    make(tmp_path / "b.sqlite3", [(1, "LSU", 25), (2, "Clemson", 25)])
    make(tmp_path / "c.sqlite3", base, extra_column=True)

    a = _read_tables(tmp_path / "a.sqlite3")
    assert _differences(a, _read_tables(tmp_path / "a.sqlite3")) == []

    changed = _differences(a, _read_tables(tmp_path / "b.sqlite3"))
    assert "games: 1 row(s) only in the committed fixture, by id: 3" in changed
    assert "games: 1 row(s) differ, by id: 1; differing columns: points" in changed

    column = _differences(a, _read_tables(tmp_path / "c.sqlite3"))
    assert any(p.startswith("games: columns differ") for p in column), column
    assert any(p.startswith("sqlite_master: 1 row(s) differ") for p in column), column
