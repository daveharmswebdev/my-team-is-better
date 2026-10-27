"""Issue #343: the curated neutral-site correction layer for CFBD games.

CFBD's cached `/games` data stores `neutralSite: false` for neutral-site
games in 1998-2007 (conference title games, Red River, Florida-Georgia,
Army-Navy). `data/raw/cfbd_neutral_site_overrides.json` lists the 50 games
to correct, each with a source, and `ingest_one` applies it after
`dedupe_game_records`. These tests use the real committed cache and the real
override file (no synthetic game records): the cited games are

  * 213420099, 2001 SEC Championship, Tennessee at LSU, Georgia Dome. CFBD
    already reports the venue; only the flag is wrong.
  * 213350251, 2001 Big 12 Championship, Colorado at Texas. CFBD has no
    venue; the override supplies Texas Stadium.
  * 253370251, 2005 Big 12 Championship, Texas at Colorado, Reliant Stadium.

and two December 2001 games that must stay exactly as CFBD reports them:

  * 213342649, 2001 MAC Championship, Marshall at Toledo, a real home game
    for the higher seed at the Glass Bowl.
  * 213350099, Auburn at LSU, a rescheduled regular-season game at Tiger
    Stadium on 2001-12-02, a week before the SEC title game.

No test here calls the live CFBD API: the cache read is replaced with a
read of the committed `data/raw/` file.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from cfb_strength.db.connection import get_conn
from cfb_strength.ingest.ingest_season import ingest_one
from cfb_strength.ingest.neutral_site_overrides import (
    NEUTRAL_SITE_OVERRIDES_PATH,
    NeutralSiteOverride,
    NeutralSiteOverrideError,
    load_neutral_site_overrides,
)
from cfb_strength.ingest.normalize import dedupe_game_records, normalize_game

ENGINE_DIR = Path(__file__).resolve().parents[1]
COMMITTED_RAW_DIR = ENGINE_DIR / "data" / "raw"
LOGGER_NAME = "cfb_strength.ingest.neutral_site_overrides"


def _cached_games(year: int, season_type: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = json.loads(
        (COMMITTED_RAW_DIR / f"{year}_{season_type}.json").read_text()
    )
    return records


@pytest.fixture
def committed_cache_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point `ingest_one`'s cache read at the committed `data/raw/` file,
    whatever `CFB_DATA_DIR` says, and never reach the network."""

    def _fake_get_games(
        year: int, season_type: str, *, force: bool = False
    ) -> tuple[list[dict[str, Any]], bool]:
        return _cached_games(year, season_type), False

    monkeypatch.setattr("cfb_strength.ingest.ingest_season.get_games", _fake_get_games)


def _ingest(
    db_path: Path,
    year: int,
    season_type: str = "regular",
    *,
    overrides: tuple[NeutralSiteOverride, ...] | None = None,
) -> sqlite3.Connection:
    conn = get_conn(db_path)
    ingest_one(conn, year, season_type, neutral_site_overrides=overrides)
    return conn


def _game(conn: sqlite3.Connection, game_id: int) -> sqlite3.Row:
    row: sqlite3.Row | None = conn.execute(
        "SELECT neutral_site, venue, raw_json FROM games WHERE id = ?", (game_id,)
    ).fetchone()
    assert row is not None, f"game {game_id} was not written"
    return row


def _override(game_id: int) -> NeutralSiteOverride:
    return next(o for o in load_neutral_site_overrides() if o.game_id == game_id)


# ---------------------------------------------------------------------------
# the cited games, through the real CFBD ingest path
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("year", "game_id", "venue"),
    [
        (2001, 213420099, "Georgia Dome"),
        (2001, 213350251, "Texas Stadium"),
        (2005, 253370251, "Reliant Stadium"),
    ],
)
def test_listed_title_games_are_stored_neutral_with_the_override_venue(
    empty_schema_db: Path, committed_cache_only: None, year: int, game_id: int, venue: str
) -> None:
    conn = _ingest(empty_schema_db, year)

    row = _game(conn, game_id)
    assert row["neutral_site"] == 1
    assert row["venue"] == venue


@pytest.mark.parametrize(
    ("game_id", "cfbd_venue"),
    [(213342649, "Glass Bowl"), (213350099, "Tiger Stadium (LA)")],
)
def test_unlisted_december_games_keep_cfbds_flag_and_venue(
    empty_schema_db: Path, committed_cache_only: None, game_id: int, cfbd_venue: str
) -> None:
    conn = _ingest(empty_schema_db, 2001)

    row = _game(conn, game_id)
    assert row["neutral_site"] == 0
    assert row["venue"] == cfbd_venue


