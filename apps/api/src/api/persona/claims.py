"""Typed narration claims: the narrator's prose carries no numbers of its own
(issue #290, epic #199, child 1 of 4).

The narrator will (from #291) answer with one `submit_narration` tool call,
`{text, claims[]}`. `text` holds `{id}` placeholders; each claim says what one
placeholder is ("Alabama's record", "the score of Alabama vs Georgia, a W for
Alabama"). This module:

1. publishes the tool definition (`tool_schema`);
2. resolves every claim against the production FACT BLOCK JSON (exactly
   `api.persona.service.team_case_fact_block_json` /
   `comparison_fact_block_json`) and, when one doesn't resolve, returns an
   error naming what the block *does* hold -- the errors become the retry
   feedback verbatim;
3. renders every value from the block itself, never from the narrator: a
   claim can only point at a fact, so a wrong number cannot be typed;
4. checks the prose outside the placeholders: no digits, no spelled-out
   numbers or number-word records, no ordinal ranks, and every team reference
   spelled exactly as the block spells it (no alias of a block team, no
   mascot, no other case of a block team, no capitalized team the block
   doesn't hold, no name typed again beside a placeholder that already prints
   it). A number or ordinal inside a conference name or game phase ("Big Ten",
   "second half") is rejected like any other, with an error saying the block
   holds no such detail.

What counts as a team reference, so ordinary bar-stool prose passes (#290
round 2): a block team's name in any case; any other catalog name only with
its first letter uppercase (founder decision, no English-word exemption list:
"the pace" is prose, "Pace" is not); an alias only of a block team ("ME" is
prose without Maine); a multi-word mascot capitalized anywhere ("Crimson
Tide"); a single-word mascot, or a multi-word mascot's final word alone, only
capitalized and right after "the"/"The" or a team name ("the Tide", "Texas
Longhorns"), so "Pride goes before the fall" is prose.

A record, rating or rank always prints its team's name ("Lima Lions 350.00",
"No. 3 Georgia"), so a figure can no longer sit beside the wrong team. A game
score is resolved from a named team's side with its result, so the winner is
checked; it prints winner-first. `when` and `where` follow founder decision C
on #199: they print only what the block records ("in the postseason", "to
open the season", "in week 11", "at a neutral site"), and a game row that
isn't neutral cannot yet say home or away (#294).

Accepted gaps, by decision: "first" and "last" are not treated as ordinals,
so "first half" passes; NFL catalog rows carry no mascot, so an NFL nickname
alone is not caught; a lowercase name of a team the block doesn't hold
("alabama") is prose; a single-word mascot with neither "the" nor a team name
before it ("Longhorns fans") is not caught, nor is a singular ("Longhorn") or a
nickname the catalog doesn't hold ("Bama");
Unicode look-alikes and non-English number words are deliberate evasion, out
of scope; a prose verb that contradicts a claim's result ("beat {g1}" with an
L) is #291's prompt and #293's measurement, not a check here.

Pure: no IO, no database, no network, no logging. Nothing in production calls
this yet (#291 wires it), so no PROMPT_VERSION or GROUNDING_VERSION moves.
"""

from __future__ import annotations

import json
import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from typing import Any, Final, cast, get_args

from api.models import Method
from api.rating_display import display_value
from api.repositories.teams import TeamRecord

TOOL_NAME: Final = "submit_narration"

KINDS: Final[tuple[str, ...]] = (
    "record",
    "rating",
    "rank",
    "game_score",
    "margin",
    "year",
    "count",
    "win_pct",
    "when",
    "where",
)
COUNT_OF: Final[tuple[str, ...]] = (
    "wins",
    "losses",
    "ties",
    "quality_wins",
    "games",
    "common_opponents",
    "meetings",
)
RESULTS: Final[tuple[str, ...]] = ("W", "L", "T")
SEASON_TYPES: Final[tuple[str, ...]] = ("regular", "postseason")

_TEAM_KEYS: Final = ("id", "kind", "team")
_GAME_KEYS: Final = ("id", "kind", "team", "opponent", "result", "week", "season_type")
_KEYS_BY_KIND: Final[Mapping[str, tuple[str, ...]]] = {
    "record": _TEAM_KEYS,
    "rating": _TEAM_KEYS,
    "rank": _TEAM_KEYS,
    "game_score": _GAME_KEYS,
    "margin": _GAME_KEYS,
    "year": ("id", "kind"),
    "count": ("id", "kind", "of", "team", "opponent"),
    "win_pct": _TEAM_KEYS,
    "when": _GAME_KEYS,
    "where": _GAME_KEYS,
}
_GAME_KINDS: Final = frozenset({"game_score", "margin", "when", "where"})
# Kinds whose rendering prints the team's name.
_NAME_KINDS: Final = frozenset({"record", "rating", "rank"})

_ID_PATTERN: Final = "[A-Za-z][A-Za-z0-9_]*"
_ID_RE: Final = re.compile(_ID_PATTERN)
_PLACEHOLDER_RE: Final = re.compile(r"\{(" + _ID_PATTERN + r")\}")
# Placeholders are masked with this character (same length, so every offset
# still points into the original text). It is not a word character, a digit
# or whitespace, so it can neither complete nor break a match; a text that
# already contains it is rejected before the mask is applied.
_MASK: Final = "\x00"

