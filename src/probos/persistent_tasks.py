"""PersistentTaskStore — SQLite-backed scheduled tasks (Phase 25a).

Runs alongside the in-memory TaskScheduler. TaskScheduler handles transient
session-scoped tasks with monotonic time; PersistentTaskStore handles
user-created scheduled tasks with wall-clock awareness, cron support,
and SQLite persistence. Tasks survive server restarts.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

import aiosqlite

from probos.events import EventType

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class PersistentTask:
    """A single persistent scheduled task."""

    id: str
    name: str
    intent_text: str
    created_at: float
    schedule_type: str = "once"        # once | interval | cron
    execute_at: float | None = None    # wall-clock epoch for one-shot
    interval_seconds: float | None = None  # for interval-based
    cron_expr: str | None = None       # for cron-based (croniter format)
    channel_id: str | None = None
    status: str = "pending"            # pending | running | completed | failed | cancelled
    last_result: str | None = None     # JSON string
    last_run_at: float | None = None
    next_run_at: float | None = None   # computed next fire time
    run_count: int = 0
    max_runs: int | None = None        # None = unlimited
    created_by: str = "captain"
    webhook_name: str | None = None
    enabled: bool = True
    agent_hint: str | None = None     # AD-418: preferred agent_type for routing bias


# ---------------------------------------------------------------------------
# SQLite schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    intent_text TEXT NOT NULL,
    created_at REAL NOT NULL,
    schedule_type TEXT NOT NULL DEFAULT 'once',
    execute_at REAL,
    interval_seconds REAL,
    cron_expr TEXT,
    channel_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    last_result TEXT,
    last_run_at REAL,
    next_run_at REAL,
    run_count INTEGER NOT NULL DEFAULT 0,
    max_runs INTEGER,
    created_by TEXT NOT NULL DEFAULT 'captain',
    webhook_name TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    agent_hint TEXT
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON scheduled_tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_webhook ON scheduled_tasks(webhook_name);
"""

