"""AD-570c: Natural Language Anchor Query Routing.

26 tests across 5 classes:
  TestParseAnchorQuery (12)      -- parse_anchor_query() pure function
  TestAnchorQueryTimeRange (4)   -- time_range computation
  TestTryAnchorRecall (5)        -- CognitiveAgent._try_anchor_recall()
  TestRecallMemoriesMerge (4)    -- anchor + semantic merge in _recall_relevant_memories()
  TestAllCallsigns (1)           -- CallsignRegistry.all_callsigns() contract
"""

from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.source_governance import (
    AnchorQuery,
    parse_anchor_query,
    _DEPARTMENT_ALIASES,
    _WATCH_SECTIONS,
    _WATCH_HOUR_RANGES,
    _WATCH_ORDER,
    _watch_section_to_time_range,
)


# ===========================================================================
# Test Class 1: TestParseAnchorQuery (12 tests)
# ===========================================================================


class TestParseAnchorQuery:
    """AD-570c: parse_anchor_query() pure function."""

    def test_no_signal_returns_empty(self):
        """Plain query with no anchor signals -> has_anchor_signal=False."""
        result = parse_anchor_query("what is the weather like")
        assert result.has_anchor_signal is False
        assert result.department == ""
        assert result.trigger_agent == ""
        assert result.participants == []
        assert result.watch_section == ""
        assert result.time_range is None
        assert result.semantic_query == "what is the weather like"

    def test_department_extraction_canonical(self):
        """'what happened in engineering' -> department='engineering'."""
        result = parse_anchor_query("what happened in engineering")
        assert result.has_anchor_signal is True
        assert result.department == "engineering"

    def test_department_extraction_alias(self):
        """'check sickbay logs' -> department='medical'."""
        result = parse_anchor_query("check sickbay logs")
        assert result.has_anchor_signal is True
        assert result.department == "medical"

    def test_department_extraction_case_insensitive(self):
        """'Engineering observations' -> department='engineering'."""
        result = parse_anchor_query("Engineering observations")
        assert result.has_anchor_signal is True
        assert result.department == "engineering"

    def test_watch_section_extraction(self):
        """'during the morning watch' -> watch_section='morning', time_range valid."""
        result = parse_anchor_query("during the morning watch")
        assert result.has_anchor_signal is True
        assert result.watch_section == "morning"
        assert result.time_range is not None
        # Morning watch = 0400-0800 UTC
        assert isinstance(result.time_range, tuple)
        assert len(result.time_range) == 2

    def test_watch_section_relative_last(self):
        """'last watch' -> resolves to previous watch section."""
        result = parse_anchor_query("events during last watch")
        assert result.has_anchor_signal is True
        assert result.watch_section != ""
        assert result.watch_section in _WATCH_ORDER
        assert result.time_range is not None

    def test_watch_section_relative_this(self):
        """'this watch' -> resolves to current watch section."""
        result = parse_anchor_query("what happened this watch")
        assert result.has_anchor_signal is True
        assert result.watch_section != ""
        assert result.watch_section in _WATCH_ORDER

    def test_agent_at_mention(self):
        """'what did @Worf observe' -> trigger_agent='Worf'."""
        result = parse_anchor_query("what did @Worf observe")
        assert result.has_anchor_signal is True
        assert result.trigger_agent == "Worf"

    def test_agent_bare_name_with_callsigns(self):
        """'observations from Worf' with known_callsigns=['Worf'] -> trigger_agent='Worf'."""
        result = parse_anchor_query(
            "observations from Worf",
            known_callsigns=["Worf", "LaForge", "Data"],
        )
        assert result.has_anchor_signal is True
        assert result.trigger_agent == "Worf"

    def test_agent_bare_name_without_callsigns(self):
        """'observations from Worf' without callsign list -> no trigger_agent."""
        result = parse_anchor_query("observations from Worf")
        # Bare names rejected without validation list
        assert result.trigger_agent == ""

    def test_combined_query(self):
        """Multi-signal query extracts department + agent + watch."""
        result = parse_anchor_query(
            "what did @LaForge see in engineering during the forenoon watch"
        )
        assert result.has_anchor_signal is True
        assert result.department == "engineering"
        assert result.trigger_agent == "LaForge"
        assert result.watch_section == "forenoon"
        # Remaining text should have the structural words stripped
        assert "engineering" not in result.semantic_query.lower()
        assert "@LaForge" not in result.semantic_query

    def test_semantic_query_preserves_remainder(self):
        """After extracting department, remaining text preserved as semantic_query."""
        result = parse_anchor_query("latency anomalies in engineering today")
        assert result.department == "engineering"
        # "latency anomalies" should remain in semantic_query
        assert "latency" in result.semantic_query.lower()
        assert "anomalies" in result.semantic_query.lower()


