# Phase 25a: Persistent Task Engine

## Context

ProbOS's TaskScheduler (AD-281) runs deferred and recurring tasks but is entirely in-memory — tasks vanish on restart. Its docstring literally says "persistent checkpointing is deferred to Phase 25." Meanwhile, the DAG checkpoint system (AD-405) can detect stale checkpoints at startup but never resumes them. Phase 25a makes scheduling persistent and wires up DAG resume.

**Key design decision: Wrap, Don't Replace.** Create a new `PersistentTaskStore` (SQLite-backed) that runs **alongside** the existing `TaskScheduler`, not replacing it. The in-memory TaskScheduler continues handling transient tasks with its 1-second monotonic tick. PersistentTaskStore handles user-created scheduled tasks with wall-clock awareness, cron support, and SQLite persistence. Both share the same `process_fn` (wired to `process_natural_language`) but don't interact.

**Follow the AssignmentService aiosqlite pattern** (`src/probos/assignment.py`): `_SCHEMA` string, `start()/stop()` lifecycle, `_db` attribute, `aiosqlite.connect()`.

---

## Part 1: Config — `src/probos/config.py` + `config/system.yaml`

### 1a. New PersistentTasksConfig class

Add **after** `ProactiveCognitiveConfig` (line 301) and **before** `DiscordConfig` (line 304):

```python
class PersistentTasksConfig(BaseModel):
    """Persistent Task Engine — SQLite-backed scheduled tasks (Phase 25a)."""
    enabled: bool = False
    tick_interval_seconds: float = 5.0
    max_concurrent_executions: int = 1   # Sequential by design
    dag_auto_resume: bool = False        # Future: auto-resume stale DAGs
```

### 1b. Add to SystemConfig

Add a new field to `SystemConfig` (currently lines 343-365). Add **after** `proactive_cognitive` (line 363) and **before** `channels` (line 364):

```python
    persistent_tasks: PersistentTasksConfig = PersistentTasksConfig()
```

### 1c. system.yaml

Add **after** the `proactive_cognitive:` section (line 249) and **before** `# --- Channel Adapters ---` (line 251):

```yaml
# --- Persistent Task Engine (Phase 25a) ---
persistent_tasks:
  enabled: true
  tick_interval_seconds: 5
  max_concurrent_executions: 1
  dag_auto_resume: false
```

---

## Part 2: Core Service — NEW `src/probos/persistent_tasks.py`

Create a new file `src/probos/persistent_tasks.py` (~280 lines). Follow the AssignmentService pattern from `src/probos/assignment.py`.

```python
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
    enabled INTEGER NOT NULL DEFAULT 1
);
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
            self._db.row_factory = aiosqlite.Row
            await self._db.executescript(_SCHEMA)
            await self._db.commit()

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
        )

        if self._db:
            await self._db.execute(
                """INSERT INTO scheduled_tasks
                   (id, name, intent_text, created_at, schedule_type,
                    execute_at, interval_seconds, cron_expr, channel_id,
                    status, next_run_at, run_count, max_runs, created_by,
                    webhook_name, enabled)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    task.id, task.name, task.intent_text, task.created_at,
                    task.schedule_type, task.execute_at, task.interval_seconds,
                    task.cron_expr, task.channel_id, task.status,
                    task.next_run_at, task.run_count, task.max_runs,
                    task.created_by, task.webhook_name, 1,
                ),
            )
            await self._db.commit()

        self._emit("scheduled_task_created", self._task_to_dict(task))
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
            self._emit("scheduled_task_cancelled", {"task_id": task_id})
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
            self._emit("scheduled_task_dag_resumed", {
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

        self._emit("scheduled_task_fired", {
            "task_id": task.id,
            "name": task.name,
            "intent_text": task.intent_text[:100],
        })

        try:
            result = await self._process_fn(
                task.intent_text,
                channel_id=task.channel_id,
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
            self._emit("scheduled_task_updated", {"task_id": task.id, "status": "failed"})
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
        self._emit("scheduled_task_updated", {
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
            self._emit("scheduled_task_dag_stale", {
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
        )
```

