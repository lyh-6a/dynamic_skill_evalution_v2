"""Subclass of HarborTerminus2WithSkills that auto-loads all discovered
skills at setup time, so their full SKILL.md content appears in the
episode-0 ``LOADED SKILLS:`` block.  The agent never has to emit an
explicit ``load_skill`` call and sees the skill instructions from the
very first turn.

Usage (import path for ``--agent-import-path``)::

    dynamic_skill_eval_v2.task_runner.forced_skill_agent:HarborTerminus2ForcedSkills
"""

from libs.terminus_agent.agents.terminus_2.harbor_terminus_2_skills import (
    HarborTerminus2WithSkills,
)
from harbor.environments.base import BaseEnvironment


class HarborTerminus2ForcedSkills(HarborTerminus2WithSkills):
    """Same as HarborTerminus2WithSkills but pre-loads every discovered skill
    during ``setup()`` so the in-context skill block is populated from episode 0.
    """

    async def setup(self, environment: BaseEnvironment) -> None:
        await super().setup(environment)
        # Auto-load every discovered skill so their full SKILL.md text is
        # available in the prompt's LOADED SKILLS: block immediately.
        for skill in self._skills_metadata:
            name = skill["name"]
            if name in self._loaded_skills:
                continue
            content = await self._skill_loader.load_skill(name, self._skill_dirs)
            if content:
                self._loaded_skills[name] = content