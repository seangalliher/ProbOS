"""Tests for EmergentDetector — Phase 20 (AD-240)."""

from __future__ import annotations

import json
import time
from io import StringIO
from typing import Any
from unittest.mock import MagicMock

import pytest
from rich.console import Console

from probos.agents.introspect import IntrospectionAgent
from probos.cognitive.emergent_detector import (
    EmergentDetector,
    EmergentPattern,
    SystemDynamicsSnapshot,
)
from probos.cognitive.llm_client import MockLLMClient
from probos.consensus.trust import TrustNetwork
from probos.experience.panels import render_anomalies_panel
from probos.experience.shell import ProbOSShell
from probos.mesh.routing import HebbianRouter, REL_INTENT
from probos.types import DreamReport, IntentMessage, LLMRequest


# ---------------------------------------------------------------------------
# Stubs / helpers
# ---------------------------------------------------------------------------


class _FakeTrustNetwork:
    """Minimal trust network stub."""

    def __init__(self, records: dict[str, dict] | None = None) -> None:
        self._data = records or {}

    def raw_scores(self) -> dict[str, dict[str, float]]:
        return dict(self._data)

    def all_scores(self) -> dict[str, float]:
        return {
            aid: r["alpha"] / (r["alpha"] + r["beta"])
            for aid, r in self._data.items()
        }


class _FakeRouter:
    """Minimal Hebbian router stub."""

    def __init__(self, weights: dict[tuple, float] | None = None) -> None:
        self._weights = weights or {}

    def all_weights_typed(self) -> dict[tuple, float]:
        return dict(self._weights)

    @property
    def weight_count(self) -> int:
        return len(self._weights)


def _make_detector(
    weights: dict | None = None,
    trust_records: dict | None = None,
    episodic_memory: Any = None,
    max_history: int = 100,
) -> EmergentDetector:
    """Create an EmergentDetector with fake dependencies."""
    router = _FakeRouter(weights)
    trust = _FakeTrustNetwork(trust_records)
    return EmergentDetector(
        hebbian_router=router,  # type: ignore[arg-type]
        trust_network=trust,  # type: ignore[arg-type]
        episodic_memory=episodic_memory,
        max_history=max_history,
    )


# ===========================================================================
# Dataclass tests
# ===========================================================================


class TestEmergentPatternDataclass:
    def test_fields_roundtrip(self) -> None:
        p = EmergentPattern(
            pattern_type="trust_anomaly",
            description="Agent X high trust",
            confidence=0.85,
            evidence={"agent": "X"},
            timestamp=1000.0,
            severity="notable",
        )
        assert p.pattern_type == "trust_anomaly"
        assert p.confidence == 0.85
        assert p.severity == "notable"
        assert p.evidence == {"agent": "X"}

    def test_severity_values(self) -> None:
        for sev in ("info", "notable", "significant"):
            p = EmergentPattern(
                pattern_type="test",
                description="test",
                confidence=0.5,
                severity=sev,
            )
            assert p.severity == sev


class TestSystemDynamicsSnapshotDataclass:
    def test_fields_roundtrip(self) -> None:
        s = SystemDynamicsSnapshot(
            timestamp=123.0,
            tc_n=0.5,
            cooperation_clusters=[{"size": 3}],
            trust_distribution={"mean": 0.5},
            routing_entropy=1.2,
            capability_count=5,
            dream_consolidation_rate=10.0,
        )
        assert s.tc_n == 0.5
        assert s.routing_entropy == 1.2
        assert s.capability_count == 5
        assert len(s.cooperation_clusters) == 1


# ===========================================================================
# TC_N computation
# ===========================================================================


