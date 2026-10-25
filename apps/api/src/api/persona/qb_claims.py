"""Typed claims for the QB-vs-QB narration (issue #451, epic #439 step 2).

The QB narrator answers with the same forced `submit_narration` tool call as
the team narrator, `{text, claims[]}`, and the same rule holds: it types no
number. Every score, margin, year, count and record in `text` is a `{id}`
placeholder whose claim this module resolves against the QB FACT BLOCK
(exactly `api.persona.service.qb_fact_block_json`) and prints. A claim the
block doesn't back is an error naming what the block does hold, and the
errors are the retry feedback, through the same `narrate_checked` loop as the
team verdicts.

**What is shared with the team check** (`api.persona.claims`): the
placeholder syntax and masking, the quoting, and the typed-number rules
(`typed_number_matches`: digits, number words, number-word records and
ordinals from "second" up), so the two paths reject exactly the same typed
numbers. The claim kinds, the name rules and the block are this module's own:
a quarterback comparison has no teams, games or ratings, and the team kinds
are not accepted here.

**The kinds** (kept few):

* `score` {player, measure}: a QB's career or peak score, two decimals,
  signed only when negative ("2.25", "-1.92").
* `margin` {measure, player}: how far the measure's winner is ahead, two
  decimals and unsigned, where `player` must be the one ahead. It is the
  difference of the two scores as printed, so it always matches the two
  numbers on screen; two scores that print the same have no margin to state.
* `winner` {measure}: the measure's winner, printed by name, or with measure
  "both" the one QB who takes career and peak (rejected on a split). The
  verdict itself, so the narrator can't name the wrong one.
* `year` {}: the first season the score can count (1999 for the NFL).
* `career_start` {player}: the first season of the player's real career.
* `count` {of}: `qualifying_seasons` (with `player`), `min_dropbacks` (the
  qualifying line) or `peak_seasons`, AP style ("one", "224").
* `record` {player, season_type}: his starter W-L(-T) over the seasons the db
  holds; `head_to_head` {player, season_type}: his starter record against the
  other one. Color only: the prompt says the score never counted wins.

**Names.** A player is written exactly as the block spells `display_name`,
or as its `short_name` (the last-name form, null when it would be ambiguous,
`api.models.qb_short_names`). A claim's `player` must be one of those forms.
In the prose, a name form in another case ("WARNER", "Mcnair"), a close
misspelling of one ("Warnr"), or a player's other word alone ("Kurt", or
"Manning" when the two share it) is rejected, and so is the full name of any
other player in the sport's catalog ("Marshall Faulk", "Marshall Faulk's").
A word that opens any sentence, not just the first (#457), is never taken for
a misspelled name ("Meaning", "Warned", "Stove"), and a first name alone that
opens one is let through,
because it is as often an English word ("Will", for Will Levis); a lowercase
name is prose; another player's last name alone ("Brady") is not caught.
Those are accepted gaps.

A score, record or head-to-head prints its player's name ("McNair 0.60")
unless the nearest player reference before it in the sentence (a name typed
in the prose, or a placeholder that refers to a player) is that player
("McNair sits at 0.60"), so a figure can't sit beside the wrong player. A
`career_start` or a count of qualifying seasons prints no name, so it is an
error when the last player reference before it is the other player. That
reference carries across a sentence break ("Warner? His career started in
{cs}" can't be McNair's); with none before it at all, it passes. A margin
prints no name either, and the player the prose puts ahead by it must be its
winner: the last player named, unless he trails ("McNair trails by {m}") or
is the object of a verb ("{wb} beats McNair by {m}"), #457. So "McNair's
ahead by {m}" and "McNair, by {m}" are rejected. The verdict backstop also
reads a margin after a win verb as a mention of its measure.

**The verdict goes through claims** (D1 on #451). Every narration holds a
`year` claim; a conclusive one holds one `winner` both claim or a `winner`
career plus a `winner` peak claim (a measure that is exactly level has none
to claim). The backstop on a verdict typed in prose: within one sentence, a
player reference, then a win verb ("takes", "wins", "edges", "beats", "tops",
"grabs", "owns", "is ahead", "leads", "has the better"), then "career" or
"peak" a few words on in the same clause, is rejected when that player isn't
that measure's winner, and always on an inconclusive block. "Warner takes the
career" passes for the winner; "Nobody beats Warner on the career" has no
subject and passes. #457 added the shapes that slipped past it: "McNair is
the career winner", "The career goes to McNair", "McNair takes it: career
and peak" (a colon after a bare object carries on to the measures), and
"McNair? He takes the career" (a lone "he" is the one player the sentence
before named; after a sentence naming both, it is not caught).

**Margin size** (the coordinator's voice call on #457): any margin is still
a win, and the words scale with it. Each measure's printed margin falls in a
band (`MARGIN_BANDS`: close, clear or decisive) that the fact block states
next to the margin. A runaway phrase ("runs away", "blowout", "in a walk")
on a measure that isn't decisive, or a photo-finish phrase ("by a nose", "a
photo finish") on one that isn't close, is rejected, and so is either on a
dead-level measure. A phrase speaks of the measure named nearest it in its
clause, else in its sentence, else of both.

**The voice rules a check can see** (the coordinator's voice call on #451):
there is always a winner, so a hedge that withholds the verdict ("too close
to call", "toss-up", "basically even", "dead heat", "coin flip", "can't
separate them", "even steven") is rejected; speculation about the seasons
the data doesn't hold ("would've flipped", "if we had his rookie year",
"could swing it", "a different story", "give him those years back") is
rejected, unless a negator heads its clause ("nothing would change that")
or it is the idiom ("that might change your mind"), and "a different story"
only as a conditional ("it'd be a different story", "a different story
if ..."); z-score jargon is rejected; a Roman numeral ("Super Bowl XXXIV")
is rejected as a number (QB path only, D3), as a whole valid numeral word
("LIVID" is not one). On an inconclusive block a
`winner` or `margin` claim is rejected, and so is a score for the side with
no qualifying season. A starter record used to argue with the score is the
prompt's job, not a check here.

Pure: no IO, no database, no network, no logging. `QB_GROUNDING_VERSION` is
these rules' version in the QB cache key.
"""

from __future__ import annotations

import bisect
import json
import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Final, Literal, cast

from api.persona.claims import (
    ID_PATTERN,
    ID_RE,
    MASK,
    PLACEHOLDER_RE,
    SENTENCE_BREAK_RE,
    SURROGATE,
    TOOL_NAME,
    ClaimOutcome,
    ap_number,
    has_surrogate,
    quote,
    type_name,
    typed_number_matches,
)

# These rules' version in the QB narration cache key
# (`api.persona.cache.qb_cache_key`): bump it when a change could accept or
# reject a QB narration differently.
QB_GROUNDING_VERSION: Final = "qb-claims-v2"

# The verdict alone takes two or three claims (the winners and the year, D1
# on #451), so the cap leaves room for a few figures on top.
MAX_QB_CLAIMS: Final = 8

QB_KINDS: Final[tuple[str, ...]] = (
    "score",
    "margin",
    "winner",
    "year",
    "career_start",
    "count",
    "record",
    "head_to_head",
)
MEASURES: Final[tuple[str, ...]] = ("career", "peak")
# A `winner` claim also takes "both": one QB who wins career and peak (D1).
WINNER_MEASURES: Final[tuple[str, ...]] = (*MEASURES, "both")
SEASON_TYPES: Final[tuple[str, ...]] = ("regular", "postseason")
QB_COUNT_OF: Final[tuple[str, ...]] = ("qualifying_seasons", "min_dropbacks", "peak_seasons")

_KEYS_BY_KIND: Final[Mapping[str, tuple[str, ...]]] = {
    "score": ("id", "kind", "player", "measure"),
    "margin": ("id", "kind", "measure", "player"),
    "winner": ("id", "kind", "measure"),
    "year": ("id", "kind"),
    "career_start": ("id", "kind", "player"),
    "count": ("id", "kind", "of", "player"),
    "record": ("id", "kind", "player", "season_type"),
    "head_to_head": ("id", "kind", "player", "season_type"),
}

Side = Literal["a", "b"]
_SIDES: Final[tuple[Side, Side]] = ("a", "b")
_OTHER: Final[Mapping[Side, Side]] = {"a": "b", "b": "a"}
_CENT: Final = Decimal("0.01")

# How a resolved placeholder relates to the players around it (module
# docstring): "name" prints its player's name unless the sentence just named
# him; "attributed" prints no name and must not follow the other player;
# "reference" (a winner) counts as naming its player; "none" changes nothing.
_Mode = Literal["name", "attributed", "reference", "none"]


@dataclass(frozen=True)
class _ClaimMeasure:
    kind: str
    measures: tuple[str, ...]


