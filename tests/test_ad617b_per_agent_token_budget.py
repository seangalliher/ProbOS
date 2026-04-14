"""AD-617b: Per-Agent Hourly Token Budget tests.

Tests for CognitiveJournal.get_token_usage_since(), proactive loop
budget gate, and LLMRateConfig per-agent fields.
"""

import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.journal import CognitiveJournal
from probos.config import LLMRateConfig, SystemConfig
from probos.proactive import ProactiveCognitiveLoop


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _insert_entry(journal, agent_id, total_tokens, timestamp, cached=False):
    """Insert a journal entry for testing."""
    await journal.record(
        entry_id=uuid.uuid4().hex,
        timestamp=timestamp,
        agent_id=agent_id,
        total_tokens=total_tokens,
        cached=cached,
    )


def _make_proactive_loop(**kwargs) -> ProactiveCognitiveLoop:
    """Create a ProactiveCognitiveLoop with minimal wiring."""
    return ProactiveCognitiveLoop(**kwargs)


# ---------------------------------------------------------------------------
# Class 1: TestGetTokenUsageSince
# ---------------------------------------------------------------------------

class TestGetTokenUsageSince:
    """Tests for CognitiveJournal.get_token_usage_since()."""

    @pytest.fixture
    async def journal(self, tmp_path):
        j = CognitiveJournal(db_path=str(tmp_path / "journal.db"))
        await j.start()
        yield j
        await j.stop()

    @pytest.mark.asyncio
    async def test_returns_zero_for_no_entries(self, journal):
        """No entries for agent. Returns 0."""
        result = await journal.get_token_usage_since("agent_x", time.time() - 3600)
        assert result == 0

    @pytest.mark.asyncio
    async def test_sums_tokens_within_window(self, journal):
        """Insert 3 entries, query within window. Returns sum."""
        now = time.time()
        await _insert_entry(journal, "a1", 100, now - 10)
        await _insert_entry(journal, "a1", 200, now - 5)
        await _insert_entry(journal, "a1", 300, now - 1)

        result = await journal.get_token_usage_since("a1", now - 3600)
        assert result == 600

    @pytest.mark.asyncio
    async def test_excludes_entries_before_window(self, journal):
        """Entries before the `since` timestamp are excluded."""
        now = time.time()
        await _insert_entry(journal, "a1", 1000, now - 7200)  # 2 hours ago — excluded
        await _insert_entry(journal, "a1", 200, now - 10)     # recent — included

        result = await journal.get_token_usage_since("a1", now - 3600)
        assert result == 200

    @pytest.mark.asyncio
    async def test_excludes_cached_entries(self, journal):
        """Cached entries are not counted."""
        now = time.time()
        await _insert_entry(journal, "a1", 500, now - 10, cached=True)
        await _insert_entry(journal, "a1", 200, now - 5, cached=False)

        result = await journal.get_token_usage_since("a1", now - 3600)
        assert result == 200

    @pytest.mark.asyncio
    async def test_filters_by_agent_id(self, journal):
        """Query for a1 only returns a1's tokens, not a2's."""
        now = time.time()
        await _insert_entry(journal, "a1", 100, now - 10)
        await _insert_entry(journal, "a2", 999, now - 5)

        result = await journal.get_token_usage_since("a1", now - 3600)
        assert result == 100


# ---------------------------------------------------------------------------
# Class 2: TestTokenBudgetGate
# ---------------------------------------------------------------------------