class TestComputeTcN:
    def test_no_episodic_memory_returns_zero(self) -> None:
        d = _make_detector()
        assert d.compute_tc_n() == 0.0

    def test_no_weights_returns_zero(self) -> None:
        d = _make_detector(episodic_memory=object())
        assert d.compute_tc_n() == 0.0

    def test_single_pool_dags_return_zero(self) -> None:
        """All intents route to same pool → tc_n = 0."""
        weights = {
            ("read_file", "file_reader_filesystem_0_abc", REL_INTENT): 0.5,
            ("stat_file", "file_reader_filesystem_1_def", REL_INTENT): 0.3,
        }
        d = _make_detector(weights=weights, episodic_memory=object())
        tc = d.compute_tc_n()
        assert tc == 0.0

    def test_multi_pool_dags_return_one(self) -> None:
        """Each intent routes to a different pool → tc_n = 1.0."""
        weights = {
            ("read_file", "file_reader_filesystem_0_abc", REL_INTENT): 0.5,
            ("read_file", "shell_command_shell_0_xyz", REL_INTENT): 0.4,
            ("run_cmd", "runner_commands_0_qqq", REL_INTENT): 0.3,
            ("run_cmd", "writer_output_0_www", REL_INTENT): 0.2,
        }
        d = _make_detector(weights=weights, episodic_memory=object())
        tc = d.compute_tc_n()
        assert tc == 1.0

    def test_mixed_single_multi_returns_fraction(self) -> None:
        """One single-pool intent, one multi-pool intent → tc_n = 0.5."""
        weights = {
            # read_file → single pool (filesystem)
            ("read_file", "file_reader_filesystem_0_abc", REL_INTENT): 0.5,
            # run_command → two pools
            ("run_command", "shell_cmd_shell_0_xyz", REL_INTENT): 0.4,
            ("run_command", "alt_cmd_alt_pool_1_qqq", REL_INTENT): 0.3,
        }
        d = _make_detector(weights=weights, episodic_memory=object())
        tc = d.compute_tc_n()
        assert 0.0 < tc < 1.0

    def test_pool_extraction_from_agent_id(self) -> None:
        pool = EmergentDetector._extract_pool("file_reader_filesystem_0_abc123")
        assert pool != ""

    def test_malformed_agent_id_graceful(self) -> None:
        pool = EmergentDetector._extract_pool("x")
        assert pool == ""


# ===========================================================================
# Cooperation cluster detection
# ===========================================================================


class TestCooperationClusters:
    def test_empty_weights_no_clusters(self) -> None:
        d = _make_detector()
        assert d.detect_cooperation_clusters() == []

    def test_single_strong_connection_one_cluster(self) -> None:
        weights = {
            ("read_file", "agent_pool_0_abc", REL_INTENT): 0.5,
        }
        d = _make_detector(weights=weights)
        clusters = d.detect_cooperation_clusters()
        assert len(clusters) == 1
        assert clusters[0]["size"] == 2

    def test_two_disconnected_groups(self) -> None:
        weights = {
            ("read_file", "reader_pool_0_abc", REL_INTENT): 0.5,
            ("write_file", "writer_pool_0_def", REL_INTENT): 0.4,
        }
        d = _make_detector(weights=weights)
        clusters = d.detect_cooperation_clusters()
        assert len(clusters) == 2

    def test_weights_below_threshold_filtered(self) -> None:
        weights = {
            ("read_file", "agent_pool_0_abc", REL_INTENT): 0.05,  # below 0.1
        }
        d = _make_detector(weights=weights)
        clusters = d.detect_cooperation_clusters()
        assert clusters == []

    def test_cluster_contains_expected_members(self) -> None:
        weights = {
            ("intent_a", "agent_pool_0_abc", REL_INTENT): 0.5,
            ("intent_a", "agent_pool_1_def", REL_INTENT): 0.3,
        }
        d = _make_detector(weights=weights)
        clusters = d.detect_cooperation_clusters()
        assert len(clusters) == 1
        assert clusters[0]["size"] == 3  # intent_a + 2 agents


# ===========================================================================
# Trust anomaly detection
# ===========================================================================


