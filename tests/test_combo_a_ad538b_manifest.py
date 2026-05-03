"""Combo A AD-538b: Dream Consolidation Manifest tests."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from probos.cognitive.dream_manifest import DreamManifest


def test_dream_manifest_mark_and_check(tmp_path):
    mf = DreamManifest(store_path=tmp_path / "manifest.json")
    assert mf.is_processed("ep-1", "consolidate") is False
    mf.mark_processed("ep-1", "consolidate")
    assert mf.is_processed("ep-1", "consolidate") is True
    # Different step is independent
    assert mf.is_processed("ep-1", "prune") is False


def test_dream_manifest_persists_across_restarts(tmp_path):
    path = tmp_path / "m.json"
    mf1 = DreamManifest(store_path=path)
    mf1.mark_processed("ep-A", "consolidate")
    # New instance reading the same file
    mf2 = DreamManifest(store_path=path)
    assert mf2.is_processed("ep-A", "consolidate") is True


def test_dream_manifest_prune_removes_old_entries(tmp_path):
    mf = DreamManifest(store_path=tmp_path / "m.json")
    mf.mark_processed("old", "consolidate")
    # Force the entry into the past
    mf._entries["old"]["consolidate"] = time.time() - 7200
    mf.mark_processed("recent", "consolidate")
    removed = mf.prune(max_age_seconds=3600)
    assert removed == 1
    assert mf.is_processed("old", "consolidate") is False
    assert mf.is_processed("recent", "consolidate") is True


@pytest.mark.asyncio
async def test_dream_scheduler_skips_processed_episodes(tmp_path):
    """Stub the manifest layer; verify _replay_episodes is called with filtered list.

    Note: the consolidation logic with _replay_episodes lives on
    DreamingEngine (not DreamScheduler). Combo A's verify-first footer
    cited the wrong class header; the actual __init__ + micro_dream are
    on DreamingEngine.
    """
    from types import SimpleNamespace

    # Manifest reports ep-1 already processed
    mf = MagicMock()
    mf.is_processed.side_effect = lambda ep_id, step: ep_id == "ep-1"
    mf.mark_processed = MagicMock()

    # Build a minimal DreamingEngine-like stub via the actual class
    from probos.cognitive.dreaming import DreamingEngine
    from probos.config import DreamingConfig

    fake_em = MagicMock()
    # Async context: get_stats and recent must be coroutines
    async def _async_get_stats():
        return {"total": 5}
    async def _async_recent(k):
        return [
            SimpleNamespace(id="ep-1"),
            SimpleNamespace(id="ep-2"),
        ]
    fake_em.get_stats = _async_get_stats
    fake_em.recent = _async_recent

    fake_router = MagicMock()
    fake_trust = MagicMock()
    cfg = DreamingConfig()

    engine = DreamingEngine(
        router=fake_router,
        trust_network=fake_trust,
        episodic_memory=fake_em,
        config=cfg,
        manifest=mf,
    )
    # Bypass actual replay logic: stub _replay_episodes to count calls
    engine._replay_episodes = MagicMock(return_value=0)

    summary = await engine.micro_dream()

    # Only ep-2 should reach _replay_episodes
    assert engine._replay_episodes.called
    replayed_episodes = engine._replay_episodes.call_args[0][0]
    replayed_ids = [getattr(ep, "id", "") for ep in replayed_episodes]
    assert "ep-1" not in replayed_ids
    assert "ep-2" in replayed_ids
    # ep-2 should be marked processed after replay
    mf.mark_processed.assert_any_call("ep-2", "consolidate")
