"""`python -m api.admin purge-narrations` (issue #447): a developer clears
cached narrations on purpose, by prompt version, by age, or all of them.

Nothing here opens a real Postgres connection. `api.admin.main` takes the DSN
and the connect function as arguments, and these tests hand it a
`_FakePersonaCache`: an in-memory `persona_cache` table that answers the two
statements the command sends (a grouped count and a `DELETE ... RETURNING`),
applying the statement's named parameters the way Postgres applies its
`WHERE` clause. It records every statement, so a test can assert that a dry
run never sent a `DELETE` at all, not only that the rows survived.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from api.admin import main

FAKE_DSN = "postgresql://purge.invalid/persona"
NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)


@dataclass
class _Row:
    cache_key: str
    prompt_version: str
    created_at: datetime


@dataclass
class _FakePersonaCache:
    """An in-memory `persona_cache`, reached through a psycopg-shaped
    connection: `execute(query, params).fetchall()`, `commit()`, and use as a
    context manager."""

    rows: list[_Row]
    statements: list[str] = field(default_factory=list)
    committed: int = 0
    _result: list[tuple[Any, ...]] = field(default_factory=list)

    def __enter__(self) -> _FakePersonaCache:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def _matches(self, row: _Row, params: Mapping[str, Any]) -> bool:
        versions = params["prompt_versions"]
        days = params["older_than_days"]
        if versions is not None and row.prompt_version not in versions:
            return False
        return days is None or row.created_at < NOW - timedelta(days=days)

    def execute(self, query: str, params: Mapping[str, Any]) -> _FakePersonaCache:
        self.statements.append(query)
        matching = [row for row in self.rows if self._matches(row, params)]
        verb = query.split()[0].upper()
        if verb == "SELECT":
            counts = Counter(row.prompt_version for row in matching)
            self._result = sorted(counts.items())
        elif verb == "DELETE":
            self.rows = [row for row in self.rows if row not in matching]
            self._result = [(row.prompt_version,) for row in matching]
        else:  # pragma: no cover - a statement this fake doesn't model
            raise AssertionError(f"unexpected statement: {query}")
        return self

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._result

    def commit(self) -> None:
        self.committed += 1

    @property
    def deletes(self) -> list[str]:
        return [s for s in self.statements if s.split()[0].upper() == "DELETE"]

    def versions(self) -> Counter[str]:
        return Counter(row.prompt_version for row in self.rows)


def _table() -> _FakePersonaCache:
    """Two team narrations (one 40 days old), three QB ones (one 40 days
    old), and one under a retired team prompt."""
    return _FakePersonaCache(
        rows=[
            _Row("t1", "persona-v13", NOW - timedelta(days=1)),
            _Row("t2", "persona-v13", NOW - timedelta(days=40)),
            _Row("q1", "qb-persona-v3", NOW - timedelta(days=2)),
            _Row("q2", "qb-persona-v3", NOW - timedelta(days=3)),
            _Row("q3", "qb-persona-v3", NOW - timedelta(days=40)),
            _Row("o1", "persona-v12", NOW - timedelta(days=90)),
        ]
    )


def _connector(table: _FakePersonaCache, dsns: list[str] | None = None) -> Callable[..., Any]:
    def _connect(dsn: str, **kwargs: Any) -> _FakePersonaCache:
        if dsns is not None:
            dsns.append(dsn)
        return table

    return _connect


def _run(
    argv: list[str],
    table: _FakePersonaCache,
    *,
    answer: str | None = None,
) -> int:
    def _confirm(prompt: str) -> str:
        if answer is None:
            raise AssertionError(f"asked for confirmation unexpectedly: {prompt!r}")
        return answer

    return main(
        ["purge-narrations", *argv],
        database_url=FAKE_DSN,
        connect=_connector(table),
        confirm=_confirm,
    )


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_no_selector_refuses_with_usage_and_touches_nothing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    table = _table()

    code = _run([], table)

    assert code != 0
    err = capsys.readouterr().err
    assert "usage:" in err
    assert "--all" in err and "--prompt-version" in err and "--older-than" in err
    assert table.statements == []
    assert len(table.rows) == 6


def test_dry_run_alone_is_still_no_selector(capsys: pytest.CaptureFixture[str]) -> None:
    table = _table()

    code = _run(["--dry-run"], table)

    assert code != 0
    assert "usage:" in capsys.readouterr().err
    assert table.statements == []


def test_all_cannot_be_combined_with_a_narrower_selector(
    capsys: pytest.CaptureFixture[str],
) -> None:
    table = _table()

    code = _run(["--all", "--prompt-version", "persona-v13", "--yes"], table)

    assert code != 0
    assert table.statements == []
    assert len(table.rows) == 6


def test_a_negative_age_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    table = _table()

    code = _run(["--older-than", "-1"], table)

    assert code != 0
    assert table.statements == []


def test_no_database_url_is_an_error_not_a_traceback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    table = _table()

    code = main(
        ["purge-narrations", "--all", "--yes"],
        database_url=None,
        connect=_connector(table),
        confirm=lambda prompt: "",
    )

    assert code != 0
    assert "DATABASE_URL" in capsys.readouterr().err
    assert table.statements == []


# ---------------------------------------------------------------------------
# --dry-run
# ---------------------------------------------------------------------------


def test_dry_run_reports_the_count_and_deletes_nothing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    table = _table()

    code = _run(["--prompt-version", "qb-persona-v3", "--dry-run"], table)

    assert code == 0
    out = capsys.readouterr().out
    assert "Would delete 3 narrations" in out
    assert "qb-persona-v3: 3" in out
    assert table.deletes == []
    assert len(table.rows) == 6


def test_dry_run_of_all_needs_no_confirmation(capsys: pytest.CaptureFixture[str]) -> None:
    table = _table()

    code = _run(["--all", "--dry-run"], table)  # `answer=None`: asking would fail

    assert code == 0
    assert "Would delete 6 narrations" in capsys.readouterr().out
    assert table.deletes == []
    assert len(table.rows) == 6


# ---------------------------------------------------------------------------
# --prompt-version
# ---------------------------------------------------------------------------


def test_prompt_version_deletes_only_matching_rows(capsys: pytest.CaptureFixture[str]) -> None:
    table = _table()

    code = _run(["--prompt-version", "qb-persona-v3"], table)

    assert code == 0
    assert table.versions() == Counter({"persona-v13": 2, "persona-v12": 1})
    assert table.committed >= 1
    out = capsys.readouterr().out
    assert "Deleted 3 narrations" in out
    assert "qb-persona-v3: 3" in out


def test_prompt_version_is_repeatable_and_reports_per_version_counts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    table = _table()

    code = _run(["--prompt-version", "persona-v13", "--prompt-version", "persona-v12"], table)

    assert code == 0
    assert table.versions() == Counter({"qb-persona-v3": 3})
    out = capsys.readouterr().out
    assert "Deleted 3 narrations" in out
    assert "persona-v12: 1" in out
    assert "persona-v13: 2" in out
    assert "qb-persona-v3" not in out


def test_a_version_nothing_matches_deletes_nothing_and_says_so(
    capsys: pytest.CaptureFixture[str],
) -> None:
    table = _table()

    code = _run(["--prompt-version", "persona-v1"], table)

    assert code == 0
    assert len(table.rows) == 6
    assert "No narrations match" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# --older-than
# ---------------------------------------------------------------------------


def test_older_than_deletes_only_rows_past_the_age(capsys: pytest.CaptureFixture[str]) -> None:
    table = _table()

    code = _run(["--older-than", "30"], table)

    assert code == 0
    assert sorted(row.cache_key for row in table.rows) == ["q1", "q2", "t1"]
    out = capsys.readouterr().out
    assert "Deleted 3 narrations" in out
    assert "persona-v12: 1" in out and "persona-v13: 1" in out and "qb-persona-v3: 1" in out


def test_older_than_and_prompt_version_together_narrow_each_other(
    capsys: pytest.CaptureFixture[str],
) -> None:
    table = _table()

    code = _run(["--older-than", "30", "--prompt-version", "qb-persona-v3"], table)

    assert code == 0
    assert sorted(row.cache_key for row in table.rows) == ["o1", "q1", "q2", "t1", "t2"]
    assert "Deleted 1 narration" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# --all and its confirmation
# ---------------------------------------------------------------------------


def test_all_with_yes_deletes_everything_without_asking(
    capsys: pytest.CaptureFixture[str],
) -> None:
    table = _table()

    code = _run(["--all", "--yes"], table)  # `answer=None`: asking would fail

    assert code == 0
    assert table.rows == []
    assert "Deleted 6 narrations" in capsys.readouterr().out


def test_all_without_yes_deletes_after_the_typed_confirmation(
    capsys: pytest.CaptureFixture[str],
) -> None:
    table = _table()

    code = _run(["--all"], table, answer="purge")

    assert code == 0
    assert table.rows == []
    assert "Deleted 6 narrations" in capsys.readouterr().out


@pytest.mark.parametrize("answer", ["", "n", "no", "y", "yes", "PURGE-ish"])
def test_all_without_yes_declined_deletes_nothing(
    answer: str, capsys: pytest.CaptureFixture[str]
) -> None:
    table = _table()

    code = _run(["--all"], table, answer=answer)

    assert code != 0
    assert table.deletes == []
    assert len(table.rows) == 6
    assert "nothing deleted" in capsys.readouterr().err.lower()


def test_all_without_yes_and_no_terminal_input_deletes_nothing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    table = _table()

    def _eof(prompt: str) -> str:
        raise EOFError

    code = main(
        ["purge-narrations", "--all"],
        database_url=FAKE_DSN,
        connect=_connector(table),
        confirm=_eof,
    )

    assert code != 0
    assert table.deletes == []
    assert len(table.rows) == 6


# ---------------------------------------------------------------------------
# The database it is given, and its errors
# ---------------------------------------------------------------------------


def test_it_connects_to_the_database_url_it_is_given() -> None:
    table = _table()
    dsns: list[str] = []

    main(
        ["purge-narrations", "--all", "--dry-run"],
        database_url="postgresql://given.invalid/db",
        connect=_connector(table, dsns),
        confirm=lambda prompt: "",
    )

    assert dsns == ["postgresql://given.invalid/db"]


def test_a_database_error_exits_non_zero_with_a_message_not_a_traceback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _unreachable(dsn: str, **kwargs: Any) -> Any:
        raise psycopg.OperationalError("could not connect to server: host unreachable")

    code = main(
        ["purge-narrations", "--prompt-version", "persona-v13"],
        database_url=FAKE_DSN,
        connect=_unreachable,
        confirm=lambda prompt: "",
    )

    assert code != 0
    err = capsys.readouterr().err
    assert "host unreachable" in err
    assert "Traceback" not in err


def test_the_password_in_the_dsn_is_never_printed(capsys: pytest.CaptureFixture[str]) -> None:
    def _unreachable(dsn: str, **kwargs: Any) -> Any:
        raise psycopg.OperationalError("connection refused")

    main(
        ["purge-narrations", "--all", "--dry-run"],
        database_url="postgresql://user:s3cret-pw@db.invalid/persona",
        connect=_unreachable,
        confirm=lambda prompt: "",
    )

    captured = capsys.readouterr()
    assert "s3cret-pw" not in captured.out + captured.err
