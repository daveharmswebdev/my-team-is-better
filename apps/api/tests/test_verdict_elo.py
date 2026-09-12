"""Real, end-to-end Elo responses through the HTTP layer.

`method` became a validated Literal that admits `elo`, but admitting a value
is not the same as serving it: until this file, every route test ran on the
default `keener`, and the committed fixture db held keener rows only. "Elo
works through the API" was therefore entirely untested, and would have
stayed untested while looking fine -- a request at `method="elo"` would have
404'd as an unknown year, which is indistinguishable from a season nobody
ingested.

`tests/fixtures/build_fixture.py` now bakes real `elo` ratings alongside
`keener` for the same three seasons (2001/2005/2013), computed by the real
engine, so the assertions below are against genuine Elo output rather than
handwritten rows. See that script for why `elo_career` is deliberately
absent (its offseason reversion counts elapsed years, and these seasons are
non-contiguous on purpose -- issue #98).

The scale assertion in `test_elo_champion_is_on_the_elo_scale_not_keeners`
is the load-bearing one: Keener ratings are eigenvector components in the
thousandths, Elo ratings are points around 1500. Asserting the magnitude
proves the `method` parameter actually selected Elo rows, which a check on
team name alone would not -- 2005 Texas ranks #1 under both methods, so
every other assertion here would pass just as happily against keener rows
leaking through a broken method filter.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_elo_champion_returns_a_real_case(client: TestClient) -> None:
    response = client.post("/api/verdict/champion", json={"year": 2005, "method": "elo"})

    assert response.status_code == 200, response.json()
    body = response.json()["evidence"]

    assert body["method"] == "elo"
    assert body["year"] == 2005
    assert body["team_name"] == "Texas"
    assert body["rank"] == 1
    assert body["wins"] == 13
    assert body["losses"] == 0

    # The evidence half is fully populated, not a shell: 13 games, and the
    # USC win (the golden-dataset case) is there with its real score.
    assert len(body["games"]) == 13
    usc_wins = [g for g in body["quality_wins"] if g["opponent_name"] == "USC"]
    assert len(usc_wins) == 1
    assert usc_wins[0]["team_score"] == 41
    assert usc_wins[0]["opponent_score"] == 38


def test_elo_champion_is_on_the_elo_scale_not_keeners(client: TestClient) -> None:
    """Proves `method=elo` selected Elo rows rather than falling through to
    the default. The two methods' ratings differ by five orders of
    magnitude, so this cannot pass by accident."""
    elo = client.post("/api/verdict/champion", json={"year": 2005, "method": "elo"}).json()
    keener = client.post("/api/verdict/champion", json={"year": 2005}).json()

    elo_rating = elo["evidence"]["rating"]
    keener_rating = keener["evidence"]["rating"]

    assert 1500 < elo_rating < 2500, elo_rating
    assert 0 < keener_rating < 1, keener_rating
    assert elo["evidence"]["team_name"] == keener["evidence"]["team_name"] == "Texas"


def test_elo_team_case_and_comparison_are_coherent(client: TestClient) -> None:
    """USC is the #2 Elo team of 2005 and its only loss is to #1 Texas, so
    the team-case and the head-to-head comparison have to agree with each
    other and with the season that actually happened."""
    usc = client.post("/api/verdict/team-case", json={"year": 2005, "team": "USC", "method": "elo"})
    assert usc.status_code == 200, usc.json()
    usc_body = usc.json()["evidence"]
    assert usc_body["method"] == "elo"
    assert usc_body["rank"] == 2
    assert (usc_body["wins"], usc_body["losses"]) == (12, 1)
    assert usc_body["worst_loss"] is not None
    assert usc_body["worst_loss"]["opponent_name"] == "Texas"

    compare = client.post(
        "/api/verdict/compare",
        json={"year": 2005, "team_a": "Texas", "team_b": "USC", "method": "elo"},
    )
    assert compare.status_code == 200, compare.json()
    comparison = compare.json()["evidence"]
    assert comparison["team_a"]["rank"] == 1
    assert comparison["team_b"]["rank"] == 2
    # rating_diff is team_a minus team_b, so the higher-rated team leads.
    assert comparison["rating_diff"] > 0
    assert comparison["rating_diff"] == (
        comparison["team_a"]["rating"] - comparison["team_b"]["rating"]
    )
    assert comparison["head_to_head"]["played"] is True
    assert "Texas" in comparison["verdict"]


def test_elo_case_has_no_per_opponent_breakdown(client: TestClient) -> None:
    """Pinned as a known, deliberate state rather than left to be
    rediscovered: the per-opponent decomposition (`rating_breakdown`) is a
    Keener construct -- it is that method's credit matrix, row by row --
    and the Elo engine writes no `rating_breakdowns` rows at all. So an Elo
    case carries an empty breakdown, and any consumer that renders the
    "receipts" panel must handle that rather than assume entries exist.

    This asserts the current truthful shape. It is not an endorsement of it;
    if Elo ever gains a per-game decomposition, this test should fail and be
    rewritten.
    """
    body = client.post("/api/verdict/champion", json={"year": 2005, "method": "elo"}).json()[
        "evidence"
    ]

    assert body["rating_breakdown"]["entries"] == []
    assert body["rating_breakdown"]["residual_contribution"] == 0.0

    keener = client.post("/api/verdict/champion", json={"year": 2005}).json()["evidence"]
    assert keener["rating_breakdown"]["entries"] != []


def test_elo_catalog_routes_serve_the_same_seasons_as_keener(client: TestClient) -> None:
    """`/api/years` and `/api/teams` are the picker's universe -- with Elo
    baked for the same three seasons, both must answer for it, not return
    the empty list that used to be indistinguishable from a typo."""
    years = client.get("/api/years", params={"method": "elo"})
    assert years.status_code == 200
    assert years.json() == {"years": [2001, 2005, 2013]}

    teams = client.get("/api/teams", params={"method": "elo", "year": 2005})
    assert teams.status_code == 200
    elo_teams = teams.json()["teams"]
    keener_teams = client.get("/api/teams", params={"method": "keener", "year": 2005}).json()[
        "teams"
    ]
    assert elo_teams == keener_teams
    assert "Texas" in elo_teams
