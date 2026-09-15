"""Static attribution data: methodology citation + data source credits.

This is the single source of truth for the project's attribution copy --
`mcp_server/server.py`'s `credits_resource()` and, via a direct Python
import, `apps/api`'s credits endpoint both build on `get_credits()` rather
than each keeping their own copy (ARCHITECTURE §4.5 / PRD §5.6). No db
access is required; the content is static.
"""

from __future__ import annotations

from cfb_strength.contracts import Credits, DataSourceCredit, MethodologyCredit


def get_credits() -> Credits:
    """Return the project's static attribution data.

    Covers every methodology this engine implements -- Keener's method and
    Elo -- and the three data sources, each with a stable `id` a page can
    select it by (issue #296): `cfbd` (CollegeFootballData.com, CFB game
    results), `nflverse_games` (nflverse, originally Lee Sharpe's schedule
    data, NFL game results) and `nflverse_player_stats` (nflverse's
    stats_player release, built with nflfastR, NFL player stats).
    tests/test_evidence_credits.py pins the ids, their order and their
    uniqueness.

    That coverage is checked, not hand-kept (issue #144): each
    `MethodologyCredit.methods` names the registered rating methods the
    citation covers, and tests/test_evidence_credits.py fails if the union
    across credits differs from `contracts.Method` or
    `ratings.compute_ratings.METHODS`, if a method is covered twice, or if a
    credit names a method that isn't registered. `methods[0]` is the credit's
    stable id downstream (`keener`, `elo`), so the Elo tuple lists `elo`
    before its career variant, which shares the citation.

    Takes no arguments and does not vary by the method that answered a given
    question: the About page credits the whole basis of the rankings, not
    whichever engine happened to run.
    """
    return Credits(
        methodologies=[
            MethodologyCredit(
                name="Keener's method",
                citation=(
                    'J. P. Keener, "The Perron-Frobenius Theorem and the Ranking '
                    'of Football Teams," SIAM Review, 35(1), 1993.'
                ),
                url="https://dl.acm.org/doi/10.1137/1035004",
                summary=(
                    "A team's rating depends recursively on the strength of the "
                    "teams it beat, whose strength depends on the strength of "
                    "their opponents -- the same Perron-Frobenius eigenvector "
                    "idea behind PageRank, applied to a win graph. This is stock "
                    "Keener, with win/loss as the dominant signal: this method "
                    "does not weight margin of victory, so running up the score "
                    "doesn't move the needle. It is the default, and the only "
                    "method checked against the golden dataset of undisputed "
                    "champions."
                ),
                methods=("keener",),
            ),
            MethodologyCredit(
                name="Elo",
                citation=(
                    "Arpad E. Elo, The Rating of Chessplayers, Past and Present, "
                    "Arco, 1978 -- as adapted for professional football by "
                    "FiveThirtyEight (fivethirtyeight/nfl-elo-game)."
                ),
                url="https://github.com/fivethirtyeight/nfl-elo-game",
                summary=(
                    "Every team starts even and they trade points after each "
                    "game: beat someone better than you and you take more from "
                    "them than you would from a team you were supposed to beat. "
                    "Arpad Elo built it for chess; FiveThirtyEight published the "
                    "football adaptation implemented here -- including the "
                    "margin-of-victory multiplier, so unlike Keener above, "
                    "blowouts do count, with diminishing returns and a damping "
                    "term that stops a heavy favorite from farming easy wins. "
                    "This is a clean-room implementation written from the "
                    "published formula: no code and no data were taken from "
                    "FiveThirtyEight, and they are credited here because they "
                    "earned it, not because a license required it. The pro "
                    "football constants are theirs; the college ones are our own "
                    "first pass and are not yet calibrated against anything. "
                    "Offered as a second opinion, not a replacement -- two "
                    "different methods will naturally rank teams differently "
                    "from time to time."
                ),
                methods=("elo", "elo_career"),
            ),
        ],
        data_sources=[
            DataSourceCredit(
                id="cfbd",
                name="CollegeFootballData.com (CFBD)",
                url="https://collegefootballdata.com",
                note=(
                    "All game results are ingested from the CFBD API. This project "
                    "performs no independent data collection and claims no "
                    "ownership of the underlying game data."
                ),
            ),
            DataSourceCredit(
                id="nflverse_games",
                name="nflverse (Lee Sharpe's NFL schedule/game data)",
                url="https://github.com/nflverse/nflverse-data",
                note=(
                    "NFL game results are ingested from nflverse's static CSV "
                    "release assets (the schedule data was originally compiled "
                    "and maintained by Lee Sharpe before nflverse took over "
                    "publishing it). This project performs no independent data "
                    "collection and claims no ownership of the underlying game "
                    "data."
                ),
            ),
            DataSourceCredit(
                id="nflverse_player_stats",
                name="nflverse player stats (nflfastR, by Sebastian Carl and Ben Baldwin)",
                url="https://github.com/nflverse/nflfastR",
                note=(
                    "NFL player stats are ingested from nflverse's stats_player "
                    "release (the weekly stats_player_week CSV files, 1999-2025), "
                    "which nflverse creates with nflfastR's calculate_stats(). "
                    "nflfastR is written by Sebastian Carl and Ben Baldwin, with "
                    "contributions from Lee Sharpe, Maksim Horowitz, Ron Yurko, "
                    "Samuel Ventura, Tan Ho and John Edwards, and is MIT licensed. "
                    "Player identities come from nflverse's players release "
                    "(players.csv). This project performs no independent data "
                    "collection and claims no ownership of the underlying player "
                    "data."
                ),
            ),
        ],
    )
