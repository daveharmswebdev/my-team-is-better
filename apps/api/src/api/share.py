"""Share-link preview pages (issue #185).

A share link holds a question, never an answer (#184). Link-preview
scrapers (chat apps, social sites) run no JavaScript, so the SPA's static
`index.html` tags describe every shared link the same way. These two routes
answer a share link's own query with a small HTML page whose Open Graph and
Twitter tags describe the question asked, and which sends a human straight
on to the SPA page with that question:

- `GET /api/share?<verdict share query>`: the home page's share link, the
  query `apps/web/src/pages/HomePage/shareLink.ts` writes (`q`, `sport`,
  `year`, `engine`, `team` | `a`, `b`, `for`). Redirects to
  `PUBLIC_WEB_URL + "/?" + query`.
- `GET /api/share/nfl/compare?a=<id>&b=<id>`: the QB compare page's link.
  Redirects to `PUBLIC_WEB_URL + "/nfl/compare?a=..&b=.."`.

The web domain proxies `/s` and `/s/nfl/compare` here, so a page must work
served from either origin: every URL in it is absolute.

**What the text may come from.** The query, the sport's team catalog
(`list_team_records` resolved by `api.verdict.resolve_user_team`, so a team
previews under its canonical name: `OSU` is Ohio State) and the player read
path `/api/players/{player_id}` uses (`get_player_career`). Never the
narrator, the Claude client or a verdict: a preview is fetched by every app
a link is pasted into, and must cost nothing. `for` never appears in the
text.

**Validation mirrors the web exactly, all or nothing.** A link the web would
refuse to open (`fromShareSearch` returning null; `parsePick` answering
"invalid") gets the generic site text and a redirect to the page's home. A
link the web would open, whose teams or players don't resolve (or name one
side twice, a question the API refuses), keeps its redirect and falls back
to the generic text only. Nothing here returns a 4xx or 5xx for any query:
the page is always a 200, so these routes are left out of `/openapi.json`
(they are HTML for scrapers, not part of the JSON API) and read the query
by hand instead of declaring parameters FastAPI would 422 on.

**Escaping.** A third party writes the query, so every interpolated value is
escaped for its context: `html.escape` for HTML text and attribute values,
and for the one JS string (the redirect target in `location.replace`) a JSON
literal with `<`, `>` and `&` written as `\\u` escapes, so neither `</script>`
nor `<!--` can appear inside the script.
"""

from __future__ import annotations

import html
import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlencode

from cfb_strength.contracts import UnknownPlayerError
from cfb_strength.evidence.proof import StaleDatabaseError
from cfb_strength.players import get_player_career
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from api.config import PUBLIC_WEB_URL
from api.deps import get_db_conn
from api.repositories.teams import TeamRecord, list_team_records
from api.verdict import resolve_user_team

router = APIRouter(prefix="/api/share", tags=["share"], include_in_schema=False)

SITE_NAME: Final = "My Team Is Better"
GENERIC_TITLE: Final = "My Team Is Better"
# Verbatim from apps/web/index.html.
GENERIC_DESCRIPTION: Final = (
    "Ask whose team is better and the guy at the end of the bar settles it, "
    "with the math to back him up."
)
OG_IMAGE: Final = "https://my-team-is-better-web.onrender.com/og-image.png"
OG_IMAGE_ALT: Final = (
    "The words My Team Is Better beside a football on a leather band, "
    "for college football and the NFL."
)
CACHE_CONTROL: Final = "public, max-age=300"

SPORT_LABELS: Final = {"cfb": "college football", "nfl": "NFL"}
# The web's DISPLAYED_METHODS (apps/web/src/lib/methods.ts), not every
# method the API knows: the landing page seeds the Engine toggle from it.
DISPLAYED_ENGINES: Final = frozenset({"keener", "elo"})
QUESTION_TYPES: Final = frozenset({"champion", "team_case", "compare"})

# shareLink.ts's MAX_TEAM_NAME_LENGTH, in JS `.length` units (UTF-16).
MAX_TEAM_NAME_LENGTH: Final = 64
TEAM_NAME_PUNCTUATION: Final = frozenset(" &'.()-")
# `[0-9]`, not `\d`: Python's `\d` matches every Unicode digit, the web's
# (no `u` flag on FOUR_DIGIT_YEAR; `\d+` in parsePick) only ASCII ones.
FOUR_DIGIT_YEAR: Final = re.compile(r"[0-9]{4}")
PLAYER_ID: Final = re.compile(r"[0-9]+")
MAX_SAFE_INTEGER: Final = 2**53 - 1

# `String.prototype.trim`'s set: WhiteSpace (TAB, VT, FF, SP, NBSP, ZWNBSP
# and every Zs) plus LineTerminator (LF, CR, LS, PS). Not `str.strip()`'s,
# which also strips U+001C-U+001F and U+0085 and keeps U+FEFF.
_JS_WHITESPACE: Final = frozenset("\t\n\v\f\r  ﻿  ")

