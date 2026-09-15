"""The app's own SQL against the engine's db (issue #209): the bottom layer
of `api`, below `api.persona`, `api.deps` and the routes.

Every query this app runs itself, rather than through
`cfb_strength.evidence`, lives here -- today that is `api.repositories.teams`
(the two team-name queries). A module here takes an open
`sqlite3.Connection` and returns plain values or frozen dataclasses; it
never opens a connection, never imports FastAPI, and never imports
`api.deps`, `api.persona`, `api.verdict`, `api.catalog` or `api.main`. The
`layers` contract in `apps/api/.importlinter` checks that order, so the
persona layer can call a query without depending on the dependency-injection
wiring that also imports the persona layer.
"""
