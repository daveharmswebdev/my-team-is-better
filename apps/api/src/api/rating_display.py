"""How the site displays a rating, defined once (issue #165).

apps/web shows a rating scaled and rounded to a fixed number of decimals
(a Keener rating is a small fraction, so it is scaled up; an Elo rating is
shown in whole points). The persona grounding check has to accept exactly
that on-screen number, and the persona prompt has to tell the narrator what
it is, so all three read the scale from `RATING_DISPLAY` here instead of
each typing their own.

The definition is published as `apps/api/rating-display.json`, which apps/web
is checked against. `tests/test_rating_display.py` fails when that committed
file is stale. Regenerate it (from the repo root) with:

    cd apps/api && uv run python -m api.rating_display

Format (fixed, because apps/web builds against it): one key per method,
keys sorted, each value `{"decimals": ..., "scale": ...}` with sorted keys,
two-space indent, trailing newline -- the same convention as
`api.openapi_vocabularies.render`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Final

from api.models import Method

OUTPUT_FILE: Path = Path(__file__).resolve().parents[2] / "rating-display.json"


@dataclass(frozen=True)
class RatingDisplay:
    """A rating is displayed as `value * scale`, rounded to `decimals` places
    and printed at exactly that precision.

    `display_value` rounds the exact decimal half away from zero. apps/web's
    `toFixed` rounds the binary double instead, so the two can differ on a
    short decimal tie (`0.003505` -> "3.51" here, "3.50" on the card). Real
    ratings are full-precision doubles, where they agree; see
    `tests/test_rating_display.py`'s cross-check on the fixture."""

    scale: int
    decimals: int


RATING_DISPLAY: Final[Mapping[Method, RatingDisplay]] = MappingProxyType(
    {
        "keener": RatingDisplay(scale=1000, decimals=2),
        "elo": RatingDisplay(scale=1, decimals=0),
        "elo_career": RatingDisplay(scale=1, decimals=0),
    }
)
"""Per method, in `Method`'s order (a test pins both)."""


def display_value(value: Decimal, method: Method) -> str:
    """`value` as the site displays it under `method`: scaled, rounded half
    away from zero to the display's decimals, printed at exactly that
    precision with no grouping. A result that rounds to zero is unsigned."""
    display = RATING_DISPLAY[method]
    rounded = (value * display.scale).quantize(
        Decimal(1).scaleb(-display.decimals), rounding=ROUND_HALF_UP
    )
    if rounded.is_zero():
        rounded = abs(rounded)
    return f"{rounded:.{display.decimals}f}"


def render() -> str:
    """The committed file's exact bytes."""
    payload = {method: asdict(display) for method, display in RATING_DISPLAY.items()}
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def main() -> int:
    OUTPUT_FILE.write_text(render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
