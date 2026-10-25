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


def qb_rejected(block: str, text: str, *claims: dict[str, object]) -> tuple[str, ...]:
    outcome = qb_check(block, text, *claims)
    assert outcome.text is None, f"expected a rejection, rendered {outcome.text!r}"
    assert outcome.errors, "a rejection must carry errors"
    return outcome.errors


def assert_an_error_says(errors: Sequence[str], *needles: str) -> None:
    assert any(all(needle in error for needle in needles) for error in errors), (
        f"no error mentions all of {needles}: {list(errors)}"
    )
