"""AD-566e: Tier 3 Collective Qualification Tests — 35+ tests.

Tests cover:
  D1 — CoordinationBreakevenProbe (5)
  D2 — ScaffoldDecompositionProbe (5)
  D3 — CollectiveIntelligenceProbe (6)
  D4 — ConvergenceRateProbe (5)
  D5 — EmergenceCapacityProbe (5)
  Harness extension (4)
  Registration wiring (2)
  DriftScheduler collective integration (3)
  Helpers (2)
"""

from __future__ import annotations

import math
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.collective_tests import (
    CREW_AGENT_ID,
    CoordinationBreakevenProbe,
    CollectiveIntelligenceProbe,
    ConvergenceRateProbe,
    EmergenceCapacityProbe,
    ScaffoldDecompositionProbe,
    _gini,
    _skip_result,
)
from probos.cognitive.qualification import (
    CREW_AGENT_ID as HARNESS_CREW_AGENT_ID,
    QualificationHarness,
    QualificationStore,
    QualificationTest,
    TestResult,
)
from probos.config import QualificationConfig


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


class MockEmergenceSnapshot:
    """Fake EmergenceSnapshot with configurable fields."""

    def __init__(
        self,
        emergence_capacity: float = 0.6,
        coordination_balance: float = 0.5,
        synergy_ratio: float = 0.4,
        redundancy_ratio: float = 0.3,
        threads_analyzed: int = 10,
        pairs_analyzed: int = 15,
        significant_pairs: int = 8,
        groupthink_risk: bool = False,
        fragmentation_risk: bool = False,
        tom_effectiveness: float | None = 0.7,
        hebbian_synergy_correlation: float | None = 0.3,
    ):
        self.emergence_capacity = emergence_capacity
        self.coordination_balance = coordination_balance
        self.synergy_ratio = synergy_ratio
        self.redundancy_ratio = redundancy_ratio
        self.threads_analyzed = threads_analyzed
        self.pairs_analyzed = pairs_analyzed
        self.significant_pairs = significant_pairs
        self.groupthink_risk = groupthink_risk
        self.fragmentation_risk = fragmentation_risk
        self.tom_effectiveness = tom_effectiveness
        self.hebbian_synergy_correlation = hebbian_synergy_correlation


class MockEmergenceEngine:
    """Fake emergence metrics engine."""

    def __init__(self, snapshot: MockEmergenceSnapshot | None = None):
        self.latest_snapshot = snapshot


class MockWardRoom:
    """Fake ward room service."""

    def __init__(
        self,
        stats: dict | None = None,
        credibility_map: dict[str, int] | None = None,
    ):
        self._stats = stats or {"total_posts": 10, "total_threads": 5}
        self._credibility_map = credibility_map or {}

    async def get_stats(self) -> dict:
        return self._stats

    async def get_credibility(self, agent_id: str) -> Any:
        posts = self._credibility_map.get(agent_id, 0)
        cred = MagicMock()
        cred.total_posts = posts
        return cred


class MockCrewAgent:
    """Fake crew agent."""

    def __init__(self, agent_id: str, agent_type: str = "counselor"):
        self.id = agent_id
        self.agent_type = agent_type


class MockPool:
    """Fake pool with healthy agents."""

    def __init__(self, agents: list[MockCrewAgent]):
        self.healthy_agents = agents


def _build_runtime(
    snapshot: MockEmergenceSnapshot | None = None,
    ward_room: MockWardRoom | None = None,
    agents: list[MockCrewAgent] | None = None,
    harness: Any = None,
    store: Any = None,
) -> MagicMock:
    """Build a mock runtime with configurable components."""
    runtime = MagicMock()

    # Emergence engine
    engine = MockEmergenceEngine(snapshot)
    runtime._emergence_metrics_engine = engine

    # Ward room
    runtime.ward_room = ward_room or MockWardRoom()

    # Pools with crew agents
    if agents:
        pool = MockPool(agents)
        runtime.pools = {"default": pool}
    else:
        runtime.pools = {}

    # Harness/store
    if harness is not None:
        runtime._qualification_harness = harness
    if store is not None:
        runtime._qualification_store = store

    return runtime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    """Test _gini, _skip_result, CREW_AGENT_ID."""

    def test_crew_agent_id_constant(self):
        assert CREW_AGENT_ID == "__crew__"

    def test_gini_perfect_equality(self):
        assert _gini([1.0, 1.0, 1.0, 1.0]) == 0.0

    def test_gini_perfect_inequality(self):
        # One person has everything
        g = _gini([0.0, 0.0, 0.0, 100.0])
        assert g > 0.5

    def test_gini_empty(self):
        assert _gini([]) == 0.0

    def test_gini_all_zeros(self):
        assert _gini([0, 0, 0]) == 0.0

    def test_skip_result_shape(self):
        r = _skip_result("test_x", "no_data")
        assert isinstance(r, TestResult)
        assert r.agent_id == CREW_AGENT_ID
        assert r.passed is True
        assert r.details["skipped"] is True
        assert r.details["reason"] == "no_data"
        assert r.tier == 3


