# apps/api

FastAPI backend for My Team Is Better. Owns HTTP endpoints and (later)
Claude persona orchestration. Imports `cfb_strength.evidence` and
`cfb_strength.db.connection` directly (read-only, workspace dependency on
`packages/cfb-engine`) -- see `docs/ARCHITECTURE.md` §2 and §4 for the
layering rule this app must not violate.

## Local development

```bash
cd apps/api
uv sync --all-extras --dev
uv run uvicorn api.main:app --reload
uv run pytest
uv run mypy --strict src/api
```
