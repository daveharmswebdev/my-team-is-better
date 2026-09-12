"""Failing-first tests for the /api/verdict endpoints (GitHub issue #3).

Written before api/verdict.py existed, per CLAUDE.md's TDD rule. Covers the
three PRD §5.1 structured question types plus the three typed-exception ->
HTTP mappings from Architecture Brief §4.4. The 2005-champion-is-Texas test
is also this issue's required real-engine integration test: it goes through
the actual HTTP endpoint (TestClient), against the committed, real-engine
-computed fixture db (tests/fixtures/cfb_verdict_fixture.sqlite3) -- not a
mocked/handwritten evidence dataclass.

Issue #4 wrapped these routes' response in a `{"evidence": ..., "narration":
...}` envelope -- the assertions below read `body["evidence"][...]` rather
than `body[...]` to match (an expected, in-scope update to this file, since
issue #4's brief is the one that changed the response shape; error-path
tests are untouched, since typed-exception responses were never wrapped).
The `client` fixture (see conftest.py) wires a stub persona narrator + an
in-memory cache by default, so these tests never call the real Claude API.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def test_champion_endpoint_returns_2005_texas_full_case(client: TestClient) -> None:
    response = client.post("/api/verdict/champion", json={"year": 2005})

    assert response.status_code == 200
    body = response.json()["evidence"]
    assert body["year"] == 2005
    assert body["method"] == "keener"
    assert body["team_name"] == "Texas"
    assert body["rank"] == 1
    assert body["wins"] == 13
    assert body["losses"] == 0
    assert isinstance(body["games"], list) and len(body["games"]) > 0
    usc_wins = [g for g in body["quality_wins"] if g["opponent_name"] == "USC"]
    assert len(usc_wins) == 1
    assert usc_wins[0]["team_score"] == 41
    assert usc_wins[0]["opponent_score"] == 38


def test_team_case_endpoint_returns_named_team_case(client: TestClient) -> None:
    response = client.post("/api/verdict/team-case", json={"year": 2005, "team": "USC"})

    assert response.status_code == 200
    body = response.json()["evidence"]
    assert body["team_name"] == "USC"
    assert body["year"] == 2005
    assert body["wins"] == 12
    assert body["losses"] == 1
    assert body["worst_loss"] is not None


def test_team_case_endpoint_includes_rating_breakdown(client: TestClient) -> None:
    """Issue #31: the per-opponent rating decomposition rides along on
    /api/verdict/team-case, reconstructing to the team's `rating` field."""
    known_teams = set(client.get("/api/teams").json()["teams"])

    response = client.post("/api/verdict/team-case", json={"year": 2005, "team": "USC"})

    assert response.status_code == 200
    body = response.json()["evidence"]
    breakdown = body["rating_breakdown"]
    entries = breakdown["entries"]
    assert isinstance(entries, list) and len(entries) > 0
    assert isinstance(breakdown["residual_contribution"], float)

    for entry in entries:
        assert set(entry.keys()) == {
            "opponent_team_id",
            "opponent_name",
            "games_played",
            "wins",
            "losses",
            "credit",
            "contribution",
            "explanation",
        }
        assert isinstance(entry["opponent_name"], str) and entry["opponent_name"]
        assert entry["opponent_name"] in known_teams
        assert isinstance(entry["explanation"], str) and entry["explanation"]

    total = sum(e["contribution"] for e in entries) + breakdown["residual_contribution"]
    assert total == pytest.approx(body["rating"], abs=1e-6)


def test_compare_endpoint_returns_comparison_of_two_named_teams(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/verdict/compare",
        json={"year": 2005, "team_a": "Texas", "team_b": "USC"},
    )

    assert response.status_code == 200
    body = response.json()["evidence"]
    assert body["year"] == 2005
    assert body["team_a"]["team_name"] == "Texas"
    assert body["team_b"]["team_name"] == "USC"
    assert body["head_to_head"]["played"] is True
    assert isinstance(body["common_opponents"], list)
    assert isinstance(body["verdict"], str) and body["verdict"]


def test_compare_endpoint_includes_rating_breakdown_for_both_teams(
    client: TestClient,
) -> None:
    """Issue #31: both sides of a comparison carry their own rating breakdown,
    each reconstructing to that team's own `rating` field."""
    known_teams = set(client.get("/api/teams").json()["teams"])

    response = client.post(
        "/api/verdict/compare",
        json={"year": 2005, "team_a": "Texas", "team_b": "USC"},
    )

    assert response.status_code == 200
    body = response.json()["evidence"]

    for team_key in ("team_a", "team_b"):
        team = body[team_key]
        breakdown = team["rating_breakdown"]
        entries = breakdown["entries"]
        assert isinstance(entries, list) and len(entries) > 0
        assert isinstance(breakdown["residual_contribution"], float)

        for entry in entries:
            assert set(entry.keys()) == {
                "opponent_team_id",
                "opponent_name",
                "games_played",
                "wins",
                "losses",
                "credit",
                "contribution",
                "explanation",
            }
            assert isinstance(entry["opponent_name"], str) and entry["opponent_name"]
            assert entry["opponent_name"] in known_teams
            assert isinstance(entry["explanation"], str) and entry["explanation"]

        total = sum(e["contribution"] for e in entries) + breakdown["residual_contribution"]
        assert total == pytest.approx(team["rating"], abs=1e-6)


