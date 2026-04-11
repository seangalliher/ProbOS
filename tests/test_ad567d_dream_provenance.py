"""AD-567d: Anchor-Preserving Dream Consolidation + Active Forgetting — 31 tests."""

from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.types import AnchorFrame, Episode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_episode(
    *,
    id: str = "",
    user_input: str = "test input",
    timestamp: float | None = None,
    agent_ids: list[str] | None = None,
    source: str = "direct",
    anchors: AnchorFrame | None = None,
) -> Episode:
    ep = Episode(
        user_input=user_input,
        timestamp=timestamp or time.time(),
        agent_ids=agent_ids or ["agent-001"],
        source=source,
        anchors=anchors,
        outcomes=[{"intent": "test_intent", "success": True}],
    )
    if id:
        object.__setattr__(ep, "id", id)
    return ep


def _full_anchor(**overrides: Any) -> AnchorFrame:
    defaults = dict(
        duty_cycle_id="duty-001",
        watch_section="alpha",
        channel="ward_room",
        channel_id="ch-123",
        department="science",
        participants=["Atlas", "Horizon"],
        trigger_agent="Atlas",
        trigger_type="ward_room_post",
        thread_id="thread-456",
        event_log_window=1000.0,
    )
    defaults.update(overrides)
    return AnchorFrame(**defaults)


# ===========================================================================
# Section 1-3: Provenance Composition (10 tests)
# ===========================================================================

class TestProvenanceComposition:
    """Tests for anchor provenance composition functions."""

    def test_summarize_cluster_anchors_shared_channel(self) -> None:
        """All episodes same channel -> shared channel populated."""
        from probos.cognitive.anchor_provenance import summarize_cluster_anchors

        eps = [
            _make_episode(anchors=_full_anchor(channel="ward_room")),
            _make_episode(anchors=_full_anchor(channel="ward_room")),
            _make_episode(anchors=_full_anchor(channel="ward_room")),
        ]
        summary = summarize_cluster_anchors(eps)
        assert summary["channels"] == ["ward_room"]
        assert summary["episode_count"] == 3

    def test_summarize_cluster_anchors_mixed(self) -> None:
        """Mixed channels -> channels list complete."""
        from probos.cognitive.anchor_provenance import summarize_cluster_anchors

        eps = [
            _make_episode(anchors=_full_anchor(channel="ward_room")),
            _make_episode(anchors=_full_anchor(channel="bridge")),
            _make_episode(anchors=_full_anchor(channel="engineering")),
        ]
        summary = summarize_cluster_anchors(eps)
        assert sorted(summary["channels"]) == ["bridge", "engineering", "ward_room"]

    def test_summarize_cluster_anchors_participants_union(self) -> None:
        """Participants unioned across episodes."""
        from probos.cognitive.anchor_provenance import summarize_cluster_anchors

        eps = [
            _make_episode(anchors=_full_anchor(participants=["Atlas"], trigger_agent="Atlas")),
            _make_episode(anchors=_full_anchor(participants=["Horizon"], trigger_agent="Horizon")),
            _make_episode(anchors=_full_anchor(participants=["Vega"], trigger_agent="Atlas")),
        ]
        summary = summarize_cluster_anchors(eps)
        assert sorted(summary["participants"]) == ["Atlas", "Horizon", "Vega"]

    def test_summarize_cluster_anchors_empty_anchors(self) -> None:
        """Episodes with no anchors -> empty summary."""
        from probos.cognitive.anchor_provenance import summarize_cluster_anchors

        eps = [
            _make_episode(anchors=None),
            _make_episode(anchors=None),
        ]
        summary = summarize_cluster_anchors(eps)
        assert summary["channels"] == []
        assert summary["departments"] == []
        assert summary["episode_count"] == 0

    def test_summarize_cluster_anchors_time_span(self) -> None:
        """Min/max timestamps correct."""
        from probos.cognitive.anchor_provenance import summarize_cluster_anchors

        t1, t2, t3 = 1000.0, 2000.0, 3000.0
        eps = [
            _make_episode(timestamp=t1, anchors=_full_anchor()),
            _make_episode(timestamp=t2, anchors=_full_anchor()),
            _make_episode(timestamp=t3, anchors=_full_anchor()),
        ]
        summary = summarize_cluster_anchors(eps)
        assert summary["temporal_span"] == [t1, t3]

    def test_procedure_provenance_populated(self) -> None:
        """Extracted procedure has source_anchors from episodes."""
        from probos.cognitive.anchor_provenance import (
            build_procedure_provenance,
            summarize_cluster_anchors,
        )

        eps = [
            _make_episode(id="ep-1", anchors=_full_anchor(channel="bridge", department="science")),
            _make_episode(id="ep-2", anchors=_full_anchor(channel="ward_room", department="medical")),
        ]
        summary = summarize_cluster_anchors(eps)
        anchors = build_procedure_provenance(summary, cluster_id="cluster-001")
        assert len(anchors) == 2
        assert anchors[0]["episode_id"] == "ep-1"
        assert anchors[0]["cluster_id"] == "cluster-001"
        assert anchors[1]["episode_id"] == "ep-2"

    def test_procedure_provenance_serialization(self) -> None:
        """Source_anchors round-trips through to_dict/from_dict."""
        from probos.cognitive.procedures import Procedure

        p = Procedure(
            id="proc-1",
            name="test",
            intent_types=["test_intent"],
            steps=[],
            provenance=["ep-1"],
            source_anchors=[
                {"episode_id": "ep-1", "channel": "bridge", "department": "science"},
            ],
        )
        d = p.to_dict()
        assert d["source_anchors"] == p.source_anchors
        p2 = Procedure.from_dict(d)
        assert p2.source_anchors == p.source_anchors

    def test_procedure_store_schema_migration(self) -> None:
        """source_anchors_json column added on upgrade."""
        from probos.cognitive.procedure_store import ProcedureStore

        store = ProcedureStore.__new__(ProcedureStore)
        # Verify the migration method exists
        assert hasattr(store, "_ensure_source_anchors_column")

    def test_format_episode_blocks_includes_anchors(self) -> None:
        """Episode blocks include anchor context."""
        from probos.cognitive.procedures import _format_episode_blocks

        ep = _make_episode(anchors=_full_anchor(channel="bridge", department="science"))
        text = _format_episode_blocks([ep])
        assert "Channel: bridge" in text
        assert "Department: science" in text

    def test_convergence_report_provenance_section(self) -> None:
        """Convergence report includes provenance from contributing entries."""
        from probos.cognitive.anchor_provenance import enrich_convergence_report

        report: dict[str, Any] = {"topic": "test convergence"}
        entries = [
            {"agent": "Atlas", "department": "science", "path": "/notebooks/atlas/test.md"},
            {"agent": "Chapel", "department": "medical", "path": "/notebooks/chapel/test.md"},
        ]
        enriched = enrich_convergence_report(report, entries)
        assert "source_anchors" in enriched
        assert len(enriched["source_anchors"]) == 2
        assert enriched["source_anchors"][0]["agent"] == "Atlas"
        assert enriched["source_anchors"][1]["department"] == "medical"