# ---------------------------------------------------------------------------
# D1 — CoordinationBreakevenProbe
# ---------------------------------------------------------------------------


class TestCoordinationBreakevenProbe:
    """Tests for CoordinationBreakevenProbe."""

    def test_protocol_compliance(self):
        probe = CoordinationBreakevenProbe()
        assert isinstance(probe, QualificationTest)
        assert probe.tier == 3
        assert probe.threshold == 0.0

    @pytest.mark.asyncio
    async def test_positive_breakeven(self):
        """High synergy + low overhead → CBS > 0.5."""
        snapshot = MockEmergenceSnapshot(emergence_capacity=0.8)
        ward_room = MockWardRoom(stats={"total_posts": 5, "total_threads": 5})
        runtime = _build_runtime(snapshot=snapshot, ward_room=ward_room)
        result = await CoordinationBreakevenProbe().run("any", runtime)
        assert result.agent_id == CREW_AGENT_ID
        assert result.details["skipped"] is False
        assert result.details["cbs_score"] > 0.5

    @pytest.mark.asyncio
    async def test_negative_breakeven(self):
        """Low synergy + high overhead → CBS < 0.5."""
        snapshot = MockEmergenceSnapshot(emergence_capacity=0.05)
        # 40 posts in 2 threads = 20 avg = max overhead
        ward_room = MockWardRoom(stats={"total_posts": 40, "total_threads": 2})
        runtime = _build_runtime(snapshot=snapshot, ward_room=ward_room)
        result = await CoordinationBreakevenProbe().run("any", runtime)
        assert result.details["cbs_score"] < 0.5

    @pytest.mark.asyncio
    async def test_no_emergence_data_skipped(self):
        runtime = _build_runtime(snapshot=None)
        result = await CoordinationBreakevenProbe().run("any", runtime)
        assert result.details["skipped"] is True

    @pytest.mark.asyncio
    async def test_details_structure(self):
        snapshot = MockEmergenceSnapshot()
        runtime = _build_runtime(snapshot=snapshot)
        result = await CoordinationBreakevenProbe().run("any", runtime)
        details = result.details
        assert "emergence_capacity" in details
        assert "coordination_balance" in details
        assert "avg_posts_per_thread" in details
        assert "overhead_estimate" in details
        assert "cbs_score" in details
        assert "threads_analyzed" in details


# ---------------------------------------------------------------------------
# D2 — ScaffoldDecompositionProbe
# ---------------------------------------------------------------------------


