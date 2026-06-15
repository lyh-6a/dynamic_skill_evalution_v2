# dynamic_skill_eval_v2

SKILL.md → structured capability extraction, without the SSL
(scenes / logic_steps) intermediate representation.

## Layout

```
dynamic_skill_eval_v2/
├── llm_client/          # Minimal OpenAI / Anthropic chat client
└── skill_extractor/     # SKILL.md → SkillExtraction
```

## Quick start

```bash
export OPENAI_API_KEY=sk-...
export OPENAI_BASE_URL=https://api.openai.com/v1
export OPENAI_MODEL=gpt-4o-mini

python -m dynamic_skill_eval_v2.skill_extractor.cli \
    --skill /path/to/skill-dir \
    --out   /tmp/extraction.json
```
