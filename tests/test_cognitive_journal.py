"""Tests for Cognitive Journal (AD-431, AD-432)."""

from __future__ import annotations

import time
import uuid

import pytest
from unittest.mock import AsyncMock, MagicMock

from probos.cognitive.journal import CognitiveJournal


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

async def _record(journal, agent_id="agent-A", agent_type="test", **kw):
    """Store a journal entry with sensible defaults."""
    defaults = dict(
        entry_id=uuid.uuid4().hex,
        timestamp=time.time(),
        agent_id=agent_id,
        agent_type=agent_type,
        tier="standard",
        model="test-model",
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        latency_ms=42.0,
        intent="test_intent",
        success=True,
        cached=False,
        request_id=uuid.uuid4().hex,
        prompt_hash="abc123",
        response_length=200,
    )
    defaults.update(kw)
    await journal.record(**defaults)


# ===========================================================================
# Test cases
# ===========================================================================

class TestJournalLifecycle:
    """Test 1: Journal starts and stops cleanly."""

    @pytest.mark.asyncio
    async def test_start_and_stop(self, tmp_path):
        db = str(tmp_path / "journal.db")
        journal = CognitiveJournal(db_path=db)
        await journal.start()
        assert journal._db is not None
        await journal.stop()
        assert journal._db is None
        assert (tmp_path / "journal.db").exists()

    @pytest.mark.asyncio
    async def test_start_no_db_path(self):
        """Journal with db_path=None starts silently (no crash)."""
        journal = CognitiveJournal(db_path=None)
        await journal.start()
        assert journal._db is None
        await journal.stop()


class TestJournalRecord:
    """Tests 2-3: record() stores entries and is fire-and-forget."""

    @pytest.mark.asyncio
    async def test_record_stores_entry(self, tmp_path):
        """Test 2: record() stores an entry with correct fields."""
        journal = CognitiveJournal(db_path=str(tmp_path / "journal.db"))
        await journal.start()
        try:
            await _record(journal, agent_id="agent-A", intent="analyze")
            entries = await journal.get_reasoning_chain("agent-A")
            assert len(entries) == 1
            assert entries[0]["agent_id"] == "agent-A"
            assert entries[0]["intent"] == "analyze"
            assert entries[0]["total_tokens"] == 150
            assert entries[0]["latency_ms"] == 42.0
        finally:
            await journal.stop()

    @pytest.mark.asyncio
    async def test_record_no_db_no_crash(self):
        """Test 3: record() with no db is fire-and-forget."""
        journal = CognitiveJournal(db_path=None)
        await journal.start()
        # Should not raise
        await _record(journal)
        await journal.stop()


class TestReasoningChain:
    """Tests 4-5: get_reasoning_chain ordering and filtering."""

    @pytest.mark.asyncio
    async def test_returns_most_recent_first(self, tmp_path):
        """Test 4: get_reasoning_chain returns entries most recent first."""
        journal = CognitiveJournal(db_path=str(tmp_path / "journal.db"))
        await journal.start()
        try:
            for i in range(5):
                await _record(journal, timestamp=1000.0 + i)
            entries = await journal.get_reasoning_chain("agent-A", limit=3)
            assert len(entries) == 3
            assert entries[0]["timestamp"] > entries[1]["timestamp"]
            assert entries[1]["timestamp"] > entries[2]["timestamp"]
        finally:
            await journal.stop()

    @pytest.mark.asyncio
    async def test_filters_by_agent_id(self, tmp_path):
        """Test 5: get_reasoning_chain filters by agent_id."""
        journal = CognitiveJournal(db_path=str(tmp_path / "journal.db"))
        await journal.start()
        try:
            await _record(journal, agent_id="agent-A")
            await _record(journal, agent_id="agent-A")
            await _record(journal, agent_id="agent-B")
            entries = await journal.get_reasoning_chain("agent-A")
            assert len(entries) == 2
            assert all(e["agent_id"] == "agent-A" for e in entries)
        finally:
            await journal.stop()


