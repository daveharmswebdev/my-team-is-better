---
paths:
  - "packages/**/*.py"
  - "apps/api/**/*.py"
  - "**/pyproject.toml"
  - ".claude/hooks/**/*.py"
---

# Python: the exact checks

Run the same commands CI runs (`.github/workflows/ci.yml`), from the package directory:

| Where | Checks |
|---|---|
| `packages/cfb-engine` | `uv run pytest -q` · `uv run mypy --strict src/cfb_strength tests/fixtures/build_regression_fixtures.py` · `uv run lint-imports` |
| `apps/api` | `uv run pytest -q` · `uv run mypy --strict src/api tests` · `uv run ruff check .` · `uv run ruff format --check .` · `uv run lint-imports` |
| `.claude/hooks` | see the `claude-process` job in ci.yml |

- `uv` only — never `pip install`. Install with `uv sync --all-extras --dev` from the
  package directory (#119: a bare `uv sync` in `apps/api` prunes root-only dev deps).
- `packages/cfb-engine` has no ruff gate yet (#141). Don't add new findings: run
  `uv run --with ruff ruff check <files you touched>`.
- `mypy --strict` is not negotiable across a module boundary. Don't add
  `# type: ignore` without an error code and a reason on the same line.
- `import-linter` contracts (`.importlinter` in each package) are the boundary. A task
  that needs to cross one is a `contract-insufficient` finding, never a new import.
- Secrets: never run `apps/api` tests from a checkout that has `apps/api/.env`
  (spoke-protocol explains why).