class TestTokenBudgetGate:
    """Tests for _is_over_token_budget in ProactiveLoop."""

    def _make_loop_with_runtime(self, hourly_cap=0, journal_tokens=0):
        """Create ProactiveLoop with mocked runtime."""
        loop = _make_proactive_loop()

        # Mock runtime
        rt = MagicMock()
        config = MagicMock()
        rate_config = LLMRateConfig(per_agent_hourly_token_cap=hourly_cap)
        config.llm_rate = rate_config
        rt.config = config

        journal = AsyncMock()
        journal.get_token_usage_since = AsyncMock(return_value=journal_tokens)
        rt.cognitive_journal = journal

        loop._runtime = rt
        return loop, journal

    @pytest.mark.asyncio
    async def test_allows_when_disabled(self):
        """per_agent_hourly_token_cap=0 means disabled. Returns False."""
        loop, _ = self._make_loop_with_runtime(hourly_cap=0)
        result = await loop._is_over_token_budget("agent1")
        assert result is False

    @pytest.mark.asyncio
    async def test_allows_when_under_budget(self):
        """Under budget. Returns False."""
        loop, _ = self._make_loop_with_runtime(hourly_cap=10000, journal_tokens=5000)
        result = await loop._is_over_token_budget("agent1")
        assert result is False

    @pytest.mark.asyncio
    async def test_blocks_when_over_budget(self):
        """Over budget. Returns True."""
        loop, _ = self._make_loop_with_runtime(hourly_cap=10000, journal_tokens=15000)
        result = await loop._is_over_token_budget("agent1")
        assert result is True

    @pytest.mark.asyncio
    async def test_caches_exhaustion_for_60s(self):
        """First check returns over-budget. Second within 60s uses cache."""
        loop, journal = self._make_loop_with_runtime(
            hourly_cap=10000, journal_tokens=15000
        )

        # First call — queries journal, gets over-budget
        result1 = await loop._is_over_token_budget("agent1")
        assert result1 is True
        assert journal.get_token_usage_since.call_count == 1

        # Second call — within 60s, should use cache (no re-query)
        result2 = await loop._is_over_token_budget("agent1")
        assert result2 is True
        assert journal.get_token_usage_since.call_count == 1  # No additional query

    @pytest.mark.asyncio
    async def test_clears_exhaustion_when_recovered(self):
        """Over-budget, then tokens age out. Exhaustion cleared."""
        loop, journal = self._make_loop_with_runtime(
            hourly_cap=10000, journal_tokens=15000
        )

        # First call — over budget
        await loop._is_over_token_budget("agent1")
        assert "agent1" in loop._budget_exhausted

        # Age the exhaustion timestamp so cache expires
        loop._budget_exhausted["agent1"] = time.monotonic() - 61.0

        # Second call — journal now reports under budget
        journal.get_token_usage_since.return_value = 3000
        result = await loop._is_over_token_budget("agent1")
        assert result is False
        assert "agent1" not in loop._budget_exhausted

    @pytest.mark.asyncio
    async def test_budget_gate_ordering_after_circuit_breaker(self):
        """Verify budget gate is after circuit breaker and before _think_for_agent."""
        import inspect
        source = inspect.getsource(ProactiveCognitiveLoop._run_cycle)

        # Find positions of key markers
        cb_pos = source.find("circuit_breaker.should_allow_think")
        budget_pos = source.find("_is_over_token_budget")
        think_pos = source.find("_think_for_agent")

        assert cb_pos > 0, "Circuit breaker gate not found"
        assert budget_pos > 0, "Budget gate not found"
        assert think_pos > 0, "_think_for_agent not found"

        assert cb_pos < budget_pos < think_pos, (
            f"Ordering wrong: CB@{cb_pos}, budget@{budget_pos}, think@{think_pos}"
        )


# ---------------------------------------------------------------------------
# Class 3: TestTokenBudgetConfig
# ---------------------------------------------------------------------------

class TestTokenBudgetConfig:
    """Tests for LLMRateConfig per-agent token budget field."""

    def test_default_disabled(self):
        """Default per_agent_hourly_token_cap is 0 (disabled)."""
        config = LLMRateConfig()
        assert config.per_agent_hourly_token_cap == 0

    def test_custom_value(self):
        """Custom cap value persists."""
        config = LLMRateConfig(per_agent_hourly_token_cap=50000)
        assert config.per_agent_hourly_token_cap == 50000
