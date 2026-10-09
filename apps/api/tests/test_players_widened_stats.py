"""The widened player stat contract as apps/api sees it (#313, #354, epic #311).

`contracts.PlayerStats` went from 10 stat columns to 34 (#313), then to 42
(#354: five defensive columns and three EPA columns), and the committed
fixture was rebuilt through the widened nflverse ingest each time. This
module pins the behavioural changes that came with the widening, so that
none can regress silently. Since #315 the API (`PlayerStatsOut`) publishes
28 of the contract's stats; the fourteen it leaves out are pinned below.

1. Sign convention (#298). `sack_yards_lost` is stored and published
   POSITIVE. It used to be negative, and every consumer -- the career page,
   the compare page, #315's boards -- reads it straight through, so the sign
   is asserted here through the HTTP layer on measured anchors, not just at
   the db.

2. Maxima, not totals. `fg_long` and `pt_long` are season maxima
   (`contracts.PLAYER_STAT_MAX_FIELDS`) and are NULL for anyone who never
   kicked or punted -- never 0. A quarterback's row is the check: 0 would
   read as "his longest field goal was zero yards", and any renderer that
   coerces NULL to 0 would publish that. They are asserted against the
   fixture db directly and, since #315 publishes them, through HTTP too.

3. Stored, not published (#354). The five defensive columns and three EPA
   columns are in the fixture's `player_season_stats` -- `def_sacks` and the
   EPA columns as REAL, because a shared sack is 0.5 and EPA is fractional
   (`contracts.PLAYER_STAT_REAL_FIELDS`) -- and no player endpoint publishes
   any of them yet (#317 for defense, #347 for EPA). Values are pinned on
   season rows of the fixture db only: a career EPA total is the engine's
   to compute (`contracts.PLAYER_STAT_SPARSE_FIELDS`), and no published
   field carries one.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from fixtures.player_api_fixture import (
    DEFENSE_STATS,
    EPA_STATS,
    PUBLISHED_STAT_NAMES,
    PUBLISHED_STATS,
    STAT_NAMES,
    UNPUBLISHED_STATS,
    fixture_conn,
    stats_body,
)

KURT_WARNER = 2044124519
PATRICK_MAHOMES = 2319407936

# (player, season, season_type, sacks_suffered, sack_yards_lost), measured on
# the rebuilt fixture. The yards were negative before #298.
SACK_ANCHORS = [
    (KURT_WARNER, 1999, "regular", 26, 176),
    (KURT_WARNER, 1999, "postseason", 4, 24),
    (PATRICK_MAHOMES, 2023, "regular", 27, 186),
]

MAX_FIELDS = ("fg_long", "pt_long")


def _season_stats(client: TestClient, player_id: int, season: int, season_type: str) -> Any:
    response = client.get(f"/api/players/{player_id}")
    assert response.status_code == 200, response.text
    lines = [
        line
        for line in response.json()["seasons"]
        if line["season"] == season and line["season_type"] == season_type
    ]
    assert len(lines) == 1, lines
    return lines[0]["stats"]


@pytest.mark.parametrize("player_id,season,season_type,sacks,yards", SACK_ANCHORS)
def test_sack_yards_lost_is_published_positive(
    client: TestClient,
    player_id: int,
    season: int,
    season_type: str,
    sacks: int,
    yards: int,
) -> None:
    stats = _season_stats(client, player_id, season, season_type)

    assert (stats["sacks_suffered"], stats["sack_yards_lost"]) == (sacks, yards)


def test_career_totals_carry_the_positive_sack_yards(client: TestClient) -> None:
    response = client.get(f"/api/players/{KURT_WARNER}")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["regular_season"]["stats"]["sack_yards_lost"] == 176
    assert body["postseason"]["stats"]["sack_yards_lost"] == 24


def test_no_fixture_row_stores_a_negative_sack_yards_lost() -> None:
    with fixture_conn() as conn:
        negative = conn.execute(
            "SELECT COUNT(*) FROM player_season_stats WHERE sack_yards_lost < 0"
        ).fetchone()[0]
        populated = conn.execute(
            "SELECT COUNT(*) FROM player_season_stats WHERE sack_yards_lost > 0"
        ).fetchone()[0]

    assert negative == 0
    assert populated > 0, "no populated sack yards at all would make the sign check vacuous"


def test_the_fixture_carries_every_contract_stat_column() -> None:
    with fixture_conn() as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(player_season_stats)")}

    assert len(STAT_NAMES) == 42
    assert set(STAT_NAMES) <= columns


@pytest.mark.parametrize("field", MAX_FIELDS)
def test_a_quarterbacks_season_maximum_is_null_never_zero(field: str) -> None:
    """`fg_long`/`pt_long` are maxima: not applicable reads as NULL."""
    with fixture_conn() as conn:
        position, value = conn.execute(
            f"SELECT p.position, s.{field} FROM player_season_stats s "
            "JOIN players p ON p.id = s.player_id "
            "WHERE s.player_id = ? AND s.season = 1999 AND s.season_type = 'regular'",
            (KURT_WARNER,),
        ).fetchone()

    assert position == "QB"
    assert value is None


@pytest.mark.parametrize("field", MAX_FIELDS)
def test_no_season_maximum_is_stored_as_zero(field: str) -> None:
    with fixture_conn() as conn:
        zeros, nulls, populated = conn.execute(
            f"SELECT SUM({field} = 0), SUM({field} IS NULL), SUM({field} > 0) "
            "FROM player_season_stats"
        ).fetchone()

    assert zeros == 0, f"{field} is a maximum; 'not applicable' must be NULL, not 0"
    assert nulls > 0
    assert populated > 0, f"no populated {field} would make this check vacuous"


# ---------------------------------------------------------------------------
# `stats_body`, the expected-body helper the compare test builds its four
# measured games with. It replaced a positional `_stats(*values)` that
# asserted its arity against the live contract and so broke the moment
# `PlayerStats` widened. Naming is only safe if a wrong name is loud.
# ---------------------------------------------------------------------------


def test_stats_body_fills_unnamed_published_stats_with_none() -> None:
    named = {"completions": 29, "attempts": 46}
    body = stats_body(**named)

    assert set(body) == set(PUBLISHED_STAT_NAMES)
    assert {name: body[name] for name in named} == named
    assert body["rushing_tds"] is None, "a stat with no value is not applicable, never 0"
    assert [name for name, value in body.items() if value is None] == [
        name for name in PUBLISHED_STAT_NAMES if name not in named
    ]


def test_stats_body_rejects_a_name_that_is_not_a_stat() -> None:
    with pytest.raises(ValueError, match="'passing_yardz' is not a PlayerStats field"):
        stats_body(passing_yardz=328)


def test_the_contract_stats_the_api_leaves_out() -> None:
    """Since #315 the API publishes every contract stat but these: the two
    rushing columns #313 added and nothing has published yet, the 0-49
    yard field-goal buckets, which #315 leaves out deliberately, and
    #354's five defensive and three EPA columns (#317, #347). Both sides
    are literals, so neither a dropped nor an added field can hide."""
    assert len(UNPUBLISHED_STATS) == 14
    assert [name for name in STAT_NAMES if name not in PUBLISHED_STAT_NAMES] == list(
        UNPUBLISHED_STATS
    )
    assert [name for name in STAT_NAMES if name not in UNPUBLISHED_STATS] == list(PUBLISHED_STATS)


@pytest.mark.parametrize("name", UNPUBLISHED_STATS)
def test_stats_body_rejects_a_stat_the_api_does_not_publish(name: str) -> None:
    assert name in STAT_NAMES and name not in PUBLISHED_STAT_NAMES
    with pytest.raises(ValueError, match="does not publish"):
        stats_body(**{name: 4})


def test_stats_body_accepts_the_kicking_and_punting_stats() -> None:
    body = stats_body(fg_made=36, fg_made_60_=1, pt_att=99)

    assert (body["fg_made"], body["fg_made_60_"], body["pt_att"], body["fg_long"]) == (
        36,
        1,
        99,
        None,
    )


@pytest.mark.parametrize("field", MAX_FIELDS)
def test_a_quarterbacks_maximum_is_published_as_null(client: TestClient, field: str) -> None:
    """The HTTP half of the check below (#315): Kurt Warner's 1999 line and
    his career totals publish `fg_long`/`pt_long` as JSON null, not 0."""
    response = client.get(f"/api/players/{KURT_WARNER}")
    assert response.status_code == 200, response.text
    assert f'"{field}":0' not in response.text
    body = response.json()

    season = _season_stats(client, KURT_WARNER, 1999, "regular")
    assert field in season and season[field] is None
    totals = body["regular_season"]["stats"]
    assert field in totals and totals[field] is None


def test_stats_body_accepts_the_receiving_stats() -> None:
    body = stats_body(receptions=4, targets=6)

    assert (body["receptions"], body["targets"], body["receiving_yards"]) == (4, 6, None)


# ---------------------------------------------------------------------------
# #354: five defensive and three EPA columns, stored but not published.
# ---------------------------------------------------------------------------

T_J_WATT = 2459036925
DARON_BLAND = 2211547534
KEVIN_CARTER = 2003451235
TREY_HENDRICKSON = 2125290444

NEW_STATS = (*DEFENSE_STATS, *EPA_STATS)

# (player, season, season_type, column, value), measured on the rebuilt
# fixture; Watt's and Bland's agree with the raw nflverse weekly files.
# 1999 is the season nflverse undercounts: Kevin Carter's official total is
# 17 sacks, and the fixture reproduces nflverse's 15 faithfully. A sack
# split between two rushers is 0.5 each, hence Hendrickson's 17.5.
DEFENSE_ANCHORS = [
    (T_J_WATT, 2023, "regular", "def_sacks", 19.0),
    (DARON_BLAND, 2023, "regular", "def_interceptions", 9),
    (DARON_BLAND, 2023, "regular", "def_pass_defended", 15),
    (KEVIN_CARTER, 1999, "regular", "def_sacks", 15.0),
    (TREY_HENDRICKSON, 2023, "regular", "def_sacks", 17.5),
]

# Season-row EPA, never a career total (see the module docstring).
EPA_ANCHORS = [
    (KURT_WARNER, 1999, "regular", "passing_epa", 163.010521898648),
    (PATRICK_MAHOMES, 2023, "regular", "rushing_epa", 13.3321867141371),
]


def _season_value(player_id: int, season: int, season_type: str, column: str) -> Any:
    with fixture_conn() as conn:
        rows = conn.execute(
            f"SELECT {column} FROM player_season_stats "
            "WHERE player_id = ? AND season = ? AND season_type = ? AND sport = 'nfl'",
            (player_id, season, season_type),
        ).fetchall()
    assert len(rows) == 1, rows
    return rows[0][0]


def test_the_fixture_stores_the_defense_and_epa_columns_with_their_types() -> None:
    with fixture_conn() as conn:
        types = {row[1]: row[2] for row in conn.execute("PRAGMA table_info(player_season_stats)")}

    assert {name: types.get(name) for name in NEW_STATS} == {
        "def_interceptions": "INTEGER",
        "def_sacks": "REAL",
        "def_fumbles_forced": "INTEGER",
        "def_tackles_solo": "INTEGER",
        "def_pass_defended": "INTEGER",
        "passing_epa": "REAL",
        "rushing_epa": "REAL",
        "receiving_epa": "REAL",
    }


def test_the_fixture_holds_half_sacks_and_epa_values() -> None:
    """The REAL columns are not vacuous: a fractional sack total survives
    storage (an int() parse would have truncated or rejected it), and every
    EPA column holds values, every one stored as an SQLite real."""
    with fixture_conn() as conn:
        fractional_sacks = conn.execute(
            "SELECT COUNT(*) FROM player_season_stats WHERE def_sacks <> CAST(def_sacks AS INTEGER)"
        ).fetchone()[0]
        epa = {
            name: conn.execute(
                f"SELECT COUNT(*), SUM(typeof({name}) = 'real') FROM player_season_stats "
                f"WHERE {name} IS NOT NULL"
            ).fetchone()
            for name in EPA_STATS
        }

    assert fractional_sacks > 0
    for name, (populated, reals) in epa.items():
        assert populated > 0, f"no populated {name} would make the REAL check vacuous"
        assert reals == populated, name


@pytest.mark.parametrize("player_id,season,season_type,column,value", DEFENSE_ANCHORS)
def test_defense_season_rows_reproduce_nflverse(
    player_id: int, season: int, season_type: str, column: str, value: float
) -> None:
    stored = _season_value(player_id, season, season_type, column)

    assert stored == value
    assert type(stored) is type(value)


@pytest.mark.parametrize("player_id,season,season_type,column,value", EPA_ANCHORS)
def test_epa_season_rows_are_stored(
    player_id: int, season: int, season_type: str, column: str, value: float
) -> None:
    stored = _season_value(player_id, season, season_type, column)

    assert stored == pytest.approx(value, abs=1e-9)


def _keys(value: Any) -> set[str]:
    """Every object key anywhere in a JSON body."""
    if isinstance(value, dict):
        return set(value).union(*(_keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(_keys(item) for item in value))
    return set()


def _stats_objects(value: Any) -> list[Any]:
    """Every `stats` object anywhere in a JSON body."""
    if isinstance(value, dict):
        found = [value["stats"]] if isinstance(value.get("stats"), dict) else []
        return found + [obj for item in value.values() for obj in _stats_objects(item)]
    if isinstance(value, list):
        return [obj for item in value for obj in _stats_objects(item)]
    return []


def test_no_player_endpoint_publishes_the_defense_or_epa_columns(client: TestClient) -> None:
    """#354 stores eight columns the API does not publish yet. Every player
    endpoint -- every leaders board, the career page of a quarterback and of
    three defenders, compare, search -- answers without any of their names,
    and every stats object carries exactly the literal `PUBLISHED_STATS`,
    unchanged by the widening."""
    assert set(PUBLISHED_STATS).isdisjoint(NEW_STATS)

    bodies: list[Any] = []

    def get(path: str, **params: str | int) -> Any:
        response = client.get(path, params=params)
        assert response.status_code == 200, response.text
        bodies.append(response.json())
        return response.json()

    for category in ("passing", "rushing", "receiving", "kicking", "punting"):
        for season_type in ("regular", "postseason"):
            get("/api/players/leaders", category=category, season_type=season_type, limit=5)
    for player_id in (KURT_WARNER, T_J_WATT, DARON_BLAND, KEVIN_CARTER):
        get(f"/api/players/{player_id}")
    get("/api/players/compare", a=KURT_WARNER, b=PATRICK_MAHOMES)
    # Search lists only players who qualify for a leaderboard, and no board
    # ranks defense yet (#317), so a pure defender is not found; search a
    # quarterback instead.
    search = get("/api/players/search", q="Warner")
    assert KURT_WARNER in {row["player_id"] for row in search["rows"]}

    stats_objects = _stats_objects(bodies)
    assert len(stats_objects) > 10 * 5
    for body in bodies:
        assert _keys(body).isdisjoint(NEW_STATS)
    for stats in stats_objects:
        assert list(stats) == list(PUBLISHED_STATS)
