"""Failing-first tests for issue #166: a stated record and a stated rating
are tied to the team the sentence says they belong to.

Before this, "Texas went 12-1" passed on the 2005 Texas-vs-USC comparison
because 12-1 is *some* subject's record (USC's, #107's skip), and "Elo has
Texas at 1892" passed because 1892 is *some* rating in the block (USC's,
#162's rounding). Both are now checked against the team named nearest the
claim, with the same sentence-scoped, parenthetical-vs-bare attribution the
score rule uses (#26) and the same documented limit: a bare claim is rescued
when another team named in the same sentence owns it, so a two-team swap in
one sentence goes uncaught (asserted below, so the trade-off stays visible).

Every fact block here is the real one `api.persona.service` hands Claude,
built the way the routes build it (`build_team_case`/`build_comparison` ->
`TeamCaseOut`/`ComparisonResultOut.from_dataclass(...)` -> the service's own
`team_case_fact_block_json`/`comparison_fact_block_json`) against the
committed `cfb_verdict_fixture.sqlite3` (2005 Texas 13-0-0 vs USC 12-1-0)
and the NFL tie cluster in `tests/fixtures/sport_fixture.py` (2023 Kilo
Kings 2-1-1 vs Mike Mustangs 0-2-1). The one hand-typed block is the
multi-valued-name case, which no fixture expresses.

Real values these tests lean on, pinned in
`test_fixture_values_these_tests_rely_on`:

* Elo: Texas `1933.1932908945062` (shown "1933"), USC `1891.8303466707475`
  ("1892"); Oklahoma's `opponent_rating` `1714.83...` ("1715"). Keener:
  Texas `0.005044108672990355` ("5.04"), USC `0.004736299273644764`
  ("4.74"); Oklahoma "4.16". None of "1892", "1933", "4.74", "5.04" is a
  number token of any 2005 block once the rating literals are removed, so
  each is grounded *only* as a rating and is subject to attribution.
* "15" is a number token of the Texas Elo team case (so "15-0" there is a
  pure attribution catch) and not of the Keener one.
* The USC Elo team case carries Texas's rating (`1933.19...`) as the
  `opponent_rating` of USC's loss to Texas, so "Texas at 1933.1932908945062"
  is a true statement there; the exact-literal message form is proved with
  the same number said about USC instead.
* NFL Keener: Kilo Kings `0.25` (shown "250.00"), Mike Mustangs `0.15`
  ("150.00"), Lima Lions `0.35` ("350.00"), November Nomads `0.05`
  ("50.00").
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

from api.deps import list_all_team_names
from api.models import ComparisonResultOut, Method, Sport, TeamCaseOut
from api.persona.grounding import find_ungrounded_tokens
from api.persona.service import comparison_fact_block_json, team_case_fact_block_json

FIXTURE_DB = Path(__file__).parent / "fixtures" / "cfb_verdict_fixture.sqlite3"
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_RATING_LITERAL_RE = re.compile(
    r'("(?:rating|opponent_rating)":\s*)(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)'
)


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
    conn: sqlite3.Connection, year: int, team: str, sport: Sport, method: Method
) -> str:
    case = build_team_case(conn, year, team, method=method, sport=sport)
    return team_case_fact_block_json(TeamCaseOut.from_dataclass(case))


def _comparison_block(
    conn: sqlite3.Connection, year: int, team_a: str, team_b: str, sport: Sport, method: Method
) -> str:
    comparison = build_comparison(conn, year, team_a, team_b, method=method, sport=sport)
    return comparison_fact_block_json(ComparisonResultOut.from_dataclass(comparison))


def _check(conn: sqlite3.Connection, response: str, fact_block: str, sport: Sport) -> list[str]:
    return find_ungrounded_tokens(response, fact_block, list_all_team_names(conn, sport))


# --- the blocks, by name, so parametrized tests read as prose ----------------

CFB_BLOCKS = ["texas_case_elo", "texas_case_keener", "compare_elo", "compare_keener"]
NFL_BLOCKS = ["kilo_case", "kilo_compare"]


def _block(
    request: pytest.FixtureRequest, cfb_conn: sqlite3.Connection, nfl_conn: sqlite3.Connection
) -> tuple[str, Sport, sqlite3.Connection]:
    name: str = request.param
    if name == "texas_case_elo":
        return _team_case_block(cfb_conn, 2005, "Texas", "cfb", "elo"), "cfb", cfb_conn
    if name == "texas_case_keener":
        return _team_case_block(cfb_conn, 2005, "Texas", "cfb", "keener"), "cfb", cfb_conn
    if name == "compare_elo":
        return _comparison_block(cfb_conn, 2005, "Texas", "USC", "cfb", "elo"), "cfb", cfb_conn
    if name == "compare_keener":
        return _comparison_block(cfb_conn, 2005, "Texas", "USC", "cfb", "keener"), "cfb", cfb_conn
    if name == "usc_case_elo":
        return _team_case_block(cfb_conn, 2005, "USC", "cfb", "elo"), "cfb", cfb_conn
    if name == "kilo_case":
        return _team_case_block(nfl_conn, 2023, "Kilo Kings", "nfl", "keener"), "nfl", nfl_conn
    if name == "kilo_compare":
        block = _comparison_block(nfl_conn, 2023, "Kilo Kings", "Mike Mustangs", "nfl", "keener")
        return block, "nfl", nfl_conn
    raise AssertionError(name)


@pytest.fixture
def block(
    request: pytest.FixtureRequest, cfb_conn: sqlite3.Connection, nfl_conn: sqlite3.Connection
) -> tuple[str, Sport, sqlite3.Connection]:
    return _block(request, cfb_conn, nfl_conn)


def _blanked_number_tokens(fact_block: str) -> set[str]:
    """The block's number tokens with every `rating` / `opponent_rating`
    literal removed: what a token has to be absent from to be grounded only
    as a rating."""
    return set(_NUMBER_RE.findall(_RATING_LITERAL_RE.sub(r"\1null", fact_block)))


def test_fixture_values_these_tests_rely_on(
    cfb_conn: sqlite3.Connection, nfl_conn: sqlite3.Connection
) -> None:
    texas_elo = _team_case_block(cfb_conn, 2005, "Texas", "cfb", "elo")
    texas_keener = _team_case_block(cfb_conn, 2005, "Texas", "cfb", "keener")
    usc_elo = _team_case_block(cfb_conn, 2005, "USC", "cfb", "elo")
    compare_elo = _comparison_block(cfb_conn, 2005, "Texas", "USC", "cfb", "elo")
    compare_keener = _comparison_block(cfb_conn, 2005, "Texas", "USC", "cfb", "keener")
    kilo_compare = _comparison_block(nfl_conn, 2023, "Kilo Kings", "Mike Mustangs", "nfl", "keener")

    for block in (texas_elo, texas_keener, compare_elo, compare_keener):
        assert '"team_name":"Texas"' in block
    for block in (texas_elo, texas_keener, usc_elo, compare_elo, compare_keener):
        assert not {"1892", "1933", "4.74", "5.04", "1891"} & _blanked_number_tokens(block)
    assert '"rating":1933.1932908945062' in texas_elo
    assert '"opponent_rating":1891.8303466707475' in texas_elo
    assert '"opponent_rating":1714.8314369251768' in texas_elo
    assert '"rating":0.005044108672990355' in texas_keener
    assert '"opponent_rating":0.004736299273644764' in texas_keener
    assert '"opponent_rating":0.0041587932077007525' in texas_keener
    assert "15" in _blanked_number_tokens(texas_elo)
    assert "15" not in _NUMBER_RE.findall(texas_keener)
    # The USC Elo case names Texas as an opponent with Texas's own rating.
    assert '"rating":1891.8303466707475' in usc_elo
    assert '"opponent_name":"Texas"' in usc_elo
    assert '"opponent_rating":1933.1932908945062' in usc_elo
    for block in (compare_elo, compare_keener):
        data = json.loads(block)
        assert (data["team_a"]["wins"], data["team_a"]["losses"], data["team_a"]["ties"]) == (
            13,
            0,
            0,
        )
        assert (data["team_b"]["wins"], data["team_b"]["losses"], data["team_b"]["ties"]) == (
            12,
            1,
            0,
        )
    assert '"rating":1891.8303466707475' in compare_elo
    assert '"rating":0.004736299273644764' in compare_keener
    nfl = json.loads(kilo_compare)
    assert (nfl["team_a"]["team_name"], nfl["team_a"]["wins"], nfl["team_a"]["losses"]) == (
        "Kilo Kings",
        2,
        1,
    )
    assert (nfl["team_b"]["team_name"], nfl["team_b"]["wins"], nfl["team_b"]["losses"]) == (
        "Mike Mustangs",
        0,
        2,
    )
    assert '"rating":0.25' in kilo_compare
    assert '"rating":0.15' in kilo_compare


# ---------------------------------------------------------------------------
# A. a record is the named team's record
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("block", CFB_BLOCKS, indirect=True)
def test_another_subjects_record_stated_about_texas_is_flagged(
    block: tuple[str, Sport, sqlite3.Connection],
) -> None:
    """The issue's own sentence: 12-1 is USC's record, said about Texas. On
    the comparison #107's skip used to ground it as "some subject's record";
    on the team case, where USC is not a subject, the digits alone did."""
    fact_block, sport, conn = block

    assert _check(conn, "Texas went 12-1 this year.", fact_block, sport) == [
        "12-1 is not Texas's record; Texas's record is 13-0"
    ]


@pytest.mark.parametrize("block", ["compare_elo", "compare_keener"], indirect=True)
def test_another_subjects_w_l_t_record_stated_about_texas_is_flagged(
    block: tuple[str, Sport, sqlite3.Connection],
) -> None:
    fact_block, sport, conn = block

    assert _check(conn, "Texas went 12-1-0.", fact_block, sport) == [
        "12-1-0 is not Texas's record; Texas's record is 13-0-0"
    ]


@pytest.mark.parametrize("block", CFB_BLOCKS, indirect=True)
def test_invented_record_stated_about_texas_is_flagged_with_the_record_message(
    block: tuple[str, Sport, sqlite3.Connection],
) -> None:
    """15-0 is nobody's record. On the Texas Elo case "15" is a real token
    and Texas has no game tuples, so before #166 nothing flagged it; the
    Keener case also reports the bare "15" by membership, and the
    comparisons used to report it as a score ("Texas 15-0")."""
    fact_block, sport, conn = block

    assert "15-0 is not Texas's record; Texas's record is 13-0" in _check(
        conn, "Texas finished 15-0.", fact_block, sport
    )


@pytest.mark.parametrize("block", ["compare_elo", "compare_keener"], indirect=True)
def test_parenthetical_record_is_held_to_its_own_name_without_rescue(
    block: tuple[str, Sport, sqlite3.Connection],
) -> None:
    """USC is named in the sentence and 12-1 is USC's, but the parenthetical
    binds the record to Texas, so no other-team rescue applies."""
    fact_block, sport, conn = block

    assert _check(conn, "Texas (12-1) beat USC.", fact_block, sport) == [
        "12-1 is not Texas's record; Texas's record is 13-0"
    ]


@pytest.mark.parametrize("block", ["compare_elo", "compare_keener"], indirect=True)
def test_bare_record_nearer_the_other_team_is_rescued_by_its_owner(
    block: tuple[str, Sport, sqlite3.Connection],
) -> None:
    """ "Texas" sits nearer 12-1 than "USC" does, but USC is named in the
    sentence and 12-1 is USC's record."""
    fact_block, sport, conn = block

    assert _check(conn, "USC lost only to Texas, finishing 12-1.", fact_block, sport) == []


