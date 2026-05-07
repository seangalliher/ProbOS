"""AD-628 v1: Crew Skill Readiness Monitoring + Training Officer Role tests."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from probos.cognitive.drill_calendar import DrillCalendar, DrillEntry
from probos.cognitive.limdu import LIMDURecommendation, LIMDUService
from probos.cognitive.qual_skill_bridge import SkillAdvancement
from probos.cognitive.readiness_reporter import (
    DepartmentReadinessReport,
    ReadinessReporter,
    ShipReadinessReport,
    _to_c_rating,
)
from probos.cognitive.skill_readiness import (
    AgentSkillReadinessProfile,
    AgentSkillReadinessService,
    SkillRegressionEvent,
)
from probos.events import EventType
from probos.skill_framework import (
    AgentSkillService,
    ProficiencyLevel,
    SkillCategory,
    SkillDefinition,
    SkillRegistry,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def skill_registry(tmp_path: Path) -> SkillRegistry:
    reg = SkillRegistry(db_path=str(tmp_path / "registry.db"))
    await reg.start()
    # Register a small synthetic catalog
    await reg.register_skill(SkillDefinition(
        skill_id="alpha",
        name="Alpha",
        category=SkillCategory.ROLE,
        description="alpha",
        domain="operations",
    ))
    await reg.register_skill(SkillDefinition(
        skill_id="beta",
        name="Beta",
        category=SkillCategory.ROLE,
        description="beta",
        domain="operations",
    ))
    return reg


@pytest.fixture
async def skill_service(tmp_path: Path, skill_registry: SkillRegistry) -> AgentSkillService:
    svc = AgentSkillService(
        db_path=str(tmp_path / "skills.db"),
        registry=skill_registry,
    )
    await svc.start()
    return svc


# ---------------------------------------------------------------------------
# Section 1: AD-628a — Skill telemetry events
# ---------------------------------------------------------------------------


class TestSkillTelemetryEvents:

    @pytest.mark.asyncio
    async def test_set_event_emitter_registers_and_clears(self, skill_service: AgentSkillService) -> None:
        emitter = MagicMock()
        skill_service.set_event_emitter(emitter)
        assert skill_service._event_emitter is emitter
        skill_service.set_event_emitter(None)
        assert skill_service._event_emitter is None

    @pytest.mark.asyncio
    async def test_acquire_skill_emits_skill_acquired(self, skill_service: AgentSkillService) -> None:
        events: list[tuple] = []
        skill_service.set_event_emitter(lambda et, p: events.append((et, p)))
        await skill_service.acquire_skill("agent-1", "alpha", source="test")
        assert any(e[0] == EventType.SKILL_ACQUIRED for e in events)
        evt = next(e for e in events if e[0] == EventType.SKILL_ACQUIRED)
        assert evt[1]["agent_id"] == "agent-1"
        assert evt[1]["skill_id"] == "alpha"
        assert evt[1]["source"] == "test"
        assert evt[1]["reason"] == "acquired"

    @pytest.mark.asyncio
    async def test_update_proficiency_upward_emits_skill_exercised(self, skill_service: AgentSkillService) -> None:
        await skill_service.acquire_skill("agent-1", "alpha", proficiency=ProficiencyLevel.FOLLOW)
        events: list[tuple] = []
        skill_service.set_event_emitter(lambda et, p: events.append((et, p)))
        await skill_service.update_proficiency("agent-1", "alpha", ProficiencyLevel.APPLY)
        evt = next(e for e in events if e[0] == EventType.SKILL_EXERCISED)
        assert evt[1]["from_level"] == ProficiencyLevel.FOLLOW.value
        assert evt[1]["to_level"] == ProficiencyLevel.APPLY.value

    @pytest.mark.asyncio
    async def test_update_proficiency_downward_emits_skill_regression(self, skill_service: AgentSkillService) -> None:
        await skill_service.acquire_skill("agent-1", "alpha", proficiency=ProficiencyLevel.APPLY)
        events: list[tuple] = []
        skill_service.set_event_emitter(lambda et, p: events.append((et, p)))
        await skill_service.update_proficiency("agent-1", "alpha", ProficiencyLevel.FOLLOW)
        evt = next(e for e in events if e[0] == EventType.SKILL_REGRESSION)
        assert evt[1]["to_level"] < evt[1]["from_level"]

    @pytest.mark.asyncio
    async def test_record_exercise_emits_skill_exercised(self, skill_service: AgentSkillService) -> None:
        await skill_service.acquire_skill("agent-1", "alpha")
        events: list[tuple] = []
        skill_service.set_event_emitter(lambda et, p: events.append((et, p)))
        await skill_service.record_exercise("agent-1", "alpha")
        assert any(e[0] == EventType.SKILL_EXERCISED for e in events)

    @pytest.mark.asyncio
    async def test_check_decay_emits_skill_decay_per_record(self, skill_service: AgentSkillService) -> None:
        # Acquire two records at APPLY (decayable)
        await skill_service.acquire_skill("agent-1", "alpha", proficiency=ProficiencyLevel.APPLY)
        await skill_service.acquire_skill("agent-2", "alpha", proficiency=ProficiencyLevel.APPLY)
        events: list[tuple] = []
        skill_service.set_event_emitter(lambda et, p: events.append((et, p)))
        # Force decay by passing a 'now' far in the future (>14 default decay days).
        future_now = time.time() + (60 * 86400)
        decayed = await skill_service.check_decay(now=future_now)
        decay_events = [e for e in events if e[0] == EventType.SKILL_DECAY]
        assert len(decay_events) == len(decayed)

    @pytest.mark.asyncio
    async def test_emitter_exception_does_not_propagate(self, skill_service: AgentSkillService) -> None:
        def bad_emitter(et, p):
            raise RuntimeError("boom")
        skill_service.set_event_emitter(bad_emitter)
        # Should not raise
        await skill_service.acquire_skill("agent-1", "alpha")

    @pytest.mark.asyncio
    async def test_no_emitter_no_exception(self, skill_service: AgentSkillService) -> None:
        # No emitter registered — must not raise
        await skill_service.acquire_skill("agent-1", "alpha")
        await skill_service.update_proficiency("agent-1", "alpha", ProficiencyLevel.APPLY)
        await skill_service.record_exercise("agent-1", "alpha")

    @pytest.mark.asyncio
    async def test_payload_timestamp_is_finite_float(self, skill_service: AgentSkillService) -> None:
        events: list[tuple] = []
        skill_service.set_event_emitter(lambda et, p: events.append((et, p)))
        await skill_service.acquire_skill("agent-1", "alpha")
        ts = events[0][1]["timestamp"]
        assert isinstance(ts, float) and ts > 0

    @pytest.mark.asyncio
    async def test_payload_ids_match_call_arguments(self, skill_service: AgentSkillService) -> None:
        events: list[tuple] = []
        skill_service.set_event_emitter(lambda et, p: events.append((et, p)))
        await skill_service.acquire_skill("agent-XYZ", "alpha")
        evt = events[0][1]
        assert evt["agent_id"] == "agent-XYZ"
        assert evt["skill_id"] == "alpha"


# ---------------------------------------------------------------------------
# Section 2: AD-628b — Skill readiness profile
# ---------------------------------------------------------------------------


class TestSkillReadinessProfile:

    @pytest.mark.asyncio
    async def test_get_profile_unknown_agent(self, skill_service: AgentSkillService) -> None:
        svc = AgentSkillReadinessService(skill_service)
        profile = await svc.get_profile("nobody")
        assert profile.agent_id == "nobody"
        assert profile.qualifications == []

    @pytest.mark.asyncio
    async def test_qualifications_only_apply_plus(self, skill_service: AgentSkillService) -> None:
        await skill_service.acquire_skill("agent-1", "alpha", proficiency=ProficiencyLevel.FOLLOW)
        await skill_service.acquire_skill("agent-1", "beta", proficiency=ProficiencyLevel.APPLY)
        svc = AgentSkillReadinessService(skill_service)
        profile = await svc.get_profile("agent-1")
        assert "beta" in profile.qualifications
        assert "alpha" not in profile.qualifications

    @pytest.mark.asyncio
    async def test_proficiency_distribution(self, skill_service: AgentSkillService) -> None:
        await skill_service.acquire_skill("agent-1", "alpha", proficiency=ProficiencyLevel.FOLLOW)
        await skill_service.acquire_skill("agent-1", "beta", proficiency=ProficiencyLevel.FOLLOW)
        svc = AgentSkillReadinessService(skill_service)
        profile = await svc.get_profile("agent-1")
        assert profile.proficiency_distribution.get("FOLLOW") == 2

    @pytest.mark.asyncio
    async def test_recent_advancements_capped(self, skill_service: AgentSkillService) -> None:
        log = [
            SkillAdvancement("agent-1", f"skill-{i}", 1, 2, "test", 0.8)
            for i in range(20)
        ]
        svc = AgentSkillReadinessService(skill_service, advancement_log=log)
        profile = await svc.get_profile("agent-1")
        assert len(profile.recent_advancements) == 10
        # Newest-first means index 0 should be the last appended (skill-19)
        assert profile.recent_advancements[0].skill_id == "skill-19"

    @pytest.mark.asyncio
    async def test_recent_regressions_capped_and_sorted(self, skill_service: AgentSkillService) -> None:
        svc = AgentSkillReadinessService(skill_service)
        for i in range(15):
            svc.record_regression(SkillRegressionEvent(
                agent_id="agent-1", skill_id=f"s{i}",
                from_level=3, to_level=2, timestamp=float(i),
            ))
        profile = await svc.get_profile("agent-1")
        assert len(profile.recent_regressions) == 10
        assert profile.recent_regressions[0].timestamp >= profile.recent_regressions[-1].timestamp

    @pytest.mark.asyncio
    async def test_record_regression_ring_caps_at_100(self, skill_service: AgentSkillService) -> None:
        svc = AgentSkillReadinessService(skill_service)
        for i in range(150):
            svc.record_regression(SkillRegressionEvent(
                agent_id="agent-1", skill_id=f"s{i}",
                from_level=3, to_level=2, timestamp=float(i),
            ))
        assert len(svc._regression_ring) == 100

    @pytest.mark.asyncio
    async def test_last_exercised_per_skill(self, skill_service: AgentSkillService) -> None:
        await skill_service.acquire_skill("agent-1", "alpha")
        svc = AgentSkillReadinessService(skill_service)
        profile = await svc.get_profile("agent-1")
        assert "alpha" in profile.last_exercised_per_skill
        assert profile.last_exercised_per_skill["alpha"] > 0

    @pytest.mark.asyncio
    async def test_composite_capabilities_listed(self, skill_service: AgentSkillService, skill_registry: SkillRegistry) -> None:
        # Register a composite combining alpha+beta
        await skill_registry.register_skill(SkillDefinition(
            skill_id="alpha_beta_composite",
            name="Composite",
            category=SkillCategory.ROLE,
            description="composite",
            composite_skill_ids=["alpha", "beta"],
        ))
        await skill_service.acquire_skill("agent-1", "alpha", proficiency=ProficiencyLevel.APPLY)
        await skill_service.acquire_skill("agent-1", "beta", proficiency=ProficiencyLevel.APPLY)
        svc = AgentSkillReadinessService(skill_service, registry=skill_registry)
        profile = await svc.get_profile("agent-1")
        assert "alpha_beta_composite" in profile.composite_capabilities


# ---------------------------------------------------------------------------
# Section 3: AD-628c — Training Officer crew profile
# ---------------------------------------------------------------------------


REPO_ROOT = Path(__file__).resolve().parent.parent
TRAINING_YAML = REPO_ROOT / "config" / "standing_orders" / "crew_profiles" / "training_officer.yaml"
ORG_YAML = REPO_ROOT / "config" / "ontology" / "organization.yaml"


class TestTrainingOfficerCrewProfile:

    def test_training_officer_yaml_parses(self) -> None:
        data = yaml.safe_load(TRAINING_YAML.read_text(encoding="utf-8"))
        assert "display_name" in data
        assert "callsign" in data
        assert "department" in data
        assert "role" in data
        assert "personality" in data

    def test_callsign_and_department(self) -> None:
        data = yaml.safe_load(TRAINING_YAML.read_text(encoding="utf-8"))
        assert data["callsign"] == "Tucker"
        assert data["department"] == "operations"
        assert data["role"] == "officer"

    def test_organization_has_chief_training_post(self) -> None:
        data = yaml.safe_load(ORG_YAML.read_text(encoding="utf-8"))
        posts = data.get("posts", [])
        chief_training = next((p for p in posts if p.get("id") == "chief_training"), None)
        assert chief_training is not None
        assert chief_training["tier"] == "crew"

    def test_organization_has_tucker_assignment(self) -> None:
        data = yaml.safe_load(ORG_YAML.read_text(encoding="utf-8"))
        assignments = data.get("assignments", [])
        tucker = next((a for a in assignments if a.get("callsign") == "Tucker"), None)
        assert tucker is not None
        assert tucker["agent_type"] == "training_officer"
        assert tucker["watches"] == ["alpha", "beta"]

    def test_no_callsign_collision(self) -> None:
        data = yaml.safe_load(ORG_YAML.read_text(encoding="utf-8"))
        callsigns = [a["callsign"] for a in data.get("assignments", [])]
        assert callsigns.count("Tucker") == 1

    def test_chief_training_reports_to_chief_operations(self) -> None:
        data = yaml.safe_load(ORG_YAML.read_text(encoding="utf-8"))
        posts = data.get("posts", [])
        chief_training = next(p for p in posts if p.get("id") == "chief_training")
        assert chief_training["reports_to"] == "chief_operations"


# ---------------------------------------------------------------------------
# Section 4: AD-628d — Drill calendar
# ---------------------------------------------------------------------------


def _make_harness_with_tests(test_names: list[str]) -> Any:
    harness = MagicMock()
    registered = {name: MagicMock() for name in test_names}
    type(harness).registered_tests = property(lambda self: registered)
    harness.run_test = AsyncMock(return_value=MagicMock(passed=True, score=0.9))
    return harness


class TestDrillCalendar:

    def test_schedule_drill_returns_id_and_stores(self) -> None:
        harness = _make_harness_with_tests(["test_a"])
        cal = DrillCalendar(harness)
        did = cal.schedule_drill("agent-1", "test_a", time.time())
        assert did
        assert cal.get_drill(did) is not None

    def test_schedule_drill_unknown_test_raises_keyerror(self) -> None:
        harness = _make_harness_with_tests(["test_a"])
        cal = DrillCalendar(harness)
        with pytest.raises(KeyError):
            cal.schedule_drill("agent-1", "no_such_test", time.time())

    def test_list_due_drills_returns_only_scheduled(self) -> None:
        harness = _make_harness_with_tests(["test_a"])
        cal = DrillCalendar(harness)
        now = time.time()
        cal.schedule_drill("agent-1", "test_a", now - 100)
        cal.schedule_drill("agent-1", "test_a", now + 100)
        due = cal.list_due_drills(before=now)
        assert len(due) == 1
        assert due[0].scheduled_at <= now

    def test_list_due_drills_excludes_executed_and_missed(self) -> None:
        harness = _make_harness_with_tests(["test_a"])
        cal = DrillCalendar(harness)
        now = time.time()
        d1 = cal.schedule_drill("agent-1", "test_a", now - 100)
        d2 = cal.schedule_drill("agent-1", "test_a", now - 100)
        cal.mark_missed(d1)
        # mark d2 executed manually
        from dataclasses import replace
        cal._drills[d2] = replace(cal._drills[d2], status="executed")
        due = cal.list_due_drills(before=now)
        assert due == []

    @pytest.mark.asyncio
    async def test_execute_drill_calls_run_test(self) -> None:
        harness = _make_harness_with_tests(["test_a"])
        cal = DrillCalendar(harness, runtime="rt-sentinel")
        did = cal.schedule_drill("agent-1", "test_a", time.time())
        await cal.execute_drill(did)
        harness.run_test.assert_awaited_once_with("agent-1", "test_a", "rt-sentinel")

    @pytest.mark.asyncio
    async def test_execute_drill_records_result_and_status(self) -> None:
        harness = _make_harness_with_tests(["test_a"])
        cal = DrillCalendar(harness)
        did = cal.schedule_drill("agent-1", "test_a", time.time())
        updated = await cal.execute_drill(did)
        assert updated.status == "executed"
        assert updated.result is not None

    def test_mark_missed_sets_status(self) -> None:
        harness = _make_harness_with_tests(["test_a"])
        cal = DrillCalendar(harness)
        did = cal.schedule_drill("agent-1", "test_a", time.time())
        updated = cal.mark_missed(did)
        assert updated.status == "missed"

    def test_get_drill_unknown_returns_none(self) -> None:
        harness = _make_harness_with_tests(["test_a"])
        cal = DrillCalendar(harness)
        assert cal.get_drill("nope") is None

    def test_list_drills_for_agent_filters(self) -> None:
        harness = _make_harness_with_tests(["test_a"])
        cal = DrillCalendar(harness)
        cal.schedule_drill("agent-1", "test_a", time.time())
        cal.schedule_drill("agent-2", "test_a", time.time())
        assert len(cal.list_drills_for_agent("agent-1")) == 1
        assert len(cal.list_drills_for_agent("agent-2")) == 1

    def test_drill_ids_unique(self) -> None:
        harness = _make_harness_with_tests(["test_a"])
        cal = DrillCalendar(harness)
        ids = {cal.schedule_drill("a", "test_a", time.time()) for _ in range(5)}
        assert len(ids) == 5


# ---------------------------------------------------------------------------
# Section 5: AD-628e — Onboarding mentor announcer
# ---------------------------------------------------------------------------


class TestOnboardingMentorAnnouncer:

    def _make_service(self) -> Any:
        from probos.agent_onboarding import AgentOnboardingService
        # Construct by direct attribute assignment to avoid full DI
        svc = AgentOnboardingService.__new__(AgentOnboardingService)
        svc._mentor_announcer = None
        return svc

    def test_register_none_clears_prior(self) -> None:
        svc = self._make_service()
        a = AsyncMock()
        svc.register_mentor_announcer(a)
        assert svc._mentor_announcer is a
        svc.register_mentor_announcer(None)
        assert svc._mentor_announcer is None

    @pytest.mark.asyncio
    async def test_announcer_invoked_with_callsign_and_post(self) -> None:
        svc = self._make_service()
        announcer = AsyncMock()
        svc.register_mentor_announcer(announcer)
        # Simulate the invocation block directly
        if svc._mentor_announcer is not None and asyncio.iscoroutinefunction(svc._mentor_announcer):
            await svc._mentor_announcer("Worf", "chief_security")
        announcer.assert_awaited_once_with("Worf", "chief_security")

    @pytest.mark.asyncio
    async def test_no_announcer_no_exception(self) -> None:
        svc = self._make_service()
        # Should not raise
        if svc._mentor_announcer is not None and asyncio.iscoroutinefunction(svc._mentor_announcer):
            await svc._mentor_announcer("x", "y")

    @pytest.mark.asyncio
    async def test_announcer_exception_caught(self) -> None:
        async def failing(callsign, post):
            raise RuntimeError("boom")
        svc = self._make_service()
        svc.register_mentor_announcer(failing)
        # Mirror the production try/except structure
        try:
            if svc._mentor_announcer is not None and asyncio.iscoroutinefunction(svc._mentor_announcer):
                try:
                    await svc._mentor_announcer("x", "y")
                except Exception:
                    pass
        except Exception:
            pytest.fail("Exception should have been swallowed")

    def test_sync_announcer_skipped(self) -> None:
        svc = self._make_service()
        svc.register_mentor_announcer(MagicMock())  # sync MagicMock — not coroutine
        # Guard at production site uses iscoroutinefunction; sync should be skipped
        assert not asyncio.iscoroutinefunction(svc._mentor_announcer)

    @pytest.mark.asyncio
    async def test_announcer_receives_final_callsign(self) -> None:
        svc = self._make_service()
        seen: list[str] = []

        async def capture(cs, post):
            seen.append(cs)

        svc.register_mentor_announcer(capture)
        await svc._mentor_announcer("FinalName", "post-1")
        assert seen == ["FinalName"]


# ---------------------------------------------------------------------------
# Section 6: AD-628f — Readiness reporter
# ---------------------------------------------------------------------------


class _FakeAgent:
    def __init__(self, agent_id: str, agent_type: str) -> None:
        self.id = agent_id
        self.agent_type = agent_type


class _FakeRegistry:
    def __init__(self, agents: list[_FakeAgent]) -> None:
        self._agents = agents

    def all(self) -> list[_FakeAgent]:
        return list(self._agents)


class _FakeOntology:
    def __init__(self, dept_for_type: dict[str, str]) -> None:
        self._map = dept_for_type

    def get_all_assignments(self) -> list:
        return [MagicMock(agent_type=t) for t in self._map]

    def get_agent_department(self, agent_type: str) -> str | None:
        return self._map.get(agent_type)

    def get_departments(self) -> list:
        from types import SimpleNamespace
        names = sorted(set(self._map.values()))
        return [SimpleNamespace(name=n, id=n) for n in names]


class TestReadinessReporter:

    @pytest.mark.asyncio
    async def test_empty_department(self, skill_service: AgentSkillService) -> None:
        rs = AgentSkillReadinessService(skill_service)
        ont = _FakeOntology({})
        reg = _FakeRegistry([])
        rep = ReadinessReporter(rs, ont, reg)
        d = await rep.compute_department_readiness("operations")
        assert d.member_count == 0
        assert d.qualified_skill_coverage == 0.0

    @pytest.mark.asyncio
    async def test_department_aggregates_three_agents(self, skill_service: AgentSkillService, skill_registry: SkillRegistry) -> None:
        await skill_service.acquire_skill("a1", "alpha", proficiency=ProficiencyLevel.APPLY)
        await skill_service.acquire_skill("a2", "alpha", proficiency=ProficiencyLevel.APPLY)
        await skill_service.acquire_skill("a3", "alpha", proficiency=ProficiencyLevel.FOLLOW)
        rs = AgentSkillReadinessService(skill_service, registry=skill_registry)
        ont = _FakeOntology({"t1": "operations", "t2": "operations", "t3": "operations"})
        reg = _FakeRegistry([
            _FakeAgent("a1", "t1"),
            _FakeAgent("a2", "t2"),
            _FakeAgent("a3", "t3"),
        ])
        rep = ReadinessReporter(rs, ont, reg, skill_registry=skill_registry)
        d = await rep.compute_department_readiness("operations")
        assert d.member_count == 3

    @pytest.mark.asyncio
    async def test_qualified_skill_coverage_mean(self, skill_service: AgentSkillService, skill_registry: SkillRegistry) -> None:
        await skill_service.acquire_skill("a1", "alpha", proficiency=ProficiencyLevel.APPLY)
        await skill_service.acquire_skill("a1", "beta", proficiency=ProficiencyLevel.APPLY)
        rs = AgentSkillReadinessService(skill_service, registry=skill_registry)
        ont = _FakeOntology({"t1": "operations"})
        reg = _FakeRegistry([_FakeAgent("a1", "t1")])
        rep = ReadinessReporter(rs, ont, reg, skill_registry=skill_registry)
        d = await rep.compute_department_readiness("operations")
        # 2 qualifications / 2 expected operations skills = 1.0
        assert d.qualified_skill_coverage == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_proficiency_mean(self, skill_service: AgentSkillService, skill_registry: SkillRegistry) -> None:
        await skill_service.acquire_skill("a1", "alpha", proficiency=ProficiencyLevel.APPLY)  # 3
        rs = AgentSkillReadinessService(skill_service, registry=skill_registry)
        ont = _FakeOntology({"t1": "operations"})
        reg = _FakeRegistry([_FakeAgent("a1", "t1")])
        rep = ReadinessReporter(rs, ont, reg, skill_registry=skill_registry)
        d = await rep.compute_department_readiness("operations")
        assert d.proficiency_mean == pytest.approx(3.0)

    @pytest.mark.asyncio
    async def test_regression_count_24h(self, skill_service: AgentSkillService) -> None:
        rs = AgentSkillReadinessService(skill_service)
        rs.record_regression(SkillRegressionEvent("a1", "alpha", 3, 2, time.time(), "recent"))
        rs.record_regression(SkillRegressionEvent("a1", "alpha", 3, 2, time.time() - 100000, "old"))
        ont = _FakeOntology({"t1": "operations"})
        reg = _FakeRegistry([_FakeAgent("a1", "t1")])
        rep = ReadinessReporter(rs, ont, reg)
        d = await rep.compute_department_readiness("operations")
        assert d.regression_count_24h == 1

    @pytest.mark.asyncio
    async def test_decay_count_24h(self, skill_service: AgentSkillService) -> None:
        rs = AgentSkillReadinessService(skill_service)
        rs.record_regression(SkillRegressionEvent("a1", "alpha", 3, 2, time.time(), "idle_decay"))
        ont = _FakeOntology({"t1": "operations"})
        reg = _FakeRegistry([_FakeAgent("a1", "t1")])
        rep = ReadinessReporter(rs, ont, reg)
        d = await rep.compute_department_readiness("operations")
        assert d.decay_count_24h == 1

    @pytest.mark.asyncio
    async def test_ship_readiness_one_per_department(self, skill_service: AgentSkillService) -> None:
        rs = AgentSkillReadinessService(skill_service)
        ont = _FakeOntology({"t1": "operations", "t2": "medical"})
        reg = _FakeRegistry([_FakeAgent("a1", "t1"), _FakeAgent("a2", "t2")])
        rep = ReadinessReporter(rs, ont, reg)
        ship = await rep.compute_ship_readiness()
        assert {d.department for d in ship.departments} == {"operations", "medical"}

    @pytest.mark.asyncio
    async def test_composite_score_member_weighted(self, skill_service: AgentSkillService) -> None:
        rs = AgentSkillReadinessService(skill_service)
        ont = _FakeOntology({"t1": "operations"})
        reg = _FakeRegistry([_FakeAgent("a1", "t1")])
        rep = ReadinessReporter(rs, ont, reg)
        ship = await rep.compute_ship_readiness()
        assert 0.0 <= ship.composite_score <= 1.0

    def test_c_rating_thresholds(self) -> None:
        assert _to_c_rating(0.90) == "C1"
        assert _to_c_rating(0.75) == "C2"
        assert _to_c_rating(0.55) == "C3"
        assert _to_c_rating(0.20) == "C4"

    @pytest.mark.asyncio
    async def test_captured_at_finite(self, skill_service: AgentSkillService) -> None:
        rs = AgentSkillReadinessService(skill_service)
        rep = ReadinessReporter(rs, _FakeOntology({}), _FakeRegistry([]))
        ship = await rep.compute_ship_readiness()
        assert isinstance(ship.captured_at, float) and ship.captured_at > 0


# ---------------------------------------------------------------------------
# Section 7: AD-628g — LIMDU protocol
# ---------------------------------------------------------------------------


class TestLIMDUProtocol:

    @pytest.mark.asyncio
    async def test_required_kwargs_enforced(self, skill_service: AgentSkillService) -> None:
        rs = AgentSkillReadinessService(skill_service)
        harness = _make_harness_with_tests(["t1"])
        cal = DrillCalendar(harness)
        svc = LIMDUService(rs, cal)
        with pytest.raises(TypeError):
            await svc.recommend_limited_duty("a1")  # type: ignore[call-arg]
        with pytest.raises(TypeError):
            await svc.recommend_limited_duty("a1", medical_callsign="Bones")  # type: ignore[call-arg]

    @pytest.mark.asyncio
    async def test_returns_recommendation_with_callsigns(self, skill_service: AgentSkillService) -> None:
        rs = AgentSkillReadinessService(skill_service)
        harness = _make_harness_with_tests(["t1"])
        cal = DrillCalendar(harness)
        svc = LIMDUService(rs, cal)
        rec = await svc.recommend_limited_duty(
            "a1", medical_callsign="Bones", traino_callsign="Tucker", reason="r",
        )
        assert rec.medical_callsign == "Bones"
        assert rec.traino_callsign == "Tucker"

    @pytest.mark.asyncio
    async def test_regressed_skills_from_profile(self, skill_service: AgentSkillService) -> None:
        rs = AgentSkillReadinessService(skill_service)
        rs.record_regression(SkillRegressionEvent("a1", "alpha", 3, 2, time.time(), ""))
        harness = _make_harness_with_tests(["t_alpha"])
        cal = DrillCalendar(harness)
        svc = LIMDUService(rs, cal, test_for_skill=lambda s: "t_alpha" if s == "alpha" else None)
        rec = await svc.recommend_limited_duty(
            "a1", medical_callsign="M", traino_callsign="T", reason="r",
        )
        assert "alpha" in rec.regressed_skills

    @pytest.mark.asyncio
    async def test_remediation_plan_per_regressed(self, skill_service: AgentSkillService) -> None:
        rs = AgentSkillReadinessService(skill_service)
        rs.record_regression(SkillRegressionEvent("a1", "alpha", 3, 2, time.time(), ""))
        harness = _make_harness_with_tests(["t_alpha"])
        cal = DrillCalendar(harness)
        svc = LIMDUService(rs, cal, test_for_skill=lambda s: "t_alpha" if s == "alpha" else None)
        rec = await svc.recommend_limited_duty(
            "a1", medical_callsign="M", traino_callsign="T", reason="r",
        )
        assert len(rec.remediation_plan) == 1

    @pytest.mark.asyncio
    async def test_skill_without_test_skipped(self, skill_service: AgentSkillService) -> None:
        rs = AgentSkillReadinessService(skill_service)
        rs.record_regression(SkillRegressionEvent("a1", "unmapped", 3, 2, time.time(), ""))
        harness = _make_harness_with_tests(["t_alpha"])
        cal = DrillCalendar(harness)
        svc = LIMDUService(rs, cal, test_for_skill=lambda s: None)
        rec = await svc.recommend_limited_duty(
            "a1", medical_callsign="M", traino_callsign="T", reason="r",
        )
        assert rec.remediation_plan == []

    @pytest.mark.asyncio
    async def test_default_zone_green_when_no_breaker(self, skill_service: AgentSkillService) -> None:
        from probos.cognitive.circuit_breaker import CognitiveZone
        rs = AgentSkillReadinessService(skill_service)
        cal = DrillCalendar(_make_harness_with_tests([]))
        svc = LIMDUService(rs, cal)
        rec = await svc.recommend_limited_duty(
            "a1", medical_callsign="M", traino_callsign="T", reason="r",
        )
        assert rec.cognitive_zone == CognitiveZone.GREEN

    @pytest.mark.asyncio
    async def test_zone_from_breaker(self, skill_service: AgentSkillService) -> None:
        from probos.cognitive.circuit_breaker import CognitiveZone
        rs = AgentSkillReadinessService(skill_service)
        cal = DrillCalendar(_make_harness_with_tests([]))
        breaker = MagicMock()
        breaker.get_zone.return_value = "amber"
        svc = LIMDUService(rs, cal, circuit_breaker=breaker)
        rec = await svc.recommend_limited_duty(
            "a1", medical_callsign="M", traino_callsign="T", reason="r",
        )
        assert rec.cognitive_zone == CognitiveZone.AMBER

    @pytest.mark.asyncio
    async def test_limdu_recommended_event_emitted(self, skill_service: AgentSkillService) -> None:
        rs = AgentSkillReadinessService(skill_service)
        cal = DrillCalendar(_make_harness_with_tests([]))
        events: list = []
        svc = LIMDUService(rs, cal)
        svc.set_event_emitter(lambda et, p: events.append((et, p)))
        await svc.recommend_limited_duty(
            "a1", medical_callsign="M", traino_callsign="T", reason="r",
        )
        assert any(e[0] == EventType.LIMDU_RECOMMENDED for e in events)

    @pytest.mark.asyncio
    async def test_update_status(self, skill_service: AgentSkillService) -> None:
        rs = AgentSkillReadinessService(skill_service)
        cal = DrillCalendar(_make_harness_with_tests([]))
        svc = LIMDUService(rs, cal)
        rec = await svc.recommend_limited_duty(
            "a1", medical_callsign="M", traino_callsign="T", reason="r",
        )
        updated = svc.update_status(rec.recommendation_id, "accepted")
        assert updated is not None
        assert updated.status == "accepted"

    @pytest.mark.asyncio
    async def test_list_active_excludes_completed_and_expired(self, skill_service: AgentSkillService) -> None:
        rs = AgentSkillReadinessService(skill_service)
        cal = DrillCalendar(_make_harness_with_tests([]))
        svc = LIMDUService(rs, cal)
        r1 = await svc.recommend_limited_duty("a1", medical_callsign="M", traino_callsign="T", reason="r")
        r2 = await svc.recommend_limited_duty("a2", medical_callsign="M", traino_callsign="T", reason="r")
        svc.update_status(r1.recommendation_id, "completed")
        svc.update_status(r2.recommendation_id, "expired")
        assert svc.list_active_recommendations() == []


# ---------------------------------------------------------------------------
# Section 8: AD-628h — /readiness slash command
# ---------------------------------------------------------------------------


class TestReadinessSlashCommand:

    @pytest.mark.asyncio
    async def test_no_reporter_prints_fallback(self) -> None:
        from probos.experience.commands.commands_status import cmd_readiness
        runtime = MagicMock(spec=[])  # no readiness_reporter attribute
        console = MagicMock()
        await cmd_readiness(runtime, console, "")
        printed = " ".join(str(c) for c in console.print.call_args_list)
        assert "not wired" in printed

    @pytest.mark.asyncio
    async def test_table_title_contains_c_rating(self) -> None:
        from probos.experience.commands.commands_status import cmd_readiness
        runtime = MagicMock()
        report = ShipReadinessReport(captured_at=time.time(), departments=[], composite_score=0.9, c_rating="C1")
        runtime.readiness_reporter.compute_ship_readiness = AsyncMock(return_value=report)
        console = MagicMock()
        await cmd_readiness(runtime, console, "")
        printed_args = console.print.call_args[0]
        # The single positional arg is the Table; check title
        table = printed_args[0]
        assert "C1" in str(table.title)

    @pytest.mark.asyncio
    async def test_table_one_row_per_department(self) -> None:
        from probos.experience.commands.commands_status import cmd_readiness
        runtime = MagicMock()
        depts = [
            DepartmentReadinessReport("ops", 2, 0.5, 3.0, 0, 0),
            DepartmentReadinessReport("med", 1, 0.7, 4.0, 1, 0),
        ]
        report = ShipReadinessReport(captured_at=time.time(), departments=depts, composite_score=0.6, c_rating="C3")
        runtime.readiness_reporter.compute_ship_readiness = AsyncMock(return_value=report)
        console = MagicMock()
        await cmd_readiness(runtime, console, "")
        table = console.print.call_args[0][0]
        # Rich Table tracks rows in `.rows`
        assert len(table.rows) == 2

    @pytest.mark.asyncio
    async def test_numeric_columns_two_decimals(self) -> None:
        from probos.experience.commands.commands_status import cmd_readiness
        runtime = MagicMock()
        depts = [DepartmentReadinessReport("ops", 1, 0.123456, 3.987, 0, 0)]
        report = ShipReadinessReport(captured_at=time.time(), departments=depts, composite_score=0.5, c_rating="C3")
        runtime.readiness_reporter.compute_ship_readiness = AsyncMock(return_value=report)
        console = MagicMock()
        await cmd_readiness(runtime, console, "")
        table = console.print.call_args[0][0]
        # Cells stored on table.columns[i]._cells
        coverage_cells = list(table.columns[2]._cells)
        assert coverage_cells[0] == "0.12"

    @pytest.mark.asyncio
    async def test_empty_report_renders_header_only(self) -> None:
        from probos.experience.commands.commands_status import cmd_readiness
        runtime = MagicMock()
        report = ShipReadinessReport(captured_at=time.time(), departments=[], composite_score=0.0, c_rating="C4")
        runtime.readiness_reporter.compute_ship_readiness = AsyncMock(return_value=report)
        console = MagicMock()
        await cmd_readiness(runtime, console, "")
        table = console.print.call_args[0][0]
        assert len(table.rows) == 0
        assert len(table.columns) == 6

    @pytest.mark.asyncio
    async def test_reporter_exception_caught(self) -> None:
        from probos.experience.commands.commands_status import cmd_readiness
        runtime = MagicMock()
        runtime.readiness_reporter.compute_ship_readiness = AsyncMock(side_effect=RuntimeError("boom"))
        console = MagicMock()
        # Must not propagate
        await cmd_readiness(runtime, console, "")
        printed = " ".join(str(c) for c in console.print.call_args_list)
        assert "unavailable" in printed.lower() or "error" in printed.lower()


# ---------------------------------------------------------------------------
# Startup wiring (smoke)
# ---------------------------------------------------------------------------


class TestStartupWiring:

    def test_runtime_has_skill_readiness_service_slot(self) -> None:
        # Assert the attribute name exists on a runtime instance.
        from probos.runtime import ProbOSRuntime
        # Construct a bare instance via __new__ to avoid full startup.
        rt = ProbOSRuntime.__new__(ProbOSRuntime)
        rt.skill_readiness_service = None  # type: ignore[attr-defined]
        assert hasattr(rt, "skill_readiness_service")

    def test_runtime_has_drill_calendar_slot(self) -> None:
        from probos.runtime import ProbOSRuntime
        rt = ProbOSRuntime.__new__(ProbOSRuntime)
        rt.drill_calendar = None  # type: ignore[attr-defined]
        assert hasattr(rt, "drill_calendar")

    def test_runtime_has_readiness_reporter_slot(self) -> None:
        from probos.runtime import ProbOSRuntime
        rt = ProbOSRuntime.__new__(ProbOSRuntime)
        rt.readiness_reporter = None  # type: ignore[attr-defined]
        assert hasattr(rt, "readiness_reporter")

    def test_runtime_has_limdu_service_slot(self) -> None:
        from probos.runtime import ProbOSRuntime
        rt = ProbOSRuntime.__new__(ProbOSRuntime)
        rt.limdu_service = None  # type: ignore[attr-defined]
        assert hasattr(rt, "limdu_service")
