"""Failing-first tests for issue #290 (epic #199, child 1 of 4): the typed-claim
model, `api.persona.claims`.

The narrator will (in #291) answer with one `submit_narration {text, claims}`
tool call. `text` carries `{id}` placeholders and each claim says what a
placeholder is; the server resolves every claim against the fact block and
prints every value from the block itself, so the prose carries no number of
its own. This file covers the claims: their shape, each kind's resolution and
rendering, game resolution (the winner, a rematch, a game the block doesn't
hold), malformed tool input and the tool schema. The checks on the prose
outside the placeholders are in `test_persona_claims_prose.py`.

Every block is the one production builds (`tests/fixtures/claim_blocks.py`):
2017 Alabama, 2005 USC and 2005 Texas from the committed CFB fixture, 2023
Kilo Kings vs Lima Lions from the NFL sport fixture's tie cluster, and Alpha
State vs Bravo Tech under every rating method from the method fixture. The
facts the tests lean on are pinned in `test_fixture_facts_these_tests_rely_on`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from fixtures.claim_blocks import (
    ALPHA_STATE,
    BRAVO_TECH,
    KILO_KINGS,
    LIMA_LIONS,
    MIKE_MUSTANGS,
    assert_an_error_says,
    catalog_of,
    cfb_catalog,
    cfb_comparison_block,
    cfb_team_case_block,
    game_claim,
    method_comparison_block,
    nfl_tie_comparison_block,
    rejected,
    rendered,
)
from fixtures.method_fixture import METHODS, make_method_fixture_db
from fixtures.sport_fixture import make_sport_fixture_db

from api.models import Method
from api.persona.claims import (
    GROUNDING_VERSION,
    MAX_CLAIMS,
    MAX_GAME_SCORE_CLAIMS,
    TOOL_NAME,
    ClaimOutcome,
    check_and_render,
    tool_schema,
)
from api.repositories.teams import TeamRecord

# ---------------------------------------------------------------------------
# blocks
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def sport_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return make_sport_fixture_db(tmp_path_factory.mktemp("claims_sport"))


@pytest.fixture(scope="module")
def kilo_lima(sport_db: Path) -> str:
    return nfl_tie_comparison_block(sport_db)


@pytest.fixture(scope="module")
def nfl_catalog(sport_db: Path) -> tuple[TeamRecord, ...]:
    return catalog_of(sport_db, "nfl")


@pytest.fixture(scope="module")
def method_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return make_method_fixture_db(tmp_path_factory.mktemp("claims_method"))


@pytest.fixture(scope="module")
def catalog() -> tuple[TeamRecord, ...]:
    return cfb_catalog()


@pytest.fixture(scope="module")
def alabama_2017() -> str:
    return cfb_team_case_block(2017, "Alabama")


@pytest.fixture(scope="module")
def usc_2005() -> str:
    return cfb_team_case_block(2005, "USC")


@pytest.fixture(scope="module")
def texas_2005() -> str:
    return cfb_team_case_block(2005, "Texas")


@pytest.fixture(scope="module")
def texas_usc_2005() -> str:
    return cfb_comparison_block(2005, "Texas", "USC")


@pytest.fixture(scope="module")
def texas_colorado_2005() -> str:
    return cfb_comparison_block(2005, "Texas", "Colorado")


@pytest.fixture(scope="module")
def auburn_2017() -> str:
    return cfb_team_case_block(2017, "Auburn")


@pytest.fixture(scope="module")
def auburn_usc_2017() -> str:
    return cfb_comparison_block(2017, "Auburn", "USC")


@pytest.fixture(scope="module")
def alabama_auburn_2017() -> str:
    return cfb_comparison_block(2017, "Alabama", "Auburn")


_game = game_claim


def _row(block: str, *path: str | int) -> Any:
    node: Any = json.loads(block)
    for step in path:
        node = node[step]
    return node


def test_fixture_facts_these_tests_rely_on(
    alabama_2017: str, usc_2005: str, texas_2005: str, kilo_lima: str
) -> None:
    alabama = json.loads(alabama_2017)
    assert (alabama["rank"], alabama["wins"], alabama["losses"], alabama["ties"]) == (1, 13, 1, 0)
    games = alabama["games"]
    assert len(games) == 14
    assert (games[0]["opponent_name"], games[0]["week"], games[0]["neutral_site"]) == (
        "Florida State",
        1,
        True,
    )
    assert games[0]["venue"] == "neutral"
    # A home game and a road game, for the two renderings #294 added.
    by_opponent = {g["opponent_name"]: g for g in games}
    assert (by_opponent["Tennessee"]["week"], by_opponent["Tennessee"]["venue"]) == (8, "home")
    regular = [g for g in games if g["season_type"] == "regular"]
    assert regular[-1]["opponent_name"] == "Auburn"
    assert (regular[-1]["result"], regular[-1]["neutral_site"]) == ("L", False)
    # Auburn hosted the 2017 Iron Bowl, so Alabama's side of it is "away".
    assert (regular[-1]["venue"], regular[-1]["team_score"], regular[-1]["opponent_score"]) == (
        "away",
        14,
        26,
    )
    postseason = {g["opponent_name"]: g for g in games if g["season_type"] == "postseason"}
    assert postseason["Georgia"]["week"] == postseason["Clemson"]["week"] == 1
    assert postseason["Georgia"]["opponent_rank"] == 3
    assert 9 not in {g["week"] for g in regular}
    assert [q["opponent_name"] for q in alabama["quality_wins"]] == ["Georgia", "Clemson"]
    assert all(g["opponent_name"] != "Georgia Tech" for g in games)

    usc_loss = json.loads(usc_2005)["worst_loss"]
    assert (usc_loss["opponent_name"], usc_loss["team_score"], usc_loss["opponent_score"]) == (
        "Texas",
        38,
        41,
    )
    texas = json.loads(texas_2005)
    assert (texas["wins"], texas["losses"]) == (13, 0)
    assert [g["week"] for g in texas["games"] if g["opponent_name"] == "Colorado"] == [7, 14]

    comparison = json.loads(kilo_lima)
    kilo, lima = comparison["team_a"], comparison["team_b"]
    assert (kilo["team_name"], kilo["rank"], kilo["rating"]) == (KILO_KINGS, 6, 0.25)
    assert (kilo["wins"], kilo["losses"], kilo["ties"]) == (2, 1, 1)
    assert (lima["team_name"], lima["rank"], lima["rating"]) == (LIMA_LIONS, 5, 0.35)
    (common,) = comparison["common_opponents"]
    assert common["opponent_name"] == MIKE_MUSTANGS
    assert [(m["result"], m["week"]) for m in common["team_a_meetings"]] == [("T", 2), ("W", 4)]
    assert [
        (m["result"], m["team_score"], m["opponent_score"]) for m in common["team_b_meetings"]
    ] == [("W", 27, 10)]
    # A common-opponent meeting carries `venue` and never a `neutral_site`
    # companion (#294): "neutral" says the same thing.
    assert "neutral_site" not in common["team_a_meetings"][0]
    assert [m["venue"] for m in common["team_a_meetings"]] == ["home", "home"]
    assert [m["venue"] for m in common["team_b_meetings"]] == ["home"]


# ---------------------------------------------------------------------------
# record / rating / rank: always printed with the team's name
# ---------------------------------------------------------------------------


def test_record_prints_the_name_and_a_tie_column_only_when_tied(
    kilo_lima: str, nfl_catalog: tuple[TeamRecord, ...]
) -> None:
    claims: list[dict[str, object]] = [
        {"id": "k", "kind": "record", "team": KILO_KINGS},
        {"id": "l", "kind": "record", "team": LIMA_LIONS},
    ]
    assert (
        rendered("Look at {k} next to {l}.", claims, kilo_lima, nfl_catalog)
        == "Look at Kilo Kings 2-1-1 next to Lima Lions 2-0."
    )


def test_record_on_a_team_case(alabama_2017: str, catalog: tuple[TeamRecord, ...]) -> None:
    claim: dict[str, object] = {"id": "r", "kind": "record", "team": "Alabama"}
    assert rendered("That was {r}.", [claim], alabama_2017, catalog) == "That was Alabama 13-1."


def test_record_for_a_team_that_is_not_a_subject_is_rejected_listing_the_subjects(
    alabama_2017: str, catalog: tuple[TeamRecord, ...]
) -> None:
    claim: dict[str, object] = {"id": "r", "kind": "record", "team": "Auburn"}
    errors = rejected("Look at {r}.", [claim], alabama_2017, catalog)
    assert_an_error_says(errors, '"r"', "Auburn", "Alabama 13-1")


def test_rating_prints_the_name_and_the_display_value(
    kilo_lima: str, nfl_catalog: tuple[TeamRecord, ...]
) -> None:
    claims: list[dict[str, object]] = [
        {"id": "a", "kind": "rating", "team": LIMA_LIONS},
        {"id": "b", "kind": "rating", "team": KILO_KINGS},
    ]
    assert (
        rendered("{a} against {b}.", claims, kilo_lima, nfl_catalog)
        == "Lima Lions 350.00 against Kilo Kings 250.00."
    )


def test_rating_of_an_opponent_comes_from_its_game_row(
    alabama_2017: str, catalog: tuple[TeamRecord, ...]
) -> None:
    # Georgia's opponent_rating is 0.004746916581693488 -> keener x1000, 2dp.
    claim: dict[str, object] = {"id": "g", "kind": "rating", "team": "Georgia"}
    assert rendered("{g} is no joke.", [claim], alabama_2017, catalog) == "Georgia 4.75 is no joke."


def test_method_fixture_methods_are_in_registry_order() -> None:
    # The expected display values below are written out by method, so pin the
    # offsets `make_method_fixture_db` derives from this order.
    assert METHODS == ("keener", "elo", "elo_career")


@pytest.mark.parametrize(
    ("method", "alpha", "bravo"),
    [
        ("keener", "Alpha State 3000.00", "Bravo Tech 2000.00"),
        ("elo", "Alpha State 4", "Bravo Tech 3"),
        ("elo_career", "Alpha State 5", "Bravo Tech 4"),
    ],
)
def test_rating_renders_under_every_method(
    method_db: Path, method: Method, alpha: str, bravo: str
) -> None:
    block = method_comparison_block(method_db, method)
    catalog = catalog_of(method_db, "cfb")
    claims: list[dict[str, object]] = [
        {"id": "a", "kind": "rating", "team": ALPHA_STATE},
        {"id": "b", "kind": "rating", "team": BRAVO_TECH},
    ]
    assert rendered("{a}, {b}.", claims, block, catalog) == f"{alpha}, {bravo}."


def test_rating_for_a_team_the_block_gives_no_rating_is_rejected(
    alabama_2017: str, catalog: tuple[TeamRecord, ...]
) -> None:
    # Mercer is an unrated FCS opponent: its row has opponent_rating null.
    claim: dict[str, object] = {"id": "m", "kind": "rating", "team": "Mercer"}
    errors = rejected("{m} showed up.", [claim], alabama_2017, catalog)
    assert_an_error_says(errors, "Mercer", "Georgia")


def test_rank_prints_no_and_the_name(alabama_2017: str, catalog: tuple[TeamRecord, ...]) -> None:
    claims: list[dict[str, object]] = [
        {"id": "k1", "kind": "rank", "team": "Georgia"},
        _game("g1", "game_score", "Alabama", "Georgia", "W"),
    ]
    assert (
        rendered("Alabama beat {k1} {g1}.", claims, alabama_2017, catalog)
        == "Alabama beat No. 3 Georgia 26-23."
    )


def test_rank_for_an_unranked_team_is_rejected(
    alabama_2017: str, catalog: tuple[TeamRecord, ...]
) -> None:
    claim: dict[str, object] = {"id": "m", "kind": "rank", "team": "Mercer"}
    errors = rejected("{m} showed up.", [claim], alabama_2017, catalog)
    assert_an_error_says(errors, "Mercer", "Georgia")


# ---------------------------------------------------------------------------
# game_score / margin: the winner is checked, the score is winner-first
# ---------------------------------------------------------------------------


def test_a_loss_prints_winner_first(usc_2005: str, catalog: tuple[TeamRecord, ...]) -> None:
    claim = _game("g1", "game_score", "USC", "Texas", "L")
    assert (
        rendered("The {g1} loss to Texas still stings.", [claim], usc_2005, catalog)
        == "The 41-38 loss to Texas still stings."
    )


def test_a_tie_prints_both_scores(kilo_lima: str, nfl_catalog: tuple[TeamRecord, ...]) -> None:
    claim = _game("t", "game_score", KILO_KINGS, MIKE_MUSTANGS, "T", week=2)
    assert rendered("A {t} tie.", [claim], kilo_lima, nfl_catalog) == "A 17-17 tie."


def test_a_rematch_resolves_by_week(kilo_lima: str, nfl_catalog: tuple[TeamRecord, ...]) -> None:
    claims = [
        _game("s", "game_score", KILO_KINGS, MIKE_MUSTANGS, "W", week=4),
        _game("m", "margin", KILO_KINGS, MIKE_MUSTANGS, "W", week=4, season_type="regular"),
    ]
    assert (
        rendered("Kilo Kings won {s}, by {m}.", claims, kilo_lima, nfl_catalog)
        == "Kilo Kings won 31-14, by 17."
    )


def test_a_rematch_without_a_week_is_rejected_listing_the_meetings(
    kilo_lima: str, nfl_catalog: tuple[TeamRecord, ...]
) -> None:
    claim = _game("s", "game_score", KILO_KINGS, MIKE_MUSTANGS, "W")
    errors = rejected("Kilo Kings won {s}.", [claim], kilo_lima, nfl_catalog)
    assert_an_error_says(errors, '"s"', "week 2", "week 4", "regular")


def test_a_rematch_with_a_week_they_did_not_meet_is_rejected(
    kilo_lima: str, nfl_catalog: tuple[TeamRecord, ...]
) -> None:
    claim = _game("s", "game_score", KILO_KINGS, MIKE_MUSTANGS, "W", week=9)
    errors = rejected("Kilo Kings won {s}.", [claim], kilo_lima, nfl_catalog)
    assert_an_error_says(errors, '"s"', "week 2", "week 4")


def test_the_wrong_winner_is_rejected_with_the_real_result(
    kilo_lima: str, nfl_catalog: tuple[TeamRecord, ...]
) -> None:
    # Lima Lions beat Mike Mustangs 27-10: from Mike Mustangs' side, L 10-27.
    claim = _game("g1", "game_score", MIKE_MUSTANGS, LIMA_LIONS, "W")
    errors = rejected("Mike Mustangs went {g1} over Lima Lions.", [claim], kilo_lima, nfl_catalog)
    assert_an_error_says(errors, '"g1"', "L 10-27")


def test_the_wrong_winner_is_rejected_from_the_opponent_side_of_a_team_case(
    usc_2005: str, catalog: tuple[TeamRecord, ...]
) -> None:
    claim = _game("g1", "game_score", "Texas", "USC", "L")
    errors = rejected("Texas lost {g1} to USC.", [claim], usc_2005, catalog)
    assert_an_error_says(errors, '"g1"', "W 41-38")


def test_margin_of_a_loss(alabama_2017: str, catalog: tuple[TeamRecord, ...]) -> None:
    claim = _game("m", "margin", "Alabama", "Auburn", "L")
    assert rendered("Lost by {m}.", [claim], alabama_2017, catalog) == "Lost by 12."


def test_a_head_to_head_meeting_resolves_from_both_sides(
    texas_usc_2005: str, catalog: tuple[TeamRecord, ...]
) -> None:
    claims = [
        _game("a", "game_score", "Texas", "USC", "W"),
        _game("b", "game_score", "USC", "Texas", "L"),
    ]
    assert rendered("{a}, or {b}.", claims, texas_usc_2005, catalog) == "41-38, or 41-38."


def test_a_game_between_two_block_teams_that_never_met_is_rejected(
    alabama_2017: str, catalog: tuple[TeamRecord, ...]
) -> None:
    claim = _game("g", "game_score", "Florida State", "Georgia", "W")
    errors = rejected("{g}.", [claim], alabama_2017, catalog)
    assert_an_error_says(errors, '"g"', "Florida State", "Georgia", "Alabama")


# ---------------------------------------------------------------------------
# year / count / win_pct
# ---------------------------------------------------------------------------


def test_year(alabama_2017: str, catalog: tuple[TeamRecord, ...]) -> None:
    claim: dict[str, object] = {"id": "y", "kind": "year"}
    assert rendered("Back in {y}.", [claim], alabama_2017, catalog) == "Back in 2017."


@pytest.mark.parametrize(
    ("claim", "expected"),
    [
        ({"of": "quality_wins", "team": "Alabama"}, "two"),
        ({"of": "wins", "team": "Alabama"}, "13"),
        ({"of": "losses", "team": "Alabama"}, "one"),
        ({"of": "ties", "team": "Alabama"}, "zero"),
        ({"of": "games", "team": "Alabama"}, "14"),
        ({"of": "meetings", "team": "Alabama", "opponent": "Auburn"}, "one"),
    ],
)
def test_count_on_a_team_case_is_ap_style(
    alabama_2017: str, catalog: tuple[TeamRecord, ...], claim: dict[str, object], expected: str
) -> None:
    full: dict[str, object] = {"id": "c", "kind": "count", **claim}
    assert rendered("{c}", [full], alabama_2017, catalog) == expected


def test_count_of_meetings_counts_a_rematch(
    texas_2005: str, catalog: tuple[TeamRecord, ...]
) -> None:
    claim: dict[str, object] = {
        "id": "c",
        "kind": "count",
        "of": "meetings",
        "team": "Texas",
        "opponent": "Colorado",
    }
    assert rendered("{c}", [claim], texas_2005, catalog) == "two"


def test_auburn_2017_facts_the_meeting_tests_rely_on(
    auburn_2017: str, auburn_usc_2017: str, alabama_auburn_2017: str
) -> None:
    # Auburn played Georgia twice in 2017, and its team case holds both games.
    games = [
        (g["result"], g["team_score"], g["opponent_score"], g["week"], g["season_type"])
        for g in json.loads(auburn_2017)["games"]
        if g["opponent_name"] == "Georgia"
    ]
    assert games == [("W", 40, 17, 11, "regular"), ("L", 7, 28, 14, "regular")]
    # On the Auburn vs USC comparison, Georgia is neither the other subject nor a
    # common opponent: only Auburn's week-11 quality win over Georgia is there.
    comparison = json.loads(auburn_usc_2017)
    assert comparison["head_to_head"]["meetings"] == []
    assert comparison["common_opponents"] == []
    assert [
        (q["opponent_name"], q["result"], q["week"]) for q in comparison["team_a"]["quality_wins"]
    ] == [("Alabama", "W", 13), ("Georgia", "W", 11)]
    assert comparison["team_a"]["worst_loss"]["opponent_name"] == "LSU"
    # On the Alabama vs Auburn comparison, Georgia is a common opponent, so the
    # block lists every meeting of each subject with Georgia.
    iron_bowl = json.loads(alabama_auburn_2017)
    assert len(iron_bowl["head_to_head"]["meetings"]) == 1
    common = {c["opponent_name"]: c for c in iron_bowl["common_opponents"]}
    assert [m["week"] for m in common["Georgia"]["team_a_meetings"]] == [1]
    assert [m["week"] for m in common["Georgia"]["team_b_meetings"]] == [11, 14]


@pytest.mark.parametrize(("team", "opponent"), [("Auburn", "Georgia"), ("Georgia", "Auburn")])
def test_count_of_meetings_on_a_pair_the_comparison_may_not_fully_hold_is_rejected(
    auburn_usc_2017: str, catalog: tuple[TeamRecord, ...], team: str, opponent: str
) -> None:
    # The block holds one Auburn-Georgia game (a quality win), but they played
    # twice: a count here would print "one" for a pair that met two times.
    claim: dict[str, object] = {
        "id": "c",
        "kind": "count",
        "of": "meetings",
        "team": team,
        "opponent": opponent,
    }
    errors = rejected("They met {c} times.", [claim], auburn_usc_2017, catalog)
    assert_an_error_says(errors, '"c"', "Auburn", "Georgia", "does not hold every game")


def test_count_of_meetings_renders_on_the_team_case_that_holds_every_game(
    auburn_2017: str, catalog: tuple[TeamRecord, ...]
) -> None:
    claim: dict[str, object] = {
        "id": "c",
        "kind": "count",
        "of": "meetings",
        "team": "Auburn",
        "opponent": "Georgia",
    }
    assert rendered("{c}", [claim], auburn_2017, catalog) == "two"


@pytest.mark.parametrize(
    ("team", "opponent", "expected"),
    [
        # head_to_head
        ("Alabama", "Auburn", "one"),
        ("Auburn", "Alabama", "one"),
        # a subject vs a common opponent (team_a_meetings / team_b_meetings)
        ("Auburn", "Georgia", "two"),
        ("Georgia", "Alabama", "one"),
    ],
)
def test_count_of_meetings_renders_on_a_comparison_for_a_pair_it_fully_holds(
    alabama_auburn_2017: str,
    catalog: tuple[TeamRecord, ...],
    team: str,
    opponent: str,
    expected: str,
) -> None:
    claim: dict[str, object] = {
        "id": "c",
        "kind": "count",
        "of": "meetings",
        "team": team,
        "opponent": opponent,
    }
    assert rendered("{c}", [claim], alabama_auburn_2017, catalog) == expected


def test_a_result_the_comparison_does_not_hold_lists_its_meetings_without_one_only_game(
    auburn_usc_2017: str, catalog: tuple[TeamRecord, ...]
) -> None:
    # Auburn did lose to Georgia (week 14); this block just doesn't hold that
    # game, so the error must not say the week-11 win was "that game".
    claim = _game("g", "game_score", "Auburn", "Georgia", "L")
    errors = rejected("Auburn lost {g}.", [claim], auburn_usc_2017, catalog)
    assert_an_error_says(errors, '"g"', "W 40-17 (regular week 11)", "may not hold every game")
    assert not any("that game" in error for error in errors), errors


def test_a_week_the_comparison_does_not_hold_is_not_called_a_week_they_did_not_meet(
    auburn_usc_2017: str, catalog: tuple[TeamRecord, ...]
) -> None:
    claim = _game("m", "margin", "Auburn", "Georgia", "L", week=14, season_type="regular")
    errors = rejected("Auburn lost by {m}.", [claim], auburn_usc_2017, catalog)
    assert_an_error_says(errors, '"m"', "W 40-17 (regular week 11)", "may not hold every game")
    assert not any("did not meet" in error for error in errors), errors


def test_a_game_on_a_pair_the_block_may_not_fully_hold_still_resolves_when_it_matches(
    auburn_2017: str, auburn_usc_2017: str, catalog: tuple[TeamRecord, ...]
) -> None:
    win = _game("g", "game_score", "Auburn", "Georgia", "W")
    assert rendered("{g}", [win], auburn_usc_2017, catalog) == "40-17"
    loss = _game("g", "game_score", "Auburn", "Georgia", "L", week=14)
    assert rendered("{g}", [loss], auburn_2017, catalog) == "28-7"


@pytest.mark.parametrize(
    ("claim", "expected"),
    [
        ({"of": "common_opponents"}, "one"),
        ({"of": "meetings", "team": KILO_KINGS, "opponent": MIKE_MUSTANGS}, "two"),
        ({"of": "meetings", "team": LIMA_LIONS, "opponent": KILO_KINGS}, "one"),
        ({"of": "ties", "team": KILO_KINGS}, "one"),
        ({"of": "quality_wins", "team": LIMA_LIONS}, "two"),
    ],
)
def test_count_on_a_comparison(
    kilo_lima: str,
    nfl_catalog: tuple[TeamRecord, ...],
    claim: dict[str, object],
    expected: str,
) -> None:
    full: dict[str, object] = {"id": "c", "kind": "count", **claim}
    assert rendered("{c}", [full], kilo_lima, nfl_catalog) == expected


@pytest.mark.parametrize(
    ("claim", "needles"),
    [
        # a comparison block has no games[] for either team
        ({"of": "games", "team": KILO_KINGS}, (KILO_KINGS, "games")),
        # wins are given only for the two subjects
        ({"of": "wins", "team": MIKE_MUSTANGS}, (MIKE_MUSTANGS, KILO_KINGS, LIMA_LIONS)),
        ({"of": "points", "team": KILO_KINGS}, ("points", "quality_wins")),
        ({"of": "meetings", "team": KILO_KINGS}, ("opponent",)),
    ],
)
def test_count_rejections_on_a_comparison(
    kilo_lima: str,
    nfl_catalog: tuple[TeamRecord, ...],
    claim: dict[str, object],
    needles: tuple[str, ...],
) -> None:
    full: dict[str, object] = {"id": "c", "kind": "count", **claim}
    assert_an_error_says(rejected("{c}", [full], kilo_lima, nfl_catalog), '"c"', *needles)


def test_count_of_common_opponents_on_a_team_case_is_rejected(
    alabama_2017: str, catalog: tuple[TeamRecord, ...]
) -> None:
    claim: dict[str, object] = {"id": "c", "kind": "count", "of": "common_opponents"}
    assert_an_error_says(rejected("{c}", [claim], alabama_2017, catalog), '"c"', "common")


@pytest.mark.parametrize(
    ("team", "expected"),
    [(KILO_KINGS, ".625"), (LIMA_LIONS, "1.000")],
)
def test_win_pct_counts_a_tie_as_half(
    kilo_lima: str, nfl_catalog: tuple[TeamRecord, ...], team: str, expected: str
) -> None:
    claim: dict[str, object] = {"id": "p", "kind": "win_pct", "team": team}
    assert rendered("{p}", [claim], kilo_lima, nfl_catalog) == expected


@pytest.mark.parametrize(
    ("block_team", "expected"),
    [("Alabama", ".929"), ("Texas", "1.000"), ("USC", ".923")],
)
def test_win_pct_rounds_to_three_places(
    catalog: tuple[TeamRecord, ...], block_team: str, expected: str
) -> None:
    year = 2017 if block_team == "Alabama" else 2005
    block = cfb_team_case_block(year, block_team)
    claim: dict[str, object] = {"id": "p", "kind": "win_pct", "team": block_team}
    assert rendered("{p}", [claim], block, catalog) == expected


@pytest.mark.parametrize(
    ("wins", "losses", "ties", "expected"),
    [
        # 9/16 is exactly .5625: .563 rounding half up, .562 half-even or float round
        (9, 7, 0, ".563"),
        # 5/16 is exactly .3125
        (5, 11, 0, ".313"),
        # 4.5/8 is exactly .5625, with the tie as half a win
        (4, 3, 1, ".563"),
    ],
)
def test_win_pct_rounds_an_exact_half_thousandth_up(
    wins: int, losses: int, ties: int, expected: str
) -> None:
    """None of the fixture subjects these tests use has a record that lands on a
    .0005 tie, so the module's formatter is pinned directly."""
    from api.persona.claims import _format_win_pct

    assert _format_win_pct(wins, losses, ties) == expected