@pytest.mark.parametrize("block", ["compare_elo", "compare_keener"], indirect=True)
def test_two_team_record_swap_in_one_sentence_is_the_documented_limit(
    block: tuple[str, Sport, sqlite3.Connection],
) -> None:
    """Accepted trade-off, the same as #26's score rule: each bare record is
    rescued by the other team named in the sentence, so a swap of both goes
    uncaught. Asserted so that a future change to it is deliberate."""
    fact_block, sport, conn = block

    assert _check(conn, "Texas went 12-1 and USC went 13-0.", fact_block, sport) == []


def test_nfl_w_l_t_record_of_the_other_compared_team_is_flagged(
    nfl_conn: sqlite3.Connection,
) -> None:
    block = _comparison_block(nfl_conn, 2023, "Kilo Kings", "Mike Mustangs", "nfl", "keener")

    assert _check(nfl_conn, "Mike Mustangs went 2-1-1.", block, "nfl") == [
        "2-1-1 is not Mike Mustangs's record; Mike Mustangs's record is 0-2-1"
    ]


def test_bare_record_with_two_subjects_named_does_not_name_a_team(
    cfb_conn: sqlite3.Connection,
) -> None:
    """When the sentence names both compared teams and neither owns the
    record, the message never picks one (#181's reasoning): the sentence may
    be about either."""
    block = _comparison_block(cfb_conn, 2005, "Texas", "USC", "cfb", "elo")

    assert _check(cfb_conn, "Texas went 13-1 and USC went 12-1 in 2005.", block, "cfb") == [
        "13-1 is not a stated record"
    ]


