"""Tests for PersistentTaskStore (Phase 25a)."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.persistent_tasks import PersistentTask, PersistentTaskStore


@pytest.fixture
def tmp_db(tmp_path):
    """Return path for a temporary SQLite database."""
    return str(tmp_path / "test_tasks.db")


@pytest.fixture
def mock_emit():
    return MagicMock()


@pytest.fixture
def mock_process_fn():
    """Mock process_fn that returns a simple result."""
    fn = AsyncMock(return_value={"response": "Task processed", "success": True})
    return fn


@pytest.fixture
async def store(tmp_db, mock_emit, mock_process_fn):
    """Create, start, yield, and stop a PersistentTaskStore."""
    s = PersistentTaskStore(
        db_path=tmp_db,
        emit_event=mock_emit,
        process_fn=mock_process_fn,
        tick_interval=100,  # High interval to prevent auto-ticking in tests
    )
    await s.start()
    yield s
    await s.stop()


# ---------------------------------------------------------------------------
# Lifecycle tests
# ---------------------------------------------------------------------------

class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_stop(self, tmp_db, mock_emit):
        store = PersistentTaskStore(db_path=tmp_db, emit_event=mock_emit, tick_interval=100)
        await store.start()
        assert store._db is not None
        assert store._running is True
        await store.stop()
        assert store._db is None
        assert store._running is False

    @pytest.mark.asyncio
    async def test_start_idempotent_schema(self, tmp_db, mock_emit):
        """Starting twice with same DB doesn't fail."""
        s1 = PersistentTaskStore(db_path=tmp_db, emit_event=mock_emit, tick_interval=100)
        await s1.start()
        await s1.stop()
        s2 = PersistentTaskStore(db_path=tmp_db, emit_event=mock_emit, tick_interval=100)
        await s2.start()
        assert s2._db is not None
        await s2.stop()

    @pytest.mark.asyncio
    async def test_start_without_db(self, mock_emit):
        """Store works without a db_path (in-memory mode)."""
        store = PersistentTaskStore(db_path=None, emit_event=mock_emit, tick_interval=100)
        await store.start()
        assert store._db is None
        tasks = await store.list_tasks()
        assert tasks == []
        await store.stop()


# ---------------------------------------------------------------------------
# Create task tests
# ---------------------------------------------------------------------------

class TestCreateTask:
    @pytest.mark.asyncio
    async def test_create_once(self, store, mock_emit):
        task = await store.create_task(
            intent_text="Run daily report",
            schedule_type="once",
            execute_at=time.time() + 3600,
        )
        assert task.id
        assert task.schedule_type == "once"
        assert task.status == "pending"
        assert task.next_run_at is not None
        mock_emit.assert_any_call("scheduled_task_created", pytest.approx(store._task_to_dict(task), abs=1))

    @pytest.mark.asyncio
    async def test_create_interval(self, store):
        task = await store.create_task(
            intent_text="Check system health",
            schedule_type="interval",
            interval_seconds=300,
        )
        assert task.schedule_type == "interval"
        assert task.interval_seconds == 300
        assert task.next_run_at is not None
        assert task.next_run_at > time.time()

    @pytest.mark.asyncio
    async def test_create_cron(self, store):
        task = await store.create_task(
            intent_text="Nightly cleanup",
            schedule_type="cron",
            cron_expr="0 2 * * *",
        )
        assert task.schedule_type == "cron"
        assert task.cron_expr == "0 2 * * *"
        assert task.next_run_at is not None

    @pytest.mark.asyncio
    async def test_create_invalid_schedule_type(self, store):
        with pytest.raises(ValueError, match="Invalid schedule_type"):
            await store.create_task(
                intent_text="Bad task",
                schedule_type="invalid",
            )

    @pytest.mark.asyncio
    async def test_create_with_webhook_name(self, store):
        task = await store.create_task(
            intent_text="Webhook handler",
            schedule_type="once",
            webhook_name="deploy-hook",
            execute_at=time.time() + 99999,  # Far future — only triggers via webhook
        )
        assert task.webhook_name == "deploy-hook"

    @pytest.mark.asyncio
    async def test_create_defaults(self, store):
        task = await store.create_task(intent_text="Simple task")
        assert task.name == "Simple task"  # name defaults to intent_text[:60]
        assert task.schedule_type == "once"
        assert task.created_by == "captain"
        assert task.run_count == 0
        assert task.enabled is True