class TestScaffoldDecompositionProbe:
    """Tests for ScaffoldDecompositionProbe."""

    def test_protocol_compliance(self):
        probe = ScaffoldDecompositionProbe()
        assert isinstance(probe, QualificationTest)
        assert probe.tier == 3
        assert probe.threshold == 0.0

    @pytest.mark.asyncio
    async def test_positive_multiplier(self):
        """Scores above threshold → multiplier > 1.0."""
        # Create a mock harness with Tier 1 tests
        mock_test = MagicMock()
        mock_test.tier = 1
        mock_test.threshold = 0.5
        mock_test.name = "personality_probe"

        harness = MagicMock()
        harness.registered_tests = {"personality_probe": mock_test}

        # Create store that returns high scores
        store = AsyncMock()
        result = TestResult(
            agent_id="a1", test_name="personality_probe", tier=1,
            score=0.9, passed=True, timestamp=time.time(),
            duration_ms=1.0,
        )
        store.get_latest = AsyncMock(return_value=result)

        agents = [MockCrewAgent("a1", "counselor")]
        runtime = _build_runtime(agents=agents, harness=harness, store=store)

        probe_result = await ScaffoldDecompositionProbe().run("any", runtime)
        assert probe_result.details["skipped"] is False
        assert probe_result.details["architecture_multiplier"] > 1.0

    @pytest.mark.asyncio
    async def test_no_amplification(self):
        """Scores == threshold → multiplier ~1.0."""
        mock_test = MagicMock()
        mock_test.tier = 1
        mock_test.threshold = 0.5
        mock_test.name = "personality_probe"

        harness = MagicMock()
        harness.registered_tests = {"personality_probe": mock_test}

        store = AsyncMock()
        result = TestResult(
            agent_id="a1", test_name="personality_probe", tier=1,
            score=0.5, passed=True, timestamp=time.time(),
            duration_ms=1.0,
        )
        store.get_latest = AsyncMock(return_value=result)

        agents = [MockCrewAgent("a1", "counselor")]
        runtime = _build_runtime(agents=agents, harness=harness, store=store)

        probe_result = await ScaffoldDecompositionProbe().run("any", runtime)
        assert abs(probe_result.details["architecture_multiplier"] - 1.0) < 0.01

    @pytest.mark.asyncio
    async def test_no_tier1_data_skipped(self):
        """No stored results → skip result."""
        mock_test = MagicMock()
        mock_test.tier = 1
        mock_test.threshold = 0.5
        mock_test.name = "personality_probe"

        harness = MagicMock()
        harness.registered_tests = {"personality_probe": mock_test}

        store = AsyncMock()
        store.get_latest = AsyncMock(return_value=None)

        agents = [MockCrewAgent("a1", "counselor")]
        runtime = _build_runtime(agents=agents, harness=harness, store=store)

        probe_result = await ScaffoldDecompositionProbe().run("any", runtime)
        assert probe_result.details["skipped"] is True

    @pytest.mark.asyncio
    async def test_details_structure(self):
        mock_test = MagicMock()
        mock_test.tier = 1
        mock_test.threshold = 0.5
        mock_test.name = "personality_probe"

        harness = MagicMock()
        harness.registered_tests = {"personality_probe": mock_test}

        store = AsyncMock()
        result = TestResult(
            agent_id="a1", test_name="personality_probe", tier=1,
            score=0.8, passed=True, timestamp=time.time(),
            duration_ms=1.0,
        )
        store.get_latest = AsyncMock(return_value=result)

        agents = [MockCrewAgent("a1", "counselor")]
        runtime = _build_runtime(agents=agents, harness=harness, store=store)

        probe_result = await ScaffoldDecompositionProbe().run("any", runtime)
        details = probe_result.details
        assert "architecture_multiplier" in details
        assert "mean_actual" in details
        assert "mean_threshold" in details
        assert "agents_measured" in details
        assert "tests_measured" in details
        assert "per_test_multipliers" in details


# ---------------------------------------------------------------------------
# D3 — CollectiveIntelligenceProbe
# ---------------------------------------------------------------------------


