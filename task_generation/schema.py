"""Typed dataclasses for SkillsBench-format task generation.

One ``GeneratedTask`` = one cross-skill task that becomes a single
SkillsBench task directory (task.toml / instruction.md / environment/
/ tests/). The ``candidate_solutions`` field travels alongside as a
sidecar file (not part of the official SkillsBench schema) so our
runner knows which skills to compare on this task.

A task carries everything needed to **self-validate** before it is
materialized: a ``ground_truth`` dict, a ``solution_py`` that turns the
inputs into the expected output, and per-asset ``renderer_py`` scripts
for binary inputs (png / pdf / xlsx). The TaskValidator runs the chain
end-to-end and only valid tasks are written to disk.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = "task-generation-v2"


# ----------------------------------------------------------- Discriminator


@dataclass
class Discriminator:
    """One axis along which the candidate skills are predicted to *differ*.

    Produced by step 1 of the two-step generator (``analyze_discriminators``).
    Step 2 (``generate_from_discriminator``) consumes one of these to author a
    single task whose instruction + tests are pointed directly at this delta.
    """

    id: str                                  # kebab-case, unique within a batch
    axis: str                                # human label of the dimension (e.g. "input_modality")
    description: str = ""                    # one-line summary of the difference
    skill_verdicts: dict[str, str] = field(default_factory=dict)
    # ^ {skill_id: "PASS"|"FAIL"|"PARTIAL — <reason>"} — what the LLM predicts
    test_handle: str = ""                    # how to detect the difference in a test
    rationale: str = ""                      # which extracted fields drove this call

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Discriminator":
        return cls(
            id=str(value.get("id", "")).strip(),
            axis=str(value.get("axis", "")).strip(),
            description=str(value.get("description", "")).strip(),
            skill_verdicts={
                str(k): str(v) for k, v in (value.get("skill_verdicts") or {}).items()
            },
            test_handle=str(value.get("test_handle", "")).strip(),
            rationale=str(value.get("rationale", "")).strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "axis": self.axis,
            "description": self.description,
            "skill_verdicts": dict(self.skill_verdicts),
            "test_handle": self.test_handle,
            "rationale": self.rationale,
        }


# ----------------------------------------------------------- Capability


@dataclass
class Capability:
    """One generic capability axis the matrix-mode evaluator scores skills on.

    Produced by ``analyze_capabilities``. Each capability becomes one column
    in the capability × skill matrix and one task in the per-batch task set.
    The capability spec is the *only* input fed into per-capability task
    generation — the prompt does not see the skill list, which is what makes
    the resulting task skill-set-agnostic and column-comparable.
    """

    id: str                          # kebab-case, unique within batch (e.g. "cap-read-pdf-text")
    name: str                        # human label (e.g. "Read native-text PDF")
    description: str                 # one line: what the ability *is*
    input_shape: str                 # the kind of input the per-capability task will provide
    output_shape: str                # what the agent must produce
    judgement_dimensions: list[str] = field(default_factory=list)
    # ^ high-level axes the task's tests should judge: e.g. ["correctness", "fidelity"]
    skill_ids: list[str] = field(default_factory=list)
    # ^ skills (by skill_id) that declare this capability; drives skill_capability_map

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Capability":
        return cls(
            id=str(value.get("id", "")).strip(),
            name=str(value.get("name", "")).strip(),
            description=str(value.get("description", "")).strip(),
            input_shape=str(value.get("input_shape", "")).strip(),
            output_shape=str(value.get("output_shape", "")).strip(),
            judgement_dimensions=[
                str(x).strip() for x in (value.get("judgement_dimensions") or []) if str(x).strip()
            ],
            skill_ids=[
                str(x).strip() for x in (value.get("skill_ids") or []) if str(x).strip()
            ],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "input_shape": self.input_shape,
            "output_shape": self.output_shape,
            "judgement_dimensions": list(self.judgement_dimensions),
            "skill_ids": list(self.skill_ids),
        }


@dataclass
class CapabilityAnalysis:
    """Output of ``analyze_capabilities``: the frozen capability list + map.

    ``skill_capability_map`` is derived from each capability's ``skill_ids``
    and exposed as a flat ``{skill_id: [capability_id, ...]}`` for direct
    consumption by the matrix runner.
    """

    capabilities: list[Capability] = field(default_factory=list)
    skill_capability_map: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CapabilityAnalysis":
        caps = [Capability.from_dict(c) for c in (value.get("capabilities") or [])]
        # If LLM provided an explicit map, prefer it; else derive from skill_ids.
        raw_map = value.get("skill_capability_map") or {}
        if raw_map:
            mapping: dict[str, list[str]] = {
                str(k): [str(v) for v in (vs or []) if str(v).strip()]
                for k, vs in raw_map.items()
            }
        else:
            mapping = {}
            for cap in caps:
                for sid in cap.skill_ids:
                    mapping.setdefault(sid, []).append(cap.id)
        return cls(capabilities=caps, skill_capability_map=mapping)

    def to_dict(self) -> dict[str, Any]:
        return {
            "capabilities": [c.to_dict() for c in self.capabilities],
            "skill_capability_map": {
                k: list(v) for k, v in self.skill_capability_map.items()
            },
        }


# ----------------------------------------------------------- DiscriminatorTest


@dataclass
class DiscriminatorTest:
    """One pytest **TestClass** inside the combined task's single test file.

    The combined-task path bundles N discriminators into ONE pytest module
    (``tests/test_outputs.py``); each discriminator gets its own
    ``class Test<...>:`` block so per-discriminator pass/fail is reported
    by pytest's collection-level test ids (``classname`` in junit XML,
    ``::ClassName::`` in nodeids).

    The shared module header (imports, helper functions, path constants) is
    carried separately on ``GeneratedTask.tests_header`` so each class can
    stay short and free of boilerplate.
    """

    discriminator_id: str
    class_name: str      # e.g. "TestFormatPreservation" — must start with "Test"
    body: str            # `def test_xxx(self): ...` lines, indented one level

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "DiscriminatorTest":
        cn = str(value.get("class_name", "")).strip()
        # tolerate LLM forgetting the Test prefix
        if cn and not cn.startswith("Test"):
            cn = "Test" + cn[:1].upper() + cn[1:]
        if not cn:
            cn = "TestUnknown"
        # back-compat: older prompts produced {filename, body}; if filename
        # came through, derive a class name from it.
        if value.get("filename") and not value.get("class_name"):
            stem = str(value["filename"]).strip().removesuffix(".py").removeprefix("test_")
            parts = [p.capitalize() for p in stem.replace("-", "_").split("_") if p]
            cn = "Test" + "".join(parts) if parts else "TestUnknown"
        return cls(
            discriminator_id=str(value.get("discriminator_id", "")).strip(),
            class_name=cn,
            body=str(value.get("body", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "discriminator_id": self.discriminator_id,
            "class_name": self.class_name,
            "body": self.body,
        }


# ----------------------------------------------------------- CandidateSolution


@dataclass
class CandidateSolution:
    """One skill that should attempt this task during cross-skill comparison."""

    skill_id: str
    capability_id: str
    approach: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CandidateSolution":
        return cls(
            skill_id=str(value.get("skill_id", "")).strip(),
            capability_id=str(value.get("capability_id", "")).strip(),
            approach=str(value.get("approach", "")).strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "capability_id": self.capability_id,
            "approach": self.approach,
        }


# ----------------------------------------------------------- TaskAsset


@dataclass
class TaskAsset:
    """One file that ends up inside the task's environment/.

    ``kind == "text"``    — ``content`` is the literal file body.
    ``kind == "binary"``  — ``renderer_py`` is a stand-alone Python script
        that, given ``GROUND_TRUTH_PATH`` in env, writes the file to its
        current working directory. The bytes it produces are captured by
        the validator and stored in ``content_bytes`` for later writeout.
    """

    path: str                            # relative to environment/, e.g. "receipt.png"
    kind: str = "text"                   # "text" | "binary"
    content: str = ""                    # text body (kind == "text")
    renderer_py: str = ""                # script body (kind == "binary")
    container_path: str = ""             # absolute path inside Docker, e.g. "/root/receipt.png"
    # populated by the validator for binary assets:
    content_bytes: bytes | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "TaskAsset":
        path = str(value.get("path", "")).strip().lstrip("/")
        kind = str(value.get("kind", "text")).strip().lower() or "text"
        container_path = str(value.get("container_path", "")).strip()
        if not container_path:
            container_path = f"/root/{path}"
        return cls(
            path=path,
            kind=kind,
            content=str(value.get("content", "")),
            renderer_py=str(value.get("renderer_py", "")),
            container_path=container_path,
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "path": self.path,
            "kind": self.kind,
            "container_path": self.container_path,
        }
        if self.kind == "text":
            out["content"] = self.content
        else:
            out["renderer_py"] = self.renderer_py
        return out


# ----------------------------------------------------------- GeneratedTask


@dataclass
class GeneratedTask:
    """One SkillsBench-shaped task plus the cross-skill comparison sidecar."""

    task_id: str
    name: str
    query: str   # the user query that produced this task (provenance)

    candidate_solutions: list[CandidateSolution] = field(default_factory=list)

    instruction_md: str = ""
    assets: list[TaskAsset] = field(default_factory=list)
    tests_py: str = ""                       # body of tests/test_outputs.py (single-test mode)
    task_toml_extras: dict[str, Any] = field(default_factory=dict)

    # --- multi-check (combined-task) payload ---------------------------------
    # Populated by the combined-task generator. When ``tests`` is non-empty,
    # ``tests_py`` is ignored; the bundle writer assembles a single
    # tests/test_outputs.py from ``tests_header`` + each entry's class body.
    # ``discriminators`` are the per-axis discriminators this combined task
    # exercises (parallel to ``tests``).
    tests_header: str = ""                                # shared imports + helpers
    tests: list[DiscriminatorTest] = field(default_factory=list)
    discriminators: list[Discriminator] = field(default_factory=list)

    # --- self-validation payload ---------------------------------------------
    # Structured truth the LLM commits to up front. The renderer scripts read
    # this to produce binary assets; the solution reads asset files (NOT this)
    # to derive the same answer. tests_py asserts on the answer.
    #
    # solution_py has no per-task dependency list — the host validator
    # preinstalls a small library whitelist (PRELOAD_LIBS in validator.py).
    # Per-skill dependencies for the *evaluated agent* come from each skill's
    # own SKILL.md / requirements / *.py and are baked into the per-skill
    # docker image by the runner, not here.
    ground_truth: dict[str, Any] = field(default_factory=dict)
    solution_py: str = ""                # body of solution/solution.py
    output_path: str = "/root/result.json"   # where solution & tests look

    # When produced by the two-step generator, this records which discriminator
    # row this task was derived from. None for one-step (A) outputs.
    discriminator: Discriminator | None = None

    # When produced by the matrix-mode generator (``generate_for_capability``),
    # this is the column id this task scores. Empty in combined / two-step
    # paths. Same-column tasks across a batch are the *same* task — that's the
    # whole point of matrix mode.
    capability_id: str = ""
    capability: Capability | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "GeneratedTask":
        # Back-compat: accept legacy "input_files" key (v1) and promote to assets.
        raw_assets = value.get("assets")
        if raw_assets is None:
            raw_assets = value.get("input_files") or []
        raw_disc = value.get("discriminator")
        raw_cap = value.get("capability")
        raw_tests = value.get("tests") or []
        raw_discs_plural = value.get("discriminators") or []
        return cls(
            task_id=str(value.get("task_id", "")).strip(),
            name=str(value.get("name", "")).strip(),
            query=str(value.get("query", "")).strip(),
            candidate_solutions=[
                CandidateSolution.from_dict(c)
                for c in value.get("candidate_solutions", []) or []
            ],
            instruction_md=str(value.get("instruction_md", "")),
            assets=[TaskAsset.from_dict(f) for f in raw_assets],
            tests_py=str(value.get("tests_py", "")),
            task_toml_extras=dict(value.get("task_toml_extras", {}) or {}),
            ground_truth=dict(value.get("ground_truth", {}) or {}),
            solution_py=str(value.get("solution_py", "")),
            output_path=str(value.get("output_path", "/root/result.json")).strip()
            or "/root/result.json",
            discriminator=Discriminator.from_dict(raw_disc) if raw_disc else None,
            capability_id=str(value.get("capability_id", "")).strip(),
            capability=Capability.from_dict(raw_cap) if raw_cap else None,
            tests_header=str(value.get("tests_header", "")),
            tests=[DiscriminatorTest.from_dict(t) for t in raw_tests],
            discriminators=[Discriminator.from_dict(d) for d in raw_discs_plural],
        )

    def to_dict(self) -> dict[str, Any]:
        out = {
            "task_id": self.task_id,
            "name": self.name,
            "query": self.query,
            "candidate_solutions": [c.to_dict() for c in self.candidate_solutions],
            "instruction_md": self.instruction_md,
            "assets": [f.to_dict() for f in self.assets],
            "tests_py": self.tests_py,
            "task_toml_extras": dict(self.task_toml_extras),
            "ground_truth": dict(self.ground_truth),
            "solution_py": self.solution_py,
            "output_path": self.output_path,
        }
        if self.discriminator is not None:
            out["discriminator"] = self.discriminator.to_dict()
        if self.capability_id:
            out["capability_id"] = self.capability_id
        if self.capability is not None:
            out["capability"] = self.capability.to_dict()
        if self.tests:
            out["tests"] = [t.to_dict() for t in self.tests]
        if self.tests_header:
            out["tests_header"] = self.tests_header
        if self.discriminators:
            out["discriminators"] = [d.to_dict() for d in self.discriminators]
        return out


# Back-compat alias — old smoke tests may import TaskInputFile.
TaskInputFile = TaskAsset


# ----------------------------------------------------------- TaskBatch


@dataclass
class TaskBatch:
    """The full output of one TaskGenerator.generate() call."""

    query: str = ""
    tasks: list[GeneratedTask] = field(default_factory=list)
    generator_meta: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "TaskBatch":
        return cls(
            query=str(value.get("query", "")),
            tasks=[GeneratedTask.from_dict(t) for t in value.get("tasks", []) or []],
            generator_meta=dict(value.get("generator_meta", {}) or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "query": self.query,
            "tasks": [t.to_dict() for t in self.tasks],
            "generator_meta": dict(self.generator_meta),
        }
