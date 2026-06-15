"""CLI for task_runner.

Usage examples
--------------

Run a generated task with its own oracle solution (sanity check)::

    python -m dynamic_skill_eval_v2.task_runner.cli \
        --task /tmp/generated_combined/pdf-email-to-docx-combined \
        --mode solution

Run with a custom shell command (your own agent harness)::

    python -m dynamic_skill_eval_v2.task_runner.cli \
        --task /tmp/.../pdf-email-to-docx-combined \
        --mode agent-command \
        --skill-id my-skill --skill-file ./SKILL.md \
        --agent-command "my-agent --workdir {root} --instruction {instruction}"

Run with the built-in LLM bash-script agent (uses ChatClient env vars)::

    python -m dynamic_skill_eval_v2.task_runner.cli \
        --task /tmp/.../pdf-email-to-docx-combined \
        --mode llm-agent \
        --skill-id pdf-extract-v1 --skill-file ./SKILL.md
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dynamic_skill_eval_v2.llm_client import ChatClient
from dynamic_skill_eval_v2.task_runner.runner import SkillRunner


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="task_runner",
        description="Execute one SkillsBench task bundle with one skill and report per-discriminator pass/fail.",
    )
    parser.add_argument("--task", required=True, type=Path,
                        help="Path to a task bundle directory (the output of TaskBundleWriter).")
    parser.add_argument("--mode", choices=["solution", "agent-command", "llm-agent"], default="solution")
    parser.add_argument("--skill-id", default="skill",
                        help="Identifier for the skill being evaluated (only used to label the result).")
    parser.add_argument("--skill-file", type=Path, default=None,
                        help="Path to SKILL.md or equivalent; its contents are passed to the LLM agent.")
    parser.add_argument("--agent-command", type=str, default=None,
                        help="Shell command template for mode='agent-command'. Supports "
                             "{root}/{tests}/{logs}/{app_workspace}/{instruction}/{skill}/{task}.")
    parser.add_argument("--timeout-sec", type=int, default=300)
    parser.add_argument("--work-dir", type=Path, default=None,
                        help="Stage dirs go under here. Defaults to a fresh tempdir.")
    parser.add_argument("--keep-workspace", action="store_true",
                        help="Don't delete the stage directory after the run.")
    parser.add_argument("--out", type=Path, default=None,
                        help="If set, write the result JSON to this path.")
    # LLM config (only used in llm-agent mode)
    parser.add_argument("--model", type=str, default=None)
    parser.add_argument("--base-url", type=str, default=None)
    parser.add_argument("--api-type", choices=["openai", "anthropic"], default=None)
    parser.add_argument("--max-agent-tokens", type=int, default=3000)
    args = parser.parse_args(argv)

    skill_text = ""
    if args.skill_file:
        if not args.skill_file.is_file():
            print(f"error: --skill-file not found: {args.skill_file}", file=sys.stderr)
            return 2
        skill_text = args.skill_file.read_text(encoding="utf-8", errors="replace")

    llm_client = None
    if args.mode == "llm-agent":
        llm_client = ChatClient(
            model=args.model,
            base_url=args.base_url,
            api_type=args.api_type,
            timeout_sec=args.timeout_sec,
        )
        if not llm_client.available:
            print("error: LLM client is not configured (need OPENAI_*/ANTHROPIC_* env "
                  "or --model/--base-url and api key).", file=sys.stderr)
            return 2

    runner = SkillRunner(
        mode=args.mode,
        agent_command=args.agent_command,
        llm_client=llm_client,
        timeout_sec=args.timeout_sec,
        work_dir=args.work_dir,
        keep_workspace=args.keep_workspace,
        max_agent_tokens=args.max_agent_tokens,
    )
    result = runner.run(args.task, skill_id=args.skill_id, skill_text=skill_text)

    summary = result.to_dict()
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote: {args.out}", file=sys.stderr)

    # Human-friendly summary on stderr; raw JSON on stdout for piping.
    print(_summarize(result), file=sys.stderr)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if result.passed else 1


def _summarize(result) -> str:
    lines = [
        f"task        : {result.task_id}",
        f"skill       : {result.skill_id}",
        f"mode        : {result.mode}",
        f"executor    : {'PASS' if result.executor_passed else f'FAIL ({result.executor_failure})'} "
        f"({result.executor_seconds:.1f}s)",
    ]
    if result.executor_passed:
        verifier_line = f"verifier    : {'PASS' if result.verifier_passed else f'FAIL ({result.verifier_failure})'} ({result.verifier_seconds:.1f}s)"
        lines.append(verifier_line)
        if result.discriminators:
            lines.append(f"discriminators ({len(result.discriminators)}):")
            for d in result.discriminators:
                status = "PASS" if d.passed else f"FAIL — {d.detail}"
                lines.append(f"  • {d.class_name}: {status}")
        lines.append(f"pass_rate   : {result.pass_rate}")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
