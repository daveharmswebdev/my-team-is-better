"""Issue #163: `get_conn(read_only=True)` must open exactly the file it was
given, read-only, whatever characters the path contains.

Before the fix the URI was built as ``f"file:{db_path}?mode=ro"`` with no
escaping, so SQLite parsed a ``?`` or ``#`` in the path as the start of the
query string or fragment: ``mode=ro`` was lost, and a *truncated* path was
opened read-write and created on disk. A ``%HH`` sequence was
percent-decoded, so the open failed on a path that exists.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from cfb_strength.db.connection import get_conn

AWKWARD_DIRS = ["q?mark", "hash#tag", "pct%41", "with space", "amp&ersand"]


def _seed(db: Path) -> None:
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE marker (v TEXT)")
    conn.execute("INSERT INTO marker VALUES ('seeded')")
    conn.commit()
    conn.close()


@pytest.mark.parametrize("dirname", AWKWARD_DIRS)
def test_read_only_open_reads_the_real_file_under_an_awkward_directory(
    tmp_path: Path, dirname: str
) -> None:
    db = tmp_path / dirname / "x.sqlite3"
    db.parent.mkdir()
    _seed(db)

    conn = get_conn(db, read_only=True)
    try:
        assert conn.execute("SELECT v FROM marker").fetchone()[0] == "seeded"
    finally:
        conn.close()


@pytest.mark.parametrize("dirname", AWKWARD_DIRS)
def test_read_only_open_is_really_read_only_under_an_awkward_directory(
    tmp_path: Path, dirname: str
) -> None:
    db = tmp_path / dirname / "x.sqlite3"
    db.parent.mkdir()
    _seed(db)

    conn = get_conn(db, read_only=True)
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("INSERT INTO marker VALUES ('written')")
    finally:
        conn.close()


@pytest.mark.parametrize("dirname", AWKWARD_DIRS)
def test_read_only_open_creates_nothing_outside_the_given_path(
    tmp_path: Path, dirname: str
) -> None:
    db = tmp_path / dirname / "x.sqlite3"
    db.parent.mkdir()
    _seed(db)
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))

    get_conn(db, read_only=True).close()

    after = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    assert after == before


@pytest.mark.parametrize("dirname", AWKWARD_DIRS)
def test_immutable_open_reads_the_real_file_under_an_awkward_directory(
    tmp_path: Path, dirname: str
) -> None:
    db = tmp_path / dirname / "x.sqlite3"
    db.parent.mkdir()
    _seed(db)

    conn = get_conn(db, read_only=True, immutable=True)
    try:
        assert conn.execute("SELECT v FROM marker").fetchone()[0] == "seeded"
    finally:
        conn.close()