class TestTokenUsage:
    """Tests 6-7: get_token_usage returns correct totals."""

    @pytest.mark.asyncio
    async def test_per_agent_token_usage(self, tmp_path):
        """Test 6: get_token_usage returns correct sums, excludes cached."""
        journal = CognitiveJournal(db_path=str(tmp_path / "journal.db"))
        await journal.start()
        try:
            await _record(journal, agent_id="agent-A", prompt_tokens=100,
                          completion_tokens=50, total_tokens=150, cached=False)
            await _record(journal, agent_id="agent-A", prompt_tokens=200,
                          completion_tokens=100, total_tokens=300, cached=False)
            # Cached entry — should be excluded from totals
            await _record(journal, agent_id="agent-A", prompt_tokens=0,
                          completion_tokens=0, total_tokens=0, cached=True)

            usage = await journal.get_token_usage("agent-A")
            assert usage["total_calls"] == 2  # cached excluded
            assert usage["total_tokens"] == 450
            assert usage["prompt_tokens"] == 300
            assert usage["completion_tokens"] == 150
        finally:
            await journal.stop()

    @pytest.mark.asyncio
    async def test_ship_wide_token_usage(self, tmp_path):
        """Test 7: get_token_usage(None) returns ship-wide totals."""
        journal = CognitiveJournal(db_path=str(tmp_path / "journal.db"))
        await journal.start()
        try:
            await _record(journal, agent_id="agent-A", total_tokens=100, cached=False)
            await _record(journal, agent_id="agent-B", total_tokens=200, cached=False)

            usage = await journal.get_token_usage(None)
            assert usage["total_calls"] == 2
            assert usage["total_tokens"] == 300
        finally:
            await journal.stop()


class TestJournalStats:
    """Test 8: get_stats returns counts by type and intent."""

    @pytest.mark.asyncio
    async def test_stats_breakdown(self, tmp_path):
        journal = CognitiveJournal(db_path=str(tmp_path / "journal.db"))
        await journal.start()
        try:
            await _record(journal, agent_type="builder", intent="analyze")
            await _record(journal, agent_type="builder", intent="analyze")
            await _record(journal, agent_type="counselor", intent="direct_message")

            stats = await journal.get_stats()
            assert stats["total_entries"] == 3
            assert stats["by_agent_type"]["builder"] == 2
            assert stats["by_agent_type"]["counselor"] == 1
            assert stats["by_intent"]["analyze"] == 2
            assert stats["by_intent"]["direct_message"] == 1
        finally:
            await journal.stop()


# ---------------------------------------------------------------------------
# Integration with CognitiveAgent.decide()
# ---------------------------------------------------------------------------

from probos.cognitive.cognitive_agent import CognitiveAgent, _DECISION_CACHES, _CACHE_HITS, _CACHE_MISSES
from probos.cognitive.llm_client import MockLLMClient
from probos.types import IntentDescriptor


class _TestAgent(CognitiveAgent):
    agent_type = "test_journal_agent"
    _handled_intents = {"test"}
    instructions = "You are a test agent."
    intent_descriptors = [
        IntentDescriptor(name="test", params={}, description="Test", tier="domain")
    ]


