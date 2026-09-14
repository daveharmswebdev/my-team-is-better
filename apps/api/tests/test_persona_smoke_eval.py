"""Architecture Brief §8's persona smoke eval, as a test (issue #109).

For each of the seven CFB golden years this posts `POST /api/verdict/champion
{"year": Y}` through the real app, with:

- the **production narrator**, resolved by calling `api.deps.get_narrator()`
  itself (so a `ClaudeNarrator` calling the real `claude-haiku-4-5`), wrapped
  only in a pass-through recorder that records every call and output;
- the committed seven-year fixture db and an `InMemoryNarrationCache`, both
  from the shared `client` fixture (tests/conftest.py).

It then asserts §8's four properties plus one anti-vacuity check, per year:

1. **Correct #1 named.** The response evidence's `team_name` is the known
   Keener #1 for the year, and it is one of the team mentions the catalog
   scanner finds in the narration (leftmost-longest, so "Texas Tech" never
   counts as naming "Texas").
2. **Grounded, checked independently of `api.persona.grounding`.** Three
   checks, all this module's own code:
   - every number token is in the fact block verbatim, or is a
     `rating`/`opponent_rating` from it rounded (#162) or rendered the way the
     site displays it (#165), with the display scale read as data from
     `api.rating_display.RATING_DISPLAY`;
   - every catalog team mentioned is one the fact block mentions;
   - every hyphen-joined pair is a game score the fact block states (in either
     order) or, in its stated order, a W-L or W-L-T record the fact block
     states, so "went 99-0" and a reversed "went 0-13" are both caught.
   These checks do not tie a score or record to the team or game it is said
   about. That relational rule (#26, and #166 for records) is production's,
   and a real score credited to the wrong opponent passes here. Reusing
   `find_ungrounded_tokens` instead would make the eval vacuous against the
   regression it exists to catch: a grounding layer that stops rejecting
   anything also stops the eval from seeing anything.
3. **Length bounded.** 1-4 sentences, at most 700 characters.
4. **No banned-word hits.** Profanity and slurs as exact word forms, plus real
   AI disclaimers.
5. **Served by the narrator, not the fallback.** The served text must be one
   of the narrator's recorded outputs. That is structural, so a fallback that
   drifts from `team_case_fallback_text` cannot slip past it. The fallback
   always names the right team and is always grounded, so without this check
   a persona that never gets a line past grounding would pass 1-4.

The check functions are unit-tested offline, in CI, by
`tests/test_persona_smoke_eval_checks.py`.

**Key.** Gated on `ANTHROPIC_API_KEY` alone, as `api.config` resolves it: from
the environment, or through `load_dotenv` from `apps/api/.env` (or the file
named by `MY_TEAM_IS_BETTER_API_ENV_FILE`), which never overrides a variable
already set. CI has no such secret by decision, so the CI step reports this
test skipped.

**Postgres.** `api.main` imports `DATABASE_URL`, and its lifespan connects to
Postgres when it is set. This eval does not reach Postgres, for two reasons:
the `client` fixture overrides the narration cache with an
`InMemoryNarrationCache`, and the `TestClient` is not used as a context
manager, so the lifespan never runs. Keep `DATABASE_URL` unset anyway. Run it
from `apps/api` with the key exported and `-s` to see the per-year summary:

    env -u DATABASE_URL -u MY_TEAM_IS_BETTER_API_ENV_FILE \\
        uv run pytest -q -rs -s tests/test_persona_smoke_eval.py
"""

from __future__ import annotations

import json
import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.config import ANTHROPIC_API_KEY
from api.deps import get_narrator
from api.main import app
from api.models import TeamCaseOut
from api.persona.claude_client import MODEL, ClaudeNarrator, Narrator
from api.persona.fallback import team_case_fallback_text
from api.persona.prompt import build_user_message
from api.persona.service import team_case_fact_block_json
from api.rating_display import RATING_DISPLAY

# The Keener #1 per golden year, as the PRD's golden dataset and the fixture
# db both have it (2003 and 2017 are the contested seasons).
EXPECTED_KEENER_NUMBER_ONE: dict[int, str] = {
    2001: "Miami",
    2003: "LSU",
    2004: "USC",
    2005: "Texas",
    2013: "Florida State",
    2017: "Alabama",
    2019: "LSU",
}

