"""Failing-first tests for `api.persona.grounding` (issue #4 / Architecture
Brief §4.3): every number-like token and known-team-name mention in the
persona's response must be a subset of what's in the fact block.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from cfb_strength.db.connection import get_conn
from cfb_strength.evidence.proof import build_comparison, build_team_case
from fixtures.sport_fixture import make_sport_fixture_db

from api.models import ComparisonResultOut, Method, Sport, TeamCaseOut
from api.persona.grounding import _mismatch_message, find_ungrounded_tokens
from api.persona.narrate import NarrationResult, narrate
from api.persona.service import comparison_fact_block_json, team_case_fact_block_json
from api.repositories.teams import list_all_team_names

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
    '{"opponent_name": "LSU", "opponent_rank": 12, '
    '"team_a_meetings": ['
    '{"result": "W", "team_score": 31, "opponent_score": 24, "week": 5, "season_type": "regular"}, '
    '{"result": "L", "team_score": 17, "opponent_score": 20, "week": 11, "season_type": "regular"}'
    "], "
    '"team_b_meetings": ['
    '{"result": "W", "team_score": 20, "opponent_score": 17, "week": 9, "season_type": "regular"}'
    "]}"
    '], "rating_diff": 3.1, "verdict": "Texas"}'
)
COMPARISON_KNOWN_TEAMS = ["Vanderbilt", "Texas", "LSU"]
# LSU carries three real tuples (31-24 and 17-20 from Vanderbilt's side, 20-17
# from Texas's), so a wrong pair gets #255's multi-tuple form listing them all.
LSU_24_31_MISMATCH = "LSU 24-31 matches no game; LSU's real scores are 17-20, 20-17 and 31-24"


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

    assert LSU_24_31_MISMATCH in mismatches


def test_common_opponent_correct_order_is_not_flagged() -> None:
    response = "Vanderbilt handled LSU (31-24) as a common opponent, for what it's worth."

    mismatches = find_ungrounded_tokens(response, COMPARISON_FACT_BLOCK, COMPARISON_KNOWN_TEAMS)

    assert mismatches == []


# ---------------------------------------------------------------------------
# issue #130: a common opponent carries EVERY meeting per side
# (`team_a_meetings` / `team_b_meetings`, each a list of
# `CommonOpponentMeetingOut`), so a side that met the shared opponent twice
# no longer has its earlier meeting hidden. A serialized meeting has
# `team_score`/`opponent_score` but no `opponent_name` of its own -- the name
# sits on the enclosing row -- so the walker must register every meeting's
# pair under that row's `opponent_name`, not just the last one.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "response",
    [
        "Vanderbilt beat LSU (31-24) early in the year, for what it's worth.",
        "Vanderbilt then lost to LSU (17-20) in the rematch, for what it's worth.",
        "Texas beat LSU (20-17) the one time they met, for what it's worth.",
    ],
)
def test_every_common_opponent_meeting_score_is_grounded_in_correct_order(response: str) -> None:
    mismatches = find_ungrounded_tokens(response, COMPARISON_FACT_BLOCK, COMPARISON_KNOWN_TEAMS)

    assert mismatches == []


def test_common_opponent_meeting_swapped_order_is_still_flagged() -> None:
    response = "Vanderbilt handled LSU (24-31) as a common opponent, for what it's worth."

    mismatches = find_ungrounded_tokens(response, COMPARISON_FACT_BLOCK, COMPARISON_KNOWN_TEAMS)

    # LSU has three real tuples, so the multi-tuple message form (#255 lists
    # them all, ascending).
    assert LSU_24_31_MISMATCH in mismatches


def test_earlier_common_opponent_meeting_is_grounded_the_issue_130_regression() -> None:
    """The first of two meetings, not the last: exactly the fact the old
    one-pair-per-side shape hid, and the one a walker that only kept each
    list's last element would drop."""
    response = "Vanderbilt beat LSU (31-24) in week 5 before dropping the rematch."

    mismatches = find_ungrounded_tokens(response, COMPARISON_FACT_BLOCK, COMPARISON_KNOWN_TEAMS)

    assert mismatches == []
    # The same claim, swapped, is a real mismatch and not a silently
    # unchecked pair: the walker did register (31, 24) for LSU.
    swapped = "Vanderbilt beat LSU (24-31) in week 5 before dropping the rematch."
    assert LSU_24_31_MISMATCH in find_ungrounded_tokens(
        swapped, COMPARISON_FACT_BLOCK, COMPARISON_KNOWN_TEAMS
    )


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
# issue #26 on a Keener block (#166 round 4): a Keener `rating_breakdown`
# explanation quotes every game score ("Beat them, 45-12"), so each score is a
# hyphen pair inside a string value, in either order. #166's record-attribution
# path took over "Texas beat Oklahoma 12-45" (the sentence names a subject, so
# the pair is a record claim first) and granted it the either-order
# string-value exemption #181 gave only to sentences naming no team -- so the
# swapped score beside the opponent passed on every Keener block (282 of 1,126
# swapped-score probes at round 3, 20 before #166). The blocks here are the
# real Keener ones (`_team_case_block` / `_comparison_block` default to Keener),
# and each test first pins the premise: the swapped pair is a string pair of
# the block and not, in order, a game score of it.
# ---------------------------------------------------------------------------


