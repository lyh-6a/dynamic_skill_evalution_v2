# dynamic_skill_eval_v2 — 阶段说明

把一组 SKILL.md 变成一张「能力 × 技能」可执行评测矩阵，最后给每个 (skill, capability) 输出一个 reward / pass-rate / token，并和 no-skill baseline 一减得到增益矩阵。

整条流水线：

```
SKILL.md  ─►  skill_extractor  ─►  task_generation.matrix_cli  ──►  outputs/matrix_batch_v2/
                                                                            │
                                                                            ▼
                                              task_runner.matrix_cli  ──►  matrix.json
                                                                            │
                                                              (vs no-skill baseline)
                                                                            │
                                                                            ▼
                                                                     matrix.md (gain)
```

各阶段的输入 / 输出 / 原理见下。所有产物默认落到 `dynamic_skill_eval_v2/outputs/` 下，对应路径直接看仓库即可。

---

## 1. skill_extractor — SKILL.md 抽结构

**目的**：把人写的 `SKILL.md`（自然语言）规整成机器可比的 `SkillExtraction` JSON：列出这个 skill 声称做什么、做不了什么、用什么命令、在哪些维度上能变化、怎么算成功。

**入口**：`python -m dynamic_skill_eval_v2.skill_extractor.cli`

**输入**：
- `--skill <path>`：一个 skill 目录（必须包含 `SKILL.md`，可以有子文件）
- `--out <file>`：输出 JSON 路径
- `--model / --base-url / --api-type`：LLM 配置（OpenAI 兼容或 Anthropic）

**原理**：
1. `source_scanner` 扫 skill 目录，把 `SKILL.md` 主文档 + 引用到的子文档拼成上下文。
2. `prompt_loader` 套上抽取 prompt（要求 LLM 按 schema 输出 JSON）。
3. `llm_client.ChatClient` 调 LLM，强制 JSON 输出。
4. `extractor` 把返回的 JSON 解析成 dataclass，schema 不齐就 raise（**不兜底**）。

**输出**（`SkillExtraction`，见 `skill_extractor/schema.py`）：
```jsonc
{
  "skill_id": "doc-process-4.1.1",
  "skill_name": "...",
  "version": "...",
  "description": "...",
  "capabilities": [
    {
      "id": "cap-read-pdf",
      "name": "Read PDF",
      "description": "...",
      "evidence": [{"file": "SKILL.md", "lines": "12-18", "quote": "..."}],
      "variation_axes": [{"name": "page_count", "values": [...]}],
      "success_criteria": [...]
    }
  ],
  "scheduling": {...},        // 何时被调用
  "non_goals": [...],         // 明确不做的事
  "preconditions": [...]
}
```

每个 skill 一份 JSON，作为后面所有阶段的"事实源"。

**实际产物**：`outputs/extractions/<skill_id>.json`
- `doc-process-4.1.1.json`
- `docx-compare-1.0.2.json`
- `document-reader-1.0.0.json`
- `document-translate-0.1.0.json`
- `document-format-converter-1.0.0.json`

---

## 2. task_generation — 把抽象能力变成可执行任务包

**入口（矩阵模式）**：`python -m dynamic_skill_eval_v2.task_generation.matrix_cli`

**目的**：每个 capability 对应一个具体的、能在 docker 里跑、能用 pytest 判分的任务包（SkillsBench 兼容格式）。同一列（同一 capability）所有 skill 跑同一个任务包——这是矩阵的"列不变性"。

**输入**：
- `--query "Compare doc-skill capabilities ..."`：高层评测意图
- `--input <skill_extraction.json> ...` 或 `--input-glob`
- `--out-dir <batch_dir>`
- `--domain "<domain>"`：评测场景名（自由字符串），用于 stage 0 给 LLM 提示当前是哪个域。**第一次跑某个域必填**（除非传 `--taxonomy`）。
- `--taxonomy <taxonomy.json>`：可选，跳过 stage 0 直接复用上次跑出的 taxonomy。同域多次跑想锁住命名约定时用。
- `--no-validate / --validator-timeout / --no-pip-install / --repair-attempts`：生成后是否本地 sanity 跑通 pytest
- LLM 配置 + `--max-tokens / --temperature`

