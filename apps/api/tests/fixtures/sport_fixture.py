"""Throwaway sqlite db builder for sport-threading tests (GitHub issue #59).

Mirrors `cfb_strength.evidence.test_proof`'s `_build_fixture` almost exactly
(same insert helpers, same CFB win-cycle/NFL win-cycle/"Wildcats" name-
collision shape) rather than reusing the committed
`cfb_verdict_fixture.sqlite3`, which is a CFB-only slice and has no
`sport='nfl'` rows at all. This is the one place in `apps/api` that needs a
hand-built db instead of the real-engine-computed fixture, since exercising
sport threading through the HTTP layer requires NFL rows to exist somewhere,
and building a second real-engine-computed fixture is unnecessary weight for
what's ultimately a plumbing test (the engine layer's own real-ratings
integration test already lives in `cfb_verdict_fixture.sqlite3` / this
module's own `test_proof.py` counterpart).

The season defaults to `YEAR` (2023). Issue #151 builds the same shape in
other seasons (`year=2003` etc.) because no committed fixture has NFL rows in
a contested CFB year, and `contested` has to be proven per league there.

Not part of the pytest suite itself (doesn't match `test_*.py`) -- imported
by `test_verdict_sport.py`, `test_catalog_sport.py`, `test_deps.py` and
`test_verdict_contested_by_sport.py`.
"""

from __future__ import annotations

import math
import sqlite3
from pathlib import Path

from cfb_strength.db.connection import ensure_schema, get_conn

YEAR = 2023
METHOD = "keener"
# The season only NFL has a (keener) row for; see `build_sport_fixture`.
NFL_ONLY_YEAR = 2024

# CFB team ids/names (a 3-team win cycle 1 > 2 > 3 > 1).
CFB_TEAM_NAMES = {1: "Alpha State", 2: "Bravo Tech", 3: "Charlie U"}
# NFL team ids/names (an analogous, disjoint-id 3-team win cycle).
NFL_TEAM_NAMES = {101: "Delta Squad", 102: "Echo Corp", 103: "Foxtrot Ltd"}
# Name-colliding pair across sports, same year/method -- proves a CFB/NFL
# team-name collision (e.g. shared city/mascot names) doesn't cross-
# contaminate `resolve_team`'s candidate pool or the sport-scoped team
# catalog (`list_team_records`) the claim validator grounds against.
CFB_COLLISION_TEAM_ID = 4
NFL_COLLISION_TEAM_ID = 104
COLLISION_NAME = "Wildcats"

# Issue #254: every CFB team carries a mascot, as a real ingest's #77 alias
# enrichment gives it, so `cfb doctor` doesn't report `no_cfb_mascots` (which
# no slice waives). Invented animals no other fixture name, prose word or
# test string uses, so the grounding check's mascot matching (claims.py) has
# nothing to catch in existing narration. NFL catalog rows carry no mascot,
# as in production.
CFB_MASCOTS = {
    1: "Aardvarks",
    2: "Bandicoots",
    3: "Capybaras",
    CFB_COLLISION_TEAM_ID: "Dugongs",
}


def _insert_team(
    conn: sqlite3.Connection,
    team_id: int,
    school: str,
    classification: str | None = None,
    sport: str = "cfb",
    mascot: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO teams (id, school, classification, sport, mascot) VALUES (?, ?, ?, ?, ?)",
        (team_id, school, classification, sport, mascot),
    )


def _insert_game(
    conn: sqlite3.Connection,
    game_id: int,
    year: int,
    home_id: int,
    away_id: int,
    home_team: str,
    away_team: str,
    home_points: int,
    away_points: int,
    week: int = 1,
    season_type: str = "regular",
    completed: bool = True,
    sport: str = "cfb",
) -> None:
    conn.execute(
        """
        INSERT INTO games (
            id, season, week, season_type, start_date, neutral_site, completed,
            home_team_id, away_team_id, home_team, away_team,
            home_points, away_points, home_conference, away_conference, venue, raw_json, sport
        ) VALUES (?, ?, ?, ?, NULL, 0, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, '{}', ?)
        """,
        (
            game_id,
            year,
            week,
            season_type,
            1 if completed else 0,
            home_id,
            away_id,
            home_team,
            away_team,
            home_points,
            away_points,
            sport,
        ),
    )


