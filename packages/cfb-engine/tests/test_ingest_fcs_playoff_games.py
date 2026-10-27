"""Issue #379: FCS (I-AA) playoff games are stored as postseason.

CFBD files most FCS playoff games as season_type 'regular' (the 2013 first
round sits in regular week 14), and only some of them carry a notes marker.
`data/raw/cfbd_fcs_playoff_games.json` lists every FCS playoff game in the
committed cache by CFBD id, and `ingest_one` stores exactly those ids with
season_type 'postseason'. Week, every other column and `raw_json` stay as
CFBD reports them.

These tests use the real committed cache and the real list (no synthetic
game records). The cited games are

  * 333340055, 2013 FCS first round, Samford at Jacksonville State, CFBD
    regular week 14 (notes "NCAA DIVISION I FOOTBALL CHAMPIONSHIP - FIRST
    ROUND").
  * 400930788, 2016 FCS final, Youngstown State at James Madison, already
    postseason in CFBD (notes empty).
  * 333342755, the 2013 Bayou Classic, Southern at Grambling, played on
    first-round Saturday but not a playoff game: it stays regular.

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

from cfb_strength.db.connection import ensure_schema, get_conn
from cfb_strength.ingest.fcs_playoff_games import (
    FCS_PLAYOFF_GAMES_PATH,
    FcsPlayoffGame,
    FcsPlayoffGameError,
    apply_fcs_playoff_games,
    load_fcs_playoff_games,
)
from cfb_strength.ingest.ingest_season import ingest_one
from cfb_strength.ingest.normalize import dedupe_game_records, normalize_game

ENGINE_DIR = Path(__file__).resolve().parents[1]
COMMITTED_RAW_DIR = ENGINE_DIR / "data" / "raw"
LOGGER_NAME = "cfb_strength.ingest.fcs_playoff_games"

JSU_SAMFORD_2013 = 333340055
FINAL_2016 = 400930788
BAYOU_CLASSIC_2013 = 333342755


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
    playoff_games: tuple[FcsPlayoffGame, ...] | None = None,
) -> sqlite3.Connection:
    conn = get_conn(db_path)
    ingest_one(conn, year, season_type, fcs_playoff_games=playoff_games)
    return conn


def _game(conn: sqlite3.Connection, game_id: int) -> sqlite3.Row:
    row: sqlite3.Row | None = conn.execute(
        "SELECT season_type, week, raw_json FROM games WHERE id = ?", (game_id,)
    ).fetchone()
    assert row is not None, f"game {game_id} was not written"
    return row


def _entry(game_id: int) -> FcsPlayoffGame:
    return next(g for g in load_fcs_playoff_games() if g.game_id == game_id)


def _rows(year: int, season_type: str) -> list[Any]:
    return [
        normalize_game(g, season=year, season_type=season_type)
        for g in dedupe_game_records(_cached_games(year, season_type))
    ]


# ---------------------------------------------------------------------------
# the apply function on real normalized rows
# ---------------------------------------------------------------------------


def test_apply_relabels_a_listed_regular_game_and_nothing_else() -> None:
    rows = _rows(2013, "regular")
    entry = _entry(JSU_SAMFORD_2013)

    applied = apply_fcs_playoff_games(rows, season=2013, season_type="regular", games=(entry,))

    assert len(applied) == len(rows)
    for before, after in zip(rows, applied, strict=True):
        if before.id == JSU_SAMFORD_2013:
            assert before.season_type == "regular"
            assert after == dataclasses.replace(before, season_type="postseason")
        else:
            assert after == before


def test_apply_is_a_no_op_on_a_listed_postseason_game(caplog: pytest.LogCaptureFixture) -> None:
    rows = _rows(2016, "postseason")
    entry = _entry(FINAL_2016)
    assert entry.season_type == "postseason"

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        applied = apply_fcs_playoff_games(
            rows, season=2016, season_type="postseason", games=(entry,)
        )

    assert applied == rows
    assert [r for r in caplog.records if r.name == LOGGER_NAME] == []


def test_apply_raises_on_a_listed_id_missing_from_the_batch() -> None:
    ghost = dataclasses.replace(_entry(JSU_SAMFORD_2013), game_id=999999999)

    with pytest.raises(FcsPlayoffGameError, match="999999999"):
        apply_fcs_playoff_games(
            _rows(2013, "regular"), season=2013, season_type="regular", games=(ghost,)
        )


# ---------------------------------------------------------------------------
# the cited games, through the real CFBD ingest path
# ---------------------------------------------------------------------------


def test_a_2013_week_14_first_round_game_is_stored_as_postseason(
    empty_schema_db: Path, committed_cache_only: None
) -> None:
    cfbd = next(g for g in _cached_games(2013, "regular") if g["id"] == JSU_SAMFORD_2013)
    assert (cfbd["seasonType"], cfbd["week"]) == ("regular", 14)
    assert (cfbd["awayTeam"], cfbd["homeTeam"]) == ("Samford", "Jacksonville State")

    conn = _ingest(empty_schema_db, 2013)

    row = _game(conn, JSU_SAMFORD_2013)
    assert row["season_type"] == "postseason"
    assert row["week"] == 14
    # The correction shows up only as a diff between raw_json and the row.
    assert row["raw_json"] == json.dumps(cfbd, sort_keys=True)


def test_every_other_game_in_the_batch_keeps_cfbds_season_type(
    empty_schema_db: Path, committed_cache_only: None
) -> None:
    listed = {
        g.game_id
        for g in load_fcs_playoff_games()
        if (g.season, g.season_type) == (2013, "regular")
    }
    assert len(listed) == 8

    conn = _ingest(empty_schema_db, 2013)

    stored = {r["id"]: r["season_type"] for r in conn.execute("SELECT id, season_type FROM games")}
    assert {i for i, t in stored.items() if t == "postseason"} == listed
    assert stored[BAYOU_CLASSIC_2013] == "regular"
    assert len(stored) == len(dedupe_game_records(_cached_games(2013, "regular")))


def test_a_listed_postseason_game_is_stored_unchanged(
    empty_schema_db: Path, tmp_path: Path, committed_cache_only: None
) -> None:
    with_list = _ingest(empty_schema_db, 2016, "postseason")
    other_db = _fresh_schema_db(tmp_path / "without.sqlite3")
    without_list = _ingest(other_db, 2016, "postseason", playoff_games=())

    query = "SELECT * FROM games ORDER BY id"
    assert [tuple(r) for r in with_list.execute(query)] == [
        tuple(r) for r in without_list.execute(query)
    ]
    assert _game(with_list, FINAL_2016)["season_type"] == "postseason"


def _fresh_schema_db(dest: Path) -> Path:
    conn = get_conn(dest)
    ensure_schema(conn)
    conn.close()
    return dest


def test_one_info_line_per_relabelled_game(
    empty_schema_db: Path, committed_cache_only: None, caplog: pytest.LogCaptureFixture
) -> None:
    expected = {
        g.game_id
        for g in load_fcs_playoff_games()
        if (g.season, g.season_type) == (2013, "regular")
    }

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        _ingest(empty_schema_db, 2013)

    lines = [r for r in caplog.records if r.name == LOGGER_NAME]
    assert all(r.levelno == logging.INFO for r in lines)
    assert len(lines) == len(expected)
    assert {next(i for i in expected if str(i) in r.getMessage()) for r in lines} == expected
    jsu = next(r.getMessage() for r in lines if str(JSU_SAMFORD_2013) in r.getMessage())
    assert "season_type 'regular' -> 'postseason'" in jsu
    assert "first round" in jsu


# ---------------------------------------------------------------------------
# a mismatched entry is loud, never a silent skip, and writes nothing
# ---------------------------------------------------------------------------


def _games_written(db_path: Path) -> int:
    conn = get_conn(db_path)
    try:
        count: int = conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]
    finally:
        conn.close()
    return count


@pytest.mark.parametrize(
    "change",
    [
        {"game_id": 999999999},
        {"season": 2014},
        {"season_type": "postseason"},
        {"home_team": "Samford", "away_team": "Jacksonville State"},
        {"home_team": "Furman"},
    ],
    ids=["missing", "wrong-season", "wrong-season-type", "swapped-teams", "wrong-team"],
)
def test_a_mismatched_entry_raises_and_writes_nothing(
    empty_schema_db: Path, committed_cache_only: None, change: dict[str, Any]
) -> None:
    bad = dataclasses.replace(_entry(JSU_SAMFORD_2013), **change)
    entries = (bad,) if "game_id" in change else (bad, _entry(333340160))

    with pytest.raises(FcsPlayoffGameError, match=str(bad.game_id)):
        _ingest(empty_schema_db, 2013, playoff_games=entries)
    assert _games_written(empty_schema_db) == 0


def test_an_entry_listed_for_another_season_raises_in_the_batch_that_holds_it(
    empty_schema_db: Path, committed_cache_only: None
) -> None:
    # 333340055 is in the 2013 regular payload, but the entry claims 2012.
    wrong_season = dataclasses.replace(_entry(JSU_SAMFORD_2013), season=2012)

    with pytest.raises(FcsPlayoffGameError, match=str(JSU_SAMFORD_2013)):
        _ingest(empty_schema_db, 2013, playoff_games=(wrong_season,))
    assert _games_written(empty_schema_db) == 0


# ---------------------------------------------------------------------------
# the loader
# ---------------------------------------------------------------------------


def _committed_document() -> dict[str, Any]:
    document: dict[str, Any] = json.loads(FCS_PLAYOFF_GAMES_PATH.read_text())
    return document


def _write(path: Path, entries: list[dict[str, Any]]) -> Path:
    document = _committed_document()
    document["games"] = entries
    path.write_text(json.dumps(document))
    return path


def test_the_committed_file_loads() -> None:
    assert FCS_PLAYOFF_GAMES_PATH == COMMITTED_RAW_DIR / "cfbd_fcs_playoff_games.json"
    games = load_fcs_playoff_games()
    assert len(games) == len(_committed_document()["games"])
    assert _entry(JSU_SAMFORD_2013) == FcsPlayoffGame(
        game_id=JSU_SAMFORD_2013,
        season=2013,
        season_type="regular",
        home_team="Jacksonville State",
        away_team="Samford",
        round="first round",
        source="CFBD notes: NCAA DIVISION I FOOTBALL CHAMPIONSHIP - FIRST ROUND",
    )


def test_a_duplicate_id_in_the_file_raises(tmp_path: Path) -> None:
    entries = _committed_document()["games"]
    duplicated = [*entries, dict(entries[0])]

    with pytest.raises(FcsPlayoffGameError, match=str(entries[0]["id"])):
        load_fcs_playoff_games(_write(tmp_path / "g.json", duplicated))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("round", "play-in"),
        ("source", ""),
        ("season_type", "bowl"),
        ("home_team", ""),
        ("season", "2013"),
    ],
)
def test_an_entry_with_a_bad_field_raises(tmp_path: Path, field: str, value: object) -> None:
    entries = _committed_document()["games"]
    entries[0] = {**entries[0], field: value}

    with pytest.raises(FcsPlayoffGameError, match=field):
        load_fcs_playoff_games(_write(tmp_path / "g.json", entries))


def test_an_entry_missing_or_adding_a_field_raises(tmp_path: Path) -> None:
    entries = _committed_document()["games"]
    missing = [{k: v for k, v in entries[0].items() if k != "round"}, *entries[1:]]
    extra = [{**entries[0], "week": 14}, *entries[1:]]

    with pytest.raises(FcsPlayoffGameError, match="round"):
        load_fcs_playoff_games(_write(tmp_path / "missing.json", missing))
    with pytest.raises(FcsPlayoffGameError, match="week"):
        load_fcs_playoff_games(_write(tmp_path / "extra.json", extra))
