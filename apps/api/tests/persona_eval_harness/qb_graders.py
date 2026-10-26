"""The QB narrator's code graders (issue #463), pure functions of one served
narration.

1. **no hedge**: none of `HEDGE_PHRASES` in the served text. The founder's
   rule is that the numbers are the numbers; a narrator that calls a decided
   comparison a toss-up argues with the math.
2. **year present**: the accepted `submit_narration` input has a `year`
   claim (the counting-since disclosure, #443).
3. **both winners named**: for each of career and peak that has a winner in
   the fact block, a `winner` claim for that measure (or for `both`). N/A
   when neither measure has a winner (an inconclusive verdict).
4. **margin wording fits the band**, under the founder's two-tier rule
   (2026-10-26): photo-finish words only if some measure is close; MILD
   runaway words only if some measure is clear or decisive; HARD runaway
   words only if some measure is decisive. Coarse on purpose: it reads the
   whole served text, not which measure a word is about, so a split with a
   close peak and a decisive career allows both kinds. The production check
   (`api.persona.qb_claims`) is stricter and per measure; this grader is the
   target the next prompt round (round B of #463) is scored against. The
   word lists are `MARGIN_WORDING`, one table, so that round can edit them.

A served fallback, or a served text the harness can't trace to an accepted
call, has no accepted input: graders 2-4 are N/A (`None`) for it, neither a
pass nor a fail. Grader 1 still reads its text.

Words match whole, case-insensitively, with any run of spaces or hyphens
between the words of a phrase ("toss up" and "toss-up" both match "toss
up"), so "rout" doesn't match "route" and "laps" doesn't match "lapse".
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

HEDGE_PHRASES: Final[tuple[str, ...]] = (
    "too close to call",
    "toss-up",
    "toss up",
    "basically even",
    "coin flip",
    "could go either way",
    "hard to say",
    "dead even",
)


@dataclass(frozen=True)
class MarginTier:
    """Words that fit only when some measure's band is in `allowed_bands`."""

    allowed_bands: frozenset[str]
    words: tuple[str, ...]


MARGIN_WORDING: Final[Mapping[str, MarginTier]] = {
    "photo_finish": MarginTier(
        allowed_bands=frozenset({"close"}),
        words=(
            "by a nose",
            "photo finish",
            "by a hair",
            "squeaks by",
            "razor-thin",
            "by a whisker",
        ),
    ),
    "mild_runaway": MarginTier(
        allowed_bands=frozenset({"clear", "decisive"}),
        words=("not close", "pulls away", "comfortably", "with room to spare"),
    ),
    "hard_runaway": MarginTier(
        allowed_bands=frozenset({"decisive"}),
        words=("runs away", "blowout", "laps", "no contest", "landslide", "rout", "in a walk"),
    ),
}

_MEASURES: Final = ("career", "peak")


def _phrase_re(phrase: str) -> re.Pattern[str]:
    parts = [re.escape(part) for part in re.split(r"[\s-]+", phrase)]
    return re.compile(r"(?<!\w)" + r"[\s-]+".join(parts) + r"(?!\w)", re.IGNORECASE)


def phrase_hits(text: str, phrases: Sequence[str]) -> tuple[str, ...]:
    """Every phrase in `phrases` that occurs in `text`, in list order."""
    normalized = text.replace("’", "'")
    return tuple(phrase for phrase in phrases if _phrase_re(phrase).search(normalized))


def hedge_hits(text: str) -> tuple[str, ...]:
    return phrase_hits(text, HEDGE_PHRASES)


def margin_wording_violations(text: str, bands: frozenset[str]) -> tuple[str, ...]:
    """One line per margin word whose tier allows none of `bands` (the bands
    of the measures in this fact block)."""
    violations: list[str] = []
    for tier_name, tier in MARGIN_WORDING.items():
        if tier.allowed_bands & bands:
            continue
        for word in phrase_hits(text, tier.words):
            violations.append(
                f"{tier_name} word {word!r} needs a {'/'.join(sorted(tier.allowed_bands))} "
                f"margin; this block's bands are {sorted(bands) or 'none'}"
            )
    return tuple(violations)


def _claims(served_input: object) -> list[Mapping[object, object]]:
    if not isinstance(served_input, dict):
        return []
    claims = served_input.get("claims")
    if not isinstance(claims, list):
        return []
    return [claim for claim in claims if isinstance(claim, dict)]


def has_year_claim(served_input: object) -> bool:
    return any(claim.get("kind") == "year" for claim in _claims(served_input))


def winners_named(served_input: object, fact_block_json: str) -> bool | None:
    """Whether every measure with a winner has a winner claim; None when no
    measure has one."""
    score = json.loads(fact_block_json)["qb_score"]
    needed = [measure for measure in _MEASURES if score.get(f"{measure}_winner") is not None]
    if not needed:
        return None
    named = {
        claim.get("measure") for claim in _claims(served_input) if claim.get("kind") == "winner"
    }
    return all(measure in named or "both" in named for measure in needed)


def block_bands(fact_block_json: str) -> frozenset[str]:
    """The margin bands the QB fact block states (`career_band`,
    `peak_band`), the ones production's check holds the prose to."""
    score = json.loads(fact_block_json)["qb_score"]
    return frozenset(
        band for measure in _MEASURES if isinstance(band := score.get(f"{measure}_band"), str)
    )


@dataclass(frozen=True)
class QbGrades:
    """The four graders on one narration; `None` is N/A."""

    no_hedge: bool
    year_present: bool | None
    winners_named: bool | None
    margin_wording: bool | None
    hedge_hits: tuple[str, ...]
    margin_violations: tuple[str, ...]


def grade_qb(*, served_text: str, served_input: object | None, fact_block_json: str) -> QbGrades:
    """Grade one served narration. `served_input` is the accepted
    `submit_narration` input production rendered, or None for a served
    fallback (or an untraceable text)."""
    hedges = hedge_hits(served_text)
    if served_input is None:
        return QbGrades(
            no_hedge=not hedges,
            year_present=None,
            winners_named=None,
            margin_wording=None,
            hedge_hits=hedges,
            margin_violations=(),
        )
    violations = margin_wording_violations(served_text, block_bands(fact_block_json))
    return QbGrades(
        no_hedge=not hedges,
        year_present=has_year_claim(served_input),
        winners_named=winners_named(served_input, fact_block_json),
        margin_wording=not violations,
        hedge_hits=hedges,
        margin_violations=violations,
    )
