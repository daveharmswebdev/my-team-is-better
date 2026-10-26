"""A throwaway Postgres schema for the tests that run production's real SQL
(issue #210).

Those tests run only when `TEST_DATABASE_URL` names a disposable database
(CI's `postgres` service, or a local container). They never read
`DATABASE_URL`: locally that points at production.

`scratch_schema_dsn` creates a randomly named schema in that database and
yields a DSN whose libpq `options` set `search_path` to it, so every
connection the code under test opens -- `PostgresNarrationCache` connects
per call, `api.admin` once per command -- sees only that schema's
`persona_cache`. The schema is dropped afterwards. Nothing here assumes the
database is empty, and nothing touches any other database.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

TEST_DATABASE_URL_VAR = "TEST_DATABASE_URL"


def configured_test_database_url() -> str | None:
    """The disposable database's DSN, or None when the tests should skip."""
    return os.environ.get(TEST_DATABASE_URL_VAR) or None


requires_test_database = pytest.mark.skipif(
    configured_test_database_url() is None,
    reason=(
        f"{TEST_DATABASE_URL_VAR} is not set: these tests run production's Postgres SQL "
        "against a disposable database and never use DATABASE_URL"
    ),
)


@contextmanager
def scratch_schema_dsn() -> Iterator[tuple[str, str]]:
    """Yield `(dsn, schema)`: a fresh schema in `TEST_DATABASE_URL`, and a
    DSN whose connections resolve unqualified names in it. Dropped on exit."""
    base = configured_test_database_url()
    if base is None:  # pragma: no cover - callers are skipped first
        raise RuntimeError(f"{TEST_DATABASE_URL_VAR} is not set")
    schema = f"t210_{uuid.uuid4().hex[:16]}"
    with psycopg.connect(base) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        admin.commit()
    try:
        yield make_conninfo(base, options=f"-c search_path={schema}"), schema
    finally:
        with psycopg.connect(base) as admin:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
            admin.commit()