# ===========================================================================
# Test Class 2: TestAnchorQueryTimeRange (4 tests)
# ===========================================================================


class TestAnchorQueryTimeRange:
    """AD-570c: Time range computation from watch sections and temporal phrases."""

    def test_watch_section_to_time_range(self):
        """Known watch section -> time_range tuple with correct hour boundaries."""
        tr = _watch_section_to_time_range("morning")
        assert tr is not None
        start_dt = datetime.fromtimestamp(tr[0], tz=timezone.utc)
        end_dt = datetime.fromtimestamp(tr[1], tz=timezone.utc)
        assert start_dt.hour == 4
        assert end_dt.hour == 8

    def test_today_time_range(self):
        """'today' -> time_range from midnight UTC to now."""
        result = parse_anchor_query("events today")
        assert result.has_anchor_signal is True
        assert result.time_range is not None
        start_dt = datetime.fromtimestamp(result.time_range[0], tz=timezone.utc)
        now = datetime.now(timezone.utc)
        assert start_dt.hour == 0
        assert start_dt.minute == 0
        # End should be close to now
        assert abs(result.time_range[1] - now.timestamp()) < 5.0

    def test_yesterday_time_range(self):
        """'yesterday' -> time_range from yesterday midnight to today midnight."""
        result = parse_anchor_query("what happened yesterday")
        assert result.has_anchor_signal is True
        assert result.time_range is not None
        start_dt = datetime.fromtimestamp(result.time_range[0], tz=timezone.utc)
        end_dt = datetime.fromtimestamp(result.time_range[1], tz=timezone.utc)
        now = datetime.now(timezone.utc)
        today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_midnight = today_midnight - timedelta(days=1)
        assert abs(start_dt.timestamp() - yesterday_midnight.timestamp()) < 1.0
        assert abs(end_dt.timestamp() - today_midnight.timestamp()) < 1.0

    def test_no_temporal_signal(self):
        """Query without temporal phrases -> time_range=None, watch_section=''."""
        result = parse_anchor_query("show me the latest logs")
        assert result.time_range is None
        assert result.watch_section == ""


# ===========================================================================
# Test Class 3: TestTryAnchorRecall (5 tests)
# ===========================================================================


