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

Round 2 (sections C and D below) closes two escapes the round-1 rules left:

* A comparison's top-level `verdict` string restates both subjects' ratings
  rounded ("Texas rates higher overall (1933.2 vs 1891.8, rank 1 vs 2)"), so
  on a comparison block "1891.8" used to be a plain number token, never
  rating-only, never attributed. Pinned in
  `test_fixture_verdict_states_both_ratings_rounded_and_nowhere_else`: the
  verdict-rounded pair per block is 2005 Elo `1933.2` / `1891.8`, Keener
  `0.005044` / `0.004736`; 2013 Florida State vs Michigan State Elo `1990.4` /
  `1924.0`, Keener `0.004567` / `0.004277`; NFL 2023 Kilo Kings vs Mike
  Mustangs Keener `0.250000` / `0.150000` (the raw literals there are `0.25`
  and `0.15`, so the message gives the exact literal, not a rounding).
* Known names used to be matched as raw substrings, so "Florida State" also
  registered a phantom "Florida" mention whose rating the bare rescue then
  accepted. On the 2013 Florida State case Florida's `opponent_rating` is
  `0.00299...` (shown "2.99") / `1409.59...` ("1410") against Florida
  State's `0.004567` ("4.57") / `1990.43` ("1990"); on the 2013 Michigan
  State case Michigan's is `1535.12` ("1535") against `1923.96` ("1924"); on
  the 2019 LSU case Georgia's is `1821.19` ("1821"), Georgia Southern's
  `1518.88` ("1519"), against LSU's `2044.43` ("2044"). 2005 Ohio State beat
  Miami (OH) 34-14 (Elo `1547.04`, "1547"); 2013 Michigan State beat Purdue
  14-0 (its record is 13-1-0).
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterator
from decimal import ROUND_HALF_UP, Decimal
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
    if name == "compare_2013_elo":
        block = _comparison_block(cfb_conn, 2013, "Florida State", "Michigan State", "cfb", "elo")
        return block, "cfb", cfb_conn
    if name == "compare_2013_keener":
        block = _comparison_block(
            cfb_conn, 2013, "Florida State", "Michigan State", "cfb", "keener"
        )
        return block, "cfb", cfb_conn
    if name == "compare_2019_elo":
        return _comparison_block(cfb_conn, 2019, "LSU", "Clemson", "cfb", "elo"), "cfb", cfb_conn
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


# ---------------------------------------------------------------------------
# C. a comparison's `verdict` string restates both ratings rounded (#166
# round 2): those roundings are rating-only tokens too, so they are
# attributed like any other rating.
# ---------------------------------------------------------------------------

_VERDICT_STRING_RE = re.compile(r'("verdict":\s*)"(?:[^"\\]|\\.)*"')

# (block, team_a, team_b, a's rating as the verdict states it, b's likewise,
#  a's rating as the message gives it, b's likewise). For CFB the message
#  form is the same rounding; for NFL the literals `0.25` / `0.15` have fewer
#  places than the verdict's `0.250000` / `0.150000`, so the token matches the
#  exact value, not a rounding, and the message gives the exact literal.
VERDICT_RATINGS = [
    pytest.param(
        "compare_elo", "Texas", "USC", "1933.2", "1891.8", "1933.2", "1891.8", id="2005-elo"
    ),
    pytest.param(
        "compare_keener",
        "Texas",
        "USC",
        "0.005044",
        "0.004736",
        "0.005044",
        "0.004736",
        id="2005-keener",
    ),
    pytest.param(
        "compare_2013_elo",
        "Florida State",
        "Michigan State",
        "1990.4",
        "1924.0",
        "1990.4",
        "1924.0",
        id="2013-elo",
    ),
    pytest.param(
        "compare_2013_keener",
        "Florida State",
        "Michigan State",
        "0.004567",
        "0.004277",
        "0.004567",
        "0.004277",
        id="2013-keener",
    ),
    pytest.param(
        "kilo_compare",
        "Kilo Kings",
        "Mike Mustangs",
        "0.250000",
        "0.150000",
        "0.25",
        "0.15",
        id="nfl-keener",
    ),
]
_VERDICT_PARAMS = ("block", "team_a", "team_b", "a_stated", "b_stated", "a_own", "b_own")


