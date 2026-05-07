"""AD-539b v1 — Holodeck scenario generation from skill gaps."""

import pytest
from unittest.mock import MagicMock

from probos.cognitive.gap_predictor import GapReport
from probos.cognitive.qualification import (
    QualificationHarness,
    QualificationTest,
    TestResult,
)
from probos.config import HolodeckScenarioConfig, SystemConfig
from probos.crew_development.discovery.scenarios import (
    DiscoveryScenario,
    DiscoveryScenarioRegistry,
)
from probos.events import EventType
from probos.holodeck.scenarios import (
    GapScenarioGenerator,
    HolodeckGapBridge,
    HolodeckGapDrill,
    HolodeckScenarioStore,
    ScenarioGapLink,
    ScenarioOutcome,
)


# ---------------------------------------------------------------------
# 0. EventTypes
# ---------------------------------------------------------------------

class TestEventTypes:
    def test_scenario_generated_value(self):
        assert EventType.HOLODECK_SCENARIO_GENERATED.value == "holodeck_scenario_generated"

    def test_scenario_registered_value(self):
        assert EventType.HOLODECK_SCENARIO_REGISTERED.value == "holodeck_scenario_registered"

    def test_scenario_gap_linked_value(self):
        assert EventType.HOLODECK_SCENARIO_GAP_LINKED.value == "holodeck_scenario_gap_linked"

    def test_scenario_outcome_recorded_value(self):
        assert EventType.HOLODECK_SCENARIO_OUTCOME_RECORDED.value == "holodeck_scenario_outcome_recorded"


# ---------------------------------------------------------------------
# 1. Config
# ---------------------------------------------------------------------

class TestConfig:
    def test_defaults(self):
        cfg = HolodeckScenarioConfig()
        assert cfg.enabled is False
        assert cfg.auto_register_with_harness is True
        assert cfg.default_threshold == 0.6
        assert cfg.default_tier == 2
        assert cfg.category_fallback == "construction"

    def test_threshold_bounds(self):
        with pytest.raises(Exception):
            HolodeckScenarioConfig(default_threshold=1.5)

    def test_tier_bounds(self):
        with pytest.raises(Exception):
            HolodeckScenarioConfig(default_tier=5)

    def test_system_config_field(self):
        sc = SystemConfig()
        assert isinstance(sc.holodeck_scenarios, HolodeckScenarioConfig)
        assert sc.holodeck_scenarios.enabled is False

    def test_persist_default_off(self):
        assert HolodeckScenarioConfig().persist_to_sqlite is False


# ---------------------------------------------------------------------
# 2. ScenarioGapLink
# ---------------------------------------------------------------------

class TestScenarioGapLink:
    def test_frozen(self):
        link = ScenarioGapLink(gap_id="g1", scenario_id="s1", drill_test_name="d1",
                               agent_id="a1", generated_at=1.0)
        with pytest.raises(Exception):
            link.gap_id = "g2"  # type: ignore

    def test_default_status_generated(self):
        link = ScenarioGapLink(gap_id="g1", scenario_id="s1", drill_test_name="d1",
                               agent_id="a1", generated_at=1.0)
        assert link.status == "generated"
        assert link.last_run_score is None

    def test_to_dict_roundtrip(self):
        link = ScenarioGapLink(gap_id="g1", scenario_id="s1", drill_test_name="d1",
                               agent_id="a1", generated_at=1.0,
                               status="executed", last_run_score=0.8, last_run_at=2.0)
        d = link.to_dict()
        assert d["status"] == "executed"
        assert d["last_run_score"] == 0.8

    def test_field_order_defaults_after_required(self):
        # Required fields first
        link = ScenarioGapLink("g", "s", "d", "a", 1.0)
        assert link.status == "generated"


# ---------------------------------------------------------------------
# 3. GapScenarioGenerator
# ---------------------------------------------------------------------

