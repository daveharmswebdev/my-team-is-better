"""The persona smoke eval's judge, properties and measurements (issue #293).

Shared by `tests/test_persona_smoke_eval.py` (the live, key-gated §8 eval),
its offline unit tests in `tests/test_persona_smoke_eval_checks.py`, and the
scored eval harness that follows (#327). Pure: no network, no database, no
pytest. The catalog and fact blocks are passed in; `RecordingNarrator` only
wraps whatever narrator it is given. Not part of the pytest suite itself
(doesn't match `test_*.py`).

**Judging with the production validator.** Since #291 the narrator answers
with one `submit_narration` tool call, and production serves only
`api.persona.claims.check_and_render`'s rendering of a valid one. The eval
used to carry its own grounding checker, which disagreed with production in
both directions (#293). Now `judge_narration` re-runs `check_and_render` over
every recorded call, against the fact block that call actually carried and the
sport's catalog, and requires the served text to be exactly the rendering of a
valid call (§8 property 2), never the fallback and never text it can't trace
to a recorded valid call (property 5). A valid call before the served one is
flagged too: production would have served it, so the re-check disagrees with
production.

**Why that can't go vacuous unnoticed.** Reusing the production validator
means a validator that stops rejecting things would stop the eval seeing
anything. So every live test first runs the same judge on a planted invalid
submission for its own fact block (`judge_planted_invalid`: the subject team
and a typed record, no claims) and asserts it is rejected. A judge that skips
the validator, or a validator that stops rejecting typed numbers, fails that
canary before any Claude call is spent. Evading it means editing the canary or
the test code that asserts on it, both visible in a diff.

**Measurements that never block** (founder decision C on #199), printed per
narration by `format_record` and as rates by `format_summary`:

(a) `timing_venue_flags`: when/where wording the narrator typed itself, over
    the raw tool-call text with every `{placeholder}` removed, so the phrases
    `when`/`where` claims render ("in the postseason", "to open the season",
    "in week 11", "at a neutral site") never count. A false positive costs
    nothing; the list errs wide.
(b) `ambiguous_when_sentences`: a raw sentence holding a `when` or `where`
    placeholder and game_score placeholders for two or more different games,
    so the when reads as covering both.
(c) served narrations over the prompt's "Two or three sentences"
    (`PROMPT_MAX_SENTENCES`), separate from property 3's blocking bound.
(d) `is_lowercase_block_team_error`: a rejection for a lowercase spelling of
    a block team ("rice" for Rice), the validator's known false positive.
(e) served first / retry / fallback counts and total Claude calls.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from anthropic.types import MessageParam

from api.persona.claims import TOOL_NAME, check_and_render
from api.persona.claude_client import Narrator, NarratorReply
from api.persona.prompt import build_user_message
from api.repositories.teams import TeamRecord

# ---------------------------------------------------------------------------
# bounds
# ---------------------------------------------------------------------------

# Property 3. The prompt asks for "Two or three sentences". 1-4 allows one
# either side of that for a model that folds two thoughts into one sentence or
# adds a short kicker, without letting a paragraph-length answer through. 700
# characters: the validator's hand run on #109 measured 245-523 characters
# across the seven golden years, so 700 is that ceiling plus about a third of
# headroom, and is still well under what four long sentences would take.
MIN_SENTENCES = 1
MAX_SENTENCES = 4
MAX_CHARACTERS = 700

# Measurement (c): the prompt's own "Two or three sentences".
PROMPT_MAX_SENTENCES = 3

ServedBy = Literal["first", "retry", "fallback", "untraceable"]

_PLACEHOLDER_RE = re.compile(r"\{[A-Za-z][A-Za-z0-9_]*\}")
_PLACEHOLDER_ID_RE = re.compile(r"\{([A-Za-z][A-Za-z0-9_]*)\}")

# ---------------------------------------------------------------------------
# recording
# ---------------------------------------------------------------------------

_FACT_BLOCK_HEADER = "FACT BLOCK (JSON):\n"


def fact_block_from_user_turn(user_turn: str) -> str:
    """The fact block inside `api.persona.prompt.build_user_message`'s turn.

    Accepted only when rebuilding the turn from the extracted block gives the
    same string back, so a change to the turn's shape raises `ValueError`
    instead of silently judging against the wrong text."""
    if user_turn.startswith(_FACT_BLOCK_HEADER):
        for contested in (False, True):
            suffix = f"\n\ncontested: {'true' if contested else 'false'}"
            if user_turn.endswith(suffix):
                block = user_turn[len(_FACT_BLOCK_HEADER) : -len(suffix)]
                if build_user_message(block, contested=contested) == user_turn:
                    return block
    raise ValueError(f"not a FACT BLOCK user turn: {user_turn[:80]!r}")


@dataclass(frozen=True)
class RecordedCall:
    """One narrator call: the raw `submit_narration` input (`None` when no
    tool call came back), the fact block the call carried, and the stop
    reason."""

    tool_input: object | None
    fact_block_json: str
    stop_reason: str | None = None

    @property
    def raw_text(self) -> str | None:
        """The narrator's own `text`, placeholders and all, when there is one."""
        if not isinstance(self.tool_input, dict):
            return None
        text = self.tool_input.get("text")
        return text if isinstance(text, str) else None


