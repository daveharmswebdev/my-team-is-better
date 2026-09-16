"""The model grader: one `claude-opus-5` call per narration the user saw.

**The request.** Structured outputs (`output_config.format` with a JSON
schema) whose fields come in the order the model should think in:
strengths, weaknesses, contradictions, reasoning, and only then the score. No
`temperature`, `top_p` or `top_k` (Opus 5 answers those with a 400), thinking
left at the model default, and `GRADER_MAX_TOKENS` enough for adaptive
thinking plus the JSON. No server-side model fallback: a different grader
model would make scores incomparable across runs.

**The rubric** is the product's, verbatim: the PRD's §3 "The persona"
paragraph and tone bullet, all three of §4's bullets (may, may not, and the
contested-year disclosure), the founder's "The numbers are the numbers.
This is math." (#231) and the prompt's length ask.
`tests/test_persona_eval_harness.py` checks the PRD excerpts are still in
docs/PRD.md, so a PRD edit makes that test fail rather than silently moving
what "voice" means. The grader never sees the variant's prompt: a variant is
graded against the product's rubric, not against itself.

**Ungraded is not a score.** A `stop_reason` of `refusal`, a transport
error, or output that doesn't parse into exactly the schema's shape with an
integer score from 1 to 10 is recorded as ungraded, with the reason and the
raw text, and is counted separately in the report. A transport error also
sets `Grade.transport_error`: the report counts it as a grader error, warns,
and the command exits 4 (`cli.py`).

Bump `GRADER_PROMPT_VERSION` whenever the rubric, the instructions or the
schema change: reports with different grader versions don't compare.
`grader-v2` added §4's contested-year bullet to the rubric.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

import anthropic
from anthropic.types import Message, TextBlock

GRADER_MODEL = "claude-opus-5"
GRADER_MAX_TOKENS = 16000
GRADER_PROMPT_VERSION = "grader-v2"

MIN_SCORE = 1
MAX_SCORE = 10

GRADE_FIELDS = ("strengths", "weaknesses", "contradictions", "reasoning", "score")

_STRING_LIST: dict[str, object] = {"type": "array", "items": {"type": "string"}}

# Property order is generation order. Structured outputs don't support
# numeric bounds, so the 1-10 range is stated in the description and checked
# by `parse_grade`.
GRADE_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "strengths": {
            **_STRING_LIST,
            "description": "What the narration does well against the rubric.",
        },
        "weaknesses": {
            **_STRING_LIST,
            "description": "Where the narration falls short of the rubric.",
        },
        "contradictions": {
            **_STRING_LIST,
            "description": (
                "Each statement in the narration that the fact block contradicts or does not "
                "support, quoted, with the reason. Empty when there are none."
            ),
        },
        "reasoning": {
            "type": "string",
            "description": "How the strengths, weaknesses and contradictions weigh up.",
        },
        "score": {
            "type": "integer",
            "description": f"The overall grade, an integer from {MIN_SCORE} to {MAX_SCORE}.",
        },
    },
    "required": list(GRADE_FIELDS),
    "additionalProperties": False,
}

# docs/PRD.md §3 "The persona": the paragraph and the tone bullet, verbatim.
PRD_PERSONA = """Think: the regular at the end of the bar who has an opinion on every game,
is sure his fanhood is a heavier cross to bear than yours, and will absolutely
die on a hill for his team — but is fundamentally good-natured about it, not
mean-spirited. He roots *for whichever team the user roots for* in a given
session (see §5.1) rather than having a fixed rival.