---

## Part 3: Dependencies — `pyproject.toml`

Add `croniter>=1.3` to the main `dependencies` list (line 21-32). Add it after `python-dotenv`:

```toml
    "croniter>=1.3",
```

---

## Part 4: Runtime Wiring — `src/probos/runtime.py`

### 4a. Attribute declaration

Add after `self.task_scheduler` (line 229):

```python
        # --- Persistent Task Store (Phase 25a) ---
        self.persistent_task_store: Any = None  # PersistentTaskStore | None
```

### 4b. Startup wiring

**Replace** the existing DAG checkpoint scan block (lines 1164-1181, everything from `# Scan for abandoned DAG checkpoints` through the `logger.info` loop) with the PersistentTaskStore initialization. The checkpoint scanning is now handled inside `PersistentTaskStore.start()`.

Replace lines 1164-1181 with:

```python
        # --- Persistent Task Store (Phase 25a) ---
        # Replaces the old checkpoint-scan-only block (AD-405).
        # PersistentTaskStore handles stale checkpoint detection internally.
        if self.config.persistent_tasks.enabled:
            from probos.persistent_tasks import PersistentTaskStore
            self.persistent_task_store = PersistentTaskStore(
                db_path=str(self._data_dir / "scheduled_tasks.db"),
                emit_event=self._emit_event,
                process_fn=self.process_natural_language,
                tick_interval=self.config.persistent_tasks.tick_interval_seconds,
                checkpoint_dir=self._checkpoint_dir,
            )
            await self.persistent_task_store.start()
            logger.info("persistent-task-store started")
        else:
            # Fallback: still scan checkpoints for logging (original AD-405 behavior)
            from probos.cognitive.checkpoint import scan_checkpoints
            stale = scan_checkpoints(self._checkpoint_dir)
            if stale:
                logger.info(
                    "Found %d incomplete DAG checkpoint(s) from previous session",
                    len(stale),
                )
                for cp in stale:
                    completed = sum(
                        1 for s in cp.node_states.values()
                        if s.get("status") == "completed"
                    )
                    logger.info(
                        "  - DAG %s: '%s' (%d/%d nodes completed)",
                        cp.dag_id[:8], cp.source_text[:60],
                        completed, len(cp.node_states),
                    )
```

### 4c. Shutdown

Add to `stop()` — add **after** the Proactive Cognitive Loop stop block (line 1269) and **before** the build dispatcher stop block (line 1271):

```python
        # Stop Persistent Task Store (Phase 25a)
        if self.persistent_task_store:
            await self.persistent_task_store.stop()
            self.persistent_task_store = None
```

### 4d. State snapshot

In `build_state_snapshot()` (return dict starting at line 465), add this field to the returned dict after `"notifications"` (line 477):

```python
            "scheduled_tasks": self.persistent_task_store.snapshot() if self.persistent_task_store else [],
```

---

## Part 5: REST API — `src/probos/api.py`

### 5a. Pydantic request model

Add at module scope, after the last request model (around line 230, after `ModifyMembersRequest`):

```python
class ScheduledTaskRequest(BaseModel):
    """Request to create a persistent scheduled task (Phase 25a)."""
    intent_text: str
    name: str = ""
    schedule_type: str = "once"   # once | interval | cron
    execute_at: float | None = None
    interval_seconds: float | None = None
    cron_expr: str | None = None
    channel_id: str | None = None
    max_runs: int | None = None
    created_by: str = "captain"
    webhook_name: str | None = None
```

### 5b. Route handlers

Add a new route group inside `create_app()`. Add **after** the Assignments route group (around line 1370) and **before** any helper functions or the WebSocket endpoint:

