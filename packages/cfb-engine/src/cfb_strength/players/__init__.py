"""Player read layer (issue #296, epic #288): career leaders, a player's
career by season, two players compared (#301), player search (#301) and the
era-adjusted QB score (#440), read from the player tables with SQL.

Owned by players-agent. Implements `get_player_leaders`, `get_player_career`,
`get_player_comparison`, `search_players`, `get_qb_score`,
`get_qb_score_comparison` and `fit_qb_score_weights` against the dataclasses in
`contracts.py`. Does not import `ingest`, `ratings` or `evidence`
(`.importlinter`).
"""

from cfb_strength.players.career import get_player_career
from cfb_strength.players.comparison import get_player_comparison
from cfb_strength.players.leaders import get_player_leaders
from cfb_strength.players.qb_score import (
    fit_qb_score_weights,
    get_qb_score,
    get_qb_score_comparison,
)
from cfb_strength.players.search import search_players

__all__ = [
    "fit_qb_score_weights",
    "get_player_career",
    "get_player_comparison",
    "get_player_leaders",
    "get_qb_score",
    "get_qb_score_comparison",
    "search_players",
]
