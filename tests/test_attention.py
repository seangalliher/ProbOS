"""Tests for attention mechanism — priority scoring, batching, and focus tracking."""

import time
from datetime import datetime, timezone

import pytest

from probos.cognitive.attention import AttentionManager
from probos.types import AttentionEntry


def _make_entry(
    task_id: str = "t1",
    intent: str = "read_file",
    urgency: float = 0.5,
    dependency_depth: int = 0,
    is_background: bool = False,
    ttl_seconds: float = 30.0,
    created_at: datetime | None = None,
) -> AttentionEntry:
    """Helper to create an AttentionEntry with sensible defaults."""
    return AttentionEntry(
        task_id=task_id,
        intent=intent,
        urgency=urgency,
        dependency_depth=dependency_depth,
        is_background=is_background,
        ttl_seconds=ttl_seconds,
        created_at=created_at or datetime.now(timezone.utc),
    )


class TestAttentionManager:
    @pytest.fixture
    def am(self) -> AttentionManager:
        return AttentionManager(max_concurrent=8, decay_rate=0.95)

    # ---- submit and retrieve ------------------------------------

    def test_submit_and_retrieve(self, am: AttentionManager):
        """Submit 3 tasks, get_next_batch returns them sorted by score."""
        am.submit(_make_entry("t1", urgency=0.3))
        am.submit(_make_entry("t2", urgency=0.9))
        am.submit(_make_entry("t3", urgency=0.6))

        batch = am.get_next_batch()
        assert len(batch) == 3
        # Highest urgency first
        assert batch[0].task_id == "t2"
        assert batch[1].task_id == "t3"
        assert batch[2].task_id == "t1"

    def test_budget_limit(self, am: AttentionManager):
        """Submit 10 tasks with budget=3, only top 3 returned."""
        for i in range(10):
            am.submit(_make_entry(f"t{i}", urgency=i / 10.0))

        batch = am.get_next_batch(budget=3)
        assert len(batch) == 3
        # Top 3 by urgency (0.9, 0.8, 0.7)
        assert batch[0].task_id == "t9"
        assert batch[1].task_id == "t8"
        assert batch[2].task_id == "t7"

    # ---- scoring factors ----------------------------------------

    def test_urgency_affects_score(self, am: AttentionManager):
        """Higher urgency → higher score."""
        low = _make_entry("low", urgency=0.1)
        high = _make_entry("high", urgency=0.9)
        am.submit(low)
        am.submit(high)
        am.compute_scores()
        assert high.score > low.score

    def test_deadline_factor_increases_near_expiry(self):
        """A task near TTL expiry gets a higher deadline factor."""
        am = AttentionManager()

        # Task created 29 seconds ago with 30s TTL — nearly expired
        near_expiry = _make_entry(
            "near",
            urgency=0.5,
            ttl_seconds=30.0,
            created_at=datetime.fromtimestamp(
                time.time() - 29.0, tz=timezone.utc
            ),
        )
        # Task just created — full TTL remaining
        fresh = _make_entry("fresh", urgency=0.5, ttl_seconds=30.0)

        am.submit(near_expiry)
        am.submit(fresh)
        am.compute_scores()

        assert near_expiry.score > fresh.score
        assert near_expiry.deadline_factor > fresh.deadline_factor

    def test_dependency_depth_bonus(self, am: AttentionManager):
        """Task with higher dependency depth gets bonus."""
        shallow = _make_entry("shallow", urgency=0.5, dependency_depth=0)
        deep = _make_entry("deep", urgency=0.5, dependency_depth=3)

        am.submit(shallow)
        am.submit(deep)
        am.compute_scores()

        # deep gets 1.0 + 3*0.1 = 1.3x bonus
        assert deep.score > shallow.score

    # ---- focus tracking (infrastructure only) -------------------

    def test_focus_stores_keywords(self, am: AttentionManager):
        """update_focus() stores keywords, retrievable via current_focus."""
        am.update_focus("read_file", "looking at quarterly report data")
        focus = am.current_focus
        assert "keywords" in focus
        assert "read_file" in focus["keywords"]
        assert "quarterly" in focus["keywords"]
        assert focus["context"] == "looking at quarterly report data"

    def test_background_flag_accepted(self, am: AttentionManager):
        """is_background flag is stored but does not affect scoring this phase."""
        fg = _make_entry("fg", urgency=0.5, is_background=False)
        bg = _make_entry("bg", urgency=0.5, is_background=True)
        am.submit(fg)
        am.submit(bg)
        am.compute_scores()

        # Same urgency, same scoring — background flag is stored but inert
        assert bg.is_background is True
        assert fg.is_background is False
        # Scores should be approximately equal (both have same params)
        assert abs(fg.score - bg.score) < 0.01

    # ---- removal ------------------------------------------------

    def test_mark_completed_removes(self, am: AttentionManager):
        """Completed task no longer in queue."""
        am.submit(_make_entry("t1"))
        am.submit(_make_entry("t2"))
        assert am.queue_size == 2

        am.mark_completed("t1")
        assert am.queue_size == 1
        batch = am.get_next_batch()
        assert all(e.task_id != "t1" for e in batch)

    def test_mark_failed_removes(self, am: AttentionManager):
        """Failed task no longer in queue."""
        am.submit(_make_entry("t1"))
        am.mark_failed("t1")
        assert am.queue_size == 0

    # ---- edge cases ---------------------------------------------

    def test_empty_queue(self, am: AttentionManager):
        """get_next_batch on empty queue returns empty list."""
        batch = am.get_next_batch()
        assert batch == []

    def test_focus_update_stores_state(self, am: AttentionManager):
        """update_focus() stores keywords without affecting scores."""
        am.submit(_make_entry("t1", urgency=0.5))
        am.compute_scores()
        score_before = am.get_queue_snapshot()[0].score

        am.update_focus("read_file", "some context about files")
        am.compute_scores()
        score_after = am.get_queue_snapshot()[0].score

        # Scores unchanged — focus not wired into scoring this phase
        assert abs(score_before - score_after) < 0.001

    def test_queue_snapshot(self, am: AttentionManager):
        """get_queue_snapshot returns current state of all queued tasks."""
        am.submit(_make_entry("t1", urgency=0.3))
        am.submit(_make_entry("t2", urgency=0.7))
        am.submit(_make_entry("t3", urgency=0.5))

        snapshot = am.get_queue_snapshot()
        assert len(snapshot) == 3
        # Sorted by score descending
        assert snapshot[0].task_id == "t2"
        assert snapshot[1].task_id == "t3"
        assert snapshot[2].task_id == "t1"
        # All scores computed
        assert all(e.score > 0 for e in snapshot)