def _string_pairs(fact_block: str) -> set[tuple[int, int]]:
    """Every two-part hyphen pair inside a string value of the block, as
    `(low, high)`, the way the module's string-value exemption reads them."""
    pairs: set[tuple[int, int]] = set()
    for text in _string_values(json.loads(fact_block)):
        for match in re.finditer(r"(?<!\d)(\d+)\s*-\s*(\d+)(?!\s*-\s*\d)(?!\d)", text):
            low, high = sorted((int(match.group(1)), int(match.group(2))))
            pairs.add((low, high))
    return pairs


def _in_order_game_scores(fact_block: str) -> set[tuple[int, int]]:
    scores: set[tuple[int, int]] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            if "opponent_name" in node and "team_score" in node and "opponent_score" in node:
                scores.add((node["team_score"], node["opponent_score"]))
            if "team_a_meetings" in node and "team_b_meetings" in node:
                for meeting in (*node["team_a_meetings"], *node["team_b_meetings"]):
                    scores.add((meeting["team_score"], meeting["opponent_score"]))
            if "home_points" in node and "away_points" in node:
                scores.add((node["home_points"], node["away_points"]))
                scores.add((node["away_points"], node["home_points"]))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(json.loads(fact_block))
    return scores


@pytest.mark.parametrize("block_fixture", ["texas_2005_case", "texas_usc_2005"])
def test_swapped_score_beside_the_opponent_is_flagged_on_a_keener_block(
    cfb_conn: sqlite3.Connection, block_fixture: str, request: pytest.FixtureRequest
) -> None:
    """The #26 regression #166 introduced: 2005 Texas beat Oklahoma 45-12, and
    the Keener explanation quotes it, so (12, 45) is a string pair of the
    block. The swapped score beside Oklahoma is still Oklahoma's score, said
    backwards, on the team case and on the comparison alike."""
    block: str = request.getfixturevalue(block_fixture)
    assert (12, 45) in _string_pairs(block)
    assert (12, 45) not in _in_order_game_scores(block)

    assert _check(cfb_conn, "Texas beat Oklahoma 12-45.", block, "cfb") == [
        "Oklahoma's score should be stated 45-12, not 12-45"
    ]
    assert _check(cfb_conn, "Texas beat Oklahoma 45-12.", block, "cfb") == []


def test_swapped_score_beside_the_other_compared_teams_opponent_is_flagged_on_a_keener_block(
    cfb_conn: sqlite3.Connection, texas_usc_2005: str
) -> None:
    """USC beat Notre Dame 34-31; Notre Dame is `team_b`'s opponent, and the
    comparison's Keener explanations quote the score."""
    assert (31, 34) in _string_pairs(texas_usc_2005)
    assert (31, 34) not in _in_order_game_scores(texas_usc_2005)

    assert _check(cfb_conn, "USC beat Notre Dame 31-34.", texas_usc_2005, "cfb") == [
        "Notre Dame's score should be stated 34-31, not 31-34"
    ]
    assert _check(cfb_conn, "USC beat Notre Dame 34-31.", texas_usc_2005, "cfb") == []


