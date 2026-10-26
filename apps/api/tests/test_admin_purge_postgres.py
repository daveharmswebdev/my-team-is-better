"""`python -m api.admin purge-narrations` against a real Postgres (issue #210).

`test_admin_purge.py` drives the command through a fake connection that
re-implements its `WHERE` clause in Python; that proves the command's logic,
not that `COUNT_SQL` and `DELETE_SQL` mean the same thing to Postgres. These
run the real command (`api.admin.main` with its default psycopg connect)
against the disposable database `TEST_DATABASE_URL` names, each test in its
own throwaway schema (`tests/fixtures/postgres_scratch.py`), and check the
table afterwards. Without `TEST_DATABASE_URL` the module skips; it never
reads `DATABASE_URL`.

Rows are written through `PostgresNarrationCache.set`, production's own
write path; only their age is set by hand (`created_at` is `now()` on
write), which is test setup, not a copy of the SQL under test.
"""

from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest
from fixtures.postgres_scratch import requires_test_database, scratch_schema_dsn

from api.admin import main
from api.persona.cache import CachedNarration, PostgresNarrationCache, ensure_schema

pytestmark = requires_test_database

# (cache_key, prompt_version, age in days)
SEED: list[tuple[str, str, int]] = [
    ("team-v12-old", "persona-v12", 40),
    ("team-v12-new", "persona-v12", 1),
    ("team-v13-old", "persona-v13", 40),
    ("team-v13-new", "persona-v13", 0),
    ("qb-v3-old", "qb-persona-v3", 40),
    ("qb-v3-mid", "qb-persona-v3", 10),
    ("qb-v4-new", "qb-persona-v4", 0),
]
ALL_KEYS = {key for key, _, _ in SEED}


@pytest.fixture
def dsn() -> Iterator[str]:
    with scratch_schema_dsn() as (scratch_dsn, _):
        with psycopg.connect(scratch_dsn) as conn:
            ensure_schema(conn)
        for key, version, _ in SEED:
            PostgresNarrationCache(scratch_dsn, prompt_version=version).set(
                key, CachedNarration(text=f"Narration {key}.", contested=False)
            )
        with psycopg.connect(scratch_dsn) as conn:
            for key, _, days in SEED:
                conn.execute(
                    "UPDATE persona_cache SET created_at = now() - make_interval(days => %s)"
                    " WHERE cache_key = %s",
                    (days, key),
                )
        yield scratch_dsn


def _keys(dsn: str) -> set[str]:
    with psycopg.connect(dsn) as conn:
        return {str(row[0]) for row in conn.execute("SELECT cache_key FROM persona_cache")}


def _run(dsn: str, *args: str, answer: str = "") -> int:
    def confirm(prompt: str) -> str:
        return answer

    return main(["purge-narrations", *args], database_url=dsn, confirm=confirm)


def _out(capsys: pytest.CaptureFixture[str]) -> str:
    return capsys.readouterr().out


# ---------------------------------------------------------------------------
# --dry-run: the grouped count, nothing deleted
# ---------------------------------------------------------------------------


def test_dry_run_by_prompt_version_counts_and_deletes_nothing(
    dsn: str, capsys: pytest.CaptureFixture[str]
) -> None:
    status = _run(dsn, "--prompt-version", "persona-v12", "--dry-run")

    assert status == 0
    assert _out(capsys) == "Would delete 2 narrations:\n  persona-v12: 2\n"
    assert _keys(dsn) == ALL_KEYS


def test_dry_run_with_several_versions_and_an_age_counts_per_version(
    dsn: str, capsys: pytest.CaptureFixture[str]
) -> None:
    status = _run(
        dsn,
        "--prompt-version",
        "persona-v13",
        "--prompt-version",
        "qb-persona-v3",
        "--older-than",
        "7",
        "--dry-run",
    )

    assert status == 0
    assert _out(capsys) == ("Would delete 3 narrations:\n  persona-v13: 1\n  qb-persona-v3: 2\n")
    assert _keys(dsn) == ALL_KEYS


def test_dry_run_matching_nothing_says_so(dsn: str, capsys: pytest.CaptureFixture[str]) -> None:
    status = _run(dsn, "--prompt-version", "persona-v1", "--dry-run")

    assert status == 0
    assert _out(capsys) == "No narrations match; nothing deleted.\n"
    assert _keys(dsn) == ALL_KEYS


# ---------------------------------------------------------------------------
# The DELETE: exactly the matching rows, correct counts, idempotent
# ---------------------------------------------------------------------------


