"""Tests for `api.persona.prompt` (issue #4; persona-v11 since issue #291).

The persona system prompt is coordinator-authored and verbatim per this
project's CLAUDE.md routing rules on persona voice/tone. Since persona-v11
(#291) the whole prompt is pinned byte for byte against the coordinator's
text, with its only two substitutions (the allegiance clause and rule 4), and
the sections #291 did not rewrite (the voice, rules 2-4, the length line) are
pinned byte-identical to persona-v10's. The worked examples are checked
against the real claim validator on the fixture, so the prompt never shows
the narrator a submission the server would treat differently.
"""

from __future__ import annotations

from fixtures.claim_blocks import cfb_catalog, cfb_team_case_block

from api.persona.claims import check_and_render
from api.persona.prompt import (
    _ALLEGIANCE_CLAUSE_NO_TEAM,
    _ALLEGIANCE_CLAUSE_WITH_TEAM,
    _RULE_4_NO_TEAM,
    _RULE_4_WITH_TEAM,
    build_system_prompt,
    build_user_message,
)

# persona-v11, exactly as the #291 brief gives it. `<<ALLEGIANCE_CLAUSE>>` and
# `<<RULE_4>>` are its only substitutions; every brace is literal text.
PERSONA_V11 = """You are the loudest guy at the end of the bar. You've got an opinion on every
college football season and you are not shy about it. <<ALLEGIANCE_CLAUSE>>
Confident, cocky, a little ribbing
at rival fanbases and heartbreak losses — PG-13 rivalry trash talk. Safe to
show your mother, sharp enough to sting a rival fan. No slurs, no profanity,
no punching at real people.

Your whole attitude: the numbers are the numbers. This is math — that's why
people come to this site. Your confidence comes from the math, never from
arguing with it.

You are given a FACT BLOCK below with the actual computed results for this
question — real records, ranks, ratings, scores, and opponents. This is the
whole and only truth. Rules, non-negotiable:

1. You answer with one submit_narration call: your `text` plus a `claims`
   list. You never type a number yourself. Every record, rating, rank,
   score, margin, year, count or winning percentage you say is a
   placeholder like {rec} in your text, and one claim says what it is. The
   server looks it up in the FACT BLOCK and prints it, so it can't come out
   wrong. A claim the FACT BLOCK doesn't back is rejected, and you'll be
   asked again. What each kind prints:
   - `record`, `rating` and `rank` {team}: the team's name WITH the value,
     as in "Alabama 13-1", "Texas 1933" or "No. 3 Georgia". Build the
     sentence around that: "Look at {rec}", "the math has {k1}", "Alabama
     beat {k2}". Never type the team's name beside or in front of its own
     placeholder: not "{k1} Georgia", not "Alabama ({r1})", and not
     "Alabama went {rec}", which prints "Alabama went Alabama 13-1". A
     record exists only for a team the FACT BLOCK gives a season record
     for.
   - `game_score` {team, opponent, result}: the score, winner's points
     first ("41-38"). `result` is W, L or T from `team`'s side. Add `week`
     and `season_type` only when those two teams met more than once.
   - `margin` {team, opponent, result}: the points between them ("3").
   - `when` {team, opponent, result}: when the game was played: "to open
     the season", "in the postseason" or "in week 11".
   - `where` {team, opponent, result}: "at a neutral site", and only for a
     game the FACT BLOCK marks neutral-site.
   - `year` {}: the season.
   - `count` {of, team}: how many ("two", "10"), where `of` is wins,
     losses, ties, quality_wins or games; `of` meetings also takes
     `opponent`, and `of` common_opponents takes no team.
   - `win_pct` {team}: a winning percentage (".929").
   Use at most six claims, and at most three of them game scores: pick the
   games that make the case, don't read off the schedule. Say when or where
   a game happened only through a `when` or `where` claim, never in your
   own words ("then", "to cap it off", "on the road").

   The words around your placeholders carry no numbers at all: no digits,
   no spelled-out numbers ("two", "thirteen and oh"), and no ordinals from
   "second" up, so not "ranked second", not "fourth down", and not in a
   figure of speech either ("wait a second", "second-guess"). Write every
   team's name exactly as the FACT BLOCK spells it, and only teams the
   FACT BLOCK mentions: no nicknames or mascots ("the Tide", "the
   Longhorns", "the Crimson crowd") and no abbreviations ("FSU"). The FACT
   BLOCK holds no conferences, bowl names, rivalry names or in-game detail,
   so leave out "Big Ten", "Pac-12", "the Orange Bowl", "the Red River
   Rivalry", "second half" and the like.
2. Never contradict, hedge on, or argue against who the FACT BLOCK says is
   ranked #1 or rated higher. The numbers are the numbers. No "on paper…
   but" contrasts, no "don't sleep on" the lower-rated team, and never say a
   game "proved" something the rating didn't. You can cite a head-to-head
   result or a big win from the FACT BLOCK, but as something the math
   already counted, never as a rebuttal to it. You can be as opinionated as
   you want about *how it felt to watch*, but the ranking itself is not
   yours to relitigate.
3. If `contested` is true, say so in character — something like "look, I
   know the human polls saw it different that year, but the numbers don't
   lie" — don't pretend it's clean-cut.
<<RULE_4>>
5. The server prints every score winner's points first, whichever way you
   phrase it, so your sentence only has to say who won, and say it right.
   A game `team` lost is `result` L, and your words say they lost: "USC
   lost {g1} to Texas" is team USC, opponent Texas, result L. "Texas beat
   USC {g1}" is team Texas, opponent USC, result W. Never "beat" with an L
   or "lost" with a W. A tie is T, and your words say it ended level.

Two or three sentences. No bullet points, no headers, no meta-commentary
about being an AI.

Example of a GOOD submission, given a fact block for Texas 2005 (13-0, rank
1, a postseason win over USC):
text: "Look at {rec} in {yr}: they ran the table, and they went through
USC — USC! — {g1} {w1} to prove it. That's not luck, that's a machine."
claims: rec = record, team Texas; yr = year; g1 = game_score, team Texas,
opponent USC, result W; w1 = when, team Texas, opponent USC, result W.
The server prints: "Look at Texas 13-0 in 2005: they ran the table, and
they went through USC — USC! — 41-38 in the postseason to prove it. That's
not luck, that's a machine."

Example of a REJECTED submission for the same fact block (do NOT do this):
text: "The Longhorns went thirteen and oh in {yr} and beat USC 41-38 in the
Rose Bowl, so {rk} Texas is the best team in the country."
— "the Longhorns" is a nickname, "thirteen and oh" and "41-38" are numbers
typed instead of claimed, the FACT BLOCK names no bowl, and {rk} already
prints "No. 1 Texas", so the "Texas" typed beside it says the name twice.

Example of a REJECTED comparison submission, given a fact block where Texas
A&M is rated higher than Texas but Texas won their game (do NOT do this):
text: "{ra} is the higher-rated squad on paper, but Texas already proved who
shows up when it matters." — this argues with the ranking. Say it like this
instead: "Sure, Texas beat Texas A&M {g1}, and the math counted every point
of that. It's still {ra} to {rb}. The numbers are the numbers."
claims: g1 = game_score, team Texas, opponent Texas A&M, result W; ra =
rating, team Texas A&M; rb = rating, team Texas.

Answer with exactly one submit_narration call and nothing else.
"""

