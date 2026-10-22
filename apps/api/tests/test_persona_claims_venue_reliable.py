"""Failing-first tests for issue #349: a `where` claim only on a game whose
venue is reliable.

Founder decision on #343: CFBD's venue data is unreliable for CFB before 2008
(a game it flags neutral was played on a home field, and the reverse), so the
engine marks every game row `venue_reliable` -- true iff the sport isn't CFB,
or the season is 2008 or later, or the game is one of #359's curated
neutral-site overrides. The API copies the flag onto every game row of the
fact block, and the claim validator refuses a `where` claim on a row that has
it false, whatever the row's venue says. On a reliable row the claim renders
as before: "at home", "on the road" or "at a neutral site", from the claim
team's side.

Every block is the one production builds from the committed CFB fixture
(`tests/fixtures/claim_blocks.py`). The fixture facts are pinned first.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
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
    rendered_value,
)

from api.models import ComparisonResultOut, TeamCaseOut
from api.repositories.teams import TeamRecord


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


def _where(team: str, opponent: str, result: str, **extra: object) -> dict[str, object]:
    return game_claim("v", "where", team, opponent, result, **extra)


def _block(block: str) -> Any:
    return json.loads(block)


def _games(block: str, opponent: str) -> list[dict[str, Any]]:
    return [g for g in _block(block)["games"] if g["opponent_name"] == opponent]


# ---------------------------------------------------------------------------
# the fixture facts these tests rely on
# ---------------------------------------------------------------------------


def test_the_team_case_block_carries_venue_reliable_on_every_row() -> None:
    for year, team in ((2005, "Texas"), (2005, "Houston"), (2013, "Auburn")):
        block = _block(cfb_team_case_block(year, team))
        rows = [*block["games"], *block["quality_wins"]]
        if block["worst_loss"] is not None:
            rows.append(block["worst_loss"])
        assert all(isinstance(row["venue_reliable"], bool) for row in rows), (year, team)


def test_fixture_facts_these_tests_rely_on() -> None:
    texas = cfb_team_case_block(2005, "Texas")
    assert [(g["week"], g["venue"], g["venue_reliable"]) for g in _games(texas, "Ohio State")] == [
        (2, "away", False)
    ]
    # Houston vs Sam Houston: CFBD flags it neutral, but it was played at
    # Houston's Robertson Stadium.
    houston = cfb_team_case_block(2005, "Houston")
    assert [
        (g["week"], g["venue"], g["venue_reliable"]) for g in _games(houston, "Sam Houston")
    ] == [(2, "neutral", False)]

    auburn = cfb_team_case_block(2013, "Auburn")
    assert [(g["venue"], g["venue_reliable"]) for g in _games(auburn, "Georgia")] == [
        ("home", True)
    ]
    assert [(g["venue"], g["venue_reliable"]) for g in _games(auburn, "LSU")] == [("away", True)]

    comparison = _block(cfb_comparison_block(2005, "Texas", "Colorado"))
    assert [
        (m["week"], m["home_team"], m["neutral_site"], m["venue_reliable"])
        for m in comparison["head_to_head"]["meetings"]
    ] == [(7, "Texas", False, False), (14, "Colorado", True, True)]
    (kansas,) = [c for c in comparison["common_opponents"] if c["opponent_name"] == "Kansas"]
    assert [(m["venue"], m["venue_reliable"]) for m in kansas["team_a_meetings"]] == [
        ("home", False)
    ]


# ---------------------------------------------------------------------------
# an unreliable venue: the claim is rejected, whatever the row says
# ---------------------------------------------------------------------------


def test_where_on_texas_at_ohio_state_2005_is_rejected(catalog: tuple[TeamRecord, ...]) -> None:
    errors = rejected(
        "Texas won {v}.",
        [_where("Texas", "Ohio State", "W")],
        cfb_team_case_block(2005, "Texas"),
        catalog,
    )
    assert_an_error_says(
        errors,
        '"v"',
        "Texas vs Ohio State (regular week 2)",
        "venue_reliable false",
        "remove this claim and its placeholder",
        "don't say where the game was played in your own words",
        "A game_score or when claim on it is fine.",
    )


def test_where_on_ohio_states_side_of_the_same_game_is_rejected(
    catalog: tuple[TeamRecord, ...],
) -> None:
    """The flag is the game's, so the mirrored row the block indexes for the
    opponent carries it too."""
    errors = rejected(
        "{v}", [_where("Ohio State", "Texas", "L")], cfb_team_case_block(2005, "Texas"), catalog
    )
    assert_an_error_says(errors, '"v"', "Ohio State vs Texas", "venue_reliable false")


def test_where_on_houston_vs_sam_houston_2005_is_rejected_though_the_block_says_neutral(
    catalog: tuple[TeamRecord, ...],
) -> None:
    errors = rejected(
        "{v}",
        [_where("Houston", "Sam Houston", "W")],
        cfb_team_case_block(2005, "Houston"),
        catalog,
    )
    assert_an_error_says(errors, '"v"', "Houston vs Sam Houston", "venue_reliable false")


def test_a_game_score_and_when_on_the_unreliable_game_still_render(
    catalog: tuple[TeamRecord, ...],
) -> None:
    claims = [
        game_claim("s", "game_score", "Texas", "Ohio State", "W"),
        game_claim("w", "when", "Texas", "Ohio State", "W"),
    ]
    assert (
        rendered_value("{s} {w}", claims, cfb_team_case_block(2005, "Texas"), catalog)
        == "25-22 in week 2"
    )


def test_where_on_an_unreliable_head_to_head_meeting_is_rejected(
    catalog: tuple[TeamRecord, ...],
) -> None:
    block = cfb_comparison_block(2005, "Texas", "Colorado")
    for claim in (
        _where("Texas", "Colorado", "W", week=7, season_type="regular"),
        _where("Colorado", "Texas", "L", week=7, season_type="regular"),
    ):
        assert_an_error_says(
            rejected("{v}", [claim], block, catalog), '"v"', "venue_reliable false"
        )


def test_where_on_the_2005_rose_bowl_is_rejected(catalog: tuple[TeamRecord, ...]) -> None:
    block = cfb_comparison_block(2005, "Texas", "USC")
    assert_an_error_says(
        rejected("{v}", [_where("USC", "Texas", "L")], block, catalog),
        '"v"',
        "USC vs Texas",
        "venue_reliable false",
    )


def test_where_on_an_unreliable_common_opponent_meeting_is_rejected(
    catalog: tuple[TeamRecord, ...],
) -> None:
    block = cfb_comparison_block(2005, "Texas", "Colorado")
    assert_an_error_says(
        rejected("{v}", [_where("Texas", "Kansas", "W")], block, catalog),
        '"v"',
        "Texas vs Kansas",
        "venue_reliable false",
    )


# ---------------------------------------------------------------------------
# a reliable venue: rendered as before
# ---------------------------------------------------------------------------


def test_where_on_the_2005_big_12_title_game_is_a_neutral_site_from_both_sides(
    catalog: tuple[TeamRecord, ...],
) -> None:
    """#359's curated override: the 2005 Big 12 Championship was played at
    Reliant Stadium in Houston, so its venue is reliable before 2008."""
    block = cfb_comparison_block(2005, "Texas", "Colorado")
    texas = _where("Texas", "Colorado", "W", week=14, season_type="regular")
    colorado = _where("Colorado", "Texas", "L", week=14, season_type="regular")
    assert rendered_value("{v}", [texas], block, catalog) == "at a neutral site"
    assert rendered_value("{v}", [colorado], block, catalog) == "at a neutral site"


def test_where_on_a_2013_home_game(catalog: tuple[TeamRecord, ...]) -> None:
    block = cfb_team_case_block(2013, "Auburn")
    assert rendered_value("{v}", [_where("Auburn", "Georgia", "W")], block, catalog) == "at home"
    # and the opponent's mirrored side of the same game
    assert (
        rendered_value("{v}", [_where("Georgia", "Auburn", "L")], block, catalog) == "on the road"
    )


def test_where_on_a_2013_road_game(catalog: tuple[TeamRecord, ...]) -> None:
    block = cfb_team_case_block(2013, "Auburn")
    score = game_claim("s", "game_score", "Auburn", "LSU", "L")
    assert (
        rendered("Auburn lost {s} {v}.", [score, _where("Auburn", "LSU", "L")], block, catalog)
        == "Auburn lost 35-21 on the road."
    )


def test_where_on_a_reliable_common_opponent_meeting(catalog: tuple[TeamRecord, ...]) -> None:
    block = cfb_comparison_block(2017, "Alabama", "Auburn")
    (mississippi_state,) = [
        c for c in _block(block)["common_opponents"] if c["opponent_name"] == "Mississippi State"
    ]
    assert [m["venue_reliable"] for m in mississippi_state["team_a_meetings"]] == [True]
    alabama = _where("Alabama", "Mississippi State", "W")
    auburn = _where("Auburn", "Mississippi State", "W")
    assert rendered_value("{v}", [alabama], block, catalog) == "on the road"
    assert rendered_value("{v}", [auburn], block, catalog) == "at home"


# ---------------------------------------------------------------------------
# the four Out models copy venue_reliable from the engine
# ---------------------------------------------------------------------------


def test_team_case_out_copies_venue_reliable(conn: sqlite3.Connection) -> None:
    texas = TeamCaseOut.from_dataclass(
        build_team_case(conn, 2005, "Texas", method="elo", sport="cfb")
    )
    by_week = {(g.week, g.season_type): g.venue_reliable for g in texas.games}
    assert by_week[(2, "regular")] is False  # at Ohio State
    assert by_week[(14, "regular")] is True  # the Big 12 title game
    assert by_week[(1, "postseason")] is False  # the Rose Bowl
    assert texas.elo_ledger is not None
    steps = {(s.week, s.season_type): s.venue_reliable for s in texas.elo_ledger.steps}
    assert steps == by_week

    auburn = TeamCaseOut.from_dataclass(
        build_team_case(conn, 2013, "Auburn", method="elo", sport="cfb")
    )
    assert {g.venue_reliable for g in auburn.games} == {True}
    assert auburn.elo_ledger is not None
    assert {s.venue_reliable for s in auburn.elo_ledger.steps} == {True}
    assert {q.venue_reliable for q in auburn.quality_wins} == {True}


def test_comparison_out_copies_venue_reliable(conn: sqlite3.Connection) -> None:
    texas_colorado = ComparisonResultOut.from_dataclass(
        build_comparison(conn, 2005, "Texas", "Colorado", method="elo", sport="cfb")
    )
    assert [(m.week, m.venue_reliable) for m in texas_colorado.head_to_head.meetings] == [
        (7, False),
        (14, True),
    ]
    (kansas,) = [c for c in texas_colorado.common_opponents if c.opponent_name == "Kansas"]
    assert [m.venue_reliable for m in kansas.team_a_meetings] == [False]
    assert [m.venue_reliable for m in kansas.team_b_meetings] == [False]
    assert texas_colorado.team_a.elo_ledger is not None
    assert False in {s.venue_reliable for s in texas_colorado.team_a.elo_ledger.steps}

    auburn_fsu = ComparisonResultOut.from_dataclass(
        build_comparison(conn, 2013, "Auburn", "Florida State", method="elo", sport="cfb")
    )
    assert [m.venue_reliable for m in auburn_fsu.head_to_head.meetings] == [True]
    for side in (auburn_fsu.team_a, auburn_fsu.team_b):
        assert {q.venue_reliable for q in side.quality_wins} == {True}
        assert side.elo_ledger is not None
        assert {s.venue_reliable for s in side.elo_ledger.steps} == {True}


def test_the_comparison_wire_json_carries_venue_reliable(conn: sqlite3.Connection) -> None:
    dumped = ComparisonResultOut.from_dataclass(
        build_comparison(conn, 2017, "Alabama", "Auburn", method="keener", sport="cfb")
    ).model_dump(mode="json")
    for common in dumped["common_opponents"]:
        for row in [*common["team_a_meetings"], *common["team_b_meetings"]]:
            assert row["venue_reliable"] is True
    for meeting in dumped["head_to_head"]["meetings"]:
        assert meeting["venue_reliable"] is True