**原理**：
1. **Stage 0 — propose_taxonomy**（新增）：把 `--domain` + 所有 skill 的精简提取喂给 LLM，让它**针对这一批 skill 自己提一份 taxonomy**：定义 4–9 个互斥的 `kind`（READ/RENDER/EDIT/SOLVE...，按域而异）、modality 命名空间（开放或闭枚举 + examples）、id 格式、3–6 条 few-shot。这份 taxonomy 落到 `out_dir/taxonomy.json` 并作为后续 stage 1/3 的强约束。传了 `--taxonomy` 就跳过这步。
2. **Stage 1 — decompose_atoms**：用 LLM 按 stage 0 的 taxonomy 把每个 skill 的 capability 列表拆成原子操作（`{skill_id: [atom...]}`）。`atom.kind` 必须来自 taxonomy；非法 kind 直接 raise（**不兜底**）。
3. **Stage 2 — mechanical merge**：按 atom id 求并集，每个 unique id 一列；同 id 跨 skill 的 kind 必须一致，否则 raise。
4. **Stage 3 — normalize_capabilities**：第二次 LLM 调用，对合并后的 capability 列表做 absorb/expand 重写（`cap-read-document` 收编到 `cap-read-pdf` / 拆成多列 specific），同样受 taxonomy 约束。
5. 对每个 capability，LLM 生成 `GeneratedTask`（domain-neutral prompt，不再硬编码 PDF/openpyxl 范例）：
   - `prompt`：告诉 agent 要做什么（用户视角自然语言）
   - `assets`：起始输入文件
   - `discriminators` → `tests/test_outputs.py`：pytest 判别器
6. `validator` 临时跑一遍 pytest 确认题目自洽，不过就 raise（**不兜底**）。
7. `bundle_writer` 写入磁盘：
   ```
   batch_<id>/
     taxonomy.json              # stage 0 产物，本次跑的命名约定
     capabilities.json          # CapabilityAnalysis
     skill_capability_map.json  # {skill_id: [capability_id, ...]}
     tasks/<capability_id>/     # 每个 capability 一个 SkillsBench bundle
     build_report.json
   ```

**输出**：上面这个 batch 目录，是后面 task_runner 的唯一输入。

**实际产物**：`outputs/matrix_batch_v2/`
- `taxonomy.json` — 当次跑的 kind 列表 + modality 命名空间 + few-shot
- `capabilities.json` / `capabilities_full.json` — 互斥能力列表
- `skill_capability_map.json` — 每个 skill 声明哪些 capability
- `tasks/<cap_id>/` — 每个 capability 的 SkillsBench task bundle
- `build_report.json` — 生成阶段日志

---

## 3. task_runner — 跑矩阵 / baseline

**入口（矩阵模式）**：`python -m dynamic_skill_eval_v2.task_runner.matrix_cli`

**目的**：把 batch 里的每个 `(skill, capability)` cell 在 docker 里跑一遍，记录 reward / pass-rate / agent_tokens / agent_seconds。

**输入**：
- `--batch-dir <batch_dir>`：上一阶段产物
- `--skills-root <dir>`：默认按 `<root>/<skill_id>/` 找 skill 目录；也可用 `--skill-map <json>` 显式映射
- `--model openai/qwen3.6-flash` 等
- `--ak api_base=... --ak api_key=...`：注入到 agent 子进程的额外参数（这里是 LLM endpoint 配置）
- `--no-skill-deps`：跳过 skill 自带 pip 依赖（baseline 用）
- `--work-dir / --timeout-sec / --force-build / --keep-workspace / --no-cleanup-images`
- `--out <matrix.json>`

**原理**：
1. `MatrixBatch.load()` 读 batch 目录，校验每个 capability 都有 task bundle，否则 raise（**不兜底**）。
2. 对每个 skill 起一个 `HarborSkillRunner`（保证同一 skill 的 docker 镜像/层 cache 跨 capability 复用）。
3. 对每个声明的 `(skill, capability)`：
   - 把 task bundle 拷到工作区，让 harbor 起 docker 容器
   - 容器里跑 `forced_skill_agent.HarborTerminus2ForcedSkills`：基类是 `HarborTerminus2WithSkills`，子类在 setup 里把 skill 的 `SKILL.md` 全文塞进 episode 0 的 system prompt，agent 不需要主动 `load_skill`
   - agent 在容器里读 prompt + assets，调工具完成任务
   - 容器结束后跑 `tests/test_outputs.py`，每个 `class Test*` 的 pass/fail 进 `ctrf.json`
   - reward = 全部 discriminator class 都过 → 1.0，否则 0.0；pass-rate = 通过 class 数 / 总 class 数
