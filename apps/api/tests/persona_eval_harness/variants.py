"""Prompt variants, and the narrator wrapper that applies one.

A variant is a system prompt and nothing else (the package docstring's known
limit): `baseline` is production's `build_system_prompt`, `degraded` is
`degraded_variant.py`, and `name=path` loads any file exposing
`build_system_prompt(user_team: str | None) -> str`.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from anthropic.types import MessageParam

from api.persona.claude_client import Narrator, NarratorReply
from api.persona.prompt import build_system_prompt as build_production_prompt

BASELINE_VARIANT_NAME = "baseline"
DEGRADED_VARIANT_NAME = "degraded"
DEGRADED_VARIANT_PATH = Path(__file__).resolve().parent / "degraded_variant.py"

PromptBuilder = Callable[[str | None], str]


@dataclass(frozen=True)
class Variant:
    name: str
    source: str
    build_system_prompt: PromptBuilder


def baseline_variant() -> Variant:
    return Variant(
        name=BASELINE_VARIANT_NAME,
        source="api.persona.prompt.build_system_prompt",
        build_system_prompt=build_production_prompt,
    )


def load_variant_file(name: str, path: Path) -> Variant:
    """The variant in `path`, which must define a callable
    `build_system_prompt`."""
    if not path.is_file():
        raise ValueError(f"variant {name!r}: no such file {path}")
    spec = importlib.util.spec_from_file_location(f"persona_eval_variant_{name}", path)
    if spec is None or spec.loader is None:
        raise ValueError(f"variant {name!r}: {path} can't be loaded as a Python module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    builder: object = getattr(module, "build_system_prompt", None)
    if not callable(builder):
        raise ValueError(f"variant {name!r}: {path} defines no build_system_prompt(user_team)")

    def build(user_team: str | None) -> str:
        prompt = builder(user_team)
        if not isinstance(prompt, str):
            raise ValueError(f"variant {name!r}: build_system_prompt returned {type(prompt)}")
        return prompt

    return Variant(name=name, source=str(path), build_system_prompt=build)


def parse_variant(argument: str) -> Variant:
    """One `--variant` value: `baseline`, `degraded` or `name=path`."""
    if argument == BASELINE_VARIANT_NAME:
        return baseline_variant()
    if argument == DEGRADED_VARIANT_NAME:
        return load_variant_file(DEGRADED_VARIANT_NAME, DEGRADED_VARIANT_PATH)
    name, separator, path = argument.partition("=")
    name = name.strip()
    if not separator or not name or not path:
        raise ValueError(
            f"--variant {argument!r}: expected {BASELINE_VARIANT_NAME}, "
            f"{DEGRADED_VARIANT_NAME} or name=path/to/variant.py"
        )
    return load_variant_file(name, Path(path))


def parse_variants(arguments: Sequence[str]) -> tuple[Variant, ...]:
    if not arguments:
        raise ValueError("at least one --variant is required")
    variants = tuple(parse_variant(argument) for argument in arguments)
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