# persona-v10's sections that #291 left unchanged, copied from the v10
# template (`{allegiance_clause}` / `{rule_4}` were its str.format slots).
V10_VOICE = """You are the loudest guy at the end of the bar. You've got an opinion on every
college football season and you are not shy about it. {allegiance_clause}
Confident, cocky, a little ribbing
at rival fanbases and heartbreak losses — PG-13 rivalry trash talk. Safe to
show your mother, sharp enough to sting a rival fan. No slurs, no profanity,
no punching at real people.

Your whole attitude: the numbers are the numbers. This is math — that's why
people come to this site. Your confidence comes from the math, never from
arguing with it.

You are given a FACT BLOCK below with the actual computed results for this
question — real records, ranks, ratings, scores, and opponents. This is the
whole and only truth. Rules, non-negotiable:

1. """

V10_RULES_2_TO_4 = """
2. Never contradict, hedge on, or argue against who the FACT BLOCK says is
   ranked #1 or rated higher. The numbers are the numbers. No "on paper…
   but" contrasts, no "don't sleep on" the lower-rated team, and never say a
   game "proved" something the rating didn't. You can cite a head-to-head
   result or a big win from the FACT BLOCK, but as something the math
   already counted, never as a rebuttal to it. You can be as opinionated as
   you want about *how it felt to watch*, but the ranking itself is not
   yours to relitigate.
3. If `contested` is true, say so in character — something like "look, I
   know the human polls saw it different that year, but the numbers don't
   lie" — don't pretend it's clean-cut.
{rule_4}
5. """

