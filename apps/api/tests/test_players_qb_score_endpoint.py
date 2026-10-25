"""`GET /api/players/compare`'s `qb_score` (issue #451, epic #439): two
quarterbacks' deterministic era-adjusted QB score, published field for field
from `cfb_strength.players.get_qb_score_comparison` on the committed
fixture's real NFL 1999 + 2023 slice.

The API adds the score and nothing else: no rounding, no recomputation, no
reordering of seasons, and no winner of its own. The expectation is the
engine's own answer on the same fixture db, so a mapping that swaps `a` and
`b`, drops a season or rounds a z-score fails here, while no number from the
spike is hard-coded. The two scoring parameters the engine's comparison does
not carry (the qualifying line and the peak length) come from
`cfb_strength.contracts`' constants.

Fixture players, measured (regular season, dropbacks = attempts + sacks):
Kurt Warner (1999, 481) and Steve McNair (1999) both qualify, so the score is
conclusive. Randall Cunningham (1999, 214) and Tommy DeVito (2023, 215) are
quarterbacks below the 224-dropback line, so each has seasons shown but none
scored: one of them makes the comparison inconclusive for that side, both make
it inconclusive for both. Marshall Faulk and Edgerrin James are two RBs: a
comparable pair, but not quarterbacks, so `qb_score` is JSON `null`.
"""

from __future__ import annotations

from typing import Any, get_args

import pytest
from cfb_strength.contracts import (
    QB_SCORE_MIN_DROPBACKS,
    QB_SCORE_PEAK_SEASONS,
    QB_SCORE_VERSION,
    QB_SCORE_WEIGHTS,
    QbScoreInconclusiveReason,
    QbScoreMetric,
    QbScoreSide,
)
from cfb_strength.players import get_qb_score_comparison
from fastapi.testclient import TestClient
from fixtures.player_api_fixture import engine_json, fixture_conn

COMPARE = "/api/players/compare"

KURT_WARNER = 2044124519
STEVE_MCNAIR = 2385180619
RANDALL_CUNNINGHAM = 2024782845
TOMMY_DEVITO = 2031699001
MARSHALL_FAULK = 2252790861
EDGERRIN_JAMES = 2425879833

QB_SCORE_COMPARISON_KEYS = {
    "sport",
    "version",
    "a",
    "b",
    "career_winner",
    "peak_winner",
    "career_margin",
    "peak_margin",
    "inconclusive",
    "weights",
    "min_dropbacks",
    "peak_seasons",
}
QB_SCORE_KEYS = {
    "sport",
    "player_id",
    "display_name",
    "version",
    "seasons",
    "qualifying_seasons",
    "career",
    "peak",
    "peak_filled_with_average",
    "first_season",
    "first_scored_season",
}
QB_SCORE_SEASON_KEYS = {
    "season",
    "dropbacks",
    "qualifies",
    "epa_per_dropback",
    "rush_epa_per_play",
    "any_a",
    "composite",
    "in_peak",
}
QB_METRIC_VALUE_KEYS = {"value", "season_mean", "season_sd", "z"}

NEW_MODELS = (
    "PlayerQbScoreComparisonOut",
    "PlayerQbScoreOut",
    "PlayerQbScoreSeasonOut",
    "PlayerQbMetricValueOut",
)


