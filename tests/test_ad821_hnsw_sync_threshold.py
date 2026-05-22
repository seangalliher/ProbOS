"""AD-821: ChromaDB HNSW per-collection sync threshold tuning.

Verifies that MemoryConfig accepts/rejects threshold values correctly, that
EpisodicMemory propagates them to the underlying Chroma collection metadata,
and that the cross-field batch-size cap is enforced at construction.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from probos.cognitive.episodic import EpisodicMemory
from probos.config import MemoryConfig


# ---- Unit: MemoryConfig field validation ----

def test_ad821_memoryconfig_accepts_default_threshold():
    cfg = MemoryConfig()
    assert cfg.hnsw_sync_threshold == 64
    assert cfg.hnsw_batch_size == 32


def test_ad821_memoryconfig_accepts_custom_threshold():
    cfg = MemoryConfig(hnsw_sync_threshold=128, hnsw_batch_size=64)
    assert cfg.hnsw_sync_threshold == 128
    assert cfg.hnsw_batch_size == 64


def test_ad821_memoryconfig_rejects_below_minimum():
    with pytest.raises(Exception):  # pydantic.ValidationError
        MemoryConfig(hnsw_sync_threshold=3)


def test_ad821_memoryconfig_rejects_above_maximum():
    with pytest.raises(Exception):  # pydantic.ValidationError
        MemoryConfig(hnsw_sync_threshold=10001)


# ---- Unit: EpisodicMemory constructor ----

def test_ad821_episodicmemory_constructs_with_threshold(tmp_path: Path):
    em = EpisodicMemory(
        db_path=str(tmp_path / "episodic.db"),
        hnsw_sync_threshold=64,
        hnsw_batch_size=32,
    )
    assert em._hnsw_sync_threshold == 64
    assert em._hnsw_batch_size == 32


def test_ad821_episodicmemory_caps_batch_size_to_half_threshold(tmp_path: Path):
    # Batch size 100 with threshold 64 should be capped to 32 (=64//2).
    em = EpisodicMemory(
        db_path=str(tmp_path / "episodic.db"),
        hnsw_sync_threshold=64,
        hnsw_batch_size=100,
    )
    assert em._hnsw_batch_size == 32


# ---- Integration: collection metadata reflects threshold ----

def test_ad821_chroma_collection_metadata_carries_threshold(tmp_path: Path):
    em = EpisodicMemory(
        db_path=str(tmp_path / "episodic.db"),
        hnsw_sync_threshold=64,
        hnsw_batch_size=32,
    )
    asyncio.run(em.start())
    try:
        meta = em._collection.metadata or {}
        assert meta.get("hnsw:space") == "cosine"
        assert int(meta.get("hnsw:sync_threshold", -1)) == 64
        assert int(meta.get("hnsw:batch_size", -1)) == 32
    finally:
        # Best-effort cleanup; Chroma PersistentClient holds OS file handles.
        em._client = None
        em._collection = None


# ---- Optional slow smoke (skipped by default per AD-821 build prompt) ----

@pytest.mark.slow
def test_ad821_threshold_smoke_100_episode_roundtrip(tmp_path: Path):
    """Optional smoke: 100-episode write with threshold=64. Skipped by default;
    Windows CI flakiness makes this unsuitable for the standard gate."""
    em = EpisodicMemory(
        db_path=str(tmp_path / "episodic.db"),
        hnsw_sync_threshold=64,
        hnsw_batch_size=32,
    )
    asyncio.run(em.start())
    try:
        for i in range(100):
            em._collection.add(
                ids=[f"smoke-{i}"],
                documents=[f"smoke episode {i}"],
                metadatas=[{"smoke": True}],
            )
        assert em._collection.count() == 100
    finally:
        em._client = None
        em._collection = None
