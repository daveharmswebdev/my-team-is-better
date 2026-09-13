# cfb-strength-orchestrated

Recursive strength-of-schedule college football rankings, computed deterministically
and exposed to an LLM via an MCP server. This is a rebuild of
[`cfb-strength`](../cfb-strength) under a hub-and-spoke coordinator/subagent
architecture — see `CLAUDE.md` for the process this codebase was built under, and
`docs/comparison.md` for how that process compared to the original solo build.

The idea: a team's rating should depend on the strength of the teams it beat, whose
strength depends on the strength of *their* opponents, recursively. This is
[Keener's eigenvector method](https://dl.acm.org/doi/10.1137/1035004) (Perron-Frobenius
theorem applied to a win-graph) — the same mathematical idea behind PageRank.

## Setup

```bash
uv sync
```

Sign up for a free API key at [collegefootballdata.com](https://collegefootballdata.com)
(1,000 calls/month free tier), then:

```bash
cp .env.example .env
# edit .env, set CFBD_API_KEY=...
```

## Usage

```bash
uv run cfb ingest --years 2005              # ingest CFB game data (cached raw JSON in data/raw/)
uv run cfb ingest --sport nfl --years 2023-2025   # ingest NFL game data (cached raw CSV in data/raw/nfl/)
uv run cfb rate --years 2005                # compute ratings from ingested games
uv run cfb serve                            # run the MCP server (stdio)
uv run cfb doctor                           # is the local db's *data* current? (read-only)
```

### Is my local db stale? `cfb doctor`

A stale `data/cfb.sqlite3` looks exactly like a fresh one, and `ensure_schema`
migrating its missing columns in doesn't make its *data* any newer (a pre-#51
build has no NFL rows and no mascots). `cfb doctor [--db-path PATH] [--raw-dir PATH]`
opens the db read-only and exits 0 only when:
- its schema matches what `ensure_schema` would produce
- every league has games
- no (season, season type) batch in the committed raw cache is missing from
  `games`, counting only seasons inside each league's ingest window. A
  regular season ingested without its postseason counts as behind.
- every season with games is rated by every method
- at least one CFB team has a mascot, if the db has CFB teams at all. This is
  a zero rule, not a coverage target, because CFBD has no mascot for some
  real teams.
- `--raw-dir` looks like the committed cache. An empty or wrong directory
  fails rather than skipping the cache checks. A partial but recognizable
  directory still passes when the db matches it.
- the cache holds no *finished* season past a league's ingest `MAX_YEAR`.
  For NFL that means a Super Bowl with both scores recorded. For CFB it means
  a postseason file whose latest-dated games are all completed, so an earlier
  bowl that was cancelled doesn't matter. `cfb ingest` skips such a season,
  so no db can be current until `MAX_YEAR` is bumped.

Otherwise it exits 1 and names each problem. An unfinished season past
`MAX_YEAR`, like the season in progress, gets a note that doesn't change the
exit code. The doctor never migrates or writes the file. It reads a WAL-mode
db that has no `-wal` file without creating `-wal`/`-shm` next to it.

Check a WAL-mode db together with its `-wal` file, never a copy of the main
file alone: commits still in the `-wal` aren't in the main file yet. Don't
run the doctor while `cfb ingest` or `cfb rate` is writing to the db either.
Without a `-wal` it reads the main file with `immutable`, which takes no
locks.

When `ensure_schema` does add a column, table or index to a db that already
holds games, it emits a `StaleDatabaseWarning` pointing here. The usual fix is
to rebuild from the committed cache with render.yaml's ingest/rate commands.
`rate` has no `--db-path` flag, so pin every step with `CFB_DB_PATH=...`.

## Data sources

- College football: [collegefootballdata.com](https://collegefootballdata.com) (CFBD).
- NFL (added for issue #51): [nflverse](https://github.com/nflverse/nflverse-data)'s
  `games.csv` (schedules release) and `teams_colors_logos.csv` (teams release). The
  NFL schedule data in `games.csv` was originally compiled and maintained by
  **Lee Sharpe**, whose work nflverse now publishes and maintains — see
  [nflverse-data](https://github.com/nflverse/nflverse-data) and
  [nflreadr's data dictionary](https://nflreadr.nflverse.com/articles/dictionary_schedules.html)
  for the full history and citation.

## Tools exposed

The database holds both leagues. Every tool below takes `sport="cfb"` (college
football, the default) or `sport="nfl"`, and scopes everything it reads to that league.

- `list_seasons()` — one entry per `(sport, year)` with computed ratings, listing its methods
- `get_rankings(year, top_n=25, method="keener", sport="cfb")` — ranked list for a season
- `get_team_season(year, team, method="keener", sport="cfb")` — a team's rank, rating,
  full schedule with opponent context, quality wins, worst loss
- `compare_teams(year, team_a, team_b, method="keener", sport="cfb")` — head-to-head,
  common opponents, rating comparison
- `get_champion(year, method="keener", sport="cfb")` — the #1 team with full evidence

## Development

```bash
uv run pytest
uv run mypy --strict src/cfb_strength
uv run lint-imports
```

`mypy --strict` covers the whole package, not just `contracts.py` — widened in
PR #93 so that the modules *implementing* `RatingMethod` are checked for
conformance, not only the Protocol declaring it. `.github/workflows/ci.yml`
runs exactly these three commands.

### Regenerating the test fixtures

`tests/fixtures/cfb_regression.sqlite3` (CFB 2001, 2003, 2004, 2005, 2013,
2017, 2019) and `tests/fixtures/nfl_regression.sqlite3` (NFL 1999, 2004,
2013, 2022) are generated from the committed raw cache, never copied out of
a local db:

```bash
uv run python tests/fixtures/build_regression_fixtures.py
```

It runs the real ingest path with live fetches disabled, prunes to those
seasons, stores no ratings, and is byte-for-byte reproducible on the same
SQLite build. Rerun it after any change to the schema, to either ingest
path, or to those seasons' cached data, then rebuild `apps/api`'s fixture
(`apps/api/tests/fixtures/build_fixture.py`), which starts from
`cfb_regression.sqlite3`. Pytest treats `StaleDatabaseWarning` as an error,
and `tests/test_regression_fixtures_currency.py` runs `cfb doctor`'s check
on both fixtures, so a stale fixture fails the suite.

### `src/cfb_strength/py.typed`

That zero-byte file is a [PEP 561](https://peps.python.org/pep-0561/) marker
and is load-bearing — do not delete it as stray. Without it, every consumer
(today: `apps/api`) sees this package's every symbol as `Any`, so a misspelled
keyword argument or a typo'd attribute on a `contracts.py` exception type-checks
clean at the call site (issue #102). It is included in the wheel automatically
by `uv_build`; `apps/api`'s CI `mypy --strict` job goes red if it goes missing.