def _compare(client: TestClient, **params: Any) -> dict[str, Any]:
    response = client.get(COMPARE, params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _engine_qb_score(a: int, b: int) -> dict[str, Any]:
    """The engine's comparison as the JSON the API must publish: every
    dataclass field under its own name, plus the two contract constants."""
    with fixture_conn() as conn:
        comparison = get_qb_score_comparison(conn, sport="nfl", a=a, b=b)
    expected: dict[str, Any] = engine_json(comparison)
    expected["weights"] = dict(comparison.weights)
    expected["min_dropbacks"] = QB_SCORE_MIN_DROPBACKS
    expected["peak_seasons"] = QB_SCORE_PEAK_SEASONS
    return expected


QB_PAIRS = [
    (KURT_WARNER, STEVE_MCNAIR),
    (STEVE_MCNAIR, KURT_WARNER),
    (KURT_WARNER, RANDALL_CUNNINGHAM),
    (RANDALL_CUNNINGHAM, KURT_WARNER),
    (RANDALL_CUNNINGHAM, TOMMY_DEVITO),
]


# ---------------------------------------------------------------------------
# faithful to the engine, field for field
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("a,b", QB_PAIRS)
def test_qb_score_is_the_engines_comparison_field_for_field(
    client: TestClient, a: int, b: int
) -> None:
    score = _compare(client, a=a, b=b)["qb_score"]

    assert score is not None
    assert set(score) == QB_SCORE_COMPARISON_KEYS
    for side in ("a", "b"):
        assert set(score[side]) == QB_SCORE_KEYS
        assert score[side]["seasons"], f"{side} has no seasons on the fixture"
        for season in score[side]["seasons"]:
            assert set(season) == QB_SCORE_SEASON_KEYS
            for metric in ("epa_per_dropback", "rush_epa_per_play", "any_a"):
                if season[metric] is not None:
                    assert set(season[metric]) == QB_METRIC_VALUE_KEYS
    assert score == _engine_qb_score(a, b)


def test_the_conclusive_pair_has_winners_and_margins_that_swap_with_the_sides(
    client: TestClient,
) -> None:
    forward = _compare(client, a=KURT_WARNER, b=STEVE_MCNAIR)["qb_score"]
    backward = _compare(client, a=STEVE_MCNAIR, b=KURT_WARNER)["qb_score"]

    assert forward["inconclusive"] is None
    assert forward["a"]["player_id"] == KURT_WARNER
    assert forward["b"]["player_id"] == STEVE_MCNAIR
    assert forward["career_winner"] in get_args(QbScoreSide)
    assert forward["peak_winner"] in get_args(QbScoreSide)
    swapped = {"a": "b", "b": "a"}
    assert backward["career_winner"] == swapped[forward["career_winner"]]
    assert backward["peak_winner"] == swapped[forward["peak_winner"]]
    assert backward["career_margin"] == -forward["career_margin"]
    assert backward["peak_margin"] == -forward["peak_margin"]
    # Each side's score is that player's, whichever side he is on.
    assert backward["a"] == forward["b"]
    assert backward["b"] == forward["a"]
    # The margin is a's minus b's, as the engine defines it, copied unrounded.
    assert forward["career_margin"] == forward["a"]["career"] - forward["b"]["career"]


def test_a_qualifying_season_carries_its_baseline_and_composite(client: TestClient) -> None:
    score = _compare(client, a=KURT_WARNER, b=STEVE_MCNAIR)["qb_score"]

    (season,) = score["a"]["seasons"]
    assert season["season"] == 1999
    assert season["qualifies"] is True
    assert season["dropbacks"] >= QB_SCORE_MIN_DROPBACKS
    assert season["composite"] is not None
    for metric in ("epa_per_dropback", "rush_epa_per_play", "any_a"):
        value = season[metric]
        assert None not in (value["season_mean"], value["season_sd"], value["z"]), metric


# ---------------------------------------------------------------------------
# inconclusive
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "a,b,reason",
    [
        (KURT_WARNER, RANDALL_CUNNINGHAM, "b_no_qualifying_season"),
        (RANDALL_CUNNINGHAM, KURT_WARNER, "a_no_qualifying_season"),
        (RANDALL_CUNNINGHAM, TOMMY_DEVITO, "neither_has_qualifying_season"),
    ],
)
def test_a_qb_with_no_qualifying_season_is_inconclusive(
    client: TestClient, a: int, b: int, reason: str
) -> None:
    score = _compare(client, a=a, b=b)["qb_score"]

    assert reason in get_args(QbScoreInconclusiveReason)
    assert score["inconclusive"] == reason
    assert score["career_winner"] is None
    assert score["peak_winner"] is None
    assert score["career_margin"] is None
    assert score["peak_margin"] is None


