"""A shared helper for the narrator test doubles (issue #291).

Since #291 a `Narrator` is handed Messages API `MessageParam`s, whose
`content` is either a string or a list of content blocks. The FACT BLOCK user
turn `api.persona.narrate` sends first is always a string; doubles that read
it back use `user_text`, so a change to that turn's shape fails loudly
instead of type-erasing. Not part of the pytest suite itself (doesn't match
`test_*.py`).
"""

from __future__ import annotations

from anthropic.types import MessageParam


def user_text(message: MessageParam) -> str:
    """The text of a plain-text turn, such as the FACT BLOCK user turn."""
    content = message["content"]
    assert isinstance(content, str), content
    return content