def _make_gap(**overrides):
    defaults = dict(
        id="gap:test:abc", agent_id="agent-1", agent_type="science",
        gap_type="knowledge", description="Lacks diagnose ability",
        evidence_sources=["episode:low_confidence"],
        affected_intent_types=["diagnose"], failure_rate=0.5,
        episode_count=5, mapped_skill_id="diagnose", current_proficiency=1,
        target_proficiency=3, priority="medium",
    )
    defaults.update(overrides)
    return GapReport(**defaults)


class TestGapScenarioGenerator:
    def test_no_registry_no_match_returns_template(self):
        gen = GapScenarioGenerator()
        gap = _make_gap(affected_intent_types=["xyz_unknown"], mapped_skill_id="")
        scen = gen.generate_from_gap(gap)
        assert scen.scenario_id == f"gap_drill:{gap.id}"

    def test_registry_match_diagnosis_category(self):
        gen = GapScenarioGenerator()
        reg = DiscoveryScenarioRegistry()
        gap = _make_gap(affected_intent_types=["diagnose"])
        scen = gen.generate_from_gap(gap, registry=reg)
        assert scen.capability_category == "diagnosis"

    def test_registry_match_picks_lowest_difficulty(self):
        gen = GapScenarioGenerator()
        reg = DiscoveryScenarioRegistry()
        gap = _make_gap(affected_intent_types=["diagnose"])
        scen = gen.generate_from_gap(gap, registry=reg)
        all_diag = reg.list_by_category("diagnosis")
        assert scen.difficulty == min(s.difficulty for s in all_diag)

    def test_template_uses_priority_difficulty(self):
        gen = GapScenarioGenerator()
        gap_high = _make_gap(affected_intent_types=["unknown"], priority="critical")
        scen = gen.generate_from_gap(gap_high)
        assert scen.difficulty == 0.70

    def test_intent_prefix_matching(self):
        gen = GapScenarioGenerator()
        reg = DiscoveryScenarioRegistry()
        gap = _make_gap(affected_intent_types=["analyze_telemetry"])
        scen = gen.generate_from_gap(gap, registry=reg)
        assert scen.capability_category == "analysis"

    def test_falls_back_via_mapped_skill_id(self):
        gen = GapScenarioGenerator()
        reg = DiscoveryScenarioRegistry()
        gap = _make_gap(affected_intent_types=[], mapped_skill_id="coordinate")
        scen = gen.generate_from_gap(gap, registry=reg)
        assert scen.capability_category == "coordination"

    def test_category_fallback_used(self):
        gen = GapScenarioGenerator(category_fallback="analysis")
        gap = _make_gap(affected_intent_types=["unknown"], mapped_skill_id="unknown_skill")
        scen = gen.generate_from_gap(gap)
        assert scen.capability_category == "analysis"

    def test_template_scenario_id_format(self):
        gen = GapScenarioGenerator()
        gap = _make_gap(affected_intent_types=["unknown"])
        scen = gen.generate_from_gap(gap)
        assert scen.scenario_id == f"gap_drill:{gap.id}"


# ---------------------------------------------------------------------
# 4. HolodeckGapDrill (QualificationTest Protocol)
# ---------------------------------------------------------------------

class TestHolodeckGapDrill:
    def _make_drill(self, **kwargs):
        scen = DiscoveryScenario(
            scenario_id="s1", title="t", capability_category="diagnosis",
            summary="sum", learning_objectives=("lo1",), difficulty=0.4,
            scaffolding_level="medium",
        )
        gap = _make_gap()
        return HolodeckGapDrill(scenario=scen, gap=gap, **kwargs)

    def test_implements_protocol(self):
        d = self._make_drill()
        assert isinstance(d, QualificationTest)

    def test_name_format(self):
        d = self._make_drill()
        assert d.name == "holodeck_gap:gap:test:abc"

    def test_threshold_default(self):
        d = self._make_drill(threshold=0.7)
        assert d.threshold == 0.7

    def test_tier_default(self):
        d = self._make_drill()
        assert d.tier == 2

    @pytest.mark.asyncio
    async def test_run_noop_returns_neutral(self):
        d = self._make_drill()
        result = await d.run("agent-1", runtime=None)
        assert isinstance(result, TestResult)
        assert result.score == 0.5
        assert result.passed is False
        assert result.details["noop"] is True

    @pytest.mark.asyncio
    async def test_run_with_runner_tuple(self):
        async def runner(scen, gap, agent_id, runtime):
            return (0.9, True, {"k": "v"})
        d = self._make_drill(drill_runner=runner)
        result = await d.run("agent-1", runtime=None)
        assert result.score == 0.9
        assert result.passed is True
        assert result.details["k"] == "v"


