"""Tests for AD-323: Agent Notification Queue."""

import time
import unittest
from unittest.mock import MagicMock

from probos.notifications import AgentNotification, NotificationQueue


class TestAgentNotification(unittest.TestCase):
    def test_to_dict(self) -> None:
        n = AgentNotification(
            id="abc123",
            agent_id="builder-001",
            agent_type="builder",
            department="engineering",
            notification_type="info",
            title="Build complete",
            detail="AD-323 merged successfully",
            action_url="task:abc",
            created_at=1000.0,
            acknowledged=False,
        )
        d = n.to_dict()
        assert d["id"] == "abc123"
        assert d["agent_type"] == "builder"
        assert d["department"] == "engineering"
        assert d["notification_type"] == "info"
        assert d["title"] == "Build complete"
        assert d["detail"] == "AD-323 merged successfully"
        assert d["action_url"] == "task:abc"
        assert d["created_at"] == 1000.0
        assert d["acknowledged"] is False


class TestNotificationQueue(unittest.TestCase):
    def setUp(self) -> None:
        self.events: list[tuple[str, dict]] = []
        self.queue = NotificationQueue(on_event=lambda t, d: self.events.append((t, d)))

    def test_notify_creates_notification(self) -> None:
        n = self.queue.notify(
            agent_id="builder-001",
            agent_type="builder",
            department="engineering",
            title="Build complete",
            detail="Tests passed",
        )
        assert n.title == "Build complete"
        assert n.agent_type == "builder"
        assert n.department == "engineering"
        assert n.detail == "Tests passed"
        assert n.notification_type == "info"
        assert n.acknowledged is False

    def test_notify_emits_event(self) -> None:
        self.queue.notify(
            agent_id="builder-001",
            agent_type="builder",
            department="engineering",
            title="Test notification",
        )
        assert len(self.events) == 1
        event_type, data = self.events[0]
        assert event_type == "notification"
        assert "notification" in data
        assert "notifications" in data
        assert data["unread_count"] == 1

    def test_acknowledge_marks_read(self) -> None:
        n = self.queue.notify(
            agent_id="builder-001",
            agent_type="builder",
            department="engineering",
            title="Ack test",
        )
        ok = self.queue.acknowledge(n.id)
        assert ok is True
        assert n.acknowledged is True
        assert self.queue.unread_count() == 0

    def test_acknowledge_nonexistent_returns_false(self) -> None:
        ok = self.queue.acknowledge("nonexistent-id")
        assert ok is False

    def test_acknowledge_all(self) -> None:
        for i in range(3):
            self.queue.notify(
                agent_id=f"agent-{i}",
                agent_type="builder",
                department="engineering",
                title=f"Notification {i}",
            )
        assert self.queue.unread_count() == 3
        count = self.queue.acknowledge_all()
        assert count == 3
        assert self.queue.unread_count() == 0

    def test_acknowledge_all_emits_snapshot(self) -> None:
        for i in range(2):
            self.queue.notify(
                agent_id=f"agent-{i}",
                agent_type="builder",
                department="engineering",
                title=f"Notification {i}",
            )
        self.events.clear()
        self.queue.acknowledge_all()
        assert len(self.events) == 1
        assert self.events[0][0] == "notification_snapshot"

    def test_snapshot_sorted_newest_first(self) -> None:
        n1 = self.queue.notify(
            agent_id="a", agent_type="builder", department="eng", title="First",
        )
        n1.created_at = 1000.0
        n2 = self.queue.notify(
            agent_id="b", agent_type="builder", department="eng", title="Second",
        )
        n2.created_at = 2000.0
        n3 = self.queue.notify(
            agent_id="c", agent_type="builder", department="eng", title="Third",
        )
        n3.created_at = 3000.0
        snap = self.queue.snapshot()
        assert snap[0]["title"] == "Third"
        assert snap[1]["title"] == "Second"
        assert snap[2]["title"] == "First"

    def test_prune_old_acknowledged(self) -> None:
        queue = NotificationQueue()
        queue._max_acknowledged = 5
        # Create 8 acknowledged notifications
        for i in range(8):
            n = queue.notify(
                agent_id=f"a-{i}",
                agent_type="builder",
                department="eng",
                title=f"N-{i}",
            )
            n.created_at = 1000.0 + i
            n.acknowledged = True
        # Trigger pruning
        queue._prune_acknowledged()
        # Should have 5 left (the 3 oldest pruned)
        assert len(queue._notifications) == 5
        titles = {n.title for n in queue._notifications.values()}
        # Oldest 3 (N-0, N-1, N-2) should be pruned
        assert "N-0" not in titles
        assert "N-1" not in titles
        assert "N-2" not in titles
        assert "N-7" in titles

    def test_unread_count(self) -> None:
        n1 = self.queue.notify(
            agent_id="a1", agent_type="builder", department="eng", title="One",
        )
        self.queue.notify(
            agent_id="a2", agent_type="builder", department="eng", title="Two",
        )
        self.queue.notify(
            agent_id="a3", agent_type="builder", department="eng", title="Three",
        )
        assert self.queue.unread_count() == 3
        self.queue.acknowledge(n1.id)
        assert self.queue.unread_count() == 2

    def test_no_event_without_callback(self) -> None:
        queue = NotificationQueue()  # no on_event
        n = queue.notify(
            agent_id="a", agent_type="builder", department="eng", title="Silent",
        )
        assert n.title == "Silent"
        # No exception raised

    def test_acknowledge_emits_ack_event(self) -> None:
        n = self.queue.notify(
            agent_id="a", agent_type="builder", department="eng", title="Ack",
        )
        self.events.clear()
        self.queue.acknowledge(n.id)
        assert len(self.events) == 1
        assert self.events[0][0] == "notification_ack"


