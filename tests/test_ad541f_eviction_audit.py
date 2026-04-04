"""Tests for AD-541f: Episode Eviction Audit Trail.

Append-only audit log for episode evictions across all eviction paths.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.eviction_audit import EvictionAuditLog, EvictionRecord
from probos.types import Episode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_episode(eid: str = "ep-001", agent_id: str = "agent-1", **kw) -> Episode:
    defaults = dict(
        id=eid,
        timestamp=1700000000.0,
        user_input=f"test input for {eid}",
        dag_summary={},
        outcomes=[],
        reflection=None,
        agent_ids=[agent_id],
        duration_ms=100.0,
        embedding=[],
        shapley_values={},
        trust_deltas=[],
        source="direct",
    )
    defaults.update(kw)
    return Episode(**defaults)


# ===========================================================================
# D1 — EvictionAuditLog Core (6 tests)
# ===========================================================================


class TestEvictionAuditLogCore:
    """Core audit log operations."""

    @pytest.mark.asyncio
    async def test_record_eviction_persists(self, tmp_path):
        """Record an eviction, query_by_episode returns it with matching fields."""
        log = EvictionAuditLog()
        await log.start(db_path=str(tmp_path / "audit.db"))
        try:
            await log.record_eviction(
                episode_id="ep-123",
                agent_id="agent-a",
                reason="capacity",
                process="_evict",
                details="test batch",
                content_hash="abc123",
                episode_timestamp=1700000000.0,
            )
            rec = await log.query_by_episode("ep-123")
            assert rec is not None
            assert rec.episode_id == "ep-123"
            assert rec.agent_id == "agent-a"
            assert rec.reason == "capacity"
            assert rec.process == "_evict"
            assert rec.details == "test batch"
            assert rec.content_hash == "abc123"
            assert rec.episode_timestamp == 1700000000.0
        finally:
            await log.stop()

    @pytest.mark.asyncio
    async def test_record_batch_eviction(self, tmp_path):
        """Record 5 evictions in one call, query_recent returns all 5."""
        log = EvictionAuditLog()
        await log.start(db_path=str(tmp_path / "audit.db"))
        try:
            records = [
                {"episode_id": f"ep-{i}", "agent_id": "agent-x"}
                for i in range(5)
            ]
            await log.record_batch_eviction(
                records, reason="capacity", process="_evict"
            )
            recent = await log.query_recent(limit=10)
            assert len(recent) == 5
        finally:
            await log.stop()

    @pytest.mark.asyncio
    async def test_query_by_agent(self, tmp_path):
        """Records for 2 agents, query_by_agent returns only matching."""
        log = EvictionAuditLog()
        await log.start(db_path=str(tmp_path / "audit.db"))
        try:
            await log.record_eviction(
                episode_id="ep-1", agent_id="alice", reason="capacity", process="_evict",
            )
            await log.record_eviction(
                episode_id="ep-2", agent_id="bob", reason="capacity", process="_evict",
            )
            await log.record_eviction(
                episode_id="ep-3", agent_id="alice", reason="capacity", process="_evict",
            )
            alice_recs = await log.query_by_agent("alice")
            assert len(alice_recs) == 2
            assert all(r.agent_id == "alice" for r in alice_recs)
        finally:
            await log.stop()

    @pytest.mark.asyncio
    async def test_query_by_episode_not_found(self, tmp_path):
        """Query non-existent episode_id -> returns None."""
        log = EvictionAuditLog()
        await log.start(db_path=str(tmp_path / "audit.db"))
        try:
            result = await log.query_by_episode("nonexistent")
            assert result is None
        finally:
            await log.stop()

    @pytest.mark.asyncio
    async def test_count_by_reason(self, tmp_path):
        """Record capacity + reset + force_update -> counts match each reason."""
        log = EvictionAuditLog()
        await log.start(db_path=str(tmp_path / "audit.db"))
        try:
            await log.record_eviction(
                episode_id="ep-1", agent_id="a", reason="capacity", process="_evict",
            )
            await log.record_eviction(
                episode_id="ep-2", agent_id="a", reason="capacity", process="_evict",
            )
            await log.record_eviction(
                episode_id="*", agent_id="*", reason="reset", process="probos_reset",
            )
            await log.record_eviction(
                episode_id="ep-3", agent_id="a", reason="force_update", process="_force_update",
            )
            counts = await log.count_by_reason()
            assert counts["capacity"] == 2
            assert counts["reset"] == 1
            assert counts["force_update"] == 1
        finally:
            await log.stop()

    def test_eviction_record_frozen(self):
        """EvictionRecord is frozen — cannot mutate."""
        rec = EvictionRecord(
            id="r1", episode_id="ep-1", agent_id="a",
            timestamp=1.0, reason="capacity", process="_evict",
        )
        with pytest.raises(FrozenInstanceError):
            rec.reason = "reset"  # type: ignore[misc]


# ===========================================================================
# D2 — EpisodicMemory _evict() Integration (3 tests)
# ===========================================================================


class TestEvictIntegration:
    """EpisodicMemory._evict() creates audit records."""

    @pytest.mark.asyncio
    async def test_evict_logs_to_audit(self, tmp_path):
        """Store episodes over budget, trigger eviction -> audit records created."""
        from probos.cognitive.episodic import EpisodicMemory

        audit = EvictionAuditLog()
        await audit.start(db_path=str(tmp_path / "audit.db"))
        try:
            em = EpisodicMemory(
                db_path=str(tmp_path / "ep.db"),
                max_episodes=3,
                eviction_audit=audit,
            )
            await em.start()
            try:
                # Store 5 episodes (budget=3, so 2 should be evicted after last store)
                for i in range(5):
                    ep = _make_episode(eid=f"ep-{i}", timestamp=float(i))
                    await em.store(ep)
                # Should have audit records for evicted episodes
                recent = await audit.query_recent()
                assert len(recent) >= 1
                assert all(r.reason == "capacity" for r in recent)
            finally:
                await em.stop()
        finally:
            await audit.stop()

    @pytest.mark.asyncio
    async def test_evict_succeeds_when_audit_fails(self, tmp_path):
        """Audit log raises exception -> eviction still succeeds."""
        from probos.cognitive.episodic import EpisodicMemory

        broken_audit = AsyncMock()
        broken_audit.record_batch_eviction = AsyncMock(side_effect=RuntimeError("DB error"))

        em = EpisodicMemory(
            db_path=str(tmp_path / "ep.db"),
            max_episodes=2,
            eviction_audit=broken_audit,
        )
        await em.start()
        try:
            for i in range(4):
                ep = _make_episode(eid=f"ep-{i}", timestamp=float(i))
                await em.store(ep)
            # Collection should not have grown beyond budget + excess
            count = em._collection.count()
            assert count <= 3  # max_episodes=2, at most 1 excess on last store
        finally:
            await em.stop()

    @pytest.mark.asyncio
    async def test_evict_captures_metadata(self, tmp_path):
        """Evicted episode audit record contains content_hash and episode_timestamp."""
        from probos.cognitive.episodic import EpisodicMemory

        audit = EvictionAuditLog()
        await audit.start(db_path=str(tmp_path / "audit.db"))
        try:
            em = EpisodicMemory(
                db_path=str(tmp_path / "ep.db"),
                max_episodes=2,
                eviction_audit=audit,
            )
            await em.start()
            try:
                for i in range(4):
                    ep = _make_episode(eid=f"ep-{i}", timestamp=1000.0 + i)
                    await em.store(ep)
                recent = await audit.query_recent()
                assert len(recent) >= 1
                # Check metadata was captured
                rec = recent[0]
                assert rec.episode_timestamp > 0
                assert rec.content_hash != ""
            finally:
                await em.stop()
        finally:
            await audit.stop()


# ===========================================================================
# D3 — _force_update() Integration (1 test)
# ===========================================================================


class TestForceUpdateIntegration:
    """_force_update() logs to audit."""

    @pytest.mark.asyncio
    async def test_force_update_logs_overwrite(self, tmp_path):
        """Call _force_update() -> audit record with reason='force_update'."""
        from probos.cognitive.episodic import EpisodicMemory

        audit = EvictionAuditLog()
        await audit.start(db_path=str(tmp_path / "audit.db"))
        try:
            em = EpisodicMemory(
                db_path=str(tmp_path / "ep.db"),
                eviction_audit=audit,
            )
            await em.start()
            try:
                ep = _make_episode(eid="ep-force")
                await em.store(ep)
                # Force update (migration path)
                import dataclasses
                updated_ep = dataclasses.replace(ep, user_input="updated content")
                em._force_update(updated_ep)
                # Give the fire-and-forget task a chance to complete
                await asyncio.sleep(0.1)
                rec = await audit.query_by_episode("ep-force")
                assert rec is not None
                assert rec.reason == "force_update"
                assert rec.process == "_force_update"
            finally:
                await em.stop()
        finally:
            await audit.stop()


# ===========================================================================
# D4 — KnowledgeStore Integration (2 tests)
# ===========================================================================


class TestKnowledgeStoreIntegration:
    """KnowledgeStore._evict_episodes() creates audit records."""

    @pytest.mark.asyncio
    async def test_knowledge_store_evict_logs(self, tmp_path):
        """Store episodes over budget -> audit records created."""
        from probos.config import KnowledgeConfig
        from probos.knowledge.store import KnowledgeStore

        audit = EvictionAuditLog()
        await audit.start(db_path=str(tmp_path / "audit.db"))
        try:
            kcfg = KnowledgeConfig(repo_path=str(tmp_path / "knowledge"), max_episodes=2)
            ks = KnowledgeStore(kcfg, eviction_audit=audit)
            await ks.initialize()

            # Create episode files manually
            ep_dir = tmp_path / "knowledge" / "episodes"
            ep_dir.mkdir(parents=True, exist_ok=True)
            for i in range(4):
                fp = ep_dir / f"ep-{i}.json"
                fp.write_text(json.dumps({
                    "agent_ids": ["agent-a"],
                    "timestamp": 1000.0 + i,
                }))

            await ks._evict_episodes()

            recent = await audit.query_recent()
            assert len(recent) >= 1
            assert all(r.reason == "capacity" for r in recent)
        finally:
            await audit.stop()

    @pytest.mark.asyncio
    async def test_knowledge_store_evict_survives_audit_failure(self, tmp_path):
        """Audit failure -> eviction still proceeds."""
        from probos.config import KnowledgeConfig
        from probos.knowledge.store import KnowledgeStore

        broken_audit = AsyncMock()
        broken_audit.record_batch_eviction = AsyncMock(side_effect=RuntimeError("fail"))

        kcfg = KnowledgeConfig(repo_path=str(tmp_path / "knowledge"), max_episodes=1)
        ks = KnowledgeStore(kcfg, eviction_audit=broken_audit)
        await ks.initialize()

        ep_dir = tmp_path / "knowledge" / "episodes"
        ep_dir.mkdir(parents=True, exist_ok=True)
        for i in range(3):
            fp = ep_dir / f"ep-{i}.json"
            fp.write_text(json.dumps({"agent_ids": ["a"], "timestamp": float(i)}))

        await ks._evict_episodes()

        # Files should still have been evicted despite audit failure
        remaining = list(ep_dir.glob("*.json"))
        assert len(remaining) <= 1


# ===========================================================================
# D5 — Reset Integration (1 test)
# ===========================================================================


class TestResetIntegration:
    """probos reset records wildcard eviction."""

    @pytest.mark.asyncio
    async def test_reset_logs_wildcard_eviction(self, tmp_path):
        """Simulate reset eviction recording -> record with episode_id='*', reason='reset'."""
        audit = EvictionAuditLog()
        await audit.start(db_path=str(tmp_path / "audit.db"))
        try:
            await audit.record_eviction(
                episode_id="*",
                agent_id="*",
                reason="reset",
                process="probos_reset",
                details="Tier 2 reset — total episodic memory wipe",
            )
            rec = await audit.query_by_episode("*")
            assert rec is not None
            assert rec.reason == "reset"
            assert rec.process == "probos_reset"
            assert "Tier 2" in rec.details
        finally:
            await audit.stop()


# ===========================================================================
# D6 — SIF Integration (2 tests)
# ===========================================================================


class TestSIFIntegration:
    """SIF check_eviction_health with audit log."""

    def _make_sif(self, eviction_audit=None):
        from probos.sif import StructuralIntegrityField
        sif = StructuralIntegrityField.__new__(StructuralIntegrityField)
        sif._trust_network = None
        sif._intent_bus = None
        sif._hebbian_router = None
        sif._spawner = None
        sif._pool_manager = None
        sif._episodic_memory = None
        sif._eviction_audit = eviction_audit
        sif._task = None
        sif._last_report = None
        sif._last_violation_details = ""
        sif._check_interval = 5.0
        return sif

    def test_sif_eviction_health_passes(self):
        """Empty audit log -> SIF passes."""
        audit = MagicMock()
        audit._cached_total = 0
        sif = self._make_sif(audit)
        result = sif.check_eviction_health()
        assert result.passed is True
        assert "total_evictions=0" in result.details

    def test_sif_eviction_health_reports_total(self):
        """Records in audit -> details contains 'total_evictions=N'."""
        audit = MagicMock()
        audit._cached_total = 42
        sif = self._make_sif(audit)
        result = sif.check_eviction_health()
        assert result.passed is True
        assert "total_evictions=42" in result.details


# ===========================================================================
# D7 — Config (1 test)
# ===========================================================================


class TestConfig:
    """eviction_audit_enabled config flag."""

    def test_eviction_audit_disabled(self):
        """eviction_audit_enabled=False -> EpisodicMemory has no audit."""
        from probos.cognitive.episodic import EpisodicMemory

        em = EpisodicMemory(db_path="/tmp/test.db", eviction_audit=None)
        assert em._eviction_audit is None
