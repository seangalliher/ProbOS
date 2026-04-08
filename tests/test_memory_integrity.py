"""Tests for AD-541: Memory Integrity Verification — MemorySource, verification, reliability."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.episodic import EpisodicMemory
from probos.cognitive.standing_orders import compose_instructions, clear_cache
from probos.types import Episode, IntentDescriptor, IntentMessage, MemorySource


# ---------------------------------------------------------------------------
# Concrete subclass for testing
# ---------------------------------------------------------------------------

class IntegrityTestAgent(CognitiveAgent):
    """Minimal CognitiveAgent for memory integrity tests."""

    agent_type = "integrity_test"
    _handled_intents = {"direct_message"}
    instructions = "You are a test agent."
    intent_descriptors = [
        IntentDescriptor(
            name="direct_message",
            params={"text": "input"},
            description="DM",
            tier="domain",
        )
    ]


# ---------------------------------------------------------------------------
# MemorySource Enum Tests
# ---------------------------------------------------------------------------

class TestMemorySourceEnum:
    """Test MemorySource enum values and properties."""

    def test_values_are_strings(self):
        assert MemorySource.DIRECT == "direct"
        assert MemorySource.SECONDHAND == "secondhand"
        assert MemorySource.SHIP_RECORDS == "ship_records"
        assert MemorySource.BRIEFING == "briefing"

    def test_is_str_enum(self):
        assert isinstance(MemorySource.DIRECT, str)
        assert isinstance(MemorySource.SECONDHAND, str)


# ---------------------------------------------------------------------------
# Episode Source Field Tests
# ---------------------------------------------------------------------------

class TestEpisodeSourceField:
    """Test Episode dataclass source field."""

    def test_default_is_direct(self):
        ep = Episode()
        assert ep.source == "direct"

    def test_accepts_memory_source(self):
        ep = Episode(source=MemorySource.SECONDHAND)
        assert ep.source == "secondhand"

    def test_accepts_string(self):
        ep = Episode(source="briefing")
        assert ep.source == "briefing"


# ---------------------------------------------------------------------------
# ChromaDB Metadata Round-Trip Tests
# ---------------------------------------------------------------------------

class TestEpisodicMetadataRoundTrip:
    """Test source field persists through ChromaDB metadata conversion."""

    def test_source_persisted_in_metadata(self):
        ep = Episode(source=MemorySource.DIRECT)
        metadata = EpisodicMemory._episode_to_metadata(ep)
        assert metadata["source"] == "direct"

    def test_source_restored_from_metadata(self):
        metadata = {
            "timestamp": 1000.0,
            "intent_type": "",
            "dag_summary_json": "{}",
            "outcomes_json": "[]",
            "reflection": "",
            "agent_ids_json": "[]",
            "duration_ms": 0.0,
            "shapley_values_json": "{}",
            "trust_deltas_json": "[]",
            "source": "secondhand",
        }
        ep = EpisodicMemory._metadata_to_episode("test-id", "test doc", metadata)
        assert ep.source == "secondhand"

    def test_missing_source_defaults_to_direct(self):
        metadata = {
            "timestamp": 1000.0,
            "intent_type": "",
            "dag_summary_json": "{}",
            "outcomes_json": "[]",
            "reflection": "",
            "agent_ids_json": "[]",
            "duration_ms": 0.0,
            "shapley_values_json": "{}",
            "trust_deltas_json": "[]",
            # No "source" key — backwards compatibility
        }
        ep = EpisodicMemory._metadata_to_episode("test-id", "test doc", metadata)
        assert ep.source == "direct"


# ---------------------------------------------------------------------------
# EventLog Verification Tests
# ---------------------------------------------------------------------------

class TestEventLogVerification:
    """Test AD-541 Pillar 1: EventLog verification at recall time."""

    def _make_agent_with_runtime(self, episodes, event_log=None):
        """Create an IntegrityTestAgent with mocked runtime."""
        agent = IntegrityTestAgent.__new__(IntegrityTestAgent)
        agent.id = "test-agent-id"
        agent.agent_type = "integrity_test"

        rt = MagicMock()
        rt.episodic_memory = AsyncMock()
        rt.episodic_memory.recall_for_agent = AsyncMock(return_value=episodes)
        # AD-567b: recall_weighted is the primary path; return empty to fall through to recall_for_agent
        rt.episodic_memory.recall_weighted = AsyncMock(return_value=[])
        rt.episodic_memory.count_for_agent = AsyncMock(return_value=len(episodes))

        # Ontology + crew check
        mock_ontology = MagicMock()
        rt.ontology = mock_ontology
        rt.callsign_registry = MagicMock()
        rt.callsign_registry.get_callsign = MagicMock(return_value="TestAgent")

        # Config for temporal awareness
        rt.config = MagicMock()
        rt.config.temporal.include_episode_timestamps = True

        if event_log is not None:
            rt.event_log = event_log
        else:
            # No event_log attribute
            if hasattr(rt, 'event_log'):
                del rt.event_log

        agent._runtime = rt
        return agent

    @pytest.mark.asyncio
    async def test_verified_when_eventlog_corroborates(self):
        """Test 7: Verified when EventLog has entry within 120s."""
        now = time.time()
        ep = Episode(
            user_input="Test action",
            timestamp=now,
            agent_ids=["agent-1"],
            source=MemorySource.DIRECT,
        )
        from datetime import datetime, timezone
        evt_ts = datetime.fromtimestamp(now + 10, tz=timezone.utc).isoformat()
        event_log = AsyncMock()
        event_log.query = AsyncMock(return_value=[{"timestamp": evt_ts}])

        agent = self._make_agent_with_runtime([ep], event_log=event_log)
        # Need crew check to pass
        with patch("probos.crew_utils.is_crew_agent", return_value=True):
            intent = IntentMessage(
                intent="direct_message",
                params={"text": "test"},
                target_agent_id=agent.id,
            )
            observation = {"intent": "direct_message", "params": {"text": "test"}}
            result = await agent._recall_relevant_memories(intent, observation)

        assert result["recent_memories"][0]["verified"] is True

    @pytest.mark.asyncio
    async def test_unverified_when_eventlog_empty(self):
        """Test 8: Unverified when EventLog returns no matching entry."""
        now = time.time()
        ep = Episode(
            user_input="Test action",
            timestamp=now,
            agent_ids=["agent-1"],
            source=MemorySource.DIRECT,
        )
        event_log = AsyncMock()
        event_log.query = AsyncMock(return_value=[])

        agent = self._make_agent_with_runtime([ep], event_log=event_log)
        with patch("probos.crew_utils.is_crew_agent", return_value=True):
            intent = IntentMessage(
                intent="direct_message",
                params={"text": "test"},
                target_agent_id=agent.id,
            )
            observation = {"intent": "direct_message", "params": {"text": "test"}}
            result = await agent._recall_relevant_memories(intent, observation)

        assert result["recent_memories"][0]["verified"] is False

    @pytest.mark.asyncio
    async def test_unverified_when_no_eventlog(self):
        """Test 9: Unverified when runtime has no event_log."""
        now = time.time()
        ep = Episode(
            user_input="Test action",
            timestamp=now,
            agent_ids=["agent-1"],
            source=MemorySource.DIRECT,
        )
        agent = self._make_agent_with_runtime([ep], event_log=None)
        # Explicitly remove event_log
        if hasattr(agent._runtime, 'event_log'):
            del agent._runtime.event_log

        with patch("probos.crew_utils.is_crew_agent", return_value=True):
            intent = IntentMessage(
                intent="direct_message",
                params={"text": "test"},
                target_agent_id=agent.id,
            )
            observation = {"intent": "direct_message", "params": {"text": "test"}}
            result = await agent._recall_relevant_memories(intent, observation)

        assert result["recent_memories"][0]["verified"] is False

    @pytest.mark.asyncio
    async def test_unverified_when_timestamp_outside_window(self):
        """Test 10: Unverified when EventLog timestamp is > 120s from episode."""
        now = time.time()
        ep = Episode(
            user_input="Test action",
            timestamp=now,
            agent_ids=["agent-1"],
            source=MemorySource.DIRECT,
        )
        from datetime import datetime, timezone
        # 300 seconds away — outside 120s window
        evt_ts = datetime.fromtimestamp(now + 300, tz=timezone.utc).isoformat()
        event_log = AsyncMock()
        event_log.query = AsyncMock(return_value=[{"timestamp": evt_ts}])

        agent = self._make_agent_with_runtime([ep], event_log=event_log)
        with patch("probos.crew_utils.is_crew_agent", return_value=True):
            intent = IntentMessage(
                intent="direct_message",
                params={"text": "test"},
                target_agent_id=agent.id,
            )
            observation = {"intent": "direct_message", "params": {"text": "test"}}
            result = await agent._recall_relevant_memories(intent, observation)

        assert result["recent_memories"][0]["verified"] is False


# ---------------------------------------------------------------------------
# Boundary Marker Source/Verification Tag Tests
# ---------------------------------------------------------------------------

class TestBoundaryMarkerTags:
    """Test AD-541 source and verification tags in formatted output."""

    def setup_method(self):
        self.agent = IntegrityTestAgent.__new__(IntegrityTestAgent)

    def test_direct_verified_tags(self):
        memories = [{"input": "Test", "source": "direct", "verified": True}]
        lines = self.agent._format_memory_section(memories)
        text = "\n".join(lines)
        assert "[direct | verified]" in text

    def test_secondhand_unverified_tags(self):
        memories = [{"input": "Test", "source": "secondhand", "verified": False}]
        lines = self.agent._format_memory_section(memories)
        text = "\n".join(lines)
        assert "[secondhand | unverified]" in text

    def test_marker_legend_present(self):
        memories = [{"input": "Test", "source": "direct", "verified": False}]
        lines = self.agent._format_memory_section(memories)
        text = "\n".join(lines)
        assert "[direct] = you experienced it" in text
        assert "[verified] = corroborated" in text

    def test_source_field_from_recall(self):
        """Source field included in memory dicts from _recall_relevant_memories."""
        memories = [{"input": "Test", "source": "direct", "verified": False}]
        lines = self.agent._format_memory_section(memories)
        text = "\n".join(lines)
        assert "[direct |" in text


# ---------------------------------------------------------------------------
# Standing Order — Memory Reliability Hierarchy
# ---------------------------------------------------------------------------

class TestMemoryReliabilityHierarchy:
    """Test AD-541 Pillar 6: Memory Reliability Hierarchy standing order."""

    def test_hierarchy_section_present(self):
        clear_cache()
        result = compose_instructions(
            "integrity_test",
            "Test instructions.",
        )
        assert "Memory Reliability Hierarchy" in result

    def test_hierarchy_order(self):
        clear_cache()
        result = compose_instructions(
            "integrity_test",
            "Test instructions.",
        )
        # Within the hierarchy section, EventLog should appear before Episodic Memory
        hierarchy_start = result.index("Memory Reliability Hierarchy")
        hierarchy_text = result[hierarchy_start:]
        idx_eventlog = hierarchy_text.index("EventLog")
        idx_episodic = hierarchy_text.index("Episodic Memory")
        assert idx_eventlog < idx_episodic

    def test_hierarchy_has_all_tiers(self):
        clear_cache()
        result = compose_instructions(
            "integrity_test",
            "Test instructions.",
        )
        assert "[direct | verified]" in result
        assert "[direct | unverified]" in result
        assert "[secondhand]" in result
        assert "Training Knowledge" in result
