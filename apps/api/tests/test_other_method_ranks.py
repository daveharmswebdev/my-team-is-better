"""Issue #155: every verdict envelope says where each other rating method
ranks the team(s) it is about.

`TeamCaseEnvelope.other_method_ranks` and `ComparisonEnvelope`'s
`team_a_other_method_ranks`/`team_b_other_method_ranks` hold one
`{method, rank}` per registered method (`contracts.Method`, in its declared
order) other than the one that answered, for which the `ratings` table has a
row for that year, sport and team. A method with no row is left out. Rank
only, never rating: the methods' ratings are on different scales.

The field is composed by the route around the narration, never handed to the
persona layer, so the narrator's input and the narration cache key do not
change (the last test here).

The committed fixture db rates keener and elo for its seven seasons and has
no elo_career rows at all, which is the "no row, left out" case. Every
expected rank below is also read back from the `ratings` table in the test,
so the assertions hold the API to the table rather than to a copied number.
Texas 2005 and Penn State 2005 are both covered with assertions of the same
shape; the test makes no distinction between their two pairs of ranks.
"""

from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any, get_args

import pytest
from cfb_strength import contracts
from cfb_strength.db.connection import get_conn
from fastapi.testclient import TestClient
from fixtures.narrator_fake import FakeNarrator

from api.config import PROMPT_VERSION, TEAM_NARRATOR_MODEL
from api.deps import get_db_conn, get_narration_cache, get_narrator
from api.main import app
from api.models import TeamCaseOut
from api.persona.cache import InMemoryNarrationCache, cache_key
from api.persona.claims import GROUNDING_VERSION
from api.persona.service import team_case_fact_block_json

FIXTURE_DB = Path(__file__).parent / "fixtures" / "cfb_verdict_fixture.sqlite3"
METHOD_ORDER: tuple[contracts.Method, ...] = get_args(contracts.Method)


def _table_rank(db: Path, year: int, school: str, method: str) -> int | None:
    """`ratings.rank` for one team, method and season, straight from the db."""
    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            """
            SELECT r.rank FROM ratings r JOIN teams t ON t.id = r.team_id
            WHERE r.year = ? AND t.school = ? AND r.method = ? AND r.sport = 'cfb'
              AND t.sport = 'cfb'
            """,
            (year, school, method),
        ).fetchone()
    finally:
        conn.close()
    return None if row is None else int(row[0])


def _expected(db: Path, year: int, school: str, answering: str) -> list[dict[str, Any]]:
    """What the field must hold, derived from the table: every other method in
    `contracts.Method` order that has a row."""
    expected: list[dict[str, Any]] = []
    for method in METHOD_ORDER:
        if method == answering:
            continue
        rank = _table_rank(db, year, school, method)
        if rank is not None:
            expected.append({"method": method, "rank": rank})
    return expected


# ---------------------------------------------------------------------------
# the fixture's own facts the tests below lean on
# ---------------------------------------------------------------------------


def test_fixture_has_no_elo_career_rows() -> None:
    conn = sqlite3.connect(FIXTURE_DB)
    try:
        (count,) = conn.execute(
            "SELECT COUNT(*) FROM ratings WHERE method = 'elo_career'"
        ).fetchone()
    finally:
        conn.close()
    assert count == 0