def test_reversed_record_stated_about_its_owner_keeps_the_181_message(
    cfb_conn: sqlite3.Connection,
) -> None:
    block = _comparison_block(cfb_conn, 2005, "Texas", "USC", "cfb", "elo")

    assert _check(cfb_conn, "Texas went 0-13 in 2005.", block, "cfb") == [
        "0-13 is not a stated record; Texas's record is 13-0"
    ]


def test_score_said_about_a_non_subject_opponent_keeps_the_score_message(
    cfb_conn: sqlite3.Connection,
) -> None:
    """A record-shaped pair nearest a non-subject opponent with game data is
    still reported as that opponent's score (#107's shape), not as the
    subject's record."""
    block = _team_case_block(cfb_conn, 2005, "Texas", "cfb", "elo")

    assert _check(cfb_conn, "Texas went 13-0 with a 45-13 win over Oklahoma.", block, "cfb") == [
        "Oklahoma's score should be stated 45-12, not 45-13"
    ]


# ---------------------------------------------------------------------------
# B. a rating is the named team's rating
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("block", ["texas_case_elo", "compare_elo"], indirect=True)
def test_other_teams_elo_rating_stated_about_texas_is_flagged(
    block: tuple[str, Sport, sqlite3.Connection],
) -> None:
    """1892 is USC's Elo rating as the card shows it (`opponent_rating` in
    the team case, `team_b.rating` in the comparison), said about Texas."""
    fact_block, sport, conn = block

    assert _check(conn, "Elo has Texas at 1892.", fact_block, sport) == [
        "1892 is not Texas's rating; Texas's rating is 1933"
    ]