# `api.config.CONTESTED_YEARS`, restated rather than imported so a change to
# that set shows up here as a red eval instead of silently moving the target.
# CFB-only on purpose: `is_contested` ignores sport (#151).
EXPECTED_CONTESTED_YEARS = {2003, 2017}

# The prompt asks for "Two or three sentences". 1-4 allows one either side
# of that for a model that folds two thoughts into one sentence or adds a
# short kicker, without letting a paragraph-length answer through. 700
# characters: the validator's hand run on #109 measured 245-523 characters
# across the same seven years, so 700 is that ceiling plus about a third of
# headroom, and is still well under what four long sentences would take.
MIN_SENTENCES = 1
MAX_SENTENCES = 4
MAX_CHARACTERS = 700

# ---------------------------------------------------------------------------
# independent grounding check
# ---------------------------------------------------------------------------

# Number-like tokens. A hyphen is a separator here ("13-0" is 13 and 0), not a
# sign, because records and scores are the numbers a narration quotes. Word
# numbers ("thirteen") are not tokens; that is a known blind spot of this
# check, shared with production. A comma-grouped "1,933" reads as two tokens:
# only an Elo rating is displayed grouped, and this eval asks Keener questions.
_NUMBER_TOKEN_RE = re.compile(r"\d+(?:\.\d+)?")

# The only fact-block keys whose values may be said other than verbatim: a
# team's own rating and an opponent's rating (#162, #165). Derived floats
# (`credit`, `contribution`, `residual_contribution`, `rating_diff`) get no
# allowance, so a rounded one is still an invented number.
_RATING_KEYS = frozenset({"rating", "opponent_rating"})


def _number_tokens(text: str) -> set[str]:
    return set(_NUMBER_TOKEN_RE.findall(text))


def _rating_values(node: Any) -> list[Decimal]:
    """Every `rating`/`opponent_rating` value in JSON parsed with
    `parse_float=Decimal`, so rounding works on the exact literal rather than
    on a float repr."""
    if isinstance(node, dict):
        found = [
            value
            for key, value in node.items()
            if key in _RATING_KEYS and isinstance(value, Decimal) and value.is_finite()
        ]
        return found + [rating for value in node.values() for rating in _rating_values(value)]
    if isinstance(node, list):
        return [rating for item in node for rating in _rating_values(item)]
    return []


def _decimal_places(value: Decimal) -> int:
    exponent = value.as_tuple().exponent
    return -exponent if isinstance(exponent, int) and exponent < 0 else 0


def _rendered(value: Decimal, places: int) -> str:
    """`value` rounded half away from zero to `places` decimals and printed at
    exactly that precision, unsigned when it rounds to zero."""
    rounded = value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    if rounded.is_zero():
        rounded = abs(rounded)
    return f"{rounded:.{places}f}"


def _grounded_number_forms(fact_block_json: str) -> set[str]:
    """Every number string check 2a accepts for this fact block, and nothing
    broader:

    (i) a number token of the fact block, verbatim;
    (ii) for each `rating`/`opponent_rating` value `v`:
      - rounded (#162): `|v|` rounded half up to any number of decimal places
        fewer than its JSON literal has ("0.0048" for 0.004784...);
      - displayed (#165): `v * scale` rounded half up to `decimals` places and
        printed at exactly that precision ("4.78"), where `scale`/`decimals`
        are `RATING_DISPLAY`'s entry for the fact block's own top-level
        `method`. No entry for that method (or no `method`) means no display
        allowance.

    Only the scale and precision are read from `api.rating_display`, as data;
    the rendering is this module's own, so a regression in
    `display_value` is not inherited. Rounding half away from zero is the
    display rule `api.rating_display` documents.
    """
    data: Any = json.loads(fact_block_json, parse_float=Decimal)
    forms = _number_tokens(fact_block_json)
    ratings = _rating_values(data)
    for value in ratings:
        for places in range(_decimal_places(value)):
            forms.add(_rendered(abs(value), places))
    method = data.get("method") if isinstance(data, dict) else None
    display = next((d for m, d in RATING_DISPLAY.items() if m == method), None)
    if display is not None:
        for value in ratings:
            forms.add(_rendered(value * display.scale, display.decimals))
    return forms


