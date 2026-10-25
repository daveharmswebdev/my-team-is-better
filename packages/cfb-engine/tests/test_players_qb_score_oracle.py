"""The QB score (#440) against a full 1999-2025 NFL build: the numbers the
coordinator measured with the epic #439 spike over our own
`player_season_stats`. Skips unless `QB_SCORE_ORACLE_DB` names such a db
(`cfb ingest --sport nfl` then `cfb ingest-players --sport nfl`); opened
read-only, never written."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from cfb_strength.contracts import POSITION_GROUP_BY_LABEL, QB_SCORE_WEIGHTS
from cfb_strength.db.connection import get_conn
from cfb_strength.players import fit_qb_score_weights, get_qb_score

ORACLE_DB = os.environ.get("QB_SCORE_ORACLE_DB")

pytestmark = pytest.mark.skipif(
    not ORACLE_DB, reason="QB_SCORE_ORACLE_DB does not name a full NFL build"
)

# name: (qualifying seasons, career, peak), measured.
MEASURED = {
    "Tom Brady": (21, 18.19, 1.73),
    "Peyton Manning": (16, 18.09, 1.77),
    "Drew Brees": (19, 14.61, 1.36),
    "Aaron Rodgers": (17, 13.71, 1.70),
    "Patrick Mahomes": (8, 9.91, 1.61),
    "Joe Flacco": (14, -4.42, 0.13),
    "Lamar Jackson": (7, 6.73, 1.25),
}


@pytest.fixture(scope="module")
def conn() -> Iterator[sqlite3.Connection]:
    assert ORACLE_DB is not None
    c = get_conn(Path(ORACLE_DB), read_only=True)
    try:
        yield c
    finally:
        c.close()


def _qb_id(conn: sqlite3.Connection, name: str) -> int:
    rows = conn.execute(
        "SELECT id FROM players WHERE sport = 'nfl' AND display_name = ? AND position = 'QB'",
        (name,),
    ).fetchall()
    assert len(rows) == 1, name
    return int(rows[0][0])


@pytest.mark.parametrize("name", sorted(MEASURED))
def test_qb_score_oracle_career_and_peak(conn: sqlite3.Connection, name: str) -> None:
    n, career, peak = MEASURED[name]
    score = get_qb_score(conn, sport="nfl", player_id=_qb_id(conn, name))
    assert score.qualifying_seasons == n
    assert score.career == pytest.approx(career, abs=0.01)
    assert score.peak == pytest.approx(peak, abs=0.01)
    assert score.first_scored_season is not None and score.first_scored_season >= 1999


def test_qb_score_oracle_counts_924_qualifying_seasons(conn: sqlite3.Connection) -> None:
    labels = [label for label, group in POSITION_GROUP_BY_LABEL.items() if group == "QB"]
    ids = [
        int(r[0])
        for r in conn.execute(
            f"SELECT id FROM players WHERE sport = 'nfl' AND position IN "
            f"({', '.join('?' * len(labels))})",
            labels,
        )
    ]
    total = sum(get_qb_score(conn, sport="nfl", player_id=i).qualifying_seasons for i in ids)
    assert total == 924


def test_qb_score_oracle_fit_reproduces_the_frozen_weights(conn: sqlite3.Connection) -> None:
    fit = fit_qb_score_weights(conn, sport="nfl")
    assert fit.n_pairs == 629
    assert (fit.first_season, fit.last_season) == (1999, 2025)
    for metric, weight in QB_SCORE_WEIGHTS.items():
        assert fit.weights[metric] == pytest.approx(weight, abs=0.001)
    assert fit.coefficients["epa_per_dropback"] == pytest.approx(0.4318, abs=0.0001)
    assert fit.coefficients["rush_epa_per_play"] == pytest.approx(0.0913, abs=0.0001)