# The hedges that withhold the verdict (voice call on #451: always a winner).
_HEDGE_RE: Final = re.compile(
    r"\btoo\s+close\s+to\s+call\b|\btoss[\s-]?ups?\b|\bbasically\s+(?:even|tied|a\s+tie)\b"
    r"|\bdead\s+(?:heat|even)\b|\bcoin[\s-]?flips?\b|\bcall\s+it\s+(?:even|a\s+draw|a\s+tie)\b"
    # D2 on #451, the prompt-engineer's probes. "Nobody gets to call it a
    # toss-up" is a known, accepted false positive.
    r"|\bcan(?:'t|’t|not)\s+(?:separate|split)\s+(?:them|these\s+two|the\s+two|'em)\b"
    r"|\bno\s+separating\b|\beven[\s-]steven\b",
    re.IGNORECASE,
)
_HEDGE_ERROR: Final = (
    "there is always a winner on this score unless the FACT BLOCK says inconclusive: any "
    'margin counts, so say who took it ("by a nose" and "a photo finish" fit a close margin '
    "only)"
)
# Speculating about the seasons the data doesn't hold (#231: that's arguing
# with the math).
_SPECULATION_RE: Final = re.compile(
    r"\bwould(?:'ve|’ve|\s+have)\s+(?:flipped|changed|swung|won|turned|been\s+different)\b"
    # The listener shape "if you had McNair, you'd be crying" is exempted in
    # `_speculation_matches` (#457 round 3), not here.
    r"|\bif\s+(?:we|they|you|the\s+books?)\s+(?:had|counted|included)\b"
    r"|\bwith\s+(?:those|the\s+missing|his\s+early|his\s+missing)\s+(?:years|seasons)\b"
    # D2 on #451.
    # "That might change your mind" is about the listener, not the seasons
    # (#457).
    r"|\b(?:could|might|would)(?:\s+easily)?\s+(?:swing|flip|change)\b"
    r"(?!\s+(?:your|his|my|their|our|anybody['’]s|anyone['’]s|somebody['’]s|someone['’]s)"
    r"\s+minds?\b)"
    r"|\bgive\s+(?:[\w'’]+\s+){1,5}(?:years?|seasons?)\s+back\b",
    re.IGNORECASE,
)
# A would/could/might speculation behind a negator is the math holding, not
# arguing with it ("nothing would change that", "no amount of whining could
# change it", #457): it passes when a negator sits within a few words before
# the modal in the same clause.
_MODAL_RE: Final = re.compile(r"\b(?:would|could|might)\b", re.IGNORECASE)
_NEGATOR_RE: Final = re.compile(
    r"\b(?:nothing|nothin|nobody|no|none|never|not)\b|n['’]t\b", re.IGNORECASE
)
_NEGATOR_WORDS: Final = 4
# "A different story" is speculation only as a conditional (#457): "it'd be
# a different story", "different story if/with ...", or a conditional cue
# earlier in its clause ("With his early stuff it's a different story").
# "McNair's a different story." is just the next topic.
_DIFFERENT_STORY_RE: Final = re.compile(r"\bdifferent\s+story\b", re.IGNORECASE)
_STORY_AFTER_RE: Final = re.compile(r"\s+(?:if|with|once|given|had)\b", re.IGNORECASE)
_STORY_CUE_RE: Final = re.compile(
    r"\b(?:if|with|give|count|counting|add|had|would|could|might|be)\b|['’]d\b",
    re.IGNORECASE,
)
# A Roman numeral ("Super Bowl XXXIV") is a number too, and the QB block holds
# no Super Bowls (D3 on #451). QB path only: the team path's rules are
# untouched. A whole uppercase word of two or more numeral letters that is a
# valid numeral, never an empty match: "DID", "LIVID" and "LCD" are not
# numerals (#457). The valid numerals of 400 or more that are everyday
# abbreviations ("DC", "MD", "CD") are no game number and pass; "XL" is
# Super Bowl XL and doesn't.
_ROMAN_RE: Final = re.compile(
    r"\b(?=[MDCLXVI]{2,}\b)M{0,4}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})(?!\w)"
)
_ROMAN_ABBREVIATIONS: Final = frozenset({"DC", "MD", "CD"})
_ROMAN_ERROR: Final = (
    "a Roman numeral is a number, and the FACT BLOCK holds no Super Bowls or numbered "
    "games, so leave it out"
)
# D1's backstop: a win verb after a player, then a measure (`_verdict_backstop`).
_WIN_VERB_RE: Final = re.compile(
    r"\b(?:takes|wins|edges|beats|tops|grabs|owns|is\s+ahead|leads|has\s+the\s+better)\b"
    # "McNair is the career winner", "McNair's the peak king" (#457): the
    # measure sits inside the verb, so the window starts at the verb.
    r"|(?:\bis|['’]s)\s+the\s+(?:(?:career|peak)\s+)?(?:winner|leader|champ|champion|king)\b",
    re.IGNORECASE,
)
_MEASURE_RE: Final = re.compile(r"\b(?:career|peak)\b", re.IGNORECASE)
_MEASURE_WINDOW: Final = 6
_CLAUSE_END_RE: Final = re.compile(r"[,;:—–()]|\s-\s|\b(?:but|while|though|not)\b", re.IGNORECASE)
_AND_BEFORE_RE: Final = re.compile(r"\b(?:and|while)\s+\Z", re.IGNORECASE)
# "McNair takes it: career and peak" (#457): after a bare object, a colon or
# dash introduces the measures instead of ending the clause.
_OBJECT_COLON_RE: Final = re.compile(
    r"\s+(?:it|both|them|it\s+all|everything)\s*(?:[:—–]|\s-\s)", re.IGNORECASE
)
# "McNair? He takes the career" (#457): a pronoun alone before the verb is
# the last player named, even in the sentence before.
_PRONOUN_SUBJECT_RE: Final = re.compile(
    r"(?:(?:and|but|so|yeah|now|look|sure|oh|well)[,]?\s+)?he", re.IGNORECASE
)
# "The career goes to McNair" (#457): a measure handed to a player.
_GOES_TO_RE: Final = re.compile(
    r"\b(?P<measure>career|peak)(?:\s+(?:score|crown|title|race|side))?\s+"
    r"(?:goes|went|belongs|falls|fell)\s+to\b",
    re.IGNORECASE,
)
# Who a margin belongs to (`_margin_holder`, #457 round 2): a trail word
# between the last name and the margin makes the other player the one ahead;
# a verb or "over" right before the last name makes it an object.
_TRAIL_RE: Final = re.compile(
    r"\b(?:trails?|trailed|trailing|behind|short|lags?|lagged|lagging|loses|lost|down)\b"
    # The passive (#457 round 3): "McNair gets beat by {m}".
    r"|\b(?:gets?|got|was|is|been|getting)\s+beat(?:en)?\b",
    re.IGNORECASE,
)
# A trail word right after the margin: "McNair falls {m} short", "finishes
# {m} behind" (#457 round 3).
_TRAIL_AFTER_RE: Final = re.compile(r"\s+(?:short|behind|back)\b", re.IGNORECASE)
_OBJECT_BEFORE_RE: Final = re.compile(
    r"\b(?:beats|beat|beating|tops|topped|topping|edges|edged|edging|over|past|than"
    r"|outplays|outplayed|outscores|outscored|outdoes|outdid|leads|led|ahead\s+of"
    r"|in\s+front\s+of|clears|cleared)\s+\Z",
    re.IGNORECASE,
)
# A coordinated new verb starts its own attribution for margin words (#457
# round 2): "runs away with the career and takes the peak".
_COORDINATED_VERB_RE: Final = re.compile(
    r"\b(?:and|then)\s+(?:then\s+)?(?:he\s+)?"
    r"(?!(?:his|its|this|thus|as|us|plus|less|yes)\b)"
    r"(?:[a-z]+(?:s|ed)|took|won|ran|got|had|is|was)\b",
    re.IGNORECASE,
)
# An appositive list of measures after the clause ("runs away with it,
# career and peak"; "with the career, and the peak too"): the phrase covers
# every listed measure, as the backstop's colon rule does (#457 round 2).
_APPOSITIVE_RE: Final = re.compile(
    r"\s*(?:[,:—–]|\s-\s)\s*(?P<list>(?:(?:and|the|both|too|also|career|peak)\b[\s,]*)+?)"
    r"(?=[.!?;,]|\s*\Z)",
    re.IGNORECASE,
)
# A negated extreme is no use of it ("no photo finish here", "this was no
# squeaker", "doesn't run away with it", "forget by a nose"; #457 round 2).
# The negator must govern the phrase: right before it, with at most an
# auxiliary, "even" or "a" between (round 3), so "No doubt Manning runs away"
# is still a runaway.
_MARGIN_NEGATOR_RE: Final = re.compile(
    r"(?:\b(?:no|not|never|nobody|forget|nothing\s+like)|n['’]t)\s+"
    r"(?:(?:even|a|an|is|was|be|been|do|does|did|really|ever|just)\s+){0,2}\Z",
    re.IGNORECASE,
)
# A clause that opens on an imperative conditional ("Give him those years and
# it's a different story") governs the clause it is coordinated with.
_IMPERATIVE_CUE_RE: Final = re.compile(
    r"\s*(?:give|count|add|throw|put|hand|toss|let|credit)\b", re.IGNORECASE
)
_AND_RE: Final = re.compile(r"\band\b", re.IGNORECASE)
# The listener shape of "if you had": "If you had McNair, you'd be crying"
# (#457 round 3) is about the fan, not the missing seasons.
_IF_YOU_HAD_RE: Final = re.compile(r"if\s+you\s+had", re.IGNORECASE)

