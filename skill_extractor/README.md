# skill_extractor

Extract structured capability information from a `SKILL.md` file, without
generating an SSL (scenes / logic_steps) graph.

## Output schema

A single SKILL.md produces a `SkillExtraction`:

```python
SkillExtraction(
    skill_id: str,
    source_path: str,
    scheduling: SkillScheduling(
        skill_name, skill_goal,
        tags, expected_inputs, expected_outputs, dependencies,
    ),
    capability_candidates: list[CapabilityCandidate],
    raw_text: str,
    extractor_meta: {
        "backend": "openai" | "anthropic",
        "model": "...",
        "schema_version": "skill-extractor-v1",
        "usage_tokens": int,
    },
)
```

Each `CapabilityCandidate` carries the scenario-shaped fields:

```python
CapabilityCandidate(
    capability_id: str,           # kebab-case, alignable across skills
    name: str,
    description: str,
    matched_terms: list[str],     # source phrases (evidence)
    inputs: list[str],
    outputs: list[str],
    actions: list[str],

    # Scenario information — drives downstream probe generation
    variation_axes: list[VariationAxis],          # {axis, values, default}
    preconditions: list[Evidence],                # input-side assumptions
    success_criteria: SuccessCriteria(            # output-side judges
        structural: list[Evidence],               # machine-checkable today
        semantic:   list[Evidence],               # LLM-judge hints
    ),
    common_failure_modes: list[Evidence],         # negative scenarios

    level: "fine" | "coarse",
)
```

`Evidence` is `{text, source: "explicit" | "inferred", evidence: "SKILL.md:LN"}`,
so downstream code can weight `explicit` fields higher than `inferred` ones.

## Usage

### Python

```python
from dynamic_skill_eval_v2.llm_client import ChatClient
from dynamic_skill_eval_v2.skill_extractor import LLMSkillExtractor

client = ChatClient()                           # reads env vars
extractor = LLMSkillExtractor(client=client)
extraction = extractor.extract_path("/path/to/skill-dir")
print(extraction.to_dict())
```

### CLI

```bash
python -m dynamic_skill_eval_v2.skill_extractor.cli \
    --skill /path/to/skill-dir \
    --out   /tmp/extraction.json
```

## Field extraction quality

Different SKILL.md files yield different field coverage. The extractor is
instructed to ground every value in source text, and to leave a field empty
rather than hallucinate. Empirically:

| Field | Reliability | Likely source section in SKILL.md |
|---|---|---|
| `variation_axes` | high | script parameters, supported-format tables |
| `common_failure_modes` | medium-high | "pitfalls", "error handling", "unsupported" |
| `preconditions` | medium | "requirements", "unsupported" (reversed) |
| `success_criteria.structural` | medium | "output" sections (file paths) |
| `success_criteria.semantic` | low-medium | rarely explicit; often left empty |
