"""Coverage for the CFBD `/teams` alias-enrichment path (issue #77, epic #76):
the cache-first `get_teams` client, `/teams` -> `TeamRow` normalization, and
the `teams.mascot` / `teams.alternate_names` enrichment wired into
`ingest_season.main`.

Fixtures are real captured data, never synthesized shapes:

  - `tests/fixtures/raw_cfbd_teams_sample.json` -- 18 records extracted
    verbatim (including payload order) from the committed
    `data/raw/teams.json` cache of a single live `GET /teams` call with no
    `year` param. Chosen to cover every case that actually occurs in the
    1933-record payload:
      * ordinary joins, incl. the awkward identity strings the web picker
        will have to match: Texas/Longhorns, Ohio State/Buckeyes,
        Miami (OH)/RedHawks vs Miami/Hurricanes, NC State/Wolfpack, and
        San José State/Spartans (accent survives the round trip).
      * `USC`, whose own `alternateNames` is the literal `["USC", "USC"]`
        and whose `abbreviation` is also `"USC"` -- a real in-payload
        duplicate, so dedupe is exercised against real data.
      * `Albany State`, a duplicate-school pair whose mascot-less STUB
        record comes FIRST in the payload (`records[0]` or a naive
        `{school: record}` dict silently drops `Golden Rams`).
      * `Alma`, the same duplicate-school case with the stub SECOND.
      * `Centenary (LA)`, a duplicate where BOTH records have a mascot.
      * `Cal State Northridge`, the single stored CFB school for which
        CFBD has no mascot at all (`mascot: null`, `alternateNames: []`,
        `abbreviation: null`).
      * `Avila University`, a real record for a team that never appears in
        any `/games` payload we ingest -- it must NOT be inserted into
        `teams`.
    `Morgan State` is deliberately absent from this fixture (it does have a
    mascot in the full payload) so the games-derived-but-unmatched path has
    a real subject too.

  - `tests/fixtures/raw_games_sample.json` -- the existing real `/games`
    fixture, reused here to build the `teams` rows enrichment runs against,
    so the join is tested against genuinely `/games`-derived rows rather
    than hand-placed ones.

Nothing here makes a live API call: the `get_teams` cache tests assert the
HTTP function is never invoked, and every enrichment test points `raw_dir`
at a `tmp_path` copy of the fixture.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from cfb_strength.contracts import TeamRow
from cfb_strength.db.connection import get_conn
from cfb_strength.ingest import client as client_module
from cfb_strength.ingest.client import CFBDClientError, get_teams, teams_cache_path
from cfb_strength.ingest.ingest_season import (
    _write_teams,
    enrich_team_aliases,
)
from cfb_strength.ingest.normalize import (
    normalize_game,
    team_row_from_cfbd_team,
    team_rows_from_cfbd_teams,
    team_rows_from_game,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
TEAMS_FIXTURE = FIXTURES_DIR / "raw_cfbd_teams_sample.json"
GAMES_FIXTURE = FIXTURES_DIR / "raw_games_sample.json"

# Patched by string rather than by attribute so `mypy --strict` doesn't have
# to treat the client's `requests` import as a re-export.
_REQUESTS_GET = "cfb_strength.ingest.client.requests.get"


def _teams_fixture() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = json.loads(TEAMS_FIXTURE.read_text())
    return records


def _record(school: str, *, team_id: int | None = None) -> dict[str, Any]:
    """Pull one real fixture record, disambiguating duplicates by CFBD id."""
    matches = [r for r in _teams_fixture() if r["school"] == school]
    if team_id is not None:
        matches = [r for r in matches if r["id"] == team_id]
    assert len(matches) == 1, f"{school!r} did not uniquely match: {len(matches)} records"
    return matches[0]


@pytest.fixture
def cached_teams_dir(tmp_path: Path) -> Path:
    """A `raw_dir` containing only the real `/teams` fixture as `teams.json`."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    shutil.copy(TEAMS_FIXTURE, raw_dir / "teams.json")
    return raw_dir


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """Replace the client's HTTP call with a recorder that fails if used."""
    calls: list[object] = []

    def _forbidden(*args: object, **kwargs: object) -> object:
        calls.append((args, kwargs))
        raise AssertionError("a live HTTP request was made when the cache should have been used")

    monkeypatch.setattr(_REQUESTS_GET, _forbidden)
    return calls


# ---------------------------------------------------------------------------
# client: cache-first get_teams, mirroring get_games's load-or-fetch contract
# ---------------------------------------------------------------------------