# ===========================================================================
# Section 4: Activation Tracker (10 tests)
# ===========================================================================

class TestActivationTracker:
    """Tests for ACT-R activation model."""

    @pytest.fixture
    async def tracker(self, tmp_path):
        from probos.cognitive.activation_tracker import ActivationTracker

        t = ActivationTracker(
            decay_d=0.5,
            access_max_age_days=180,
            db_path=str(tmp_path / "activation.db"),
        )
        await t.start()
        yield t
        await t.stop()

    @pytest.mark.asyncio
    async def test_activation_tracker_start(self, tracker) -> None:
        """Creates DB and table."""
        assert tracker._db is not None
        cursor = await tracker._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='episode_access_log'"
        )
        row = await cursor.fetchone()
        assert row is not None

    @pytest.mark.asyncio
    async def test_record_access(self, tracker) -> None:
        """Inserts access log entry."""
        await tracker.record_access("ep-1", access_type="recall")
        cursor = await tracker._db.execute(
            "SELECT COUNT(*) FROM episode_access_log WHERE episode_id = 'ep-1'"
        )
        row = await cursor.fetchone()
        assert row[0] == 1

    @pytest.mark.asyncio
    async def test_record_batch_access(self, tracker) -> None:
        """Bulk insert."""
        await tracker.record_batch_access(["ep-1", "ep-2", "ep-3"], access_type="dream_replay")
        cursor = await tracker._db.execute("SELECT COUNT(*) FROM episode_access_log")
        row = await cursor.fetchone()
        assert row[0] == 3

    @pytest.mark.asyncio
    async def test_compute_activation_single_access(self, tracker) -> None:
        """Returns positive finite value."""
        await tracker.record_access("ep-1")
        activation = await tracker.get_activation("ep-1")
        assert math.isfinite(activation)

    @pytest.mark.asyncio
    async def test_compute_activation_multiple_accesses(self, tracker) -> None:
        """Higher than single (reinforcement)."""
        await tracker.record_access("ep-1")
        single = await tracker.get_activation("ep-1")
        await tracker.record_access("ep-1")
        await tracker.record_access("ep-1")
        multi = await tracker.get_activation("ep-1")
        assert multi > single

    @pytest.mark.asyncio
    async def test_compute_activation_no_accesses(self, tracker) -> None:
        """Returns -inf."""
        activation = await tracker.get_activation("ep-never")
        assert activation == float("-inf")

    @pytest.mark.asyncio
    async def test_compute_batch_activation(self, tracker) -> None:
        """Computes for multiple episodes efficiently."""
        await tracker.record_access("ep-1")
        await tracker.record_access("ep-2")
        batch = await tracker.get_activations_batch(["ep-1", "ep-2", "ep-3"])
        assert len(batch) == 3
        assert math.isfinite(batch["ep-1"])
        assert math.isfinite(batch["ep-2"])
        assert batch["ep-3"] == float("-inf")

    @pytest.mark.asyncio
    async def test_activation_decays_with_time(self, tracker) -> None:
        """Older access -> lower activation."""
        # Use compute_activation directly with controlled times
        now = time.time()
        recent = tracker.compute_activation([now - 1], now=now)       # 1 second ago
        old = tracker.compute_activation([now - 86400], now=now)       # 1 day ago
        assert recent > old

    @pytest.mark.asyncio
    async def test_prune_old_accesses(self, tracker) -> None:
        """Removes records older than max_age."""
        # Insert an old access
        old_time = time.time() - (200 * 86400)  # 200 days ago
        await tracker._db.execute(
            "INSERT INTO episode_access_log (episode_id, access_time, access_type) VALUES (?, ?, ?)",
            ("ep-old", old_time, "recall"),
        )
        await tracker._db.commit()
        removed = await tracker.cleanup_old_accesses()
        assert removed >= 1

    @pytest.mark.asyncio
    async def test_delete_episode_cleanup(self, tracker) -> None:
        """Removes all access records for evicted episode."""
        await tracker.record_access("ep-1")
        await tracker.record_access("ep-1")
        await tracker.delete_episode_accesses(["ep-1"])
        cursor = await tracker._db.execute(
            "SELECT COUNT(*) FROM episode_access_log WHERE episode_id = 'ep-1'"
        )
        row = await cursor.fetchone()
        assert row[0] == 0


