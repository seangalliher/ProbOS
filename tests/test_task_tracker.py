"""Tests for TaskTracker service (AD-316)."""

import unittest
import time

from probos.task_tracker import (
    TaskTracker, TaskType, TaskStatus, StepStatus, AgentTask, TaskStep,
)


class TestTaskStep(unittest.TestCase):
    def test_start_sets_status_and_time(self) -> None:
        step = TaskStep(label="Build code")
        step.start()
        assert step.status == StepStatus.IN_PROGRESS
        assert step.started_at > 0

    def test_complete_sets_status_and_duration(self) -> None:
        step = TaskStep(label="Build code")
        step.start()
        step.complete()
        assert step.status == StepStatus.DONE
        assert step.duration_ms >= 0

    def test_fail_sets_status_and_duration(self) -> None:
        step = TaskStep(label="Build code")
        step.start()
        step.fail()
        assert step.status == StepStatus.FAILED
        assert step.duration_ms >= 0

    def test_complete_without_start_no_duration(self) -> None:
        step = TaskStep(label="Build code")
        step.complete()
        assert step.status == StepStatus.DONE
        assert step.duration_ms == 0.0

    def test_to_dict(self) -> None:
        step = TaskStep(label="Test")
        d = step.to_dict()
        assert d["label"] == "Test"
        assert d["status"] == "pending"
        assert "started_at" in d
        assert "duration_ms" in d


class TestAgentTask(unittest.TestCase):
    def test_defaults(self) -> None:
        task = AgentTask()
        assert task.status == TaskStatus.QUEUED
        assert task.requires_action is False
        assert len(task.id) == 12

    def test_start(self) -> None:
        task = AgentTask()
        task.start()
        assert task.status == TaskStatus.WORKING
        assert task.started_at > 0

    def test_set_review(self) -> None:
        task = AgentTask()
        task.set_review("approve")
        assert task.status == TaskStatus.REVIEW
        assert task.requires_action is True
        assert task.action_type == "approve"

    def test_complete(self) -> None:
        task = AgentTask()
        task.start()
        task.complete()
        assert task.status == TaskStatus.DONE
        assert task.completed_at > 0
        assert task.requires_action is False
        assert task.action_type == ""

    def test_fail(self) -> None:
        task = AgentTask()
        task.start()
        task.fail("something broke")
        assert task.status == TaskStatus.FAILED
        assert task.error == "something broke"
        assert task.completed_at > 0
        assert task.requires_action is False

    def test_add_step(self) -> None:
        task = AgentTask()
        step = task.add_step("Preparing")
        assert isinstance(step, TaskStep)
        assert step.label == "Preparing"
        assert len(task.steps) == 1

    def test_current_step(self) -> None:
        task = AgentTask()
        assert task.current_step() is None
        step = task.add_step("A")
        step.start()
        assert task.current_step() is step

    def test_step_progress(self) -> None:
        task = AgentTask()
        task.add_step("A").start()
        task.steps[0].complete()
        task.add_step("B").start()
        done, total = task.step_progress()
        assert done == 1
        assert total == 2

    def test_to_dict_includes_all_fields(self) -> None:
        task = AgentTask(
            agent_id="a1", agent_type="builder", department="engineering",
            task_type=TaskType.BUILD, title="Build it", priority=2, ad_number=100,
        )
        task.add_step("Step 1").start()
        task.steps[0].complete()
        d = task.to_dict()
        assert d["id"] == task.id
        assert d["agent_type"] == "builder"
        assert d["type"] == "build"
        assert d["step_current"] == 1
        assert d["step_total"] == 1
        assert d["priority"] == 2
        assert d["ad_number"] == 100