def test_raw_json_keeps_cfbds_original_record_for_an_overridden_game(
    empty_schema_db: Path, committed_cache_only: None
) -> None:
    cfbd = next(g for g in _cached_games(2001, "regular") if g["id"] == 213350251)
    conn = _ingest(empty_schema_db, 2001)

    row = _game(conn, 213350251)
    assert json.loads(row["raw_json"]) == cfbd
    assert row["raw_json"] == json.dumps(cfbd, sort_keys=True)
    assert cfbd["neutralSite"] is False and cfbd["venue"] is None
    # The correction shows up only as a diff between raw_json and the row.
    assert (row["neutral_site"], row["venue"]) == (1, "Texas Stadium")


def test_every_unlisted_game_in_the_batch_is_stored_exactly_as_cfbd_reports_it(
    empty_schema_db: Path, committed_cache_only: None
) -> None:
    listed = {o.game_id for o in load_neutral_site_overrides()}
    conn = _ingest(empty_schema_db, 2001)

    stored = {
        r["id"]: (r["neutral_site"], r["venue"])
        for r in conn.execute("SELECT id, neutral_site, venue FROM games")
    }
    games = dedupe_game_records(_cached_games(2001, "regular"))
    unlisted = [g for g in games if g["id"] not in listed]
    assert len(unlisted) == len(games) - 5
    for g in unlisted:
        expected = normalize_game(g, season=2001, season_type="regular")
        assert stored[g["id"]] == (int(expected.neutral_site), expected.venue)


def test_one_info_line_per_applied_override(
    empty_schema_db: Path, committed_cache_only: None, caplog: pytest.LogCaptureFixture
) -> None:
    expected_ids = {
        o.game_id
        for o in load_neutral_site_overrides()
        if (o.season, o.season_type) == (2001, "regular")
    }
    assert len(expected_ids) == 5

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        _ingest(empty_schema_db, 2001)

    lines = [r for r in caplog.records if r.name == LOGGER_NAME]
    assert all(r.levelno == logging.INFO for r in lines)
    assert len(lines) == len(expected_ids)
    assert {
        next(i for i in expected_ids if str(i) in r.getMessage()) for r in lines
    } == expected_ids
    big12 = next(r.getMessage() for r in lines if "213350251" in r.getMessage())
    assert "neutral_site False -> True" in big12
    assert "venue None -> 'Texas Stadium'" in big12


