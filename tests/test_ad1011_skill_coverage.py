"""AD-1011: ship-wide skill coverage (#815 view 1).

Inverts every crew agent's skill profile into a skill->holders map joined against
the full registry, so unheld skills surface as coverage gaps.

BF-287: real SkillRegistry + AgentSkillService (tmp SQLite) + a real
SimpleNamespace registry/ontology/callsign stub — no MagicMock at the substrate
boundary.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from probos.routers.skills import skills_coverage
from probos.skill_framework import (
    AgentSkillService,
    ProficiencyLevel,
    SkillCategory,
    SkillDefinition,
    SkillRegistry,
)


async def _registry(tmp_path: Path, *skill_ids: str) -> SkillRegistry:
    reg = SkillRegistry(db_path=str(tmp_path / "skill_registry.db"))
    await reg.start()
    for sid in skill_ids:
        await reg.register_skill(SkillDefinition(
            skill_id=sid, name=sid.replace("-", " ").title(),
            category=SkillCategory.ROLE, description=f"{sid} skill", domain="*",
        ))
    return reg


async def _service(tmp_path: Path, registry: SkillRegistry) -> AgentSkillService:
    svc = AgentSkillService(db_path=str(tmp_path / "skills.db"), registry=registry)
    await svc.start()
    return svc


class _Registry:
    def __init__(self, agents):
        self._agents = list(agents)

    def all(self):
        return list(self._agents)


class _Ontology:
    def __init__(self, crew_types):
        self._crew = set(crew_types)

    def get_crew_agent_types(self):
        return self._crew


class _Callsigns:
    def __init__(self, mapping):
        self._m = mapping

    def get_callsign(self, agent_type):
        return self._m.get(agent_type, "")


def _agent(agent_id, agent_type):
    return SimpleNamespace(id=agent_id, agent_type=agent_type)


async def _runtime(tmp_path, *, agents, registry, service):
    return SimpleNamespace(
        skill_registry=registry,
        skill_service=service,
        registry=_Registry(agents),
        ontology=_Ontology({a.agent_type for a in agents}),
        callsign_registry=_Callsigns({a.agent_type: a.agent_type.title() for a in agents}),
    )


# ---------------------------------------------------------------------------
# coverage aggregation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_coverage_inverts_profiles_to_holders(tmp_path: Path):
    reg = await _registry(tmp_path, "active-listening", "diagnostics", "warp-theory")
    svc = await _service(tmp_path, reg)
    # ezri holds active-listening; yeo holds active-listening + diagnostics;
    # warp-theory is held by nobody (a coverage gap).
    await svc.acquire_skill("ezri-1", "active-listening", source="commission", proficiency=ProficiencyLevel.APPLY)
    await svc.acquire_skill("yeo-1", "active-listening", source="commission", proficiency=ProficiencyLevel.FOLLOW)
    await svc.acquire_skill("yeo-1", "diagnostics", source="commission", proficiency=ProficiencyLevel.LEAD)
    rt = await _runtime(tmp_path, agents=[_agent("ezri-1", "counselor"), _agent("yeo-1", "yeoman")],
                        registry=reg, service=svc)

    body = await skills_coverage(rt)
    by_id = {s["skill_id"]: s for s in body["skills"]}
    assert body["crew_count"] == 2
    # most-held first
    assert body["skills"][0]["skill_id"] == "active-listening"
    assert by_id["active-listening"]["holder_count"] == 2
    holders = {h["agent_id"] for h in by_id["active-listening"]["holders"]}
    assert holders == {"ezri-1", "yeo-1"}
    assert by_id["diagnostics"]["holder_count"] == 1
    # the unheld skill is a gap
    assert by_id["warp-theory"]["holder_count"] == 0
    assert by_id["warp-theory"]["gap"] is True
    assert body["gap_count"] == 1
    await svc.stop()


@pytest.mark.asyncio
async def test_coverage_holder_carries_callsign_and_proficiency(tmp_path: Path):
    reg = await _registry(tmp_path, "active-listening")
    svc = await _service(tmp_path, reg)
    await svc.acquire_skill("ezri-1", "active-listening", source="commission", proficiency=ProficiencyLevel.APPLY)
    rt = await _runtime(tmp_path, agents=[_agent("ezri-1", "counselor")], registry=reg, service=svc)
    body = await skills_coverage(rt)
    holder = body["skills"][0]["holders"][0]
    assert holder["callsign"] == "Counselor"
    assert holder["proficiency"] == ProficiencyLevel.APPLY.value
    assert holder["proficiency_label"] == "apply"
    await svc.stop()


@pytest.mark.asyncio
async def test_coverage_all_gaps_when_no_skills_acquired(tmp_path: Path):
    reg = await _registry(tmp_path, "active-listening", "diagnostics")
    svc = await _service(tmp_path, reg)
    rt = await _runtime(tmp_path, agents=[_agent("ezri-1", "counselor")], registry=reg, service=svc)
    body = await skills_coverage(rt)
    assert body["gap_count"] == 2
    assert all(s["gap"] for s in body["skills"])
    await svc.stop()


@pytest.mark.asyncio
async def test_coverage_honest_degrade_no_service():
    rt = SimpleNamespace(skill_registry=object(), skill_service=None, registry=object())
    assert await skills_coverage(rt) == {"skills": [], "crew_count": 0, "gap_count": 0}


@pytest.mark.asyncio
async def test_coverage_non_crew_agents_excluded(tmp_path: Path):
    reg = await _registry(tmp_path, "active-listening")
    svc = await _service(tmp_path, reg)
    await svc.acquire_skill("tool-1", "active-listening", source="commission", proficiency=ProficiencyLevel.FOLLOW)
    # ontology says only 'counselor' is crew; the tool agent is excluded.
    rt = SimpleNamespace(
        skill_registry=reg, skill_service=svc,
        registry=_Registry([_agent("tool-1", "file_reader")]),
        ontology=_Ontology({"counselor"}),
        callsign_registry=_Callsigns({}),
    )
    body = await skills_coverage(rt)
    assert body["crew_count"] == 0
    assert body["skills"][0]["holder_count"] == 0  # the tool agent didn't count
    await svc.stop()