# Margin size (the coordinator's voice call on #457, 2026-10-25): any margin
# is a win, and the words scale with it. Each measure's margin, as printed
# (the difference of the two printed scores), falls in a band on fixed
# thresholds, inclusive on the upper band:
#   career: close < 1.5 <= clear < 7.5 <= decisive
#   peak:   close < 0.15 <= clear < 0.75 <= decisive
# About 0.24 and 1.2 standard deviations of each measure's spread over the
# 26 notable QBs sampled from production on 2026-10-25 (career pstdev 6.29,
# peak 0.64: the two differ in scale by about 10x, so one threshold can't
# serve both). Over those 325 pairs |career margin| p10/p25/p50/p75 =
# 1.28/3.17/5.89/10.55 and |peak margin| = 0.13/0.31/0.64/1.05.
MarginBand = Literal["close", "clear", "decisive"]
MARGIN_BANDS: Final[Mapping[str, tuple[Decimal, Decimal]]] = {
    "career": (Decimal("1.5"), Decimal("7.5")),
    "peak": (Decimal("0.15"), Decimal("0.75")),
}
# Runaway words fit a decisive margin only, photo-finish words a close one
# only; a clear margin takes neither.
_RUNAWAY_RE: Final = re.compile(
    r"\b(?:runs|ran|running|run)\s+away\b|\brunaway\b|\bblow[\s-]?outs?\b"
    r"|\b(?:blows|blew|blowing|blow)\s+(?:[\w'’]+\s+)?out\b|\bno\s+contest\b"
    # The adjective only ("it isn't close", "wasn't even close"), never the
    # verb with an object ("can't close the gap", "couldn't close it out")
    # or "close to" (#457 round 2).
    r"|(?:\bnot|n['’]t)\s+(?:even\s+)?close\b"
    r"(?!\s+(?:to|the|a|an|it|out|that|this|his|her|their|them|him|ground|in|down|off|any"
    r"|gaps?|distance|deals?|shop|up)\b)"
    r"|(?<!victory\s)\blaps\b|\blapped\b|\blapping\b|\blandslide\b|\brout(?:s|ed)?\b"
    r"|\b(?:buries|buried|burying)\b|\b(?:walks|walked|walking)\s+away\s+with\b"
    r"|\bin\s+a\s+walk\b|\bby\s+(?:a\s+mile|miles)\b|\bmiles\s+ahead\b|\bcakewalk\b"
    # The review's probes (#457 round 2).
    r"|\bgoing\s+away\b|\b(?:cruises|cruised|cruising)\b",
    re.IGNORECASE,
)
_PHOTO_FINISH_RE: Final = re.compile(
    r"\bphoto[\s-]finish\b|\bby\s+a\s+(?:nose|hair|whisker|eyelash)\b|\brazor[\s-]thin\b"
    r"|\bcoin[\s-]?flips?\b|\bsqueak(?:s|ed|ing|er)?\b|\bneck\s+and\s+neck\b"
    r"|\bnip\s+and\s+tuck\b|\bskin\s+of\s+his\s+teeth\b"
    # "barely" only as a near-miss win ("barely takes the peak"), never
    # "barely qualified".
    r"|\bbarely\s+(?:[\w'’]+\s+)?(?:edges?|edged|beats?|takes?|took|wins?|won|tops?|topped"
    r"|gets?|got|ahead|nips?|nipped|grabs?|grabbed|holds?\s+on|held\s+on|pulls?|pulled)\b",
    re.IGNORECASE,
)
_SPECULATION_ERROR: Final = (
    "never speculate about the missing seasons: the score counts only the seasons in the "
    "books, so say what got counted, never what the missing seasons would do"
)
_JARGON_RE: Final = re.compile(
    r"\bz[\s-]?scores?\b|\bstandard\s+deviations?\b|\bsigmas?\b", re.IGNORECASE
)
_JARGON_ERROR: Final = (
    "explain the score in bar words (efficiency per play, measured against the QBs of his "
    "own season), with no z-score or standard-deviation talk"
)

# A word of a name: letters, with inner apostrophes ("O'Connell").
_WORD_RE: Final = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*")
_POSSESSIVE_RE: Final = re.compile(r"['’]s$")
# What may sit between two words of one name: "A.J. Brown", "Amon-Ra St. Brown".
_NAME_GAP_RE: Final = re.compile(r"[ .\-‐‑]{1,3}")
_MAX_NAME_WORDS: Final = 4


@dataclass(frozen=True)
class _Record:
    wins: int
    losses: int
    ties: int
    starts: int

    @property
    def text(self) -> str:
        if self.ties:
            return f"{self.wins}-{self.losses}-{self.ties}"
        return f"{self.wins}-{self.losses}"

    def flipped(self) -> _Record:
        return _Record(self.losses, self.wins, self.ties, self.starts)


@dataclass(frozen=True)
class _Player:
    side: Side
    name: str
    short: str | None
    scores: Mapping[str, Decimal | None]
    qualifying_seasons: int
    career_first_season: int | None
    cut_off_before: bool
    records: Mapping[str, _Record | None]
    head_to_head: Mapping[str, _Record]

    @property
    def forms(self) -> tuple[str, ...]:
        return (self.name,) if self.short is None else (self.name, self.short)

    @property
    def called(self) -> str:
        """How a placeholder prints him: the short name when there is one."""
        return self.short or self.name

    @property
    def described(self) -> str:
        return self.name if self.short is None else f"{self.name} (or {self.short})"


@dataclass(frozen=True)
class _QbBlock:
    players: Mapping[Side, _Player]
    winners: Mapping[str, Side | None]
    inconclusive: str | None
    min_dropbacks: int
    peak_seasons: int
    data_first_season: int | None

    def unqualified(self) -> list[_Player]:
        return [p for p in self.players.values() if p.scores["career"] is None]

    def verdict_text(self) -> str:
        """The verdict in words, for feedback: who takes which measure."""
        if self.inconclusive is not None:
            names = " and ".join(p.name for p in self.unqualified())
            return f"the verdict is inconclusive ({names} has no qualifying season)"
        career, peak = self.winners["career"], self.winners["peak"]
        if career is not None and career == peak:
            return f"{self.players[career].called} takes both the career and the peak"
        parts = [
            f"{self.players[side].called} takes the {measure}"
            if side is not None
            else f"the {measure} is dead level"
            for measure, side in (("career", career), ("peak", peak))
        ]
        return f"the two split it: {parts[0]} and {parts[1]}"

    def roster(self) -> str:
        a, b = self.players["a"], self.players["b"]
        return f"{a.described} and {b.described}"

    def holdings(self) -> str:
        items: list[str] = []
        for player in self.players.values():
            facts: list[str] = []
            for measure in MEASURES:
                value = player.scores[measure]
                if value is not None:
                    facts.append(f"{measure} {_score_text(value)}")
            qualifying = player.qualifying_seasons
            facts.append(
                f"{ap_number(qualifying)} qualifying season{'' if qualifying == 1 else 's'}"
            )
            if player.career_first_season is not None:
                facts.append(f"career began {player.career_first_season}")
            for season_type in SEASON_TYPES:
                record = player.records[season_type]
                if record is not None and record.starts:
                    facts.append(f"{_season_words(season_type)} {record.text}")
            items.append(f"{player.name} " + ", ".join(facts))
        a = self.players["a"]
        for measure in MEASURES:
            winner = self.winners[measure]
            if winner is not None:
                ahead = self.players[winner]
                items.append(
                    f"{measure}: {ahead.called} ahead by {self.shown_margin(measure, winner)} "
                    f"({self.band(measure)})"
                )
        if self.inconclusive is not None:
            names = " and ".join(p.name for p in self.unqualified())
            items.append(f"inconclusive: {names} has no qualifying season")
        for season_type in SEASON_TYPES:
            record = a.head_to_head[season_type]
            if record.starts:
                items.append(f"{a.name}'s {_season_words(season_type)} head-to-head {record.text}")
        if self.data_first_season is not None:
            items.append(f"the score counts from {self.data_first_season}")
        items.append(f"a season qualifies at {self.min_dropbacks} dropbacks")
        items.append(f"the peak averages the best {ap_number(self.peak_seasons)} seasons")
        return "The fact block holds: " + "; ".join(items) + "."

    def shown_margin(self, measure: str, winner: Side) -> str:
        high = self.players[winner].scores[measure]
        low = self.players[_OTHER[winner]].scores[measure]
        assert high is not None and low is not None
        return _decimal_text(_shown(high) - _shown(low))

    def band(self, measure: str) -> MarginBand | None:
        """The measure's margin band; None on an exact tie or an
        inconclusive block, which have no margin."""
        if self.inconclusive is not None:
            return None
        a, b = self.players["a"].scores[measure], self.players["b"].scores[measure]
        return qb_margin_band(measure, self.winners[measure], a, b)


