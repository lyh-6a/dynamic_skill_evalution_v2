"""CLI for the skill_extractor.

Usage:
    python -m dynamic_skill_eval_v2.skill_extractor.cli \
        --skill /path/to/skill-dir \
        --out   /tmp/extraction.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dynamic_skill_eval_v2.llm_client import ChatClient
from dynamic_skill_eval_v2.skill_extractor.extractor import LLMSkillExtractor


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="skill_extractor",
        description="Extract a SkillExtraction from a SKILL.md file using an LLM.",
    )
    parser.add_argument(
        "--skill",
        required=True,
        type=Path,
        help="Path to a SKILL.md file or a directory containing one.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Where to write the extraction JSON. Defaults to stdout.",
    )
    parser.add_argument(
        "--include-raw-text",
        action="store_true",
        help="Include the full SKILL.md text in the output (off by default).",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=4000,
        help="Cap for the model's response length.",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.0,
        help="Sampling temperature.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Override the model id (otherwise read from OPENAI_MODEL / ANTHROPIC_MODEL).",
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default=None,
        help="Override the API base URL.",
    )
    parser.add_argument(
        "--api-type",
        choices=["openai", "anthropic"],
        default=None,
        help="Force a specific API style (otherwise auto-detected).",
    )
    args = parser.parse_args(argv)

    client = ChatClient(
        model=args.model,
        base_url=args.base_url,
        api_type=args.api_type,
    )
    if not client.available:
        print(
            "ChatClient is not configured. Set OPENAI_API_KEY, OPENAI_BASE_URL, "
            "and OPENAI_MODEL (or the Anthropic equivalents).",
            file=sys.stderr,
        )
        return 2

    extractor = LLMSkillExtractor(
        client=client,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
    )
    extraction = extractor.extract_path(args.skill)
    payload = extraction.to_dict(include_raw_text=args.include_raw_text)
    text = json.dumps(payload, ensure_ascii=False, indent=2)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
        print(f"Wrote {args.out}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
