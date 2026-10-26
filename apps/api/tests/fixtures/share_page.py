"""Parse and check a share page from `api.share` (issue #185).

Not a test module. `tests/test_share_route.py`, `test_share_player_compare.py`
and `test_share_injection.py` read every page through `parse_share_page`,
which uses the standard library's `html.parser`, the same tokenizer rules a
link-preview scraper applies, so a value that breaks out of its attribute or
its `<script>` shows up here as an extra element or a wrong meta content.

`assert_share_page` is the whole contract of one page: the exact element
sequence (nothing added, nothing missing), every meta tag's content, the
`<title>`, the three redirect forms all pointing at the same target, and a
script that is one `location.replace(<JSON string>);` call with no `</` or
`<!--` in it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from html.parser import HTMLParser

GENERIC_TITLE = "My Team Is Better"
GENERIC_DESCRIPTION = (
    "Ask whose team is better and the guy at the end of the bar settles it, "
    "with the math to back him up."
)
OG_IMAGE = "https://my-team-is-better-web.onrender.com/og-image.png"
OG_IMAGE_ALT = (
    "The words My Team Is Better beside a football on a leather band, "
    "for college football and the NFL."
)
WEB = "https://my-team-is-better-web.onrender.com"

# Every element the page has, in document order. Anything a hostile value
# smuggles in (an <img>, a second <script>) makes the real sequence differ.
EXPECTED_TAGS = [
    "html",
    "head",
    "meta",  # charset
    "title",
    *["meta"] * 18,
    "script",
    "body",
    "p",
    "a",
]

SCRIPT_PREFIX = "location.replace("
SCRIPT_SUFFIX = ");"


@dataclass
class SharePage:
    doctype: str | None = None
    tags: list[str] = field(default_factory=list)
    charset: str | None = None
    metas: dict[str, str] = field(default_factory=dict)
    title: str = ""
    script: str = ""
    link_href: str | None = None
    link_text: str = ""


class _Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.page = SharePage()
        self._open: list[str] = []

    def handle_decl(self, decl: str) -> None:
        self.page.doctype = decl

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.page.tags.append(tag)
        values = dict(attrs)
        if tag == "meta":
            if "charset" in values:
                self.page.charset = values["charset"]
            else:
                key = values.get("property") or values.get("name") or values.get("http-equiv")
                assert key is not None, f"meta with no key: {attrs}"
                assert key not in self.page.metas, f"duplicate meta {key}"
                content = values.get("content")
                assert content is not None, f"meta {key} has no content"
                self.page.metas[key] = content
            return
        if tag == "a":
            self.page.link_href = values.get("href")
        self._open.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if self._open and self._open[-1] == tag:
            self._open.pop()

    def handle_data(self, data: str) -> None:
        current = self._open[-1] if self._open else None
        if current == "title":
            self.page.title += data
        elif current == "script":
            self.page.script += data
        elif current == "a":
            self.page.link_text += data


def parse_share_page(html: str) -> SharePage:
    parser = _Parser()
    parser.feed(html)
    parser.close()
    return parser.page


def script_target(script: str) -> str:
    """The URL `location.replace` is called with, decoded as JSON."""
    assert script.startswith(SCRIPT_PREFIX) and script.endswith(SCRIPT_SUFFIX), script
    literal = script[len(SCRIPT_PREFIX) : -len(SCRIPT_SUFFIX)]
    value = json.loads(literal)
    assert isinstance(value, str)
    return value


def expected_metas(title: str, description: str, target: str) -> dict[str, str]:
    return {
        "og:type": "website",
        "og:site_name": "My Team Is Better",
        "og:title": title,
        "og:description": description,
        "og:url": target,
        "og:image": OG_IMAGE,
        "og:image:type": "image/png",
        "og:image:width": "1200",
        "og:image:height": "630",
        "og:image:alt": OG_IMAGE_ALT,
        "twitter:card": "summary_large_image",
        "twitter:title": title,
        "twitter:description": description,
        "twitter:image": OG_IMAGE,
        "twitter:image:alt": OG_IMAGE_ALT,
        "description": description,
        "robots": "noindex",
        "refresh": f"0; url={target}",
    }


def assert_share_page(html: str, *, title: str, description: str, target: str) -> SharePage:
    """`html` is exactly the share page for `title`, `description` and
    redirect `target`, and nothing else."""
    page = parse_share_page(html)
    assert page.doctype is not None and page.doctype.lower() == "doctype html"
    assert page.tags == EXPECTED_TAGS
    assert page.charset == "utf-8"
    assert page.title == title
    assert page.metas == expected_metas(title, description, target)
    assert "</" not in page.script and "<!--" not in page.script
    assert script_target(page.script) == target
    assert page.link_href == target
    assert page.link_text == title
    return page