# ---------------------------------------------------------------------------
# /team-case
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("team", "method", "literal"),
    [
        ("Penn State", "keener", [{"method": "elo", "rank": 6}]),
        ("Penn State", "elo", [{"method": "keener", "rank": 3}]),
        ("Texas", "keener", [{"method": "elo", "rank": 1}]),
        ("Texas", "elo", [{"method": "keener", "rank": 1}]),
    ],
)
def test_team_case_carries_other_method_ranks(
    client: TestClient, team: str, method: str, literal: list[dict[str, Any]]
) -> None:
    response = client.post(
        "/api/verdict/team-case", json={"year": 2005, "team": team, "method": method}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["evidence"]["team_name"] == team
    assert body["other_method_ranks"] == _expected(FIXTURE_DB, 2005, team, method)
    assert body["other_method_ranks"] == literal


@pytest.mark.parametrize("method", ["keener", "elo"])
def test_answering_method_is_never_listed(client: TestClient, method: str) -> None:
    response = client.post(
        "/api/verdict/team-case", json={"year": 2005, "team": "Penn State", "method": method}
    )

    assert response.status_code == 200, response.text
    listed = [entry["method"] for entry in response.json()["other_method_ranks"]]
    assert method not in listed


def test_method_without_a_row_is_omitted(client: TestClient) -> None:
    response = client.post("/api/verdict/team-case", json={"year": 2005, "team": "Penn State"})

    assert response.status_code == 200, response.text
    listed = [entry["method"] for entry in response.json()["other_method_ranks"]]
    assert "elo_career" not in listed


def test_entries_carry_rank_and_method_only(client: TestClient) -> None:
    response = client.post("/api/verdict/team-case", json={"year": 2005, "team": "Penn State"})

    assert response.status_code == 200, response.text
    for entry in response.json()["other_method_ranks"]:
        assert set(entry) == {"method", "rank"}


# ---------------------------------------------------------------------------
# /champion
# ---------------------------------------------------------------------------


def test_champion_carries_other_method_ranks(client: TestClient) -> None:
    response = client.post("/api/verdict/champion", json={"year": 2005, "method": "keener"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["evidence"]["team_name"] == "Texas"
    assert body["other_method_ranks"] == _expected(FIXTURE_DB, 2005, "Texas", "keener")
    assert body["other_method_ranks"] == [{"method": "elo", "rank": 1}]


# ---------------------------------------------------------------------------
# /compare
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["keener", "elo"])
def test_compare_carries_each_sides_other_method_ranks(client: TestClient, method: str) -> None:
    response = client.post(
        "/api/verdict/compare",
        json={"year": 2005, "team_a": "Texas", "team_b": "Penn State", "method": method},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["evidence"]["team_a"]["team_name"] == "Texas"
    assert body["evidence"]["team_b"]["team_name"] == "Penn State"
    assert body["team_a_other_method_ranks"] == _expected(FIXTURE_DB, 2005, "Texas", method)
    assert body["team_b_other_method_ranks"] == _expected(FIXTURE_DB, 2005, "Penn State", method)


def test_compare_literal_ranks_under_keener(client: TestClient) -> None:
    response = client.post(
        "/api/verdict/compare",
        json={"year": 2005, "team_a": "Texas", "team_b": "Penn State"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["team_a_other_method_ranks"] == [{"method": "elo", "rank": 1}]
    assert body["team_b_other_method_ranks"] == [{"method": "elo", "rank": 6}]


# ---------------------------------------------------------------------------
# order follows contracts.Method, on a db that rates all three methods
# ---------------------------------------------------------------------------


@pytest.fixture
def three_method_db(tmp_path: Path) -> Path:
    """A copy of the fixture db with an elo_career row added for every 2005
    elo row (rank shifted by 10, so it is distinguishable from elo's)."""
    db = tmp_path / "three_methods.sqlite3"
    shutil.copyfile(FIXTURE_DB, db)
    conn = sqlite3.connect(db)
    try:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(ratings)")]
        selected = [
            "'elo_career'" if c == "method" else ("rank + 10" if c == "rank" else c)
            for c in columns
            if c != "id"
        ]
        inserted = [c for c in columns if c != "id"]
        conn.execute(
            f"INSERT INTO ratings ({', '.join(inserted)}) "
            f"SELECT {', '.join(selected)} FROM ratings WHERE method = 'elo' AND year = 2005"
        )
        conn.commit()
    finally:
        conn.close()
    return db


@pytest.fixture
def three_method_client(three_method_db: Path) -> Iterator[TestClient]:
    def _override() -> Iterator[sqlite3.Connection]:
        conn = get_conn(three_method_db, read_only=True)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db_conn] = _override
    app.dependency_overrides[get_narration_cache] = lambda: InMemoryNarrationCache()
    app.dependency_overrides[get_narrator] = lambda: FakeNarrator()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db_conn, None)
        app.dependency_overrides.pop(get_narration_cache, None)
        app.dependency_overrides.pop(get_narrator, None)


def test_route_lists_every_other_method_with_a_row_in_contract_order(
    three_method_client: TestClient, three_method_db: Path
) -> None:
    response = three_method_client.post(
        "/api/verdict/team-case", json={"year": 2005, "team": "Penn State", "method": "keener"}
    )

    assert response.status_code == 200, response.text
    ranks = response.json()["other_method_ranks"]
    assert ranks == _expected(three_method_db, 2005, "Penn State", "keener")
    assert ranks == [{"method": "elo", "rank": 6}, {"method": "elo_career", "rank": 16}]


@pytest.mark.parametrize("answering", METHOD_ORDER)
def test_query_orders_by_contract_method_order(
    three_method_db: Path, answering: contracts.Method
) -> None:
    """The query helper directly, for each answering method, including
    elo_career, which no route can answer on this db (it holds no elo_career
    ledger). With elo_career answering, contract order is keener then elo,
    the reverse of alphabetical."""
    from api.repositories.ratings import other_method_ranks

    conn = get_conn(three_method_db, read_only=True)
    try:
        (team_id,) = conn.execute(
            "SELECT id FROM teams WHERE school = 'Penn State' AND sport = 'cfb'"
        ).fetchone()
        ranks = other_method_ranks(
            conn, year=2005, sport="cfb", team_id=int(team_id), method=answering
        )
    finally:
        conn.close()

    got = [entry.model_dump() for entry in ranks]
    assert got == _expected(three_method_db, 2005, "Penn State", answering)
    assert [entry["method"] for entry in got] == [m for m in METHOD_ORDER if m != answering]


# ---------------------------------------------------------------------------
# the persona never sees it
# ---------------------------------------------------------------------------


def test_narrator_input_and_cache_key_do_not_carry_other_method_ranks(client: TestClient) -> None:
    """The narrator gets the evidence fact block and nothing composed beside
    it, and the narration is cached under the key the fact block alone
    determines (the same `cache_key` the persona golden tests compute)."""
    narrator = FakeNarrator()
    cache = InMemoryNarrationCache()
    app.dependency_overrides[get_narration_cache] = lambda: cache
    app.dependency_overrides[get_narrator] = lambda: narrator
    try:
        response = client.post("/api/verdict/team-case", json={"year": 2005, "team": "Penn State"})
    finally:
        app.dependency_overrides.pop(get_narration_cache, None)
        app.dependency_overrides.pop(get_narrator, None)

    assert response.status_code == 200, response.text
    assert response.json()["other_method_ranks"]

    assert len(narrator.calls) == 1
    call = narrator.calls[0]
    assert "other_method_ranks" not in call.system
    assert all("other_method_ranks" not in text for text in call.user_texts)

    case = TeamCaseOut.model_validate(response.json()["evidence"])
    fact_block = team_case_fact_block_json(case)
    assert "other_method_ranks" not in fact_block
    assert any(fact_block in text for text in call.user_texts)

    key = cache_key(
        question_type="team_case",
        year=2005,
        teams=("Penn State",),
        user_team=None,
        method="keener",
        sport="cfb",
        prompt_version=PROMPT_VERSION,
        fact_block_json=fact_block,
        grounding_version=GROUNDING_VERSION,
        model=TEAM_NARRATOR_MODEL,
    )
    assert cache.get(key) is not None