QB_GROUP: Final = "QB"


def js_trim(value: str) -> str:
    """`value.trim()` as JavaScript does it."""

    def is_space(char: str) -> bool:
        return char in _JS_WHITESPACE or unicodedata.category(char) == "Zs"

    start, end = 0, len(value)
    while start < end and is_space(value[start]):
        start += 1
    while end > start and is_space(value[end - 1]):
        end -= 1
    return value[start:end]


def _js_length(value: str) -> int:
    """JS `.length`: UTF-16 code units, so an astral character counts 2."""
    return len(value.encode("utf-16-le")) // 2


def is_plain_team_name(value: str) -> bool:
    """shareLink.ts's `isPlainTeamName`: non-empty, at most 64 UTF-16 code
    units, and matching `^[\\p{L}\\p{N} &'.()-]+$`. `str.isalnum()` is true
    exactly for the letter (`L*`) and number (`N*`) categories."""
    return 0 < _js_length(value) <= MAX_TEAM_NAME_LENGTH and all(
        char.isalnum() or char in TEAM_NAME_PUNCTUATION for char in value
    )


@dataclass(frozen=True)
class VerdictQuestion:
    """A share link the web would open: `fromShareSearch`'s submission."""

    question_type: str
    sport: str
    year: str
    engine: str
    teams: tuple[str, ...]  # (team,) for team_case, (a, b) for compare
    for_team: str | None

    def query(self) -> str:
        pairs = [
            ("q", self.question_type),
            ("sport", self.sport),
            ("year", self.year),
            ("engine", self.engine),
        ]
        if self.question_type == "team_case":
            pairs.append(("team", self.teams[0]))
        elif self.question_type == "compare":
            pairs += [("a", self.teams[0]), ("b", self.teams[1])]
        if self.for_team is not None:
            pairs.append(("for", self.for_team))
        return urlencode(pairs)


def _first(request: Request, key: str) -> str | None:
    """`URLSearchParams.get`: the first value of a repeated key."""
    values = request.query_params.getlist(key)
    return values[0] if values else None


def parse_verdict_question(request: Request) -> VerdictQuestion | None:
    """`fromShareSearch`, rule for rule; `None` where it returns null."""

    def read(key: str) -> str:
        return js_trim(_first(request, key) or "")

    question_type = read("q")
    sport = read("sport")
    engine = read("engine")
    year = read("year")
    if (
        sport not in SPORT_LABELS
        or engine not in DISPLAYED_ENGINES
        or FOUR_DIGIT_YEAR.fullmatch(year) is None
    ):
        return None
    if question_type == "champion":
        # #198: `for` is ignored on a champion link, not validated.
        return VerdictQuestion(question_type, sport, year, engine, (), None)

    for_team = read("for")
    if for_team != "" and not is_plain_team_name(for_team):
        return None
    for_value = for_team or None

    if question_type == "team_case":
        team = read("team")
        if not is_plain_team_name(team):
            return None
        return VerdictQuestion(question_type, sport, year, engine, (team,), for_value)
    if question_type == "compare":
        a, b = read("a"), read("b")
        if not (is_plain_team_name(a) and is_plain_team_name(b)):
            return None
        return VerdictQuestion(question_type, sport, year, engine, (a, b), for_value)
    return None


def _canonical_teams(
    conn: sqlite3.Connection, sport: str, teams: tuple[str, ...]
) -> tuple[str, ...] | None:
    """Each team's canonical name in `sport`'s catalog, or `None` when one
    doesn't resolve, two name the same team, or the catalog can't be read."""
    try:
        records: list[TeamRecord] = list_team_records(conn, sport)
    except (StaleDatabaseError, sqlite3.Error):
        return None
    names = tuple(resolve_user_team(records, team) for team in teams)
    resolved = tuple(name for name in names if name is not None)
    if len(resolved) != len(teams) or len(set(resolved)) != len(resolved):
        return None
    return resolved


def verdict_text(conn: sqlite3.Connection, question: VerdictQuestion) -> tuple[str, str]:
    """The (title, description) for a valid verdict link."""
    sport, year = SPORT_LABELS[question.sport], question.year
    if question.question_type == "champion":
        return (
            f"Best {sport} team of {year}",
            f"The {year} {sport} season, ranked by the math. See who comes out on top.",
        )
    names = _canonical_teams(conn, question.sport, question.teams)
    if names is None:
        return GENERIC_TITLE, GENERIC_DESCRIPTION
    if question.question_type == "team_case":
        (team,) = names
        return (
            f"The case for {team}, {year}",
            f"How good was {team} in {year}? The numbers make the case.",
        )
    a, b = names
    return f"{a} vs. {b}, {year}", f"{a} or {b}? The numbers settle it."


