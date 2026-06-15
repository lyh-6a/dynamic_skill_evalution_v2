"""LLMSkillExtractor — extract a SkillExtraction from a SKILL.md file.

Single responsibility: ``SKILL.md`` (path or text) → ``SkillExtraction``.

The extractor does no caching, no parallelism, no retry, no local fallback.
It relies on ``ChatClient`` for the model call and on the typed
``SkillExtraction.from_dict`` constructors for parsing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dynamic_skill_eval_v2.llm_client import ChatClient
from dynamic_skill_eval_v2.skill_extractor.prompt_loader import load_prompt
from dynamic_skill_eval_v2.skill_extractor.schema import (
    SCHEMA_VERSION,
    SkillExtraction,
)
from dynamic_skill_eval_v2.skill_extractor.source_scanner import (
    SourceDocument,
    find_reference_skills,
    head_text,
    load_source,
    number_lines,
    parse_frontmatter,
)

DEFAULT_MAX_TOKENS = 8000

# When the main SKILL.md is at least this long AND a references/ directory of
# sub-skill .md files exists alongside it, the extractor switches to "hub
# mode": one extraction per sub-skill .md plus one against the head of the
# main file for scheduling. Below this threshold the main file is extracted
# whole, even if a references/ directory is present.
HUB_MODE_MIN_CHARS = 12000

# How many leading characters of the main hub SKILL.md to send when we only
# need scheduling-level information. The frontmatter is always preserved.
HUB_MAIN_HEAD_CHARS = 4000


class LLMSkillExtractor:
    """Extract a structured capability map from a SKILL.md file.

    Parameters
    ----------
    client:
        A configured ``ChatClient``. Required.
    max_tokens:
        Cap for the model's response length. The prompt is asked for a
        compact JSON object, but capability-dense skills can produce many
        candidates; default of 4000 is comfortable.
    temperature:
        Sampling temperature. Defaults to 0.0 for reproducible structure
        extraction.
    system_prompt / user_prompt_template:
        Override the bundled prompts if you want to A/B a variation without
        editing the package files.
    """

    def __init__(
        self,
        client: ChatClient,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = 0.0,
        system_prompt: str | None = None,
        user_prompt_template: str | None = None,
    ) -> None:
        if client is None:
            raise ValueError("LLMSkillExtractor requires a ChatClient")
        self.client = client
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._system_prompt = system_prompt if system_prompt is not None else load_prompt("extractor_system.txt")
        self._user_prompt_template = (
            user_prompt_template if user_prompt_template is not None else load_prompt("extractor_user.txt")
        )

    # --------------------------------------------------------------- public

    def extract_path(self, path: str | Path) -> SkillExtraction:
        """Locate SKILL.md under ``path`` and extract it.

        If the main SKILL.md is long (``HUB_MODE_MIN_CHARS`` chars or more)
        AND has a sibling ``references/`` directory of sub-skill .md files,
        switches to *hub mode*: extracts scheduling from the truncated head of
        the main file, then extracts capabilities one-by-one from each
        reference .md, and merges the results. This avoids feeding a 20KB hub
        SKILL.md through the model in a single call (which would either
        truncate, OOM the response budget, or get torn down by the gateway).
        """

        source = load_source(path)
        references = find_reference_skills(source.source_path)
        if references and len(source.raw_text) >= HUB_MODE_MIN_CHARS:
            return self._extract_hub(source, references)
        return self.extract_source(source)

    def extract_text(
        self,
        text: str,
        source_path: str | Path,
        skill_id: str | None = None,
    ) -> SkillExtraction:
        """Extract from raw SKILL.md text (e.g. for tests / in-memory pipelines)."""

        frontmatter, body = parse_frontmatter(text)
        path = Path(source_path)
        source = SourceDocument(
            skill_id=skill_id or path.parent.name or path.stem,
            source_path=path,
            raw_text=text,
            frontmatter=frontmatter,
            body=body,
        )
        return self.extract_source(source)

    def extract_source(self, source: SourceDocument) -> SkillExtraction:
        """Run extraction against a pre-loaded ``SourceDocument``."""

        user_prompt = self._render_user_prompt(source)
        data = self.client.chat_json(
            system=self._system_prompt,
            user=user_prompt,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )

        # The LLM might omit or rename ``skill_id`` / ``source_path``;
        # canonicalize before we hand the payload to the dataclass.
        data["skill_id"] = source.skill_id
        data["source_path"] = str(source.source_path)
        data["raw_text"] = source.raw_text
        data["extractor_meta"] = self._build_meta(data.get("extractor_meta"))

        return SkillExtraction.from_dict(data)

    # ----------------------------------------------------------- hub mode

    def _extract_hub(
        self,
        main_source: SourceDocument,
        references: list[Path],
    ) -> SkillExtraction:
        """Hub-mode extraction: scheduling from main, capabilities from refs.

        The main SKILL.md's head is used to fill ``scheduling`` (it's where
        skill_name, overview, dependencies live). Each reference .md is then
        extracted independently as if it were its own SKILL.md, and only the
        capability_candidates are kept. The ``evidence`` pointers from the
        reference extractions stay as ``SKILL.md:<line>`` (the line numbers
        refer to the originating reference file — preserved via the
        per-capability ``source_file`` field in extractor_meta so downstream
        consumers can resolve them).
        """

        head = head_text(main_source.raw_text, max_chars=HUB_MAIN_HEAD_CHARS)
        head_source = SourceDocument(
            skill_id=main_source.skill_id,
            source_path=main_source.source_path,
            raw_text=head,
            frontmatter=main_source.frontmatter,
            body=main_source.body[: max(0, HUB_MAIN_HEAD_CHARS - len(main_source.raw_text) + len(main_source.body))],
        )
        head_extraction = self.extract_source(head_source)

        # Per-reference extraction. Failures on individual refs are surfaced
        # in extractor_meta rather than aborting the whole hub — a single bad
        # sub-skill should not lose the others.
        all_capabilities = list(head_extraction.capability_candidates)
        ref_errors: list[dict[str, str]] = []
        ref_usage_total = 0
        for ref_path in references:
            try:
                ref_source = load_source(ref_path)
                # Keep skill_id stable across the hub: every capability still
                # belongs to the same logical skill, regardless of which file
                # the LLM saw.
                ref_source = SourceDocument(
                    skill_id=main_source.skill_id,
                    source_path=ref_source.source_path,
                    raw_text=ref_source.raw_text,
                    frontmatter=ref_source.frontmatter,
                    body=ref_source.body,
                )
                ref_extraction = self.extract_source(ref_source)
                ref_usage_total += int(
                    (ref_extraction.extractor_meta or {}).get("usage_tokens", 0) or 0
                )
                for cap in ref_extraction.capability_candidates:
                    all_capabilities.append(cap)
            except Exception as exc:  # noqa: BLE001 — best-effort per ref
                ref_errors.append({"reference": str(ref_path), "error": repr(exc)})

        # Build a hub-mode SkillExtraction off the head extraction.
        head_extraction.capability_candidates = all_capabilities
        meta = dict(head_extraction.extractor_meta or {})
        meta["hub_mode"] = True
        meta["hub_main_head_chars"] = len(head)
        meta["hub_reference_files"] = [str(p) for p in references]
        meta["hub_reference_usage_tokens"] = ref_usage_total
        if ref_errors:
            meta["hub_reference_errors"] = ref_errors
        # Make usage_tokens reflect the whole hub run (head + every ref).
        meta["usage_tokens"] = int(meta.get("usage_tokens", 0) or 0) + ref_usage_total
        head_extraction.extractor_meta = meta
        head_extraction.raw_text = main_source.raw_text
        return head_extraction

    # --------------------------------------------------------------- helpers

    def _render_user_prompt(self, source: SourceDocument) -> str:
        from string import Template

        return Template(self._user_prompt_template).safe_substitute(
            {
                "source_path": str(source.source_path),
                "skill_id": source.skill_id,
                "skill_text_numbered": number_lines(source.raw_text),
            }
        )

    def _build_meta(self, llm_meta: Any) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "backend": self.client.api_type,
            "model": self.client.model,
            "usage_tokens": int(getattr(self.client, "last_usage_tokens", 0) or 0),
        }
        # If the LLM volunteered its own meta block, preserve it under a
        # nested key — useful for debugging but never load-bearing.
        if isinstance(llm_meta, dict) and llm_meta:
            meta["llm_returned"] = llm_meta
        return meta


def load_extraction(path: str | Path) -> SkillExtraction:
    """Read one ``skill_extractor`` JSON file from disk."""

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return SkillExtraction.from_dict(data)