def test_a_postseason_batch_applies_nothing(
    empty_schema_db: Path, committed_cache_only: None, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        conn = _ingest(empty_schema_db, 2001, "postseason")

    assert [r for r in caplog.records if r.name == LOGGER_NAME] == []
    games = dedupe_game_records(_cached_games(2001, "postseason"))
    neutral = conn.execute("SELECT SUM(neutral_site) FROM games").fetchone()[0]
    assert neutral == sum(1 for g in games if g["neutralSite"])


# ---------------------------------------------------------------------------
# a mismatched entry is loud, never a silent skip
# ---------------------------------------------------------------------------


def test_an_override_id_missing_from_its_seasons_payload_raises(
    empty_schema_db: Path, committed_cache_only: None
) -> None:
    ghost = dataclasses.replace(_override(213420099), game_id=999999999)

    with pytest.raises(NeutralSiteOverrideError, match="999999999"):
        _ingest(empty_schema_db, 2001, overrides=(ghost,))


def test_an_override_whose_teams_dont_match_its_record_raises(
    empty_schema_db: Path, committed_cache_only: None
) -> None:
    entry = _override(213420099)
    swapped = dataclasses.replace(entry, home_team=entry.away_team, away_team=entry.home_team)

    with pytest.raises(NeutralSiteOverrideError, match="213420099"):
        _ingest(empty_schema_db, 2001, overrides=(swapped,))


def test_an_override_whose_season_doesnt_match_its_record_raises(
    empty_schema_db: Path, committed_cache_only: None
) -> None:
    # 213420099 is in the 2001 payload, but the entry claims 2002.
    wrong_season = dataclasses.replace(_override(213420099), season=2002)

    with pytest.raises(NeutralSiteOverrideError, match="213420099"):
        _ingest(empty_schema_db, 2001, overrides=(wrong_season,))


def test_a_failed_override_writes_nothing_for_the_batch(
    empty_schema_db: Path, committed_cache_only: None
) -> None:
    ghost = dataclasses.replace(_override(213420099), game_id=999999999)

    with pytest.raises(NeutralSiteOverrideError):
        conn = _ingest(empty_schema_db, 2001, overrides=(ghost,))
    conn = get_conn(empty_schema_db)
    assert conn.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 0


def _write_file(path: Path, entries: list[dict[str, Any]]) -> Path:
    path.write_text(json.dumps({"description": "test", "overrides": entries}))
    return path


def _committed_entries() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = json.loads(NEUTRAL_SITE_OVERRIDES_PATH.read_text())["overrides"]
    return entries


def test_a_duplicate_id_in_the_file_raises(tmp_path: Path) -> None:
    entries = _committed_entries()
    duplicated = [*entries, dict(entries[0])]

    with pytest.raises(NeutralSiteOverrideError, match=str(entries[0]["id"])):
        load_neutral_site_overrides(_write_file(tmp_path / "o.json", duplicated))


@pytest.mark.parametrize(
    ("field", "value"),
    [("neutral_site", False), ("source", ""), ("venue", ""), ("season_type", "bowl")],
)
def test_an_entry_with_a_bad_field_raises(tmp_path: Path, field: str, value: object) -> None:
    entries = _committed_entries()
    entries[0] = {**entries[0], field: value}

    with pytest.raises(NeutralSiteOverrideError, match=field):
        load_neutral_site_overrides(_write_file(tmp_path / "o.json", entries))


def test_an_entry_missing_a_field_raises(tmp_path: Path) -> None:
    entries = _committed_entries()
    entries[0] = {k: v for k, v in entries[0].items() if k != "source"}

    with pytest.raises(NeutralSiteOverrideError, match="source"):
        load_neutral_site_overrides(_write_file(tmp_path / "o.json", entries))


# ---------------------------------------------------------------------------
# the real committed file against the real committed cache
# ---------------------------------------------------------------------------


def test_the_committed_override_file_matches_the_committed_cache() -> None:
    overrides = load_neutral_site_overrides()
    assert NEUTRAL_SITE_OVERRIDES_PATH == COMMITTED_RAW_DIR / "cfbd_neutral_site_overrides.json"
    assert len(overrides) == 50
    assert len({o.game_id for o in overrides}) == 50

    payloads: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for o in overrides:
        for season_type in ("regular", "postseason"):
            key = (o.season, season_type)
            if key not in payloads:
                payloads[key] = dedupe_game_records(_cached_games(o.season, season_type))
        season_records = [
            (season_type, g)
            for season_type in ("regular", "postseason")
            for g in payloads[(o.season, season_type)]
            if g["id"] == o.game_id
        ]
        assert len(season_records) == 1, f"{o.game_id}: {len(season_records)} records"
        season_type, record = season_records[0]
        assert season_type == o.season_type, o.game_id
        assert record["season"] == o.season, o.game_id
        assert (record["homeTeam"], record["awayTeam"]) == (o.home_team, o.away_team), o.game_id
        # A stale or redundant entry (CFBD already says neutral) fails here.
        assert record["neutralSite"] is False, o.game_id
        assert o.source.startswith("Wikipedia: "), o.game_id
        assert o.venue, o.game_id


def test_the_committed_file_lists_the_expected_games_per_rivalry_and_title_game() -> None:
    by_source: dict[str, int] = {}
    for o in load_neutral_site_overrides():
        family = o.source.removeprefix("Wikipedia: ")
        family = family.split(" ", 1)[1] if family[:4].isdigit() else family
        by_source[family] = by_source.get(family, 0) + 1

    assert by_source == {
        "SEC Championship Game": 7,
        "Big 12 Championship Game": 7,
        "ACC Championship Game": 3,
        "MAC Championship Game": 4,
        "Red River Rivalry": 10,
        "Florida-Georgia football rivalry": 9,
        "Army-Navy Game": 10,
    }


def test_the_controls_are_not_in_the_committed_file() -> None:
    listed = {o.game_id for o in load_neutral_site_overrides()}
    # 2004 Florida-Georgia is already neutral in CFBD; the rest are real home games.
    assert listed.isdisjoint({243040061, 213342649, 213350099, 233380189, 263350248})
