"""The rating display scale is defined once, in `api.rating_display`, and
published as `apps/api/rating-display.json` for apps/web (issue #165, epic
#113).

apps/web shows a Keener rating scaled and rounded (2005 Texas
`0.005044108672990355` is shown as `5.04`), and the grounding check has to
accept exactly that on-screen number. Both sides are therefore checked
against one definition rather than each typing its own scale:

1. **Covers every method.** `RATING_DISPLAY`'s keys are the `Method`
   contract alias, in order.
2. **The committed file is current.** `rating-display.json` is byte-identical
   to `render()`; on mismatch the message prints the regenerate command.
3. **`display_value` is the card's rounding.** Worked examples, half cases
   and signed zero here; and across every `rating`/`opponent_rating` literal
   in the real fixture fact blocks, it equals Python's
   `format(float(literal) * scale, f".{decimals}f")` -- a faithful proxy for
   apps/web's `(value * scale).toFixed(decimals)`, which formats the same
   binary double.
4. **No redeclared scale.** No module under `src/api/` spells out the Keener
   scale anywhere except `RATING_DISPLAY` itself.
"""

from __future__ import annotations

import ast
import json
import re
import sqlite3
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any, get_args

import pytest
from cfb_strength.db.connection import get_conn
from cfb_strength.evidence.proof import build_team_case

from api.models import Method, TeamCaseOut

API_ROOT = Path(__file__).resolve().parents[1]
SRC_API = API_ROOT / "src" / "api"
DISPLAY_FILE = API_ROOT / "rating-display.json"
REGENERATE_COMMAND = "cd apps/api && uv run python -m api.rating_display"
FIXTURE_DB = Path(__file__).parent / "fixtures" / "cfb_verdict_fixture.sqlite3"


# ---------------------------------------------------------------------------
# 1. covers every method
# ---------------------------------------------------------------------------


def test_rating_display_keys_are_the_method_alias_in_order() -> None:
    from api.rating_display import RATING_DISPLAY

    assert tuple(RATING_DISPLAY) == get_args(Method)


def test_rating_display_values() -> None:
    from api.rating_display import RATING_DISPLAY, RatingDisplay

    assert dict(RATING_DISPLAY) == {
        "keener": RatingDisplay(scale=1000, decimals=2),
        "elo": RatingDisplay(scale=1, decimals=0),
        "elo_career": RatingDisplay(scale=1, decimals=0),
    }


def test_rating_display_is_frozen() -> None:
    from dataclasses import FrozenInstanceError

    from api.rating_display import RATING_DISPLAY

    with pytest.raises(FrozenInstanceError):
        RATING_DISPLAY["keener"].scale = 1  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 2. the committed file is current
# ---------------------------------------------------------------------------


def test_committed_rating_display_file_matches_the_definition() -> None:
    from api.rating_display import render

    expected = render()
    committed_bytes = DISPLAY_FILE.read_bytes() if DISPLAY_FILE.exists() else b"<missing>"
    committed = committed_bytes.decode(errors="replace")

    assert committed_bytes == expected.encode(), (
        f"{DISPLAY_FILE.name} is stale: it is what apps/web is checked against, and it no "
        f"longer matches api.rating_display.RATING_DISPLAY. Regenerate it with:\n\n"
        f"    {REGENERATE_COMMAND}\n\n"
        f"committed:\n{committed}\nlive:\n{expected}"
    )


def test_rendered_format_is_fixed() -> None:
    from api.rating_display import render

    assert render() == (
        "{\n"
        '  "elo": {\n    "decimals": 0,\n    "scale": 1\n  },\n'
        '  "elo_career": {\n    "decimals": 0,\n    "scale": 1\n  },\n'
        '  "keener": {\n    "decimals": 2,\n    "scale": 1000\n  }\n'
        "}\n"
    )


def test_main_writes_the_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import api.rating_display as rating_display

    target = tmp_path / "rating-display.json"
    monkeypatch.setattr(rating_display, "OUTPUT_FILE", target)

    assert rating_display.main() == 0
    assert target.read_text() == rating_display.render()


# ---------------------------------------------------------------------------
# 3. display_value is the card's rounding
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "method", "expected"),
    [
        # Real fixture values (2005 Texas / USC under keener, Texas under elo).
        ("0.005044108672990355", "keener", "5.04"),
        ("0.004736299273644764", "keener", "4.74"),
        ("1933.1932908945062", "elo", "1933"),
        # Exact half cases round away from zero, per method.
        ("0.005045", "keener", "5.05"),
        ("1933.5", "elo", "1934"),
        ("1500.5", "elo_career", "1501"),
        # Printed at exactly the display precision, trailing zeros kept.
        ("0.0051", "keener", "5.10"),
        ("0.005", "keener", "5.00"),
        # No grouping.
        ("1234567.2", "elo", "1234567"),
        # A value that rounds to zero prints unsigned.
        ("-0.000001", "keener", "0.00"),
        ("-0.4", "elo", "0"),
        ("-0.4", "elo_career", "0"),
    ],
)
def test_display_value_examples(value: str, method: Method, expected: str) -> None:
    from api.rating_display import display_value

    assert display_value(Decimal(value), method) == expected