_DASHES: Final = "-‐‑‒–—−"
_DIGITS_RE: Final = re.compile(
    rf"\d+(?:[.,:]\d+)*(?:\s*[{_DASHES}]\s*\d+(?:[.,:]\d+)*)*",
)
_NUMBER_WORDS: Final = (
    "two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty "
    "ninety hundred"
).split()
_NUMBER_WORD_RE: Final = re.compile(
    r"\b(?:" + "|".join(_NUMBER_WORDS) + r")\b",
    re.IGNORECASE,
)
_RECORD_TERMS: Final = "|".join(("zero", "oh", "one", *_NUMBER_WORDS))
_RECORD_SEPARATOR: Final = rf"(?:\s*[{_DASHES}]\s*(?:and\s*[{_DASHES}]\s*)?|\s+and\s+)"
# "thirteen and oh", "one-and-one", "twelve-one": a record spelled in words.
_WORD_RECORD_RE: Final = re.compile(
    rf"\b(?:{_RECORD_TERMS}){_RECORD_SEPARATOR}(?:{_RECORD_TERMS})\b",
    re.IGNORECASE,
)
_ORDINAL_WORDS: Final = (
    "second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth "
    "fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth twentieth thirtieth "
    "fortieth fiftieth sixtieth seventieth eightieth ninetieth hundredth"
).split()
_ORDINAL_RE: Final = re.compile(r"\b(?:" + "|".join(_ORDINAL_WORDS) + r")\b", re.IGNORECASE)
_SENTENCE_BREAK_RE: Final = re.compile(r"(?<=[.!?])\s+")
# Conference names and game phases whose number, number word or ordinal is
# still rejected; this only picks a clearer error, never accept vs reject.
_NO_DETAIL_RE: Final = re.compile(
    rf"\bBig\s+(?:Ten|Twelve|12)\b|\bPac\s*[{_DASHES}]\s*(?:12|10)\b"
    r"|\b(?:second\s+half|third\s+quarter|fourth\s+quarter)\b",
    re.IGNORECASE,
)
_THE: Final = ("the", "The")
_WORD_CHAR_RE: Final = re.compile(r"\w")

_AP_WORDS: Final = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")
_FLIP: Final[Mapping[str, str]] = {"W": "L", "L": "W", "T": "T"}
_QUOTE_LIMIT: Final = 60


@dataclass(frozen=True)
class ClaimOutcome:
    """The result of `check_and_render`: `text` is the rendered narration when,
    and only when, `errors` is empty."""

    errors: tuple[str, ...]
    text: str | None


