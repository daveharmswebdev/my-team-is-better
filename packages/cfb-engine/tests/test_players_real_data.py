"""`cfb_strength.players` against real data (#296): the committed nflverse
cache, ingested for every season 1999-2025 into a tmp db (about two seconds,
zero network), checked against the numbers the coordinator measured on a full
`cfb ingest --sport nfl` + `cfb ingest-players --sport nfl` build.

The whole window is needed: a career total and a leaderboard rank are only
right when every season of every player is present.
"""

from __future__ import annotations

import itertools
import sqlite3
from collections.abc import Iterator

import pytest

from cfb_strength.config import RAW_DIR
from cfb_strength.contracts import (
    PlayerCareer,
    PlayerComparison,
    PlayerHeadToHead,
    PlayerHeadToHeadGame,
    PlayerSeasonLine,
    StarterRecord,
)
from cfb_strength.db.connection import ensure_schema, get_conn
from cfb_strength.ingest.nflverse import client as nflverse_client
from cfb_strength.ingest.nflverse import ingest_season as nflverse_ingest
from cfb_strength.ingest.nflverse.ingest_players import ingest_players
from cfb_strength.ingest.nflverse.normalize import build_team_lookup
from cfb_strength.players import (
    get_player_career,
    get_player_comparison,
    get_player_leaders,
    search_players,
)

YEARS = list(range(1999, 2026))
BRADY = 2054406429
PEYTON_MANNING = 2153701690
ELI_MANNING = 2302152414
MAHOMES = 2319407936
BLEDSOE = 2017631641
KORDELL_STEWART = 2216460621
SORGI = 2398371226
PLUMMER = 2260685818
MADDOX = 2448560637
VICK = 2079758716
WARNER = 2044124519
SCOTT_MITCHELL = 2330103075


def _refuse_live_fetch(url: str) -> str:
    raise AssertionError(f"live fetch attempted: {url}")


@pytest.fixture(scope="module")
def conn(tmp_path_factory: pytest.TempPathFactory) -> Iterator[sqlite3.Connection]:
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(nflverse_client, "_fetch_csv_live", _refuse_live_fetch)
        c = get_conn(tmp_path_factory.mktemp("players_real") / "nfl.sqlite3")
        ensure_schema(c)
        games_raw, games_live = nflverse_client.get_games(raw_dir=RAW_DIR)
        teams_raw, teams_live = nflverse_client.get_teams(raw_dir=RAW_DIR)
        assert not (games_live or teams_live)
        lookup = build_team_lookup(teams_raw)
        for year in YEARS:
            for season_type in ("regular", "postseason"):
                nflverse_ingest.ingest_one(c, year, season_type, games_raw, lookup)
        report = ingest_players(c, YEARS, raw_dir=RAW_DIR)
        assert report.fetched_live is False
    try:
        yield c
    finally:
        c.close()


def _player_id(conn: sqlite3.Connection, name: str) -> int:
    rows = conn.execute(
        "SELECT id FROM players WHERE sport = 'nfl' AND display_name = ?", (name,)
    ).fetchall()
    assert len(rows) == 1
    return int(rows[0][0])


def _line(career: PlayerCareer, season: int, season_type: str) -> PlayerSeasonLine:
    (line,) = [s for s in career.seasons if (s.season, s.season_type) == (season, season_type)]
    return line


def test_qualifying_populations(conn: sqlite3.Connection) -> None:
    assert get_player_leaders(conn, sport="nfl").total == 819
    assert get_player_leaders(conn, sport="nfl", season_type="postseason").total == 180


def test_brady_leads_regular_season_passing_yards(conn: sqlite3.Connection) -> None:
    rows = get_player_leaders(conn, sport="nfl", limit=3).rows

    brady = rows[0]
    assert (brady.rank, brady.player_id, brady.display_name) == (1, BRADY, "Tom Brady")
    assert (brady.first_season, brady.last_season, brady.games) == (2000, 2022, 335)
    assert brady.record == StarterRecord(251, 79, 0)
    s = brady.stats
    assert (s.passing_yards, s.passing_tds, s.completions, s.attempts) == (89216, 649, 7754, 12052)
    assert s.passing_interceptions == 212
    assert [
        (r.rank, r.display_name, r.stats.passing_yards, r.stats.passing_tds) for r in rows[1:]
    ] == [
        (2, "Drew Brees", 80428, 571),
        (3, "Peyton Manning", 68201, 513),
    ]


def test_regular_season_wins_order(conn: sqlite3.Connection) -> None:
    rows = get_player_leaders(conn, sport="nfl", sort="wins", limit=5).rows
    assert [(r.rank, r.display_name, r.record) for r in rows] == [
        (1, "Tom Brady", StarterRecord(251, 79, 0)),
        (2, "Peyton Manning", StarterRecord(181, 64, 0)),
        (3, "Drew Brees", StarterRecord(172, 112, 0)),
        (4, "Ben Roethlisberger", StarterRecord(165, 81, 1)),
        (5, "Aaron Rodgers", StarterRecord(163, 92, 1)),
    ]