def _rating_word(fact_block: str) -> str:
    return "Keener" if json.loads(fact_block)["method"] == "keener" else "Elo"


@pytest.mark.parametrize(_VERDICT_PARAMS, VERDICT_RATINGS, indirect=["block"])
def test_fixture_verdict_states_both_ratings_rounded_and_nowhere_else(
    block: tuple[str, Sport, sqlite3.Connection],
    team_a: str,
    team_b: str,
    a_stated: str,
    b_stated: str,
    a_own: str,
    b_own: str,
) -> None:
    """The round-2 premise: each verdict-rounded rating is a number token of
    the block only because the verdict states it. With the rating literals
    blanked (round 1) it is still a plain token; with the verdict blanked too
    it is gone, so only a rating grounds it."""
    fact_block, _, _ = block
    data = json.loads(fact_block, parse_float=Decimal)

    assert (data["team_a"]["team_name"], data["team_b"]["team_name"]) == (team_a, team_b)
    assert a_stated in data["verdict"] and b_stated in data["verdict"]
    assert fact_block.count('"verdict"') == 1
    without_ratings = _RATING_LITERAL_RE.sub(r"\1null", fact_block)
    assert {a_stated, b_stated} <= set(_NUMBER_RE.findall(without_ratings))
    without_verdict = _VERDICT_STRING_RE.sub(r"\1null", without_ratings)
    assert not {a_stated, b_stated} & set(_NUMBER_RE.findall(without_verdict))
    for stated, own, rating in (
        (a_stated, a_own, data["team_a"]["rating"]),
        (b_stated, b_own, data["team_b"]["rating"]),
    ):
        assert rating.quantize(Decimal(stated), rounding=ROUND_HALF_UP) == Decimal(stated)
        # The message form (round 1): the owner's rating rounded to the
        # token's places when the token is a rounding of the literal, else
        # the exact literal (NFL's `0.25` has fewer places than `0.250000`).
        stated_places = -int(Decimal(stated).as_tuple().exponent)
        literal_places = -int(rating.as_tuple().exponent)
        assert own == (stated if stated_places < literal_places else format(rating, "f"))


@pytest.mark.parametrize(_VERDICT_PARAMS, VERDICT_RATINGS, indirect=["block"])
def test_other_compared_teams_verdict_rounded_rating_is_flagged(
    block: tuple[str, Sport, sqlite3.Connection],
    team_a: str,
    team_b: str,
    a_stated: str,
    b_stated: str,
    a_own: str,
    b_own: str,
) -> None:
    """The reviewer's escape: on a comparison block, the other team's rating
    rounded as the verdict rounds it, said about the named team, bare and
    parenthetical, in both directions. Round 1's message shape."""
    fact_block, sport, conn = block
    word = _rating_word(fact_block)
    about_a = [f"{b_stated} is not {team_a}'s rating; {team_a}'s rating is {a_own}"]
    about_b = [f"{a_stated} is not {team_b}'s rating; {team_b}'s rating is {b_own}"]

    assert _check(conn, f"{word} has {team_a} at {b_stated}.", fact_block, sport) == about_a
    assert _check(conn, f"{team_a} ({b_stated}) is rated.", fact_block, sport) == about_a
    assert _check(conn, f"{word} has {team_b} at {a_stated}.", fact_block, sport) == about_b
    assert _check(conn, f"{team_b} ({a_stated}) is rated.", fact_block, sport) == about_b


