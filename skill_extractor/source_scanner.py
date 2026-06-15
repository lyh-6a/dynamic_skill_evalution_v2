"""Locate a SKILL.md file under a path and split its frontmatter from body.

Kept intentionally small: file location + frontmatter parsing only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


SKILL_FILE_CANDIDATES: tuple[str, ...] = ("SKILL.md", "skill.md", "Skill.md")


@dataclass
class SourceDocument:
    """The result of locating and reading a SKILL.md file."""

    skill_id: str               # directory name (or stem if pointed at a file)
    source_path: Path           # absolute path to the resolved .md file
    raw_text: str               # full file contents
    frontmatter: dict[str, str] # parsed YAML key/value pairs (string-only)
    body: str                   # everything after the frontmatter


def resolve_skill_file(path: str | Path) -> Path:
    """Return the SKILL.md file under ``path``.

    ``path`` may be a directory containing SKILL.md, or the file itself.
    Raises ``FileNotFoundError`` if no suitable file exists.
    """

    p = Path(path).expanduser().resolve()
    if p.is_file():
        return p
    if p.is_dir():
        for name in SKILL_FILE_CANDIDATES:
            candidate = p / name
            if candidate.is_file():
                return candidate
        raise FileNotFoundError(
            f"No SKILL.md (tried {', '.join(SKILL_FILE_CANDIDATES)}) under {p}"
        )
    raise FileNotFoundError(f"Path does not exist: {p}")


def load_source(path: str | Path) -> SourceDocument:
    """Locate, read, and split a SKILL.md file."""

    skill_file = resolve_skill_file(path)
    raw_text = skill_file.read_text(encoding="utf-8", errors="replace")
    frontmatter, body = parse_frontmatter(raw_text)
    # Use the containing directory name as the skill_id; that matches the
    # convention used elsewhere in the project (one skill = one directory).
    skill_id = skill_file.parent.name if skill_file.parent != skill_file else skill_file.stem
    return SourceDocument(
        skill_id=skill_id,
        source_path=skill_file,
        raw_text=raw_text,
        frontmatter=frontmatter,
        body=body,
    )


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Split YAML-style frontmatter off the front of ``text``.

    Only supports the common ``key: value`` flat form. Multi-line / nested
    YAML structures are returned as raw strings and left for the LLM to
    interpret. Returns ``({}, text)`` when no frontmatter is present.
    """

    if not text.startswith("---"):
        return {}, text
    # Find the closing '---' on its own line, anywhere after the first one.
    closing = re.search(r"\n---\s*(\n|$)", text[3:])
    if not closing:
        return {}, text
    fm_block = text[3 : closing.start() + 3]
    body = text[closing.end() + 3 :]
    fm: dict[str, str] = {}
    for line in fm_block.splitlines():
        if ":" not in line or line.lstrip().startswith("#"):
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        if key:
            fm[key] = value
    return fm, body


def number_lines(text: str) -> str:
    """Return ``text`` with each line prefixed by ``"NNN: "``.

    Used to feed the source into the LLM with stable line numbers so it can
    cite ``SKILL.md:<line>`` evidence pointers.
    """

    lines = text.splitlines()
    width = max(3, len(str(len(lines))))
    return "\n".join(f"{str(i + 1).rjust(width)}: {line}" for i, line in enumerate(lines))


# ----------------------------------------------------- multi-file hub support

REFERENCES_DIR_CANDIDATES: tuple[str, ...] = ("references", "subskills", "modes")


def find_reference_skills(main_skill_path: str | Path) -> list[Path]:
    """Find sibling sub-skill markdown files for a hub-style SKILL.md.

    A "hub" skill stores its main SKILL.md plus a sibling ``references/`` (or
    ``subskills`` / ``modes``) directory containing one ``.md`` per sub-skill.
    Returns the list of those .md files (sorted), or an empty list if none.
    """

    main = Path(main_skill_path).expanduser().resolve()
    parent = main.parent if main.is_file() else main
    out: list[Path] = []
    for name in REFERENCES_DIR_CANDIDATES:
        ref_dir = parent / name
        if ref_dir.is_dir():
            out.extend(sorted(p for p in ref_dir.glob("*.md") if p.is_file()))
    return out


def head_text(text: str, max_chars: int = 4000) -> str:
    """Return the leading slice of ``text`` truncated to whole lines.

    Used to keep a long main SKILL.md within a single LLM call when we only
    need its scheduling block (frontmatter + overview). Frontmatter is always
    kept in full even if it exceeds ``max_chars``.
    """

    if len(text) <= max_chars:
        return text
    # Always keep the full YAML frontmatter if present.
    keep_until = 0
    if text.startswith("---"):
        m = re.search(r"\n---\s*(\n|$)", text[3:])
        if m:
            keep_until = m.end() + 3
    budget = max(max_chars, keep_until)
    if len(text) <= budget:
        return text
    # Truncate at the last newline before the budget so we don't cut a line.
    cut = text.rfind("\n", keep_until, budget)
    if cut < 0:
        cut = budget
    return text[:cut]