def test_regular_season_passing_tds_ties_share_a_rank(conn: sqlite3.Connection) -> None:
    rows = get_player_leaders(conn, sport="nfl", sort="passing_tds", limit=40).rows
    by_tds: dict[int | None, list[int | None]] = {}
    for r in rows:
        by_tds.setdefault(r.stats.passing_tds, []).append(r.rank)
    for tds in (161, 157):
        ranks = by_tds[tds]
        assert len(ranks) == 2 and ranks[0] == ranks[1], tds
    ranked = [r.rank for r in rows]
    assert ranked == sorted(ranked, key=lambda x: x or 0)


def test_postseason_boards(conn: sqlite3.Connection) -> None:
    yards = get_player_leaders(conn, sport="nfl", season_type="postseason", limit=1).rows[0]
    assert (yards.rank, yards.display_name) == (1, "Tom Brady")
    assert (yards.stats.passing_yards, yards.stats.passing_tds) == (13400, 88)
    assert yards.record.starts == 48

    wins = get_player_leaders(
        conn, sport="nfl", season_type="postseason", sort="wins", limit=4
    ).rows
    assert [(r.rank, r.display_name, r.record.wins, r.record.losses) for r in wins] == [
        (1, "Tom Brady", 35, 13),
        (2, "Patrick Mahomes", 17, 4),
        (3, "Peyton Manning", 14, 13),
        (4, "Ben Roethlisberger", 13, 10),
    ]


def test_warner_1999(conn: sqlite3.Connection) -> None:
    career = get_player_career(conn, sport="nfl", player_id=_player_id(conn, "Kurt Warner"))

    regular = _line(career, 1999, "regular")
    assert (regular.stats.passing_yards, regular.stats.passing_tds, regular.games) == (4044, 38, 15)
    assert regular.record == StarterRecord(13, 3, 0)
    assert regular.teams == ["St. Louis Rams"]
    assert regular.games_without_stat_lines == 1
    assert _line(career, 1999, "postseason").record == StarterRecord(3, 0, 0)


def test_manning_2004_and_brady_2022(conn: sqlite3.Connection) -> None:
    manning = get_player_career(conn, sport="nfl", player_id=_player_id(conn, "Peyton Manning"))
    assert _line(manning, 2004, "regular").record == StarterRecord(12, 3, 0)
    assert _line(manning, 2004, "postseason").record == StarterRecord(1, 1, 0)

    brady = get_player_career(conn, sport="nfl", player_id=BRADY)
    assert _line(brady, 2022, "regular").record == StarterRecord(8, 8, 0)
    assert _line(brady, 2022, "postseason").record == StarterRecord(0, 1, 0)


def test_a_season_row_with_no_team_takes_its_teams_from_game_rows(
    conn: sqlite3.Connection,
) -> None:
    orton = _player_id(conn, "Kyle Orton")
    assert (
        conn.execute(
            "SELECT team_id FROM player_season_stats WHERE player_id = ? AND season = 2011 "
            "AND season_type = 'regular'",
            (orton,),
        ).fetchone()[0]
        is None
    )
    line = _line(get_player_career(conn, sport="nfl", player_id=orton), 2011, "regular")
    assert line.teams == ["Denver Broncos", "Kansas City Chiefs"]


def test_brady_career_matches_his_leaders_rows(conn: sqlite3.Connection) -> None:
    career = get_player_career(conn, sport="nfl", player_id=BRADY)
    for season_type, totals in (
        ("regular", career.regular_season),
        ("postseason", career.postseason),
    ):
        board = get_player_leaders(conn, sport="nfl", season_type=season_type, limit=1)  # type: ignore[arg-type]  # loop over the Literal's values
        row = board.rows[0]
        assert totals is not None
        assert (row.games, row.record, row.stats) == (totals.games, totals.record, totals.stats)


# --- comparison and search (#301) ---------------------------------------------


def _compare(conn: sqlite3.Connection, a: int, b: int) -> PlayerComparison:
    return get_player_comparison(conn, sport="nfl", a=a, b=b)


def _results(h2h: PlayerHeadToHead) -> list[tuple[str | None, int, int]]:
    return [(g.source_id, g.a_points, g.b_points) for g in h2h.games]


def _game(h2h: PlayerHeadToHead, source_id: str) -> PlayerHeadToHeadGame:
    (game,) = [g for g in h2h.games if g.source_id == source_id]
    return game