class RecordingNarrator:
    """A pass-through around any `Narrator` that records every call's messages
    and reply, without touching production code. A call that raises (a
    transport error, which production answers with the fallback) is not
    recorded. `recorded_calls` reads the fact block out of each call's first
    user turn afterwards, so a turn of an unexpected shape fails the test that
    judges it rather than the request."""

    def __init__(self, inner: Narrator) -> None:
        self._inner = inner
        self.messages: list[list[MessageParam]] = []
        self.replies: list[NarratorReply] = []

    def submit(self, *, system: str, messages: list[MessageParam]) -> NarratorReply:
        sent = list(messages)
        reply = self._inner.submit(system=system, messages=messages)
        self.messages.append(sent)
        self.replies.append(reply)
        return reply

    def recorded_calls(self) -> tuple[RecordedCall, ...]:
        calls: list[RecordedCall] = []
        for messages, reply in zip(self.messages, self.replies, strict=True):
            first = messages[0]["content"]
            if not isinstance(first, str):
                raise ValueError(f"the first user turn is not text: {first!r}")
            calls.append(
                RecordedCall(
                    tool_input=None if reply.tool_call is None else reply.tool_call.input,
                    fact_block_json=fact_block_from_user_turn(first),
                    stop_reason=reply.stop_reason,
                )
            )
        return tuple(calls)


# ---------------------------------------------------------------------------
# the judge: properties 2 and 5
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class JudgedCall:
    """A recorded call re-checked by the production validator: `text` is its
    rendering when, and only when, `errors` is empty."""

    call: RecordedCall
    errors: tuple[str, ...]
    text: str | None

    @property
    def valid(self) -> bool:
        return self.text is not None and not self.errors


@dataclass(frozen=True)
class Judgement:
    """What `judge_narration` found. `served_attempt` is the valid call whose
    rendering is the served text; `violations` are §8 properties 2 and 5,
    labelled "grounded:" and "not-fallback:"."""

    served_text: str
    attempts: tuple[JudgedCall, ...]
    served_by: ServedBy
    served_attempt: JudgedCall | None
    violations: tuple[str, ...]


def judge_call(call: RecordedCall, catalog: Sequence[TeamRecord]) -> JudgedCall:
    """`check_and_render` on one recorded call; no tool call is a rejection,
    worded as production words it."""
    if call.tool_input is None:
        error = f"no {TOOL_NAME} call came back (stop reason: {call.stop_reason})"
        return JudgedCall(call=call, errors=(error,), text=None)
    outcome = check_and_render(call.tool_input, call.fact_block_json, catalog)
    return JudgedCall(call=call, errors=outcome.errors, text=outcome.text)


def _attempt_line(number: int, attempt: JudgedCall) -> str:
    if attempt.valid:
        return f"call {number}: valid, renders {attempt.text!r}"
    shown = "; ".join(attempt.errors[:3])
    more = f" (+{len(attempt.errors) - 3} more)" if len(attempt.errors) > 3 else ""
    return f"call {number}: rejected, {len(attempt.errors)} error(s): {shown}{more}"


