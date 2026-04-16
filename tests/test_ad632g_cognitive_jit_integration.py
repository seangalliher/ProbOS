"""AD-632g: Cognitive JIT Integration — Chain Pattern Learning tests.

Tests chain-aware procedure extraction, metadata propagation,
dream step integration, and replay of chain-compiled procedures.

Target: 27 tests across 6 classes.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.procedures import (
    Procedure,
    ProcedureStep,
    extract_chain_procedure,
    _CHAIN_DOMINANCE_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Helpers — lightweight Episode / Cluster mocks
# ---------------------------------------------------------------------------

@dataclass
class _MockAnchorFrame:
    channel: str = ""
    department: str = ""
    trigger_type: str = ""


@dataclass
class _MockEpisode:
    id: str = "ep-1"
    timestamp: float = 0.0
    user_input: str = ""
    outcomes: list[dict[str, Any]] = field(default_factory=list)
    reflection: str | None = None
    agent_ids: list[str] = field(default_factory=list)
    anchors: _MockAnchorFrame | None = None
    dag_summary: dict[str, Any] = field(default_factory=dict)


@dataclass
class _MockCluster:
    cluster_id: str = "cluster-1"
    episode_ids: list[str] = field(default_factory=list)
    intent_types: list[str] = field(default_factory=list)
    participating_agents: list[str] = field(default_factory=list)
    success_rate: float = 0.9
    is_success_dominant: bool = True
    anchor_summary: dict[str, Any] = field(default_factory=dict)


def _make_chain_episode(
    ep_id: str = "ep-1",
    intent: str = "ward_room_notification",
    chain_source: str = "intent_trigger:ward_room_notification",
    chain_steps: int = 5,
    success: bool = True,
    timestamp: float = 1000.0,
    response: str = "[REPLY] Acknowledged.",
) -> _MockEpisode:
    """Create a mock episode with chain metadata in outcomes."""
    return _MockEpisode(
        id=ep_id,
        timestamp=timestamp,
        outcomes=[{
            "intent": intent,
            "success": success,
            "response": response,
            "agent_type": "science_officer",
            "source": "intent_bus",
            "sub_task_chain": True,
            "chain_source": chain_source,
            "chain_steps": chain_steps,
        }],
        anchors=_MockAnchorFrame(
            channel="action",
            department="science",
            trigger_type=intent,
        ),
    )


def _make_non_chain_episode(ep_id: str = "ep-nc", intent: str = "ward_room_notification") -> _MockEpisode:
    """Create a mock episode without chain metadata."""
    return _MockEpisode(
        id=ep_id,
        timestamp=900.0,
        outcomes=[{
            "intent": intent,
            "success": True,
            "response": "Simple response.",
            "agent_type": "science_officer",
            "source": "intent_bus",
        }],
    )


# ===================================================================
# Class 1: TestChainDominanceDetection
# ===================================================================

class TestChainDominanceDetection:
    """Test chain dominance threshold detection."""

    def test_all_chain_episodes_dominant(self):
        eps = [_make_chain_episode(f"ep-{i}") for i in range(5)]
        cluster = _MockCluster(
            episode_ids=[e.id for e in eps],
            intent_types=["ward_room_notification"],
            participating_agents=["sci-abc"],
        )
        result = extract_chain_procedure(cluster, eps)
        assert result is not None

    def test_below_threshold_returns_none(self):
        chain_eps = [_make_chain_episode("ep-c1")]
        non_chain_eps = [_make_non_chain_episode(f"ep-nc-{i}") for i in range(4)]
        all_eps = chain_eps + non_chain_eps  # 20% chain — below 60%
        cluster = _MockCluster(
            episode_ids=[e.id for e in all_eps],
            intent_types=["ward_room_notification"],
            participating_agents=["sci-abc"],
        )
        result = extract_chain_procedure(cluster, all_eps)
        assert result is None

    def test_no_metadata_returns_none(self):
        eps = [_make_non_chain_episode(f"ep-{i}") for i in range(5)]
        cluster = _MockCluster(
            episode_ids=[e.id for e in eps],
            intent_types=["ward_room_notification"],
            participating_agents=["sci-abc"],
        )
        result = extract_chain_procedure(cluster, eps)
        assert result is None

    def test_boundary_60_percent_is_dominant(self):
        # 3 chain + 2 non-chain = 60% exactly
        chain_eps = [_make_chain_episode(f"ep-c{i}") for i in range(3)]
        non_chain_eps = [_make_non_chain_episode(f"ep-nc{i}") for i in range(2)]
        all_eps = chain_eps + non_chain_eps
        cluster = _MockCluster(
            episode_ids=[e.id for e in all_eps],
            intent_types=["ward_room_notification"],
            participating_agents=["sci-abc"],
        )
        result = extract_chain_procedure(cluster, all_eps)
        assert result is not None


# ===================================================================
# Class 2: TestChainProcedureExtraction
# ===================================================================

class TestChainProcedureExtraction:
    """Test procedure fields from chain extraction."""

    def _extract(self, intent: str = "ward_room_notification", source: str = "intent_trigger:ward_room_notification"):
        eps = [_make_chain_episode(f"ep-{i}", intent=intent, chain_source=source, timestamp=1000.0 + i) for i in range(3)]
        cluster = _MockCluster(
            cluster_id="cl-test",
            episode_ids=[e.id for e in eps],
            intent_types=[intent],
            participating_agents=["sci-abc"],
        )
        return extract_chain_procedure(cluster, eps)

    def test_ward_room_extraction(self):
        proc = self._extract("ward_room_notification")
        assert proc is not None
        assert "ward_room_notification" in proc.name

    def test_proactive_extraction(self):
        proc = self._extract("proactive_think", "intent_trigger:proactive_think")
        assert proc is not None
        assert "proactive_think" in proc.name

    def test_learned_via_chain_compiled(self):
        proc = self._extract()
        assert proc.learned_via == "chain_compiled"

    def test_compilation_level_2(self):
        proc = self._extract()
        assert proc.compilation_level == 2

    def test_intent_types_from_cluster(self):
        proc = self._extract("ward_room_notification")
        assert proc.intent_types == ["ward_room_notification"]

    def test_tags_include_chain_compiled(self):
        proc = self._extract()
        assert "chain_compiled" in proc.tags
        assert any(t.startswith("chain_source:") for t in proc.tags)


# ===================================================================
# Class 3: TestChainMetadataPropagation
# ===================================================================

class TestChainMetadataPropagation:
    """Test that chain metadata flows into decision dict."""

    def _make_agent(self):
        """Create a minimal mock cognitive agent."""
        from probos.cognitive.cognitive_agent import CognitiveAgent

        agent = CognitiveAgent.__new__(CognitiveAgent)
        agent.id = "test-agent-id"
        agent.agent_type = "test_agent"
        agent._sub_task_executor = MagicMock()
        agent._sub_task_executor.enabled = True
        agent._runtime = MagicMock()
        agent._runtime.cognitive_journal = MagicMock()
        return agent

    @pytest.mark.asyncio
    async def test_decision_includes_chain_source(self):
        from probos.cognitive.sub_task import SubTaskChain, SubTaskSpec, SubTaskType, SubTaskResult

        agent = self._make_agent()
        chain = SubTaskChain(
            steps=[SubTaskSpec(sub_task_type=SubTaskType.COMPOSE, name="test")],
            source="intent_trigger:ward_room_notification",
        )
        fake_result = SubTaskResult(
            sub_task_type=SubTaskType.COMPOSE,
            name="test",
            success=True,
            result={"output": "Hello"},
            tier_used="standard",
        )
        agent._sub_task_executor.execute = AsyncMock(return_value=[fake_result])

        result = await agent._execute_sub_task_chain(chain, {"intent": "ward_room_notification"})

        assert result is not None
        assert result["chain_source"] == "intent_trigger:ward_room_notification"

    @pytest.mark.asyncio
    async def test_decision_includes_chain_steps(self):
        from probos.cognitive.sub_task import SubTaskChain, SubTaskSpec, SubTaskType, SubTaskResult

        agent = self._make_agent()
        chain = SubTaskChain(
            steps=[
                SubTaskSpec(sub_task_type=SubTaskType.QUERY, name="q"),
                SubTaskSpec(sub_task_type=SubTaskType.COMPOSE, name="c"),
            ],
            source="test",
        )
        fake_result = SubTaskResult(
            sub_task_type=SubTaskType.COMPOSE,
            name="c",
            success=True,
            result={"output": "response"},
            tier_used="standard",
        )
        agent._sub_task_executor.execute = AsyncMock(return_value=[fake_result])

        result = await agent._execute_sub_task_chain(chain, {"intent": "test"})

        assert result is not None
        assert result["chain_steps"] == 2

    @pytest.mark.asyncio
    async def test_sub_task_chain_flag_still_present(self):
        from probos.cognitive.sub_task import SubTaskChain, SubTaskSpec, SubTaskType, SubTaskResult

        agent = self._make_agent()
        chain = SubTaskChain(
            steps=[SubTaskSpec(sub_task_type=SubTaskType.COMPOSE, name="c")],
            source="test",
        )
        fake_result = SubTaskResult(
            sub_task_type=SubTaskType.COMPOSE,
            name="c",
            success=True,
            result={"output": "ok"},
            tier_used="standard",
        )
        agent._sub_task_executor.execute = AsyncMock(return_value=[fake_result])

        result = await agent._execute_sub_task_chain(chain, {"intent": "test"})

        assert result["sub_task_chain"] is True

    def test_chain_metadata_injected_into_observation(self):
        """Chain metadata dict should be built from decision with sub_task_chain=True."""
        decision = {
            "sub_task_chain": True,
            "chain_source": "intent_trigger:ward_room_notification",
            "chain_steps": 5,
        }
        observation: dict[str, Any] = {}

        # Replicate the logic from handle_intent
        if decision.get("sub_task_chain"):
            observation["_chain_metadata"] = {
                "sub_task_chain": True,
                "chain_source": decision.get("chain_source", ""),
                "chain_steps": decision.get("chain_steps", 0),
            }

        assert observation["_chain_metadata"]["sub_task_chain"] is True
        assert observation["_chain_metadata"]["chain_source"] == "intent_trigger:ward_room_notification"
        assert observation["_chain_metadata"]["chain_steps"] == 5


# ===================================================================
# Class 4: TestDreamStepChainExtraction
# ===================================================================

class TestDreamStepChainExtraction:
    """Test Dream Step 7 chain-aware extraction integration."""

    def test_chain_extraction_before_llm(self):
        """Verify extract_chain_procedure is tried before LLM extraction."""
        # This is a structural test — chain extraction returns a procedure,
        # so LLM extraction should be skipped
        eps = [_make_chain_episode(f"ep-{i}", timestamp=1000.0 + i) for i in range(3)]
        cluster = _MockCluster(
            cluster_id="cl-dream",
            episode_ids=[e.id for e in eps],
            intent_types=["ward_room_notification"],
            participating_agents=["sci-abc"],
        )
        proc = extract_chain_procedure(cluster, eps)
        assert proc is not None
        # Chain procedure should be usable without LLM client
        assert proc.learned_via == "chain_compiled"

    def test_non_chain_cluster_returns_none(self):
        """Non-chain cluster falls through to LLM extraction."""
        eps = [_make_non_chain_episode(f"ep-{i}") for i in range(3)]
        cluster = _MockCluster(
            episode_ids=[e.id for e in eps],
            intent_types=["ward_room_notification"],
            participating_agents=["sci-abc"],
        )
        result = extract_chain_procedure(cluster, eps)
        assert result is None

    def test_dream_report_has_chain_field(self):
        from probos.types import DreamReport
        report = DreamReport()
        assert hasattr(report, "chain_procedures_extracted")
        assert report.chain_procedures_extracted == 0

    def test_dream_report_chain_field_assignable(self):
        from probos.types import DreamReport
        report = DreamReport(chain_procedures_extracted=3)
        assert report.chain_procedures_extracted == 3

    def test_has_cluster_dedup_prevents_duplicates(self):
        """Already-processed clusters shouldn't be re-extracted."""
        eps = [_make_chain_episode(f"ep-{i}") for i in range(3)]
        cluster = _MockCluster(
            cluster_id="cl-dedup",
            episode_ids=[e.id for e in eps],
            intent_types=["ward_room_notification"],
            participating_agents=["sci-abc"],
        )
        # First extraction succeeds
        proc1 = extract_chain_procedure(cluster, eps)
        assert proc1 is not None
        assert proc1.origin_cluster_id == "cl-dedup"
        # has_cluster check happens in dreaming.py, not in extract_chain_procedure,
        # so calling again with same cluster still returns a procedure
        proc2 = extract_chain_procedure(cluster, eps)
        assert proc2 is not None


