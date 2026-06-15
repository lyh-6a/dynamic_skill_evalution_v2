"""TaskBundleWriter — materialize a GeneratedTask as a SkillsBench task dir.

Layout produced (matches /home/liuyuhan/dynamic_skill_evalution/skillsbench/tasks/<id>/):

    <out_dir>/<task_id>/
    ├── task.toml
    ├── instruction.md
    ├── candidate_solutions.json     # cross-skill comparison sidecar (ours)
    ├── ground_truth.json            # sidecar: structured truth used by solution
    ├── environment/
    │   ├── Dockerfile
    │   └── <asset(s)>               # text bodies or rendered binary bytes
    ├── solution/
    │   ├── solve.sh                 # SkillsBench-standard entrypoint (debug only)
    │   └── solution.py              # reference solution that produced the truth
    └── tests/
        ├── test.sh
        └── test_outputs.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dynamic_skill_eval_v2.task_generation.schema import GeneratedTask, TaskAsset
from dynamic_skill_eval_v2.task_generation.validator import _assemble_combined_tests

# Intentionally minimal. The agent should NOT get a generic toolbox (no
# tesseract, no poppler) at the base layer — capability must come from the
# candidate skill (which can declare its own apt/pip needs). Previously
# leaving these in let the agent shell out to ``pdftotext``/``tesseract``
# and "pass" skills that declared zero deps, masking real coverage gaps.
SYSTEM_PACKAGES: tuple[str, ...] = ()

# pip index URL used during ``docker build`` so the per-task image can install
# PRELOAD_LIBS on networks where pypi.org is unreachable. Defaults to the
# Tsinghua mirror; override via env at writer instantiation time if needed.
# Pytest + ctrf reporter the verifier needs at runtime. Baked into the
# image at build time (host has internet) so ``test.sh`` doesn't need to
# pip-install anything in the offline runtime container — previously the
# verifier could hang or time out on flaky outbound networking.
VERIFIER_DEPS: tuple[str, ...] = (
    "pytest==8.4.1",
    "pytest-json-ctrf==0.3.5",
)

DEFAULT_PIP_INDEX_URL = "https://pypi.tuna.tsinghua.edu.cn/simple"

DOCKERFILE_TEMPLATE = """FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \\
    python3 python3-pip \\
