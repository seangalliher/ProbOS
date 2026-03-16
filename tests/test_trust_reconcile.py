"""Tests for TrustNetwork.reconcile() and post-boot trust cleanup (AD-280)."""

from __future__ import annotations

import pytest

from probos.consensus.trust import TrustNetwork, TrustRecord
from probos.cognitive.llm_client import MockLLMClient
from probos.runtime import ProbOSRuntime


class TestTrustReconcile:
    @pytest.fixture
    def trust_net(self, tmp_path):
        return TrustNetwork(db_path=str(tmp_path / "trust.db"))

    async def test_removes_stale_entries(self, trust_net):
        """reconcile() removes entries not in the active set."""
        trust_net._records = {
            "agent-a": TrustRecord(agent_id="agent-a"),
            "agent-b": TrustRecord(agent_id="agent-b"),
            "agent-c": TrustRecord(agent_id="agent-c"),
        }
        removed = trust_net.reconcile({"agent-a"})
        assert removed == 2
        assert "agent-a" in trust_net._records
        assert "agent-b" not in trust_net._records
        assert "agent-c" not in trust_net._records

    async def test_preserves_active_entries(self, trust_net):
        """reconcile() keeps all entries when all are active."""
        trust_net._records = {
            "agent-a": TrustRecord(agent_id="agent-a"),
            "agent-b": TrustRecord(agent_id="agent-b"),
        }
        removed = trust_net.reconcile({"agent-a", "agent-b"})
        assert removed == 0
        assert len(trust_net._records) == 2

    async def test_noop_when_empty(self, trust_net):
        """reconcile() is a no-op on empty trust network."""
        removed = trust_net.reconcile({"agent-a"})
        assert removed == 0

    async def test_returns_correct_count(self, trust_net):
        """reconcile() returns accurate count of removed entries."""
        trust_net._records = {
            f"agent-{i}": TrustRecord(agent_id=f"agent-{i}")
            for i in range(10)
        }
        active = {f"agent-{i}" for i in range(3)}
        removed = trust_net.reconcile(active)
        assert removed == 7
        assert trust_net.agent_count == 3


class TestTrustReconcileIntegration:
    async def test_trust_matches_registry_after_boot(self, tmp_path):
        """After start(), trust agent_count == registry.count."""
        llm = MockLLMClient()
        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=llm)
        await rt.start()
        try:
            assert rt.trust_network.agent_count == rt.registry.count
        finally:
            await rt.stop()