class TestCollectiveIntelligenceProbe:
    """Tests for CollectiveIntelligenceProbe."""

    def test_protocol_compliance(self):
        probe = CollectiveIntelligenceProbe()
        assert isinstance(probe, QualificationTest)
        assert probe.tier == 3
        assert probe.threshold == 0.0

    @pytest.mark.asyncio
    async def test_equal_participation(self):
        """Equal post counts → high turn-taking, low Gini."""
        agents = [
            MockCrewAgent("a1", "counselor"),
            MockCrewAgent("a2", "builder"),
            MockCrewAgent("a3", "diagnostician"),
        ]
        ward_room = MockWardRoom(
            credibility_map={"a1": 10, "a2": 10, "a3": 10}
        )
        snapshot = MockEmergenceSnapshot(tom_effectiveness=0.7)
        runtime = _build_runtime(
            snapshot=snapshot, ward_room=ward_room, agents=agents
        )

        result = await CollectiveIntelligenceProbe().run("any", runtime)
        assert result.details["skipped"] is False
        assert result.details["gini_coefficient"] == 0.0
        assert result.details["turn_taking_equality"] == 1.0

    @pytest.mark.asyncio
    async def test_skewed_participation(self):
        """One agent dominates → low turn-taking, high Gini."""
        agents = [
            MockCrewAgent("a1", "counselor"),
            MockCrewAgent("a2", "builder"),
            MockCrewAgent("a3", "diagnostician"),
        ]
        ward_room = MockWardRoom(
            credibility_map={"a1": 100, "a2": 1, "a3": 1}
        )
        snapshot = MockEmergenceSnapshot(tom_effectiveness=0.5)
        runtime = _build_runtime(
            snapshot=snapshot, ward_room=ward_room, agents=agents
        )

        result = await CollectiveIntelligenceProbe().run("any", runtime)
        assert result.details["gini_coefficient"] > 0.3
        assert result.details["turn_taking_equality"] < 0.7

    @pytest.mark.asyncio
    async def test_diverse_personalities(self):
        """With diverse seed profiles → positive diversity score."""
        agents = [
            MockCrewAgent("a1", "counselor"),
            MockCrewAgent("a2", "builder"),
        ]
        ward_room = MockWardRoom(credibility_map={"a1": 5, "a2": 5})
        snapshot = MockEmergenceSnapshot(tom_effectiveness=0.6)
        runtime = _build_runtime(
            snapshot=snapshot, ward_room=ward_room, agents=agents
        )

        # Personality diversity depends on actual crew profiles existing.
        # Even with 0.0 diversity, the test should not crash.
        result = await CollectiveIntelligenceProbe().run("any", runtime)
        assert result.details["skipped"] is False
        assert "personality_diversity" in result.details

    @pytest.mark.asyncio
    async def test_no_data_skipped(self):
        """No ward room data → skip."""
        agents = [MockCrewAgent("a1", "counselor")]
        ward_room = MockWardRoom(credibility_map={"a1": 0})
        runtime = _build_runtime(ward_room=ward_room, agents=agents)

        result = await CollectiveIntelligenceProbe().run("any", runtime)
        assert result.details["skipped"] is True

    @pytest.mark.asyncio
    async def test_no_crew_agents_skipped(self):
        """No crew agents → skip."""
        runtime = _build_runtime()  # No agents
        result = await CollectiveIntelligenceProbe().run("any", runtime)
        assert result.details["skipped"] is True

    @pytest.mark.asyncio
    async def test_details_structure(self):
        agents = [MockCrewAgent("a1", "counselor"), MockCrewAgent("a2", "builder")]
        ward_room = MockWardRoom(credibility_map={"a1": 5, "a2": 5})
        snapshot = MockEmergenceSnapshot(tom_effectiveness=0.7)
        runtime = _build_runtime(
            snapshot=snapshot, ward_room=ward_room, agents=agents
        )

        result = await CollectiveIntelligenceProbe().run("any", runtime)
        details = result.details
        assert "turn_taking_equality" in details
        assert "gini_coefficient" in details
        assert "tom_effectiveness" in details
        assert "personality_diversity" in details
        assert "agent_count" in details
        assert "post_distribution" in details
        assert "cfactor_score" in details


# ---------------------------------------------------------------------------
# D4 — ConvergenceRateProbe
# ---------------------------------------------------------------------------


class TestConvergenceRateProbe:
    """Tests for ConvergenceRateProbe."""

    def test_protocol_compliance(self):
        probe = ConvergenceRateProbe()
        assert isinstance(probe, QualificationTest)
        assert probe.tier == 3
        assert probe.threshold == 0.0

    @pytest.mark.asyncio
    async def test_high_coordination(self):
        """Many significant pairs → high score."""
        snapshot = MockEmergenceSnapshot(
            pairs_analyzed=10, significant_pairs=8
        )
        runtime = _build_runtime(snapshot=snapshot)
        result = await ConvergenceRateProbe().run("any", runtime)
        assert result.details["skipped"] is False
        assert result.details["coordination_rate"] == 0.8
        assert result.score == 0.8

    @pytest.mark.asyncio
    async def test_low_coordination(self):
        """Few significant pairs → low score."""
        snapshot = MockEmergenceSnapshot(
            pairs_analyzed=20, significant_pairs=2
        )
        runtime = _build_runtime(snapshot=snapshot)
        result = await ConvergenceRateProbe().run("any", runtime)
        assert result.details["coordination_rate"] == 0.1
        assert result.score == 0.1

    @pytest.mark.asyncio
    async def test_no_data_skipped(self):
        runtime = _build_runtime(snapshot=None)
        result = await ConvergenceRateProbe().run("any", runtime)
        assert result.details["skipped"] is True

    @pytest.mark.asyncio
    async def test_details_structure(self):
        snapshot = MockEmergenceSnapshot()
        runtime = _build_runtime(snapshot=snapshot)
        result = await ConvergenceRateProbe().run("any", runtime)
        details = result.details
        assert "pairs_analyzed" in details
        assert "significant_pairs" in details
        assert "coordination_rate" in details
        assert "threads_analyzed" in details
        assert "groupthink_risk" in details
        assert "fragmentation_risk" in details