def test_teams_cache_path_is_one_year_independent_file(tmp_path: Path) -> None:
    """`/teams` is fetched once with no `year` param (1933 records, covering
    every stored CFB school), so the cache is a single file -- not one per
    season like `/games`."""
    assert teams_cache_path(tmp_path) == tmp_path / "teams.json"


def test_get_teams_reads_cache_without_network(
    cached_teams_dir: Path, no_network: list[object]
) -> None:
    records, fetched_live = get_teams(raw_dir=cached_teams_dir)

    assert fetched_live is False
    assert no_network == [], "get_teams must not touch the network on a cache hit"
    assert len(records) == len(_teams_fixture())
    assert {r["school"] for r in records} >= {"Texas", "Alma", "Albany State"}


def test_get_teams_fetches_and_writes_cache_on_miss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_dir = tmp_path / "nested" / "raw"  # not created yet -- get_teams must mkdir
    payload = _teams_fixture()
    seen: list[dict[str, Any]] = []

    class _Resp:
        status_code = 200
        text = ""

        def json(self) -> list[dict[str, Any]]:
            return payload

    def _fake_get(url: str, **kwargs: Any) -> _Resp:
        seen.append({"url": url, **kwargs})
        return _Resp()

    monkeypatch.setattr(client_module, "CFBD_API_KEY", "test-key")
    monkeypatch.setattr(_REQUESTS_GET, _fake_get)

    records, fetched_live = get_teams(raw_dir=raw_dir)

    assert fetched_live is True
    assert len(seen) == 1
    assert seen[0]["url"].endswith("/teams")
    # Year-independent: one call for the whole project, so no `year` param.
    assert "year" not in (seen[0]["params"] or {})
    assert records == payload

    cache_file = raw_dir / "teams.json"
    assert cache_file.exists()
    assert json.loads(cache_file.read_text()) == payload

    # A second call is now a pure cache hit.
    monkeypatch.setattr(
        _REQUESTS_GET,
        lambda *a, **k: pytest.fail("second call should have hit the cache"),
    )
    again, fetched_again = get_teams(raw_dir=raw_dir)
    assert fetched_again is False
    assert again == payload