```python
    # --- Scheduled Tasks (Phase 25a) ---

    @app.get("/api/scheduled-tasks")
    async def list_scheduled_tasks(status: str | None = None) -> dict[str, Any]:
        """List persistent scheduled tasks."""
        if not runtime.persistent_task_store:
            return {"tasks": [], "error": "Persistent task store not enabled"}
        tasks = await runtime.persistent_task_store.list_tasks(status=status)
        return {"tasks": [runtime.persistent_task_store._task_to_dict(t) for t in tasks]}

    @app.post("/api/scheduled-tasks")
    async def create_scheduled_task(req: ScheduledTaskRequest) -> dict[str, Any]:
        """Create a new persistent scheduled task."""
        if not runtime.persistent_task_store:
            return JSONResponse(status_code=503, content={"error": "Persistent task store not enabled"})
        try:
            task = await runtime.persistent_task_store.create_task(
                intent_text=req.intent_text,
                schedule_type=req.schedule_type,
                name=req.name,
                execute_at=req.execute_at,
                interval_seconds=req.interval_seconds,
                cron_expr=req.cron_expr,
                channel_id=req.channel_id,
                max_runs=req.max_runs,
                created_by=req.created_by,
                webhook_name=req.webhook_name,
            )
            return runtime.persistent_task_store._task_to_dict(task)
        except ValueError as e:
            return JSONResponse(status_code=400, content={"error": str(e)})

    @app.get("/api/scheduled-tasks/{task_id}")
    async def get_scheduled_task(task_id: str) -> dict[str, Any]:
        """Get a single scheduled task by ID."""
        if not runtime.persistent_task_store:
            return JSONResponse(status_code=503, content={"error": "Persistent task store not enabled"})
        task = await runtime.persistent_task_store.get_task(task_id)
        if not task:
            return JSONResponse(status_code=404, content={"error": "Task not found"})
        return runtime.persistent_task_store._task_to_dict(task)

    @app.delete("/api/scheduled-tasks/{task_id}")
    async def cancel_scheduled_task(task_id: str) -> dict[str, Any]:
        """Cancel a scheduled task."""
        if not runtime.persistent_task_store:
            return JSONResponse(status_code=503, content={"error": "Persistent task store not enabled"})
        cancelled = await runtime.persistent_task_store.cancel_task(task_id)
        if not cancelled:
            return JSONResponse(status_code=404, content={"error": "Task not found or already cancelled"})
        return {"cancelled": True, "task_id": task_id}

    @app.post("/api/scheduled-tasks/webhook/{webhook_name}")
    async def trigger_webhook(webhook_name: str) -> dict[str, Any]:
        """Trigger a named webhook task."""
        if not runtime.persistent_task_store:
            return JSONResponse(status_code=503, content={"error": "Persistent task store not enabled"})
        task = await runtime.persistent_task_store.trigger_webhook(webhook_name)
        if not task:
            return JSONResponse(status_code=404, content={"error": f"Webhook '{webhook_name}' not found"})
        return {"triggered": True, "task_id": task.id, "webhook_name": webhook_name}

    @app.post("/api/scheduled-tasks/dag/{dag_id}/resume")
    async def resume_dag_checkpoint(dag_id: str) -> dict[str, Any]:
        """Resume a stale DAG checkpoint (Captain-approved)."""
        if not runtime.persistent_task_store:
            return JSONResponse(status_code=503, content={"error": "Persistent task store not enabled"})
        result = await runtime.persistent_task_store.resume_dag(dag_id)
        if "error" in result:
            return JSONResponse(status_code=400, content=result)
        return result
```

**Import note:** If `JSONResponse` is not already imported in api.py, add it:
```python
from fastapi.responses import JSONResponse
```

---

## Part 6: HXI Store — `ui/src/store/types.ts` + `ui/src/store/useStore.ts`

### 6a. Types

Add to `ui/src/store/types.ts`, after the `Assignment` interface (around line 393):