4. 没声明该 capability 的 cell 写成 `null`（不跑）。
5. 一行 PASS/FAIL 实时打到 stderr，最后整张矩阵写到 `matrix.json`。

**输出**：`matrix.json`：
```jsonc
{
  "schema_version": "matrix.v1",
  "skills": [...],
  "capabilities": [...],
  "cells": {
    "<skill_id>": {
      "<cap_id>": {
        "task_id": "...", "reward": 1.0, "pass_rate": 1.0,
        "agent_ok": true, "verifier_ok": true,
        "agent_seconds": 29.8, "agent_tokens": 858,
        "failure": "", "job_dir": "/tmp/.../jobs/..."
      } /* | null  // 该 skill 没声明这个 capability */
    }
  },
  "elapsed_sec": 3529
}
```

**实际产物**：写回到同一个 batch 目录里
- `outputs/matrix_batch_v2/matrix.json` — glm-5.1 跑的结果
- `outputs/matrix_batch_v2/matrix_qwen36.json` — qwen3.6-flash 跑的结果

### 3b. baseline（同入口，不同参数）

baseline = 用一个空壳 `without-skill` 加 `--no-skill-deps`，跑同一份 batch，得到「裸模型在每个 capability 上的成绩」。把同模型 baseline 的 reward 从 skill matrix 一减就是 **gain**：
```
gain[skill, cap] = reward_skill[skill, cap] − reward_baseline[without-skill, cap]
```

baseline 必须用**同一个模型 + 同一份 batch**，否则 gain 不可比。本次先用 glm-5.1 baseline，后来发现 qwen 跑出的部分 capability 行为不同（qwen baseline 在 read-pptx/rtf FAIL 但 write-xlsx PASS），所以又跑了 qwen baseline。

**实际产物**：
- `outputs/baseline_skill_root/without-skill/SKILL.md` — 空壳 skill（只有 frontmatter + 一段说明）
- `outputs/baseline_batch_v2/` — 跟 matrix_batch_v2 同样的 capabilities.json + tasks/，但 `skill_capability_map.json` 改成 `{"without-skill": [全部 cap]}`
- `outputs/baseline_batch_v2/matrix.json` — glm-5.1 baseline
- `outputs/baseline_batch_v2/matrix_qwen36.json` — qwen3.6-flash baseline

---

## 4. 报表（手工）

最后把 `matrix.json` + `matrix_qwen36.json`（baseline）做一次 join，渲染成 markdown：

- **Strict Score Matrix**：reward 表
- **Pass-rate Matrix**：discriminator 类粒度通过率
- **Gain Matrix**：reward − baseline
- **Skill / Capability ranking by gain**
- **Failure breakdown**：FAIL cell 的 token / time / 失败类型

这一步暂时是脚本现写的，不在 v2 里固化。

**实际产物**：
- `outputs/matrix_batch_v2/matrix.md` — glm-5.1 报表（vs glm baseline）
- `outputs/matrix_batch_v2/matrix_qwen36.md` — qwen3.6-flash 报表（vs qwen baseline，含 vs glm 对比）

---

## 命名 / 规则约定

- **不兜底**：任何 LLM 输出 schema 缺字段、batch 缺 task bundle、skill 路径不存在 → 直接 raise，不静默 fallback。便于把生成端的问题暴露在前面阶段而不是混进矩阵里。
- **列不变性**：同一 capability 列上，所有 skill 跑的是同一个 task bundle（相同输入文件、相同 prompt、相同判别器），结果差异只能来自 skill 行为。
- **同模型 baseline**：gain 必须用同一个 LLM 跑出来的 baseline 减；跨模型混用会污染 gain。
- **Discriminator 类粒度**：`tests/test_outputs.py` 里每个 `class Test*` 是一个独立判别维度，pass-rate 是类粒度而不是函数粒度。reward 是「全部类都过」的 0/1 指标，更严。
- **0-token AgentTimeout**：观察到 LLM 端冷启动偶发会导致 agent 整段不发 token 直接超时，这种 cell 应在「真实负增益」之外单独标注并允许重跑（重跑逻辑目前手工，不放进 runner，避免和"不兜底"冲突）。