def test_unknown_year_returns_404_with_available_years(client: TestClient) -> None:
    response = client.post("/api/verdict/champion", json={"year": 1999})

    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["error"] == "unknown_year"
    assert detail["year"] == 1999
    assert 2005 in detail["available_years"]


def test_ambiguous_team_returns_422_with_candidates(client: TestClient) -> None:
    response = client.post("/api/verdict/team-case", json={"year": 2005, "team": "State"})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["error"] == "ambiguous_team"
    assert detail["query"] == "State"
    assert len(detail["candidates"]) > 1


def test_same_team_comparison_returns_400(client: TestClient) -> None:
    response = client.post(
        "/api/verdict/compare",
        json={"year": 2005, "team_a": "Texas", "team_b": "Texas"},
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["error"] == "same_team_comparison"
    assert detail["team_name"] == "Texas"


# ---------------------------------------------------------------------------
# unknown team -> 404 (issue #100)
#
# `resolve_team` used to raise `AmbiguousTeamError` with an *empty* candidate
# list for a zero-match query, so a genuine not-found reached the client as
# 422 `ambiguous_team` -- a "did you mean:" prompt with nothing under it.
# `UnknownTeamError` splits that case out and this app maps it to 404, the
# same "we have no data for what you asked about" status `unknown_year`
# already uses; 422 stays reserved for real ambiguity.
#
# These go through the real engine against the committed fixture db rather
# than mocking the evidence call, so they pin the whole path, not just the
# handler. `"Gonzaga"` and `"Zzyzx Polytechnic"` are both zero-match against
# the 2005 fixture: no D-I basketball-only school, and no such school at all.
#
# The body deliberately carries **no suggestion list**. The first cut of
# #100 added one, and these tests asserted it was non-empty -- which passed
# only because `"Gonzaga"` fuzzy-matched `"Georgia"` at 0.5714, i.e. the
# tests were pinned to the exact noise the field was removed for. See
# `models.UnknownTeamErrorBody` for the measurement. What is asserted now is
# the contract that survives: 404, and a body that names what was asked for
# (`query`/`year`/`sport`) so the client can say so instead of dead-ending.
# ---------------------------------------------------------------------------


def test_unknown_team_returns_404_naming_what_was_asked_for(client: TestClient) -> None:
    """A zero-match query is 404 `unknown_team`, and the body echoes the
    exact `query`/`year`/`sport` back. Those three fields are the whole
    payload now, so the client can render "no rating for Gonzaga in 2005
    college football" rather than a bare failure."""
    response = client.post(
        "/api/verdict/team-case",
        json={"year": 2005, "team": "Gonzaga", "sport": "cfb"},
    )

    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["error"] == "unknown_team"
    assert detail["query"] == "Gonzaga"
    assert detail["year"] == 2005
    assert detail["sport"] == "cfb"


def test_unknown_team_body_carries_no_suggestion_list(client: TestClient) -> None:
    """The field is gone and must stay gone. It could not be made to work:
    `resolve_team` already resolves anything scoring >= 0.6, so this branch
    is reached only when nothing does, and the leftovers are noise --
    `"Gonzaga"`/`"Georgia"` (0.5714) outranks `"Texas"`/`"Houston Texans"`
    (0.5263), and `"Abilene Christian"` shipped Michigan, Minnesota, Ole
    Miss and Virginia to real users. A reintroduced key would turn this red.
    """
    response = client.post(
        "/api/verdict/team-case",
        json={"year": 2005, "team": "Gonzaga"},
    )

    assert response.status_code == 404
    assert "suggestions" not in response.json()["detail"]
    # ...as literal JSON too, not just as decoded Python -- a `null`-valued
    # key would still be a key on the wire.
    assert "suggestions" not in response.text


def test_unknown_team_omits_the_year_defaults_to_cfb_and_still_404s(
    client: TestClient,
) -> None:
    """`"Zzyzx Polytechnic"` matches nothing at any similarity, unlike
    `"Gonzaga"` -- it reaches the same zero-match branch by a different
    route, with `sport` left off the request entirely so the default is
    exercised end-to-end and echoed back."""
    response = client.post(
        "/api/verdict/team-case",
        json={"year": 2005, "team": "Zzyzx Polytechnic"},
    )

    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["error"] == "unknown_team"
    assert detail["query"] == "Zzyzx Polytechnic"
    assert detail["year"] == 2005
    assert detail["sport"] == "cfb"


def test_unknown_team_on_compare_route_returns_404(client: TestClient) -> None:
    """The mapping is registered app-wide (`api.errors`), not per-route --
    the comparison route surfaces the same 404 for its own team arguments."""
    response = client.post(
        "/api/verdict/compare",
        json={"year": 2005, "team_a": "Zzyzx Polytechnic", "team_b": "Texas"},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "unknown_team"


def test_ambiguous_compare_query_still_returns_422_with_candidates(
    client: TestClient,
) -> None:
    """The #100 split must not swallow the real >1-match case: a query that
    matches several rated teams is still 422 `ambiguous_team` with a
    non-empty `candidates`, not the new 404."""
    response = client.post(
        "/api/verdict/compare",
        json={"year": 2005, "team_a": "State", "team_b": "Texas"},
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["error"] == "ambiguous_team"
    assert detail["query"] == "State"
    assert len(detail["candidates"]) > 1