def test_swapped_score_beside_the_opponent_is_flagged_on_another_keener_block(
    cfb_conn: sqlite3.Connection,
) -> None:
    """The reviewer's other measured escape: 2019 Kansas State (8-5-0) beat
    Kansas 38-10."""
    block = _team_case_block(cfb_conn, 2019, "Kansas State", "cfb")
    assert (10, 38) in _string_pairs(block)
    assert (10, 38) not in _in_order_game_scores(block)

    assert _check(cfb_conn, "Kansas State beat Kansas 10-38.", block, "cfb") == [
        "Kansas's score should be stated 38-10, not 10-38"
    ]
    assert _check(cfb_conn, "Kansas State beat Kansas 38-10.", block, "cfb") == []


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
                # No digit "1" here either (see the comment above).
                game_id=2008,
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


def _team_case_block(
    conn: sqlite3.Connection, year: int, team: str, sport: Sport, method: Method = "keener"
) -> str:
    case = build_team_case(conn, year, team, method=method, sport=sport)
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
    """#166: a record-shaped pair nearest a subject is a record claim, so 13-1
    is no longer reported as USC's score; with both subjects named and
    neither owning it, no team is named."""
    block = _comparison_block(cfb_conn, 2005, "Texas", "USC", "cfb")
    response = "Texas went 13-1 and USC went 12-1 in 2005."

    assert _check(cfb_conn, response, block, "cfb") == ["13-1 is not a stated record"]


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

    assert _check(cfb_conn, response, block, "cfb") == [
        "Georgia 2-0 matches no game; Georgia's real scores are 17-10 and 34-13"
    ]


# --- parenthetical record ---------------------------------------------------

PARENTHETICAL_2005 = "Texas ({record}) and USC (12-1) met in the Rose Bowl, and Texas won 41-38."


def test_parenthetical_record_is_grounded(cfb_conn: sqlite3.Connection) -> None:
    block = _comparison_block(cfb_conn, 2005, "Texas", "USC", "cfb")
    response = PARENTHETICAL_2005.format(record="13-0")

    assert _check(cfb_conn, response, block, "cfb") == []


def test_parenthetical_fabricated_record_is_still_flagged(cfb_conn: sqlite3.Connection) -> None:
    """#166: a parenthetical bound to a subject is that subject's record
    claim, so the message names the record, not a score."""
    block = _comparison_block(cfb_conn, 2005, "Texas", "USC", "cfb")
    response = PARENTHETICAL_2005.format(record="13-1")

    assert _check(cfb_conn, response, block, "cfb") == [
        "13-1 is not Texas's record; Texas's record is 13-0"
    ]


# --- W-L-T, using the NFL tie cluster in tests/fixtures/sport_fixture.py ----

TIE_TEAM_CASE = "The Kilo Kings tied the Mike Mustangs {tie_score} and went {record} in 2023."


def test_w_l_t_record_next_to_a_tied_opponent_is_grounded(nfl_conn: sqlite3.Connection) -> None:
    """#107's first comment ("went 8-8-1 ... tied the Minnesota Vikings
    26-26"), on the fixture's Kilo Kings (2-1-1 since #130's rematch), who
    tied the Mike Mustangs 17-17. The regex reads "2-1" out of "2-1-1";
    `ties` grounds the last 1."""
    block = _team_case_block(nfl_conn, 2023, "Kilo Kings", "nfl")
    response = TIE_TEAM_CASE.format(tie_score="17-17", record="2-1-1")

    assert _check(nfl_conn, response, block, "nfl") == []


