"""The widened player stat contract as apps/api sees it (#313, #354, epic #311).

`contracts.PlayerStats` went from 10 stat columns to 34 (#313), then to 42
(#354: five defensive columns and three EPA columns), and the committed
fixture was rebuilt through the widened nflverse ingest each time. This
module pins the behavioural changes that came with the widening, so that
none can regress silently. Since #347 the API (`PlayerStatsOut`) publishes
37 of the contract's stats; the five it leaves out are pinned below.

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

3. Defense stored and published, EPA partly published (#354, #317, #347). The five
   defensive columns and three EPA columns are in the fixture's
   `player_season_stats` -- `def_sacks` and the EPA columns as REAL, because
   a shared sack is 0.5 and EPA is fractional
   (`contracts.PLAYER_STAT_REAL_FIELDS`). #354 stored all eight and
   published none. #317 published the five defensive ones on every player
   endpoint, mapped 1:1 from the engine: the same season anchors now hold
   through HTTP, `def_sacks` as a JSON float (17.5 stays 17.5), and a
   quarterback's defensive line publishes whatever the engine returns.
   #347 publishes `passing_epa` and `rushing_epa`, 1:1 and unrounded, the
   career sums being the engine's (`contracts.PLAYER_STAT_SPARSE_FIELDS`);
   `receiving_epa` stays unpublished (#484: NULL for 2003-2008, so a career
   sum would cover tracked seasons only). The season-row values are pinned
   at the fixture db and through HTTP.

4. Rushing first downs and fumbles lost published (#352). #313 added
   `rushing_first_downs` and `rushing_fumbles_lost` to the contract and the
   API deliberately left them out; the founder's call on #352 publishes
   both. They sit right after `rushing_tds`, are mapped 1:1 from the
   engine on every stats object (leaders rows, career lines and totals,
   compare careers and head-to-head game lines), and a NULL stays null.
   nflverse never leaves either blank for a player with a carry,
   1999-2025, so a published 0 is a real zero.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from cfb_strength.players import get_player_career
from fastapi.testclient import TestClient
from fixtures.player_api_fixture import (
    DEFENSE_STATS,
    EPA_STATS,
    PUBLISHED_EPA_STATS,
    PUBLISHED_STAT_NAMES,
    PUBLISHED_STATS,
    RUSHING_DETAIL_STATS,
    STAT_NAMES,
    UNPUBLISHED_EPA_STATS,
    UNPUBLISHED_STATS,
    client_for_db,
    engine_json,
    fixture_conn,
    make_player_db_with_null_stat,
    stats_body,
)

KURT_WARNER = 2044124519
FRED_WARNER = 2283364210
PATRICK_MAHOMES = 2319407936
STEVE_MCNAIR = 2385180619

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
    """Since #352 the API publishes every contract stat but these: the 0-49
    yard field-goal buckets, which #315 leaves out deliberately, and
    `receiving_epa` (#484). #347 published the other two EPA columns,
    #354's five defensive columns left
    this list when #317 published them, and the two rushing columns #313
    added left it when #352 published them. Both sides are literals, so
    neither a dropped nor an added field can hide."""
    assert len(UNPUBLISHED_STATS) == 5
    for published in (DEFENSE_STATS, RUSHING_DETAIL_STATS, PUBLISHED_EPA_STATS):
        assert set(published) <= set(PUBLISHED_STATS)
        assert set(published).isdisjoint(UNPUBLISHED_STATS)
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


def test_stats_body_accepts_the_defense_stats() -> None:
    """#317: published now, so an expectation may name them; a half sack is
    carried as given."""
    body = stats_body(def_sacks=0.5, def_tackles_solo=3)

    assert (body["def_sacks"], body["def_tackles_solo"], body["def_interceptions"]) == (
        0.5,
        3,
        None,
    )


def test_stats_body_accepts_the_rushing_detail_stats() -> None:
    """#352: published now, so an expectation may name them."""
    body = stats_body(rushing_first_downs=5, rushing_fumbles_lost=0)

    assert (body["rushing_first_downs"], body["rushing_fumbles_lost"], body["carries"]) == (
        5,
        0,
        None,
    )


def test_stats_body_accepts_the_receiving_stats() -> None:
    body = stats_body(receptions=4, targets=6)

    assert (body["receptions"], body["targets"], body["receiving_yards"]) == (4, 6, None)


# ---------------------------------------------------------------------------
# #354: five defensive and three EPA columns, stored. #317 publishes the
# defensive five; #347 publishes two of the EPA three, never receiving_epa.
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


@pytest.mark.parametrize("player_id,season,season_type,column,value", EPA_ANCHORS)
def test_epa_season_rows_are_published_as_stored(
    client: TestClient,
    player_id: int,
    season: int,
    season_type: str,
    column: str,
    value: float,
) -> None:
    """#347: the season line publishes the stored REAL exactly, unrounded."""
    stats = _season_stats(client, player_id, season, season_type)

    assert stats[column] == _season_value(player_id, season, season_type, column)
    assert stats[column] == pytest.approx(value, abs=1e-9)
    assert type(stats[column]) is float


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


def test_every_player_endpoint_publishes_defense_and_no_receiving_epa(
    client: TestClient,
) -> None:
    """#354 stored eight columns and published none; #317 publishes the five
    defensive ones and #347 `passing_epa` and `rushing_epa`. Every player
    endpoint -- every leaders board (defense and the EPA sorts included),
    the career page of a quarterback and of three defenders, compare,
    search -- answers without the name `receiving_epa` anywhere, and every
    stats object carries exactly the literal `PUBLISHED_STATS`, the five
    defensive stats and two EPA sums among them."""
    assert set(DEFENSE_STATS) <= set(PUBLISHED_STATS)
    assert set(PUBLISHED_EPA_STATS) <= set(PUBLISHED_STATS)
    assert set(PUBLISHED_STATS).isdisjoint(UNPUBLISHED_EPA_STATS)

    bodies: list[Any] = []

    def get(path: str, **params: str | int) -> Any:
        response = client.get(path, params=params)
        assert response.status_code == 200, response.text
        bodies.append(response.json())
        return response.json()

    for category in ("passing", "rushing", "receiving", "kicking", "punting", "defense"):
        for season_type in ("regular", "postseason"):
            get("/api/players/leaders", category=category, season_type=season_type, limit=5)
    for category, sort in (("passing", "epa_per_dropback"), ("rushing", "epa_per_carry")):
        for season_type in ("regular", "postseason"):
            get("/api/players/leaders", category=category, sort=sort, season_type=season_type)
    for player_id in (KURT_WARNER, T_J_WATT, DARON_BLAND, KEVIN_CARTER):
        get(f"/api/players/{player_id}")
    # Warner and McNair met twice in 1999 (#301), so compare has games to check.
    compare = get("/api/players/compare", a=KURT_WARNER, b=STEVE_MCNAIR)
    # Search rows carry no stats, so search is here only for the receiving_epa
    # check. Every board qualifies a player for search (#371), so "Warner"
    # finds the linebacker Fred Warner as well as the quarterback.
    search = get("/api/players/search", q="Warner")
    assert {FRED_WARNER, KURT_WARNER} <= {row["player_id"] for row in search["rows"]}

    stats_objects = _stats_objects(bodies)
    assert len(stats_objects) > 12 * 5
    for body in bodies:
        assert _keys(body).isdisjoint(UNPUBLISHED_EPA_STATS)
        assert "receiving_epa" not in str(body)
    for stats in stats_objects:
        assert list(stats) == list(PUBLISHED_STATS)
    # Compare's per-game sides are `a_stats`/`b_stats`, not `stats`.
    games = [
        game
        for key in ("regular_season_head_to_head", "postseason_head_to_head")
        for game in compare[key]["games"]
    ]
    assert len(games) == 2
    for game in games:
        assert list(game["a_stats"]) == list(game["b_stats"]) == list(PUBLISHED_STATS)


@pytest.mark.parametrize("player_id,season,season_type,column,value", DEFENSE_ANCHORS)
def test_defense_season_rows_are_published_as_stored(
    client: TestClient,
    player_id: int,
    season: int,
    season_type: str,
    column: str,
    value: float,
) -> None:
    """The same anchors as the db check above, through HTTP: the career
    page publishes each value 1:1, and `def_sacks` stays a float -- a
    half sack reaches JSON as 17.5, and Watt's 19 sacks as 19.0."""
    stats = _season_stats(client, player_id, season, season_type)

    assert stats[column] == value
    assert type(stats[column]) is type(value)


def test_a_defenders_career_publishes_his_five_stats(client: TestClient) -> None:
    """T.J. Watt's career (2023 only on the fixture), every defense stat."""
    response = client.get(f"/api/players/{T_J_WATT}")
    assert response.status_code == 200, response.text
    assert '"def_sacks":19.0' in response.text
    body = response.json()

    assert {name: body["regular_season"]["stats"][name] for name in DEFENSE_STATS} == {
        "def_interceptions": 1,
        "def_sacks": 19.0,
        "def_fumbles_forced": 4,
        "def_tackles_solo": 38,
        "def_pass_defended": 8,
    }
    assert body["postseason"] is None


def test_a_quarterbacks_defense_line_is_the_engines(client: TestClient) -> None:
    """Kurt Warner's 1999 defensive line publishes exactly what the engine
    returns: nflverse's recorded zeros, `def_sacks` as the float 0.0, and the
    one solo tackle he made in the regular season (after an interception,
    presumably). Nothing here is coerced -- a NULL would stay null, as
    `test_a_null_defense_stat_stays_null_and_unranked` checks on a copy."""
    with fixture_conn() as conn:
        engine = get_player_career(conn, sport="nfl", player_id=KURT_WARNER)
    body = client.get(f"/api/players/{KURT_WARNER}").json()

    assert engine.regular_season is not None and engine.postseason is not None
    for key, totals in (
        ("regular_season", engine.regular_season),
        ("postseason", engine.postseason),
    ):
        published = {name: body[key]["stats"][name] for name in DEFENSE_STATS}
        assert published == {name: getattr(totals.stats, name) for name in DEFENSE_STATS}
        assert type(published["def_sacks"]) is float
    assert {name: body["regular_season"]["stats"][name] for name in DEFENSE_STATS} == {
        "def_interceptions": 0,
        "def_sacks": 0.0,
        "def_fumbles_forced": 0,
        "def_tackles_solo": 1,
        "def_pass_defended": 0,
    }


# ---------------------------------------------------------------------------
# #352: `rushing_first_downs` and `rushing_fumbles_lost`, published.
# ---------------------------------------------------------------------------

EDDIE_GEORGE = 2464876093

# (player, season, season_type, rushing_first_downs, rushing_fumbles_lost),
# measured on the fixture's `player_season_stats`; McNair's regular season
# carries a real 0.
RUSHING_DETAIL_ANCHORS = [
    (KURT_WARNER, 1999, "regular", 5, 2),
    (KURT_WARNER, 1999, "postseason", 1, 1),
    (STEVE_MCNAIR, 1999, "regular", 34, 0),
    (STEVE_MCNAIR, 1999, "postseason", 16, 1),
    (EDDIE_GEORGE, 1999, "regular", 66, 4),
]


def _rushing_detail(stats: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(stats[name] for name in RUSHING_DETAIL_STATS)


def test_the_rushing_detail_stats_sit_after_rushing_tds() -> None:
    position = PUBLISHED_STATS.index("rushing_tds")
    assert PUBLISHED_STATS[position + 1 : position + 3] == RUSHING_DETAIL_STATS


@pytest.mark.parametrize(
    "player_id,season,season_type,first_downs,fumbles_lost", RUSHING_DETAIL_ANCHORS
)
def test_a_career_season_line_publishes_the_rushing_detail(
    client: TestClient,
    player_id: int,
    season: int,
    season_type: str,
    first_downs: int,
    fumbles_lost: int,
) -> None:
    stats = _season_stats(client, player_id, season, season_type)

    assert _rushing_detail(stats) == (first_downs, fumbles_lost)


def test_career_totals_publish_the_rushing_detail(client: TestClient) -> None:
    """The fixture holds Warner's and McNair's 1999 only, so each total is
    that one season's line; checked against the engine as well."""
    for player_id, regular, postseason in (
        (KURT_WARNER, (5, 2), (1, 1)),
        (STEVE_MCNAIR, (34, 0), (16, 1)),
    ):
        body = client.get(f"/api/players/{player_id}").json()
        with fixture_conn() as conn:
            engine = get_player_career(conn, sport="nfl", player_id=player_id)
        assert engine.regular_season is not None and engine.postseason is not None
        for key, totals, expected in (
            ("regular_season", engine.regular_season, regular),
            ("postseason", engine.postseason, postseason),
        ):
            published = _rushing_detail(body[key]["stats"])
            assert published == expected
            assert published == tuple(getattr(totals.stats, name) for name in RUSHING_DETAIL_STATS)


def test_a_rushing_leaders_row_publishes_the_rushing_detail(client: TestClient) -> None:
    """Eddie George's 1999 is his whole fixture career: 66 rushing first
    downs and 4 fumbles lost, on his rushing-board row."""
    response = client.get(
        "/api/players/leaders",
        params={"category": "rushing", "season_type": "regular", "limit": 50},
    )
    assert response.status_code == 200, response.text
    rows = [row for row in response.json()["rows"] if row["player_id"] == EDDIE_GEORGE]

    assert len(rows) == 1
    assert _rushing_detail(rows[0]["stats"]) == (66, 4)


def test_compare_publishes_the_rushing_detail_on_careers_and_games(client: TestClient) -> None:
    """Warner against McNair (#301): both careers and both head-to-head
    game lines carry the two stats, measured on `player_game_stats`."""
    response = client.get("/api/players/compare", params={"a": KURT_WARNER, "b": STEVE_MCNAIR})
    assert response.status_code == 200, response.text
    body = response.json()

    assert _rushing_detail(body["a"]["regular_season"]["stats"]) == (5, 2)
    assert _rushing_detail(body["b"]["postseason"]["stats"]) == (16, 1)
    (regular,) = body["regular_season_head_to_head"]["games"]
    (postseason,) = body["postseason_head_to_head"]["games"]
    assert (_rushing_detail(regular["a_stats"]), _rushing_detail(regular["b_stats"])) == (
        (1, 1),
        (5, 0),
    )
    assert (_rushing_detail(postseason["a_stats"]), _rushing_detail(postseason["b_stats"])) == (
        (0, 0),
        (6, 0),
    )


@pytest.mark.parametrize("stat", RUSHING_DETAIL_STATS)
def test_a_null_rushing_detail_stat_stays_null(tmp_path: Path, stat: str) -> None:
    """No fixture row has either stat NULL, so the copy NULLs Kurt Warner's
    1999 regular-season value: his season line publishes null, never 0, the
    other stat is untouched, and the whole body is still the engine's."""
    db = make_player_db_with_null_stat(
        tmp_path, player_id=KURT_WARNER, season=1999, season_type="regular", stat=stat
    )
    expected_other = {"rushing_first_downs": 5, "rushing_fumbles_lost": 2}
    (other,) = (name for name in RUSHING_DETAIL_STATS if name != stat)

    with client_for_db(db) as nulled:
        response = nulled.get(f"/api/players/{KURT_WARNER}")
    assert response.status_code == 200, response.text
    body = response.json()

    (line,) = (
        line
        for line in body["seasons"]
        if line["season"] == 1999 and line["season_type"] == "regular"
    )
    assert stat in line["stats"] and line["stats"][stat] is None
    assert line["stats"][other] == expected_other[other]
    with fixture_conn(db) as conn:
        assert body == engine_json(get_player_career(conn, sport="nfl", player_id=KURT_WARNER))


def test_openapi_lists_the_rushing_detail_stats() -> None:
    from api.main import app

    schema = app.openapi()["components"]["schemas"]["PlayerStatsOut"]

    assert list(schema["properties"]) == list(PUBLISHED_STATS)
    for name in RUSHING_DETAIL_STATS:
        assert name in schema["required"]
        types = {option.get("type") for option in schema["properties"][name]["anyOf"]}
        assert types == {"integer", "null"}
