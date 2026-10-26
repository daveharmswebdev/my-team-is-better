"""`api.share`'s team-value rule mirrors the web's `isPlainTeamName`
(`apps/web/src/pages/HomePage/shareLink.ts`, issue #185).

The web checks `/^[\\p{L}\\p{N} &'.()-]+$/u` and `value.length <= 64`.
Python's `re` has no `\\p{L}`, so `api.share` checks each character with
`str.isalnum()` (Unicode letters `L*` and numbers `N*`) or the six
punctuation characters. JS `.length` counts UTF-16 code units, so an astral
letter counts twice. And the web trims with `String.prototype.trim`, whose
whitespace set is not Python's `str.strip()`'s. Each case below states what
the web answers for it.
"""

from __future__ import annotations

import pytest

from api.share import is_plain_team_name, js_trim

# Values the web's PLAIN_TEAM_NAME accepts.
ACCEPTED = [
    "Texas A&M",
    "San José State",  # precomposed é (Ll)
    "Miami (FL)",
    "St. John's",
    "Bethune-Cookman",
    "Zürich Lions",
    "東京大学",  # Lo
    "Москва",  # Cyrillic
    "Ελλάδα",
    "عربي",
    "١٢٣",  # Arabic-Indic digits (Nd)
    "Ⅻ Legion",  # Roman numeral (Nl)
    "½ Back",  # vulgar fraction (No)
    "ǅ",  # titlecase letter (Lt)
    "ʰ",  # modifier letter (Lm)
    "\U0001d400",  # mathematical bold A: astral, Lu
    "A" * 64,
    "\U0001d400" * 32,  # 64 UTF-16 code units
]

# Values it rejects.
REJECTED = [
    "",
    "Tex<as",
    'Tex"as',
    "Texas_A",
    "Texas/A",
    "Texas:A",
    "Texas\tA",
    "José",  # combining acute (Mn): neither \p{L} nor \p{N}
    "\U0001f600",  # emoji (So)
    "A" * 65,
    "\U0001d400" * 33,  # 33 code points but 66 UTF-16 code units
    " ",  # NBSP is Zs, not a plain space
]


@pytest.mark.parametrize("value", ACCEPTED)
def test_accepts_what_the_web_accepts(value: str) -> None:
    assert is_plain_team_name(value)


@pytest.mark.parametrize("value", REJECTED)
def test_rejects_what_the_web_rejects(value: str) -> None:
    assert not is_plain_team_name(value)


@pytest.mark.parametrize(
    ("raw", "trimmed"),
    [
        ("  Texas  ", "Texas"),
        ("\t\n\r\v\fTexas ", "Texas"),
        ("﻿Texas  　", "Texas"),  # BOM, line/para seps, ideographic space
        ("\x1cTexas\x1f", "\x1cTexas\x1f"),  # Python strips these, JS does not
        ("\x85Texas", "\x85Texas"),  # NEL: Python whitespace, not JS
    ],
)
def test_js_trim_matches_string_prototype_trim(raw: str, trimmed: str) -> None:
    assert js_trim(raw) == trimmed
