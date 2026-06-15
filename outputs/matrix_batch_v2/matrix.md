# Capability × Skill Matrix

- batch: `/tmp/matrix_batch_v2`
- baseline: `/tmp/baseline_batch_v2` (`without-skill` placeholder, no skill mounted)
- skills: 5  ·  capabilities: 15  ·  declared cells: 44

## Baseline (no-skill agent reward)

| Capability | reward | pass_rate | failure |
| --- | ---: | ---: | --- |
| read-docx | 1.00 | 1.00 |  |
| read-html | 1.00 | 1.00 |  |
| read-image | 0.00 | 0.00 | AgentTimeoutError |
| read-json | 1.00 | 1.00 |  |
| read-markdown | 1.00 | 1.00 |  |
| read-odt | 1.00 | 1.00 |  |
| read-pdf | 1.00 | 1.00 |  |
| read-pptx | 1.00 | 1.00 |  |
| read-rtf | 1.00 | 1.00 |  |
| read-xlsx | 1.00 | 1.00 |  |
| transform-tabular-to-json | 1.00 | 1.00 |  |
| write-json | 1.00 | 1.00 |  |
| write-markdown | 1.00 | 1.00 |  |
| write-pdf | 0.00 | 0.00 | AgentTimeoutError |
| write-xlsx | 0.00 | 0.00 | 1/1 discriminator classes failed: TestOutputs |

## Strict Score Matrix (skill reward)

| Skill | read-docx | read-html | read-image | read-json | read-markdown | read-odt | read-pdf | read-pptx | read-rtf | read-xlsx | transform-tabular-to-json | write-json | write-markdown | write-pdf | write-xlsx | row mean |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| doc-process-4-1-1 | 1.00 | 1.00 | 0.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | — | — | **0.92** |
| document-format-converter-1-0-0 | 1.00 | 1.00 | 0.00 | 1.00 | 1.00 | 1.00 | 0.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 | 1.00 | **0.80** |
| document-reader-1-0-0 | 1.00 | 0.00 | — | — | 1.00 | 1.00 | 1.00 | 0.00 | 1.00 | 1.00 | 1.00 | — | — | — | — | **0.78** |
| document-translate-0-1-0 | 1.00 | — | — | — | — | — | 0.00 | 1.00 | — | 1.00 | — | — | — | 0.00 | 0.00 | **0.50** |
| docx-compare-1-0-2 | 1.00 | — | — | — | — | — | — | — | — | — | — | — | — | — | — | **1.00** |
| **col mean** | **1.00** | **0.67** | **0.00** | **1.00** | **1.00** | **1.00** | **0.50** | **0.75** | **1.00** | **1.00** | **1.00** | **1.00** | **1.00** | **0.00** | **0.50** | **0.80** |

## Pass-rate Matrix

| Skill | read-docx | read-html | read-image | read-json | read-markdown | read-odt | read-pdf | read-pptx | read-rtf | read-xlsx | transform-tabular-to-json | write-json | write-markdown | write-pdf | write-xlsx | row mean |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| doc-process-4-1-1 | 1.00 | 1.00 | 0.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | — | — | **0.92** |
| document-format-converter-1-0-0 | 1.00 | 1.00 | 0.00 | 1.00 | 1.00 | 1.00 | 0.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 | 1.00 | **0.80** |
| document-reader-1-0-0 | 1.00 | 0.00 | — | — | 1.00 | 1.00 | 1.00 | 0.00 | 1.00 | 1.00 | 1.00 | — | — | — | — | **0.78** |
| document-translate-0-1-0 | 1.00 | — | — | — | — | — | 0.00 | 1.00 | — | 1.00 | — | — | — | 0.00 | 0.00 | **0.50** |
| docx-compare-1-0-2 | 1.00 | — | — | — | — | — | — | — | — | — | — | — | — | — | — | **1.00** |
| **col mean** | **1.00** | **0.67** | **0.00** | **1.00** | **1.00** | **1.00** | **0.50** | **0.75** | **1.00** | **1.00** | **1.00** | **1.00** | **1.00** | **0.00** | **0.50** | **0.80** |

## Gain Matrix (skill reward − no-skill baseline)

