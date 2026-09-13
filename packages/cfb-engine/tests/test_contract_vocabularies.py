"""The engine's two closed vocabularies, `Sport` and `Method`, are named once
in `cfb_strength.contracts`. Every engine surface that enumerates either one
must agree with that single definition (issue #112, epic #113).

Before #112, `Literal["cfb", "nfl"]` was written out inline in contracts.py,
evidence/proof.py and mcp_server/server.py. On top of that,
compute_ratings had `choices=("cfb", "nfl")` and cli.py had a hand-written
if/if dispatch, and the method list existed only as the keys of
`compute_ratings.METHODS`. Nothing checked that any pair agreed.
`apps/api` now imports both aliases from here, so:

- a league or method the engine gains without the alias turns THIS file red;
- one the alias gains without the engine also turns this file red (the
  registries below would disagree), and turns apps/api's and apps/web's
  vocabulary checks red until they follow.

Every test compares the alias against a registry the engine actually uses at
runtime (`ELO_CONFIGS`, `METHODS`, the CLI's dispatch table, argparse), never
against a second hand-written copy in this file. A hardcoded tuple here
would only prove that the test and the alias agree with each other.
"""

from __future__ import annotations

import typing
from typing import Any

import pytest

from cfb_strength import cli
from cfb_strength.contracts import ComparisonResult, GameRow, Method, Sport, TeamRow
from cfb_strength.evidence import proof
from cfb_strength.mcp_server import server
from cfb_strength.ratings import compute_ratings
from cfb_strength.ratings.elo import ELO_CONFIGS

SPORTS: tuple[str, ...] = typing.get_args(Sport)
METHODS: tuple[str, ...] = typing.get_args(Method)


def test_aliases_are_non_empty_literals_of_distinct_strings() -> None:
    # Floor for everything below: an empty or malformed alias would make every
    # set comparison in this file pass or fail for the wrong reason.
    for values in (SPORTS, METHODS):
        assert values, "alias has no values"
        assert all(isinstance(v, str) for v in values)
        assert len(set(values)) == len(values)


# ---------------------------------------------------------------------------
# Method
# ---------------------------------------------------------------------------


def test_method_alias_matches_the_registered_rating_methods() -> None:
    # Order included: the alias's docstring promises display order, and the
    # API and web publish and mirror the alias in that order.
    assert METHODS == tuple(compute_ratings.METHODS), (
        "contracts.Method and compute_ratings.METHODS disagree, in membership or "
        "order. Register a rating method in both, in the same position (apps/api "
        "and apps/web follow the alias)."
    )


# ---------------------------------------------------------------------------
# Sport
# ---------------------------------------------------------------------------


def test_sport_alias_matches_the_elo_config_registry() -> None:
    assert set(SPORTS) == set(ELO_CONFIGS), (
        "contracts.Sport and ratings.elo.ELO_CONFIGS disagree: every league "
        "needs an Elo tuning, and every tuned league needs to be in the alias."
    )


def test_cli_ingest_dispatches_exactly_the_sport_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every league in the alias reaches its own real ingest entry point, and
    the dispatch table has no league the alias lacks. (The entry points'
    signatures are checked by mypy --strict through `cli.IngestMain`.)"""
    assert set(cli.INGEST_ENTRY_POINTS) == set(SPORTS)

    targets = {sport: load() for sport, load in cli.INGEST_ENTRY_POINTS.items()}
    for sport, target in targets.items():
        assert callable(target), f"{sport}'s ingest entry point is not callable"
        assert target.__module__.startswith("cfb_strength.ingest"), (sport, target.__module__)
    assert len({t.__module__ for t in targets.values()}) == len(targets), (
        "two leagues dispatch to the same ingest module"
    )

    called: list[tuple[str, list[str]]] = []
    for sport in SPORTS:

        def load_fake(_sport: str = sport) -> cli.IngestMain:
            def fake_main(argv: list[str]) -> int:
                called.append((_sport, argv))
                return 0

            return fake_main

        monkeypatch.setitem(cli.INGEST_ENTRY_POINTS, sport, load_fake)

    for sport in SPORTS:
        assert cli.main(["ingest", "--sport", sport, "--years", "2005"]) == 0

    assert called == [(sport, ["--years", "2005"]) for sport in SPORTS]


def test_cli_ingest_rejects_a_sport_outside_the_alias(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["ingest", "--sport", "curling", "--years", "2005"]) == 2
    err = capsys.readouterr().err
    for sport in SPORTS:
        assert sport in err, "the error should name every valid league"


def test_cli_usage_advertises_both_aliases() -> None:
    assert "{" + ",".join(SPORTS) + "}" in cli.USAGE
    assert "{" + ",".join(METHODS) + "}" in cli.USAGE


def test_rate_cli_sport_choices_are_exactly_the_alias(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Compares the exact choice set argparse publishes. Checking "accepts every
    alias league, rejects one made-up league" is not enough: a hand-written
    `choices=` that gains an extra league still passes both, and that
    exact sabotage stayed green against an earlier version of this test."""
    monkeypatch.setenv("COLUMNS", "500")  # keep argparse from wrapping the usage line
    with pytest.raises(SystemExit) as excinfo:
        compute_ratings.main(["--help"])
    assert excinfo.value.code == 0
    assert "--sport {" + ",".join(SPORTS) + "}" in capsys.readouterr().out


