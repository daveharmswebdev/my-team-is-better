"""A record, rating or rank belongs to the team its claim names, and a rating
is the value the site displays (issue #292, epic #199).

This file is where `test_persona_grounding_attribution.py` (#166),
`test_persona_grounding_rating_display.py` (#165) and
`test_persona_grounding_rating_rounding.py` (#162) end up. Those three suites
guarded a *lexical* checker that read the narrator's finished prose: it found
each number, guessed which team the sentence meant by nearest name, and
compared. `api.persona.claims` makes all three questions structural instead --
the narrator names the team in the claim, and the server prints the block's
own value for that team -- so the rules those files pinned (nearest-name
attribution, the parenthetical-vs-bare split, the rescue by another team named
in the sentence, the rounding and display-scale allowances) describe machinery
that no longer exists. What survives here is the *properties* they existed to
protect:

* A figure is the claimed team's, wherever in the sentence it sits and
  whatever other team is named nearer (section B). The lexical checker's
  documented limit -- a two-team swap in one sentence went uncaught -- is gone
  with it, and section B pins that too.
* A rating is the display value, at the method's own scale and decimals
  (section C). Every rounding the old checker had to *allow* ("1933",
  "1933.2", "1,933") is now rejected outright when typed, because the prose
  carries no digits at all; the one rendering is the block's.
* Neither the wrong team's figure nor a right figure said about the wrong team
  can be expressed (section B), which is the whole point of #199.

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
from fastapi.testclient import TestClient
from fixtures.claim_blocks import (
    KILO_KINGS,
    LIMA_LIONS,
    MIKE_MUSTANGS,
    assert_an_error_says,
    catalog_of,
    cfb_catalog,
    cfb_comparison_block,
    cfb_team_case_block,
    nfl_comparison_block,
    rejected,
    rendered,
)
from fixtures.narrator_fake import FakeNarrator
from fixtures.sport_fixture import make_sport_fixture_db

from api.deps import get_narration_cache, get_narrator
from api.main import app
from api.persona.cache import InMemoryNarrationCache
from api.repositories.teams import TeamRecord

NOVEMBER_NOMADS = "November Nomads"


@pytest.fixture(scope="module")
def catalog() -> tuple[TeamRecord, ...]:
    return cfb_catalog()


@pytest.fixture(scope="module")
def sport_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return make_sport_fixture_db(tmp_path_factory.mktemp("claims_attribution_sport"))


@pytest.fixture(scope="module")
def nfl_catalog(sport_db: Path) -> tuple[TeamRecord, ...]:
    return catalog_of(sport_db, "nfl")


@pytest.fixture(scope="module")
def kilo_mustangs(sport_db: Path) -> str:
    """2023 Kilo Kings vs Mike Mustangs: Lima Lions is a common opponent, so
    the block holds a third team's rating (the #200 spike's case)."""
    return nfl_comparison_block(sport_db, KILO_KINGS, MIKE_MUSTANGS)


@pytest.fixture(scope="module")
def fsu_msu_2013() -> str:
    return cfb_comparison_block(2013, "Florida State", "Michigan State")


@pytest.fixture(scope="module")
def texas_usc_2005() -> str:
    return cfb_comparison_block(2005, "Texas", "USC")


@pytest.fixture(scope="module")
def texas_usc_2005_elo() -> str:
    return cfb_comparison_block(2005, "Texas", "USC", method="elo")


@pytest.fixture(scope="module")
def texas_2005_elo() -> str:
    return cfb_team_case_block(2005, "Texas", method="elo")


@pytest.fixture(scope="module")
def texas_2005() -> str:
    return cfb_team_case_block(2005, "Texas")


@pytest.fixture(scope="module")
def alabama_2017() -> str:
    return cfb_team_case_block(2017, "Alabama")


def _json(block: str) -> Any:
    return json.loads(block)


def test_fixture_facts_these_tests_rely_on(
    fsu_msu_2013: str,
    kilo_mustangs: str,
    texas_usc_2005: str,
    texas_usc_2005_elo: str,
    texas_2005_elo: str,
) -> None:
    """The real values the probes below quote. Migrated from the pins in the
    three grounding suites this file replaces, keeping only what is still
    load-bearing."""
    fsu_msu = _json(fsu_msu_2013)
    fsu, msu = fsu_msu["team_a"], fsu_msu["team_b"]
    assert (fsu["team_name"], fsu["wins"], fsu["losses"], fsu["ties"]) == (
        "Florida State",
        14,
        0,
        0,
    )
    assert (msu["team_name"], msu["wins"], msu["losses"], msu["ties"]) == (
        "Michigan State",
        13,
        1,
        0,
    )

    nfl = _json(kilo_mustangs)
    assert (nfl["team_a"]["team_name"], nfl["team_a"]["rating"]) == (KILO_KINGS, 0.25)
    assert (nfl["team_b"]["team_name"], nfl["team_b"]["rating"]) == (MIKE_MUSTANGS, 0.15)
    # Lima Lions and November Nomads are neither subject: their ratings reach
    # the block only through Kilo Kings' game rows, which is the shape the
    # lexical checker misattributed to whichever subject was named nearest.
    rows = [*nfl["team_a"]["quality_wins"], nfl["team_a"]["worst_loss"]]
    ratings = {row["opponent_name"]: row["opponent_rating"] for row in rows}
    assert ratings[LIMA_LIONS] == 0.35
    assert ratings[NOVEMBER_NOMADS] == 0.05
    assert (nfl["common_opponents"][0]["opponent_name"], nfl["rating_diff"]) == (LIMA_LIONS, 0.1)

    # Keener scales x1000 at two decimals, Elo rounds to a whole number.
    keener = _json(texas_usc_2005)
    assert keener["method"] == "keener"
    assert keener["team_a"]["rating"] == 0.005044108672990355
    assert keener["team_b"]["rating"] == 0.004736299273644764
    elo = _json(texas_usc_2005_elo)
    assert elo["method"] == "elo"
    assert elo["team_a"]["rating"] == 1933.1932908945062
    assert elo["team_b"]["rating"] == 1891.8303466707475
    assert elo["rating_diff"] == 41.36294422375863
    assert '"opponent_rating":1891.8303466707475' in texas_2005_elo
    assert '"rating":1891.8303466707475' not in texas_2005_elo


# ---------------------------------------------------------------------------
# A. the #200 spike narrations the lexical checker wrongly rejected
#
# `find_ungrounded_tokens` rejected 5 of the spike's 15 correct rendered
# narrations. Two were of this shape: a figure whose team was not the name
# nearest it, which the nearest-name rule credited to the wrong team
# ("13-1 is not Florida State's record"; "350.00 is not Kilo Kings's
# rating"). Both are ordinary typed claims now.
# ---------------------------------------------------------------------------


def test_spike_a_record_for_a_team_that_is_not_the_nearest_name(
    fsu_msu_2013: str, catalog: tuple[TeamRecord, ...]
) -> None:
    claim: dict[str, object] = {"id": "r", "kind": "record", "team": "Michigan State"}

    assert (
        rendered("Florida State knows it: {r}.", [claim], fsu_msu_2013, catalog)
        == "Florida State knows it: Michigan State 13-1."
    )


def test_spike_a_rating_for_a_team_that_is_not_the_nearest_name(
    kilo_mustangs: str, nfl_catalog: tuple[TeamRecord, ...]
) -> None:
    claim: dict[str, object] = {"id": "r", "kind": "rating", "team": LIMA_LIONS}

    assert (
        rendered("Keener said {r}, and Kilo Kings knows it.", [claim], kilo_mustangs, nfl_catalog)
        == "Keener said Lima Lions 350.00, and Kilo Kings knows it."
    )


# ---------------------------------------------------------------------------
# B. a figure is the claimed team's, wherever the sentence puts it
#
# #166's rules: a bare figure went to the nearest name, a parenthetical one to
# the name it hung off, and a bare one was rescued when another team in the
# sentence owned it -- which left a two-team swap in one sentence uncaught, a
# limit that file pinned deliberately. None of that machinery survives: the
# claim carries the team.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # nearest name is the other subject, before the placeholder
        (
            "Florida State was the pick, and {r} is why it was close.",
            "Florida State was the pick, and Michigan State 13-1 is why it was close.",
        ),
        # nearest name is the other subject, after it
        (
            "{r} is the number, and Florida State barely survived it.",
            "Michigan State 13-1 is the number, and Florida State barely survived it.",
        ),
        # what used to be the "parenthetical" form, bound to the wrong name
        (
            "Florida State ({r}) is the story people tell.",
            "Florida State (Michigan State 13-1) is the story people tell.",
        ),
        # a sentence naming nobody at all
        (
            "Nobody remembers the other one: {r}.",
            "Nobody remembers the other one: Michigan State 13-1.",
        ),
    ],
)
def test_a_record_renders_its_own_teams_number_wherever_it_sits(
    fsu_msu_2013: str, catalog: tuple[TeamRecord, ...], text: str, expected: str
) -> None:
    claim: dict[str, object] = {"id": "r", "kind": "record", "team": "Michigan State"}

    assert rendered(text, [claim], fsu_msu_2013, catalog) == expected


def test_both_records_in_one_sentence_cannot_be_swapped(
    fsu_msu_2013: str, catalog: tuple[TeamRecord, ...]
) -> None:
    """#166 round 1 pinned a two-team swap in one sentence as the documented
    limit of nearest-name attribution ("Florida State went 13-1 and Michigan
    State went 14-0" passed). There is nothing left to swap: each placeholder
    prints its own claim's team."""
    claims: list[dict[str, object]] = [
        {"id": "a", "kind": "record", "team": "Florida State"},
        {"id": "b", "kind": "record", "team": "Michigan State"},
    ]

    assert (
        rendered("{a} and {b}, and that was the argument.", claims, fsu_msu_2013, catalog)
        == "Florida State 14-0 and Michigan State 13-1, and that was the argument."
    )


def test_both_ratings_in_one_sentence_cannot_be_swapped(
    texas_usc_2005_elo: str, catalog: tuple[TeamRecord, ...]
) -> None:
    claims: list[dict[str, object]] = [
        {"id": "a", "kind": "rating", "team": "Texas"},
        {"id": "b", "kind": "rating", "team": "USC"},
    ]

    assert (
        rendered("Elo has {a} over {b}.", claims, texas_usc_2005_elo, catalog)
        == "Elo has Texas 1933 over USC 1892."
    )


def test_a_rank_renders_its_own_teams_number(
    texas_usc_2005: str, catalog: tuple[TeamRecord, ...]
) -> None:
    claim: dict[str, object] = {"id": "k", "kind": "rank", "team": "USC"}

    assert (
        rendered("Texas took it, but {k} was right there.", [claim], texas_usc_2005, catalog)
        == "Texas took it, but No. 2 USC was right there."
    )


def test_an_opponents_rating_comes_from_its_own_game_row(
    kilo_mustangs: str, nfl_catalog: tuple[TeamRecord, ...]
) -> None:
    """#166's hardest case: a team the block holds only as an opponent. Its
    rating is that row's `opponent_rating`, never a subject's."""
    claims: list[dict[str, object]] = [
        {"id": "n", "kind": "rating", "team": NOVEMBER_NOMADS},
        {"id": "l", "kind": "rating", "team": LIMA_LIONS},
    ]

    assert (
        rendered("{n} and {l} were the bookends.", claims, kilo_mustangs, nfl_catalog)
        == "November Nomads 50.00 and Lima Lions 350.00 were the bookends."
    )


def test_a_record_for_a_team_the_block_holds_only_as_an_opponent_is_rejected(
    fsu_msu_2013: str, catalog: tuple[TeamRecord, ...]
) -> None:
    """A record exists only for a subject, so the narrator cannot borrow one
    for an opponent and have it credited to whoever is nearest."""
    claim: dict[str, object] = {"id": "r", "kind": "record", "team": "Notre Dame"}

    errors = rejected("{r} was in the way.", [claim], fsu_msu_2013, catalog)
    assert_an_error_says(errors, '"r"', "Notre Dame", "Florida State 14-0")


def test_a_rating_for_a_team_the_block_does_not_hold_at_all_is_rejected(
    fsu_msu_2013: str, catalog: tuple[TeamRecord, ...]
) -> None:
    claim: dict[str, object] = {"id": "r", "kind": "rating", "team": "Alabama"}

    errors = rejected("{r} loomed over all of it.", [claim], fsu_msu_2013, catalog)
    assert_an_error_says(errors, '"r"', "Alabama")


def test_the_other_teams_figure_typed_into_the_prose_is_rejected(
    fsu_msu_2013: str, catalog: tuple[TeamRecord, ...]
) -> None:
    """#166's headline bug ("Texas went 12-1" on a Texas/USC comparison, USC's
    record) needed a nearest-name rule to catch. Typing any record at all is
    now the error, and the message names what the block holds."""
    errors = rejected("Florida State went 13-1 and took the title.", [], fsu_msu_2013, catalog)
    assert_an_error_says(errors, "13-1")


def test_a_rating_of_the_wrong_team_typed_into_the_prose_is_rejected(
    texas_usc_2005_elo: str, catalog: tuple[TeamRecord, ...]
) -> None:
    """#166's other headline ("Elo has Texas at 1892", USC's rating)."""
    errors = rejected("Elo has Texas at 1892.", [], texas_usc_2005_elo, catalog)
    assert_an_error_says(errors, "1892")


# ---------------------------------------------------------------------------
# C. a rating is the display value, and nothing else
#
# #165 taught the lexical checker the on-screen scale (keener x1000 at two
# decimals, elo at zero) and #162 taught it to accept any rounding of a
# rating, because the narrator typed the number itself and the prompt could
# not pin which form it would pick. Both allowances are gone: the server
# prints `api.rating_display.display_value` and the prose may carry no digit.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("block_name", "expected"),
    [("texas_usc_2005", "Texas 5.04"), ("texas_usc_2005_elo", "Texas 1933")],
)
def test_a_rating_renders_at_the_blocks_own_method_scale(
    request: pytest.FixtureRequest,
    catalog: tuple[TeamRecord, ...],
    block_name: str,
    expected: str,
) -> None:
    block: str = request.getfixturevalue(block_name)
    claim: dict[str, object] = {"id": "r", "kind": "rating", "team": "Texas"}

    assert rendered("{r}, and that's the argument.", [claim], block, catalog) == (
        f"{expected}, and that's the argument."
    )