@pytest.mark.parametrize("block", ["texas_case_keener", "compare_keener"], indirect=True)
def test_other_teams_keener_display_rating_stated_about_texas_is_flagged(
    block: tuple[str, Sport, sqlite3.Connection],
) -> None:
    fact_block, sport, conn = block

    assert _check(conn, "Keener has Texas at 4.74.", fact_block, sport) == [
        "4.74 is not Texas's rating; Texas's rating is 5.04"
    ]


def test_parenthetical_rating_is_held_to_its_own_name(cfb_conn: sqlite3.Connection) -> None:
    """On the USC Elo case Texas is an opponent whose `opponent_rating` is
    Texas's own 1933.19; USC's 1892 in Texas's parenthetical is wrong."""
    block = _team_case_block(cfb_conn, 2005, "USC", "cfb", "elo")

    assert _check(cfb_conn, "Texas (1892) is rated.", block, "cfb") == [
        "1892 is not Texas's rating; Texas's rating is 1933"
    ]


def test_exact_literal_of_another_teams_rating_is_flagged_with_the_exact_literal(
    cfb_conn: sqlite3.Connection,
) -> None:
    """The exact-literal message form: a token that is no display value and
    no rounding gets the owner's rating as its JSON literal. Said about USC,
    because on this block "Texas at 1933.1932908945062" is simply true (the
    brief's sentence; pinned as grounded below)."""
    block = _team_case_block(cfb_conn, 2005, "USC", "cfb", "elo")

    assert _check(cfb_conn, "USC at 1933.1932908945062 is the exact number.", block, "cfb") == [
        "1933.1932908945062 is not USC's rating; USC's rating is 1891.8303466707475"
    ]
    assert _check(cfb_conn, "Texas at 1933.1932908945062 is the exact number.", block, "cfb") == []