def parse_player_id(raw: str | None) -> int | None:
    """`parsePick` in PlayerComparePage.tsx, where only an id is valid:
    ASCII digits, untrimmed, and a JS safe integer. Missing or empty is
    `None` here (no pick is not a shareable comparison)."""
    if raw is None or PLAYER_ID.fullmatch(raw) is None:
        return None
    # Bounded before `int()`: a 5000-digit string is still just "invalid".
    digits = raw.lstrip("0") or "0"
    if len(digits) > len(str(MAX_SAFE_INTEGER)):
        return None
    player_id = int(digits)
    return player_id if player_id <= MAX_SAFE_INTEGER else None


def player_text(conn: sqlite3.Connection, a: int, b: int) -> tuple[str, str]:
    """The (title, description) for a valid player compare link. The QB
    line when both are quarterbacks: the position-group rule by which
    `/api/players/compare` carries the QB score."""
    if a == b:
        return GENERIC_TITLE, GENERIC_DESCRIPTION
    try:
        career_a = get_player_career(conn, sport="nfl", player_id=a)
        career_b = get_player_career(conn, sport="nfl", player_id=b)
    except (UnknownPlayerError, sqlite3.Error):
        return GENERIC_TITLE, GENERIC_DESCRIPTION
    name_a, name_b = career_a.display_name, career_b.display_name
    title = f"{name_a} vs. {name_b}"
    if career_a.group == QB_GROUP and career_b.group == QB_GROUP:
        return title, "Two quarterbacks, one era-adjusted score. The numbers settle it."
    return title, f"{name_a} or {name_b}? The numbers settle it."


def _script_string(value: str) -> str:
    """`value` as a JS string literal safe inside a `<script>` element."""
    return json.dumps(value).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def render_share_page(title: str, description: str, target: str) -> str:
    """The preview page: tags describing the question, then a redirect to
    `target` as a meta refresh, a script and a visible link."""
    t, d, u = html.escape(title), html.escape(description), html.escape(target)
    image, alt = html.escape(OG_IMAGE), html.escape(OG_IMAGE_ALT)
    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        f"<title>{t}</title>\n"
        f'<meta name="description" content="{d}">\n'
        '<meta property="og:type" content="website">\n'
        f'<meta property="og:site_name" content="{html.escape(SITE_NAME)}">\n'
        f'<meta property="og:title" content="{t}">\n'
        f'<meta property="og:description" content="{d}">\n'
        f'<meta property="og:url" content="{u}">\n'
        f'<meta property="og:image" content="{image}">\n'
        '<meta property="og:image:type" content="image/png">\n'
        '<meta property="og:image:width" content="1200">\n'
        '<meta property="og:image:height" content="630">\n'
        f'<meta property="og:image:alt" content="{alt}">\n'
        '<meta name="twitter:card" content="summary_large_image">\n'
        f'<meta name="twitter:title" content="{t}">\n'
        f'<meta name="twitter:description" content="{d}">\n'
        f'<meta name="twitter:image" content="{image}">\n'
        f'<meta name="twitter:image:alt" content="{alt}">\n'
        '<meta name="robots" content="noindex">\n'
        f'<meta http-equiv="refresh" content="0; url={u}">\n'
        f"<script>location.replace({_script_string(target)});</script>\n"
        "</head>\n"
        "<body>\n"
        f'<p><a href="{u}">{t}</a></p>\n'
        "</body>\n"
        "</html>\n"
    )


def _page(title: str, description: str, target: str) -> HTMLResponse:
    return HTMLResponse(
        render_share_page(title, description, target),
        headers={"Cache-Control": CACHE_CONTROL},
    )


@router.get("", response_class=HTMLResponse)
def share_verdict(
    request: Request, conn: sqlite3.Connection = Depends(get_db_conn)
) -> HTMLResponse:
    """The home page's share link (`/?q=...`), previewed."""
    question = parse_verdict_question(request)
    if question is None:
        return _page(GENERIC_TITLE, GENERIC_DESCRIPTION, f"{PUBLIC_WEB_URL}/")
    title, description = verdict_text(conn, question)
    return _page(title, description, f"{PUBLIC_WEB_URL}/?{question.query()}")


@router.get("/nfl/compare", response_class=HTMLResponse)
def share_player_compare(
    request: Request, conn: sqlite3.Connection = Depends(get_db_conn)
) -> HTMLResponse:
    """The QB compare page's link (`/nfl/compare?a=..&b=..`), previewed."""
    a = parse_player_id(_first(request, "a"))
    b = parse_player_id(_first(request, "b"))
    if a is None or b is None:
        return _page(GENERIC_TITLE, GENERIC_DESCRIPTION, f"{PUBLIC_WEB_URL}/nfl/compare")
    title, description = player_text(conn, a, b)
    return _page(title, description, f"{PUBLIC_WEB_URL}/nfl/compare?a={a}&b={b}")
