"""The QB narrator's dataset (issue #463): eight QB-vs-QB fact blocks.

Every block is a real one from `tests/fixtures/qb_blocks.py` (the engine's
comparison on the committed fixture's NFL 1999 + 2023 slice, through
`QbVerdictEvidenceOut` and production's `qb_fact_block_json`):

- `qb-warner-mcnair-sweep`: Warner takes career and peak, both clear;
- `qb-warner-mcnair-split`: `split_block()`, Warner's career (clear) and
  McNair's peak (close);
- `qb-mcnabb-warner-one-cut-off`: McNabb (career began 1999, fully covered)
  against Warner (began 1998, cut off before 1999);
- `qb-cunningham-devito-inconclusive`: neither has a qualifying season;
- `qb-wilson-lawrence-printed-equal`: careers that print the same, close;

and three production-shaped cases, `rescored_block` over Warner vs McNair
with the career and peak scores measured from production on 2026-10-25:

- `qb-brady-manning-split`: career 18.1914 vs 18.0904 (+0.101, close), peak
  1.7261 vs 1.7704 (-0.044, close, b wins);
- `qb-herbert-mayfield-clear`: career 2.1171 vs -0.7880 (+2.905, clear),
  peak 0.4393 vs 0.2644 (+0.175, clear) -- the live miss of 2026-10-25,
  where "not close" was rejected twice and the fallback was served;
- `qb-brady-flacco-decisive`: career 18.1914 vs -4.4199 (+22.611,
  decisive), peak 1.7261 vs 0.1280 (+1.598, decisive).

The names in those three blocks are Warner's and McNair's: only the scores
are production's. Each spec states its (career, peak) bands, which
`tests/test_persona_eval_harness_qb.py` checks against the built block.
Reads the committed sqlite fixture only; never Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from fixtures.qb_blocks import (
    DONOVAN_MCNABB,
    KURT_WARNER,
    RANDALL_CUNNINGHAM,
    RUSSELL_WILSON,
    STEVE_MCNAIR,
    TOMMY_DEVITO,
    TREVOR_LAWRENCE,
    nfl_player_names,
    qb_evidence,
    rescored_evidence,
    split_evidence,
)

from api.models import QbVerdictEvidenceOut
from api.persona.fallback import qb_comparison_fallback_text
from api.persona.service import qb_fact_block_json

Scores = tuple[tuple[float, float], tuple[float, float]]


@dataclass(frozen=True)
class QbCaseSpec:
    """One QB case: the fixture pair, optionally rescored ((career a, b),
    (peak a, b)) or split (`split_evidence`), and its expected bands."""

    id: str
    a: int
    b: int
    career_band: str | None
    peak_band: str | None
    rescore: Scores | None = None
    split: bool = False


QB_CASE_SPECS: tuple[QbCaseSpec, ...] = (
    QbCaseSpec("qb-warner-mcnair-sweep", KURT_WARNER, STEVE_MCNAIR, "clear", "clear"),
    QbCaseSpec("qb-warner-mcnair-split", KURT_WARNER, STEVE_MCNAIR, "clear", "close", split=True),
    QbCaseSpec("qb-mcnabb-warner-one-cut-off", DONOVAN_MCNABB, KURT_WARNER, "clear", "decisive"),
    QbCaseSpec("qb-cunningham-devito-inconclusive", RANDALL_CUNNINGHAM, TOMMY_DEVITO, None, None),
    QbCaseSpec(
        "qb-wilson-lawrence-printed-equal", RUSSELL_WILSON, TREVOR_LAWRENCE, "close", "close"
    ),
    QbCaseSpec(
        "qb-brady-manning-split",
        KURT_WARNER,
        STEVE_MCNAIR,
        "close",
        "close",
        rescore=((18.1914, 18.0904), (1.7261, 1.7704)),
    ),
    QbCaseSpec(
        "qb-herbert-mayfield-clear",
        KURT_WARNER,
        STEVE_MCNAIR,
        "clear",
        "clear",
        rescore=((2.1171, -0.7880), (0.4393, 0.2644)),
    ),
    QbCaseSpec(
        "qb-brady-flacco-decisive",
        KURT_WARNER,
        STEVE_MCNAIR,
        "decisive",
        "decisive",
        rescore=((18.1914, -4.4199), (1.7261, 0.1280)),
    ),
)


@dataclass(frozen=True)
class QbEvalCase:
    """A QB case ready to narrate: the evidence production's
    `narrate_qb_comparison` takes, and what it derives from it."""

    spec: QbCaseSpec
    evidence: QbVerdictEvidenceOut
    fact_block_json: str
    fallback_text: str
    player_names: frozenset[str]
    contested: bool = False
    user_team: str | None = None

    @property
    def id(self) -> str:
        return self.spec.id

    @property
    def players(self) -> str:
        return f"{self.evidence.a.display_name} vs {self.evidence.b.display_name}"


def _evidence(spec: QbCaseSpec) -> QbVerdictEvidenceOut:
    if spec.split:
        return split_evidence()
    if spec.rescore is not None:
        career, peak = spec.rescore
        return rescored_evidence(spec.a, spec.b, career=career, peak=peak)
    return qb_evidence(spec.a, spec.b)


def build_qb_dataset(specs: Sequence[QbCaseSpec] = QB_CASE_SPECS) -> tuple[QbEvalCase, ...]:
    """Every case in `specs`, in order."""
    names = nfl_player_names()
    cases: list[QbEvalCase] = []
    for spec in specs:
        evidence = _evidence(spec)
        cases.append(
            QbEvalCase(
                spec=spec,
                evidence=evidence,
                fact_block_json=qb_fact_block_json(evidence),
                fallback_text=qb_comparison_fallback_text(evidence),
                player_names=names,
            )
        )
    return tuple(cases)
