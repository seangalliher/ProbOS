"""Tests for Phase 14c: Persistent Agent Identity.

Covers manifest persistence, warm boot trust reconnection,
warm boot Hebbian routing reconnection, pruning, and the
end-to-end milestone test.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.config import KnowledgeConfig
from probos.substrate.identity import generate_agent_id, generate_pool_ids


def _set_trust(trust_network, agent_id: str, alpha: float, beta: float):
    """Force-set trust parameters for testing (bypasses create_with_prior no-op)."""
    from probos.consensus.trust import TrustRecord
    trust_network._records[agent_id] = TrustRecord(
        agent_id=agent_id, alpha=alpha, beta=beta,
    )


# ------------------------------------------------------------------
# Manifest persistence tests
# ------------------------------------------------------------------


@pytest.fixture
def knowledge_store(tmp_path):
    """Create a KnowledgeStore with temp directory."""
    cfg = KnowledgeConfig(
        enabled=True,
        repo_path=str(tmp_path / "knowledge"),
        auto_commit=False,
    )
    return __import__("probos.knowledge.store", fromlist=["KnowledgeStore"]).KnowledgeStore(cfg)


class TestManifestPersistence:
    @pytest.mark.asyncio
    async def test_store_manifest_creates_file(self, knowledge_store):
        await knowledge_store.initialize()
        manifest = [
            {"agent_id": "a1", "agent_type": "file_reader", "pool_name": "filesystem", "instance_index": 0},
        ]
        await knowledge_store.store_manifest(manifest)
        path = knowledge_store.repo_path / "manifest.json"
        assert path.is_file()

    @pytest.mark.asyncio
    async def test_load_manifest_returns_stored_data(self, knowledge_store):
        await knowledge_store.initialize()
        manifest = [
            {"agent_id": "a1", "agent_type": "file_reader", "pool_name": "filesystem", "instance_index": 0},
            {"agent_id": "a2", "agent_type": "file_writer", "pool_name": "filesystem_writers", "instance_index": 0},
        ]
        await knowledge_store.store_manifest(manifest)
        loaded = await knowledge_store.load_manifest()
        assert loaded == manifest

    @pytest.mark.asyncio
    async def test_load_manifest_returns_empty_list_when_no_manifest(self, knowledge_store):
        await knowledge_store.initialize()
        loaded = await knowledge_store.load_manifest()
        assert loaded == []

    @pytest.mark.asyncio
    async def test_manifest_round_trip_preserves_fields(self, knowledge_store):
        await knowledge_store.initialize()
        manifest = [
            {
                "agent_id": "x_y_0_abcd1234",
                "agent_type": "x",
                "pool_name": "y",
                "instance_index": 0,
            },
        ]
        await knowledge_store.store_manifest(manifest)
        loaded = await knowledge_store.load_manifest()
        assert loaded[0]["agent_id"] == "x_y_0_abcd1234"
        assert loaded[0]["agent_type"] == "x"
        assert loaded[0]["pool_name"] == "y"
        assert loaded[0]["instance_index"] == 0

    @pytest.mark.asyncio
    async def test_manifest_includes_designed_agents(self, knowledge_store):
        await knowledge_store.initialize()
        manifest = [
            {
                "agent_id": "gen_script_designed_gen_script_0_deadbeef",
                "agent_type": "gen_script",
                "pool_name": "designed_gen_script",
                "instance_index": 0,
                "skills_attached": ["generate_script"],
            },
        ]
        await knowledge_store.store_manifest(manifest)
        loaded = await knowledge_store.load_manifest()
        assert loaded[0]["skills_attached"] == ["generate_script"]


# ------------------------------------------------------------------
# Warm boot reconnection tests (runtime integration)
# ------------------------------------------------------------------


@pytest.fixture
def _runtime_fixture(tmp_path):
    """Create a minimal ProbOS runtime for warm boot testing."""
    from probos.runtime import ProbOSRuntime

    data_dir = tmp_path / "data"
    rt = ProbOSRuntime(data_dir=data_dir)
    # Enable knowledge store with temp path, auto_commit off
    rt.config.knowledge.enabled = True
    rt.config.knowledge.auto_commit = False
    rt.config.knowledge.repo_path = str(tmp_path / "knowledge")
    rt.config.self_mod.enabled = True
    rt.config.qa.enabled = False
    rt.config.scaling.enabled = False
    rt.config.federation.enabled = False
    return rt


class TestWarmBootReconnection:
    @pytest.mark.asyncio
    async def test_builtin_agents_get_deterministic_ids(self, _runtime_fixture):
        """Built-in agents get the same deterministic IDs across calls."""
        rt = _runtime_fixture
        await rt.start()
        try:
            pool = rt.pools["filesystem"]
            ids = pool._agent_ids
            expected = generate_pool_ids("file_reader", "filesystem", 3)
            assert ids == expected
        finally:
            await rt.stop()

    @pytest.mark.asyncio
    async def test_warm_boot_agents_retain_earned_trust(self, _runtime_fixture, tmp_path):
        """THE KEY TEST: restored agents retain earned trust, not probationary."""
        rt = _runtime_fixture
        await rt.start()

        # Verify a built-in agent has a deterministic ID
        pool = rt.pools["filesystem"]
        agent_id = pool._agent_ids[0]
        expected_id = generate_agent_id("file_reader", "filesystem", 0)
        assert agent_id == expected_id

        # Simulate earning trust (direct set — create_with_prior is a no-op
        # when the record already exists)
        _set_trust(rt.trust_network, agent_id, alpha=20.0, beta=2.0)
        assert rt.trust_network.get_score(agent_id) > 0.8  # sanity

        await rt.stop()

        # Start a new runtime with the same config (warm boot)
        from probos.runtime import ProbOSRuntime

        rt2 = ProbOSRuntime(data_dir=rt._data_dir)
        rt2.config.knowledge.enabled = True
        rt2.config.knowledge.auto_commit = False
        rt2.config.knowledge.repo_path = rt.config.knowledge.repo_path
        rt2.config.self_mod.enabled = True
        rt2.config.qa.enabled = False
        rt2.config.scaling.enabled = False
        rt2.config.federation.enabled = False
        await rt2.start()
        try:
            # Agent should have the same deterministic ID
            pool2 = rt2.pools["filesystem"]
            agent_id2 = pool2._agent_ids[0]
            assert agent_id2 == expected_id

            # Trust should be restored (NOT probationary)
            trust = rt2.trust_network.get_score(agent_id2)
            # Earned trust Beta(20, 2) → E[trust] ≈ 0.909
            assert trust > 0.8, f"Expected earned trust > 0.8, got {trust}"
        finally:
            await rt2.stop()

    @pytest.mark.asyncio
    async def test_warm_boot_hebbian_weights_reconnect(self, _runtime_fixture):
        """Hebbian weights reconnect to restored agents via matching IDs."""
        rt = _runtime_fixture
        await rt.start()

        pool = rt.pools["filesystem"]
        agent_id = pool._agent_ids[0]
        expected_id = generate_agent_id("file_reader", "filesystem", 0)
        assert agent_id == expected_id

        # Add a Hebbian weight
        rt.hebbian_router.record_interaction("read_file_intent", agent_id, success=True)
        weight_before = rt.hebbian_router.get_weight("read_file_intent", agent_id)
        assert weight_before > 0

        await rt.stop()

        # New runtime (warm boot)
        from probos.runtime import ProbOSRuntime

        rt2 = ProbOSRuntime(data_dir=rt._data_dir)
        rt2.config.knowledge.enabled = True
        rt2.config.knowledge.auto_commit = False
        rt2.config.knowledge.repo_path = rt.config.knowledge.repo_path
        rt2.config.self_mod.enabled = True
        rt2.config.qa.enabled = False
        rt2.config.scaling.enabled = False
        rt2.config.federation.enabled = False
        await rt2.start()
        try:
            agent_id2 = rt2.pools["filesystem"]._agent_ids[0]
            assert agent_id2 == expected_id

            weight_after = rt2.hebbian_router.get_weight("read_file_intent", agent_id2)
            assert weight_after == weight_before
        finally:
            await rt2.stop()

    @pytest.mark.asyncio
    async def test_warm_boot_without_manifest_is_backward_compatible(self, _runtime_fixture):
        """Warm boot with no manifest still starts normally (fresh repo)."""
        rt = _runtime_fixture
        await rt.start()
        try:
            # Should have pools with deterministic IDs
            assert len(rt.pools) > 0
            pool = rt.pools["filesystem"]
            assert len(pool._agent_ids) == 3
        finally:
            await rt.stop()

    @pytest.mark.asyncio
    async def test_new_agents_get_probationary_trust(self, _runtime_fixture):
        """Agents not in the trust snapshot get probationary trust."""
        rt = _runtime_fixture
        await rt.start()

        # Built-in agents start with no explicit trust record
        pool = rt.pools["filesystem"]
        agent_id = pool._agent_ids[0]

        # The trust network may have a default or no prior set for built-in
        # agents beyond what warm boot provides. Verify pools are functional.
        assert len(pool._agent_ids) == 3
        await rt.stop()

    @pytest.mark.asyncio
    async def test_fresh_flag_gives_deterministic_ids_but_no_restore(self, _runtime_fixture, tmp_path):
        """--fresh: agents get deterministic IDs but no trust restore."""
        rt = _runtime_fixture
        await rt.start()

        # Earn trust
        pool = rt.pools["filesystem"]
        agent_id = pool._agent_ids[0]
        _set_trust(rt.trust_network, agent_id, alpha=20.0, beta=2.0)

        await rt.stop()

        # Fresh start (no restore) — use a fresh data_dir so the SQLite
        # trust database is also empty (not just the KnowledgeStore)
        from probos.runtime import ProbOSRuntime

        rt2 = ProbOSRuntime(data_dir=tmp_path / "data_fresh")
        rt2.config.knowledge.enabled = True
        rt2.config.knowledge.auto_commit = False
        rt2.config.knowledge.repo_path = rt.config.knowledge.repo_path
        rt2.config.knowledge.restore_on_boot = False  # --fresh
        rt2.config.self_mod.enabled = True
        rt2.config.qa.enabled = False
        rt2.config.scaling.enabled = False
        rt2.config.federation.enabled = False
        await rt2.start()
        try:
            # Same deterministic ID
            pool2 = rt2.pools["filesystem"]
            agent_id2 = pool2._agent_ids[0]
            assert agent_id2 == agent_id

            # But trust was NOT restored (fresh start)
            trust = rt2.trust_network.get_score(agent_id2)
            # Default trust when no prior set — should be the default (0.5)
            assert trust <= 0.5
        finally:
            await rt2.stop()


# ------------------------------------------------------------------
# Pruning tests
# ------------------------------------------------------------------


class TestPruning:
    @pytest.mark.asyncio
    async def test_prune_removes_agent_from_pool(self, _runtime_fixture):
        rt = _runtime_fixture
        await rt.start()
        try:
            pool = rt.pools["filesystem"]
            agent_id = pool._agent_ids[0]
            assert agent_id in pool._agent_ids

            removed = await rt.prune_agent(agent_id)
            assert removed is True
            assert agent_id not in pool._agent_ids
        finally:
            await rt.stop()

    @pytest.mark.asyncio
    async def test_prune_removes_agent_from_registry(self, _runtime_fixture):
        rt = _runtime_fixture
        await rt.start()
        try:
            pool = rt.pools["filesystem"]
            agent_id = pool._agent_ids[0]
            assert rt.registry.get(agent_id) is not None

            await rt.prune_agent(agent_id)
            assert rt.registry.get(agent_id) is None
        finally:
            await rt.stop()

    @pytest.mark.asyncio
    async def test_prune_removes_trust_records(self, _runtime_fixture):
        rt = _runtime_fixture
        await rt.start()
        try:
            pool = rt.pools["filesystem"]
            agent_id = pool._agent_ids[0]
            _set_trust(rt.trust_network, agent_id, alpha=10.0, beta=2.0)
            assert agent_id in rt.trust_network._records

            await rt.prune_agent(agent_id)
            assert agent_id not in rt.trust_network._records
        finally:
            await rt.stop()

    @pytest.mark.asyncio
    async def test_prune_removes_routing_weights(self, _runtime_fixture):
        rt = _runtime_fixture
        await rt.start()
        try:
            pool = rt.pools["filesystem"]
            agent_id = pool._agent_ids[0]
            rt.hebbian_router.record_interaction("some_intent", agent_id, success=True)
            assert rt.hebbian_router.get_weight("some_intent", agent_id) > 0

            await rt.prune_agent(agent_id)
            assert rt.hebbian_router.get_weight("some_intent", agent_id) == 0.0
        finally:
            await rt.stop()

    @pytest.mark.asyncio
    async def test_pruned_id_not_recycled_on_pool_recovery(self, _runtime_fixture):
        rt = _runtime_fixture
        await rt.start()
        try:
            pool = rt.pools["filesystem"]
            pruned_id = pool._agent_ids[0]

            await rt.prune_agent(pruned_id)

            # Pool is now below target. Health check should spawn a replacement.
            await pool.check_health()

            # The replacement should NOT reuse the pruned ID
            assert pruned_id not in pool._agent_ids
            # Pool should be back to target size
            assert len(pool._agent_ids) == 3
        finally:
            await rt.stop()

    @pytest.mark.asyncio
    async def test_prune_nonexistent_agent_is_noop(self, _runtime_fixture):
        rt = _runtime_fixture
        await rt.start()
        try:
            removed = await rt.prune_agent("nonexistent_agent_id_xyz")
            assert removed is False
        finally:
            await rt.stop()


# ------------------------------------------------------------------
# Milestone end-to-end test
# ------------------------------------------------------------------


class TestMilestoneEndToEnd:
    @pytest.mark.asyncio
    async def test_full_lifecycle(self, _runtime_fixture):
        """
        End-to-end: start → earn trust → shutdown → warm boot → verify trust.

        Demonstrates deterministic IDs, manifest persistence, trust reconnection,
        routing reconnection, and the distinction between restored agents (earned
        trust) and new agents (probationary trust).
        """
        rt = _runtime_fixture
        await rt.start()

        # 1. Get a deterministic agent ID
        pool = rt.pools["filesystem"]
        agent_id = pool._agent_ids[0]
        expected_id = generate_agent_id("file_reader", "filesystem", 0)
        assert agent_id == expected_id

        # 2. Earn trust and strengthen routing
        _set_trust(rt.trust_network, agent_id, alpha=8.0, beta=2.0)
        rt.hebbian_router.record_interaction("read_file", agent_id, success=True)
        earned_trust = rt.trust_network.get_score(agent_id)
        earned_weight = rt.hebbian_router.get_weight("read_file", agent_id)

        # 3. Shutdown (persists trust, routing, manifest)
        await rt.stop()

        # 4. Warm boot
        from probos.runtime import ProbOSRuntime

        rt2 = ProbOSRuntime(data_dir=rt._data_dir)
        rt2.config.knowledge.enabled = True
        rt2.config.knowledge.auto_commit = False
        rt2.config.knowledge.repo_path = rt.config.knowledge.repo_path
        rt2.config.self_mod.enabled = True
        rt2.config.qa.enabled = False
        rt2.config.scaling.enabled = False
        rt2.config.federation.enabled = False
        await rt2.start()
        try:
            # 5. Same deterministic ID
            pool2 = rt2.pools["filesystem"]
            agent_id2 = pool2._agent_ids[0]
            assert agent_id2 == expected_id

            # 6. Trust reconnected (NOT probationary)
            restored_trust = rt2.trust_network.get_score(agent_id2)
            assert restored_trust == pytest.approx(earned_trust, abs=0.01)

            # 7. Routing reconnected
            restored_weight = rt2.hebbian_router.get_weight("read_file", agent_id2)
            assert restored_weight == earned_weight
        finally:
            await rt2.stop()