class TestTrustAnomalies:
    def test_all_similar_no_anomalies(self) -> None:
        records = {
            f"agent_{i}": {"alpha": 2.0, "beta": 2.0, "observations": 0.0}
            for i in range(5)
        }
        d = _make_detector(trust_records=records)
        patterns = d.detect_trust_anomalies()
        assert len(patterns) == 0

    def test_one_very_low_trust(self) -> None:
        records = {
            "agent_0": {"alpha": 2.0, "beta": 2.0, "observations": 0.0},
            "agent_1": {"alpha": 2.0, "beta": 2.0, "observations": 0.0},
            "agent_2": {"alpha": 2.0, "beta": 2.0, "observations": 0.0},
            "agent_3": {"alpha": 2.0, "beta": 2.0, "observations": 0.0},
            "agent_4": {"alpha": 2.0, "beta": 2.0, "observations": 0.0},
            "agent_5": {"alpha": 2.0, "beta": 2.0, "observations": 0.0},
            "agent_6": {"alpha": 2.0, "beta": 2.0, "observations": 0.0},
            "outlier": {"alpha": 0.5, "beta": 20.0, "observations": 19.0},
        }
        d = _make_detector(trust_records=records)
        patterns = d.detect_trust_anomalies()
        trust_patterns = [p for p in patterns if "outlier" in p.description]
        assert len(trust_patterns) >= 1
        assert trust_patterns[0].evidence["direction"] == "low"

    def test_one_very_high_trust(self) -> None:
        records = {
            "agent_0": {"alpha": 2.0, "beta": 2.0, "observations": 0.0},
            "agent_1": {"alpha": 2.0, "beta": 2.0, "observations": 0.0},
            "agent_2": {"alpha": 2.0, "beta": 2.0, "observations": 0.0},
            "agent_3": {"alpha": 2.0, "beta": 2.0, "observations": 0.0},
            "agent_4": {"alpha": 2.0, "beta": 2.0, "observations": 0.0},
            "agent_5": {"alpha": 2.0, "beta": 2.0, "observations": 0.0},
            "agent_6": {"alpha": 2.0, "beta": 2.0, "observations": 0.0},
            "star": {"alpha": 20.0, "beta": 0.5, "observations": 19.0},
        }
        d = _make_detector(trust_records=records)
        patterns = d.detect_trust_anomalies()
        trust_patterns = [p for p in patterns if "star" in p.description]
        assert len(trust_patterns) >= 1
        assert trust_patterns[0].evidence["direction"] == "high"

    def test_change_point_detection(self) -> None:
        records = {
            "agent_0": {"alpha": 5.0, "beta": 2.0, "observations": 3.0},
            "agent_1": {"alpha": 2.0, "beta": 2.0, "observations": 0.0},
        }
        d = _make_detector(trust_records=records)
        # Create a previous snapshot with different trust for agent_0
        prev_snapshot = SystemDynamicsSnapshot(
            trust_distribution={
                "mean": 0.5,
                "std": 0.1,
                "per_agent": {
                    "agent_0": 0.4,  # was 0.4, now ~0.71 → delta > 0.15
                    "agent_1": 0.5,
                },
            },
        )
        d._history.append(prev_snapshot)
        patterns = d.detect_trust_anomalies()
        change_points = [p for p in patterns if "change point" in p.description]
        assert len(change_points) >= 1

    def test_hyperactive_agent(self) -> None:
        records = {
            "agent_0": {"alpha": 2.0, "beta": 2.0, "observations": 1.0},
            "agent_1": {"alpha": 2.0, "beta": 2.0, "observations": 1.0},
            "agent_2": {"alpha": 2.0, "beta": 2.0, "observations": 1.0},
            "agent_3": {"alpha": 2.0, "beta": 2.0, "observations": 1.0},
            "agent_4": {"alpha": 2.0, "beta": 2.0, "observations": 1.0},
            "agent_5": {"alpha": 2.0, "beta": 2.0, "observations": 1.0},
            "agent_6": {"alpha": 2.0, "beta": 2.0, "observations": 1.0},
            "hyperact": {"alpha": 2.0, "beta": 2.0, "observations": 500.0},
        }
        d = _make_detector(trust_records=records)
        patterns = d.detect_trust_anomalies()
        hyper = [p for p in patterns if "hyperact" in p.description]
        assert len(hyper) >= 1

    def test_single_agent_no_anomaly(self) -> None:
        records = {"only_one": {"alpha": 2.0, "beta": 2.0, "observations": 0.0}}
        d = _make_detector(trust_records=records)
        patterns = d.detect_trust_anomalies()
        assert len(patterns) == 0


# ===========================================================================
# Routing shift detection
# ===========================================================================


