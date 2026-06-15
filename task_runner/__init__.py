"""TaskRunner — execute a generated SkillsBench task and score it.

Two modes available:

* :class:`SkillRunner` (local) — runs the LLM-generated bash on the host.
  Fast, no Docker; but the LLM can freely ``pip install`` anything and
  ignore the skill's declared boundaries. Use for smoke tests.

* :class:`HarborSkillRunner` (sandboxed) — drives Harbor's Docker backend
  with the candidate skill mounted via ``--skill`` and the terminus-2
  skills-aware agent injecting the skill block into every prompt. Use for
  real evaluation; matches the v1 ``HarborExecutionRunner`` flow.
"""

from dynamic_skill_eval_v2.task_runner.harbor_runner import (
    DEFAULT_TERMINUS_AGENT,
    HarborRunResult,
    HarborSkillRunner,
)
from dynamic_skill_eval_v2.task_runner.runner import (
    DiscriminatorOutcome,
    RunResult,
    SkillRunner,
)

__all__ = [
    "DEFAULT_TERMINUS_AGENT",
    "DiscriminatorOutcome",
    "HarborRunResult",
    "HarborSkillRunner",
    "RunResult",
    "SkillRunner",
]
