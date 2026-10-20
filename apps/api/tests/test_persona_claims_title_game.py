"""Failing-first tests for issue #300: the narrator can say when a conference
title game was played, and the regular-season finale wording comes back.

Founder decision (2026-10-20, on #300): a `when` claim on a title game prints
"in the <Conference> title game", and on the last regular-season game of a
team case's games[] that isn't a title game it prints "in the regular-season
finale" -- reversing the #291 removal, which existed only because the two
couldn't be told apart. The API reads the engine's `title_game_conference`
(the CFBD conference name, or None) off every game row; it never derives a
title game from week, date or conference.

Every block is the one production builds from the committed CFB fixture
(`tests/fixtures/claim_blocks.py`), except the 1998-2000 case: the fixture
holds no title game from those seasons (when CFBD filed them postseason), so
that test takes the real 2005 Texas block and refiles its title game the way
those seasons did.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from cfb_strength.db.connection import get_conn
from cfb_strength.evidence.proof import build_comparison, build_team_case
from fixtures.claim_blocks import (
    CFB_FIXTURE_DB,
    assert_an_error_says,
    cfb_catalog,
    cfb_comparison_block,
    cfb_team_case_block,
    game_claim,
    rejected,
    rendered,
)

from api.models import (
    CommonOpponentMeetingOut,
    ComparisonResultOut,
    HeadToHeadMeetingOut,
    OpponentResultOut,
    TeamCaseOut,
)
from api.repositories.teams import TeamRecord

TEXAS_A_AND_M_2005 = 253290245
COLORADO_TITLE_GAME_2005 = 253370251
GEORGIA_TITLE_GAME_2017 = 400955153
GEORGIA_WEEK_11_2017 = 400933913


@pytest.fixture(scope="module")
def catalog() -> tuple[TeamRecord, ...]:
    return cfb_catalog()


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = get_conn(CFB_FIXTURE_DB, read_only=True)
    try:
        yield connection
    finally:
        connection.close()


def _when(claim_id: str, team: str, opponent: str, result: str, **extra: object) -> Any:
    return game_claim(claim_id, "when", team, opponent, result, **extra)


def _games(block: str) -> list[dict[str, Any]]:
    games: list[dict[str, Any]] = json.loads(block)["games"]
    return games


# ---------------------------------------------------------------------------
# the fixture facts these tests rely on
# ---------------------------------------------------------------------------


def test_fixture_facts_these_tests_rely_on() -> None:
    texas = _games(cfb_team_case_block(2005, "Texas"))
    # The block carries no game_id (#218), so games are told apart by week.
    tail = [
        (g["opponent_name"], g["week"], g["season_type"], g["title_game_conference"])
        for g in texas[-3:]
    ]
    assert tail == [
        ("Texas A&M", 13, "regular", None),
        ("Colorado", 14, "regular", "Big 12"),
        ("USC", 1, "postseason", None),
    ]
    assert texas[0]["opponent_name"] == "Louisiana"

    auburn = _games(cfb_team_case_block(2017, "Auburn"))
    georgia = [
        (g["week"], g["result"], g["title_game_conference"])
        for g in auburn
        if g["opponent_name"] == "Georgia"
    ]
    assert georgia == [(11, "W", None), (14, "L", "SEC")]
    regular = [g for g in auburn if g["season_type"] == "regular"]
    assert (regular[-2]["opponent_name"], regular[-2]["week"]) == ("Alabama", 13)


# ---------------------------------------------------------------------------
# the fact block carries title_game_conference on every game row
# ---------------------------------------------------------------------------


def test_the_team_case_block_carries_title_game_conference_on_every_row() -> None:
    block = json.loads(cfb_team_case_block(2005, "Texas"))
    rows = [*block["games"], *block["quality_wins"]]
    assert all("title_game_conference" in row for row in rows)
    assert {row["title_game_conference"] for row in block["games"]} == {None, "Big 12"}


def test_the_comparison_block_carries_title_game_conference_on_every_row() -> None:
    block = json.loads(cfb_comparison_block(2005, "Texas", "Colorado"))
    meetings = block["head_to_head"]["meetings"]
    assert [(m["week"], m["title_game_conference"]) for m in meetings] == [
        (7, None),
        (14, "Big 12"),
    ]
    for common in block["common_opponents"]:
        for row in [*common["team_a_meetings"], *common["team_b_meetings"]]:
            assert "title_game_conference" in row


# ---------------------------------------------------------------------------
# models carry title_game_conference from the engine
# ---------------------------------------------------------------------------


def test_opponent_result_out_carries_title_game_conference(conn: sqlite3.Connection) -> None:
    case = TeamCaseOut.from_dataclass(
        build_team_case(conn, 2005, "Texas", method="keener", sport="cfb")
    )
    by_id: dict[int, OpponentResultOut] = {g.game_id: g for g in case.games}
    assert by_id[COLORADO_TITLE_GAME_2005].title_game_conference == "Big 12"
    assert by_id[TEXAS_A_AND_M_2005].title_game_conference is None


def test_head_to_head_and_common_opponent_meetings_carry_title_game_conference(
    conn: sqlite3.Connection,
) -> None:
    comparison = ComparisonResultOut.from_dataclass(
        build_comparison(conn, 2005, "Texas", "Colorado", method="keener", sport="cfb")
    )
    meetings: list[HeadToHeadMeetingOut] = comparison.head_to_head.meetings
    assert {m.game_id: m.title_game_conference for m in meetings}[
        COLORADO_TITLE_GAME_2005
    ] == "Big 12"
    assert [m.title_game_conference for m in meetings if m.week == 7] == [None]

    common: list[CommonOpponentMeetingOut] = [
        meeting
        for opponent in comparison.common_opponents
        for meeting in [*opponent.team_a_meetings, *opponent.team_b_meetings]
    ]
    assert common
    assert {m.title_game_conference for m in common} == {None}

    # 2017 Auburn vs Alabama: Georgia is a common opponent, and Auburn met it
    # in the SEC title game as well as in week 11.
    auburn = ComparisonResultOut.from_dataclass(
        build_comparison(conn, 2017, "Auburn", "Alabama", method="keener", sport="cfb")
    )
    georgia = next(c for c in auburn.common_opponents if c.opponent_name == "Georgia")
    assert {m.game_id: m.title_game_conference for m in georgia.team_a_meetings} == {
        GEORGIA_WEEK_11_2017: None,
        GEORGIA_TITLE_GAME_2017: "SEC",
    }


# ---------------------------------------------------------------------------
# `when` on a team case
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("opponent", "result", "extra", "expected"),
    [
        # Texas met Colorado twice in 2005: week 7, and the Big 12 title game
        ("Colorado", "W", {"week": 14, "season_type": "regular"}, "in the Big 12 title game"),
        ("Colorado", "W", {"week": 7, "season_type": "regular"}, "in week 7"),
        # The last regular-season game that isn't a title game
        ("Texas A&M", "W", {}, "in the regular-season finale"),
        ("USC", "W", {}, "in the postseason"),
        ("Louisiana", "W", {}, "to open the season"),
        ("Kansas", "W", {}, "in week 11"),
    ],
)
def test_when_on_2005_texas(
    catalog: tuple[TeamRecord, ...],
    opponent: str,
    result: str,
    extra: dict[str, object],
    expected: str,
) -> None:
    block = cfb_team_case_block(2005, "Texas")
    claim = _when("w", "Texas", opponent, result, **extra)
    assert rendered("It happened {w}.", [claim], block, catalog) == f"It happened {expected}."


@pytest.mark.parametrize(
    ("opponent", "result", "extra", "expected"),
    [
        ("Georgia", "L", {"week": 14}, "in the SEC title game"),
        ("Georgia", "W", {"week": 11}, "in week 11"),
        # The Iron Bowl, Auburn's last regular-season game that isn't a title game
        ("Alabama", "W", {}, "in the regular-season finale"),
        ("UCF", "L", {}, "in the postseason"),
    ],
)
def test_when_on_2017_auburn(
    catalog: tuple[TeamRecord, ...],
    opponent: str,
    result: str,
    extra: dict[str, object],
    expected: str,
) -> None:
    block = cfb_team_case_block(2017, "Auburn")
    claim = _when("w", "Auburn", opponent, result, **extra)
    assert rendered("{w}", [claim], block, catalog) == expected


def test_a_title_game_reads_the_same_from_the_opponents_side(
    catalog: tuple[TeamRecord, ...],
) -> None:
    # The block holds Texas's games[], not Colorado's; the title game is
    # still the title game from Colorado's side.
    block = cfb_team_case_block(2005, "Texas")
    claim = _when("w", "Colorado", "Texas", "L", week=14)
    assert rendered("{w}", [claim], block, catalog) == "in the Big 12 title game"


def test_the_finale_is_only_the_subjects_own(catalog: tuple[TeamRecord, ...]) -> None:
    # Texas A&M's side of its game with Texas: the block holds no games[] for
    # Texas A&M, so it can't say that was Texas A&M's finale.
    block = cfb_team_case_block(2005, "Texas")
    claim = _when("w", "Texas A&M", "Texas", "L")
    assert rendered("{w}", [claim], block, catalog) == "in week 13"


# ---------------------------------------------------------------------------
# `when` on a comparison
# ---------------------------------------------------------------------------


def test_a_head_to_head_title_game_on_a_comparison(catalog: tuple[TeamRecord, ...]) -> None:
    block = cfb_comparison_block(2005, "Texas", "Colorado")
    claims = [
        _when("t", "Texas", "Colorado", "W", week=14),
        _when("s", "Texas", "Colorado", "W", week=7),
    ]
    assert rendered("{t}; {s}.", claims, block, catalog) == "in the Big 12 title game; in week 7."


def test_a_comparison_has_no_finale(catalog: tuple[TeamRecord, ...]) -> None:
    # A comparison holds no games[], so Texas's last non-title regular-season
    # game (Texas A&M, a common opponent here) prints its week.
    block = cfb_comparison_block(2005, "Texas", "Colorado")
    claim = _when("w", "Texas", "Texas A&M", "W")
    assert rendered("{w}", [claim], block, catalog) == "in week 13"


def test_a_common_opponent_title_game_on_a_comparison(catalog: tuple[TeamRecord, ...]) -> None:
    block = cfb_comparison_block(2017, "Auburn", "Alabama")
    claims = [
        _when("t", "Auburn", "Georgia", "L", week=14),
        _when("s", "Auburn", "Georgia", "W", week=11),
    ]
    assert rendered("{t}; {s}.", claims, block, catalog) == "in the SEC title game; in week 11."


# ---------------------------------------------------------------------------
# 1998-2000: CFBD filed title games as postseason
# ---------------------------------------------------------------------------


def _refiled_as_postseason(block: str) -> str:
    """The real 2005 Texas block with its Big 12 title game filed the way
    CFBD filed 1998-2000 title games: season_type 'postseason', week 1,
    moved after the regular season."""
    data = json.loads(block)
    games = data["games"]
    title = next(g for g in games if g["opponent_name"] == "Colorado" and g["week"] == 14)
    games.remove(title)
    title["season_type"] = "postseason"
    title["week"] = 1
    games.insert(len(games) - 1, title)
    return json.dumps(data)


def test_a_postseason_filed_title_game_prints_the_title_game(
    catalog: tuple[TeamRecord, ...],
) -> None:
    block = _refiled_as_postseason(cfb_team_case_block(2005, "Texas"))
    claims = [
        _when("t", "Texas", "Colorado", "W", season_type="postseason"),
        _when("b", "Texas", "USC", "W"),
        _when("f", "Texas", "Texas A&M", "W"),
    ]
    assert rendered("{t}; {b}; {f}.", claims, block, catalog) == (
        "in the Big 12 title game; in the postseason; in the regular-season finale."
    )


def test_the_fixture_has_no_1998_to_2000_title_game() -> None:
    """Why the test above refiles a real block rather than reading one."""
    connection = sqlite3.connect(f"file:{Path(CFB_FIXTURE_DB)}?mode=ro", uri=True)
    try:
        (count,) = connection.execute(
            "SELECT COUNT(*) FROM games WHERE conference_championship = 1 "
            "AND season BETWEEN 1998 AND 2000"
        ).fetchone()
    finally:
        connection.close()
    assert count == 0


# ---------------------------------------------------------------------------
# grounding: only a `when` placeholder prints the title game
# ---------------------------------------------------------------------------


def test_the_title_game_restated_through_a_when_claim_passes(
    catalog: tuple[TeamRecord, ...],
) -> None:
    block = cfb_team_case_block(2005, "Texas")
    claims = [
        game_claim("s", "game_score", "Texas", "Colorado", "W", week=14),
        _when("w", "Texas", "Colorado", "W", week=14),
    ]
    assert rendered("They ran Colorado off the field {s} {w}.", claims, block, catalog) == (
        "They ran Colorado off the field 70-3 in the Big 12 title game."
    )


def test_a_title_game_typed_into_the_prose_is_rejected(catalog: tuple[TeamRecord, ...]) -> None:
    # The block holds the conference now, but only a `when` placeholder may
    # print it: the narrator typing "Big 12" itself is a typed number.
    block = cfb_team_case_block(2005, "Texas")
    claims = [game_claim("s", "game_score", "Texas", "Colorado", "W", week=14)]
    errors = rejected("They ran Colorado off {s} in the Big 12 title game.", claims, block, catalog)
    assert_an_error_says(errors, '"12"')


def test_a_game_the_block_does_not_flag_is_no_title_game(
    catalog: tuple[TeamRecord, ...],
) -> None:
    # The other direction: the week-7 Colorado game was no title game, and a
    # `when` on it prints only what the block records.
    block = cfb_team_case_block(2005, "Texas")
    claim = _when("w", "Texas", "Colorado", "W", week=7)
    assert rendered("{w}", [claim], block, catalog) == "in week 7"
