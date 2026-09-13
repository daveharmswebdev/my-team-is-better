"""Post-generation grounding check (issue #4 / Architecture Brief §4.3,
made relational in issue #26, and made sentence-scoped in the #26 follow-up
that fixed two real gaps in the first relational pass).

Every number-like token and known-team-name mention in the persona's
generated response must be a subset of what's already in the fact block
(the exact evidence JSON given to Claude) -- nothing invented, nothing
rounded, with one deliberate exception (issue #162):

* **A rating may be rounded.** A number is also grounded if it equals the
  value of some key named exactly `rating` or `opponent_rating` in the fact
  block, rounded half
  away from zero (apps/web's display rule) to fewer decimal places than the
  JSON literal has -- "1933" or "1933.2" for `1933.1932908945062`, "0.005"
  for Keener's `0.005012...`. apps/web shows ratings rounded (Elo in whole
  points), so a narrator repeating the on-screen number must not be treated
  as fabricating it. The literal is parsed as an exact `Decimal`, so the
  rounding never depends on float repr. A token's own decimal places are
  the precision it claims: "1933.0" is not a rounding of `1933.19`.
* **Only ratings, not every float.** The allowance is scoped by field name
  because a rounded rating restates a fact, while a rounding of any float
  would quietly ground numbers nobody decided to allow: a rounded
  `rating_diff` is arithmetic on two ratings, and derived figures (a `.500`
  from a W-L record, point differentials) are an open voice call on #108,
  not something this checker settles by accident. An `opponent_rating` is
  included because it is another team's real rating, restated; `credit`,
  `contribution`, `residual_contribution` and `rating_diff` are derived and
  stay exact-membership only.
* **Grouped thousands.** A narrator mirroring the UI's "1,933" writes an
  en-US comma-grouped integer, which is read as one number token (its
  ungrouped value is checked under the same rules above) rather than as
  "1" and "933". An ungrounded grouped number is reported in grouped form.

That token-membership check alone isn't enough
(issue #26): "34", "31", and "Texas" can each appear *somewhere* in a fact
block without "beat Texas 34-31" ever being a true fact for that specific
game -- the digits can belong to different rows entirely. So on top of the
membership check, `find_ungrounded_tokens` also verifies that any
hyphen-joined score pair stated in the response is attributable to a real
opponent's `(own_score, other_score)`-shaped tuple recorded in the fact
block -- order included, per the persona prompt's rule 5 convention
(`team_score` first, `opponent_score` second).

The first version of that relational check attributed every score pair to
its single nearest team-name mention by character distance, within a fixed
window. Both of those choices turned out to be wrong in realistic persona
phrasing (not just in the terse, parenthetical style the original test
suite happened to use):

* A fixed distance window produced false negatives: "Vanderbilt handled
  Texas pretty well for most of the game, but when the final whistle blew
  it was 34-31." puts the score ~70 characters from "Texas", past any
  reasonable fixed window, so the swapped score silently fell back to
  plain membership checking and went uncaught -- the exact issue #26 bug,
  just phrased less tersely than "Texas (34-31)".
* Nearest-by-distance produced false positives on the equally common
  "TeamA beat TeamB 34-31" construction: textually, "TeamB" sits right next
  to the score, but the score is *TeamA's* per rule 5 (whoever's win/loss
  is being narrated states their own score first) -- attributing it to the
  nearest name instead flags a fully correct sentence as ungrounded.

The fix distinguishes two syntactic shapes rather than leaning on distance
alone:

* A **parenthetical** score, e.g. "Texas (34-31)" or "LSU (31-24)", is an
  explicit, unambiguous attribution device -- whichever name the
  parenthetical is bound to is what the sentence claims that score is for,
  full stop. These are checked against *that specific name's* tuples only,
  same as the original nearest-neighbor design (which is exactly right
  once the enclosing parens confirm the attribution is real and not just
  textual proximity).
* A **bare** score (no enclosing parens) is syntactically ambiguous about
  which of the sentence's mentioned teams it belongs to -- "beat Vanderbilt
  34-31" and "Vanderbilt lost 34-31" read identically at the character
  level. For these, the nearest team-name mention is still the first
  guess (same as the parenthetical case, just with no fixed window --
  that's what fixes Finding 1: a bare score can legitimately sit much
  farther from its team name than a parenthetical one does), but a
  mismatch against that nearest guess isn't flagged outright: if some
  *other* team mentioned in the same sentence has real data that *does*
  match the claim, the pair is treated as grounded under that other
  attribution instead (that's what fixes Finding 2 -- "Vanderbilt" sits
  textually closer to "34-31" than "Texas" does, but Texas's real tuple
  matches, so the sentence is accepted). This can't cross-check a
  two-team head-to-head swap as precisely as the parenthetical case does
  (a swapped pair for one team is, in a two-team meeting, mathematically
  identical to the other team's correct pair), but that ambiguity is
  inherent to the bare phrasing itself, not a gap this checker can close
  without also risking the false positive it just fixed. Bare numbers
  that aren't a game score at all (e.g. a team's own season record, "went
  13-0") are unaffected: their nearest name has no recorded opponent data
  to begin with, so they're skipped before any rescue check runs, exactly
  like the parenthetical case.

Sentence-scoping (splitting `response_text` naively on `.`/`!`/`?`) keeps
both checks from reaching across unrelated sentences to grab a team name
or tuple that has nothing to do with the score pair at hand.

`find_ungrounded_tokens` extracts all of these signals from the response
and returns whichever are *not* grounded, so the caller
(`api.persona.narrate`) can retry with that specific feedback.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

# No leading `-?`: records and scores in this domain (e.g. "13-0", "41-38")
# use a hyphen as a separator, not a negative sign, and treating it as one
# would misparse "13-0" as the tokens "13" and "-0" instead of "13" and "0".
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")

# Response-side number tokens (issue #162): an en-US comma-grouped number
# ("1,933", as apps/web displays an Elo rating) is one token; anything else
# falls back to `_NUMBER_RE`'s shape. A group needs exactly three digits and
# no digit right after it, so "13-0, 12 wins" (comma then space) and "1,9334"
# never read as grouped. Only the response is tokenized this way -- the fact
# block is JSON, where a comma separates values.
_RESPONSE_NUMBER_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?(?!\d)|\d+(?:\.\d+)?")

# The only fact-block keys whose values may be restated rounded: a team's
# own rating and an opponent's rating, both real ratings rather than derived
# arithmetic (see module docstring for why the allowance is scoped by name).
_ROUNDABLE_KEYS = frozenset({"rating", "opponent_rating"})

# A hyphen-joined pair of whole-number scores, e.g. "34-31" or "34 - 31".
# Reuses this module's hyphen-as-separator convention (see `_NUMBER_RE`
# above) rather than treating the hyphen as a negative sign.
_SCORE_PAIR_RE = re.compile(r"(\d+)\s*-\s*(\d+)")

# Naive sentence splitting (deliberately not real NLP -- see module
# docstring) so a score pair and a team-name mention several sentences
# apart don't get treated as related to each other.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

# How close (in characters) a *parenthetical* score pair's enclosing name
# mention may be for that attribution to count, e.g. the "(34-31)"
# immediately following "Texas" in "...like Texas (34-31), LSU (31-24)...".
# Only used for the parenthetical branch (see module docstring) -- a bare
# score pair's candidates are gathered per-sentence instead, with no
# distance cutoff, since distance is not what disambiguates a bare pair.
_PROXIMITY_WINDOW = 30

# `(own_score, other_score)` ordered-int tuples that are actually true for
# a given opponent/team name, gathered from every recognized shape in the
# fact block.
_ScoreTuplesByName = dict[str, set[tuple[int, int]]]

# A team name's mention and its character span within whatever string
# (response text or a single sentence of it) it was found in.
_NameOccurrence = tuple[str, tuple[int, int]]


def find_ungrounded_tokens(
    response_text: str, fact_block_json: str, known_team_names: Iterable[str]
) -> list[str]:
    """Return the sorted, de-duplicated set of number-like tokens,
    known-team-name mentions, and opponent/score-order mismatches in
    `response_text` that are not grounded in `fact_block_json`. An empty
    list means the response is fully grounded.
    """
    fact_numbers = set(_NUMBER_RE.findall(fact_block_json))
    rating_values = _extract_rating_values(fact_block_json)
    ungrounded_numbers = {
        token
        for token in _RESPONSE_NUMBER_RE.findall(response_text)
        if not _is_grounded_number(token, fact_numbers, rating_values)
    }

    names = [name for name in known_team_names if name]
    mentioned_teams = {name for name in names if name in response_text}
    fact_teams = {name for name in names if name in fact_block_json}
    ungrounded_teams = mentioned_teams - fact_teams

    valid_tuples = _extract_valid_score_tuples(fact_block_json)
    relational_mismatches = _find_relational_mismatches(response_text, names, valid_tuples)

    return sorted(ungrounded_numbers | ungrounded_teams | relational_mismatches)


def _is_grounded_number(token: str, fact_numbers: set[str], rating_values: list[Decimal]) -> bool:
    """A response number token is grounded if its ungrouped form is a
    number token of the fact block, or it is a rounding of a `rating`.
    """
    plain = token.replace(",", "")
    if plain in fact_numbers:
        return True
    return any(_is_rounding_of(plain, rating) for rating in rating_values)


def _is_rounding_of(plain_token: str, rating: Decimal) -> bool:
    """Whether `plain_token` is `rating` rounded half away from zero to the
    token's own number of decimal places, which must be fewer than the
    rating literal has. Compared on magnitude because response tokens never
    carry a sign (see `_NUMBER_RE`).
    """
    claimed = Decimal(plain_token)
    places = _decimal_places(claimed)
    if places >= _decimal_places(rating):
        return False
    try:
        rounded = abs(rating).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return False
    return rounded == claimed


def _decimal_places(value: Decimal) -> int:
    exponent = value.as_tuple().exponent
    return -exponent if isinstance(exponent, int) and exponent < 0 else 0


def _extract_rating_values(fact_block_json: str) -> list[Decimal]:
    """Every value of a key in `_ROUNDABLE_KEYS`, anywhere in the fact
    block, parsed as an exact `Decimal` from its JSON literal (so rounding
    never depends on float repr). Walks by field name, like
    `_extract_valid_score_tuples`, never importing the Pydantic models.
    """
    try:
        data: Any = json.loads(fact_block_json, parse_float=Decimal)
    except json.JSONDecodeError:
        return []

    ratings: list[Decimal] = []
    _collect_rating_values(data, ratings)
    return ratings


def _collect_rating_values(node: Any, ratings: list[Decimal]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in _ROUNDABLE_KEYS and isinstance(value, Decimal) and value.is_finite():
                ratings.append(value)
            _collect_rating_values(value, ratings)
    elif isinstance(node, list):
        for item in node:
            _collect_rating_values(item, ratings)


def _extract_valid_score_tuples(fact_block_json: str) -> _ScoreTuplesByName:
    """Recursively walk the parsed fact block, pattern-matching dict shapes
    by field name (never importing the Pydantic models -- see
    `api.models` for `OpponentResultOut` / `HeadToHeadMeetingOut` /
    `CommonOpponentOut`, the three shapes recognized here) to build every
    `name -> {(own_score, other_score), ...}` fact this fact block states.
    """
    try:
        data: Any = json.loads(fact_block_json)
    except json.JSONDecodeError:
        return {}

    valid: _ScoreTuplesByName = defaultdict(set)
    _walk_fact_block(data, valid)
    return valid


def _walk_fact_block(node: Any, valid: _ScoreTuplesByName) -> None:
    if isinstance(node, dict):
        if _is_opponent_result_shape(node):
            valid[node["opponent_name"]].add((node["team_score"], node["opponent_score"]))
        elif _is_head_to_head_meeting_shape(node):
            valid[node["home_team"]].add((node["home_points"], node["away_points"]))
            valid[node["away_team"]].add((node["away_points"], node["home_points"]))
        elif _is_common_opponent_shape(node):
            valid[node["opponent_name"]].add((node["team_a_score"], node["team_a_opponent_score"]))
            valid[node["opponent_name"]].add((node["team_b_score"], node["team_b_opponent_score"]))
        for value in node.values():
            _walk_fact_block(value, valid)
    elif isinstance(node, list):
        for item in node:
            _walk_fact_block(item, valid)


def _is_opponent_result_shape(node: dict[Any, Any]) -> bool:
    """`OpponentResultOut`: a single opponent's own game result."""
    return (
        isinstance(node.get("opponent_name"), str)
        and isinstance(node.get("team_score"), int)
        and isinstance(node.get("opponent_score"), int)
    )


