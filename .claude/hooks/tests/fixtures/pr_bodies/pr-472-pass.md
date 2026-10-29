## Why
The live proxy check for #471 showed `HEAD /s?…` on the web domain returning **405** from the API: FastAPI's `@router.get` doesn't answer HEAD.

## What changed
- `apps/api/src/api/share.py`: both share routes are `api_route(methods=["GET", "HEAD"])`.

## Verification (coordinator, inline one-line fix)
- Red first: the new test failed on the unchanged module (2 failed).
- `apps/api` (no .env): `pytest -q` 2680 passed; `mypy --strict`, `ruff` and `lint-imports` are clean.

Part of #185.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