def test_win_pct_for_a_non_subject_is_rejected(
    alabama_2017: str, catalog: tuple[TeamRecord, ...]
) -> None:
    claim: dict[str, object] = {"id": "p", "kind": "win_pct", "team": "Auburn"}
    assert_an_error_says(rejected("{p}", [claim], alabama_2017, catalog), '"p"', "Alabama")


# ---------------------------------------------------------------------------
# when / where (founder decision C on #199)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("opponent", "result", "expected"),
    [
        ("Florida State", "W", "to open the season"),
        # The last regular-season game is only its week until #300 tells a
        # conference title game from a true finale (founder decision 2, #291).
        ("Auburn", "L", "in week 13"),
        # 2017 Alabama's postseason games are both week 1: never "week 1"
        ("Georgia", "W", "in the postseason"),
        ("Clemson", "W", "in the postseason"),
        ("Mississippi State", "W", "in week 11"),
    ],
)
def test_when_on_the_subjects_full_game_list(
    alabama_2017: str,
    catalog: tuple[TeamRecord, ...],
    opponent: str,
    result: str,
    expected: str,
) -> None:
    claim = _game("w", "when", "Alabama", opponent, result)
    assert rendered("It happened {w}.", [claim], alabama_2017, catalog) == (
        f"It happened {expected}."
    )