@pytest.mark.parametrize(
    "typed",
    [
        # every form #162 had to allow for the Elo rating 1933.1932908945062
        "1933",
        "1933.2",
        "1,933",
        "1933.19",
        "1933.1932908945062",
        # the roundings #162 rejected, now rejected for the same reason as the rest
        "1933.1",
        "1891",
        # #165's wrong-scale answer: keener's scale applied to an elo rating
        "1933193.29",
        # #165 and #108: a rating_diff, at display precision or rounded
        "41.4",
        "41.36294422375863",
    ],
)
def test_no_form_of_a_rating_may_be_typed_into_the_prose(
    texas_2005_elo: str, catalog: tuple[TeamRecord, ...], typed: str
) -> None:
    """The narrator can no longer say a rating at all, right or wrong. #162's
    whole accepted list and #165's whole rejected list collapse into one
    rule, and the error still tells the narrator what the block holds."""
    errors = rejected(f"Elo rates Texas at {typed}.", [], texas_2005_elo, catalog)
    assert_an_error_says(errors, typed)


@pytest.mark.parametrize(
    "typed",
    ["5.04", "0.005", "0.00504", "5.05", "50.4", "504", "105.27", "0.39"],
)
def test_no_form_of_a_keener_rating_or_breakdown_figure_may_be_typed(
    texas_2005: str, catalog: tuple[TeamRecord, ...], typed: str
) -> None:
    """#165's keener half, including the two derived breakdown figures (#108)
    it proved were never grounded: a `credit` of 105.27 and a
    `contribution` of 0.39."""
    rejected(f"Keener rates Texas at {typed}.", [], texas_2005, catalog)