def _insert_rating(
    conn: sqlite3.Connection,
    year: int,
    method: str,
    team_id: int,
    rating: float,
    rank: int,
    wins: int,
    losses: int,
    sport: str = "cfb",
    ties: int = 0,
) -> None:
    conn.execute(
        """
        INSERT INTO ratings (
            year, method, team_id, rating, rank, wins, losses, ties, computed_at, sport
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'test', ?)
        """,
        (year, method, team_id, rating, rank, wins, losses, ties, sport),
    )


def _insert_breakdown(
    conn: sqlite3.Connection,
    year: int,
    method: str,
    team_id: int,
    opponent_team_id: int | None,
    games_played: int | None,
    wins: int | None,
    losses: int | None,
    credit: float | None,
    contribution: float,
    sport: str = "cfb",
) -> None:
    conn.execute(
        """
        INSERT INTO rating_breakdowns (
            year, method, team_id, opponent_team_id, games_played, wins, losses,
            credit, contribution, computed_at, sport
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'test', ?)
        """,
        (
            year,
            method,
            team_id,
            opponent_team_id,
            games_played,
            wins,
            losses,
            credit,
            contribution,
            sport,
        ),
    )


def build_sport_fixture(conn: sqlite3.Connection, year: int = YEAR) -> None:
    """Populate `conn` (an already-`ensure_schema`'d connection) with a CFB
    win cycle, an NFL win cycle, and a cross-sport name collision, all in
    season `year`."""
    for tid, name in CFB_TEAM_NAMES.items():
        _insert_team(conn, tid, name, classification="fbs", sport="cfb", mascot=CFB_MASCOTS[tid])
    _insert_game(conn, 1, year, 1, 2, CFB_TEAM_NAMES[1], CFB_TEAM_NAMES[2], 30, 10, sport="cfb")
    _insert_game(conn, 2, year, 2, 3, CFB_TEAM_NAMES[2], CFB_TEAM_NAMES[3], 20, 17, sport="cfb")
    _insert_game(conn, 3, year, 3, 1, CFB_TEAM_NAMES[3], CFB_TEAM_NAMES[1], 3, 40, sport="cfb")
    _insert_rating(conn, year, METHOD, 1, 1.5, 1, 2, 0, sport="cfb")
    _insert_rating(conn, year, METHOD, 2, 1.0, 2, 1, 1, sport="cfb")
    _insert_rating(conn, year, METHOD, 3, 0.5, 3, 0, 2, sport="cfb")
    for tid in (1, 2, 3):
        _insert_breakdown(conn, year, METHOD, tid, None, None, None, None, None, 0.1, sport="cfb")
    _insert_breakdown(conn, year, METHOD, 1, 2, 1, 1, 0, 0.6, 0.9, sport="cfb")
    _insert_breakdown(conn, year, METHOD, 1, 3, 1, 1, 0, 0.6, 0.5, sport="cfb")

    for tid, name in NFL_TEAM_NAMES.items():
        _insert_team(conn, tid, name, classification=None, sport="nfl")
    _insert_game(
        conn, 101, year, 101, 102, NFL_TEAM_NAMES[101], NFL_TEAM_NAMES[102], 24, 20, sport="nfl"
    )
    _insert_game(
        conn, 102, year, 102, 103, NFL_TEAM_NAMES[102], NFL_TEAM_NAMES[103], 27, 3, sport="nfl"
    )
    _insert_game(
        conn, 103, year, 103, 101, NFL_TEAM_NAMES[103], NFL_TEAM_NAMES[101], 14, 31, sport="nfl"
    )
    _insert_rating(conn, year, METHOD, 101, 1.4, 1, 2, 0, sport="nfl")
    _insert_rating(conn, year, METHOD, 102, 0.9, 2, 1, 1, sport="nfl")
    _insert_rating(conn, year, METHOD, 103, 0.4, 3, 0, 2, sport="nfl")
    for tid in (101, 102, 103):
        _insert_breakdown(conn, year, METHOD, tid, None, None, None, None, None, 0.1, sport="nfl")

    # NFL-only rating for a year CFB has no rows for, so a sport-scoped
    # "unknown year" 404 for CFB never accidentally reports the NFL list.
    _insert_team(conn, 105, "Golf United", classification=None, sport="nfl")
    _insert_rating(conn, NFL_ONLY_YEAR, METHOD, 105, 0.2, 1, 1, 0, sport="nfl")

    # Cross-sport name collision, same year/method, no games needed
    # (build_team_case only requires a ratings row to exist).
    _insert_team(
        conn,
        CFB_COLLISION_TEAM_ID,
        COLLISION_NAME,
        classification="fbs",
        sport="cfb",
        mascot=CFB_MASCOTS[CFB_COLLISION_TEAM_ID],
    )
    _insert_rating(conn, year, METHOD, CFB_COLLISION_TEAM_ID, 0.3, 4, 0, 0, sport="cfb")
    _insert_breakdown(
        conn, year, METHOD, CFB_COLLISION_TEAM_ID, None, None, None, None, None, 0.1, sport="cfb"
    )

    _insert_team(conn, NFL_COLLISION_TEAM_ID, COLLISION_NAME, classification=None, sport="nfl")
    _insert_rating(conn, year, METHOD, NFL_COLLISION_TEAM_ID, 0.3, 4, 0, 0, sport="nfl")
    _insert_breakdown(
        conn, year, METHOD, NFL_COLLISION_TEAM_ID, None, None, None, None, None, 0.1, sport="nfl"
    )

    build_tie_cluster(conn, year)
    for sport in ("cfb", "nfl"):
        build_elo(conn, year, sport)