def test_when_from_the_opponent_side_has_no_season_position(
    alabama_2017: str, catalog: tuple[TeamRecord, ...]
) -> None:
    # The block holds Alabama's games[], not Auburn's, so Auburn's side of the
    # Iron Bowl is only "week 13".
    claim = _game("w", "when", "Auburn", "Alabama", "W")
    assert rendered("{w}", [claim], alabama_2017, catalog) == "in week 13"


def test_when_on_a_comparison(
    kilo_lima: str,
    nfl_catalog: tuple[TeamRecord, ...],
    texas_usc_2005: str,
    catalog: tuple[TeamRecord, ...],
) -> None:
    # A comparison holds no games[]: week 1 is "in week 1", not the opener.
    claims = [
        _game("a", "when", KILO_KINGS, MIKE_MUSTANGS, "W", week=4),
        _game("b", "when", LIMA_LIONS, KILO_KINGS, "W"),
    ]
    assert rendered("{a}; {b}.", claims, kilo_lima, nfl_catalog) == "in week 4; in week 1."
    postseason = _game("p", "when", "USC", "Texas", "L")
    assert rendered("{p}", [postseason], texas_usc_2005, catalog) == "in the postseason"


def test_when_for_a_week_the_block_does_not_hold_is_rejected(
    alabama_2017: str, catalog: tuple[TeamRecord, ...]
) -> None:
    # Alabama had no week 9; LSU was week 10.
    claim = _game("w", "when", "Alabama", "LSU", "W", week=9)
    errors = rejected("{w}", [claim], alabama_2017, catalog)
    assert_an_error_says(errors, '"w"', "LSU", "week 10")


