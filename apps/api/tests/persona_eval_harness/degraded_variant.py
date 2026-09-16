"""The harness's deliberately degraded variant, for anti-vacuity (#327).

Production's persona prompt with its rules (1-5, including how typed claims
work) and its worked examples cut out. What is left is still the bar-stool
narrator (the voice and attitude paragraphs), still told it has a FACT BLOCK,
still asked for two or three sentences and for one `submit_narration` call.
A harness whose graders can't score this lower than `baseline` on both the
code graders and the model grader is not measuring anything.

It is derived from production's text rather than copied, so it tracks the
voice sections as they change. Each cut is made at an anchor that must occur
exactly once; a prompt rewrite that moves one raises `ValueError` here (and
fails the harness's offline test) instead of silently degrading something
else.
"""

from __future__ import annotations

from api.persona.prompt import build_system_prompt as build_production_prompt

_RULES_ANCHOR = " Rules, non-negotiable:"
_LENGTH_ANCHOR = "Two or three sentences."
_EXAMPLES_ANCHOR = "\n\nExample of a GOOD submission"
_CLOSING = "Answer with exactly one submit_narration call and nothing else.\n"


def _index_once(text: str, anchor: str) -> int:
    count = text.count(anchor)
    if count != 1:
        raise ValueError(
            f"the degraded variant's anchor {anchor!r} occurs {count} times in the "
            "production prompt, not once; update persona_eval_harness/degraded_variant.py"
        )
    return text.index(anchor)


def build_system_prompt(user_team: str | None) -> str:
    production = build_production_prompt(user_team)
    rules = _index_once(production, _RULES_ANCHOR)
    length = _index_once(production, _LENGTH_ANCHOR)
    examples = _index_once(production, _EXAMPLES_ANCHOR)
    if not production.endswith(_CLOSING) or not rules < length < examples:
        raise ValueError(
            "the production prompt no longer has the shape the degraded variant cuts; "
            "update persona_eval_harness/degraded_variant.py"
        )
    voice_and_fact_block = production[:rules]
    length_line = production[length:examples]
    return f"{voice_and_fact_block}\n\n{length_line}\n\n{_CLOSING}"
