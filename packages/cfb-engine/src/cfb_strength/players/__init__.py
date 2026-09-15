"""Player read layer (issue #296, epic #288): career leaders and a player's
career by season, read from the player tables with SQL.

Owned by players-agent. Implements `get_player_leaders` and
`get_player_career` against the dataclasses in `contracts.py`. Does not
import `ingest`, `ratings` or `evidence` (`.importlinter`).
"""
