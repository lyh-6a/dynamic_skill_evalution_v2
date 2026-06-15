# outputs/

`dynamic_skill_eval_v2` 流水线的产物。每一阶段的输出都落在这里，对照 `../PIPELINE.md` 看上下文。

```
outputs/
├── extractions/                   # stage 1: skill_extractor
│   ├── doc-process-4.1.1.json
│   ├── docx-compare-1.0.2.json
│   ├── document-reader-1.0.0.json
│   ├── document-translate-0.1.0.json
│   └── document-format-converter-1.0.0.json
│
├── matrix_batch_v2/               # stage 2: task_generation.matrix_cli
│   ├── capabilities.json          #   15 个互斥能力
│   ├── capabilities_full.json     #   带 evidence 的完整版
│   ├── skill_capability_map.json  #   5 个 skill 各自声明哪些 capability
│   ├── tasks/<cap_id>/            #   15 个 SkillsBench task bundle
│   ├── build_report.json          #   生成阶段日志
│   ├── matrix.json                # stage 3: task_runner — glm-5.1
│   ├── matrix_qwen36.json         # stage 3: task_runner — qwen3.6-flash
│   ├── matrix.md                  # stage 4: 报表 (vs glm baseline)
│   └── matrix_qwen36.md           # stage 4: 报表 (vs qwen baseline + 跨模型对比)
│
├── baseline_batch_v2/             # stage 3b: no-skill baseline batch
│   ├── capabilities.json          #   复制自 matrix_batch_v2
│   ├── tasks/<cap_id>/            #   复制自 matrix_batch_v2
│   ├── skill_capability_map.json  #   {"without-skill": [全部 cap]}
│   ├── matrix.json                #   glm-5.1 baseline 跑分
│   └── matrix_qwen36.json         #   qwen3.6-flash baseline 跑分
│
└── baseline_skill_root/           # stage 3b: no-skill 占位 skill
    └── without-skill/
        └── SKILL.md               #   只含 frontmatter + 一段说明，没有真实工具
```

## 当前快照（doc-skills 5 × 15）

- 5 skills × 15 capabilities = 44 declared cells
- glm-5.1：35/44 PASS（80%），70 min，25k token
- qwen3.6-flash：32/44 PASS（73%），59 min，50k token
- baseline（无 skill）：glm 12/15 PASS、qwen 11/15 PASS

详细排名、增益矩阵、失败明细见 `matrix_batch_v2/matrix*.md`。