def test_a_rating_gap_is_the_gap_between_the_displayed_ratings(
    texas_usc_2005_elo: str, catalog: tuple[TeamRecord, ...]
) -> None:
    """#165 pinned that `rating_diff` is derived and never grounded, so a
    narrator quoting a gap had nothing to lean on. A `rating_gap` claim is the
    supported way to say it, and it prints the difference of the two numbers
    on screen (1933 - 1892), not of the raw ratings (41.36...)."""
    claim: dict[str, object] = {
        "id": "g",
        "kind": "rating_gap",
        "team": "Texas",
        "opponent": "USC",
    }

    assert rendered("{g} points of daylight.", [claim], texas_usc_2005_elo, catalog) == (
        "41 points of daylight."
    )


# ---------------------------------------------------------------------------
# D. end to end: the rating the site shows reaches the user on the first call
#
# The two route tests the rating suites carried, which is the only part of
# them that ever exercised production wiring rather than the checker.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("route", "payload", "submission", "expected"),
    [
        (
            "/api/verdict/champion",
            {"year": 2005, "method": "keener"},
            {
                "text": "Keener rates {r}, and nobody's arguing.",
                "claims": [{"id": "r", "kind": "rating", "team": "Texas"}],
            },
            "Keener rates Texas 5.04, and nobody's arguing.",
        ),
        (
            "/api/verdict/champion",
            {"year": 2005, "method": "elo"},
            {
                "text": "Elo rates {r}, and nobody's arguing.",
                "claims": [{"id": "r", "kind": "rating", "team": "Texas"}],
            },
            "Elo rates Texas 1933, and nobody's arguing.",
        ),
        (
            "/api/verdict/compare",
            {"year": 2005, "team_a": "Texas", "team_b": "USC", "method": "elo"},
            {
                "text": "Elo has {a} and {b}, and Texas beat USC {g} to prove it.",
                "claims": [
                    {"id": "a", "kind": "rating", "team": "Texas"},
                    {"id": "b", "kind": "rating", "team": "USC"},
                    {
                        "id": "g",
                        "kind": "game_score",
                        "team": "Texas",
                        "opponent": "USC",
                        "result": "W",
                    },
                ],
            },
            "Elo has Texas 1933 and USC 1892, and Texas beat USC 41-38 to prove it.",
        ),
    ],
)
def test_the_displayed_rating_is_served_on_the_first_narrator_call(
    client: TestClient,
    route: str,
    payload: dict[str, object],
    submission: dict[str, object],
    expected: str,
) -> None:
    narrator = FakeNarrator([submission])
    app.dependency_overrides[get_narration_cache] = lambda: InMemoryNarrationCache()
    app.dependency_overrides[get_narrator] = lambda: narrator
    try:
        response = client.post(route, json=payload)
    finally:
        app.dependency_overrides.pop(get_narration_cache, None)
        app.dependency_overrides.pop(get_narrator, None)

    assert response.status_code == 200, response.json()
    assert response.json()["narration"]["text"] == expected
    assert len(narrator.calls) == 1, "a displayed rating must not cost a retry"