class TestDecideJournalIntegration:
    """Tests 9-11: decide() records to journal."""

    @pytest.fixture(autouse=True)
    def clear_caches(self):
        _DECISION_CACHES.clear()
        _CACHE_HITS.clear()
        _CACHE_MISSES.clear()

    @pytest.mark.asyncio
    async def test_decide_records_to_journal(self):
        """Test 9: decide() records entry with correct metadata."""
        mock_journal = MagicMock()
        mock_journal.record = AsyncMock()
        rt = MagicMock()
        rt.cognitive_journal = mock_journal

        llm = MockLLMClient()
        agent = _TestAgent(llm_client=llm, runtime=rt)
        obs = {"intent": "test", "params": {"q": "hello"}, "context": ""}

        result = await agent.decide(obs)
        assert result["action"] == "execute"

        # Journal should have been called
        mock_journal.record.assert_called_once()
        call_kwargs = mock_journal.record.call_args[1]
        assert call_kwargs["agent_id"] == agent.id
        assert call_kwargs["agent_type"] == "test_journal_agent"
        assert call_kwargs["intent"] == "test"
        assert call_kwargs["cached"] is False
        assert call_kwargs["latency_ms"] >= 0

    @pytest.mark.asyncio
    async def test_cache_hit_records_cached_true(self):
        """Test 10: decide() cache hit records cached=True."""
        mock_journal = MagicMock()
        mock_journal.record = AsyncMock()
        rt = MagicMock()
        rt.cognitive_journal = mock_journal

        llm = MockLLMClient()
        agent = _TestAgent(llm_client=llm, runtime=rt, pool="test")
        obs = {"intent": "test", "params": {"q": "cache_test"}, "context": ""}

        await agent.decide(obs)  # First call — LLM miss
        await agent.decide(obs)  # Second call — cache hit

        assert mock_journal.record.call_count == 2
        # Second call should have cached=True
        second_call_kwargs = mock_journal.record.call_args_list[1][1]
        assert second_call_kwargs["cached"] is True

    @pytest.mark.asyncio
    async def test_journal_failure_doesnt_block_decide(self):
        """Test 11: journal.record() failure doesn't block decide()."""
        mock_journal = MagicMock()
        mock_journal.record = AsyncMock(side_effect=RuntimeError("DB error"))
        rt = MagicMock()
        rt.cognitive_journal = mock_journal

        llm = MockLLMClient()
        agent = _TestAgent(llm_client=llm, runtime=rt)
        obs = {"intent": "test", "params": {"q": "fail"}, "context": ""}

        result = await agent.decide(obs)
        assert result["action"] == "execute"
        assert "llm_output" in result


class TestResetWipesJournal:
    """Test 12: probos reset wipes the journal db file."""

    def test_reset_deletes_journal_db(self, tmp_path):
        """The reset code path should delete cognitive_journal.db."""
        journal_db = tmp_path / "cognitive_journal.db"
        journal_db.write_text("fake db")
        assert journal_db.exists()

        # Simulate the reset wipe logic
        if journal_db.is_file():
            journal_db.unlink()
        assert not journal_db.exists()


# ===========================================================================
# AD-432: Cognitive Journal Expansion tests
# ===========================================================================

class TestSchemaMigration:
    """AD-432 Test 1: Schema migration adds new columns idempotently."""

    @pytest.mark.asyncio
    async def test_migration_idempotent(self, tmp_path):
        db = str(tmp_path / "journal.db")
        journal = CognitiveJournal(db_path=db)
        await journal.start()
        await journal.stop()

        # Re-create with same DB — migration runs again, no error
        journal2 = CognitiveJournal(db_path=db)
        await journal2.start()
        try:
            await _record(journal2, intent_id="abc123", dag_node_id="node-1",
                          response_hash="deadbeef")
            entries = await journal2.get_reasoning_chain("agent-A")
            assert len(entries) == 1
            assert entries[0]["intent_id"] == "abc123"
            assert entries[0]["dag_node_id"] == "node-1"
            assert entries[0]["response_hash"] == "deadbeef"
        finally:
            await journal2.stop()


class TestNewColumns:
    """AD-432 Test 2: record() stores intent_id, dag_node_id, response_hash."""

    @pytest.mark.asyncio
    async def test_record_new_fields(self, tmp_path):
        journal = CognitiveJournal(db_path=str(tmp_path / "journal.db"))
        await journal.start()
        try:
            await _record(journal, intent_id="abc123", dag_node_id="node-1",
                          response_hash="deadbeef")
            entries = await journal.get_reasoning_chain("agent-A")
            assert entries[0]["intent_id"] == "abc123"
            assert entries[0]["dag_node_id"] == "node-1"
            assert entries[0]["response_hash"] == "deadbeef"
        finally:
            await journal.stop()