def _team_mention_pattern(catalog: list[str]) -> re.Pattern[str]:
    """One alternation over every catalog name, longest names first, bounded
    by non-word characters on both sides, matched case-sensitively.

    - **Longest first** makes each match leftmost-longest: at a given start
      position Python's regex takes the first alternative that matches, so
      "Texas Tech" is consumed whole and never also reported as "Texas", and
      "Miami (OH)" is never reported as "Miami". `finditer` does not overlap,
      so a longer name hides any shorter name inside it.
    - **Word bounds** (`(?<!\\w)`, `(?!\\w)`) stop "Concord" matching inside
      "Concordia" or "Troy" inside "Troyer", while still allowing a
      possessive ("LSU's") or trailing punctuation ("USC!").
    - **Case-sensitive**, because a team mention in narration is a proper
      noun, and several catalog names are ordinary words ("Liberty",
      "Temple", "Southern", "Miles", "Shorter").
    """
    ordered = sorted({name for name in catalog if name}, key=len, reverse=True)
    alternation = "|".join(re.escape(name) for name in ordered)
    return re.compile(rf"(?<!\w)(?:{alternation})(?!\w)")


def _team_mentions(pattern: re.Pattern[str], text: str) -> set[str]:
    return {match.group(0) for match in pattern.finditer(text)}


def _string_leaves(node: Any) -> list[str]:
    """Every string value anywhere in parsed JSON."""
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [leaf for value in node.values() for leaf in _string_leaves(value)]
    if isinstance(node, list):
        return [leaf for item in node for leaf in _string_leaves(item)]
    return []


def _fact_block_team_mentions(pattern: re.Pattern[str], fact_block_json: str) -> set[str]:
    """Team names the fact block mentions, found with the same scanner as the
    narration but run over each string value separately, so a match can never
    straddle two JSON fields and "Texas Tech" in the fact block grounds
    "Texas Tech", not "Texas".
    """
    leaves = _string_leaves(json.loads(fact_block_json))
    return {name for leaf in leaves for name in _team_mentions(pattern, leaf)}


# A hyphen-joined score or record claim: "41-38", "13-0", "34 - 31", or a
# three-part record with ties, "6-9-1". Never starts or ends inside a longer
# number or a decimal, but may end at a sentence's full stop ("went 13-0.").
_SCORE_OR_RECORD_RE = re.compile(
    r"(?<!\d)(?<!\d\.)(\d+)\s*-\s*(\d+)(?:\s*-\s*(\d+))?(?!\d)(?!\.\d)"
)


def _claim_parts(match: re.Match[str]) -> tuple[int, ...]:
    return tuple(int(group) for group in match.groups() if group is not None)


def _fact_block_claims(fact_block_json: str) -> tuple[set[tuple[int, ...]], set[tuple[int, ...]]]:
    """`(scores, records)` the fact block states.

    `scores` are game score pairs, stored sorted, so a claim matches in either
    order: which side is said first is attribution, production's rule-5
    relational check (#26). They come from each game's own score fields, plus
    any score written inside a string value (an `explanation` says "Beat them,
    37-10").

    `records` are each object's `(wins, losses)` and `(wins, losses, ties)`,
    kept in order: a record read backwards ("went 0-13" for 13-0) is a
    different, false claim, and no game-score allowance applies to it. A
    record is accepted if any object in the block states it; which team it is
    said about is not checked (#166).
    """
    scores: set[tuple[int, ...]] = set()
    records: set[tuple[int, ...]] = set()
    score_keys = (
        ("team_score", "opponent_score"),
        ("home_points", "away_points"),
        ("team_a_score", "team_a_opponent_score"),
        ("team_b_score", "team_b_opponent_score"),
    )

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            wins, losses, ties = node.get("wins"), node.get("losses"), node.get("ties")
            if isinstance(wins, int) and isinstance(losses, int):
                records.add((wins, losses))
                if isinstance(ties, int):
                    records.add((wins, losses, ties))
            for first, second in score_keys:
                if isinstance(node.get(first), int) and isinstance(node.get(second), int):
                    scores.add(tuple(sorted((node[first], node[second]))))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, str):
            for match in _SCORE_OR_RECORD_RE.finditer(node):
                parts = _claim_parts(match)
                if len(parts) == 2:
                    scores.add(tuple(sorted(parts)))

    walk(json.loads(fact_block_json))
    return scores, records