def test_purge_by_prompt_version_deletes_exactly_those_rows(
    dsn: str, capsys: pytest.CaptureFixture[str]
) -> None:
    status = _run(dsn, "--prompt-version", "qb-persona-v3")

    assert status == 0
    assert _out(capsys) == "Deleted 2 narrations:\n  qb-persona-v3: 2\n"
    assert _keys(dsn) == ALL_KEYS - {"qb-v3-old", "qb-v3-mid"}

    # Idempotent: a second run finds nothing and leaves the rest alone.
    assert _run(dsn, "--prompt-version", "qb-persona-v3") == 0
    assert _out(capsys) == "No narrations match; nothing deleted.\n"
    assert _keys(dsn) == ALL_KEYS - {"qb-v3-old", "qb-v3-mid"}


def test_purge_by_several_prompt_versions(dsn: str, capsys: pytest.CaptureFixture[str]) -> None:
    status = _run(dsn, "--prompt-version", "persona-v12", "--prompt-version", "qb-persona-v4")

    assert status == 0
    assert _out(capsys) == ("Deleted 3 narrations:\n  persona-v12: 2\n  qb-persona-v4: 1\n")
    assert _keys(dsn) == ALL_KEYS - {"team-v12-old", "team-v12-new", "qb-v4-new"}


def test_purge_older_than_deletes_only_older_rows(
    dsn: str, capsys: pytest.CaptureFixture[str]
) -> None:
    status = _run(dsn, "--older-than", "7")

    assert status == 0
    assert _out(capsys) == (
        "Deleted 4 narrations:\n  persona-v12: 1\n  persona-v13: 1\n  qb-persona-v3: 2\n"
    )
    assert _keys(dsn) == {"team-v12-new", "team-v13-new", "qb-v4-new"}

    assert _run(dsn, "--older-than", "7") == 0
    assert _out(capsys) == "No narrations match; nothing deleted.\n"
    assert _keys(dsn) == {"team-v12-new", "team-v13-new", "qb-v4-new"}


def test_purge_older_than_zero_spares_nothing_written_before_now(
    dsn: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--older-than 0` is `created_at < now()`; every seeded row was written
    in an earlier transaction, so all of them go."""
    assert _run(dsn, "--older-than", "0") == 0
    assert _out(capsys).startswith("Deleted 7 narrations:\n")
    assert _keys(dsn) == set()


def test_purge_prompt_version_and_age_must_both_hold(
    dsn: str, capsys: pytest.CaptureFixture[str]
) -> None:
    status = _run(dsn, "--prompt-version", "qb-persona-v3", "--older-than", "20")

    assert status == 0
    assert _out(capsys) == "Deleted 1 narration:\n  qb-persona-v3: 1\n"
    assert _keys(dsn) == ALL_KEYS - {"qb-v3-old"}


def test_purge_all_with_yes_deletes_every_row(dsn: str, capsys: pytest.CaptureFixture[str]) -> None:
    status = _run(dsn, "--all", "--yes")

    assert status == 0
    assert _out(capsys) == (
        "Deleted 7 narrations:\n"
        "  persona-v12: 2\n"
        "  persona-v13: 2\n"
        "  qb-persona-v3: 2\n"
        "  qb-persona-v4: 1\n"
    )
    assert _keys(dsn) == set()

    assert _run(dsn, "--all", "--yes") == 0
    assert _out(capsys) == "No narrations match; nothing deleted.\n"


def test_purge_all_confirmed_counts_then_deletes(
    dsn: str, capsys: pytest.CaptureFixture[str]
) -> None:
    status = _run(dsn, "--all", answer="purge")

    assert status == 0
    out = _out(capsys)
    assert out.startswith("--all matches 7 narrations:\n")
    assert "Deleted 7 narrations:\n" in out
    assert _keys(dsn) == set()


def test_purge_all_not_confirmed_deletes_nothing(
    dsn: str, capsys: pytest.CaptureFixture[str]
) -> None:
    status = _run(dsn, "--all", answer="no")

    assert status == 1
    assert _out(capsys).startswith("--all matches 7 narrations:\n")
    assert _keys(dsn) == ALL_KEYS


# ---------------------------------------------------------------------------
# A real database error is one line and exit 1
# ---------------------------------------------------------------------------


def test_missing_table_error_message_names_no_dsn(capsys: pytest.CaptureFixture[str]) -> None:
    with scratch_schema_dsn() as (empty_dsn, schema):
        assert main(["purge-narrations", "--all", "--yes"], database_url=empty_dsn) == 1
    err = capsys.readouterr().err
    assert err.startswith("purge-narrations: database error: ")
    assert err.count("\n") == 1
    assert "persona_cache" in err
    assert "password" not in err and schema not in err