def test_w_l_t_fabricated_record_is_still_flagged(nfl_conn: sqlite3.Connection) -> None:
    """#181 reads a W-L-T record as one claim, so "7-1-1" is checked as a
    record (it used to be read as the pair "7-1" and attributed to Mike
    Mustangs as a score). Its reverse, 1-7-1, is no subject's record; #166
    attributes it to Kilo Kings, the one subject the sentence names."""
    block = _team_case_block(nfl_conn, 2023, "Kilo Kings", "nfl")
    response = TIE_TEAM_CASE.format(tie_score="17-17", record="7-1-1")

    assert _check(nfl_conn, response, block, "nfl") == [
        "7-1-1 is not Kilo Kings's record; Kilo Kings's record is 2-1-1"
    ]


def test_w_l_t_fabricated_tie_score_beside_a_real_record_is_still_flagged(
    nfl_conn: sqlite3.Connection,
) -> None:
    block = _team_case_block(nfl_conn, 2023, "Kilo Kings", "nfl")
    response = TIE_TEAM_CASE.format(tie_score="17-7", record="2-1-1")

    assert _check(nfl_conn, response, block, "nfl") == [
        "Mike Mustangs 17-7 matches no game; Mike Mustangs's real scores are 17-17 and 31-14"
    ]


TIE_COMPARISON = (
    "Kilo Kings went {record} and Mike Mustangs went 0-2-1 after they tied 17-17 in 2023."
)


def test_w_l_t_records_of_both_compared_teams_are_grounded(nfl_conn: sqlite3.Connection) -> None:
    """Both compared teams have a tie and met each other (twice, #130), so
    both names carry a 17-17 head-to-head tuple: the comparison shape, with
    W-L-T records."""
    block = _comparison_block(nfl_conn, 2023, "Kilo Kings", "Mike Mustangs", "nfl")
    response = TIE_COMPARISON.format(record="2-1-1")

    assert _check(nfl_conn, response, block, "nfl") == []


def test_w_l_t_fabricated_record_in_a_comparison_is_still_flagged(
    nfl_conn: sqlite3.Connection,
) -> None:
    """#181 reads a W-L-T record as one claim, so "1-0-1" is checked as a
    record (it used to be read as the pair "1-0" and attributed to Kilo Kings
    as a score). Its reverse, 0-1-1, was Mike Mustangs's record until #130's
    rematch made them 0-2-1; now it is no subject's record, so no owner is
    named."""
    block = _comparison_block(nfl_conn, 2023, "Kilo Kings", "Mike Mustangs", "nfl")
    response = TIE_COMPARISON.format(record="1-0-1")

    assert _check(nfl_conn, response, block, "nfl") == ["1-0-1 is not a stated record"]


# ---------------------------------------------------------------------------
# issue #181: two fabrications that passed production grounding but not the
# independent smoke-eval checker. (1) A score pair in a sentence naming no
# team, whose numbers each occur somewhere in the block but never as one game
# ("They beat them 42-25."). (2) A subject record stated out of order, as a
# W-L-T ("0-13-0") or a W-L ("0-13") for a 13-0-0 team. Every block here is
# the real one the service hands Claude, from the committed fixture. 2005
# Texas is 13-0-0 and USC 12-1-0; 42 and 25 both occur in each block, but
# neither 42-25 nor 25-42 is a game (2019 LSU-Clemson was 42-25, so 2019 is
# not used). Each "stays grounded" probe is a real fact-block claim that one
# of the new rules could otherwise misread as a fabrication.
# ---------------------------------------------------------------------------


@pytest.fixture
def texas_2005_case(cfb_conn: sqlite3.Connection) -> str:
    return _team_case_block(cfb_conn, 2005, "Texas", "cfb")


@pytest.fixture
def texas_usc_2005(cfb_conn: sqlite3.Connection) -> str:
    return _comparison_block(cfb_conn, 2005, "Texas", "USC", "cfb")


# --- (1) a score pair in a sentence that names no team ----------------------


