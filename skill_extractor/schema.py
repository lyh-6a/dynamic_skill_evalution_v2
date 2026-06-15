"""Typed dataclasses for SKILL.md extraction output.

The schema is designed to be the *single contract* between extraction and
downstream consumers (capability node builder, scenario enumerator, probe
synthesizer). Keep it stable; add fields with defaults rather than breaking
existing ones.

Schema version is exposed via ``SCHEMA_VERSION``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = "skill-extractor-v1"

# Controlled vocabularies. The LLM is asked to use these, but unknown values
# pass through with no error — we report them in ``extractor_meta.warnings``
# so callers can decide what to do.
KNOWN_ACTIONS: frozenset[str] = frozenset(
    {"READ", "WRITE", "TRANSFORM", "INFER", "VALIDATE", "CALL_TOOL", "COMPARE", "SELECT"}
)
KNOWN_LEVELS: frozenset[str] = frozenset({"fine", "coarse"})
KNOWN_SOURCES: frozenset[str] = frozenset({"explicit", "inferred"})


# ---------------------------------------------------------------- Evidence


@dataclass
class Evidence:
    """A single statement extracted from SKILL.md with provenance.

    ``source`` is ``"explicit"`` when ``text`` is grounded in the source
    document (and ``evidence`` should be a ``SKILL.md:<line>`` pointer), or
    ``"inferred"`` when the extractor judged the value to be implied but
    not literally present.
    """

    text: str
    source: str = "explicit"
    evidence: str = ""

    @classmethod
    def from_any(cls, value: Any) -> "Evidence":
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            return cls(text=value.strip())
        if isinstance(value, dict):
            return cls(
                text=str(value.get("text", "")).strip(),
                source=str(value.get("source", "explicit")).strip() or "explicit",
                evidence=str(value.get("evidence", "")).strip(),
            )
        raise TypeError(f"Cannot build Evidence from {type(value).__name__}: {value!r}")

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "source": self.source, "evidence": self.evidence}


# ------------------------------------------------------------ Variation axis


@dataclass
class VariationAxis:
    """A dimension along which this capability is used in different ways.

    ``values`` enumerates the variants the extractor saw (or could reasonably
    plan to test); ``default`` must be one of them.
    """

    axis: str
    values: list[str] = field(default_factory=list)
    default: str = ""

    @classmethod
    def from_any(cls, value: Any) -> "VariationAxis":
        if isinstance(value, cls):
            return value
        if isinstance(value, dict):
            values = [str(v).strip() for v in value.get("values", []) if str(v).strip()]
            default = str(value.get("default", "")).strip()
            if not default and values:
                default = values[0]
            return cls(
                axis=str(value.get("axis", "")).strip(),
                values=values,
                default=default,
            )
        raise TypeError(f"Cannot build VariationAxis from {type(value).__name__}: {value!r}")

    def to_dict(self) -> dict[str, Any]:
        return {"axis": self.axis, "values": list(self.values), "default": self.default}


# ----------------------------------------------------------- Success criteria


@dataclass
class SuccessCriteria:
    """Output-side judges, split by whether they can drive a deterministic
    verifier today.

    ``structural`` criteria map ~1:1 to verifier checks
    (file_exists / json_exact / file_count / schema_match …).

    ``semantic`` criteria are NL judges intended for LLM-judge auxiliaries.
    Downstream code is expected to weight ``structural`` higher.
    """

    structural: list[Evidence] = field(default_factory=list)
    semantic: list[Evidence] = field(default_factory=list)

    @classmethod
    def from_any(cls, value: Any) -> "SuccessCriteria":
        if isinstance(value, cls):
            return value
        if value in (None, ""):
            return cls()
        if isinstance(value, dict):
            return cls(
                structural=[Evidence.from_any(v) for v in value.get("structural", []) or []],
                semantic=[Evidence.from_any(v) for v in value.get("semantic", []) or []],
            )
        # Backward-compatible flat list: treat all items as semantic.
        if isinstance(value, list):
            return cls(semantic=[Evidence.from_any(v) for v in value])
        raise TypeError(
            f"Cannot build SuccessCriteria from {type(value).__name__}: {value!r}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "structural": [e.to_dict() for e in self.structural],
            "semantic": [e.to_dict() for e in self.semantic],
        }


# -------------------------------------------------------- Capability candidate


@dataclass
class CapabilityCandidate:
    """One fine-grained capability extracted from a single SKILL.md.

    Multiple skills can declare the same ``capability_id`` to indicate that
    they implement the same capability; downstream code merges those.
    """

    capability_id: str
    name: str
    description: str = ""
    matched_terms: list[str] = field(default_factory=list)
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)

    variation_axes: list[VariationAxis] = field(default_factory=list)
    preconditions: list[Evidence] = field(default_factory=list)
    success_criteria: SuccessCriteria = field(default_factory=SuccessCriteria)
    common_failure_modes: list[Evidence] = field(default_factory=list)

    level: str = "fine"

    @classmethod
    def from_any(cls, value: Any) -> "CapabilityCandidate":
        if isinstance(value, cls):
            return value
        if not isinstance(value, dict):
            raise TypeError(
                f"CapabilityCandidate must be a dict, got {type(value).__name__}: {value!r}"
            )
        return cls(
            capability_id=str(value.get("capability_id", "")).strip(),
            name=str(value.get("name", "")).strip(),
            description=str(value.get("description", "")).strip(),
            matched_terms=[str(v).strip() for v in value.get("matched_terms", []) or [] if str(v).strip()],
            inputs=[str(v).strip() for v in value.get("inputs", []) or [] if str(v).strip()],
            outputs=[str(v).strip() for v in value.get("outputs", []) or [] if str(v).strip()],
            actions=[str(v).strip().upper() for v in value.get("actions", []) or [] if str(v).strip()],
            variation_axes=[VariationAxis.from_any(v) for v in value.get("variation_axes", []) or []],
            preconditions=[Evidence.from_any(v) for v in value.get("preconditions", []) or []],
            success_criteria=SuccessCriteria.from_any(value.get("success_criteria")),
            common_failure_modes=[Evidence.from_any(v) for v in value.get("common_failure_modes", []) or []],
            level=str(value.get("level", "fine")).strip().lower() or "fine",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "name": self.name,
            "description": self.description,
            "matched_terms": list(self.matched_terms),
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
            "actions": list(self.actions),
            "variation_axes": [a.to_dict() for a in self.variation_axes],
            "preconditions": [e.to_dict() for e in self.preconditions],
            "success_criteria": self.success_criteria.to_dict(),
            "common_failure_modes": [e.to_dict() for e in self.common_failure_modes],
            "level": self.level,
        }


# ----------------------------------------------------------- Skill scheduling


@dataclass
class SkillScheduling:
    """Skill-level metadata (one per SKILL.md)."""

    skill_name: str = ""
    skill_goal: str = ""
    tags: list[str] = field(default_factory=list)
    expected_inputs: list[str] = field(default_factory=list)
    expected_outputs: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)

    @classmethod
    def from_any(cls, value: Any) -> "SkillScheduling":
        if isinstance(value, cls):
            return value
        if value in (None, ""):
            return cls()
        if not isinstance(value, dict):
            raise TypeError(
                f"SkillScheduling must be a dict, got {type(value).__name__}: {value!r}"
            )
        return cls(
            skill_name=str(value.get("skill_name", "")).strip(),
            skill_goal=str(value.get("skill_goal", "")).strip(),
            tags=[str(v).strip() for v in value.get("tags", []) or [] if str(v).strip()],
            expected_inputs=[str(v).strip() for v in value.get("expected_inputs", []) or [] if str(v).strip()],
            expected_outputs=[str(v).strip() for v in value.get("expected_outputs", []) or [] if str(v).strip()],
            dependencies=[str(v).strip() for v in value.get("dependencies", []) or [] if str(v).strip()],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_name": self.skill_name,
            "skill_goal": self.skill_goal,
            "tags": list(self.tags),
            "expected_inputs": list(self.expected_inputs),
            "expected_outputs": list(self.expected_outputs),
            "dependencies": list(self.dependencies),
        }


# ------------------------------------------------------------- Skill extraction


@dataclass
class SkillExtraction:
    """The full extraction result for one SKILL.md file."""

    skill_id: str
    source_path: str
    scheduling: SkillScheduling = field(default_factory=SkillScheduling)
    capability_candidates: list[CapabilityCandidate] = field(default_factory=list)
    raw_text: str = ""
    extractor_meta: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SkillExtraction":
        return cls(
            skill_id=str(value.get("skill_id", "")).strip(),
            source_path=str(value.get("source_path", "")).strip(),
            scheduling=SkillScheduling.from_any(value.get("scheduling")),
            capability_candidates=[
                CapabilityCandidate.from_any(v)
                for v in value.get("capability_candidates", []) or []
            ],
            raw_text=str(value.get("raw_text", "")),
            extractor_meta=dict(value.get("extractor_meta", {}) or {}),
        )

    def to_dict(self, include_raw_text: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "skill_id": self.skill_id,
            "source_path": self.source_path,
            "scheduling": self.scheduling.to_dict(),
            "capability_candidates": [c.to_dict() for c in self.capability_candidates],
            "extractor_meta": dict(self.extractor_meta),
        }
        if include_raw_text:
            data["raw_text"] = self.raw_text
        return data