---

## 一次完整跑通示例（doc-skills 5 × 15）

环境变量：
```bash
export DASHSCOPE_API_KEY=sk-...
V2=/home/liuyuhan/dynamic_skill_evalution/dynamic_skill_eval_v2
```

```bash
# 1) 抽 5 个 skill
mkdir -p $V2/outputs/extractions
for s in doc-process-4.1.1 docx-compare-1.0.2 document-reader-1.0.0 \
         document-translate-0.1.0 document-format-converter-1.0.0; do
  python -m dynamic_skill_eval_v2.skill_extractor.cli \
    --skill /home/liuyuhan/dynamic_skill_evalution/doc_skills/$s \
    --out   $V2/outputs/extractions/$s.json
done

# 2) 生成矩阵 batch（含 stage 0 自动提 taxonomy）
python -m dynamic_skill_eval_v2.task_generation.matrix_cli \
  --query "Compare doc-skill capabilities for an evaluation matrix." \
  --domain "document processing" \
  --input-glob "$V2/outputs/extractions/*.json" \
  --out-dir $V2/outputs/matrix_batch_v2

#    跨域跑：换 --domain 即可
# python -m dynamic_skill_eval_v2.task_generation.matrix_cli \
#   --query "Compare draw-skill capabilities for an evaluation matrix." \
#   --domain "image drawing" \
#   --input-glob "$V2/outputs/extractions/draw-*.json" \
#   --out-dir $V2/outputs/matrix_batch_draw
#
#    想锁住一份 taxonomy 复用：
# python -m dynamic_skill_eval_v2.task_generation.matrix_cli \
#   --taxonomy $V2/outputs/matrix_batch_v2/taxonomy.json \
#   --input-glob "$V2/outputs/extractions/*.json" \
#   --query "..." --out-dir $V2/outputs/matrix_batch_v3

# 3) 跑矩阵（skill）— qwen3.6-flash
python -m dynamic_skill_eval_v2.task_runner.matrix_cli \
  --batch-dir $V2/outputs/matrix_batch_v2 \
  --skills-root /home/liuyuhan/dynamic_skill_evalution/doc_skills \
  --work-dir /tmp/matrix_run_work_qwen36 \
  --out $V2/outputs/matrix_batch_v2/matrix_qwen36.json \
  --model openai/qwen3.6-flash \
  --ak api_base=https://dashscope.aliyuncs.com/compatible-mode/v1 \
  --ak api_key=$DASHSCOPE_API_KEY

# 4) 跑 baseline（同模型）
# 4a) 准备 baseline batch（只需第一次做）
mkdir -p $V2/outputs/baseline_batch_v2
cp $V2/outputs/matrix_batch_v2/capabilities.json $V2/outputs/baseline_batch_v2/
cp -r $V2/outputs/matrix_batch_v2/tasks $V2/outputs/baseline_batch_v2/
python -c "import json; caps=[c['id'] for c in json.load(open('$V2/outputs/baseline_batch_v2/capabilities.json'))['capabilities']]; \
  json.dump({'without-skill': caps}, open('$V2/outputs/baseline_batch_v2/skill_capability_map.json','w'), indent=2)"

# 4b) 跑 baseline
python -m dynamic_skill_eval_v2.task_runner.matrix_cli \
  --batch-dir $V2/outputs/baseline_batch_v2 \
  --skills-root $V2/outputs/baseline_skill_root \
  --no-skill-deps \
  --work-dir /tmp/baseline_run_work_qwen36 \
  --out $V2/outputs/baseline_batch_v2/matrix_qwen36.json \
  --model openai/qwen3.6-flash \
  --ak api_base=https://dashscope.aliyuncs.com/compatible-mode/v1 \
  --ak api_key=$DASHSCOPE_API_KEY

# 5) 手工 render 报表（脚本，输出到 matrix.md）
```