class TestRoutingShifts:
    def test_no_previous_snapshot_no_shifts(self) -> None:
        weights = {("read_file", "agent_pool_0_abc", REL_INTENT): 0.5}
        d = _make_detector(weights=weights)
        patterns = d.detect_routing_shifts()
        assert len(patterns) == 0

    def test_new_connection_detected(self) -> None:
        weights = {
            ("read_file", "agent_pool_0_abc", REL_INTENT): 0.5,
            ("write_file", "writer_pool_0_def", REL_INTENT): 0.3,
        }
        d = _make_detector(weights=weights)
        # Set previous map with only read_file
        d._prev_intent_agent_map = {"read_file": {"agent_pool_0_abc"}}
        patterns = d.detect_routing_shifts()
        # write_file + writer should be detected as new
        assert len(patterns) >= 1

    def test_stable_routing_no_shifts(self) -> None:
        weights = {("read_file", "agent_pool_0_abc", REL_INTENT): 0.5}
        d = _make_detector(weights=weights)
        d._prev_intent_agent_map = {"read_file": {"agent_pool_0_abc"}}
        patterns = d.detect_routing_shifts()
        assert len(patterns) == 0

    def test_entropy_uniform_high(self) -> None:
        """Uniform weight distribution → high entropy."""
        weights = {
            ("i1", "agent_poolA_0_abc", REL_INTENT): 0.5,
            ("i2", "agent_poolB_0_def", REL_INTENT): 0.5,
            ("i3", "agent_poolC_0_ghi", REL_INTENT): 0.5,
        }
        d = _make_detector(weights=weights)
        entropy = d.compute_routing_entropy()
        # With 3 equal pools, entropy should be log2(3) ≈ 1.585
        assert entropy > 1.0

    def test_entropy_concentrated_low(self) -> None:
        """All weight on one pool → entropy = 0."""
        weights = {
            ("i1", "agent_pool_0_abc", REL_INTENT): 0.5,
            ("i2", "agent_pool_1_def", REL_INTENT): 0.5,
        }
        d = _make_detector(weights=weights)
        entropy = d.compute_routing_entropy()
        # Both agents in same pool → entropy = 0
        assert entropy == 0.0


# ===========================================================================
# Consolidation anomaly detection
# ===========================================================================


class TestConsolidationAnomalies:
    def test_no_dream_report_no_anomalies(self) -> None:
        d = _make_detector()
        patterns = d.detect_consolidation_anomalies(None)
        assert patterns == []

    def test_normal_dream_report_no_anomalies(self) -> None:
        d = _make_detector()
        report1 = DreamReport(weights_strengthened=5, weights_pruned=3)
        d.detect_consolidation_anomalies(report1)
        report2 = DreamReport(weights_strengthened=5, weights_pruned=3)
        patterns = d.detect_consolidation_anomalies(report2)
        assert len(patterns) == 0

    def test_high_strengthened_anomaly(self) -> None:
        d = _make_detector()
        # Build baseline
        for _ in range(3):
            d.detect_consolidation_anomalies(
                DreamReport(weights_strengthened=5, weights_pruned=3)
            )
        # Now a spike: > 2x average
        patterns = d.detect_consolidation_anomalies(
            DreamReport(weights_strengthened=50, weights_pruned=3)
        )
        strengthened = [p for p in patterns if "strengthening" in p.description]
        assert len(strengthened) == 1

    def test_high_pruned_anomaly(self) -> None:
        d = _make_detector()
        for _ in range(3):
            d.detect_consolidation_anomalies(
                DreamReport(weights_strengthened=5, weights_pruned=3)
            )
        patterns = d.detect_consolidation_anomalies(
            DreamReport(weights_strengthened=5, weights_pruned=30)
        )
        pruned = [p for p in patterns if "pruning" in p.description]
        assert len(pruned) == 1

    def test_prewarm_intents_not_yet_checked(self) -> None:
        """Pre-warm intents are stored but don't cause anomalies without handler check."""
        d = _make_detector()
        d.detect_consolidation_anomalies(
            DreamReport(weights_strengthened=1, weights_pruned=1, pre_warm_intents=["foo"])
        )
        patterns = d.detect_consolidation_anomalies(
            DreamReport(weights_strengthened=1, weights_pruned=1, pre_warm_intents=["bar"])
        )
        # No anomaly — just baseline
        assert len(patterns) == 0


