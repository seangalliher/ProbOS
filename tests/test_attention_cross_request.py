"""Tests for Phase 3b-3a: cross-request focus, relevance scoring, background demotion."""

from datetime import datetime, timezone

import pytest

from probos.cognitive.attention import AttentionManager
from probos.config import load_config
from probos.types import AttentionEntry, FocusSnapshot, TaskNode, TaskDAG


def _make_entry(
    task_id: str = "t1",
    intent: str = "read_file",
    urgency: float = 0.5,
    dependency_depth: int = 0,
    is_background: bool = False,
    ttl_seconds: float = 30.0,
) -> AttentionEntry:
    return AttentionEntry(
        task_id=task_id,
        intent=intent,
        urgency=urgency,
        dependency_depth=dependency_depth,
        is_background=is_background,
        ttl_seconds=ttl_seconds,
        created_at=datetime.now(timezone.utc),
    )


# ---- Focus history tests ------------------------------------------------


class TestFocusHistory:
    def test_focus_history_records_snapshots(self):
        """Call update_focus() 3 times with different text. Assert focus_history has 3 entries."""
        am = AttentionManager()
        am.update_focus("read file test.txt", "reading files")
        am.update_focus("write config yaml", "writing config")
        am.update_focus("run command ls", "running commands")

        history = am.focus_history
        assert len(history) == 3
        # Check keywords are populated
        assert "read" in history[0].keywords
        assert "write" in history[1].keywords
        assert "command" in history[2].keywords

    def test_focus_history_ring_buffer_evicts(self):
        """Call update_focus() 12 times (exceeds max 10). Assert oldest 2 are gone."""
        am = AttentionManager(focus_history_size=10)
        for i in range(12):
            am.update_focus(f"task{i} keyword{i}", f"context{i}")

        history = am.focus_history
        assert len(history) == 10
        # First entry should be from i=2 (oldest 0 and 1 evicted)
        assert "task2" in history[0].keywords
        assert "task11" in history[-1].keywords

    def test_focus_history_empty_initially(self):
        """New AttentionManager has empty focus_history."""
        am = AttentionManager()
        assert am.focus_history == []
        assert len(am.focus_history) == 0


# ---- Cross-request relevance tests --------------------------------------


class TestCrossRequestRelevance:
    def test_relevance_boosts_matching_tasks(self):
        """Focus on 'read file test.txt' boosts read_file intent over http_fetch."""
        am = AttentionManager()
        am.update_focus("read file test.txt", "reading files")

        read_entry = _make_entry("t1", intent="read_file")
        fetch_entry = _make_entry("t2", intent="http_fetch")

        am.submit(read_entry)
        am.submit(fetch_entry)
        am.compute_scores()

        assert read_entry.score > fetch_entry.score

    def test_relevance_floor_prevents_zero(self):
        """Task with zero keyword overlap still gets relevance >= 0.3."""
        am = AttentionManager()
        am.update_focus("read file test.txt", "reading files")

        # Intent with no overlap with "read", "file", "test.txt"
        entry = _make_entry("t1", intent="completely_unrelated_thing")
        relevance = am._compute_relevance(entry)
        assert relevance >= 0.3

    def test_relevance_uses_recent_focus_only(self):
        """Only the last 3 focus snapshots affect relevance."""
        am = AttentionManager(focus_history_size=10)

        # Fill with 10 unrelated entries
        for i in range(10):
            am.update_focus(f"nonsense{i} junk{i} garbage{i}", f"ctx{i}")

        # Now add 3 relevant entries
        am.update_focus("read file data", "reading")
        am.update_focus("read file config", "reading config")
        am.update_focus("read file logs", "file access")

        entry = _make_entry("t1", intent="read_file")
        relevance = am._compute_relevance(entry)
        # "read" and "file" should be in the last 3 snapshots
        assert relevance > 0.3


# ---- Background demotion tests ------------------------------------------


