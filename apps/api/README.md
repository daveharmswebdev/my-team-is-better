# apps/api

FastAPI backend for My Team Is Better. Owns HTTP endpoints, the
deterministic `/api/verdict/*` evidence routes (issue #3), and the Claude
persona narration layer wrapping them (issue #4).

## The engine layering rule

This app is a top-layer consumer of `packages/cfb-engine`, exactly like
`cfb_strength.cli` and `cfb_strength.mcp_server` are. It calls the engine
directly as a read-only Python import (workspace dependency), and:

- it **may** import `cfb_strength.evidence`, `cfb_strength.db`,
  `cfb_strength.contracts` and `cfb_strength.config`;
- it **must not** import `cfb_strength.ratings`, `cfb_strength.ingest`,
  `cfb_strength.mcp_server` or `cfb_strength.cli`.

That is a checked rule, not a review convention -- `.importlinter` in this
directory, run by `uv run lint-imports` from `apps/api` (issue #54). See
`docs/ARCHITECTURE.md` §2 and §4 for the reasoning.

The one sanctioned exception is `tests/fixtures/build_fixture.py`, a
standalone generator script that imports `cfb_strength.ratings` to bake the
committed test fixture db. It is not part of the `api` package and not
collected by pytest, so it sits outside the contract's graph structurally --
there is no ignore rule, and none should be added. A generator script that
needs `ratings` or `ingest` belongs there, never under `src/api/`.

## Local development

Copy `.env.example` to `.env` (gitignored) and fill in `DATABASE_URL`
(a real Postgres instance -- the persona response cache) and
`ANTHROPIC_API_KEY` (for the persona narration calls). Both are optional
for the mocked unit test suite: unset, `pytest` still passes (a small
number of tests that require a live Postgres connection and a real Claude
API call auto-skip via `pytest.mark.skipif`).

```bash
cd apps/api
uv sync --all-extras --dev
uv run uvicorn api.main:app --reload
uv run pytest
uv run mypy --strict src/api tests
uv run ruff check .
uv run ruff format --check .
uv run lint-imports
```
