"""Tests for AD-541e: Episode Content Hashing.

Cryptographic content hash for episodic memory tamper detection.
"""

from __future__ import annotations

import dataclasses
import logging
from unittest.mock import MagicMock, patch

import pytest

from probos.cognitive.episodic import (
    EpisodicMemory,
    compute_episode_hash,
    _verify_episode_hash,
)
from probos.types import Episode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_episode(**overrides) -> Episode:
    """Create a test episode with sensible defaults."""
    defaults = dict(
        id="ep-test-001",
        timestamp=1700000000.0,
        user_input="run diagnostics",
        dag_summary={"nodes": ["a", "b"]},
        outcomes=[{"intent": "diagnostics", "result": "ok"}],
        reflection="went well",
        agent_ids=["agent-uuid-1"],
        duration_ms=150.0,
        embedding=[],
        shapley_values={"agent-uuid-1": 0.8},
        trust_deltas=[{"agent": "agent-uuid-1", "delta": 0.01}],
        source="direct",
    )
    defaults.update(overrides)
    return Episode(**defaults)


# ===========================================================================
# D1 — Hash Utility (6 tests)
# ===========================================================================


class TestHashUtility:
    """compute_episode_hash determinism, field coverage, and format."""

    def test_hash_deterministic(self):
        """Same Episode -> same hash, every time."""
        ep = _make_episode()
        h1 = compute_episode_hash(ep)
        h2 = compute_episode_hash(ep)
        assert h1 == h2

    def test_hash_changes_on_content_change(self):
        """Different user_input -> different hash."""
        ep1 = _make_episode()
        ep2 = dataclasses.replace(ep1, user_input="different input")
        assert compute_episode_hash(ep1) != compute_episode_hash(ep2)

    def test_hash_excludes_id(self):
        """Two episodes with same content but different IDs -> same hash."""
        ep1 = _make_episode(id="id-aaa")
        ep2 = _make_episode(id="id-bbb")
        assert compute_episode_hash(ep1) == compute_episode_hash(ep2)

    def test_hash_excludes_embedding(self):
        """Two episodes with same content but different embeddings -> same hash."""
        ep1 = _make_episode(embedding=[0.1, 0.2])
        ep2 = _make_episode(embedding=[0.9, 0.8])
        assert compute_episode_hash(ep1) == compute_episode_hash(ep2)

    def test_hash_includes_all_content_fields(self):
        """Changing each included field produces a different hash."""
        base = _make_episode()
        base_hash = compute_episode_hash(base)

        field_changes = {
            "timestamp": 9999999999.0,
            "user_input": "something else",
            "dag_summary": {"nodes": ["x"]},
            "outcomes": [{"intent": "other"}],
            "reflection": "different reflection",
            "agent_ids": ["other-agent"],
            "duration_ms": 9999.0,
            "shapley_values": {"other": 0.1},
            "trust_deltas": [{"agent": "x", "delta": -0.5}],
            "source": "dream_consolidation",
        }

        for field_name, new_value in field_changes.items():
            modified = dataclasses.replace(base, **{field_name: new_value})
            modified_hash = compute_episode_hash(modified)
            assert modified_hash != base_hash, (
                f"Changing '{field_name}' did not change the hash"
            )

    def test_hash_is_sha256_hex(self):
        """Hash is a 64-character hex string (SHA-256)."""
        h = compute_episode_hash(_make_episode())
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


# ===========================================================================
# D2 — Store-Time Hashing (2 tests)
# ===========================================================================


class TestStoreTimeHashing:
    """_episode_to_metadata includes content_hash."""

    def test_metadata_includes_content_hash(self):
        """Metadata dict contains content_hash key."""
        ep = _make_episode()
        meta = EpisodicMemory._episode_to_metadata(ep)
        assert "content_hash" in meta
        assert isinstance(meta["content_hash"], str)
        assert len(meta["content_hash"]) == 64

    def test_stored_hash_matches_recomputed(self):
        """Hash in metadata matches recomputation from episode."""
        ep = _make_episode()
        meta = EpisodicMemory._episode_to_metadata(ep)
        recomputed = compute_episode_hash(ep)
        assert meta["content_hash"] == recomputed


# ===========================================================================
# D3 — Recall Verification (5 tests)
# ===========================================================================