def judge_narration(
    *,
    served_text: str,
    calls: Sequence[RecordedCall],
    catalog: Sequence[TeamRecord],
    fallback_text: str,
) -> Judgement:
    """§8 properties 2 and 5 for one served narration.

    2. **grounded**: a recorded call re-checks valid and renders exactly
       `served_text`, and no earlier call re-checks valid (production serves
       the first valid call and makes no further one).
    5. **not-fallback**: `served_text` is not `fallback_text`, and it traces
       to that recorded valid call.
    """
    attempts = tuple(judge_call(call, catalog) for call in calls)
    served_index = next(
        (i for i, attempt in enumerate(attempts) if attempt.valid and attempt.text == served_text),
        None,
    )
    is_fallback = served_text == fallback_text
    trail = "; ".join(_attempt_line(i + 1, attempt) for i, attempt in enumerate(attempts))
    violations: list[str] = []

    if not attempts:
        violations.append("grounded: the narrator was never called")
    elif served_index is None:
        violations.append(
            "grounded: no recorded submit_narration call re-checks valid with a rendering "
            f"equal to the served text ({trail})"
        )
    else:
        earlier = [i + 1 for i, attempt in enumerate(attempts[:served_index]) if attempt.valid]
        if earlier:
            violations.append(
                f"grounded: call {earlier[0]} re-checks valid, but production went on to call "
                f"{served_index + 1}; the eval's re-check disagrees with production's ({trail})"
            )

    if is_fallback:
        violations.append(
            "not-fallback: the served text is the templated fallback "
            f"(claude_calls={len(attempts)})"
        )
    elif served_index is None:
        violations.append(
            "not-fallback: the served text can't be traced to a recorded valid call "
            f"(matches fallback: False). Served text: {served_text!r}"
        )

    served_by: ServedBy
    if is_fallback:
        served_by = "fallback"
    elif served_index is None:
        served_by = "untraceable"
    else:
        served_by = "first" if served_index == 0 else "retry"
    return Judgement(
        served_text=served_text,
        attempts=attempts,
        served_by=served_by,
        served_attempt=None if served_index is None else attempts[served_index],
        violations=tuple(violations),
    )


def _subject_team(fact_block_json: str) -> str:
    data = json.loads(fact_block_json)
    if "team_a" in data:
        return str(data["team_a"]["team_name"])
    return str(data["team_name"])


def planted_invalid_call(fact_block_json: str) -> RecordedCall:
    """A submission production must reject on any fact block: the subject team
    and a typed record, with no claims. Rejected only for the typed number,
    true or not, so it tracks the rule that keeps figures out of the prose."""
    text = f"{_subject_team(fact_block_json)} went 13-0 and nobody came close."
    return RecordedCall(
        tool_input={"text": text, "claims": []},
        fact_block_json=fact_block_json,
        stop_reason="tool_use",
    )


def judge_planted_invalid(
    fact_block_json: str, catalog: Sequence[TeamRecord], *, fallback_text: str
) -> Judgement:
    """The judge on `planted_invalid_call`, served as its own raw text. Its
    violations must not be empty; if they are, the judge has gone vacuous."""
    call = planted_invalid_call(fact_block_json)
    return judge_narration(
        served_text=call.raw_text or "",
        calls=[call],
        catalog=catalog,
        fallback_text=fallback_text,
    )


# ---------------------------------------------------------------------------
# property 1: the right team named
# ---------------------------------------------------------------------------


def team_mention_pattern(catalog_names: Sequence[str]) -> re.Pattern[str]:
    """One alternation over every catalog name, longest names first, bounded
    by non-word characters on both sides, matched case-sensitively.

    - **Longest first** makes each match leftmost-longest, so "Texas Tech" is
      consumed whole and never also reported as "Texas", and "Miami (OH)" is
      never reported as "Miami".
    - **Word bounds** stop "Concord" matching inside "Concordia", while still
      allowing a possessive ("LSU's") or trailing punctuation ("USC!").
    - **Case-sensitive**, because several catalog names are ordinary words
      ("Liberty", "Temple").
    """
    ordered = sorted({name for name in catalog_names if name}, key=len, reverse=True)
    alternation = "|".join(re.escape(name) for name in ordered)
    return re.compile(rf"(?<!\w)(?:{alternation})(?!\w)")


