"""Matrix-mode batch builder.

Pipeline:
  1. ``analyze_capabilities(query, extractions)`` -> CapabilityAnalysis
  2. for each capability:
        ``generate_for_capability(query, capability)`` -> GeneratedTask
        ``TaskValidator.validate(task)``       -> renderer / solution / pytest
        if validation fails: capability dropped from batch (no silent
        weakening — the column is removed, the matrix renderer can decide
        how to surface it).
  3. ``TaskBundleWriter.write(task, batch_dir/tasks/)`` -> SkillsBench bundle
  4. emit ``capabilities.json`` and ``skill_capability_map.json`` so
     ``MatrixRunner`` can pick this batch up later.

This keeps the orchestration in one place; the generator / validator /
bundle writer themselves stay single-purpose.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dynamic_skill_eval_v2.skill_extractor.schema import SkillExtraction
from dynamic_skill_eval_v2.task_generation.bundle_writer import TaskBundleWriter
from dynamic_skill_eval_v2.task_generation.generator import TaskGenerator
from dynamic_skill_eval_v2.task_generation.schema import (
    Capability,
    CapabilityAnalysis,
    GeneratedTask,
)
from dynamic_skill_eval_v2.task_generation.validator import TaskValidator, ValidationReport


@dataclass
class CapabilityBuildOutcome:
    capability_id: str
    ok: bool = False
    task_id: str = ""
    failure: str = ""
    failed_stage: str = ""
    bundle_dir: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "ok": self.ok,
            "task_id": self.task_id,
            "failure": self.failure,
            "failed_stage": self.failed_stage,
            "bundle_dir": self.bundle_dir,
        }


@dataclass
class MatrixBatchReport:
    batch_dir: str = ""
    query: str = ""
    skill_ids: list[str] = field(default_factory=list)
    capability_ids: list[str] = field(default_factory=list)
    outcomes: list[CapabilityBuildOutcome] = field(default_factory=list)
    tokens_used: int = 0
    elapsed_sec: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_dir": self.batch_dir,
            "query": self.query,
            "skill_ids": list(self.skill_ids),
            "capability_ids": list(self.capability_ids),
            "outcomes": [o.to_dict() for o in self.outcomes],
            "tokens_used": self.tokens_used,
            "elapsed_sec": round(self.elapsed_sec, 2),
        }


class MatrixBatchBuilder:
    """Compose generator + validator + writer into a single batch_<id>/ dir."""

    def __init__(
        self,
        generator: TaskGenerator,
        validator: TaskValidator | None = None,
        bundle_writer: TaskBundleWriter | None = None,
        repair_attempts: int = 1,
    ) -> None:
        self.generator = generator
        self.validator = validator
        self.bundle_writer = bundle_writer or TaskBundleWriter()
        self.repair_attempts = max(0, repair_attempts)

    def build(
        self,
        query: str,
        extractions: list[SkillExtraction],
        out_dir: str | Path,
        analysis: CapabilityAnalysis | None = None,
    ) -> MatrixBatchReport:
        started = time.time()
        out_root = Path(out_dir).resolve()
        out_root.mkdir(parents=True, exist_ok=True)
        tasks_root = out_root / "tasks"
        tasks_root.mkdir(exist_ok=True)

        if analysis is None:
            analysis = self.generator.analyze_capabilities(
                query=query, extractions=extractions
            )

        # capabilities.json + skill_capability_map.json: write *before* any
        # per-capability task is built so a partial batch is still inspectable.
        (out_root / "capabilities.json").write_text(
            json.dumps(analysis.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (out_root / "skill_capability_map.json").write_text(
            json.dumps(analysis.skill_capability_map, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        report = MatrixBatchReport(
            batch_dir=str(out_root),
            query=query,
            skill_ids=[e.skill_id for e in extractions],
            capability_ids=[c.id for c in analysis.capabilities],
        )

        for cap in analysis.capabilities:
            outcome = self._build_one(cap, query, tasks_root)
            report.outcomes.append(outcome)

        report.tokens_used = self.generator.usage_tokens()
        report.elapsed_sec = time.time() - started

        # Trim capabilities.json + skill_capability_map.json to only the caps
        # that successfully produced bundles. Failed capabilities are dropped
        # from the matrix so MatrixRunner doesn't try to run a missing bundle.
        ok_ids = {o.capability_id for o in report.outcomes if o.ok}
        if ok_ids != {c.id for c in analysis.capabilities}:
            kept_caps = [c for c in analysis.capabilities if c.id in ok_ids]
            kept_caps_with_filtered_skills: list[Capability] = []
            for c in kept_caps:
                kept_caps_with_filtered_skills.append(c)
            kept_map: dict[str, list[str]] = {}
            for sid, caps in analysis.skill_capability_map.items():
                kept = [cid for cid in caps if cid in ok_ids]
                if kept:
                    kept_map[sid] = kept
            trimmed = CapabilityAnalysis(
                capabilities=kept_caps_with_filtered_skills,
                skill_capability_map=kept_map,
            )
            (out_root / "capabilities.json").write_text(
                json.dumps(trimmed.to_dict(), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            (out_root / "skill_capability_map.json").write_text(
                json.dumps(kept_map, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

        (out_root / "build_report.json").write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return report

    def _build_one(
        self,
        cap: Capability,
        query: str,
        tasks_root: Path,
    ) -> CapabilityBuildOutcome:
        outcome = CapabilityBuildOutcome(capability_id=cap.id)
        # Prompt-isolated generation — this raises if the LLM returns garbage.
        try:
            task = self.generator.generate_for_capability(query=query, capability=cap)
        except Exception as exc:  # noqa: BLE001 — surface as a build failure
            outcome.failure = f"generate: {type(exc).__name__}: {exc}"
            outcome.failed_stage = "generate"
            return outcome
        outcome.task_id = task.task_id

        if self.validator is not None:
            task, val_report = self._validate_with_repair(task)
            if not val_report.ok:
                outcome.failure = (
                    f"validate({val_report.failed_stage}): {val_report.detail}"
                )
                outcome.failed_stage = val_report.failed_stage or "validate"
                return outcome

        # Write into <tasks_root>/<task_id>/. We rename the dir to capability id
        # afterwards so MatrixRunner can locate the bundle by capability_id.
        bundle_dir = self.bundle_writer.write(task, tasks_root)
        target = tasks_root / cap.id
        if bundle_dir != target:
            if target.exists():
                # stale bundle from a previous run — remove and replace
                import shutil
                shutil.rmtree(target)
            bundle_dir.rename(target)
        outcome.bundle_dir = str(target)
        outcome.ok = True
        return outcome

    def _validate_with_repair(
        self, task: GeneratedTask
    ) -> tuple[GeneratedTask, ValidationReport]:
        report = self.validator.validate(task)
        attempts = 0
        while not report.ok and attempts < self.repair_attempts:
            attempts += 1
            try:
                task = self.generator.repair_task(
                    task=task,
                    failed_stage=report.failed_stage,
                    detail=report.detail,
                    logs=(report.stdout or "") + "\n" + (report.stderr or ""),
                )
            except Exception:  # noqa: BLE001 — repair is best-effort
                break
            report = self.validator.validate(task)
        return task, report


__all__ = [
    "CapabilityBuildOutcome",
    "MatrixBatchBuilder",
    "MatrixBatchReport",
]
