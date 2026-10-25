"""Typed claims for the QB-vs-QB narration (issue #451, epic #439 step 2).

The narrator types no number on the QB path either: every score, margin,
year, count and record is a `{id}` placeholder whose claim
`api.persona.qb_claims.check_and_render_qb` resolves against the QB FACT
BLOCK and prints. These tests run on real fact blocks from the committed
fixture (`tests/fixtures/qb_blocks.py`), in both directions: an ordinary
on-voice restatement must render, and a typed or unbacked figure, a
misspelled or third player, a hedge or a speculation must be rejected with
feedback naming what the block does hold.

Fixture facts (measured): Kurt Warner career 2.25 / peak 0.45, Steve McNair
0.60 / 0.12, so Warner wins both by 1.65 and 0.33; Donovan McNabb -1.92;
Russell Wilson and Trevor Lawrence both print -0.05; Randall Cunningham has
no qualifying season (214 dropbacks under the 224 line).
"""

from __future__ import annotations

import json

import pytest
from fixtures.qb_blocks import (
    DONOVAN_MCNABB,
    KURT_WARNER,
    PEYTON_MANNING,
    RANDALL_CUNNINGHAM,
    RUSSELL_WILSON,
    STEVE_MCNAIR,
    TOMMY_DEVITO,
    TREVOR_LAWRENCE,
    assert_an_error_says,
    nfl_player_names,
    qb_block,
    qb_check,
    qb_rejected,
    qb_rendered,
)

from api.models import qb_short_names
from api.persona.claims import TOOL_NAME
from api.persona.qb_claims import (
    MAX_QB_CLAIMS,
    QB_GROUNDING_VERSION,
    QB_KINDS,
    check_and_render_qb,
    qb_tool_schema,
)


def _warner_mcnair() -> str:
    return qb_block(KURT_WARNER, STEVE_MCNAIR)


def _mcnair_warner() -> str:
    return qb_block(STEVE_MCNAIR, KURT_WARNER)


def _inconclusive() -> str:
    return qb_block(KURT_WARNER, RANDALL_CUNNINGHAM)


def score(claim_id: str, player: str, measure: str) -> dict[str, object]:
    return {"id": claim_id, "kind": "score", "player": player, "measure": measure}


def margin(claim_id: str, measure: str, player: str) -> dict[str, object]:
    return {"id": claim_id, "kind": "margin", "measure": measure, "player": player}


def winner(claim_id: str, measure: str) -> dict[str, object]:
    return {"id": claim_id, "kind": "winner", "measure": measure}


YEAR: dict[str, object] = {"id": "yr", "kind": "year"}


# ---------------------------------------------------------------------------
# the fact block itself
# ---------------------------------------------------------------------------


def test_the_fact_block_carries_the_verdict_and_no_z_score_detail() -> None:
    block = json.loads(_warner_mcnair())
    assert block["qb_score"]["career_winner"] == "a"
    assert block["a"]["display_name"] == "Kurt Warner"
    assert block["a"]["short_name"] == "Warner"
    assert block["b"]["short_name"] == "McNair"
    assert block["data_first_season"] == 1999
    # The narrator explains the score in bar words; the z-score machinery and
    # the weights stay out of what it reads.
    assert "weights" not in block["qb_score"]
    season = block["qb_score"]["a"]["seasons"][0]
    assert set(season) == {"season", "dropbacks", "qualifies"}


# ---------------------------------------------------------------------------
# each kind resolves and prints from the block
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "player,measure,printed",
    [
        ("Warner", "career", "2.25"),
        ("Warner", "peak", "0.45"),
        ("McNair", "career", "0.60"),
        ("Steve McNair", "peak", "0.12"),
    ],
)
def test_a_score_prints_two_decimals_from_the_block(
    player: str, measure: str, printed: str
) -> None:
    text = f"{player} sits at {{s}} on the {measure}."
    assert qb_rendered(_warner_mcnair(), text, score("s", player, measure)) == (
        f"{player} sits at {printed} on the {measure}."
    )