- **Tone:** PG-13 rivalry trash talk. Confident, cocky, ribbing about rival
  fanbases and heartbreak losses. No slurs, no profanity, no punching at real
  people — safe to show your mother, sharp enough to sting a rival fan."""

# docs/PRD.md §4: the may, may-not and contested-year bullets, verbatim.
PRD_MAY = """- The persona **may** be as opinionated as it wants about eye-test stuff,
  rivalries, "how it felt to watch," and — for genuinely split-decision years
  like 2003 (BCS gave it to LSU, AP voters to USC) or 2017 (Alabama won the
  CFP without a division/conference title) — it can voice the human/poll-era
  argument in character."""

PRD_MAY_NOT = """- The persona **may not** override, hedge, or "well actually" its way around
  what the algorithm says is #1, or invent a stat, score, or record that isn't
  in the computed evidence."""

PRD_CONTESTED = """- When the underlying case is one of those contested years, the UI/persona
  discloses that it's contested rather than presenting it as clean-cut."""

# The founder's rule on #231.
FOUNDER_RULE = (
    'The founder\'s rule: "The numbers are the numbers. This is math." The narrator never '
    "argues against, hedges on or relitigates who the fact block ranks #1 or rates higher. "
    "Citing a head-to-head result or a big win as something the math already counted is "
    "fine; using it as a rebuttal to the ranking is not."
)

# The persona prompt's length line.
LENGTH_ASK = 'Length: the narrator is asked for "Two or three sentences".'

GRADER_SYSTEM_PROMPT = f"""Grade one narration from a sports site's bar-stool narrator against the
product's voice rubric and the fact block it was written from, and answer in the JSON format
you have been given.

The site computes every ranking deterministically; the narrator only delivers the verdict in
character, from the fact block alone. The narration you grade is exactly what the user saw.
The user named no team of their own, so the narrator isn't expected to root for one: it
hypes whoever the fact block puts on top.

<voice_rubric>
<persona>
{PRD_PERSONA}
</persona>

<may>
{PRD_MAY}
</may>

<may_not>
{PRD_MAY_NOT}
</may_not>

<contested_years>
{PRD_CONTESTED}
</contested_years>

<founder_rule>
{FOUNDER_RULE}
</founder_rule>

<length>
{LENGTH_ASK}
</length>
</voice_rubric>

How to fill each field:
1. strengths: what the narration does well against the rubric.
2. weaknesses: where it falls short: a flat, generic or neutral voice; hedging on or arguing
   with the ranking; a contested season (<contested>true</contested>) presented as
   clean-cut; more than three sentences; meta-commentary; anything past PG-13.
3. contradictions: every statement the fact block contradicts or does not support, quoted
   from the narration, each with a short reason. For example, "split their matchups" when
   the fact block shows a tie and a win, or "sits atop the standings" for a team ranked 5,
   or a bowl, conference, venue or in-game detail the fact block does not contain. Opinion
   about how a season felt, and a contested season's human/poll-era argument voiced in
   character as the rubric allows, are not contradictions. Use an empty list when there are
   none.
4. reasoning: weigh the strengths, weaknesses and contradictions against each other.
5. score: an integer from 1 to 10 for the narration as a whole. 9-10: unmistakably this
   persona, loud and good-natured, every statement backed by the fact block, within length.
   6-8: the persona comes through, with minor lapses. 3-5: a generic or template-like voice,
   or an unsupported statement. 1-2: argues with or hedges on the ranking, invents facts, or
   breaks the tone rules.

Read the fact block as the whole truth: when the narration and the fact block disagree, the
narration is wrong."""


def grader_user_message(*, fact_block_json: str, contested: bool, narration: str) -> str:
    """The per-narration turn: the fact block, the contested flag and the
    narration, each in its own XML tag."""
    return (
        f"<fact_block>\n{fact_block_json}\n</fact_block>\n\n"
        f"<contested>{'true' if contested else 'false'}</contested>\n\n"
        f"<narration>\n{narration}\n</narration>"
    )


