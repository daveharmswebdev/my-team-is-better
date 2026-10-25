"""The QB narrator's prompt (issue #451) agrees with its claim check, and a
few more of the check's edges on real fixture blocks.

The prompt's worked GOOD example must render against the fact block it
describes (Kurt Warner vs Steve McNair), and its REJECTED example must be
rejected for the reasons it lists: an example the validator disagrees with
would teach the narrator to fail.
"""

from __future__ import annotations

import re

from fixtures.qb_blocks import (
    KURT_WARNER,
    STEVE_MCNAIR,
    assert_an_error_says,
    qb_block,
    qb_rejected,
    qb_rendered,
)

from api.persona.prompt import build_system_prompt
from api.persona.qb_prompt import build_qb_system_prompt, build_qb_user_message

WILL_LEVIS = 2459892344


def _example(label: str) -> str:
    prompt = build_qb_system_prompt()
    match = re.search(rf"Example of a {label}.*?\ntext: \"(.*?)\"", prompt, re.DOTALL)
    assert match, f"no {label} example in the QB prompt"
    return " ".join(match.group(1).split())


def test_the_good_example_renders_against_its_block() -> None:
    rendered = qb_rendered(
        qb_block(KURT_WARNER, STEVE_MCNAIR),
        _example("GOOD"),
        {"id": "wc", "kind": "winner", "measure": "career"},
        {"id": "sw", "kind": "score", "player": "Warner", "measure": "career"},
        {"id": "sm", "kind": "score", "player": "McNair", "measure": "career"},
        {"id": "yr", "kind": "year"},
        {"id": "h", "kind": "head_to_head", "player": "Warner", "season_type": "postseason"},
    )
    assert rendered.startswith("Warner takes the career and the peak, 2.25 to McNair 0.60")
    assert "before 1999" in rendered and "went 1-0 against McNair" in rendered


def test_the_rejected_example_is_rejected_for_its_stated_reasons() -> None:
    errors = qb_rejected(qb_block(KURT_WARNER, STEVE_MCNAIR), _example("REJECTED"))
    assert_an_error_says(errors, '"2.25"')
    assert_an_error_says(errors, '"0.60"')
    assert_an_error_says(errors, "coin flip")
    assert_an_error_says(errors, "missing seasons")
    assert_an_error_says(errors, '"Kurt"')
    assert_an_error_says(errors, '"second"')


def test_the_qb_prompt_is_the_nfl_bar_guy_and_the_team_prompt_is_untouched() -> None:
    prompt = build_qb_system_prompt()
    assert "NFL" in prompt and "the numbers are the numbers" in prompt
    for banned in ("too close to call", "toss-up", "basically even", "dead heat", "coin flip"):
        assert banned in prompt
    assert "college football" in build_system_prompt(None)
    assert "quarterback" not in build_system_prompt(None)


def test_the_user_message_is_the_fact_block() -> None:
    block = qb_block(KURT_WARNER, STEVE_MCNAIR)
    assert build_qb_user_message(block) == f"FACT BLOCK (JSON):\n{block}"


def test_a_first_name_that_opens_a_sentence_is_prose() -> None:
    block = qb_block(WILL_LEVIS, KURT_WARNER)
    rendered = qb_rendered(
        block,
        "Will anybody argue? {w} takes the career.",
        {"id": "w", "kind": "winner", "measure": "career"},
    )
    assert rendered == "Will anybody argue? Warner takes the career."
    errors = qb_rejected(block, "Look, Will got outplayed.")
    assert_an_error_says(errors, '"Will"', "Will Levis")


def test_a_figure_without_a_name_must_not_follow_the_other_player() -> None:
    errors = qb_rejected(
        qb_block(KURT_WARNER, STEVE_MCNAIR),
        "McNair was already a vet when this one started in {ws}.",
        {"id": "ws", "kind": "career_start", "player": "Warner"},
    )
    assert_an_error_says(errors, "{ws}", "Kurt Warner", "Steve McNair")