def team_mentions(pattern: re.Pattern[str], text: str) -> set[str]:
    return {match.group(0) for match in pattern.finditer(text)}


def named_team_violations(text: str, team_name: str, catalog_names: Sequence[str]) -> list[str]:
    """Property 1's narration half: `text` names `team_name` as itself, not
    only inside a longer catalog name."""
    mentions = team_mentions(team_mention_pattern(catalog_names), text)
    if team_name in mentions:
        return []
    return [
        f"correct-#1: narration does not name {team_name!r} (team mentions found: "
        f"{sorted(mentions)})"
    ]


# ---------------------------------------------------------------------------
# property 3: length
# ---------------------------------------------------------------------------

# A candidate sentence break: . ! or ?, optionally followed by closing
# quotes/parens, then whitespace, then a capital letter (optionally behind an
# opening quote). Requiring the capital keeps a mid-sentence exclamation like
# "USC -- USC! -- 41-38" as one sentence, and never splits before a digit, so
# "No. 1" and "... 13-0" never start a new sentence. A real sentence that
# starts with a digit is merged with the one before: an undercount, never an
# overcount, and the 700-character cap still bounds the length.
_SENTENCE_BREAK_RE = re.compile("[.!?]+[\"'”’)]*\\s+(?=[\"'“‘(]*[A-Z])")

# A "." after one of these is an abbreviation, not the end of a sentence
# ("vs. USC", "St. John's", "U.S. Bank Stadium").
_ABBREVIATIONS = frozenset({"no", "vs", "st", "jr", "sr", "mt", "ft", "dr", "mr", "mrs", "u.s"})
_WORD_BEFORE_RE = re.compile(r"[A-Za-z][A-Za-z.]*$")


def sentence_count(text: str) -> int:
    stripped = text.strip()
    if not stripped:
        return 0
    count = 1
    for match in _SENTENCE_BREAK_RE.finditer(stripped):
        if stripped[match.start()] == ".":
            word = _WORD_BEFORE_RE.search(stripped, 0, match.start())
            if word is not None and word.group(0).lower() in _ABBREVIATIONS:
                continue
        count += 1
    return count


def length_violations(text: str) -> list[str]:
    violations: list[str] = []
    sentences = sentence_count(text)
    if not MIN_SENTENCES <= sentences <= MAX_SENTENCES:
        violations.append(f"length: {sentences} sentences, want {MIN_SENTENCES}-{MAX_SENTENCES}")
    if len(text) > MAX_CHARACTERS:
        violations.append(f"length: {len(text)} characters, want <= {MAX_CHARACTERS}")
    return violations


# ---------------------------------------------------------------------------
# property 4: banned words
# ---------------------------------------------------------------------------

# Profanity and slurs, as exact word forms (no open-ended stems), so a word
# that merely starts with one ("cocky", which the prompt asks for,
# "Scunthorpe", "Spicer", "Hancock") never hits. Short by design: a smoke check
# that the prompt's "no slurs, no profanity" rule still binds, not a content
# filter. Mild PG-13 words the prompt allows ("hell of a season", "damn") are
# deliberately out. No catalog team name hits (checked offline).
_PROFANITY_AND_SLURS_RE = re.compile(
    r"\b(?:"
    r"(?:mother)?fuck(?:s|ed|er|ers|ing|in)?|bullshit|shit(?:s|ty|ting|ted)?"
    r"|bitch(?:es|ing|y)?|cunts?|assholes?|bastards?"
    r"|fags?|faggots?|retards?|retarded|niggers?|niggas?|spics?|trann(?:y|ies)|wetbacks?"
    r")\b",
    re.IGNORECASE,
)

