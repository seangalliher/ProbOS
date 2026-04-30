"""Qualification → Skill Bridge (AD-566f).

Bridges QualificationStore test results to SkillFramework
proficiency updates. When an agent passes qualification tests
at a sufficient score, their skill proficiency is advanced.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from probos.skill_framework import AgentSkillService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SkillAdvancement:
    """Record of a qualification-triggered skill advancement (AD-566f)."""

    agent_id: str
    skill_id: str
    from_level: int
    to_level: int
    qualification_test: str
    qualification_score: float
    reason: str = ""


DEFAULT_SCORE_THRESHOLDS: dict[int, float] = {
    2: 0.50,
    3: 0.60,
    4: 0.70,
    5: 0.80,
    6: 0.90,
    7: 0.95,
}


class QualificationSkillBridge:
    """Maps qualification test results to skill proficiency updates (AD-566f)."""

    def __init__(
        self,
        *,
        skill_service: AgentSkillService | None = None,
        qualification_store: Any = None,
        score_thresholds: dict[int, float] | None = None,
    ) -> None:
        self._skill_service = skill_service
        self._qualification_store = qualification_store
        self._score_thresholds = score_thresholds or dict(DEFAULT_SCORE_THRESHOLDS)
        self._test_skill_map: dict[str, str] = {}
        self._advancement_history: list[SkillAdvancement] = []

    def register_mapping(self, test_name: str, skill_id: str) -> None:
        """Map a qualification test to a skill."""
        self._test_skill_map[test_name] = skill_id

    def register_mappings(self, mappings: dict[str, str]) -> None:
        """Register multiple test to skill mappings."""
        self._test_skill_map.update(mappings)

    async def process_qualification(
        self,
        agent_id: str,
        test_name: str,
        score: float,
        passed: bool,
    ) -> SkillAdvancement | None:
        """Process a qualification result and potentially advance skill."""
        if not passed:
            return None

        skill_id = self._test_skill_map.get(test_name)
        if not skill_id:
            logger.debug(
                "AD-566f: Mapping absent for qualification test %s; skill proficiency unchanged",
                test_name,
            )
            return None

        if not self._skill_service:
            return None

        profile = await self._skill_service.get_profile(agent_id)
        current_record = None
        for skill in profile.all_skills:
            if skill.skill_id == skill_id:
                current_record = skill
                break

        if not current_record:
            logger.debug(
                "AD-566f: Agent %s lacks skill record %s; skill proficiency unchanged",
                agent_id[:12], skill_id,
            )
            return None

        current_level = current_record.proficiency.value
        target_level = current_level + 1

        threshold = self._score_thresholds.get(target_level)
        if threshold is None:
            return None

        if score < threshold:
            logger.debug(
                "AD-566f: Qualification score %.2f below %.2f for level %d; skill proficiency unchanged",
                score, threshold, target_level,
            )
            return None

        from probos.skill_framework import ProficiencyLevel

        new_level = ProficiencyLevel(target_level)
        await self._skill_service.update_proficiency(
            agent_id=agent_id,
            skill_id=skill_id,
            new_level=new_level,
            source="qualification",
            notes=f"Qualification test '{test_name}' score={score:.2f}",
        )

        advancement = SkillAdvancement(
            agent_id=agent_id,
            skill_id=skill_id,
            from_level=current_level,
            to_level=target_level,
            qualification_test=test_name,
            qualification_score=score,
            reason=f"Score {score:.2f} >= threshold {threshold:.2f}",
        )
        self._advancement_history.append(advancement)

        logger.info(
            "AD-566f: Advanced agent %s skill %s from level %d to %d after qualification score %.2f",
            agent_id[:12], skill_id, current_level, target_level, score,
        )
        return advancement

    def get_advancement_history(
        self, *, agent_id: str = "", limit: int = 50,
    ) -> list[SkillAdvancement]:
        """Query advancement history."""
        results = self._advancement_history
        if agent_id:
            results = [r for r in results if r.agent_id == agent_id]
        return results[-limit:]

    def get_mappings(self) -> dict[str, str]:
        """Return all test to skill mappings."""
        return dict(self._test_skill_map)
