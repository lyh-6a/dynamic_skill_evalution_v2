"""task_generation — turn a user query + SkillExtractions into SkillsBench tasks.

Flow:
    user query  +  SkillExtraction(s)
        │
        ▼   TaskGenerator   (one LLM call)
              picks comparable skills, designs concrete cross-skill task,
              produces instruction / assets (text + binary renderers) /
              ground_truth / solution_py / tests_py / candidate_solutions
        │
        ▼   GeneratedTask[]
        │
        ▼   TaskValidator    (host-side self-check)
              run renderers → run solution → run pytest;
              keep only tasks whose own solution + tests agree
        │
        ▼   TaskBundleWriter
              materializes each surviving task as a SkillsBench-compatible
              directory (including environment/, tests/, solution/)
"""

from dynamic_skill_eval_v2.task_generation.bundle_writer import TaskBundleWriter
from dynamic_skill_eval_v2.task_generation.generator import TaskGenerator
from dynamic_skill_eval_v2.task_generation.schema import (
    SCHEMA_VERSION,
    CandidateSolution,
    Discriminator,
    DiscriminatorTest,
    GeneratedTask,
    TaskAsset,
    TaskBatch,
    TaskInputFile,  # back-compat alias of TaskAsset
)
from dynamic_skill_eval_v2.task_generation.validator import (
    TaskValidator,
    ValidationReport,
)

__all__ = [
    "SCHEMA_VERSION",
    "CandidateSolution",
    "Discriminator",
    "DiscriminatorTest",
    "GeneratedTask",
    "TaskAsset",
    "TaskBatch",
    "TaskBundleWriter",
    "TaskGenerator",
    "TaskInputFile",
    "TaskValidator",
    "ValidationReport",
]