def test_rounding_of_another_teams_rating_is_flagged_with_the_owner_rounded_alike(
    cfb_conn: sqlite3.Connection,
) -> None:
    """1891.8 is USC's rating rounded to one place (not a display value), so
    Texas's rating is reported rounded to one place too."""
    block = _team_case_block(cfb_conn, 2005, "Texas", "cfb", "elo")

    assert _check(cfb_conn, "Elo has Texas at 1891.8.", block, "cfb") == [
        "1891.8 is not Texas's rating; Texas's rating is 1933.2"
    ]


def test_grouped_rating_is_reported_as_written(cfb_conn: sqlite3.Connection) -> None:
    block = _team_case_block(cfb_conn, 2005, "Texas", "cfb", "elo")

    assert _check(cfb_conn, "Elo has Texas at 1,892.", block, "cfb") == [
        "1,892 is not Texas's rating; Texas's rating is 1933"
    ]


@pytest.mark.parametrize("block", ["texas_case_elo", "compare_elo"], indirect=True)
def test_two_team_rating_swap_in_one_sentence_is_the_documented_limit(
    block: tuple[str, Sport, sqlite3.Connection],
) -> None:
    """Each bare rating is rescued by the other team named in the sentence
    (the same trade-off as the record and score rules)."""
    fact_block, sport, conn = block

    assert _check(conn, "Elo has USC at 1933 and Texas at 1892.", fact_block, sport) == []


def test_rating_nearer_the_opponent_is_rescued_by_the_subject(cfb_conn: sqlite3.Connection) -> None:
    """ "them" is Texas, but "USC" is the nearest name to 1,933."""
    block = _team_case_block(cfb_conn, 2005, "Texas", "cfb", "elo")
    response = "Texas went 13-0, beat USC 41-38, and Elo has them at 1,933."

    assert _check(cfb_conn, response, block, "cfb") == []


@pytest.mark.parametrize(
    ("method", "response"),
    [
        ("keener", "Texas beat Oklahoma 45-12, and Keener had Oklahoma at 4.16."),
        ("elo", "Texas beat Oklahoma 45-12, and Elo had Oklahoma at 1715."),
    ],
)
def test_opponents_rating_beside_the_opponents_name_stays_grounded(
    cfb_conn: sqlite3.Connection, method: Method, response: str
) -> None:
    block = _team_case_block(cfb_conn, 2005, "Texas", "cfb", method)

    assert _check(cfb_conn, response, block, "cfb") == []


def test_rating_in_a_sentence_naming_no_team_is_not_attributed(
    cfb_conn: sqlite3.Connection,
) -> None:
    """No name, no attribution: 1892 is a real rating in the block, and the
    sentence does not say whose it is."""
    block = _team_case_block(cfb_conn, 2005, "Texas", "cfb", "elo")
    response = "Texas went 13-0 in 2005. The other rating came out to 1892."

    assert _check(cfb_conn, response, block, "cfb") == []


