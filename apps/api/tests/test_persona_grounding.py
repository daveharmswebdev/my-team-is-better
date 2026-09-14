"""Failing-first tests for `api.persona.grounding` (issue #4 / Architecture
Brief §4.3): every number-like token and known-team-name mention in the
persona's response must be a subset of what's in the fact block.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from cfb_strength.db.connection import get_conn
from cfb_strength.evidence.proof import build_comparison, build_team_case
from fixtures.sport_fixture import make_sport_fixture_db

from api.deps import list_all_team_names
from api.models import ComparisonResultOut, Sport, TeamCaseOut
from api.persona.grounding import find_ungrounded_tokens
from api.persona.service import comparison_fact_block_json, team_case_fact_block_json

FACT_BLOCK = (
    '{"team_name": "Texas", "year": 2005, "wins": 13, "losses": 0, "rank": 1, '
    '"quality_wins": [{"opponent_name": "USC", "team_score": 41, '
    '"opponent_score": 38}]}'
)
KNOWN_TEAMS = ["Texas", "USC", "Alabama", "Oklahoma"]


def test_fully_grounded_response_has_no_mismatches() -> None:
    response = "Texas ran the table at 13-0 in 2005 and beat USC 41-38."

    assert find_ungrounded_tokens(response, FACT_BLOCK, KNOWN_TEAMS) == []


def test_invented_number_is_flagged() -> None:
    # "14" doesn't appear anywhere in FACT_BLOCK's number tokens
    # (2005, 13, 0, 1, 41, 38) -- a clean fabrication to catch.
    response = "Texas went 13-0 and stomped USC by 14 points, easy."

    mismatches = find_ungrounded_tokens(response, FACT_BLOCK, KNOWN_TEAMS)

    assert "14" in mismatches


def test_mentioned_team_not_in_fact_block_is_flagged() -> None:
    response = "Texas would have smoked Alabama too, probably."

    mismatches = find_ungrounded_tokens(response, FACT_BLOCK, KNOWN_TEAMS)

    assert "Alabama" in mismatches


def test_team_mentioned_and_present_in_fact_block_is_not_flagged() -> None:
    response = "Texas beat USC, plain and simple."

    mismatches = find_ungrounded_tokens(response, FACT_BLOCK, KNOWN_TEAMS)

    assert mismatches == []


def test_number_present_in_fact_block_is_not_flagged() -> None:
    response = "That 2005 Texas team went 13-0, ranked #1, with a 41-38 win over USC."

    mismatches = find_ungrounded_tokens(response, FACT_BLOCK, KNOWN_TEAMS)

    assert mismatches == []


# ---------------------------------------------------------------------------
# issue #26: relational (order-aware, opponent-aware) grounding. Individual
# token membership is not enough -- "34", "31", and "Texas" can each appear
# somewhere in the fact block without "Texas 34-31" ever being a true fact.
# ---------------------------------------------------------------------------

VANDY_FACT_BLOCK = (
    '{"team_name": "Vanderbilt", "year": 2025, "wins": 10, "losses": 3, '
    '"rank": 21, "games": [], '
    '"quality_wins": ['
    '{"opponent_name": "Texas", "team_score": 31, "opponent_score": 34, "result": "L"}, '
    '{"opponent_name": "LSU", "team_score": 31, "opponent_score": 24, "result": "W"}, '
    '{"opponent_name": "Tennessee", "team_score": 45, "opponent_score": 24, "result": "W"}'
    '], "worst_loss": null}'
)
VANDY_KNOWN_TEAMS = ["Vanderbilt", "Texas", "LSU", "Tennessee", "Iowa"]


def test_swapped_score_order_for_real_opponent_is_flagged_the_issue_26_regression() -> None:
    # Texas actually lost 31-34 (team_score first); the narration swapped
    # the digit order, which flips the implied result. LSU and Tennessee are
    # both stated correctly right next to Texas's mismatch and must NOT be
    # cross-contaminated by the nearest-neighbor pairing.
    response = (
        "Vanderbilt finished 10-3, and they beat ranked teams like Texas "
        "(34-31), LSU (31-24), and Tennessee (45-24) along the way."
    )

    mismatches = find_ungrounded_tokens(response, VANDY_FACT_BLOCK, VANDY_KNOWN_TEAMS)

    assert "Texas's score should be stated 31-34, not 34-31" in mismatches
    assert not any(m.startswith("LSU") for m in mismatches)
    assert not any(m.startswith("Tennessee") for m in mismatches)


def test_correctly_ordered_multi_game_sentence_is_not_flagged() -> None:
    response = (
        "Vanderbilt finished 10-3, and they beat ranked teams like LSU "
        "(31-24) and Tennessee (45-24), but Texas (31-34) got them."
    )

    mismatches = find_ungrounded_tokens(response, VANDY_FACT_BLOCK, VANDY_KNOWN_TEAMS)

    assert mismatches == []


def test_team_mentioned_with_no_nearby_score_pair_is_not_spuriously_flagged() -> None:
    response = "Vanderbilt had a great year, and honestly Texas gave them all they could handle."

    mismatches = find_ungrounded_tokens(response, VANDY_FACT_BLOCK, VANDY_KNOWN_TEAMS)

    assert mismatches == []


COMPARISON_FACT_BLOCK = (
    '{"year": 2025, '
    '"team_a": {"team_name": "Vanderbilt", "quality_wins": [], "worst_loss": null}, '
    '"team_b": {"team_name": "Texas", "quality_wins": [], "worst_loss": null}, '
    '"head_to_head": {"played": true, "meetings": ['
    '{"home_team": "Texas", "away_team": "Vanderbilt", '
    '"home_points": 34, "away_points": 31, "winner": "Texas"}'
    "]}, "
    '"common_opponents": ['
    '{"opponent_name": "LSU", "team_a_score": 31, "team_a_opponent_score": 24, '
    '"team_b_score": 20, "team_b_opponent_score": 17}'
    '], "rating_diff": 3.1, "verdict": "Texas"}'
)
COMPARISON_KNOWN_TEAMS = ["Vanderbilt", "Texas", "LSU"]


def test_head_to_head_meeting_swapped_order_is_flagged() -> None:
    response = "Texas (31-34) got the better of Vanderbilt in a real slugfest."

    mismatches = find_ungrounded_tokens(response, COMPARISON_FACT_BLOCK, COMPARISON_KNOWN_TEAMS)

    assert "Texas's score should be stated 34-31, not 31-34" in mismatches


def test_head_to_head_meeting_correct_order_is_not_flagged() -> None:
    response = "Texas (34-31) got the better of Vanderbilt in a real slugfest."

    mismatches = find_ungrounded_tokens(response, COMPARISON_FACT_BLOCK, COMPARISON_KNOWN_TEAMS)

    assert mismatches == []


def test_common_opponent_swapped_order_is_flagged() -> None:
    response = "Vanderbilt handled LSU (24-31) as a common opponent, for what it's worth."

    mismatches = find_ungrounded_tokens(response, COMPARISON_FACT_BLOCK, COMPARISON_KNOWN_TEAMS)

    assert "LSU 24-31" in mismatches


def test_common_opponent_correct_order_is_not_flagged() -> None:
    response = "Vanderbilt handled LSU (31-24) as a common opponent, for what it's worth."

    mismatches = find_ungrounded_tokens(response, COMPARISON_FACT_BLOCK, COMPARISON_KNOWN_TEAMS)

    assert mismatches == []


# ---------------------------------------------------------------------------
# issue #26 follow-up: nearest-neighbor-with-a-fixed-window missed realistic
# phrasing where the score isn't textually adjacent to the team name
# (Finding 1), and wrongly flagged the equally common "TeamA beat TeamB
# score" construction where the nearest name is textually close but not who
# the score actually belongs to (Finding 2). Sentence-scoped, parenthetical-
# vs-bare matching (see grounding.py's module docstring) fixes both without
# regressing the original three-team case above.
# ---------------------------------------------------------------------------


def test_swapped_score_far_from_team_name_is_now_flagged_finding_1() -> None:
    # The exact issue #26 bug (a swapped score for a real opponent), just
    # phrased with the score ~70 characters from "Texas" instead of
    # immediately next to it in a parenthetical -- past the old fixed
    # proximity window, so it used to fall through to plain membership
    # checking and go uncaught.
    response = (
        "Vanderbilt handled Texas pretty well for most of the game, but when "
        "the final whistle blew it was 34-31."
    )

    mismatches = find_ungrounded_tokens(response, VANDY_FACT_BLOCK, VANDY_KNOWN_TEAMS)

    assert mismatches != []


def test_team_a_beat_team_b_score_construction_is_not_falsely_flagged_finding_2() -> None:
    # "Texas beat Vanderbilt 34-31" is 100% accurate (Texas's own score, 34,
    # stated first per rule 5) -- but "Vanderbilt" is textually closer to
    # "34-31" than "Texas" is, so naive nearest-neighbor attribution used to
    # check it against Vanderbilt's tuples instead and wrongly flag it.
    response = "Texas beat Vanderbilt 34-31 in a real slugfest."

    mismatches = find_ungrounded_tokens(response, COMPARISON_FACT_BLOCK, COMPARISON_KNOWN_TEAMS)

    assert mismatches == []


def test_relational_mismatch_message_states_the_correct_order_explicitly() -> None:
    # Finding 3: the feedback string for a relational mismatch must name
    # the correct order, not just repeat the wrong one -- otherwise a retry
    # has nothing concrete to self-correct from.
    response = "Texas (31-34) got the better of Vanderbilt in a real slugfest."

    mismatches = find_ungrounded_tokens(response, COMPARISON_FACT_BLOCK, COMPARISON_KNOWN_TEAMS)

    assert any("should be stated 34-31" in m and "not 31-34" in m for m in mismatches)


# ---------------------------------------------------------------------------
# issue #83: a tied team's own W-L-T record, and its tied game, ground
# against the *real* fact block `api.persona.service` hands Claude
# (`TeamCaseOut.model_dump_json()`), not a hand-typed string. The numbers are
# chosen so the digit "1" appears in that JSON only as `ties` -- the 2016
# Bengals' 27-27 tie with Washington in London, week 8.
# ---------------------------------------------------------------------------

BENGALS_KNOWN_TEAMS = ["Cincinnati Bengals", "Washington Redskins", "Pittsburgh Steelers"]


def _bengals_fact_block(*, with_tie_game: bool) -> str:
    from api.models import OpponentResultOut, RatingBreakdownOut, TeamCaseOut

    games = (
        [
            OpponentResultOut(
                opponent_team_id=33,
                opponent_name="Washington Redskins",
                opponent_rank=14,
                opponent_rating=0.4,
                result="T",
                team_score=27,
                opponent_score=27,
                week=8,
                season_type="regular",
                neutral_site=True,
            )
        ]
        if with_tie_game
        else []
    )
    return TeamCaseOut(
        year=2016,
        method="keener",
        team_id=7,
        team_name="Cincinnati Bengals",
        rank=20,
        rating=0.35,
        wins=6,
        losses=9,
        ties=1,
        rating_breakdown=RatingBreakdownOut(entries=[], residual_contribution=0.0),
        elo_ledger=None,
        games=games,
        quality_wins=[],
        worst_loss=None,
    ).model_dump_json()


def test_tied_teams_own_w_l_t_record_is_grounded() -> None:
    fact_block = _bengals_fact_block(with_tie_game=False)
    response = "Cincinnati Bengals went 6-9-1 in 2016, and that's all you need to know."

    assert find_ungrounded_tokens(response, fact_block, BENGALS_KNOWN_TEAMS) == []


def test_invented_tie_count_is_still_flagged() -> None:
    fact_block = _bengals_fact_block(with_tie_game=False)
    response = "Cincinnati Bengals went 6-9-2 in 2016."

    assert "2" in find_ungrounded_tokens(response, fact_block, BENGALS_KNOWN_TEAMS)


def test_tied_game_score_is_grounded_against_the_tied_opponent() -> None:
    fact_block = _bengals_fact_block(with_tie_game=True)
    response = (
        "Cincinnati Bengals went 6-9-1 in 2016. They tied the Washington Redskins 27-27 in London."
    )

    assert find_ungrounded_tokens(response, fact_block, BENGALS_KNOWN_TEAMS) == []


# ---------------------------------------------------------------------------
# issue #107: a subject team's own W-L(-T) record is not a game score. Before
# the fix, a record was attributed to its nearest team name like any other
# hyphen pair and flagged whenever that name had game data -- which served the
# fallback for correct narrations in production. Every fact block here is the
# real one `api.persona.service` hands Claude (its `team_case_fact_block_json`
# / `comparison_fact_block_json` of the evidence built from a committed
# fixture, which leave out `elo_ledger`, #183), not a hand-typed string.
#
# Each grounded sentence is paired with the same sentence carrying a
# fabricated pair that is NOT a subject team's record, asserted to produce the
# exact mismatch message the relational check produces. Those fail if the
# relational check is disabled, or if the skip widens past "equals a subject
# team's record".
# ---------------------------------------------------------------------------

FIXTURE_DB = Path(__file__).parent / "fixtures" / "cfb_verdict_fixture.sqlite3"


@pytest.fixture
def cfb_conn() -> Iterator[sqlite3.Connection]:
    conn = get_conn(FIXTURE_DB, read_only=True)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def nfl_conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    conn = get_conn(make_sport_fixture_db(tmp_path), read_only=True)
    try:
        yield conn
    finally:
        conn.close()


def _team_case_block(conn: sqlite3.Connection, year: int, team: str, sport: Sport) -> str:
    case = build_team_case(conn, year, team, method="keener", sport=sport)
    return team_case_fact_block_json(TeamCaseOut.from_dataclass(case))


def _comparison_block(
    conn: sqlite3.Connection, year: int, team_a: str, team_b: str, sport: Sport
) -> str:
    comparison = build_comparison(conn, year, team_a, team_b, method="keener", sport=sport)
    return comparison_fact_block_json(ComparisonResultOut.from_dataclass(comparison))


def _check(conn: sqlite3.Connection, response: str, fact_block: str, sport: Sport) -> list[str]:
    return find_ungrounded_tokens(response, fact_block, list_all_team_names(conn, sport))


# --- comparison, each record next to its own team (bare) -------------------


def test_comparison_records_attributed_to_their_own_teams_are_grounded(
    cfb_conn: sqlite3.Connection,
) -> None:
    """The production 2025 Texas vs Texas A&M shape ("Texas went 10-3 and
    Texas A&M went 11-2"). 2025 isn't in the committed fixture, so this uses
    the fixture's 2005 Texas (13-0) vs USC (12-1) comparison, which has the
    same shape: the two teams met, so both names carry head-to-head score
    tuples, and neither record is a game score."""
    block = _comparison_block(cfb_conn, 2005, "Texas", "USC", "cfb")
    response = "Texas went 13-0 and USC went 12-1 in 2005."

    assert _check(cfb_conn, response, block, "cfb") == []


def test_comparison_fabricated_record_is_still_flagged(cfb_conn: sqlite3.Connection) -> None:
    block = _comparison_block(cfb_conn, 2005, "Texas", "USC", "cfb")
    response = "Texas went 13-1 and USC went 12-1 in 2005."

    assert _check(cfb_conn, response, block, "cfb") == ["USC 13-1"]


# --- team case, record next to an opponent (bare) --------------------------

LSU_2003_NARRATION = (
    "LSU is your #1, and they earned it going {record} with wins over Oklahoma "
    "{bowl_score} in the bowl game and swept Georgia twice (17-10, then 34-13)."
)


def test_team_case_record_next_to_an_opponent_is_grounded(cfb_conn: sqlite3.Connection) -> None:
    """#107's 2003 LSU reproduction from the #109 smoke eval, verbatim up to
    its ellipsis: LSU's 13-1 sits nearer "Oklahoma" than "LSU"."""
    block = _team_case_block(cfb_conn, 2003, "LSU", "cfb")
    response = LSU_2003_NARRATION.format(record="13-1", bowl_score="21-14")

    assert _check(cfb_conn, response, block, "cfb") == []


def test_team_case_fabricated_record_next_to_an_opponent_is_still_flagged(
    cfb_conn: sqlite3.Connection,
) -> None:
    block = _team_case_block(cfb_conn, 2003, "LSU", "cfb")
    response = LSU_2003_NARRATION.format(record="14-1", bowl_score="21-14")

    assert _check(cfb_conn, response, block, "cfb") == [
        "Oklahoma's score should be stated 21-14, not 14-1"
    ]


def test_team_case_fabricated_game_score_beside_a_real_record_is_still_flagged(
    cfb_conn: sqlite3.Connection,
) -> None:
    block = _team_case_block(cfb_conn, 2003, "LSU", "cfb")
    response = LSU_2003_NARRATION.format(record="13-1", bowl_score="21-13")

    assert _check(cfb_conn, response, block, "cfb") == [
        "Oklahoma's score should be stated 21-14, not 21-13"
    ]


def test_per_opponent_breakdown_record_is_not_treated_as_a_subject_record(
    cfb_conn: sqlite3.Connection,
) -> None:
    """Only the subject team's own season record is skipped. LSU's 2003
    `rating_breakdown` carries a 2-0 series record against Georgia, but a
    "2-0" stated as a Georgia score is still checked against Georgia's real
    game scores."""
    block = _team_case_block(cfb_conn, 2003, "LSU", "cfb")
    response = "LSU beat Georgia 2-0 that year."

    assert _check(cfb_conn, response, block, "cfb") == ["Georgia 2-0"]


# --- parenthetical record ---------------------------------------------------

PARENTHETICAL_2005 = "Texas ({record}) and USC (12-1) met in the Rose Bowl, and Texas won 41-38."


def test_parenthetical_record_is_grounded(cfb_conn: sqlite3.Connection) -> None:
    block = _comparison_block(cfb_conn, 2005, "Texas", "USC", "cfb")
    response = PARENTHETICAL_2005.format(record="13-0")

    assert _check(cfb_conn, response, block, "cfb") == []


def test_parenthetical_fabricated_record_is_still_flagged(cfb_conn: sqlite3.Connection) -> None:
    block = _comparison_block(cfb_conn, 2005, "Texas", "USC", "cfb")
    response = PARENTHETICAL_2005.format(record="13-1")

    assert _check(cfb_conn, response, block, "cfb") == ["Texas 13-1"]


# --- W-L-T, using the NFL tie cluster in tests/fixtures/sport_fixture.py ----

TIE_TEAM_CASE = "The Kilo Kings tied the Mike Mustangs {tie_score} and went {record} in 2023."


def test_w_l_t_record_next_to_a_tied_opponent_is_grounded(nfl_conn: sqlite3.Connection) -> None:
    """#107's first comment ("went 8-8-1 ... tied the Minnesota Vikings
    26-26"), on the fixture's Kilo Kings (1-1-1), who tied the Mike Mustangs
    17-17. The regex reads "1-1" out of "1-1-1"; `ties` grounds the last 1."""
    block = _team_case_block(nfl_conn, 2023, "Kilo Kings", "nfl")
    response = TIE_TEAM_CASE.format(tie_score="17-17", record="1-1-1")

    assert _check(nfl_conn, response, block, "nfl") == []


def test_w_l_t_fabricated_record_is_still_flagged(nfl_conn: sqlite3.Connection) -> None:
    block = _team_case_block(nfl_conn, 2023, "Kilo Kings", "nfl")
    response = TIE_TEAM_CASE.format(tie_score="17-17", record="7-1-1")

    assert _check(nfl_conn, response, block, "nfl") == [
        "Mike Mustangs's score should be stated 17-17, not 7-1"
    ]


def test_w_l_t_fabricated_tie_score_beside_a_real_record_is_still_flagged(
    nfl_conn: sqlite3.Connection,
) -> None:
    block = _team_case_block(nfl_conn, 2023, "Kilo Kings", "nfl")
    response = TIE_TEAM_CASE.format(tie_score="17-7", record="1-1-1")

    assert _check(nfl_conn, response, block, "nfl") == [
        "Mike Mustangs's score should be stated 17-17, not 17-7"
    ]


TIE_COMPARISON = (
    "Kilo Kings went {record} and Mike Mustangs went 0-1-1 after they tied 17-17 in 2023."
)


def test_w_l_t_records_of_both_compared_teams_are_grounded(nfl_conn: sqlite3.Connection) -> None:
    """Both compared teams have a tie and met each other, so both names carry
    a 17-17 head-to-head tuple: the comparison shape, with W-L-T records."""
    block = _comparison_block(nfl_conn, 2023, "Kilo Kings", "Mike Mustangs", "nfl")
    response = TIE_COMPARISON.format(record="1-1-1")

    assert _check(nfl_conn, response, block, "nfl") == []


def test_w_l_t_fabricated_record_in_a_comparison_is_still_flagged(
    nfl_conn: sqlite3.Connection,
) -> None:
    block = _comparison_block(nfl_conn, 2023, "Kilo Kings", "Mike Mustangs", "nfl")
    response = TIE_COMPARISON.format(record="1-0-1")

    assert _check(nfl_conn, response, block, "nfl") == [
        "Kilo Kings's score should be stated 17-17, not 1-0"
    ]