# ---------------------------------------------------------------------------
# Task execution tests
# ---------------------------------------------------------------------------

class TestTaskExecution:
    @pytest.mark.asyncio
    async def test_fire_once_completes(self, store, mock_process_fn):
        task = await store.create_task(
            intent_text="One-shot task",
            schedule_type="once",
            execute_at=time.time() - 1,  # Already due
        )
        await store._execute_due_tasks()
        mock_process_fn.assert_awaited_once()
        updated = await store.get_task(task.id)
        assert updated.status == "completed"
        assert updated.run_count == 1

    @pytest.mark.asyncio
    async def test_fire_interval_reschedules(self, store, mock_process_fn):
        task = await store.create_task(
            intent_text="Recurring task",
            schedule_type="interval",
            interval_seconds=60,
        )
        # Force next_run_at to be in the past
        await store._db.execute(
            "UPDATE scheduled_tasks SET next_run_at = ? WHERE id = ?",
            (time.time() - 1, task.id),
        )
        await store._db.commit()

        await store._execute_due_tasks()
        mock_process_fn.assert_awaited_once()
        updated = await store.get_task(task.id)
        assert updated.status == "pending"  # Not completed — rescheduled
        assert updated.run_count == 1
        assert updated.next_run_at > time.time()  # Next run in the future

    @pytest.mark.asyncio
    async def test_max_runs_enforcement(self, store, mock_process_fn):
        task = await store.create_task(
            intent_text="Limited task",
            schedule_type="interval",
            interval_seconds=60,
            max_runs=1,
        )
        await store._db.execute(
            "UPDATE scheduled_tasks SET next_run_at = ? WHERE id = ?",
            (time.time() - 1, task.id),
        )
        await store._db.commit()

        await store._execute_due_tasks()
        updated = await store.get_task(task.id)
        assert updated.status == "completed"  # max_runs=1, ran once → completed
        assert updated.run_count == 1

    @pytest.mark.asyncio
    async def test_channel_delivery(self, store, mock_process_fn):
        task = await store.create_task(
            intent_text="Channel task",
            schedule_type="once",
            execute_at=time.time() - 1,
            channel_id="test-channel",
        )
        await store._execute_due_tasks()
        mock_process_fn.assert_awaited_once_with(
            "Channel task",
            channel_id="test-channel",
        )

    @pytest.mark.asyncio
    async def test_fire_failure_marks_failed(self, store, mock_process_fn):
        mock_process_fn.side_effect = RuntimeError("LLM exploded")
        task = await store.create_task(
            intent_text="Failing task",
            schedule_type="once",
            execute_at=time.time() - 1,
        )
        await store._execute_due_tasks()
        updated = await store.get_task(task.id)
        assert updated.status == "failed"
        assert "LLM exploded" in (updated.last_result or "")


# ---------------------------------------------------------------------------
# Cancel tests
# ---------------------------------------------------------------------------

class TestCancelTask:
    @pytest.mark.asyncio
    async def test_cancel(self, store):
        task = await store.create_task(intent_text="Cancel me")
        cancelled = await store.cancel_task(task.id)
        assert cancelled is True
        updated = await store.get_task(task.id)
        assert updated.status == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_idempotent(self, store):
        task = await store.create_task(intent_text="Cancel me")
        await store.cancel_task(task.id)
        cancelled_again = await store.cancel_task(task.id)
        assert cancelled_again is False  # Already cancelled

    @pytest.mark.asyncio
    async def test_cancel_nonexistent(self, store):
        cancelled = await store.cancel_task("nonexistent-id")
        assert cancelled is False