@pytest.mark.parametrize("block_fixture", ["texas_2005_case", "texas_usc_2005"])
def test_unnamed_sentence_score_mixing_numbers_from_different_rows_is_flagged(
    cfb_conn: sqlite3.Connection, block_fixture: str, request: pytest.FixtureRequest
) -> None:
    block: str = request.getfixturevalue(block_fixture)
    response = "Texas went 13-0 in 2005. They beat them 42-25."

    assert _check(cfb_conn, response, block, "cfb") == [
        "42-25 is not a score from any game in the facts"
    ]


@pytest.mark.parametrize("score", ["41-38", "38-41"])
def test_unnamed_sentence_real_game_score_in_either_order_is_grounded(
    cfb_conn: sqlite3.Connection, texas_2005_case: str, score: str
) -> None:
    """The Rose Bowl, 41-38, said from either side: which side is said first
    is attribution, which a sentence naming no team can't be held to. This
    Keener block's USC explanation also quotes "41-38", so the string-value
    allowance grounds 38-41 too; the Elo test below is the one that guards
    the either-order game-score allowance on its own."""
    response = f"Texas went 13-0 in 2005. They won it {score}."

    assert _check(cfb_conn, response, texas_2005_case, "cfb") == []


def _string_values(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _string_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _string_values(item)


@pytest.mark.parametrize("score", ["33-7", "7-33"])
def test_unnamed_sentence_real_game_score_in_either_order_is_grounded_on_an_elo_block(
    cfb_conn: sqlite3.Connection, score: str
) -> None:
    """2001 Miami beat Penn State 33-7. An Elo block carries no explanation
    strings (`rating_breakdown.entries` is empty), so nothing but the game
    tuple can ground 7-33: removing the either-order game-score allowance
    for sentences naming no team turns this red."""
    block = _team_case_block(cfb_conn, 2001, "Miami", "cfb", method="elo")
    facts = json.loads(block)
    assert facts["rating_breakdown"]["entries"] == []
    assert not [text for text in _string_values(facts) if any(ch.isdigit() for ch in text)]
    response = f"Miami went 12-0 in 2001. That one ended {score}."

    assert _check(cfb_conn, response, block, "cfb") == []


def test_unnamed_sentence_breakdown_record_in_order_is_grounded(
    cfb_conn: sqlite3.Connection, texas_2005_case: str
) -> None:
    """2005 Texas's `rating_breakdown` carries a 2-0 series record against one
    opponent. 2-0 is no game score (either order) and no pair in a string
    value, so only the any-object (wins, losses) allowance grounds it."""
    response = "Texas went 13-0 in 2005. They went 2-0 against that one opponent."

    assert _check(cfb_conn, response, texas_2005_case, "cfb") == []


def test_unnamed_sentence_score_pair_inside_a_string_value_is_grounded(
    cfb_conn: sqlite3.Connection, texas_usc_2005: str
) -> None:
    """The 2005 comparison's explanation strings quote 42-17, which is no game
    tuple in that block and no (wins, losses): only the string-value
    allowance grounds it."""
    response = "Texas went 13-0 in 2005. That one ended 42-17."

    assert _check(cfb_conn, response, texas_usc_2005, "cfb") == []


# --- (2) a subject record stated out of order -------------------------------


@pytest.mark.parametrize("block_fixture", ["texas_2005_case", "texas_usc_2005"])
def test_w_l_t_subject_record_stated_out_of_order_is_flagged(
    cfb_conn: sqlite3.Connection, block_fixture: str, request: pytest.FixtureRequest
) -> None:
    block: str = request.getfixturevalue(block_fixture)
    response = "Texas went 0-13-0 in 2005."

    assert _check(cfb_conn, response, block, "cfb") == [
        "0-13-0 is not a stated record; Texas's record is 13-0-0"
    ]


def test_w_l_t_record_matching_no_subject_either_way_is_flagged(
    cfb_conn: sqlite3.Connection, texas_2005_case: str
) -> None:
    """#166: the sentence names Texas, so the message says whose record it
    is not, and what that record is."""
    response = "Texas went 13-1-0 in 2005."

    assert _check(cfb_conn, response, texas_2005_case, "cfb") == [
        "13-1-0 is not Texas's record; Texas's record is 13-0-0"
    ]


@pytest.mark.parametrize("block_fixture", ["texas_2005_case", "texas_usc_2005"])
def test_w_l_t_subject_record_in_order_is_grounded(
    cfb_conn: sqlite3.Connection, block_fixture: str, request: pytest.FixtureRequest
) -> None:
    block: str = request.getfixturevalue(block_fixture)
    response = "Texas went 13-0-0 in 2005."

    assert _check(cfb_conn, response, block, "cfb") == []


@pytest.mark.parametrize("block_fixture", ["texas_2005_case", "texas_usc_2005"])
def test_w_l_subject_record_stated_out_of_order_is_flagged(
    cfb_conn: sqlite3.Connection, block_fixture: str, request: pytest.FixtureRequest
) -> None:
    """One string, not also the named-sentence relational "Texas 0-13" the
    comparison block used to produce."""
    block: str = request.getfixturevalue(block_fixture)
    response = "Texas went 0-13 in 2005."

    assert _check(cfb_conn, response, block, "cfb") == [
        "0-13 is not a stated record; Texas's record is 13-0"
    ]


def test_second_compared_teams_record_stated_out_of_order_is_flagged(
    cfb_conn: sqlite3.Connection, texas_usc_2005: str
) -> None:
    """The owner named is whoever's record the reverse is -- team_b here,
    never just the first subject."""
    response = "USC went 1-12 in 2005."

    assert _check(cfb_conn, response, texas_usc_2005, "cfb") == [
        "1-12 is not a stated record; USC's record is 12-1"
    ]


@pytest.mark.parametrize("block_fixture", ["texas_2005_case", "texas_usc_2005"])
def test_w_l_subject_record_out_of_order_in_an_unnamed_sentence_is_flagged(
    cfb_conn: sqlite3.Connection, block_fixture: str, request: pytest.FixtureRequest
) -> None:
    block: str = request.getfixturevalue(block_fixture)
    response = "They went 0-13 in 2005."

    assert _check(cfb_conn, response, block, "cfb") == [
        "0-13 is not a stated record; Texas's record is 13-0"
    ]


def test_reversed_record_owned_by_both_compared_teams_names_no_owner() -> None:
    """No fixture comparison has two subjects with the same record, so this
    is hand-typed: both teams went 12-1. Naming either one as the owner of
    12-1 would pick a team the sentence may not be about, so no owner is
    named."""
    fact_block = (
        '{"team_a": {"team_name": "Texas", "wins": 12, "losses": 1, "ties": 0}, '
        '"team_b": {"team_name": "USC", "wins": 12, "losses": 1, "ties": 0}}'
    )
    response = "They went 1-12."

    assert find_ungrounded_tokens(response, fact_block, KNOWN_TEAMS) == [
        "1-12 is not a stated record"
    ]


def test_string_value_score_equal_to_a_reversed_record_is_not_read_as_a_record(
    cfb_conn: sqlite3.Connection,
) -> None:
    """The 2013 Florida State (team_a, 14-0-0) vs Michigan State (team_b,
    13-1-0) comparison: an explanation string in Michigan State's
    `rating_breakdown` quotes a 14-0 win. "0-14" is that score said from the
    other side, not Florida State's record read backwards, so the reversed-
    record rule steps aside for a pair a string value states (#181's accepted
    trade-off, like #107's)."""
    block = _comparison_block(cfb_conn, 2013, "Florida State", "Michigan State", "cfb")
    response = "That one ended 0-14."

    assert _check(cfb_conn, response, block, "cfb") == []


def test_real_game_score_equal_to_a_reversed_record_is_not_read_as_a_record() -> None:
    """No fixture season has a game whose score is its subject's record
    reversed, so this is hand-typed: a 3-1 team that lost a game 1-3. "1-3"
    is that game, said in order, not the record read backwards."""
    fact_block = (
        '{"team_name": "Texas", "year": 2005, "wins": 3, "losses": 1, "ties": 0, '
        '"games": [{"opponent_name": "USC", "team_score": 1, "opponent_score": 3}]}'
    )
    response = "Texas went 3-1. They lost one 1-3."

    assert find_ungrounded_tokens(response, fact_block, KNOWN_TEAMS) == []


# ---------------------------------------------------------------------------
# issue #255: when a name carries two or more real score tuples, the retry
# feedback used to name only the wrong pair ("Mike Mustangs 17-7"), so the
# narrator was told what was wrong but not what the real pairs are. Since
# #249 every NFL division opponent in a comparison carries both meetings, so
# every wrong-order score against a division rival hit that bare form. The
# message now lists the real tuples (ascending, so the set's iteration order
# never leaks into the wording) while still not asserting a single "correct"
# order. The one-tuple form is unchanged byte for byte.
# ---------------------------------------------------------------------------


class _ScriptedNarrator:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[list[dict[str, str]]] = []

    def complete(self, *, system: str, messages: list[dict[str, str]]) -> str:
        self.calls.append(messages)
        return self.responses.pop(0)


def test_two_tuple_mismatch_lists_both_real_scores_ascending() -> None:
    message = _mismatch_message("Texas", (12, 45), {(45, 12), (24, 20)})

    assert message == "Texas 12-45 matches no game; Texas's real scores are 24-20 and 45-12"


def test_three_tuple_mismatch_lists_all_real_scores_ascending() -> None:
    message = _mismatch_message("Texas", (12, 45), {(45, 12), (24, 20), (31, 7)})

    assert message == "Texas 12-45 matches no game; Texas's real scores are 24-20, 31-7 and 45-12"


def test_one_tuple_mismatch_message_is_unchanged() -> None:
    """Byte-identical to the pre-#255 form, so every expectation on it above
    stays green untouched."""
    message = _mismatch_message("Texas", (12, 45), {(45, 12)})

    assert message == "Texas's score should be stated 45-12, not 12-45"


def test_two_tuple_mismatch_on_a_real_team_case_lists_both_meetings(
    nfl_conn: sqlite3.Connection,
) -> None:
    """The fixture's Kilo Kings met Mike Mustangs twice (17-17, then 31-14),
    so a Kilo Kings team case gives Mike Mustangs exactly two tuples."""
    block = _team_case_block(nfl_conn, 2023, "Kilo Kings", "nfl")
    response = "The Kilo Kings beat the Mike Mustangs 14-31 in the rematch."

    assert _check(nfl_conn, response, block, "nfl") == [
        "Mike Mustangs 14-31 matches no game; Mike Mustangs's real scores are 17-17 and 31-14"
    ]


def test_retry_feedback_lists_every_real_score_of_a_twice_met_rival(
    nfl_conn: sqlite3.Connection,
) -> None:
    """End to end through `narrate()`: on the Kilo Kings vs Lima Lions
    comparison, Mike Mustangs is the common opponent Kilo Kings met twice
    (both meetings carried since #249) and Lima Lions met once, so the name
    holds three real tuples. A wrong-order rematch score in the first draft
    must send the retry a user turn naming all three, not just the wrong
    pair."""
    block = _comparison_block(nfl_conn, 2023, "Kilo Kings", "Lima Lions", "nfl")
    grounded = "Kilo Kings beat Mike Mustangs 31-14 in the rematch."
    narrator = _ScriptedNarrator(["Kilo Kings beat Mike Mustangs 14-31 in the rematch.", grounded])

    result = narrate(
        fact_block_json=block,
        user_team=None,
        contested=False,
        known_team_names=list_all_team_names(nfl_conn, "nfl"),
        narrator=narrator,
        fallback_text="Kilo Kings over Lima Lions, says the math.",
    )

    assert result == NarrationResult(text=grounded, is_fallback=False)
    assert len(narrator.calls) == 2
    feedback = narrator.calls[1][-1]
    assert feedback["role"] == "user"
    assert (
        "Mike Mustangs 14-31 matches no game; "
        "Mike Mustangs's real scores are 17-17, 27-10 and 31-14" in feedback["content"]
    )
