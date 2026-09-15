"""Every top-level `cfb_strength` module must be classified for `apps/api`
(issue #54, epic #113).

`docs/ARCHITECTURE.md` §2 states the layering rule as an allow list: this app
may import `evidence`, `players`, `db`, `contracts` and `config` from the engine, and
nothing else. import-linter has no "source may import only these" contract
type, so `.importlinter` enforces it as `forbidden` contracts naming every
other top-level module. A deny list like that silently goes stale the moment
the engine grows a module nobody added to it -- which is exactly how
`cfb_strength.credit_math` sat unforbidden while four docstrings called it
forbidden (found in review of PR #118).

This test is what makes the deny list the exact complement of the allow list:
it fails on any top-level engine module that is neither permitted here nor
named in one of `.importlinter`'s forbidden contracts. Adding an engine module
therefore forces a decision about whether this app may use it.
"""

from __future__ import annotations

import configparser
import pkgutil
from pathlib import Path

import cfb_strength

PERMITTED = frozenset({"evidence", "players", "db", "contracts", "config"})

IMPORTLINTER_CONFIG = Path(__file__).resolve().parents[1] / ".importlinter"


def _top_level_engine_modules() -> frozenset[str]:
    return frozenset(m.name for m in pkgutil.iter_modules(cfb_strength.__path__))


def _forbidden_modules() -> frozenset[str]:
    parser = configparser.ConfigParser(interpolation=None)
    assert parser.read(IMPORTLINTER_CONFIG), f"missing {IMPORTLINTER_CONFIG}"
    forbidden: set[str] = set()
    for section in parser.sections():
        if not section.startswith("importlinter:contract:"):
            continue
        contract = parser[section]
        if contract.get("type") != "forbidden":
            continue
        assert contract.get("source_modules", "").split() == ["api"], section
        for module in contract["forbidden_modules"].split():
            top, _, _ = module.removeprefix("cfb_strength.").partition(".")
            assert module.startswith("cfb_strength.") and module == f"cfb_strength.{top}", (
                f"{section}: forbid whole top-level modules, got {module!r}"
            )
            forbidden.add(top)
    return frozenset(forbidden)


def test_every_top_level_engine_module_is_permitted_or_forbidden() -> None:
    unclassified = _top_level_engine_modules() - PERMITTED - _forbidden_modules()
    assert not unclassified, (
        f"cfb_strength module(s) {sorted(unclassified)} are neither PERMITTED for apps/api "
        "nor forbidden in apps/api/.importlinter -- classify them in both this test and "
        "docs/ARCHITECTURE.md §2"
    )


def test_permitted_and_forbidden_are_disjoint() -> None:
    assert not PERMITTED & _forbidden_modules()


def test_every_classified_module_exists() -> None:
    # A renamed or deleted engine module must not leave a stale entry behind
    # on either list, where it would read as coverage it no longer provides.
    stale = (PERMITTED | _forbidden_modules()) - _top_level_engine_modules()
    assert not stale, f"classified but no longer in cfb_strength: {sorted(stale)}"