# Slur forms that are also real names -- "Dykes" (Sonny Dykes, a college
# coach) and "Kike" (a common Spanish nickname) -- match only in lowercase,
# where they cannot be a proper noun. The chosen trade-off: a capitalised
# slur of this kind at the start of a sentence is missed rather than flagging
# a real name.
_NAME_HOMOGRAPH_SLURS_RE = re.compile(r"\b(?:dykes?|kikes?)\b")

# Real AI disclaimers the prompt forbids ("no meta-commentary about being an
# AI"), not bar talk: "I cannot believe Texas went 13-0" must not hit. Both
# apostrophe forms, since the model sometimes writes a curly one.
_AI_META_RE = re.compile(
    r"\bas an AI\b|\blanguage model\b|\bI(?:'|’)m (?:just )?an AI\b|\bI am (?:just )?an AI\b"
    r"|\bI cannot (?:help|assist|provide|comply)\b|\bI(?:'|’)m not able to\b|\bI am not able to\b",
    re.IGNORECASE,
)


def banned_hits(text: str) -> list[str]:
    return [
        match.group(0)
        for pattern in (_PROFANITY_AND_SLURS_RE, _NAME_HOMOGRAPH_SLURS_RE, _AI_META_RE)
        for match in pattern.finditer(text)
    ]


# ---------------------------------------------------------------------------
# all five properties
# ---------------------------------------------------------------------------


def section_8_violations(
    *,
    served_text: str,
    expected_team: str,
    evidence_team: str,
    catalog_names: Sequence[str],
    judgement: Judgement,
) -> tuple[str, ...]:
    """Every §8 property the served narration violates, empty when it passes.
    All are evaluated and reported together, so a red run says which broke.
    Measurements are never part of this."""
    violations: list[str] = []
    # 1. the right team: the evidence names it, and so does the narration
    if evidence_team != expected_team:
        violations.append(
            f"correct-#1: evidence team is {evidence_team!r}, expected {expected_team!r}"
        )
    violations += named_team_violations(served_text, expected_team, catalog_names)
    # 2 and 5. grounded by the production validator; served by the narrator
    violations += judgement.violations
    # 3. length bounded
    violations += length_violations(served_text)
    # 4. no banned-word hits
    hits = banned_hits(served_text)
    if hits:
        violations.append(f"banned-words: {hits}")
    return tuple(violations)


# Reported, never asserted: whether a contested year's narration says so in
# character. Wording varies too much to assert on.
_CONTESTED_DISCLOSURE_RE = re.compile(
    r"\bpolls?\b|\bcontested\b|\bdebat\w*|\bargu\w*|\bcontrovers\w*|\bsplit\b"
    r"|\bdisagree\w*|\bvoters?\b|\bhumans?\b|\bBCS\b|\bAP\b|\bcoaches\b|\bsaw it\b",
    re.IGNORECASE,
)


def contested_disclosure_words(text: str) -> list[str]:
    return sorted({match.group(0).lower() for match in _CONTESTED_DISCLOSURE_RE.finditer(text)})


# ---------------------------------------------------------------------------
# measurement (a): when/where wording typed by the narrator
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TimingVenueFlag:
    kind: Literal["timing", "venue"]
    phrase: str


_MONTHS = "august|september|october|november|december|january"

# Case-insensitive. Deliberately wide: this is a measurement, a false positive
# costs nothing, and a miss on a known phrase is what matters (#293).
_TIMING_PATTERNS: tuple[str, ...] = (
    r"\bopen(?:ed|er|ers|ing)\b",
    r"\bto (?:start|open|close|end|finish|begin|kick off|wrap up|cap off|cap|round out)"
    r"(?: (?:the|their|its|his|that|a))? (?:regular season|season|year|campaign|schedule|run)\b",
    r"\bcap(?:ped|ping)\b|\bto cap\b|\bcaps? (?:it|off|things)\b",
    r"\bfinale\b",
    r"\bthen\b",
    r"\bweek(?:s|end|ends)?\b",
    r"\bbowls?\b",
    r"\bpost-?season\b",
    r"\bregular[- ]season\b",
    r"\bplayoffs?\b",
    r"\b(?:championship|title) game\b",
    r"\bdown the stretch\b",
    r"\b(?:early|late|later|earlier|mid)(?: on)? in the (?:season|year|schedule)\b",
    r"\b(?:early|late|mid)[- ]season\b",
    r"\bseason[- ](?:ending|ender)\b",
    r"\b(?:first|last|final|opening|closing) (?:game|games|week|weekend|test|matchup|stretch)\b",
    r"\b(?:everybody|everyone|everything) else\b",
    r"\bafter(?:wards?| that| this)\b",
    r"\bfrom there\b",
    r"\bbefore (?:that|this)\b",
    r"\bthe rest of the (?:way|season|year|schedule)\b",
    r"\bhomecoming\b",
    r"\bthanksgiving\b|\bnew year'?s\b|\bsaturday\b",
    rf"\b(?:{_MONTHS})\b",
)

