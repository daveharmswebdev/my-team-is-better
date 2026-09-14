"""Post-generation grounding check (issue #4 / Architecture Brief §4.3,
made relational in issue #26, and made sentence-scoped in the #26 follow-up
that fixed two real gaps in the first relational pass).

Every number-like token and known-team-name mention in the persona's
generated response must be a subset of what's already in the fact block
(the exact evidence JSON given to Claude) -- nothing invented, nothing
rounded, with two deliberate exceptions for ratings (issues #162 and #165):

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
* **A rating may be quoted as the site displays it (issue #165).** apps/web
  shows a Keener rating scaled up and rounded ("5.04" for
  `0.005044108672990355`), which no rounding of the raw literal produces. So
  a number is also grounded if it is exactly
  `api.rating_display.display_value(v, method)` for some `rating` or
  `opponent_rating` value `v`, where `method` is the fact block's own
  top-level `"method"` (`TeamCaseOut.method` for champion and team-case
  blocks, `ComparisonResultOut.method` for compare). The comparison is on
  the string, so only the display's own precision counts: "5.04" is
  grounded, "5.0" and "5.040" are not (by this rule). The scale is the
  block's method's, so a Keener-scaled figure in an Elo block is not
  grounded. A block with no `method`, or one not in `RATING_DISPLAY`, gets
  no display allowance; the literal and #162 rules still apply to it.
* **Only ratings, not every float.** The allowance is scoped by field name
  because a rounded rating restates a fact, while a rounding of any float
  would quietly ground numbers nobody decided to allow: a rounded
  `rating_diff` is arithmetic on two ratings, and derived figures (a `.500`
  from a W-L record, point differentials) are an open voice call on #108,
  not something this checker settles by accident. An `opponent_rating` is
  included because it is another team's real rating, restated; `credit`,
  `contribution`, `residual_contribution` and `rating_diff` are derived and
  stay exact-membership only -- neither rounded nor scaled.
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
  without also risking the false positive it just fixed.

**A subject team's own season record is not a game score (issue #107).**
Before a pair is attributed to any name, bare or parenthetical, it is
skipped if it equals `(wins, losses)` of *any* subject team in the fact
block: the top-level `wins`/`losses` of a team case (`TeamCaseOut`), and
both `team_a`'s and `team_b`'s of a comparison (`ComparisonResultOut`).
Which name is nearest does not matter. Without the skip, a record was
attributed like any other pair and flagged whenever its nearest name had
game data: "going 13-1 with wins over Oklahoma 21-14" checked LSU's 13-1
against Oklahoma's score, and "Texas went 10-3 and Texas A&M went 11-2"
checked each record against its own team's head-to-head score. (An earlier
version of this docstring claimed a record was safe because its nearest
name had no game data; that was only true when the nearest name was a
team-case subject.) Only subject records are skipped -- a
`rating_breakdown` entry's per-opponent `wins`/`losses` is not, so "beat
Georgia 2-0" is still checked against Georgia's real scores.

Accepted trade-off: a fabricated score that happens to equal a subject
team's record (e.g. "beat Oklahoma 13-1" in LSU's 13-1 season) is no longer
caught relationally. Its numbers still have to pass the membership check.

**Records read in order, and pairs in sentences that name no team (issue
#181).** Two fabrications passed every rule above: a subject record stated
backwards ("Texas went 0-13" or "0-13-0" for a 13-0-0 team -- every digit is
in the block), and a score pair in a sentence naming no team, whose numbers
come from different rows ("They beat them 42-25."), which the attribution
branches never saw because they need a name to attribute to. So the response
is scanned for claims with a regex that reads a W-L-T record as one
three-part claim (never also as a two-part pair, as the earlier pair regex
did with "8-8" out of "8-8-1"), and each claim, sentence by sentence, goes
through these rules in order:

* **A three-part claim** is grounded only if it is, in order, a subject
  team's `(wins, losses, ties)` (the same subjects as #107). Which subject it
  is said about is checked by the #166 rules below when the sentence names
  a subject; these #181 rules are the path for a claim no subject is
  attributed to.
* **A two-part claim equal to a subject `(wins, losses)`** is skipped (#107).
* **A two-part claim that is a subject `(wins, losses)` backwards** is
  flagged, whether or not the sentence names a team and before either
  attribution branch, so it yields one message -- unless the pair is, in
  that order, a real game score for some name (a 3-1 team's 1-3 loss is that
  game, not the record reversed), or is a hyphen pair inside some string
  value, in either order. That last exemption exists because an
  `explanation` quotes scores that are not always a game tuple of the block:
  2013 Michigan State's breakdown quotes a 14-0 win, and "That one ended
  0-14." in the 2013 Florida State (14-0) comparison is that score, not
  Florida State's record backwards. An exempted pair falls through to the
  two rules below, as any other pair does. Accepted trade-off, the same kind
  as #107's: a record stated backwards goes uncaught when some string value
  quotes a score equal to that record.
* **A two-part claim in a sentence that names a team** goes through the
  parenthetical/bare attribution above, unchanged.
* **A two-part claim in a sentence that names no team** can't be held to an
  attribution, so it only has to be *some* pair the block states: a game
  score from any recognized shape, in either order; a hyphen pair inside
  any string value, in either order (an `explanation` quotes scores that
  are not always a game tuple of this block); or, in order, the
  `(wins, losses)` of any object (a `rating_breakdown` series record).

A record mismatch says the claim "is not a stated record". When exactly one
subject team's record is the claim's reverse (wins and losses swapped, ties
kept, same number of parts), it also names whose record that is: "0-13 is
not a stated record; Texas's record is 13-0", "0-13-0 is not a stated
record; Texas's record is 13-0-0". The owner is the subject's `team_name`
(a team case's top level, or a comparison's `team_a` / `team_b`). The
message deliberately does not say the claim "should be stated" as the
reverse: in a comparison the sentence may be about the other team, and
which team a sentence is about is attribution (the #166 rules below, which
only apply when the sentence names a subject) -- whose record the reverse
is, though, is simply true. When no subject's record is the reverse, or more
than one subject's is, no owner is named ("7-1-1 is not a stated record").
An unattributed pair that is none of the above is reported as "42-25 is not
a score from any game in the facts".
These rules are stricter than the independent smoke-eval checker's
(`tests/test_persona_smoke_eval.py`), which production must never import.
That checker accepts any object's W-L or W-L-T in its stated order and any
game score in either order, and has no rule of its own for a reversed
record. Production grounds a three-part claim only as a subject's record,
and flags a subject's `(wins, losses)` stated backwards unless it is a game
score in that order or a hyphen pair inside some string value.

**A record and a rating belong to the team the sentence says they do (issue
#166).** Two more fabrications passed everything above because each number
was *somebody's*: "Texas went 12-1" on the 2005 Texas (13-0) vs USC (12-1)
comparison, grounded by #107's skip since 12-1 is a subject's record, and
"Elo has Texas at 1892" on the same blocks, grounded by #162's rounding
since 1892 is USC's rating as the card shows it. Both are now attributed to
a team with the same sentence-scoped, parenthetical-vs-bare device the
score rule uses: a parenthetical claim is bound to its nearest name within
`_PROXIMITY_WINDOW` and nothing else; a bare claim's first guess is the
nearest name, at any distance, and it is rescued when another team named
in the same sentence owns it.

* **A record claim's subject.** For a two- or three-part claim, the
  attributed subject is: parenthetical -- the nearest name, if it is a
  subject team (#107's subjects: a team case's top level, a comparison's
  `team_a` / `team_b`); bare -- the nearest *subject* mention in the
  sentence, skipping non-subject names for this step only, so "going 13-1
  with wins over Oklahoma 21-14" still attributes LSU's record to LSU. A
  claim with no attributed subject (the sentence names no subject, a
  parenthetical is bound to an opponent, a hand-typed block whose sides
  carry no `wins`/`losses`) takes the #181 path above, unchanged. With a
  subject, `_check_claim` applies, in order: grounded if the claim is the
  subject's record with the same number of parts; grounded (bare only) if
  it is another named subject's record; grounded (two-part only) if it is a
  game score -- one of the nearest name's tuples, bare and one of another
  named team's, in order a game score from any row, or in either order a
  hyphen pair inside a string value; otherwise flagged. The message, in
  this order: a subject record backwards keeps #181's wording ("0-13 is not
  a stated record; Texas's record is 13-0"); a two-part claim whose nearest
  name is a non-subject opponent with game data is that opponent's score,
  in #26's wording ("Oklahoma's score should be stated 21-14, not 14-1");
  otherwise, when the attribution is unambiguous (parenthetical, or bare
  with exactly one subject named in the sentence), "12-1 is not Texas's
  record; Texas's record is 13-0" ("12-1-0 ... 13-0-0" for three parts);
  when bare and more than one subject is named, "13-1 is not a stated
  record" -- never a team the sentence may not be about (#181's reasoning).
* **A rating claim's owner.** Ratings are keyed by name: a subject's
  `rating` under its `team_name`, and every `opponent_rating` under the
  `opponent_name` beside it (`games[]`, `quality_wins[]`, `worst_loss`, at
  the top level and inside `team_a` / `team_b`). A response number is
  *rating-only* when the membership rules accept it but it is not a number
  token of the block with the `rating` / `opponent_rating` literals blanked
  out and, on a comparison, the whole top-level `verdict` string blanked
  too: "1892", "1933", "4.74", "5.04", the exact literal
  `1933.1932908945062` and the verdict's own "1933.2" / "1891.8" are; "13",
  "0", "2005", "41" never are. The verdict is blanked because it restates
  both subjects' ratings rounded ("Texas rates higher overall (1933.2 vs
  1891.8, rank 1 vs 2)"), which made each rounding a plain token of every
  comparison block, never rating-only, so "Elo has Texas at 1891.8" passed
  there while the same sentence on Texas's team case was caught. Blanking
  the whole string rather than the rating pair is safe because the verdict
  is a derived summary of facts the block states elsewhere as rows (the
  head-to-head scores and weeks in `head_to_head.meetings`, the
  common-opponent scores in `common_opponents[*]`, the ranks in
  `team_a.rank` / `team_b.rank`): removing it changes rating-only-ness for
  nothing but the rounded rating pair, and it keeps grounding independent
  of the verdict's prose. The record and score rules still read the verdict
  (a hyphen pair quoted there is still a string-value exemption). Each
  rating-only token in a sentence naming a team is attributed like a bare
  or parenthetical claim, and is grounded if it is the attributed name's
  rating exactly, rounded (#162) or as displayed (#165); a bare token is
  also grounded if it is another named team's. A name with no rating in
  the block (nothing to check, like a name with no game data) and a token
  in a sentence naming no team are grounded as before. Otherwise "1892 is
  not Texas's rating; Texas's rating is 1933", the token as written (a
  grouped "1,892" stays grouped) and the owner's rating in the form the
  token matched under -- the display value when the token is a display
  value of the block, else rounded half away from zero to the token's
  decimal places when the token is a rounding, else the exact literal. When
  the name carries more than one distinct rating, only "1892 is not Texas's
  rating".
* **A sentence quoting both compared teams' ratings is a comparison
  statement (round 3).** On a comparison -- two subjects, `team_a` and
  `team_b`, each with a `rating` under its `team_name` -- a bare
  rating-only token that fails the nearest-name check and the bare rescue
  is also grounded when it is the rating (exact, rounded or as displayed)
  of the subject that is *not* its nearest name, and another bare
  rating-only token in the same sentence is the other subject's rating,
  that other subject being the nearest subject mention to it. The engine's
  own verdict sentence handed to the narrator, "Texas rates higher overall
  (1933.2 vs 1891.8, rank 1 vs 2)", names only `team_a`, and it and its
  voiced forms ("Texas rates higher, 1933 to 1892"; "USC rates lower,
  1933.2 vs 1891.8") are grounded: a sentence quoting both compared teams'
  ratings is a comparison statement, and the rating that is not the named
  team's can only be the other team's. A lone bare token gets no such
  rescue, so "Elo has Texas at 1892" on the comparison is still flagged;
  a parenthetical token never uses it and never counts as the partner
  ("Texas (1892) sits above 1933" and "Texas sits at 1892 (1933)" are
  flagged); a sentence naming neither subject has no named subject to
  hold the partner to; and a team case has one subject, so the rule never
  applies there.

* **A name is a mention only when it stands on its own.** The sentence's
  name mentions (`_name_occurrences`, shared by the score rule, the record
  rule and the rating pass) are the known names not glued to a word
  character on either side (a possessive "Texas's" / "Texas'" counts, and so
  do "Miami (OH)" and "Texas A&M") and not inside another known name's
  occurrence: in "Florida State" only Florida State is mentioned, never a
  phantom Florida. Matching raw substrings had registered that phantom, and
  the bare rescue then accepted its rating: "Keener has Florida State at
  2.99" passed on the 2013 Florida State case because 2.99 is Florida's
  `opponent_rating` as displayed. The membership check on the whole response
  (`name in response_text`) is unchanged and still matches substrings.

Accepted trade-offs, all shared with #26's score rule: a two-team swap in
one sentence ("Texas went 12-1 and USC went 13-0"; "Elo has USC at 1933 and
Texas at 1892") is rescued, because the bare phrasing itself cannot say
which of the two names each number belongs to, and the rescue is what keeps
"USC lost only to Texas, finishing 12-1" and "beat USC 41-38, and Elo has
them at 1,933" grounded. The comparison-statement rule has the same
trade-off in one-name prose: "Texas sits at 1892, up from 1933" quotes both
compared teams' ratings, and bare prose cannot say which figure is Texas's,
so it is grounded like the two-team swap; a lone wrong rating beside a name
("Elo has Texas at 1892") is still caught. A wrong-team
two-part record that equals, in order, a game score the block states
("Michigan State went 14-0" in Michigan State's 13-1-0 season, after a 14-0
win over Purdue) is grounded by the game-score rule, the same kind of
trade-off as #107's; the three-part form ("14-0-0") is caught. And only
rating-only tokens are attributed: a rating that also happens to be an id, a
rank, a year or a week token of the block is grounded by membership and
never reaches this check (epic #199).

Sentence-scoping (splitting `response_text` naively on `.`/`!`/`?`) keeps
all of these checks from reaching across unrelated sentences to grab a team
name or tuple that has nothing to do with the claim at hand.

`find_ungrounded_tokens` extracts all of these signals from the response
and returns whichever are *not* grounded, so the caller
(`api.persona.narrate`) can retry with that specific feedback.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from api.models import Method
from api.rating_display import RATING_DISPLAY, display_value

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

# A `rating` / `opponent_rating` key with its JSON number literal (issue
# #166): blanking these out of the fact-block text leaves the number tokens
# a response number can be grounded by *without* being a rating, so a token
# grounded only as a rating can be told apart and attributed to a name.
_RATING_LITERAL_RE = re.compile(
    r'("(?:rating|opponent_rating)":\s*)(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)'
)

# A comparison's `verdict` key with its whole JSON string value (issue #166,
# round 2): the verdict restates both subjects' ratings rounded ("1933.2 vs
# 1891.8"), so it is blanked along with the rating literals when deciding
# whether a token is grounded only as a rating. Applied to the JSON text, so
# it matches the key wherever it sits; `ComparisonResultOut.verdict` is the
# only such key any fact block carries, and a JSON string value can't contain
# an unescaped `"verdict":`. Everything the verdict quotes besides the rating
# pair is a row of the block, so the blank costs nothing (module docstring).
_VERDICT_STRING_RE = re.compile(r'("verdict":\s*)"(?:[^"\\]|\\.)*"')

# A known team name standing on its own in a sentence (issue #166, round 2):
# not glued to a word character on either side. A possessive ("Texas's",
# "Texas'") still counts, and so do "Miami (OH)" and "Texas A&M".
_NAME_BOUNDARY = (r"(?<!\w)", r"(?!\w)")

# A hyphen-joined score pair or record, e.g. "34-31", "34 - 31" or "8-8-1".
# Reuses this module's hyphen-as-separator convention (see `_NUMBER_RE`
# above) rather than treating the hyphen as a negative sign. A W-L-T record
# is one three-part claim (group 3 set), never also read as a two-part pair,
# and no part may be glued to a neighbouring digit or decimal (issue #181;
# the same shape as the independent smoke-eval checker's regex).
_SCORE_OR_RECORD_RE = re.compile(
    r"(?<!\d)(?<!\d\.)(\d+)\s*-\s*(\d+)(?:\s*-\s*(\d+))?(?!\d)(?!\.\d)"
)

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

# `name -> {rating}`: a subject's own `rating` and every `opponent_rating`
# beside an `opponent_name`, as exact `Decimal`s (issue #166).
_RatingsByName = dict[str, set[Decimal]]

# A response number token grounded only as a rating, with its span in the
# sentence it was found in and the token as written (issue #166, round 3).
_RatingToken = tuple[tuple[int, int], str]


@dataclass(frozen=True)
class _SubjectRecord:
    """A subject team's season record (#107's subjects), with `ties` when the
    block states them."""

    wins: int
    losses: int
    ties: int | None

    def parts(self, count: int) -> tuple[int, ...] | None:
        """The record with `count` parts (2 or 3), or `None` when the block
        states no `ties` and three parts are asked for."""
        if count == 2:
            return (self.wins, self.losses)
        if self.ties is None:
            return None
        return (self.wins, self.losses, self.ties)


@dataclass(frozen=True)
class _RecordAttribution:
    """Which team a record-shaped claim is about (issue #166; see the module
    docstring's #166 rules)."""

    # N: the nearest known-team mention (within `_PROXIMITY_WINDOW` for a
    # parenthetical claim), or `None`.
    nearest: str | None
    # S: the subject the claim is attributed to, or `None`.
    subject: str | None
    # Every distinct subject the sentence names, for the bare rescue and
    # for deciding whether the message may name a team.
    named_subjects: tuple[str, ...]
    parenthetical: bool


@dataclass(frozen=True)
class _NumberFacts:
    """What a response number token is grounded against, and what the
    rating-attribution pass (issue #166) needs on top of that."""

    # Every number token of the fact block, as written.
    fact_numbers: set[str]
    # Every `rating` / `opponent_rating` value, for #162's rounding.
    rating_values: list[Decimal]
    # Those values as the card shows them under `method` (#165).
    display_values: set[str]
    method: Method | None
    # `fact_numbers` with the rating literals blanked out: a grounded token
    # absent from this set is grounded only as a rating.
    non_rating_numbers: set[str]
    ratings_by_name: _RatingsByName
    # A comparison's `team_a` / `team_b` `rating` under each `team_name`,
    # for the comparison-statement rule (#166, round 3). Empty on a team
    # case, or when either side lacks a name or a finite rating.
    compared_ratings: Mapping[str, Decimal]


@dataclass(frozen=True)
class _ClaimFacts:
    """What the fact block states that a score or record claim can match
    (see the module docstring's #181 rules for which rule reads which)."""

    # `name -> {(own_score, other_score)}`, for the attribution branches.
    valid_tuples: _ScoreTuplesByName
    # Every real game score, ordered as recorded for some name.
    game_scores: frozenset[tuple[int, int]]
    # Subject teams' `(wins, losses)` and `(wins, losses, ties)`.
    subject_records: frozenset[tuple[int, int]]
    subject_w_l_t_records: frozenset[tuple[int, int, int]]
    # `(wins, losses)` of any object in the block, e.g. a breakdown entry.
    object_records: frozenset[tuple[int, int]]
    # Two-part hyphen pairs inside any string value, stored `(low, high)`.
    string_value_pairs: frozenset[tuple[int, int]]
    # A subject record, `(wins, losses)` or `(wins, losses, ties)`, to the
    # `team_name` of every subject whose record it is (`None` for a subject
    # with no string `team_name`), for naming whose record a reverse is.
    record_owners: Mapping[tuple[int, ...], tuple[str | None, ...]]
    # Each subject's record under its `team_name`, for attributing a record
    # claim to the team the sentence names (#166). A subject with no string
    # `team_name` cannot be named, so it is not here.
    subjects: Mapping[str, _SubjectRecord]


def find_ungrounded_tokens(
    response_text: str, fact_block_json: str, known_team_names: Iterable[str]
) -> list[str]:
    """Return the sorted, de-duplicated set of number-like tokens,
    known-team-name mentions, and opponent/score-order, record and rating
    attribution mismatches in `response_text` that are not grounded in
    `fact_block_json`. An empty list means the response is fully grounded.
    """
    numbers = _extract_number_facts(fact_block_json)
    ungrounded_numbers = {
        token
        for token in _RESPONSE_NUMBER_RE.findall(response_text)
        if not _is_grounded_number(
            token, numbers.fact_numbers, numbers.rating_values, numbers.display_values
        )
    }

    names = [name for name in known_team_names if name]
    mentioned_teams = {name for name in names if name in response_text}
    fact_teams = {name for name in names if name in fact_block_json}
    ungrounded_teams = mentioned_teams - fact_teams

    relational_mismatches = _find_relational_mismatches(
        response_text, names, _extract_claim_facts(fact_block_json)
    )
    rating_mismatches = _find_rating_mismatches(response_text, names, numbers)

    return sorted(ungrounded_numbers | ungrounded_teams | relational_mismatches | rating_mismatches)


def _extract_number_facts(fact_block_json: str) -> _NumberFacts:
    rating_values = _extract_rating_values(fact_block_json)
    method = _extract_fact_block_method(fact_block_json)
    display_values = (
        set() if method is None else {display_value(rating, method) for rating in rating_values}
    )
    blanked = _VERDICT_STRING_RE.sub(r"\1null", _RATING_LITERAL_RE.sub(r"\1null", fact_block_json))
    return _NumberFacts(
        fact_numbers=set(_NUMBER_RE.findall(fact_block_json)),
        rating_values=rating_values,
        display_values=display_values,
        method=method,
        non_rating_numbers=set(_NUMBER_RE.findall(blanked)),
        ratings_by_name=_extract_ratings_by_name(fact_block_json),
        compared_ratings=_extract_compared_ratings(fact_block_json),
    )


def _is_grounded_number(
    token: str, fact_numbers: set[str], rating_values: list[Decimal], display_values: set[str]
) -> bool:
    """A response number token is grounded if its ungrouped form is a
    number token of the fact block, exactly the display value of a value
    under one of `_ROUNDABLE_KEYS` (`rating` or `opponent_rating`) under the
    fact block's method, or a rounding of such a value.
    """
    plain = token.replace(",", "")
    if plain in fact_numbers or plain in display_values:
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
    `_extract_valid_score_tuples`, never importing the Pydantic response
    models (this module takes only the `Method` alias from `api.models`).
    """
    try:
        data: Any = json.loads(fact_block_json, parse_float=Decimal)
    except json.JSONDecodeError:
        return []

    ratings: list[Decimal] = []
    _collect_rating_values(data, ratings)
    return ratings


def _extract_fact_block_method(fact_block_json: str) -> Method | None:
    """The fact block's own top-level `"method"`, if it is one
    `RATING_DISPLAY` knows; `None` otherwise (missing, not a string, or not
    a displayed method), in which case no display allowance applies.
    """
    try:
        data: Any = json.loads(fact_block_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    raw = data.get("method")
    return next((method for method in RATING_DISPLAY if method == raw), None)


def _collect_rating_values(node: Any, ratings: list[Decimal]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in _ROUNDABLE_KEYS and isinstance(value, Decimal) and value.is_finite():
                ratings.append(value)
            _collect_rating_values(value, ratings)
    elif isinstance(node, list):
        for item in node:
            _collect_rating_values(item, ratings)


def _extract_ratings_by_name(fact_block_json: str) -> _RatingsByName:
    """Every rating the block states *for a named team* (issue #166): a
    subject's `rating` under its `team_name` (a team case's top level, a
    comparison's `team_a` / `team_b`), and every finite `opponent_rating` in
    a dict that also carries a string `opponent_name`, under that name
    (`OpponentResultOut` rows: `games[]`, `quality_wins[]`, `worst_loss`).
    Parsed as exact `Decimal`s, like `_extract_rating_values`.
    """
    try:
        data: Any = json.loads(fact_block_json, parse_float=Decimal)
    except json.JSONDecodeError:
        return {}

    ratings: _RatingsByName = defaultdict(set)
    if isinstance(data, dict):
        for subject in (data, data.get("team_a"), data.get("team_b")):
            if not isinstance(subject, dict):
                continue
            team_name, rating = subject.get("team_name"), subject.get("rating")
            if isinstance(team_name, str) and isinstance(rating, Decimal) and rating.is_finite():
                ratings[team_name].add(rating)
    _collect_opponent_ratings(data, ratings)
    return ratings


def _extract_compared_ratings(fact_block_json: str) -> Mapping[str, Decimal]:
    """A comparison's two subjects' own ratings under their names (issue
    #166, round 3): `{team_a.team_name: team_a.rating, team_b.team_name:
    team_b.rating}` when both sides carry a string `team_name` and a finite
    `rating` and the names differ, else empty. A team case has one subject,
    so the comparison-statement rule never applies to it.
    """
    try:
        data: Any = json.loads(fact_block_json, parse_float=Decimal)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    compared: dict[str, Decimal] = {}
    for side in (data.get("team_a"), data.get("team_b")):
        if not isinstance(side, dict):
            return {}
        team_name, rating = side.get("team_name"), side.get("rating")
        if not (isinstance(team_name, str) and isinstance(rating, Decimal) and rating.is_finite()):
            return {}
        compared[team_name] = rating
    return compared if len(compared) == 2 else {}


def _collect_opponent_ratings(node: Any, ratings: _RatingsByName) -> None:
    if isinstance(node, dict):
        opponent_name, rating = node.get("opponent_name"), node.get("opponent_rating")
        if isinstance(opponent_name, str) and isinstance(rating, Decimal) and rating.is_finite():
            ratings[opponent_name].add(rating)
        for value in node.values():
            _collect_opponent_ratings(value, ratings)
    elif isinstance(node, list):
        for item in node:
            _collect_opponent_ratings(item, ratings)


def _extract_valid_score_tuples(fact_block_json: str) -> _ScoreTuplesByName:
    """Recursively walk the parsed fact block, pattern-matching dict shapes
    by field name (never importing the Pydantic response models -- see
    `api.models` for `OpponentResultOut` / `HeadToHeadMeetingOut` /
    `CommonOpponentOut`, the three shapes recognized here; the last carries
    its `CommonOpponentMeetingOut` lists, whose pairs are registered under
    the enclosing row's `opponent_name`, #130) to build every
    `name -> {(own_score, other_score), ...}` fact this fact block states.
    """
    try:
        data: Any = json.loads(fact_block_json)
    except json.JSONDecodeError:
        return {}

    valid: _ScoreTuplesByName = defaultdict(set)
    _walk_fact_block(data, valid)
    return valid


def _extract_subject_records(fact_block_json: str) -> frozenset[tuple[int, int]]:
    """Every subject team's own `(wins, losses)` (issue #107): the top-level
    record of a team case (`TeamCaseOut`), and `team_a`'s and `team_b`'s of
    a comparison (`ComparisonResultOut`). Deliberately not a recursive walk:
    `rating_breakdown` entries also carry `wins`/`losses`, but those are
    per-opponent series records, not a subject's season record.
    """
    try:
        data: Any = json.loads(fact_block_json)
    except json.JSONDecodeError:
        return frozenset()
    if not isinstance(data, dict):
        return frozenset()

    records: set[tuple[int, int]] = set()
    for subject in (data, data.get("team_a"), data.get("team_b")):
        if not isinstance(subject, dict):
            continue
        wins, losses = subject.get("wins"), subject.get("losses")
        if isinstance(wins, int) and isinstance(losses, int):
            records.add((wins, losses))
    return frozenset(records)


def _extract_claim_facts(fact_block_json: str) -> _ClaimFacts:
    """Everything a score or record claim is checked against (issue #181):
    the existing name-keyed game tuples and subject `(wins, losses)`, plus
    each subject's `(wins, losses, ties)`, every game score regardless of
    name, every object's `(wins, losses)`, and every two-part hyphen pair
    inside a string value.
    """
    valid_tuples = _extract_valid_score_tuples(fact_block_json)
    game_scores = frozenset(score for scores in valid_tuples.values() for score in scores)
    subject_records = _extract_subject_records(fact_block_json)
    try:
        data: Any = json.loads(fact_block_json)
    except json.JSONDecodeError:
        data = None

    subject_w_l_t_records: set[tuple[int, int, int]] = set()
    record_owners: defaultdict[tuple[int, ...], list[str | None]] = defaultdict(list)
    subjects: dict[str, _SubjectRecord] = {}
    if isinstance(data, dict):
        for subject in (data, data.get("team_a"), data.get("team_b")):
            if not isinstance(subject, dict):
                continue
            wins, losses, ties = subject.get("wins"), subject.get("losses"), subject.get("ties")
            if not (isinstance(wins, int) and isinstance(losses, int)):
                continue
            team_name = subject.get("team_name")
            owner = team_name if isinstance(team_name, str) else None
            record_owners[(wins, losses)].append(owner)
            if isinstance(ties, int):
                subject_w_l_t_records.add((wins, losses, ties))
                record_owners[(wins, losses, ties)].append(owner)
            if owner is not None and owner not in subjects:
                subjects[owner] = _SubjectRecord(
                    wins, losses, ties if isinstance(ties, int) else None
                )

    object_records: set[tuple[int, int]] = set()
    string_value_pairs: set[tuple[int, int]] = set()
    _collect_records_and_string_pairs(data, object_records, string_value_pairs)
    return _ClaimFacts(
        valid_tuples=valid_tuples,
        game_scores=game_scores,
        subject_records=subject_records,
        subject_w_l_t_records=frozenset(subject_w_l_t_records),
        object_records=frozenset(object_records),
        string_value_pairs=frozenset(string_value_pairs),
        record_owners={record: tuple(owners) for record, owners in record_owners.items()},
        subjects=subjects,
    )


def _collect_records_and_string_pairs(
    node: Any, object_records: set[tuple[int, int]], string_value_pairs: set[tuple[int, int]]
) -> None:
    if isinstance(node, dict):
        wins, losses = node.get("wins"), node.get("losses")
        if isinstance(wins, int) and isinstance(losses, int):
            object_records.add((wins, losses))
        for value in node.values():
            _collect_records_and_string_pairs(value, object_records, string_value_pairs)
    elif isinstance(node, list):
        for item in node:
            _collect_records_and_string_pairs(item, object_records, string_value_pairs)
    elif isinstance(node, str):
        for match in _SCORE_OR_RECORD_RE.finditer(node):
            first, second, third = match.groups()
            if third is None:
                low, high = sorted((int(first), int(second)))
                string_value_pairs.add((low, high))


def _walk_fact_block(node: Any, valid: _ScoreTuplesByName) -> None:
    if isinstance(node, dict):
        if _is_opponent_result_shape(node):
            valid[node["opponent_name"]].add((node["team_score"], node["opponent_score"]))
        elif _is_head_to_head_meeting_shape(node):
            valid[node["home_team"]].add((node["home_points"], node["away_points"]))
            valid[node["away_team"]].add((node["away_points"], node["home_points"]))
        elif _is_common_opponent_shape(node):
            # Every meeting in both lists (issue #130), not just the last:
            # a serialized meeting carries no `opponent_name` of its own, so
            # the plain descent below can't attribute it and would lose the
            # fact if it weren't registered here under the row's name.
            for meeting in (*node["team_a_meetings"], *node["team_b_meetings"]):
                if _is_common_opponent_meeting_shape(meeting):
                    valid[node["opponent_name"]].add(
                        (meeting["team_score"], meeting["opponent_score"])
                    )
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
    every meeting each team had against it (issue #130) as
    `team_a_meetings` / `team_b_meetings` lists of
    `CommonOpponentMeetingOut`.
    """
    return (
        isinstance(node.get("opponent_name"), str)
        and isinstance(node.get("team_a_meetings"), list)
        and isinstance(node.get("team_b_meetings"), list)
    )


def _is_common_opponent_meeting_shape(node: Any) -> bool:
    """`CommonOpponentMeetingOut`: one compared team's own `(team_score,
    opponent_score)` against the common opponent. Has no `opponent_name` of
    its own, which is why `_is_opponent_result_shape` never matches it.
    """
    return (
        isinstance(node, dict)
        and isinstance(node.get("team_score"), int)
        and isinstance(node.get("opponent_score"), int)
    )


def _split_sentences(text: str) -> list[str]:
    """Naive sentence split on `.`/`!`/`?` (see module docstring -- this
    project doesn't need real NLP here, just enough to keep unrelated
    sentences from being cross-checked against each other).
    """
    return [sentence for sentence in _SENTENCE_SPLIT_RE.split(text.strip()) if sentence]


def _find_relational_mismatches(
    response_text: str, known_team_names: list[str], facts: _ClaimFacts
) -> set[str]:
    """For every score or record claim in `response_text`, sentence by
    sentence, apply the module docstring's rules in order (issue #181): a
    three-part record must be a subject's; a subject's own `(wins, losses)`
    is skipped (#107); a subject's `(wins, losses)` backwards is flagged; a
    pair in a sentence naming a team goes through the parenthetical-vs-bare
    attribution (#26); a pair in a sentence naming none must be some pair
    the block states.
    """
    mismatches: set[str] = set()
    for sentence in _split_sentences(response_text):
        name_occurrences = _name_occurrences(sentence, known_team_names)
        for claim_match in _SCORE_OR_RECORD_RE.finditer(sentence):
            mismatch = _check_claim(sentence, claim_match, name_occurrences, facts)
            if mismatch is not None:
                mismatches.add(mismatch)
    return mismatches


def _name_occurrences(sentence: str, known_team_names: list[str]) -> list[_NameOccurrence]:
    """Every known name mentioned in `sentence`, with its span, for the score
    rule (#26), the record rule and the rating pass (#166). A name counts
    only when it stands on its own (issue #166, round 2): not glued to a word
    character (`_NAME_BOUNDARY`), and not inside another known name's
    occurrence -- the longer name wins, so "Florida State" is one mention of
    Florida State and never also a phantom "Florida", whose rating the bare
    rescue would otherwise accept for Florida State.
    """
    before, after = _NAME_BOUNDARY
    found = [
        (name, match.span())
        for name in known_team_names
        for match in re.finditer(f"{before}{re.escape(name)}{after}", sentence)
    ]
    return [
        (name, span)
        for name, span in found
        if not any(_lies_inside(span, other) for _, other in found if other != span)
    ]


def _lies_inside(span: tuple[int, int], other: tuple[int, int]) -> bool:
    return other[0] <= span[0] and span[1] <= other[1]


def _check_claim(
    sentence: str,
    claim_match: re.Match[str],
    name_occurrences: list[_NameOccurrence],
    facts: _ClaimFacts,
) -> str | None:
    """One score or record claim, in this order:

    1. Attribute it to a subject (#166). With one, `_check_attributed_record`
       decides; the rest of this function never runs.
    2. Otherwise the #181 order: a three-part claim must be some subject's
       record; a two-part claim equal to a subject record is skipped (#107);
       a subject record backwards is flagged; a pair in a sentence naming a
       team goes through the parenthetical / bare attribution (#26); a pair
       in a sentence naming none must be some pair the block states.
    """
    first, second, third = claim_match.groups()
    span = claim_match.span()
    parenthetical = _is_parenthesized(sentence, span)
    attribution = _attribute_record_claim(span, parenthetical, name_occurrences, facts.subjects)
    if attribution.subject is not None:
        claimed_parts: tuple[int, ...] = (
            (int(first), int(second)) if third is None else (int(first), int(second), int(third))
        )
        return _check_attributed_record(
            claimed_parts, attribution.subject, attribution, name_occurrences, facts
        )

    if third is not None:
        return _check_w_l_t_record((int(first), int(second), int(third)), facts)

    claimed = (int(first), int(second))
    if claimed in facts.subject_records:
        return None
    reversed_record = _check_reversed_record(claimed, facts)
    if reversed_record is not None:
        return reversed_record
    if not name_occurrences:
        return _check_unattributed_pair(claimed, facts)
    if parenthetical:
        return _check_parenthetical_pair(span, claimed, name_occurrences, facts.valid_tuples)
    return _check_bare_pair(span, claimed, name_occurrences, facts.valid_tuples)


def _attribute_record_claim(
    claim_span: tuple[int, int],
    parenthetical: bool,
    name_occurrences: list[_NameOccurrence],
    subjects: Mapping[str, _SubjectRecord],
) -> _RecordAttribution:
    """Which team a record-shaped claim is about (issue #166). The nearest
    name is the parenthetical / bare device the score rule uses (a
    parenthetical binds only within `_PROXIMITY_WINDOW`). The subject is that
    name for a parenthetical claim, if it is a subject; for a bare claim it
    is the nearest *subject* mention at any distance, skipping non-subject
    names for this step only.
    """
    nearest: str | None = None
    found = _nearest_name(claim_span, name_occurrences)
    if found is not None and (not parenthetical or found[1] <= _PROXIMITY_WINDOW):
        nearest = found[0]

    named_subjects = tuple(dict.fromkeys(name for name, _ in name_occurrences if name in subjects))
    if parenthetical:
        subject = nearest if nearest is not None and nearest in subjects else None
    else:
        nearest_subject = _nearest_name(
            claim_span, [(name, span) for name, span in name_occurrences if name in subjects]
        )
        subject = None if nearest_subject is None else nearest_subject[0]
    return _RecordAttribution(
        nearest=nearest,
        subject=subject,
        named_subjects=named_subjects,
        parenthetical=parenthetical,
    )


def _check_attributed_record(
    claimed: tuple[int, ...],
    subject: str,
    attribution: _RecordAttribution,
    name_occurrences: list[_NameOccurrence],
    facts: _ClaimFacts,
) -> str | None:
    """A record-shaped claim attributed to `subject` (issue #166), in this
    order: grounded as the subject's record; grounded (bare) as another
    named subject's record; grounded (two-part) as a game score; else
    flagged -- a subject record backwards keeps #181's message, a two-part
    claim nearest a non-subject opponent with game data is that opponent's
    score (#26's message), and anything else is not the subject's record.
    """
    parts = len(claimed)
    own_record = facts.subjects[subject]
    record = own_record.parts(parts)
    if claimed == record:
        return None
    if not attribution.parenthetical and any(
        facts.subjects[other].parts(parts) == claimed
        for other in attribution.named_subjects
        if other != subject
    ):
        return None
    if parts == 2 and _is_stated_game_score(
        (claimed[0], claimed[1]), attribution, name_occurrences, facts
    ):
        return None

    reverse = (claimed[1], claimed[0], *claimed[2:])
    stated_records: frozenset[tuple[int, ...]] = (
        facts.subject_records if parts == 2 else facts.subject_w_l_t_records
    )
    if reverse in stated_records:
        return _record_mismatch_message(claimed, reverse, facts)
    nearest = attribution.nearest
    if parts == 2 and nearest is not None and nearest != subject:
        valid_for_nearest = facts.valid_tuples.get(nearest)
        if valid_for_nearest:
            return _mismatch_message(nearest, (claimed[0], claimed[1]), valid_for_nearest)
    stated = _hyphenated(claimed)
    if attribution.parenthetical or len(attribution.named_subjects) == 1:
        # The subject's record with the claim's number of parts; a block
        # stating no `ties` can only answer a three-part claim with two.
        own = _hyphenated(record if record is not None else (own_record.wins, own_record.losses))
        return f"{stated} is not {subject}'s record; {subject}'s record is {own}"
    return f"{stated} is not a stated record"


def _is_stated_game_score(
    claimed: tuple[int, int],
    attribution: _RecordAttribution,
    name_occurrences: list[_NameOccurrence],
    facts: _ClaimFacts,
) -> bool:
    """A two-part claim attributed to a subject may still be a game score:
    one of the nearest name's tuples; bare, one of another named team's; in
    order, any row's game score; in either order, a hyphen pair inside some
    string value (an `explanation` quotes scores that are not always a game
    tuple of the block).
    """
    nearest = attribution.nearest
    if nearest is not None and claimed in facts.valid_tuples.get(nearest, set()):
        return True
    if not attribution.parenthetical and any(
        claimed in facts.valid_tuples.get(other, set())
        for other, _ in name_occurrences
        if other != nearest
    ):
        return True
    if claimed in facts.game_scores:
        return True
    return (min(claimed), max(claimed)) in facts.string_value_pairs


def _check_w_l_t_record(claimed: tuple[int, int, int], facts: _ClaimFacts) -> str | None:
    """A three-part claim is grounded only as a subject's `(wins, losses,
    ties)`, in order. Its reverse swaps wins and losses and keeps ties."""
    if claimed in facts.subject_w_l_t_records:
        return None
    wins, losses, ties = claimed
    return _record_mismatch_message(claimed, (losses, wins, ties), facts)


def _check_reversed_record(claimed: tuple[int, int], facts: _ClaimFacts) -> str | None:
    """A two-part claim (already known not to be a subject record) that is a
    subject's `(wins, losses)` backwards -- unless it is a real game score in
    that order, or a hyphen pair inside some string value in either order,
    which fall through to the attribution / unattributed rules instead."""
    swapped = (claimed[1], claimed[0])
    if (
        swapped not in facts.subject_records
        or claimed in facts.game_scores
        or (min(claimed), max(claimed)) in facts.string_value_pairs
    ):
        return None
    return _record_mismatch_message(claimed, swapped, facts)


def _check_unattributed_pair(claimed: tuple[int, int], facts: _ClaimFacts) -> str | None:
    """A two-part claim in a sentence naming no team: grounded if the block
    states it anywhere, as a game score (either order), as a pair inside a
    string value (either order), or as some object's `(wins, losses)` (in
    order)."""
    swapped = (claimed[1], claimed[0])
    if claimed in facts.game_scores or swapped in facts.game_scores:
        return None
    if (min(claimed), max(claimed)) in facts.string_value_pairs:
        return None
    if claimed in facts.object_records:
        return None
    return f"{claimed[0]}-{claimed[1]} is not a score from any game in the facts"


def _record_mismatch_message(
    claimed: tuple[int, ...], reverse: tuple[int, ...], facts: _ClaimFacts
) -> str:
    """Retry feedback for a record claim (issue #181). Names whose record
    `reverse` is only when exactly one named subject owns it; never says the
    claim "should be stated" as the reverse, since which team the sentence
    is about is attribution, which `_check_attributed_record` (#166) settles
    only when the sentence names a subject, and this message is also used
    when it does not."""
    stated = _hyphenated(claimed)
    owners = facts.record_owners.get(reverse, ())
    if len(owners) == 1 and owners[0] is not None:
        return f"{stated} is not a stated record; {owners[0]}'s record is {_hyphenated(reverse)}"
    return f"{stated} is not a stated record"


def _hyphenated(parts: tuple[int, ...]) -> str:
    return "-".join(str(part) for part in parts)


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


# ---------------------------------------------------------------------------
# Rating attribution (issue #166; see the module docstring's #166 rules)
# ---------------------------------------------------------------------------


def _find_rating_mismatches(
    response_text: str, known_team_names: list[str], numbers: _NumberFacts
) -> set[str]:
    """For every response number grounded only as a rating, sentence by
    sentence, in a sentence that names at least one team: attribute it to
    its nearest name (parenthetical within `_PROXIMITY_WINDOW`, bare at any
    distance) and require it to be that name's rating -- exactly, rounded
    (#162) or as displayed (#165) -- or, bare, another named team's, or,
    bare on a comparison, the other compared team's beside the named team's
    (`_is_comparison_statement`, round 3).
    """
    mismatches: set[str] = set()
    for sentence in _split_sentences(response_text):
        name_occurrences = _name_occurrences(sentence, known_team_names)
        if not name_occurrences:
            continue
        rating_tokens: list[_RatingToken] = [
            (token_match.span(), token_match.group())
            for token_match in _RESPONSE_NUMBER_RE.finditer(sentence)
            if _is_rating_only(token_match.group(), numbers)
        ]
        bare_tokens = [
            (span, token) for span, token in rating_tokens if not _is_parenthesized(sentence, span)
        ]
        for span, token in rating_tokens:
            mismatch = _check_rating_claim(
                sentence, span, token, name_occurrences, numbers, bare_tokens
            )
            if mismatch is not None:
                mismatches.add(mismatch)
    return mismatches


def _is_rating_only(token: str, numbers: _NumberFacts) -> bool:
    """Grounded by the membership rules, but not a number token of the block
    once its rating literals are blanked out: only a rating grounds it, so
    the sentence's attribution of it can be checked. An id, rank, year or
    week token that shares a rating's digits is grounded either way and
    never attributed (epic #199).
    """
    plain = token.replace(",", "")
    return plain not in numbers.non_rating_numbers and _is_grounded_number(
        token, numbers.fact_numbers, numbers.rating_values, numbers.display_values
    )


def _check_rating_claim(
    sentence: str,
    token_span: tuple[int, int],
    token: str,
    name_occurrences: list[_NameOccurrence],
    numbers: _NumberFacts,
    bare_tokens: list[_RatingToken],
) -> str | None:
    plain = token.replace(",", "")
    parenthetical = _is_parenthesized(sentence, token_span)
    nearest = _nearest_name(token_span, name_occurrences)
    if nearest is None:
        return None
    name, distance = nearest
    if parenthetical and distance > _PROXIMITY_WINDOW:
        return None

    values = numbers.ratings_by_name.get(name)
    if not values:
        # No rating stated for this name: nothing to hold the claim to,
        # like a score beside a name with no game data.
        return None
    if any(_rating_matches(plain, value, numbers.method) for value in values):
        return None
    if not parenthetical and any(
        _rating_matches(plain, value, numbers.method)
        for other, _ in name_occurrences
        if other != name
        for value in numbers.ratings_by_name.get(other, set())
    ):
        return None
    if not parenthetical and _is_comparison_statement(
        plain, token_span, name, name_occurrences, numbers, bare_tokens
    ):
        return None

    if len(values) > 1:
        return f"{token} is not {name}'s rating"
    (value,) = values
    own = _rating_as_claimed(plain, value, numbers)
    return f"{token} is not {name}'s rating; {name}'s rating is {own}"


def _is_comparison_statement(
    plain: str,
    token_span: tuple[int, int],
    nearest_name: str,
    name_occurrences: list[_NameOccurrence],
    numbers: _NumberFacts,
    bare_tokens: list[_RatingToken],
) -> bool:
    """Whether a bare rating-only token that failed the nearest-name check
    and the bare rescue is half of a comparison statement (issue #166, round
    3; see the module docstring): on a block with two rated subjects, it
    states the rating of the subject S2 that is *not* its nearest name, and
    another bare rating-only token in the sentence states the other subject
    S1's rating, where S1 is that token's nearest subject mention. Never for
    a parenthetical token (the caller's check), never with a parenthetical
    partner (`bare_tokens` excludes them), and never on a one-subject block
    (`compared_ratings` is empty there). A lone token has no partner, so
    "Elo has Texas at 1892" is never grounded this way.
    """
    compared = numbers.compared_ratings
    if len(compared) != 2:
        return False
    subject_mentions = [occurrence for occurrence in name_occurrences if occurrence[0] in compared]
    for other_subject, other_rating in compared.items():
        if other_subject == nearest_name or not _rating_matches(
            plain, other_rating, numbers.method
        ):
            continue
        (named_subject,) = (subject for subject in compared if subject != other_subject)
        for partner_span, partner in bare_tokens:
            if partner_span == token_span:
                continue
            if not _rating_matches(
                partner.replace(",", ""), compared[named_subject], numbers.method
            ):
                continue
            partner_subject = _nearest_name(partner_span, subject_mentions)
            if partner_subject is not None and partner_subject[0] == named_subject:
                return True
    return False


def _rating_matches(plain_token: str, rating: Decimal, method: Method | None) -> bool:
    """Whether the (ungrouped) token states `rating`: the exact value, its
    display value under `method` (#165), or a rounding of it (#162)."""
    if Decimal(plain_token) == rating:
        return True
    if method is not None and display_value(rating, method) == plain_token:
        return True
    return _is_rounding_of(plain_token, rating)


def _rating_as_claimed(plain_token: str, rating: Decimal, numbers: _NumberFacts) -> str:
    """`rating` in the form the token matched some rating under, so the
    retry feedback compares like with like: the display value when the
    token is a display value of the block, else rounded half away from zero
    to the token's decimal places when the token is a rounding of some
    rating, else the exact literal.
    """
    if numbers.method is not None and plain_token in numbers.display_values:
        return display_value(rating, numbers.method)
    places = _decimal_places(Decimal(plain_token))
    if places < _decimal_places(rating) and any(
        _is_rounding_of(plain_token, value) for value in numbers.rating_values
    ):
        try:
            rounded = abs(rating).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
        except InvalidOperation:
            return format(rating, "f")
        return format(rounded, "f")
    return format(rating, "f")