def _invented_claims(text: str, fact_block_json: str) -> list[str]:
    """Hyphen-joined pairs in `text` that are neither a stated game score (in
    either order) nor a stated record (in its order), as written."""
    scores, records = _fact_block_claims(fact_block_json)
    invented: set[str] = set()
    for match in _SCORE_OR_RECORD_RE.finditer(text):
        parts = _claim_parts(match)
        if parts in records:
            continue
        if len(parts) == 2 and tuple(sorted(parts)) in scores:
            continue
        invented.add(match.group(0))
    return sorted(invented)


# ---------------------------------------------------------------------------
# length and banned words
# ---------------------------------------------------------------------------

# A candidate sentence break: . ! or ?, optionally followed by closing
# quotes/parens, then whitespace, then a capital letter (optionally behind an
# opening quote). Requiring the capital keeps a mid-sentence exclamation like
# "USC -- USC! -- 41-38" (the prompt's own GOOD example) as one sentence, and
# never splits before a digit, so "No. 1" and "... 13-0" never start a new
# sentence. A real sentence that starts with a digit is merged with the one
# before: an undercount, never an overcount, and the 700-character cap still
# bounds the length.
_SENTENCE_BREAK_RE = re.compile("[.!?]+[\"'”’)]*\\s+(?=[\"'“‘(]*[A-Z])")

# A "." after one of these is an abbreviation, not the end of a sentence
# ("vs. USC", "St. John's", "U.S. Bank Stadium").
_ABBREVIATIONS = frozenset({"no", "vs", "st", "jr", "sr", "mt", "ft", "dr", "mr", "mrs", "u.s"})
_WORD_BEFORE_RE = re.compile(r"[A-Za-z][A-Za-z.]*$")


def _sentence_count(text: str) -> int:
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


# Profanity and slurs, as exact word forms (no open-ended stems), so a word
# that merely starts with one ("cocky", which the prompt asks for,
# "Scunthorpe", "Spicer", "Hancock") never hits. Short by design: a smoke check
# that the prompt's "no slurs, no profanity" rule still binds, not a content
# filter. Mild PG-13 words the prompt allows ("hell of a season", "damn") are
# deliberately out. No catalog team name hits (checked offline), and neither
# does any coach or player name we know of, except as handled below.
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


def _banned_hits(text: str) -> list[str]:
    return [
        match.group(0)
        for pattern in (_PROFANITY_AND_SLURS_RE, _NAME_HOMOGRAPH_SLURS_RE, _AI_META_RE)
        for match in pattern.finditer(text)
    ]


