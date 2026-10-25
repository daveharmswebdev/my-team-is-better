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
* `winner` {measure}: the measure's winner, printed by name. The verdict
  itself, so the narrator can't name the wrong one.
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
other player in the sport's catalog ("Marshall Faulk"). A first name alone
that opens a sentence is let through, because it is as often an English word
("Will", for Will Levis); a lowercase name is prose; another player's last
name alone ("Brady") is not caught. Those are accepted gaps.

A score, record or head-to-head prints its player's name ("McNair 0.60")
unless the nearest player reference before it in the sentence (a name typed
in the prose, or a placeholder that refers to a player) is that player
("McNair sits at 0.60"), so a figure can't sit beside the wrong player. A
`career_start` or a count of qualifying seasons prints no name, so it is an
error when the nearest player reference before it in the sentence is the
other player; with none before it (a pronoun), it passes.

**The voice rules a check can see** (the coordinator's voice call on #451):
there is always a winner, so a hedge that withholds the verdict ("too close
to call", "toss-up", "basically even", "dead heat", "coin flip") is rejected;
speculation about the seasons the data doesn't hold ("would've flipped", "if
we had his rookie year", "with those years") is rejected; z-score jargon is
rejected. On an inconclusive block a `winner` or `margin` claim is rejected,
and so is a score for the side with no qualifying season. Whether the prose
argues with the verdict in other words is the prompt's job, not a check here.

Pure: no IO, no database, no network, no logging. `QB_GROUNDING_VERSION` is
these rules' version in the QB cache key.
"""

from __future__ import annotations

import json
import re
from collections.abc import Collection, Mapping
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
QB_GROUNDING_VERSION: Final = "qb-claims-v1"

# Two or three sentences need far fewer figures than a team case.
MAX_QB_CLAIMS: Final = 6

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

# The hedges that withhold the verdict (voice call on #451: always a winner).
_HEDGE_RE: Final = re.compile(
    r"\btoo\s+close\s+to\s+call\b|\btoss[\s-]?ups?\b|\bbasically\s+(?:even|tied|a\s+tie)\b"
    r"|\bdead\s+(?:heat|even)\b|\bcoin[\s-]?flips?\b|\bcall\s+it\s+(?:even|a\s+draw|a\s+tie)\b",
    re.IGNORECASE,
)
_HEDGE_ERROR: Final = (
    "there is always a winner on this score unless the FACT BLOCK says inconclusive: any "
    'margin counts, so say who took it (close is fine: "by a nose", "a photo finish")'
)
# Speculating about the seasons the data doesn't hold (#231: that's arguing
# with the math).
_SPECULATION_RE: Final = re.compile(
    r"\bwould(?:'ve|’ve|\s+have)\s+(?:flipped|changed|swung|won|turned|been\s+different)\b"
    r"|\bif\s+(?:we|they|you|the\s+books?)\s+(?:had|counted|included)\b"
    r"|\bwith\s+(?:those|the\s+missing|his\s+early|his\s+missing)\s+(?:years|seasons)\b",
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
                    f"{measure}: {ahead.called} ahead by {self.shown_margin(measure, winner)}"
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


def qb_tool_schema() -> dict[str, Any]:
    """The QB verdict's `submit_narration` tool definition, in the Anthropic
    Messages API's `tools` shape. Same name and input shape as the team tool
    (`api.persona.claims.tool_schema`); the claim kinds are the QB ones."""
    return {
        "name": TOOL_NAME,
        "description": (
            "Submit the narration. Write every score, margin, year, count or record as a {id} "
            "placeholder in text, and describe it with one claim; the server prints each value "
            "from the fact block. The prose itself must contain no digits, no spelled-out "
            "numbers and no ordinals, and must write each quarterback exactly as the fact "
            "block spells his display_name or short_name. Use at most "
            f"{MAX_QB_CLAIMS} claims."
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
                                    "prints the measure's winner by name; margin takes the "
                                    "player who is ahead; count needs of; year takes "
                                    "nothing else."
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
                                "enum": list(MEASURES),
                                "description": "Which score: the whole career or the peak.",
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
            prose_errors, named_at = _check_prose(text, modes, block, player_names)
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
    if "measure" in raw and raw["measure"] not in MEASURES:
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


def _resolve_winner(
    where: str, raw: dict[Any, Any], block: _QbBlock
) -> tuple[tuple[str, _Mode, Side | None] | None, list[str]]:
    if block.inconclusive is not None:
        return None, [_inconclusive_error(where, block)]
    measure = cast(str, raw["measure"])
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
    return (block.shown_margin(measure, winner), "none", None), []


# ---------------------------------------------------------------------------
# the prose outside the placeholders
# ---------------------------------------------------------------------------


def _check_prose(
    text: str,
    modes: Mapping[str, tuple[_Mode, Side | None]],
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

    holdings = block.holdings()
    for what, match, rule in typed_number_matches(masked):
        errors.append(f"the prose {what} {quote(match.group(0))}; {rule}. {holdings}")
    for pattern, message in (
        (_HEDGE_RE, _HEDGE_ERROR),
        (_SPECULATION_RE, _SPECULATION_ERROR),
        (_JARGON_RE, _JARGON_ERROR),
    ):
        for match in pattern.finditer(masked):
            errors.append(f"the prose says {quote(match.group(0))}; {message}")

    third = _third_players(masked, block, player_names)
    for _, _, name in third:
        errors.append(
            f"{quote(name)} is not a player in this fact block; it names only {block.roster()}, "
            "so leave other players out"
        )
    references, name_errors = _name_references(masked, block, [(s, e) for s, e, _ in third])
    errors.extend(name_errors)

    breaks = [match.end() for match in SENTENCE_BREAK_RE.finditer(masked)]
    walk: list[tuple[int, Side | None, str | None]] = sorted(
        [(start, side, None) for start, side in references]
        + [(match.start(), None, match.group(1)) for match in placeholders]
    )
    named_at: set[int] = set()
    sentence = -1
    nearest: Side | None = None
    for start, side, claim_id in walk:
        at = sum(1 for end in breaks if end <= start)
        if at != sentence:
            sentence, nearest = at, None
        if claim_id is None:
            nearest = side
            continue
        mode, claim_side = modes.get(claim_id, ("none", None))
        if claim_side is None or mode == "none":
            continue
        if mode == "name" and nearest != claim_side:
            named_at.add(start)
        if mode == "attributed" and nearest is not None and nearest != claim_side:
            player, other = block.players[claim_side], block.players[nearest]
            errors.append(
                f"{{{claim_id}}} is {player.name}'s figure, but the last player named before it "
                f"in that sentence is {other.name}; name {player.called} right before it"
            )
        nearest = claim_side
    return errors, named_at


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
            candidate = masked[run[0].start() : run[-1].end()]
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
        if len(word) < 4 or (opens and len(word) < 5):
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
    left = start
    while left > 0 and (masked[left - 1].isspace() or masked[left - 1] in "\"'‘’“”("):
        left -= 1
    return left in sentence_starts


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
