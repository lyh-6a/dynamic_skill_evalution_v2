"""HarborSkillRunner — execute a generated task via Harbor's Docker backend.

Why this exists (vs. the local ``SkillRunner``):

The local runner runs the LLM-generated bash script on the host with the
host's own Python/pip available. The LLM cheerfully ``pip install``\\s
whatever library it wants and ignores SKILL.md's declared boundaries.
That makes the evaluation a measure of "what the model can do given
internet + free choice", not "what the skill enables".

Harbor mode fixes that by:

1.  Building **one Docker image per task** from the task's
    ``environment/Dockerfile`` (so the runtime libraries are whatever the
    task author baked in — no surprise installs).
2.  Asking ``harbor run`` to mount the **candidate skill** under
    ``/root/.claude/skills/<skill-name>/`` via Harbor's ``--skill`` flag.
3.  Driving the run with Harbor's ``terminus-2-skills`` agent
    (``HarborTerminus2WithSkills``) — a terminal-interactive agent that
    discovers and loads skills from those mount points and types commands
    into a real shell. The skill block is **injected into every prompt**,
    so the agent literally cannot pretend the skill isn't there.
4.  Reading the task's own ``tests/test.sh`` output (the SkillsBench-standard
    ``ctrf.json`` written under ``/logs/verifier/``) to recover per-TestClass
    pass/fail — same logic as the local runner.

This mirrors the v1 ``dynamic_skill_eval.runners.harbor_execution_runner``
flow, minus the dependency on the v1 ProbeArtifact / StructuredSkill model
and minus the assertion-selector / capability-coalescing machinery.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dynamic_skill_eval_v2.task_runner.runner import DiscriminatorOutcome


# Default container mount path used by HarborTerminus2WithSkills' skill
# loader (see ``harbor_terminus_2_skills._resolve_skill_dirs``). Harbor's
# ``--skill`` flag drops the skill folder under one of these paths.
# We default to the *forced-skills* subclass (see ``forced_skill_agent.py``)
# which pre-loads every discovered skill in setup() so the in-context
# skill block is populated from episode 0 — the evaluated agent literally
# sees the SKILL.md text on its first turn and cannot pretend the skill
# isn't there. To restore the upstream behaviour (lazy load_skill) pass
# ``--agent-import-path libs.terminus_agent.agents.terminus_2.harbor_terminus_2_skills:HarborTerminus2WithSkills``.
DEFAULT_TERMINUS_AGENT = (
    "dynamic_skill_eval_v2.task_runner.forced_skill_agent:HarborTerminus2ForcedSkills"
)


# Auto-derived project roots, prepended to PYTHONPATH for the harbor
# subprocess so the layout-only ``libs.terminus_agent`` and
# ``dynamic_skill_eval_v2`` packages are importable without per-shell
# environment setup. _DYN_SKILL_EVAL_ROOT is the repo root that contains the
# ``dynamic_skill_eval_v2/`` package; _SKILLSBENCH_ROOT contains ``libs/``.
_DYN_SKILL_EVAL_ROOT = Path(__file__).resolve().parents[2]
_SKILLSBENCH_ROOT_CANDIDATES = (
    Path("/home/liuyuhan/yewu/skillbench_atuo_arena"),
)
_SKILLSBENCH_ROOT = next(
    (p for p in _SKILLSBENCH_ROOT_CANDIDATES if (p / "libs" / "terminus_agent").is_dir()),
    None,
)


@dataclass
class HarborRunResult:
    """One (skill, task) trial executed through Harbor."""

    task_id: str
    skill_id: str
    workspace: str
    image_name: str = ""
    image_build_ok: bool = False
    image_build_detail: str = ""
    agent_ok: bool = False
    agent_failure: str = ""
    agent_seconds: float = 0.0
    agent_tokens: int = 0
    verifier_ok: bool = False
    verifier_failure: str = ""
    reward: float = 0.0
    discriminators: list[DiscriminatorOutcome] = field(default_factory=list)
    pass_rate: float = 0.0
    job_dir: str = ""
    harbor_returncode: int | None = None
    harbor_stdout_tail: str = ""

    @property
    def passed(self) -> bool:
        return self.image_build_ok and self.agent_ok and self.verifier_ok

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "skill_id": self.skill_id,
            "passed": self.passed,
            "workspace": self.workspace,
            "image_name": self.image_name,
            "image_build_ok": self.image_build_ok,
            "image_build_detail": self.image_build_detail,
            "agent_ok": self.agent_ok,
            "agent_failure": self.agent_failure,
            "agent_seconds": self.agent_seconds,
            "agent_tokens": self.agent_tokens,
            "verifier_ok": self.verifier_ok,
            "verifier_failure": self.verifier_failure,
            "reward": self.reward,
            "discriminators": [d.to_dict() for d in self.discriminators],
            "pass_rate": self.pass_rate,
            "job_dir": self.job_dir,
            "harbor_returncode": self.harbor_returncode,
            "harbor_stdout_tail": self.harbor_stdout_tail[-4000:],
        }


class HarborSkillRunner:
    """Run a generated task bundle against one skill via Harbor + Docker.

    Args:
        skill_path: Filesystem path to the candidate skill directory (the
            dir that contains SKILL.md). Harbor's ``--skill`` mounts this
            into the container, and the terminus-2 agent's skill_docs
            loader picks it up.
        skill_id: Identifier for logging / result labelling (defaults to
            ``skill_path.name``).
        model: Model name passed to harbor as ``--model``.
        agent_import_path: Defaults to ``HarborTerminus2WithSkills`` so the
            skill block is injected into the agent's system prompt. Override
            only if you have a different skills-aware agent.
        work_dir: Root for staged task copies and harbor job outputs;
            defaults to ``./.dynamic_skill_eval_v2_harbor`` in cwd.
        harbor_command: Name/path of the harbor CLI (default ``harbor``).
        keep_workspace: Don't delete the staged task dir after a run.
        force_build: Pass ``--force-build`` to harbor (rebuild image every
            time). Default false (re-use cached images).
        agent_kwargs: Extra ``--ak key=value`` entries.
        timeout_sec: Wall-clock guard for the whole ``harbor run`` invocation.
    """

    def __init__(
        self,
        skill_path: str | Path,
        skill_id: str | None = None,
        model: str | None = None,
        agent_import_path: str = DEFAULT_TERMINUS_AGENT,
        work_dir: str | Path | None = None,
        harbor_command: str = "harbor",
        keep_workspace: bool = False,
        force_build: bool = False,
        agent_kwargs: dict[str, str] | None = None,
        timeout_sec: int = 1800,
        registry_mirror: str | None = None,
        cleanup_images: bool = True,
        cleanup_base_images: bool = False,
        use_skill_deps: bool = True,
    ) -> None:
        self.skill_path = Path(skill_path).resolve()
        if not self.skill_path.is_dir():
            raise FileNotFoundError(f"skill_path not a directory: {self.skill_path}")
        self.skill_id = skill_id or self.skill_path.name
        self.model = model or os.environ.get("ANTHROPIC_MODEL") or os.environ.get("OPENAI_MODEL")
        self.agent_import_path = agent_import_path
        self.work_dir = Path(work_dir).resolve() if work_dir else Path.cwd() / ".dynamic_skill_eval_v2_harbor"
        self.harbor_command = harbor_command
        self.keep_workspace = keep_workspace
        self.force_build = force_build
        self.agent_kwargs = dict(agent_kwargs or {})
        self.timeout_sec = timeout_sec
        # Registry mirror for pulling base images (e.g. "docker.m.daocloud.io").
        # Pulls "<mirror>/library/ubuntu:24.04" and re-tags it as
        # "ubuntu:24.04" so the task's own Dockerfile (which references the
        # canonical name) sees a cache hit and never hits docker hub.
        self.registry_mirror = (
            registry_mirror
            or os.environ.get("DYN_SKILL_EVAL_REGISTRY_MIRROR")
            or None
        )
        self.cleanup_images = cleanup_images
        self.cleanup_base_images = cleanup_base_images
        self.use_skill_deps = use_skill_deps
        self._image_builds: dict[str, dict[str, Any]] = {}
        # Tracks tags this runner created, for cleanup on exit.
        # task_image -> built by us; base_image -> pulled+retagged by us.
        self._built_task_images: set[str] = set()
        self._pulled_base_images: set[str] = set()

    # ------------------------------------------------------------------ run

    def run(self, task_bundle: str | Path) -> HarborRunResult:
        bundle = Path(task_bundle).resolve()
        if not bundle.is_dir():
            raise FileNotFoundError(f"task bundle not found: {bundle}")
        task_id = _safe(bundle.name)
        result = HarborRunResult(
            task_id=task_id,
            skill_id=_safe(self.skill_id),
            workspace="",
        )

        # 1. preflight: CLIs present
        if shutil.which(self.harbor_command) is None:
            result.agent_failure = f"harbor CLI not found: {self.harbor_command}"
            return result
        if shutil.which("docker") is None:
            result.agent_failure = "docker CLI not found"
            return result

        # 2. stage task bundle (we mutate the staged Dockerfile per-skill, so
        # the build context must be the staged copy, not the original bundle)
        staged = self.work_dir / "_tasks" / f"{result.skill_id}__{task_id}"
        if staged.exists():
            shutil.rmtree(staged)
        shutil.copytree(bundle, staged)
        result.workspace = str(staged)

        # Rewrite the staged Dockerfile's pip-install block to install only
        # the candidate skill's declared dependencies (skill/requirements.txt
        # or skill/scripts/requirements.txt) instead of validator.PRELOAD_LIBS.
        # If the skill has no requirements file we fall back to whatever the
        # bundle was generated with — PRELOAD_LIBS for tasks produced by
        # ``TaskBundleWriter`` — so the runner stays compatible with skills
        # that don't ship a manifest.
        dockerfile_path = staged / "environment" / "Dockerfile"
        skill_deps = self._discover_skill_deps() if self.use_skill_deps else []
        skill_deps_used = False
        if skill_deps and dockerfile_path.is_file():
            if _rewrite_dockerfile_pip(dockerfile_path, skill_deps):
                skill_deps_used = True

        # 3. build (or reuse) per-(task, skill) docker image. The skill_id is
        # part of the cache key + the tag so different skills don't clobber
        # each other's images.
        cache_key = f"{task_id}__{result.skill_id}" if skill_deps_used else task_id
        image_name = _harbor_image_name(cache_key)
        build = self._image_builds.get(cache_key)
        if build is None:
            build = self._build_task_image(staged, task_id, image_name)
            self._image_builds[cache_key] = build
        result.image_name = image_name
        result.image_build_ok = bool(build.get("ok"))
        detail = build.get("detail", "")
        if skill_deps_used:
            detail = f"{detail} [skill-deps: {len(skill_deps)} pkg(s)]"
        result.image_build_detail = detail
        if not result.image_build_ok:
            return result

        _set_task_docker_image(staged / "task.toml", image_name)
        # Pin skills_dir to a path the terminus-2-skills agent actually scans
        # (DEFAULT_SKILL_DIRS in skill_docs.py). Without this harbor uploads to
        # /harbor/skills and the agent finds nothing — "No skills loaded".
        _set_task_skills_dir(staged / "task.toml", AGENT_SKILL_MOUNT_PATH)
        shutil.rmtree(staged / "solution", ignore_errors=True)

        # 4. harbor run
        jobs_dir = self.work_dir / "_jobs"
        jobs_dir.mkdir(parents=True, exist_ok=True)
        job_name = _safe(f"{result.skill_id}-{task_id}-{time.time_ns()}")
        harbor_proc = self._run_harbor(staged, jobs_dir, job_name)
        result.harbor_returncode = harbor_proc.get("returncode")
        result.harbor_stdout_tail = harbor_proc.get("stdout", "")[-8000:]
        result.agent_seconds = harbor_proc.get("seconds", 0.0)

        job_dir = jobs_dir / job_name
        result.job_dir = str(job_dir)
        trial = _load_trial_payload(job_dir / "result.json")
        agent_meta = (trial.get("agent_result") or {}).get("metadata") or {}
        exception = trial.get("exception_info") or {}
        result.agent_tokens = int(((trial.get("agent_result") or {}).get("n_output_tokens") or 0))
        if exception:
            result.agent_failure = str(exception.get("exception_type") or "harbor_agent_exception")
        elif harbor_proc.get("returncode") != 0:
            result.agent_failure = "harbor_returncode_nonzero"
        else:
            result.agent_ok = True

        # 5. verifier results: reward + per-class breakdown from ctrf.json
        result.reward = _reward_from_trial(trial)
        outcomes = _parse_ctrf_in_job(job_dir)
        result.discriminators = outcomes
        if outcomes:
            passed_classes = sum(1 for o in outcomes if o.passed)
            result.pass_rate = round(passed_classes / len(outcomes), 4)
            result.verifier_ok = passed_classes == len(outcomes)
            if not result.verifier_ok:
                failed = [o.class_name for o in outcomes if not o.passed]
                result.verifier_failure = (
                    f"{len(failed)}/{len(outcomes)} discriminator classes failed: "
                    f"{', '.join(failed[:5])}"
                )
        else:
            # Fall back to reward >= 1.0 (the SkillsBench standard)
            result.verifier_ok = result.reward >= 1.0
            result.pass_rate = result.reward
            if not result.verifier_ok and not result.verifier_failure:
                result.verifier_failure = "no_ctrf_and_reward_below_1"

        if not self.keep_workspace:
            shutil.rmtree(staged, ignore_errors=True)
        return result

    # ----------------------------------------------------------- image build

    def _build_task_image(self, bundle: Path, task_id: str, image_name: str) -> dict[str, Any]:
        env_dir = bundle / "environment"
        dockerfile = env_dir / "Dockerfile"
        if not dockerfile.exists():
            return {"ok": False, "detail": f"missing Dockerfile: {dockerfile}"}
        # Pre-pull the base image via the configured registry mirror so
        # `docker build` finds it locally and never reaches docker hub.
        if self.registry_mirror:
            base = _read_dockerfile_base(dockerfile)
            if base:
                pull = self._ensure_base_image(base)
                if not pull["ok"]:
                    return {"ok": False, "detail": pull["detail"], "stdout_tail": pull.get("stdout_tail", "")}
        cmd = ["docker", "build", "--tag", image_name, str(env_dir)]
        proc = _run_streaming(cmd, log_prefix="docker", timeout_sec=self.timeout_sec)
        if proc["returncode"] != 0:
            return {
                "ok": False,
                "detail": f"docker build exited {proc['returncode']}",
                "stdout_tail": proc["stdout"][-4000:],
            }
        self._built_task_images.add(image_name)
        return {"ok": True, "detail": f"built {image_name}"}

    def _ensure_base_image(self, base: str) -> dict[str, Any]:
        """Pull ``base`` through ``self.registry_mirror`` and re-tag it as
        ``base`` locally so subsequent ``docker build``\\s resolve from cache.

        No-op if the image already exists locally.
        """
        if _image_exists_locally(base):
            return {"ok": True, "detail": f"{base} already present"}
        mirrored = _mirror_image_ref(base, self.registry_mirror or "")
        if not mirrored:
            return {"ok": False, "detail": f"cannot rewrite {base!r} for mirror"}
        pull = _run_streaming(
            ["docker", "pull", mirrored],
            log_prefix="docker-pull",
            timeout_sec=self.timeout_sec,
        )
        if pull["returncode"] != 0:
            return {
                "ok": False,
                "detail": f"docker pull {mirrored} exited {pull['returncode']}",
                "stdout_tail": pull["stdout"][-2000:],
            }
        tag = _run_streaming(
            ["docker", "tag", mirrored, base],
            log_prefix="docker-tag",
            timeout_sec=60,
        )
        if tag["returncode"] != 0:
            return {
                "ok": False,
                "detail": f"docker tag {mirrored} {base} exited {tag['returncode']}",
                "stdout_tail": tag["stdout"][-2000:],
            }
        # Remove the mirrored tag (the canonical tag now points to the same
        # image, so the layers stay cached). Best-effort.
        _run_streaming(
            ["docker", "rmi", mirrored],
            log_prefix="docker-rmi",
            timeout_sec=60,
        )
        self._pulled_base_images.add(base)
        return {"ok": True, "detail": f"pulled {mirrored} -> {base}"}

    # ------------------------------------------------------------ skill deps

    def _discover_skill_deps(self) -> list[str]:
        """Read the candidate skill's pip requirements, if any.

        Search order:
            <skill>/requirements.txt
            <skill>/scripts/requirements.txt

        Returns the list of non-comment, non-blank requirement specifiers
        found in the first file that exists, or [] if no manifest is present.
        """
        for rel in ("requirements.txt", "scripts/requirements.txt"):
            candidate = self.skill_path / rel
            if candidate.is_file():
                return _parse_requirements(candidate)
        return []

    # --------------------------------------------------------------- cleanup

    def cleanup(self) -> None:
        """Remove every docker image this runner created.

        Always removes task images (built per-task, cheap to rebuild). Only
        removes base images when ``cleanup_base_images=True`` — otherwise the
        base layers stay cached for the next run.
        """
        if self.cleanup_images:
            for image in sorted(self._built_task_images):
                _run_streaming(
                    ["docker", "rmi", "-f", image],
                    log_prefix="docker-rmi",
                    timeout_sec=60,
                )
            self._built_task_images.clear()
            self._image_builds.clear()
        if self.cleanup_base_images:
            for image in sorted(self._pulled_base_images):
                _run_streaming(
                    ["docker", "rmi", "-f", image],
                    log_prefix="docker-rmi",
                    timeout_sec=60,
                )
            self._pulled_base_images.clear()

    def __enter__(self) -> "HarborSkillRunner":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.cleanup()

    # ------------------------------------------------------------ harbor run

    def _run_harbor(
        self,
        staged_task: Path,
        jobs_dir: Path,
        job_name: str,
    ) -> dict[str, Any]:
        cmd: list[str] = [
            self.harbor_command,
            "run",
            "--yes",
            "--path", str(staged_task),
            "--env", "docker",
            "--jobs-dir", str(jobs_dir),
            "--job-name", job_name,
            "--n-attempts", "1",
            "--n-concurrent", "1",
            "--max-retries", "0",
            "--no-delete",
            "--agent-import-path", self.agent_import_path,
            "--skill", str(self.skill_path),
        ]
        if not self.force_build:
            cmd.append("--no-force-build")
        if self.model:
            cmd.extend(["--model", self.model])
        for key, value in self.agent_kwargs.items():
            cmd.extend(["--ak", f"{key}={value}"])
        env = dict(os.environ)
        # Ensure the harbor subprocess can import:
        #   - libs.terminus_agent (HarborTerminus2WithSkills)
        #   - dynamic_skill_eval_v2 (HarborTerminus2ForcedSkills subclass)
        # Both are layout-only sources, not pip-installed.
        existing = env.get("PYTHONPATH", "")
        extras = [str(p) for p in (_DYN_SKILL_EVAL_ROOT, _SKILLSBENCH_ROOT) if p]
        parts = [p for p in extras if p not in existing.split(os.pathsep)]
        if parts:
            env["PYTHONPATH"] = (
                os.pathsep.join(parts) + (os.pathsep + existing if existing else "")
            )
        return _run_streaming(cmd, log_prefix="harbor", env=env, timeout_sec=self.timeout_sec)


# ---------------------------------------------------------- module helpers


def _safe(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", name).strip("-") or "unknown"


_FROM_RE = re.compile(r"^\s*FROM\s+(?:--platform=\S+\s+)?([^\s]+)(?:\s+AS\s+\S+)?\s*$", re.IGNORECASE)


def _read_dockerfile_base(dockerfile: Path) -> str | None:
    """Return the first ``FROM`` image reference, or None if not found."""
    try:
        text = dockerfile.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line:
            continue
        m = _FROM_RE.match(line)
        if m:
            ref = m.group(1).strip()
            # "scratch" doesn't need to be pulled.
            if ref.lower() == "scratch":
                return None
            return ref
    return None


def _image_exists_locally(image: str) -> bool:
    proc = subprocess.run(
        ["docker", "image", "inspect", image],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return proc.returncode == 0


def _mirror_image_ref(image: str, mirror: str) -> str | None:
    """Rewrite ``image`` to pull from ``mirror`` instead of its default registry.

    Examples (with mirror=``docker.m.daocloud.io``):
        ``ubuntu:24.04``                  -> ``docker.m.daocloud.io/library/ubuntu:24.04``
        ``library/ubuntu:24.04``          -> ``docker.m.daocloud.io/library/ubuntu:24.04``
        ``docker.io/library/ubuntu:24.04``-> ``docker.m.daocloud.io/library/ubuntu:24.04``
        ``ghcr.io/foo/bar:1``             -> unchanged (mirror only fronts docker.io)
        ``myhost.local:5000/x:1``         -> unchanged (already a custom registry)
    """
    if not mirror:
        return None
    mirror = mirror.rstrip("/")
    # Strip any tag/digest, keep for re-attachment.
    head, sep, tail = image.partition("@")  # digest
    if sep:
        suffix = "@" + tail
        ref = head
    else:
        ref = head
        suffix = ""
    if not suffix:
        # tag form
        if ":" in ref.rsplit("/", 1)[-1]:
            base, tag = ref.rsplit(":", 1)
            suffix = ":" + tag
            ref = base
    parts = ref.split("/")
    # custom registry already present (host has a dot, colon, or is localhost)
    if len(parts) >= 2 and ("." in parts[0] or ":" in parts[0] or parts[0] == "localhost"):
        if parts[0] in {"docker.io", "registry-1.docker.io", "index.docker.io"}:
            tail_path = "/".join(parts[1:]) or "library"
            return f"{mirror}/{tail_path}{suffix}"
        # Different registry — mirror doesn't apply.
        return None
    # Bare name (docker.io implied).
    if len(parts) == 1:
        return f"{mirror}/library/{parts[0]}{suffix}"
    return f"{mirror}/{ref}{suffix}"


# Mount path inside the container where skills must land so the
# HarborTerminus2WithSkills agent (via SkillDocLoader) can discover them.
# Must match one of the DEFAULT_SKILL_DIRS paths in skill_docs.py.
AGENT_SKILL_MOUNT_PATH = "/root/.claude/skills"


def _set_task_skills_dir(task_toml: Path, skills_dir: str) -> None:
    """Ensure ``[environment].skills_dir`` is set in ``task.toml`` so Harbor
    uploads injected skills to the path the agent actually scans.
    """
    text = task_toml.read_text(encoding="utf-8") if task_toml.exists() else ""
    lines = text.splitlines()
    marker = "[environment]"
    env_start = next((i for i, ln in enumerate(lines) if ln.strip() == marker), None)
    setting = f'skills_dir = "{skills_dir}"'
    if env_start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend([marker, setting])
    else:
        env_end = next(
            (i for i in range(env_start + 1, len(lines)) if lines[i].strip().startswith("[")),
            len(lines),
        )
        existing = next(
            (
                i
                for i in range(env_start + 1, env_end)
                if re.match(r"^\s*skills_dir\s*=", lines[i])
            ),
            None,
        )
        if existing is None:
            lines.insert(env_start + 1, setting)
        else:
            lines[existing] = setting
    task_toml.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _harbor_image_name(task_id: str) -> str:
    name = f"hb__{task_id}".lower()
    if not re.match(r"^[a-z0-9]", name):
        name = "0" + name
    return re.sub(r"[^a-z0-9._-]", "-", name)


def _parse_requirements(req_path: Path) -> list[str]:
    """Read a ``requirements.txt`` file → list of requirement specifiers.

    Strips blank lines, comments, and inline ``# ...`` trailers. Lines that
    start with ``-r``/``-c``/``--`` are skipped (we don't support recursive
    requirement files in skill manifests).
    """
    deps: list[str] = []
    try:
        text = req_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return deps
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-") or line.startswith("--"):
            continue
        deps.append(line)
    return deps


# Match the pip block emitted by TaskBundleWriter's Dockerfile template:
#
#     RUN pip3 install --no-cache-dir --break-system-packages \
#         --index-url https://pypi.tuna.tsinghua.edu.cn/simple \
#         pypdf \
#         pdfplumber \
#         ...
#         Pillow
#
# The continuation lines (`\\\n`) carry the package list; we replace the
# whole block — including those continuations — with one that lists the
# skill's declared dependencies instead.
_PIP_BLOCK_RE = re.compile(
    r"^RUN\s+pip3[^\n]*\\\n(?:\s+[^\n]*\\\n)*\s+[^\\\n]+",
    re.MULTILINE,
)


def _rewrite_dockerfile_pip(dockerfile: Path, skill_deps: list[str]) -> bool:
    """Merge ``skill_deps`` into the existing ``RUN pip3 install ...`` block
    in ``dockerfile``.

    Each skill dep is deduplicated by bare package name (e.g. ``Pillow>=10``
    dedup with ``Pillow`` from the existing list). Skill deps win on version.

    Convenience-only: the agent can still ``pip install`` other packages at
    runtime (the container has network access). Pre-baking skill-declared
    deps just saves it from a needless install step, since the skill author
    has already declared what's required.

    Returns True if a block was rewritten, False otherwise.
    """
    if not skill_deps:
        return False
    try:
        text = dockerfile.read_text(encoding="utf-8")
    except OSError:
        return False
    match = _PIP_BLOCK_RE.search(text)
    if not match:
        return False
    old_block = match.group(0)

    existing = _parse_pip_block_pkgs(old_block)
    merged = _merge_dep_lists(existing, skill_deps)

    index_url_match = re.search(r"--index-url[ \t]+(\S+)", old_block)
    index_flag = (
        f"--index-url {index_url_match.group(1)} \\\n    "
        if index_url_match
        else ""
    )
    dep_lines = " \\\n    ".join(merged)
    new_block = (
        "RUN pip3 install --no-cache-dir --break-system-packages \\\n"
        f"    {index_flag}{dep_lines}"
    )
    dockerfile.write_text(text.replace(old_block, new_block, 1), encoding="utf-8")
    return True


# ------------------------------------------------------ dep-list helpers

_PKG_NAME_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")


def _pkg_key(spec: str) -> str:
    """Extract bare package name from a pip requirement specifier.

    ``Pillow>=10.0.0`` → ``Pillow``
    ``python-docx>=1.0.0`` → ``python-docx``
    ``pdfplumber`` → ``pdfplumber``
    """
    m = _PKG_NAME_RE.match(spec.strip())
    return m.group(1) if m else spec.strip()


def _parse_pip_block_pkgs(block: str) -> list[str]:
    """Extract package specifier lines from a ``RUN pip3 install ...`` block.

    Filters out the RUN header and any ``--flag`` lines, keeping only the
    package requirement lines (continuation ``\\`` is stripped).
    """
    pkgs: list[str] = []
    for raw in block.splitlines():
        line = raw.strip()
        if not line or line.startswith("RUN") or line.startswith("--"):
            continue
        pkgs.append(line.rstrip("\\").strip())
    return pkgs


def _merge_dep_lists(
    existing: list[str],
    additional: list[str],
) -> list[str]:
    """Merge two dep-spec lists by bare package name.

    ``additional`` wins on version when the same package appears in both.
    Order: ``existing`` base, with ``additional`` entries appended (or
    overriding in-place if the key already exists).
    """
    merged: dict[str, str] = {}
    for spec in existing:
        merged[_pkg_key(spec)] = spec
    for spec in additional:
        merged[_pkg_key(spec)] = spec
    return list(merged.values())


def _set_task_docker_image(task_toml: Path, image_name: str) -> None:
    """Pin task.toml's [environment].docker_image to the prebuilt image so
    harbor skips re-building the image from environment/Dockerfile.
    """
    text = task_toml.read_text(encoding="utf-8") if task_toml.exists() else ""
    lines = text.splitlines()
    env_start = next((i for i, ln in enumerate(lines) if ln.strip() == "[environment]"), None)
    setting = f'docker_image = "{image_name}"'
    if env_start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend(["[environment]", setting])
    else:
        env_end = next(
            (i for i in range(env_start + 1, len(lines)) if lines[i].strip().startswith("[")),
            len(lines),
        )
        existing = next(
            (i for i in range(env_start + 1, env_end) if re.match(r"^\s*docker_image\s*=", lines[i])),
            None,
        )
        if existing is None:
            lines.insert(env_start + 1, setting)
        else:
            lines[existing] = setting
    task_toml.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run_streaming(
    cmd: list[str],
    log_prefix: str,
    env: dict[str, str] | None = None,
    timeout_sec: int = 1800,
) -> dict[str, Any]:
    """Run a command, stream its merged stdout/stderr live (for visibility),
    and return ``{returncode, seconds, stdout}``.

    A timeout terminates the process and returns returncode=None.
    """
    started = time.time()
    try:
        proc = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError as exc:
        return {"returncode": 127, "seconds": 0.0, "stdout": f"{exc}\n"}
    chunks: list[str] = []
    assert proc.stdout is not None
    deadline = started + timeout_sec
    try:
        for line in proc.stdout:
            chunks.append(line)
            print(f"[{log_prefix}] {line}", end="", flush=True)
            if time.time() > deadline:
                proc.kill()
                chunks.append(f"\n[{log_prefix}] *** TIMEOUT after {timeout_sec}s, killed\n")
                break
        rc = proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        rc = None
    return {
        "returncode": rc,
        "seconds": round(time.time() - started, 3),
        "stdout": "".join(chunks),
    }


def _load_trial_payload(result_path: Path) -> dict[str, Any]:
    """Load harbor's result.json for a single-trial job. If the top-level
    payload is a job summary, dive into the nested trial result.
    """
    if not result_path.exists():
        return {}
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    trials = payload.get("trial_results") or []
    if trials and isinstance(trials[0], dict):
        return trials[0]
    # Newer harbor versions write per-trial result.json files in
    # subdirectories. Sniff for those.
    for candidate in sorted(result_path.parent.glob("*/result.json")):
        if candidate == result_path:
            continue
        try:
            trial = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(trial, dict) and (
            "verifier_result" in trial
            or "agent_result" in trial
            or "exception_info" in trial
        ):
            return trial
    return payload if isinstance(payload, dict) else {}


def _reward_from_trial(trial: dict[str, Any]) -> float:
    rewards = (trial.get("verifier_result") or {}).get("rewards") or {}
    if not rewards:
        return 0.0
    value = rewards.get("reward")
    if value is None:
        value = next(iter(rewards.values()), 0.0)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _parse_ctrf_in_job(job_dir: Path) -> list[DiscriminatorOutcome]:
    """Walk the job dir for any ``ctrf.json`` and parse per-TestClass results.

    Harbor writes the verifier's ctrf.json at
    ``<job_dir>/<trial_id>/verifier/ctrf.json``.
    """
    candidates = sorted(job_dir.glob("*/verifier/ctrf.json"))
    if not candidates:
        candidates = sorted(job_dir.rglob("ctrf.json"))
    for ctrf_path in candidates:
        outcomes = _parse_ctrf_file(ctrf_path)
        if outcomes:
            return outcomes
    return []


def _parse_ctrf_file(ctrf_path: Path) -> list[DiscriminatorOutcome]:
    """Same shape as ``task_runner.runner._parse_ctrf`` — split out here so
    we don't depend on the local-runner internals."""
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
            cls = parts[1]
        elif len(parts) == 2:
            cls = "<module>"
        else:
            cls = name or "TestUnknown"
        rec = grouped.setdefault(cls, {"total": 0, "failed": 0})
        if cls not in order:
            order.append(cls)
        rec["total"] += 1
        status = str(entry.get("status") or "").lower()
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
                discriminator_id="",
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


__all__ = ["HarborRunResult", "HarborSkillRunner", "DEFAULT_TERMINUS_AGENT"]
