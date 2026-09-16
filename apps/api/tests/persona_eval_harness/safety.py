"""The harness's refusals, checked before anything imports `api.config`.

Standard library only: `api.config` loads `apps/api/.env` at import, and a
run from a checkout with that file (or with `DATABASE_URL` or
`MY_TEAM_IS_BETTER_API_ENV_FILE` set) is exactly what spoke-protocol's
secrets rule forbids. So `persona_eval_harness.cli` runs these checks on the
raw environment first and imports the rest of the harness only after they
pass.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

# tests/persona_eval_harness/safety.py -> apps/api/
API_APP_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = API_APP_ROOT / ".env"

# Set at all, even empty, is a refusal: `api.config` reads the env-file
# variable as a path, and an empty DATABASE_URL still marks a checkout that
# was pointed at a database.
FORBIDDEN_ENV_VARS = ("DATABASE_URL", "MY_TEAM_IS_BETTER_API_ENV_FILE")
KEY_ENV_VAR = "ANTHROPIC_API_KEY"


def preflight_refusals(*, environ: Mapping[str, str], env_file: Path, live: bool) -> list[str]:
    """Every reason not to start, empty when the run may go ahead. `live` is
    false for `--dry-run`, which needs no key but still refuses the rest."""
    refusals: list[str] = []
    if env_file.exists():
        refusals.append(
            f"{env_file} exists; run the harness from a worktree without apps/api/.env "
            "(api.config would load it)"
        )
    for variable in FORBIDDEN_ENV_VARS:
        if variable in environ:
            refusals.append(
                f"{variable} is set; unset it (env -u {variable}) so nothing can reach "
                "production Postgres or load another env file"
            )
    if live and not environ.get(KEY_ENV_VAR):
        refusals.append(
            f"{KEY_ENV_VAR} is unset; a live run makes real Claude calls "
            "(use --dry-run to check the dataset and estimate without one)"
        )
    return refusals