```typescript
// Scheduled Task types (Phase 25a)

export interface ScheduledTaskView {
  id: string;
  name: string;
  intent_text: string;
  created_at: number;
  schedule_type: 'once' | 'interval' | 'cron';
  execute_at: number | null;
  interval_seconds: number | null;
  cron_expr: string | null;
  channel_id: string | null;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
  last_result: string | null;
  last_run_at: number | null;
  next_run_at: number | null;
  run_count: number;
  max_runs: number | null;
  created_by: string;
  webhook_name: string | null;
  enabled: boolean;
}
```

### 6b. Store fields and actions

In `ui/src/store/useStore.ts`:

1. Add `ScheduledTaskView` to the type imports from `'./types'` (line 5-15).

2. Add state fields to the store (in the state section, near other data arrays):

```typescript
  // Scheduled Tasks (Phase 25a)
  scheduledTasks: [] as ScheduledTaskView[],
```

3. Add a refresh action (near other refresh actions like `refreshWardRoomThreads`):

```typescript
  refreshScheduledTasks: async () => {
    try {
      const res = await fetch('/api/scheduled-tasks?status=pending');
      const data = await res.json();
      set({ scheduledTasks: data.tasks || [] });
    } catch { /* fail silently */ }
  },
```

4. Hydrate from `state_snapshot` — in the `handleWSEvent` case for `'state_snapshot'` (where other snapshot fields are unpacked), add:

```typescript
        if ((data as any).scheduled_tasks) {
          set({ scheduledTasks: (data as any).scheduled_tasks });
        }
```

5. Handle WebSocket events — add cases in `handleWSEvent` switch, **before** the `default:` case (around line 1263):

```typescript
      // Scheduled Task events (Phase 25a)
      case 'scheduled_task_created':
      case 'scheduled_task_updated':
      case 'scheduled_task_cancelled':
      case 'scheduled_task_fired': {
        get().refreshScheduledTasks();
        break;
      }
      case 'scheduled_task_dag_stale': {
        // Surface as notification — stale DAGs need Captain review
        break;
      }
```

---

## Part 7: SchedulerAgent Update — `src/probos/agents/utility/organizer_agents.py`

Update `SchedulerAgent` to route through `PersistentTaskStore` when available.

### 7a. perceive() update

In the `perceive()` method, **after** the existing TaskScheduler task listing block (around line 265), add:

```python
            # Include persistent scheduled tasks (Phase 25a)
            if hasattr(self._runtime, "persistent_task_store") and self._runtime.persistent_task_store:
                try:
                    import asyncio
                    p_tasks = await self._runtime.persistent_task_store.list_tasks(limit=20)
                    if p_tasks:
                        lines = [f"  {t.id}: {t.name} ({t.schedule_type}, status={t.status}, runs={t.run_count})" for t in p_tasks]
                        parts.append(f"Persistent scheduled tasks ({len(p_tasks)}):\n" + "\n".join(lines))
                    else:
                        parts.append("Persistent scheduled tasks: none")
                except Exception:
                    pass
```

### 7b. act() update — remind action

In the `act()` method, inside the `action == "remind"` branch (around line 273), **before** the existing `self._runtime.task_scheduler.schedule()` call, add a check for persistent store:

```python
                    # --- Schedule via PersistentTaskStore if available (Phase 25a) ---
                    if action == "remind" and hasattr(self._runtime, "persistent_task_store") and self._runtime.persistent_task_store:
                        delay = data.get("delay_seconds", 60)
                        text = data.get("text", "")
                        interval = data.get("interval_seconds")
                        channel_id = data.get("channel_id")
                        if text:
                            schedule_type = "interval" if interval else "once"
                            execute_at = time.time() + float(delay) if not interval else None
                            await self._runtime.persistent_task_store.create_task(
                                intent_text=text,
                                schedule_type=schedule_type,
                                execute_at=execute_at,
                                interval_seconds=float(interval) if interval else None,
                                channel_id=channel_id,
                            )
```

The logic should be: if PersistentTaskStore is available, use it; otherwise fall through to the existing TaskScheduler. Restructure the `action == "remind"` block as:

