"""Tests for GossipProtocol."""

import asyncio

import pytest

from probos.mesh.gossip import GossipProtocol
from probos.types import AgentState, GossipEntry


class TestGossipProtocol:
    def test_update_local(self):
        gp = GossipProtocol()
        entry = gp.update_local(
            agent_id="a1",
            agent_type="file_reader",
            state=AgentState.ACTIVE,
            pool="filesystem",
            capabilities=["read_file"],
            confidence=0.9,
        )
        assert gp.view_size == 1
        assert entry.agent_id == "a1"
        assert entry.state == AgentState.ACTIVE

    def test_receive_new_entry(self):
        gp = GossipProtocol()
        entry = GossipEntry(
            agent_id="a1",
            agent_type="file_reader",
            state=AgentState.ACTIVE,
        )
        updated = gp.receive(entry)
        assert updated
        assert gp.get_entry("a1") is entry

    def test_receive_older_entry_ignored(self):
        gp = GossipProtocol()
        from datetime import datetime, timezone, timedelta

        newer = GossipEntry(
            agent_id="a1",
            agent_type="file_reader",
            state=AgentState.ACTIVE,
            timestamp=datetime.now(timezone.utc),
        )
        older = GossipEntry(
            agent_id="a1",
            agent_type="file_reader",
            state=AgentState.DEGRADED,
            timestamp=datetime.now(timezone.utc) - timedelta(seconds=10),
        )
        gp.receive(newer)
        updated = gp.receive(older)
        assert not updated
        assert gp.get_entry("a1").state == AgentState.ACTIVE

    def test_receive_batch(self):
        gp = GossipProtocol()
        entries = [
            GossipEntry(agent_id=f"a{i}", agent_type="test", state=AgentState.ACTIVE)
            for i in range(5)
        ]
        count = gp.receive_batch(entries)
        assert count == 5
        assert gp.view_size == 5

    def test_remove(self):
        gp = GossipProtocol()
        gp.update_local("a1", "test", AgentState.ACTIVE)
        gp.remove("a1")
        assert gp.get_entry("a1") is None
        assert gp.view_size == 0

    def test_get_active_agents(self):
        gp = GossipProtocol()
        gp.update_local("a1", "test", AgentState.ACTIVE)
        gp.update_local("a2", "test", AgentState.DEGRADED)
        gp.update_local("a3", "test", AgentState.RECYCLING)
        active = gp.get_active_agents()
        assert len(active) == 2  # ACTIVE + DEGRADED

    def test_random_sample(self):
        gp = GossipProtocol()
        for i in range(10):
            gp.update_local(f"a{i}", "test", AgentState.ACTIVE)
        sample = gp.random_sample(3, exclude="a0")
        assert len(sample) == 3
        assert all(e.agent_id != "a0" for e in sample)

    def test_random_sample_excludes(self):
        gp = GossipProtocol()
        gp.update_local("only", "test", AgentState.ACTIVE)
        sample = gp.random_sample(5, exclude="only")
        assert len(sample) == 0

    @pytest.mark.asyncio
    async def test_gossip_loop_runs(self):
        received: list[dict] = []
        gp = GossipProtocol(interval_seconds=0.1)
        gp.add_listener(lambda view: received.append(dict(view)))

        gp.update_local("a1", "test", AgentState.ACTIVE)
        await gp.start()
        await asyncio.sleep(0.4)
        await gp.stop()

        assert len(received) >= 2