def test_a_negative_score_keeps_its_sign() -> None:
    block = qb_block(DONOVAN_MCNABB, KURT_WARNER)
    rendered = qb_rendered(block, "McNabb finished at {s}.", score("s", "McNabb", "career"))
    assert rendered == "McNabb finished at -1.92."


def test_a_score_names_its_player_unless_the_sentence_just_did() -> None:
    rendered = qb_rendered(
        _warner_mcnair(),
        "It's {sw} to {sm} on the career.",
        score("sw", "Warner", "career"),
        score("sm", "McNair", "career"),
    )
    assert rendered == "It's Warner 2.25 to McNair 0.60 on the career."


@pytest.mark.parametrize("block", [_warner_mcnair, _mcnair_warner], ids=["a-wins", "b-wins"])
@pytest.mark.parametrize("measure,printed", [("career", "1.65"), ("peak", "0.33")])
def test_a_margin_prints_unsigned_from_its_own_measure(
    block: object, measure: str, printed: str
) -> None:
    assert callable(block)
    rendered = qb_rendered(
        block(),
        f"Warner takes the {measure} by {{m}}.",
        margin("m", measure, "Warner"),
    )
    assert rendered == f"Warner takes the {measure} by {printed}."


def test_a_margin_must_be_claimed_for_the_player_ahead() -> None:
    errors = qb_rejected(_warner_mcnair(), "McNair by {m}.", margin("m", "career", "McNair"))
    assert_an_error_says(errors, "Kurt Warner", "ahead", "2.25", "0.60")


def test_a_margin_between_two_scores_that_print_the_same_is_rejected() -> None:
    block = qb_block(RUSSELL_WILSON, TREVOR_LAWRENCE)
    errors = qb_rejected(block, "Lawrence by {m}.", margin("m", "career", "Lawrence"))
    assert_an_error_says(errors, "-0.05", "same")
    # And the winner is still named: any margin counts.
    assert qb_rendered(block, "{w} takes the career.", winner("w", "career")) == (
        "Lawrence takes the career."
    )


@pytest.mark.parametrize("measure", ["career", "peak"])
def test_a_winner_claim_prints_the_winners_name(measure: str) -> None:
    assert qb_rendered(_mcnair_warner(), f"{{w}} owns the {measure}.", winner("w", measure)) == (
        f"Warner owns the {measure}."
    )


def test_the_year_claim_prints_the_scores_first_season() -> None:
    rendered = qb_rendered(
        _warner_mcnair(), "The play-by-play starts in {yr}, so that's what counts.", YEAR
    )
    assert rendered == "The play-by-play starts in 1999, so that's what counts."


def test_a_career_start_prints_the_players_first_career_season() -> None:
    rendered = qb_rendered(
        _warner_mcnair(),
        "Warner's career started in {ws}, and the books open in {yr}.",
        {"id": "ws", "kind": "career_start", "player": "Warner"},
        YEAR,
    )
    assert rendered == "Warner's career started in 1998, and the books open in 1999."


@pytest.mark.parametrize(
    "claim,printed",
    [
        ({"of": "qualifying_seasons", "player": "Warner"}, "one"),
        ({"of": "qualifying_seasons", "player": "Cunningham"}, "zero"),
        ({"of": "min_dropbacks"}, "224"),
        ({"of": "peak_seasons"}, "five"),
    ],
)
def test_a_count_prints_ap_style(claim: dict[str, object], printed: str) -> None:
    rendered = qb_rendered(_inconclusive(), "That's {n}.", {"id": "n", "kind": "count", **claim})
    assert rendered == f"That's {printed}."


def test_a_count_opening_a_sentence_is_capitalized() -> None:
    rendered = qb_rendered(
        _inconclusive(),
        "{n} dropbacks is the line.",
        {"id": "n", "kind": "count", "of": "min_dropbacks"},
    )
    assert rendered == "224 dropbacks is the line."
    rendered = qb_rendered(
        _inconclusive(),
        "Cunningham came up short. {n} qualifying seasons.",
        {"id": "n", "kind": "count", "of": "qualifying_seasons", "player": "Cunningham"},
    )
    assert rendered == "Cunningham came up short. Zero qualifying seasons."