# ---------------------------------------------------------------------------
# Webhook tests
# ---------------------------------------------------------------------------

class TestWebhookTrigger:
    @pytest.mark.asyncio
    async def test_trigger_by_name(self, store):
        task = await store.create_task(
            intent_text="Webhook task",
            schedule_type="once",
            webhook_name="my-hook",
            execute_at=time.time() + 99999,
        )
        triggered = await store.trigger_webhook("my-hook")
        assert triggered is not None
        assert triggered.next_run_at <= time.time() + 1  # Should be ~now

    @pytest.mark.asyncio
    async def test_trigger_not_found(self, store):
        triggered = await store.trigger_webhook("nonexistent")
        assert triggered is None

    @pytest.mark.asyncio
    async def test_webhook_fires_on_tick(self, store, mock_process_fn):
        task = await store.create_task(
            intent_text="Webhook fires",
            schedule_type="once",
            webhook_name="fire-hook",
            execute_at=time.time() + 99999,
        )
        await store.trigger_webhook("fire-hook")
        await store._execute_due_tasks()
        mock_process_fn.assert_awaited_once()


# ---------------------------------------------------------------------------
# Persistence tests
# ---------------------------------------------------------------------------

class TestPersistence:
    @pytest.mark.asyncio
    async def test_tasks_survive_restart(self, tmp_db, mock_emit, mock_process_fn):
        """Tasks created in session 1 are visible in session 2."""
        s1 = PersistentTaskStore(
            db_path=tmp_db, emit_event=mock_emit,
            process_fn=mock_process_fn, tick_interval=100,
        )
        await s1.start()
        await s1.create_task(intent_text="Survive restart", schedule_type="interval", interval_seconds=300)
        await s1.stop()

        s2 = PersistentTaskStore(
            db_path=tmp_db, emit_event=mock_emit,
            process_fn=mock_process_fn, tick_interval=100,
        )
        await s2.start()
        tasks = await s2.list_tasks()
        assert len(tasks) == 1
        assert tasks[0].intent_text == "Survive restart"
        assert tasks[0].status == "pending"
        await s2.stop()

    @pytest.mark.asyncio
    async def test_status_preserved(self, tmp_db, mock_emit, mock_process_fn):
        """Cancelled status persists across restart."""
        s1 = PersistentTaskStore(
            db_path=tmp_db, emit_event=mock_emit,
            process_fn=mock_process_fn, tick_interval=100,
        )
        await s1.start()
        task = await s1.create_task(intent_text="Will cancel", execute_at=time.time() + 99999)
        await s1.cancel_task(task.id)
        await s1.stop()

        s2 = PersistentTaskStore(
            db_path=tmp_db, emit_event=mock_emit,
            process_fn=mock_process_fn, tick_interval=100,
        )
        await s2.start()
        restored = await s2.get_task(task.id)
        assert restored.status == "cancelled"
        await s2.stop()


# ---------------------------------------------------------------------------
# DAG resume tests
# ---------------------------------------------------------------------------