def test_when_for_a_game_the_block_does_not_hold_is_rejected(
    alabama_2017: str, catalog: tuple[TeamRecord, ...]
) -> None:
    claim = _game("w", "when", "Florida State", "Georgia", "W")
    errors = rejected("{w}", [claim], alabama_2017, catalog)
    assert_an_error_says(errors, '"w"', "Florida State", "Alabama")


def test_where_at_a_neutral_site(
    alabama_2017: str, catalog: tuple[TeamRecord, ...], texas_usc_2005: str
) -> None:
    claim = _game("v", "where", "Alabama", "Georgia", "W")
    assert rendered("{v}", [claim], alabama_2017, catalog) == "at a neutral site"
    h2h = _game("v", "where", "USC", "Texas", "L")
    assert rendered("{v}", [h2h], texas_usc_2005, catalog) == "at a neutral site"


def test_where_at_home(alabama_2017: str, catalog: tuple[TeamRecord, ...]) -> None:
    """A home game says so since #294; before it, only a neutral site could
    be rendered at all."""
    claim = _game("v", "where", "Alabama", "Tennessee", "W")
    assert rendered("{v}", [claim], alabama_2017, catalog) == "at home"


def test_where_on_the_road(alabama_2017: str, catalog: tuple[TeamRecord, ...]) -> None:
    """An away game is "on the road", the narrator's register, not "away"
    (founder's voice call on #294); and it composes after a score."""
    claim = _game("v", "where", "Alabama", "Auburn", "L")
    assert rendered("{v}", [claim], alabama_2017, catalog) == "on the road"
    score = _game("s", "game_score", "Alabama", "Auburn", "L")
    assert (
        rendered("Alabama lost {s} {v}.", [score, claim], alabama_2017, catalog)
        == "Alabama lost 26-14 on the road."
    )