class TestRecallVerification:
    """_verify_episode_hash returns, logging, and recall behavior."""

    def test_verify_hash_match_returns_true(self):
        """Correct hash -> True."""
        ep = _make_episode()
        correct_hash = compute_episode_hash(ep)
        assert _verify_episode_hash(ep, correct_hash) is True

    def test_verify_hash_mismatch_returns_false(self):
        """Wrong hash -> False."""
        ep = _make_episode()
        assert _verify_episode_hash(ep, "bad" * 16) is False

    def test_verify_empty_hash_returns_true(self):
        """Empty/missing hash (legacy episode) -> True."""
        ep = _make_episode()
        assert _verify_episode_hash(ep, "") is True
        assert _verify_episode_hash(ep, None) is True  # type: ignore[arg-type]

    def test_recall_logs_warning_on_mismatch(self, caplog):
        """Hash mismatch triggers a WARNING log."""
        ep = _make_episode()
        with caplog.at_level(logging.WARNING, logger="probos.cognitive.episodic"):
            _verify_episode_hash(ep, "deadbeef" * 8)
        assert any("hash mismatch" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_recall_still_returns_tampered_episode(self, tmp_path):
        """Even on hash mismatch, the episode IS returned (degrade, not deny)."""
        em = EpisodicMemory(db_path=str(tmp_path / "ep.db"), verify_content_hash=True)
        try:
            await em.start()
        except Exception as exc:
            if "INVALID_PROTOBUF" in str(exc) or "onnx" in str(exc).lower() or "No such file" in str(exc):
                pytest.skip(f"ChromaDB ONNX model unavailable: {exc}")
            raise
        try:
            # Store an episode
            ep = _make_episode(agent_ids=["agent-1"])
            try:
                await em.store(ep)
            except Exception as exc:
                if "INVALID_PROTOBUF" in str(exc) or "onnx" in str(exc).lower() or "No such file" in str(exc):
                    pytest.skip(f"ChromaDB ONNX model unavailable: {exc}")
                raise

            # Tamper with the stored hash in ChromaDB metadata
            result = em._collection.get(ids=[ep.id], include=["metadatas", "documents"])
            meta = result["metadatas"][0]
            meta["content_hash"] = "tampered" + "0" * 56
            em._collection.update(ids=[ep.id], metadatas=[meta])

            # Recall should still return the episode
            recalled = await em.recall_for_agent("agent-1", "diagnostics", k=5)
            assert len(recalled) >= 1
            assert any(r.id == ep.id for r in recalled)
        finally:
            await em.stop()


# ===========================================================================
# D4 — SIF Integration (3 tests)
# ===========================================================================


class TestSIFIntegration:
    """SIF check_memory_integrity with content hashes."""

    def _make_sif(self, episodic_memory=None):
        from probos.sif import StructuralIntegrityField
        sif = StructuralIntegrityField.__new__(StructuralIntegrityField)
        sif._episodic_memory = episodic_memory
        sif._trust_network = None
        sif._hebbian_router = None
        sif._cognitive_journal = None
        sif._knowledge_store = None
        sif._records_store = None
        return sif

    def test_sif_passes_with_valid_hash(self):
        """Episode with matching hash -> SIF passes."""
        ep = _make_episode()
        meta = EpisodicMemory._episode_to_metadata(ep)

        collection = MagicMock()
        collection.count.return_value = 1
        collection.get.return_value = {
            "ids": [ep.id],
            "metadatas": [meta],
            "documents": [ep.user_input],
        }

        em = MagicMock()
        em._collection = collection

        sif = self._make_sif(em)
        result = sif.check_memory_integrity()
        assert result.passed is True

    def test_sif_detects_hash_mismatch(self):
        """Episode with mismatched hash -> SIF reports violation."""
        ep = _make_episode()
        meta = EpisodicMemory._episode_to_metadata(ep)
        meta["content_hash"] = "wrong" * 12 + "beef"  # 52 chars — intentionally wrong

        collection = MagicMock()
        collection.count.return_value = 1
        collection.get.return_value = {
            "ids": [ep.id],
            "metadatas": [meta],
            "documents": [ep.user_input],
        }

        em = MagicMock()
        em._collection = collection

        sif = self._make_sif(em)
        result = sif.check_memory_integrity()
        assert result.passed is False
        assert "content hash mismatch" in result.details

    def test_sif_skips_legacy_no_hash(self):
        """Episode without content_hash -> SIF passes (no false alarm)."""
        ep = _make_episode()
        meta = EpisodicMemory._episode_to_metadata(ep)
        del meta["content_hash"]  # Simulate legacy episode

        collection = MagicMock()
        collection.count.return_value = 1
        collection.get.return_value = {
            "ids": [ep.id],
            "metadatas": [meta],
            "documents": [ep.user_input],
        }

        em = MagicMock()
        em._collection = collection

        sif = self._make_sif(em)
        result = sif.check_memory_integrity()
        assert result.passed is True


# ===========================================================================
# D5 — Config (2 tests)
# ===========================================================================


class TestConfig:
    """verify_content_hash config flag."""

    def test_verify_on_recall_default_true(self):
        """Default config -> verification enabled."""
        em = EpisodicMemory(db_path="/tmp/test.db")
        assert em._verify_on_recall is True

    @pytest.mark.asyncio
    async def test_verify_disabled_skips_check(self, tmp_path, caplog):
        """verify_content_hash=False -> no WARNING logged even on mismatch."""
        em = EpisodicMemory(
            db_path=str(tmp_path / "ep.db"),
            verify_content_hash=False,
        )
        try:
            await em.start()
        except Exception as exc:
            if "INVALID_PROTOBUF" in str(exc) or "onnx" in str(exc).lower() or "No such file" in str(exc):
                pytest.skip(f"ChromaDB ONNX model unavailable: {exc}")
            raise
        try:
            ep = _make_episode(agent_ids=["agent-1"])
            try:
                await em.store(ep)
            except Exception as exc:
                if "INVALID_PROTOBUF" in str(exc) or "onnx" in str(exc).lower() or "No such file" in str(exc):
                    pytest.skip(f"ChromaDB ONNX model unavailable: {exc}")
                raise

            # Tamper with stored hash
            result = em._collection.get(ids=[ep.id], include=["metadatas"])
            meta = result["metadatas"][0]
            meta["content_hash"] = "tampered" + "0" * 56
            em._collection.update(ids=[ep.id], metadatas=[meta])

            # Recall with verification disabled
            with caplog.at_level(logging.WARNING, logger="probos.cognitive.episodic"):
                recalled = await em.recall_for_agent("agent-1", "diagnostics", k=5)

            # Episode still returned
            assert len(recalled) >= 1
            # No tamper warning logged
            assert not any(
                "hash mismatch" in r.message for r in caplog.records
            )
        finally:
            await em.stop()


# ===========================================================================
# D7 — Int/float coercion resilience
# ===========================================================================


class TestNumericCoercion:
    """Ensure hash survives int/float type coercion (ChromaDB round-trip)."""

    def test_duration_ms_int_vs_float(self):
        """duration_ms=0 (int) and duration_ms=0.0 (float) produce same hash."""
        ep_int = _make_episode(duration_ms=0)
        ep_float = _make_episode(duration_ms=0.0)
        assert compute_episode_hash(ep_int) == compute_episode_hash(ep_float)

    def test_duration_ms_int_150(self):
        """duration_ms=150 (int) and duration_ms=150.0 (float) produce same hash."""
        ep_int = _make_episode(duration_ms=150)
        ep_float = _make_episode(duration_ms=150.0)
        assert compute_episode_hash(ep_int) == compute_episode_hash(ep_float)

    def test_timestamp_int_vs_float(self):
        """timestamp=1700000000 (int) and =1700000000.0 (float) same hash."""
        ep_int = _make_episode(timestamp=1700000000)
        ep_float = _make_episode(timestamp=1700000000.0)
        assert compute_episode_hash(ep_int) == compute_episode_hash(ep_float)

    @pytest.mark.asyncio
    async def test_chromadb_roundtrip_int_duration(self, tmp_path):
        """Hash survives ChromaDB round-trip when duration_ms is an integer."""
        em = EpisodicMemory(db_path=str(tmp_path / "ep.db"), verify_content_hash=True)
        try:
            await em.start()
        except Exception as exc:
            if "INVALID_PROTOBUF" in str(exc) or "onnx" in str(exc).lower() or "No such file" in str(exc):
                pytest.skip(f"ChromaDB ONNX model unavailable: {exc}")
            raise
        try:
            ep = _make_episode(duration_ms=150, agent_ids=["agent-1"])
            try:
                await em.store(ep)
            except Exception as exc:
                if "INVALID_PROTOBUF" in str(exc) or "onnx" in str(exc).lower() or "No such file" in str(exc):
                    pytest.skip(f"ChromaDB ONNX model unavailable: {exc}")
                raise
            recalled = await em.recall_for_agent("agent-1", "diagnostics", k=5)
            assert len(recalled) >= 1
            r = next(r for r in recalled if r.id == ep.id)
            assert compute_episode_hash(r) == compute_episode_hash(ep)
        finally:
            await em.stop()

    def test_timestamp_precision_truncation(self):
        """Hash is stable when timestamp has >16 significant digits.

        IEEE 754 double holds ~15-16 significant digits.  ChromaDB/SQLite
        can truncate the 17th digit.  The round(ts, 6) normalization
        in compute_episode_hash makes the hash resilient to this.
        """
        # 17 significant digits — the 7th decimal exceeds safe precision
        ep_full = _make_episode(timestamp=1775286253.5509393)
        # 16 significant digits — what ChromaDB returns after truncation
        ep_trunc = _make_episode(timestamp=1775286253.550939)
        assert compute_episode_hash(ep_full) == compute_episode_hash(ep_trunc)
