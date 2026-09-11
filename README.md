# My Team Is Better

Ask a college football question. Get a mathematically defensible answer,
delivered by a guy at the end of the bar who is absolutely certain your team
is better — because today, the numbers happen to agree with him.

Sports debate runs on vibes, recency bias, and whoever's loudest. This project
exists to occasionally interrupt that with actual data: a deterministic
strength-of-schedule ranking engine, wrapped in a persona that argues your
case, but never with a number the engine didn't produce.

See `docs/PRD.md` and `docs/ARCHITECTURE.md` for the full product and
architecture picture. `CLAUDE.md` governs how changes get made in this repo
(coordinator/subagent process, engineering standards, CI gates) — read it
before contributing.

## Attribution

This project stands entirely on two things it didn't invent, and credits both
prominently rather than as a footnote:

- **[Keener's method](https://dl.acm.org/doi/10.1137/1035004)** — J. P.
  Keener, "The Perron-Frobenius Theorem and the Ranking of Football Teams,"
  SIAM Review, 35(1), 1993. A team's rating depends recursively on the
  strength of the teams it beat — the same Perron-Frobenius eigenvector idea
  behind PageRank, applied to a win graph instead of a hyperlink graph.
- **Game data** from [CollegeFootballData.com](https://collegefootballdata.com).

## Structure

This is a monorepo with three independently-owned pieces:

| Path | What it is |
| --- | --- |
| `packages/cfb-engine/` | The deterministic ratings engine (Keener's method) and its MCP server. Python, `uv`-managed. See its own [README](packages/cfb-engine/README.md). |
| `apps/api/` | FastAPI backend — verdict/comparison endpoints over the engine, plus the Claude persona narration layer. See its own [README](apps/api/README.md). |
| `apps/web/` | React + TypeScript + Storybook frontend. See its own [README](apps/web/README.md). |

## Engineering standards (short version)

TDD, `mypy --strict` and `import-linter` on the Python side, TypeScript
strict mode and `dependency-cruiser` on the React side, everything gated by
CI (`.github/workflows/ci.yml`) on every PR. Full detail in `CLAUDE.md`.
