"""The fact block a `/api/verdict/*` response was narrated from, rebuilt the
way production builds it (issue #145).

Since #145 the narration cache key covers the fact block (as a sha256), so
a test that wants to look up the key a route wrote needs the exact block the
route handed `api.persona.service`. The route builds that block from the
same `TeamCaseOut` / `ComparisonResultOut` it returns as the envelope's
`evidence`, and pydantic's JSON is a fixed point (dump, parse, validate,
dump again is byte-identical -- checked on both sports' fixtures for keener
and elo before this helper was written), so re-validating the response's
`evidence` and calling the production `team_case_fact_block_json` /
`comparison_fact_block_json` reproduces the block byte for byte.

Only the service's own functions are called here: a hand-written block
would drift from production the first time an exclusion map changed.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from api.models import ComparisonResultOut, TeamCaseOut
from api.persona.service import comparison_fact_block_json, team_case_fact_block_json


def team_case_fact_block(evidence: Mapping[str, Any]) -> str:
    """The fact block for a champion or team-case envelope's `evidence`."""
    return team_case_fact_block_json(TeamCaseOut.model_validate(evidence))


def comparison_fact_block(evidence: Mapping[str, Any]) -> str:
    """The fact block for a compare envelope's `evidence`."""
    return comparison_fact_block_json(ComparisonResultOut.model_validate(evidence))


def envelope_fact_block(question_type: str, body: Mapping[str, Any]) -> str:
    """The fact block for a whole verdict response `body`, by the cache
    key's `question_type` (`champion` and `team_case` share the team-case
    shape; `compare` is the comparison)."""
    if question_type == "compare":
        return comparison_fact_block(body["evidence"])
    return team_case_fact_block(body["evidence"])