$apt_lines \\
    && rm -rf /var/lib/apt/lists/*

# Preinstall the verifier framework (pytest + ctrf reporter) so test.sh
# runs immediately. If the candidate skill ships a ``requirements.txt``
# the runner merges it here at build time too (convenience — agent gets
# skill deps without a runtime pip install). The agent is free to
# ``pip install`` or ``apt-get install`` additional packages at runtime;
# the evaluation measures whether it *followed the skill*, not whether it
# managed without internet.
RUN pip3 install --no-cache-dir --break-system-packages \\
    --index-url $pip_index_url \\
$pip_lines

WORKDIR /root

# Inputs for this task
$copy_lines
"""

TEST_SH = """#!/bin/bash
# pytest/pytest-json-ctrf are baked into the image at build time (see
# Dockerfile), so this script does not need any runtime pip-install —
# previously that hung on flaky outbound networking inside the container.
mkdir -p /logs/verifier
pytest --ctrf /logs/verifier/ctrf.json /tests/test_outputs.py -rA -v
if [ $? -eq 0 ]; then echo 1 > /logs/verifier/reward.txt; else echo 0 > /logs/verifier/reward.txt; fi
exit 0
"""

SOLVE_SH = """#!/bin/bash
# Reference solution kept for debugging only — NOT used by the evaluated agent.
# The runtime dependencies of solution.py mirror the validator's PRELOAD_LIBS
# (see dynamic_skill_eval_v2.task_generation.validator.PRELOAD_LIBS).
set -e
python3 /solution/solution.py
"""


class TaskBundleWriter:
    """Write a SkillsBench-format task directory to disk."""

    def __init__(
        self,
        verifier_timeout_sec: float = 120.0,
        agent_timeout_sec: float = 300.0,
        build_timeout_sec: float = 600.0,
        cpus: int = 1,
        memory_mb: int = 2048,
        storage_mb: int = 4096,
        pip_index_url: str = DEFAULT_PIP_INDEX_URL,
    ) -> None:
        self.verifier_timeout_sec = verifier_timeout_sec
        self.agent_timeout_sec = agent_timeout_sec
        self.build_timeout_sec = build_timeout_sec
        self.cpus = cpus
        self.memory_mb = memory_mb
        self.storage_mb = storage_mb
        self.pip_index_url = pip_index_url

    def write(self, task: GeneratedTask, out_root: str | Path) -> Path:
        task_root = Path(out_root) / task.task_id
        task_root.mkdir(parents=True, exist_ok=True)
        (task_root / "environment").mkdir(exist_ok=True)
        (task_root / "tests").mkdir(exist_ok=True)

        self._write_task_toml(task_root / "task.toml", task)
        (task_root / "instruction.md").write_text(
            task.instruction_md.rstrip() + "\n", encoding="utf-8"
        )
        self._write_candidate_solutions(task_root / "candidate_solutions.json", task)
        if task.ground_truth:
            (task_root / "ground_truth.json").write_text(
                json.dumps(task.ground_truth, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        self._write_environment(task_root / "environment", task)
        self._write_tests(task_root / "tests", task)
        if task.solution_py.strip():
            self._write_solution(task_root / "solution", task)
        return task_root

    def write_batch(
        self, tasks: list[GeneratedTask], out_root: str | Path
    ) -> list[Path]:
        out_root_path = Path(out_root)
        out_root_path.mkdir(parents=True, exist_ok=True)
        return [self.write(t, out_root_path) for t in tasks]

    # --------------------------------------------------------------- writers

    def _write_task_toml(self, path: Path, task: GeneratedTask) -> None:
        extras = task.task_toml_extras or {}
        meta_lines: list[str] = []
        for key, value in extras.items():
            meta_lines.append(f"{key} = {_toml_value(value)}")
        meta_block = "\n".join(meta_lines)

        body = (
            f'version = "1.0"\n'
            f"\n"
            f"[metadata]\n"
            f'task_name = "{_toml_escape(task.name or task.task_id)}"\n'
            f'generated_by = "dynamic_skill_eval_v2.task_generation"\n'
            f"{meta_block}\n"
            f"\n"
            f"[verifier]\n"
            f"timeout_sec = {self.verifier_timeout_sec}\n"
            f"\n"
            f"[agent]\n"
            f"timeout_sec = {self.agent_timeout_sec}\n"
            f"\n"
            f"[environment]\n"
            f"build_timeout_sec = {self.build_timeout_sec}\n"
            f"cpus = {self.cpus}\n"
            f"memory_mb = {self.memory_mb}\n"
            f"storage_mb = {self.storage_mb}\n"
        )
        path.write_text(body, encoding="utf-8")

    def _write_candidate_solutions(self, path: Path, task: GeneratedTask) -> None:
        payload: dict[str, Any] = {
            "schema_version": "candidate_solutions.v1",
            "task_id": task.task_id,
            "query": task.query,
            "candidate_solutions": [c.to_dict() for c in task.candidate_solutions],
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _write_environment(self, env_root: Path, task: GeneratedTask) -> None:
        copy_lines: list[str] = []
        for asset in task.assets:
            rel = asset.path.lstrip("/")
            dst = env_root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            self._write_asset(asset, dst)
            container_path = asset.container_path or f"/root/{rel}"
            copy_lines.append(f"COPY {rel} {container_path}")

        dockerfile = (
            DOCKERFILE_TEMPLATE
            .replace(
                "$apt_lines",
                " \\\n".join(f"    {pkg}" for pkg in SYSTEM_PACKAGES),
            )
            .replace("$pip_index_url", self.pip_index_url)
            .replace(
                "$pip_lines",
                " \\\n".join(f"    {pkg}" for pkg in VERIFIER_DEPS),
            )
            .replace(
                "$copy_lines",
                "\n".join(copy_lines) if copy_lines else "# (no input files)",
            )
        )
        (env_root / "Dockerfile").write_text(dockerfile, encoding="utf-8")

    def _write_asset(self, asset: TaskAsset, dst: Path) -> None:
        if asset.kind == "text":
            dst.write_text(asset.content, encoding="utf-8")
            return
        # binary
        if asset.content_bytes is None:
            raise ValueError(
                f"binary asset {asset.path!r} has no rendered bytes — "
                "did you run TaskValidator before writing?"
            )
        dst.write_bytes(asset.content_bytes)

    def _write_tests(self, tests_root: Path, task: GeneratedTask) -> None:
        (tests_root / "test.sh").write_text(TEST_SH, encoding="utf-8")
        if task.tests:
            # combined-task mode: assemble header + all TestClasses into one file.
            # Runner-side ctrf.json keeps classname so per-discriminator results
            # are still recoverable downstream.
            assembled = _assemble_combined_tests(task)
            (tests_root / "test_outputs.py").write_text(
                assembled.rstrip() + "\n", encoding="utf-8"
            )
        else:
            (tests_root / "test_outputs.py").write_text(
                task.tests_py.rstrip() + "\n", encoding="utf-8"
            )

    def _write_solution(self, sol_root: Path, task: GeneratedTask) -> None:
        sol_root.mkdir(parents=True, exist_ok=True)
        (sol_root / "solution.py").write_text(
            task.solution_py.rstrip() + "\n", encoding="utf-8"
        )
        (sol_root / "solve.sh").write_text(SOLVE_SH, encoding="utf-8")


# --------------------------------------------------------------- TOML helpers


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    return f'"{_toml_escape(str(value))}"'


def _toml_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


__all__ = ["TaskBundleWriter"]