class TestBackgroundDemotion:
    def test_background_task_scored_lower(self):
        """Background task score is ~0.25x the foreground task score."""
        am = AttentionManager()
        fg = _make_entry("fg", intent="read_file", urgency=0.5)
        bg = _make_entry("bg", intent="read_file", urgency=0.5, is_background=True)

        am.submit(fg)
        am.submit(bg)
        am.compute_scores()

        assert bg.score < fg.score
        # Background demotion factor is 0.25 by default
        assert abs(bg.score - fg.score * 0.25) < 0.01

    def test_background_tasks_sort_below_foreground(self):
        """All foreground tasks appear before background tasks in batch."""
        am = AttentionManager()

        # 3 foreground tasks
        for i in range(3):
            am.submit(_make_entry(f"fg{i}", intent="read_file", urgency=0.5))

        # 2 background tasks
        for i in range(2):
            am.submit(_make_entry(f"bg{i}", intent="read_file", urgency=0.5, is_background=True))

        batch = am.get_next_batch(budget=5)
        fg_ids = {e.task_id for e in batch if not e.is_background}
        bg_ids = {e.task_id for e in batch if e.is_background}
        assert len(fg_ids) == 3
        assert len(bg_ids) == 2

        # All foreground entries should come before background
        fg_positions = [i for i, e in enumerate(batch) if not e.is_background]
        bg_positions = [i for i, e in enumerate(batch) if e.is_background]
        assert max(fg_positions) < min(bg_positions)

    def test_background_demotion_factor_configurable(self):
        """Custom background_demotion_factor is used instead of default 0.25."""
        am = AttentionManager(background_demotion_factor=0.5)
        fg = _make_entry("fg", intent="read_file", urgency=0.5)
        bg = _make_entry("bg", intent="read_file", urgency=0.5, is_background=True)

        am.submit(fg)
        am.submit(bg)
        am.compute_scores()

        # With factor 0.5, background score should be ~0.5x foreground
        assert abs(bg.score - fg.score * 0.5) < 0.01


# ---- TaskNode background field tests ------------------------------------


class TestTaskNodeBackground:
    def test_task_node_background_default_false(self):
        """TaskNode background field defaults to False."""
        node = TaskNode(id="t1", intent="read_file")
        assert node.background is False

    def test_task_node_background_set_true(self):
        """TaskNode background can be set to True."""
        node = TaskNode(id="t1", intent="read_file", background=True)
        assert node.background is True


# ---- Config tests --------------------------------------------------------


class TestConfig:
    def test_config_focus_history_size(self):
        """Default config has focus_history_size == 10."""
        from pathlib import Path

        config = load_config(Path(__file__).parent.parent / "config" / "system.yaml")
        assert config.cognitive.focus_history_size == 10

    def test_config_background_demotion_factor(self):
        """Default config has background_demotion_factor == 0.25."""
        from pathlib import Path

        config = load_config(Path(__file__).parent.parent / "config" / "system.yaml")
        assert config.cognitive.background_demotion_factor == 0.25


# ---- Integration test: attention batch propagates background -------------


class TestIntegration:
    def test_attention_batch_propagates_background(self):
        """Foreground node appears before background node in attention batch."""
        from probos.cognitive.decomposer import DAGExecutor

        am = AttentionManager()
        executor = DAGExecutor(runtime=None, attention=am)

        fg_node = TaskNode(id="t1", intent="read_file", background=False)
        bg_node = TaskNode(id="t2", intent="read_file", background=True)
        dag = TaskDAG(nodes=[fg_node, bg_node])

        ready = dag.get_ready_nodes()
        batch = executor._attention_batch(ready, dag)

        # Foreground node should appear first
        assert batch[0].id == "t1"

    def test_end_to_end_attention_scenario(self):
        """End-to-end: focus + relevance + background demotion + budget limiting."""
        am = AttentionManager()

        # Simulate 3 prior requests about reading files
        am.update_focus("read config files", "configuration")
        am.update_focus("read config files", "configuration")
        am.update_focus("read config files", "configuration")

        # Submit 5 tasks
        entries = [
            _make_entry("rf1", intent="read_file", urgency=0.5),          # fg, relevant
            _make_entry("rf2", intent="read_file", urgency=0.5),          # fg, relevant
            _make_entry("rf_bg", intent="read_file", urgency=0.5, is_background=True),  # bg
            _make_entry("hf1", intent="http_fetch", urgency=0.5),         # fg, less relevant
            _make_entry("rc1", intent="run_command", urgency=0.5),        # fg, less relevant
        ]
        for e in entries:
            am.submit(e)

        batch = am.get_next_batch(budget=3)
        batch_ids = [e.task_id for e in batch]

        # Both foreground read_file tasks should be in the batch (boosted by focus)
        assert "rf1" in batch_ids
        assert "rf2" in batch_ids
        # Background read_file should NOT be in top 3
        assert "rf_bg" not in batch_ids
        # The 3rd slot goes to one of the non-file foreground tasks
        assert len(batch_ids) == 3