def tool_schema() -> dict[str, Any]:
    """The `submit_narration` tool definition, in the Anthropic Messages API's
    `tools` shape (`name`, `description`, `input_schema`)."""
    return {
        "name": TOOL_NAME,
        "description": (
            "Submit the narration. Write every number, record, rating, rank, score, "
            "count, date or venue as a {id} placeholder in text, and describe it with "
            "one claim; the server prints each value from the fact block. The prose "
            "itself must contain no digits, no spelled-out numbers and no ordinals, and "
            "must write each team's name exactly as the fact block spells it."
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
                                "pattern": f"^{_ID_PATTERN}$",
                                "description": "The placeholder name used in text as {id}.",
                            },
                            "kind": {
                                "type": "string",
                                "enum": list(KINDS),
                                "description": (
                                    "record, rating and rank print the team's name with "
                                    "the value; game_score, margin, when and where name "
                                    "one game; count needs of; year takes nothing else."
                                ),
                            },
                            "team": {
                                "type": "string",
                                "description": "A team, spelled as the fact block does.",
                            },
                            "opponent": {
                                "type": "string",
                                "description": "The other team in the game, as spelled.",
                            },
                            "result": {
                                "type": "string",
                                "enum": list(RESULTS),
                                "description": "The game's result from team's side.",
                            },
                            "week": {
                                "type": "integer",
                                "description": "Only when the two teams met more than once.",
                            },
                            "season_type": {
                                "type": "string",
                                "enum": list(SEASON_TYPES),
                                "description": "Only when the two teams met more than once.",
                            },
                            "of": {
                                "type": "string",
                                "enum": list(COUNT_OF),
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


def check_and_render(
    tool_input: object,
    fact_block_json: str,
    catalog: Sequence[TeamRecord],
) -> ClaimOutcome:
    """Validate one `submit_narration` tool input against the fact block and,
    if nothing is wrong, render it.

    `catalog` is the sport's team catalog (`list_team_records`), used to
    recognise team references in the prose. Malformed or hostile tool input
    only ever produces errors. A `fact_block_json` that is not a production
    fact block is a programming error and raises `ValueError`.
    """
    block = _parse_block(fact_block_json)
    records = tuple(catalog)
    extra_names = tuple(sorted(set(block.teams) - {record.name for record in records}))
    index = _catalog_index(records, extra_names)
    name_re = _name_re(records, extra_names, frozenset(block.teams))
    if not isinstance(tool_input, dict):
        return ClaimOutcome(
            errors=(
                f'{TOOL_NAME} input must be an object with "text" and "claims", '
                f"not {_type_name(tool_input)}",
            ),
            text=None,
        )

    errors: list[str] = []
    for key in tool_input:
        if key not in ("text", "claims"):
            errors.append(f'{TOOL_NAME} does not take {_quote(key)}; it takes "text" and "claims"')

    text = tool_input.get("text")
    if "text" not in tool_input:
        errors.append(f'{TOOL_NAME} needs "text"')
    elif not isinstance(text, str):
        errors.append(f'"text" must be a string, not {_type_name(text)}')
    elif not text.strip():
        errors.append('"text" is empty')

    raw_claims = tool_input.get("claims")
    rendered: dict[str, str] = {}
    name_claims: dict[str, str] = {}
    rank_claims: set[str] = set()
    claim_ids: list[str] = []
    if "claims" not in tool_input:
        errors.append(f'{TOOL_NAME} needs "claims" (a list, which may be empty)')
    elif not isinstance(raw_claims, list):
        errors.append(f'"claims" must be a list of claim objects, not {_type_name(raw_claims)}')
    else:
        duplicated: set[str] = set()
        for position, raw in enumerate(raw_claims):
            if not isinstance(raw, dict):
                errors.append(f"claims[{position}] must be an object, not {_type_name(raw)}")
                continue
            claim_id = raw.get("id")
            if not isinstance(claim_id, str) or not claim_id:
                errors.append(f'claims[{position}] needs a string "id"')
                continue
            if not _ID_RE.fullmatch(claim_id):
                errors.append(
                    f"claims[{position}] id {_quote(claim_id)} must be letters, digits and "
                    "underscores, starting with a letter"
                )
                continue
            if claim_id in claim_ids:
                if claim_id not in duplicated:
                    errors.append(f"claim id {_quote(claim_id)} is used by more than one claim")
                    duplicated.add(claim_id)
                continue
            claim_ids.append(claim_id)
            value, claim_errors = _resolve_claim(claim_id, raw, block)
            errors.extend(claim_errors)
            if value is not None:
                rendered[claim_id] = value
            kind, team = raw.get("kind"), raw.get("team")
            # isinstance first: a hostile list or dict "kind" is unhashable.
            if isinstance(kind, str) and kind in _NAME_KINDS and isinstance(team, str):
                name_claims[claim_id] = team
                if kind == "rank":
                    rank_claims.add(claim_id)

    if isinstance(text, str):
        used = list(dict.fromkeys(match.group(1) for match in _PLACEHOLDER_RE.finditer(text)))
        known = ", ".join(_quote(claim_id) for claim_id in claim_ids) if claim_ids else "none"
        for placeholder in used:
            if placeholder not in claim_ids:
                errors.append(
                    f"placeholder {{{placeholder}}} has no claim; the claim ids are: {known}"
                )
        for claim_id in claim_ids:
            if claim_id not in used:
                errors.append(
                    f"claim {_quote(claim_id)} is not used by any placeholder in the text"
                )
        if _MASK in text:
            errors.append("the text contains a NUL character")
        else:
            errors.extend(_check_prose(text, name_claims, rank_claims, block, index, name_re))

    if errors or not isinstance(text, str):
        return ClaimOutcome(errors=tuple(dict.fromkeys(errors)), text=None)
    return ClaimOutcome(
        errors=(),
        text=_PLACEHOLDER_RE.sub(lambda match: rendered[match.group(1)], text),
    )


# ---------------------------------------------------------------------------
# the fact block
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Game:
    """One game as seen from `team`'s side."""

    team: str
    opponent: str
    result: str
    team_score: int
    opponent_score: int
    week: int | None
    season_type: str
    neutral_site: bool | None

    @property
    def key(self) -> tuple[str, str, int | None, str]:
        return (self.team, self.opponent, self.week, self.season_type)

    @property
    def label(self) -> str:
        if self.week is None:
            return f"{self.season_type}, no week"
        return f"{self.season_type} week {self.week}"

    @property
    def line(self) -> str:
        return f"{self.result} {self.team_score}-{self.opponent_score} ({self.label})"

    def mirrored(self) -> _Game:
        return replace(
            self,
            team=self.opponent,
            opponent=self.team,
            result=_FLIP[self.result],
            team_score=self.opponent_score,
            opponent_score=self.team_score,
        )


@dataclass(frozen=True)
class _Subject:
    """A team the block gives a record for: the team case's team, or a
    comparison's team_a / team_b. `games` is the full game list, which only a
    team case holds."""

    name: str
    rank: int
    rating: Decimal
    wins: int
    losses: int
    ties: int
    quality_wins: int
    games: tuple[_Game, ...] | None

    @property
    def record(self) -> str:
        if self.ties:
            return f"{self.wins}-{self.losses}-{self.ties}"
        return f"{self.wins}-{self.losses}"


@dataclass
class _Block:
    year: int
    method: Method
    is_comparison: bool
    subjects: dict[str, _Subject] = field(default_factory=dict)
    teams: list[str] = field(default_factory=list)
    ratings: dict[str, Decimal] = field(default_factory=dict)
    ranks: dict[str, int] = field(default_factory=dict)
    games: dict[tuple[str, str, int | None, str], _Game] = field(default_factory=dict)
    common_opponents: int | None = None

    def add_team(self, name: str) -> None:
        if name not in self.teams:
            self.teams.append(name)

    def add_game(self, game: _Game) -> None:
        """Index `game` from both sides, deduped by (team, opponent, week,
        season_type). A row without `neutral_site` (a common-opponent meeting)
        takes it from another row for the same game when one exists."""
        for side in (game, game.mirrored()):
            existing = self.games.get(side.key)
            if existing is None:
                self.games[side.key] = side
            elif existing.neutral_site is None and side.neutral_site is not None:
                self.games[side.key] = replace(existing, neutral_site=side.neutral_site)

    def meetings(self, team: str, opponent: str) -> list[_Game]:
        return [g for g in self.games.values() if g.team == team and g.opponent == opponent]

    def holdings(self, names: Sequence[str]) -> str:
        """What the block holds for the subjects and for `names`, for an error
        about a number typed into the prose."""
        items: list[str] = []
        for subject in self.subjects.values():
            items.append(f"{subject.name} {subject.record}")
            items.append(f"No. {subject.rank} {subject.name}")
            items.append(f"{subject.name} rated {display_value(subject.rating, self.method)}")
        others = [name for name in names if name not in self.subjects]
        for name in others:
            if name in self.ranks:
                items.append(f"No. {self.ranks[name]} {name}")
        seen: set[tuple[frozenset[str], int | None, str]] = set()
        for team in [*self.subjects, *others]:
            for opponent in names:
                for game in self.meetings(team, opponent):
                    game_key = (frozenset((team, opponent)), game.week, game.season_type)
                    if game_key not in seen:
                        seen.add(game_key)
                        items.append(f"{team} vs {opponent}: {game.line}")
        return "The fact block holds: " + "; ".join(items) + "."


def _parse_block(fact_block_json: str) -> _Block:
    try:
        data = json.loads(fact_block_json, parse_float=Decimal)
        method = data["method"]
        if method not in get_args(Method):
            raise ValueError(f"unknown rating method {method!r}")
        block = _Block(
            year=int(data["year"]),
            method=cast(Method, method),
            is_comparison="team_a" in data,
        )
        if block.is_comparison:
            _parse_comparison(data, block)
        else:
            _parse_subject(data, block, with_games=True)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"not a production fact block: {exc!r}") from exc
    return block


def _parse_comparison(data: Any, block: _Block) -> None:
    for side in ("team_a", "team_b"):
        block.add_team(str(data[side]["team_name"]))
    for side in ("team_a", "team_b"):
        _parse_subject(data[side], block, with_games=False)
    for meeting in data["head_to_head"]["meetings"]:
        home, away = str(meeting["home_team"]), str(meeting["away_team"])
        home_points, away_points = int(meeting["home_points"]), int(meeting["away_points"])
        block.add_team(home)
        block.add_team(away)
        block.add_game(
            _Game(
                team=home,
                opponent=away,
                result=_result(home_points, away_points),
                team_score=home_points,
                opponent_score=away_points,
                week=_week(meeting["week"]),
                season_type=str(meeting["season_type"]),
                neutral_site=bool(meeting["neutral_site"]),
            )
        )
    for common in data["common_opponents"]:
        opponent = str(common["opponent_name"])
        block.add_team(opponent)
        if common["opponent_rank"] is not None:
            block.ranks.setdefault(opponent, int(common["opponent_rank"]))
        for side, meetings_key in (("team_a", "team_a_meetings"), ("team_b", "team_b_meetings")):
            for meeting in common[meetings_key]:
                block.add_game(
                    _Game(
                        team=str(data[side]["team_name"]),
                        opponent=opponent,
                        result=str(meeting["result"]),
                        team_score=int(meeting["team_score"]),
                        opponent_score=int(meeting["opponent_score"]),
                        week=_week(meeting["week"]),
                        season_type=str(meeting["season_type"]),
                        neutral_site=None,
                    )
                )
    block.common_opponents = len(data["common_opponents"])


def _parse_subject(node: Any, block: _Block, *, with_games: bool) -> None:
    name = str(node["team_name"])
    block.add_team(name)
    rating = Decimal(node["rating"])
    block.ratings[name] = rating
    block.ranks[name] = int(node["rank"])
    games: tuple[_Game, ...] | None = None
    if with_games:
        games = tuple(_parse_row(name, row, block) for row in node["games"])
    for row in node["quality_wins"]:
        _parse_row(name, row, block)
    if node["worst_loss"] is not None:
        _parse_row(name, node["worst_loss"], block)
    for entry in node["rating_breakdown"]["entries"]:
        block.add_team(str(entry["opponent_name"]))
    block.subjects[name] = _Subject(
        name=name,
        rank=int(node["rank"]),
        rating=rating,
        wins=int(node["wins"]),
        losses=int(node["losses"]),
        ties=int(node["ties"]),
        quality_wins=len(node["quality_wins"]),
        games=games,
    )


def _parse_row(team: str, row: Any, block: _Block) -> _Game:
    opponent = str(row["opponent_name"])
    block.add_team(opponent)
    if row["opponent_rank"] is not None:
        block.ranks.setdefault(opponent, int(row["opponent_rank"]))
    if row["opponent_rating"] is not None:
        block.ratings.setdefault(opponent, Decimal(row["opponent_rating"]))
    game = _Game(
        team=team,
        opponent=opponent,
        result=str(row["result"]),
        team_score=int(row["team_score"]),
        opponent_score=int(row["opponent_score"]),
        week=_week(row["week"]),
        season_type=str(row["season_type"]),
        neutral_site=bool(row["neutral_site"]),
    )
    block.add_game(game)
    return game


def _week(value: Any) -> int | None:
    return None if value is None else int(value)


def _result(team_score: int, opponent_score: int) -> str:
    if team_score > opponent_score:
        return "W"
    if team_score < opponent_score:
        return "L"
    return "T"


# ---------------------------------------------------------------------------
# claims
# ---------------------------------------------------------------------------


def _resolve_claim(
    claim_id: str, raw: dict[Any, Any], block: _Block
) -> tuple[str | None, list[str]]:
    """The rendered value of one claim, or the errors that stop it rendering."""
    where = f"claim {_quote(claim_id)}"
    kind = raw.get("kind")
    if not isinstance(kind, str) or kind not in _KEYS_BY_KIND:
        shown = "missing" if "kind" not in raw else _quote(kind)
        return None, [f"{where}: unknown kind {shown}; the kinds are {', '.join(KINDS)}"]

    errors = _shape_errors(where, kind, raw)
    if errors:
        return None, errors

    if kind == "year":
        return str(block.year), []
    if kind == "count":
        return _resolve_count(where, raw, block)

    team, errors = _team_key(where, kind, raw, "team", block)
    if team is None:
        return None, errors
    if kind in _GAME_KINDS:
        return _resolve_game_kind(where, kind, team, raw, block)
    if kind == "rating":
        rating = block.ratings.get(team)
        if rating is None:
            rated = ", ".join(block.ratings)
            return None, [f"{where}: the fact block gives no rating for {team}; it rates: {rated}"]
        return f"{team} {display_value(rating, block.method)}", []
    if kind == "rank":
        rank = block.ranks.get(team)
        if rank is None:
            ranked = ", ".join(f"No. {r} {name}" for name, r in block.ranks.items())
            return None, [f"{where}: the fact block gives no rank for {team}; it ranks: {ranked}"]
        return f"No. {rank} {team}", []

    subject = block.subjects.get(team)
    if subject is None:
        return None, [_not_a_subject(where, kind, team, block)]
    if kind == "record":
        return f"{subject.name} {subject.record}", []
    # win_pct (#108): a tie counts as half a win.
    played = subject.wins + subject.losses + subject.ties
    if played == 0:
        return None, [f"{where}: {team} has no games in the fact block, so no winning percentage"]
    pct = ((Decimal(subject.wins) + Decimal(subject.ties) / 2) / Decimal(played)).quantize(
        Decimal("0.001"), rounding=ROUND_HALF_UP
    )
    shown = f"{pct:.3f}"
    return (shown[1:] if shown.startswith("0") else shown), []


def _shape_errors(where: str, kind: str, raw: dict[Any, Any]) -> list[str]:
    allowed = _KEYS_BY_KIND[kind]
    errors: list[str] = []
    for key in raw:
        if key not in allowed:
            errors.append(
                f"{where} ({kind}) does not take {_quote(key)}; it takes {', '.join(allowed)}"
            )
    for key in ("team", "opponent"):
        if key in raw and not isinstance(raw[key], str):
            errors.append(
                f'{where}: "{key}" must be a team name string, not {_type_name(raw[key])}'
            )
    if "result" in raw and not (isinstance(raw["result"], str) and raw["result"] in RESULTS):
        errors.append(f'{where}: "result" must be W, L or T (from team\'s side)')
    week = raw.get("week")
    if "week" in raw and (not isinstance(week, int) or isinstance(week, bool)):
        errors.append(f'{where}: "week" must be an integer, not {_type_name(week)}')
    season_type = raw.get("season_type")
    if "season_type" in raw and not (isinstance(season_type, str) and season_type in SEASON_TYPES):
        errors.append(f'{where}: "season_type" must be regular or postseason')
    of = raw.get("of")
    if "of" in raw and not (isinstance(of, str) and of in COUNT_OF):
        errors.append(f'{where}: "of" must be one of {", ".join(COUNT_OF)}, not {_quote(of)}')
    return errors


def _team_key(
    where: str, kind: str, raw: dict[Any, Any], key: str, block: _Block
) -> tuple[str | None, list[str]]:
    """`raw[key]` as a team the block holds, spelled as the block spells it."""
    if key not in raw:
        return None, [f'{where} ({kind}) needs "{key}"']
    value = cast(str, raw[key])
    if value in block.teams:
        return value, []
    close = [team for team in block.teams if team.casefold() == value.casefold()]
    if close:
        return None, [
            f"{where}: {_quote(value)} is not spelled as the fact block spells it; "
            f"did you mean {_quote(close[0])}?"
        ]
    return None, [
        f"{where}: {_quote(value)} is not a team in the fact block; its teams are: "
        f"{', '.join(block.teams)}"
    ]


def _not_a_subject(where: str, what: str, team: str, block: _Block) -> str:
    subjects = ", ".join(f"{s.name} {s.record}" for s in block.subjects.values())
    return f"{where}: the fact block gives a {what} only for {subjects}; {team} is not one of them"


def _resolve_game_kind(
    where: str, kind: str, team: str, raw: dict[Any, Any], block: _Block
) -> tuple[str | None, list[str]]:
    opponent, errors = _team_key(where, kind, raw, "opponent", block)
    if "result" not in raw:
        errors.append(f'{where} ({kind}) needs "result" (W, L or T, from team\'s side)')
    if opponent is None or errors:
        return None, errors

    meetings = block.meetings(team, opponent)
    if not meetings:
        against = list(dict.fromkeys(g.opponent for g in block.games.values() if g.team == team))
        return None, [
            f"{where}: the fact block holds no game between {team} and {opponent}; "
            f"it holds {team}'s games against: {', '.join(against)}"
        ]
    week, season_type = raw.get("week"), raw.get("season_type")
    chosen = [
        game
        for game in meetings
        if (week is None or game.week == week)
        and (season_type is None or game.season_type == season_type)
    ]
    listing = "; ".join(game.line for game in meetings)
    if not chosen:
        asked = " ".join(
            str(part)
            for part in (season_type, "week" if week is not None else None, week)
            if part is not None
        )
        return None, [
            f"{where}: {team} and {opponent} did not meet in {asked}; "
            f"the fact block holds {team}'s side as: {listing}"
        ]
    if len(chosen) > 1:
        return None, [
            f"{where}: {team} and {opponent} met {len(meetings)} times in the fact block "
            f'({listing}, from {team}\'s side); add "week" and "season_type" to say which'
        ]
    game = chosen[0]
    if raw["result"] != game.result:
        return None, [
            f"{where}: from {team}'s side that game ({game.label}) was "
            f"{game.result} {game.team_score}-{game.opponent_score}, not {raw['result']}"
        ]

    if kind == "game_score":
        high, low = sorted((game.team_score, game.opponent_score), reverse=True)
        return f"{high}-{low}", []
    if kind == "margin":
        return str(abs(game.team_score - game.opponent_score)), []
    if kind == "when":
        return _when(where, game, block)
    return _where(where, game)


def _when(where: str, game: _Game, block: _Block) -> tuple[str | None, list[str]]:
    # Postseason first: 2017 Alabama's two playoff games are both "week 1".
    if game.season_type == "postseason":
        return "in the postseason", []
    subject = block.subjects.get(game.team)
    if subject is not None and subject.games:
        # games[] is the engine's order: regular season by week, then postseason.
        if game.key == subject.games[0].key:
            return "to open the season", []
        regular = [g for g in subject.games if g.season_type == "regular"]
        if regular and game.key == regular[-1].key:
            return "in the regular-season finale", []
    if game.week is not None:
        return f"in week {game.week}", []
    return None, [
        f"{where}: the fact block has no week for {game.team} vs {game.opponent} "
        f"({game.season_type}), so it records no time to state"
    ]


def _where(where: str, game: _Game) -> tuple[str | None, list[str]]:
    if game.neutral_site is True:
        return "at a neutral site", []
    if game.neutral_site is False:
        # A head-to-head row does carry home_team/away_team: the claim model just
        # can't print it yet, so never say the block lacks it.
        return None, [
            f"{where}: {game.team} vs {game.opponent} ({game.label}) was not at a neutral "
            'site, and a "where" claim can only say where a game was played when the fact '
            "block marks it neutral-site; home/away rendering arrives with #294"
        ]
    return None, [
        f"{where}: the fact block does not record where {game.team} vs {game.opponent} "
        f"({game.label}) was played"
    ]


def _resolve_count(where: str, raw: dict[Any, Any], block: _Block) -> tuple[str | None, list[str]]:
    if "of" not in raw:
        return None, [f'{where} (count) needs "of", one of {", ".join(COUNT_OF)}']
    of = cast(str, raw["of"])

    if of == "common_opponents":
        extra = [key for key in ("team", "opponent") if key in raw]
        if extra:
            return None, [f"{where}: a count of common_opponents takes no {' or '.join(extra)}"]
        if block.common_opponents is None:
            return None, [
                f"{where}: a team-case fact block has no common opponents; "
                "that count needs a comparison"
            ]
        return _ap(block.common_opponents), []

    team, errors = _team_key(where, f"count of {of}", raw, "team", block)
    if of != "meetings" and "opponent" in raw:
        errors.append(
            f'{where}: a count of {of} does not take "opponent"; a count of meetings does'
        )
    if team is None or errors:
        return None, errors

    if of == "meetings":
        opponent, errors = _team_key(where, "count of meetings", raw, "opponent", block)
        if opponent is None:
            return None, errors
        if opponent == team:
            return None, [f"{where}: a count of meetings needs two different teams"]
        found = len(block.meetings(team, opponent))
        complete = (
            set(block.subjects) == {team, opponent}
            if block.is_comparison
            else any(
                block.subjects[s].games is not None for s in (team, opponent) if s in block.subjects
            )
        )
        if found == 0 and not complete:
            return None, [
                f"{where}: the fact block holds no game between {team} and {opponent}, "
                "and does not hold either team's full schedule"
            ]
        return _ap(found), []

    subject = block.subjects.get(team)
    if subject is None:
        return None, [_not_a_subject(where, f"count of {of}", team, block)]
    if of == "games":
        if subject.games is None:
            return None, [
                f"{where}: a comparison fact block holds no full game list, so there is no "
                f"count of games for {team}"
            ]
        return _ap(len(subject.games)), []
    counts = {
        "wins": subject.wins,
        "losses": subject.losses,
        "ties": subject.ties,
        "quality_wins": subject.quality_wins,
    }
    return _ap(counts[of]), []


def _ap(number: int) -> str:
    """AP style: words for zero through nine, numerals from 10."""
    return _AP_WORDS[number] if 0 <= number < len(_AP_WORDS) else str(number)


# ---------------------------------------------------------------------------
# the prose outside the placeholders
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _CatalogIndex:
    names_by_fold: Mapping[str, tuple[str, ...]]
    alias_teams: Mapping[str, tuple[str, ...]]
    mascot_teams: Mapping[str, tuple[str, ...]]
    mascot_re: re.Pattern[str] | None


@lru_cache(maxsize=8)
def _catalog_index(catalog: tuple[TeamRecord, ...], extra_names: tuple[str, ...]) -> _CatalogIndex:
    """Team references to look for in prose, before a block narrows the names
    and aliases (`_name_re`). Mascots (the whole phrase and its final word)
    match capitalized only, so "the tide turned" is prose; one alternation,
    longest first, so the leftmost match is the longest ("Crimson Tide", never
    "Tide"). Whether a mascot match counts is `_check_prose`'s call."""
    names: dict[str, list[str]] = {}
    for name in [record.name for record in catalog] + list(extra_names):
        if name.strip() and name not in names.setdefault(name.casefold(), []):
            names[name.casefold()].append(name)

    aliases: dict[str, list[str]] = {}
    mascots: dict[str, list[str]] = {}
    for record in catalog:
        for alias in record.aliases:
            if alias.strip() and alias.casefold() not in names:
                teams = aliases.setdefault(alias, [])
                if record.name not in teams:
                    teams.append(record.name)
        if record.mascot and record.mascot.strip():
            phrase = record.mascot.strip()
            for form in (phrase, phrase.split()[-1]):
                if form[0].isupper() and form.casefold() not in names:
                    teams = mascots.setdefault(form, [])
                    if record.name not in teams:
                        teams.append(record.name)

    return _CatalogIndex(
        names_by_fold={fold: tuple(found) for fold, found in names.items()},
        alias_teams={alias: tuple(teams) for alias, teams in aliases.items()},
        mascot_teams={form: tuple(teams) for form, teams in mascots.items()},
        mascot_re=_longest_first([(form, re.escape(form)) for form in mascots])
        if mascots
        else None,
    )


@lru_cache(maxsize=32)
def _name_re(
    catalog: tuple[TeamRecord, ...],
    extra_names: tuple[str, ...],
    block_teams: frozenset[str],
) -> re.Pattern[str]:
    """Team names and aliases to look for in prose, given the teams the block
    mentions:

    * a block team's name matches in any case, so "texas" is a spelling error;
    * any other catalog name matches only when its first letter is uppercase
      ("Alabama", "ALABAMA"), so "the pace" and "the assumption" are prose
      (founder decision on #290, 2026-09-15: no English-word exemption list);
    * an alias matches, exactly as the catalog spells it, only when it is an
      alias of a block team, so "ME" and "UK" are prose on a block without
      Maine or Kentucky (coordinator decision 4 on #290).

    One alternation, longest first, so the leftmost match is the longest that
    qualifies: "West Virginia", never "Virginia". Lowercase "west virginia" does
    not qualify on a block without West Virginia, so it hides nothing, and the
    block's "virginia" inside it is still checked."""
    index = _catalog_index(catalog, extra_names)
    alternatives: list[tuple[str, str]] = []
    for fold, names in index.names_by_fold.items():
        if any(name in block_teams for name in names):
            alternatives.append((fold, f"(?i:{re.escape(fold)})"))
        else:
            alternatives.append((fold, _capitalized(names[0])))
    for alias, teams in index.alias_teams.items():
        if any(team in block_teams for team in teams):
            alternatives.append((alias, re.escape(alias)))
    return _longest_first(alternatives)


def _capitalized(name: str) -> str:
    """A pattern for `name` with its first character uppercase, the rest in any case."""
    return re.escape(name[0].upper()) + f"(?i:{re.escape(name[1:])})"


def _longest_first(alternatives: Sequence[tuple[str, str]]) -> re.Pattern[str]:
    ordered = sorted(alternatives, key=lambda item: len(item[0]), reverse=True)
    return re.compile(r"(?<!\w)(?:" + "|".join(pattern for _, pattern in ordered) + r")(?!\w)")


def _check_prose(
    text: str,
    name_claims: Mapping[str, str],
    rank_claims: Collection[str],
    block: _Block,
    index: _CatalogIndex,
    name_re: re.Pattern[str],
) -> list[str]:
    placeholders = list(_PLACEHOLDER_RE.finditer(text))
    masked = _PLACEHOLDER_RE.sub(lambda match: _MASK * len(match.group(0)), text)
    errors: list[str] = []
    if "{" in masked or "}" in masked:
        errors.append('the text has a "{" or "}" that is not part of a placeholder like {id}')

    breaks = [(match.start(), match.end()) for match in _SENTENCE_BREAK_RE.finditer(masked)]
    no_detail = [(m.start(), m.end(), m.group(0)) for m in _NO_DETAIL_RE.finditer(masked)]

    def holdings(start: int, end: int) -> str:
        left = max((b_end for _, b_end in breaks if b_end <= start), default=0)
        right = min((b_start for b_start, _ in breaks if b_start >= end), default=len(masked))
        return block.holdings(_block_teams_in(masked[left:right], block, index, name_re))

    def typed(what: str, match: re.Match[str], rule: str) -> str:
        # The phrase only picks the wording: the token is rejected either way.
        for start, end, phrase in no_detail:
            if start <= match.start() and match.end() <= end:
                return (
                    f"the prose {what} {_quote(match.group(0))} in {_quote(phrase)}; the FACT "
                    "BLOCK holds no conference or in-game detail, so leave it out"
                )
        return (
            f"the prose {what} {_quote(match.group(0))}; {rule}. "
            f"{holdings(match.start(), match.end())}"
        )

    every_number = "every number must come from a claim placeholder"
    for match in _DIGITS_RE.finditer(masked):
        errors.append(typed("types the number", match, every_number))
    words_masked = masked
    for match in _WORD_RECORD_RE.finditer(masked):
        errors.append(typed("spells out the number", match, every_number))
        words_masked = _mask_span(words_masked, match.start(), match.end())
    for match in _NUMBER_WORD_RE.finditer(words_masked):
        errors.append(typed("spells out the number", match, every_number))
    for match in _ORDINAL_RE.finditer(masked):
        errors.append(typed("uses the ordinal", match, "a rank must come from a rank claim"))

    placeholder_ending = {match.end(): match.group(1) for match in placeholders}
    placeholder_starting = {match.start(): match.group(1) for match in placeholders}
    # Where a team name ends: a mascot word right after one is a nickname.
    # A rank placeholder prints "No. 3 Georgia", so it ends in a team name too.
    name_ends = {match.end() for match in placeholders if match.group(1) in rank_claims}
    names_masked = masked
    for match in name_re.finditer(masked):
        names_masked = _mask_span(names_masked, match.start(), match.end())
        found = match.group(0)
        names = index.names_by_fold.get(found.casefold())
        if names is not None:
            name_ends.add(match.end())
            in_block = [name for name in names if name in block.teams]
            if not in_block:
                errors.append(
                    f"{_quote(found)} is not a team in the fact block; its teams are: "
                    f"{', '.join(block.teams)}"
                )
                continue
            spelled = found if found in in_block else in_block[0]
            if found != spelled:
                errors.append(
                    f"{_quote(found)} must be written exactly as the fact block spells it: "
                    f"{_quote(spelled)}"
                )
            left, right = match.start(), match.end()
            while left > 0 and masked[left - 1].isspace():
                left -= 1
            while right < len(masked) and masked[right].isspace():
                right += 1
            for placeholder in (placeholder_ending.get(left), placeholder_starting.get(right)):
                if placeholder is not None and name_claims.get(placeholder) == spelled:
                    errors.append(
                        f"{{{placeholder}}} already prints the name {_quote(spelled)}; delete "
                        f"the {_quote(found)} typed beside it"
                    )
            continue
        teams = index.alias_teams.get(found)
        if teams is not None:
            errors.append(_nickname_error(found, "another name", teams, block))

    if index.mascot_re is not None:
        for match in index.mascot_re.finditer(names_masked):
            form = match.group(0)
            teams = index.mascot_teams.get(form)
            if teams is None:
                continue
            # A multi-word mascot counts anywhere; a single word ("Pride",
            # "Tide") only after "the" or a team name (coordinator decision 3).
            if len(form.split()) == 1 and not _introduced(masked, match.start(), name_ends):
                continue
            errors.append(_nickname_error(form, "a nickname", teams, block))
    return errors


def _introduced(masked: str, start: int, name_ends: Collection[int]) -> bool:
    """Whether the word at `start` follows "the"/"The" or the end of a team
    name, across whitespace ("the Tide", "Texas Longhorns")."""
    left = start
    while left > 0 and masked[left - 1].isspace():
        left -= 1
    if left == start:
        return False
    if left in name_ends:
        return True
    return masked[max(0, left - len("the")) : left] in _THE and (
        left == len("the") or not _WORD_CHAR_RE.match(masked[left - len("the") - 1])
    )


def _nickname_error(found: str, what: str, teams: Sequence[str], block: _Block) -> str:
    in_block = [team for team in teams if team in block.teams]
    if in_block:
        spelled = ", ".join(_quote(team) for team in in_block)
        return (
            f"{_quote(found)} is {what} for {', '.join(in_block)}; write the team's name as "
            f"the fact block spells it: {spelled}"
        )
    shown = ", ".join(teams[:3]) + (f" and {len(teams) - 3} more" if len(teams) > 3 else "")
    return (
        f"{_quote(found)} is {what} for {shown}, not a team in the fact block; its teams "
        f"are: {', '.join(block.teams)}"
    )


def _block_teams_in(
    sentence: str, block: _Block, index: _CatalogIndex, name_re: re.Pattern[str]
) -> list[str]:
    found: list[str] = []
    for match in name_re.finditer(sentence):
        for name in index.names_by_fold.get(match.group(0).casefold(), ()):
            if name in block.teams and name not in found:
                found.append(name)
    return found


def _mask_span(text: str, start: int, end: int) -> str:
    return text[:start] + _MASK * (end - start) + text[end:]


def _quote(value: object) -> str:
    shown = value if isinstance(value, str) else repr(value)
    if len(shown) > _QUOTE_LIMIT:
        shown = shown[: _QUOTE_LIMIT - 3] + "..."
    return f'"{shown}"'


def _type_name(value: object) -> str:
    return "null" if value is None else type(value).__name__