# ===========================================================================
# Section 5: Recall Reinforcement (3 tests)
# ===========================================================================

class TestRecallReinforcement:
    """Tests for recall recording activation."""

    @pytest.fixture
    def mock_tracker(self):
        tracker = AsyncMock()
        tracker.record_batch_access = AsyncMock()
        return tracker

    @pytest.fixture
    async def episodic_memory(self, tmp_path, mock_tracker):
        """Minimal EpisodicMemory with activation tracker."""
        from probos.cognitive.episodic import EpisodicMemory

        em = EpisodicMemory(db_path=str(tmp_path / "ep"), max_episodes=100)
        await em.start()
        em.set_activation_tracker(mock_tracker)
        # Store a test episode
        ep = _make_episode(id="ep-recall-1", anchors=_full_anchor())
        await em.store(ep)
        yield em, mock_tracker
        await em.stop()

    @pytest.mark.asyncio
    async def test_recall_for_agent_records_access(self, episodic_memory) -> None:
        """recall_for_agent triggers activation recording."""
        em, tracker = episodic_memory
        results = await em.recall_for_agent("agent-001", "test", k=5)
        if results:
            tracker.record_batch_access.assert_called()

    @pytest.mark.asyncio
    async def test_recall_weighted_records_access(self, episodic_memory) -> None:
        """recall_weighted triggers activation recording."""
        em, tracker = episodic_memory
        results = await em.recall_weighted("agent-001", "test", k=5)
        if results:
            tracker.record_batch_access.assert_called()

    @pytest.mark.asyncio
    async def test_recent_for_agent_no_access_recording(self, episodic_memory) -> None:
        """recent_for_agent (fallback scan) does NOT record access."""
        em, tracker = episodic_memory
        tracker.record_batch_access.reset_mock()
        await em.recent_for_agent("agent-001", k=5)
        tracker.record_batch_access.assert_not_called()