class TestDagResume:
    @pytest.mark.asyncio
    async def test_stale_checkpoint_detected(self, tmp_path, mock_emit):
        """Stale checkpoints emit events on start."""
        cp_dir = tmp_path / "checkpoints"
        cp_dir.mkdir()
        checkpoint = {
            "checkpoint_id": "test-dag-1",
            "dag_id": "test-dag-1",
            "source_text": "Do something important",
            "created_at": "2025-01-01T00:00:00",
            "updated_at": "2025-01-01T00:01:00",
            "node_states": {"n1": {"status": "completed"}, "n2": {"status": "running"}},
            "dag_json": {"nodes": [], "source_text": "Do something important"},
        }
        (cp_dir / "test-dag-1.json").write_text(json.dumps(checkpoint))

        store = PersistentTaskStore(
            db_path=str(tmp_path / "tasks.db"),
            emit_event=mock_emit,
            checkpoint_dir=str(cp_dir),
            tick_interval=100,
        )
        await store.start()
        mock_emit.assert_any_call("scheduled_task_dag_stale", {
            "dag_id": "test-dag-1",
            "source_text": "Do something important",
            "completed_nodes": 1,
            "total_nodes": 2,
            "updated_at": "2025-01-01T00:01:00",
        })
        await store.stop()

    @pytest.mark.asyncio
    async def test_resume_not_found(self, store):
        """Resuming a non-existent DAG returns error."""
        result = await store.resume_dag("nonexistent-dag-id")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_resume_no_checkpoint_dir(self, tmp_db, mock_emit, mock_process_fn):
        """Resume with no checkpoint_dir returns error."""
        store = PersistentTaskStore(
            db_path=tmp_db, emit_event=mock_emit,
            process_fn=mock_process_fn, tick_interval=100,
            checkpoint_dir=None,
        )
        await store.start()
        result = await store.resume_dag("any-id")
        assert result == {"error": "No checkpoint directory configured"}
        await store.stop()


# ---------------------------------------------------------------------------
# Event emission tests
# ---------------------------------------------------------------------------

class TestEventEmission:
    @pytest.mark.asyncio
    async def test_create_emits_event(self, store, mock_emit):
        mock_emit.reset_mock()
        task = await store.create_task(intent_text="Emit test")
        calls = [c for c in mock_emit.call_args_list if c[0][0] == "scheduled_task_created"]
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_fire_emits_events(self, store, mock_emit, mock_process_fn):
        task = await store.create_task(
            intent_text="Fire emit test",
            schedule_type="once",
            execute_at=time.time() - 1,
        )
        mock_emit.reset_mock()
        await store._execute_due_tasks()
        event_types = [c[0][0] for c in mock_emit.call_args_list]
        assert "scheduled_task_fired" in event_types
        assert "scheduled_task_updated" in event_types

    @pytest.mark.asyncio
    async def test_cancel_emits_event(self, store, mock_emit):
        task = await store.create_task(intent_text="Cancel emit test")
        mock_emit.reset_mock()
        await store.cancel_task(task.id)
        mock_emit.assert_any_call("scheduled_task_cancelled", {"task_id": task.id})


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------

class TestConfig:
    def test_defaults(self):
        from probos.config import PersistentTasksConfig
        cfg = PersistentTasksConfig()
        assert cfg.enabled is False
        assert cfg.tick_interval_seconds == 5.0
        assert cfg.max_concurrent_executions == 1
        assert cfg.dag_auto_resume is False

    def test_system_config_integration(self):
        from probos.config import SystemConfig
        cfg = SystemConfig()
        assert hasattr(cfg, "persistent_tasks")
        assert cfg.persistent_tasks.enabled is False


# ---------------------------------------------------------------------------
# Snapshot tests
# ---------------------------------------------------------------------------

class TestSnapshot:
    @pytest.mark.asyncio
    async def test_snapshot_returns_pending(self, store):
        await store.create_task(intent_text="Pending task")
        snap = store.snapshot()
        assert len(snap) == 1
        assert snap[0]["status"] == "pending"

    @pytest.mark.asyncio
    async def test_snapshot_excludes_completed(self, store, mock_process_fn):
        task = await store.create_task(
            intent_text="Complete me",
            schedule_type="once",
            execute_at=time.time() - 1,
        )
        await store._execute_due_tasks()
        snap = store.snapshot()
        assert len(snap) == 0  # Completed tasks not in snapshot

    @pytest.mark.asyncio
    async def test_snapshot_sync_safe(self, store):
        """Snapshot is sync-callable (no await needed)."""
        await store.create_task(intent_text="Sync test")
        # snapshot() is a regular method, not async
        result = store.snapshot()
        assert isinstance(result, list)