@pytest.mark.parametrize(
    "kind,season_type,player,printed",
    [
        ("record", "regular", "Warner", "13-3"),
        ("record", "postseason", "Warner", "3-0"),
        ("record", "regular", "McNair", "9-2"),
        ("head_to_head", "regular", "Warner", "0-1"),
        ("head_to_head", "postseason", "Warner", "1-0"),
        ("head_to_head", "regular", "McNair", "1-0"),
    ],
)
def test_records_print_from_the_players_side(
    kind: str, season_type: str, player: str, printed: str
) -> None:
    claim: dict[str, object] = {
        "id": "r",
        "kind": kind,
        "player": player,
        "season_type": season_type,
    }
    for block in (_warner_mcnair(), _mcnair_warner()):
        assert qb_rendered(block, f"{player} went {{r}}.", claim) == f"{player} went {printed}."


def test_a_record_the_block_does_not_hold_is_rejected() -> None:
    block = qb_block(RANDALL_CUNNINGHAM, TOMMY_DEVITO)
    errors = qb_rejected(
        block,
        "DeVito went {r}.",
        {"id": "r", "kind": "record", "player": "DeVito", "season_type": "postseason"},
    )
    assert_an_error_says(errors, "Tommy DeVito", "postseason")
    errors = qb_rejected(
        block,
        "DeVito went {r} against him.",
        {"id": "r", "kind": "head_to_head", "player": "DeVito", "season_type": "regular"},
    )
    assert_an_error_says(errors, "never met")


# ---------------------------------------------------------------------------
# the inconclusive verdict: no winner, no margin, no score for the unqualified
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("measure", ["career", "peak"])
def test_an_inconclusive_block_rejects_a_winner_claim(measure: str) -> None:
    errors = qb_rejected(_inconclusive(), "{w} wins it.", winner("w", measure))
    assert_an_error_says(errors, "inconclusive", "Randall Cunningham")


def test_an_inconclusive_block_rejects_a_margin_and_the_unqualified_score() -> None:
    errors = qb_rejected(_inconclusive(), "Warner by {m}.", margin("m", "career", "Warner"))
    assert_an_error_says(errors, "inconclusive")
    errors = qb_rejected(
        _inconclusive(), "Cunningham sits at {s}.", score("s", "Cunningham", "career")
    )
    assert_an_error_says(errors, "Randall Cunningham", "no qualifying season", "224")


def test_an_inconclusive_narration_without_a_winner_renders() -> None:
    rendered = qb_rendered(
        _inconclusive(),
        "Cunningham never got to {n} dropbacks in a season we've got, so the body of work "
        "isn't there. Inconclusive, and the books only open in {yr}.",
        {"id": "n", "kind": "count", "of": "min_dropbacks"},
        YEAR,
    )
    assert rendered == (
        "Cunningham never got to 224 dropbacks in a season we've got, so the body of work "
        "isn't there. Inconclusive, and the books only open in 1999."
    )


# ---------------------------------------------------------------------------
# an ordinary on-voice narration is accepted (no false rejections)
# ---------------------------------------------------------------------------


def test_the_gates_example_sentence_passes() -> None:
    rendered = qb_rendered(
        _warner_mcnair(),
        "Warner takes the career by a nose, and the books only open in {yr}.",
        YEAR,
    )
    assert rendered == "Warner takes the career by a nose, and the books only open in 1999."


def test_a_full_on_voice_narration_renders() -> None:
    rendered = qb_rendered(
        qb_block(PEYTON_MANNING, KURT_WARNER),
        "{wc} takes the career and the peak, {sw} to {sm}, measured play for play against "
        "the QBs of his own season. Manning's first year isn't in the books - the "
        "play-by-play starts in {yr} - and that's what got counted. Kurt Warner went {r} "
        "as a starter, but the score never counted wins.",
        winner("wc", "career"),
        score("sw", "Warner", "career"),
        score("sm", "Manning", "career"),
        YEAR,
        {"id": "r", "kind": "record", "player": "Kurt Warner", "season_type": "regular"},
    )
    assert rendered == (
        "Warner takes the career and the peak, 2.25 to Manning 1.43, measured play for play "
        "against the QBs of his own season. Manning's first year isn't in the books - the "
        "play-by-play starts in 1999 - and that's what got counted. Kurt Warner went 13-3 "
        "as a starter, but the score never counted wins."
    )


