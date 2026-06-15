"""CLI for HarborSkillRunner.

Run one generated task bundle against one skill, in a per-task Docker
image built from the task's environment/Dockerfile, with the skill mounted
inside the container via harbor's --skill flag and the terminus-2 agent
forcing the LLM to acknowledge & use the skill on every turn.

Prerequisites:
    - docker CLI on PATH
    - harbor CLI on PATH (defaults to the one in your conda env)
    - libs.terminus_agent on the harbor process's PYTHONPATH (set
      SKILLSBENCH_ROOT or add a sitecustomize hook; see harbor's docs)
    - LLM API env vars (ANTHROPIC_AUTH_TOKEN / OPENAI_API_KEY, etc.)
      consumable by liteLLM inside the harbor process

Example:
    python -m dynamic_skill_eval_v2.task_runner.harbor_cli \
        --task /tmp/generated_combined2/pdf-email-to-docx-combined \
        --skill /home/liuyuhan/dynamic_skill_evalution/doc_skills/document-format-converter-1.0.0 \
        --model anthropic/claude-sonnet-4-5 \
        --work-dir /tmp/harbor_demo
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dynamic_skill_eval_v2.task_runner.harbor_runner import (
    DEFAULT_TERMINUS_AGENT,
    HarborSkillRunner,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="harbor_skill_runner",
        description="Run one task bundle against one skill via Harbor + Docker, force-injecting the skill.",
    )
    parser.add_argument("--task", required=True, type=Path)
    parser.add_argument("--skill", required=True, type=Path,
                        help="Path to the candidate skill directory (the dir containing SKILL.md).")
    parser.add_argument("--skill-id", type=str, default=None,
                        help="Label for the skill in the result. Defaults to skill dir basename.")
    parser.add_argument("--model", type=str, default=None,
                        help="Model name passed to harbor as --model. "
                             "Defaults to ANTHROPIC_MODEL or OPENAI_MODEL env.")
    parser.add_argument("--agent-import-path", type=str, default=DEFAULT_TERMINUS_AGENT,
                        help="Harbor --agent-import-path. Default is HarborTerminus2WithSkills.")
    parser.add_argument("--work-dir", type=Path, default=None)
    parser.add_argument("--harbor-command", type=str, default="harbor")
    parser.add_argument("--keep-workspace", action="store_true")
    parser.add_argument("--force-build", action="store_true",
                        help="Pass --force-build to harbor (rebuild the docker image).")
    parser.add_argument("--ak", action="append", default=[],
                        help="Extra --ak key=value pairs forwarded to harbor.")
    parser.add_argument("--timeout-sec", type=int, default=1800)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--registry-mirror", type=str, default=None,
                        help="Docker Hub mirror host (e.g. docker.m.daocloud.io). "
                             "If set, base images referenced by the task's Dockerfile "
                             "are pulled from this mirror and re-tagged locally. "
                             "Falls back to env DYN_SKILL_EVAL_REGISTRY_MIRROR.")
    parser.add_argument("--no-cleanup-images", action="store_true",
                        help="Keep per-task images instead of removing them after the run.")
    parser.add_argument("--cleanup-base-images", action="store_true",
                        help="Also delete base images this runner pulled. "
                             "Default keeps them so subsequent runs reuse the layers.")
    parser.add_argument("--no-skill-deps", action="store_true",
                        help="Disable skill-deps Dockerfile rewriting. By default the runner "
                             "replaces the bundle's pip block with the candidate skill's "
                             "requirements.txt (or scripts/requirements.txt) so the runtime "
                             "container is sandboxed to skill-declared deps. Pass this flag "
                             "to fall back to the bundle's PRELOAD_LIBS for debugging.")
    args = parser.parse_args(argv)

    agent_kwargs: dict[str, str] = {}
    for entry in args.ak:
        if "=" not in entry:
            print(f"error: --ak expects key=value, got {entry!r}", file=sys.stderr)
            return 2
        key, value = entry.split("=", 1)
        agent_kwargs[key.strip()] = value

    runner = HarborSkillRunner(
        skill_path=args.skill,
        skill_id=args.skill_id,
        model=args.model,
        agent_import_path=args.agent_import_path,
        work_dir=args.work_dir,
        harbor_command=args.harbor_command,
        keep_workspace=args.keep_workspace,
        force_build=args.force_build,
        agent_kwargs=agent_kwargs,
        timeout_sec=args.timeout_sec,
        registry_mirror=args.registry_mirror,
        cleanup_images=not args.no_cleanup_images,
        cleanup_base_images=args.cleanup_base_images,
        use_skill_deps=not args.no_skill_deps,
    )
    try:
        result = runner.run(args.task)
    finally:
        runner.cleanup()
    summary = result.to_dict()
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote: {args.out}", file=sys.stderr)
    print(_summarize(result), file=sys.stderr)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if result.passed else 1


def _summarize(result) -> str:
    lines = [
        f"task         : {result.task_id}",
        f"skill        : {result.skill_id}",
        f"image_build  : {'OK' if result.image_build_ok else 'FAIL'} — {result.image_build_detail}",
        f"agent        : {'OK' if result.agent_ok else f'FAIL ({result.agent_failure})'} "
        f"({result.agent_seconds:.1f}s, {result.agent_tokens} out-tokens)",
        f"verifier     : {'OK' if result.verifier_ok else f'FAIL ({result.verifier_failure})'}",
        f"reward       : {result.reward}",
    ]
    if result.discriminators:
        lines.append(f"discriminators ({len(result.discriminators)}):")
        for d in result.discriminators:
            status = "PASS" if d.passed else f"FAIL — {d.detail}"
            lines.append(f"  • {d.class_name}: {status}")
    lines.append(f"pass_rate    : {result.pass_rate}")
    lines.append(f"job_dir      : {result.job_dir}")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