# Issue #83: a synthetic NFL tie. No committed apps/api fixture had a single
# equal-score game (the CFB fixture's real seven-season data and the win
# cycles above are all decisive), so nothing could prove a tie survives the
# HTTP layer. Kept disjoint from the win cycle above -- separate ids, ranks
# below every existing NFL row -- so no pre-existing assertion moves.
#
#   Lima Lions   20-13 Kilo Kings      (week 1: Kilo's only loss, to rank 5)
#   Kilo Kings   17-17 Mike Mustangs   (week 2: the tie, against rank 8)
#   Kilo Kings   24-7  November Nomads (week 3: a win over rank 9)
#   Lima Lions   27-10 Mike Mustangs   (week 2: so Mike is a common opponent)
#   Kilo Kings   31-14 Mike Mustangs   (week 4: the rematch, issue #130)
#
# The ranks are chosen so a tie mistaken for a loss would *become*
# `worst_loss` (rank 8 is worse than rank 5), and a tie mistaken for a win
# would join `quality_wins` (rank 8 is inside the top-25 threshold) as a
# third entry with equal scores.
#
# The week-4 rematch (issue #130) makes Kilo Kings meet the common opponent
# twice, so `CommonOpponent.team_a_meetings` for a Kilo-vs-Lima comparison
# is [T 17-17, W 31-14] in that order while Lima's is the single 27-10 win.
# A decisive win rather than a loss keeps `worst_loss` on Lima Lions, so the
# tie-mistaken-for-a-loss check above still has a single real loss to compare
# against. Kilo Kings are 2-1-1; Mike Mustangs 0-2-1.
TIE_TEAM_ID = 106
TIE_TEAM = "Kilo Kings"
TIE_RIVAL_ID = 107
TIE_RIVAL = "Lima Lions"
TIE_OPPONENT_ID = 108
TIE_OPPONENT = "Mike Mustangs"
TIE_WIN_OPPONENT_ID = 109
TIE_WIN_OPPONENT = "November Nomads"


def build_tie_cluster(conn: sqlite3.Connection, year: int = YEAR) -> None:
    names = {
        TIE_TEAM_ID: TIE_TEAM,
        TIE_RIVAL_ID: TIE_RIVAL,
        TIE_OPPONENT_ID: TIE_OPPONENT,
        TIE_WIN_OPPONENT_ID: TIE_WIN_OPPONENT,
    }
    for tid, name in names.items():
        _insert_team(conn, tid, name, classification=None, sport="nfl")

    _insert_game(
        conn, 104, year, TIE_RIVAL_ID, TIE_TEAM_ID, TIE_RIVAL, TIE_TEAM, 20, 13, sport="nfl"
    )
    _insert_game(
        conn,
        105,
        year,
        TIE_TEAM_ID,
        TIE_OPPONENT_ID,
        TIE_TEAM,
        TIE_OPPONENT,
        17,
        17,
        week=2,
        sport="nfl",
    )
    _insert_game(
        conn,
        106,
        year,
        TIE_TEAM_ID,
        TIE_WIN_OPPONENT_ID,
        TIE_TEAM,
        TIE_WIN_OPPONENT,
        24,
        7,
        week=3,
        sport="nfl",
    )
    _insert_game(
        conn,
        107,
        year,
        TIE_RIVAL_ID,
        TIE_OPPONENT_ID,
        TIE_RIVAL,
        TIE_OPPONENT,
        27,
        10,
        week=2,
        sport="nfl",
    )
    _insert_game(
        conn,
        108,
        year,
        TIE_TEAM_ID,
        TIE_OPPONENT_ID,
        TIE_TEAM,
        TIE_OPPONENT,
        31,
        14,
        week=4,
        sport="nfl",
    )

    _insert_rating(conn, year, METHOD, TIE_RIVAL_ID, 0.35, 5, 2, 0, sport="nfl")
    _insert_rating(conn, year, METHOD, TIE_TEAM_ID, 0.25, 6, 2, 1, sport="nfl", ties=1)
    _insert_rating(conn, year, METHOD, TIE_OPPONENT_ID, 0.15, 8, 0, 2, sport="nfl", ties=1)
    _insert_rating(conn, year, METHOD, TIE_WIN_OPPONENT_ID, 0.05, 9, 0, 1, sport="nfl")
    for tid in names:
        _insert_breakdown(conn, year, METHOD, tid, None, None, None, None, None, 0.1, sport="nfl")