def _is_head_to_head_meeting_shape(node: dict[Any, Any]) -> bool:
    """`HeadToHeadMeetingOut`: a direct meeting between two named teams."""
    return (
        isinstance(node.get("home_team"), str)
        and isinstance(node.get("away_team"), str)
        and isinstance(node.get("home_points"), int)
        and isinstance(node.get("away_points"), int)
    )


def _is_common_opponent_shape(node: dict[Any, Any]) -> bool:
    """`CommonOpponentOut`: an opponent both compared teams played, with
    each team's own score against it.
    """
    return (
        isinstance(node.get("opponent_name"), str)
        and isinstance(node.get("team_a_score"), int)
        and isinstance(node.get("team_a_opponent_score"), int)
        and isinstance(node.get("team_b_score"), int)
        and isinstance(node.get("team_b_opponent_score"), int)
    )


def _split_sentences(text: str) -> list[str]:
    """Naive sentence split on `.`/`!`/`?` (see module docstring -- this
    project doesn't need real NLP here, just enough to keep unrelated
    sentences from being cross-checked against each other).
    """
    return [sentence for sentence in _SENTENCE_SPLIT_RE.split(text.strip()) if sentence]


def _find_relational_mismatches(
    response_text: str, known_team_names: list[str], valid_tuples: _ScoreTuplesByName
) -> set[str]:
    """For every hyphen-joined score pair in `response_text`, decide which
    team(s) it's plausibly claiming a score for and check that claim
    against the fact block, sentence by sentence (see module docstring for
    why: sentence-scoping first, then a parenthetical-vs-bare split within
    each sentence).
    """
    mismatches: set[str] = set()
    for sentence in _split_sentences(response_text):
        name_occurrences = [
            (name, match.span())
            for name in known_team_names
            for match in re.finditer(re.escape(name), sentence)
        ]
        if not name_occurrences:
            continue

        for pair_match in _SCORE_PAIR_RE.finditer(sentence):
            claimed = (int(pair_match.group(1)), int(pair_match.group(2)))
            if _is_parenthesized(sentence, pair_match.span()):
                mismatch = _check_parenthetical_pair(
                    pair_match.span(), claimed, name_occurrences, valid_tuples
                )
            else:
                mismatch = _check_bare_pair(
                    pair_match.span(), claimed, name_occurrences, valid_tuples
                )
            if mismatch is not None:
                mismatches.add(mismatch)
    return mismatches