def test_name_with_two_distinct_ratings_gets_the_short_message() -> None:
    """No fixture block carries two different ratings under one name, so
    this is hand-typed: Texas's `rating` and its `opponent_rating` in USC's
    games disagree. Naming one as "Texas's rating" would not be true."""
    fact_block = json.dumps(
        {
            "method": "elo",
            "team_a": {
                "team_name": "Texas",
                "wins": 13,
                "losses": 0,
                "rating": 1933.5,
                "games": [
                    {
                        "opponent_name": "USC",
                        "opponent_rating": 1891.5,
                        "team_score": 41,
                        "opponent_score": 38,
                    }
                ],
            },
            "team_b": {
                "team_name": "USC",
                "wins": 12,
                "losses": 1,
                "rating": 1891.5,
                "games": [
                    {
                        "opponent_name": "Texas",
                        "opponent_rating": 1930.5,
                        "team_score": 38,
                        "opponent_score": 41,
                    }
                ],
            },
        }
    )
    known = ["Texas", "USC"]

    assert find_ungrounded_tokens("Elo has Texas at 1891.5.", fact_block, known) == [
        "1891.5 is not Texas's rating"
    ]
    assert find_ungrounded_tokens("Elo has Texas at 1930.5.", fact_block, known) == []
    assert find_ungrounded_tokens("Elo has Texas at 1933.5.", fact_block, known) == []


# ---------------------------------------------------------------------------
# false-positive probes: ordinary correct narrations on every block, mixing
# records, scores, ranks, the year, a display-value rating, a rounded rating
# and an opponent's rating beside the opponent's name. Includes responses the
# #107 / #162 / #165 / #181 suites accept, verbatim.
# ---------------------------------------------------------------------------

