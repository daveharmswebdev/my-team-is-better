"""Franchise relocations: which historical team identity continues as which.

Why this exists
---------------
`EloCareerRating` carries a rating across seasons, so it needs to know that
the 2015 St. Louis Rams and the 2016 Los Angeles Rams are one continuous
franchise rather than two teams, one of which vanished and one of which
appeared from nowhere at the initial rating. Without this table a relocation
silently resets 17 seasons of accumulated rating.

Keyed on `teams.source_id`, NOT on `teams.id`
---------------------------------------------
`source_id` is nflverse's own team abbreviation ("STL", "LA"). Our ingest
mints a *different* surrogate integer `teams.id` for "STL" and for "LA"
(see `ingest/nflverse/`), precisely because they are distinct rows in the
source data -- so `teams.id` cannot express the relationship and hardcoding
ids here would bind this table to one particular database's id minting.
`compute_ratings._franchise_successors` resolves these abbreviations to the
local ids at call time and passes the resolved map into the rating method,
which keeps `elo.py` a pure function of its inputs with no db dependency.

The non-overlap premise
-----------------------
Every pair below is strictly non-overlapping in the committed nflverse
cache (`data/raw/nfl/games.csv`, 35 distinct abbreviations): STL 1999-2015 /
LA 2016-, SD 1999-2016 / LAC 2017-, OAK 1999-2019 / LV 2020-. That is the
property that makes the Elo walk's "fold every season into root space, but
emit the id that actually played the target season" unambiguous -- at most
one member of a lineage can appear in any single season.
`test_franchise_lineage.py` re-derives those spans from the cache on every
run so a future edit cannot introduce an overlapping pair silently.

nflverse's own numeric franchise ids corroborate each pairing: Rams 2510,
Chargers 4400, Raiders 2520.

This is a rename/relocation table, not an expansion or merger table. A
genuinely new franchise (e.g. HOU in 2002) correctly starts at
`EloConfig.initial` and must not appear here.
"""

from __future__ import annotations

FRANCHISE_LINEAGE: dict[str, dict[str, str]] = {
    "nfl": {
        "STL": "LA",  # Rams:     St. Louis 1999-2015 -> Los Angeles 2016-
        "SD": "LAC",  # Chargers: San Diego 1999-2016 -> Los Angeles 2017-
        "OAK": "LV",  # Raiders:  Oakland   1999-2019 -> Las Vegas   2020-
    },
    # College programs do not relocate the way pro franchises do, and CFB
    # `teams` rows carry `source_id IS NULL` anyway (CFBD's integer id is
    # already the row's real primary key) -- there is nothing to key on.
    "cfb": {},
}
