"""Real QB-verdict evidence and fact blocks for the QB narration tests (#451).

Every block here is the exact string production hands the narrator: the
engine's `get_player_comparison` and `get_qb_score_comparison` on the
committed fixture's NFL 1999 + 2023 slice, then
`QbVerdictEvidenceOut.from_dataclasses`, then `api.persona.service`'s own
`qb_fact_block_json`. A hand-written block would drift from production the
first time the exclusion map changed.

Fixture quarterbacks, measured on that db (every one has exactly one
regular season, so career and peak always have the same winner here):

* Kurt Warner (1999; career began 1998, so cut off): career 2.25, peak 0.45.
* Steve McNair (1999; began 1995, cut off): career 0.60, peak 0.12.
* Donovan McNabb (1999; began 1999, not cut off): career -1.92, peak -0.38.
* Russell Wilson (2023) and Trevor Lawrence (2023): careers -0.047 and
  -0.046, both printed "-0.05", so a margin between them prints nothing.
* Randall Cunningham (1999, 214 dropbacks) and Tommy DeVito (2023, 215):
  below the 224-dropback line, no qualifying season.

Not part of the pytest suite itself (doesn't match `test_*.py`).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from functools import cache

from cfb_strength.players import get_player_comparison, get_qb_score_comparison

from api.models import QbVerdictEvidenceOut
from api.persona.claims import ClaimOutcome
from api.persona.qb_claims import check_and_render_qb
from api.persona.service import qb_fact_block_json
from api.repositories.players import list_player_names
from fixtures.player_api_fixture import fixture_conn

KURT_WARNER = 2044124519
STEVE_MCNAIR = 2385180619
DONOVAN_MCNABB = 2363866023
RUSSELL_WILSON = 2286374911
TREVOR_LAWRENCE = 2348857057
PEYTON_MANNING = 2153701690
RANDALL_CUNNINGHAM = 2024782845
TOMMY_DEVITO = 2031699001
MARSHALL_FAULK = 2252790861
EDGERRIN_JAMES = 2425879833


@cache
def qb_evidence(a: int, b: int) -> QbVerdictEvidenceOut:
    with fixture_conn() as conn:
        comparison = get_player_comparison(conn, sport="nfl", a=a, b=b)
        qb_score = get_qb_score_comparison(conn, sport="nfl", a=a, b=b)
    return QbVerdictEvidenceOut.from_dataclasses(comparison, qb_score)


@cache
def qb_block(a: int, b: int) -> str:
    return qb_fact_block_json(qb_evidence(a, b))


@cache
def split_evidence() -> QbVerdictEvidenceOut:
    """Kurt Warner vs Steve McNair with McNair's peak raised to 0.5, so Warner
    takes the career and McNair the peak. Every fixture QB has one season, so
    no real fixture pair splits; this is the real block with that one change,
    and the peak verdict and margin changed to match."""
    evidence = qb_evidence(KURT_WARNER, STEVE_MCNAIR)
    score = evidence.qb_score
    assert score.a.peak is not None
    b = score.b.model_copy(update={"peak": 0.5})
    return evidence.model_copy(
        update={
            "qb_score": score.model_copy(
                update={"b": b, "peak_winner": "b", "peak_margin": score.a.peak - 0.5}
            )
        }
    )


@cache
def split_block() -> str:
    return qb_fact_block_json(split_evidence())


@cache
def rescored_evidence(
    a: int, b: int, *, career: tuple[float, float], peak: tuple[float, float]
) -> QbVerdictEvidenceOut:
    """The real block for (a, b) with both players' career and peak scores
    replaced, and the winners and margins recomputed the engine's way
    (winner the higher score, margin a minus b, an exact tie no winner).
    For the margin bands (#457): no fixture pair has a decisive career, a
    split, or a live pair's exact figures (Brady vs P. Manning)."""
    evidence = qb_evidence(a, b)
    score = evidence.qb_score

    def winner(pair: tuple[float, float]) -> str | None:
        if pair[0] == pair[1]:
            return None
        return "a" if pair[0] > pair[1] else "b"

    return evidence.model_copy(
        update={
            "qb_score": score.model_copy(
                update={
                    "a": score.a.model_copy(update={"career": career[0], "peak": peak[0]}),
                    "b": score.b.model_copy(update={"career": career[1], "peak": peak[1]}),
                    "career_winner": winner(career),
                    "peak_winner": winner(peak),
                    "career_margin": career[0] - career[1],
                    "peak_margin": peak[0] - peak[1],
                }
            )
        }
    )


def rescored_block(
    a: int, b: int, *, career: tuple[float, float], peak: tuple[float, float]
) -> str:
    return qb_fact_block_json(rescored_evidence(a, b, career=career, peak=peak))


@cache
def nfl_player_names() -> frozenset[str]:
    with fixture_conn() as conn:
        return list_player_names(conn, "nfl")


def qb_submit(text: str, *claims: dict[str, object]) -> dict[str, object]:
    return {"text": text, "claims": list(claims)}


def qb_check(block: str, text: str, *claims: dict[str, object]) -> ClaimOutcome:
    return check_and_render_qb(qb_submit(text, *claims), block, nfl_player_names())


def qb_rendered(block: str, text: str, *claims: dict[str, object]) -> str:
    outcome = qb_check(block, text, *claims)
    assert outcome.errors == (), outcome.errors
    assert outcome.text is not None
    return outcome.text


def verdict_tail(block: str) -> tuple[str, list[dict[str, object]]]:
    """A closing sentence carrying the claims every QB narration must hold
    (D1 on #451): the `year`, and on a conclusive block the verdict through
    `winner` claims. A test about one kind appends it with
    `qb_rendered_verdict` so it only has to write the sentence it is about."""
    score = json.loads(block)["qb_score"]
    year: dict[str, object] = {"id": "vy", "kind": "year"}
    if score["inconclusive"] is not None:
        return "Counting since {vy}.", [year]
    if score["career_winner"] == score["peak_winner"]:
        return "{vw} takes both, counting since {vy}.", [
            {"id": "vw", "kind": "winner", "measure": "both"},
            year,
        ]
    return "{vc} takes the career, {vp} the peak, counting since {vy}.", [
        {"id": "vc", "kind": "winner", "measure": "career"},
        {"id": "vp", "kind": "winner", "measure": "peak"},
        year,
    ]


def qb_rendered_verdict(block: str, text: str, *claims: dict[str, object]) -> str:
    """`text` rendered with `verdict_tail` appended, and the tail's own
    rendering cut back off, so the assertion is about `text` alone."""
    tail, tail_claims = verdict_tail(block)
    full = qb_rendered(block, f"{text} {tail}", *claims, *tail_claims)
    shown_tail = qb_rendered(block, tail, *tail_claims)
    assert full.endswith(f" {shown_tail}"), (full, shown_tail)
    return full[: -len(shown_tail) - 1]


def qb_rejected(block: str, text: str, *claims: dict[str, object]) -> tuple[str, ...]:
    outcome = qb_check(block, text, *claims)
    assert outcome.text is None, f"expected a rejection, rendered {outcome.text!r}"
    assert outcome.errors, "a rejection must carry errors"
    return outcome.errors


def assert_an_error_says(errors: Sequence[str], *needles: str) -> None:
    assert any(all(needle in error for needle in needles) for error in errors), (
        f"no error mentions all of {needles}: {list(errors)}"
    )