@pytest.mark.parametrize(_VERDICT_PARAMS, VERDICT_RATINGS, indirect=["block"])
def test_verdict_rounded_ratings_beside_their_own_names_stay_grounded(
    block: tuple[str, Sport, sqlite3.Connection],
    team_a: str,
    team_b: str,
    a_stated: str,
    b_stated: str,
    a_own: str,
    b_own: str,
) -> None:
    fact_block, sport, conn = block
    word = _rating_word(fact_block)
    responses = [
        f"{team_a} rates higher than {team_b}, {a_stated} vs {b_stated}.",
        f"{word} has {team_a} at {a_stated} and {team_b} at {b_stated}.",
        f"{team_b} ({b_stated}) trails {team_a} ({a_stated}).",
    ]

    for response in responses:
        assert _check(conn, response, fact_block, sport) == [], response


@pytest.mark.parametrize(_VERDICT_PARAMS, VERDICT_RATINGS, indirect=["block"])
def test_verdict_quoted_verbatim(
    block: tuple[str, Sport, sqlite3.Connection],
    team_a: str,
    team_b: str,
    a_stated: str,
    b_stated: str,
    a_own: str,
    b_own: str,
) -> None:
    """The engine's verdict quoted as-is. Every sentence of it that names both
    teams (the head-to-head and common-opponent sentences) stays grounded.
    Its last sentence, "<team_a> rates higher overall (<a> vs <b>, rank ...)",
    names only `team_a` once the response is split into sentences, so it is
    the one-name limit pinned in
    `test_single_name_sentence_quoting_both_ratings_is_the_documented_limit`:
    the retry feedback names the fix (say whose the second rating is)."""
    fact_block, sport, conn = block
    verdict: str = json.loads(fact_block)["verdict"]
    *both_named, rating_sentence = re.split(r"(?<=[.!?])\s+", verdict)
    limit = [f"{b_stated} is not {team_a}'s rating; {team_a}'s rating is {a_own}"]

    assert team_a in rating_sentence and team_b not in rating_sentence
    assert a_stated in rating_sentence and b_stated in rating_sentence
    for sentence in both_named:
        assert team_a in sentence and team_b in sentence, sentence
        assert _check(conn, sentence, fact_block, sport) == [], sentence
    assert _check(conn, rating_sentence, fact_block, sport) == limit
    assert _check(conn, verdict, fact_block, sport) == limit


@pytest.mark.parametrize("block", ["compare_elo", "compare_keener"], indirect=True)
def test_single_name_sentence_quoting_both_ratings_is_the_documented_limit(
    block: tuple[str, Sport, sqlite3.Connection],
) -> None:
    """Accepted trade-off, the same limit as #26's score rule and the
    two-team swap above: nearest-name attribution has one name to give a
    rating to, so a sentence naming one team while quoting both ratings
    hands the second rating to that team and flags it. Naming the other
    team rescues it (the bare rescue), which is what the retry feedback
    tells the narrator to do. Asserted so a future change is deliberate."""
    fact_block, sport, conn = block
    elo = _rating_word(fact_block) == "Elo"
    a_stated, b_stated = ("1933.2", "1891.8") if elo else ("0.005044", "0.004736")

    assert _check(conn, f"Texas rates higher, {a_stated} vs {b_stated}.", fact_block, sport) == [
        f"{b_stated} is not Texas's rating; Texas's rating is {a_stated}"
    ]
    assert (
        _check(conn, f"Texas rates higher than USC, {a_stated} vs {b_stated}.", fact_block, sport)
        == []
    )