def test_a_close_call_that_still_names_the_winner_passes() -> None:
    block = qb_block(RUSSELL_WILSON, TREVOR_LAWRENCE)
    rendered = qb_rendered(
        block,
        "Photo finish, but {w} takes it by a nose. Wilson's career started in {ws}, "
        "before the books open in {yr}.",
        winner("w", "career"),
        {"id": "ws", "kind": "career_start", "player": "Wilson"},
        YEAR,
    )
    assert rendered == (
        "Photo finish, but Lawrence takes it by a nose. Wilson's career started in 2012, "
        "before the books open in 1999."
    )


# ---------------------------------------------------------------------------
# rejections, each with feedback naming what the block holds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,token",
    [
        ("Warner put up a 2.25 career.", "2.25"),
        ("Warner had two great years.", "two"),
        ("McNair finishes second here.", "second"),
        ("Warner went thirteen and three.", "thirteen and three"),
    ],
    ids=["digit", "number-word", "ordinal", "word-record"],
)
def test_a_typed_number_is_rejected_with_the_blocks_holdings(text: str, token: str) -> None:
    errors = qb_rejected(_warner_mcnair(), text)
    assert_an_error_says(errors, f'"{token}"', "The fact block holds", "Kurt Warner career 2.25")


@pytest.mark.parametrize(
    "player",
    ["Kurt Warnr", "warner", "Kurt"],
    ids=["misspelled", "wrong-case", "first-name-only"],
)
def test_a_claim_on_a_misspelled_player_is_rejected(player: str) -> None:
    errors = qb_rejected(_warner_mcnair(), "He's at {s}.", score("s", player, "career"))
    assert_an_error_says(errors, "Kurt Warner", "Warner")


def test_a_claim_about_a_third_player_is_rejected() -> None:
    errors = qb_rejected(_warner_mcnair(), "He's at {s}.", score("s", "Peyton Manning", "career"))
    assert_an_error_says(errors, "not a player in the fact block", "Kurt Warner", "Steve McNair")


@pytest.mark.parametrize(
    "text,needle",
    [
        ("Warnr takes the career by a nose.", "did you mean"),
        ("WARNER takes the career by a nose.", "Warner"),
        ("Look, Kurt takes the career by a nose.", "Kurt Warner"),
        ("Mcnair gets left behind.", "McNair"),
    ],
    ids=["misspelled", "shouted", "first-name-only", "wrong-case"],
)
def test_a_misspelled_name_in_the_prose_is_rejected(text: str, needle: str) -> None:
    errors = qb_rejected(_warner_mcnair(), text)
    assert_an_error_says(errors, needle)


def test_a_third_player_named_in_the_prose_is_rejected() -> None:
    assert "Marshall Faulk" in nfl_player_names()
    errors = qb_rejected(_warner_mcnair(), "Warner had Marshall Faulk behind him, sure.")
    assert_an_error_says(errors, "Marshall Faulk", "Kurt Warner", "Steve McNair")


def test_an_unknown_kind_is_rejected_naming_the_kinds() -> None:
    errors = qb_rejected(
        _warner_mcnair(), "Warner had {t} touchdowns.", {"id": "t", "kind": "touchdowns"}
    )
    assert_an_error_says(errors, "unknown kind", *QB_KINDS)


def test_a_team_claim_kind_is_not_a_qb_kind() -> None:
    errors = qb_rejected(
        _warner_mcnair(), "Look at {r}.", {"id": "r", "kind": "rating", "team": "Warner"}
    )
    assert_an_error_says(errors, "unknown kind")