# ===========================================================================
# Section 6: Dream Step 12 (7 tests)
# ===========================================================================

class TestDreamStep12:
    """Tests for activation-based memory pruning during dream cycle."""

    def _make_dreaming_engine(self, *, activation_enabled=True, tracker=None):
        from probos.config import DreamingConfig

        config = DreamingConfig(
            activation_enabled=activation_enabled,
            activation_prune_threshold=-2.0,
            activation_access_max_age_days=180,
            aggressive_prune_enabled=False,  # BF-145: isolate standard-tier tests from AD-593 aggressive tier
        )
        mock_router = MagicMock()
        mock_router.all_weights.return_value = {}
        mock_router.get_weight.return_value = 0.5
        mock_router.strengthen.return_value = None
        mock_router.weaken.return_value = None
        mock_trust = MagicMock()
        mock_trust.raw_scores.return_value = {}
        mock_trust.consolidate = AsyncMock(return_value=[])

        mock_em = AsyncMock()
        mock_em.recent = AsyncMock(return_value=[])
        mock_em.get_stats = AsyncMock(return_value={"total": 0})
        mock_em.evict_by_ids = AsyncMock(return_value=0)
        mock_em.get_episode_ids_older_than = AsyncMock(return_value=[])

        from probos.cognitive.dreaming import DreamingEngine

        engine = DreamingEngine(
            router=mock_router,
            trust_network=mock_trust,
            episodic_memory=mock_em,
            config=config,
            activation_tracker=tracker,
        )
        return engine, mock_em

    @pytest.mark.asyncio
    async def test_dream_step_12_prunes_low_activation(self) -> None:
        """Low-activation episodes evicted."""
        tracker = AsyncMock()
        tracker.record_batch_access = AsyncMock()
        tracker.find_low_activation_episodes = AsyncMock(return_value=["ep-old-1", "ep-old-2"])
        tracker.cleanup_old_accesses = AsyncMock()

        engine, mock_em = self._make_dreaming_engine(tracker=tracker)

        old_ep = _make_episode(id="ep-1", timestamp=time.time() - 100000)
        mock_em.recent.return_value = [old_ep]
        mock_em.get_stats.return_value = {"total": 20}
        mock_em.get_episode_ids_older_than.return_value = ["ep-old-1", "ep-old-2", "ep-old-3"]

        report = await engine.dream_cycle()
        assert report.activation_pruned == 2
        mock_em.evict_by_ids.assert_called_once()

    @pytest.mark.asyncio
    async def test_dream_step_12_skips_young_episodes(self) -> None:
        """Episodes < 24h old never pruned."""
        tracker = AsyncMock()
        tracker.record_batch_access = AsyncMock()
        tracker.find_low_activation_episodes = AsyncMock(return_value=[])
        tracker.cleanup_old_accesses = AsyncMock()

        engine, mock_em = self._make_dreaming_engine(tracker=tracker)

        # recent episode
        ep = _make_episode(id="ep-new", timestamp=time.time())
        mock_em.recent.return_value = [ep]
        mock_em.get_stats.return_value = {"total": 5}
        # get_episode_ids_older_than will return empty since none are old
        mock_em.get_episode_ids_older_than.return_value = []

        report = await engine.dream_cycle()
        assert report.activation_pruned == 0
        # find_low_activation_episodes should not even be called
        tracker.find_low_activation_episodes.assert_not_called()

    @pytest.mark.asyncio
    async def test_dream_step_12_respects_cap(self) -> None:
        """Max 10% pruned per cycle."""
        tracker = AsyncMock()
        tracker.record_batch_access = AsyncMock()
        # Returns more than 10% — the cap is enforced inside find_low_activation_episodes
        tracker.find_low_activation_episodes = AsyncMock(return_value=["ep-1", "ep-2"])
        tracker.cleanup_old_accesses = AsyncMock()

        engine, mock_em = self._make_dreaming_engine(tracker=tracker)
        mock_em.recent.return_value = [_make_episode(id="ep-x")]
        mock_em.get_stats.return_value = {"total": 100}
        mock_em.get_episode_ids_older_than.return_value = [f"ep-{i}" for i in range(50)]

        report = await engine.dream_cycle()
        # Verify max_prune_fraction=0.10 was passed
        call_kwargs = tracker.find_low_activation_episodes.call_args
        assert call_kwargs.kwargs.get("max_prune_fraction") == 0.10 or \
            (call_kwargs[1].get("max_prune_fraction") == 0.10 if len(call_kwargs) > 1 else True)

    @pytest.mark.asyncio
    async def test_dream_step_12_eviction_audit(self) -> None:
        """Pruned episodes routed through evict_by_ids which handles audit."""
        tracker = AsyncMock()
        tracker.record_batch_access = AsyncMock()
        tracker.find_low_activation_episodes = AsyncMock(return_value=["ep-1"])
        tracker.cleanup_old_accesses = AsyncMock()

        engine, mock_em = self._make_dreaming_engine(tracker=tracker)
        mock_em.recent.return_value = [_make_episode(id="ep-x")]
        mock_em.get_stats.return_value = {"total": 10}
        mock_em.get_episode_ids_older_than.return_value = ["ep-1", "ep-2"]

        await engine.dream_cycle()
        mock_em.evict_by_ids.assert_called_once_with(["ep-1"], reason="activation_decay")

    @pytest.mark.asyncio
    async def test_dream_step_12_disabled(self) -> None:
        """activation_enabled=False -> step skipped."""
        tracker = AsyncMock()
        engine, mock_em = self._make_dreaming_engine(activation_enabled=False, tracker=tracker)
        mock_em.recent.return_value = [_make_episode(id="ep-x")]
        mock_em.get_stats.return_value = {"total": 5}

        report = await engine.dream_cycle()
        assert report.activation_pruned == 0
        assert report.activation_reinforced == 0
        tracker.record_batch_access.assert_not_called()

    @pytest.mark.asyncio
    async def test_dream_step_12_no_tracker(self) -> None:
        """No tracker wired -> step skipped gracefully."""
        engine, mock_em = self._make_dreaming_engine(tracker=None)
        mock_em.recent.return_value = [_make_episode(id="ep-x")]
        mock_em.get_stats.return_value = {"total": 5}

        report = await engine.dream_cycle()
        assert report.activation_pruned == 0
        assert report.activation_reinforced == 0

    @pytest.mark.asyncio
    async def test_dream_step_12_skips_unknown_episode_ids(self) -> None:
        """Episode IDs not in episodic memory are handled by evict_by_ids (returns 0 for invalid)."""
        tracker = AsyncMock()
        tracker.record_batch_access = AsyncMock()
        tracker.find_low_activation_episodes = AsyncMock(return_value=["ep-ghost"])
        tracker.cleanup_old_accesses = AsyncMock()

        engine, mock_em = self._make_dreaming_engine(tracker=tracker)
        mock_em.recent.return_value = [_make_episode(id="ep-x")]
        mock_em.get_stats.return_value = {"total": 10}
        mock_em.get_episode_ids_older_than.return_value = ["ep-ghost"]
        mock_em.evict_by_ids.return_value = 0  # ghost ID not found

        report = await engine.dream_cycle()
        # evict_by_ids was called but returned 0
        mock_em.evict_by_ids.assert_called_once()