def test_a_season_below_the_line_is_shown_but_not_scored(client: TestClient) -> None:
    score = _compare(client, a=KURT_WARNER, b=RANDALL_CUNNINGHAM)["qb_score"]
    cunningham = score["b"]

    assert cunningham["qualifying_seasons"] == 0
    assert cunningham["career"] is None
    assert cunningham["peak"] is None
    assert cunningham["first_scored_season"] is None
    (season,) = cunningham["seasons"]
    assert season["season"] == 1999
    assert 0 < season["dropbacks"] < QB_SCORE_MIN_DROPBACKS
    assert season["qualifies"] is False
    assert season["composite"] is None
    assert season["in_peak"] is False
    # The raw rate is shown; the baseline it would be judged against is not.
    assert season["epa_per_dropback"]["value"] is not None
    assert season["epa_per_dropback"]["z"] is None


# ---------------------------------------------------------------------------
# the scoring parameters
# ---------------------------------------------------------------------------


def test_the_scoring_parameters_are_the_contracts(client: TestClient) -> None:
    score = _compare(client, a=KURT_WARNER, b=STEVE_MCNAIR)["qb_score"]

    assert score["version"] == QB_SCORE_VERSION
    assert score["a"]["version"] == QB_SCORE_VERSION
    assert score["weights"] == dict(QB_SCORE_WEIGHTS)
    assert list(score["weights"]) == list(get_args(QbScoreMetric))
    assert score["min_dropbacks"] == QB_SCORE_MIN_DROPBACKS
    assert score["peak_seasons"] == QB_SCORE_PEAK_SEASONS
    assert score["sport"] == "nfl"


# ---------------------------------------------------------------------------
# not quarterbacks
# ---------------------------------------------------------------------------


def test_two_backs_have_a_null_qb_score(client: TestClient) -> None:
    body = _compare(client, a=MARSHALL_FAULK, b=EDGERRIN_JAMES)

    assert (body["a"]["group"], body["b"]["group"]) == ("RB", "RB")
    assert "qb_score" in body
    assert body["qb_score"] is None


def test_a_quarterback_against_a_back_is_still_not_comparable(client: TestClient) -> None:
    response = client.get(COMPARE, params={"a": KURT_WARNER, "b": MARSHALL_FAULK})

    assert response.status_code == 400, response.text
    assert response.json()["detail"]["error"] == "players_not_comparable"


# ---------------------------------------------------------------------------
# the published schema
# ---------------------------------------------------------------------------


def _schemas() -> dict[str, Any]:
    from api.main import app

    schemas: dict[str, Any] = app.openapi()["components"]["schemas"]
    return schemas


def _ref(name: str) -> dict[str, str]:
    return {"$ref": f"#/components/schemas/{name}"}


def _nullable_enum(prop: dict[str, Any]) -> list[str]:
    branches = [b for b in prop["anyOf"] if b != {"type": "null"}]
    assert len(branches) == 1, prop
    enum: list[str] = branches[0]["enum"]
    return enum


def test_the_comparison_schema_publishes_a_nullable_qb_score() -> None:
    prop = _schemas()["PlayerComparisonOut"]["properties"]["qb_score"]

    assert {"type": "null"} in prop["anyOf"]
    assert _ref("PlayerQbScoreComparisonOut") in prop["anyOf"]
    assert "qb_score" in _schemas()["PlayerComparisonOut"]["required"]
    assert prop.get("description"), prop


def test_the_new_models_describe_every_field() -> None:
    schemas = _schemas()
    undescribed = [
        f"{model}.{name}"
        for model in NEW_MODELS
        for name, prop in schemas[model]["properties"].items()
        if not prop.get("description")
    ]

    assert undescribed == []


def test_the_new_models_require_every_field() -> None:
    schemas = _schemas()
    for model in NEW_MODELS:
        assert set(schemas[model]["required"]) == set(schemas[model]["properties"]), model


def test_the_score_schema_publishes_the_contract_enums() -> None:
    props = _schemas()["PlayerQbScoreComparisonOut"]["properties"]

    assert _nullable_enum(props["career_winner"]) == list(get_args(QbScoreSide))
    assert _nullable_enum(props["peak_winner"]) == list(get_args(QbScoreSide))
    assert _nullable_enum(props["inconclusive"]) == list(get_args(QbScoreInconclusiveReason))
    assert props["weights"]["propertyNames"]["enum"] == list(get_args(QbScoreMetric))
    assert props["weights"]["additionalProperties"] == {"type": "number"}