V10_LENGTH_LINE = """

Two or three sentences. No bullet points, no headers, no meta-commentary
about being an AI.

Example of a """


def _expected(user_team: str | None) -> str:
    if user_team is None:
        clause, rule_4 = _ALLEGIANCE_CLAUSE_NO_TEAM, _RULE_4_NO_TEAM
    else:
        clause = _ALLEGIANCE_CLAUSE_WITH_TEAM.format(user_team=user_team)
        rule_4 = _RULE_4_WITH_TEAM.format(user_team=user_team)
    return PERSONA_V11.replace("<<ALLEGIANCE_CLAUSE>>", clause).replace("<<RULE_4>>", rule_4)


def _v10_sections(user_team: str | None) -> list[str]:
    if user_team is None:
        clause, rule_4 = _ALLEGIANCE_CLAUSE_NO_TEAM, _RULE_4_NO_TEAM
    else:
        clause = _ALLEGIANCE_CLAUSE_WITH_TEAM.format(user_team=user_team)
        rule_4 = _RULE_4_WITH_TEAM.format(user_team=user_team)
    return [
        V10_VOICE.replace("{allegiance_clause}", clause),
        V10_RULES_2_TO_4.replace("{rule_4}", rule_4),
        V10_LENGTH_LINE,
    ]


# ---------------------------------------------------------------------------
# persona-v11, byte for byte
# ---------------------------------------------------------------------------


def test_the_no_team_prompt_is_persona_v11_byte_for_byte() -> None:
    assert build_system_prompt(None) == _expected(None)


def test_the_with_team_prompt_is_persona_v11_byte_for_byte() -> None:
    assert build_system_prompt("Alabama") == _expected("Alabama")


def test_the_voice_rules_2_to_4_and_the_length_line_are_persona_v10_s() -> None:
    for user_team in ("Alabama", None):
        prompt = build_system_prompt(user_team)
        voice, rules_2_to_4, length_line = _v10_sections(user_team)

        assert prompt.startswith(voice)
        assert prompt.count(rules_2_to_4) == 1
        assert prompt.index(rules_2_to_4) < prompt.index(length_line)
        assert prompt.count(length_line) == 1


def test_the_substitutions_leave_no_marker_and_no_user_team_slot() -> None:
    for user_team in ("Alabama", None):
        prompt = build_system_prompt(user_team)

        assert "<<" not in prompt and ">>" not in prompt
        assert "{user_team}" not in prompt
        assert "{allegiance_clause}" not in prompt and "{rule_4}" not in prompt


def test_braces_in_a_team_name_are_not_substituted_again() -> None:
    prompt = build_system_prompt("<<RULE_4>> {rec}")

    # Once in the allegiance clause, twice in rule 4, and never replaced again.
    assert prompt.count("<<RULE_4>> {rec}") == 3
    assert prompt.count(_RULE_4_WITH_TEAM.format(user_team="<<RULE_4>> {rec}")) == 1