def test_get_teams_force_refetches_even_with_a_cache_file(
    cached_teams_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Resp:
        status_code = 200
        text = ""

        def json(self) -> list[dict[str, Any]]:
            return [{"id": 1, "school": "Forced", "mascot": "Refetches"}]

    monkeypatch.setattr(client_module, "CFBD_API_KEY", "test-key")
    monkeypatch.setattr(_REQUESTS_GET, lambda *a, **k: _Resp())

    records, fetched_live = get_teams(force=True, raw_dir=cached_teams_dir)

    assert fetched_live is True
    assert records == [{"id": 1, "school": "Forced", "mascot": "Refetches"}]


def test_get_teams_without_cache_or_api_key_raises_cfbd_client_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(client_module, "CFBD_API_KEY", None)

    with pytest.raises(CFBDClientError) as excinfo:
        get_teams(raw_dir=tmp_path / "empty")

    assert "CFBD_API_KEY" in str(excinfo.value)


# ---------------------------------------------------------------------------
# normalize: one raw /teams record -> TeamRow
# ---------------------------------------------------------------------------


def test_team_row_from_cfbd_team_carries_mascot_and_alternate_names() -> None:
    row = team_row_from_cfbd_team(_record("Texas"))

    assert isinstance(row, TeamRow)
    assert row.id == 251
    assert row.school == "Texas"
    assert row.mascot == "Longhorns"
    # CFBD's alternateNames (["TEX", "Texas"]) plus its `abbreviation`
    # scalar ("TEX"), deduped -- "TEX" must not be ranked twice by a later
    # alias search.
    assert isinstance(row.alternate_names, tuple)
    assert "TEX" in row.alternate_names
    assert "Texas" in row.alternate_names
    assert len(row.alternate_names) == len(set(row.alternate_names))
    assert row.alternate_names == ("TEX", "Texas")
    # classification/conference come through too, but note what they mean:
    # the year-independent /teams call reports PRESENT-DAY affiliation, so
    # Texas here is "SEC", not the "Big 12" the 2005 /games records say. That
    # is exactly why enrichment must never write these two columns -- see
    # test_enrichment_does_not_overwrite_historical_conference_or_classification.
    assert row.classification == "fbs"
    assert row.conference == "SEC"


def test_team_row_dedupes_a_real_in_payload_duplicate_alias() -> None:
    """USC's own alternateNames is literally ["USC", "USC"], and its
    abbreviation is "USC" as well."""
    row = team_row_from_cfbd_team(_record("USC"))

    assert row.mascot == "Trojans"
    assert row.alternate_names == ("USC",)


def test_team_row_carries_richer_alternate_names_than_just_the_abbreviation() -> None:
    row = team_row_from_cfbd_team(_record("NC State"))

    assert row.mascot == "Wolfpack"
    assert row.alternate_names == ("North Carolina St.", "NCSU", "NC State")


def test_team_row_from_cfbd_team_handles_a_null_mascot_record() -> None:
    row = team_row_from_cfbd_team(_record("Cal State Northridge"))

    assert row.school == "Cal State Northridge"
    assert row.mascot is None
    assert row.alternate_names == ()


def test_awkward_identity_strings_join_byte_identically() -> None:
    """No fuzzy matching is needed (or wanted) to join /teams onto the
    /games-derived rows: `school` is byte-identical, accents included."""
    by_school = team_rows_from_cfbd_teams(_teams_fixture())

    assert by_school["Ohio State"].mascot == "Buckeyes"
    assert by_school["Miami (OH)"].mascot == "RedHawks"
    assert by_school["Miami"].mascot == "Hurricanes"
    assert by_school["San José State"].mascot == "Spartans"
    assert by_school["San José State"].school == "San José State"


def test_duplicate_school_records_prefer_the_one_with_a_mascot() -> None:
    """42 stored schools have duplicate CFBD records under the same `school`,
    usually a stub with `mascot: null`. Selection must not depend on payload
    order -- the stub is first about half the time."""
    alma = [r for r in _teams_fixture() if r["school"] == "Alma"]
    assert len(alma) == 2
    assert [r["mascot"] for r in alma] == ["Scots", None]

    stub_last = team_rows_from_cfbd_teams(alma)
    stub_first = team_rows_from_cfbd_teams(list(reversed(alma)))

    assert stub_last["Alma"].mascot == "Scots"
    assert stub_first["Alma"].mascot == "Scots", "the stub-first ordering dropped the mascot"
    assert stub_first["Alma"].alternate_names == ("ALMA", "Alma")


def test_real_stub_first_duplicate_keeps_its_mascot() -> None:
    """Albany State's mascot-less stub is genuinely first in the live payload,
    in the fixture's untouched capture order."""
    albany = [r for r in _teams_fixture() if r["school"] == "Albany State"]
    assert [r["mascot"] for r in albany] == [None, "Golden Rams"]

    rows = team_rows_from_cfbd_teams(_teams_fixture())

    assert rows["Albany State"].mascot == "Golden Rams"
    assert rows["Albany State"].alternate_names == ("ABSU", "Albany St")


def test_duplicate_where_both_records_have_a_mascot_is_deterministic() -> None:
    rows_forward = team_rows_from_cfbd_teams(_teams_fixture())
    rows_reversed = team_rows_from_cfbd_teams(list(reversed(_teams_fixture())))

    # Centenary (LA): ("Gentlemen", "CTLA") and ("Gents", None). The record
    # with aliases wins regardless of order.
    assert rows_forward["Centenary (LA)"].mascot == "Gentlemen"
    assert rows_reversed["Centenary (LA)"].mascot == "Gentlemen"


def test_team_rows_from_cfbd_teams_is_keyed_by_school_with_no_duplicates() -> None:
    rows = team_rows_from_cfbd_teams(_teams_fixture())

    schools = {r["school"] for r in _teams_fixture()}
    assert set(rows) == schools
    assert all(school == row.school for school, row in rows.items())


# ---------------------------------------------------------------------------
# ingest_season: enrichment against real /games-derived teams rows
# ---------------------------------------------------------------------------


def _db_with_games_derived_teams(db_path: Path) -> sqlite3.Connection:
    """Build the `teams` rows the real ingest would, from the real /games
    fixture (Cincinnati, Eastern Michigan, Towson, Morgan State, Texas, USC)."""
    conn = get_conn(db_path)
    records: list[dict[str, Any]] = json.loads(GAMES_FIXTURE.read_text())
    team_rows: dict[int, TeamRow] = {}
    for raw in records:
        normalize_game(raw, season=2005, season_type=raw["seasonType"])
        for tr in team_rows_from_game(raw):
            team_rows[tr.id] = tr
    _write_teams(conn, team_rows, 2005)
    conn.commit()
    return conn


def test_enrichment_populates_mascot_and_alternate_names(
    empty_schema_db: Path, cached_teams_dir: Path, no_network: list[object]
) -> None:
    conn = _db_with_games_derived_teams(empty_schema_db)
    try:
        result = enrich_team_aliases(conn, raw_dir=cached_teams_dir)

        assert result.fetched_live is False
        assert no_network == []
        assert result.rows_updated >= 5

        texas = conn.execute(
            "SELECT school, mascot, alternate_names FROM teams WHERE school = 'Texas'"
        ).fetchone()
        assert texas["school"] == "Texas"
        assert texas["mascot"] == "Longhorns"
        assert json.loads(texas["alternate_names"]) == ["TEX", "Texas"]

        usc = conn.execute("SELECT mascot FROM teams WHERE school = 'USC'").fetchone()
        assert usc["mascot"] == "Trojans"
    finally:
        conn.close()


def test_team_without_mascot_ingests_with_null_mascot(
    empty_schema_db: Path, cached_teams_dir: Path, no_network: list[object]
) -> None:
    """Two real shapes of "no mascot", neither of which may raise:
    (a) Morgan State -- present in /games, absent from this /teams payload;
    (b) Cal State Northridge -- present in /teams with `mascot: null`."""
    conn = _db_with_games_derived_teams(empty_schema_db)
    try:
        northridge = team_row_from_cfbd_team(_record("Cal State Northridge"))
        _write_teams(conn, {northridge.id: northridge}, 2005)
        conn.commit()

        enrich_team_aliases(conn, raw_dir=cached_teams_dir)

        morgan = conn.execute(
            "SELECT school, mascot, alternate_names FROM teams WHERE school = 'Morgan State'"
        ).fetchone()
        assert morgan is not None, "an unmatched team must not be deleted"
        assert morgan["mascot"] is None

        csun = conn.execute(
            "SELECT school, mascot FROM teams WHERE school = 'Cal State Northridge'"
        ).fetchone()
        assert csun is not None
        assert csun["mascot"] is None
    finally:
        conn.close()


def test_enrichment_does_not_insert_teams_that_never_appeared_in_games(
    empty_schema_db: Path, cached_teams_dir: Path, no_network: list[object]
) -> None:
    """This is an enrichment of teams /games discovered, not a second source
    of team rows -- inserting all 1933 /teams records would put unrated,
    never-played teams into the picker's universe."""
    conn = _db_with_games_derived_teams(empty_schema_db)
    try:
        before = conn.execute("SELECT COUNT(*) AS c FROM teams").fetchone()["c"]

        enrich_team_aliases(conn, raw_dir=cached_teams_dir)

        after = conn.execute("SELECT COUNT(*) AS c FROM teams").fetchone()["c"]
        assert after == before
        for never_played in ("Avila University", "Alma", "Albany State", "NC State"):
            row = conn.execute("SELECT id FROM teams WHERE school = ?", (never_played,)).fetchone()
            assert row is None, f"{never_played} was inserted but never played a fixture game"
    finally:
        conn.close()


def test_reingest_is_idempotent_and_preserves_school(
    empty_schema_db: Path, cached_teams_dir: Path, no_network: list[object]
) -> None:
    conn = _db_with_games_derived_teams(empty_schema_db)
    try:
        schools_before = sorted(
            r["school"] for r in conn.execute("SELECT school FROM teams").fetchall()
        )

        first = enrich_team_aliases(conn, raw_dir=cached_teams_dir)
        snapshot_one = sorted(
            tuple(r) for r in conn.execute("SELECT id, school, mascot, alternate_names FROM teams")
        )
        second = enrich_team_aliases(conn, raw_dir=cached_teams_dir)
        snapshot_two = sorted(
            tuple(r) for r in conn.execute("SELECT id, school, mascot, alternate_names FROM teams")
        )

        assert first.rows_updated == second.rows_updated
        assert snapshot_one == snapshot_two
        # One row per team, and `school` -- the canonical identity string the
        # verdict lookup/grounding check/narration cache all key on -- is
        # byte-for-byte unchanged.
        schools_after = sorted(
            r["school"] for r in conn.execute("SELECT school FROM teams").fetchall()
        )
        assert schools_after == schools_before
        assert len(schools_after) == len(set(schools_after))
    finally:
        conn.close()


def test_enrichment_does_not_overwrite_historical_conference_or_classification(
    empty_schema_db: Path, cached_teams_dir: Path, no_network: list[object]
) -> None:
    """The year-independent /teams payload carries present-day affiliation
    (Texas: "SEC"), while `team_season` holds the historical, per-year value
    the ratings depend on (Texas in 2005: "Big 12"). Enrichment writes mascot
    and alternate_names only, so realignment can never rewrite history here."""
    conn = _db_with_games_derived_teams(empty_schema_db)
    try:
        assert _record("Texas")["conference"] == "SEC"
        before = conn.execute(
            "SELECT ts.conference, ts.classification, t.classification AS team_class "
            "FROM team_season ts JOIN teams t ON t.id = ts.team_id "
            "WHERE t.school = 'Texas' AND ts.year = 2005"
        ).fetchone()
        assert before["conference"] == "Big 12"

        enrich_team_aliases(conn, raw_dir=cached_teams_dir)

        after = conn.execute(
            "SELECT ts.conference, ts.classification, t.classification AS team_class "
            "FROM team_season ts JOIN teams t ON t.id = ts.team_id "
            "WHERE t.school = 'Texas' AND ts.year = 2005"
        ).fetchone()
        assert tuple(after) == tuple(before)
        assert after["conference"] == "Big 12"
    finally:
        conn.close()


def test_enrichment_leaves_nfl_rows_alone(
    empty_schema_db: Path, cached_teams_dir: Path, no_network: list[object]
) -> None:
    """A CFB `/teams` payload must not reach into the NFL rows sharing this
    db -- nflverse `school` is already the full "New England Patriots"
    string, so it needs no alias data at all."""
    conn = _db_with_games_derived_teams(empty_schema_db)
    try:
        conn.execute(
            "INSERT INTO teams (id, school, classification, sport, source_id) "
            "VALUES (9000001, 'Texas', 'nfl', 'nfl', 'TEXNFL')"
        )
        conn.commit()

        enrich_team_aliases(conn, raw_dir=cached_teams_dir)

        nfl_row = conn.execute(
            "SELECT mascot, alternate_names FROM teams WHERE id = 9000001"
        ).fetchone()
        assert nfl_row["mascot"] is None
        assert nfl_row["alternate_names"] is None
    finally:
        conn.close()


def test_two_teams_rows_sharing_one_school_both_get_the_aliases(
    empty_schema_db: Path, cached_teams_dir: Path, no_network: list[object]
) -> None:
    """Two `teams` rows can share one school string. CFBD's `/games` payloads
    give "Charlotte" two ids: 2429 (the 49ers, 149 games) and 3253 (the
    Charlotte Saints / "Faith NC", 1 game), which is a genuinely different
    program (#91). Edward Waters also had a second row once, but that came from
    a duplicate game record and is no longer minted (#125). A school-keyed
    UPDATE gives both rows the same mascot. For 3253 that is the 49ers'
    mascot, which is harmless while 3253 is unrated (#91). What the UPDATE
    must not do is insert, drop, or renumber either row.
    """
    conn = _db_with_games_derived_teams(empty_schema_db)
    try:
        second_texas = TeamRow(id=999251, school="Texas", classification=None, conference=None)
        _write_teams(conn, {second_texas.id: second_texas}, 2005)
        conn.commit()

        enrich_team_aliases(conn, raw_dir=cached_teams_dir)

        rows = conn.execute(
            "SELECT id, school, mascot FROM teams WHERE school = 'Texas' ORDER BY id"
        ).fetchall()
        assert [r["id"] for r in rows] == [251, 999251]
        assert [r["mascot"] for r in rows] == ["Longhorns", "Longhorns"]
    finally:
        conn.close()


def test_enrichment_reports_a_clear_error_without_cache_or_key(
    empty_schema_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(client_module, "CFBD_API_KEY", None)
    conn = _db_with_games_derived_teams(empty_schema_db)
    try:
        with pytest.raises(CFBDClientError):
            enrich_team_aliases(conn, raw_dir=tmp_path / "nonexistent")
    finally:
        conn.close()


def test_committed_teams_cache_exists_and_covers_the_stored_schools() -> None:
    """The production build runs `uv run cfb ingest --years 1998-2025` against
    committed cache and must make zero live API calls, so data/raw/teams.json
    is a committed artifact, not something a deploy fetches."""
    from cfb_strength.config import RAW_DIR

    cache_file = teams_cache_path(RAW_DIR)
    assert cache_file.exists(), f"{cache_file} must be committed for a zero-live-call build"

    records: list[dict[str, Any]] = json.loads(cache_file.read_text())
    assert len(records) > 1800, "expected the year-independent (~1933 record) /teams payload"

    rows = team_rows_from_cfbd_teams(records)
    for school, mascot in (
        ("Texas", "Longhorns"),
        ("Ohio State", "Buckeyes"),
        ("Miami (OH)", "RedHawks"),
        ("Miami", "Hurricanes"),
        ("NC State", "Wolfpack"),
        ("San José State", "Spartans"),
        ("Alma", "Scots"),
        ("Albany State", "Golden Rams"),
    ):
        assert rows[school].mascot == mascot