def test_where_renders_the_side_of_the_team_the_claim_names(
    alabama_2017: str, auburn_2017: str, catalog: tuple[TeamRecord, ...]
) -> None:
    """Venue is team-relative, like the score pair: the same Iron Bowl is
    "on the road" from Alabama's side and "at home" from Auburn's."""
    alabama = _game("v", "where", "Alabama", "Auburn", "L")
    auburn = _game("v", "where", "Auburn", "Alabama", "W")
    assert rendered("{v}", [alabama], alabama_2017, catalog) == "on the road"
    assert rendered("{v}", [auburn], auburn_2017, catalog) == "at home"
    # ... including the mirrored row the block indexes for the opponent, which
    # is the only place Auburn's side of the game exists in Alabama's block.
    assert rendered("{v}", [auburn], alabama_2017, catalog) == "at home"


def test_where_for_a_head_to_head_meeting_renders_from_the_home_teams_side(
    texas_colorado_2005: str, texas_usc_2005: str, catalog: tuple[TeamRecord, ...]
) -> None:
    """A head-to-head meeting row is home/away-oriented (`home_team` /
    `away_team` / `neutral_site`), not team-relative, so its venue is read
    from the home team's side and mirrored for the away team."""
    # Neither 2005 Texas-Colorado meeting is a quality win or a worst loss on
    # either side, so head_to_head is the only row in the block that holds it.
    meetings = _row(texas_colorado_2005, "head_to_head", "meetings")
    assert [(m["home_team"], m["week"], m["neutral_site"]) for m in meetings] == [
        ("Texas", 7, False),
        ("Colorado", 14, False),
    ]
    for side in ("team_a", "team_b"):
        rows = _row(texas_colorado_2005, side, "quality_wins")
        worst = _row(texas_colorado_2005, side, "worst_loss")
        assert all(row["opponent_name"] not in ("Texas", "Colorado") for row in rows)
        assert worst is None or worst["opponent_name"] not in ("Texas", "Colorado")

    home = _game("v", "where", "Texas", "Colorado", "W", week=7)
    # Week 14 is the 2005 Big 12 Championship, played at Reliant Stadium in
    # Houston -- so "at home" below is what the FACT BLOCK says, not what is
    # true. `games.neutral_site` is 0 for it (issue #343): this asserts the
    # renderer is faithful to the block, and the block is wrong. When #343
    # lands, this expectation becomes "at a neutral site".
    away = _game("v", "where", "Colorado", "Texas", "L", week=14, season_type="regular")
    assert rendered("{v}", [home], texas_colorado_2005, catalog) == "at home"
    assert rendered("{v}", [away], texas_colorado_2005, catalog) == "at home"
    mirrored = _game("v", "where", "Colorado", "Texas", "L", week=7)
    assert rendered("{v}", [mirrored], texas_colorado_2005, catalog) == "on the road"

    # A neutral meeting reads the same from either side.
    (neutral,) = _row(texas_usc_2005, "head_to_head", "meetings")
    assert neutral["neutral_site"] is True
    usc = _game("v", "where", "USC", "Texas", "L")
    assert rendered("{v}", [usc], texas_usc_2005, catalog) == "at a neutral site"