# Recorded, never asserted: whether a contested year's narration says so in
# character. Wording varies too much to assert on.
_CONTESTED_DISCLOSURE_RE = re.compile(
    r"\bpolls?\b|\bcontested\b|\bdebat\w*|\bargu\w*|\bcontrovers\w*|\bsplit\b"
    r"|\bdisagree\w*|\bvoters?\b|\bhumans?\b|\bBCS\b|\bAP\b|\bcoaches\b|\bsaw it\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# #107 diagnosis (reported, never asserted)
# ---------------------------------------------------------------------------

_FEEDBACK_PAIR_RE = re.compile(r"(\d+)-(\d+)")


def _issue_107_suspect(grounding_feedback: str | None, case: TeamCaseOut) -> bool:
    """Whether production's grounding feedback objects to a pair equal to the
    team's own W-L record, the shape of #107's false positive ("Oklahoma's
    score should be stated 21-14, not 13-1" for a 13-1 team). Only the first
    attempt's objection is visible: a second rejection leads to the fallback
    without another call, so its feedback is never sent."""
    if grounding_feedback is None:
        return False
    record = (case.wins, case.losses)
    return any(
        (int(first), int(second)) == record
        for first, second in _FEEDBACK_PAIR_RE.findall(grounding_feedback)
    )


# ---------------------------------------------------------------------------
# the eval
# ---------------------------------------------------------------------------


class _RecordingNarrator:
    """Pass-through around the production narrator. Records every call's
    messages and every returned text, so check 5 can require the served text
    to be one of them, and the summary can say whether it was the first call
    or the grounding retry, without touching production code.
    """

    def __init__(self, inner: Narrator) -> None:
        self._inner = inner
        self.calls: list[list[dict[str, str]]] = []
        self.outputs: list[str] = []

    def complete(self, *, system: str, messages: list[dict[str, str]]) -> str:
        self.calls.append([dict(message) for message in messages])
        text = self._inner.complete(system=system, messages=messages)
        self.outputs.append(text)
        return text


def _catalog_team_names(client: TestClient) -> list[str]:
    response = client.get("/api/teams", params={"sport": "cfb"})
    assert response.status_code == 200, response.text
    names: list[str] = response.json()["teams"]
    assert names, "the fixture db's CFB team catalog is empty"
    return names


@pytest.mark.skipif(
    not ANTHROPIC_API_KEY,
    reason=(
        "persona smoke eval requires ANTHROPIC_API_KEY (it makes real "
        f"{MODEL} calls); unset, so skipped"
    ),
)
@pytest.mark.parametrize("year", sorted(EXPECTED_KEENER_NUMBER_ONE))
def test_champion_narration_meets_the_section_8_properties(client: TestClient, year: int) -> None:
    production_narrator = get_narrator()
    assert isinstance(production_narrator, ClaudeNarrator), (
        "get_narrator() did not resolve the production ClaudeNarrator "
        f"(got {type(production_narrator).__name__}); is APP_TEST_MODE set?"
    )
    recorder = _RecordingNarrator(production_narrator)
    # `client` (conftest.py) already wires the fixture db and a fresh
    # InMemoryNarrationCache per request; only the narrator is swapped, and
    # the fixture's teardown pops this override.
    app.dependency_overrides[get_narrator] = lambda: recorder

    response = client.post("/api/verdict/champion", json={"year": year})
    assert response.status_code == 200, response.text
    body = response.json()

    case = TeamCaseOut.model_validate(body["evidence"])
    narration = body["narration"]
    text: str = narration["text"]
    team_name = case.team_name
    fact_block_json = team_case_fact_block_json(case)
    fallback_text = team_case_fallback_text(case)
    # The retry's last user turn is production's grounding feedback, so a
    # retry or fallback shows what `api.persona.grounding` objected to.
    grounding_feedback = recorder.calls[1][-1]["content"] if len(recorder.calls) > 1 else None

    if recorder.outputs and text == recorder.outputs[0]:
        served = "first"
    elif text in recorder.outputs:
        served = "retry"
    elif text == fallback_text:
        served = "fallback"
    else:
        served = "not-a-narrator-output"
    sentences = _sentence_count(text)
    disclosure = sorted({m.group(0).lower() for m in _CONTESTED_DISCLOSURE_RE.finditer(text)})
    summary = (
        f"[persona-eval] {year} #1={team_name} chars={len(text)} sentences={sentences} "
        f"claude_calls={len(recorder.calls)} served={served} "
        f"contested={narration['contested']}"
    )
    if narration["contested"]:
        summary += f" disclosure_words={disclosure or 'none'}"
    if grounding_feedback is not None:
        summary += f" issue107_suspect={_issue_107_suspect(grounding_feedback, case)}"
    lines = [summary, f"[persona-eval] {year} text: {text}"]
    if grounding_feedback is not None:
        lines.append(f"[persona-eval] {year} first attempt: {recorder.outputs[0]}")
        lines.append(f"[persona-eval] {year} grounding feedback: {grounding_feedback}")
    print("\n".join(lines))

    # The fact block this test grounds against must be the one the model was
    # actually given, or check 2 would be checking the wrong thing.
    assert recorder.calls, "the narrator was never called"
    first_user_turn = recorder.calls[0][0]["content"]
    assert fact_block_json in first_user_turn, "the fact block was not sent to the narrator"
    assert first_user_turn == build_user_message(
        fact_block_json, contested=narration["contested"]
    ), "reconstructed fact block differs from the one sent to the narrator"
    assert narration["cached"] is False

    # contested flag: true for exactly 2003 and 2017.
    assert narration["contested"] is (year in EXPECTED_CONTESTED_YEARS)

    violations = _section_8_violations(
        year=year,
        text=text,
        case=case,
        catalog=_catalog_team_names(client),
        claude_calls=len(recorder.calls),
        model_outputs=recorder.outputs,
        grounding_feedback=grounding_feedback,
    )
    assert not violations, f"{year}: " + "; ".join(violations) + f" -- text: {text!r}"


def _section_8_violations(
    *,
    year: int,
    text: str,
    case: TeamCaseOut,
    catalog: list[str],
    claude_calls: int,
    model_outputs: list[str],
    grounding_feedback: str | None = None,
) -> list[str]:
    """Every §8 property `text` violates for `case`, empty when it passes.

    `model_outputs` are the texts the narrator actually returned, in call
    order; check 5 requires `text` to be one of them. All properties are
    evaluated and reported together, so a red run says which of them broke
    rather than only the first.
    """
    violations: list[str] = []
    team_name = case.team_name
    fact_block_json = team_case_fact_block_json(case)
    pattern = _team_mention_pattern(catalog)
    mentions = _team_mentions(pattern, text)

    # 1. correct #1 named: the right team, and named as itself, not inside a
    # longer catalog name ("Texas Tech" does not name "Texas")
    if team_name != EXPECTED_KEENER_NUMBER_ONE[year]:
        violations.append(
            f"correct-#1: evidence #1 is {team_name!r}, expected "
            f"{EXPECTED_KEENER_NUMBER_ONE[year]!r}"
        )
    if team_name not in mentions:
        violations.append(
            f"correct-#1: narration does not name {team_name!r} (team mentions found: "
            f"{sorted(mentions)})"
        )

    # 2a. grounded: every number is in the fact block verbatim, or is a rating
    # rounded or displayed the way the site displays it
    invented_numbers = _number_tokens(text) - _grounded_number_forms(fact_block_json)
    if invented_numbers:
        violations.append(
            "grounded: numbers neither in the fact block nor a rounded/displayed rating "
            f"{sorted(invented_numbers)}"
        )

    # 2b. grounded: every catalog team mentioned is mentioned in the fact block
    invented_teams = mentions - _fact_block_team_mentions(pattern, fact_block_json)
    if invented_teams:
        violations.append(f"grounded: teams not in the fact block {sorted(invented_teams)}")

    # 2c. grounded: every hyphen-joined pair is a stated score or record
    invented_claims = _invented_claims(text, fact_block_json)
    if invented_claims:
        violations.append(f"grounded: scores/records not in the fact block {invented_claims}")

    # 3. length bounded
    sentences = _sentence_count(text)
    if not MIN_SENTENCES <= sentences <= MAX_SENTENCES:
        violations.append(f"length: {sentences} sentences, want {MIN_SENTENCES}-{MAX_SENTENCES}")
    if len(text) > MAX_CHARACTERS:
        violations.append(f"length: {len(text)} characters, want <= {MAX_CHARACTERS}")

    # 4. no banned-word hits
    hits = _banned_hits(text)
    if hits:
        violations.append(f"banned-words: {hits}")

    # 5. served by the narrator: structural, so a drifted fallback template
    # cannot pass by no longer equalling `team_case_fallback_text`
    if text not in model_outputs:
        first_attempt = model_outputs[0] if model_outputs else None
        retry_attempt = model_outputs[1] if len(model_outputs) > 1 else None
        violations.append(
            "not-fallback: the served text is not any narrator output "
            f"(claude_calls={claude_calls}; matches team_case_fallback_text: "
            f"{text == team_case_fallback_text(case)}). Served text: {text!r}. "
            f"First attempt: {first_attempt!r}. Retry attempt: {retry_attempt!r}. "
            f"Production grounding feedback on the first attempt: {grounding_feedback!r}. "
            "One possible cause: production grounding's known false positive that reads "
            "a team's own W-L record as a game score (#107); feedback naming the team's "
            f"own record here: {_issue_107_suspect(grounding_feedback, case)}"
        )

    return violations
