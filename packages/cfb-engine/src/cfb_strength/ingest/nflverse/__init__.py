"""NFL ingest path (nflverse), added for issue #51 (sprint 2: NFL support).

Writes into the same sqlite db the CFBD path already uses (`sport='nfl'`
rows alongside `sport='cfb'` rows) -- see `db/schema.sql`'s comment on the
`teams` table and this package's `ingest_season.py` module docstring for the
surrogate-id scheme that keeps the two sources from colliding on `teams.id`
/ `games.id`.

This package and `cfb_strength.ingest.client` / `.normalize` / `.ingest_season`
(the CFBD path) must never import each other -- enforced by the
`no-nflverse-import-of-cfbd / no-cfbd-import-of-nflverse` contract in `.importlinter`.
"""

from __future__ import annotations
