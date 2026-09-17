"""The widened player stat contract as apps/api sees it (issue #313, epic #311).

`contracts.PlayerStats` went from 10 stat columns to 34, and the committed
fixture was rebuilt through the widened nflverse ingest. This module pins the
two behavioural changes that came with the widening, so that neither can
regress silently while the API still publishes only the original ten fields
(`PlayerStatsOut`; receiving/kicking/punting are #314 and #315).

1. Sign convention (#298). `sack_yards_lost` is stored and published
   POSITIVE. It used to be negative, and every consumer -- the career page,
   the compare page, #315's boards -- reads it straight through, so the sign
   is asserted here through the HTTP layer on measured anchors, not just at
   the db.

2. Maxima, not totals. `fg_long` and `pt_long` are season maxima
   (`contracts.PLAYER_STAT_MAX_FIELDS`) and are NULL for anyone who never
   kicked or punted -- never 0. A quarterback's row is the check: 0 would
   read as "his longest field goal was zero yards", and any renderer that
   coerces NULL to 0 would publish that. The API does not expose these yet,
   so they are asserted against the fixture db directly; #315 inherits a
   checked expectation rather than discovering it.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from fixtures.player_api_fixture import (
    PUBLISHED_STAT_NAMES,
    STAT_NAMES,
    fixture_conn,
    stats_body,
)

KURT_WARNER = 2044124519
PATRICK_MAHOMES = 2319407936

# (player, season, season_type, sacks_suffered, sack_yards_lost), measured on
# the rebuilt fixture. The yards were negative before #298.
SACK_ANCHORS = [
    (KURT_WARNER, 1999, "regular", 26, 176),
    (KURT_WARNER, 1999, "postseason", 4, 24),
    (PATRICK_MAHOMES, 2023, "regular", 27, 186),
]

MAX_FIELDS = ("fg_long", "pt_long")


def _season_stats(client: TestClient, player_id: int, season: int, season_type: str) -> Any:
    response = client.get(f"/api/players/{player_id}")
    assert response.status_code == 200, response.text
    lines = [
        line
        for line in response.json()["seasons"]
        if line["season"] == season and line["season_type"] == season_type
    ]
    assert len(lines) == 1, lines
    return lines[0]["stats"]


@pytest.mark.parametrize("player_id,season,season_type,sacks,yards", SACK_ANCHORS)
def test_sack_yards_lost_is_published_positive(
    client: TestClient,
    player_id: int,
    season: int,
    season_type: str,
    sacks: int,
    yards: int,
) -> None:
    stats = _season_stats(client, player_id, season, season_type)

    assert (stats["sacks_suffered"], stats["sack_yards_lost"]) == (sacks, yards)


def test_career_totals_carry_the_positive_sack_yards(client: TestClient) -> None:
    response = client.get(f"/api/players/{KURT_WARNER}")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["regular_season"]["stats"]["sack_yards_lost"] == 176
    assert body["postseason"]["stats"]["sack_yards_lost"] == 24


def test_no_fixture_row_stores_a_negative_sack_yards_lost() -> None:
    with fixture_conn() as conn:
        negative = conn.execute(
            "SELECT COUNT(*) FROM player_season_stats WHERE sack_yards_lost < 0"
        ).fetchone()[0]
        populated = conn.execute(
            "SELECT COUNT(*) FROM player_season_stats WHERE sack_yards_lost > 0"
        ).fetchone()[0]

    assert negative == 0
    assert populated > 0, "no populated sack yards at all would make the sign check vacuous"


def test_the_fixture_carries_every_contract_stat_column() -> None:
    with fixture_conn() as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(player_season_stats)")}

    assert len(STAT_NAMES) == 34
    assert set(STAT_NAMES) <= columns


@pytest.mark.parametrize("field", MAX_FIELDS)
def test_a_quarterbacks_season_maximum_is_null_never_zero(field: str) -> None:
    """`fg_long`/`pt_long` are maxima: not applicable reads as NULL."""
    with fixture_conn() as conn:
        position, value = conn.execute(
            f"SELECT p.position, s.{field} FROM player_season_stats s "
            "JOIN players p ON p.id = s.player_id "
            "WHERE s.player_id = ? AND s.season = 1999 AND s.season_type = 'regular'",
            (KURT_WARNER,),
        ).fetchone()

    assert position == "QB"
    assert value is None


@pytest.mark.parametrize("field", MAX_FIELDS)
def test_no_season_maximum_is_stored_as_zero(field: str) -> None:
    with fixture_conn() as conn:
        zeros, nulls, populated = conn.execute(
            f"SELECT SUM({field} = 0), SUM({field} IS NULL), SUM({field} > 0) "
            "FROM player_season_stats"
        ).fetchone()

    assert zeros == 0, f"{field} is a maximum; 'not applicable' must be NULL, not 0"
    assert nulls > 0
    assert populated > 0, f"no populated {field} would make this check vacuous"


# ---------------------------------------------------------------------------
# `stats_body`, the expected-body helper the compare test builds its four
# measured games with. It replaced a positional `_stats(*values)` that
# asserted its arity against the live contract and so broke the moment
# `PlayerStats` widened. Naming is only safe if a wrong name is loud.
# ---------------------------------------------------------------------------


def test_stats_body_fills_unnamed_published_stats_with_none() -> None:
    named = {"completions": 29, "attempts": 46}
    body = stats_body(**named)

    assert set(body) == set(PUBLISHED_STAT_NAMES)
    assert {name: body[name] for name in named} == named
    assert body["rushing_tds"] is None, "a stat with no value is not applicable, never 0"
    assert [name for name, value in body.items() if value is None] == [
        name for name in PUBLISHED_STAT_NAMES if name not in named
    ]


def test_stats_body_rejects_a_name_that_is_not_a_stat() -> None:
    with pytest.raises(ValueError, match="'passing_yardz' is not a PlayerStats field"):
        stats_body(passing_yardz=328)


def test_stats_body_rejects_a_stat_the_api_does_not_publish_yet() -> None:
    assert "receptions" in STAT_NAMES and "receptions" not in PUBLISHED_STAT_NAMES
    with pytest.raises(ValueError, match="does not publish yet"):
        stats_body(receptions=4)