# ---------------------------------------------------------------------
# 5. HolodeckGapBridge
# ---------------------------------------------------------------------

class TestHolodeckGapBridge:
    def _make_bridge(self, *, enabled=True, harness=None, registry=None,
                     emit_calls=None):
        cfg = HolodeckScenarioConfig(enabled=enabled)
        gen = GapScenarioGenerator()
        store = HolodeckScenarioStore()
        emit = (lambda et, p: emit_calls.append((et, p))) if emit_calls is not None else None
        return HolodeckGapBridge(
            config=cfg, generator=gen, store=store,
            emit_event_fn=emit, qualification_harness=harness,
            scenario_registry=registry,
        )

    @pytest.mark.asyncio
    async def test_disabled_returns_none(self):
        b = self._make_bridge(enabled=False)
        gap = _make_gap()
        assert await b.bridge_gap_to_holodeck(gap) is None

    @pytest.mark.asyncio
    async def test_capability_gap_skipped(self):
        b = self._make_bridge()
        gap = _make_gap(gap_type="capability")
        assert await b.bridge_gap_to_holodeck(gap) is None

    @pytest.mark.asyncio
    async def test_no_mapped_skill_skipped(self):
        b = self._make_bridge()
        gap = _make_gap(mapped_skill_id="")
        assert await b.bridge_gap_to_holodeck(gap) is None

    @pytest.mark.asyncio
    async def test_idempotent_returns_existing(self):
        b = self._make_bridge()
        gap = _make_gap()
        first = await b.bridge_gap_to_holodeck(gap)
        second = await b.bridge_gap_to_holodeck(gap)
        assert first is not None
        assert first.gap_id == second.gap_id
        assert first.generated_at == second.generated_at

    @pytest.mark.asyncio
    async def test_registers_with_harness(self):
        harness = MagicMock(spec=QualificationHarness)
        b = self._make_bridge(harness=harness)
        gap = _make_gap()
        link = await b.bridge_gap_to_holodeck(gap)
        assert link is not None
        assert link.status == "registered"
        harness.register_test.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_harness_status_generated(self):
        b = self._make_bridge(harness=None)
        gap = _make_gap()
        link = await b.bridge_gap_to_holodeck(gap)
        assert link is not None
        assert link.status == "generated"

    @pytest.mark.asyncio
    async def test_emits_three_events(self):
        emit_calls: list = []
        harness = MagicMock(spec=QualificationHarness)
        b = self._make_bridge(harness=harness, emit_calls=emit_calls)
        gap = _make_gap()
        await b.bridge_gap_to_holodeck(gap)
        types = [c[0] for c in emit_calls]
        assert EventType.HOLODECK_SCENARIO_GENERATED in types
        assert EventType.HOLODECK_SCENARIO_REGISTERED in types
        assert EventType.HOLODECK_SCENARIO_GAP_LINKED in types

    @pytest.mark.asyncio
    async def test_back_fills_qualification_path_id(self):
        b = self._make_bridge()
        gap = _make_gap()
        assert gap.qualification_path_id == ""
        await b.bridge_gap_to_holodeck(gap)
        assert gap.qualification_path_id == f"holodeck_gap:{gap.id}"


# ---------------------------------------------------------------------
# 6. HolodeckScenarioStore (in-memory fallback)
# ---------------------------------------------------------------------