@pytest.mark.parametrize(
    ("block", "response"),
    [
        pytest.param("compare_elo", "Texas beat USC 41-38 in week 1.", id="2005-h2h"),
        pytest.param(
            "compare_keener", "Texas (41-38) beat USC in the Rose Bowl.", id="2005-h2h-paren"
        ),
        pytest.param("compare_2019_elo", "LSU beat Clemson 42-25 in week 1.", id="2019-h2h"),
        pytest.param(
            "compare_2019_elo",
            "LSU beat Texas A&M 50-7 in week 14 and Clemson beat Texas A&M 24-10 in week 2.",
            id="2019-common-opponent",
        ),
        pytest.param(
            "compare_2019_elo",
            "LSU rates higher than Clemson, 2044.4 vs 1915.4, rank 1 vs 3.",
            id="2019-ratings-and-ranks",
        ),
        pytest.param(
            "kilo_compare",
            "Kilo Kings tied Mike Mustangs 17-17 in week 2 and beat them 31-14 in week 4.",
            id="nfl-h2h",
        ),
        pytest.param(
            "kilo_compare",
            "Kilo Kings lost to Lima Lions 13-20 and Mike Mustangs lost to Lima Lions 10-27.",
            id="nfl-common-opponent",
        ),
    ],
    indirect=["block"],
)
def test_scores_the_verdict_also_states_stay_grounded(
    block: tuple[str, Sport, sqlite3.Connection], response: str
) -> None:
    """Blanking the whole verdict string loses nothing but the rounded rating
    pair: every score, week and rank it quotes is a row of the block."""
    fact_block, sport, conn = block

    assert _check(conn, response, fact_block, sport) == []


# ---------------------------------------------------------------------------
# D. a name is a mention only when it stands on its own (#166 round 2): not
# glued to a word character, and not inside a longer known name.
# ---------------------------------------------------------------------------


def test_fixture_values_the_name_mention_tests_rely_on(cfb_conn: sqlite3.Connection) -> None:
    fsu_keener = _team_case_block(cfb_conn, 2013, "Florida State", "cfb", "keener")
    fsu_elo = _team_case_block(cfb_conn, 2013, "Florida State", "cfb", "elo")
    msu_elo = _team_case_block(cfb_conn, 2013, "Michigan State", "cfb", "elo")
    lsu_elo = _team_case_block(cfb_conn, 2019, "LSU", "cfb", "elo")
    osu_elo = _team_case_block(cfb_conn, 2005, "Ohio State", "cfb", "elo")
    known = set(list_all_team_names(cfb_conn, "cfb"))

    assert {"Florida", "Michigan", "Georgia", "Ohio", "Miami", "Texas"} <= known
    assert {"Florida State", "Western Michigan", "Georgia Southern", "Miami (OH)"} <= known
    assert {"Texas Tech", "Texas A&M", "Ohio State", "Michigan State"} <= known
    for block, own_rating, opponent, opponent_rating in (
        (fsu_keener, '"rating":0.004566992948687425', "Florida", "0.0029902972687814067"),
        (fsu_elo, '"rating":1990.4284849870103', "Florida", "1409.5921933737932"),
        (msu_elo, '"rating":1923.9553514326844', "Michigan", "1535.1193570414061"),
        (lsu_elo, '"rating":2044.432081520423', "Georgia", "1821.1921941233863"),
        (lsu_elo, '"rating":2044.432081520423', "Georgia Southern", "1518.8766007827535"),
        (osu_elo, '"rating":1858.4141852412133', "Miami (OH)", "1547.0423918950503"),
    ):
        assert own_rating in block
        assert f'"opponent_rating":{opponent_rating}' in block
        rows = [game for game in json.loads(block)["games"] if game["opponent_name"] == opponent]
        assert [str(row["opponent_rating"]) for row in rows] == [opponent_rating]
    for block, tokens in (
        (fsu_keener, {"2.99", "4.57"}),
        (fsu_elo, {"1410", "1990"}),
        (msu_elo, {"1535", "1924"}),
        (lsu_elo, {"1821", "1519", "2044"}),
        (osu_elo, {"1547"}),
    ):
        assert not tokens & _blanked_number_tokens(block)
    games = {
        (game["opponent_name"], game["team_score"], game["opponent_score"])
        for block in (fsu_elo, msu_elo, lsu_elo, osu_elo)
        for game in json.loads(block)["games"]
    }
    assert {
        ("Florida", 37, 7),
        ("Michigan", 29, 6),
        ("Western Michigan", 26, 13),
        ("Purdue", 14, 0),
        ("Georgia Southern", 55, 3),
        ("Georgia", 37, 10),
        ("Miami (OH)", 34, 14),
    } <= games
    msu = json.loads(msu_elo)
    assert (msu["wins"], msu["losses"], msu["ties"]) == (13, 1, 0)