# Case-insensitive, except `_AT_CAPITALIZED`.
_VENUE_PATTERNS: tuple[str, ...] = (
    r"\bterritory\b",
    r"\bon the road\b",
    r"\bat home\b",
    r"\broad (?:win|wins|loss|losses|game|games|victory|trip|test|upset|record)\b",
    r"\bhome (?:win|wins|loss|losses|game|games|crowd|field|turf|stadium|opener|record)\b",
    r"\bneutral[- ](?:site|field|ground)\b",
    r"\bstadium\b",
    r"(?:\b(?:their|his|its|your|our)|['’]s) (?:own )?"
    r"(?:house|building|backyard|yard|turf|den|barn)\b",
    r"\b(?:hostile|enemy|foreign) (?:territory|turf|ground|soil|crowd|environment)\b",
    r"\baway (?:game|games|from home|win|wins|loss|losses)\b",
    r"\btrip to\b",
    r"\bvisit(?:ed|ing|or|ors)?\b",
    r"\bin front of\b",
    r"\bcrowd\b",
)

# "at <Capitalized word>": "at Clemson", "at the Swamp". Case-sensitive, so
# "look at that" is prose.
_AT_CAPITALIZED = r"\b[Aa]t\s+(?:the\s+)?[A-Z][\w'’&.-]*"

_DETECTORS: tuple[tuple[Literal["timing", "venue"], re.Pattern[str]], ...] = (
    *(("timing", re.compile(pattern, re.IGNORECASE)) for pattern in _TIMING_PATTERNS),
    *(("venue", re.compile(pattern, re.IGNORECASE)) for pattern in _VENUE_PATTERNS),
    ("venue", re.compile(_AT_CAPITALIZED)),
)


def strip_placeholders(raw_text: str) -> str:
    """`raw_text` with every `{id}` placeholder removed."""
    return _PLACEHOLDER_RE.sub("", raw_text)


def timing_venue_flags(raw_text: str) -> tuple[TimingVenueFlag, ...]:
    """Timing and venue wording in the narrator's own words: every detector
    match over `raw_text` with its placeholders removed, in text order.
    Overlapping matches count once, as the leftmost (then longest)."""
    text = strip_placeholders(raw_text)
    matches = sorted(
        (
            (match.start(), -(match.end() - match.start()), kind, match.group(0))
            for kind, pattern in _DETECTORS
            for match in pattern.finditer(text)
        ),
    )
    flags: list[TimingVenueFlag] = []
    covered_to = 0
    for start, negative_length, kind, phrase in matches:
        if start < covered_to:
            continue
        flags.append(TimingVenueFlag(kind=kind, phrase=" ".join(phrase.split())))
        covered_to = start - negative_length
    return tuple(flags)


# ---------------------------------------------------------------------------
# measurement (b): a when/where that reads as covering two games
# ---------------------------------------------------------------------------

_RAW_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _game_key(claim: Mapping[object, object]) -> tuple[str, ...]:
    teams = sorted((repr(claim.get("team")), repr(claim.get("opponent"))))
    return (*teams, repr(claim.get("week")), repr(claim.get("season_type")))