def _is_parenthesized(sentence: str, pair_span: tuple[int, int]) -> bool:
    """Whether `pair_span` is wrapped in `(...)` within `sentence`, e.g.
    the "34-31" in "Texas (34-31)". An explicit, unambiguous attribution
    device -- see module docstring for why this is checked differently
    from a bare score pair.
    """
    start, end = pair_span
    before = sentence[:start].rstrip()
    after = sentence[end:].lstrip()
    return before.endswith("(") and after.startswith(")")


def _check_parenthetical_pair(
    pair_span: tuple[int, int],
    claimed: tuple[int, int],
    name_occurrences: list[_NameOccurrence],
    valid_tuples: _ScoreTuplesByName,
) -> str | None:
    """A parenthetical score pair is attributed to its single nearest
    team-name mention (within `_PROXIMITY_WINDOW`), since the parens make
    that attribution an explicit textual claim, not a distance guess.
    """
    nearest = _nearest_name(pair_span, name_occurrences)
    if nearest is None:
        return None
    name, distance = nearest
    if distance > _PROXIMITY_WINDOW:
        return None

    valid_for_name = valid_tuples.get(name)
    if not valid_for_name or claimed in valid_for_name:
        # Either not a real opponent this fact block has game data for
        # (nothing relational to check -- the membership check elsewhere
        # already flags the mention itself if it isn't grounded at all),
        # or the claim matches, so it's grounded.
        return None
    return _mismatch_message(name, claimed, valid_for_name)