CORRECT_NARRATIONS: dict[str, list[str]] = {
    "texas_case_elo": [
        "Texas went 13-0 in 2005 and finished #1, and Elo has them at 1933.",
        "Texas beat USC 41-38 in the Rose Bowl, and Elo had USC at 1892.",
        "Elo rates Texas at 1933.2, and Ohio State, who they beat 25-22, sits at 1858.",
        "Oklahoma got run 45-12, and Elo had Oklahoma at 1715 for the year.",
        "Texas went 13-0, beat USC 41-38, and Elo has them at 1,933.",
        "Texas (13-0) and their 1933 Elo rating sit at #1 in 2005.",
        "USC (1892) lost to Texas 41-38.",
        "Colorado lost twice, 42-17 and 70-3, and Elo had Colorado at 1478.",
        "Texas's exact Elo number is 1933.1932908945062, and nobody's arguing.",
        "Elo rates Texas at 1933.19, and that's the whole argument.",
        "Elo rates Texas at 1933 and USC at 1892.",
        "Texas went 13-0-0 in 2005.",
        "Texas went 13-0 in 2005. That one ended 41-38.",
    ],
    "texas_case_keener": [
        "Texas went 13-0 in 2005 and finished #1, and Keener has them at 5.04.",
        "Texas beat USC 41-38 in the Rose Bowl, and Keener had USC at 4.74.",
        "Keener rates Texas at 0.005, and Ohio State, who they beat 25-22, sits at 4.55.",
        "Oklahoma got run 45-12, and Keener had Oklahoma at 4.16 for the year.",
        "Texas beat Oklahoma 45-12, and Keener had Oklahoma at 4.16.",
        "Texas (13-0) and their 5.04 Keener rating sit at #1 in 2005.",
        "USC (4.74) lost to Texas 41-38.",
        "Colorado lost twice, 42-17 and 70-3, and Keener had Colorado at 3.67.",
        "Keener rates Texas at 0.00504, top of the pile.",
        "Keener rates Texas at 5.04, and nobody's arguing.",
        "Texas went 13-0 in 2005. They won it 38-41.",
        "Texas went 13-0 in 2005. They went 2-0 against that one opponent.",
    ],
    "compare_elo": [
        "Texas went 13-0 and USC went 12-1 in 2005.",
        "Elo has Texas at 1,933 and USC at 1892, and Texas beat USC 41-38 to settle it.",
        "Texas (13-0) and USC (12-1) met in the Rose Bowl, and Texas won 41-38.",
        "USC lost only to Texas, finishing 12-1 with Elo at 1892.",
        "Texas beat Ohio State 25-22, and Elo had Ohio State at 1858.",
        "USC handled Oregon 45-13, and Elo had Oregon at 1726.",
        "Elo rates Texas at 1933.2 and USC at 1891.8 after a 13-0 and a 12-1 season.",
        "Texas went 13-0, beat USC 41-38, and Elo has them at 1,933.",
        "Notre Dame lost to USC 34-31, and Elo had Notre Dame at 1718.",
        "USC went 12-1 in 2005, ranked #2, and USC lost to Texas 38-41.",
        "Texas went 13-0-0 in 2005.",
    ],
    "compare_keener": [
        "Texas went 13-0 and USC went 12-1 in 2005.",
        "Keener has Texas at 5.04 and USC at 4.74, and Texas beat USC 41-38.",
        "Texas (13-0) and USC (12-1) met in the Rose Bowl, and Texas won 41-38.",
        "USC lost only to Texas, finishing 12-1 with Keener at 4.74.",
        "Texas beat Ohio State 25-22, and Keener had Ohio State at 4.55.",
        "USC handled Oregon 45-13, and Keener had Oregon at 4.36.",
        "Keener has Texas at 0.0050 and USC at 0.0047, and Texas beat USC 41-38.",
        "Texas went 13-0, beat USC 41-38, and Keener has them at 5.04.",
        "Notre Dame lost to USC 34-31, and Keener had Notre Dame at 4.18.",
        "Texas went 13-0 in 2005. That one ended 42-17.",
        "Texas went 13-0-0 in 2005.",
    ],
    "kilo_case": [
        "Kilo Kings went 2-1-1 in 2023, and Keener has them at 250.00.",
        "The Kilo Kings tied the Mike Mustangs 17-17 and went 2-1-1 in 2023.",
        "Kilo Kings lost to Lima Lions 13-20, and Keener had Lima Lions at 350.00.",
        "Keener rates Kilo Kings at 0.3, rank 6, after beating November Nomads 24-7.",
        "Mike Mustangs (150.00) tied Kilo Kings 17-17 and then lost 31-14.",
        "Kilo Kings (2-1-1) sit at rank 6 with a 0.25 Keener rating in 2023.",
        "November Nomads fell 24-7, and Keener had November Nomads at 50.00.",
        "Kilo Kings went 2-1-1 and beat Mike Mustangs 31-14 in the week 4 rematch.",
    ],
    "kilo_compare": [
        "Kilo Kings went 2-1-1 and Mike Mustangs went 0-2-1 after they tied 17-17 in 2023.",
        "Keener has Kilo Kings at 250.00 and Mike Mustangs at 150.00.",
        "Kilo Kings (2-1-1) beat Mike Mustangs (0-2-1) 31-14 in the rematch.",
        "Mike Mustangs lost to Kilo Kings 14-31, and Keener has Mike Mustangs at 0.2.",
        (
            "Both lost to Lima Lions, Kilo Kings 13-20 and Mike Mustangs 10-27, "
            "and Keener had Lima Lions at 350.00."
        ),
        "Kilo Kings went 2-1-1 in 2023, rank 6, with Keener at 0.25 exactly.",
        "Mike Mustangs went 0-2-1, and Keener's 0.15 says it all.",
        "Kilo Kings (250.00) and Mike Mustangs (150.00) tied 17-17 in 2023.",
    ],
}


@pytest.mark.parametrize(
    ("block", "response"),
    [
        pytest.param(name, response, id=f"{name}-{index}")
        for name, responses in CORRECT_NARRATIONS.items()
        for index, response in enumerate(responses)
    ],
    indirect=["block"],
)
def test_correct_narration_is_fully_grounded(
    block: tuple[str, Sport, sqlite3.Connection], response: str
) -> None:
    fact_block, sport, conn = block

    assert _check(conn, response, fact_block, sport) == []


def test_every_block_has_at_least_eight_probes() -> None:
    for name in CFB_BLOCKS + NFL_BLOCKS:
        assert len(CORRECT_NARRATIONS[name]) >= 8, name