def ambiguous_when_sentences(tool_input: object) -> tuple[str, ...]:
    """Each sentence of the raw `text` holding a `when` or `where` placeholder
    and game_score placeholders for two or more different games ("They took
    down Clemson {g1} and Auburn {g2} {w1}"). Malformed input gives ()."""
    if not isinstance(tool_input, dict):
        return ()
    text, claims = tool_input.get("text"), tool_input.get("claims")
    if not isinstance(text, str) or not isinstance(claims, list):
        return ()
    by_id: dict[str, Mapping[object, object]] = {}
    for claim in claims:
        if isinstance(claim, dict) and isinstance(claim.get("id"), str):
            by_id.setdefault(claim["id"], claim)
    flagged: list[str] = []
    for sentence in _RAW_SENTENCE_SPLIT_RE.split(text.strip()):
        used = [by_id[i] for i in _PLACEHOLDER_ID_RE.findall(sentence) if i in by_id]
        when_or_where = any(claim.get("kind") in ("when", "where") for claim in used)
        games = {_game_key(claim) for claim in used if claim.get("kind") == "game_score"}
        if when_or_where and len(games) >= 2:
            flagged.append(sentence)
    return tuple(flagged)


# ---------------------------------------------------------------------------
# measurement (d): the lowercase block-team false positive
# ---------------------------------------------------------------------------

# `api.persona.claims` builds this error as
# f"{_quote(found)} must be written exactly as the fact block spells it: {_quote(spelled)}".
_SPELLING_ERROR_RE = re.compile(
    r'"(?P<found>.+)" must be written exactly as the fact block spells it: "(?P<spelled>.+)"',
    re.DOTALL,
)


def is_lowercase_block_team_error(error: str) -> bool:
    """A spelling rejection whose typed form is all lowercase ("rice" for Rice)."""
    match = _SPELLING_ERROR_RE.fullmatch(error)
    if match is None:
        return False
    found = match.group("found")
    return found == found.lower() and found != found.upper()


# ---------------------------------------------------------------------------
# the per-narration record and the run summary
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NarrationRecord:
    """One narration's judgement and measurements. The detectors read the
    served call's raw text, so a fallback or untraceable narration has none."""

    label: str
    judgement: Judgement
    sentences: int
    timing_venue: tuple[TimingVenueFlag, ...]
    ambiguous_when: tuple[str, ...]
    lowercase_rejections: int

    @property
    def served_by(self) -> ServedBy:
        return self.judgement.served_by

    @property
    def claude_calls(self) -> int:
        return len(self.judgement.attempts)

    @property
    def narrator_served(self) -> bool:
        return self.served_by in ("first", "retry")

    @property
    def over_prompt_length(self) -> bool:
        return self.narrator_served and self.sentences > PROMPT_MAX_SENTENCES


def build_record(label: str, judgement: Judgement) -> NarrationRecord:
    served = judgement.served_attempt
    raw = None if served is None else served.call.raw_text
    return NarrationRecord(
        label=label,
        judgement=judgement,
        sentences=sentence_count(judgement.served_text),
        timing_venue=() if raw is None else timing_venue_flags(raw),
        ambiguous_when=() if served is None else ambiguous_when_sentences(served.call.tool_input),
        lowercase_rejections=sum(
            1
            for attempt in judgement.attempts
            if any(is_lowercase_block_team_error(error) for error in attempt.errors)
        ),
    )