def _check_bare_pair(
    pair_span: tuple[int, int],
    claimed: tuple[int, int],
    name_occurrences: list[_NameOccurrence],
    valid_tuples: _ScoreTuplesByName,
) -> str | None:
    """A bare score pair (no enclosing parens) is syntactically ambiguous
    about which mentioned team it belongs to -- see module docstring. The
    nearest name is still the first guess (no fixed window, unlike the
    parenthetical branch -- Finding 1 needs a bare score to reach much
    farther than a parenthetical one ever does), but a mismatch against
    that guess is only flagged if no *other* team named in the same
    sentence has real data that matches the claim instead (Finding 2's
    rescue -- a bare score can plausibly belong to any team in its
    sentence, not just whichever one is textually closest).
    """
    nearest = _nearest_name(pair_span, name_occurrences)
    if nearest is None:
        return None
    name, _ = nearest

    valid_for_name = valid_tuples.get(name)
    if not valid_for_name or claimed in valid_for_name:
        return None

    for other_name, _ in name_occurrences:
        if other_name == name:
            continue
        other_valid = valid_tuples.get(other_name)
        if other_valid and claimed in other_valid:
            return None

    return _mismatch_message(name, claimed, valid_for_name)


def _mismatch_message(
    name: str, claimed: tuple[int, int], valid_for_name: set[tuple[int, int]]
) -> str:
    """The string surfaced in `find_ungrounded_tokens`'s return value (and,
    via `api.persona.narrate`, fed back to Claude as retry feedback -- see
    issue #26 follow-up Finding 3). When there's exactly one real tuple for
    `name`, the correction is unambiguous, so say it outright instead of
    just naming the wrong pair. When there's more than one (e.g. a common
    opponent recorded from both compared teams' perspectives), asserting a
    single "correct" order wouldn't be true, so fall back to the plainer,
    still-honest form that just names the wrong pair.
    """
    if len(valid_for_name) == 1:
        (correct,) = valid_for_name
        return (
            f"{name}'s score should be stated {correct[0]}-{correct[1]}, "
            f"not {claimed[0]}-{claimed[1]}"
        )
    return f"{name} {claimed[0]}-{claimed[1]}"


def _nearest_name(
    pair_span: tuple[int, int], name_occurrences: list[_NameOccurrence]
) -> tuple[str, int] | None:
    """The `(name, distance)` pair whose mention is character-distance
    nearest to `pair_span`, or `None` if there are no team-name mentions
    at all.
    """
    best: tuple[str, int] | None = None
    for name, name_span in name_occurrences:
        distance = _span_distance(pair_span, name_span)
        if best is None or distance < best[1]:
            best = (name, distance)
    return best


def _span_distance(a: tuple[int, int], b: tuple[int, int]) -> int:
    a_start, a_end = a
    b_start, b_end = b
    if b_start >= a_end:
        return b_start - a_end
    if a_start >= b_end:
        return a_start - b_end
    return 0
