"""CLI for task_generation.

Usage:
    # Generate tasks + self-validate (runs renderers, solution, pytest on host)
    # before materializing only the passing ones as SkillsBench task dirs.
    python -m dynamic_skill_eval_v2.task_generation.cli \
        --input-glob '/tmp/extraction_*.json' \
        --query "我想对比两个 skill 提取小票的能力" \
        --out-dir /tmp/generated_tasks

    # Skip validation (faster, no pip install, lets through broken tasks):
    python -m dynamic_skill_eval_v2.task_generation.cli ... --no-validate

    # Just emit the raw JSON batch (no on-disk bundles, no validation):
    python -m dynamic_skill_eval_v2.task_generation.cli ... --json-only --out /tmp/tasks.json
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
from dynamic_skill_eval_v2.task_generation.schema import TaskBatch
from dynamic_skill_eval_v2.task_generation.validator import TaskValidator


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="task_generation",
        description="Generate self-validating SkillsBench tasks from a query + skill_extractor JSONs.",
    )
    parser.add_argument("--query", required=True, type=str)
    parser.add_argument("--input", nargs="*", type=Path, default=[])
    parser.add_argument("--input-glob", type=str, default=None)
    parser.add_argument("--out-dir", type=Path, default=None,
                        help="Root directory to materialize SkillsBench task bundles into.")
    parser.add_argument("--out", type=Path, default=None,
                        help="Where to dump the raw TaskBatch JSON.")
    parser.add_argument("--json-only", action="store_true",
                        help="Skip writing SkillsBench bundle directories and skip validation; only emit JSON.")
    parser.add_argument("--no-validate", action="store_true",
                        help="Skip the host-side self-validation pass (runners/solution/pytest).")
    parser.add_argument("--keep-failed", action="store_true",
                        help="Materialize tasks even if validation fails (still records the report).")
    parser.add_argument("--keep-stage", action="store_true",
                        help="Keep validator stage directories on disk for inspection.")
    parser.add_argument("--no-pip-install", action="store_true",
                        help="Skip `pip install` of renderer/solution deps in the validator.")
    parser.add_argument("--validator-timeout", type=float, default=60.0)
    parser.add_argument("--repair-attempts", type=int, default=1,
                        help="If validation fails, ask the LLM to patch the task this many times "
                             "before giving up. 0 disables repair. Each attempt costs one extra LLM call.")
    parser.add_argument("--two-step", action="store_true",
                        help="Use the combined two-step generator: first analyze "
                             "discrimination axes, then produce ONE task with N "
                             "discriminator-bound test files sharing assets/solution.")
    parser.add_argument("--per-discriminator", action="store_true",
                        help="(Legacy) Two-step but one separate task per discriminator. "
                             "Implies --two-step. Produces duplicated environments; "
                             "kept for A/B comparison.")
    parser.add_argument("--model", type=str, default=None)
    parser.add_argument("--base-url", type=str, default=None)
    parser.add_argument("--api-type", choices=["openai", "anthropic"], default=None)
    parser.add_argument("--max-tokens", type=int, default=16000)
    parser.add_argument("--temperature", type=float, default=0.2)
    args = parser.parse_args(argv)

    paths: list[Path] = list(args.input)
    if args.input_glob:
        paths.extend(Path(p) for p in glob.glob(args.input_glob))
    if not paths:
        print("error: provide --input or --input-glob", file=sys.stderr)
        return 2

    extractions = [load_extraction(p) for p in paths]

    client = ChatClient(model=args.model, base_url=args.base_url, api_type=args.api_type)
    if not client.available:
        print("ChatClient is not configured.", file=sys.stderr)
        return 2

    generator = TaskGenerator(client=client, max_tokens=args.max_tokens, temperature=args.temperature)
    if args.per_discriminator:
        tasks = generator.generate_two_step(query=args.query, extractions=extractions)
        discs = generator.last_discriminators
        mode_label = "two-step (per-discriminator, legacy)"
        print(f"Discriminator analysis produced {len(discs)} axis/axes:", file=sys.stderr)
        for d in discs:
            print(f"  - [{d.id}] {d.axis}: {d.description}", file=sys.stderr)
    elif args.two_step:
        t = generator.generate_combined(query=args.query, extractions=extractions)
        tasks = [t] if t is not None else []
        discs = generator.last_discriminators
        mode_label = "two-step (combined)"
        print(f"Discriminator analysis produced {len(discs)} axis/axes:", file=sys.stderr)
        for d in discs:
            print(f"  - [{d.id}] {d.axis}: {d.description}", file=sys.stderr)
        if tasks and tasks[0].tests:
            print(
                f"Combined task has {len(tasks[0].tests)} discriminator-bound test file(s) "
                f"sharing {len(tasks[0].assets)} asset(s).",
                file=sys.stderr,
            )
    else:
        tasks = generator.generate(query=args.query, extractions=extractions)
        discs = []
        mode_label = "one-step"
    print(f"LLM produced {len(tasks)} candidate task(s).", file=sys.stderr)

    reports: list[dict] = []
    valid_tasks = tasks
    if not args.json_only and not args.no_validate:
        validator = TaskValidator(
            timeout_sec=args.validator_timeout,
            pip_install=not args.no_pip_install,
            keep_stage=args.keep_stage,
        )
        valid_tasks = []
        for t in tasks:
            try:
                rep = validator.validate(t)
            except Exception as exc:  # noqa: BLE001 — never let one bad task kill the batch
                from dynamic_skill_eval_v2.task_generation.validator import ValidationReport
                rep = ValidationReport(
                    task_id=t.task_id,
                    ok=False,
                    failed_stage="exception",
                    detail=f"{type(exc).__name__}: {exc}",
                )

            # Repair loop: ask the LLM to patch the failing task, then re-validate.
            repair_history: list[dict] = []
            attempts_left = max(0, int(args.repair_attempts))
            while not rep.ok and attempts_left > 0:
                attempts_left -= 1
                print(
                    f"      → repairing {t.task_id} (attempt {args.repair_attempts - attempts_left}, "
                    f"failed at {rep.failed_stage})",
                    file=sys.stderr,
                )
                try:
                    t = generator.repair_task(
                        t,
                        failed_stage=rep.failed_stage,
                        detail=rep.detail,
                        logs=(rep.stdout or "") + "\n" + (rep.stderr or ""),
                    )
                    rep = validator.validate(t)
                except Exception as exc:  # noqa: BLE001
                    from dynamic_skill_eval_v2.task_generation.validator import ValidationReport
                    rep = ValidationReport(
                        task_id=t.task_id, ok=False, failed_stage="repair",
                        detail=f"{type(exc).__name__}: {exc}",
                    )
                repair_history.append({
                    "ok": rep.ok,
                    "failed_stage": rep.failed_stage,
                    "detail": rep.detail,
                })
                status = "OK" if rep.ok else f"still FAIL({rep.failed_stage}: {rep.detail})"
                print(f"      → repair result: {status}", file=sys.stderr)
                if rep.ok:
                    break

            reports.append({
                "task_id": t.task_id,
                "ok": rep.ok,
                "failed_stage": rep.failed_stage,
                "detail": rep.detail,
                "stage_dir": rep.stage_dir,
                "rendered_assets": rep.rendered_assets,
                "per_test_results": rep.per_test_results,
                "repair_history": repair_history,
            })
            status = "OK" if rep.ok else f"FAIL({rep.failed_stage}: {rep.detail})"
            print(f"  [validate] {t.task_id}: {status}", file=sys.stderr)
            if rep.per_test_results:
                for disc_id, sub in rep.per_test_results.items():
                    if sub["ok"]:
                        sub_status = f"OK ({sub.get('tests_total', '?')} tests)"
                    else:
                        sub_status = f"FAIL ({sub.get('detail', '')})"
                    print(f"      • {disc_id}: {sub_status}", file=sys.stderr)
            if not rep.ok and (rep.stdout or rep.stderr):
                tail = (rep.stdout + "\n" + rep.stderr).strip().splitlines()[-15:]
                for ln in tail:
                    print(f"      | {ln}", file=sys.stderr)
            if rep.ok or args.keep_failed:
                valid_tasks.append(t)
        print(
            f"Validation: {sum(r['ok'] for r in reports)}/{len(reports)} passed; "
            f"{len(valid_tasks)} will be materialized.",
            file=sys.stderr,
        )

    batch = TaskBatch(
        query=args.query,
        tasks=valid_tasks,
        generator_meta={
            "skill_count": len(extractions),
            "task_count_llm": len(tasks),
            "task_count_valid": len(valid_tasks),
            "model": client.model,
            "backend": client.api_type,
            "usage_tokens": generator.usage_tokens(),
            "mode": mode_label,
            "discriminators": [d.to_dict() for d in discs],
            "validation": reports,
        },
    )

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(batch.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote raw batch JSON: {args.out}", file=sys.stderr)

    if not args.json_only:
        if not args.out_dir:
            print("error: provide --out-dir or pass --json-only", file=sys.stderr)
            return 2
        written = TaskBundleWriter().write_batch(valid_tasks, args.out_dir)
        print(f"Materialized {len(written)} SkillsBench task(s) under {args.out_dir}", file=sys.stderr)
        for p in written:
            print(f"  - {p}", file=sys.stderr)

    if not args.out and args.json_only:
        print(json.dumps(batch.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