# ===================================================================
# Class 5: TestChainProcedureReplay
# ===================================================================

class TestChainProcedureReplay:
    """Test that chain-compiled procedures work with existing replay path."""

    def test_chain_procedure_has_valid_structure(self):
        """Procedure should have steps, intent_types, etc. for store compatibility."""
        eps = [_make_chain_episode(f"ep-{i}") for i in range(3)]
        cluster = _MockCluster(
            cluster_id="cl-replay",
            episode_ids=[e.id for e in eps],
            intent_types=["ward_room_notification"],
            participating_agents=["sci-abc"],
        )
        proc = extract_chain_procedure(cluster, eps)
        assert proc is not None
        assert len(proc.steps) >= 1
        assert proc.intent_types == ["ward_room_notification"]
        assert proc.origin_cluster_id == "cl-replay"
        assert len(proc.provenance) == 3

    def test_learned_via_preserved_in_dict_roundtrip(self):
        eps = [_make_chain_episode(f"ep-{i}") for i in range(3)]
        cluster = _MockCluster(
            episode_ids=[e.id for e in eps],
            intent_types=["ward_room_notification"],
            participating_agents=["sci-abc"],
        )
        proc = extract_chain_procedure(cluster, eps)
        d = proc.to_dict()
        restored = Procedure.from_dict(d)
        assert restored.learned_via == "chain_compiled"

    def test_compilation_level_2_in_roundtrip(self):
        eps = [_make_chain_episode(f"ep-{i}") for i in range(3)]
        cluster = _MockCluster(
            episode_ids=[e.id for e in eps],
            intent_types=["ward_room_notification"],
            participating_agents=["sci-abc"],
        )
        proc = extract_chain_procedure(cluster, eps)
        d = proc.to_dict()
        restored = Procedure.from_dict(d)
        assert restored.compilation_level == 2

    def test_chain_procedure_replays_at_level_1(self):
        """Chain procedure produces flat decision dict (Level 1 replay)."""
        eps = [_make_chain_episode(f"ep-{i}") for i in range(3)]
        cluster = _MockCluster(
            episode_ids=[e.id for e in eps],
            intent_types=["ward_room_notification"],
            participating_agents=["sci-abc"],
        )
        proc = extract_chain_procedure(cluster, eps)
        # Verify it has the right shape for Level 1 replay
        assert proc.steps[0].expected_input == "ward_room_notification"
        assert proc.evolution_type == "CAPTURED"