def margin_band(measure: str, margin: Decimal) -> MarginBand:
    """The band of a printed `margin` on `measure` (`MARGIN_BANDS`): a
    boundary belongs to the upper band."""
    close_below, decisive_from = MARGIN_BANDS[measure]
    size = abs(margin)
    if size < close_below:
        return "close"
    return "clear" if size < decisive_from else "decisive"


def qb_margin_band(
    measure: str,
    winner: str | None,
    a: Decimal | float | None,
    b: Decimal | float | None,
) -> MarginBand | None:
    """The band of the margin between two scores as the narration prints
    them (two decimals, half up), so the band always matches the margin on
    screen. None when the measure has no winner (an exact tie) or either
    score is missing (inconclusive). The QB fact block
    (`api.persona.service.qb_fact_block_json`) and the check both use it."""
    if winner is None or a is None or b is None:
        return None
    return margin_band(measure, _shown(_decimal(a)) - _shown(_decimal(b)))


def _decimal(value: Decimal | float) -> Decimal:
    # repr is the shortest round-trip form, the same digits the JSON block
    # carries and `_parse_block` reads back.
    return value if isinstance(value, Decimal) else Decimal(repr(value))


def qb_tool_schema() -> dict[str, Any]:
    """The QB verdict's `submit_narration` tool definition, in the Anthropic
    Messages API's `tools` shape. Same name and input shape as the team tool
    (`api.persona.claims.tool_schema`); the claim kinds are the QB ones."""
    return {
        "name": TOOL_NAME,
        "description": (
            "Submit the narration. Write every score, margin, year, count or record as a {id} "
            "placeholder in text, and describe it with one claim; the server prints each value "
            "from the fact block. Name the verdict only through winner claims, and always "
            "include one year claim. The prose itself must contain no digits, no spelled-out "
            "numbers, no Roman numerals and no ordinals from second up, and must write each "
            "quarterback exactly as the fact block spells his display_name or short_name. "
            f"Use at most {MAX_QB_CLAIMS} claims."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The narration, with {id} placeholders for every figure.",
                },
                "claims": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string",
                                "pattern": f"^{ID_PATTERN}$",
                                "description": "The placeholder name used in text as {id}.",
                            },
                            "kind": {
                                "type": "string",
                                "enum": list(QB_KINDS),
                                "description": (
                                    "score, record and head_to_head print the value with "
                                    "the player's name, left off when the last player named "
                                    "before it in the sentence is the same one; winner "
                                    "prints the measure's winner by name (measure both for "
                                    "one QB who takes career and peak); margin takes the "
                                    "player who is ahead; career_start and count print no "
                                    "name, so name their player right before them; count "
                                    "needs of; year takes nothing else."
                                ),
                            },
                            "player": {
                                "type": "string",
                                "description": (
                                    "A quarterback, spelled as the fact block spells his "
                                    "display_name or short_name."
                                ),
                            },
                            "measure": {
                                "type": "string",
                                "enum": list(WINNER_MEASURES),
                                "description": (
                                    "Which score: the whole career or the peak. Only a "
                                    "winner claim takes both."
                                ),
                            },
                            "season_type": {
                                "type": "string",
                                "enum": list(SEASON_TYPES),
                                "description": "Which starter record: regular season or playoffs.",
                            },
                            "of": {
                                "type": "string",
                                "enum": list(QB_COUNT_OF),
                                "description": "What a count counts.",
                            },
                        },
                        "required": ["id", "kind"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["text", "claims"],
            "additionalProperties": False,
        },
    }


def check_and_render_qb(
    tool_input: object,
    fact_block_json: str,
    player_names: Collection[str],
) -> ClaimOutcome:
    """Validate one QB `submit_narration` tool input against the QB fact
    block and, if nothing is wrong, render it.

    `player_names` is every player `display_name` in the sport
    (`api.repositories.players.list_player_names`), used to recognise a third
    player named in the prose. Malformed or hostile tool input only ever
    produces errors. A `fact_block_json` that is not a QB fact block is a
    programming error and raises `ValueError`.
    """
    block = _parse_block(fact_block_json)
    if not isinstance(tool_input, dict):
        return ClaimOutcome(
            errors=(
                f'{TOOL_NAME} input must be an object with "text" and "claims", '
                f"not {type_name(tool_input)}",
            ),
            text=None,
        )

    errors: list[str] = []
    for key in tool_input:
        if has_surrogate(key):
            errors.append(f"{TOOL_NAME} input has a key holding {SURROGATE}")
        elif key not in ("text", "claims"):
            errors.append(f'{TOOL_NAME} does not take {quote(key)}; it takes "text" and "claims"')

    text = tool_input.get("text")
    if "text" not in tool_input:
        errors.append(f'{TOOL_NAME} needs "text"')
    elif not isinstance(text, str):
        errors.append(f'"text" must be a string, not {type_name(text)}')
    elif has_surrogate(text):
        errors.append(f'"text" holds {SURROGATE}')
    elif not text.strip():
        errors.append('"text" is empty')

    raw_claims = tool_input.get("claims")
    rendered: dict[str, str] = {}
    modes: dict[str, tuple[_Mode, Side | None]] = {}
    claim_ids: list[str] = []
    # The resolved claims that carry the verdict: "year", "winner:career",
    # "winner:peak", "winner:both" (D1 on #451: the verdict goes through claims).
    verdict_claims: set[str] = set()
    # The measures a resolved score, margin or winner placeholder speaks of,
    # for the margin-size words and the verdict backstop (#457).
    claim_measures: dict[str, _ClaimMeasure] = {}
    if "claims" not in tool_input:
        errors.append(f'{TOOL_NAME} needs "claims" (a list, which may be empty)')
    elif not isinstance(raw_claims, list):
        errors.append(f'"claims" must be a list of claim objects, not {type_name(raw_claims)}')
    else:
        if len(raw_claims) > MAX_QB_CLAIMS:
            errors.append(
                f"{TOOL_NAME} has {len(raw_claims)} claims, over the limit of {MAX_QB_CLAIMS}; "
                "keep only the figures that make the case"
            )
        duplicated: set[str] = set()
        for position, raw in enumerate(raw_claims):
            if not isinstance(raw, dict):
                errors.append(f"claims[{position}] must be an object, not {type_name(raw)}")
                continue
            claim_id = raw.get("id")
            if any(has_surrogate(key) or has_surrogate(value) for key, value in raw.items()):
                errors.append(f"claims[{position}] holds {SURROGATE}")
                if isinstance(claim_id, str) and ID_RE.fullmatch(claim_id):
                    if claim_id not in claim_ids:
                        claim_ids.append(claim_id)
                continue
            if not isinstance(claim_id, str) or not claim_id:
                errors.append(f'claims[{position}] needs a string "id"')
                continue
            if not ID_RE.fullmatch(claim_id):
                errors.append(
                    f"claims[{position}] id {quote(claim_id)} must be letters, digits and "
                    "underscores, starting with a letter"
                )
                continue
            if claim_id in claim_ids:
                if claim_id not in duplicated:
                    errors.append(f"claim id {quote(claim_id)} is used by more than one claim")
                    duplicated.add(claim_id)
                continue
            claim_ids.append(claim_id)
            resolved, claim_errors = _resolve_claim(claim_id, raw, block)
            errors.extend(claim_errors)
            if resolved is not None:
                value, mode, side = resolved
                rendered[claim_id] = value
                modes[claim_id] = (mode, side)
                kind = raw["kind"]
                verdict_claims.add(f"winner:{raw['measure']}" if kind == "winner" else str(kind))
                if kind in ("score", "margin", "winner"):
                    measure = cast(str, raw["measure"])
                    claim_measures[claim_id] = _ClaimMeasure(
                        kind, MEASURES if measure == "both" else (measure,)
                    )
        errors.extend(_required_claim_errors(verdict_claims, block))

    named_at: set[int] = set()
    if isinstance(text, str) and not has_surrogate(text):
        used = list(dict.fromkeys(match.group(1) for match in PLACEHOLDER_RE.finditer(text)))
        known = ", ".join(quote(claim_id) for claim_id in claim_ids) if claim_ids else "none"
        for placeholder in used:
            if placeholder not in claim_ids:
                errors.append(
                    f"placeholder {{{placeholder}}} has no claim; the claim ids are: {known}"
                )
        for claim_id in claim_ids:
            if claim_id not in used:
                errors.append(f"claim {quote(claim_id)} is not used by any placeholder in the text")
        if MASK in text:
            errors.append("the text contains a NUL character")
        else:
            prose_errors, named_at = _check_prose(text, modes, claim_measures, block, player_names)
            errors.extend(prose_errors)

    if errors or not isinstance(text, str):
        return ClaimOutcome(errors=tuple(dict.fromkeys(errors)), text=None)

    sentence_starts = {len(text) - len(text.lstrip())} | {
        match.end() for match in SENTENCE_BREAK_RE.finditer(text)
    }

    def show(match: re.Match[str]) -> str:
        claim_id = match.group(1)
        figure = rendered[claim_id]
        mode, side = modes[claim_id]
        if mode == "name" and side is not None and match.start() in named_at:
            figure = f"{block.players[side].called} {figure}"
        if match.start() in sentence_starts and figure[:1].islower():
            figure = figure[0].upper() + figure[1:]
        return figure

    return ClaimOutcome(errors=(), text=PLACEHOLDER_RE.sub(show, text))