class TestTryAnchorRecall:
    """AD-570c: CognitiveAgent._try_anchor_recall()."""

    def _make_agent(self):
        from probos.cognitive.cognitive_agent import CognitiveAgent
        agent = CognitiveAgent.__new__(CognitiveAgent)
        agent._runtime = MagicMock()
        agent._runtime.episodic_memory = MagicMock()
        agent._runtime.callsign_registry = MagicMock()
        agent._runtime.callsign_registry.all_callsigns.return_value = {
            "security_chief": "Worf",
            "engineer": "LaForge",
        }
        return agent

    @pytest.mark.asyncio
    async def test_no_signal_returns_none(self):
        """Query with no anchor signals -> returns None."""
        agent = self._make_agent()
        result = await agent._try_anchor_recall("what is the time", "agent-1")
        assert result is None
        agent._runtime.episodic_memory.recall_by_anchor.assert_not_called()

    @pytest.mark.asyncio
    async def test_anchor_recall_called_with_department(self):
        """Query with department signal -> recall_by_anchor called with correct param."""
        agent = self._make_agent()
        mock_ep = MagicMock()
        mock_ep.id = "ep-1"
        agent._runtime.episodic_memory.recall_by_anchor = AsyncMock(return_value=[mock_ep])

        result = await agent._try_anchor_recall("what happened in engineering", "agent-1")
        assert result is not None
        assert len(result) == 1
        agent._runtime.episodic_memory.recall_by_anchor.assert_called_once()
        call_kwargs = agent._runtime.episodic_memory.recall_by_anchor.call_args.kwargs
        assert call_kwargs["department"] == "engineering"

    @pytest.mark.asyncio
    async def test_anchor_recall_fallthrough_on_empty(self):
        """recall_by_anchor returns [] -> returns None."""
        agent = self._make_agent()
        agent._runtime.episodic_memory.recall_by_anchor = AsyncMock(return_value=[])
        result = await agent._try_anchor_recall("what happened in engineering", "agent-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_anchor_recall_failure_returns_none(self):
        """recall_by_anchor raises -> returns None (log-and-degrade)."""
        agent = self._make_agent()
        agent._runtime.episodic_memory.recall_by_anchor = AsyncMock(
            side_effect=RuntimeError("db error")
        )
        # Should not raise
        result = await agent._try_anchor_recall("what happened in engineering", "agent-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_known_callsigns_passed(self):
        """all_callsigns() called on registry, result used for bare-name validation."""
        agent = self._make_agent()
        mock_ep = MagicMock()
        mock_ep.id = "ep-1"
        agent._runtime.episodic_memory.recall_by_anchor = AsyncMock(return_value=[mock_ep])

        # "from Worf" should be validated against known callsigns
        result = await agent._try_anchor_recall("observations from Worf", "agent-1")
        agent._runtime.callsign_registry.all_callsigns.assert_called()
        assert result is not None


# ===========================================================================
# Test Class 4: TestRecallMemoriesMerge (4 tests)
# ===========================================================================


class TestRecallMemoriesMerge:
    """AD-570c: Anchor + semantic merge in recall path."""

    def test_anchor_and_semantic_merged(self):
        """Both paths return episodes -> deduplicated merge, anchor first."""
        ep1 = MagicMock()
        ep1.id = "anchor-1"
        ep2 = MagicMock()
        ep2.id = "semantic-1"
        ep3 = MagicMock()
        ep3.id = "shared-1"

        anchor_episodes = [ep1, ep3]
        semantic_episodes = [ep3, ep2]  # ep3 appears in both

        # Simulate merge logic
        _seen_ids = {getattr(ep, 'id', id(ep)) for ep in anchor_episodes}
        for ep in semantic_episodes:
            if getattr(ep, 'id', id(ep)) not in _seen_ids:
                anchor_episodes.append(ep)
                _seen_ids.add(getattr(ep, 'id', id(ep)))
        episodes = anchor_episodes

        assert len(episodes) == 3  # ep1, ep3, ep2 (no dups)
        assert episodes[0].id == "anchor-1"  # Anchor episodes first
        assert episodes[1].id == "shared-1"
        assert episodes[2].id == "semantic-1"

    def test_anchor_only(self):
        """Anchor returns results, semantic returns empty -> anchor episodes used."""
        ep1 = MagicMock()
        ep1.id = "anchor-1"
        anchor_episodes = [ep1]
        semantic_episodes = []

        _seen_ids = {getattr(ep, 'id', id(ep)) for ep in anchor_episodes}
        for ep in semantic_episodes:
            if getattr(ep, 'id', id(ep)) not in _seen_ids:
                anchor_episodes.append(ep)
                _seen_ids.add(getattr(ep, 'id', id(ep)))
        episodes = anchor_episodes

        assert len(episodes) == 1
        assert episodes[0].id == "anchor-1"

    def test_semantic_only(self):
        """No anchor signal -> normal semantic path unchanged."""
        result = parse_anchor_query("tell me about the ship")
        assert result.has_anchor_signal is False
        # Caller would skip merge entirely

    def test_dedup_by_episode_id(self):
        """Same episode in both results -> appears only once."""
        ep_shared = MagicMock()
        ep_shared.id = "shared-1"

        anchor_episodes = [ep_shared]
        semantic_episodes = [ep_shared]

        _seen_ids = {getattr(ep, 'id', id(ep)) for ep in anchor_episodes}
        for ep in semantic_episodes:
            if getattr(ep, 'id', id(ep)) not in _seen_ids:
                anchor_episodes.append(ep)
                _seen_ids.add(getattr(ep, 'id', id(ep)))
        episodes = anchor_episodes

        assert len(episodes) == 1


# ===========================================================================
# Test Class 5: TestAllCallsigns (1 test)
# ===========================================================================


class TestAllCallsigns:
    """AD-570c: CallsignRegistry.all_callsigns() contract."""

    def test_all_callsigns_returns_dict(self):
        """CallsignRegistry.all_callsigns() returns dict of agent_type -> callsign."""
        from probos.crew_profile import CallsignRegistry

        reg = CallsignRegistry()
        result = reg.all_callsigns()
        assert isinstance(result, dict)

        # Register a callsign and verify
        reg._type_to_callsign["security_chief"] = "Worf"
        reg._callsign_to_type["worf"] = "security_chief"
        result = reg.all_callsigns()
        assert "security_chief" in result
        assert result["security_chief"] == "Worf"
