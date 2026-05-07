"""AD-510 v1 — Holodeck Team Simulations test suite (~46 tests / 8 classes).

Floor: 38 — exceeded by 8.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.config import HolodeckTeamSimulationConfig, SystemConfig
from probos.events import EventType
from probos.holodeck.team_simulations import (
    DebriefRecord,
    TeamScenario,
    TeamScenarioRegistry,
    TeamSimulationDrill,
    TeamSimulationOrchestrator,
    TeamSimulationParticipant,
    TeamSimulationRecord,
    TeamSimulationStore,
    _DEFAULT_TEAM_SCENARIOS,
)


# ──────────────────────────────────────────────────────────────────────
# Class 1: EventTypes (6)
# ──────────────────────────────────────────────────────────────────────

class TestAd510EventTypes:
    def test_team_scenario_registered_value(self):
        assert EventType.TEAM_SCENARIO_REGISTERED.value == "team_scenario_registered"

    def test_team_simulation_started_value(self):
        assert EventType.TEAM_SIMULATION_STARTED.value == "team_simulation_started"

    def test_team_simulation_role_rotated_value(self):
        assert EventType.TEAM_SIMULATION_ROLE_ROTATED.value == "team_simulation_role_rotated"

    def test_team_simulation_communication_constraint_applied_value(self):
        assert (
            EventType.TEAM_SIMULATION_COMMUNICATION_CONSTRAINT_APPLIED.value
            == "team_simulation_communication_constraint_applied"
        )

    def test_team_simulation_debrief_recorded_value(self):
        assert EventType.TEAM_SIMULATION_DEBRIEF_RECORDED.value == "team_simulation_debrief_recorded"

    def test_team_simulation_completed_value(self):
        assert EventType.TEAM_SIMULATION_COMPLETED.value == "team_simulation_completed"


# ──────────────────────────────────────────────────────────────────────
# Class 2: HolodeckTeamSimulationConfig (6)
# ──────────────────────────────────────────────────────────────────────

class TestAd510Config:
    def test_default_disabled(self):
        cfg = HolodeckTeamSimulationConfig()
        assert cfg.enabled is False

    def test_default_auto_register_true(self):
        assert HolodeckTeamSimulationConfig().auto_register_with_harness is True

    def test_default_threshold_in_range(self):
        cfg = HolodeckTeamSimulationConfig()
        assert 0.0 <= cfg.default_threshold <= 1.0
        assert cfg.default_threshold == 0.6

    def test_default_tier_is_two(self):
        assert HolodeckTeamSimulationConfig().default_tier == 2

    def test_default_enforce_required_departments_true(self):
        assert HolodeckTeamSimulationConfig().enforce_required_departments is True

    def test_attached_to_system_config(self):
        sc = SystemConfig()
        assert hasattr(sc, "team_simulations")
        assert isinstance(sc.team_simulations, HolodeckTeamSimulationConfig)


# ──────────────────────────────────────────────────────────────────────
# Class 3: TeamScenario + TeamScenarioRegistry (6)
# ──────────────────────────────────────────────────────────────────────

class TestAd510ScenarioRegistry:
    def test_default_catalog_has_six_scenarios(self):
        assert len(_DEFAULT_TEAM_SCENARIOS) == 6

    def test_catalog_covers_all_axes(self):
        scenarios = list(_DEFAULT_TEAM_SCENARIOS)
        # Mixed-dept (all 6 require >=2 departments)
        assert all(len(s.required_departments) >= 2 for s in scenarios)
        # At least one time-pressured
        assert any(s.time_limit_seconds is not None for s in scenarios)
        # At least one communication-only
        assert any(s.communication_only for s in scenarios)
        # At least one role-rotation-allowed
        assert any(s.role_rotation_allowed for s in scenarios)

    def test_get_scenario_returns_scenario(self):
        reg = TeamScenarioRegistry()
        s = reg.get_scenario("medical_engineering_wellness_diagnose")
        assert s is not None
        assert "medical" in s.required_departments
        assert "engineering" in s.required_departments

    def test_get_scenario_missing_returns_none(self):
        assert TeamScenarioRegistry().get_scenario("nope") is None

    def test_list_by_department_filters_correctly(self):
        reg = TeamScenarioRegistry()
        eng = reg.list_by_department("engineering")
        assert all("engineering" in s.required_departments for s in eng)
        assert len(eng) >= 2

    def test_list_by_time_pressure_returns_only_timed(self):
        reg = TeamScenarioRegistry()
        timed = reg.list_by_time_pressure()
        assert all(s.time_limit_seconds is not None for s in timed)
        assert len(timed) >= 1

    def test_register_scenario_emits_event(self):
        reg = TeamScenarioRegistry()
        events: list = []
        reg.emit_event = lambda et, payload: events.append((et, payload))
        new_s = TeamScenario(
            scenario_id="custom_x",
            title="Custom",
            summary="Custom scenario",
            required_departments=("medical", "operations"),
            skills_tested=("communication",),
            learning_objectives=("Learn",),
        )
        reg.register_scenario(new_s)
        assert reg.get_scenario("custom_x") is new_s
        assert len(events) == 1
        assert events[0][0] is EventType.TEAM_SCENARIO_REGISTERED
        assert events[0][1]["scenario_id"] == "custom_x"


# ──────────────────────────────────────────────────────────────────────
# Class 4: Frozen dataclasses (4)
# ──────────────────────────────────────────────────────────────────────

class TestAd510Dataclasses:
    def test_team_simulation_participant_frozen(self):
        p = TeamSimulationParticipant(
            agent_id="a1", department="medical",
            assigned_role="medical", entered_at=1000.0,
        )
        with pytest.raises(Exception):
            p.assigned_role = "engineering"  # type: ignore[misc]

    def test_team_simulation_record_defaults(self):
        r = TeamSimulationRecord(
            simulation_id="s1", scenario_id="sc1",
            participants=tuple(), started_at=1000.0,
        )
        assert r.status == "started"
        assert r.completed_at is None
        assert r.last_score is None
        assert r.debrief_id is None

    def test_debrief_record_required_fields(self):
        d = DebriefRecord(
            debrief_id="d1", simulation_id="s1", scenario_id="sc1",
            started_at=1000.0, completed_at=1100.0,
            outcome_score=0.7, passed=True, time_elapsed=100.0,
            participants=tuple(),
        )
        assert d.notes == ""
        assert d.time_limit_seconds is None

    def test_team_scenario_default_difficulty(self):
        s = TeamScenario(
            scenario_id="x", title="x", summary="x",
            required_departments=("a", "b"),
            skills_tested=("y",),
            learning_objectives=("z",),
        )
        assert s.difficulty == 0.5
        assert s.communication_only is False
        assert s.role_rotation_allowed is False
        assert s.time_limit_seconds is None


# ──────────────────────────────────────────────────────────────────────
# Class 5: TeamSimulationDrill (5) — implements QualificationTest Protocol
# ──────────────────────────────────────────────────────────────────────

class TestAd510Drill:
    def _make_drill(self, sim_runner=None):
        scenario = TeamScenario(
            scenario_id="x", title="x", summary="x scenario summary",
            required_departments=("a", "b"),
            skills_tested=("y",),
            learning_objectives=("z",),
        )
        record = TeamSimulationRecord(
            simulation_id="sim_alpha", scenario_id="x",
            participants=tuple(), started_at=1000.0,
        )
        return TeamSimulationDrill(
            scenario=scenario, record=record, sim_runner=sim_runner,
        )

    def test_protocol_compliance(self):
        from probos.cognitive.qualification import QualificationTest
        d = self._make_drill()
        assert isinstance(d, QualificationTest)

    def test_name_format(self):
        assert self._make_drill().name == "holodeck_team:sim_alpha"

    def test_tier_threshold_description(self):
        d = self._make_drill()
        assert d.tier == 2
        assert d.threshold == 0.6
        assert d.description == "x scenario summary"

    @pytest.mark.asyncio
    async def test_run_with_no_runner_returns_noop_result(self):
        d = self._make_drill()
        rt = MagicMock(spec=[])
        result = await d.run("agent_007", rt)
        assert result.score == 0.5
        assert result.passed is False
        assert result.details["noop"] is True
        assert result.details["scenario_id"] == "x"
        assert result.details["simulation_id"] == "sim_alpha"

    @pytest.mark.asyncio
    async def test_run_with_runner_returns_runner_result(self):
        async def runner(scenario, record, runtime):
            return (0.85, True, {"reason": "well-done"})
        d = self._make_drill(sim_runner=runner)
        result = await d.run("agent_007", MagicMock(spec=[]))
        assert result.score == 0.85
        assert result.passed is True
        assert result.details["reason"] == "well-done"


# ──────────────────────────────────────────────────────────────────────
# Class 6: TeamSimulationStore (4)
# ──────────────────────────────────────────────────────────────────────

class TestAd510Store:
    @pytest.mark.asyncio
    async def test_in_memory_save_and_get_record(self):
        s = TeamSimulationStore(data_dir=None)
        await s.start()
        rec = TeamSimulationRecord(
            simulation_id="m1", scenario_id="sc1",
            participants=tuple(), started_at=1.0,
        )
        await s.save_record(rec)
        assert await s.get_record("m1") == rec
        await s.stop()

    @pytest.mark.asyncio
    async def test_save_and_get_debrief_in_memory(self):
        s = TeamSimulationStore(data_dir=None)
        await s.start()
        d = DebriefRecord(
            debrief_id="d1", simulation_id="s1", scenario_id="sc1",
            started_at=1.0, completed_at=2.0,
            outcome_score=0.8, passed=True, time_elapsed=1.0,
            participants=tuple(),
        )
        await s.save_debrief(d)
        assert await s.get_debrief("d1") == d
        await s.stop()

    @pytest.mark.asyncio
    async def test_list_records_by_scenario(self):
        s = TeamSimulationStore(data_dir=None)
        await s.start()
        for i in range(3):
            await s.save_record(TeamSimulationRecord(
                simulation_id=f"s{i}", scenario_id="sc",
                participants=tuple(), started_at=float(i),
            ))
        await s.save_record(TeamSimulationRecord(
            simulation_id="other", scenario_id="other_sc",
            participants=tuple(), started_at=99.0,
        ))
        out = await s.list_records_by_scenario("sc")
        assert len(out) == 3
        assert all(r.scenario_id == "sc" for r in out)
        await s.stop()

    @pytest.mark.asyncio
    async def test_sqlite_persistence_roundtrip(self, tmp_path):
        s = TeamSimulationStore(data_dir=tmp_path)
        await s.start()
        rec = TeamSimulationRecord(
            simulation_id="persisted", scenario_id="sc",
            participants=(TeamSimulationParticipant(
                agent_id="a1", department="medical",
                assigned_role="medical", entered_at=1.0,
            ),),
            started_at=1.0,
        )
        await s.save_record(rec)
        await s.stop()
        s2 = TeamSimulationStore(data_dir=tmp_path)
        await s2.start()
        loaded = await s2.get_record("persisted")
        assert loaded is not None
        assert loaded.simulation_id == "persisted"
        assert len(loaded.participants) == 1
        assert loaded.participants[0].agent_id == "a1"
        await s2.stop()


# ──────────────────────────────────────────────────────────────────────
# Class 7: TeamSimulationOrchestrator (12)
# ──────────────────────────────────────────────────────────────────────

class TestAd510Orchestrator:
    def _config(self, **kw) -> HolodeckTeamSimulationConfig:
        return HolodeckTeamSimulationConfig(enabled=True, **kw)

    async def _make(self, config=None):
        config = config or self._config()
        store = TeamSimulationStore(data_dir=None)
        await store.start()
        registry = TeamScenarioRegistry()
        events: list = []
        orch = TeamSimulationOrchestrator(
            config=config,
            store=store,
            emit_event_fn=lambda et, p: events.append((et, p)),
            team_scenario_registry=registry,
        )
        return orch, store, registry, events

    @pytest.mark.asyncio
    async def test_disabled_returns_none(self):
        orch, _, _, _ = await self._make(
            HolodeckTeamSimulationConfig(enabled=False)
        )
        result = await orch.start_simulation(
            "medical_engineering_wellness_diagnose",
            [("a1", "medical"), ("a2", "engineering")],
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_unknown_scenario_returns_none(self):
        orch, _, _, _ = await self._make()
        result = await orch.start_simulation(
            "nope_does_not_exist",
            [("a1", "medical"), ("a2", "engineering")],
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_missing_required_dept_returns_none(self):
        orch, _, _, _ = await self._make()
        result = await orch.start_simulation(
            "medical_engineering_wellness_diagnose",
            [("a1", "medical"), ("a2", "operations")],  # missing engineering
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_happy_path_emits_started_event(self):
        orch, store, _, events = await self._make()
        rec = await orch.start_simulation(
            "medical_engineering_wellness_diagnose",
            [("a1", "medical"), ("a2", "engineering")],
        )
        assert rec is not None
        assert rec.status == "started"
        started_events = [e for e in events if e[0] is EventType.TEAM_SIMULATION_STARTED]
        assert len(started_events) == 1
        assert started_events[0][1]["scenario_id"] == "medical_engineering_wellness_diagnose"
        assert await store.get_record(rec.simulation_id) == rec

    @pytest.mark.asyncio
    async def test_role_rotation_emits_event(self):
        orch, _, _, events = await self._make()
        rec = await orch.start_simulation(
            "engineering_science_research_buildout",  # role_rotation_allowed=True
            [("a1", "engineering"), ("a2", "science")],
            role_rotation={"a1": "science"},
        )
        assert rec is not None
        rotated = [e for e in events if e[0] is EventType.TEAM_SIMULATION_ROLE_ROTATED]
        assert len(rotated) == 1
        assert rotated[0][1]["agent_id"] == "a1"
        assert rotated[0][1]["original_role"] == "engineering"
        assert rotated[0][1]["rotated_role"] == "science"
        # And participant carries the rotated role
        assert rec.participants[0].assigned_role == "science"

    @pytest.mark.asyncio
    async def test_role_rotation_not_emitted_when_scenario_disallows(self):
        orch, _, _, events = await self._make()
        rec = await orch.start_simulation(
            "medical_engineering_wellness_diagnose",  # role_rotation_allowed=False
            [("a1", "medical"), ("a2", "engineering")],
            role_rotation={"a1": "engineering"},
        )
        assert rec is not None
        rotated = [e for e in events if e[0] is EventType.TEAM_SIMULATION_ROLE_ROTATED]
        assert rotated == []

    @pytest.mark.asyncio
    async def test_communication_only_emits_event(self):
        orch, _, _, events = await self._make()
        rec = await orch.start_simulation(
            "medical_communications_outbreak_brief",  # communication_only=True
            [("a1", "medical"), ("a2", "communications")],
        )
        assert rec is not None
        comm_events = [
            e for e in events
            if e[0] is EventType.TEAM_SIMULATION_COMMUNICATION_CONSTRAINT_APPLIED
        ]
        assert len(comm_events) == 1
        assert all(p.communication_only_constraint for p in rec.participants)

    @pytest.mark.asyncio
    async def test_time_limit_seconds_in_started_payload(self):
        orch, _, _, events = await self._make()
        await orch.start_simulation(
            "bridge_engineering_emergency_routing",  # 60s
            [("a1", "operations"), ("a2", "engineering")],
        )
        started = next(
            e for e in events if e[0] is EventType.TEAM_SIMULATION_STARTED
        )
        assert started[1]["time_limit_seconds"] == 60.0

    @pytest.mark.asyncio
    async def test_harness_register_test_called(self):
        orch, _, _, _ = await self._make()
        harness = MagicMock()
        harness.register_test = MagicMock()
        orch.set_qualification_harness(harness)
        rec = await orch.start_simulation(
            "medical_engineering_wellness_diagnose",
            [("a1", "medical"), ("a2", "engineering")],
        )
        assert rec is not None
        harness.register_test.assert_called_once()
        registered = harness.register_test.call_args[0][0]
        assert registered.name == f"holodeck_team:{rec.simulation_id}"

    @pytest.mark.asyncio
    async def test_complete_simulation_persists_debrief_and_emits(self):
        orch, store, _, events = await self._make()
        rec = await orch.start_simulation(
            "medical_engineering_wellness_diagnose",
            [("a1", "medical"), ("a2", "engineering")],
        )
        assert rec is not None
        debrief = await orch.complete_simulation(
            rec.simulation_id, score=0.82, passed=True, notes="Good handoff",
        )
        assert debrief is not None
        assert debrief.outcome_score == 0.82
        assert debrief.passed is True
        assert debrief.notes == "Good handoff"
        assert await store.get_debrief(debrief.debrief_id) == debrief
        # Updated record reflects completion
        updated = await store.get_record(rec.simulation_id)
        assert updated is not None
        assert updated.status == "completed"
        assert updated.last_score == 0.82
        assert updated.debrief_id == debrief.debrief_id
        # Both events emitted
        kinds = [e[0] for e in events]
        assert EventType.TEAM_SIMULATION_DEBRIEF_RECORDED in kinds
        assert EventType.TEAM_SIMULATION_COMPLETED in kinds

    @pytest.mark.asyncio
    async def test_complete_simulation_unknown_id_returns_none(self):
        orch, _, _, _ = await self._make()
        result = await orch.complete_simulation("does_not_exist", score=0.5)
        assert result is None

    @pytest.mark.asyncio
    async def test_debrief_publisher_invoked_and_exception_logged(self, caplog):
        orch, _, _, _ = await self._make()
        publisher = AsyncMock()
        orch.set_debrief_publisher(publisher)
        rec = await orch.start_simulation(
            "medical_engineering_wellness_diagnose",
            [("a1", "medical"), ("a2", "engineering")],
        )
        assert rec is not None
        debrief = await orch.complete_simulation(rec.simulation_id, score=0.7)
        assert debrief is not None
        publisher.assert_awaited_once_with(debrief)
        # Exception path — replace publisher; orchestrator must log+continue
        bad = AsyncMock(side_effect=RuntimeError("publisher down"))
        orch.set_debrief_publisher(bad)
        rec2 = await orch.start_simulation(
            "medical_engineering_wellness_diagnose",
            [("a1", "medical"), ("a2", "engineering")],
        )
        assert rec2 is not None
        with caplog.at_level("WARNING"):
            d2 = await orch.complete_simulation(rec2.simulation_id, score=0.5)
        assert d2 is not None
        assert any("debrief_publisher raised" in m for m in caplog.messages)


# ──────────────────────────────────────────────────────────────────────
# Class 8: Startup wiring (3)
# ──────────────────────────────────────────────────────────────────────

class TestAd510StartupWiring:
    def test_disabled_does_not_set_attributes(self):
        from types import SimpleNamespace
        from probos.startup.finalize import _wire_holodeck_team_simulations
        sc = SystemConfig()
        rt = SimpleNamespace()
        wired = _wire_holodeck_team_simulations(runtime=rt, config=sc)
        assert wired is False
        assert not hasattr(rt, "team_simulation_orchestrator")
        assert not hasattr(rt, "team_scenario_registry")

    def test_enabled_sets_orchestrator_and_registry(self):
        from types import SimpleNamespace
        from probos.startup.finalize import _wire_holodeck_team_simulations
        sc = SystemConfig()
        sc.team_simulations.enabled = True
        rt = SimpleNamespace(emit_event=lambda et, p: None)
        wired = _wire_holodeck_team_simulations(runtime=rt, config=sc)
        assert wired is True
        assert isinstance(rt.team_simulation_orchestrator, TeamSimulationOrchestrator)
        assert isinstance(rt.team_scenario_registry, TeamScenarioRegistry)

    def test_late_bind_harness_attached_when_present(self):
        from types import SimpleNamespace
        from probos.startup.finalize import _wire_holodeck_team_simulations
        sc = SystemConfig()
        sc.team_simulations.enabled = True
        harness = MagicMock()
        rt = SimpleNamespace(
            emit_event=lambda et, p: None,
            qualification_harness=harness,
        )
        _wire_holodeck_team_simulations(runtime=rt, config=sc)
        assert rt.team_simulation_orchestrator.qualification_harness is harness
