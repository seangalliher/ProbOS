from __future__ import annotations

from dataclasses import dataclass

import pytest

from probos.cognitive.qual_skill_bridge import QualificationSkillBridge, SkillAdvancement
from probos.skill_framework import AgentSkillRecord, ProficiencyLevel, SkillProfile


@dataclass
class _UpdateCall:
    agent_id: str
    skill_id: str
    new_level: ProficiencyLevel
    source: str
    notes: str


class _FakeSkillService:
    def __init__(self, profile: SkillProfile) -> None:
        self._profile = profile
        self.update_calls: list[_UpdateCall] = []

    async def get_profile(self, agent_id: str) -> SkillProfile:
        return self._profile

    async def update_proficiency(
        self,
        agent_id: str,
        skill_id: str,
        new_level: ProficiencyLevel,
        source: str = "assessment",
        notes: str = "",
    ) -> AgentSkillRecord | None:
        self.update_calls.append(_UpdateCall(agent_id, skill_id, new_level, source, notes))
        return AgentSkillRecord(agent_id=agent_id, skill_id=skill_id, proficiency=new_level)


def _profile_with_skill(
    *,
    agent_id: str = "agent-1",
    skill_id: str = "threat_analysis",
    proficiency: ProficiencyLevel = ProficiencyLevel.FOLLOW,
) -> SkillProfile:
    return SkillProfile(
        agent_id=agent_id,
        role_skills=[
            AgentSkillRecord(
                agent_id=agent_id,
                skill_id=skill_id,
                proficiency=proficiency,
            ),
        ],
    )


def test_skill_advancement_creation() -> None:
    advancement = SkillAdvancement(
        agent_id="agent-1",
        skill_id="threat_analysis",
        from_level=1,
        to_level=2,
        qualification_test="threat_analysis_t1",
        qualification_score=0.85,
        reason="test",
    )

    assert advancement.agent_id == "agent-1"
    assert advancement.skill_id == "threat_analysis"
    assert advancement.from_level == 1
    assert advancement.to_level == 2
    assert advancement.qualification_test == "threat_analysis_t1"
    assert advancement.qualification_score == 0.85


def test_register_mapping() -> None:
    bridge = QualificationSkillBridge()

    bridge.register_mapping("threat_analysis_t1", "threat_analysis")

    assert bridge.get_mappings() == {"threat_analysis_t1": "threat_analysis"}


@pytest.mark.asyncio
async def test_process_qualification_no_mapping() -> None:
    bridge = QualificationSkillBridge(skill_service=_FakeSkillService(_profile_with_skill()))

    advancement = await bridge.process_qualification(
        agent_id="agent-1",
        test_name="unknown_t1",
        score=1.0,
        passed=True,
    )

    assert advancement is None


@pytest.mark.asyncio
async def test_process_qualification_failed() -> None:
    skill_service = _FakeSkillService(_profile_with_skill())
    bridge = QualificationSkillBridge(skill_service=skill_service)
    bridge.register_mapping("threat_analysis_t1", "threat_analysis")

    advancement = await bridge.process_qualification(
        agent_id="agent-1",
        test_name="threat_analysis_t1",
        score=1.0,
        passed=False,
    )

    assert advancement is None
    assert skill_service.update_calls == []


@pytest.mark.asyncio
async def test_process_qualification_below_threshold() -> None:
    skill_service = _FakeSkillService(_profile_with_skill())
    bridge = QualificationSkillBridge(skill_service=skill_service)
    bridge.register_mapping("threat_analysis_t1", "threat_analysis")

    advancement = await bridge.process_qualification(
        agent_id="agent-1",
        test_name="threat_analysis_t1",
        score=0.3,
        passed=True,
    )

    assert advancement is None
    assert skill_service.update_calls == []


@pytest.mark.asyncio
async def test_process_qualification_advances() -> None:
    skill_service = _FakeSkillService(_profile_with_skill())
    bridge = QualificationSkillBridge(skill_service=skill_service)
    bridge.register_mapping("threat_analysis_t1", "threat_analysis")

    advancement = await bridge.process_qualification(
        agent_id="agent-1",
        test_name="threat_analysis_t1",
        score=0.6,
        passed=True,
    )

    assert advancement is not None
    assert advancement.from_level == 1
    assert advancement.to_level == 2
    assert len(skill_service.update_calls) == 1
    assert skill_service.update_calls[0].new_level is ProficiencyLevel.ASSIST
    assert skill_service.update_calls[0].source == "qualification"


@pytest.mark.asyncio
async def test_advancement_history() -> None:
    skill_service = _FakeSkillService(_profile_with_skill())
    bridge = QualificationSkillBridge(skill_service=skill_service)
    bridge.register_mapping("threat_analysis_t1", "threat_analysis")

    first = await bridge.process_qualification(
        agent_id="agent-1",
        test_name="threat_analysis_t1",
        score=0.6,
        passed=True,
    )
    second = await bridge.process_qualification(
        agent_id="agent-1",
        test_name="threat_analysis_t1",
        score=0.7,
        passed=True,
    )

    assert bridge.get_advancement_history(agent_id="agent-1") == [first, second]
    assert bridge.get_advancement_history(agent_id="other-agent") == []
