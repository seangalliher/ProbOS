"""AD-671: Tests for Dream-Working Memory Integration."""

from __future__ import annotations

import pytest

from probos.cognitive.agent_working_memory import AgentWorkingMemory
from probos.cognitive.dream_wm_bridge import DreamWorkingMemoryBridge
from probos.config import DreamWMConfig, SystemConfig
from probos.types import DreamReport, Episode, MemorySource


def _populated_wm(entry_count: int = 10) -> AgentWorkingMemory:
    wm = AgentWorkingMemory()
    for index in range(entry_count):
        wm.record_action(f"action-{index}", source="test")
    return wm


class TestPreDreamFlush:
    def test_pre_dream_flush_happy_path_returns_episode(self) -> None:
        bridge = DreamWorkingMemoryBridge(DreamWMConfig())
        wm = _populated_wm(10)

        result = bridge.pre_dream_flush(wm, agent_id="test-agent")

        assert result["flushed"] is True
        assert result["entry_count"] == 10
        assert isinstance(result["episode"], Episode)
        assert result["episode"].source == MemorySource.REFLECTION
        assert result["episode"].anchors is not None
        assert result["episode"].anchors.trigger_type == "dream_wm_flush"
        assert result["episode"].user_input == "[WM Session Summary]"

    def test_pre_dream_flush_below_threshold_returns_reason(self) -> None:
        bridge = DreamWorkingMemoryBridge(DreamWMConfig())
        wm = _populated_wm(3)

        result = bridge.pre_dream_flush(wm, agent_id="test-agent")

        assert result["flushed"] is False
        assert result["entry_count"] == 3
        assert result["reason"] == "below_threshold"
        assert "episode" not in result

    def test_pre_dream_flush_none_wm_returns_no_wm(self) -> None:
        bridge = DreamWorkingMemoryBridge(DreamWMConfig())

        result = bridge.pre_dream_flush(None, agent_id="test-agent")

        assert result["flushed"] is False
        assert result["entry_count"] == 0
        assert result["reason"] == "no_wm"

    def test_pre_dream_flush_empty_wm_returns_below_threshold(self) -> None:
        bridge = DreamWorkingMemoryBridge(DreamWMConfig())
        wm = AgentWorkingMemory()

        result = bridge.pre_dream_flush(wm, agent_id="test-agent")

        assert result["flushed"] is False
        assert result["entry_count"] == 0
        assert result["reason"] == "below_threshold"

    def test_pre_dream_flush_session_summary_content(self) -> None:
        bridge = DreamWorkingMemoryBridge(DreamWMConfig(flush_min_entries=1))
        wm = AgentWorkingMemory()
        for index in range(3):
            wm.record_action(f"action-{index}", source="proactive")
        for index in range(2):
            wm.record_observation(f"observation-{index}", source="ward_room")

        result = bridge.pre_dream_flush(wm, agent_id="test-agent")
        summary = result["episode"].dag_summary

        assert summary["buffer_counts"]["recent_actions"] == 3
        assert summary["buffer_counts"]["recent_observations"] == 2
        assert ("proactive", 3) in summary["top_sources"]


class TestPostDreamSeed:
    def test_post_dream_seed_happy_path_records_insights(self) -> None:
        bridge = DreamWorkingMemoryBridge(DreamWMConfig())
        wm = AgentWorkingMemory()
        report = DreamReport(procedures_extracted=2, gaps_classified=1)

        seeded = bridge.post_dream_seed(wm, report, dream_cycle_id="cycle-1")
        observations = wm.to_dict()["recent_observations"]

        assert seeded == 2
        assert len(observations) == 2
        assert observations[0]["content"].startswith("Dream insight:")
        assert observations[0]["metadata"]["dream_cycle_id"] == "cycle-1"

    def test_post_dream_seed_respects_max_priming_entries(self) -> None:
        bridge = DreamWorkingMemoryBridge(DreamWMConfig(max_priming_entries=2))
        wm = AgentWorkingMemory()
        report = DreamReport(
            procedures_extracted=1,
            procedures_evolved=1,
            gaps_classified=1,
            emergence_capacity=0.8,
            notebook_consolidations=1,
        )

        seeded = bridge.post_dream_seed(wm, report, dream_cycle_id="cycle-1")

        assert seeded == 2
        assert len(wm.to_dict()["recent_observations"]) == 2

    def test_post_dream_seed_no_insights_returns_zero(self) -> None:
        bridge = DreamWorkingMemoryBridge(DreamWMConfig())
        wm = AgentWorkingMemory()

        seeded = bridge.post_dream_seed(wm, DreamReport(), dream_cycle_id="cycle-1")

        assert seeded == 0
        assert wm.to_dict()["recent_observations"] == []

    def test_post_dream_seed_knowledge_source_is_procedural(self) -> None:
        bridge = DreamWorkingMemoryBridge(DreamWMConfig())
        wm = AgentWorkingMemory()
        report = DreamReport(procedures_extracted=1)

        bridge.post_dream_seed(wm, report, dream_cycle_id="cycle-1")
        observation = wm.to_dict()["recent_observations"][0]

        assert observation["knowledge_source"] == "procedural"


class TestConfigAndReport:
    def test_dream_wm_config_defaults(self) -> None:
        config = DreamWMConfig()

        assert config.enabled is True
        assert config.max_priming_entries == 3
        assert config.flush_min_entries == 5

    def test_dream_wm_config_in_system_config(self) -> None:
        config = SystemConfig()

        assert config.dream_wm.enabled is True
        assert isinstance(config.dream_wm, DreamWMConfig)

    def test_dream_report_has_wm_bridge_fields(self) -> None:
        report = DreamReport(wm_entries_flushed=5, wm_priming_entries=2)

        assert report.wm_entries_flushed == 5
        assert report.wm_priming_entries == 2


class TestDreamingEngineIntegration:
    @pytest.mark.asyncio
    async def test_dreaming_engine_accepts_bridge_parameter(self) -> None:
        from probos.cognitive.dreaming import DreamingEngine
        from probos.config import DreamingConfig

        engine = DreamingEngine(
            router=None,
            trust_network=None,
            episodic_memory=None,
            config=DreamingConfig(),
            dream_wm_bridge="sentinel",
        )

        assert engine._dream_wm_bridge == "sentinel"