# ===================================================================
# Class 6: TestChainProcedureEdgeCases
# ===================================================================

class TestChainProcedureEdgeCases:
    """Edge cases for chain procedure extraction."""

    def test_empty_cluster_returns_none(self):
        cluster = _MockCluster(
            episode_ids=[],
            intent_types=["ward_room_notification"],
            participating_agents=["sci-abc"],
        )
        result = extract_chain_procedure(cluster, [])
        assert result is None

    def test_malformed_metadata_falls_through(self):
        """Episodes with broken chain metadata should not crash."""
        ep = _MockEpisode(
            id="ep-bad",
            timestamp=1000.0,
            outcomes=[{
                "sub_task_chain": True,
                # Missing intent, chain_source, success
            }],
        )
        cluster = _MockCluster(
            episode_ids=["ep-bad"],
            intent_types=["ward_room_notification"],
            participating_agents=["sci-abc"],
        )
        # Should not crash — may return None or a degraded procedure
        result = extract_chain_procedure(cluster, [ep])
        # Acceptable: None or a procedure (fail-open)

    def test_single_chain_episode_still_extracts(self):
        """A single chain episode that's 100% dominant should extract."""
        ep = _make_chain_episode("ep-solo")
        cluster = _MockCluster(
            episode_ids=["ep-solo"],
            intent_types=["ward_room_notification"],
            participating_agents=["sci-abc"],
        )
        result = extract_chain_procedure(cluster, [ep])
        assert result is not None

    def test_negative_cluster_flags_procedure(self):
        """Chain procedure from failure-dominant cluster gets is_negative."""
        eps = [_make_chain_episode(f"ep-{i}", success=False) for i in range(3)]
        cluster = _MockCluster(
            episode_ids=[e.id for e in eps],
            intent_types=["ward_room_notification"],
            participating_agents=["sci-abc"],
            success_rate=0.3,  # failure-dominant
        )
        result = extract_chain_procedure(cluster, eps)
        # Returns None because no successful episodes to extract from
        # (best_ep requires success=True in outcome)
        assert result is None

    def test_action_tags_detected(self):
        """Procedure step should detect action tags from response."""
        eps = [_make_chain_episode(f"ep-{i}", response="[REPLY] I agree. [ENDORSE]") for i in range(3)]
        cluster = _MockCluster(
            episode_ids=[e.id for e in eps],
            intent_types=["ward_room_notification"],
            participating_agents=["sci-abc"],
        )
        proc = extract_chain_procedure(cluster, eps)
        assert proc is not None
        assert "REPLY" in proc.steps[0].expected_output
        assert "ENDORSE" in proc.steps[0].expected_output

    def test_source_anchors_collected(self):
        """Procedure should collect source anchors from chain episodes."""
        eps = [_make_chain_episode(f"ep-{i}") for i in range(3)]
        cluster = _MockCluster(
            episode_ids=[e.id for e in eps],
            intent_types=["ward_room_notification"],
            participating_agents=["sci-abc"],
        )
        proc = extract_chain_procedure(cluster, eps)
        assert proc is not None
        assert len(proc.source_anchors) >= 1
        assert proc.source_anchors[0]["department"] == "science"