# ===========================================================================
# analyze() integration
# ===========================================================================


class TestAnalyzeIntegration:
    def test_returns_list_of_patterns(self) -> None:
        d = _make_detector()
        result = d.analyze()
        assert isinstance(result, list)

    def test_stores_snapshot_in_history(self) -> None:
        d = _make_detector()
        assert len(d._history) == 0
        d.analyze()
        assert len(d._history) == 1

    def test_history_respects_max_history(self) -> None:
        d = _make_detector(max_history=3)
        for _ in range(5):
            d.analyze()
        assert len(d._history) == 3

    def test_multiple_analyze_builds_trend(self) -> None:
        d = _make_detector()
        d.analyze()
        d.analyze()
        d.analyze()
        assert len(d._history) == 3


# ===========================================================================
# summary() and get_snapshot()
# ===========================================================================


class TestSummaryAndSnapshot:
    def test_summary_json_serializable(self) -> None:
        d = _make_detector()
        d.analyze()
        s = d.summary()
        # Should not raise
        json.dumps(s)
        assert "tc_n" in s
        assert "routing_entropy" in s
        assert "patterns_detected" in s

    def test_get_snapshot_returns_dynamics(self) -> None:
        d = _make_detector()
        snap = d.get_snapshot()
        assert isinstance(snap, SystemDynamicsSnapshot)
        assert snap.timestamp > 0

    def test_summary_latest_patterns_capped(self) -> None:
        d = _make_detector()
        # Manually add 10 patterns
        for i in range(10):
            d._all_patterns.append(EmergentPattern(
                pattern_type="test",
                description=f"pattern {i}",
                confidence=0.5,
            ))
        s = d.summary()
        assert len(s["latest_patterns"]) == 5


# ===========================================================================
# Runtime integration
# ===========================================================================


class TestRuntimeIntegration:
    @pytest.fixture
    def runtime(self, tmp_path):
        from probos.runtime import ProbOSRuntime
        from probos.config import load_config

        config_path = tmp_path / "system.yaml"
        config_path.write_text(
            "system:\n  name: ProbOS\n  version: 0.1.0\n"
            "pools:\n  default_size: 2\n  min_size: 1\n  max_size: 5\n"
            "mesh:\n  hebbian_decay_rate: 0.99\n  hebbian_reward: 0.05\n"
            "  gossip_interval_ms: 5000\n  signal_ttl_seconds: 30\n"
            "  semantic_matching: false\n"
            "consensus:\n  min_votes: 2\n  approval_threshold: 0.6\n"
            "  use_confidence_weights: true\n  trust_prior_alpha: 2.0\n"
            "  trust_prior_beta: 2.0\n  trust_decay_rate: 0.999\n"
            "  red_team_pool_size: 2\n"
            "cognitive:\n  llm_base_url: 'http://localhost:8080/v1'\n"
            "  llm_api_key: ''\n  llm_model_fast: 'mock'\n"
            "  llm_model_standard: 'mock'\n  llm_model_deep: 'mock'\n"
            "  llm_timeout_seconds: 5\n  working_memory_token_budget: 2000\n"
            "  decomposition_timeout_seconds: 5\n  dag_execution_timeout_seconds: 10\n"
            "  max_concurrent_tasks: 5\n  attention_decay_rate: 0.95\n"
            "  focus_history_size: 5\n  background_demotion_factor: 0.5\n"
            "scaling:\n  enabled: false\n"
            "federation:\n  enabled: false\n"
            "self_mod:\n  enabled: false\n"
            "qa:\n  enabled: false\n"
            "knowledge:\n  enabled: false\n"
            "dreaming:\n  idle_threshold_seconds: 300\n  dream_interval_seconds: 600\n"
            "  replay_episode_count: 10\n  pathway_strengthening_factor: 0.02\n"
            "  pathway_weakening_factor: 0.01\n  prune_threshold: 0.005\n"
            "  trust_boost: 0.1\n  trust_penalty: 0.05\n  pre_warm_top_k: 5\n"
        )
        config = load_config(str(config_path))
        rt = ProbOSRuntime(config=config, data_dir=str(tmp_path / "data"))
        return rt

    @pytest.mark.asyncio
    async def test_runtime_creates_detector(self, runtime, tmp_path) -> None:
        await runtime.start()
        try:
            assert runtime._emergent_detector is not None
            assert isinstance(runtime._emergent_detector, EmergentDetector)
        finally:
            await runtime.stop()

    @pytest.mark.asyncio
    async def test_status_includes_emergent(self, runtime, tmp_path) -> None:
        await runtime.start()
        try:
            status = runtime.status()
            assert "emergent" in status
            assert "tc_n" in status["emergent"]
        finally:
            await runtime.stop()

    @pytest.mark.asyncio
    async def test_detector_without_episodic_tc_n_zero(self, runtime, tmp_path) -> None:
        await runtime.start()
        try:
            tc = runtime._emergent_detector.compute_tc_n()
            assert tc == 0.0  # No episodic memory
        finally:
            await runtime.stop()

    @pytest.mark.asyncio
    async def test_post_dream_analysis_wired(self, runtime, tmp_path) -> None:
        """If dream scheduler exists, post_dream_fn should be set."""
        from probos.cognitive.episodic_mock import MockEpisodicMemory

        runtime.episodic_memory = MockEpisodicMemory()
        await runtime.start()
        try:
            if runtime.dream_scheduler:
                assert runtime.dream_scheduler._post_dream_fn is not None
        finally:
            await runtime.stop()