| Skill | read-docx | read-html | read-image | read-json | read-markdown | read-odt | read-pdf | read-pptx | read-rtf | read-xlsx | transform-tabular-to-json | write-json | write-markdown | write-pdf | write-xlsx | row mean |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| doc-process-4-1-1 | +0.00 | +0.00 | +0.00 | +0.00 | +0.00 | +0.00 | +0.00 | +0.00 | +0.00 | +0.00 | +0.00 | +0.00 | +0.00 | — | — | **+0.00** |
| document-format-converter-1-0-0 | +0.00 | +0.00 | +0.00 | +0.00 | +0.00 | +0.00 | -1.00 | +0.00 | +0.00 | +0.00 | +0.00 | +0.00 | +0.00 | +0.00 | +1.00 | **+0.00** |
| document-reader-1-0-0 | +0.00 | -1.00 | — | — | +0.00 | +0.00 | +0.00 | -1.00 | +0.00 | +0.00 | +0.00 | — | — | — | — | **-0.22** |
| document-translate-0-1-0 | +0.00 | — | — | — | — | — | -1.00 | +0.00 | — | +0.00 | — | — | — | +0.00 | +0.00 | **-0.17** |
| docx-compare-1-0-2 | +0.00 | — | — | — | — | — | — | — | — | — | — | — | — | — | — | **+0.00** |
| **col mean** | **+0.00** | **-0.33** | **+0.00** | **+0.00** | **+0.00** | **+0.00** | **-0.50** | **-0.25** | **+0.00** | **+0.00** | **+0.00** | **+0.00** | **+0.00** | **+0.00** | **+0.50** | **-0.07** |

## Failure breakdown

| Skill | Capability | reward | baseline | gain | failure | tokens | seconds |
| --- | --- | ---: | ---: | ---: | --- | ---: | ---: |
| doc-process-4-1-1 | read-image | 0.00 | 0.00 | +0.00 | AgentTimeoutError | 0 | 322.9 |
| document-format-converter-1-0-0 | read-image | 0.00 | 0.00 | +0.00 | AgentTimeoutError | 0 | 335.1 |
| document-format-converter-1-0-0 | read-pdf | 0.00 | 1.00 | -1.00 | AgentTimeoutError | 0 | 345.0 |
| document-format-converter-1-0-0 | write-pdf | 0.00 | 0.00 | +0.00 | 1/1 discriminator classes failed: TestOutputs | 866 | 163.4 |
| document-reader-1-0-0 | read-html | 0.00 | 1.00 | -1.00 | 1/1 discriminator classes failed: TestOutputs | 282 | 43.9 |
| document-reader-1-0-0 | read-pptx | 0.00 | 1.00 | -1.00 | AgentTimeoutError | 0 | 338.2 |
| document-translate-0-1-0 | read-pdf | 0.00 | 1.00 | -1.00 | AgentTimeoutError | 0 | 334.5 |
| document-translate-0-1-0 | write-pdf | 0.00 | 0.00 | +0.00 | 1/1 discriminator classes failed: TestOutputs | 1712 | 126.2 |
| document-translate-0-1-0 | write-xlsx | 0.00 | 0.00 | +0.00 | 1/1 discriminator classes failed: TestOutputs | 1092 | 84.2 |

## Skill ranking (mean over declared cells)

| Skill | declared | passed | mean reward | mean baseline | mean gain |
| --- | ---: | ---: | ---: | ---: | ---: |
| doc-process-4-1-1 | 13 | 12 | 0.92 | 0.92 | **+0.00** |
| document-format-converter-1-0-0 | 15 | 12 | 0.80 | 0.80 | **+0.00** |
| docx-compare-1-0-2 | 1 | 1 | 1.00 | 1.00 | **+0.00** |
| document-translate-0-1-0 | 6 | 3 | 0.50 | 0.67 | **-0.17** |
| document-reader-1-0-0 | 9 | 7 | 0.78 | 1.00 | **-0.22** |

## Capability ranking (mean gain across skills declaring it)

| Capability | skills | passed | mean reward | baseline | mean gain |
| --- | ---: | ---: | ---: | ---: | ---: |
| write-xlsx | 2 | 1 | 0.50 | 0.00 | **+0.50** |
| read-docx | 5 | 5 | 1.00 | 1.00 | **+0.00** |
| read-image | 2 | 0 | 0.00 | 0.00 | **+0.00** |
| read-json | 2 | 2 | 1.00 | 1.00 | **+0.00** |
| read-markdown | 3 | 3 | 1.00 | 1.00 | **+0.00** |
| read-odt | 3 | 3 | 1.00 | 1.00 | **+0.00** |
| read-rtf | 3 | 3 | 1.00 | 1.00 | **+0.00** |
| read-xlsx | 4 | 4 | 1.00 | 1.00 | **+0.00** |
| transform-tabular-to-json | 3 | 3 | 1.00 | 1.00 | **+0.00** |
| write-json | 2 | 2 | 1.00 | 1.00 | **+0.00** |
| write-markdown | 2 | 2 | 1.00 | 1.00 | **+0.00** |
| write-pdf | 2 | 0 | 0.00 | 0.00 | **+0.00** |
| read-pptx | 4 | 3 | 0.75 | 1.00 | **-0.25** |
| read-html | 3 | 2 | 0.67 | 1.00 | **-0.33** |
| read-pdf | 4 | 2 | 0.50 | 1.00 | **-0.50** |
