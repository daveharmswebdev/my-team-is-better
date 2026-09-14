"""All seven PRD golden years served through the real HTTP layer (issue #110,
epic #113).

`POST /api/verdict/champion` must return the Keener #1, with its record, for
every golden season: 2001, 2003, 2004, 2005, 2013, 2017 and 2019. These run
against the committed, real-engine-computed `cfb_verdict_fixture.sqlite3`
(see `tests/fixtures/build_fixture.py`), not handwritten rows. This is the
ground issue #109's persona smoke eval stands on: an eval of what the persona
says about a season is meaningless if the route can't serve that season.

The expected answers are written out here by hand and deliberately not read
from the fixture, the generator, or `api.config`, because this file is the
oracle those are checked against. They match the engine's own golden test
(`packages/cfb-engine/tests/test_golden_dataset_regressions.py`):

- must-match years: 2001 Miami 12-0, 2004 USC 13-0, 2005 Texas 13-0,
  2013 Florida State 14-0, 2019 LSU 15-0;
- contested years: 2003 LSU 13-1 and 2017 Alabama 13-1. For these the pinned
  team is the answer the engine computes, not a claim that it is the "right"
  champion. That's why `narration.contested` must be true for exactly these
  two years, so the persona discloses the dispute.

Keener only. Nothing here asserts Elo's #1, or that Elo agrees or disagrees
with Keener: the founder's neutrality rule. `build_fixture.py` reports the Elo
#1 for each year and never asserts it.

`contested` is asserted for CFB only. `api.persona.service.is_contested`
currently ignores `sport` (issue #151), and changing that is out of scope
here, so this file makes no claim about any other league.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

# year -> (Keener #1 team_name, wins, losses). No golden champion has a tie.
KEENER_CHAMPIONS: dict[int, tuple[str, int, int]] = {
    2001: ("Miami", 12, 0),
    2003: ("LSU", 13, 1),
    2004: ("USC", 13, 0),
    2005: ("Texas", 13, 0),
    2013: ("Florida State", 14, 0),
    2017: ("Alabama", 13, 1),
    2019: ("LSU", 15, 0),
}

CONTESTED_GOLDEN_YEARS: frozenset[int] = frozenset({2003, 2017})


def test_golden_years_are_the_seven_prd_seasons() -> None:
    assert tuple(KEENER_CHAMPIONS) == (2001, 2003, 2004, 2005, 2013, 2017, 2019)
    assert CONTESTED_GOLDEN_YEARS <= set(KEENER_CHAMPIONS)


def test_years_catalog_serves_every_golden_year(client: TestClient) -> None:
    response = client.get("/api/years", params={"sport": "cfb", "method": "keener"})

    assert response.status_code == 200
    assert response.json() == {"years": sorted(KEENER_CHAMPIONS)}


@pytest.mark.parametrize("year", sorted(KEENER_CHAMPIONS))
def test_champion_is_the_keener_number_one_with_its_record(client: TestClient, year: int) -> None:
    team_name, wins, losses = KEENER_CHAMPIONS[year]

    response = client.post(
        "/api/verdict/champion", json={"year": year, "sport": "cfb", "method": "keener"}
    )

    assert response.status_code == 200, response.json()
    evidence = response.json()["evidence"]
    assert evidence["year"] == year
    assert evidence["method"] == "keener"
    assert evidence["rank"] == 1
    assert evidence["team_name"] == team_name
    assert (evidence["wins"], evidence["losses"], evidence["ties"]) == (wins, losses, 0)
    assert isinstance(evidence["games"], list) and len(evidence["games"]) == wins + losses


@pytest.mark.parametrize("year", sorted(KEENER_CHAMPIONS))
def test_champion_contested_flag_is_true_for_exactly_2003_and_2017(
    client: TestClient, year: int
) -> None:
    response = client.post(
        "/api/verdict/champion", json={"year": year, "sport": "cfb", "method": "keener"}
    )

    assert response.status_code == 200, response.json()
    assert response.json()["narration"]["contested"] is (year in CONTESTED_GOLDEN_YEARS)
