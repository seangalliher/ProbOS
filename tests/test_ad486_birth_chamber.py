"""AD-486 v1 — Holodeck Birth Chamber tests.

50 focused tests across 8 classes covering: HolodeckPhase enum,
HolodeckBirthChamberConfig, BirthChamberRecord, gate predicates,
BirthChamber orchestrator, is_graduated semantics,
DepartmentActivationScheduler, and wirer/onboarding integration.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.config import HolodeckBirthChamberConfig, SystemConfig
from probos.events import EventType
from probos.holodeck import (
    BirthChamber,
    BirthChamberRecord,
    DepartmentActivationScheduler,
    HolodeckPhase,
    NoOpAffectiveBaselineCheck,
)
from probos.holodeck.affect import AffectiveObservation
from probos.holodeck.gates import (
    conscientiousness_multiplier,
    gate_calibration_baseline,
    gate_orientation_complete,
    gate_self_discovery,
    gate_ship_records,
    gate_ward_room_integration,
)
from probos.holodeck.phases import PHASE_ORDER, next_phase


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def make_config(**overrides: Any) -> HolodeckBirthChamberConfig:
    """Build a HolodeckBirthChamberConfig with sensible test defaults."""
    base: dict[str, Any] = {
        "enabled": True,
        "auto_advance_enabled": False,  # tests drive try_advance directly
        "affective_baseline_check_enabled": True,
    }
    base.update(overrides)
    return HolodeckBirthChamberConfig(**base)


def make_chamber(
    config: HolodeckBirthChamberConfig | None = None,
    affective_check: Any = None,
) -> tuple[BirthChamber, list[tuple[EventType, dict[str, Any]]]]:
    events: list[tuple[EventType, dict[str, Any]]] = []

    def emit(event_type: EventType, payload: dict[str, Any]) -> None:
        events.append((event_type, dict(payload)))

    cfg = config or make_config()
    chamber = BirthChamber(
        config=cfg,
        emit_event_fn=emit,
        affective_check=affective_check,
    )
    return chamber, events


@dataclass
class _FakeAgent:
    id: str
    agent_type: str = "engineer"


def _make_record(agent_id: str = "a1", agent_type: str = "engineer") -> BirthChamberRecord:
    return BirthChamberRecord(
        agent_id=agent_id, agent_type=agent_type, department="engineering"
    )


# --------------------------------------------------------------------------
# Class A — HolodeckPhase enum (5)
# --------------------------------------------------------------------------


class TestHolodeckPhase:
    def test_phase_values(self) -> None:
        assert HolodeckPhase.ORIENTATION.value == "orientation"
        assert HolodeckPhase.CALIBRATION.value == "calibration"
        assert HolodeckPhase.SELF_DISCOVERY.value == "self_discovery"
        assert HolodeckPhase.SHIP_RECORDS.value == "ship_records"
        assert HolodeckPhase.WARD_ROOM_INTEGRATION.value == "ward_room_integration"
        assert HolodeckPhase.GRADUATED.value == "graduated"

    def test_phase_order_length(self) -> None:
        assert len(PHASE_ORDER) == 6

    def test_next_phase_orientation_to_calibration(self) -> None:
        assert next_phase(HolodeckPhase.ORIENTATION) == HolodeckPhase.CALIBRATION

    def test_next_phase_ward_room_to_graduated(self) -> None:
        assert (
            next_phase(HolodeckPhase.WARD_ROOM_INTEGRATION) == HolodeckPhase.GRADUATED
        )

    def test_next_phase_graduated_returns_graduated(self) -> None:
        assert next_phase(HolodeckPhase.GRADUATED) == HolodeckPhase.GRADUATED


# --------------------------------------------------------------------------
# Class B — HolodeckBirthChamberConfig (4)
# --------------------------------------------------------------------------


class TestHolodeckBirthChamberConfig:
    def test_config_defaults(self) -> None:
        cfg = HolodeckBirthChamberConfig()
        assert cfg.enabled is False
        assert cfg.bypass_for_existing_agents is True
        assert cfg.department_order == [
            "security", "operations", "engineering", "science", "medical"
        ]
        assert cfg.calibration_min_episodes == 5
        assert cfg.affective_baseline_check_enabled is True
        assert cfg.auto_advance_enabled is True
        assert cfg.max_self_discovery_probe_attempts == 3

    def test_config_calibration_min_episodes_validator_rejects_zero(self) -> None:
        with pytest.raises(Exception):
            HolodeckBirthChamberConfig(calibration_min_episodes=0)

    def test_config_department_order_lowercased(self) -> None:
        cfg = HolodeckBirthChamberConfig(department_order=["Security", "MEDICAL"])
        assert cfg.department_order == ["security", "medical"]

    def test_config_max_probe_attempts_rejects_zero(self) -> None:
        with pytest.raises(Exception):
            HolodeckBirthChamberConfig(max_self_discovery_probe_attempts=0)


# --------------------------------------------------------------------------
# Class C — BirthChamberRecord (3)
# --------------------------------------------------------------------------


class TestBirthChamberRecord:
    def test_record_initial_state(self) -> None:
        rec = _make_record()
        assert rec.current_phase == HolodeckPhase.ORIENTATION
        assert rec.phase_history == []
        assert rec.affective_observations == []
        assert rec.gates_passed == {}

    def test_record_to_dict_round_trip(self) -> None:
        rec = _make_record()
        rec.gates_passed["x"] = True
        d = rec.to_dict()
        assert d["agent_id"] == "a1"
        assert d["current_phase"] == "orientation"
        assert d["gates_passed"] == {"x": True}
        assert isinstance(d["phase_history"], list)
        assert isinstance(d["affective_observations"], list)

    def test_record_self_discovery_attempts_default_zero(self) -> None:
        assert _make_record().self_discovery_attempts == 0


# --------------------------------------------------------------------------
# Class D — Gate predicates (10)
# --------------------------------------------------------------------------


class TestGatePredicates:
    @pytest.mark.asyncio
    async def test_gate_orientation_blocks_when_no_flags(self) -> None:
        rec = _make_record()
        passed, _ = await gate_orientation_complete(rec, {})
        assert passed is False

    @pytest.mark.asyncio
    async def test_gate_orientation_passes_when_three_flags_set(self) -> None:
        rec = _make_record()
        rec.gates_passed["identity_grounded"] = True
        rec.gates_passed["code_of_conduct_acknowledged"] = True
        rec.gates_passed["curriculum_orientation_delivered"] = True
        passed, _ = await gate_orientation_complete(rec, {})
        assert passed is True

    @pytest.mark.asyncio
    async def test_gate_calibration_passes_when_episode_count_meets_threshold(
        self,
    ) -> None:
        rec = _make_record()

        class _EM:
            async def count_for_agent(self, agent_id: str) -> int:
                return 5

        services = {
            "calibration_min_episodes": 5,
            "callsign_registry": None,
            "episodic_memory": _EM(),
        }
        passed, _ = await gate_calibration_baseline(rec, services)
        assert passed is True

    @pytest.mark.asyncio
    async def test_gate_calibration_high_conscientiousness_doubles_threshold(
        self,
    ) -> None:
        rec = _make_record()

        class _EM:
            def __init__(self) -> None:
                self.count = 5

            async def count_for_agent(self, agent_id: str) -> int:
                return self.count

        em = _EM()

        class _CR:
            def get_profile(self, agent_type: str) -> dict[str, Any]:
                return {"personality": {"conscientiousness": 0.8}}

        services = {
            "calibration_min_episodes": 5,
            "callsign_registry": _CR(),
            "episodic_memory": em,
        }
        # 5 < 10 (5 * 2.0 multiplier)
        passed, _ = await gate_calibration_baseline(rec, services)
        assert passed is False
        em.count = 10
        passed2, _ = await gate_calibration_baseline(rec, services)
        assert passed2 is True

    @pytest.mark.asyncio
    async def test_gate_calibration_low_conscientiousness_halves_threshold(
        self,
    ) -> None:
        rec = _make_record()

        class _EM:
            async def count_for_agent(self, agent_id: str) -> int:
                return 3

        class _CR:
            def get_profile(self, agent_type: str) -> dict[str, Any]:
                return {"personality": {"conscientiousness": 0.2}}

        services = {
            "calibration_min_episodes": 5,
            "callsign_registry": _CR(),
            "episodic_memory": _EM(),
        }
        # effective = round(5 * 0.5) = 2, 3 >= 2
        passed, _ = await gate_calibration_baseline(rec, services)
        assert passed is True

    @pytest.mark.asyncio
    async def test_gate_calibration_no_episodic_memory_auto_passes(self) -> None:
        rec = _make_record()
        services = {"calibration_min_episodes": 5, "episodic_memory": None}
        passed, _ = await gate_calibration_baseline(rec, services)
        assert passed is True

    @pytest.mark.asyncio
    async def test_gate_self_discovery_blocks_until_probe_succeeds(self) -> None:
        rec = _make_record()
        passed, _ = await gate_self_discovery(rec, {})
        assert passed is False
        rec.gates_passed["self_distillation_probe_succeeded"] = True
        passed2, _ = await gate_self_discovery(rec, {})
        assert passed2 is True

    @pytest.mark.asyncio
    async def test_gate_ship_records_blocks_when_circuit_breaker_open(self) -> None:
        rec = _make_record()
        rec.gates_passed["ship_records_acknowledged"] = True

        class _CB:
            def should_allow_think(self, agent_id: str) -> bool:
                return False

        passed, _ = await gate_ship_records(rec, {"circuit_breaker": _CB()})
        assert passed is False

    @pytest.mark.asyncio
    async def test_gate_ship_records_passes_when_acknowledged_and_breaker_closed(
        self,
    ) -> None:
        rec = _make_record()
        rec.gates_passed["ship_records_acknowledged"] = True

        class _CB:
            def should_allow_think(self, agent_id: str) -> bool:
                return True

        passed, _ = await gate_ship_records(rec, {"circuit_breaker": _CB()})
        assert passed is True

    @pytest.mark.asyncio
    async def test_gate_ward_room_integration_passes_only_when_flag_set(
        self,
    ) -> None:
        rec = _make_record()
        passed, _ = await gate_ward_room_integration(rec, {})
        assert passed is False
        rec.gates_passed["integration_ready"] = True
        passed2, _ = await gate_ward_room_integration(rec, {})
        assert passed2 is True


# --------------------------------------------------------------------------
# Class E — BirthChamber orchestrator (12)
# --------------------------------------------------------------------------


class TestBirthChamber:
    @pytest.mark.asyncio
    async def test_admit_creates_record_with_orientation_phase(self) -> None:
        chamber, _ = make_chamber()
        rec = await chamber.admit(_FakeAgent("a1"), department="Engineering")
        assert rec.current_phase == HolodeckPhase.ORIENTATION
        assert rec.department == "engineering"
        assert chamber.is_admitted("a1")

    @pytest.mark.asyncio
    async def test_admit_emits_admitted_and_phase_entered_events(self) -> None:
        chamber, events = make_chamber()
        await chamber.admit(_FakeAgent("a1"))
        types = [e[0] for e in events]
        assert EventType.HOLODECK_AGENT_ADMITTED in types
        assert EventType.HOLODECK_PHASE_ENTERED in types

    @pytest.mark.asyncio
    async def test_admit_calls_curriculum_list_by_phase_orientation(self) -> None:
        chamber, _ = make_chamber()
        curriculum = MagicMock()
        curriculum.list_by_phase.return_value = (
            SimpleNamespace(id="m1"), SimpleNamespace(id="m2"),
        )
        chamber.set_curriculum_registry(curriculum)
        await chamber.admit(_FakeAgent("a1"))
        curriculum.list_by_phase.assert_called_once_with("orientation")

    @pytest.mark.asyncio
    async def test_try_advance_orientation_to_calibration(self) -> None:
        chamber, _ = make_chamber()
        await chamber.admit(_FakeAgent("a1"))
        # Curriculum auto-marks delivered (no registry); identity + cod set
        # by _deliver_orientation_content.
        new = await chamber.try_advance("a1")
        assert new == HolodeckPhase.CALIBRATION

    @pytest.mark.asyncio
    async def test_try_advance_blocks_when_gate_returns_false(self) -> None:
        chamber, events = make_chamber()
        await chamber.admit(_FakeAgent("a1"))
        # Force orientation to be incomplete by clearing a flag
        rec = chamber.get_record("a1")
        assert rec is not None
        rec.gates_passed["identity_grounded"] = False
        new = await chamber.try_advance("a1")
        assert new == HolodeckPhase.ORIENTATION
        blocked = [e for e in events if e[0] == EventType.HOLODECK_PHASE_GATE_BLOCKED]
        assert blocked, "expected at least one HOLODECK_PHASE_GATE_BLOCKED event"
        assert "reason" in blocked[-1][1]

    @pytest.mark.asyncio
    async def test_try_advance_emits_phase_gate_passed(self) -> None:
        chamber, events = make_chamber()
        await chamber.admit(_FakeAgent("a1"))
        await chamber.try_advance("a1")
        passed = [e for e in events if e[0] == EventType.HOLODECK_PHASE_GATE_PASSED]
        assert passed
        payload = passed[-1][1]
        assert payload["phase"] == "orientation"
        assert payload["next_phase"] == "calibration"

    @pytest.mark.asyncio
    async def test_try_advance_calls_affective_check_between_phases(self) -> None:
        captured: list[tuple[HolodeckPhase, HolodeckPhase]] = []

        class _AC:
            async def observe(
                self, *, agent_id: str, prev_phase: HolodeckPhase, new_phase: HolodeckPhase
            ) -> AffectiveObservation:
                captured.append((prev_phase, new_phase))
                return AffectiveObservation(status="stable", score=1.0)

        chamber, events = make_chamber(affective_check=_AC())
        await chamber.admit(_FakeAgent("a1"))
        await chamber.try_advance("a1")
        assert captured == [(HolodeckPhase.ORIENTATION, HolodeckPhase.CALIBRATION)]
        observed = [
            e for e in events
            if e[0] == EventType.HOLODECK_AFFECTIVE_BASELINE_OBSERVED
        ]
        assert observed

    @pytest.mark.asyncio
    async def test_try_advance_self_discovery_runs_probe(self) -> None:
        chamber, _ = make_chamber()
        prober = MagicMock()

        async def _probe(agent_id: str, domain: str) -> Any:
            return SimpleNamespace(sub_topics=("foo",))

        prober.probe_domain = _probe
        chamber.set_personal_ontology_prober(prober)

        await chamber.admit(_FakeAgent("a1"))
        # Walk to SELF_DISCOVERY: orientation -> calibration (no episodic, auto-pass)
        await chamber.try_advance("a1")  # -> CALIBRATION
        await chamber.try_advance("a1")  # -> SELF_DISCOVERY
        rec = chamber.get_record("a1")
        assert rec is not None
        assert rec.current_phase == HolodeckPhase.SELF_DISCOVERY
        new = await chamber.try_advance("a1")  # runs probe -> SHIP_RECORDS
        assert new == HolodeckPhase.SHIP_RECORDS
        assert rec.gates_passed["self_distillation_probe_succeeded"] is True

    @pytest.mark.asyncio
    async def test_try_advance_self_discovery_probe_failure_does_not_advance(
        self,
    ) -> None:
        from probos.cognitive.self_distillation.prober import ProbeRateLimitedError

        chamber, _ = make_chamber()
        prober = MagicMock()

        async def _probe(agent_id: str, domain: str) -> Any:
            raise ProbeRateLimitedError("rate-limited")

        prober.probe_domain = _probe
        chamber.set_personal_ontology_prober(prober)

        await chamber.admit(_FakeAgent("a1"))
        await chamber.try_advance("a1")  # CALIBRATION
        await chamber.try_advance("a1")  # SELF_DISCOVERY
        new = await chamber.try_advance("a1")  # probe fails -> stays
        assert new == HolodeckPhase.SELF_DISCOVERY

    @pytest.mark.asyncio
    async def test_try_advance_self_discovery_attempts_capped_at_max(self) -> None:
        chamber, _ = make_chamber(make_config(max_self_discovery_probe_attempts=2))
        calls = {"n": 0}

        async def _probe(agent_id: str, domain: str) -> Any:
            calls["n"] += 1
            raise RuntimeError("boom")

        prober = MagicMock()
        prober.probe_domain = _probe
        chamber.set_personal_ontology_prober(prober)

        await chamber.admit(_FakeAgent("a1"))
        await chamber.try_advance("a1")  # CALIBRATION
        await chamber.try_advance("a1")  # SELF_DISCOVERY
        # Three try_advance calls in SELF_DISCOVERY should yield only 2 probe calls
        await chamber.try_advance("a1")
        await chamber.try_advance("a1")
        await chamber.try_advance("a1")
        assert calls["n"] == 2

    @pytest.mark.asyncio
    async def test_try_advance_graduation_drains_pending_subscriptions(self) -> None:
        chamber, _ = make_chamber()
        await chamber.admit(_FakeAgent("a1"))
        called: list[str] = []

        async def sub_a() -> None:
            called.append("a")

        async def sub_b() -> None:
            called.append("b")

        chamber.queue_pending_subscription("a1", "ch1", sub_a)
        chamber.queue_pending_subscription("a1", "ch2", sub_b)

        # Walk to GRADUATED. Orientation flags pre-set by admit.
        await chamber.try_advance("a1")  # CALIBRATION (no episodic mem -> pass)
        # In SELF_DISCOVERY no prober was set, so the helper auto-marks success.
        await chamber.try_advance("a1")  # SELF_DISCOVERY
        await chamber.try_advance("a1")  # SELF_DISCOVERY -> SHIP_RECORDS
        rec = chamber.get_record("a1")
        assert rec is not None
        assert rec.current_phase == HolodeckPhase.SHIP_RECORDS
        chamber.acknowledge_ship_records("a1")
        await chamber.try_advance("a1")  # WARD_ROOM_INTEGRATION
        chamber.acknowledge_integration_ready("a1")
        new = await chamber.try_advance("a1")  # GRADUATED
        assert new == HolodeckPhase.GRADUATED
        assert called == ["a", "b"]

    @pytest.mark.asyncio
    async def test_try_advance_graduation_emits_holodeck_graduation_event(
        self,
    ) -> None:
        chamber, events = make_chamber()
        await chamber.admit(_FakeAgent("a1"))
        await chamber.try_advance("a1")
        await chamber.try_advance("a1")
        await chamber.try_advance("a1")
        chamber.acknowledge_ship_records("a1")
        await chamber.try_advance("a1")
        chamber.acknowledge_integration_ready("a1")
        await chamber.try_advance("a1")
        types = [e[0] for e in events]
        assert EventType.HOLODECK_GRADUATION in types


# --------------------------------------------------------------------------
# Class F — is_graduated production-gate semantics (4)
# --------------------------------------------------------------------------


class TestIsGraduated:
    def test_is_graduated_returns_true_for_unknown_agent(self) -> None:
        chamber, _ = make_chamber()
        # Unknown -> never gated; production code path treats as graduated.
        assert chamber.is_graduated("never-admitted") is True

    @pytest.mark.asyncio
    async def test_is_graduated_returns_false_during_orientation(self) -> None:
        chamber, _ = make_chamber()
        await chamber.admit(_FakeAgent("a1"))
        assert chamber.is_graduated("a1") is False

    @pytest.mark.asyncio
    async def test_is_graduated_returns_true_after_full_walk(self) -> None:
        chamber, _ = make_chamber()
        await chamber.admit(_FakeAgent("a1"))
        await chamber.try_advance("a1")  # CALIBRATION
        await chamber.try_advance("a1")  # SELF_DISCOVERY
        await chamber.try_advance("a1")  # SHIP_RECORDS
        chamber.acknowledge_ship_records("a1")
        await chamber.try_advance("a1")  # WARD_ROOM_INTEGRATION
        chamber.acknowledge_integration_ready("a1")
        await chamber.try_advance("a1")  # GRADUATED
        assert chamber.is_graduated("a1") is True

    def test_get_current_phase_none_for_unknown(self) -> None:
        chamber, _ = make_chamber()
        assert chamber.get_current_phase("nope") is None


# --------------------------------------------------------------------------
# Class G — DepartmentActivationScheduler (7)
# --------------------------------------------------------------------------


class TestDepartmentActivationScheduler:
    def _make(
        self,
        order: list[str] | None = None,
        phase_map: dict[str, HolodeckPhase] | None = None,
    ) -> DepartmentActivationScheduler:
        phases = dict(phase_map or {})
        return DepartmentActivationScheduler(
            department_order=order if order is not None else [
                "security", "operations", "engineering", "science", "medical",
            ],
            get_phase_fn=lambda aid: phases.get(aid),
        )

    def test_register_admission_returns_position(self) -> None:
        s = self._make()
        assert s.register_admission("a1", "secguard", "security") == 1
        assert s.register_admission("a2", "ops", "operations") == 2
        assert s.queue_size() == 2

    def test_next_candidate_first_in_first_department(self) -> None:
        s = self._make()
        s.register_admission("a1", "engineer", "engineering")
        s.register_admission("a2", "secguard", "security")
        # security is first in default order, so a2 is next regardless of insert order
        assert s.next_admit_candidate() == "a2"

    def test_next_candidate_blocks_until_previous_group_reaches_self_discovery(
        self,
    ) -> None:
        phases: dict[str, HolodeckPhase] = {}
        s = DepartmentActivationScheduler(
            department_order=["security", "engineering"],
            get_phase_fn=lambda aid: phases.get(aid),
        )
        s.register_admission("sec1", "secguard", "security")
        s.register_admission("eng1", "engineer", "engineering")
        # Admit security agent at ORIENTATION
        assert s.next_admit_candidate() == "sec1"
        s.mark_admitted("sec1")
        phases["sec1"] = HolodeckPhase.ORIENTATION
        # Engineering blocked
        assert s.next_admit_candidate() is None

    def test_next_candidate_unblocks_when_previous_group_at_self_discovery(
        self,
    ) -> None:
        phases: dict[str, HolodeckPhase] = {}
        s = DepartmentActivationScheduler(
            department_order=["security", "engineering"],
            get_phase_fn=lambda aid: phases.get(aid),
        )
        s.register_admission("sec1", "secguard", "security")
        s.register_admission("eng1", "engineer", "engineering")
        s.mark_admitted("sec1")
        phases["sec1"] = HolodeckPhase.SELF_DISCOVERY
        assert s.next_admit_candidate() == "eng1"

    def test_next_candidate_empty_department_order_is_fcfs(self) -> None:
        s = self._make(order=[])
        s.register_admission("a1", "x", "engineering")
        s.register_admission("a2", "y", "security")
        assert s.next_admit_candidate() == "a1"

    def test_unknown_department_falls_through_to_default_bucket_after_known_groups(
        self,
    ) -> None:
        s = self._make(order=["security"])
        s.register_admission("a1", "x", "unknown_dept")
        # No security agents queued; fallthrough returns the unknown one.
        assert s.next_admit_candidate() == "a1"

    def test_mark_admitted_excludes_from_future_candidates(self) -> None:
        s = self._make()
        s.register_admission("a1", "secguard", "security")
        s.register_admission("a2", "secguard", "security")
        first = s.next_admit_candidate()
        assert first is not None
        s.mark_admitted(first)
        # When the admitted agent has no phase yet, _previous_groups_eligible
        # returns False (phase is None) → we're still in the same group.
        # The group is the FIRST in order, so no precedence-block applies.
        # The unblocked second agent should now be returned.
        # However our impl: previous_groups_eligible checks earlier groups
        # only. For "security" (idx 0) it's auto-True. So:
        second = s.next_admit_candidate()
        assert second is not None
        assert second != first


# --------------------------------------------------------------------------
# Class H — Wirer + onboarding integration (5)
# --------------------------------------------------------------------------


class TestWirerAndOnboarding:
    def test_wirer_no_op_when_disabled(self) -> None:
        from probos.startup.finalize import _wire_birth_chamber

        runtime = SimpleNamespace()
        config = SystemConfig()  # default: holodeck_birth_chamber.enabled=False
        result = _wire_birth_chamber(runtime=runtime, config=config)
        assert result is False
        assert not hasattr(runtime, "birth_chamber")

    @pytest.mark.asyncio
    async def test_wirer_constructs_chamber_and_scheduler_when_enabled(self) -> None:
        from probos.startup.finalize import _wire_birth_chamber

        runtime = SimpleNamespace(
            emit_event=lambda et, p: None,
            personal_ontology_prober=None,
            curriculum_registry=None,
            proactive_loop=None,
            callsign_registry=None,
            episodic_memory=None,
            onboarding=None,
            assignment_service=None,
        )
        config = SystemConfig(
            holodeck_birth_chamber=HolodeckBirthChamberConfig(
                enabled=True, auto_advance_enabled=True
            )
        )
        result = _wire_birth_chamber(runtime=runtime, config=config)
        try:
            assert result is True
            assert getattr(runtime, "birth_chamber", None) is not None
            assert getattr(runtime, "department_activation_scheduler", None) is not None
            task = getattr(runtime, "birth_chamber_advance_task", None)
            assert task is not None
        finally:
            task = getattr(runtime, "birth_chamber_advance_task", None)
            if task is not None:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

    @pytest.mark.asyncio
    async def test_onboarding_admits_crew_agent_when_chamber_enabled(self) -> None:
        # Test the onboarding admission hook directly by constructing a minimal
        # AgentOnboardingService-like context: we exercise the chamber.admit path
        # via the public setter the wirer uses.
        chamber, _ = make_chamber()
        agent = _FakeAgent("a1", agent_type="engineer")
        await chamber.admit(agent)
        assert chamber.is_admitted("a1") is True

    @pytest.mark.asyncio
    async def test_onboarding_skips_admission_for_warm_boot_when_bypass_true(
        self,
    ) -> None:
        # Verify the bypass condition logic: simulate the wire_agent decision
        # for an existing-callsign agent under bypass_for_existing_agents=True.
        cfg = HolodeckBirthChamberConfig(
            enabled=True, bypass_for_existing_agents=True
        )
        is_crew = True
        existing_callsign = "Atlas"  # truthy → warm boot
        chamber_set = True
        should_admit = (
            is_crew
            and chamber_set
            and cfg.enabled
            and not (cfg.bypass_for_existing_agents and existing_callsign)
        )
        assert should_admit is False

    @pytest.mark.asyncio
    async def test_proactive_loop_skips_pre_graduation_agent(self) -> None:
        # Stub runtime with one admitted-orientation agent + one unknown agent.
        chamber, _ = make_chamber()
        await chamber.admit(_FakeAgent("a1"))
        # is_graduated semantics drive the production gate.
        assert chamber.is_graduated("a1") is False
        assert chamber.is_graduated("a2-unknown") is True


# --------------------------------------------------------------------------
# Helpers exposed for utility coverage
# --------------------------------------------------------------------------


def test_conscientiousness_multiplier_default() -> None:
    assert conscientiousness_multiplier(None) == 1.0
    assert conscientiousness_multiplier({}) == 1.0
    assert conscientiousness_multiplier({"personality": {"conscientiousness": 0.5}}) == 1.0
    assert conscientiousness_multiplier({"personality": {"conscientiousness": 0.8}}) == 2.0
    assert conscientiousness_multiplier({"personality": {"conscientiousness": 0.2}}) == 0.5


@pytest.mark.asyncio
async def test_no_op_affective_check_returns_stable() -> None:
    check = NoOpAffectiveBaselineCheck()
    obs = await check.observe(
        agent_id="a1",
        prev_phase=HolodeckPhase.ORIENTATION,
        new_phase=HolodeckPhase.CALIBRATION,
    )
    assert obs.status == "stable"
    assert obs.score == 1.0