# ---------------------------------------------------------------------------
# the fact block
# ---------------------------------------------------------------------------


def _parse_block(fact_block_json: str) -> _QbBlock:
    try:
        data = json.loads(fact_block_json, parse_float=Decimal)
        if not isinstance(data, dict) or "qb_score" not in data:
            raise ValueError("no qb_score")
        score = data["qb_score"]
        h2h = {
            "regular": _record(data["regular_season_head_to_head"]),
            "postseason": _record(data["postseason_head_to_head"]),
        }
        players: dict[Side, _Player] = {}
        for side in _SIDES:
            context, side_score = data[side], score[side]
            coverage = context["coverage"]
            records = {
                "regular": _optional_record(context["regular_season_record"]),
                "postseason": _optional_record(context["postseason_record"]),
            }
            players[side] = _Player(
                side=side,
                name=str(context["display_name"]),
                short=None if context["short_name"] is None else str(context["short_name"]),
                scores={
                    "career": _optional_decimal(side_score["career"]),
                    "peak": _optional_decimal(side_score["peak"]),
                },
                qualifying_seasons=int(side_score["qualifying_seasons"]),
                career_first_season=_optional_int(coverage["career_first_season"]),
                cut_off_before=bool(coverage["cut_off_before"]),
                records=records,
                head_to_head=(h2h if side == "a" else {k: r.flipped() for k, r in h2h.items()}),
            )
        winners: dict[str, Side | None] = {}
        for measure in MEASURES:
            winner = score[f"{measure}_winner"]
            if winner not in (None, "a", "b"):
                raise ValueError(f"unknown winner {winner!r}")
            winners[measure] = cast(Side | None, winner)
        return _QbBlock(
            players=players,
            winners=winners,
            inconclusive=None if score["inconclusive"] is None else str(score["inconclusive"]),
            min_dropbacks=int(score["min_dropbacks"]),
            peak_seasons=int(score["peak_seasons"]),
            data_first_season=_optional_int(data["data_first_season"]),
        )
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"not a QB fact block: {exc!r}") from exc


def _record(node: Any) -> _Record:
    return _Record(
        wins=int(node["wins"]),
        losses=int(node["losses"]),
        ties=int(node["ties"]),
        starts=int(node["starts"]),
    )


def _optional_record(node: Any) -> _Record | None:
    return None if node is None else _record(node)


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _optional_decimal(value: Any) -> Decimal | None:
    return None if value is None else Decimal(value)


def _shown(value: Decimal) -> Decimal:
    """A score as printed: two decimals, half up."""
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def _decimal_text(value: Decimal) -> str:
    # Never "-0.00": a score that rounds to zero is level with average.
    return "0.00" if value == 0 else f"{value:.2f}"


def _score_text(value: Decimal) -> str:
    return _decimal_text(_shown(value))


def _season_words(season_type: str) -> str:
    return "regular season" if season_type == "regular" else "postseason"


# ---------------------------------------------------------------------------
# claims
# ---------------------------------------------------------------------------


def _resolve_claim(
    claim_id: str, raw: dict[Any, Any], block: _QbBlock
) -> tuple[tuple[str, _Mode, Side | None] | None, list[str]]:
    where = f"claim {quote(claim_id)}"
    kind = raw.get("kind")
    if not isinstance(kind, str) or kind not in _KEYS_BY_KIND:
        shown = "missing" if "kind" not in raw else quote(kind)
        return None, [f"{where}: unknown kind {shown}; the kinds are {', '.join(QB_KINDS)}"]

    errors = _shape_errors(where, kind, raw)
    if errors:
        return None, errors

    if kind == "year":
        if block.data_first_season is None:
            return None, [f"{where}: the fact block holds no first season to state"]
        return (str(block.data_first_season), "none", None), []
    if kind == "winner":
        return _resolve_winner(where, raw, block)
    if kind == "count" and raw["of"] != "qualifying_seasons":
        if "player" in raw:
            return None, [f'{where}: a count of {raw["of"]} takes no "player"']
        number = block.min_dropbacks if raw["of"] == "min_dropbacks" else block.peak_seasons
        return (ap_number(number), "none", None), []

    player, errors = _player(where, kind, raw, block)
    if player is None:
        return None, errors
    if kind == "score":
        return _resolve_score(where, raw["measure"], player, block)
    if kind == "margin":
        return _resolve_margin(where, raw["measure"], player, block)
    if kind == "career_start":
        if player.career_first_season is None:
            return None, [f"{where}: the fact block holds no career start for {player.name}"]
        return (str(player.career_first_season), "attributed", player.side), []
    if kind == "count":
        return (ap_number(player.qualifying_seasons), "attributed", player.side), []
    season_type = cast(str, raw["season_type"])
    if kind == "record":
        record = player.records[season_type]
        if record is None or record.starts == 0:
            return None, [
                f"{where}: {player.name} has no {_season_words(season_type)} starter record in "
                f"the fact block. {block.holdings()}"
            ]
        return (record.text, "name", player.side), []
    meeting = player.head_to_head[season_type]
    if meeting.starts == 0:
        other = block.players[_OTHER[player.side]]
        return None, [
            f"{where}: {player.name} and {other.name} never met as opposing starters in the "
            f"{_season_words(season_type)}, so there is no head-to-head record to state"
        ]
    return (meeting.text, "name", player.side), []


def _shape_errors(where: str, kind: str, raw: dict[Any, Any]) -> list[str]:
    allowed = _KEYS_BY_KIND[kind]
    errors = [
        f"{where} ({kind}) does not take {quote(key)}; it takes {', '.join(allowed)}"
        for key in raw
        if key not in allowed
    ]
    required = {
        "score": ("player", "measure"),
        "margin": ("measure", "player"),
        "winner": ("measure",),
        "career_start": ("player",),
        "count": ("of",),
        "record": ("player", "season_type"),
        "head_to_head": ("player", "season_type"),
    }.get(kind, ())
    errors.extend(f'{where} ({kind}) needs "{key}"' for key in required if key not in raw)
    if "player" in raw and not isinstance(raw["player"], str):
        errors.append(f'{where}: "player" must be a name string, not {type_name(raw["player"])}')
    if kind == "winner":
        if "measure" in raw and raw["measure"] not in WINNER_MEASURES:
            errors.append(
                f'{where}: a winner\'s "measure" must be career, peak or both, not '
                f"{quote(raw['measure'])}"
            )
    elif "measure" in raw and raw["measure"] not in MEASURES:
        errors.append(f'{where}: "measure" must be career or peak, not {quote(raw["measure"])}')
    if "season_type" in raw and raw["season_type"] not in SEASON_TYPES:
        errors.append(
            f'{where}: "season_type" must be regular or postseason, not {quote(raw["season_type"])}'
        )
    if "of" in raw and raw["of"] not in QB_COUNT_OF:
        errors.append(
            f'{where}: "of" must be one of {", ".join(QB_COUNT_OF)}, not {quote(raw["of"])}'
        )
    if kind == "count" and raw.get("of") == "qualifying_seasons" and "player" not in raw:
        errors.append(f'{where}: a count of qualifying_seasons needs "player"')
    return errors


def _player(
    where: str, kind: str, raw: dict[Any, Any], block: _QbBlock
) -> tuple[_Player | None, list[str]]:
    value = cast(str, raw["player"])
    for player in block.players.values():
        if value in player.forms:
            return player, []
    for player in block.players.values():
        for form in player.forms:
            if form.casefold() == value.casefold():
                return None, [
                    f"{where}: {quote(value)} is not spelled as the fact block spells it; "
                    f"did you mean {quote(form)} ({player.name})?"
                ]
    return None, [
        f"{where}: {quote(value)} is not a player in the fact block; its players are "
        f"{block.roster()}"
    ]


def _inconclusive_error(where: str, block: _QbBlock) -> str:
    names = " and ".join(p.name for p in block.unqualified())
    verb = "have" if len(block.unqualified()) > 1 else "has"
    return (
        f"{where}: the verdict is inconclusive: {names} {verb} no qualifying season (a season "
        f"needs {block.min_dropbacks} dropbacks), so neither measure has a winner or a margin; "
        "name no winner and say the body of work isn't there"
    )


def _required_claim_errors(verdict_claims: Collection[str], block: _QbBlock) -> list[str]:
    """D1 on #451: every narration holds a `year` claim, and a conclusive one
    names its verdict through `winner` claims, either one `winner` both (a
    sweep) or a `winner` career plus a `winner` peak. A measure that is
    exactly level has no winner to claim. The errors say exactly what to add."""
    errors: list[str] = []
    if block.data_first_season is not None and "year" not in verdict_claims:
        errors.append(
            f"add a year claim: every narration says the score only counts from "
            f"{block.data_first_season}"
        )
    if block.inconclusive is not None:
        return errors
    career, peak = block.winners["career"], block.winners["peak"]
    if career is not None and career == peak:
        if "winner:both" in verdict_claims or {"winner:career", "winner:peak"} <= set(
            verdict_claims
        ):
            return errors
        name = block.players[career].called
        errors.append(
            f"name the verdict through a winner claim: {name} takes both the career and the "
            'peak, so add one winner claim with measure "both" (or one for career and one '
            "for peak), and type no winner yourself"
        )
        return errors
    for measure, side in (("career", career), ("peak", peak)):
        if side is not None and f"winner:{measure}" not in verdict_claims:
            errors.append(
                f"name the verdict through winner claims: {block.verdict_text()}, so add a "
                f'winner claim with measure "{measure}" ({block.players[side].called}); '
                "neither measure is the real answer, so say both"
            )
    return errors


