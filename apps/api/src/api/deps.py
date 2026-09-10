"""FastAPI dependency wiring for the verdict routes.

Owns the single seam apps/api is allowed to cross per docs/ARCHITECTURE.md
§2: opening a read-only `sqlite3.Connection` via
`cfb_strength.db.connection.get_conn`, pointed at `cfb_strength.config.DB_PATH`.
No route imports `get_conn`/`DB_PATH` directly -- they depend on
`get_db_conn`, which tests override via `app.dependency_overrides` to point
at a fixture db instead (see tests/conftest.py).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

from cfb_strength.config import DB_PATH
from cfb_strength.db.connection import get_conn


def get_db_conn() -> Iterator[sqlite3.Connection]:
    conn = get_conn(DB_PATH, read_only=True)
    try:
        yield conn
    finally:
        conn.close()
