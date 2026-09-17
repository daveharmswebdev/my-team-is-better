"""A game score is resolved from the named team's side, and printed
winner-first (issue #292, epic #199).

This file is where `test_persona_grounding.py` (#26, #83, #107, #130, #181,
#255) and `test_persona_grounding_loss_order.py` (#228) end up. Both guarded a
*lexical* checker that found hyphen pairs in the narrator's finished prose,
guessed which team each belonged to by nearest name, and compared the pair
against that team's real tuples -- with a long tail of rules for the cases
that guess got wrong: a parenthetical pair binds to the name it hangs off; a
bare pair is rescued when another team in the sentence owns it; a subject's
own record is not a game score; a pair inside a JSON string value the block
quotes is not a claim; and a reversed pair is a real loss stated winner-first
only when the sentence carries `lost`, `fell` or `dropped`.

`api.persona.claims` removes the guessing. The narrator names the team, the
opponent and the result; the server finds that game in the block and prints
it. So none of those rules has anything left to govern, and what is kept here
is what they existed to protect:

* the winner is checked -- a claimed W that was really an L is rejected with
  the real result (section B);
* a loss prints winner-first, with no cue word needed anywhere and none
  granting anything (section C: #228's whole cue list is gone);
* a rematch is told apart by week, so the earlier meeting is reachable
  (section D, #130);
* a score the narrator types instead of claiming is rejected, and the retry
  feedback names every real score of the teams the sentence mentions
  (section E, #255).

Section A holds the two #200 spike narrations of this shape that the lexical
checker wrongly rejected, kept as regression probes.

Blocks and catalogs are the real ones production builds
(`tests/fixtures/claim_blocks.py`); the values they lean on are pinned in
`test_fixture_facts_these_tests_rely_on`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from cfb_strength.db.connection import get_conn
from fixtures.claim_blocks import (
    KILO_KINGS,
    LIMA_LIONS,
    MIKE_MUSTANGS,
    assert_an_error_says,
    catalog_of,
    cfb_catalog,
    cfb_comparison_block,
    cfb_team_case_block,
    game_claim,
    nfl_tie_comparison_block,
    rejected,
    rendered,
)
from fixtures.narrator_fake import FakeNarrator
from fixtures.sport_fixture import make_sport_fixture_db

from api.persona.narrate import NarrationResult, narrate
from api.repositories.teams import TeamRecord


@pytest.fixture(scope="module")
def catalog() -> tuple[TeamRecord, ...]:
    return cfb_catalog()


@pytest.fixture(scope="module")
def sport_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return make_sport_fixture_db(tmp_path_factory.mktemp("claims_scores_sport"))


@pytest.fixture(scope="module")
def nfl_catalog(sport_db: Path) -> tuple[TeamRecord, ...]:
    return catalog_of(sport_db, "nfl")


@pytest.fixture(scope="module")
def kilo_lima(sport_db: Path) -> str:
    return nfl_tie_comparison_block(sport_db)


@pytest.fixture(scope="module")
def usc_2005() -> str:
    return cfb_team_case_block(2005, "USC")


@pytest.fixture(scope="module")
def usc_2005_elo() -> str:
    return cfb_team_case_block(2005, "USC", method="elo")


@pytest.fixture(scope="module")
def texas_2005() -> str:
    return cfb_team_case_block(2005, "Texas")


@pytest.fixture(scope="module")
def alabama_2017() -> str:
    return cfb_team_case_block(2017, "Alabama")


@pytest.fixture(scope="module")
def texas_usc_2005() -> str:
    return cfb_comparison_block(2005, "Texas", "USC")


@pytest.fixture(scope="module")
def fsu_msu_2013() -> str:
    return cfb_comparison_block(2013, "Florida State", "Michigan State")


def _json(block: str) -> Any:
    return json.loads(block)


def test_fixture_facts_these_tests_rely_on(
    usc_2005: str, texas_2005: str, alabama_2017: str, fsu_msu_2013: str, kilo_lima: str
) -> None:
    """The real tuples the probes below quote, migrated from the pins in the
    two grounding suites this file replaces."""
    usc = _json(usc_2005)
    assert (usc["wins"], usc["losses"]) == (12, 1)
    loss = usc["worst_loss"]
    assert (loss["opponent_name"], loss["team_score"], loss["opponent_score"]) == ("Texas", 38, 41)
    notre_dame = [g for g in usc["games"] if g["opponent_name"] == "Notre Dame"]
    assert [(g["result"], g["team_score"], g["opponent_score"]) for g in notre_dame] == [
        ("W", 34, 31)
    ]

    texas = _json(texas_2005)
    assert (texas["wins"], texas["losses"]) == (13, 0)
    assert [
        (g["result"], g["team_score"], g["opponent_score"])
        for g in texas["games"]
        if g["opponent_name"] == "USC"
    ] == [("W", 41, 38)]

    alabama = _json(alabama_2017)
    assert [
        (g["result"], g["team_score"], g["opponent_score"])
        for g in alabama["games"]
        if g["opponent_name"] == "Auburn"
    ] == [("L", 14, 26)]

    # 2013 Michigan State's worst loss, 13-17 to Notre Dame, is the only row
    # stating that game: #228's comparison case.
    msu_loss = _json(fsu_msu_2013)["team_b"]["worst_loss"]
    assert (msu_loss["opponent_name"], msu_loss["team_score"], msu_loss["opponent_score"]) == (
        "Notre Dame",
        13,
        17,
    )

    # The NFL rematch cluster (#130, #255): Kilo Kings met Mike Mustangs twice
    # and Lima Lions met it once, so the name carries three real scores.
    (common,) = _json(kilo_lima)["common_opponents"]
    assert common["opponent_name"] == MIKE_MUSTANGS
    assert [
        (m["result"], m["team_score"], m["opponent_score"], m["week"])
        for m in common["team_a_meetings"]
    ] == [("T", 17, 17, 2), ("W", 31, 14, 4)]
    assert [
        (m["result"], m["team_score"], m["opponent_score"]) for m in common["team_b_meetings"]
    ] == [("W", 27, 10)]


# ---------------------------------------------------------------------------
# A. the #200 spike narrations the lexical checker wrongly rejected
#
# Three of its five false rejections were the same 41-38: USC's loss to Texas
# stated winner-first, which the checker only accepted when the sentence
# carried one of three cue words. "Texas got them 41-38" has none, and "the
# 41-38 loss to Texas" has the noun, not the verb -- the exact shape #228's
# docstring uses as its example ("lost 19-7 to Florida") with the cue removed.
# ---------------------------------------------------------------------------


def _usc_loss(claim_id: str = "g") -> dict[str, object]:
    return game_claim(claim_id, "game_score", "USC", "Texas", "L")


def test_spike_a_loss_stated_winner_first_with_no_cue_word(
    usc_2005: str, catalog: tuple[TeamRecord, ...]
) -> None:
    assert (
        rendered("Texas got them {g}.", [_usc_loss()], usc_2005, catalog) == "Texas got them 41-38."
    )


def test_spike_a_loss_behind_the_noun_rather_than_the_verb(
    usc_2005: str, catalog: tuple[TeamRecord, ...]
) -> None:
    assert (
        rendered("The {g} loss to Texas was the only one.", [_usc_loss()], usc_2005, catalog)
        == "The 41-38 loss to Texas was the only one."
    )


# ---------------------------------------------------------------------------
# B. the winner is checked
#
# #26's reason for existing: production served "USC beat Texas 41-38". The
# claim carries the result, so a wrong one is caught by resolution rather than
# by reading the prose around the number.
# ---------------------------------------------------------------------------


def test_a_claimed_win_that_was_really_a_loss_is_rejected_with_the_real_result(
    usc_2005: str, catalog: tuple[TeamRecord, ...]
) -> None:
    claim = game_claim("g", "game_score", "USC", "Texas", "W")

    errors = rejected("USC beat Texas {g}.", [claim], usc_2005, catalog)
    assert_an_error_says(errors, '"g"', "L 38-41")


def test_a_claimed_loss_that_was_really_a_win_is_rejected_with_the_real_result(
    usc_2005: str, catalog: tuple[TeamRecord, ...]
) -> None:
    claim = game_claim("g", "game_score", "USC", "Notre Dame", "L")

    errors = rejected("USC fell to Notre Dame {g}.", [claim], usc_2005, catalog)
    assert_an_error_says(errors, '"g"', "W 34-31")


def test_a_game_the_block_does_not_hold_is_rejected(
    usc_2005: str, catalog: tuple[TeamRecord, ...]
) -> None:
    """#26's invented-pair case ("USC lost 42-17 to Texas"): 42 and 17 are both
    number tokens of the block, and the lexical checker needed a tuple table to
    know they were never a game. There is no pair to invent now -- only a game,
    which either resolves or does not."""
    claim = game_claim("g", "game_score", "USC", "Alabama", "L")

    errors = rejected("USC lost {g} to Alabama.", [claim], usc_2005, catalog)
    assert_an_error_says(errors, '"g"', "Alabama")


# ---------------------------------------------------------------------------
# C. a loss prints winner-first, and no cue word is involved
#
# #228's whole rule: the checker accepted a reversed pair only inside a
# sentence containing `lost`, `fell` or `dropped` as whole words, in any case,
# which meant "The 41-38 loss" failed and "USC's fans felled a few trees" was
# carefully excluded. The rendering is winner-first unconditionally now, so
# every sentence in that suite's accepted *and* rejected lists is the same
# claim with different prose around it.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        # #228's accepted list, with the cue
        "USC lost {g} to Texas in the Rose Bowl.",
        "USC fell {g} to Texas.",
        "USC dropped one {g} to Texas.",
        "USC LOST {g} to Texas.",
        "They dropped a {g} heartbreaker to Texas.",
        # #228's rejected list: the same claim, in a sentence with no cue
        "Texas got them {g}.",
        "Texas got them {g} in the Rose Bowl.",
        "USC went down {g} to Texas.",
        "Texas ({g}) got them.",
        "Texas got them {g}, and USC's fans felled a few trees.",
        # the cue in an earlier sentence, which #228 had to exclude
        "USC lost one game. Texas got them {g}.",
    ],
)
def test_a_loss_prints_winner_first_whatever_the_sentence_says(
    usc_2005: str, catalog: tuple[TeamRecord, ...], text: str
) -> None:
    assert rendered(text, [_usc_loss()], usc_2005, catalog) == text.replace("{g}", "41-38")


@pytest.mark.parametrize("block_name", ["usc_2005", "usc_2005_elo"])
def test_the_winner_first_rendering_does_not_depend_on_the_method(
    request: pytest.FixtureRequest, catalog: tuple[TeamRecord, ...], block_name: str
) -> None:
    """#228 ran its whole suite under keener and elo, because a keener block
    also quotes every score inside its `explanation` strings ("Lost a close
    one, 38-41") and those must neither rescue nor flag anything. The claim
    reads the game rows, which both methods state identically."""
    block: str = request.getfixturevalue(block_name)

    assert rendered("Lost {g}.", [_usc_loss()], block, catalog) == "Lost 41-38."


def test_a_loss_on_a_comparison_block_prints_winner_first_too(
    fsu_msu_2013: str, catalog: tuple[TeamRecord, ...]
) -> None:
    """#228's comparison case: Michigan State's `worst_loss` 13-17 to Notre
    Dame is the only row stating that game."""
    claim = game_claim("g", "game_score", "Michigan State", "Notre Dame", "L")

    assert (
        rendered("Michigan State played Notre Dame {g}.", [claim], fsu_msu_2013, catalog)
        == "Michigan State played Notre Dame 17-13."
    )


def test_a_win_claimed_as_a_loss_is_not_rescued_by_a_cue_word(
    texas_2005: str, catalog: tuple[TeamRecord, ...]
) -> None:
    """#228's "a reversed win in a lost-sentence is still flagged": the cue is
    prose and decides nothing, the claimed result does."""
    claim = game_claim("g", "game_score", "Texas", "USC", "L")

    errors = rejected("Texas fell {g} to USC.", [claim], texas_2005, catalog)
    assert_an_error_says(errors, '"g"', "W 41-38")


def test_a_margin_of_a_loss_is_the_gap_not_a_negative_number(
    alabama_2017: str, catalog: tuple[TeamRecord, ...]
) -> None:
    claims = [
        game_claim("g", "game_score", "Alabama", "Auburn", "L"),
        game_claim("m", "margin", "Alabama", "Auburn", "L"),
    ]

    assert (
        rendered("Auburn got them {g}, by {m}.", claims, alabama_2017, catalog)
        == "Auburn got them 26-14, by 12."
    )


# ---------------------------------------------------------------------------
# D. a rematch is told apart by week (#130)
#
# #130's regression: the checker read only the *latest* meeting's tuple, so
# narrating the earlier one was flagged. A claim says which week.
# ---------------------------------------------------------------------------


def test_each_meeting_of_a_rematch_is_reachable_by_week(
    kilo_lima: str, nfl_catalog: tuple[TeamRecord, ...]
) -> None:
    claims = [
        game_claim("a", "game_score", KILO_KINGS, MIKE_MUSTANGS, "T", week=2),
        game_claim("b", "game_score", KILO_KINGS, MIKE_MUSTANGS, "W", week=4),
    ]

    assert (
        rendered("First {a}, then {b}.", claims, kilo_lima, nfl_catalog)
        == "First 17-17, then 31-14."
    )


def test_a_rematch_claimed_without_a_week_is_rejected_listing_the_meetings(
    kilo_lima: str, nfl_catalog: tuple[TeamRecord, ...]
) -> None:
    claim = game_claim("a", "game_score", KILO_KINGS, MIKE_MUSTANGS, "W")

    errors = rejected("They won {a}.", [claim], kilo_lima, nfl_catalog)
    assert_an_error_says(errors, '"a"', "week 2", "week 4")


def test_a_common_opponent_meeting_of_the_other_team_resolves_from_its_own_side(
    kilo_lima: str, nfl_catalog: tuple[TeamRecord, ...]
) -> None:
    claim = game_claim("g", "game_score", LIMA_LIONS, MIKE_MUSTANGS, "W")

    assert (
        rendered("Lima Lions handled them {g}.", [claim], kilo_lima, nfl_catalog)
        == "Lima Lions handled them 27-10."
    )


# ---------------------------------------------------------------------------
# E. a typed score is rejected, and the feedback names the real ones (#255)
#
# The lexical checker's retry message had to list a name's real tuples
# ("Mike Mustangs's real scores are 17-17 and 31-14") because a twice-met
# rival made "matches no game" useless feedback. The claim validator's
# equivalent is what it says about a number typed into the prose: every score
# the block holds for the teams that sentence names. This is the one test of
# the two suites that already ran end to end through `narrate()`.
# ---------------------------------------------------------------------------


def test_a_typed_score_is_rejected_and_the_retry_feedback_names_every_real_meeting(
    kilo_lima: str, nfl_catalog: tuple[TeamRecord, ...]
) -> None:
    typed: dict[str, object] = {
        "text": "Kilo Kings beat Mike Mustangs 14-31 in the rematch.",
        "claims": [],
    }
    claimed: dict[str, object] = {
        "text": "Kilo Kings beat Mike Mustangs {g} in the rematch.",
        "claims": [
            game_claim(
                "g", "game_score", KILO_KINGS, MIKE_MUSTANGS, "W", week=4, season_type="regular"
            )
        ],
    }
    narrator = FakeNarrator([typed, claimed])

    result = narrate(
        fact_block_json=kilo_lima,
        user_team=None,
        contested=False,
        catalog=nfl_catalog,
        narrator=narrator,
        fallback_text="Kilo Kings over Lima Lions, says the math.",
    )

    assert result == NarrationResult(
        text="Kilo Kings beat Mike Mustangs 31-14 in the rematch.", is_fallback=False
    )
    assert len(narrator.calls) == 2
    feedback = narrator.calls[1].retry_feedback
    assert feedback is not None
    assert '"14-31"' in feedback
    for real_score in (
        "Kilo Kings vs Mike Mustangs: T 17-17",
        "Kilo Kings vs Mike Mustangs: W 31-14",
        "Lima Lions vs Mike Mustangs: W 27-10",
    ):
        assert real_score in feedback, feedback


def test_a_swapped_score_typed_into_the_prose_is_rejected(
    texas_usc_2005: str, catalog: tuple[TeamRecord, ...]
) -> None:
    """#26's original bug, in the shape it can still take: the narrator types
    the pair instead of claiming it. The number is the error, whichever way
    round it is."""
    for typed in ("38-41", "41-38"):
        errors = rejected(f"USC beat Texas {typed}.", [], texas_usc_2005, catalog)
        assert_an_error_says(errors, typed)


def test_an_invented_tie_count_typed_into_the_prose_is_rejected(
    kilo_lima: str, nfl_catalog: tuple[TeamRecord, ...]
) -> None:
    """#83's tie-cluster case: a W-L-T record with a fabricated tie column."""
    errors = rejected("Kilo Kings went 2-1-2 in 2023.", [], kilo_lima, nfl_catalog)
    assert_an_error_says(errors, "2-1-2")


def test_a_score_a_keener_explanation_string_quotes_is_still_not_typable(
    usc_2005: str, catalog: tuple[TeamRecord, ...]
) -> None:
    """#181: a keener block quotes scores inside its `rating_breakdown`
    explanation strings, and the lexical checker had to decide whether a pair
    the block held only *there* was claimable. It is not a fact of its own; the
    game rows are, and a typed pair is rejected either way."""
    explanations = [
        entry["explanation"]
        for entry in _json(usc_2005)["rating_breakdown"]["entries"]
        if "38-41" in entry.get("explanation", "")
    ]
    assert explanations, "the keener block should quote the Texas loss in an explanation"

    rejected("USC's own card says 38-41.", [], usc_2005, catalog)


def test_a_narration_that_claims_every_number_it_says_renders_whole(
    usc_2005: str, catalog: tuple[TeamRecord, ...]
) -> None:
    """The other direction, which the two suites carried as their
    false-positive probes: an ordinary correct narration mixing a record, a
    rank, a win and a loss is accepted as a whole. The record prints bare
    because the rank placeholder just before it named the same team."""
    claims: list[dict[str, object]] = [
        {"id": "r", "kind": "record", "team": "USC"},
        {"id": "k", "kind": "rank", "team": "USC"},
        game_claim("w", "game_score", "USC", "Notre Dame", "W"),
        _usc_loss("l"),
    ]

    assert rendered(
        "{k} went {r}, took Notre Dame {w}, and the only blemish was {l} to Texas.",
        claims,
        usc_2005,
        catalog,
    ) == ("No. 2 USC went 12-1, took Notre Dame 34-31, and the only blemish was 41-38 to Texas.")


def test_the_committed_fixture_is_the_one_these_probes_were_measured_against(
    sport_db: Path,
) -> None:
    """`sport_db` is built fresh every run; a change to `sport_fixture.py`'s
    tie cluster would silently change what section D and E prove."""
    conn = get_conn(sport_db, read_only=True)
    try:
        names = {record.name for record in catalog_of(sport_db, "nfl")}
    finally:
        conn.close()
    assert {KILO_KINGS, LIMA_LIONS, MIKE_MUSTANGS} <= names
