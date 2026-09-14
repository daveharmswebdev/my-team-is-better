"""Safety properties of `tests/fixtures/build_regression_fixtures.py` itself
(issue #110, round 2).

1. It can never fetch live. It disables fetching by replacing the clients'
   private live-fetch functions, so a renamed function would make that
   replacement a silent no-op and the next cache miss a real HTTPS request.
   `live_fetches_disabled` therefore checks that every name it replaces
   exists and is callable before replacing any of them, and these tests
   check that it refuses otherwise, and that it covers every function in
   either client that touches `requests`.
2. A failed build leaves nothing behind: no `.partial` db, no `-journal`, and
   an existing fixture at the destination is left untouched.
"""

from __future__ import annotations

import dataclasses
import inspect
import sqlite3
from pathlib import Path
from types import ModuleType

import pytest

from cfb_strength.ingest import client as cfbd_client
from cfb_strength.ingest import ingest_season as cfbd_ingest
from cfb_strength.ingest.nflverse import client as nflverse_client
from tests.fixtures import build_regression_fixtures as generator

STUBBED = [(module, name) for module, name in generator.LIVE_FETCH_FUNCTIONS]
STUBBED_IDS = [f"{module.__name__}.{name}" for module, name in STUBBED]


def _current(module: ModuleType, name: str) -> object:
    return getattr(module, name, None)


@pytest.mark.parametrize(("module", "name"), STUBBED, ids=STUBBED_IDS)
@pytest.mark.parametrize("breakage", ["missing", "not-callable"])
def test_refuses_when_a_stubbed_live_fetch_name_is_missing_or_not_callable(
    monkeypatch: pytest.MonkeyPatch, module: ModuleType, name: str, breakage: str
) -> None:
    if breakage == "missing":
        monkeypatch.delattr(module, name)
    else:
        monkeypatch.setattr(module, name, None)
    before = {(m.__name__, n): _current(m, n) for m, n in STUBBED}

    with pytest.raises(RuntimeError, match=name):
        with generator.live_fetches_disabled():
            pytest.fail("entered the build with a live fetch left unguarded")

    # Checked before patching anything: no other name was replaced either.
    assert {(m.__name__, n): _current(m, n) for m, n in STUBBED} == before


def test_disables_every_live_fetch_and_restores_them() -> None:
    originals = {(m.__name__, n): _current(m, n) for m, n in STUBBED}
    with generator.live_fetches_disabled():
        for module, name in STUBBED:
            replacement = getattr(module, name)
            assert replacement is not originals[(module.__name__, name)]
            with pytest.raises(RuntimeError, match="never fetches live"):
                replacement()
        # The public cache-first entry points refuse on a cache miss.
        with pytest.raises(RuntimeError, match="never fetches live"):
            cfbd_client.get_games(1800, "regular", raw_dir=Path("/nonexistent-raw-dir"))
    assert {(m.__name__, n): _current(m, n) for m, n in STUBBED} == originals


@pytest.mark.parametrize("module", [cfbd_client, nflverse_client], ids=lambda m: m.__name__)
def test_every_client_function_that_touches_requests_is_stubbed(module: ModuleType) -> None:
    """A new live-fetch function added beside the stubbed ones must be
    stubbed too, or the generator could reach the network through it."""
    touching = {
        name
        for name, fn in inspect.getmembers(module, inspect.isfunction)
        if fn.__module__ == module.__name__ and "requests." in inspect.getsource(fn)
    }
    assert touching
    assert touching == {name for m, name in STUBBED if m is module}


def _leftovers(out_dir: Path) -> list[str]:
    return sorted(p.name for p in out_dir.iterdir())


@pytest.mark.parametrize("error", [RuntimeError, KeyboardInterrupt])
def test_a_build_that_fails_mid_ingest_leaves_no_partial_files(
    tmp_path: Path, error: type[BaseException]
) -> None:
    partial = tmp_path / ".cfb_regression.sqlite3.partial"
    reached: list[bool] = []

    def fail_mid_ingest(conn: sqlite3.Connection) -> None:
        cfbd_ingest.ingest_one(conn, 2001, "regular")
        conn.execute("UPDATE games SET home_points = home_points WHERE season = 2001")
        # Mid-transaction, with the partial db really on disk.
        assert partial.is_file()
        reached.append(True)
        raise error("forced mid-build failure")

    spec = dataclasses.replace(generator.FIXTURES["cfb"], build=fail_mid_ingest)
    with generator.live_fetches_disabled():
        with pytest.raises(error, match="forced mid-build failure"):
            generator.build(spec, tmp_path)

    assert reached == [True]
    assert _leftovers(tmp_path) == []


def test_a_build_that_fails_its_final_check_keeps_the_existing_fixture(tmp_path: Path) -> None:
    dest = tmp_path / "cfb_regression.sqlite3"
    dest.write_bytes(b"the previously committed fixture")

    def ingest_one_season_only(conn: sqlite3.Connection) -> None:
        cfbd_ingest.ingest_one(conn, 2001, "regular")
        cfbd_ingest.ingest_one(conn, 2001, "postseason")

    spec = dataclasses.replace(generator.FIXTURES["cfb"], build=ingest_one_season_only)
    with generator.live_fetches_disabled():
        with pytest.raises(RuntimeError, match="seasons"):
            generator.build(spec, tmp_path)

    assert _leftovers(tmp_path) == ["cfb_regression.sqlite3"]
    assert dest.read_bytes() == b"the previously committed fixture"