class TestHolodeckScenarioStore:
    @pytest.mark.asyncio
    async def test_save_and_get_in_memory(self):
        store = HolodeckScenarioStore()
        link = ScenarioGapLink(
            gap_id="g1", scenario_id="s1", drill_test_name="d1",
            agent_id="a1", generated_at=1.0,
        )
        await store.save_link(link)
        got = await store.get_link_for_gap("g1")
        assert got is not None
        assert got.scenario_id == "s1"

    @pytest.mark.asyncio
    async def test_get_missing_returns_none(self):
        store = HolodeckScenarioStore()
        assert await store.get_link_for_gap("missing") is None

    @pytest.mark.asyncio
    async def test_update_outcome_executed_when_failed(self):
        store = HolodeckScenarioStore()
        link = ScenarioGapLink(
            gap_id="g1", scenario_id="s1", drill_test_name="d1",
            agent_id="a1", generated_at=1.0,
        )
        await store.save_link(link)
        outcome = ScenarioOutcome(link=link, score=0.2, passed=False, timestamp=2.0)
        await store.update_outcome("g1", outcome)
        got = await store.get_link_for_gap("g1")
        assert got is not None
        assert got.status == "executed"
        assert got.last_run_score == 0.2

    @pytest.mark.asyncio
    async def test_update_outcome_closed_when_passed(self):
        store = HolodeckScenarioStore()
        link = ScenarioGapLink(
            gap_id="g1", scenario_id="s1", drill_test_name="d1",
            agent_id="a1", generated_at=1.0,
        )
        await store.save_link(link)
        outcome = ScenarioOutcome(link=link, score=0.9, passed=True, timestamp=2.0)
        await store.update_outcome("g1", outcome)
        got = await store.get_link_for_gap("g1")
        assert got is not None
        assert got.status == "closed"

    @pytest.mark.asyncio
    async def test_update_outcome_missing_link_no_op(self):
        store = HolodeckScenarioStore()
        outcome = ScenarioOutcome(
            link=ScenarioGapLink(gap_id="absent", scenario_id="s",
                                 drill_test_name="d", agent_id="a",
                                 generated_at=1.0),
            score=0.5, passed=False, timestamp=2.0,
        )
        # Should not raise
        await store.update_outcome("absent", outcome)
        assert await store.get_link_for_gap("absent") is None


# ---------------------------------------------------------------------
# 7. Startup wiring
# ---------------------------------------------------------------------

class TestStartupWiring:
    def test_disabled_returns_false(self):
        from probos.startup.finalize import _wire_holodeck_scenarios
        runtime = MagicMock(spec=[])
        config = MagicMock()
        config.holodeck_scenarios = HolodeckScenarioConfig(enabled=False)
        assert _wire_holodeck_scenarios(runtime=runtime, config=config) is False

    def test_enabled_wires_bridge(self):
        from probos.startup.finalize import _wire_holodeck_scenarios
        runtime = MagicMock(spec=["emit_event", "qualification_harness",
                                   "discovery_scenario_registry",
                                   "holodeck_gap_bridge"])
        runtime.emit_event = lambda *a, **k: None
        runtime.qualification_harness = MagicMock(spec=QualificationHarness)
        runtime.discovery_scenario_registry = DiscoveryScenarioRegistry()
        config = MagicMock()
        config.holodeck_scenarios = HolodeckScenarioConfig(enabled=True)
        assert _wire_holodeck_scenarios(runtime=runtime, config=config) is True
        assert isinstance(runtime.holodeck_gap_bridge, HolodeckGapBridge)
        assert runtime.holodeck_gap_bridge.qualification_harness is runtime.qualification_harness

    def test_enabled_no_harness_still_wires(self):
        from probos.startup.finalize import _wire_holodeck_scenarios
        runtime = MagicMock(spec=["emit_event", "qualification_harness",
                                   "discovery_scenario_registry",
                                   "holodeck_gap_bridge"])
        runtime.emit_event = None
        runtime.qualification_harness = None
        runtime.discovery_scenario_registry = None
        config = MagicMock()
        config.holodeck_scenarios = HolodeckScenarioConfig(enabled=True)
        assert _wire_holodeck_scenarios(runtime=runtime, config=config) is True
        assert isinstance(runtime.holodeck_gap_bridge, HolodeckGapBridge)
