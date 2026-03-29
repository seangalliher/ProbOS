"""Tests for BF-071: Database retention — EventLog and CognitiveJournal pruning."""

import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from probos.substrate.event_log import EventLog
from probos.cognitive.journal import CognitiveJournal
from probos.config import EventLogConfig, CognitiveJournalConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def event_log(tmp_path):
    el = EventLog(db_path=str(tmp_path / "events.db"))
    await el.start()
    yield el
    await el.stop()


@pytest_asyncio.fixture
async def journal(tmp_path):
    j = CognitiveJournal(db_path=str(tmp_path / "journal.db"))
    await j.start()
    yield j
    await j.stop()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _insert_event(el: EventLog, timestamp_iso: str, category: str = "test") -> None:
    """Insert an event with an explicit timestamp (bypass log() which uses now())."""
    await el._db.execute(
        "INSERT INTO events (timestamp, category, event) VALUES (?, ?, ?)",
        (timestamp_iso, category, "test_event"),
    )
    await el._db.commit()


async def _insert_journal_entry(j: CognitiveJournal, ts: float, agent_id: str = "agent-1") -> None:
    """Insert a journal entry with an explicit timestamp."""
    entry_id = str(uuid.uuid4())
    await j._db.execute(
        "INSERT INTO journal (id, timestamp, agent_id) VALUES (?, ?, ?)",
        (entry_id, ts, agent_id),
    )
    await j._db.commit()


# ===========================================================================
# EventLog.prune() tests
# ===========================================================================

class TestEventLogPrune:

    @pytest.mark.asyncio
    async def test_age_based_pruning(self, event_log):
        """Old events are deleted, recent events kept."""
        now = datetime.now(timezone.utc)
        old = (now - timedelta(days=10)).isoformat()
        recent = now.isoformat()

        await _insert_event(event_log, old)
        await _insert_event(event_log, old)
        await _insert_event(event_log, recent)

        deleted = await event_log.prune(retention_days=7, max_rows=0)
        assert deleted == 2
        assert await event_log.count() == 1

    @pytest.mark.asyncio
    async def test_max_rows_cap(self, event_log):
        """Excess rows are removed, oldest first."""
        now = datetime.now(timezone.utc)
        for i in range(10):
            ts = (now - timedelta(seconds=10 - i)).isoformat()
            await _insert_event(event_log, ts)

        deleted = await event_log.prune(retention_days=0, max_rows=5)
        assert deleted == 5
        assert await event_log.count() == 5

    @pytest.mark.asyncio
    async def test_noop_within_limits(self, event_log):
        """No deletions when everything is within limits."""
        now = datetime.now(timezone.utc).isoformat()
        await _insert_event(event_log, now)
        await _insert_event(event_log, now)

        deleted = await event_log.prune(retention_days=7, max_rows=100)
        assert deleted == 0
        assert await event_log.count() == 2

    @pytest.mark.asyncio
    async def test_retention_days_zero_skips_age(self, event_log):
        """retention_days=0 means keep forever (no age pruning)."""
        old = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
        await _insert_event(event_log, old)

        deleted = await event_log.prune(retention_days=0, max_rows=0)
        assert deleted == 0
        assert await event_log.count() == 1

    @pytest.mark.asyncio
    async def test_max_rows_zero_skips_cap(self, event_log):
        """max_rows=0 means no cap."""
        now = datetime.now(timezone.utc).isoformat()
        for _ in range(20):
            await _insert_event(event_log, now)

        deleted = await event_log.prune(retention_days=0, max_rows=0)
        assert deleted == 0
        assert await event_log.count() == 20

    @pytest.mark.asyncio
    async def test_prune_no_db(self):
        """prune() returns 0 when db is None."""
        el = EventLog(db_path="/nonexistent/path")
        assert await el.prune() == 0


# ===========================================================================
# EventLog.wipe() tests
# ===========================================================================

class TestEventLogWipe:

    @pytest.mark.asyncio
    async def test_wipe_clears_all(self, event_log):
        """wipe() removes all events."""
        now = datetime.now(timezone.utc).isoformat()
        for _ in range(5):
            await _insert_event(event_log, now)
        assert await event_log.count() == 5

        await event_log.wipe()
        assert await event_log.count() == 0

    @pytest.mark.asyncio
    async def test_count_all(self, event_log):
        """count_all() returns total event count."""
        now = datetime.now(timezone.utc).isoformat()
        await _insert_event(event_log, now)
        await _insert_event(event_log, now)
        assert await event_log.count_all() == 2


# ===========================================================================
# CognitiveJournal.prune() tests
# ===========================================================================

class TestJournalPrune:

    @pytest.mark.asyncio
    async def test_age_based_pruning(self, journal):
        """Old entries are deleted, recent entries kept."""
        now = time.time()
        old = now - (15 * 86400)  # 15 days ago

        await _insert_journal_entry(journal, old)
        await _insert_journal_entry(journal, old)
        await _insert_journal_entry(journal, now)

        deleted = await journal.prune(retention_days=14, max_rows=0)
        assert deleted == 2
        stats = await journal.get_stats()
        assert stats["total_entries"] == 1

    @pytest.mark.asyncio
    async def test_max_rows_cap(self, journal):
        """Excess rows are removed, oldest first."""
        now = time.time()
        for i in range(10):
            await _insert_journal_entry(journal, now - (10 - i))

        deleted = await journal.prune(retention_days=0, max_rows=5)
        assert deleted == 5
        stats = await journal.get_stats()
        assert stats["total_entries"] == 5

    @pytest.mark.asyncio
    async def test_noop_within_limits(self, journal):
        """No deletions when everything is within limits."""
        now = time.time()
        await _insert_journal_entry(journal, now)
        await _insert_journal_entry(journal, now)

        deleted = await journal.prune(retention_days=14, max_rows=1000)
        assert deleted == 0
        stats = await journal.get_stats()
        assert stats["total_entries"] == 2

    @pytest.mark.asyncio
    async def test_retention_days_zero_skips_age(self, journal):
        """retention_days=0 means keep forever."""
        old = time.time() - (365 * 86400)
        await _insert_journal_entry(journal, old)

        deleted = await journal.prune(retention_days=0, max_rows=0)
        assert deleted == 0

    @pytest.mark.asyncio
    async def test_max_rows_zero_skips_cap(self, journal):
        """max_rows=0 means no cap."""
        now = time.time()
        for _ in range(20):
            await _insert_journal_entry(journal, now)

        deleted = await journal.prune(retention_days=0, max_rows=0)
        assert deleted == 0

    @pytest.mark.asyncio
    async def test_prune_no_db(self):
        """prune() returns 0 when db is None."""
        j = CognitiveJournal(db_path=None)
        assert await j.prune() == 0


# ===========================================================================
# Config defaults
# ===========================================================================

class TestConfigDefaults:

    def test_event_log_config_defaults(self):
        cfg = EventLogConfig()
        assert cfg.retention_days == 7
        assert cfg.max_rows == 100_000
        assert cfg.prune_interval_seconds == 3600.0

    def test_journal_config_defaults(self):
        cfg = CognitiveJournalConfig()
        assert cfg.enabled is True
        assert cfg.retention_days == 14
        assert cfg.max_rows == 500_000
        assert cfg.prune_interval_seconds == 3600.0