def _collect_ratings(node: Any, out: list[Decimal]) -> None:
    if isinstance(node, dict):
        for key, child in node.items():
            if key in {"rating", "opponent_rating"} and isinstance(child, Decimal):
                out.append(child)
            _collect_ratings(child, out)
    elif isinstance(node, list):
        for child in node:
            _collect_ratings(child, out)


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = get_conn(FIXTURE_DB, read_only=True)
    try:
        yield connection
    finally:
        connection.close()


@pytest.mark.parametrize("method", ["keener", "elo"])
def test_display_value_matches_the_cards_float_formatting_on_real_fact_blocks(
    conn: sqlite3.Connection, method: Method
) -> None:
    """Every rated team, every fixture year (2001, 2005, 2013), both computed
    methods: every `rating`/`opponent_rating` literal in its real team-case
    fact block. `format(float, ".Nf")` rounds the exact binary double, as JS
    `toFixed` does; the only divergence would be an exact binary tie (Python
    rounds half-even there, JS up), and a disagreement of any kind fails here
    rather than being papered over. 2026-09-13: 9985 values checked across
    both methods, 0 mismatches."""
    from api.rating_display import RATING_DISPLAY, display_value

    display = RATING_DISPLAY[method]
    rows = conn.execute(
        "SELECT r.year AS year, t.school AS school FROM ratings r "
        "JOIN teams t ON t.id = r.team_id WHERE r.method = ? AND r.sport = 'cfb'",
        (method,),
    ).fetchall()
    checked = 0
    mismatches: list[str] = []
    for row in rows:
        case = build_team_case(conn, row["year"], row["school"], method=method, sport="cfb")
        ratings: list[Decimal] = []
        _collect_ratings(
            json.loads(TeamCaseOut.from_dataclass(case).model_dump_json(), parse_float=Decimal),
            ratings,
        )
        for literal in ratings:
            checked += 1
            ours = display_value(literal, method)
            card = format(float(str(literal)) * display.scale, f".{display.decimals}f")
            if ours != card:
                mismatches.append(f"{row['year']} {row['school']} {literal}: {ours} vs {card}")

    assert checked > 4000, checked
    assert mismatches == []


# ---------------------------------------------------------------------------
# 4. no redeclared scale
# ---------------------------------------------------------------------------

# The Keener scale as a number, or as text ("1000", "1,000") inside a string
# such as the prompt template.
_SCALE_TEXT_RE = re.compile(r"(?<![\d.,])1,?000(?![\d,]|\.\d)")


def _rating_display_definition_nodes(tree: ast.Module) -> set[int]:
    for node in tree.body:
        target = (
            node.target
            if isinstance(node, ast.AnnAssign)
            else node.targets[0]
            if isinstance(node, ast.Assign) and len(node.targets) == 1
            else None
        )
        if isinstance(target, ast.Name) and target.id == "RATING_DISPLAY":
            return {id(sub) for sub in ast.walk(node)}
    return set()


def _scale_redeclarations(path: Path, *, allow_definition: bool) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    allowed = _rating_display_definition_nodes(tree) if allow_definition else set()
    found: list[str] = []
    for sub in ast.walk(tree):
        if id(sub) in allowed or not isinstance(sub, ast.Constant):
            continue
        value = sub.value
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float) and value == 1000:
            found.append(f"{path.name}:{sub.lineno} numeric literal {value!r}")
        elif isinstance(value, str) and _SCALE_TEXT_RE.search(value):
            found.append(f"{path.name}:{sub.lineno} string spells out the scale: {value[:60]!r}")
    return found


def test_no_module_under_src_api_redeclares_the_keener_scale() -> None:
    found = [
        hit
        for path in sorted(SRC_API.rglob("*.py"))
        for hit in _scale_redeclarations(path, allow_definition=path.name == "rating_display.py")
    ]

    assert found == [], (
        "the rating display scale is defined once, in api.rating_display.RATING_DISPLAY; "
        "read it from there:\n  " + "\n  ".join(found)
    )


def test_scale_redeclaration_scan_is_not_vacuous(tmp_path: Path) -> None:
    sample = tmp_path / "prompt.py"
    sample.write_text(
        'TEMPLATE = """multiplied by 1000 and shown to 2 decimal places"""\n'
        "SCALE = 1_000\n"
        "OTHER = 1e3\n"
        'FINE = "10000 and 2001 and 1000.5"\n'
    )

    found = _scale_redeclarations(sample, allow_definition=False)

    assert len(found) == 3, found
