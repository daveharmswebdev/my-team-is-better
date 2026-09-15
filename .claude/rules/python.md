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
| `packages/cfb-engine` | `uv run pytest -q` · `uv run mypy --strict src/cfb_strength tests/fixtures/build_regression_fixtures.py` · `uv run lint-imports` · `uv run ruff check .` · `uv run ruff format --check .` |
| `apps/api` | `uv run pytest -q` · `uv run mypy --strict src/api tests` · `uv run ruff check .` · `uv run ruff format --check .` · `uv run lint-imports` |
| `.claude/hooks` | see the `claude-process` job in ci.yml |

- `uv` only — never `pip install`. Install with `uv sync --all-packages --all-extras --dev`
  from the **repo root**. The workspace has one shared venv, and any `uv sync` run
  inside `apps/api` or `packages/cfb-engine` resolves against that member alone and
  uninstalls the other member's dev tools from it (#119: measured 9 and 18 packages).
- Both Python packages are gated on `ruff check` and `ruff format --check` in CI and
  pre-commit, with one shared configuration (#141). Run `uv run ruff format .` before
  committing; never add `# noqa` or a per-file ignore just to reach green.
- `mypy --strict` is not negotiable across a module boundary. Don't add
  `# type: ignore` without an error code and a reason on the same line.
- `import-linter` contracts (`.importlinter` in each package) are the boundary. A task
  that needs to cross one is a `contract-insufficient` finding, never a new import.
- Secrets: never run `apps/api` tests from a checkout that has `apps/api/.env`
  (spoke-protocol explains why).
