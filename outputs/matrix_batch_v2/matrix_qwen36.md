# qwen3.6-flash × doc-skills capability matrix (same-model baseline)

- Batch: `/tmp/matrix_batch_v2/`
- Skill model & baseline model: `openai/qwen3.6-flash` via `https://dashscope.aliyuncs.com/compatible-mode/v1`
- Skill run: 3529s (58.8 min) | Baseline run: 1164s (19.4 min)

## Baseline reward per capability (without-skill, qwen3.6-flash)

| Capability | Name | qwen baseline | glm baseline (ref) |
|---|---|---:|---:|
| `cap-read-docx` | Read DOCX | 1.00 | 1.00 |
| `cap-read-html` | Read HTML body text | 1.00 | 1.00 |
| `cap-read-image` | Read image document | 0.00 | 0.00 |
| `cap-read-json` | Read JSON file | 1.00 | 1.00 |
| `cap-read-markdown` | Read Markdown | 1.00 | 1.00 |
| `cap-read-odt` | Read ODT | 1.00 | 1.00 |
| `cap-read-pdf` | Read PDF | 1.00 | 1.00 |
| `cap-read-pptx` | Read PPTX | 0.00 ⚠ | 1.00 |
| `cap-read-rtf` | Read RTF | 0.00 ⚠ | 1.00 |
| `cap-read-xlsx` | Read XLSX | 1.00 | 1.00 |
| `cap-transform-tabular-to-json` | Convert tabular data to JSON | 1.00 | 1.00 |
| `cap-write-json` | Write JSON file | 1.00 | 1.00 |
| `cap-write-markdown` | Write Markdown file | 1.00 | 1.00 |
| `cap-write-pdf` | Write PDF | 0.00 | 0.00 |
| `cap-write-xlsx` | Write XLSX | 1.00 ⚠ | 0.00 |

## Strict Score Matrix (skill reward, qwen3.6-flash)

| Skill | `cap-read-docx` | `cap-read-html` | `cap-read-image` | `cap-read-json` | `cap-read-markdown` | `cap-read-odt` | `cap-read-pdf` | `cap-read-pptx` | `cap-read-rtf` | `cap-read-xlsx` | `cap-transform-tabular-to-json` | `cap-write-json` | `cap-write-markdown` | `cap-write-pdf` | `cap-write-xlsx` | row_avg |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `doc-process-4.1.1` | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 | – | – | **0.92** |
| `document-format-converter-1.0.0` | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 | 1.00 | 0.00 | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 1.00 | **0.73** |
| `document-reader-1.0.0` | 1.00 | 1.00 | – | – | 1.00 | 1.00 | 0.00 | 0.00 | 0.00 | 1.00 | 1.00 | – | – | – | – | **0.67** |
| `document-translate-0.1.0` | 1.00 | – | – | – | – | – | 0.00 | 1.00 | – | 1.00 | – | – | – | 0.00 | 0.00 | **0.50** |
| `docx-compare-1.0.2` | 0.00 | – | – | – | – | – | – | – | – | – | – | – | – | – | – | **0.00** |
| **col_avg** | **0.80** | **1.00** | **1.00** | **1.00** | **1.00** | **1.00** | **0.25** | **0.75** | **0.33** | **1.00** | **1.00** | **1.00** | **0.00** | **0.00** | **0.50** | — |

## Pass-rate Matrix (qwen3.6-flash)

