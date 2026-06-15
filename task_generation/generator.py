"""TaskGenerator — turn (query, SkillExtraction[]) into GeneratedTask[].

Modes:

* **One-step** (``generate``): single LLM call straight from query + skills
  to finished tasks. Fast, but the LLM tends to author a "median" task
  any candidate skill can pass.

* **Two-step per-discriminator** (``generate_two_step``): step 1 produces
  a *discriminator matrix* (``analyze_discriminators``) — axes on which
  the skills are predicted to actually differ. Step 2 derives one task
  per row, instruction+tests bound to that one delta. Produces N tasks
  that share input shapes — lots of environment duplication.

* **Combined** (``generate_combined``): discriminator matrix → **single**
  task whose ``tests: list[DiscriminatorTest]`` has one pytest file per
  axis, shared environment / assets / solution. Recommended path.
"""

from __future__ import annotations

import json
from pathlib import Path
from string import Template
from typing import Any

from dynamic_skill_eval_v2.llm_client import ChatClient
from dynamic_skill_eval_v2.skill_extractor.schema import SkillExtraction
from dynamic_skill_eval_v2.task_generation.schema import (
    SCHEMA_VERSION,
    Capability,
    CapabilityAnalysis,
    Discriminator,
    DiscriminatorTest,
    GeneratedTask,
)

PROMPT_DIR = Path(__file__).parent / "prompts"
DEFAULT_MAX_TOKENS = 12000