class TestTaskTracker(unittest.TestCase):
    def setUp(self) -> None:
        self.events: list[tuple[str, dict]] = []

        def on_event(event_type: str, data: dict) -> None:
            self.events.append((event_type, data))

        self.tracker = TaskTracker(on_event=on_event)

    def test_empty_state(self) -> None:
        assert self.tracker.all_tasks() == []
        assert self.tracker.active_tasks() == []
        assert self.tracker.snapshot() == []

    def test_create_task(self) -> None:
        task = self.tracker.create_task(
            agent_id="a1", agent_type="builder", department="engineering",
            task_type=TaskType.BUILD, title="Build widget",
        )
        assert task.title == "Build widget"
        assert task.status == TaskStatus.QUEUED
        assert len(self.events) == 1
        assert self.events[0][0] == "task_created"

    def test_start_task(self) -> None:
        task = self.tracker.create_task(title="Test")
        self.tracker.start_task(task.id)
        assert task.status == TaskStatus.WORKING
        assert task.started_at > 0
        assert len(self.events) == 2  # created + updated

    def test_advance_step_first_call(self) -> None:
        task = self.tracker.create_task(title="Test")
        step = self.tracker.advance_step(task.id, "Step A")
        assert step is not None
        assert step.label == "Step A"
        assert step.status == StepStatus.IN_PROGRESS
        assert len(task.steps) == 1

    def test_advance_step_completes_current(self) -> None:
        task = self.tracker.create_task(title="Test")
        self.tracker.advance_step(task.id, "Step A")
        self.tracker.advance_step(task.id, "Step B")
        assert task.steps[0].status == StepStatus.DONE
        assert task.steps[1].status == StepStatus.IN_PROGRESS

    def test_complete_step(self) -> None:
        task = self.tracker.create_task(title="Test")
        self.tracker.advance_step(task.id, "Step A")
        self.tracker.complete_step(task.id)
        assert task.steps[0].status == StepStatus.DONE

    def test_complete_task(self) -> None:
        task = self.tracker.create_task(title="Test")
        self.tracker.start_task(task.id)
        self.tracker.advance_step(task.id, "Step A")
        self.tracker.complete_task(task.id)
        assert task.status == TaskStatus.DONE
        assert task.completed_at > 0
        # Lingering step should be completed
        assert task.steps[0].status == StepStatus.DONE

    def test_fail_task(self) -> None:
        task = self.tracker.create_task(title="Test")
        self.tracker.start_task(task.id)
        self.tracker.advance_step(task.id, "Step A")
        self.tracker.fail_task(task.id, "broken")
        assert task.status == TaskStatus.FAILED
        assert task.error == "broken"
        # Lingering step should be failed
        assert task.steps[0].status == StepStatus.FAILED

    def test_set_review(self) -> None:
        task = self.tracker.create_task(title="Test")
        self.tracker.set_review(task.id, "approve")
        assert task.status == TaskStatus.REVIEW
        assert task.requires_action is True
        assert task.action_type == "approve"

    def test_active_tasks(self) -> None:
        t1 = self.tracker.create_task(title="Active")
        t2 = self.tracker.create_task(title="Done")
        self.tracker.complete_task(t2.id)
        active = self.tracker.active_tasks()
        assert len(active) == 1
        assert active[0].id == t1.id

    def test_needs_attention(self) -> None:
        t1 = self.tracker.create_task(title="Normal")
        t2 = self.tracker.create_task(title="Needs attention")
        self.tracker.set_review(t2.id)
        attention = self.tracker.needs_attention()
        assert len(attention) == 1
        assert attention[0].id == t2.id

    def test_snapshot(self) -> None:
        self.tracker.create_task(title="A")
        self.tracker.create_task(title="B")
        snap = self.tracker.snapshot()
        assert len(snap) == 2
        assert all(isinstance(d, dict) for d in snap)

    def test_event_contains_task_and_snapshot(self) -> None:
        self.tracker.create_task(title="Test")
        _, data = self.events[0]
        assert "task" in data
        assert "tasks" in data
        assert isinstance(data["tasks"], list)

    def test_prune_done(self) -> None:
        self.tracker._max_done = 3
        for i in range(5):
            task = self.tracker.create_task(title=f"Task {i}")
            task.completed_at = time.time() + i  # ensure ordering
            self.tracker.complete_task(task.id)
        # Should have pruned to max_done
        done = [t for t in self.tracker.all_tasks()
                if t.status == TaskStatus.DONE]
        assert len(done) <= 3

    def test_advance_step_nonexistent_task(self) -> None:
        result = self.tracker.advance_step("nonexistent", "Step")
        assert result is None

    def test_get_task(self) -> None:
        task = self.tracker.create_task(title="Find me")
        found = self.tracker.get_task(task.id)
        assert found is task
        assert self.tracker.get_task("nope") is None


if __name__ == "__main__":
    unittest.main()