def rate(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


@dataclass(frozen=True)
class EvalSummary:
    """Counts over one run. Rates over narrations the narrator served
    (timing/venue, ambiguous when, length), over all attempts (lowercase
    rejections), or over all narrations (first try, fallback)."""

    narrations: int
    served_first: int
    served_retry: int
    served_fallback: int
    served_untraceable: int
    claude_calls: int
    narrator_served: int
    timing_venue_narrations: int
    timing_flags: int
    venue_flags: int
    ambiguous_when_narrations: int
    over_prompt_length: int
    lowercase_rejections: int

    @property
    def timing_venue_rate(self) -> float | None:
        return rate(self.timing_venue_narrations, self.narrator_served)

    @property
    def ambiguous_when_rate(self) -> float | None:
        return rate(self.ambiguous_when_narrations, self.narrator_served)

    @property
    def over_prompt_length_rate(self) -> float | None:
        return rate(self.over_prompt_length, self.narrator_served)

    @property
    def lowercase_rejection_rate(self) -> float | None:
        return rate(self.lowercase_rejections, self.claude_calls)

    @property
    def fallback_rate(self) -> float | None:
        return rate(self.served_fallback, self.narrations)

    @property
    def first_try_rate(self) -> float | None:
        return rate(self.served_first, self.narrations)


def summarize(records: Sequence[NarrationRecord]) -> EvalSummary:
    served = [record for record in records if record.narrator_served]
    flags = [flag for record in served for flag in record.timing_venue]
    return EvalSummary(
        narrations=len(records),
        served_first=sum(1 for record in records if record.served_by == "first"),
        served_retry=sum(1 for record in records if record.served_by == "retry"),
        served_fallback=sum(1 for record in records if record.served_by == "fallback"),
        served_untraceable=sum(1 for record in records if record.served_by == "untraceable"),
        claude_calls=sum(record.claude_calls for record in records),
        narrator_served=len(served),
        timing_venue_narrations=sum(1 for record in served if record.timing_venue),
        timing_flags=sum(1 for flag in flags if flag.kind == "timing"),
        venue_flags=sum(1 for flag in flags if flag.kind == "venue"),
        ambiguous_when_narrations=sum(1 for record in served if record.ambiguous_when),
        over_prompt_length=sum(1 for record in served if record.over_prompt_length),
        lowercase_rejections=sum(record.lowercase_rejections for record in records),
    )


def _ratio(numerator: int, denominator: int) -> str:
    value = rate(numerator, denominator)
    shown = "n/a" if value is None else f"{value:.0%}"
    return f"{numerator}/{denominator} ({shown})"


def format_record(record: NarrationRecord) -> str:
    """The per-narration lines: served_by, counts, measurements, the served
    text, the served call's raw text, and each rejected attempt's errors."""
    flags = [f"{flag.kind}:{flag.phrase!r}" for flag in record.timing_venue]
    lines = [
        f"[persona-eval] {record.label} served={record.served_by} "
        f"claude_calls={record.claude_calls} chars={len(record.judgement.served_text)} "
        f"sentences={record.sentences} timing_venue={flags or 'none'} "
        f"ambiguous_when={len(record.ambiguous_when)} "
        f"lowercase_team_rejections={record.lowercase_rejections}",
        f"[persona-eval] {record.label} text: {record.judgement.served_text}",
    ]
    served = record.judgement.served_attempt
    if served is not None:
        lines.append(f"[persona-eval] {record.label} raw: {served.call.raw_text}")
    for sentence in record.ambiguous_when:
        lines.append(f"[persona-eval] {record.label} ambiguous when: {sentence}")
    for number, attempt in enumerate(record.judgement.attempts, start=1):
        if not attempt.valid:
            lines.append(f"[persona-eval] {record.label} {_attempt_line(number, attempt)}")
    return "\n".join(lines)


def format_summary(summary: EvalSummary, *, prompt_version: str, grounding_version: str) -> str:
    """One line of counts and rates for the run, with both versions."""
    return (
        f"[persona-eval] summary prompt={prompt_version} grounding={grounding_version} "
        f"narrations={summary.narrations} first={summary.served_first} "
        f"retry={summary.served_retry} fallback={summary.served_fallback} "
        f"untraceable={summary.served_untraceable} claude_calls={summary.claude_calls} | "
        f"timing/venue narrations "
        f"{_ratio(summary.timing_venue_narrations, summary.narrator_served)}, flags "
        f"timing={summary.timing_flags} venue={summary.venue_flags} | ambiguous when "
        f"{_ratio(summary.ambiguous_when_narrations, summary.narrator_served)} | over "
        f"{PROMPT_MAX_SENTENCES} sentences "
        f"{_ratio(summary.over_prompt_length, summary.narrator_served)} | lowercase "
        f"block-team rejections {_ratio(summary.lowercase_rejections, summary.claude_calls)} "
        f"of attempts"
    )