| Skill | `cap-read-docx` | `cap-read-html` | `cap-read-image` | `cap-read-json` | `cap-read-markdown` | `cap-read-odt` | `cap-read-pdf` | `cap-read-pptx` | `cap-read-rtf` | `cap-read-xlsx` | `cap-transform-tabular-to-json` | `cap-write-json` | `cap-write-markdown` | `cap-write-pdf` | `cap-write-xlsx` | row_avg |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `doc-process-4.1.1` | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 | – | – | 12/13 |
| `document-format-converter-1.0.0` | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 | 1.00 | 0.00 | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 1.00 | 11/15 |
| `document-reader-1.0.0` | 1.00 | 1.00 | – | – | 1.00 | 1.00 | 0.00 | 0.00 | 0.00 | 1.00 | 1.00 | – | – | – | – | 6/9 |
| `document-translate-0.1.0` | 1.00 | – | – | – | – | – | 0.00 | 1.00 | – | 1.00 | – | – | – | 0.00 | 0.00 | 3/6 |
| `docx-compare-1.0.2` | 0.00 | – | – | – | – | – | – | – | – | – | – | – | – | – | – | 0/1 |

## Gain Matrix (skill reward − qwen baseline)

| Skill | `cap-read-docx` | `cap-read-html` | `cap-read-image` | `cap-read-json` | `cap-read-markdown` | `cap-read-odt` | `cap-read-pdf` | `cap-read-pptx` | `cap-read-rtf` | `cap-read-xlsx` | `cap-transform-tabular-to-json` | `cap-write-json` | `cap-write-markdown` | `cap-write-pdf` | `cap-write-xlsx` | row_avg |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `doc-process-4.1.1` | 0.00 | 0.00 | +1.00 | 0.00 | 0.00 | 0.00 | 0.00 | +1.00 | +1.00 | 0.00 | 0.00 | 0.00 | -1.00 | – | – | **+0.15** |
| `document-format-converter-1.0.0` | 0.00 | 0.00 | +1.00 | 0.00 | 0.00 | 0.00 | -1.00 | +1.00 | 0.00 | 0.00 | 0.00 | 0.00 | -1.00 | 0.00 | 0.00 | **0.00** |
| `document-reader-1.0.0` | 0.00 | 0.00 | – | – | 0.00 | 0.00 | -1.00 | 0.00 | 0.00 | 0.00 | 0.00 | – | – | – | – | **-0.11** |
| `document-translate-0.1.0` | 0.00 | – | – | – | – | – | -1.00 | +1.00 | – | 0.00 | – | – | – | 0.00 | -1.00 | **-0.17** |
| `docx-compare-1.0.2` | -1.00 | – | – | – | – | – | – | – | – | – | – | – | – | – | – | **-1.00** |
| **col_avg** | **-0.20** | **0.00** | **+1.00** | **0.00** | **0.00** | **0.00** | **-0.75** | **+0.75** | **+0.33** | **0.00** | **0.00** | **0.00** | **-1.00** | **0.00** | **-0.50** | **-0.02** |

**Overall gain (qwen-skill − qwen-baseline): -0.02**

## Failure breakdown (FAIL cells only)

| Skill | Capability | Failure | tokens | seconds | reward | qwen baseline | gain |
|---|---|---|---:|---:|---:|---:|---:|
| `doc-process-4.1.1` | `cap-write-markdown` | 1/1 discriminator classes failed: TestOutputs | 513 | 24 | 0.00 | 1.00 | -1.00 |
| `document-format-converter-1.0.0` | `cap-read-pdf` | AgentTimeoutError | 0 | 319 | 0.00 | 1.00 | -1.00 |
| `document-format-converter-1.0.0` | `cap-read-rtf` | AgentTimeoutError | 0 | 319 | 0.00 | 0.00 | 0.00 |
| `document-format-converter-1.0.0` | `cap-write-markdown` | 1/1 discriminator classes failed: TestOutputs | 494 | 25 | 0.00 | 1.00 | -1.00 |
| `document-format-converter-1.0.0` | `cap-write-pdf` | 1/1 discriminator classes failed: TestOutputs | 2225 | 44 | 0.00 | 0.00 | 0.00 |
| `document-reader-1.0.0` | `cap-read-pdf` | AgentTimeoutError | 0 | 318 | 0.00 | 1.00 | -1.00 |
| `document-reader-1.0.0` | `cap-read-pptx` | AgentTimeoutError | 0 | 319 | 0.00 | 0.00 | 0.00 |
| `document-reader-1.0.0` | `cap-read-rtf` | 1/1 discriminator classes failed: TestOutputs | 4297 | 55 | 0.00 | 0.00 | 0.00 |
| `document-translate-0.1.0` | `cap-read-pdf` | AgentTimeoutError | 0 | 319 | 0.00 | 1.00 | -1.00 |
| `document-translate-0.1.0` | `cap-write-pdf` | 1/1 discriminator classes failed: TestOutputs | 5387 | 67 | 0.00 | 0.00 | 0.00 |
| `document-translate-0.1.0` | `cap-write-xlsx` | 1/1 discriminator classes failed: TestOutputs | 1843 | 36 | 0.00 | 1.00 | -1.00 |
| `docx-compare-1.0.2` | `cap-read-docx` | AgentTimeoutError | 0 | 318 | 0.00 | 1.00 | -1.00 |

