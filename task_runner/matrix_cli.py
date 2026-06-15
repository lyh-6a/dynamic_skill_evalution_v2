"""CLI for MatrixRunner.

Run a capability × skill matrix produced by ``task_generation.matrix_cli``
through HarborSkillRunner, one cell at a time. Emits ``matrix.json`` next
to the batch.

Usage:
    python -m dynamic_skill_eval_v2.task_runner.matrix_cli \\
        --batch-dir /tmp/matrix_batch_demo \\
        --skills-root /home/liuyuhan/dynamic_skill_evalution/skills \\
        --model anthropic/claude-haiku-4-5-20251001

The default skill-path resolver looks under ``--skills-root`` for a
directory named exactly the skill_id. Override with ``--skill-map`` (a
JSON ``{skill_id: path}``) when the on-disk dir doesn't match.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dynamic_skill_eval_v2.task_runner.harbor_runner import DEFAULT_TERMINUS_AGENT
from dynamic_skill_eval_v2.task_runner.matrix_runner import (
    MatrixBatch,
    MatrixCell,
    MatrixRunner,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="task_runner.matrix_cli",
        description="Execute a capability × skill matrix via HarborSkillRunner.",
    )
    parser.add_argument("--batch-dir", required=True, type=Path,
                        help="Path to the matrix batch directory built by task_generation.matrix_cli.")
    parser.add_argument("--skills-root", type=Path, default=None,
                        help="Default resolver: <skills-root>/<skill_id>/.")
    parser.add_argument("--skill-map", type=Path, default=None,
                        help="JSON {skill_id: skill_dir_path}; takes precedence over --skills-root.")
    parser.add_argument("--model", type=str, default=None)
    parser.add_argument("--work-dir", type=Path, default=None)
    parser.add_argument("--force-build", action="store_true")
    parser.add_argument("--timeout-sec", type=int, default=1800)
    parser.add_argument("--registry-mirror", type=str, default=None)
    parser.add_argument("--ak", action="append", default=[],
                        help="Extra --ak key=value pairs for harbor.")
    parser.add_argument("--agent-import-path", type=str, default=DEFAULT_TERMINUS_AGENT)
    parser.add_argument("--keep-workspace", action="store_true")
    parser.add_argument("--no-cleanup-images", action="store_true")
    parser.add_argument("--cleanup-base-images", action="store_true")
    parser.add_argument("--no-skill-deps", action="store_true")
    parser.add_argument("--out", type=Path, default=None,
                        help="Where to write matrix.json. Defaults to <batch-dir>/matrix.json.")
    args = parser.parse_args(argv)

    batch = MatrixBatch.load(args.batch_dir)
    skill_map: dict[str, Path] = {}
    if args.skill_map:
        raw = json.loads(args.skill_map.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            print(f"--skill-map must be a JSON object", file=sys.stderr)
            return 2
        skill_map = {str(k): Path(v).resolve() for k, v in raw.items()}

    def resolver(skill_id: str) -> Path:
        if skill_id in skill_map:
            return skill_map[skill_id]
        if args.skills_root is None:
            return Path(f"<unset-skills-root>/{skill_id}")
        return (args.skills_root / skill_id).resolve()

    agent_kwargs: dict[str, str] = {}
    for entry in args.ak:
        if "=" not in entry:
            print(f"error: --ak expects key=value, got {entry!r}", file=sys.stderr)
            return 2
        key, value = entry.split("=", 1)
        agent_kwargs[key.strip()] = value

    def on_cell(cell: MatrixCell) -> None:
        status = (
            "PASS" if cell.verifier_ok
            else f"FAIL({cell.failure})" if cell.declared
            else "SKIP"
        )
        print(
            f"  [{cell.skill_id}][{cell.capability_id}] {status} "
            f"reward={cell.reward} pass={cell.pass_rate} "
            f"agent={cell.agent_seconds:.1f}s tokens={cell.agent_tokens}",
            file=sys.stderr,
            flush=True,
        )

    runner = MatrixRunner(
        batch=batch,
        skill_path_resolver=resolver,
        model=args.model,
        work_dir=args.work_dir,
        force_build=args.force_build,
        timeout_sec=args.timeout_sec,
        registry_mirror=args.registry_mirror,
        agent_kwargs=agent_kwargs,
        agent_import_path=args.agent_import_path,
        keep_workspace=args.keep_workspace,
        cleanup_images=not args.no_cleanup_images,
        cleanup_base_images=args.cleanup_base_images,
        use_skill_deps=not args.no_skill_deps,
        on_cell=on_cell,
    )
    print(
        f"Running matrix: {len(runner.batch.skill_capability_map)} skills × "
        f"{len(runner.batch.capabilities)} capabilities ...",
        file=sys.stderr,
    )
    result = runner.run()

    out_path = args.out or (args.batch_dir / "matrix.json")
    out_path.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote matrix: {out_path}", file=sys.stderr)
    print(_render_table(result), file=sys.stderr)
    return 0


def _render_table(result) -> str:
    lines = ["", "Matrix (reward / pass_rate):"]
    cap_ids = result.capabilities
    header = ["skill"] + cap_ids
    rows = [header]
    nested: dict[str, dict[str, dict | None]] = {sid: {} for sid in result.skills}
    for cell in result.cells:
        nested.setdefault(cell.skill_id, {})[cell.capability_id] = cell.to_dict()
    for sid in result.skills:
        row = [sid]
        for cap in cap_ids:
            entry = nested[sid].get(cap)
            if entry is None:
                row.append("-")
            else:
                row.append(f"{entry['reward']:.2f}/{entry['pass_rate']:.2f}")
        rows.append(row)
    widths = [max(len(r[i]) for r in rows) for i in range(len(header))]
    for r in rows:
        lines.append("  ".join(r[i].ljust(widths[i]) for i in range(len(header))))
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