# ---------------------------------------------------------------------------
# D5 — EmergenceCapacityProbe
# ---------------------------------------------------------------------------


class TestEmergenceCapacityProbe:
    """Tests for EmergenceCapacityProbe."""

    def test_protocol_compliance(self):
        probe = EmergenceCapacityProbe()
        assert isinstance(probe, QualificationTest)
        assert probe.tier == 3
        assert probe.threshold == 0.0

    @pytest.mark.asyncio
    async def test_reads_snapshot(self):
        """Score == emergence_capacity from snapshot."""
        snapshot = MockEmergenceSnapshot(emergence_capacity=0.73)
        runtime = _build_runtime(snapshot=snapshot)
        result = await EmergenceCapacityProbe().run("any", runtime)
        assert result.score == 0.73
        assert result.details["emergence_capacity"] == 0.73

    @pytest.mark.asyncio
    async def test_groupthink_flagged(self):
        """groupthink_risk=True → included in details."""
        snapshot = MockEmergenceSnapshot(groupthink_risk=True)
        runtime = _build_runtime(snapshot=snapshot)
        result = await EmergenceCapacityProbe().run("any", runtime)
        assert result.details["groupthink_risk"] is True

    @pytest.mark.asyncio
    async def test_no_data_skipped(self):
        runtime = _build_runtime(snapshot=None)
        result = await EmergenceCapacityProbe().run("any", runtime)
        assert result.details["skipped"] is True

    @pytest.mark.asyncio
    async def test_details_structure(self):
        snapshot = MockEmergenceSnapshot()
        runtime = _build_runtime(snapshot=snapshot)
        result = await EmergenceCapacityProbe().run("any", runtime)
        details = result.details
        assert "emergence_capacity" in details
        assert "coordination_balance" in details
        assert "synergy_ratio" in details
        assert "redundancy_ratio" in details
        assert "hebbian_synergy_correlation" in details
        assert "tom_effectiveness" in details
        assert "groupthink_risk" in details
        assert "fragmentation_risk" in details
        assert "threads_analyzed" in details
        assert "pairs_analyzed" in details


# ---------------------------------------------------------------------------
# Harness extension tests
# ---------------------------------------------------------------------------


class TestHarnessRunCollective:
    """Tests for QualificationHarness.run_collective()."""

    @pytest.mark.asyncio
    async def test_run_collective_executes_tier3(self):
        """run_collective(3) runs all Tier 3 tests."""
        store = AsyncMock(spec=QualificationStore)
        store.get_baseline = AsyncMock(return_value=None)
        store.save_result = AsyncMock()
        harness = QualificationHarness(store=store)

        # Register mix of tiers
        for probe_cls in (
            CoordinationBreakevenProbe,
            ScaffoldDecompositionProbe,
            CollectiveIntelligenceProbe,
            ConvergenceRateProbe,
            EmergenceCapacityProbe,
        ):
            harness.register_test(probe_cls())

        runtime = _build_runtime(snapshot=None)
        results = await harness.run_collective(3, runtime)
        assert len(results) == 5
        for r in results:
            assert r.tier == 3

    @pytest.mark.asyncio
    async def test_run_collective_skips_other_tiers(self):
        """run_collective(3) does NOT run Tier 1/2."""
        store = AsyncMock(spec=QualificationStore)
        store.get_baseline = AsyncMock(return_value=None)
        store.save_result = AsyncMock()
        harness = QualificationHarness(store=store)

        # Register a fake Tier 1 test
        mock_t1 = MagicMock()
        mock_t1.name = "fake_tier1"
        mock_t1.tier = 1
        mock_t1.threshold = 0.5
        mock_t1.description = "Fake"
        mock_t1.run = AsyncMock(return_value=TestResult(
            agent_id="x", test_name="fake_tier1", tier=1,
            score=0.9, passed=True, timestamp=time.time(), duration_ms=1.0,
        ))
        harness.register_test(mock_t1)

        harness.register_test(EmergenceCapacityProbe())

        runtime = _build_runtime(snapshot=None)
        results = await harness.run_collective(3, runtime)
        # Only Tier 3 runs
        assert len(results) == 1
        assert results[0].test_name == "emergence_capacity"
        # Tier 1 test NOT called
        mock_t1.run.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_collective_uses_crew_agent_id(self):
        """All results have agent_id == '__crew__'."""
        store = AsyncMock(spec=QualificationStore)
        store.get_baseline = AsyncMock(return_value=None)
        store.save_result = AsyncMock()
        harness = QualificationHarness(store=store)
        harness.register_test(EmergenceCapacityProbe())
        harness.register_test(ConvergenceRateProbe())

        runtime = _build_runtime(snapshot=None)
        results = await harness.run_collective(3, runtime)
        for r in results:
            assert r.agent_id == "__crew__"

    def test_crew_agent_id_constant_in_qualification(self):
        """CREW_AGENT_ID constant is importable from qualification module."""
        assert HARNESS_CREW_AGENT_ID == "__crew__"


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------