def test_rate_cli_rejects_a_sport_outside_the_alias() -> None:
    with pytest.raises(SystemExit):
        compute_ratings.main(["--years", "not-a-year", "--sport", "curling"])


# ---------------------------------------------------------------------------
# the alias is the one actually used, not a lookalike copy
# ---------------------------------------------------------------------------


def test_mcp_server_uses_the_contract_alias_itself() -> None:
    assert server.Sport is Sport


@pytest.mark.parametrize(
    "fn",
    [
        proof.list_available_years,
        proof.resolve_team,
        proof.build_team_case,
        proof.build_comparison,
    ],
    ids=lambda fn: fn.__name__,
)
def test_evidence_public_api_takes_the_contract_sport(fn: Any) -> None:
    assert typing.get_type_hints(fn)["sport"] == Sport


@pytest.mark.parametrize("row_type", [GameRow, TeamRow], ids=lambda t: t.__name__)
def test_row_contracts_declare_the_contract_sport(row_type: type) -> None:
    assert typing.get_type_hints(row_type)["sport"] == Sport


# `TeamCase` joins this list once its `method` is narrowed from `str` (#139).
@pytest.mark.parametrize("result_type", [ComparisonResult], ids=lambda t: t.__name__)
def test_result_contracts_declare_the_contract_method(result_type: type) -> None:
    """Issue #152: the method a verdict echoes is the closed `Method`
    vocabulary, so apps/api can publish it as an enum rather than a free
    string."""
    assert typing.get_type_hints(result_type)["method"] == Method


# ---------------------------------------------------------------------------
# data can't get ahead of the alias
# ---------------------------------------------------------------------------


def _game_row(sport: Any) -> GameRow:
    return GameRow(
        id=1,
        season=2005,
        week=1,
        season_type="regular",
        start_date=None,
        neutral_site=False,
        completed=True,
        home_team_id=1,
        away_team_id=2,
        home_team="Home",
        away_team="Away",
        home_points=21,
        away_points=14,
        home_conference=None,
        away_conference=None,
        home_classification=None,
        away_classification=None,
        venue=None,
        raw_json="{}",
        sport=sport,
    )


def _team_row(sport: Any) -> TeamRow:
    return TeamRow(id=1, school="Home", classification=None, conference=None, sport=sport)


@pytest.mark.parametrize("build", [_game_row, _team_row], ids=["GameRow", "TeamRow"])
def test_row_contracts_accept_every_sport_in_the_alias(build: Any) -> None:
    for sport in SPORTS:
        assert build(sport).sport == sport


@pytest.mark.parametrize("build", [_game_row, _team_row], ids=["GameRow", "TeamRow"])
def test_row_contracts_reject_a_sport_outside_the_alias(build: Any) -> None:
    """The type annotation is static only. Without a runtime check, an ingest
    path passing an unlisted league as a plain `str` would write it into
    games/teams, and every downstream Literal would silently disagree with
    the data. That is #112's "the engine's data gains a league" row."""
    with pytest.raises(ValueError) as excinfo:
        build("curling")
    message = str(excinfo.value)
    assert "curling" in message
    for sport in SPORTS:
        assert sport in message