def doctor_slice(year: int = YEAR) -> dict[str, dict[str, object]]:
    """The deliberate slice `make_sport_fixture_db(year=year)` carries, in
    `build_fixture.py`'s `--slice` JSON shape (#254): regular-season games in
    `year` for both leagues, keener and elo ratings for them (elo_career
    deliberately none, as in the verdict fixture, #98), keener for the NFL
    2024 one-team season too, and no player stats. `cfb doctor` findings
    beyond what this slice explains fail `test_sport_fixture_doctor.py`."""
    return {
        "cfb": {
            "games": {"regular": [year]},
            "rated": {"keener": [year], "elo": [year]},
        },
        "nfl": {
            "games": {"regular": [year]},
            "rated": {"keener": sorted({year, NFL_ONLY_YEAR}), "elo": [year]},
        },
    }


# Issue #254: Elo ratings and their ledger (#183), so the fixture is a slice
# `cfb doctor` accepts (`season_missing_ratings` for elo is not waivable for a
# season the fixture means to rate, and an elo-rated season without its
# ledger is `season_missing_elo_ledger`) and a validator can check NFL Elo
# against it. apps/api's tests may not import `cfb_strength.ratings`, so the
# season-isolated walk is re-done here by hand: the engine's update math
# (`ratings/elo.py`'s `_game_update` and `_walk`), its shipped `ELO_CONFIGS`
# constants, and `compute_ratings._load_games`' game order. It is a faithful
# copy for this tiny regular-season slice, not a second engine, and it is
# pinned to the engine: `test_sport_fixture_doctor.py` runs `build_fixture.py
# --check-elo-parity` (the sanctioned importer of `cfb_strength.ratings`) for
# 2023 and 2003, which re-rates a copy of the db with `compute_and_store(conn,
# year, "elo")` and requires the ratings, ledger steps and config rows to be
# exactly equal. An engine retune turns that red; update the copy to match.
# The existing assertions all use
# keener, which these rows leave untouched (`method` scopes every table).
ELO_METHOD = "elo"
# sport -> (k, hfa); `initial`, `scale`, `mov_scale`, `mov_autocorr` and the
# MOV denominator floor are shared by both sports' configs.
ELO_K_HFA = {"nfl": (20.0, 65.0), "cfb": (40.0, 100.0)}
ELO_INITIAL = 1500.0
ELO_SCALE = 400.0
ELO_MOV_SCALE = 2.2
ELO_MOV_AUTOCORR = 0.001
ELO_MOV_DENOM_FLOOR_FRACTION = 0.5


def _letter(points: int, opponent_points: int) -> str:
    return "W" if points > opponent_points else "L" if points < opponent_points else "T"


