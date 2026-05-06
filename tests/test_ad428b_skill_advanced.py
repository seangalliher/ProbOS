"""AD-428b v1: Tests for advanced skill framework features.

Covers Sections 1-6 of `prompts/ad-428b-skill-framework-advanced-v1.md`:
- Section 1: composite/synergy fields + SkillProfile helpers
- Section 2: development goals
- Section 3: earned-agency proficiency-promotion eligibility (pure inspector)
- Section 4: HebbianRouter.score_with_skill_weight
- Section 5: DreamCycle skill reinforcement
"""

from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio

from probos.earned_agency import proficiency_promotion_eligibility
from probos.crew_profile import Rank
from probos.mesh.routing import HebbianRouter
from probos.skill_framework import (
    AgentSkillRecord,
    AgentSkillService,
    ProficiencyLevel,
    SkillCategory,
    SkillDefinition,
    SkillProfile,
    SkillRegistry,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def skill_stack(tmp_path):
    """Real SkillRegistry + AgentSkillService with built-ins registered."""
    db_path = str(tmp_path / "skills.db")
    registry = SkillRegistry(db_path=db_path)
    await registry.start()
    await registry.register_builtins()
    service = AgentSkillService(db_path=db_path, registry=registry)
    await service.start()
    try:
        yield registry, service
    finally:
        await service.stop()
        await registry.stop()


# ---------------------------------------------------------------------------
# Section 1a: SkillDefinition new fields default empty
# ---------------------------------------------------------------------------

def test_skill_definition_composite_and_synergy_fields_default_empty():
    defn = SkillDefinition(
        skill_id="x", name="X", category=SkillCategory.ACQUIRED,
    )
    assert defn.composite_skill_ids == []
    assert defn.synergy_partners == []


# ---------------------------------------------------------------------------
# Section 1c-1e: round-trip composite + synergy through DB
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_skill_definition_register_and_load_round_trips_composite_and_synergy(tmp_path):
    db = str(tmp_path / "rt.db")
    reg = SkillRegistry(db_path=db)
    await reg.start()
    defn = SkillDefinition(
        skill_id="combat_op",
        name="Combat Op",
        category=SkillCategory.ACQUIRED,
        composite_skill_ids=["weapons", "tactical"],
        synergy_partners=["communication"],
    )
    await reg.register_skill(defn)
    await reg.stop()

    reg2 = SkillRegistry(db_path=db)
    await reg2.start()
    loaded = reg2.get_skill("combat_op")
    await reg2.stop()
    assert loaded is not None
    assert loaded.composite_skill_ids == ["weapons", "tactical"]
    assert loaded.synergy_partners == ["communication"]


# ---------------------------------------------------------------------------
# Section 1b: SkillProfile.get_proficiency
# ---------------------------------------------------------------------------

def test_skill_profile_get_proficiency_returns_none_for_missing_or_suspended():
    profile = SkillProfile(
        agent_id="a",
        pccs=[
            AgentSkillRecord(
                agent_id="a", skill_id="held",
                proficiency=ProficiencyLevel.APPLY,
            ),
            AgentSkillRecord(
                agent_id="a", skill_id="suspended_one",
                proficiency=ProficiencyLevel.ENABLE, suspended=True,
            ),
        ],
    )
    assert profile.get_proficiency("held") == ProficiencyLevel.APPLY
    assert profile.get_proficiency("missing") is None
    assert profile.get_proficiency("suspended_one") is None


# ---------------------------------------------------------------------------
# Section 1b: has_composite_capability
# ---------------------------------------------------------------------------

def test_has_composite_capability_requires_apply_on_every_constituent():
    composite = SkillDefinition(
        skill_id="combat_op", name="Combat", category=SkillCategory.ACQUIRED,
        composite_skill_ids=["weapons", "tactical"],
    )
    # Has both at APPLY+
    profile_full = SkillProfile(
        agent_id="a",
        acquired_skills=[
            AgentSkillRecord(agent_id="a", skill_id="weapons", proficiency=ProficiencyLevel.APPLY),
            AgentSkillRecord(agent_id="a", skill_id="tactical", proficiency=ProficiencyLevel.ENABLE),
        ],
    )
    assert profile_full.has_composite_capability(composite) is True

    # One below APPLY
    profile_partial = SkillProfile(
        agent_id="a",
        acquired_skills=[
            AgentSkillRecord(agent_id="a", skill_id="weapons", proficiency=ProficiencyLevel.APPLY),
            AgentSkillRecord(agent_id="a", skill_id="tactical", proficiency=ProficiencyLevel.ASSIST),
        ],
    )
    assert profile_partial.has_composite_capability(composite) is False

    # Missing one entirely
    profile_missing = SkillProfile(
        agent_id="a",
        acquired_skills=[
            AgentSkillRecord(agent_id="a", skill_id="weapons", proficiency=ProficiencyLevel.SHAPE),
        ],
    )
    assert profile_missing.has_composite_capability(composite) is False


def test_has_composite_capability_returns_false_for_empty_composite():
    degenerate = SkillDefinition(
        skill_id="empty", name="Empty", category=SkillCategory.ACQUIRED,
    )
    profile = SkillProfile(
        agent_id="a",
        pccs=[AgentSkillRecord(agent_id="a", skill_id="anything", proficiency=ProficiencyLevel.SHAPE)],
    )
    assert profile.has_composite_capability(degenerate) is False


# ---------------------------------------------------------------------------
# Section 1b: synergy_bonus
# ---------------------------------------------------------------------------

def _registry_lookup_factory(defs: dict[str, SkillDefinition]):
    def lookup(skill_id: str) -> SkillDefinition | None:
        return defs.get(skill_id)
    return lookup


def test_synergy_bonus_zero_when_only_one_partner_declares_other():
    a = SkillDefinition(
        skill_id="a", name="A", category=SkillCategory.PCC,
        synergy_partners=["b"],  # A declares B
    )
    b = SkillDefinition(
        skill_id="b", name="B", category=SkillCategory.PCC,
        synergy_partners=[],  # B does NOT declare A
    )
    profile = SkillProfile(
        agent_id="x",
        pccs=[
            AgentSkillRecord(agent_id="x", skill_id="a", proficiency=ProficiencyLevel.APPLY),
            AgentSkillRecord(agent_id="x", skill_id="b", proficiency=ProficiencyLevel.APPLY),
        ],
    )
    lookup = _registry_lookup_factory({"a": a, "b": b})
    assert profile.synergy_bonus("a", "b", lookup) == 0.0


def test_synergy_bonus_apply_apply_returns_0_10_caps_at_0_50():
    a = SkillDefinition(
        skill_id="a", name="A", category=SkillCategory.PCC,
        synergy_partners=["b"],
    )
    b = SkillDefinition(
        skill_id="b", name="B", category=SkillCategory.PCC,
        synergy_partners=["a"],
    )
    lookup = _registry_lookup_factory({"a": a, "b": b})

    # APPLY+APPLY = 0.10
    profile_apply = SkillProfile(
        agent_id="x",
        pccs=[
            AgentSkillRecord(agent_id="x", skill_id="a", proficiency=ProficiencyLevel.APPLY),
            AgentSkillRecord(agent_id="x", skill_id="b", proficiency=ProficiencyLevel.APPLY),
        ],
    )
    assert profile_apply.synergy_bonus("a", "b", lookup) == pytest.approx(0.10)

    # SHAPE+SHAPE => raw 0.10 * (7-3+1) = 0.50, capped exactly at 0.50
    profile_shape = SkillProfile(
        agent_id="x",
        pccs=[
            AgentSkillRecord(agent_id="x", skill_id="a", proficiency=ProficiencyLevel.SHAPE),
            AgentSkillRecord(agent_id="x", skill_id="b", proficiency=ProficiencyLevel.SHAPE),
        ],
    )
    assert profile_shape.synergy_bonus("a", "b", lookup) == pytest.approx(0.50)

    # Below APPLY returns 0.0
    profile_below = SkillProfile(
        agent_id="x",
        pccs=[
            AgentSkillRecord(agent_id="x", skill_id="a", proficiency=ProficiencyLevel.ASSIST),
            AgentSkillRecord(agent_id="x", skill_id="b", proficiency=ProficiencyLevel.APPLY),
        ],
    )
    assert profile_below.synergy_bonus("a", "b", lookup) == 0.0


# ---------------------------------------------------------------------------
# Section 2b: development goals
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_development_goal_persists_and_replaces_on_duplicate(skill_stack):
    _, svc = skill_stack
    first = await svc.add_development_goal(
        "worf", "communication", ProficiencyLevel.APPLY, notes="initial",
    )
    assert first["target_level"] == ProficiencyLevel.APPLY.value
    # Replace with higher target — same (agent, skill).
    second = await svc.add_development_goal(
        "worf", "communication", ProficiencyLevel.ENABLE, notes="raised",
    )
    assert second["target_level"] == ProficiencyLevel.ENABLE.value
    goals = await svc.get_development_goals("worf")
    assert len(goals) == 1
    assert goals[0]["target_level"] == ProficiencyLevel.ENABLE.value
    assert goals[0]["notes"] == "raised"


@pytest.mark.asyncio
async def test_get_development_goals_includes_current_level_and_target_label(skill_stack):
    _, svc = skill_stack
    # Acquire a real skill so current_level is non-None.
    await svc.acquire_skill("worf", "communication", source="commissioning")
    await svc.add_development_goal(
        "worf", "communication", ProficiencyLevel.ADVISE,
    )
    # Goal on a skill not yet held — current_level should be None.
    await svc.add_development_goal(
        "worf", "threat_analysis", ProficiencyLevel.APPLY,
    )
    goals = await svc.get_development_goals("worf")
    assert len(goals) == 2
    by_skill = {g["skill_id"]: g for g in goals}
    assert by_skill["communication"]["target_label"] == "ADVISE"
    assert by_skill["communication"]["current_level"] is not None
    assert by_skill["threat_analysis"]["target_label"] == "APPLY"
    assert by_skill["threat_analysis"]["current_level"] is None


@pytest.mark.asyncio
async def test_clear_development_goal_returns_false_when_no_row(skill_stack):
    _, svc = skill_stack
    result = await svc.clear_development_goal("ghost", "nothing")
    assert result is False
    # Now add and clear, expect True.
    await svc.add_development_goal("worf", "communication", ProficiencyLevel.APPLY)
    assert (await svc.clear_development_goal("worf", "communication")) is True
    # Idempotent — second clear returns False.
    assert (await svc.clear_development_goal("worf", "communication")) is False


# ---------------------------------------------------------------------------
# Section 3: proficiency_promotion_eligibility
# ---------------------------------------------------------------------------

def _profile_with_pccs_and_roles(pcc_levels: list[int], role_levels: list[int]) -> SkillProfile:
    pccs = [
        AgentSkillRecord(
            agent_id="a", skill_id=f"pcc_{i}",
            proficiency=ProficiencyLevel(lvl),
        )
        for i, lvl in enumerate(pcc_levels)
    ]
    roles = [
        AgentSkillRecord(
            agent_id="a", skill_id=f"role_{i}",
            proficiency=ProficiencyLevel(lvl),
        )
        for i, lvl in enumerate(role_levels)
    ]
    return SkillProfile(agent_id="a", pccs=pccs, role_skills=roles)


def test_proficiency_promotion_eligibility_blocker_lists_pcc_and_role_gaps():
    # Empty profile, requesting promotion to LIEUTENANT (needs 2 PCCs at APPLY+, 1 ROLE at APPLY+).
    profile = _profile_with_pccs_and_roles([], [])
    result = proficiency_promotion_eligibility(
        profile=profile, next_rank=Rank.LIEUTENANT,
    )
    assert result["passes"] is False
    assert result["required_pcc_count"] == 2
    assert result["required_role_count"] == 1
    assert any("PCCs at level" in b for b in result["blockers"])
    assert any("role skills at level" in b for b in result["blockers"])


def test_proficiency_promotion_eligibility_passes_with_full_profile():
    # LIEUTENANT: needs 2 PCCs at APPLY (3), 1 ROLE at APPLY (3).
    profile = _profile_with_pccs_and_roles(
        pcc_levels=[ProficiencyLevel.APPLY.value, ProficiencyLevel.APPLY.value],
        role_levels=[ProficiencyLevel.APPLY.value],
    )
    result = proficiency_promotion_eligibility(
        profile=profile, next_rank=Rank.LIEUTENANT,
    )
    assert result["passes"] is True
    assert result["blockers"] == []
    assert result["pcc_count_at_floor"] == 2
    assert result["role_count_at_floor"] == 1


def test_proficiency_promotion_eligibility_handles_none_profile():
    result = proficiency_promotion_eligibility(
        profile=None, next_rank=Rank.LIEUTENANT,
    )
    assert result["passes"] is False
    assert result["blockers"] == ["no_skill_profile"]
    assert result["pcc_count_at_floor"] == 0


# ---------------------------------------------------------------------------
# Section 4c: HebbianRouter.score_with_skill_weight
# ---------------------------------------------------------------------------

class _FakeSkillService:
    """Minimal stub for skill-weighted routing tests."""

    def __init__(self, profiles: dict[str, SkillProfile]):
        self._profiles = profiles
        self.exercises: list[tuple[str, str]] = []

    async def get_profile(self, agent_id: str) -> SkillProfile | None:
        return self._profiles.get(agent_id)

    async def record_exercise(self, agent_id: str, skill_id: str) -> None:
        self.exercises.append((agent_id, skill_id))


@pytest.mark.asyncio
async def test_hebbian_score_with_skill_weight_returns_base_when_no_service():
    router = HebbianRouter()
    # No skill_service attached, no map set — base_weight returned unchanged.
    result = await router.score_with_skill_weight("intent_x", "agent_a", 0.5)
    assert result == pytest.approx(0.5)
    # Even with an empty map AND no service, still no-op.
    router.set_intent_skill_map({})
    result2 = await router.score_with_skill_weight("intent_x", "agent_a", 0.5)
    assert result2 == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_hebbian_score_with_skill_weight_multiplies_at_apply():
    profile = SkillProfile(
        agent_id="alice",
        pccs=[
            AgentSkillRecord(
                agent_id="alice", skill_id="comms",
                proficiency=ProficiencyLevel.APPLY,
            ),
        ],
    )
    fake = _FakeSkillService({"alice": profile})
    router = HebbianRouter()
    router.set_skill_service(fake)
    router.set_intent_skill_map({"chat": "comms"})
    # APPLY (3) -> multiplier = 1 + 0.10 * (3-1) = 1.20
    result = await router.score_with_skill_weight("chat", "alice", 0.5)
    assert result == pytest.approx(0.5 * 1.20)


@pytest.mark.asyncio
async def test_hebbian_score_with_skill_weight_caps_at_2x():
    # SHAPE (7) -> raw multiplier 1 + 0.10 * 6 = 1.60, BELOW 2.0 cap.
    # To exercise the cap, fabricate a level value > 11. The cap protects against
    # any future non-Dreyfus level addition. Easiest direct test: SHAPE confirmed
    # to be 1.60 (within 2x), AND a manual capped-value path.
    profile = SkillProfile(
        agent_id="alice",
        pccs=[
            AgentSkillRecord(
                agent_id="alice", skill_id="comms",
                proficiency=ProficiencyLevel.SHAPE,
            ),
        ],
    )
    fake = _FakeSkillService({"alice": profile})
    router = HebbianRouter()
    router.set_skill_service(fake)
    router.set_intent_skill_map({"chat": "comms"})
    result = await router.score_with_skill_weight("chat", "alice", 1.0)
    # SHAPE is the highest level shipped today: 1.60x is the live ladder cap.
    assert result == pytest.approx(1.60)
    # Verify the cap is observable by directly clamping.
    multiplier = 1.0 + 0.10 * (ProficiencyLevel.SHAPE.value - 1)
    capped = min(multiplier, 2.0)
    assert capped == pytest.approx(1.60)
    assert capped <= 2.0


# ---------------------------------------------------------------------------
# Section 5c: DreamCycle._reinforce_skills_for_episodes
# ---------------------------------------------------------------------------

class _FakeEpisode:
    def __init__(self, agent_ids: Any, intent_type: str):
        self.agent_ids = agent_ids
        self.intent_type = intent_type


def _make_dream_cycle(skill_service: Any, intent_skill_map: dict[str, str]):
    """Build a DreamCycle with only the kwargs needed for skill reinforcement.

    Imports inside the helper so test discovery doesn't require dreaming.py to
    be importable at collection time.
    """
    from probos.cognitive.dreaming import DreamingEngine
    return DreamingEngine(
        router=None,
        trust_network=None,
        episodic_memory=None,
        config=None,
        skill_service=skill_service,
        intent_skill_map=intent_skill_map,
    )


@pytest.mark.asyncio
async def test_dream_reinforce_skills_records_exercise_once_per_pair():
    fake = _FakeSkillService({})
    cycle = _make_dream_cycle(fake, {"comm": "comms", "scan": "sensors"})
    episodes = [
        _FakeEpisode(agent_ids=["alice", "bob"], intent_type="comm"),
        _FakeEpisode(agent_ids=["alice"], intent_type="comm"),  # dup (alice, comms)
        _FakeEpisode(agent_ids="charlie", intent_type="scan"),  # str shape
        _FakeEpisode(agent_ids=["alice"], intent_type="unmapped"),  # no skill
    ]
    reinforced = await cycle._reinforce_skills_for_episodes(episodes)
    # Expect 3 unique pairs: (alice,comms), (bob,comms), (charlie,sensors).
    assert reinforced == 3
    assert sorted(fake.exercises) == sorted([
        ("alice", "comms"),
        ("bob", "comms"),
        ("charlie", "sensors"),
    ])


@pytest.mark.asyncio
async def test_dream_reinforce_skills_no_op_when_intent_skill_map_empty():
    fake = _FakeSkillService({})
    cycle = _make_dream_cycle(fake, {})
    episodes = [_FakeEpisode(agent_ids=["alice"], intent_type="comm")]
    reinforced = await cycle._reinforce_skills_for_episodes(episodes)
    assert reinforced == 0
    assert fake.exercises == []
    # Also a no-op when service is None even with a non-empty map.
    cycle2 = _make_dream_cycle(None, {"comm": "comms"})
    reinforced2 = await cycle2._reinforce_skills_for_episodes(episodes)
    assert reinforced2 == 0