def _resolve_winner(
    where: str, raw: dict[Any, Any], block: _QbBlock
) -> tuple[tuple[str, _Mode, Side | None] | None, list[str]]:
    if block.inconclusive is not None:
        return None, [_inconclusive_error(where, block)]
    measure = cast(str, raw["measure"])
    if measure == "both":
        career, peak = block.winners["career"], block.winners["peak"]
        if career is None or career != peak:
            return None, [f"{where}: {block.verdict_text()}, so there is no one winner of both"]
        return (block.players[career].called, "reference", career), []
    winner = block.winners[measure]
    if winner is None:
        return None, [
            f"{where}: the two {measure} scores are exactly equal in the fact block, so "
            "nobody is ahead on it"
        ]
    return (block.players[winner].called, "reference", winner), []


def _resolve_score(
    where: str, measure: str, player: _Player, block: _QbBlock
) -> tuple[tuple[str, _Mode, Side | None] | None, list[str]]:
    value = player.scores[measure]
    if value is None:
        return None, [
            f"{where}: {player.name} has no qualifying season (a season needs "
            f"{block.min_dropbacks} dropbacks), so he has no {measure} score and the "
            "comparison is inconclusive"
        ]
    return (_score_text(value), "name", player.side), []


def _resolve_margin(
    where: str, measure: str, player: _Player, block: _QbBlock
) -> tuple[tuple[str, _Mode, Side | None] | None, list[str]]:
    if block.inconclusive is not None:
        return None, [_inconclusive_error(where, block)]
    winner = block.winners[measure]
    a, b = block.players["a"], block.players["b"]
    if winner is None:
        return None, [
            f"{where}: {a.name} and {b.name} have exactly equal {measure} scores, so there is "
            "no margin to state"
        ]
    ahead, behind = block.players[winner], block.players[_OTHER[winner]]
    high, low = ahead.scores[measure], behind.scores[measure]
    assert high is not None and low is not None
    if player.side != winner:
        return None, [
            f"{where}: on the {measure} {ahead.name} is ahead, {_score_text(high)} to "
            f"{_score_text(low)}; a margin's player is the one ahead, so make it {ahead.called}"
        ]
    if _shown(high) == _shown(low):
        return None, [
            f"{where}: {ahead.name} and {behind.name} print the same {measure} score "
            f"({_score_text(high)}), so there is no margin to state; {ahead.called} is still "
            'ahead, so say he took it without a number ("by a nose")'
        ]
    # Attributed to the winner (R2, #451): "McNair's ahead by {m}" must not
    # print Warner's margin beside McNair. #457 exempts a loser who trails or
    # is the object of the winner's verb (`_margin_beside_loser_is_true`):
    # "{wb} beats McNair by {m}" and "McNair trails by {m}" are true. The
    # verdict backstop also reads a margin after a win verb as a mention of
    # its measure ("McNair is ahead by {m}").
    return (block.shown_margin(measure, winner), "attributed", winner), []


# ---------------------------------------------------------------------------
# the prose outside the placeholders
# ---------------------------------------------------------------------------


def _check_prose(
    text: str,
    modes: Mapping[str, tuple[_Mode, Side | None]],
    claim_measures: Mapping[str, _ClaimMeasure],
    block: _QbBlock,
    player_names: Collection[str],
) -> tuple[list[str], set[int]]:
    """The errors in the prose outside the placeholders, and the offsets of
    the name-printing placeholders that must print their player's name."""
    placeholders = list(PLACEHOLDER_RE.finditer(text))
    masked = PLACEHOLDER_RE.sub(lambda match: MASK * len(match.group(0)), text)
    errors: list[str] = []
    if "{" in masked or "}" in masked:
        errors.append('the text has a "{" or "}" that is not part of a placeholder like {id}')

    breaks = [match.end() for match in SENTENCE_BREAK_RE.finditer(masked)]
    holdings = block.holdings()
    for what, match, rule in typed_number_matches(masked):
        errors.append(f"the prose {what} {quote(match.group(0))}; {rule}. {holdings}")
    for match in _HEDGE_RE.finditer(masked):
        errors.append(f"the prose says {quote(match.group(0))}; {_HEDGE_ERROR}")
    names = [form for player in block.players.values() for form in player.forms]
    for match in _speculation_matches(masked, breaks, names):
        errors.append(f"the prose says {quote(match.group(0))}; {_SPECULATION_ERROR}")
    for match in _JARGON_RE.finditer(masked):
        errors.append(f"the prose says {quote(match.group(0))}; {_JARGON_ERROR}")
    # A block player's own suffix ("Robert Griffin III") is his name, not a number.
    roman_text = masked
    for player in block.players.values():
        roman_text = roman_text.replace(player.name, MASK * len(player.name))
    for match in _ROMAN_RE.finditer(roman_text):
        if not match.group(0) or match.group(0) in _ROMAN_ABBREVIATIONS:
            continue
        errors.append(f"the prose types the Roman numeral {quote(match.group(0))}; {_ROMAN_ERROR}")

    third = _third_players(masked, block, player_names)
    for _, _, name in third:
        errors.append(
            f"{quote(name)} is not a player in this fact block; it names only {block.roster()}, "
            "so leave other players out"
        )
    references, name_errors = _name_references(masked, block, [(s, e) for s, e, _ in third])
    errors.extend(name_errors)

    walk: list[tuple[int, Side | None, str | None]] = sorted(
        [(start, side, None) for start, side in references]
        + [(match.start(), None, match.group(1)) for match in placeholders]
    )
    named_at: set[int] = set()
    sentence = -1
    # `nearest` is the sentence's last player reference, for a name-printing
    # placeholder; `last` carries across sentence breaks, for an attributed
    # one, so "Warner? His career started in {cs}" can't print McNair's (R3).
    nearest: Side | None = None
    last: Side | None = None
    # Every player reference so far, as (offset, side), for a margin's
    # trail/object exemption (#457 round 2).
    history: list[tuple[int, Side]] = []
    for start, side, claim_id in walk:
        at = bisect.bisect_right(breaks, start)
        if at != sentence:
            sentence, nearest = at, None
        if claim_id is None:
            nearest = last = side
            if side is not None:
                history.append((start, side))
            continue
        mode, claim_side = modes.get(claim_id, ("none", None))
        if claim_side is None or mode == "none":
            continue
        if mode == "name" and nearest != claim_side:
            named_at.add(start)
        is_margin = claim_id in claim_measures and claim_measures[claim_id].kind == "margin"
        if is_margin:
            holder = _margin_holder(masked, start, history, breaks)
            if holder is not None and holder != claim_side:
                player, other = block.players[claim_side], block.players[holder]
                errors.append(
                    f"{{{claim_id}}} is {player.name}'s figure, but the prose puts {other.name} "
                    f"ahead by it; name {player.called} as the one ahead"
                )
            # A margin names nobody: "Warner beats McNair by {m}" leaves
            # McNair the last player named.
            continue
        if mode == "attributed" and last is not None and last != claim_side:
            player, other = block.players[claim_side], block.players[last]
            errors.append(
                f"{{{claim_id}}} is {player.name}'s figure, but the last player named before it "
                f"is {other.name}; name {player.called} right before it"
            )
        nearest = last = claim_side
        history.append((start, claim_side))

    errors.extend(_verdict_backstop(masked, walk, modes, claim_measures, breaks, block))
    errors.extend(_margin_word_errors(masked, placeholders, claim_measures, breaks, block))
    return errors, named_at


def _margin_holder(
    masked: str, start: int, history: Sequence[tuple[int, Side]], breaks: Sequence[int]
) -> Side | None:
    """Who the prose says is ahead by the margin at `start` (#457 round 2):
    the last player named before it, unless he trails ("McNair trails by
    {m}", "McNair is behind by {m}", "McNair gets beat by {m}", "McNair falls
    {m} short": the other one is ahead) or is the object of a verb ("{wb}
    beats McNair by {m}", "Warner over McNair by {m}": the player before him
    is ahead). A trail word counts only in the margin's own clause (round 3:
    "McNair went down swinging, but he's ahead by {m}" puts McNair ahead).
    None when nobody is named."""
    if not history:
        return None
    at, side = history[-1]
    if _OBJECT_BEFORE_RE.search(masked[max(0, at - 30) : at]):
        return history[-2][1] if len(history) > 1 else None
    left, _, _, _ = _clause_bounds(masked, start, start, breaks)
    end = start
    while end < len(masked) and masked[end] == MASK:
        end += 1
    if _TRAIL_RE.search(masked, max(at, left), start) or _TRAIL_AFTER_RE.match(masked, end):
        return _OTHER[side]
    return side