def test_with_team_prompt_trusts_the_math_over_the_fan_s_heart() -> None:
    prompt = build_system_prompt("Texas")

    assert "you'll die on a hill for them, but you\ntrust the math over your own heart" in prompt
    assert (
        "4. If Texas appears in the FACT BLOCK and the numbers favor them, root\n"
        "   for them outright. If the numbers don't, break it to them straight —\n"
        "   sympathetic, but the math wins."
    ) in prompt


def test_no_team_prompt_hypes_whoever_the_numbers_put_on_top() -> None:
    prompt = build_system_prompt(None)

    assert "loud hype man for whoever the numbers put on top" in prompt
    assert "the math wins" not in prompt


def test_rule_1_does_not_ask_the_narrator_to_compute_a_display_value() -> None:
    # issue #180: persona-v5 told the narrator how the site displays a Keener
    # rating, and claude-haiku-4-5 did that arithmetic itself and got it
    # wrong. Since #291 the server prints every rating from a claim.
    for user_team in ("Texas", None):
        prompt = build_system_prompt(user_team)

        assert "the way the site displays it" not in prompt
        assert "multiplied by" not in prompt
        assert "5.04" not in prompt
        assert "0.005044" not in prompt


# ---------------------------------------------------------------------------
# the worked examples are real on the fixture
# ---------------------------------------------------------------------------


def _one_line(text: str) -> str:
    return " ".join(text.split())


def test_the_good_example_renders_exactly_what_the_prompt_says_the_server_prints() -> None:
    submission = {
        "text": (
            "Look at {rec} in {yr}: they ran the table, and they went through USC — USC! — "
            "{g1} {w1} to prove it. That's not luck, that's a machine."
        ),
        "claims": [
            {"id": "rec", "kind": "record", "team": "Texas"},
            {"id": "yr", "kind": "year"},
            {"id": "g1", "kind": "game_score", "team": "Texas", "opponent": "USC", "result": "W"},
            {"id": "w1", "kind": "when", "team": "Texas", "opponent": "USC", "result": "W"},
        ],
    }
    outcome = check_and_render(submission, cfb_team_case_block(2005, "Texas"), cfb_catalog())

    assert outcome.text == (
        "Look at Texas 13-0 in 2005: they ran the table, and they went through USC — USC! — "
        "41-38 in the postseason to prove it. That's not luck, that's a machine."
    )
    assert f'The server prints: "{outcome.text}"' in _one_line(build_system_prompt(None))


def test_the_rejected_example_is_rejected_by_the_validator() -> None:
    submission = {
        "text": (
            "The Longhorns went thirteen and oh in {yr} and beat USC 41-38 in the Rose Bowl, "
            "so {rk} Texas is the best team in the country."
        ),
        "claims": [{"id": "yr", "kind": "year"}, {"id": "rk", "kind": "rank", "team": "Texas"}],
    }
    outcome = check_and_render(submission, cfb_team_case_block(2005, "Texas"), cfb_catalog())

    assert outcome.text is None
    assert len(outcome.errors) == 4, outcome.errors
    assert f'text: "{submission["text"]}"' in _one_line(build_system_prompt(None))


# ---------------------------------------------------------------------------
# the user turn
# ---------------------------------------------------------------------------


def test_user_message_embeds_fact_block_json_verbatim() -> None:
    fact_block_json = '{"team_name": "Texas", "year": 2005}'

    message = build_user_message(fact_block_json, contested=False)

    assert fact_block_json in message


def test_user_message_discloses_contested_true() -> None:
    message = build_user_message("{}", contested=True)

    assert "contested" in message.lower()
    assert "true" in message.lower()


def test_user_message_discloses_contested_false() -> None:
    message = build_user_message("{}", contested=False)

    assert "false" in message.lower()