# ===========================================================================
# Introspection integration
# ===========================================================================


class TestIntrospectionIntegration:
    def _mock_runtime_with_detector(self) -> MagicMock:
        rt = MagicMock()
        router = _FakeRouter()
        trust = _FakeTrustNetwork({"a": {"alpha": 2, "beta": 2, "observations": 0}})
        detector = EmergentDetector(
            hebbian_router=router,  # type: ignore[arg-type]
            trust_network=trust,  # type: ignore[arg-type]
        )
        rt._emergent_detector = detector
        return rt

    @pytest.mark.asyncio
    async def test_system_anomalies_intent(self) -> None:
        agent = IntrospectionAgent(pool="introspect", agent_id="test_introspect_0")
        agent._runtime = self._mock_runtime_with_detector()

        intent = IntentMessage(intent="system_anomalies", params={})
        result = await agent.handle_intent(intent)
        assert result is not None
        assert result.success is True
        assert "anomaly_count" in result.result

    @pytest.mark.asyncio
    async def test_emergent_patterns_intent(self) -> None:
        agent = IntrospectionAgent(pool="introspect", agent_id="test_introspect_0")
        agent._runtime = self._mock_runtime_with_detector()

        intent = IntentMessage(intent="emergent_patterns", params={})
        result = await agent.handle_intent(intent)
        assert result is not None
        assert result.success is True
        assert "snapshot" in result.result
        assert "summary" in result.result

    @pytest.mark.asyncio
    async def test_mock_llm_routes_anomalies(self) -> None:
        client = MockLLMClient()
        request = LLMRequest(prompt="are there any anomalies in the system?")
        response = await client.complete(request)
        data = json.loads(response.content)
        intents = data.get("intents", [])
        assert len(intents) == 1
        assert intents[0]["intent"] == "system_anomalies"

    @pytest.mark.asyncio
    async def test_mock_llm_routes_emergent(self) -> None:
        client = MockLLMClient()
        request = LLMRequest(prompt="show emergent patterns")
        response = await client.complete(request)
        data = json.loads(response.content)
        intents = data.get("intents", [])
        assert len(intents) == 1
        assert intents[0]["intent"] == "emergent_patterns"


# ===========================================================================
# Shell and panel tests
# ===========================================================================