def test_where_for_a_common_opponent_meeting_renders_that_sides_own_venue(
    alabama_auburn_2017: str, catalog: tuple[TeamRecord, ...]
) -> None:
    """The case that could not render at all before #294: a common-opponent
    meeting carried no venue, so the claim was rejected. The two sides played
    the shared opponent in different places, and each renders its own."""
    (mississippi_state,) = [
        c
        for c in _row(alabama_auburn_2017, "common_opponents")
        if c["opponent_name"] == "Mississippi State"
    ]
    assert [(m["week"], m["venue"]) for m in mississippi_state["team_a_meetings"]] == [(11, "away")]
    assert [(m["week"], m["venue"]) for m in mississippi_state["team_b_meetings"]] == [(5, "home")]
    # and those meetings are in no other row of the block
    for side in ("team_a", "team_b"):
        rows = _row(alabama_auburn_2017, side, "quality_wins")
        worst = _row(alabama_auburn_2017, side, "worst_loss")
        assert all(row["opponent_name"] != "Mississippi State" for row in rows)
        assert worst is None or worst["opponent_name"] != "Mississippi State"

    alabama = _game("v", "where", "Alabama", "Mississippi State", "W")
    auburn = _game("v", "where", "Auburn", "Mississippi State", "W")
    assert rendered("{v}", [alabama], alabama_auburn_2017, catalog) == "on the road"
    assert rendered("{v}", [auburn], alabama_auburn_2017, catalog) == "at home"


def test_where_for_a_common_opponent_meeting_no_other_row_holds(
    kilo_lima: str, nfl_catalog: tuple[TeamRecord, ...]
) -> None:
    """Kilo Kings' week-2 tie with Mike Mustangs appears only in
    common_opponents; before #294 nothing in the block said where it was
    played."""
    kilo = _game("v", "where", KILO_KINGS, MIKE_MUSTANGS, "T", week=2)
    assert rendered("{v}", [kilo], kilo_lima, nfl_catalog) == "at home"
    lima = _game("v", "where", LIMA_LIONS, MIKE_MUSTANGS, "W")
    assert rendered("{v}", [lima], kilo_lima, nfl_catalog) == "at home"


# ---------------------------------------------------------------------------
# claim shape and placeholders
# ---------------------------------------------------------------------------


def test_a_placeholder_may_be_used_more_than_once(
    alabama_2017: str, catalog: tuple[TeamRecord, ...]
) -> None:
    claim: dict[str, object] = {"id": "y", "kind": "year"}
    assert rendered("{y}, yes, {y}.", [claim], alabama_2017, catalog) == "2017, yes, 2017."


def test_there_is_no_team_kind(alabama_2017: str, catalog: tuple[TeamRecord, ...]) -> None:
    claim: dict[str, object] = {"id": "t", "kind": "team", "team": "Alabama"}
    errors = rejected("{t} rolled.", [claim], alabama_2017, catalog)
    assert_an_error_says(errors, '"t"', '"team"', "record", "win_pct")


def test_a_key_the_kind_does_not_take_is_rejected_naming_the_keys_it_takes(
    alabama_2017: str, catalog: tuple[TeamRecord, ...]
) -> None:
    claim: dict[str, object] = {"id": "r", "kind": "record", "team": "Alabama", "week": 3}
    errors = rejected("{r}", [claim], alabama_2017, catalog)
    assert_an_error_says(errors, '"r"', '"week"', "id, kind, team")


@pytest.mark.parametrize(
    ("text", "claims", "needles"),
    [
        ("{y}", [{"kind": "year"}], ("claims[0]", '"id"')),
        (
            "{y}",
            [{"id": "y", "kind": "year"}, {"id": "y", "kind": "year"}],
            ('"y"', "more than one"),
        ),
        ("{y} and {z}", [{"id": "y", "kind": "year"}], ("{z}", "y")),
        ("Just prose.", [{"id": "y", "kind": "year"}], ('"y"', "not used")),
        ("{y", [{"id": "y", "kind": "year"}], ("{",)),
        ("{r}", [{"id": "r", "kind": "record"}], ('"r"', '"team"')),
        ("{g}", [{"id": "g", "kind": "game_score", "team": "Alabama"}], ('"g"', '"opponent"')),
        (
            "{g}",
            [{"id": "g", "kind": "game_score", "team": "Alabama", "opponent": "Auburn"}],
            ('"g"', '"result"'),
        ),
        ("{r}", [{"id": "r", "kind": "record", "team": "texas"}], ('"texas"',)),
        ("{r}", [{"id": "r", "kind": "record", "team": "alabama"}], ('"Alabama"',)),
        ("   ", [], ("text",)),
    ],
)
def test_malformed_claims_and_placeholders_are_rejected(
    alabama_2017: str,
    catalog: tuple[TeamRecord, ...],
    text: str,
    claims: list[dict[str, object]],
    needles: tuple[str, ...],
) -> None:
    assert_an_error_says(rejected(text, claims, alabama_2017, catalog), *needles)


_GOOD_GAME: dict[str, object] = {
    "id": "g",
    "kind": "game_score",
    "team": "Alabama",
    "opponent": "Auburn",
    "result": "L",
}


