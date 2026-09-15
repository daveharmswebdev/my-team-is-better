"""Failing-first tests for #291 round 2 (founder decision 2, 2026-09-15): a
record, rank or rating placeholder leaves its team's name off when the nearest
team reference before it in the same sentence is that same team.

Round 1's live run of 13 claude-haiku-4-5 narrations served 4 that doubled a
name ("Auburn went Auburn 10-4 and that's No. 12 Auburn all day"). The rule,
within one sentence (claims.py's sentence break), left to right:

* a team reference is a block team's name typed in the prose, or any
  placeholder;
* a record, rank or rating placeholder for team T renders without T's name
  when the nearest reference before it refers to T, and with the name
  otherwise; either way it then counts as a reference to T;
* a game_score, margin, when, where or rating_gap placeholder refers to two
  teams, so a name-kind placeholder right after it keeps its name;
* year, count and win_pct placeholders don't change the nearest reference.

The other direction is the point of the gate: a figure never loses its name
when another team sits between it and its team's last mention, so it can
never be read as another team's.

The recorded submissions below are the live run's tool inputs, verbatim
(recorded on PR #306), on the real fixture blocks they were narrated from.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fixtures.claim_blocks import (
    KILO_KINGS,
    LIMA_LIONS,
    catalog_of,
    cfb_catalog,
    cfb_comparison_block,
    cfb_team_case_block,
    nfl_tie_comparison_block,
    rejected,
    rendered,
)
from fixtures.sport_fixture import make_sport_fixture_db

from api.persona.claims import check_and_render
from api.repositories.teams import TeamRecord


@pytest.fixture(scope="module")
def catalog() -> tuple[TeamRecord, ...]:
    return cfb_catalog()


@pytest.fixture(scope="module")
def alabama_2017() -> str:
    return cfb_team_case_block(2017, "Alabama")


@pytest.fixture(scope="module")
def fsu_msu_2013() -> str:
    return cfb_comparison_block(2013, "Florida State", "Michigan State")


_REC: dict[str, object] = {"id": "rec", "kind": "record", "team": "Alabama"}
_RANK: dict[str, object] = {"id": "rk", "kind": "rank", "team": "Alabama"}


def _game(claim_id: str, kind: str, opponent: str) -> dict[str, object]:
    """A game claim for a 2017 Alabama win."""
    return {"id": claim_id, "kind": kind, "team": "Alabama", "opponent": opponent, "result": "W"}


# ---------------------------------------------------------------------------
# the live run's recorded submissions (tool inputs verbatim)
# ---------------------------------------------------------------------------


def test_auburn_2017_drops_every_doubled_name_and_keeps_the_other_teams_ranks(
    catalog: tuple[TeamRecord, ...],
) -> None:
    tool_input = {
        "text": (
            "Look, I know the human polls saw it different that year, but the numbers don't "
            "lie: Auburn went {rec} and that's {rk} all day. They beat {rank1} and {rank2} "
            "straight up — that's not luck, that's quality — and they did it against "
            "Alabama's best team of the era {g1}. The math counts every point of every game, "
            "and {rec} at {rk} is what you earn when you play this schedule and come out on "
            "top when it matters."
        ),
        "claims": [
            {"id": "rec", "kind": "record", "team": "Auburn"},
            {"id": "rk", "kind": "rank", "team": "Auburn"},
            {"id": "rank1", "kind": "rank", "team": "Alabama"},
            {"id": "rank2", "kind": "rank", "team": "Georgia"},
            {
                "id": "g1",
                "kind": "game_score",
                "team": "Auburn",
                "opponent": "Alabama",
                "result": "W",
            },
        ],
    }
    outcome = check_and_render(tool_input, cfb_team_case_block(2017, "Auburn"), catalog)
    assert outcome.errors == ()
    assert outcome.text == (
        "Look, I know the human polls saw it different that year, but the numbers don't lie: "
        "Auburn went 10-4 and that's No. 12 all day. They beat No. 1 Alabama and No. 3 Georgia "
        "straight up — that's not luck, that's quality — and they did it against Alabama's "
        "best team of the era 26-14. The math counts every point of every game, and Auburn "
        "10-4 at No. 12 is what you earn when you play this schedule and come out on top when "
        "it matters."
    )


def test_usc_2004_drops_oklahoma_after_oklahoma_and_keeps_the_opening_record_s_name(
    catalog: tuple[TeamRecord, ...],
) -> None:
    tool_input = {
        "text": (
            "Look at {rec} in {yr}: USC didn't just win it all, they ran through everybody on "
            "the schedule and capped it off {w1} against Oklahoma — a team ranked {ok_rank} "
            "and they absolutely demolished them {g1}. That's not a miracle run, that's a "
            "machine, and the math put them exactly where they belong."
        ),
        "claims": [
            {"id": "rec", "kind": "record", "team": "USC"},
            {"id": "yr", "kind": "year"},
            {"id": "w1", "kind": "when", "team": "USC", "opponent": "Oklahoma", "result": "W"},
            {"id": "ok_rank", "kind": "rank", "team": "Oklahoma"},
            {
                "id": "g1",
                "kind": "game_score",
                "team": "USC",
                "opponent": "Oklahoma",
                "result": "W",
                "season_type": "postseason",
            },
        ],
    }
    outcome = check_and_render(tool_input, cfb_team_case_block(2004, "USC"), catalog)
    assert outcome.errors == ()
    assert outcome.text == (
        "Look at USC 13-0 in 2004: USC didn't just win it all, they ran through everybody on "
        "the schedule and capped it off in the postseason against Oklahoma — a team ranked "
        "No. 3 and they absolutely demolished them 55-19. That's not a miracle run, that's a "
        "machine, and the math put them exactly where they belong."
    )


def test_nfl_kilo_lima_keeps_another_team_s_rank_name(tmp_path: Path) -> None:
    db = make_sport_fixture_db(tmp_path)
    tool_input = {
        "text": (
            "{r1} sits atop the standings with a perfect record — no losses, and they took "
            "down {r2} straight up {g1}. When these teams both faced Mike Mustangs, Lima Lions "
            "handled them {g2}, while Kilo Kings needed another shot just to get it done {g3}. "
            "The math has spoken: {r1} is the real deal."
        ),
        "claims": [
            {"id": "r1", "kind": "rank", "team": LIMA_LIONS},
            {"id": "r2", "kind": "rank", "team": KILO_KINGS},
            {
                "id": "g1",
                "kind": "game_score",
                "team": LIMA_LIONS,
                "opponent": KILO_KINGS,
                "result": "W",
                "week": 1,
                "season_type": "regular",
            },
            {
                "id": "g2",
                "kind": "game_score",
                "team": LIMA_LIONS,
                "opponent": "Mike Mustangs",
                "result": "W",
                "week": 2,
                "season_type": "regular",
            },
            {
                "id": "g3",
                "kind": "game_score",
                "team": KILO_KINGS,
                "opponent": "Mike Mustangs",
                "result": "W",
                "week": 4,
                "season_type": "regular",
            },
        ],
    }
    outcome = check_and_render(tool_input, nfl_tie_comparison_block(db), catalog_of(db, "nfl"))
    assert outcome.errors == ()
    assert outcome.text == (
        "No. 5 Lima Lions sits atop the standings with a perfect record — no losses, and they "
        "took down No. 6 Kilo Kings straight up 20-13. When these teams both faced Mike "
        "Mustangs, Lima Lions handled them 27-10, while Kilo Kings needed another shot just to "
        "get it done 31-14. The math has spoken: No. 5 Lima Lions is the real deal."
    )


def test_lsu_2019_name_after_its_record_is_still_rejected(
    catalog: tuple[TeamRecord, ...],
) -> None:
    tool_input = {
        "text": (
            "Look at {rec}: LSU ran the table and it wasn't even close. They beat {g1} to open "
            "the season, walked through Alabama with {g2}, and then when it mattered most, they "
            "went out and demolished {g3} to seal it. That's not controversy, that's a machine "
            "that finished what it started."
        ),
        "claims": [
            {"id": "rec", "kind": "record", "team": "LSU"},
            {
                "id": "g1",
                "kind": "game_score",
                "team": "LSU",
                "opponent": "Georgia Southern",
                "result": "W",
            },
            {"id": "g2", "kind": "game_score", "team": "LSU", "opponent": "Alabama", "result": "W"},
            {"id": "g3", "kind": "game_score", "team": "LSU", "opponent": "Clemson", "result": "W"},
        ],
    }
    outcome = check_and_render(tool_input, cfb_team_case_block(2019, "LSU"), catalog)
    assert outcome.text is None
    assert outcome.errors == (
        '{rec} already prints the name "LSU"; delete the "LSU" typed beside it',
    )


def test_alabama_2017_name_after_its_rating_is_still_rejected(
    alabama_2017: str, catalog: tuple[TeamRecord, ...]
) -> None:
    tool_input = {
        "text": (
            "Look, I know the human polls saw it different that year, but {rec} and {ranking} "
            "don't lie—the math has {rating} Alabama running through the gauntlet and finishing "
            "with a pair of postseason wins that mattered: they beat {g1} and then {g2} to seal "
            "it. That Auburn loss stung, but the numbers counted every point of those "
            "championship runs."
        ),
        "claims": [
            {"id": "rec", "kind": "record", "team": "Alabama"},
            {"id": "ranking", "kind": "rank", "team": "Alabama"},
            {"id": "rating", "kind": "rating", "team": "Alabama"},
            {
                "id": "g1",
                "kind": "game_score",
                "team": "Alabama",
                "opponent": "Clemson",
                "result": "W",
                "season_type": "postseason",
            },
            {
                "id": "g2",
                "kind": "game_score",
                "team": "Alabama",
                "opponent": "Georgia",
                "result": "W",
                "season_type": "postseason",
            },
        ],
    }
    outcome = check_and_render(tool_input, alabama_2017, catalog)
    assert outcome.text is None
    assert outcome.errors == (
        '{rating} already prints the name "Alabama"; delete the "Alabama" typed beside it',
    )


# ---------------------------------------------------------------------------
# each clause of the rule
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "claims", "expected"),
    [
        # the same team with nothing between: dropped
        ("Alabama went {rec} that year.", [_REC], "Alabama went 13-1 that year."),
        ("Alabama sat at {rk} all year.", [_RANK], "Alabama sat at No. 1 all year."),
        # a rank placeholder, then the same team's record: dropped
        (
            "The math has {rk} at {rec}.",
            [_RANK, _REC],
            "The math has No. 1 Alabama at 13-1.",
        ),
        # year, count and win_pct don't change the nearest reference
        (
            "Alabama in {yr} went {rec}.",
            [{"id": "yr", "kind": "year"}, _REC],
            "Alabama in 2017 went 13-1.",
        ),
        (
            "Alabama won {n} and went {rec}.",
            [{"id": "n", "kind": "count", "of": "wins", "team": "Alabama"}, _REC],
            "Alabama won 13 and went 13-1.",
        ),
        (
            "Alabama hit {p} and went {rec}.",
            [{"id": "p", "kind": "win_pct", "team": "Alabama"}, _REC],
            "Alabama hit .929 and went 13-1.",
        ),
        # a name typed immediately before its own placeholder: accepted, dropped
        ("Alabama ({rec}) rolled.", [_REC], "Alabama (13-1) rolled."),
        ("Alabama's {rec} says it all.", [_REC], "Alabama's 13-1 says it all."),
    ],
)
def test_the_name_is_dropped_after_the_same_team(
    alabama_2017: str,
    catalog: tuple[TeamRecord, ...],
    text: str,
    claims: list[dict[str, object]],
    expected: str,
) -> None:
    assert rendered(text, claims, alabama_2017, catalog) == expected


def test_a_rating_is_dropped_after_the_same_team(
    fsu_msu_2013: str, catalog: tuple[TeamRecord, ...]
) -> None:
    claim: dict[str, object] = {"id": "r", "kind": "rating", "team": "Florida State"}
    assert (
        rendered("Florida State rates {r}, period.", [claim], fsu_msu_2013, catalog)
        == "Florida State rates 4.57, period."
    )


@pytest.mark.parametrize(
    ("text", "claims", "expected"),
    [
        # another typed team between: kept
        (
            "Alabama got past Georgia and still went {rec}.",
            [_REC],
            "Alabama got past Georgia and still went Alabama 13-1.",
        ),
        # another team's placeholder between: kept
        (
            "Alabama beat {uga} and went {rec}.",
            [{"id": "uga", "kind": "rank", "team": "Georgia"}, _REC],
            "Alabama beat No. 3 Georgia and went Alabama 13-1.",
        ),
        # game_score, margin, when and where refer to two teams: kept
        (
            "Alabama won {g} and went {rec}.",
            [_game("g", "game_score", "Georgia"), _REC],
            "Alabama won 26-23 and went Alabama 13-1.",
        ),
        (
            "Alabama won by {m} and went {rec}.",
            [_game("m", "margin", "Georgia"), _REC],
            "Alabama won by 3 and went Alabama 13-1.",
        ),
        (
            "Alabama won {w} and went {rec}.",
            [_game("w", "when", "Georgia"), _REC],
            "Alabama won in the postseason and went Alabama 13-1.",
        ),
        (
            "Alabama won {v} and sat at {rk}.",
            [_game("v", "where", "Florida State"), _RANK],
            "Alabama won at a neutral site and sat at No. 1 Alabama.",
        ),
        # a sentence break between: kept
        ("Alabama rolled. {rec} says it all.", [_REC], "Alabama rolled. Alabama 13-1 says it all."),
        ("Alabama rolled! {rk} says so.", [_RANK], "Alabama rolled! No. 1 Alabama says so."),
        # the first mention in a sentence: kept
        ("Look at {rec}.", [_REC], "Look at Alabama 13-1."),
    ],
)
def test_the_name_is_kept_when_anything_else_refers_between(
    alabama_2017: str,
    catalog: tuple[TeamRecord, ...],
    text: str,
    claims: list[dict[str, object]],
    expected: str,
) -> None:
    assert rendered(text, claims, alabama_2017, catalog) == expected


def test_a_rating_gap_between_keeps_the_name(
    fsu_msu_2013: str, catalog: tuple[TeamRecord, ...]
) -> None:
    claims: list[dict[str, object]] = [
        {"id": "gap", "kind": "rating_gap", "team": "Florida State", "opponent": "Michigan State"},
        {"id": "r", "kind": "rating", "team": "Florida State"},
    ]
    assert (
        rendered("Florida State sits {gap} clear at {r}.", claims, fsu_msu_2013, catalog)
        == "Florida State sits 0.29 clear at Florida State 4.57."
    )


def test_a_repeated_placeholder_is_decided_at_each_use(
    alabama_2017: str, catalog: tuple[TeamRecord, ...]
) -> None:
    assert (
        rendered("Look at {rec}. Alabama went {rec}.", [_REC], alabama_2017, catalog)
        == "Look at Alabama 13-1. Alabama went 13-1."
    )


@pytest.mark.parametrize(
    ("text", "claim"),
    [
        ("{rec} Alabama rolled.", _REC),
        ("{rec}, Alabama rolled.", _REC),
        ("Alabama went {rec}: Alabama rolled.", _REC),
        ("They had {rk} Alabama on top.", _RANK),
    ],
)
def test_a_name_typed_immediately_after_its_own_placeholder_is_still_an_error(
    alabama_2017: str, catalog: tuple[TeamRecord, ...], text: str, claim: dict[str, object]
) -> None:
    errors = rejected(text, [claim], alabama_2017, catalog)
    placeholder = "{" + str(claim["id"]) + "}"
    expected = f'{placeholder} already prints the name "Alabama"; delete the "Alabama" typed '
    assert expected + "beside it" in errors
