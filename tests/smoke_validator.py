"""Smoke test for TaskValidator + TaskBundleWriter on a binary asset (PDF).

Builds a synthetic receipt task whose input is a rendered PDF:
  - renderer_py:  uses reportlab to draw the receipt onto a PDF
  - solution_py:  uses pypdf to extract text and parse fields back to JSON
  - tests_py:     asserts on the JSON

Runs the full validator chain on the host, then materializes the task dir
and prints the resulting layout.

The validator pip-installs ``reportlab`` and ``pypdf`` if missing.

Run:
    python -m dynamic_skill_eval_v2.tests.smoke_validator
"""

from __future__ import annotations

import pathlib
import tempfile

from dynamic_skill_eval_v2.task_generation import (
    CandidateSolution,
    GeneratedTask,
    TaskAsset,
    TaskBundleWriter,
    TaskValidator,
)


RENDERER_PY = r"""
import json, os
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A6

gt = json.load(open(os.environ['GROUND_TRUTH_PATH']))
out = os.environ['OUTPUT_PATH']

c = canvas.Canvas(out, pagesize=A6)
W, H = A6
c.setFont('Courier-Bold', 12)

lines = [gt['merchant'], '-' * 24]
for it in gt['items']:
    lines.append(f"{it['name']:<10} {it['price']:>6.2f}")
lines += [
    '-' * 24,
    f"Subtotal {gt['subtotal']:>6.2f}",
    f"Tax      {gt['tax']:>6.2f}",
    f"Total    {gt['total']:>6.2f}",
    f"Currency {gt['currency']}",
]

y = H - 30
for ln in lines:
    c.drawString(20, y, ln)
    y -= 18

c.showPage()
c.save()
"""

SOLUTION_PY = r"""
import json, re
from pypdf import PdfReader

reader = PdfReader('/root/receipt.pdf')
text = '\n'.join(p.extract_text() or '' for p in reader.pages)

def num(pat):
    m = re.search(pat, text)
    return float(m.group(1)) if m else None

merchant_match = re.search(r'^([A-Za-z][A-Za-z ]+?)\s*$', text.strip().splitlines()[0])
result = {
    'merchant':  merchant_match.group(1).strip() if merchant_match else text.strip().splitlines()[0],
    'currency':  (re.search(r'Currency\s+([A-Z]{3})', text) or [None, ''])[1],
    'subtotal':  num(r'Subtotal\s+([0-9.]+)'),
    'tax':       num(r'Tax\s+([0-9.]+)'),
    'total':     num(r'Total\s+([0-9.]+)'),
}
with open('/root/result.json', 'w') as f:
    json.dump(result, f)
"""

TESTS_PY = r"""
import json, os

class TestOutputs:
    def test_file_exists(self):
        assert os.path.exists('/root/result.json')

    def test_fields(self):
        d = json.load(open('/root/result.json'))
        assert d['merchant'].lower().startswith('walmart')
        assert d['currency'] == 'USD'
        assert abs(float(d['subtotal']) - 12.75) < 0.01
        assert abs(float(d['tax'])      -  1.02) < 0.01
        assert abs(float(d['total'])    - 13.77) < 0.01
"""


def build_task() -> GeneratedTask:
    return GeneratedTask(
        task_id="receipt-pdf-cross-skill-smoke",
        name="PDF 小票字段抽取",
        query="我想对比两个 skill 提取 PDF 小票的能力",
        candidate_solutions=[
            CandidateSolution(
                skill_id="doc-process-4.1.1",
                capability_id="form-field-extraction",
                approach="按表单字段抽取商家、商品、金额、税额、总额、币种",
            ),
            CandidateSolution(
                skill_id="document-reader-1.0.0",
                capability_id="read-pdf-text",
                approach="解析 PDF 内嵌文字流后按行 regex",
            ),
        ],
        instruction_md=(
            "Read /root/receipt.pdf and extract structured fields. "
            "Write /root/result.json with keys merchant, currency, subtotal, tax, total."
        ),
        assets=[
            TaskAsset(
                path="receipt.pdf",
                kind="binary",
                renderer_py=RENDERER_PY,
            ),
        ],
        ground_truth={
            "merchant": "Walmart Supercenter",
            "currency": "USD",
            "items": [
                {"name": "Milk",   "price": 3.50},
                {"name": "Bread",  "price": 2.25},
                {"name": "Eggs",   "price": 4.80},
                {"name": "Apples", "price": 2.20},
            ],
            "subtotal": 12.75,
            "tax":       1.02,
            "total":    13.77,
        },
        solution_py=SOLUTION_PY,
        tests_py=TESTS_PY,
        task_toml_extras={
            "difficulty": "medium",
            "category":   "document-processing",
            "task_type":  ["extraction"],
            "modality":   ["pdf", "json"],
            "tags":       ["receipt", "pdf"],
        },
    )


def main() -> int:
    task = build_task()

    print("=== Validating task ===")
    validator = TaskValidator(timeout_sec=120.0, keep_stage=True)
    rep = validator.validate(task)
    print(f"ok={rep.ok}  failed_stage={rep.failed_stage!r}  detail={rep.detail!r}")
    print(f"stage={rep.stage_dir}")
    print(f"rendered: {rep.rendered_assets}")
    if not rep.ok:
        print("\n--- stdout ---\n" + rep.stdout)
        print("\n--- stderr ---\n" + rep.stderr)
        return 1

    print("\n=== Materializing ===")
    with tempfile.TemporaryDirectory() as tmp:
        out = TaskBundleWriter().write(task, tmp)
        print(f"written to: {out}")
        for path in sorted(pathlib.Path(out).rglob("*")):
            if path.is_file():
                rel = path.relative_to(out)
                size = path.stat().st_size
                print(f"  {rel}  ({size} B)")
        # Spot-check: instruction + candidate_solutions + ground_truth
        for name in ("instruction.md", "candidate_solutions.json",
                     "ground_truth.json", "solution/solution.py",
                     "tests/test_outputs.py"):
            p = out / name
            if p.exists():
                print(f"\n--- {name} ---")
                print(p.read_text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
