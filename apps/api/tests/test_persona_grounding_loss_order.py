"""Failing-first tests for issue #228: a loss is stated winner-first, and
the grounding check accepts that form only when the sentence says the game
was lost.

Rule 5 of the persona prompt used to demand `team_score` first for every
score, so a loss had to read losing-score-first ("Florida got them 7-19"),
which nobody says. The founder's decision: a loss is said winner-first with
a loss cue ("lost 19-7 to Florida"). `api.persona.grounding` therefore
accepts, and only accepts, a hyphen pair attributed to opponent X that is
the reverse of one of X's real tuples `(team_score, opponent_score)` with
`team_score < opponent_score` -- a real loss for the subject -- when the
enclosing sentence contains `lost`, `fell` or `dropped` (whole words, any
case). Nothing else moves: a reversed *win* in a lost-sentence is still
flagged, a reversed loss in a sentence with no cue is still a swapped score,
and the subject-first loss form ("lost to Texas 38-41") stays grounded.

Every fact block here is the real one `api.persona.service` hands Claude,
built from the committed `cfb_verdict_fixture.sqlite3`: the 2005 USC team
case (12-1, its one loss 38-41 to Texas; a 34-31 win over Notre Dame), the
2005 Texas team case (13-0, beat USC 41-38) and the 2017 Alabama team case
(13-1, its one loss 14-26 to Auburn). The tuples these tests lean on are
pinned in `test_fixture_tuples_these_tests_rely_on`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from cfb_strength.db.connection import get_conn
from cfb_strength.evidence.proof import build_comparison, build_team_case

from api.models import ComparisonResultOut, Method, TeamCaseOut
from api.persona.grounding import (
    GROUNDING_VERSION,
    _extract_valid_score_tuples,
    find_ungrounded_tokens,
)
from api.persona.service import comparison_fact_block_json, team_case_fact_block_json
from api.repositories.teams import list_all_team_names

FIXTURE_DB = Path(__file__).parent / "fixtures" / "cfb_verdict_fixture.sqlite3"


@pytest.fixture
def cfb_conn() -> Iterator[sqlite3.Connection]:
    conn = get_conn(FIXTURE_DB, read_only=True)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def known(cfb_conn: sqlite3.Connection) -> list[str]:
    return list_all_team_names(cfb_conn, "cfb")


def _team_case_block(conn: sqlite3.Connection, year: int, team: str, method: Method) -> str:
    case = build_team_case(conn, year, team, method=method, sport="cfb")
    return team_case_fact_block_json(TeamCaseOut.from_dataclass(case))


# Both methods: the acceptance is about game tuples, which every method's
# block states the same way; a Keener block also quotes every score inside
# its `explanation` strings ("Lost a close one, 38-41"), which must neither
# rescue nor flag anything here.
@pytest.fixture(params=["keener", "elo"])
def usc_2005(cfb_conn: sqlite3.Connection, request: pytest.FixtureRequest) -> str:
    return _team_case_block(cfb_conn, 2005, "USC", request.param)


@pytest.fixture(params=["keener", "elo"])
def texas_2005(cfb_conn: sqlite3.Connection, request: pytest.FixtureRequest) -> str:
    return _team_case_block(cfb_conn, 2005, "Texas", request.param)


@pytest.fixture(params=["keener", "elo"])
def alabama_2017(cfb_conn: sqlite3.Connection, request: pytest.FixtureRequest) -> str:
    return _team_case_block(cfb_conn, 2017, "Alabama", request.param)


USC_LOSS_REVERSED = "Texas's score should be stated 38-41, not 41-38"
TEXAS_WIN_REVERSED = "USC's score should be stated 41-38, not 38-41"
NOTRE_DAME_WIN_REVERSED = "Notre Dame's score should be stated 34-31, not 31-34"


def test_fixture_tuples_these_tests_rely_on(
    usc_2005: str, texas_2005: str, alabama_2017: str
) -> None:
    usc = _extract_valid_score_tuples(usc_2005)
    assert usc["Texas"] == {(38, 41)}
    assert usc["Notre Dame"] == {(34, 31)}
    assert _extract_valid_score_tuples(texas_2005)["USC"] == {(41, 38)}
    assert _extract_valid_score_tuples(alabama_2017)["Auburn"] == {(14, 26)}


def test_grounding_version_moved_for_the_newly_accepted_form() -> None:
    # The checker newly accepts a form, so every narration cached under
    # grounding-v1 was checked under rules that no longer hold (#145).
    assert GROUNDING_VERSION == "grounding-v2"


# ---------------------------------------------------------------------------
# accepted: a real loss stated winner-first, in a sentence that says so
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "response",
    [
        # bare, the loss's winner nearest the pair
        "USC lost 41-38 to Texas in the Rose Bowl.",
        "USC fell 41-38 to Texas.",
        "USC dropped one 41-38 to Texas.",
        # the cue in any case
        "USC LOST 41-38 to Texas.",
        # bare, the sentence names no subject: the pair is checked against
        # the nearest name, Texas (#26's bare branch)
        "They dropped a 41-38 heartbreaker to Texas.",
        # bare, the subject nearest: the other-team rescue must apply the rule
        "USC lost 41-38 in the Rose Bowl to Texas.",
        # bare, another opponent nearest: `_check_bare_pair`'s rescue by the
        # other named team must apply the rule too
        "They fell 41-38 in a game Notre Dame fans loved, to Texas.",
        # parenthetical, bound to the winner
        "USC lost to Texas (41-38).",
        "The one blemish: Texas (41-38), and USC fell hard.",
        # two pairs in one sentence, a win stated team-first and the loss
        # winner-first
        "USC beat Notre Dame 34-31 but lost 41-38 to Texas.",
    ],
)
def test_reversed_loss_with_a_loss_cue_is_grounded(
    usc_2005: str, known: list[str], response: str
) -> None:
    assert find_ungrounded_tokens(response, usc_2005, known) == []


@pytest.mark.parametrize(
    "response",
    [
        "Alabama lost 26-14 to Auburn in the Iron Bowl.",
        "Alabama fell 26-14 to Auburn, and that was the whole story.",
        "Auburn (26-14) is the one Alabama dropped.",
    ],
)
def test_reversed_loss_with_a_loss_cue_is_grounded_on_another_block(
    alabama_2017: str, known: list[str], response: str
) -> None:
    assert find_ungrounded_tokens(response, alabama_2017, known) == []


# ---------------------------------------------------------------------------
# still flagged: a reversed loss in a sentence with no loss cue
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "response",
    [
        # #228's own shape, with the score the other way round
        "Texas got them 41-38.",
        "Texas got them 41-38 in the Rose Bowl.",
        "USC went down 41-38 to Texas.",
        # a noun ("loss") is not a cue; only lost / fell / dropped are
        "The 41-38 loss to Texas was the only one.",
        # the cue must be in the same sentence
        "USC lost one game. Texas got them 41-38.",
        # parenthetical, no cue
        "Texas (41-38) got them.",
        # the cue word glued inside another word is no cue
        "Texas got them 41-38 in the Rose Bowl, and USC's fans felled a few trees.",
    ],
)
def test_reversed_loss_without_a_loss_cue_is_still_flagged(
    usc_2005: str, known: list[str], response: str
) -> None:
    assert find_ungrounded_tokens(response, usc_2005, known) == [USC_LOSS_REVERSED]


def test_reversed_loss_without_a_loss_cue_is_still_flagged_on_another_block(
    alabama_2017: str, known: list[str]
) -> None:
    assert find_ungrounded_tokens("Auburn got them 26-14.", alabama_2017, known) == [
        "Auburn's score should be stated 14-26, not 26-14"
    ]


# ---------------------------------------------------------------------------
# still flagged: a reversed *win* in a sentence with a loss cue
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "response",
    [
        "Texas lost 38-41 to USC.",
        "Texas fell 38-41 to USC in the Rose Bowl.",
        "Texas dropped 38-41 to USC.",
        "Texas fell to USC (38-41).",
        "USC (38-41) lost to Texas.",
    ],
)
def test_reversed_win_with_a_loss_cue_is_still_flagged(
    texas_2005: str, known: list[str], response: str
) -> None:
    assert find_ungrounded_tokens(response, texas_2005, known) == [TEXAS_WIN_REVERSED]


@pytest.mark.parametrize(
    "response",
    [
        "USC lost 31-34 to Notre Dame.",
        "USC fell to Notre Dame (31-34).",
    ],
)
def test_reversed_win_with_a_loss_cue_is_still_flagged_on_a_team_with_a_loss(
    usc_2005: str, known: list[str], response: str
) -> None:
    # USC has a real loss (38-41 to Texas), so a block-wide "this team lost
    # something" must not make every reversed pair acceptable.
    assert find_ungrounded_tokens(response, usc_2005, known) == [NOTRE_DAME_WIN_REVERSED]


# ---------------------------------------------------------------------------
# unchanged: the subject-first loss form stays grounded, with or without a cue
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "response",
    [
        "USC lost to Texas 38-41.",
        "USC fell to Texas 38-41 in the Rose Bowl.",
        "USC lost to Texas (38-41).",
        "USC went 12-1, and Texas got them 38-41.",
        "USC went 12-1 in 2005, ranked #2, and USC lost to Texas 38-41.",
    ],
)
def test_subject_first_loss_is_still_grounded(
    usc_2005: str, known: list[str], response: str
) -> None:
    assert find_ungrounded_tokens(response, usc_2005, known) == []


def test_subject_first_loss_is_still_grounded_on_another_block(
    alabama_2017: str, known: list[str]
) -> None:
    assert find_ungrounded_tokens("Alabama fell to Auburn 14-26.", alabama_2017, known) == []


# ---------------------------------------------------------------------------
# a comparison block: the rule reads the same tuples there
# ---------------------------------------------------------------------------


def test_reversed_loss_on_a_comparison_block(
    cfb_conn: sqlite3.Connection, known: list[str]
) -> None:
    # 2013 Florida State vs Michigan State: Michigan State's `worst_loss` is
    # 13-17 to Notre Dame, the only row that states that game, so the block
    # carries (13, 17) under Notre Dame and nothing the other way round.
    comparison = build_comparison(
        cfb_conn, 2013, "Florida State", "Michigan State", method="keener", sport="cfb"
    )
    block = comparison_fact_block_json(ComparisonResultOut.from_dataclass(comparison))
    assert _extract_valid_score_tuples(block)["Notre Dame"] == {(13, 17)}

    assert find_ungrounded_tokens("Michigan State lost to Notre Dame 17-13.", block, known) == []
    assert find_ungrounded_tokens("Michigan State fell 17-13 to Notre Dame.", block, known) == []
    assert find_ungrounded_tokens("Michigan State played Notre Dame 17-13.", block, known) == [
        "Notre Dame's score should be stated 13-17, not 17-13"
    ]


# ---------------------------------------------------------------------------
# unchanged: a win stated team-first, and an invented pair, in a lost-sentence
# ---------------------------------------------------------------------------


def test_win_stated_team_first_in_a_lost_sentence_is_still_grounded(
    texas_2005: str, known: list[str]
) -> None:
    assert (
        find_ungrounded_tokens(
            "USC lost to Texas 41-38, and nobody else came close.", texas_2005, known
        )
        == []
    )


def test_invented_pair_in_a_lost_sentence_is_still_flagged(usc_2005: str, known: list[str]) -> None:
    # 42 and 17 are both tokens of the block (a rating_breakdown quotes
    # Arizona 42-21 and Hawai'i 63-17); 42-17 is no game of USC's.
    assert find_ungrounded_tokens("USC lost 42-17 to Texas.", usc_2005, known) == [
        "Texas's score should be stated 38-41, not 42-17"
    ]