@pytest.mark.parametrize(
    "tool_input",
    [
        None,
        "Alabama rolled.",
        42,
        [],
        {},
        {"text": "Alabama rolled."},
        {"claims": []},
        {"text": 5, "claims": []},
        {"text": ["{g}"], "claims": [_GOOD_GAME]},
        {"text": "{g}", "claims": {"g": _GOOD_GAME}},
        {"text": "{g}", "claims": "g"},
        {"text": "{g}", "claims": ["g"]},
        {"text": "{g}", "claims": [None]},
        {"text": "{g}", "claims": [{**_GOOD_GAME, "week": "13"}]},
        {"text": "{g}", "claims": [{**_GOOD_GAME, "week": True}]},
        {"text": "{g}", "claims": [{**_GOOD_GAME, "week": 13.0}]},
        {"text": "{g}", "claims": [{**_GOOD_GAME, "id": 7}]},
        {"text": "{g}", "claims": [{**_GOOD_GAME, "kind": None}]},
        # unhashable values where a string is expected
        {"text": "{g}", "claims": [{**_GOOD_GAME, "kind": ["rank"]}]},
        {"text": "{g}", "claims": [{**_GOOD_GAME, "kind": {"record": True}}]},
        {"text": "{g}", "claims": [{**_GOOD_GAME, "result": ["L"]}]},
        {"text": "{g}", "claims": [{**_GOOD_GAME, "season_type": ["regular"]}]},
        {"text": "{c}", "claims": [{"id": "c", "kind": "count", "of": {"wins": 1}}]},
        {"text": "{g}", "claims": [{**_GOOD_GAME, "team": ["Alabama"]}]},
        {"text": "{g}", "claims": [{**_GOOD_GAME, "opponent": {"name": "Auburn"}}]},
        {"text": "{g}", "claims": [{**_GOOD_GAME, "result": "loss"}]},
        {"text": "{g}", "claims": [{**_GOOD_GAME, "season_type": "bowl"}]},
        {"text": "{g}", "claims": [{**_GOOD_GAME, 3: "x"}]},
        {"text": "{c}", "claims": [{"id": "c", "kind": "count", "of": ["wins"]}]},
        {"text": "{g}\x00", "claims": [_GOOD_GAME]},
        {"text": "{g}", "claims": [_GOOD_GAME], "extra": True},
    ],
)
def test_malformed_tool_input_returns_errors_and_never_raises(
    alabama_2017: str, catalog: tuple[TeamRecord, ...], tool_input: object
) -> None:
    outcome = check_and_render(tool_input, alabama_2017, catalog)
    assert isinstance(outcome, ClaimOutcome)
    assert outcome.errors
    assert all(isinstance(error, str) and error for error in outcome.errors)
    assert outcome.text is None


def test_the_good_game_used_above_is_itself_accepted(
    alabama_2017: str, catalog: tuple[TeamRecord, ...]
) -> None:
    # Keeps every malformed case above a one-change mutation of a valid input.
    outcome = check_and_render({"text": "{g}", "claims": [_GOOD_GAME]}, alabama_2017, catalog)
    assert outcome == ClaimOutcome(errors=(), text="26-14")


def test_a_hostile_value_is_never_echoed_in_full(
    alabama_2017: str, catalog: tuple[TeamRecord, ...]
) -> None:
    # The errors go back to the narrator as retry feedback, so a 5,000-character
    # id must not be pasted back into the conversation.
    huge = "x" * 5000
    claims: list[dict[str, object]] = [
        {"id": huge, "kind": "year"},
        {"id": "y", "kind": "count", "of": huge},
    ]
    errors = rejected("{x} and {y}", claims, alabama_2017, catalog)
    assert all(len(error) < 400 for error in errors), [len(error) for error in errors]


@pytest.mark.parametrize(
    "tool_input",
    [
        {"text": "\ud800{g}", "claims": [{"id": "g", "kind": "year"}]},
        {"text": "{g} \udfff", "claims": [_GOOD_GAME]},
        {"text": "{g}", "claims": [{**_GOOD_GAME, "team": "Alabama\ud800"}]},
        # a surrogate pair left as two code points is still not valid text
        {"text": "{g}", "claims": [{**_GOOD_GAME, "opponent": chr(0xD83D) + chr(0xDE00)}]},
        {"text": "{g}", "claims": [{**_GOOD_GAME, "id": "g\ud800"}]},
        {"text": "{c}", "claims": [{"id": "c", "kind": "count", "of": "\ud800"}]},
        {"text": "{g}", "claims": [{**_GOOD_GAME, "kind": "\ud800"}]},
        {"text": "{g}", "claims": [{**_GOOD_GAME, "\ud800": "x"}]},
        {"text": "{g}", "claims": [_GOOD_GAME], "\ud800": True},
    ],
)
def test_a_lone_surrogate_is_rejected_and_every_error_is_valid_utf8(
    alabama_2017: str, catalog: tuple[TeamRecord, ...], tool_input: object
) -> None:
    outcome = check_and_render(tool_input, alabama_2017, catalog)
    assert outcome.errors
    assert outcome.text is None
    assert any("surrogate" in error for error in outcome.errors), outcome.errors
    for error in outcome.errors:
        error.encode("utf-8")


def test_a_character_outside_the_basic_plane_is_prose(
    alabama_2017: str, catalog: tuple[TeamRecord, ...]
) -> None:
    claim: dict[str, object] = {"id": "y", "kind": "year"}
    assert rendered("\U0001f525 {y}.", [claim], alabama_2017, catalog) == "\U0001f525 2017."


# ---------------------------------------------------------------------------
# the tool schema
# ---------------------------------------------------------------------------


def test_tool_schema_is_a_valid_anthropic_tool_definition() -> None:
    schema = tool_schema()
    assert schema["name"] == TOOL_NAME == "submit_narration"
    assert isinstance(schema["description"], str) and schema["description"]
    input_schema = schema["input_schema"]
    jsonschema.Draft202012Validator.check_schema(input_schema)
    assert input_schema["required"] == ["text", "claims"]


def test_tool_schema_accepts_a_real_submission_and_names_every_kind() -> None:
    input_schema = tool_schema()["input_schema"]
    jsonschema.validate({"text": "{g}", "claims": [_GOOD_GAME]}, input_schema)
    claim_schema = input_schema["properties"]["claims"]["items"]
    assert set(claim_schema["properties"]["kind"]["enum"]) == {
        "record",
        "rating",
        "rank",
        "game_score",
        "margin",
        "rating_gap",
        "year",
        "count",
        "win_pct",
        "when",
        "where",
    }
    assert set(claim_schema["properties"]) == {
        "id",
        "kind",
        "team",
        "opponent",
        "result",
        "week",
        "season_type",
        "of",
    }
    assert claim_schema["properties"]["of"]["enum"] == [
        "wins",
        "losses",
        "ties",
        "quality_wins",
        "games",
        "common_opponents",
        "meetings",
    ]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"text": "{t}", "claims": [{"id": "t", "kind": "team"}]}, input_schema)


def test_check_and_render_is_pure_on_the_block(
    alabama_2017: str, catalog: tuple[TeamRecord, ...]
) -> None:
    before = _row(alabama_2017, "games")
    claim = _game("w", "when", "Alabama", "Auburn", "L")
    first = check_and_render({"text": "{w}", "claims": [claim]}, alabama_2017, catalog)
    second = check_and_render({"text": "{w}", "claims": [claim]}, alabama_2017, catalog)
    assert first == second == ClaimOutcome(errors=(), text="in week 13")
    assert _row(alabama_2017, "games") == before


# ---------------------------------------------------------------------------
# `when` renders no "regular-season finale" until #300 (founder decision 2 on
# #291, 2026-09-15)
# ---------------------------------------------------------------------------

# Every team case the #291 brief measured, with its last season_type='regular'
# game: a conference title game in five of the nine, a true finale in four.
# The engine cannot tell the two apart yet (#300), so both print their week.
LAST_REGULAR_GAMES: list[tuple[int, str, str, int]] = [
    (2003, "LSU", "Georgia", 16),
    (2005, "Texas", "Colorado", 14),
    (2013, "Florida State", "Duke", 15),
    (2019, "LSU", "Georgia", 15),
    (2017, "Auburn", "Georgia", 14),
    (2001, "Miami", "Virginia Tech", 15),
    (2004, "USC", "UCLA", 15),
    (2005, "USC", "UCLA", 14),
    (2017, "Alabama", "Auburn", 13),
]