@dataclass(frozen=True)
class Grade:
    """One grader result. `score` is set exactly when the output parsed;
    otherwise `ungraded_reason` says why. `transport_error` is set, as
    "ExceptionType: message", exactly when the grader call itself failed
    (after the SDK's own retries), as opposed to a refusal or bad output."""

    score: int | None
    strengths: tuple[str, ...]
    weaknesses: tuple[str, ...]
    contradictions: tuple[str, ...]
    reasoning: str | None
    ungraded_reason: str | None
    stop_reason: str | None
    raw_text: str
    transport_error: str | None = None

    @property
    def graded(self) -> bool:
        return self.score is not None


def ungraded(
    reason: str,
    *,
    stop_reason: str | None = None,
    raw_text: str = "",
    transport_error: str | None = None,
) -> Grade:
    return Grade(
        score=None,
        strengths=(),
        weaknesses=(),
        contradictions=(),
        reasoning=None,
        ungraded_reason=reason,
        stop_reason=stop_reason,
        raw_text=raw_text,
        transport_error=transport_error,
    )


def _string_list(value: object) -> tuple[str, ...] | None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return None
    return tuple(value)


def parse_grade(message: Message) -> Grade:
    """The grade in `message`, or an ungraded result; never raises."""
    stop_reason = message.stop_reason
    raw_text = "".join(block.text for block in message.content if isinstance(block, TextBlock))
    if stop_reason == "refusal":
        return ungraded(
            "the grader refused (stop_reason refusal)", stop_reason=stop_reason, raw_text=raw_text
        )
    try:
        data: object = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        return ungraded(
            f"unparseable grader output: {exc} (stop_reason {stop_reason})",
            stop_reason=stop_reason,
            raw_text=raw_text,
        )
    if not isinstance(data, dict) or set(data) != set(GRADE_FIELDS):
        return ungraded(
            f"grader output is not an object with exactly the fields {list(GRADE_FIELDS)}",
            stop_reason=stop_reason,
            raw_text=raw_text,
        )
    strengths = _string_list(data["strengths"])
    weaknesses = _string_list(data["weaknesses"])
    contradictions = _string_list(data["contradictions"])
    reasoning = data["reasoning"]
    score = data["score"]
    if strengths is None or weaknesses is None or contradictions is None:
        return ungraded(
            "grader output lists are not lists of strings",
            stop_reason=stop_reason,
            raw_text=raw_text,
        )
    if not isinstance(reasoning, str):
        return ungraded(
            "grader reasoning is not a string", stop_reason=stop_reason, raw_text=raw_text
        )
    if isinstance(score, bool) or not isinstance(score, int) or not MIN_SCORE <= score <= MAX_SCORE:
        return ungraded(
            f"grader score {score!r} is not an integer from {MIN_SCORE} to {MAX_SCORE}",
            stop_reason=stop_reason,
            raw_text=raw_text,
        )
    return Grade(
        score=score,
        strengths=strengths,
        weaknesses=weaknesses,
        contradictions=contradictions,
        reasoning=reasoning,
        ungraded_reason=None,
        stop_reason=stop_reason,
        raw_text=raw_text,
    )


class Grader(Protocol):
    def grade(self, *, fact_block_json: str, contested: bool, narration: str) -> Grade: ...


class ModelGrader:
    """The real grader. The client resolves `ANTHROPIC_API_KEY` from the
    environment the normal way, as `ClaudeNarrator` does."""

    def __init__(self, client: anthropic.Anthropic | None = None) -> None:
        self._client = client or anthropic.Anthropic()

    def grade(self, *, fact_block_json: str, contested: bool, narration: str) -> Grade:
        try:
            message = self._client.messages.create(
                model=GRADER_MODEL,
                max_tokens=GRADER_MAX_TOKENS,
                system=GRADER_SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": grader_user_message(
                            fact_block_json=fact_block_json,
                            contested=contested,
                            narration=narration,
                        ),
                    }
                ],
                output_config={"format": {"type": "json_schema", "schema": GRADE_SCHEMA}},
            )
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
            error = f"{type(exc).__name__}: {exc}"
            return ungraded(f"grader call failed: {error}", transport_error=error)
        return parse_grade(message)
