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
```

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

- `list_seasons()` — years with computed ratings
- `get_rankings(year, top_n=25, method="keener")` — ranked list for a season
- `get_team_season(year, team, method="keener")` — a team's rank, rating, full schedule
  with opponent context, quality wins, worst loss
- `compare_teams(year, team_a, team_b, method="keener")` — head-to-head, common
  opponents, rating comparison
- `get_champion(year, method="keener")` — the #1 team with full evidence

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

### `src/cfb_strength/py.typed`

That zero-byte file is a [PEP 561](https://peps.python.org/pep-0561/) marker
and is load-bearing — do not delete it as stray. Without it, every consumer
(today: `apps/api`) sees this package's every symbol as `Any`, so a misspelled
keyword argument or a typo'd attribute on a `contracts.py` exception type-checks
clean at the call site (issue #102). It is included in the wheel automatically
by `uv_build`; `apps/api`'s CI `mypy --strict` job goes red if it goes missing.
