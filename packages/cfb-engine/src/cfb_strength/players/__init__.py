"""Player read layer (issue #296, epic #288): career leaders and a player's
career by season, read from the player tables with SQL.

Owned by players-agent. Implements `get_player_leaders` and
`get_player_career` against the dataclasses in `contracts.py`. Does not
import `ingest`, `ratings` or `evidence` (`.importlinter`).
"""

from cfb_strength.players.career import get_player_career
from cfb_strength.players.leaders import get_player_leaders

__all__ = ["get_player_career", "get_player_leaders"]