def test_brady_peyton_manning_head_to_head_both_ways(conn: sqlite3.Connection) -> None:
    ab = _compare(conn, BRADY, PEYTON_MANNING)
    assert ab.regular_season_head_to_head.record == StarterRecord(9, 3, 0)
    assert len(ab.regular_season_head_to_head.games) == 12
    assert ab.postseason_head_to_head.record == StarterRecord(2, 3, 0)
    assert len(ab.postseason_head_to_head.games) == 5

    ba = _compare(conn, PEYTON_MANNING, BRADY)
    assert ba.regular_season_head_to_head.record == StarterRecord(3, 9, 0)
    assert ba.postseason_head_to_head.record == StarterRecord(3, 2, 0)


def test_comparison_careers_are_the_career_pages(conn: sqlite3.Connection) -> None:
    c = _compare(conn, BRADY, PEYTON_MANNING)
    assert c.a == get_player_career(conn, sport="nfl", player_id=BRADY)
    assert c.b == get_player_career(conn, sport="nfl", player_id=PEYTON_MANNING)
    for career, expected in (
        (c.a, (23, 335, StarterRecord(251, 79, 0), 89216, 649, 212)),
        (c.b, (16, 250, StarterRecord(181, 64, 0), 68201, 513, 223)),
    ):
        t = career.regular_season
        assert t is not None
        s = t.stats
        assert (
            t.seasons,
            t.games,
            t.record,
            s.passing_yards,
            s.passing_tds,
            s.passing_interceptions,
        ) == expected


def test_brady_eli_manning_head_to_head(conn: sqlite3.Connection) -> None:
    c = _compare(conn, BRADY, ELI_MANNING)
    assert c.regular_season_head_to_head.record == StarterRecord(2, 1, 0)
    assert _results(c.regular_season_head_to_head) == [
        ("2007_17_NE_NYG", 38, 35),
        ("2011_09_NYG_NE", 20, 24),
        ("2015_10_NE_NYG", 27, 26),
    ]
    assert c.postseason_head_to_head.record == StarterRecord(0, 2, 0)
    assert _results(c.postseason_head_to_head) == [
        ("2007_21_NYG_NE", 14, 17),
        ("2011_21_NYG_NE", 17, 21),
    ]


def test_brady_mahomes_head_to_head(conn: sqlite3.Connection) -> None:
    c = _compare(conn, BRADY, MAHOMES)
    assert c.regular_season_head_to_head.record == StarterRecord(1, 3, 0)
    assert c.postseason_head_to_head.record == StarterRecord(2, 0, 0)


def test_a_relief_appearance_is_not_head_to_head_2001_20_ne_pit(conn: sqlite3.Connection) -> None:
    listed = _game(_compare(conn, BRADY, KORDELL_STEWART).postseason_head_to_head, "2001_20_NE_PIT")
    assert (listed.season, listed.season_type) == (2001, "postseason")
    assert (listed.a_team, listed.b_team) == ("New England Patriots", "Pittsburgh Steelers")
    assert (listed.a_points, listed.b_points) == (24, 17)
    assert listed.a_stats is not None and listed.a_stats.attempts == 18
    assert listed.b_stats is not None and listed.b_stats.attempts == 42

    relief = _compare(conn, BLEDSOE, KORDELL_STEWART)
    for h2h in (relief.regular_season_head_to_head, relief.postseason_head_to_head):
        assert "2001_20_NE_PIT" not in [g.source_id for g in h2h.games]


def test_a_listed_replacement_owns_the_game_2004_17_ind_den(conn: sqlite3.Connection) -> None:
    manning = _compare(conn, PEYTON_MANNING, PLUMMER).regular_season_head_to_head
    assert "2004_17_IND_DEN" not in [g.source_id for g in manning.games]

    sorgi = _compare(conn, SORGI, PLUMMER).regular_season_head_to_head
    game = _game(sorgi, "2004_17_IND_DEN")
    assert (game.a_team, game.b_team, game.a_points, game.b_points) == (
        "Indianapolis Colts",
        "Denver Broncos",
        14,
        33,
    )
    assert game.a_stats is not None and game.a_stats.attempts == 25
    assert sorgi.record == StarterRecord(0, 1, 0)


def test_maddox_vick_tie_either_way_round(conn: sqlite3.Connection) -> None:
    for a, b in ((MADDOX, VICK), (VICK, MADDOX)):
        h2h = _compare(conn, a, b).regular_season_head_to_head
        assert h2h.record == StarterRecord(0, 0, 1)
        assert _results(h2h) == [("2002_10_ATL_PIT", 34, 34)]


