"""SkillRunner — execute one task bundle with one skill, score per discriminator.

Pipeline
--------

1. **Workspace prep**: copy the task bundle to a stage dir and rewrite the
   container paths (`/root`, `/tests`, `/logs/verifier`, `/app/workspace`)
   inside test/solve scripts to point at the stage dir.

2. **Executor**: produce ``/root/result.json`` (or whatever ``output_path``
   the task declared). Three modes:

   * ``solution``       — run ``solution/solve.sh`` (oracle / sanity check)
   * ``agent-command``  — run a user-supplied shell command, with paths
                          interpolated via str.format (``{root}``, ``{tests}``,
                          ``{instruction}``, ``{skill}``)
   * ``llm-agent``      — ask the LLM (via ChatClient) for a bash script
                          using the skill description, then run it

3. **Verifier**: run ``tests/test.sh`` (the SkillsBench-standard entrypoint).
   It writes ``ctrf.json`` under ``/logs/verifier`` (stage-mapped). We parse
   that to recover per-TestClass pass/fail, which is exactly the per-discriminator
   pass/fail for combined-task bundles.

What this is NOT
----------------
- No Docker / harbor backend — host execution only.
- No automatic apt-get / pip install of dependencies. The candidate skill
  is expected to install its own deps via its bash script. The validator
  has already proven the test file's imports are satisfiable in the runtime.
- No baseline-gain or assertion-selection logic (those were v1 features
  bound to ProbeArtifact). Per-discriminator pass/fail is the score.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from string import Template
from typing import Any

from dynamic_skill_eval_v2.llm_client import ChatClient

PROMPT_DIR = Path(__file__).parent / "prompts"


# ----------------------------------------------------------------- dataclasses


@dataclass
class DiscriminatorOutcome:
    """One ``TestClass`` (= one discriminator) result inside a combined task."""

    discriminator_id: str
    class_name: str
    passed: bool = False
    tests_total: int = 0
    tests_failed: int = 0
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "discriminator_id": self.discriminator_id,
            "class_name": self.class_name,
            "passed": self.passed,
            "tests_total": self.tests_total,
            "tests_failed": self.tests_failed,
            "detail": self.detail,
        }


@dataclass
class RunResult:
    """One (skill, task) run."""

    task_id: str
    skill_id: str
    mode: str                                 # "solution" | "agent-command" | "llm-agent"
    workspace: str
    executor_passed: bool = False
    executor_failure: str = ""                # short failure_mode string when executor died
    executor_seconds: float = 0.0
    verifier_passed: bool = False             # ALL discriminators passed
    verifier_failure: str = ""
    verifier_seconds: float = 0.0
    discriminators: list[DiscriminatorOutcome] = field(default_factory=list)
    pass_rate: float = 0.0                    # passed_classes / total_classes (or pytest pass/fail for single-test)
    executor_stdout: str = ""
    executor_stderr: str = ""
    verifier_stdout: str = ""
    verifier_stderr: str = ""

    @property
    def passed(self) -> bool:
        return self.executor_passed and self.verifier_passed

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "skill_id": self.skill_id,
            "mode": self.mode,
            "workspace": self.workspace,
            "executor_passed": self.executor_passed,
            "executor_failure": self.executor_failure,
            "executor_seconds": self.executor_seconds,
            "verifier_passed": self.verifier_passed,
            "verifier_failure": self.verifier_failure,
            "verifier_seconds": self.verifier_seconds,
            "discriminators": [d.to_dict() for d in self.discriminators],
            "pass_rate": self.pass_rate,
            "passed": self.passed,
            "executor_stdout_tail": self.executor_stdout[-2000:],
            "executor_stderr_tail": self.executor_stderr[-2000:],
            "verifier_stdout_tail": self.verifier_stdout[-2000:],
            "verifier_stderr_tail": self.verifier_stderr[-2000:],
        }


# ----------------------------------------------------------------- workspace


@dataclass(frozen=True)
class _Workspace:
    root: Path                          # stage root
    task_root: Path                     # stage/task — copy of the bundle
    root_dir: Path                      # stage/root → /root
    tests_dir: Path                     # stage/tests → /tests
    logs_dir: Path                      # stage/logs/verifier → /logs/verifier
    app_workspace: Path                 # stage/app/workspace → /app/workspace
    instruction_path: Path              # stage/instruction.md (rewritten copy)
    skill_path: Path                    # stage/skill.md


# ----------------------------------------------------------------- runner


class SkillRunner:
    """Execute one task bundle against one skill description.

    Args:
        mode: how to drive the executor — see module docstring.
        agent_command: required for mode="agent-command". A shell command
            template with ``{root}/{tests}/{logs}/{app_workspace}/
            {instruction}/{skill}/{task}`` placeholders.
        llm_client: required for mode="llm-agent". A ChatClient (created
            from env vars by default).
        timeout_sec: per-subprocess wall-clock limit.
        work_dir: stage dirs go under here; if None, a fresh tempdir per run.
        keep_workspace: keep stage dirs on disk after the run (for debugging).
        max_agent_tokens: cap on the bash-script generation call (llm-agent mode).
    """

    def __init__(
        self,
        mode: str = "solution",
        agent_command: str | None = None,
        llm_client: ChatClient | None = None,
        timeout_sec: int = 300,
        work_dir: str | Path | None = None,
        keep_workspace: bool = False,
        max_agent_tokens: int = 3000,
    ) -> None:
        if mode not in {"solution", "agent-command", "llm-agent"}:
            raise ValueError(f"unknown mode: {mode!r}")
        if mode == "agent-command" and not agent_command:
            raise ValueError("mode='agent-command' requires agent_command")
        self.mode = mode
        self.agent_command = agent_command
        self.llm_client = llm_client
        self.timeout_sec = timeout_sec
        self.work_dir = Path(work_dir) if work_dir else None
        self.keep_workspace = keep_workspace
        self.max_agent_tokens = max_agent_tokens
        self._llm_system = (PROMPT_DIR / "llm_agent_system.txt").read_text(encoding="utf-8")
        self._llm_user_template = (PROMPT_DIR / "llm_agent_user.txt").read_text(encoding="utf-8")

    # ------------------------------------------------------------------ run

    def run(
        self,
        task_bundle: str | Path,
        skill_id: str = "skill",
        skill_text: str = "",
    ) -> RunResult:
        task_bundle = Path(task_bundle).resolve()
        if not task_bundle.is_dir():
            raise FileNotFoundError(f"task bundle not found: {task_bundle}")
        task_id = task_bundle.name
        workspace = self._prepare_workspace(task_bundle, skill_id, task_id, skill_text)
        result = RunResult(
            task_id=task_id,
            skill_id=skill_id,
            mode=self.mode,
            workspace=str(workspace.root),
        )
        try:
            self._execute(workspace, result, skill_text=skill_text)
            if result.executor_passed:
                self._verify(workspace, result)
        finally:
            if not self.keep_workspace:
                shutil.rmtree(workspace.root, ignore_errors=True)
        return result

    # -------------------------------------------------------- workspace prep

    def _prepare_workspace(
        self,
        bundle: Path,
        skill_id: str,
        task_id: str,
        skill_text: str,
    ) -> _Workspace:
        if self.work_dir is not None:
            self.work_dir.mkdir(parents=True, exist_ok=True)
            stage = self.work_dir / f"{_safe(skill_id)}__{_safe(task_id)}"
            if stage.exists():
                shutil.rmtree(stage)
            stage.mkdir(parents=True)
        else:
            stage = Path(tempfile.mkdtemp(prefix=f"taskrun-{_safe(skill_id)}-{_safe(task_id)}-"))

        task_root = stage / "task"
        root_dir = stage / "root"
        tests_dir = stage / "tests"
        logs_dir = stage / "logs" / "verifier"
        app_workspace = stage / "app" / "workspace"
        for path in (root_dir, tests_dir, logs_dir, app_workspace):
            path.mkdir(parents=True, exist_ok=True)

        shutil.copytree(bundle, task_root)

        # populate /root and /tests from the task bundle
        env_src = task_root / "environment"
        if env_src.is_dir():
            for child in env_src.iterdir():
                if child.name == "Dockerfile":
                    continue
                target = root_dir / child.name
                if child.is_dir():
                    shutil.copytree(child, target, dirs_exist_ok=True)
                else:
                    shutil.copy2(child, target)

        tests_src = task_root / "tests"
        if tests_src.is_dir():
            shutil.copytree(tests_src, tests_dir, dirs_exist_ok=True)

        mapping = self._path_map(root_dir, tests_dir, logs_dir, app_workspace)
        self._rewrite_tree(tests_dir, mapping)
        # solve.sh is rewritten as part of execution if mode == "solution"

        instruction_path = stage / "instruction.md"
        instruction_src = task_root / "instruction.md"
        instruction_text = (
            instruction_src.read_text(encoding="utf-8", errors="replace")
            if instruction_src.exists()
            else ""
        )
        instruction_path.write_text(
            self._rewrite_paths(instruction_text, mapping) + "\n",
            encoding="utf-8",
        )

        skill_path = stage / "skill.md"
        skill_path.write_text(skill_text or "", encoding="utf-8")

        return _Workspace(
            root=stage,
            task_root=task_root,
            root_dir=root_dir,
            tests_dir=tests_dir,
            logs_dir=logs_dir,
            app_workspace=app_workspace,
            instruction_path=instruction_path,
            skill_path=skill_path,
        )

    # ----------------------------------------------------------- executor

    def _execute(self, ws: _Workspace, result: RunResult, skill_text: str) -> None:
        started = time.time()
        if self.mode == "solution":
            proc = self._exec_solution(ws)
        elif self.mode == "agent-command":
            proc = self._exec_agent_command(ws)
        elif self.mode == "llm-agent":
            proc = self._exec_llm_agent(ws, skill_text=skill_text)
        else:  # pragma: no cover — guarded in __init__
            raise AssertionError(f"unreachable mode: {self.mode}")
        result.executor_seconds = round(time.time() - started, 3)
        result.executor_stdout = proc.get("stdout", "")
        result.executor_stderr = proc.get("stderr", "")
        result.executor_passed = bool(proc.get("passed"))
        if not result.executor_passed:
            result.executor_failure = str(proc.get("failure_mode") or "executor_failed")

    def _exec_solution(self, ws: _Workspace) -> dict[str, Any]:
        solve_sh = ws.task_root / "solution" / "solve.sh"
        if not solve_sh.exists():
            return {"passed": False, "failure_mode": "missing_solution_script"}
        rewritten = self._rewrite_paths(
            solve_sh.read_text(encoding="utf-8", errors="replace"),
            self._workspace_map(ws),
        )
        # Also rewrite solution.py if it exists — the script invokes it as
        # `python3 /solution/solution.py` which doesn't go through our mapping.
        solution_py_src = ws.task_root / "solution" / "solution.py"
        if solution_py_src.exists():
            staged_solution_py = ws.root / "solution.py"
            staged_solution_py.write_text(
                self._rewrite_paths(
                    solution_py_src.read_text(encoding="utf-8", errors="replace"),
                    self._workspace_map(ws),
                ),
                encoding="utf-8",
            )
            # Patch the path inside solve.sh too.
            rewritten = rewritten.replace(
                "/solution/solution.py",
                str(staged_solution_py),
            )
        script = ws.root / "_solution.sh"
        script.write_text(rewritten, encoding="utf-8")
        script.chmod(0o755)
        return self._run_shell(
            ["bash", str(script)],
            cwd=ws.root_dir,
            env=self._env(ws),
        )

    def _exec_agent_command(self, ws: _Workspace) -> dict[str, Any]:
        try:
            command = self.agent_command.format(
                workspace=ws.root,
                root=ws.root_dir,
                tests=ws.tests_dir,
                logs=ws.logs_dir,
                app_workspace=ws.app_workspace,
                instruction=ws.instruction_path,
                skill=ws.skill_path,
                task=ws.task_root,
            )
        except KeyError as exc:
            return {
                "passed": False,
                "failure_mode": "agent_command_unknown_placeholder",
                "stderr": f"unknown placeholder in agent_command: {exc}",
            }
        return self._run_shell(
            command,
            cwd=ws.root_dir,
            env=self._env(ws),
            shell=True,
        )

    def _exec_llm_agent(self, ws: _Workspace, skill_text: str) -> dict[str, Any]:
        client = self.llm_client or ChatClient(timeout_sec=self.timeout_sec)
        if not client.available:
            return {
                "passed": False,
                "failure_mode": "llm_client_unconfigured",
                "stderr": "ChatClient missing api_key/base_url/model (env: OPENAI_*/ANTHROPIC_*).",
            }
        task_instruction = ws.instruction_path.read_text(encoding="utf-8", errors="replace")
        user = Template(self._llm_user_template).safe_substitute(
            root_dir=str(ws.root_dir),
            tests_dir=str(ws.tests_dir),
            logs_dir=str(ws.logs_dir),
            app_workspace=str(ws.app_workspace),
            instruction_path=str(ws.instruction_path),
            skill_path=str(ws.skill_path),
            skill_text=skill_text[:8000],
            task_instruction=task_instruction[:8000],
        )
        try:
            text = client.chat(
                system=self._llm_system,
                user=user,
                max_tokens=self.max_agent_tokens,
                temperature=0.1,
            )
        except Exception as exc:  # noqa: BLE001 — LLM failure shouldn't crash the run
            return {
                "passed": False,
                "failure_mode": "llm_agent_generation_failed",
                "stderr": f"{type(exc).__name__}: {exc}",
            }
        script = ws.root / "_agent.sh"
        script.write_text(_extract_bash(text), encoding="utf-8")
        script.chmod(0o755)
        return self._run_shell(
            ["bash", str(script)],
            cwd=ws.root_dir,
            env=self._env(ws),
        )

    # ---------------------------------------------------------- verifier

    def _verify(self, ws: _Workspace, result: RunResult) -> None:
        test_sh = ws.tests_dir / "test.sh"
        if not test_sh.exists():
            result.verifier_failure = "missing_test_sh"
            return
        test_sh.chmod(0o755)
        started = time.time()
        proc = self._run_shell(
            ["bash", str(test_sh)],
            cwd=ws.root_dir,
            env=self._env(ws),
        )
        result.verifier_seconds = round(time.time() - started, 3)
        result.verifier_stdout = proc.get("stdout", "")
        result.verifier_stderr = proc.get("stderr", "")
        # test.sh is wired to ALWAYS exit 0 (the SkillsBench standard);
        # the real signal lives in ctrf.json under /logs/verifier.
        ctrf_path = ws.logs_dir / "ctrf.json"
        outcomes = _parse_ctrf(ctrf_path)
        result.discriminators = outcomes
        if not outcomes:
            # Fall back to test.sh's exit code (covers single-class / pure pytest tasks).
            result.verifier_passed = proc.get("passed", False)
            result.pass_rate = 1.0 if result.verifier_passed else 0.0
            if not result.verifier_passed:
                result.verifier_failure = (
                    "no_ctrf_and_test_sh_nonzero"
                    if proc.get("passed") is False
                    else "no_ctrf_output"
                )
            return
        passed_classes = sum(1 for o in outcomes if o.passed)
        result.pass_rate = round(passed_classes / len(outcomes), 4)
        result.verifier_passed = passed_classes == len(outcomes)
        if not result.verifier_passed:
            failed = [o.class_name for o in outcomes if not o.passed]
            result.verifier_failure = (
                f"{len(failed)}/{len(outcomes)} discriminator classes failed: "
                f"{', '.join(failed[:5])}"
            )

    # ----------------------------------------------------------- helpers

    def _run_shell(
        self,
        command: str | list[str],
        cwd: Path,
        env: dict[str, str],
        shell: bool = False,
    ) -> dict[str, Any]:
        started = time.time()
        try:
            completed = subprocess.run(
                command,
                cwd=str(cwd),
                env=env,
                shell=shell,
                text=True,
                capture_output=True,
                timeout=self.timeout_sec,
            )
        except subprocess.TimeoutExpired as exc:
            return {
                "passed": False,
                "failure_mode": "timeout",
                "seconds": round(time.time() - started, 3),
                "stdout": (exc.stdout or "") if isinstance(exc.stdout, str) else "",
                "stderr": (exc.stderr or "") if isinstance(exc.stderr, str) else "",
            }
        return {
            "passed": completed.returncode == 0,
            "returncode": completed.returncode,
            "seconds": round(time.time() - started, 3),
            "stdout": completed.stdout or "",
            "stderr": completed.stderr or "",
            "failure_mode": "" if completed.returncode == 0 else f"exit_{completed.returncode}",
        }

    def _env(self, ws: _Workspace) -> dict[str, str]:
        env = dict(os.environ)
        env.update(
            {
                "SKILLSBENCH_ROOT": str(ws.root_dir),
                "SKILLSBENCH_TESTS": str(ws.tests_dir),
                "SKILLSBENCH_LOGS": str(ws.logs_dir),
                "APP_WORKSPACE": str(ws.app_workspace),
                "TASK_DIR": str(ws.task_root),
                "INSTRUCTION_PATH": str(ws.instruction_path),
                "SKILL_PATH": str(ws.skill_path),
                "PYTHONUNBUFFERED": "1",
            }
        )
        return env

    def _workspace_map(self, ws: _Workspace) -> dict[str, str]:
        return self._path_map(ws.root_dir, ws.tests_dir, ws.logs_dir, ws.app_workspace)

    @staticmethod
    def _path_map(
        root_dir: Path,
        tests_dir: Path,
        logs_dir: Path,
        app_workspace: Path,
    ) -> dict[str, str]:
        # Order matters: /logs/verifier must be replaced before /logs would be
        # if we ever added it, and /app/workspace before /app.
        return {
            "/logs/verifier": str(logs_dir),
            "/app/workspace": str(app_workspace),
            "/tests": str(tests_dir),
            "/root": str(root_dir),
        }

    def _rewrite_tree(self, root: Path, mapping: dict[str, str]) -> None:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in {".py", ".sh", ".md", ".txt", ".json"}:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            path.write_text(self._rewrite_paths(text, mapping), encoding="utf-8")

    @staticmethod
    def _rewrite_paths(text: str, mapping: dict[str, str]) -> str:
        for source, target in mapping.items():
            text = text.replace(source, target)
        return text


# ----------------------------------------------------------- module helpers


def _safe(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", name).strip("-") or "unknown"


def _extract_bash(content: str) -> str:
    """Pull the bash script out of an LLM response.

    Accepts a fenced ```bash …``` block, or a fenced ``` … ``` block, or
    raw text (assumed to already be a script).
    """
    match = re.search(r"```(?:bash|sh)?\s*(.*?)```", content, flags=re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip() + "\n"
    return content.strip() + "\n"


def _parse_ctrf(ctrf_path: Path) -> list[DiscriminatorOutcome]:
    """Parse the ``ctrf.json`` pytest report into per-TestClass outcomes.

    pytest-json-ctrf entry shape::

        {"name": "test_outputs.py::TestFormatPreservation::test_foo",
         "status": "passed" | "failed" | "skipped" | "broken" | ...,
         ...}

    We extract the **middle** ``::`` segment as the test class — that matches
    the ``class_name`` field on ``DiscriminatorTest`` for combined tasks
    (one class per discriminator). Free-function tests (``test_foo`` at
    module top level) fall under a synthetic ``"<module>"`` group so they
    still get a row.
    """
    if not ctrf_path.is_file():
        return []
    try:
        payload = json.loads(ctrf_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    tests = ((payload.get("results") or {}).get("tests") or [])
    if not isinstance(tests, list):
        return []
    grouped: dict[str, dict[str, int]] = {}
    order: list[str] = []
    for entry in tests:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        parts = name.split("::")
        if len(parts) >= 3:
            cls = parts[1]                # test_outputs.py::TestX::test_y
        elif len(parts) == 2:
            cls = "<module>"               # test_outputs.py::test_y  (no class)
        else:
            cls = name or "TestUnknown"
        rec = grouped.setdefault(cls, {"total": 0, "failed": 0})
        if cls not in order:
            order.append(cls)
        rec["total"] += 1
        status = str(entry.get("status") or "").lower()
        # ctrf statuses: passed | failed | skipped | pending | other | broken
        # treat failed/error/broken as a failure; skipped/pending do NOT count
        # toward total (re-decrement) — they shouldn't determine pass/fail.
        if status in {"failed", "error", "broken", "other"}:
            rec["failed"] += 1
        elif status in {"skipped", "pending"}:
            rec["total"] -= 1
    outcomes: list[DiscriminatorOutcome] = []
    for cls in order:
        rec = grouped[cls]
        total = max(0, rec["total"])
        failed = rec["failed"]
        passed = total > 0 and failed == 0
        outcomes.append(
            DiscriminatorOutcome(
                discriminator_id="",          # caller can fill from task.tests if needed
                class_name=cls,
                passed=passed,
                tests_total=total,
                tests_failed=failed,
                detail=(
                    "no tests collected" if total == 0
                    else "" if passed
                    else f"{failed}/{total} failed"
                ),
            )
        )
    return outcomes


__all__ = [
    "DiscriminatorOutcome",
    "RunResult",
    "SkillRunner",
]
