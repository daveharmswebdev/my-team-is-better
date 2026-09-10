"""Failing-first smoke test proving cfb_strength.config.DB_PATH resolves
correctly from apps/api, regardless of the process's current working
directory.

This test does NOT re-implement path resolution -- it only proves the
claim in docs/ARCHITECTURE.md / config.py's docstring: `DB_PATH` is derived
from `Path(__file__).resolve()` inside config.py itself, so it must resolve
to the same absolute path no matter where the caller's cwd is.
"""

import importlib
import sys
from pathlib import Path

import pytest


def test_db_path_resolves_to_cfb_engine_data_regardless_of_cwd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Make sure no env override is in play -- we want the real default.
    monkeypatch.delenv("CFB_DB_PATH", raising=False)
    monkeypatch.delenv("CFB_DATA_DIR", raising=False)

    # Prove cwd-independence for real: change to an unrelated directory
    # *before* importing, then force a fresh import of the module.
    monkeypatch.chdir(tmp_path)
    sys.modules.pop("cfb_strength.config", None)
    config = importlib.import_module("cfb_strength.config")

    assert config.DB_PATH.is_absolute()
    # The path must land in packages/cfb-engine/data/cfb.sqlite3 no matter
    # that the process cwd right now is an unrelated tmp_path.
    assert config.DB_PATH.parts[-4:] == (
        "packages",
        "cfb-engine",
        "data",
        "cfb.sqlite3",
    )
    assert Path.cwd() == tmp_path
