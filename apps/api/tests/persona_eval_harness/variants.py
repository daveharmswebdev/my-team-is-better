"""Prompt variants, and the narrator wrapper that applies one.

A variant is a system prompt and nothing else (the package docstring's known
limit). For the team narrator, `baseline` is production's
`build_system_prompt`, `degraded` is `degraded_variant.py`, and `name=path`
loads any file exposing `build_system_prompt(user_team: str | None) -> str`.
For the QB narrator (issue #463), `baseline` is production's
`api.persona.qb_prompt.build_qb_system_prompt`, `name=path` loads a file
exposing `build_qb_system_prompt() -> str`, and there is no `degraded`
control (it cuts the team prompt); the name stays reserved. Either way a
variant is called with the case's `user_team`, which the QB builder ignores.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from anthropic.types import MessageParam

from api.persona.claude_client import Narrator, NarratorReply
from api.persona.prompt import build_system_prompt as build_production_prompt
from api.persona.qb_prompt import build_qb_system_prompt as build_production_qb_prompt

BASELINE_VARIANT_NAME = "baseline"
DEGRADED_VARIANT_NAME = "degraded"
RESERVED_VARIANT_NAMES = (BASELINE_VARIANT_NAME, DEGRADED_VARIANT_NAME)
DEGRADED_VARIANT_PATH = Path(__file__).resolve().parent / "degraded_variant.py"

PromptBuilder = Callable[[str | None], str]
NarratorKind = Literal["team", "qb"]
NARRATOR_KINDS: tuple[NarratorKind, ...] = ("team", "qb")


@dataclass(frozen=True)
class Variant:
    name: str
    source: str
    build_system_prompt: PromptBuilder


def baseline_variant(narrator: NarratorKind = "team") -> Variant:
    if narrator == "qb":
        return Variant(
            name=BASELINE_VARIANT_NAME,
            source="api.persona.qb_prompt.build_qb_system_prompt",
            build_system_prompt=lambda _user_team: build_production_qb_prompt(),
        )
    return Variant(
        name=BASELINE_VARIANT_NAME,
        source="api.persona.prompt.build_system_prompt",
        build_system_prompt=build_production_prompt,
    )


def load_variant_file(name: str, path: Path, narrator: NarratorKind = "team") -> Variant:
    """The variant in `path`, which must define a callable
    `build_system_prompt` (team) or `build_qb_system_prompt` (QB)."""
    if not path.is_file():
        raise ValueError(f"variant {name!r}: no such file {path}")
    spec = importlib.util.spec_from_file_location(f"persona_eval_variant_{name}", path)
    if spec is None or spec.loader is None:
        raise ValueError(f"variant {name!r}: {path} can't be loaded as a Python module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    attribute = "build_qb_system_prompt" if narrator == "qb" else "build_system_prompt"
    builder: object = getattr(module, attribute, None)
    if not callable(builder):
        signature = "()" if narrator == "qb" else "(user_team)"
        raise ValueError(f"variant {name!r}: {path} defines no {attribute}{signature}")

    def build(user_team: str | None) -> str:
        prompt = builder() if narrator == "qb" else builder(user_team)
        if not isinstance(prompt, str):
            raise ValueError(f"variant {name!r}: build_system_prompt returned {type(prompt)}")
        return prompt

    return Variant(name=name, source=str(path), build_system_prompt=build)


def parse_variant(argument: str, narrator: NarratorKind = "team") -> Variant:
    """One `--variant` value: `baseline`, `degraded` (team only) or
    `name=path`. The two shipped names are reserved: `baseline=x.py` or
    `degraded=x.py` would put a candidate's numbers under production's (or
    the control's) name."""
    if argument == BASELINE_VARIANT_NAME:
        return baseline_variant(narrator)
    if argument == DEGRADED_VARIANT_NAME and narrator == "qb":
        raise ValueError(
            f"--variant {DEGRADED_VARIANT_NAME} is the team prompt's anti-vacuity control; "
            "it has no QB form, so it can't run with --narrator qb"
        )
    if argument == DEGRADED_VARIANT_NAME:
        return load_variant_file(DEGRADED_VARIANT_NAME, DEGRADED_VARIANT_PATH)
    name, separator, path = argument.partition("=")
    name = name.strip()
    if not separator or not name or not path:
        raise ValueError(
            f"--variant {argument!r}: expected {BASELINE_VARIANT_NAME}, "
            f"{DEGRADED_VARIANT_NAME} or name=path/to/variant.py"
        )
    if name in RESERVED_VARIANT_NAMES:
        raise ValueError(
            f"--variant {argument!r}: {name!r} is a reserved variant name (it means the shipped "
            f"{name} prompt); give the file another name, e.g. candidate={path}"
        )
    return load_variant_file(name, Path(path), narrator)


def parse_variants(
    arguments: Sequence[str], narrator: NarratorKind = "team"
) -> tuple[Variant, ...]:
    if not arguments:
        raise ValueError("at least one --variant is required")
    variants = tuple(parse_variant(argument, narrator) for argument in arguments)
    names = [variant.name for variant in variants]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ValueError(f"variant names must be unique: {duplicates}")
    return variants


class SystemSwappingNarrator:
    """Replaces the `system` argument with the variant's prompt and passes
    everything else, and the reply, through untouched."""

    def __init__(self, inner: Narrator, *, system: str) -> None:
        self._inner = inner
        self.system = system

    def submit(self, *, system: str, messages: list[MessageParam]) -> NarratorReply:
        return self._inner.submit(system=self.system, messages=messages)