@pytest.mark.parametrize(
    ("year", "team", "method", "response", "expected"),
    [
        pytest.param(
            2013,
            "Florida State",
            "keener",
            "Keener has Florida State at 2.99.",
            "2.99 is not Florida State's rating; Florida State's rating is 4.57",
            id="florida-inside-florida-state-keener",
        ),
        pytest.param(
            2013,
            "Florida State",
            "elo",
            "Elo has Florida State at 1410.",
            "1410 is not Florida State's rating; Florida State's rating is 1990",
            id="florida-inside-florida-state-elo",
        ),
        pytest.param(
            2013,
            "Michigan State",
            "elo",
            "Elo has Michigan State at 1535.",
            "1535 is not Michigan State's rating; Michigan State's rating is 1924",
            id="michigan-inside-michigan-state",
        ),
        pytest.param(
            2019,
            "LSU",
            "elo",
            "LSU beat Georgia Southern 55-3 and Elo has LSU at 1821.",
            "1821 is not LSU's rating; LSU's rating is 2044",
            id="georgia-inside-georgia-southern",
        ),
    ],
)
def test_rating_of_a_team_named_only_inside_a_longer_name_is_flagged(
    cfb_conn: sqlite3.Connection,
    year: int,
    team: str,
    method: Method,
    response: str,
    expected: str,
) -> None:
    """The validator's escape (67 of 7,764 narrations): the sentence never
    names Florida, Michigan or Georgia, but a substring match registered a
    phantom mention of each inside the longer name, and the bare rescue then
    accepted the phantom's rating for the team the sentence does name."""
    block = _team_case_block(cfb_conn, year, team, "cfb", method)

    assert _check(cfb_conn, response, block, "cfb") == [expected]


@pytest.mark.parametrize(
    ("year", "team", "method", "response"),
    [
        pytest.param(
            2013,
            "Florida State",
            "elo",
            "Florida State beat Florida 37-7 in 2013.",
            id="fsu-florida",
        ),
        pytest.param(
            2013,
            "Florida State",
            "keener",
            "Florida State beat Florida 37-7, and Keener had Florida at 2.99.",
            id="fsu-florida-rating",
        ),
        pytest.param(
            2013,
            "Florida State",
            "elo",
            "Florida (37-7) lost to Florida State, and Elo had Florida at 1410.",
            id="fsu-florida-paren",
        ),
        pytest.param(
            2013,
            "Michigan State",
            "elo",
            "Michigan State beat Michigan 29-6, and Elo had Michigan at 1535.",
            id="msu-michigan-rating",
        ),
        pytest.param(
            2013,
            "Michigan State",
            "elo",
            "Michigan State beat Western Michigan 26-13 and Michigan 29-6.",
            id="msu-western-michigan-and-michigan",
        ),
        pytest.param(
            2019,
            "LSU",
            "elo",
            "LSU beat Georgia Southern 55-3 and Georgia 37-10.",
            id="lsu-georgias",
        ),
        pytest.param(
            2019,
            "LSU",
            "elo",
            "LSU beat Georgia Southern 55-3, and Elo had Georgia Southern at 1519.",
            id="lsu-georgia-southern-rating",
        ),
        pytest.param(
            2019,
            "LSU",
            "elo",
            "LSU beat Georgia 37-10, and Elo had Georgia at 1821.",
            id="lsu-georgia-rating",
        ),
        pytest.param(
            2005,
            "Texas",
            "elo",
            "Texas beat Texas Tech 52-17 and Texas A&M 40-29.",
            id="texas-texases",
        ),
        pytest.param(
            2005,
            "Texas",
            "elo",
            "Texas beat Texas Tech 52-17, and Elo had Texas Tech at 1659.",
            id="texas-texas-tech-rating",
        ),
        pytest.param(
            2005,
            "Texas",
            "elo",
            "Texas beat Texas A&M 40-29, and Elo had Texas A&M at 1471.",
            id="texas-texas-am-rating",
        ),
        pytest.param(
            2005,
            "Texas",
            "elo",
            "Texas's record was 13-0, and Texas' Elo rating is 1933.",
            id="possessives",
        ),
        pytest.param(
            2005,
            "Ohio State",
            "elo",
            "Ohio State beat Miami (OH) 34-14, and Elo had Miami (OH) at 1547.",
            id="ohio-state-miami-oh",
        ),
        pytest.param(
            2005,
            "Ohio State",
            "elo",
            "Miami (OH) (34-14) lost to Ohio State.",
            id="miami-oh-paren",
        ),
    ],
)
def test_short_and_long_names_standing_on_their_own_stay_grounded(
    cfb_conn: sqlite3.Connection, year: int, team: str, method: Method, response: str
) -> None:
    """Both names are real mentions when each stands on its own, possessives
    included, and a parenthesized or ampersand name is one mention."""
    block = _team_case_block(cfb_conn, year, team, "cfb", method)

    assert _check(cfb_conn, response, block, "cfb") == []


