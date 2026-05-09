# AD-707 v1 — Workflow Cron Trigger (cron-only; webhook + workflow API deferred)

**Issue:** [#483](https://github.com/seangalliher/ProbOS/issues/483)
**Type:** Architecture Decision (cognitive — workflow scheduling)
**Depends on:** AD-580 (`WorkflowCache`), AD-281 (`TaskScheduler`).
**Wave:** 130

## Goal

`WorkflowCache` (AD-580) replays cached DAGs on demand. AD-707 adds a single new substrate: a cron-driven trigger that re-fires a cached workflow on a schedule. Webhook triggers and a fully external Workflow API are explicitly out of scope and deferred to **AD-707b** (webhook) and **AD-707c** (workflow API).

## Verified Against Codebase (2026-05-08)

- ✅ `src/probos/cognitive/workflow_cache.py:17` `class WorkflowCache`. `:29` `def store(self, user_input: str, dag: TaskDAG)`. `:56` `def lookup(self, user_input: str) -> TaskDAG | None`. `:150` `_normalize(text)` — the cache key is the **normalized user input string**, not a UUID. The trigger therefore stores the same normalized key as `pattern`.
- ✅ `src/probos/types.py:599` `class WorkflowCacheEntry` carries `pattern: str`, `dag_json: str`, `hit_count: int`, `last_hit: datetime`, `created_at: datetime`. Reusable as the unit of truth for what a "stored workflow" is.
- ✅ `src/probos/cognitive/task_scheduler.py:34` `class TaskScheduler` is the in-session scheduler with a 1-second tick (per its docstring) and `start()/stop()` lifecycle. AD-707 plugs into a parallel cron loop, not into TaskScheduler — TaskScheduler is for **delayed user intents**, not workflow re-runs.
- ✅ `croniter>=1.3` is already declared in `pyproject.toml:37`. No new dependency. `src/probos/duty_schedule.py:76` and `src/probos/persistent_tasks.py:537` are the canonical `croniter` usage patterns to mirror (lazy import inside the eval loop).
- ✅ `src/probos/runtime.py:406` `self.workflow_cache = WorkflowCache()` and `:411,1434` shows `workflow_cache=` injected into the decomposer / cognitive_agent pipeline. The trigger needs the same `runtime` reference to dispatch a cached workflow.
- ✅ `src/probos/runtime.py:2533` `async def process_natural_language(...)` — the canonical NL entry point. **There is no `process_nl` method.** The trigger must call `process_natural_language(user_input)`. Verified by `grep -n "async def process_" src/probos/runtime.py` — only hit is `:2533: async def process_natural_language(`.
- ✅ `src/probos/runtime.py:2881` shows the existing replay path: `self.workflow_cache and dag.nodes` → `self.workflow_cache.store(text, dag)`. No equivalent re-run helper exists yet — AD-707 routes the replay through `process_natural_language(user_input)` (preferred, no new public API).
- ⚠️ Dispatch said "what's the cache key shape?" — confirmed: it is the normalized `user_input` string. The trigger therefore must remember the **original** user input string to re-fire (since `_normalize` is one-way for re-execution; we want the LLM-decomposer or cache-lookup to see a real prompt, not the squashed form). This prompt accordingly stores `user_input` (raw), not `pattern` (normalized) on the trigger row.

## Build Ordering Note

This prompt edits `src/probos/config.py` (D2). Four Wave 130 prompts touch that file; serialize commits in this order to avoid register-block collisions: **claude-bootstrap → AD-701 → AD-707 → Memvid-QP**. AD-707 is third; rebase on top of the AD-701 commit before adding `WorkflowCronTriggerConfig`.

## Scope

Ship the trigger registry, the persistent SQLite table (so triggers survive restart), the cron tick, and a single new runtime hook. Do **not** add webhook firing, do **not** add a public REST/CLI surface for managing triggers in v1 (manual config-only registration is acceptable; AD-707c will add the API).

## Deliverables

### D1. New module `src/probos/cognitive/workflow_cron.py`

```python
"""AD-707: Cron-driven re-run of cached workflows.

A WorkflowCronTrigger says: "every N seconds / at this cron expression,
re-fire the workflow whose stored user_input matches this string." It
hooks into the runtime's NL processing pipeline so workflow_cache.lookup
finds the cached DAG and replays it without an LLM call (the standard
fast-path).

Design decisions
----------------
- **Persistent SQLite** so triggers survive restart (mirrors AD-664
  ConnectionFactory pattern).
- **In-process tick** (1-second resolution; cron resolution is per-minute
  anyway) — no new background process.
- **Replay via runtime.process_natural_language(user_input)** — the
  WorkflowCache fast-path picks it up automatically. We do NOT call
  the cache directly from here, because the cache lookup is the very
  shortcut we want to preserve.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from probos.protocols import ConnectionFactory, DatabaseConnection

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS workflow_cron_triggers (
    id            TEXT PRIMARY KEY,
    user_input    TEXT NOT NULL,
    cron_expr     TEXT NOT NULL,
    created_at    REAL NOT NULL,
    last_fired_at REAL NOT NULL DEFAULT 0.0,
    fire_count    INTEGER NOT NULL DEFAULT 0,
    enabled       INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_wfcron_enabled ON workflow_cron_triggers (enabled);
"""


@dataclass
class WorkflowCronTrigger:
    id: str
    user_input: str
    cron_expr: str
    created_at: float
    last_fired_at: float = 0.0
    fire_count: int = 0
    enabled: bool = True


# Callable matching ProbOSRuntime.process_natural_language(user_input: str) -> Any
ProcessNLFn = Callable[[str], Awaitable[Any]]


class WorkflowCronScheduler:
    """Background tick that fires due triggers via process_nl_fn."""

    def __init__(
        self,
        process_nl_fn: ProcessNLFn,
        *,
        db_path: str | None = None,
        connection_factory: ConnectionFactory | None = None,
        tick_interval_seconds: float = 1.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._process_nl = process_nl_fn
        self._db_path = db_path
        self._db: DatabaseConnection | None = None
        self._cf = connection_factory
        if self._cf is None:
            from probos.storage.sqlite_factory import default_factory
            self._cf = default_factory
        self._tick = tick_interval_seconds
        self._clock = clock
        self._task: asyncio.Task[None] | None = None
        self._triggers: dict[str, WorkflowCronTrigger] = {}

    async def start(self) -> None:
        if self._db_path:
            self._db = await self._cf.connect(self._db_path)
            await self._db.execute("PRAGMA journal_mode=WAL")
            await self._db.execute("PRAGMA busy_timeout=5000")
            await self._db.executescript(_SCHEMA)
            await self._db.commit()
            await self._load()
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="ad707-cron")

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def register(self, user_input: str, cron_expr: str) -> WorkflowCronTrigger:
        if not user_input.strip():
            raise ValueError("user_input required")
        if not _validate_cron(cron_expr):
            raise ValueError(f"invalid cron expression: {cron_expr!r}")
        trig = WorkflowCronTrigger(
            id=uuid.uuid4().hex[:12],
            user_input=user_input,
            cron_expr=cron_expr,
            created_at=self._clock(),
        )
        self._triggers[trig.id] = trig
        if self._db is not None:
            await self._db.execute(
                "INSERT INTO workflow_cron_triggers "
                "(id, user_input, cron_expr, created_at, last_fired_at, fire_count, enabled) "
                "VALUES (?, ?, ?, ?, 0.0, 0, 1)",
                (trig.id, trig.user_input, trig.cron_expr, trig.created_at),
            )
            await self._db.commit()
        logger.info("AD-707: registered cron trigger %s every '%s'", trig.id, cron_expr)
        return trig

    async def cancel(self, trigger_id: str) -> bool:
        trig = self._triggers.pop(trigger_id, None)
        if trig is None:
            return False
        if self._db is not None:
            await self._db.execute(
                "UPDATE workflow_cron_triggers SET enabled=0 WHERE id=?",
                (trigger_id,),
            )
            await self._db.commit()
        return True

    def list_triggers(self) -> list[WorkflowCronTrigger]:
        return list(self._triggers.values())

    async def _load(self) -> None:
        if self._db is None:
            return
        # Builder pre-check (Required #2): confirm the AD-664 ``DatabaseConnection``
        # Protocol exposes the async-cursor / async-iterator shape used below
        # (i.e. ``execute(...)`` returns an awaitable context manager whose
        # cursor is async-iterable). If the abstract surface only exposes
        # ``fetchall()`` / ``fetchone()``, replace with:
        #     rows = await (await self._db.execute(SQL)).fetchall()
        #     for row in rows: ...
        # Either shape is acceptable; the loop body is identical.
        async with self._db.execute(
            "SELECT id, user_input, cron_expr, created_at, last_fired_at, "
            "fire_count, enabled FROM workflow_cron_triggers WHERE enabled=1"
        ) as cursor:
            async for row in cursor:
                self._triggers[row[0]] = WorkflowCronTrigger(
                    id=row[0], user_input=row[1], cron_expr=row[2],
                    created_at=row[3], last_fired_at=row[4],
                    fire_count=row[5], enabled=bool(row[6]),
                )

    async def _loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._tick)
                await self._tick_once()
        except asyncio.CancelledError:
            return

    async def _tick_once(self) -> None:
        now = self._clock()
        for trig in list(self._triggers.values()):
            if not trig.enabled:
                continue
            if not _is_due(trig, now):
                continue
            try:
                await self._process_nl(trig.user_input)
            except Exception:
                logger.warning(
                    "AD-707: trigger %s replay failed", trig.id, exc_info=True,
                )
                continue
            trig.last_fired_at = now
            trig.fire_count += 1
            if self._db is not None:
                await self._db.execute(
                    "UPDATE workflow_cron_triggers "
                    "SET last_fired_at=?, fire_count=? WHERE id=?",
                    (now, trig.fire_count, trig.id),
                )
                await self._db.commit()


def _validate_cron(expr: str) -> bool:
    try:
        from croniter import croniter
        return croniter.is_valid(expr)
    except Exception:
        return False


def _is_due(trig: WorkflowCronTrigger, now: float) -> bool:
    """A trigger is due iff the next cron fire after last_fired_at is <= now."""
    try:
        from croniter import croniter
        base = trig.last_fired_at if trig.last_fired_at > 0 else trig.created_at
        return croniter(trig.cron_expr, base).get_next(float) <= now
    except Exception:
        logger.debug("AD-707: cron eval failed for %s", trig.id, exc_info=True)
        return False
```

### D2. Pydantic config

In `src/probos/config.py`:

```python
class WorkflowCronTriggerConfig(BaseModel):
    enabled: bool = False
    db_path: str = ""                       # empty → in-memory (lost on restart)
    tick_interval_seconds: float = Field(default=1.0, gt=0.0)
    initial_triggers: list[dict[str, str]] = Field(default_factory=list)
    # initial_triggers items: {"user_input": "...", "cron_expr": "*/5 * * * *"}
```

Register in the cognitive section alongside `WorkflowCache` config (verify-first the exact location).

### D3. Runtime wiring (`src/probos/startup/finalize.py`)

After `register_workflow_cache` block (verify-first: `finalize.py:2683`):

```python
# AD-707: Workflow Cron Trigger
wfc_cfg = getattr(config.cognitive, "workflow_cron", None)
if wfc_cfg is not None and wfc_cfg.enabled:
    from probos.cognitive.workflow_cron import WorkflowCronScheduler
    runtime.workflow_cron = WorkflowCronScheduler(
        process_nl_fn=runtime.process_natural_language,
        db_path=wfc_cfg.db_path or None,
        tick_interval_seconds=wfc_cfg.tick_interval_seconds,
    )
    await runtime.workflow_cron.start()
    for entry in wfc_cfg.initial_triggers:
        try:
            await runtime.workflow_cron.register(
                entry["user_input"], entry["cron_expr"],
            )
        except Exception:
            logger.warning("AD-707: initial trigger failed: %s", entry, exc_info=True)
```

In `shutdown.py`, add `await runtime.workflow_cron.stop()` if present (mirror the existing shutdown pattern).

### D4. Tests — `tests/test_ad707_workflow_cron_trigger.py`

Required (≥ 7):

1. `test_register_validates_cron_expression` — bad expr → `ValueError`; good expr → registered.
2. `test_register_persists_to_sqlite` — register, restart (new scheduler same db_path) → trigger reloaded into `list_triggers()`.
3. `test_cancel_marks_disabled_in_db_and_removes_from_memory`.
4. `test_tick_fires_due_trigger_via_process_nl_fn` — fake clock, fake `process_nl_fn` (records calls); advance clock past next cron, run `_tick_once`, assert call.
5. `test_tick_does_not_fire_undue_trigger`.
6. `test_failed_replay_logs_and_continues` — `process_nl_fn` raises; subsequent ticks still fire other triggers; original trigger still updates next eval against current `last_fired_at` (i.e. failure does not record a fake fire).
7. `test_cancelled_trigger_does_not_fire`.
8. (recommended) `test_start_stop_idempotent`.

## Hard constraints (do NOT do)

- Do **not** add webhook firing (that is **AD-707b**).
- Do **not** add a REST/CLI surface (that is **AD-707c**). Configuration via Pydantic + initial_triggers is the only registration path in v1.
- Do **not** call `WorkflowCache.lookup` directly from the scheduler — replay through `process_nl_fn` so the cache fast-path runs naturally.
- Do **not** introduce subprocess-based scheduling — in-process asyncio only.
- Do **not** default `enabled=True` (Wave 10 standing convention #14).
- Do **not** silently fire on "never executed" (mirrors `duty_schedule.py:76`-style cron, but use `created_at` as the base for the first eval, **not** `0.0`, so a freshly-registered "every minute" trigger doesn't fire instantly).

## Acceptance criteria

- **Pre-flight (Wave 129 convention #20):** run `git diff --numstat | sort -k2nr | head -5`; >200 deletions on any tracked file = STOP and surface to the Architect before reading source.
- All new code passes lint with full type annotations on public methods.
- 7+ tests pass.
- Existing test suite passes unchanged (no regressions).
- Focused gate: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad707_workflow_cron_trigger.py -v -n 0`
- Full gate: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile`
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Forward markers

- **AD-707b**: webhook trigger (HTTP POST signature → fire workflow).
- **AD-707c**: REST API + slash command for trigger CRUD.
- **AD-707d**: cap on concurrent in-flight cron fires per workflow (back-pressure).

## Revision (2026-05-08)

- **Required #1 (`process_nl` phantom):** Replaced every `runtime.process_nl` reference with `runtime.process_natural_language` (verified at `runtime.py:2533`). Updated D1's `ProcessNLFn` docstring comment, the module docstring, and D3's wiring block.
- **Required #2 (DB protocol shape):** Added an inline pre-check note in `_load` documenting which `DatabaseConnection` Protocol surface the async-iterator-cursor loop relies on, and the `fetchall()` fallback shape if the surface only exposes that.
- **Recommended R4 (line drift):** Refreshed `workflow_cache.py:29` for `store` and `:56` for `lookup`.
- **Cross-cutting:** Added Build Ordering Note (config.py serialization order: claude-bootstrap → AD-701 → AD-707 → Memvid-QP) and pre-flight working-tree integrity reminder.