class TestShellAndPanel:
    @pytest.mark.asyncio
    async def test_anomalies_command(self, tmp_path) -> None:
        from probos.config import load_config
        from probos.runtime import ProbOSRuntime

        config_path = tmp_path / "system.yaml"
        config_path.write_text(
            "system:\n  name: ProbOS\n  version: 0.1.0\n"
            "pools:\n  default_size: 2\n  min_size: 1\n  max_size: 5\n"
            "mesh:\n  hebbian_decay_rate: 0.99\n  hebbian_reward: 0.05\n"
            "  gossip_interval_ms: 5000\n  signal_ttl_seconds: 30\n"
            "  semantic_matching: false\n"
            "consensus:\n  min_votes: 2\n  approval_threshold: 0.6\n"
            "  use_confidence_weights: true\n  trust_prior_alpha: 2.0\n"
            "  trust_prior_beta: 2.0\n  trust_decay_rate: 0.999\n"
            "  red_team_pool_size: 2\n"
            "cognitive:\n  llm_base_url: 'http://localhost:8080/v1'\n"
            "  llm_api_key: ''\n  llm_model_fast: 'mock'\n"
            "  llm_model_standard: 'mock'\n  llm_model_deep: 'mock'\n"
            "  llm_timeout_seconds: 5\n  working_memory_token_budget: 2000\n"
            "  decomposition_timeout_seconds: 5\n  dag_execution_timeout_seconds: 10\n"
            "  max_concurrent_tasks: 5\n  attention_decay_rate: 0.95\n"
            "  focus_history_size: 5\n  background_demotion_factor: 0.5\n"
            "scaling:\n  enabled: false\n"
            "federation:\n  enabled: false\n"
            "self_mod:\n  enabled: false\n"
            "qa:\n  enabled: false\n"
            "knowledge:\n  enabled: false\n"
            "dreaming:\n  idle_threshold_seconds: 300\n  dream_interval_seconds: 600\n"
            "  replay_episode_count: 10\n  pathway_strengthening_factor: 0.02\n"
            "  pathway_weakening_factor: 0.01\n  prune_threshold: 0.005\n"
            "  trust_boost: 0.1\n  trust_penalty: 0.05\n  pre_warm_top_k: 5\n"
        )
        config = load_config(str(config_path))
        rt = ProbOSRuntime(config=config, data_dir=str(tmp_path / "data"))
        await rt.start()
        try:
            buf = StringIO()
            console = Console(file=buf, width=120, force_terminal=True)
            shell = ProbOSShell(rt, console=console)
            await shell.execute_command("/anomalies")
            output = buf.getvalue()
            assert "Emergent Behavior" in output or "operating normally" in output
        finally:
            await rt.stop()

    def test_help_includes_anomalies(self) -> None:
        assert "/anomalies" in ProbOSShell.COMMANDS

    def test_render_panel_with_patterns(self) -> None:
        summary = {
            "tc_n": 0.3,
            "routing_entropy": 1.2,
            "cooperation_clusters": 2,
            "snapshots_recorded": 5,
            "patterns_detected": 3,
        }
        patterns = [
            {
                "pattern_type": "trust_anomaly",
                "description": "Agent X has low trust",
                "confidence": 0.9,
                "severity": "notable",
            },
        ]
        panel = render_anomalies_panel(summary, patterns)
        # Render to string to verify it works
        buf = StringIO()
        console = Console(file=buf, width=120, force_terminal=True)
        console.print(panel)
        output = buf.getvalue()
        assert "TC_N" in output
        assert "trust_anomaly" in output

    def test_render_panel_empty_normal(self) -> None:
        summary = {
            "tc_n": 0.0,
            "routing_entropy": 0.0,
            "cooperation_clusters": 0,
            "snapshots_recorded": 0,
            "patterns_detected": 0,
        }
        panel = render_anomalies_panel(summary, [])
        buf = StringIO()
        console = Console(file=buf, width=120, force_terminal=True)
        console.print(panel)
        output = buf.getvalue()
        assert "operating normally" in output

    def test_render_panel_severity_coloring(self) -> None:
        summary = {"tc_n": 0.0, "routing_entropy": 0.0, "cooperation_clusters": 0,
                    "snapshots_recorded": 0, "patterns_detected": 2}
        patterns = [
            {"pattern_type": "test", "description": "info", "confidence": 0.5, "severity": "info"},
            {"pattern_type": "test", "description": "sig", "confidence": 0.9, "severity": "significant"},
        ]
        panel = render_anomalies_panel(summary, patterns)
        buf = StringIO()
        console = Console(file=buf, width=120, force_terminal=True)
        console.print(panel)
        output = buf.getvalue()
        # Both rows should render without error
        assert "info" in output
        assert "sig" in output