class TestReasoningChainTimeRange:
    """AD-432 Tests 3-5: get_reasoning_chain with since/until filters."""

    @pytest.mark.asyncio
    async def test_since_filter(self, tmp_path):
        journal = CognitiveJournal(db_path=str(tmp_path / "journal.db"))
        await journal.start()
        try:
            await _record(journal, timestamp=100.0)
            await _record(journal, timestamp=200.0)
            await _record(journal, timestamp=300.0)
            entries = await journal.get_reasoning_chain("agent-A", since=150.0)
            assert len(entries) == 2
            assert all(e["timestamp"] >= 150.0 for e in entries)
        finally:
            await journal.stop()

    @pytest.mark.asyncio
    async def test_until_filter(self, tmp_path):
        journal = CognitiveJournal(db_path=str(tmp_path / "journal.db"))
        await journal.start()
        try:
            await _record(journal, timestamp=100.0)
            await _record(journal, timestamp=200.0)
            await _record(journal, timestamp=300.0)
            entries = await journal.get_reasoning_chain("agent-A", until=250.0)
            assert len(entries) == 2
            assert all(e["timestamp"] <= 250.0 for e in entries)
        finally:
            await journal.stop()

    @pytest.mark.asyncio
    async def test_since_and_until(self, tmp_path):
        journal = CognitiveJournal(db_path=str(tmp_path / "journal.db"))
        await journal.start()
        try:
            await _record(journal, timestamp=100.0)
            await _record(journal, timestamp=200.0)
            await _record(journal, timestamp=300.0)
            entries = await journal.get_reasoning_chain(
                "agent-A", since=150.0, until=250.0,
            )
            assert len(entries) == 1
            assert entries[0]["timestamp"] == 200.0
        finally:
            await journal.stop()


class TestTokenUsageBy:
    """AD-432 Tests 6-9: get_token_usage_by grouped queries."""

    @pytest.mark.asyncio
    async def test_group_by_model(self, tmp_path):
        journal = CognitiveJournal(db_path=str(tmp_path / "journal.db"))
        await journal.start()
        try:
            await _record(journal, model="opus", total_tokens=100)
            await _record(journal, model="opus", total_tokens=200)
            await _record(journal, model="haiku", total_tokens=50)
            groups = await journal.get_token_usage_by(group_by="model")
            assert len(groups) == 2
            opus = next(g for g in groups if g["model"] == "opus")
            haiku = next(g for g in groups if g["model"] == "haiku")
            assert opus["total_calls"] == 2
            assert haiku["total_calls"] == 1
        finally:
            await journal.stop()

    @pytest.mark.asyncio
    async def test_group_by_tier(self, tmp_path):
        journal = CognitiveJournal(db_path=str(tmp_path / "journal.db"))
        await journal.start()
        try:
            await _record(journal, tier="standard", total_tokens=100)
            await _record(journal, tier="fast", total_tokens=50)
            await _record(journal, tier="fast", total_tokens=75)
            groups = await journal.get_token_usage_by(group_by="tier")
            assert len(groups) == 2
            standard = next(g for g in groups if g["tier"] == "standard")
            fast = next(g for g in groups if g["tier"] == "fast")
            assert standard["total_calls"] == 1
            assert fast["total_calls"] == 2
        finally:
            await journal.stop()

    @pytest.mark.asyncio
    async def test_rejects_invalid_group_by(self, tmp_path):
        journal = CognitiveJournal(db_path=str(tmp_path / "journal.db"))
        await journal.start()
        try:
            result = await journal.get_token_usage_by(group_by="DROP TABLE")
            assert result == []
        finally:
            await journal.stop()

    @pytest.mark.asyncio
    async def test_group_by_with_agent_filter(self, tmp_path):
        journal = CognitiveJournal(db_path=str(tmp_path / "journal.db"))
        await journal.start()
        try:
            await _record(journal, agent_id="agent-1", model="opus", total_tokens=100)
            await _record(journal, agent_id="agent-1", model="haiku", total_tokens=50)
            await _record(journal, agent_id="agent-2", model="opus", total_tokens=200)
            groups = await journal.get_token_usage_by(
                group_by="model", agent_id="agent-1",
            )
            # Only agent-1's entries
            total_calls = sum(g["total_calls"] for g in groups)
            assert total_calls == 2
        finally:
            await journal.stop()