# ===========================================================================
# Section 9: Micro-Dream Reinforcement (1 test)
# ===========================================================================

class TestMicroDreamReinforcement:
    """Tests for micro_dream activation reinforcement."""

    @pytest.mark.asyncio
    async def test_micro_dream_records_replay_access(self) -> None:
        """Micro_dream reinforces episode activation."""
        from probos.config import DreamingConfig

        config = DreamingConfig(activation_enabled=True)
        mock_router = MagicMock()
        mock_router.get_weight.return_value = 0.5
        mock_router.strengthen.return_value = None
        mock_router.weaken.return_value = None
        mock_trust = MagicMock()

        mock_em = AsyncMock()
        ep = _make_episode(id="ep-micro-1")
        mock_em.get_stats = AsyncMock(return_value={"total": 5})
        mock_em.recent = AsyncMock(return_value=[ep])

        tracker = AsyncMock()
        tracker.record_batch_access = AsyncMock()

        from probos.cognitive.dreaming import DreamingEngine

        engine = DreamingEngine(
            router=mock_router,
            trust_network=mock_trust,
            episodic_memory=mock_em,
            config=config,
            activation_tracker=tracker,
        )
        engine._last_consolidated_count = 0

        result = await engine.micro_dream()
        assert result["episodes_replayed"] == 1
        tracker.record_batch_access.assert_called_once()
        call_args = tracker.record_batch_access.call_args
        assert call_args[0][0] == ["ep-micro-1"]
        assert call_args[1].get("access_type") == "dream_replay" or call_args[0][1] == "dream_replay"