@pytest.mark.parametrize(
    "text",
    [
        "Too close to call, honestly.",
        "This one's a toss-up.",
        "They're basically even.",
        "Dead heat.",
        "It's a coin flip.",
    ],
)
def test_a_hedge_that_withholds_the_verdict_is_rejected(text: str) -> None:
    errors = qb_rejected(_warner_mcnair(), text)
    assert_an_error_says(errors, "always a winner")


@pytest.mark.parametrize(
    "text",
    [
        "Give McNair his early years and it would've flipped.",
        "If we had his rookie year, McNair takes it.",
        "With those years McNair wins.",
    ],
)
def test_speculating_about_the_missing_seasons_is_rejected(text: str) -> None:
    errors = qb_rejected(_warner_mcnair(), text)
    assert_an_error_says(errors, "missing seasons")


def test_z_score_jargon_is_rejected() -> None:
    errors = qb_rejected(_warner_mcnair(), "Warner is a full z-score clear.")
    assert_an_error_says(errors, "z-score")


def test_placeholder_and_claim_bookkeeping_errors() -> None:
    errors = qb_rejected(_warner_mcnair(), "Warner at {s}.", YEAR)
    assert_an_error_says(errors, "{s}", "no claim")
    assert_an_error_says(errors, '"yr"', "not used")


def test_the_claim_cap_is_enforced() -> None:
    claims: list[dict[str, object]] = [
        {"id": f"y{i}", "kind": "year"} for i in range(MAX_QB_CLAIMS + 1)
    ]
    text = " ".join(f"{{y{i}}}." for i in range(MAX_QB_CLAIMS + 1))
    errors = qb_rejected(_warner_mcnair(), text, *claims)
    assert_an_error_says(errors, "over the limit", str(MAX_QB_CLAIMS))


@pytest.mark.parametrize("tool_input", [None, [], "text", {"text": "x"}, {"claims": []}])
def test_malformed_input_only_ever_produces_errors(tool_input: object) -> None:
    outcome = check_and_render_qb(tool_input, _warner_mcnair(), nfl_player_names())
    assert outcome.text is None and outcome.errors


def test_a_team_fact_block_is_not_a_qb_fact_block() -> None:
    with pytest.raises(ValueError, match="QB fact block"):
        check_and_render_qb({"text": "x", "claims": []}, '{"year": 2005}', frozenset())


# ---------------------------------------------------------------------------
# the short names, the tool and the version
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "a,b,expected",
    [
        ("Kurt Warner", "Steve McNair", ("Warner", "McNair")),
        ("Peyton Manning", "Eli Manning", (None, None)),
        ("Odell Beckham Jr.", "Robert Griffin III", ("Beckham", "Griffin")),
        ("Josh Allen", "Allen Robinson", (None, "Robinson")),
        ("Pele", "C.J. Stroud", (None, "Stroud")),
    ],
)
def test_short_names_are_last_names_only_when_they_are_unambiguous(
    a: str, b: str, expected: tuple[str | None, str | None]
) -> None:
    assert qb_short_names(a, b) == expected


def test_the_qb_tool_is_submit_narration_with_the_qb_kinds() -> None:
    schema = qb_tool_schema()
    assert schema["name"] == TOOL_NAME
    claim = schema["input_schema"]["properties"]["claims"]["items"]
    assert claim["properties"]["kind"]["enum"] == list(QB_KINDS)
    assert "team" not in claim["properties"]
    assert set(QB_KINDS) >= {"score", "margin", "winner", "year", "career_start", "count"}


def test_the_qb_grounding_version_is_its_own() -> None:
    from api.persona.claims import GROUNDING_VERSION

    assert GROUNDING_VERSION.startswith("claims-")
    assert QB_GROUNDING_VERSION.startswith("qb-")


def test_qb_check_is_pure_on_the_block() -> None:
    first = qb_check(_warner_mcnair(), "Warner at {s}.", score("s", "Warner", "career"))
    second = qb_check(_warner_mcnair(), "Warner at {s}.", score("s", "Warner", "career"))
    assert first == second
