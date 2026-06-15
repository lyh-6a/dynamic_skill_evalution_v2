"""CLI for matrix-mode task generation.

Builds a ``batch_<id>/`` directory:

    batch_dir/
      capabilities.json
      skill_capability_map.json
      tasks/<capability_id>/...      (SkillsBench task bundles)
      build_report.json

Usage:
    python -m dynamic_skill_eval_v2.task_generation.matrix_cli \\
        --query "compare doc-skill capabilities" \\
        --input /tmp/extraction_*.json \\
        --out-dir /tmp/matrix_batch_demo

Pass ``--no-validate`` to skip the host-side renderer/solution/pytest
self-validation. Validation is on by default — without it the produced
tasks may not actually run.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

from dynamic_skill_eval_v2.llm_client import ChatClient
from dynamic_skill_eval_v2.skill_extractor.extractor import load_extraction
from dynamic_skill_eval_v2.task_generation.bundle_writer import TaskBundleWriter
from dynamic_skill_eval_v2.task_generation.generator import TaskGenerator
from dynamic_skill_eval_v2.task_generation.matrix_batch_builder import MatrixBatchBuilder
from dynamic_skill_eval_v2.task_generation.validator import TaskValidator


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="task_generation.matrix_cli",
        description="Build a capability × skill matrix-mode task batch.",
    )
    parser.add_argument("--query", required=True, type=str)
    parser.add_argument("--input", nargs="*", type=Path, default=[])
    parser.add_argument("--input-glob", type=str, default=None)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--no-validate", action="store_true")
    parser.add_argument("--validator-timeout", type=float, default=60.0)
    parser.add_argument("--no-pip-install", action="store_true")
    parser.add_argument("--repair-attempts", type=int, default=1)
    parser.add_argument("--model", type=str, default=None)
    parser.add_argument("--base-url", type=str, default=None)
    parser.add_argument("--api-type", choices=["openai", "anthropic"], default=None)
    parser.add_argument("--max-tokens", type=int, default=16000)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument(
        "--llm-timeout-sec",
        type=int,
        default=600,
        help="HTTP timeout for the LLM client (seconds). Stage-1 atom "
             "decomposition can take 2-3 min on a large skill set.",
    )
    parser.add_argument(
        "--single-stage",
        action="store_true",
        help="Use legacy single-call clustering (analyze_capabilities_single_stage). "
             "Default is two-stage: decompose_atoms + mechanical merge.",
    )
    parser.add_argument(
        "--no-normalize",
        action="store_true",
        help="Skip stage-3 LLM normalization of merged capabilities.",
    )
    parser.add_argument(
        "--min-skills-per-column",
        type=int,
        default=1,
        help="Only generate tasks for capability columns with >= N skills "
             "claiming them. Default 1 (all columns). Pass 2 to generate "
             "only for multi-skill (column-comparable) capabilities. The "
             "full unfiltered analysis is preserved at capabilities_full.json.",
    )
    args = parser.parse_args(argv)

    paths: list[Path] = list(args.input)
    if args.input_glob:
        paths.extend(Path(p) for p in glob.glob(args.input_glob))
    if not paths:
        print("error: provide --input or --input-glob", file=sys.stderr)
        return 2

    extractions = [load_extraction(p) for p in paths]

    client = ChatClient(
        model=args.model, base_url=args.base_url, api_type=args.api_type,
        timeout_sec=args.llm_timeout_sec,
    )
    if not client.available:
        print("ChatClient is not configured.", file=sys.stderr)
        return 2

    generator = TaskGenerator(
        client=client, max_tokens=args.max_tokens, temperature=args.temperature
    )
    validator = None
    if not args.no_validate:
        validator = TaskValidator(
            timeout_sec=args.validator_timeout,
            pip_install=not args.no_pip_install,
        )
    builder = MatrixBatchBuilder(
        generator=generator,
        validator=validator,
        bundle_writer=TaskBundleWriter(),
        repair_attempts=args.repair_attempts,
    )

    print(
        f"Building matrix batch from {len(extractions)} skill(s) into {args.out_dir} ...",
        file=sys.stderr,
    )
    analysis = None
    if args.single_stage:
        print("[clustering] single-stage (legacy) ...", file=sys.stderr)
        analysis = generator.analyze_capabilities_single_stage(
            query=args.query, extractions=extractions
        )
    else:
        print("[clustering] two-stage: decompose_atoms + mechanical merge ...", file=sys.stderr)
        analysis = generator.analyze_capabilities(
            query=args.query, extractions=extractions, normalize=not args.no_normalize
        )
    print(
        f"[clustering] -> {len(analysis.capabilities)} capabilities, "
        f"map covers {len(analysis.skill_capability_map)} skills",
        file=sys.stderr,
    )

    # Always preserve the full clustering output (including single-skill
    # columns) at capabilities_full.json for the archive — useful even when
    # we only generate tasks for the multi-skill subset below.
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "capabilities_full.json").write_text(
        json.dumps(analysis.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"[archive] wrote {args.out_dir / 'capabilities_full.json'}",
        file=sys.stderr,
    )

    if args.min_skills_per_column > 1:
        from dynamic_skill_eval_v2.task_generation.schema import CapabilityAnalysis
        kept = [
            c for c in analysis.capabilities
            if len(c.skill_ids) >= args.min_skills_per_column
        ]
        if not kept:
            print(
                f"error: no capabilities have >= {args.min_skills_per_column} "
                f"skills; nothing to generate.",
                file=sys.stderr,
            )
            return 2
        kept_ids = {c.id for c in kept}
        kept_map = {
            sid: [cid for cid in caps if cid in kept_ids]
            for sid, caps in analysis.skill_capability_map.items()
        }
        kept_map = {sid: caps for sid, caps in kept_map.items() if caps}
        analysis = CapabilityAnalysis(capabilities=kept, skill_capability_map=kept_map)
        print(
            f"[filter] --min-skills-per-column={args.min_skills_per_column} "
            f"-> {len(kept)} columns retained for task generation",
            file=sys.stderr,
        )

    report = builder.build(
        query=args.query,
        extractions=extractions,
        out_dir=args.out_dir,
        analysis=analysis,
    )

    ok_count = sum(1 for o in report.outcomes if o.ok)
    print(
        f"Capabilities: {len(report.capability_ids)} ; bundles built: {ok_count}/{len(report.outcomes)} ; "
        f"tokens: {report.tokens_used} ; elapsed: {report.elapsed_sec:.1f}s",
        file=sys.stderr,
    )
    for o in report.outcomes:
        status = "OK" if o.ok else f"FAIL[{o.failed_stage}]"
        print(f"  - {o.capability_id}: {status} {o.failure}", file=sys.stderr)
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 0 if ok_count == len(report.outcomes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