def test_warner_mitchell_game_has_no_stat_lines(conn: sqlite3.Connection) -> None:
    h2h = _compare(conn, WARNER, SCOTT_MITCHELL).regular_season_head_to_head
    game = _game(h2h, "1999_01_BAL_STL")
    assert (game.a_team, game.b_team, game.a_points, game.b_points) == (
        "St. Louis Rams",
        "Baltimore Ravens",
        27,
        10,
    )
    assert (game.a_stats, game.b_stats) == (None, None)
    assert h2h.record.wins >= 1


def test_starter_pair_premises(conn: sqlite3.Connection) -> None:
    """The data facts the head-to-head tests lean on: every completed game has
    exactly one listed-starter pair, no incomplete game has one (so the
    incomplete-game exclusion is proven only on synthetic rows), 15 pairs
    tied, and three games lack a starter's stat line."""
    per_game = """
        SELECT g.id, g.source_id, g.home_points, g.away_points,
               g.completed = 1 AND g.home_points IS NOT NULL AND g.away_points IS NOT NULL
                   AS counted,
               (SELECT COUNT(DISTINCT s.team_id) FROM game_starters s
                WHERE s.game_id = g.id AND s.sport = 'nfl' AND s.position = 'QB') AS sides
        FROM games g WHERE g.sport = 'nfl'
    """
    rows = conn.execute(per_game).fetchall()
    counted = [r for r in rows if r["counted"]]
    assert len(counted) == 7276
    assert all(r["sides"] == 2 for r in counted)
    assert [r for r in rows if not r["counted"] and r["sides"] == 2] == []
    assert sum(1 for r in counted if r["home_points"] == r["away_points"]) == 15
    missing = conn.execute(
        """
        SELECT DISTINCT g.source_id FROM games g
        JOIN game_starters s ON s.game_id = g.id AND s.sport = 'nfl' AND s.position = 'QB'
        WHERE g.sport = 'nfl' AND g.completed = 1 AND NOT EXISTS (
            SELECT 1 FROM player_game_stats p
            WHERE p.game_id = g.id AND p.player_id = s.player_id AND p.sport = 'nfl')
        ORDER BY g.source_id
        """
    ).fetchall()
    assert [r[0] for r in missing] == ["1999_01_BAL_STL", "2000_03_SD_KC", "2000_06_BUF_MIA"]


def test_top_ten_passers_head_to_head_invariants(conn: sqlite3.Connection) -> None:
    top = [r.player_id for r in get_player_leaders(conn, sport="nfl", limit=10).rows]
    starts: dict[int, set[tuple[str, str]]] = {
        p: {
            (r[0], r[1])
            for r in conn.execute(
                "SELECT g.source_id, g.season_type FROM game_starters s "
                "JOIN games g ON g.id = s.game_id AND g.sport = 'nfl' "
                "WHERE s.player_id = ? AND s.sport = 'nfl' AND s.position = 'QB'",
                (p,),
            )
        }
        for p in top
    }
    met = 0
    for a, b in itertools.combinations(top, 2):
        ab, ba = _compare(conn, a, b), _compare(conn, b, a)
        assert (ba.a, ba.b) == (ab.b, ab.a)
        for mine, theirs in (
            (ab.regular_season_head_to_head, ba.regular_season_head_to_head),
            (ab.postseason_head_to_head, ba.postseason_head_to_head),
        ):
            r = mine.record
            assert theirs.record == StarterRecord(r.losses, r.wins, r.ties)
            assert r.starts == len(mine.games) and theirs.record.starts == len(theirs.games)
            assert [(g.source_id, g.a_points, g.b_points) for g in theirs.games] == [
                (g.source_id, g.b_points, g.a_points) for g in mine.games
            ]
            for g in mine.games:
                assert g.source_id is not None
                assert (g.source_id, g.season_type) in starts[a]
                assert (g.source_id, g.season_type) in starts[b]
            met += len(mine.games)
    assert met > 0


def test_search_real_names(conn: sqlite3.Connection) -> None:
    def names(query: str, limit: int = 10) -> list[str]:
        return [
            r.display_name for r in search_players(conn, sport="nfl", query=query, limit=limit).rows
        ]

    assert names("manning") == ["Peyton Manning", "Eli Manning"]
    assert names("brady") == ["Tom Brady", "Brady Quinn", "Brady Cook"]
    assert names("josh", limit=6) == [
        "Josh Allen",
        "Josh McCown",
        "Josh Freeman",
        "Joshua Dobbs",
        "Josh Rosen",
        "Josh Johnson",
    ]
    assert names("jo", limit=6) == [
        "Joe Flacco",
        "Josh Allen",
        "Jon Kitna",
        "Brad Johnson",
        "Joe Burrow",
        "Josh McCown",
    ]
    (peyton,) = search_players(conn, sport="nfl", query=" Peyton Manning ").rows
    assert (peyton.player_id, peyton.first_season, peyton.last_season) == (
        PEYTON_MANNING,
        1999,
        2015,
    )
