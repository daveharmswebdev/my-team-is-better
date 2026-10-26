"""Issue #211: the nflverse season-ingest CLI (`ingest_season.main`) and its
`--years` parser, run for real.

`main()` reads the committed nflverse cache (`data/raw/nfl/games.csv` and
`teams.csv`, whole-history files) and writes a fresh temp db. The network is
stubbed to fail for every test in this module (`_no_network`), so a run that
exits 0 proves ingest is cache-first: it never asked for a live fetch. The
stub records each attempted URL, so the cache-hit tests also assert that no
fetch was even tried. Only `--force` asks for one, and that path must fail
cleanly with exit 1.

The CFBD path's equivalent is test_ingest_year_range.py; the two parsers are
deliberately duplicated (see ingest_season.py's docstring), so each gets its
own tests.
"""

from __future__ import annotations

import hashlib
import runpy
import sqlite3
import sys
from pathlib import Path
from typing import NoReturn

import pytest
import requests

from cfb_strength.contracts import TeamRow
from cfb_strength.db.connection import get_conn
from cfb_strength.ingest.nflverse import client, ingest_season
from cfb_strength.ingest.nflverse.ingest_season import (
    _assert_no_surrogate_collisions,
    main,
    parse_years,
)

# Counts measured on the committed cache (data/raw/nfl/games.csv): every
# season from 2021 on is 17 weeks of 16 games (272), and a 14-team playoff
# is 6 WC + 4 DIV + 2 CON + 1 SB = 13 games.
REGULAR_GAMES_2023 = 272
POSTSEASON_GAMES_2023 = 13
NFL_TEAMS = 32