def _sentence_bounds(masked: str, start: int, breaks: Sequence[int]) -> tuple[int, int]:
    sentence = bisect.bisect_right(breaks, start)
    left = breaks[sentence - 1] if sentence else 0
    right = breaks[sentence] if sentence < len(breaks) else len(masked)
    return left, right


def _clause_bounds(
    masked: str, start: int, end: int, breaks: Sequence[int]
) -> tuple[int, int, int, int]:
    """The clause around masked[start:end] (cut at `_CLAUSE_END_RE` and the
    sentence breaks), then its sentence, as (left, right, s_left, s_right)."""
    s_left, s_right = _sentence_bounds(masked, start, breaks)
    left = s_left
    for stop in _CLAUSE_END_RE.finditer(masked, s_left, start):
        left = max(left, stop.end())
    after = _CLAUSE_END_RE.search(masked, end, s_right)
    return left, (after.start() if after else s_right), s_left, s_right


def _speculation_matches(
    masked: str, breaks: Sequence[int], names: Collection[str]
) -> list[re.Match[str]]:
    """`_SPECULATION_RE`'s matches, less a would/could/might one behind a
    negator and the listener shape "if you had McNair, ..." (`names` are the
    block's name forms), plus a "different story" that is a conditional
    (#457)."""
    found: list[re.Match[str]] = []
    for match in _SPECULATION_RE.finditer(masked):
        if _IF_YOU_HAD_RE.fullmatch(match.group(0)) and any(
            re.match(rf"\s+{re.escape(name)}\s*(?:[,;:.!?—–]|\Z)", masked[match.end() :])
            for name in names
        ):
            continue
        if _MODAL_RE.match(masked, match.start()):
            left, _, _, _ = _clause_bounds(masked, match.start(), match.end(), breaks)
            words = masked[left : match.start()].split()[-_NEGATOR_WORDS:]
            if any(_NEGATOR_RE.search(word) for word in words):
                continue
        found.append(match)
    for match in _DIFFERENT_STORY_RE.finditer(masked):
        left, _, _, _ = _clause_bounds(masked, match.start(), match.end(), breaks)
        # The cue must govern the phrase (#457 round 2): its own coordinated
        # clause ("With his early stuff it's a different story", "it'd be a
        # different story"), or a coordinated clause before it that opens on
        # an imperative conditional ("Give him those years and it's a
        # different story"); not an earlier "with" ("Warner takes it with
        # room to spare and McNair's a different story").
        ands = list(_AND_RE.finditer(masked, left, match.start()))
        own = ands[-1].end() if ands else left
        previous = ands[-2].end() if len(ands) > 1 else left
        s_left, _ = _sentence_bounds(masked, match.start(), breaks)
        if ands and len(ands) == 1 and not masked[left : ands[0].start()].strip() and left > s_left:
            # ", and it's a different story": the coordinated clause before it
            # is the clause before the comma (#457 round 3).
            previous, _, _, _ = _clause_bounds(masked, left - 1, left - 1, breaks)
        conditional = (
            _STORY_AFTER_RE.match(masked, match.end())
            or _STORY_CUE_RE.search(masked, own, match.start())
            or (ands and _IMPERATIVE_CUE_RE.match(masked, previous))
        )
        if conditional:
            found.append(match)
    return sorted(found, key=lambda match: match.start())


def _wrong_winner_error(said: str, subject: _Player, measure: str, block: _QbBlock) -> str | None:
    if block.inconclusive is not None:
        return f"the prose says {said}, but {block.verdict_text()}: name no winner"
    winner = block.winners[measure]
    if winner == subject.side:
        return None
    goes = (
        f"the {measure} goes to {block.players[winner].called}"
        if winner is not None
        else f"the {measure} is dead level"
    )
    return (
        f"the prose says {said}, but {goes}, not {subject.called}; name the winner through a "
        "winner claim and never type a verdict the block doesn't hold"
    )


def _window_end(masked: str, start: int, end: int) -> int:
    """Where the first `_MEASURE_WINDOW` words after `start` end, before `end`."""
    tokens = list(re.finditer(r"\S+", masked[start:end]))[:_MEASURE_WINDOW]
    return start + tokens[-1].end() if tokens else start


def _verdict_backstop(
    masked: str,
    walk: Sequence[tuple[int, Side | None, str | None]],
    modes: Mapping[str, tuple[_Mode, Side | None]],
    claim_measures: Mapping[str, _ClaimMeasure],
    breaks: Sequence[int],
    block: _QbBlock,
) -> list[str]:
    """D1's backstop on a verdict typed in prose (R1, #451): within one
    sentence, a player reference (a typed name, or a `winner` placeholder),
    then a win verb, then "career" or "peak" a few words later, is rejected
    when that player isn't that measure's winner, and always on an
    inconclusive block. The subject is the last reference before the verb, so
    "McNair beats Warner on the career" is McNair's claim; "Nobody beats
    Warner on the career" has no subject before its verb and passes.

    #457 widened it: a margin placeholder in the window is a mention of its
    measure ("McNair is ahead by {m}"); "is the career winner" is a win verb;
    a colon after a bare object carries on to the measures ("McNair takes it:
    career and peak"); a lone "he" before the verb is the player the sentence
    before named, when it named only one ("McNair? He takes the career"); and
    "the career goes to McNair" hands a measure to the player after it."""
    references = [
        (start, side if claim_id is None else modes.get(claim_id, ("none", None))[1])
        for start, side, claim_id in walk
        if claim_id is None or modes.get(claim_id, ("none", None))[0] == "reference"
    ]
    margins = [
        (start, claim_measures[claim_id].measures)
        for start, _, claim_id in walk
        if claim_id is not None
        and claim_id in claim_measures
        and claim_measures[claim_id].kind == "margin"
    ]
    errors: list[str] = []
    for verb in _WIN_VERB_RE.finditer(masked):
        left, _ = _sentence_bounds(masked, verb.start(), breaks)
        before = [
            side for start, side in references if left <= start < verb.start() and side is not None
        ]
        if before:
            subject = block.players[before[-1]]
        elif _PRONOUN_SUBJECT_RE.fullmatch(masked[left : verb.start()].strip()):
            previous = _previous_sentence_subject(references, left, breaks)
            if previous is None:
                continue
            subject = block.players[previous]
        else:
            continue
        resume = verb.end()
        colon = _OBJECT_COLON_RE.match(masked, verb.end())
        if colon:
            resume = colon.end()
        stop = _CLAUSE_END_RE.search(masked, resume)
        end = stop.start() if stop else len(masked)
        # "McNair takes the career and Warner the peak": a reference after
        # "and" starts its own (gapped) clause, so the peak isn't McNair's.
        for start, _ in references:
            if verb.end() <= start < end and _AND_BEFORE_RE.search(masked, verb.end(), start):
                end = start
                break
        window_end = _window_end(masked, verb.end(), end)
        found = [
            match.group(0).casefold()
            for match in _MEASURE_RE.finditer(masked, verb.start(), window_end)
        ]
        found.extend(
            measure
            for start, measures in margins
            if verb.end() <= start < window_end
            for measure in measures
        )
        for measure in dict.fromkeys(found):
            said = quote(f"{subject.called} {verb.group(0).strip()} ... {measure}")
            error = _wrong_winner_error(said, subject, measure, block)
            if error is not None:
                errors.append(error)
    for match in _GOES_TO_RE.finditer(masked):
        stop = _CLAUSE_END_RE.search(masked, match.end())
        end = stop.start() if stop else len(masked)
        window_end = _window_end(masked, match.end(), end)
        after = [
            side
            for start, side in references
            if match.end() <= start < window_end and side is not None
        ]
        if not after:
            continue
        subject = block.players[after[0]]
        measure = match.group("measure").casefold()
        said = quote(f"{' '.join(match.group(0).split())} {subject.called}")
        error = _wrong_winner_error(said, subject, measure, block)
        if error is not None:
            errors.append(error)
    return errors


def _previous_sentence_subject(
    references: Sequence[tuple[int, Side | None]], left: int, breaks: Sequence[int]
) -> Side | None:
    """The one player the nearest earlier sentence with a reference names,
    for a lone "he"; None when it names both (the pronoun is ambiguous)."""
    earlier = [(start, side) for start, side in references if start < left and side is not None]
    if not earlier:
        return None
    sentence = bisect.bisect_right(breaks, earlier[-1][0])
    sides = {side for start, side in earlier if bisect.bisect_right(breaks, start) == sentence}
    return sides.pop() if len(sides) == 1 else None


