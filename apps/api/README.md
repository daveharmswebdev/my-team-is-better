# apps/api

FastAPI backend for My Team Is Better. Owns HTTP endpoints, the
deterministic `/api/verdict/*` evidence routes (issue #3), and the Claude
persona narration layer wrapping them (issue #4). Imports
`cfb_strength.evidence` and `cfb_strength.db.connection` directly
(read-only, workspace dependency on `packages/cfb-engine`) -- see
`docs/ARCHITECTURE.md` §2 and §4 for the layering rule this app must not
violate.

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
```