@pytest.mark.parametrize(("year", "team", "opponent", "week"), LAST_REGULAR_GAMES)
def test_the_last_regular_season_game_renders_its_week_not_a_finale(
    catalog: tuple[TeamRecord, ...], year: int, team: str, opponent: str, week: int
) -> None:
    block = cfb_team_case_block(year, team)
    regular = [g for g in _row(block, "games") if g["season_type"] == "regular"]
    last = regular[-1]
    assert (last["opponent_name"], last["week"]) == (opponent, week)
    claim = _game("w", "when", team, opponent, last["result"], week=week, season_type="regular")
    assert rendered("It happened {w}.", [claim], block, catalog) == f"It happened in week {week}."


@pytest.mark.parametrize(
    ("year", "team", "opponent", "result", "extra", "expected"),
    [
        # Texas met Colorado twice in 2005 (week 7 and week 14)
        (2005, "Texas", "Colorado", "W", {"week": 14, "season_type": "regular"}, "in week 14"),
        # Auburn met Georgia twice in 2017 (a week-11 win, the week-14 title-game loss)
        (2017, "Auburn", "Georgia", "L", {"week": 14, "season_type": "regular"}, "in week 14"),
        (2005, "Texas", "Louisiana", "W", {}, "to open the season"),
        (2005, "Texas", "USC", "W", {}, "in the postseason"),
    ],
)
def test_when_keeps_the_opener_and_the_postseason(
    catalog: tuple[TeamRecord, ...],
    year: int,
    team: str,
    opponent: str,
    result: str,
    extra: dict[str, object],
    expected: str,
) -> None:
    block = cfb_team_case_block(year, team)
    claim = _game("w", "when", team, opponent, result, **extra)
    assert rendered("{w}", [claim], block, catalog) == expected


def test_no_when_on_any_measured_block_says_finale(catalog: tuple[TeamRecord, ...]) -> None:
    for year, team, _, _ in LAST_REGULAR_GAMES:
        block = cfb_team_case_block(year, team)
        for game in _row(block, "games"):
            claim = _game(
                "w",
                "when",
                team,
                game["opponent_name"],
                game["result"],
                week=game["week"],
                season_type=game["season_type"],
            )
            outcome = check_and_render({"text": "{w}", "claims": [claim]}, block, catalog)
            assert outcome.text is not None, outcome.errors
            assert "finale" not in outcome.text


# ---------------------------------------------------------------------------
# the claim cap (founder decision 1 on #291, 2026-09-15)
# ---------------------------------------------------------------------------


def _texas_claims() -> list[dict[str, object]]:
    """Eight valid claims on the 2005 Texas team case, three of them game scores."""
    return [
        {"id": "rec", "kind": "record", "team": "Texas"},
        {"id": "yr", "kind": "year"},
        _game("g1", "game_score", "Texas", "USC", "W"),
        _game("w1", "when", "Texas", "USC", "W"),
        _game("g2", "game_score", "Texas", "Ohio State", "W"),
        _game("g3", "game_score", "Texas", "Oklahoma", "W"),
        {"id": "rk", "kind": "rank", "team": "Texas"},
        {"id": "n", "kind": "count", "of": "wins", "team": "Texas"},
    ]


_TEXAS_EIGHT = (
    "Look at {rec} in {yr}: {g1} over USC {w1}, {g2} over Ohio State and {g3} over Oklahoma. "
    "The math has {rk} with {n} wins."
)


def test_the_cap_is_eight_claims_and_three_game_scores() -> None:
    assert (MAX_CLAIMS, MAX_GAME_SCORE_CLAIMS) == (8, 3)


def test_eight_claims_with_three_game_scores_are_accepted(
    texas_2005: str, catalog: tuple[TeamRecord, ...]
) -> None:
    assert rendered(_TEXAS_EIGHT, _texas_claims(), texas_2005, catalog) == (
        "Look at Texas 13-0 in 2005: 41-38 over USC in the postseason, 25-22 over Ohio State "
        "and 45-12 over Oklahoma. The math has No. 1 Texas with 13 wins."
    )


def test_a_ninth_claim_is_rejected_with_the_count_and_the_limit(
    texas_2005: str, catalog: tuple[TeamRecord, ...]
) -> None:
    claims: list[dict[str, object]] = [
        *_texas_claims(),
        {"id": "pct", "kind": "win_pct", "team": "Texas"},
    ]
    errors = rejected(_TEXAS_EIGHT + " That's {pct}.", claims, texas_2005, catalog)
    assert len(errors) == 1, errors
    assert_an_error_says(
        errors, "9 claims", "limit of 8", "keep only the figures that make the case"
    )


def test_a_fourth_game_score_is_rejected_with_the_count_and_the_limit(
    texas_2005: str, catalog: tuple[TeamRecord, ...]
) -> None:
    claims = [claim for claim in _texas_claims() if claim["id"] != "w1"] + [
        _game("g4", "game_score", "Texas", "Colorado", "W", week=14, season_type="regular")
    ]
    assert len(claims) == 8
    text = (
        "Look at {rec} in {yr}: {g1} over USC, {g2}, {g3} and {g4} over Colorado. "
        "The math has {rk} with {n} wins."
    )
    errors = rejected(text, claims, texas_2005, catalog)
    assert len(errors) == 1, errors
    assert_an_error_says(
        errors, "4 game_score claims", "limit of 3", "keep only the games that make the case"
    )


def test_both_caps_are_reported_first_so_capped_feedback_always_holds_them(
    texas_2005: str, catalog: tuple[TeamRecord, ...]
) -> None:
    claims: list[dict[str, object]] = [
        {
            "id": f"g{week}",
            "kind": "game_score",
            "team": "Texas",
            "opponent": opponent,
            "result": "W",
        }
        for week, opponent in enumerate(
            [
                "Louisiana",
                "Ohio State",
                "Rice",
                "Missouri",
                "Oklahoma",
                "Texas Tech",
                "Oklahoma State",
                "Baylor",
                "Kansas",
            ]
        )
    ]
    # An error from the text as well, so the caps must come before it.
    text = "The Longhorns: " + ", ".join(f"{{{claim['id']}}}" for claim in claims) + "."
    errors = rejected(text, claims, texas_2005, catalog)
    assert "9 claims" in errors[0] and "limit of 8" in errors[0], errors
    assert "9 game_score claims" in errors[1] and "limit of 3" in errors[1], errors
    assert any("Longhorns" in error for error in errors[2:]), errors


def test_the_tool_description_states_both_limits() -> None:
    description = tool_schema()["description"]
    assert "at most 8 claims" in description
    assert "at most 3 of them game_score" in description


def test_the_claims_grounding_version() -> None:
    assert GROUNDING_VERSION == "claims-v1"
