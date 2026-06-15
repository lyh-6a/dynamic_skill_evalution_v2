"""TaskValidator — self-validate a GeneratedTask before materialization.

Pipeline (host-side, no Docker):

    ground_truth.json   ─┐
                         │
    asset.renderer_py  ──┼──►  stage/root/<asset.path>   (text written directly;
                         │                                 binary produced by renderer)
                         │
                         ▼
    solution_py  ──►  stage/root/<output_path>   (e.g. /root/result.json)
                         │
                         ▼
    tests_py  ──►  pytest    PASS  → task ok, binary bytes captured into TaskAsset
                                FAIL  → drop (no bundle written)

Renderer / solution scripts see ``/root/...`` paths via a chroot-style rewrite:
the validator stages everything under ``<stage>/root/`` and rewrites every
literal "/root/" in the scripts and tests to "<stage>/root/" before running.

Each script gets its declared deps installed once into the current Python via
``pip install`` (best-effort, surfaced in the report if it fails).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dynamic_skill_eval_v2.task_generation.schema import GeneratedTask, TaskAsset

# Libraries the validator preinstalls on first use so LLM-authored solutions
# can `import` them without declaring per-task deps. Out-of-scope for the
# evaluated agent — the agent's docker image is built from the candidate skill's
# own dependencies, not these.
PRELOAD_LIBS: tuple[str, ...] = (
    "pypdf",
    "pdfplumber",
    "pdfminer.six",
    "reportlab",
    "python-docx",
    "pytesseract",   # Python wrapper around the `tesseract` binary (apt install tesseract-ocr)
    "Pillow",        # image manipulation; needed by OCR-flavoured solutions to convert PDF pages
)


@dataclass
class ValidationReport:
    task_id: str
    ok: bool = False
    stage_dir: str = ""
    failed_stage: str = ""        # "deps" | "render" | "solution" | "tests"
    detail: str = ""
    stdout: str = ""
    stderr: str = ""
    rendered_assets: list[str] = field(default_factory=list)
    # For combined-task mode (task.tests non-empty): per-discriminator pass/fail.
    # Maps discriminator_id -> {"ok": bool, "detail": str}. Empty for single-test mode.
    per_test_results: dict[str, dict[str, Any]] = field(default_factory=dict)


class TaskValidator:
    """Run renderer → solution → tests for a task. Pure side-effect: in-place
    fills ``asset.content_bytes`` for binary assets, returns a report.

    Args:
        timeout_sec:  per-subprocess timeout
        pip_install:  if False, skip dependency installation (assumes preinstalled)
        keep_stage:   if True, do NOT delete the stage directory after running
    """

    def __init__(
        self,
        timeout_sec: float = 60.0,
        pip_install: bool = True,
        keep_stage: bool = False,
        preload_libs: tuple[str, ...] = PRELOAD_LIBS,
    ) -> None:
        self.timeout_sec = timeout_sec
        self.pip_install = pip_install
        self.keep_stage = keep_stage
        self.preload_libs = preload_libs
        self._installed: set[str] = set()
        self._preloaded = False

    # ---------------------------------------------------------------- public

    def validate(self, task: GeneratedTask) -> ValidationReport:
        report = ValidationReport(task_id=task.task_id)
        stage = Path(tempfile.mkdtemp(prefix=f"taskval-{task.task_id}-"))
        report.stage_dir = str(stage)
        try:
            self._run(task, stage, report)
        finally:
            if report.ok and not self.keep_stage:
                shutil.rmtree(stage, ignore_errors=True)
        return report

    # ---------------------------------------------------------------- driver

    def _run(self, task: GeneratedTask, stage: Path, report: ValidationReport) -> None:
        root_dir = stage / "root"
        root_dir.mkdir(parents=True, exist_ok=True)

        # 1. install deps: preload libs (once per validator).
        #    renderer_py and solution_py both pick from PRELOAD_LIBS; no per-task deps.
        if self.pip_install and not self._preloaded:
            try:
                self._pip_install(list(self.preload_libs))
                self._preloaded = True
            except subprocess.CalledProcessError as e:
                report.failed_stage = "deps"
                report.detail = f"pip install failed: {e}"
                report.stdout = (e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
                report.stderr = (e.stderr or b"").decode("utf-8", "replace") if isinstance(e.stderr, bytes) else (e.stderr or "")
                return

        # 2. ground_truth.json (renderers + solution may both read this)
        gt_path = stage / "ground_truth.json"
        gt_path.write_text(
            json.dumps(task.ground_truth, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 3. assets: text → write; binary → run renderer, capture bytes
        for asset in task.assets:
            dst = root_dir / asset.path.lstrip("/")
            dst.parent.mkdir(parents=True, exist_ok=True)
            if asset.kind == "text":
                dst.write_text(asset.content, encoding="utf-8")
                report.rendered_assets.append(f"{asset.path} (text)")
                continue
            # binary: run renderer_py in stage, expect it to write `dst`
            ok = self._run_renderer(asset, gt_path, dst, stage, report)
            if not ok:
                return
            if not dst.is_file():
                report.failed_stage = "render"
                report.detail = (
                    f"renderer for {asset.path} produced something at {dst} "
                    f"but it is not a regular file (likely a directory) — "
                    f"binary assets must be single files"
                )
                return
            asset.content_bytes = dst.read_bytes()
            report.rendered_assets.append(f"{asset.path} (binary, {len(asset.content_bytes)} B)")

        # 4. run solution_py — should produce file at output_path (rewritten)
        if not task.solution_py.strip():
            report.failed_stage = "solution"
            report.detail = "solution_py is empty"
            return
        ok = self._run_solution(task, stage, root_dir, gt_path, report)
        if not ok:
            return

        # 5. run pytest against tests_py
        ok = self._run_tests(task, stage, root_dir, report)
        if not ok:
            return

        report.ok = True

    # ---------------------------------------------------------------- stages

    def _run_renderer(
        self,
        asset: TaskAsset,
        gt_path: Path,
        dst: Path,
        stage: Path,
        report: ValidationReport,
    ) -> bool:
        script = stage / f"_render_{Path(asset.path).stem}.py"
        # renderer script writes its file to OUTPUT_PATH (env-provided absolute)
        # we also expose GROUND_TRUTH_PATH so it can read the truth
        rewritten = _rewrite_root_paths(asset.renderer_py, root_dir=stage / "root")
        script.write_text(rewritten, encoding="utf-8")
        proc = self._exec(
            [sys.executable, str(script)],
            cwd=stage,
            env_extra={
                "GROUND_TRUTH_PATH": str(gt_path),
                "OUTPUT_PATH": str(dst),
            },
        )
        if proc.returncode != 0 or not dst.exists():
            report.failed_stage = "render"
            report.detail = f"renderer for {asset.path} did not produce file"
            report.stdout = proc.stdout
            report.stderr = proc.stderr
            return False
        return True

    def _run_solution(
        self,
        task: GeneratedTask,
        stage: Path,
        root_dir: Path,
        gt_path: Path,
        report: ValidationReport,
    ) -> bool:
        script = stage / "_solution.py"
        rewritten = _rewrite_root_paths(task.solution_py, root_dir=root_dir)
        script.write_text(rewritten, encoding="utf-8")
        proc = self._exec(
            [sys.executable, str(script)],
            cwd=stage,
            env_extra={"GROUND_TRUTH_PATH": str(gt_path)},
        )
        out_path = _stage_path_for(task.output_path, root_dir)
        if proc.returncode != 0:
            report.failed_stage = "solution"
            report.detail = f"solution_py exited {proc.returncode}"
            report.stdout = proc.stdout
            report.stderr = proc.stderr
            return False
        if not out_path.exists():
            report.failed_stage = "solution"
            report.detail = f"solution did not produce {task.output_path} (looked at {out_path})"
            report.stdout = proc.stdout
            report.stderr = proc.stderr
            return False
        return True

    def _run_tests(
        self,
        task: GeneratedTask,
        stage: Path,
        root_dir: Path,
        report: ValidationReport,
    ) -> bool:
        """Run pytest. Two shapes:

        * Single-file mode (task.tests empty): write tests_py to test_outputs.py,
          run pytest on that one file.
        * Multi-file mode (task.tests non-empty, combined-task path): write each
          test_<...>.py separately, run pytest on each individually so the
          per-discriminator result is independent. report.ok is True iff ALL
          per-test runs pass.
        """
        if task.tests:
            return self._run_tests_multi(task, stage, root_dir, report)

        test_file = stage / "test_outputs.py"
        rewritten = _rewrite_root_paths(task.tests_py, root_dir=root_dir)
        test_file.write_text(rewritten, encoding="utf-8")
        proc = self._exec(
            [sys.executable, "-m", "pytest", "-x", "-q", str(test_file)],
            cwd=stage,
        )
        if proc.returncode != 0:
            report.failed_stage = "tests"
            report.detail = f"pytest exited {proc.returncode}"
            report.stdout = proc.stdout
            report.stderr = proc.stderr
            return False
        return True

    def _run_tests_multi(
        self,
        task: GeneratedTask,
        stage: Path,
        root_dir: Path,
        report: ValidationReport,
    ) -> bool:
        """Combined-task mode: build ONE test_outputs.py from tests_header +
        N TestClasses, run pytest once with junit XML, parse per-class results.
        """
        # 1. assemble single file
        assembled = _assemble_combined_tests(task)
        test_file = stage / "test_outputs.py"
        test_file.write_text(
            _rewrite_root_paths(assembled, root_dir=root_dir),
            encoding="utf-8",
        )
        junit_path = stage / "junit.xml"

        # NOTE: -x removed — we want all classes to run even if one fails.
        proc = self._exec(
            [
                sys.executable, "-m", "pytest", "-q",
                f"--junitxml={junit_path}",
                str(test_file),
            ],
            cwd=stage,
        )

        per_class = _parse_junit_per_class(junit_path)
        # Map class_name -> discriminator_id for the report keys
        class_to_disc = {t.class_name: t.discriminator_id for t in task.tests}
        all_ok = True
        failed: list[str] = []
        for entry in task.tests:
            cls = entry.class_name
            result = per_class.get(cls, {"total": 0, "failures": 0, "errors": 0})
            class_ok = result["total"] > 0 and result["failures"] == 0 and result["errors"] == 0
            key = entry.discriminator_id or cls
            report.per_test_results[key] = {
                "ok": class_ok,
                "class_name": cls,
                "tests_total": result["total"],
                "tests_failed": result["failures"] + result["errors"],
                "detail": (
                    "no tests collected" if result["total"] == 0
                    else "" if class_ok
                    else f"{result['failures']+result['errors']}/{result['total']} failed"
                ),
            }
            if not class_ok:
                all_ok = False
                failed.append(key)
        # pytest may have exited non-zero for reasons unrelated to per-class
        # (e.g. collection error in header) — surface those as overall failure.
        if proc.returncode != 0 and not failed:
            all_ok = False
            failed.append("(collection/global)")
        if not all_ok:
            report.failed_stage = "tests"
            report.detail = (
                f"{len(failed)}/{len(task.tests)} discriminator classes failed: "
                f"{', '.join(failed)} (pytest exit {proc.returncode})"
            )
            report.stdout = proc.stdout
            report.stderr = proc.stderr
            return False
        return True

    # ---------------------------------------------------------------- helpers

    def _exec(
        self,
        cmd: list[str],
        cwd: Path,
        env_extra: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess:
        import os

        env = os.environ.copy()
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            cmd,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=self.timeout_sec,
        )

    def _pip_install(self, deps: list[str]) -> None:
        todo = [d for d in deps if d not in self._installed]
        if not todo:
            return
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", *todo],
            check=True,
            capture_output=True,
            timeout=max(self.timeout_sec, 180.0),
        )
        self._installed.update(todo)


# --------------------------------------------------------------- path rewriter


def _rewrite_root_paths(script: str, root_dir: Path) -> str:
    """Rewrite literal '/root/' occurrences to '<stage>/root/'.

    Renderer / solution / tests are written assuming the container layout
    (/root/...); on the host they need to point at the stage directory.
    """
    target = str(root_dir).rstrip("/") + "/"
    return script.replace("/root/", target)


def _assemble_combined_tests(task: GeneratedTask) -> str:
    """Build the combined test_outputs.py: header + each TestClass.

    Each entry's ``body`` is the class-body lines (already 4-space indented).
    We prepend ``class <name>:`` and a blank line between classes.
    """
    parts: list[str] = []
    header = (task.tests_header or "").rstrip()
    if header:
        parts.append(header + "\n\n")
    for entry in task.tests:
        body = entry.body
        # tolerate LLM forgetting the class-body indent: re-indent any line
        # that starts with `def test_` to 4 spaces.
        body = _ensure_class_indent(body)
        parts.append(f"class {entry.class_name}:\n{body.rstrip()}\n\n")
    return "".join(parts)


def _ensure_class_indent(body: str) -> str:
    """If the LLM emitted `def test_xxx(self):` at column 0, indent each line.

    Heuristic: if any non-blank line starts with `def test_` at col 0 AND no
    line is indented with at least 4 spaces, treat the whole body as flush-left
    and re-indent every non-blank line with 4 spaces.
    """
    lines = body.splitlines()
    has_flush_def = any(ln.startswith("def test_") for ln in lines)
    has_indented = any(ln.startswith(("    ", "\t")) for ln in lines if ln.strip())
    if has_flush_def and not has_indented:
        return "\n".join(("    " + ln if ln.strip() else ln) for ln in lines)
    return body


def _parse_junit_per_class(junit_path: Path) -> dict[str, dict[str, int]]:
    """Parse pytest junit XML → {class_name: {total, failures, errors}}.

    junit-style XML element shapes: <testsuite> > <testcase classname="..."
    name="..." ...><failure/><error/></testcase>. Pytest's classname is
    something like ``test_outputs.TestFormatPreservation`` — we take the
    last dotted segment as the class name.
    """
    import xml.etree.ElementTree as ET

    out: dict[str, dict[str, int]] = {}
    if not junit_path.is_file():
        return out
    try:
        root = ET.parse(junit_path).getroot()
    except ET.ParseError:
        return out
    for tc in root.iter("testcase"):
        classname = (tc.get("classname") or "").strip()
        if not classname:
            continue
        cls = classname.rsplit(".", 1)[-1]
        rec = out.setdefault(cls, {"total": 0, "failures": 0, "errors": 0})
        rec["total"] += 1
        if tc.find("failure") is not None:
            rec["failures"] += 1
        if tc.find("error") is not None:
            rec["errors"] += 1
    return out


def _stage_path_for(container_path: str, root_dir: Path) -> Path:
    container_path = container_path.strip()
    if container_path.startswith("/root/"):
        return root_dir / container_path[len("/root/"):]
    if container_path.startswith("/"):
        return root_dir / container_path.lstrip("/")
    return root_dir / container_path


__all__ = ["TaskValidator", "ValidationReport"]