@pytest.mark.parametrize(
    ("year", "team", "response", "expected"),
    [
        pytest.param(
            2019,
            "LSU",
            "LSU beat Georgia Southern 3-55 and Georgia 37-10.",
            "Georgia Southern's score should be stated 55-3, not 3-55",
            id="long-name-swapped",
        ),
        pytest.param(
            2019,
            "LSU",
            "LSU beat Georgia Southern 55-3 and Georgia 10-37.",
            "Georgia's score should be stated 37-10, not 10-37",
            id="short-name-swapped",
        ),
        pytest.param(
            2005,
            "Texas",
            "Texas beat Texas Tech 17-52.",
            "Texas Tech's score should be stated 52-17, not 17-52",
            id="texas-tech-swapped",
        ),
        pytest.param(
            2013,
            "Michigan State",
            "Michigan State beat Michigan 6-29.",
            "Michigan's score should be stated 29-6, not 6-29",
            id="michigan-swapped",
        ),
        pytest.param(
            2005,
            "Ohio State",
            "Ohio State beat Miami (OH) 14-34.",
            "Miami (OH)'s score should be stated 34-14, not 14-34",
            id="miami-oh-swapped",
        ),
    ],
)
def test_score_rule_is_unchanged_when_a_short_and_a_long_name_each_stand_on_their_own(
    cfb_conn: sqlite3.Connection, year: int, team: str, response: str, expected: str
) -> None:
    """#26's behaviour, pinned across the mention change: a swapped score
    beside either name is still that name's."""
    block = _team_case_block(cfb_conn, year, team, "cfb", "elo")

    assert _check(cfb_conn, response, block, "cfb") == [expected]


def test_wrong_record_equal_to_a_game_score_is_the_documented_limit(
    cfb_conn: sqlite3.Connection,
) -> None:
    """Accepted trade-off (reviewer nit on round 1): a two-part record claim
    about a subject is grounded when it is, in order, a game score the block
    states, so a wrong record that equals one goes uncaught. 2013 Michigan
    State (13-1-0) beat Purdue 14-0. The three-part form has no score to
    hide behind and is caught."""
    block = _team_case_block(cfb_conn, 2013, "Michigan State", "cfb", "elo")

    assert _check(cfb_conn, "Michigan State went 14-0 this year.", block, "cfb") == []
    assert _check(cfb_conn, "Michigan State went 14-0-0.", block, "cfb") == [
        "14-0-0 is not Michigan State's record; Michigan State's record is 13-1-0"
    ]
