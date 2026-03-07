"""Tests for EventLog."""

import pytest

from probos.substrate.event_log import EventLog


class TestEventLog:
    @pytest.mark.asyncio
    async def test_log_and_query(self, tmp_path):
        log = EventLog(db_path=tmp_path / "test_events.db")
        await log.start()

        await log.log(
            category="lifecycle",
            event="agent_started",
            agent_id="a1",
            agent_type="file_reader",
            pool="filesystem",
            detail="spawned",
        )
        await log.log(category="system", event="boot")

        # Query all
        events = await log.query(limit=10)
        assert len(events) == 2

        # Query by category
        lifecycle = await log.query(category="lifecycle")
        assert len(lifecycle) == 1
        assert lifecycle[0]["event"] == "agent_started"
        assert lifecycle[0]["agent_id"] == "a1"

        # Query by agent
        agent_events = await log.query(agent_id="a1")
        assert len(agent_events) == 1

        await log.stop()

    @pytest.mark.asyncio
    async def test_count(self, tmp_path):
        log = EventLog(db_path=tmp_path / "test_events.db")
        await log.start()

        for i in range(5):
            await log.log(category="lifecycle", event=f"event_{i}")
        await log.log(category="system", event="boot")

        assert await log.count() == 6
        assert await log.count("lifecycle") == 5
        assert await log.count("system") == 1

        await log.stop()

    @pytest.mark.asyncio
    async def test_append_only(self, tmp_path):
        """Events persist across close/reopen."""
        db_path = tmp_path / "test_events.db"

        log = EventLog(db_path=db_path)
        await log.start()
        await log.log(category="system", event="first")
        await log.stop()

        log2 = EventLog(db_path=db_path)
        await log2.start()
        await log2.log(category="system", event="second")
        assert await log2.count() == 2
        await log2.stop()

    @pytest.mark.asyncio
    async def test_log_without_start_is_noop(self):
        log = EventLog(db_path="/dev/null/fake.db")
        # Should not raise
        await log.log(category="test", event="ignored")
        assert await log.count() == 0