@pytest.fixture
def fetch_attempts(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Stub the client's transport so every live fetch fails as a network
    outage would, recording the URL it was asked for."""
    attempts: list[str] = []

    def _no_network(url: str, timeout: float) -> NoReturn:
        attempts.append(url)
        raise requests.ConnectionError("network disabled in tests (#211)")

    monkeypatch.setattr(requests, "get", _no_network)
    return attempts


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "nfl_cli.sqlite3"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- parse_years ------------------------------------------------------------


def test_a_single_year() -> None:
    assert parse_years("2024") == [2024]


def test_a_range_is_inclusive_at_both_ends() -> None:
    assert parse_years("2005-2010") == [2005, 2006, 2007, 2008, 2009, 2010]


def test_a_reversed_range_means_the_same_years() -> None:
    assert parse_years("2010-2005") == [2005, 2006, 2007, 2008, 2009, 2010]


def test_a_comma_list_is_sorted_and_deduplicated() -> None:
    assert parse_years("2023,2001,2023") == [2001, 2023]


def test_blank_tokens_and_whitespace_are_ignored() -> None:
    assert parse_years(" 2023 ,, ,2024,") == [2023, 2024]


def test_a_mix_of_ranges_and_years_overlapping() -> None:
    assert parse_years("2001, 2003 - 2004,2004-2003,1999") == [1999, 2001, 2003, 2004]


def test_an_all_blank_spec_is_no_years() -> None:
    assert parse_years(" , ") == []


@pytest.mark.parametrize("spec", ["twenty-twenty", "2023-", "-2023", "2023x", "2023-2024-2025"])
def test_a_malformed_token_raises_value_error(spec: str) -> None:
    with pytest.raises(ValueError):
        parse_years(spec)


# --- main(): the cache-first happy path --------------------------------------


def test_main_ingests_the_committed_cache_without_a_fetch(
    fetch_attempts: list[str], db_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(["--years", "2023", "--db-path", str(db_path)])

    assert exit_code == 0
    assert fetch_attempts == []
    out = capsys.readouterr().out
    assert "live fetches this run: no (cache hit)" in out

    conn: sqlite3.Connection = get_conn(db_path)
    try:
        log = {
            (r["year"], r["season_type"]): (r["game_count"], r["status"])
            for r in conn.execute(
                "SELECT year, season_type, game_count, status FROM ingestion_log "
                "WHERE sport = 'nfl'"
            ).fetchall()
        }
        games = {
            r["season_type"]: r["c"]
            for r in conn.execute(
                "SELECT season_type, COUNT(*) AS c FROM games "
                "WHERE sport = 'nfl' AND season = 2023 GROUP BY season_type"
            ).fetchall()
        }
        teams = conn.execute(
            "SELECT source_id, classification FROM teams WHERE sport = 'nfl'"
        ).fetchall()
        conferences = {
            r["conference"]: r["c"]
            for r in conn.execute(
                "SELECT conference, COUNT(*) AS c FROM team_season "
                "WHERE sport = 'nfl' AND year = 2023 GROUP BY conference"
            ).fetchall()
        }
        non_nfl = conn.execute("SELECT COUNT(*) AS c FROM games WHERE sport != 'nfl'").fetchone()
    finally:
        conn.close()

    assert log == {
        (2023, "regular"): (REGULAR_GAMES_2023, "ok"),
        (2023, "postseason"): (POSTSEASON_GAMES_2023, "ok"),
    }
    assert games == {"regular": REGULAR_GAMES_2023, "postseason": POSTSEASON_GAMES_2023}
    assert len(teams) == NFL_TEAMS
    # NFL teams carry no classification; conference comes from teams.csv.
    assert {r["classification"] for r in teams} == {None}
    assert conferences == {"AFC": 16, "NFC": 16}
    assert non_nfl["c"] == 0


def test_main_season_types_flag_limits_the_batches(
    fetch_attempts: list[str], db_path: Path
) -> None:
    exit_code = main(
        ["--years", "2024-2023", "--season-types", "postseason", "--db-path", str(db_path)]
    )

    assert exit_code == 0
    assert fetch_attempts == []
    conn: sqlite3.Connection = get_conn(db_path)
    try:
        batches = sorted(
            (r["year"], r["season_type"])
            for r in conn.execute("SELECT year, season_type FROM ingestion_log").fetchall()
        )
    finally:
        conn.close()
    assert batches == [(2023, "postseason"), (2024, "postseason")]


def test_main_skips_years_outside_the_range_with_a_warning(
    fetch_attempts: list[str], db_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(
        ["--years", "1998,1999,2025,2026", "--season-types", "regular", "--db-path", str(db_path)]
    )

    assert exit_code == 0
    assert fetch_attempts == []
    err = capsys.readouterr().err
    assert "skipping years outside 1999-2025: [1998, 2026]" in err
    conn: sqlite3.Connection = get_conn(db_path)
    try:
        years = {r["year"] for r in conn.execute("SELECT year FROM ingestion_log").fetchall()}
    finally:
        conn.close()
    assert years == {1999, 2025}


# --- main(): failure exits -----------------------------------------------------


def test_main_rejects_a_malformed_years_spec(
    fetch_attempts: list[str], db_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(["--years", "2023,abc", "--db-path", str(db_path)])

    assert exit_code == 1
    assert "could not parse --years '2023,abc'" in capsys.readouterr().err
    assert fetch_attempts == []
    assert not db_path.exists()


def test_main_fails_when_no_requested_year_is_in_range(
    fetch_attempts: list[str], db_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(["--years", "2026", "--db-path", str(db_path)])

    assert exit_code == 1
    assert "no valid years to ingest" in capsys.readouterr().err
    assert fetch_attempts == []
    assert not db_path.exists()


def test_main_rejects_an_unknown_season_type(
    fetch_attempts: list[str], db_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(
        ["--years", "2023", "--season-types", "regular,preseason", "--db-path", str(db_path)]
    )

    assert exit_code == 1
    assert "unknown season type(s) ['preseason']" in capsys.readouterr().err
    assert not db_path.exists()


def test_main_without_years_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2
    assert "--years" in capsys.readouterr().err


def test_main_force_with_the_network_down_exits_1_and_keeps_the_cache(
    fetch_attempts: list[str], db_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    games_cache = client.games_cache_path()
    before = _sha256(games_cache)

    exit_code = main(["--years", "2023", "--force", "--db-path", str(db_path)])

    assert exit_code == 1
    assert fetch_attempts == [client.GAMES_URL]
    assert "could not reach nflverse asset" in capsys.readouterr().err
    assert _sha256(games_cache) == before
    assert not db_path.exists()


def _teams_without(monkeypatch: pytest.MonkeyPatch, abbr: str) -> None:
    """Serve the real cached teams.csv minus one team, so every game that
    team played fails to normalize (`ValueError: no team-desc entry`)."""
    rows, _ = client.get_teams()
    assert any(r["team_abbr"] == abbr for r in rows)
    kept = [r for r in rows if r["team_abbr"] != abbr]

    def _get_teams(*, force: bool = False) -> tuple[list[dict[str, str]], bool]:
        return kept, False

    monkeypatch.setattr(ingest_season, "get_teams", _get_teams)


def test_main_exits_1_when_one_batch_fails_but_writes_the_others(
    fetch_attempts: list[str],
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The 2023 Giants (6-11) played the regular season but not the playoffs.
    _teams_without(monkeypatch, "NYG")

    exit_code = main(["--years", "2023", "--db-path", str(db_path)])

    assert exit_code == 1
    assert fetch_attempts == []
    err = capsys.readouterr().err
    assert "1 year/season-type batch(es) failed to ingest" in err
    assert "2023 regular: no team-desc entry for nflverse team_abbr 'NYG'" in err
    conn: sqlite3.Connection = get_conn(db_path)
    try:
        batches = [
            (r["year"], r["season_type"], r["game_count"])
            for r in conn.execute("SELECT * FROM ingestion_log").fetchall()
        ]
    finally:
        conn.close()
    assert batches == [(2023, "postseason", POSTSEASON_GAMES_2023)]


def test_main_exits_1_when_every_batch_fails(
    fetch_attempts: list[str],
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The 2023 Chiefs played every week through the Super Bowl.
    _teams_without(monkeypatch, "KC")

    exit_code = main(["--years", "2023", "--db-path", str(db_path)])

    assert exit_code == 1
    assert "2 year/season-type batch(es) failed to ingest" in capsys.readouterr().err


def test_running_the_module_exits_with_mains_code(
    fetch_attempts: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "argv", ["ingest-season-nflverse", "--years", "2026"])
    # runpy re-executes a module that is already imported; that warning is
    # expected here and not what this test checks.
    with pytest.warns(RuntimeWarning, match="found in sys.modules"):
        with pytest.raises(SystemExit) as exc:
            runpy.run_module("cfb_strength.ingest.nflverse.ingest_season", run_name="__main__")
    assert exc.value.code == 1


# --- the surrogate-collision guard ----------------------------------------------


def test_two_source_ids_minting_one_id_is_refused() -> None:
    rows = [
        TeamRow(
            id=7, school="A", classification=None, conference="AFC", sport="nfl", source_id="AAA"
        ),
        TeamRow(
            id=7, school="B", classification=None, conference="NFC", sport="nfl", source_id="BBB"
        ),
    ]
    with pytest.raises(ValueError, match="surrogate id collision: id=7"):
        _assert_no_surrogate_collisions(rows)


def test_the_same_source_id_twice_is_not_a_collision() -> None:
    row = TeamRow(
        id=7, school="A", classification=None, conference="AFC", sport="nfl", source_id="AAA"
    )
    _assert_no_surrogate_collisions([row, row])