def build_elo(conn: sqlite3.Connection, year: int, sport: str) -> None:
    """Rate `sport`'s completed `year` games with season-isolated Elo and
    store the ratings, one ledger step per team per game, and the config
    row, as `compute_and_store(conn, year, "elo")` shapes them."""
    k, hfa = ELO_K_HFA[sport]
    games = conn.execute(
        """
        SELECT week, season_type, start_date, home_team_id, away_team_id,
               home_points, away_points, neutral_site
        FROM games
        WHERE season = ? AND sport = ? AND completed = 1
          AND home_points IS NOT NULL AND away_points IS NOT NULL
        ORDER BY season,
                 CASE season_type WHEN 'regular' THEN 0 ELSE 1 END,
                 CASE WHEN season_type = 'regular' THEN week END IS NULL,
                 CASE WHEN season_type = 'regular' THEN week END,
                 start_date IS NULL, start_date,
                 week IS NULL, week,
                 id
        """,
        (year, sport),
    ).fetchall()

    elo: dict[int, float] = {}
    record: dict[int, list[int]] = {}  # team -> [wins, losses, ties]
    steps: list[tuple[object, ...]] = []
    game_numbers: dict[int, int] = {}
    for g in games:
        home, away = int(g["home_team_id"]), int(g["away_team_id"])
        hp, ap = int(g["home_points"]), int(g["away_points"])
        neutral = bool(g["neutral_site"])
        for team in (home, away):
            elo.setdefault(team, ELO_INITIAL)
            record.setdefault(team, [0, 0, 0])
        home_before, away_before = elo[home], elo[away]

        home_field = 0.0 if neutral else hfa
        elo_diff = home_before - away_before + home_field
        result = 1.0 if hp > ap else 0.0 if hp < ap else 0.5
        if result == 0.5:
            denom = 1.0
        else:
            winner_diff = elo_diff if result == 1.0 else -elo_diff
            denom = max(
                winner_diff * ELO_MOV_AUTOCORR + ELO_MOV_SCALE,
                ELO_MOV_DENOM_FLOOR_FRACTION * ELO_MOV_SCALE,
            )
        multiplier = math.log(max(abs(hp - ap), 1.0) + 1.0) * (ELO_MOV_SCALE / denom)
        expected = 1.0 / (math.pow(10.0, -elo_diff / ELO_SCALE) + 1.0)
        shift = k * multiplier * (result - expected)
        elo[home] += shift
        elo[away] -= shift

        if hp > ap:
            record[home][0] += 1
            record[away][1] += 1
        elif ap > hp:
            record[away][0] += 1
            record[home][1] += 1
        else:
            record[home][2] += 1
            record[away][2] += 1

        sides = (
            (home, away, "home", hp, ap, home_before, away_before, home_field, elo_diff,
             expected, shift),
            (away, home, "away", ap, hp, away_before, home_before, 0.0 - home_field,
             -elo_diff, 1.0 - expected, -shift),
        )  # fmt: skip
        for team, opp, venue, pts, opp_pts, before, opp_before, hfa_adj, gap, we, sh in sides:
            game_numbers[team] = game_numbers.get(team, 0) + 1
            steps.append(
                (
                    year, ELO_METHOD, sport, team, game_numbers[team], g["week"],
                    g["season_type"], g["start_date"], opp, "neutral" if neutral else venue,
                    pts, opp_pts, _letter(pts, opp_pts), before, opp_before, hfa_adj, gap,
                    we, multiplier, sh, elo[team],
                )
            )  # fmt: skip

    order = sorted(elo, key=lambda team: (-elo[team], team))
    for rank, team in enumerate(order, start=1):
        wins, losses, ties = record[team]
        _insert_rating(conn, year, ELO_METHOD, team, elo[team], rank, wins, losses, sport, ties)
    conn.executemany(
        """
        INSERT INTO elo_ledger_steps (
            year, method, sport, team_id, game_number, week, season_type, start_date,
            opponent_team_id, venue, team_points, opponent_points, result,
            rating_before, opponent_rating_before, home_field_adjustment, rating_gap,
            win_expectancy, mov_multiplier, shift, rating_after, computed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'test')
        """,
        steps,
    )
    conn.execute(
        """
        INSERT INTO elo_ledger_configs (
            year, method, sport, starting_rating, k, hfa, scale, mov_scale, mov_autocorr,
            mov_denom_floor_fraction, computed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'test')
        """,
        (
            year,
            ELO_METHOD,
            sport,
            ELO_INITIAL,
            k,
            hfa,
            ELO_SCALE,
            ELO_MOV_SCALE,
            ELO_MOV_AUTOCORR,
            ELO_MOV_DENOM_FLOOR_FRACTION,
        ),
    )


def make_sport_fixture_db(tmp_path: Path, year: int = YEAR) -> Path:
    """Build a fresh schema-only db at `tmp_path / "sport_fixture.sqlite3"`,
    populate it via `build_sport_fixture` for season `year`, and return its
    path."""
    db_path = tmp_path / "sport_fixture.sqlite3"
    conn = get_conn(db_path)
    ensure_schema(conn)
    build_sport_fixture(conn, year)
    conn.commit()
    conn.close()
    return db_path
