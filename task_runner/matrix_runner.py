"""MatrixRunner — execute a capability × skill matrix via HarborSkillRunner.

Given a ``batch_<id>/`` directory laid out as:

    batch_<id>/
      capabilities.json          # CapabilityAnalysis
      skill_capability_map.json  # {skill_id: [capability_id, ...]}
      tasks/
        <capability_id>/         # one SkillsBench task bundle per capability
        ...

and a path-resolver that maps ``skill_id`` -> on-disk skill directory, this
walks every cell ``(skill, capability)`` where the skill declares the
capability, runs the per-capability task bundle through ``HarborSkillRunner``,
and emits ``matrix.json``:

    {
      "skills": [...],
      "capabilities": [...],
      "cells": {
        "<skill_id>": {
          "<capability_id>": {"reward": 0.9, "pass_rate": 0.83, "task_id": "..."}
                            | null    # capability not declared by this skill
        }
      }
    }

This is the per-cell executor — single-image-per-task is delegated to
``HarborSkillRunner`` (one per skill, so its image cache stays warm across
all capabilities of the same skill).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from dynamic_skill_eval_v2.task_generation.schema import (
    Capability,
    CapabilityAnalysis,
)
from dynamic_skill_eval_v2.task_runner.harbor_runner import (
    DEFAULT_TERMINUS_AGENT,
    HarborRunResult,
    HarborSkillRunner,
)


@dataclass
class MatrixCell:
    """One ``(skill, capability)`` outcome."""

    skill_id: str
    capability_id: str
    declared: bool                       # False ⇒ null cell, runner skipped it
    task_id: str = ""
    reward: float = 0.0
    pass_rate: float = 0.0
    image_build_ok: bool = False
    agent_ok: bool = False
    verifier_ok: bool = False
    agent_seconds: float = 0.0
    agent_tokens: int = 0
    failure: str = ""
    job_dir: str = ""

    def to_dict(self) -> dict[str, Any] | None:
        if not self.declared:
            return None
        return {
            "task_id": self.task_id,
            "reward": self.reward,
            "pass_rate": self.pass_rate,
            "image_build_ok": self.image_build_ok,
            "agent_ok": self.agent_ok,
            "verifier_ok": self.verifier_ok,
            "agent_seconds": self.agent_seconds,
            "agent_tokens": self.agent_tokens,
            "failure": self.failure,
            "job_dir": self.job_dir,
        }


@dataclass
class MatrixResult:
    """Full matrix run output."""

    batch_dir: str = ""
    skills: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    cells: list[MatrixCell] = field(default_factory=list)
    started_at: float = 0.0
    finished_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        # Group cells into nested {skill: {cap: cell|null}} for matrix.json.
        nested: dict[str, dict[str, Any]] = {sid: {} for sid in self.skills}
        for cell in self.cells:
            nested.setdefault(cell.skill_id, {})[cell.capability_id] = cell.to_dict()
        # Ensure every (skill, capability) key exists, even null cells, so
        # downstream report tooling can render a fully-populated matrix.
        for sid in self.skills:
            for cap in self.capabilities:
                nested[sid].setdefault(cap, None)
        return {
            "schema_version": "matrix.v1",
            "batch_dir": self.batch_dir,
            "skills": list(self.skills),
            "capabilities": list(self.capabilities),
            "cells": nested,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed_sec": round(self.finished_at - self.started_at, 2),
        }


# ---------------------------------------------------------------- batch loader


@dataclass(frozen=True)
class MatrixBatch:
    """Loaded view of a batch_<id>/ directory."""

    batch_dir: Path
    capabilities: list[Capability]
    skill_capability_map: dict[str, list[str]]
    task_bundles: dict[str, Path]        # {capability_id: bundle_dir}

    @classmethod
    def load(cls, batch_dir: str | Path) -> "MatrixBatch":
        root = Path(batch_dir).resolve()
        caps_path = root / "capabilities.json"
        map_path = root / "skill_capability_map.json"
        tasks_root = root / "tasks"
        if not caps_path.is_file():
            raise FileNotFoundError(f"missing {caps_path}")
        if not map_path.is_file():
            raise FileNotFoundError(f"missing {map_path}")
        if not tasks_root.is_dir():
            raise FileNotFoundError(f"missing {tasks_root}")
        analysis = CapabilityAnalysis.from_dict(
            json.loads(caps_path.read_text(encoding="utf-8"))
        )
        skill_map_raw = json.loads(map_path.read_text(encoding="utf-8"))
        if not isinstance(skill_map_raw, dict):
            raise ValueError(f"{map_path} must be a JSON object")
        skill_map: dict[str, list[str]] = {
            str(k): [str(v) for v in (vs or [])]
            for k, vs in skill_map_raw.items()
        }
        bundles: dict[str, Path] = {}
        for cap in analysis.capabilities:
            bundle = tasks_root / cap.id
            if not bundle.is_dir():
                raise FileNotFoundError(
                    f"batch missing task bundle for capability {cap.id!r}: {bundle}"
                )
            bundles[cap.id] = bundle
        return cls(
            batch_dir=root,
            capabilities=analysis.capabilities,
            skill_capability_map=skill_map,
            task_bundles=bundles,
        )


# ------------------------------------------------------------------ MatrixRunner


SkillPathResolver = Callable[[str], Path]


class MatrixRunner:
    """Walk every declared cell of a capability matrix.

    Args:
        batch: a loaded ``MatrixBatch``.
        skill_path_resolver: callable ``skill_id -> Path`` returning the on-disk
            skill directory for that id. The resolver MUST raise/return a
            non-existent path for unknown skills — the runner fails loudly
            rather than skip. (No fallback.)
        model: model name forwarded to harbor (--model).
        work_dir: harbor jobs / staged tasks live under here.
        force_build: pass --force-build to harbor (rebuild image every time).
        timeout_sec: per-cell harbor timeout.
        registry_mirror / agent_kwargs / agent_import_path: forwarded to
            HarborSkillRunner.
        on_cell: optional callback ``(cell) -> None`` called after each cell
            so callers can stream progress.
    """

    def __init__(
        self,
        batch: MatrixBatch,
        skill_path_resolver: SkillPathResolver,
        model: str | None = None,
        work_dir: str | Path | None = None,
        force_build: bool = False,
        timeout_sec: int = 1800,
        registry_mirror: str | None = None,
        agent_kwargs: dict[str, str] | None = None,
        agent_import_path: str = DEFAULT_TERMINUS_AGENT,
        keep_workspace: bool = False,
        cleanup_images: bool = True,
        cleanup_base_images: bool = False,
        use_skill_deps: bool = True,
        on_cell: Callable[[MatrixCell], None] | None = None,
    ) -> None:
        self.batch = batch
        self.skill_path_resolver = skill_path_resolver
        self.model = model
        self.work_dir = Path(work_dir).resolve() if work_dir else None
        self.force_build = force_build
        self.timeout_sec = timeout_sec
        self.registry_mirror = registry_mirror
        self.agent_kwargs = dict(agent_kwargs or {})
        self.agent_import_path = agent_import_path
        self.keep_workspace = keep_workspace
        self.cleanup_images = cleanup_images
        self.cleanup_base_images = cleanup_base_images
        self.use_skill_deps = use_skill_deps
        self.on_cell = on_cell

    def run(self) -> MatrixResult:
        result = MatrixResult(
            batch_dir=str(self.batch.batch_dir),
            skills=sorted(self.batch.skill_capability_map.keys()),
            capabilities=[c.id for c in self.batch.capabilities],
            started_at=time.time(),
        )
        # One HarborSkillRunner per skill. Its image cache is keyed by
        # (task_id, skill_id), so iterating capabilities under one skill
        # benefits from cached layers (ubuntu base, skill-deps pip layer).
        for skill_id in result.skills:
            declared_caps = self.batch.skill_capability_map.get(skill_id) or []
            skill_path = self.skill_path_resolver(skill_id)
            if not skill_path.is_dir():
                # Not a fallback — surface the missing skill with explicit cells.
                for cap_id in result.capabilities:
                    cell = MatrixCell(
                        skill_id=skill_id,
                        capability_id=cap_id,
                        declared=cap_id in declared_caps,
                        failure=f"skill_path_not_found: {skill_path}",
                    )
                    result.cells.append(cell)
                    if cell.declared and self.on_cell:
                        self.on_cell(cell)
                continue
            runner = HarborSkillRunner(
                skill_path=skill_path,
                skill_id=skill_id,
                model=self.model,
                agent_import_path=self.agent_import_path,
                work_dir=self.work_dir,
                keep_workspace=self.keep_workspace,
                force_build=self.force_build,
                agent_kwargs=self.agent_kwargs,
                timeout_sec=self.timeout_sec,
                registry_mirror=self.registry_mirror,
                cleanup_images=self.cleanup_images,
                cleanup_base_images=self.cleanup_base_images,
                use_skill_deps=self.use_skill_deps,
            )
            try:
                for cap_id in result.capabilities:
                    if cap_id not in declared_caps:
                        result.cells.append(MatrixCell(
                            skill_id=skill_id,
                            capability_id=cap_id,
                            declared=False,
                        ))
                        continue
                    bundle = self.batch.task_bundles[cap_id]
                    cell = self._run_cell(runner, skill_id, cap_id, bundle)
                    result.cells.append(cell)
                    if self.on_cell:
                        self.on_cell(cell)
            finally:
                runner.cleanup()
        result.finished_at = time.time()
        return result

    def _run_cell(
        self,
        runner: HarborSkillRunner,
        skill_id: str,
        capability_id: str,
        bundle: Path,
    ) -> MatrixCell:
        run: HarborRunResult = runner.run(bundle)
        return MatrixCell(
            skill_id=skill_id,
            capability_id=capability_id,
            declared=True,
            task_id=run.task_id,
            reward=run.reward,
            pass_rate=run.pass_rate,
            image_build_ok=run.image_build_ok,
            agent_ok=run.agent_ok,
            verifier_ok=run.verifier_ok,
            agent_seconds=run.agent_seconds,
            agent_tokens=run.agent_tokens,
            failure=(
                run.image_build_detail if not run.image_build_ok
                else run.agent_failure if not run.agent_ok
                else run.verifier_failure
            ),
            job_dir=run.job_dir,
        )


__all__ = [
    "MatrixBatch",
    "MatrixCell",
    "MatrixResult",
    "MatrixRunner",
    "SkillPathResolver",
]