class TestAD501Migration(unittest.TestCase):
    """AD-501: TaskTracker deprecation & NotificationQueue separation invariants."""

    def test_notifications_module_exists(self) -> None:
        """NotificationQueue + AgentNotification importable from probos.notifications."""
        from probos.notifications import AgentNotification as AN
        from probos.notifications import NotificationQueue as NQ
        assert NQ is NotificationQueue
        assert AN is AgentNotification

    def test_notification_queue_enqueue_dequeue(self) -> None:
        """Behavior preserved post-move: notify -> snapshot round-trip."""
        q = NotificationQueue()
        n = q.notify(agent_id="a1", agent_type="builder", department="eng", title="hello")
        snap = q.snapshot()
        assert len(snap) == 1
        assert snap[0]["id"] == n.id
        assert snap[0]["title"] == "hello"

    def test_notification_queue_priority_ordering(self) -> None:
        """Snapshot returns notifications newest-first (move-preserved invariant)."""
        q = NotificationQueue()
        n1 = AgentNotification(agent_id="a1", title="first", created_at=1000.0)
        n2 = AgentNotification(agent_id="a2", title="second", created_at=2000.0)
        q._notifications[n1.id] = n1
        q._notifications[n2.id] = n2
        snap = q.snapshot()
        assert snap[0]["title"] == "second"
        assert snap[1]["title"] == "first"

    def test_agent_notification_dataclass_fields(self) -> None:
        """AgentNotification dataclass contract preserved."""
        n = AgentNotification(agent_id="x", agent_type="builder", department="eng", title="t")
        assert n.acknowledged is False
        assert n.notification_type == "info"
        assert isinstance(n.id, str)
        assert isinstance(n.created_at, float)
        assert n.created_at > 0.0

    def test_runtime_no_task_tracker_attribute(self) -> None:
        """ProbOSRuntime no longer carries a `task_tracker` attribute (field removed)."""
        from probos.runtime import ProbOSRuntime
        # The dataclass annotation should be gone; instances no longer set the attribute.
        annotations = getattr(ProbOSRuntime, "__annotations__", {})
        assert "task_tracker" not in annotations

    def test_build_state_snapshot_no_tasks_key(self) -> None:
        """build_state_snapshot() no longer includes a `"tasks"` key."""
        import inspect
        from probos.runtime import ProbOSRuntime
        src = inspect.getsource(ProbOSRuntime.build_state_snapshot)
        assert '"tasks"' not in src
        assert "task_tracker.snapshot" not in src

    def test_task_tracker_module_deleted(self) -> None:
        """`probos.task_tracker` is removed; import raises ModuleNotFoundError."""
        import importlib
        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module("probos.task_tracker")

    def test_existing_notification_consumers_unbroken(self) -> None:
        """Conftest-style consumer pattern still works after the module move."""
        # Mirrors `tests/conftest.py:200` usage: spec=NotificationQueue.
        rt = MagicMock()
        rt.notification_queue = MagicMock(spec=NotificationQueue)
        rt.notification_queue.unread_count.return_value = 0
        rt.notification_queue.snapshot.return_value = []
        assert rt.notification_queue.unread_count() == 0
        assert rt.notification_queue.snapshot() == []
