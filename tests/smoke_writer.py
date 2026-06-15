"""Smoke test for TaskBundleWriter (no LLM).

Builds one synthetic GeneratedTask, materializes it under a temp dir,
prints the resulting SkillsBench task layout.

Run:
    python -m dynamic_skill_eval_v2.tests.smoke_writer
"""

from __future__ import annotations

import pathlib
import tempfile

from dynamic_skill_eval_v2.task_generation import (
    CandidateSolution,
    GeneratedTask,
    TaskBundleWriter,
    TaskInputFile,
)


def build_sample_task() -> GeneratedTask:
    return GeneratedTask(
        task_id="extract-receipt-total-from-txt",
        name="extract-receipt-total",
        query="我想对比两个 skill 提取小票的能力",
        candidate_solutions=[
            CandidateSolution(
                skill_id="document-reader-1.0.0",
                capability_id="read-plain-text",
                approach="直接读 txt 后正则提取总计行",
            ),
            CandidateSolution(
                skill_id="document-format-converter-1.0.0",
                capability_id="txt-to-csv",
                approach="转 csv 后取最后行总计",
            ),
        ],
        instruction_md=(
            "Read /root/receipt.txt and write a JSON object to /root/result.json "
            "with keys total_amount (number) and currency (string)."
        ),
        assets=[
            TaskInputFile(  # alias of TaskAsset
                path="receipt.txt",
                content=(
                    "Walmart\n"
                    "商品A 3.50\n"
                    "商品B 4.25\n"
                    "商品C 1.50\n"
                    "合计 12.75\n"
                    "货币 CNY\n"
                ),
            )
        ],
        tests_py=(
            "import json, os\n"
            "\n"
            "class TestOutputs:\n"
            "    def test_file(self):\n"
            "        assert os.path.exists('/root/result.json')\n"
            "\n"
            "    def test_values(self):\n"
            "        d = json.load(open('/root/result.json'))\n"
            "        assert d['total_amount'] == 12.75\n"
            "        assert d['currency'] == 'CNY'\n"
        ),
        task_toml_extras={
            "difficulty": "easy",
            "category": "document-processing",
            "task_type": ["extraction"],
            "modality": ["text", "json"],
            "tags": ["receipt", "amount"],
        },
    )


def main() -> int:
    task = build_sample_task()
    with tempfile.TemporaryDirectory() as tmp:
        out = TaskBundleWriter().write(task, tmp)
        print(f"written to: {out}")
        for path in sorted(pathlib.Path(out).rglob("*")):
            if path.is_file():
                print(f"  {path.relative_to(out)}")
        for name in ("task.toml", "candidate_solutions.json",
                     "environment/Dockerfile", "tests/test_outputs.py"):
            print(f"\n--- {name} ---")
            print((out / name).read_text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