def _margin_word_errors(
    masked: str,
    placeholders: Sequence[re.Match[str]],
    claim_measures: Mapping[str, _ClaimMeasure],
    breaks: Sequence[int],
    block: _QbBlock,
) -> list[str]:
    """Margin size (#457): a runaway phrase on a measure whose band isn't
    decisive, or a photo-finish phrase on one that isn't close, is rejected.
    A phrase speaks of the measure mentioned nearest it in its clause (a
    "career" or "peak", or a score, margin or winner placeholder of that
    measure; every mention after it when the nearest is after it), else the
    nearest before it in its sentence, else the nearest after it, else both
    measures. A dead-level measure takes neither. An inconclusive block has
    no margins; its verdict is checked elsewhere."""
    if block.inconclusive is not None:
        return []
    mentions: list[tuple[int, tuple[str, ...]]] = sorted(
        [(match.start(), (match.group(0).casefold(),)) for match in _MEASURE_RE.finditer(masked)]
        + [
            (match.start(), claim_measures[match.group(1)].measures)
            for match in placeholders
            if match.group(1) in claim_measures
        ]
    )
    errors: list[str] = []
    for kind, pattern, fits in (
        ("runaway", _RUNAWAY_RE, "decisive"),
        ("photo-finish", _PHOTO_FINISH_RE, "close"),
    ):
        for match in pattern.finditer(masked):
            left, _, _, _ = _clause_bounds(masked, match.start(), match.end(), breaks)
            if _MARGIN_NEGATOR_RE.search(masked[left : match.start()]):
                continue
            for measure in _phrase_measures(match, mentions, masked, breaks):
                band = block.band(measure)
                if band != fits:
                    errors.append(_margin_word_error(match.group(0), kind, measure, band, block))
    return errors


def _phrase_measures(
    match: re.Match[str],
    mentions: Sequence[tuple[int, tuple[str, ...]]],
    masked: str,
    breaks: Sequence[int],
) -> tuple[str, ...]:
    left, right, s_left, s_right = _clause_bounds(masked, match.start(), match.end(), breaks)
    # The phrase's own verb phrase (#457 round 2): a coordinated new verb
    # ("... the career and takes the peak") starts another attribution.
    for coordinated in _COORDINATED_VERB_RE.finditer(masked, left, match.start()):
        left = coordinated.start()
    cut = _COORDINATED_VERB_RE.search(masked, match.end(), right)
    listed: tuple[str, ...] = ()
    if cut:
        right = cut.start()
    else:
        apposition = _APPOSITIVE_RE.match(masked, right)
        if apposition:
            listed = tuple(
                found.group(0).casefold() for found in _MEASURE_RE.finditer(apposition["list"])
            )
    named = _nearest_measures(match, mentions, left, right, s_left, s_right)
    return tuple(dict.fromkeys((*(named or ()), *listed))) or MEASURES


def _nearest_measures(
    match: re.Match[str],
    mentions: Sequence[tuple[int, tuple[str, ...]]],
    left: int,
    right: int,
    s_left: int,
    s_right: int,
) -> tuple[str, ...] | None:
    before = [(match.start() - at, ms) for at, ms in mentions if left <= at < match.start()]
    after = [(at - match.end(), ms) for at, ms in mentions if match.end() <= at < right]
    if after and (not before or min(after)[0] < min(before)[0]):
        return tuple(dict.fromkeys(m for _, ms in after for m in ms))
    if before:
        return min(before)[1]
    # A phrase in a clause of its own is an aside on what came before it
    # ("{wc} takes the career by {mc}, a photo finish, and ..."), or, opening
    # the sentence, on what follows ("By a nose, he takes the career").
    before = [(match.start() - at, ms) for at, ms in mentions if s_left <= at < match.start()]
    if before:
        return min(before)[1]
    after = [(at - match.end(), ms) for at, ms in mentions if match.end() <= at < s_right]
    return min(after)[1] if after else None


def _margin_word_error(
    phrase: str, kind: str, measure: str, band: MarginBand | None, block: _QbBlock
) -> str:
    said = f"the prose says {quote(phrase)}"
    winner = block.winners[measure]
    if band is None or winner is None:
        return (
            f"{said}, but the {measure} is dead level: no margin words, say plainly that it "
            "is level"
        )
    fits = {
        "close": 'a close one takes "by a nose" or "a photo finish"',
        "clear": "a clear one takes neither extreme, just who took it",
        "decisive": 'a decisive one can "run away with it"',
    }[band]
    return (
        f"{said}, but the {measure} margin is {block.shown_margin(measure, winner)}, a {band} "
        f"one: no {kind} words; {fits}"
    )


def _third_players(
    masked: str, block: _QbBlock, player_names: Collection[str]
) -> list[tuple[int, int, str]]:
    """Every other catalog player's full name typed in the prose, as
    (start, end, name). A run of two to four capitalized words joined only by
    spaces, periods or hyphens ("A.J. Brown") is looked up whole."""
    ours = {player.name for player in block.players.values()}
    words = list(_WORD_RE.finditer(masked))
    found: list[tuple[int, int, str]] = []
    index = 0
    while index < len(words):
        match_end = None
        for last in range(min(len(words) - 1, index + _MAX_NAME_WORDS - 1), index, -1):
            run = words[index : last + 1]
            gaps = [masked[run[k].end() : run[k + 1].start()] for k in range(len(run) - 1)]
            if not all(_NAME_GAP_RE.fullmatch(gap) for gap in gaps):
                continue
            # "Marshall Faulk's pal" (R4, #451): the possessive is not the name.
            tail = _POSSESSIVE_RE.search(run[-1].group(0))
            end = run[-1].end() - (len(tail.group(0)) if tail else 0)
            candidate = masked[run[0].start() : end]
            if candidate[:1].isupper() and candidate in player_names and candidate not in ours:
                found.append((run[0].start(), run[-1].end(), candidate))
                match_end = last
                break
        index = match_end + 1 if match_end is not None else index + 1
    return found


def _name_references(
    masked: str, block: _QbBlock, skip: list[tuple[int, int]]
) -> tuple[list[tuple[int, Side]], list[str]]:
    """The block's players named in the prose, as (offset, side), and the
    errors for a name written any other way (module docstring)."""
    references: list[tuple[int, Side]] = []
    taken: list[tuple[int, int]] = list(skip)

    def free(start: int, end: int) -> bool:
        return not any(s < end and start < e for s, e in taken)

    # Full names first, then short names, longest first, so "Kurt Warner"
    # is one reference, not "Warner" inside it.
    forms = sorted(
        ((form, player.side) for player in block.players.values() for form in player.forms),
        key=lambda item: len(item[0]),
        reverse=True,
    )
    for form, side in forms:
        for match in re.finditer(rf"(?<!\w){re.escape(form)}(?!\w)", masked):
            if free(match.start(), match.end()):
                taken.append(match.span())
                references.append((match.start(), side))

    sentence_starts = {0} | {match.end() for match in SENTENCE_BREAK_RE.finditer(masked)}
    words: dict[str, list[_Player]] = {}
    first_words: set[str] = set()
    for player in block.players.values():
        tokens = player.name.split()
        for token in tokens:
            words.setdefault(token.casefold(), []).append(player)
        if len(tokens) > 1:
            first_words.add(tokens[0].casefold())
    errors: list[str] = []
    for match in _WORD_RE.finditer(masked):
        if not free(match.start(), match.end()):
            continue
        word = _POSSESSIVE_RE.sub("", match.group(0))
        if not word[:1].isupper():
            continue
        fold = word.casefold()
        opens = _opens_sentence(masked, match.start(), sentence_starts)
        owners = words.get(fold)
        if owners is not None:
            player = owners[0]
            if any(word == token for token in player.name.split()):
                if opens and fold in first_words:
                    continue
                errors.append(
                    f"{quote(word)} alone is not how the fact block names {player.name}; "
                    f"write {_forms_text(player)}"
                )
            else:
                spelled = next(t for t in player.name.split() if t.casefold() == fold)
                errors.append(
                    f"{quote(word)} must be written exactly as the fact block spells it: "
                    f"{quote(spelled)} ({_forms_text(player)})"
                )
            continue
        # A sentence opener is as often an English word near a name
        # ("Meaning", "Warned", "Stove") as a misspelling: never one (P3, #451).
        if len(word) < 4 or opens:
            continue
        for token, players in words.items():
            if (
                len(token) >= 4
                and token[0] == fold[0]
                and _distance(fold, token) <= (1 if len(token) <= 6 else 2)
            ):
                player = players[0]
                spelled = next(t for t in player.name.split() if t.casefold() == token)
                errors.append(
                    f"{quote(word)} is not a name the fact block spells; did you mean "
                    f"{quote(spelled)} ({player.name})? Write {_forms_text(player)}"
                )
                break
    return sorted(references), errors


def _forms_text(player: _Player) -> str:
    return " or ".join(quote(form) for form in player.forms)


def _opens_sentence(masked: str, start: int, sentence_starts: Collection[int]) -> bool:
    # A sentence start sits after the break's whitespace (`SENTENCE_BREAK_RE`
    # ends there), and the walk back stops just after the "." (#457), so any
    # start between the two counts.
    left = start
    while left > 0 and (masked[left - 1].isspace() or masked[left - 1] in "\"'‘’“”("):
        left -= 1
    return any(left <= opening <= start for opening in sentence_starts)


def _distance(a: str, b: str) -> int:
    """Levenshtein distance; both are short words."""
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        current = [i]
        for j, char_b in enumerate(b, start=1):
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (char_a != char_b))
            )
        previous = current
    return previous[-1]