_VALID_SCHEDULE_TYPES = {"once", "interval", "cron"}


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class PersistentTaskStore:
    """SQLite-backed persistent task scheduling.

    Follows the AssignmentService lifecycle pattern: start() opens DB +
    creates schema, stop() closes DB. A background tick loop fires due
    tasks and computes next_run_at.
    """

    def __init__(
        self,
        db_path: str | None = None,
        emit_event: Any = None,
        process_fn: Callable[..., Awaitable[dict]] | None = None,
        tick_interval: float = 5.0,
        checkpoint_dir: Any = None,    # Path to DAG checkpoint directory
    ):
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None
        self._emit_event = emit_event
        self._process_fn = process_fn
        self._tick_interval = tick_interval
        self._checkpoint_dir = checkpoint_dir
        self._tick_task: asyncio.Task | None = None
        self._snapshot_cache: list[dict[str, Any]] = []
        self._running = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Open DB, create schema, scan for stale DAG checkpoints."""
        if self.db_path:
            self._db = await aiosqlite.connect(self.db_path)
            await self._db.execute("PRAGMA foreign_keys = ON")
            self._db.row_factory = aiosqlite.Row
            await self._db.executescript(_SCHEMA)
            await self._db.commit()

            # AD-418: Migrate agent_hint column
            try:
                await self._db.execute("ALTER TABLE scheduled_tasks ADD COLUMN agent_hint TEXT")
                await self._db.commit()
            except Exception:
                pass  # Column already exists

        # Scan for stale DAG checkpoints and emit events
        await self._scan_stale_checkpoints()

        # Warm snapshot cache
        await self._refresh_snapshot_cache()

        # Start tick loop
        self._running = True
        self._tick_task = asyncio.create_task(self._tick_loop())
        logger.info("PersistentTaskStore started (tick=%.1fs)", self._tick_interval)

    async def stop(self) -> None:
        """Stop tick loop and close DB."""
        self._running = False
        if self._tick_task:
            self._tick_task.cancel()
            try:
                await self._tick_task
            except asyncio.CancelledError:
                pass
            self._tick_task = None
        if self._db:
            await self._db.close()
            self._db = None
        logger.info("PersistentTaskStore stopped")

    # ------------------------------------------------------------------
    # Event emission
    # ------------------------------------------------------------------

    def _emit(self, event_type: str, data: dict[str, Any]) -> None:
        if self._emit_event:
            self._emit_event(event_type, data)

    # ------------------------------------------------------------------
    # Task CRUD
    # ------------------------------------------------------------------

    async def create_task(
        self,
        intent_text: str,
        schedule_type: str = "once",
        name: str = "",
        execute_at: float | None = None,
        interval_seconds: float | None = None,
        cron_expr: str | None = None,
        channel_id: str | None = None,
        max_runs: int | None = None,
        created_by: str = "captain",
        webhook_name: str | None = None,
        agent_hint: str | None = None,    # AD-418
    ) -> PersistentTask:
        """Create and persist a new scheduled task."""
        if schedule_type not in _VALID_SCHEDULE_TYPES:
            raise ValueError(f"Invalid schedule_type: {schedule_type}")

        task_id = uuid.uuid4().hex[:12]
        now = time.time()

        # Compute next_run_at based on schedule type
        next_run_at = self._compute_next_run(
            schedule_type=schedule_type,
            execute_at=execute_at,
            interval_seconds=interval_seconds,
            cron_expr=cron_expr,
            now=now,
        )

        task = PersistentTask(
            id=task_id,
            name=name or intent_text[:60],
            intent_text=intent_text,
            created_at=now,
            schedule_type=schedule_type,
            execute_at=execute_at,
            interval_seconds=interval_seconds,
            cron_expr=cron_expr,
            channel_id=channel_id,
            next_run_at=next_run_at,
            max_runs=max_runs,
            created_by=created_by,
            webhook_name=webhook_name,
            agent_hint=agent_hint,
        )

        if self._db:
            await self._db.execute(
                """INSERT INTO scheduled_tasks
                   (id, name, intent_text, created_at, schedule_type,
                    execute_at, interval_seconds, cron_expr, channel_id,
                    status, next_run_at, run_count, max_runs, created_by,
                    webhook_name, enabled, agent_hint)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    task.id, task.name, task.intent_text, task.created_at,
                    task.schedule_type, task.execute_at, task.interval_seconds,
                    task.cron_expr, task.channel_id, task.status,
                    task.next_run_at, task.run_count, task.max_runs,
                    task.created_by, task.webhook_name, 1, task.agent_hint,
                ),
            )
            await self._db.commit()

        self._emit(EventType.SCHEDULED_TASK_CREATED, self._task_to_dict(task))
        await self._refresh_snapshot_cache()
        logger.info("Created persistent task %s: %s (%s)", task.id, task.name, schedule_type)
        return task

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a task by ID. Returns True if found and cancelled."""
        if not self._db:
            return False
        cursor = await self._db.execute(
            "UPDATE scheduled_tasks SET status = 'cancelled', enabled = 0 WHERE id = ? AND status NOT IN ('cancelled', 'completed')",
            (task_id,),
        )
        await self._db.commit()
        if cursor.rowcount > 0:
            self._emit(EventType.SCHEDULED_TASK_CANCELLED, {"task_id": task_id})
            await self._refresh_snapshot_cache()
            logger.info("Cancelled persistent task %s", task_id)
            return True
        return False

    async def list_tasks(
        self,
        status: str | None = None,
        limit: int = 50,
    ) -> list[PersistentTask]:
        """List tasks with optional status filter."""
        if not self._db:
            return []
        if status:
            cursor = await self._db.execute(
                "SELECT * FROM scheduled_tasks WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            )
        else:
            cursor = await self._db.execute(
                "SELECT * FROM scheduled_tasks ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        rows = await cursor.fetchall()
        return [self._row_to_task(row) for row in rows]

    async def get_task(self, task_id: str) -> PersistentTask | None:
        """Fetch a single task by ID."""
        if not self._db:
            return None
        cursor = await self._db.execute(
            "SELECT * FROM scheduled_tasks WHERE id = ?", (task_id,),
        )
        row = await cursor.fetchone()
        return self._row_to_task(row) if row else None

    async def trigger_webhook(self, webhook_name: str) -> PersistentTask | None:
        """Trigger a webhook task by name — sets next_run_at to now."""
        if not self._db:
            return None
        cursor = await self._db.execute(
            "SELECT * FROM scheduled_tasks WHERE webhook_name = ? AND status = 'pending' AND enabled = 1",
            (webhook_name,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        task = self._row_to_task(row)
        now = time.time()
        await self._db.execute(
            "UPDATE scheduled_tasks SET next_run_at = ? WHERE id = ?",
            (now, task.id),
        )
        await self._db.commit()
        task.next_run_at = now
        logger.info("Webhook triggered: %s (task %s)", webhook_name, task.id)
        return task

    # ------------------------------------------------------------------
    # DAG checkpoint resume
    # ------------------------------------------------------------------

    async def resume_dag(self, dag_id: str) -> dict[str, Any]:
        """Resume a stale DAG checkpoint by re-feeding it to process_fn.

        Returns the result from process_fn or an error dict.
        """
        from pathlib import Path
        from probos.cognitive.checkpoint import load_checkpoint, restore_dag, delete_checkpoint

        if not self._checkpoint_dir:
            return {"error": "No checkpoint directory configured"}

        checkpoint_path = Path(self._checkpoint_dir) / f"{dag_id}.json"
        if not checkpoint_path.exists():
            return {"error": f"Checkpoint not found: {dag_id}"}

        try:
            checkpoint = load_checkpoint(checkpoint_path)
            dag, results = restore_dag(checkpoint)
        except Exception as e:
            return {"error": f"Failed to restore checkpoint: {e}"}

        if not self._process_fn:
            return {"error": "No process function configured"}

        logger.info("Resuming DAG %s: '%s'", dag_id[:8], checkpoint.source_text[:60])

        try:
            result = await self._process_fn(
                checkpoint.source_text,
                channel_id=None,
            )
            # Clean up checkpoint on success
            delete_checkpoint(Path(self._checkpoint_dir), dag_id)
            self._emit(EventType.SCHEDULED_TASK_DAG_RESUMED, {
                "dag_id": dag_id,
                "source_text": checkpoint.source_text[:100],
                "result": str(result)[:200],
            })
            return {"success": True, "dag_id": dag_id, "result": result}
        except Exception as e:
            logger.exception("DAG resume failed: %s", dag_id[:8])
            return {"error": f"DAG resume failed: {e}"}

    # ------------------------------------------------------------------
    # Snapshot (sync access for build_state_snapshot)
    # ------------------------------------------------------------------

    def snapshot(self) -> list[dict[str, Any]]:
        """Return cached snapshot for build_state_snapshot (sync-safe)."""
        return list(self._snapshot_cache)

    async def _refresh_snapshot_cache(self) -> None:
        """Rebuild in-memory snapshot cache from DB."""
        tasks = await self.list_tasks(limit=100)
        self._snapshot_cache = [self._task_to_dict(t) for t in tasks if t.status in ("pending", "running")]

    # ------------------------------------------------------------------
    # Tick loop
    # ------------------------------------------------------------------

    async def _tick_loop(self) -> None:
        """Background loop: check for due tasks every tick_interval seconds."""
        while self._running:
            try:
                await self._execute_due_tasks()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("PersistentTaskStore tick error")
            try:
                await asyncio.sleep(self._tick_interval)
            except asyncio.CancelledError:
                break

    async def _execute_due_tasks(self) -> None:
        """Find and execute tasks whose next_run_at <= now."""
        if not self._db or not self._process_fn:
            return

        now = time.time()
        cursor = await self._db.execute(
            "SELECT * FROM scheduled_tasks WHERE enabled = 1 AND status = 'pending' AND next_run_at IS NOT NULL AND next_run_at <= ?",
            (now,),
        )
        rows = await cursor.fetchall()

        for row in rows:
            task = self._row_to_task(row)
            await self._fire_task(task)

    async def _fire_task(self, task: PersistentTask) -> None:
        """Execute a single task via process_fn."""
        if not self._process_fn or not self._db:
            return

        # Mark running
        await self._db.execute(
            "UPDATE scheduled_tasks SET status = 'running' WHERE id = ?",
            (task.id,),
        )
        await self._db.commit()

        self._emit(EventType.SCHEDULED_TASK_FIRED, {
            "task_id": task.id,
            "name": task.name,
            "intent_text": task.intent_text[:100],
        })

        try:
            result = await self._process_fn(
                task.intent_text,
                channel_id=task.channel_id,
                agent_hint=task.agent_hint,   # AD-418
            )
            result_json = json.dumps(result, default=str)[:2000]
        except Exception as e:
            logger.exception("Persistent task %s failed", task.id)
            result_json = json.dumps({"error": str(e)})
            await self._db.execute(
                "UPDATE scheduled_tasks SET status = 'failed', last_result = ?, last_run_at = ?, run_count = run_count + 1 WHERE id = ?",
                (result_json, time.time(), task.id),
            )
            await self._db.commit()
            self._emit(EventType.SCHEDULED_TASK_UPDATED, {"task_id": task.id, "status": "failed"})
            await self._refresh_snapshot_cache()
            return

        new_run_count = task.run_count + 1
        now = time.time()

        # Determine next state
        if task.schedule_type == "once":
            # One-shot: mark completed
            await self._db.execute(
                "UPDATE scheduled_tasks SET status = 'completed', last_result = ?, last_run_at = ?, run_count = ?, enabled = 0 WHERE id = ?",
                (result_json, now, new_run_count, task.id),
            )
        elif task.max_runs is not None and new_run_count >= task.max_runs:
            # Max runs reached: mark completed
            await self._db.execute(
                "UPDATE scheduled_tasks SET status = 'completed', last_result = ?, last_run_at = ?, run_count = ?, enabled = 0 WHERE id = ?",
                (result_json, now, new_run_count, task.id),
            )
        else:
            # Recurring: compute next fire time
            next_run = self._compute_next_run(
                schedule_type=task.schedule_type,
                execute_at=None,
                interval_seconds=task.interval_seconds,
                cron_expr=task.cron_expr,
                now=now,
            )
            await self._db.execute(
                "UPDATE scheduled_tasks SET status = 'pending', last_result = ?, last_run_at = ?, run_count = ?, next_run_at = ? WHERE id = ?",
                (result_json, now, new_run_count, next_run, task.id),
            )

        await self._db.commit()
        final_status = "completed" if (task.schedule_type == "once" or (task.max_runs and new_run_count >= task.max_runs)) else "pending"
        self._emit(EventType.SCHEDULED_TASK_UPDATED, {
            "task_id": task.id,
            "status": final_status,
            "run_count": new_run_count,
        })
        await self._refresh_snapshot_cache()
        logger.info("Persistent task %s fired (%s, run #%d)", task.id, task.schedule_type, new_run_count)

    # ------------------------------------------------------------------
    # Stale checkpoint scan
    # ------------------------------------------------------------------

    async def _scan_stale_checkpoints(self) -> None:
        """Scan for stale DAG checkpoints and emit notification events."""
        if not self._checkpoint_dir:
            return
        from pathlib import Path
        from probos.cognitive.checkpoint import scan_checkpoints

        checkpoint_dir = Path(self._checkpoint_dir)
        stale = scan_checkpoints(checkpoint_dir)
        if not stale:
            return

        logger.info("Found %d stale DAG checkpoint(s)", len(stale))
        for cp in stale:
            completed = sum(
                1 for s in cp.node_states.values()
                if s.get("status") == "completed"
            )
            self._emit(EventType.SCHEDULED_TASK_DAG_STALE, {
                "dag_id": cp.dag_id,
                "source_text": cp.source_text[:100],
                "completed_nodes": completed,
                "total_nodes": len(cp.node_states),
                "updated_at": cp.updated_at,
            })

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_next_run(
        schedule_type: str,
        execute_at: float | None,
        interval_seconds: float | None,
        cron_expr: str | None,
        now: float,
    ) -> float | None:
        """Compute the next fire time for a task."""
        if schedule_type == "once":
            return execute_at or now
        elif schedule_type == "interval":
            return now + (interval_seconds or 60)
        elif schedule_type == "cron":
            if not cron_expr:
                return now + 60  # fallback
            try:
                from croniter import croniter
                from datetime import datetime, timezone
                dt = datetime.fromtimestamp(now, tz=timezone.utc)
                cron = croniter(cron_expr, dt)
                next_dt = cron.get_next(datetime)
                return next_dt.timestamp()
            except ImportError:
                logger.warning("croniter not installed — falling back to 60s interval for cron task")
                return now + 60
            except Exception as e:
                logger.warning("Invalid cron expression %r: %s", cron_expr, e)
                return now + 60
        return None

    @staticmethod
    def _task_to_dict(task: PersistentTask) -> dict[str, Any]:
        """Convert a PersistentTask to a JSON-serializable dict."""
        return {
            "id": task.id,
            "name": task.name,
            "intent_text": task.intent_text,
            "created_at": task.created_at,
            "schedule_type": task.schedule_type,
            "execute_at": task.execute_at,
            "interval_seconds": task.interval_seconds,
            "cron_expr": task.cron_expr,
            "channel_id": task.channel_id,
            "status": task.status,
            "last_result": task.last_result,
            "last_run_at": task.last_run_at,
            "next_run_at": task.next_run_at,
            "run_count": task.run_count,
            "max_runs": task.max_runs,
            "created_by": task.created_by,
            "webhook_name": task.webhook_name,
            "enabled": task.enabled,
            "agent_hint": task.agent_hint,
        }

    @staticmethod
    def _row_to_task(row: Any) -> PersistentTask:
        """Convert an aiosqlite Row to a PersistentTask."""
        return PersistentTask(
            id=row["id"],
            name=row["name"],
            intent_text=row["intent_text"],
            created_at=row["created_at"],
            schedule_type=row["schedule_type"],
            execute_at=row["execute_at"],
            interval_seconds=row["interval_seconds"],
            cron_expr=row["cron_expr"],
            channel_id=row["channel_id"],
            status=row["status"],
            last_result=row["last_result"],
            last_run_at=row["last_run_at"],
            next_run_at=row["next_run_at"],
            run_count=row["run_count"],
            max_runs=row["max_runs"],
            created_by=row["created_by"],
            webhook_name=row["webhook_name"],
            enabled=bool(row["enabled"]),
            agent_hint=row["agent_hint"] if "agent_hint" in row.keys() else None,
        )
