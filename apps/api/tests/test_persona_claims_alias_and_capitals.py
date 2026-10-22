"""Failing-first tests for #318 and #319, two fixes to the typed-claim renderer.

#318: a catalog alias of a team OUTSIDE the fact block (South Alabama's
"USA") is prose to the prose check (coordinator decision 4 on #290: no error,
so "ME" and "UK" stay English), but it is still another team sitting between
a figure and its team's last mention. Before the fix, "Alabama's rival USA
went {rec}." rendered "Alabama's rival USA went 13-1.", which reads as South
Alabama's record. The name-drop walk now counts such an alias as a reference
to its own team, so the figure keeps its name. Nothing about acceptance moves.

#319: a placeholder whose rendered text starts lowercase and sits at a
sentence start prints capitalized. Served live: "...all of it legit. three
quality wins, ..." (a count rendered AP style). Mid-sentence placeholders keep
their case, and the prose the narrator typed is never touched.

All on the committed CFB fixture's 2017 Alabama team case.
"""

from __future__ import annotations

import pytest
from fixtures.claim_blocks import cfb_catalog, cfb_team_case_block, rendered, submit

from api.persona.claims import GROUNDING_VERSION
from api.repositories.teams import TeamRecord


@pytest.fixture(scope="module")
def catalog() -> tuple[TeamRecord, ...]:
    return cfb_catalog()


@pytest.fixture(scope="module")
def alabama_2017() -> str:
    return cfb_team_case_block(2017, "Alabama")


_REC: dict[str, object] = {"id": "rec", "kind": "record", "team": "Alabama"}
_QUALITY: dict[str, object] = {"id": "q", "kind": "count", "of": "quality_wins", "team": "Alabama"}


def _game(claim_id: str, kind: str, opponent: str, result: str) -> dict[str, object]:
    return {"id": claim_id, "kind": kind, "team": "Alabama", "opponent": opponent, "result": result}


# ---------------------------------------------------------------------------
# #318: an out-of-block alias is another team in the name-drop walk
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # South Alabama's alias: the figure must not read as South Alabama's.
        ("Alabama's rival USA went {rec}.", "Alabama's rival USA went Alabama 13-1."),
        # UAB's alias contains the block name "Alabama"; the alias, the longer
        # reference, is the one that sits nearest the figure.
        (
            "Alabama's rival Alabama-Birmingham went {rec}.",
            "Alabama's rival Alabama-Birmingham went Alabama 13-1.",
        ),
        # A block team between the name and its figure: unchanged.
        ("Alabama's rival Auburn went {rec}.", "Alabama's rival Auburn went Alabama 13-1."),
        # Nothing between them: the name is still dropped.
        ("Alabama went {rec}.", "Alabama went 13-1."),
        # The alias before the team's own mention doesn't stop the drop.
        ("Unlike USA, Alabama went {rec}.", "Unlike USA, Alabama went 13-1."),
    ],
)
def test_an_out_of_block_alias_keeps_the_figures_name(
    text: str, expected: str, catalog: tuple[TeamRecord, ...], alabama_2017: str
) -> None:
    assert rendered(text, [_REC], alabama_2017, catalog) == expected


@pytest.mark.parametrize("alias", ["USA", "Alabama-Birmingham"])
def test_an_out_of_block_alias_still_raises_no_error(
    alias: str, catalog: tuple[TeamRecord, ...], alabama_2017: str
) -> None:
    """Coordinator decision 4 on #290 stands: the alias is accepted prose."""
    outcome = submit(f"Even {alias} would take {{rec}}.", [_REC], alabama_2017, catalog)
    assert outcome.errors == ()
    assert outcome.text == f"Even {alias} would take Alabama 13-1."


def test_a_lowercase_out_of_block_alias_is_not_a_reference(
    catalog: tuple[TeamRecord, ...], alabama_2017: str
) -> None:
    """An alias counts only exactly as the catalog spells it, so "usa" is a word."""
    assert rendered("Alabama, usa went {rec}.", [_REC], alabama_2017, catalog) == (
        "Alabama, usa went 13-1."
    )


# ---------------------------------------------------------------------------
# #319: a placeholder at a sentence start prints capitalized
# ---------------------------------------------------------------------------


def test_a_count_after_a_sentence_break_is_capitalized(
    catalog: tuple[TeamRecord, ...], alabama_2017: str
) -> None:
    text = "Alabama went {rec}, all of it legit. {q} quality wins, no excuses."
    assert rendered(text, [_REC, _QUALITY], alabama_2017, catalog) == (
        "Alabama went 13-1, all of it legit. Two quality wins, no excuses."
    )


def test_a_count_at_the_start_of_the_text_is_capitalized(
    catalog: tuple[TeamRecord, ...], alabama_2017: str
) -> None:
    assert rendered("  {q} quality wins for Alabama.", [_QUALITY], alabama_2017, catalog) == (
        "  Two quality wins for Alabama."
    )


def test_a_count_mid_sentence_stays_lowercase(
    catalog: tuple[TeamRecord, ...], alabama_2017: str
) -> None:
    assert rendered("Alabama has {q} quality wins.", [_QUALITY], alabama_2017, catalog) == (
        "Alabama has two quality wins."
    )


def test_a_when_after_a_sentence_break_is_capitalized(
    catalog: tuple[TeamRecord, ...], alabama_2017: str
) -> None:
    claims = [_REC, _game("w", "when", "Georgia", "W")]
    text = "Alabama went {rec}. {w} they beat Georgia, too!"
    assert rendered(text, claims, alabama_2017, catalog) == (
        "Alabama went 13-1. In the postseason they beat Georgia, too!"
    )


def test_a_when_mid_sentence_stays_lowercase(
    catalog: tuple[TeamRecord, ...], alabama_2017: str
) -> None:
    claims = [_game("w", "when", "Georgia", "W")]
    assert rendered("Alabama beat Georgia {w}.", claims, alabama_2017, catalog) == (
        "Alabama beat Georgia in the postseason."
    )


def test_a_where_at_a_sentence_start_is_capitalized(
    catalog: tuple[TeamRecord, ...], alabama_2017: str
) -> None:
    claims = [_game("where", "where", "Auburn", "L")]
    text = "Auburn hurt. {where}? Alabama lost to Auburn {where}."
    assert rendered(text, claims, alabama_2017, catalog) == (
        "Auburn hurt. On the road? Alabama lost to Auburn on the road."
    )


def test_a_figure_at_a_sentence_start_is_unchanged(
    catalog: tuple[TeamRecord, ...], alabama_2017: str
) -> None:
    """A figure that starts with a capital or a digit prints as it did."""
    assert rendered("Look. {rec}, that's Alabama.", [_REC], alabama_2017, catalog) == (
        "Look. Alabama 13-1, that's Alabama."
    )


def test_the_typed_prose_is_never_capitalized(
    catalog: tuple[TeamRecord, ...], alabama_2017: str
) -> None:
    assert rendered(
        "Alabama won. and {q} of those were quality.", [_QUALITY], alabama_2017, catalog
    ) == ("Alabama won. and two of those were quality.")


# ---------------------------------------------------------------------------
# the cache key's grounding version
# ---------------------------------------------------------------------------


def test_the_grounding_version_moved_for_both_fixes() -> None:
    """Both fixes change the rendered text of an accepted submission, so
    narrations rendered under claims-v2 must miss the cache."""
    assert GROUNDING_VERSION == "claims-v4"