```python
                    if action == "remind":
                        delay = data.get("delay_seconds", 60)
                        text = data.get("text", "")
                        interval = data.get("interval_seconds")
                        channel_id = data.get("channel_id")
                        if text:
                            # Prefer persistent store (Phase 25a) over in-memory scheduler
                            if hasattr(self._runtime, "persistent_task_store") and self._runtime.persistent_task_store:
                                schedule_type = "interval" if interval else "once"
                                execute_at = time.time() + float(delay) if not interval else None
                                await self._runtime.persistent_task_store.create_task(
                                    intent_text=text,
                                    schedule_type=schedule_type,
                                    execute_at=execute_at,
                                    interval_seconds=float(interval) if interval else None,
                                    channel_id=channel_id,
                                )
                            elif hasattr(self._runtime, "task_scheduler") and self._runtime.task_scheduler:
                                self._runtime.task_scheduler.schedule(
                                    text,
                                    delay_seconds=float(delay),
                                    interval_seconds=float(interval) if interval else None,
                                    channel_id=channel_id,
                                )
```

### 7c. act() update — list action

Similarly update the `action == "list"` branch to merge results from both stores:

```python
                    elif action == "list":
                        all_lines = []
                        # Persistent tasks (Phase 25a)
                        if hasattr(self._runtime, "persistent_task_store") and self._runtime.persistent_task_store:
                            p_tasks = await self._runtime.persistent_task_store.list_tasks(limit=20)
                            for t in p_tasks:
                                all_lines.append(f"  [{t.schedule_type}] {t.id}: {t.name} (status={t.status}, runs={t.run_count})")
                        # In-memory tasks
                        if hasattr(self._runtime, "task_scheduler") and self._runtime.task_scheduler:
                            tasks = self._runtime.task_scheduler.list_tasks()
                            for t in tasks:
                                all_lines.append(f"  [session] {t.id}: {t.intent_text} (status={t.status})")
                        if all_lines:
                            return {"success": True, "result": f"{len(all_lines)} task(s):\n" + "\n".join(all_lines)}
                        return {"success": True, "result": data.get("message", "No scheduled tasks.")}
```

### 7d. Update instructions string

Update the `instructions` string to mention persistence:

Change:
```
"Tasks do not survive server restarts — they will be re-loaded from saved "
"reminders on next boot.\n\n"
```

To:
```
"Tasks are now persistent and survive server restarts. For recurring tasks, "
"specify an interval (e.g., 'every hour', 'every day'). Cron expressions "
"are also supported for complex schedules.\n\n"
```

Also add `import time` to the file's imports if not already present.

---

## Part 8: Tests — NEW `tests/test_persistent_tasks.py`

Create `tests/test_persistent_tasks.py`:

```python
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
        task = await s1.create_task(intent_text="Will cancel")
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
```

---

## Verification

Run the following after all changes:

```bash
# Targeted tests
uv run pytest tests/test_persistent_tasks.py -x -v

# Regression on existing scheduler
uv run pytest tests/test_task_scheduler.py -x -v

# Full Python test suite
uv run pytest tests/ --tb=short -q

# Frontend tests
cd ui && npx vitest run --reporter=verbose 2>&1 | head -100
```

**Manual test:** Enable `persistent_tasks.enabled: true` in config, create a task via API `POST /api/scheduled-tasks` with `schedule_type: "interval"` and `interval_seconds: 30`. Verify it fires every 30s in the logs. Stop server, restart, verify task still exists and resumes firing.

---

## What This Does NOT Change

- **TaskScheduler** (in-memory, continues running transient tasks)
- **DAG checkpoint module** (read-only dependency — `restore_dag()` is called, not modified)
- **DAGExecutor** (still writes checkpoints, still calls `delete_checkpoint` on completion)
- **TaskTracker** (HXI progress tracking — separate concern)
- **BuildDispatcher** (build pipeline — separate concern)
- **Earned Agency, Ward Room, Bridge Alerts, Proactive Loop**