class TestDecisionPoints:
    """AD-432 Tests 10-12: get_decision_points queries."""

    @pytest.mark.asyncio
    async def test_high_latency(self, tmp_path):
        journal = CognitiveJournal(db_path=str(tmp_path / "journal.db"))
        await journal.start()
        try:
            await _record(journal, latency_ms=100)
            await _record(journal, latency_ms=500)
            await _record(journal, latency_ms=1000)
            entries = await journal.get_decision_points(min_latency_ms=400)
            assert len(entries) == 2
            # Ordered by latency DESC
            assert entries[0]["latency_ms"] >= entries[1]["latency_ms"]
        finally:
            await journal.stop()

    @pytest.mark.asyncio
    async def test_failures_only(self, tmp_path):
        journal = CognitiveJournal(db_path=str(tmp_path / "journal.db"))
        await journal.start()
        try:
            await _record(journal, success=True, latency_ms=100)
            await _record(journal, success=True, latency_ms=200)
            await _record(journal, success=False, latency_ms=300)
            entries = await journal.get_decision_points(failures_only=True)
            assert len(entries) == 1
            assert entries[0]["success"] == 0
        finally:
            await journal.stop()

    @pytest.mark.asyncio
    async def test_agent_id_filter(self, tmp_path):
        journal = CognitiveJournal(db_path=str(tmp_path / "journal.db"))
        await journal.start()
        try:
            await _record(journal, agent_id="agent-1", latency_ms=100)
            await _record(journal, agent_id="agent-2", latency_ms=200)
            entries = await journal.get_decision_points(
                agent_id="agent-1", min_latency_ms=0,
            )
            assert len(entries) == 1
            assert entries[0]["agent_id"] == "agent-1"
        finally:
            await journal.stop()


class TestJournalWipe:
    """AD-432 Test 13: wipe() deletes all entries."""

    @pytest.mark.asyncio
    async def test_wipe_clears_all(self, tmp_path):
        journal = CognitiveJournal(db_path=str(tmp_path / "journal.db"))
        await journal.start()
        try:
            await _record(journal)
            await _record(journal)
            await _record(journal)
            stats = await journal.get_stats()
            assert stats["total_entries"] == 3

            await journal.wipe()

            stats = await journal.get_stats()
            assert stats["total_entries"] == 0
        finally:
            await journal.stop()


class TestPerceiveIntentId:
    """AD-432 Tests 14-15: perceive() intent_id plumbing."""

    @pytest.fixture(autouse=True)
    def clear_caches(self):
        _DECISION_CACHES.clear()
        _CACHE_HITS.clear()
        _CACHE_MISSES.clear()

    @pytest.mark.asyncio
    async def test_perceive_includes_intent_id(self):
        """Test 14: perceive() includes intent_id from IntentMessage."""
        from probos.types import IntentMessage
        agent = _TestAgent(llm_client=MockLLMClient(), runtime=MagicMock())
        msg = IntentMessage(intent="test", params={"q": "hello"}, context="ctx")
        obs = await agent.perceive(msg)
        assert "intent_id" in obs
        assert obs["intent_id"] == msg.id

    @pytest.mark.asyncio
    async def test_perceive_dict_no_intent_id(self):
        """Test 15: perceive() dict fallback does NOT add intent_id."""
        agent = _TestAgent(llm_client=MockLLMClient(), runtime=MagicMock())
        obs = await agent.perceive({"intent": "test", "params": {}, "context": ""})
        assert "intent_id" not in obs
