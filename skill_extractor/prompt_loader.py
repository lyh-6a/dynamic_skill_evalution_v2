"""Load prompt templates bundled with the skill_extractor package."""

from __future__ import annotations

from pathlib import Path
from string import Template
from typing import Any

_PROMPT_DIR = Path(__file__).parent / "prompts"


def load_prompt(name: str) -> str:
    """Read a prompt template by file name (e.g. ``extractor_system.txt``)."""

    path = _PROMPT_DIR / name
    if not path.is_file():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    return path.read_text(encoding="utf-8")


def render_prompt(name: str, **variables: Any) -> str:
    """Load a prompt template and substitute ``$variable`` placeholders.

    Uses ``string.Template`` (safe_substitute), so unknown ``$var`` tokens are
    left in place rather than raising — useful for templates with literal
    dollar signs.
    """

    template = Template(load_prompt(name))
    return template.safe_substitute({k: str(v) for k, v in variables.items()})