class TestRegistration:
    """Test that Tier 3 probes register correctly."""

    def test_all_probes_have_tier_3(self):
        probes = [
            CoordinationBreakevenProbe(),
            ScaffoldDecompositionProbe(),
            CollectiveIntelligenceProbe(),
            ConvergenceRateProbe(),
            EmergenceCapacityProbe(),
        ]
        for probe in probes:
            assert probe.tier == 3, f"{probe.name} tier != 3"

    def test_runtime_registers_tier3_tests(self):
        """Runtime registration block includes all 5 Tier 3 tests."""
        import inspect
        from probos.runtime import ProbOSRuntime

        source = inspect.getsource(ProbOSRuntime.start)
        for cls_name in (
            "CoordinationBreakevenProbe",
            "ScaffoldDecompositionProbe",
            "CollectiveIntelligenceProbe",
            "ConvergenceRateProbe",
            "EmergenceCapacityProbe",
        ):
            assert cls_name in source, f"{cls_name} not found in start()"


# ---------------------------------------------------------------------------
# DriftScheduler collective integration tests
# ---------------------------------------------------------------------------


class TestDriftSchedulerCollective:
    """Test DriftScheduler collective test integration."""

    def test_drift_scheduler_runs_collective_when_tier3_enabled(self):
        """With drift_check_tiers=[1,2,3], tier 3 is in _drift_tiers."""
        from probos.cognitive.drift_detector import DriftDetector, DriftScheduler

        cfg = QualificationConfig(drift_check_tiers=[1, 2, 3])
        store = MagicMock()
        detector = DriftDetector(store=store, config=cfg)
        scheduler = DriftScheduler(
            harness=MagicMock(),
            detector=detector,
            config=cfg,
        )
        assert 3 in scheduler._drift_tiers

    def test_drift_scheduler_skips_collective_when_tier3_disabled(self):
        """With drift_check_tiers=[1,2], tier 3 not in _drift_tiers."""
        from probos.cognitive.drift_detector import DriftDetector, DriftScheduler

        cfg = QualificationConfig(drift_check_tiers=[1, 2])
        store = MagicMock()
        detector = DriftDetector(store=store, config=cfg)
        scheduler = DriftScheduler(
            harness=MagicMock(),
            detector=detector,
            config=cfg,
        )
        assert 3 not in scheduler._drift_tiers

    @pytest.mark.asyncio
    async def test_drift_scheduler_collective_in_run_cycle(self):
        """_run_cycle calls run_collective when tier 3 enabled."""
        from probos.cognitive.drift_detector import DriftDetector, DriftScheduler

        cfg = QualificationConfig(drift_check_tiers=[1, 2, 3])

        # Mock a Tier 1 test so test_names is non-empty
        mock_t1 = MagicMock()
        mock_t1.tier = 1
        mock_t1.name = "fake_t1"

        harness = MagicMock()
        harness.registered_tests = {"fake_t1": mock_t1}
        harness.run_tier = AsyncMock(return_value=[])
        harness.run_collective = AsyncMock(return_value=[])

        mock_detector = AsyncMock()
        mock_detector.analyze_all_agents = AsyncMock(return_value=[])

        scheduler = DriftScheduler(
            harness=harness,
            detector=mock_detector,
            config=cfg,
        )
        # Give it a runtime with a crew agent via mocked _get_crew_agent_ids
        runtime = MagicMock()
        scheduler._runtime = runtime
        scheduler._get_crew_agent_ids = MagicMock(return_value=["agent-1"])

        await scheduler._run_cycle()

        # run_collective should have been called with tier 3
        harness.run_collective.assert_called_once_with(3, runtime)