## Skill ranking by avg gain

| Skill | avg gain | row pass-rate | row avg reward |
|---|---:|---:|---:|
| `doc-process-4.1.1` | **+0.15** | 12/13 | 0.92 |
| `document-format-converter-1.0.0` | **0.00** | 11/15 | 0.73 |
| `document-reader-1.0.0` | **-0.11** | 6/9 | 0.67 |
| `document-translate-0.1.0` | **-0.17** | 3/6 | 0.50 |
| `docx-compare-1.0.2` | **-1.00** | 0/1 | 0.00 |

## Capability ranking by avg gain (across skills that declare it)

| Capability | avg gain | qwen baseline | qwen avg skill reward |
|---|---:|---:|---:|
| `cap-read-image` | **+1.00** | 0.00 | 1.00 |
| `cap-read-pptx` | **+0.75** | 0.00 | 0.75 |
| `cap-read-rtf` | **+0.33** | 0.00 | 0.33 |
| `cap-read-html` | **0.00** | 1.00 | 1.00 |
| `cap-read-json` | **0.00** | 1.00 | 1.00 |
| `cap-read-markdown` | **0.00** | 1.00 | 1.00 |
| `cap-read-odt` | **0.00** | 1.00 | 1.00 |
| `cap-read-xlsx` | **0.00** | 1.00 | 1.00 |
| `cap-transform-tabular-to-json` | **0.00** | 1.00 | 1.00 |
| `cap-write-json` | **0.00** | 1.00 | 1.00 |
| `cap-write-pdf` | **0.00** | 0.00 | 0.00 |
| `cap-read-docx` | **-0.20** | 1.00 | 0.80 |
| `cap-write-xlsx` | **-0.50** | 1.00 | 0.50 |
| `cap-read-pdf` | **-0.75** | 1.00 | 0.25 |
| `cap-write-markdown` | **-1.00** | 1.00 | 0.00 |

## qwen3.6-flash vs glm-5.1 (same skill batch, same baseline batch)

| Metric | qwen3.6-flash | glm-5.1 |
|---|---:|---:|
| Skill wallclock | 3529s (58.8 min) | 4189s (69.8 min) |
| Baseline wallclock | 1164s | 1206s |
| Skill PASS / declared | 32/44 (73%) | 35/44 (80%) |
| Baseline PASS / declared | 11/15 (73%) | 12/15 (80%) |
| Skill avg reward | 0.73 | 0.80 |
| Overall gain (skill − same-model baseline) | **-0.02** | **-0.07** |
| Skill total tokens | 50,305 | 25,019 |
| Skill avg tokens / cell | 1143 | 569 |

### Baseline cells where qwen and glm disagree

| Capability | qwen baseline | glm baseline |
|---|---|---|
| `cap-read-pptx` | FAIL(AgentTimeoutError) | PASS |
| `cap-read-rtf` | FAIL(1/1 discriminator classes fail) | PASS |
| `cap-write-xlsx` | PASS | FAIL(1/1 discriminator classes fail) |