class TaskGenerator:
    """Turn (query, SkillExtraction[]) into GeneratedTask[].

    The constructor takes a chat client + tunables; ``generate`` runs the
    single-call A path, ``generate_two_step`` runs the B path. Both return
    the same ``list[GeneratedTask]`` shape so downstream (validator,
    bundle writer) doesn't care which path produced the tasks.
    """

    def __init__(
        self,
        client: ChatClient,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = 0.2,
        system_prompt: str | None = None,
        user_prompt_template: str | None = None,
        discriminator_prompt_template: str | None = None,
        task_from_discriminator_prompt_template: str | None = None,
        capability_prompt_template: str | None = None,
    ) -> None:
        if client is None:
            raise ValueError("TaskGenerator requires a ChatClient")
        self.client = client
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._system_prompt = (
            system_prompt
            if system_prompt is not None
            else (PROMPT_DIR / "task_system.txt").read_text(encoding="utf-8")
        )
        self._user_prompt_template = (
            user_prompt_template
            if user_prompt_template is not None
            else (PROMPT_DIR / "task_user.txt").read_text(encoding="utf-8")
        )
        self._discriminator_prompt_template = (
            discriminator_prompt_template
            if discriminator_prompt_template is not None
            else (PROMPT_DIR / "discriminator_user.txt").read_text(encoding="utf-8")
        )
        self._task_from_discriminator_prompt_template = (
            task_from_discriminator_prompt_template
            if task_from_discriminator_prompt_template is not None
            else (PROMPT_DIR / "task_from_discriminator_user.txt").read_text(encoding="utf-8")
        )
        self._capability_prompt_template = (
            capability_prompt_template
            if capability_prompt_template is not None
            else (PROMPT_DIR / "capability_analysis_user.txt").read_text(encoding="utf-8")
        )
        self._task_from_capability_prompt_template = (
            PROMPT_DIR / "task_from_capability_user.txt"
        ).read_text(encoding="utf-8")
        self._atom_decomposition_prompt_template = (
            PROMPT_DIR / "atom_decomposition_user.txt"
        ).read_text(encoding="utf-8")
        self._atom_normalization_prompt_template = (
            PROMPT_DIR / "atom_normalization_user.txt"
        ).read_text(encoding="utf-8")
        self._combined_prompt_template = (PROMPT_DIR / "task_combined_user.txt").read_text(encoding="utf-8")
        self._repair_prompt_template = (PROMPT_DIR / "task_repair_user.txt").read_text(encoding="utf-8")
        # cumulative token counter across multi-call workflows (B path)
        self._cum_tokens = 0
        self._last_discriminators: list[Discriminator] = []
        self._last_capability_analysis: CapabilityAnalysis | None = None

    def generate(
        self,
        query: str,
        extractions: list[SkillExtraction],
    ) -> list[GeneratedTask]:
        """One-step (A) generation — single LLM call → tasks."""
        user_prompt = self._render_user_prompt(query, extractions)
        data = self.client.chat_json(
            system=self._system_prompt,
            user=user_prompt,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )
        self._cum_tokens = int(getattr(self.client, "last_usage_tokens", 0) or 0)
        tasks: list[GeneratedTask] = []
        for raw in data.get("tasks", []) or []:
            raw.setdefault("query", query)
            tasks.append(GeneratedTask.from_dict(raw))
        return tasks

    # ---------------------------------------------------------------- two-step

    def generate_two_step(
        self,
        query: str,
        extractions: list[SkillExtraction],
    ) -> list[GeneratedTask]:
        """Two-step (B) generation.

        Step 1: ``analyze_discriminators`` → list of discrimination axes.
        Step 2: for each axis, ``generate_from_discriminator`` → one task
                with instruction + tests bound to that axis.

        Returns the union of step-2 tasks. The discriminator matrix is
        cached on ``self.last_discriminators`` for callers that want to
        surface it in their meta output.
        """
        discs = self.analyze_discriminators(query, extractions)
        self._last_discriminators = discs
        if not discs:
            return []
        tasks: list[GeneratedTask] = []
        for d in discs:
            try:
                t = self.generate_from_discriminator(query, extractions, d)
            except Exception as exc:  # noqa: BLE001 — one flaky LLM call shouldn't sink the batch
                print(
                    f"[two-step] discriminator {d.id!r} failed to produce a task: "
                    f"{type(exc).__name__}: {exc}",
                    flush=True,
                )
                continue
            if t is not None:
                tasks.append(t)
        return tasks

    def analyze_discriminators(
        self,
        query: str,
        extractions: list[SkillExtraction],
    ) -> list[Discriminator]:
        """Step 1 of the two-step generator."""
        skills_payload = [self._compact_extraction(e) for e in extractions]
        prompt = Template(self._discriminator_prompt_template).safe_substitute(
            {
                "query": query.strip(),
                "skills_payload": json.dumps(skills_payload, ensure_ascii=False, indent=2),
            }
        )
        data = self.client.chat_json(
            system=self._system_prompt,
            user=prompt,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )
        self._cum_tokens += int(getattr(self.client, "last_usage_tokens", 0) or 0)
        out: list[Discriminator] = []
        for raw in data.get("discriminators", []) or []:
            d = Discriminator.from_dict(raw)
            if d.id and d.skill_verdicts and len(d.skill_verdicts) >= 2:
                out.append(d)
        return out

    def generate_from_discriminator(
        self,
        query: str,
        extractions: list[SkillExtraction],
        discriminator: Discriminator,
    ) -> GeneratedTask | None:
        """Step 2: write one task driven by a single discriminator row."""
        # narrow skills_payload to only those mentioned in the verdict — keeps
        # the prompt small and prevents the LLM from drifting to other skills
        wanted = set(discriminator.skill_verdicts.keys())
        narrowed = [
            self._compact_extraction(e) for e in extractions if e.skill_id in wanted
        ]
        prompt = Template(self._task_from_discriminator_prompt_template).safe_substitute(
            {
                "query": query.strip(),
                "discriminator": json.dumps(
                    discriminator.to_dict(), ensure_ascii=False, indent=2
                ),
                "skills_payload": json.dumps(narrowed, ensure_ascii=False, indent=2),
            }
        )
        data = self.client.chat_json(
            system=self._system_prompt,
            user=prompt,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )
        self._cum_tokens += int(getattr(self.client, "last_usage_tokens", 0) or 0)
        if "tasks" in data:
            # tolerate a wrapped {"tasks":[{...}]} response shape
            arr = data.get("tasks") or []
            data = arr[0] if arr else {}
        if not data:
            return None
        data.setdefault("query", query)
        task = GeneratedTask.from_dict(data)
        task.discriminator = discriminator
        return task

    def usage_tokens(self) -> int:
        return self._cum_tokens

    # ---------------------------------------------------------------- capabilities (matrix mode)

    # Canonical atom kinds that the decomposition prompt is allowed to emit.
    # If the LLM returns anything else we raise — silent kind drift is exactly
    # what would break cross-skill column alignment.
    _ATOM_KINDS = {
        "READ", "WRITE", "TRANSFORM", "EXTRACT", "INFER",
        "PRESERVE", "COMPARE", "COMPOSE", "VALIDATE",
    }

    def decompose_atoms(
        self,
        query: str,
        extractions: list[SkillExtraction],
    ) -> dict[str, list[dict[str, Any]]]:
        """Stage 1 of two-stage capability clustering.

        Ask the LLM to break each skill's capability_candidates into a set of
        canonically-named atomic operations (READ/WRITE/TRANSFORM/INFER/...).
        Returns ``{skill_id: [atom_dict, ...]}``. The atom dict shape matches
        Capability fields plus a ``kind`` field.

        No fallback: if the LLM returns malformed payload, an unknown skill_id,
        an unknown ``kind``, or an empty atom list for any skill, this raises
        ValueError. Stage-2 merge depends on the ids being canonical, so silent
        recovery here would silently weaken the matrix.
        """
        skills_payload = [self._compact_extraction(e) for e in extractions]
        known_skill_ids = {e.skill_id for e in extractions}
        prompt = Template(self._atom_decomposition_prompt_template).safe_substitute(
            {
                "query": query.strip(),
                "skills_payload": json.dumps(skills_payload, ensure_ascii=False, indent=2),
            }
        )
        data = self.client.chat_json(
            system=self._system_prompt,
            user=prompt,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )
        self._cum_tokens += int(getattr(self.client, "last_usage_tokens", 0) or 0)

        per_skill = data.get("per_skill_atoms") if isinstance(data, dict) else None
        if not isinstance(per_skill, list) or not per_skill:
            raise ValueError(
                f"decompose_atoms: LLM returned no per_skill_atoms. payload={data!r}"
            )

        result: dict[str, list[dict[str, Any]]] = {}
        seen_skill_ids: set[str] = set()
        for entry in per_skill:
            if not isinstance(entry, dict):
                raise ValueError(f"decompose_atoms: per_skill entry is not a dict: {entry!r}")
            sid = str(entry.get("skill_id", "")).strip()
            if not sid:
                raise ValueError(f"decompose_atoms: per_skill entry missing skill_id: {entry!r}")
            if sid not in known_skill_ids:
                raise ValueError(
                    f"decompose_atoms: unknown skill_id {sid!r}; "
                    f"expected one of {sorted(known_skill_ids)}"
                )
            if sid in seen_skill_ids:
                raise ValueError(f"decompose_atoms: duplicate skill_id {sid!r}")
            seen_skill_ids.add(sid)
            atoms_raw = entry.get("atoms") or []
            if not isinstance(atoms_raw, list) or not atoms_raw:
                raise ValueError(
                    f"decompose_atoms: skill {sid!r} produced no atoms"
                )
            atoms_clean: list[dict[str, Any]] = []
            seen_ids_for_skill: set[str] = set()
            for a in atoms_raw:
                if not isinstance(a, dict):
                    raise ValueError(f"decompose_atoms[{sid}]: atom is not a dict: {a!r}")
                aid = str(a.get("id", "")).strip()
                kind = str(a.get("kind", "")).strip().upper()
                if not aid:
                    raise ValueError(f"decompose_atoms[{sid}]: atom missing id: {a!r}")
                if not aid.startswith("cap-"):
                    raise ValueError(
                        f"decompose_atoms[{sid}]: atom id {aid!r} must start with 'cap-'"
                    )
                if kind not in self._ATOM_KINDS:
                    raise ValueError(
                        f"decompose_atoms[{sid}]: atom {aid!r} has invalid kind {kind!r}; "
                        f"allowed: {sorted(self._ATOM_KINDS)}"
                    )
                for f in ("name", "description", "input_shape", "output_shape"):
                    if not str(a.get(f, "")).strip():
                        raise ValueError(
                            f"decompose_atoms[{sid}]: atom {aid!r} missing {f}"
                        )
                jds = a.get("judgement_dimensions") or []
                if not isinstance(jds, list) or len([j for j in jds if str(j).strip()]) < 1:
                    raise ValueError(
                        f"decompose_atoms[{sid}]: atom {aid!r} needs >=1 judgement_dimensions"
                    )
                if aid in seen_ids_for_skill:
                    # collapse silently — same id appearing twice for a skill is a
                    # canonicalisation hit, not a malformed payload
                    continue
                seen_ids_for_skill.add(aid)
                atoms_clean.append({
                    "id": aid,
                    "kind": kind,
                    "name": str(a["name"]).strip(),
                    "description": str(a["description"]).strip(),
                    "input_shape": str(a["input_shape"]).strip(),
                    "output_shape": str(a["output_shape"]).strip(),
                    "judgement_dimensions": [str(j).strip() for j in jds if str(j).strip()],
                })
            result[sid] = atoms_clean

        # Every skill should have shown up; if the LLM dropped one, fail loudly.
        missing = known_skill_ids - seen_skill_ids
        if missing:
            raise ValueError(
                f"decompose_atoms: LLM omitted skills {sorted(missing)}"
            )
        return result

    def analyze_capabilities(
        self,
        query: str,
        extractions: list[SkillExtraction],
        normalize: bool = True,
    ) -> CapabilityAnalysis:
        """Three-stage capability clustering (default).

        Stage 1: ``decompose_atoms`` — LLM breaks each skill's candidates into
            canonical atomic operations.
        Stage 2: mechanical merge — group atoms by id across skills. Each unique
            id becomes one capability column. ``skill_ids`` is the union of skills
            whose atom set contains that id. No further LLM call.
        Stage 3: ``normalize_capabilities`` — second LLM call that scans the
            merged column list and produces an absorb/expand rewrite map for
            semantic duplicates (``cap-read-document`` vs ``cap-read-pdf``).
            Then mechanical apply: rename absorbed ids, re-merge skill_ids.

        Cross-skill consistency check: if two skills both emit id X but with
        conflicting ``kind`` values, raise — that means the LLM canonicalised
        the name without canonicalising the meaning, and merging anyway would
        produce a bogus column.

        Pass ``normalize=False`` to skip stage 3 (saves one LLM call but leaves
        the cap-read-document / cap-read-pdf style duplicates in the matrix).

        Use ``analyze_capabilities_single_stage`` for the legacy single-call
        path (kept for the CLI ``--single-stage`` flag).
        """
        per_skill_atoms = self.decompose_atoms(query, extractions)
        # Stage 2: mechanical merge keyed by atom id.
        merged: dict[str, dict[str, Any]] = {}
        for sid, atoms in per_skill_atoms.items():
            for a in atoms:
                aid = a["id"]
                if aid in merged:
                    existing = merged[aid]
                    if existing["kind"] != a["kind"]:
                        raise ValueError(
                            f"analyze_capabilities: atom id {aid!r} has conflicting kinds "
                            f"across skills: {existing['kind']!r} vs {a['kind']!r}"
                        )
                    if sid not in existing["skill_ids"]:
                        existing["skill_ids"].append(sid)
                    # widen judgement_dimensions union (stable order)
                    for jd in a["judgement_dimensions"]:
                        if jd not in existing["judgement_dimensions"]:
                            existing["judgement_dimensions"].append(jd)
                else:
                    merged[aid] = {
                        "id": aid,
                        "kind": a["kind"],
                        "name": a["name"],
                        "description": a["description"],
                        "input_shape": a["input_shape"],
                        "output_shape": a["output_shape"],
                        "judgement_dimensions": list(a["judgement_dimensions"]),
                        "skill_ids": [sid],
                    }

        if not merged:
            raise ValueError("analyze_capabilities: stage-2 merge produced zero capabilities")

        # Stage 3 (optional): LLM-driven semantic normalization.
        if normalize:
            merged = self._apply_normalization(query=query, merged=merged)

        analysis = self._build_analysis_from_merged(merged)
        self._last_capability_analysis = analysis
        return analysis

    def _build_analysis_from_merged(
        self, merged: dict[str, dict[str, Any]]
    ) -> CapabilityAnalysis:
        """Turn a stage-2 (or stage-3) merged dict into a CapabilityAnalysis.

        Sorts capabilities deterministically by (kind, id). Builds the inverted
        ``skill_capability_map`` from each capability's ``skill_ids``.
        """
        kind_order = {k: i for i, k in enumerate([
            "READ", "EXTRACT", "TRANSFORM", "INFER",
            "PRESERVE", "COMPARE", "COMPOSE", "VALIDATE", "WRITE",
        ])}
        ordered_ids = sorted(
            merged.keys(),
            key=lambda x: (kind_order.get(merged[x]["kind"], 99), x),
        )
        capabilities = [
            Capability(
                id=merged[i]["id"],
                name=merged[i]["name"],
                description=merged[i]["description"],
                input_shape=merged[i]["input_shape"],
                output_shape=merged[i]["output_shape"],
                judgement_dimensions=list(merged[i]["judgement_dimensions"]),
                skill_ids=list(merged[i]["skill_ids"]),
            )
            for i in ordered_ids
        ]
        mapping: dict[str, list[str]] = {}
        for cap in capabilities:
            for sid in cap.skill_ids:
                bucket = mapping.setdefault(sid, [])
                if cap.id not in bucket:
                    bucket.append(cap.id)
        return CapabilityAnalysis(capabilities=capabilities, skill_capability_map=mapping)

    def normalize_capabilities(
        self,
        query: str,
        merged: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Stage 3 LLM call: ask for a list of absorb/expand merges over the
        already-merged capability list. Returns a validated list of merge
        records — does NOT apply them. Pure I/O + validation; the caller (or
        ``_apply_normalization``) does the rewrite.

        No fallback: if the LLM emits a merge that references unknown ids,
        crosses kinds, or self-absorbs, raise ValueError.
        """
        capabilities_payload = [
            {
                "id": v["id"],
                "kind": v["kind"],
                "name": v["name"],
                "description": v["description"],
                "input_shape": v["input_shape"],
                "output_shape": v["output_shape"],
                "skill_ids": list(v["skill_ids"]),
            }
            for v in merged.values()
        ]
        prompt = Template(self._atom_normalization_prompt_template).safe_substitute(
            {
                "query": query.strip(),
                "capabilities_payload": json.dumps(
                    capabilities_payload, ensure_ascii=False, indent=2
                ),
            }
        )
        data = self.client.chat_json(
            system=self._system_prompt,
            user=prompt,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )
        self._cum_tokens += int(getattr(self.client, "last_usage_tokens", 0) or 0)

        if not isinstance(data, dict) or "merges" not in data:
            raise ValueError(
                f"normalize_capabilities: LLM payload missing 'merges' key. payload={data!r}"
            )
        raw_merges = data.get("merges") or []
        if not isinstance(raw_merges, list):
            raise ValueError(
                f"normalize_capabilities: 'merges' is not a list: {raw_merges!r}"
            )

        known_ids = set(merged.keys())
        validated: list[dict[str, Any]] = []
        consumed_absorbs: set[str] = set()
        for m in raw_merges:
            if not isinstance(m, dict):
                raise ValueError(f"normalize_capabilities: merge is not a dict: {m!r}")
            mode = str(m.get("mode", "")).strip().lower()
            if mode not in {"absorb", "expand"}:
                raise ValueError(
                    f"normalize_capabilities: merge has invalid mode {mode!r}: {m!r}"
                )
            absorbs_raw = m.get("absorbs") or []
            if not isinstance(absorbs_raw, list) or not absorbs_raw:
                raise ValueError(
                    f"normalize_capabilities: merge has empty absorbs: {m!r}"
                )
            absorbs = [str(x).strip() for x in absorbs_raw if str(x).strip()]
            for aid in absorbs:
                if aid not in known_ids:
                    raise ValueError(
                        f"normalize_capabilities: merge absorbs unknown id {aid!r}: {m!r}"
                    )
                if aid in consumed_absorbs:
                    raise ValueError(
                        f"normalize_capabilities: id {aid!r} is absorbed in two merges"
                    )
                consumed_absorbs.add(aid)

            if mode == "absorb":
                canonical = str(m.get("canonical_id", "")).strip()
                if not canonical:
                    raise ValueError(
                        f"normalize_capabilities: absorb merge missing canonical_id: {m!r}"
                    )
                if canonical not in known_ids:
                    raise ValueError(
                        f"normalize_capabilities: canonical_id {canonical!r} not in capabilities"
                    )
                if canonical in absorbs:
                    raise ValueError(
                        f"normalize_capabilities: canonical_id {canonical!r} cannot absorb itself"
                    )
                # cross-kind check
                target_kind = merged[canonical]["kind"]
                for aid in absorbs:
                    if merged[aid]["kind"] != target_kind:
                        raise ValueError(
                            f"normalize_capabilities: cannot absorb {aid!r} ({merged[aid]['kind']}) "
                            f"into {canonical!r} ({target_kind}) — kinds differ"
                        )
                validated.append({
                    "mode": "absorb",
                    "canonical_id": canonical,
                    "absorbs": absorbs,
                    "rationale": str(m.get("rationale", "")).strip(),
                })
            else:  # expand
                expand_to_raw = m.get("expand_to") or []
                if not isinstance(expand_to_raw, list) or not expand_to_raw:
                    raise ValueError(
                        f"normalize_capabilities: expand merge missing expand_to: {m!r}"
                    )
                expand_to = [str(x).strip() for x in expand_to_raw if str(x).strip()]
                for tid in expand_to:
                    if tid not in known_ids:
                        raise ValueError(
                            f"normalize_capabilities: expand_to references unknown id {tid!r}: {m!r}"
                        )
                # cross-kind check
                for aid in absorbs:
                    src_kind = merged[aid]["kind"]
                    for tid in expand_to:
                        if merged[tid]["kind"] != src_kind:
                            raise ValueError(
                                f"normalize_capabilities: cannot expand {aid!r} ({src_kind}) into "
                                f"{tid!r} ({merged[tid]['kind']}) — kinds differ"
                            )
                    if aid in expand_to:
                        raise ValueError(
                            f"normalize_capabilities: id {aid!r} cannot expand to itself"
                        )
                validated.append({
                    "mode": "expand",
                    "absorbs": absorbs,
                    "expand_to": expand_to,
                    "rationale": str(m.get("rationale", "")).strip(),
                })
        return validated

    def _apply_normalization(
        self,
        query: str,
        merged: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        """Run stage-3 (normalize_capabilities + mechanical rewrite).

        Mutates a copy of ``merged``: for each absorb merge, fold absorbed
        skill_ids into the canonical entry and drop the absorbed entries; for
        each expand merge, copy absorbed skill_ids into every expand_to target
        and drop the source. Returns the rewritten dict.
        """
        merges = self.normalize_capabilities(query=query, merged=merged)
        if not merges:
            return merged
        out: dict[str, dict[str, Any]] = {k: dict(v, skill_ids=list(v["skill_ids"])) for k, v in merged.items()}
        for m in merges:
            if m["mode"] == "absorb":
                canonical = m["canonical_id"]
                for aid in m["absorbs"]:
                    src = out.pop(aid, None)
                    if src is None:
                        continue  # already removed by an earlier merge in this round
                    for sid in src["skill_ids"]:
                        if sid not in out[canonical]["skill_ids"]:
                            out[canonical]["skill_ids"].append(sid)
                    for jd in src["judgement_dimensions"]:
                        if jd not in out[canonical]["judgement_dimensions"]:
                            out[canonical]["judgement_dimensions"].append(jd)
            else:  # expand
                for aid in m["absorbs"]:
                    src = out.pop(aid, None)
                    if src is None:
                        continue
                    for tid in m["expand_to"]:
                        if tid not in out:
                            continue
                        for sid in src["skill_ids"]:
                            if sid not in out[tid]["skill_ids"]:
                                out[tid]["skill_ids"].append(sid)
                        for jd in src["judgement_dimensions"]:
                            if jd not in out[tid]["judgement_dimensions"]:
                                out[tid]["judgement_dimensions"].append(jd)
        if not out:
            raise ValueError(
                "_apply_normalization: stage-3 produced zero capabilities (overly aggressive merge)"
            )
        return out

    def analyze_capabilities_single_stage(
        self,
        query: str,
        extractions: list[SkillExtraction],
    ) -> CapabilityAnalysis:
        """Legacy one-shot capability clustering.

        Single LLM call: emit 3-8 capability axes directly from the skill
        extractions. The LLM picks the granularity itself, which in practice
        tends to settle at task-level (one column per "translate" / "convert"
        / "extract") and miss the atomic prerequisites (READ / WRITE /
        TRANSFORM) shared across multiple skills. The two-stage path
        (``analyze_capabilities``) addresses that by separating decomposition
        from merge.

        Kept for ``--single-stage`` CLI comparison runs. No fallbacks: if the
        LLM returns an empty / malformed payload, or the capabilities reference
        unknown skill_ids, this raises ``ValueError``.
        """
        skills_payload = [self._compact_extraction(e) for e in extractions]
        known_skill_ids = {e.skill_id for e in extractions}
        prompt = Template(self._capability_prompt_template).safe_substitute(
            {
                "query": query.strip(),
                "skills_payload": json.dumps(skills_payload, ensure_ascii=False, indent=2),
            }
        )
        data = self.client.chat_json(
            system=self._system_prompt,
            user=prompt,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )
        self._cum_tokens += int(getattr(self.client, "last_usage_tokens", 0) or 0)

        raw_caps = data.get("capabilities") if isinstance(data, dict) else None
        if not isinstance(raw_caps, list) or not raw_caps:
            raise ValueError(
                f"analyze_capabilities: LLM returned no capabilities. payload={data!r}"
            )

        analysis = CapabilityAnalysis.from_dict(data)

        if not analysis.capabilities:
            raise ValueError(
                "analyze_capabilities: payload parsed to zero Capability objects "
                f"(raw={raw_caps!r})"
            )

        seen_ids: set[str] = set()
        for cap in analysis.capabilities:
            if not cap.id:
                raise ValueError(f"analyze_capabilities: capability missing id: {cap!r}")
            if cap.id in seen_ids:
                raise ValueError(f"analyze_capabilities: duplicate capability id {cap.id!r}")
            seen_ids.add(cap.id)
            if not cap.name or not cap.description:
                raise ValueError(
                    f"analyze_capabilities: capability {cap.id!r} missing name/description"
                )
            if not cap.input_shape or not cap.output_shape:
                raise ValueError(
                    f"analyze_capabilities: capability {cap.id!r} missing input_shape/output_shape"
                )
            if not cap.skill_ids:
                raise ValueError(
                    f"analyze_capabilities: capability {cap.id!r} has no skills "
                    "claiming it (skill_ids empty)"
                )
            unknown = [sid for sid in cap.skill_ids if sid not in known_skill_ids]
            if unknown:
                raise ValueError(
                    f"analyze_capabilities: capability {cap.id!r} references "
                    f"unknown skill_ids: {unknown}"
                )

        # Re-derive skill_capability_map from skill_ids (LLM is told not to emit it).
        mapping: dict[str, list[str]] = {}
        for cap in analysis.capabilities:
            for sid in cap.skill_ids:
                bucket = mapping.setdefault(sid, [])
                if cap.id not in bucket:
                    bucket.append(cap.id)
        analysis.skill_capability_map = mapping

        self._last_capability_analysis = analysis
        return analysis

    @property
    def last_capability_analysis(self) -> CapabilityAnalysis | None:
        return self._last_capability_analysis

    def generate_for_capability(
        self,
        query: str,
        capability: Capability,
    ) -> GeneratedTask:
        """Author one task that tests exactly one capability axis.

        The prompt deliberately does NOT see the skill list — that's what makes
        the resulting task skill-set-agnostic and column-comparable. Same
        capability ⇒ same task across the whole batch.

        Raises ValueError on empty / unparseable response. No retry, no
        fallback — let the matrix runner record the failed cell rather than
        silently weakening the column.
        """
        prompt = Template(self._task_from_capability_prompt_template).safe_substitute(
            {
                "query": query.strip(),
                "capability": json.dumps(
                    capability.to_dict(), ensure_ascii=False, indent=2
                ),
            }
        )
        data = self.client.chat_json(
            system=self._system_prompt,
            user=prompt,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )
        self._cum_tokens += int(getattr(self.client, "last_usage_tokens", 0) or 0)
        # Tolerate {"tasks": [{...}]} envelope.
        if isinstance(data, dict) and "tasks" in data and isinstance(data["tasks"], list):
            arr = data["tasks"]
            data = arr[0] if arr else {}
        if not data or not isinstance(data, dict):
            raise ValueError(
                f"generate_for_capability[{capability.id!r}]: empty/unparseable LLM payload"
            )
        data.setdefault("query", query)
        data["capability_id"] = capability.id
        data["capability"] = capability.to_dict()
        # Tag the task automatically so downstream filters see the matrix label.
        extras = dict(data.get("task_toml_extras") or {})
        tags = list(extras.get("tags") or [])
        marker = f"capability:{capability.id}"
        if marker not in tags:
            tags.append(marker)
        if "matrix" not in tags:
            tags.append("matrix")
        extras["tags"] = tags
        data["task_toml_extras"] = extras
        task = GeneratedTask.from_dict(data)
        if not task.task_id:
            raise ValueError(
                f"generate_for_capability[{capability.id!r}]: LLM returned task without task_id"
            )
        if not task.assets:
            raise ValueError(
                f"generate_for_capability[{capability.id!r}]: LLM returned task with no assets"
            )
        if not task.tests_py.strip() and not task.tests:
            raise ValueError(
                f"generate_for_capability[{capability.id!r}]: LLM returned task with no tests"
            )
        if not task.solution_py.strip():
            raise ValueError(
                f"generate_for_capability[{capability.id!r}]: LLM returned task with no solution_py"
            )
        return task

    # ---------------------------------------------------------------- combined

    def generate_combined(
        self,
        query: str,
        extractions: list[SkillExtraction],
    ) -> GeneratedTask | None:
        """Combined-task path: discriminator matrix → ONE task with N tests.

        Step 1 mirrors ``generate_two_step``: produce a discriminator matrix.
        Step 2 collapses the entire matrix into a single combined task whose
        ``tests`` list has one pytest file per discriminator and whose
        ``assets`` / ``solution_py`` are shared across all of them.

        Returns ``None`` if step 1 finds no discriminators or step 2 produces
        an empty/unparseable response.
        """
        discs = self.analyze_discriminators(query, extractions)
        self._last_discriminators = discs
        if not discs:
            return None
        prompt = Template(self._combined_prompt_template).safe_substitute(
            {
                "query": query.strip(),
                "discriminators": json.dumps(
                    [d.to_dict() for d in discs], ensure_ascii=False, indent=2
                ),
                "skills_payload": json.dumps(
                    [self._compact_extraction(e) for e in extractions],
                    ensure_ascii=False,
                    indent=2,
                ),
            }
        )
        data = self.client.chat_json(
            system=self._system_prompt,
            user=prompt,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )
        self._cum_tokens += int(getattr(self.client, "last_usage_tokens", 0) or 0)
        # Tolerate {"tasks": [{...}]} envelope
        if isinstance(data, dict) and "tasks" in data and isinstance(data["tasks"], list):
            arr = data["tasks"]
            data = arr[0] if arr else {}
        if not data:
            return None
        data.setdefault("query", query)
        task = GeneratedTask.from_dict(data)
        # If LLM forgot to echo discriminators back, fill from step-1 output so
        # downstream (validator, runner) can still map test -> discriminator.
        if not task.discriminators:
            task.discriminators = discs
        return task

    # ---------------------------------------------------------------- repair

    def repair_task(
        self,
        task: GeneratedTask,
        failed_stage: str,
        detail: str,
        logs: str,
    ) -> GeneratedTask:
        """Ask the LLM to patch a task that failed self-validation.

        Returns a *new* GeneratedTask with patched fields applied. The
        caller is expected to re-validate. Common failure patterns this
        targets: pytest exit 5 (no tests collected — LLM put assertions
        at module top-level), missing ModuleNotFoundError, simple
        regex / parsing mistakes in solution_py.
        """
        # truncate logs from the tail (failures show up at the end)
        logs_tail = ("\n".join(logs.splitlines()[-40:])) if logs else "(no logs captured)"
        prompt = Template(self._repair_prompt_template).safe_substitute(
            {
                "failed_stage": failed_stage or "(unknown)",
                "detail": detail or "(no detail)",
                "logs": logs_tail,
                "task_json": json.dumps(task.to_dict(), ensure_ascii=False, indent=2),
            }
        )
        data = self.client.chat_json(
            system=self._system_prompt,
            user=prompt,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )
        self._cum_tokens += int(getattr(self.client, "last_usage_tokens", 0) or 0)
        patch = data.get("patch") or {}
        return _apply_patch(task, patch)

    @property
    def last_discriminators(self) -> list[Discriminator]:
        return list(self._last_discriminators)

    def schema_version(self) -> str:
        return SCHEMA_VERSION

    # --------------------------------------------------------------- helpers

    def _render_user_prompt(
        self,
        query: str,
        extractions: list[SkillExtraction],
    ) -> str:
        skills_payload: list[dict[str, Any]] = [
            self._compact_extraction(ext) for ext in extractions
        ]
        return Template(self._user_prompt_template).safe_substitute(
            {
                "query": query.strip(),
                "skills_payload": json.dumps(skills_payload, ensure_ascii=False, indent=2),
            }
        )

    @staticmethod
    def _compact_extraction(ext: SkillExtraction) -> dict[str, Any]:
        # Capability surface + the four fields that actually *discriminate*
        # skills from each other: variation_axes (parameter dimensions),
        # preconditions (input assumptions), success_criteria (semantic
        # quality bars), common_failure_modes (where it breaks). Without
        # these the LLM only sees "skill X can do Y" and writes median
        # tasks that any skill on the list can pass.
        return {
            "skill_id": ext.skill_id,
            "scheduling": ext.scheduling.to_dict(),
            "capability_candidates": [
                {
                    "capability_id": c.capability_id,
                    "name": c.name,
                    "description": c.description,
                    "inputs": list(c.inputs),
                    "outputs": list(c.outputs),
                    "actions": list(c.actions),
                    "variation_axes": [a.to_dict() for a in c.variation_axes],
                    "preconditions": [e.to_dict() for e in c.preconditions],
                    "success_criteria": c.success_criteria.to_dict(),
                    "common_failure_modes": [
                        e.to_dict() for e in c.common_failure_modes
                    ],
                }
                for c in ext.capability_candidates
            ],
        }


__all__ = ["TaskGenerator"]


def _apply_patch(task: GeneratedTask, patch: dict[str, Any]) -> GeneratedTask:
    """Return a shallow copy of `task` with the LLM-supplied patch merged in.

    Recognised keys:
      - ``tests_py``        — replace single-file tests body (one-step / per-disc path)
      - ``solution_py``     — replace solution body
      - ``assets``          — list of ``{"index": int, "renderer_py": str}``
      - ``tests_header``    — replace combined-task shared header
      - ``tests``           — list of ``{"discriminator_id": str, "body": str}`` OR
                              ``{"class_name": str, "body": str}``; matches an
                              entry in ``task.tests`` and replaces its body
                              (combined-task path)

    Anything else in `patch` is ignored — repair is mechanics-only, not redesign.
    """
    from copy import deepcopy

    new = deepcopy(task)
    if isinstance(patch.get("tests_py"), str) and patch["tests_py"].strip():
        new.tests_py = patch["tests_py"]
    if isinstance(patch.get("solution_py"), str) and patch["solution_py"].strip():
        new.solution_py = patch["solution_py"]
    if isinstance(patch.get("tests_header"), str) and patch["tests_header"].strip():
        new.tests_header = patch["tests_header"]
    raw_assets = patch.get("assets")
    if isinstance(raw_assets, list):
        for a in raw_assets:
            if not isinstance(a, dict):
                continue
            idx = a.get("index")
            if not isinstance(idx, int) or idx < 0 or idx >= len(new.assets):
                continue
            renderer = a.get("renderer_py")
            if isinstance(renderer, str) and renderer.strip():
                new.assets[idx].renderer_py = renderer
                new.assets[idx].content_bytes = None  # force re-render
    raw_tests = patch.get("tests")
    if isinstance(raw_tests, list) and new.tests:
        for entry in raw_tests:
            if not isinstance(entry, dict):
                continue
            body = entry.get("body")
            if not isinstance(body, str) or not body.strip():
                continue
            target_disc = (entry.get("discriminator_id") or "").strip()
            target_cls = (entry.get("class_name") or "").strip()
            for t in new.tests:
                if target_disc and t.discriminator_id == target_disc:
                    t.body = body
                    break
                if target_cls and t.class_name == target_cls:
                    t.body = body
                    break
    return new
