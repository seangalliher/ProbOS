"""AD-428: Tests for the Agent Skill Framework."""

from __future__ import annotations

import time

import pytest
import pytest_asyncio

from probos.skill_framework import (
    AgentSkillRecord,
    AgentSkillService,
    BUILTIN_PCCS,
    ProficiencyLevel,
    ROLE_SKILL_TEMPLATES,
    SkillCategory,
    SkillDefinition,
    SkillProfile,
    SkillRegistry,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def registry(tmp_path):
    db = str(tmp_path / "skills.db")
    reg = SkillRegistry(db_path=db)
    await reg.start()
    yield reg
    await reg.stop()


@pytest_asyncio.fixture
async def service(tmp_path):
    db = str(tmp_path / "skills.db")
    reg = SkillRegistry(db_path=db)
    svc = AgentSkillService(db_path=db, registry=reg)
    await reg.start()
    await reg.register_builtins()
    await svc.start()
    yield svc, reg
    await svc.stop()
    await reg.stop()


# ---------------------------------------------------------------------------
# Test 1: SkillCategory enum values
# ---------------------------------------------------------------------------

def test_skill_category_enum_values():
    assert SkillCategory.PCC.value == "pcc"
    assert SkillCategory.ROLE.value == "role"
    assert SkillCategory.ACQUIRED.value == "acquired"


# ---------------------------------------------------------------------------
# Test 2: ProficiencyLevel ordering
# ---------------------------------------------------------------------------

def test_proficiency_level_ordering():
    assert ProficiencyLevel.FOLLOW < ProficiencyLevel.APPLY < ProficiencyLevel.SHAPE
    assert ProficiencyLevel.FOLLOW.value == 1
    assert ProficiencyLevel.SHAPE.value == 7


# ---------------------------------------------------------------------------
# Test 3: SkillDefinition defaults
# ---------------------------------------------------------------------------

def test_skill_definition_defaults():
    defn = SkillDefinition(skill_id="test", name="Test", category=SkillCategory.PCC)
    assert defn.domain == "*"
    assert defn.prerequisites == []
    assert defn.decay_rate_days == 14


# ---------------------------------------------------------------------------
# Test 4: AgentSkillRecord.to_dict includes proficiency_label
# ---------------------------------------------------------------------------

def test_agent_skill_record_to_dict():
    record = AgentSkillRecord(
        agent_id="worf", skill_id="threat_analysis",
        proficiency=ProficiencyLevel.APPLY,
    )
    d = record.to_dict()
    assert d["proficiency"] == 3
    assert d["proficiency_label"] == "apply"


# ---------------------------------------------------------------------------
# Test 5: SkillProfile depth and breadth
# ---------------------------------------------------------------------------

def test_skill_profile_depth_and_breadth():
    profile = SkillProfile(
        agent_id="worf",
        pccs=[
            AgentSkillRecord(agent_id="worf", skill_id="comm", proficiency=ProficiencyLevel.ASSIST),
            AgentSkillRecord(agent_id="worf", skill_id="duty", proficiency=ProficiencyLevel.ENABLE),
        ],
        role_skills=[
            AgentSkillRecord(agent_id="worf", skill_id="threat", proficiency=ProficiencyLevel.FOLLOW),
        ],
    )
    assert profile.depth == ProficiencyLevel.ENABLE.value  # 4
    # breadth = skills at ASSIST+ (not suspended): comm (ASSIST), duty (ENABLE) = 2
    assert profile.breadth == 2


# ---------------------------------------------------------------------------
# Test 6: SkillProfile.to_dict
# ---------------------------------------------------------------------------

def test_skill_profile_to_dict():
    profile = SkillProfile(
        agent_id="worf",
        pccs=[AgentSkillRecord(agent_id="worf", skill_id="comm", proficiency=ProficiencyLevel.FOLLOW)],
        role_skills=[AgentSkillRecord(agent_id="worf", skill_id="threat", proficiency=ProficiencyLevel.FOLLOW)],
    )
    d = profile.to_dict()
    assert "pccs" in d
    assert "role_skills" in d
    assert "acquired_skills" in d
    assert "depth" in d
    assert "breadth" in d
    assert len(d["pccs"]) == 1
    assert len(d["role_skills"]) == 1


# ---------------------------------------------------------------------------
# Test 7: BUILTIN_PCCS has 7 entries
# ---------------------------------------------------------------------------

def test_builtin_pccs_count():
    assert len(BUILTIN_PCCS) == 7
    assert all(p.category == SkillCategory.PCC for p in BUILTIN_PCCS)


# ---------------------------------------------------------------------------
# Test 8: ROLE_SKILL_TEMPLATES covers all crew types
# ---------------------------------------------------------------------------

def test_role_skill_templates_coverage():
    assert "security_officer" in ROLE_SKILL_TEMPLATES
    assert "engineering_officer" in ROLE_SKILL_TEMPLATES
    assert "scout" in ROLE_SKILL_TEMPLATES
    assert len(ROLE_SKILL_TEMPLATES) >= 7


# ---------------------------------------------------------------------------
# Test 9: SkillRegistry register and get
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_registry_register_and_get(registry):
    defn = SkillDefinition(
        skill_id="custom_skill", name="Custom", category=SkillCategory.ACQUIRED,
    )
    await registry.register_skill(defn)
    got = registry.get_skill("custom_skill")
    assert got is not None
    assert got.skill_id == "custom_skill"
    assert got.category == SkillCategory.ACQUIRED
    all_skills = registry.list_skills()
    assert any(s.skill_id == "custom_skill" for s in all_skills)


# ---------------------------------------------------------------------------
# Test 10: SkillRegistry register_builtins
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_registry_register_builtins(registry):
    await registry.register_builtins()
    pccs = registry.list_skills(category=SkillCategory.PCC)
    assert len(pccs) == 7
    role_skills = registry.list_skills(category=SkillCategory.ROLE)
    assert len(role_skills) > 0


# ---------------------------------------------------------------------------
# Test 11: SkillRegistry list_skills filters
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_registry_list_skills_filters(registry):
    await registry.register_builtins()
    pccs = registry.list_skills(category=SkillCategory.PCC)
    assert len(pccs) == 7
    security_roles = registry.list_skills(category=SkillCategory.ROLE, domain="security")
    assert len(security_roles) > 0
    assert all(s.domain == "security" for s in security_roles)
    universal = registry.list_skills(domain="*")
    assert all(s.domain == "*" for s in universal)


# ---------------------------------------------------------------------------
# Test 12: SkillRegistry get_prerequisites (DAG walk)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_registry_get_prerequisites_dag(registry):
    a = SkillDefinition(skill_id="A", name="A", category=SkillCategory.ROLE)
    b = SkillDefinition(skill_id="B", name="B", category=SkillCategory.ROLE, prerequisites=["A"])
    c = SkillDefinition(skill_id="C", name="C", category=SkillCategory.ROLE, prerequisites=["B"])
    await registry.register_skill(a)
    await registry.register_skill(b)
    await registry.register_skill(c)
    prereqs = registry.get_prerequisites("C")
    assert "A" in prereqs
    assert "B" in prereqs
    assert registry.get_prerequisites("A") == []


# ---------------------------------------------------------------------------
# Test 13: SkillRegistry persists across restart
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_registry_persistence(tmp_path):
    db = str(tmp_path / "skills.db")
    reg1 = SkillRegistry(db_path=db)
    await reg1.start()
    defn = SkillDefinition(skill_id="persist_test", name="PT", category=SkillCategory.ACQUIRED)
    await reg1.register_skill(defn)
    await reg1.stop()

    reg2 = SkillRegistry(db_path=db)
    await reg2.start()
    got = reg2.get_skill("persist_test")
    assert got is not None
    assert got.skill_id == "persist_test"
    await reg2.stop()


# ---------------------------------------------------------------------------
# Test 14: AgentSkillService acquire_skill
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_service_acquire_skill(service):
    svc, reg = service
    record = await svc.acquire_skill("worf", "communication", source="commissioning")
    assert record.proficiency == ProficiencyLevel.FOLLOW
    profile = await svc.get_profile("worf")
    assert any(s.skill_id == "communication" for s in profile.all_skills)


# ---------------------------------------------------------------------------
# Test 15: AgentSkillService commission_agent
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_service_commission_agent(service):
    svc, reg = service
    profile = await svc.commission_agent("worf", "security_officer")
    assert len(profile.pccs) == 7
    assert len(profile.role_skills) > 0
    # All at FOLLOW
    for s in profile.all_skills:
        assert s.proficiency == ProficiencyLevel.FOLLOW


# ---------------------------------------------------------------------------
# Test 16: AgentSkillService prerequisite enforcement
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_service_prerequisite_enforcement(service):
    svc, reg = service
    # Register a skill with prerequisite
    a = SkillDefinition(skill_id="prereq_a", name="A", category=SkillCategory.ROLE)
    c = SkillDefinition(skill_id="prereq_c", name="C", category=SkillCategory.ROLE, prerequisites=["prereq_a"])
    await reg.register_skill(a)
    await reg.register_skill(c)
    # Agent does NOT have prereq_a — should fail
    with pytest.raises(ValueError, match="Prerequisite"):
        await svc.acquire_skill("worf", "prereq_c")


# ---------------------------------------------------------------------------
# Test 17: AgentSkillService prerequisite enforcement — level check
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_service_prerequisite_level_check(service):
    svc, reg = service
    a = SkillDefinition(skill_id="level_a", name="A", category=SkillCategory.ROLE)
    c = SkillDefinition(skill_id="level_c", name="C", category=SkillCategory.ROLE, prerequisites=["level_a"])
    await reg.register_skill(a)
    await reg.register_skill(c)
    # Give agent A at FOLLOW (level 1) — APPLY (3) required
    await svc.acquire_skill("worf", "level_a")
    with pytest.raises(ValueError):
        await svc.acquire_skill("worf", "level_c")
    # Update A to APPLY — should now succeed
    await svc.update_proficiency("worf", "level_a", ProficiencyLevel.APPLY)
    record = await svc.acquire_skill("worf", "level_c")
    assert record.skill_id == "level_c"


# ---------------------------------------------------------------------------
# Test 18: update_proficiency records assessment history
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_proficiency_assessment_history(service):
    svc, reg = service
    await svc.commission_agent("worf", "security_officer")
    record = await svc.update_proficiency(
        "worf", "communication", ProficiencyLevel.APPLY,
        source="holodeck", notes="passed scenario 3",
    )
    assert record is not None
    assert record.proficiency == ProficiencyLevel.APPLY
    assert len(record.assessment_history) >= 1
    entry = record.assessment_history[-1]
    assert entry["source"] == "holodeck"
    assert entry["notes"] == "passed scenario 3"
    assert entry["level"] == 3


# ---------------------------------------------------------------------------
# Test 19: record_exercise updates timestamp and count
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_record_exercise(service):
    svc, reg = service
    await svc.commission_agent("worf", "security_officer")
    profile = await svc.get_profile("worf")
    old_record = profile.pccs[0]
    old_exercised = old_record.last_exercised
    # Small delay to ensure timestamp changes
    import asyncio
    await asyncio.sleep(0.01)
    updated = await svc.record_exercise("worf", old_record.skill_id)
    assert updated is not None
    assert updated.last_exercised > old_exercised
    assert updated.exercise_count == 1


# ---------------------------------------------------------------------------
# Test 20: check_decay drops proficiency after idle period
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_decay_drops_proficiency(service):
    svc, reg = service
    await svc.commission_agent("worf", "security_officer")
    # Update threat_analysis to ASSIST
    await svc.update_proficiency("worf", "threat_analysis", ProficiencyLevel.ASSIST)
    # Set last_exercised to 15 days ago (decay_rate_days=14 for role skills)
    now = time.time()
    fifteen_days_ago = now - (15 * 86400)
    record = await svc._get_record("worf", "threat_analysis")
    record.last_exercised = fifteen_days_ago
    await svc._upsert_record(record)
    # Run decay
    decayed = await svc.check_decay(now=now)
    assert len(decayed) >= 1
    decayed_skill = next(r for r in decayed if r.skill_id == "threat_analysis")
    assert decayed_skill.proficiency.value < ProficiencyLevel.ASSIST.value


# ---------------------------------------------------------------------------
# Test 21: check_decay never drops below FOLLOW
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_decay_never_below_follow(service):
    svc, reg = service
    await svc.commission_agent("worf", "security_officer")
    await svc.update_proficiency("worf", "threat_analysis", ProficiencyLevel.ASSIST)
    # Set last_exercised to 60 days ago — should decay past 0 but clamp at FOLLOW
    now = time.time()
    sixty_days_ago = now - (60 * 86400)
    record = await svc._get_record("worf", "threat_analysis")
    record.last_exercised = sixty_days_ago
    await svc._upsert_record(record)
    await svc.check_decay(now=now)
    updated = await svc._get_record("worf", "threat_analysis")
    assert updated.proficiency == ProficiencyLevel.FOLLOW
    assert updated.proficiency.value >= 1


# ---------------------------------------------------------------------------
# Test 22: check_prerequisites returns met/missing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_prerequisites(service):
    svc, reg = service
    a = SkillDefinition(skill_id="check_a", name="A", category=SkillCategory.ROLE)
    b = SkillDefinition(skill_id="check_b", name="B", category=SkillCategory.ROLE, prerequisites=["check_a"])
    await reg.register_skill(a)
    await reg.register_skill(b)
    # Agent has A at APPLY
    await svc.acquire_skill("worf", "check_a")
    await svc.update_proficiency("worf", "check_a", ProficiencyLevel.APPLY)
    result = await svc.check_prerequisites("worf", "check_b")
    assert result["met"] is True
    assert result["missing"] == []
    # Agent without A
    result2 = await svc.check_prerequisites("data", "check_b")
    assert result2["met"] is False
    assert "check_a" in result2["missing"]


# ---------------------------------------------------------------------------
# Test 23: get_profile categorizes skills correctly
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_profile_categorization(service):
    svc, reg = service
    profile = await svc.commission_agent("worf", "security_officer")
    assert len(profile.pccs) == 7
    assert len(profile.role_skills) > 0
    assert all(s.skill_id in [p.skill_id for p in BUILTIN_PCCS] for s in profile.pccs)
    assert len(profile.acquired_skills) == 0


# ---------------------------------------------------------------------------
# Test 24: AgentSkillRecord persists across restart
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_skill_record_persistence(tmp_path):
    db = str(tmp_path / "skills.db")
    reg1 = SkillRegistry(db_path=db)
    svc1 = AgentSkillService(db_path=db, registry=reg1)
    await reg1.start()
    await reg1.register_builtins()
    await svc1.start()
    await svc1.commission_agent("worf", "security_officer")
    await svc1.update_proficiency("worf", "communication", ProficiencyLevel.APPLY)
    await svc1.stop()
    await reg1.stop()

    reg2 = SkillRegistry(db_path=db)
    svc2 = AgentSkillService(db_path=db, registry=reg2)
    await reg2.start()
    await svc2.start()
    profile = await svc2.get_profile("worf")
    comm = next((s for s in profile.all_skills if s.skill_id == "communication"), None)
    assert comm is not None
    assert comm.proficiency == ProficiencyLevel.APPLY
    await svc2.stop()
    await reg2.stop()


# ---------------------------------------------------------------------------
# Test 25: SkillProfile.depth with empty profile
# ---------------------------------------------------------------------------

def test_skill_profile_empty_depth():
    profile = SkillProfile(agent_id="empty")
    assert profile.depth == 0
    assert profile.breadth == 0
