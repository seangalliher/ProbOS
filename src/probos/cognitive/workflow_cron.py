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

Wave 130. Issue #483.
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
    """Mutable record of a single registered cron trigger."""

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
    """Background tick that fires due triggers via process_nl_fn.

    Public API:
      - async start() / async stop()
      - async register(user_input, cron_expr) -> WorkflowCronTrigger
      - async cancel(trigger_id) -> bool
      - list_triggers() -> list[WorkflowCronTrigger]
    """

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
        if self._db_path and self._db is None:
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
        logger.info(
            "AD-707: registered cron trigger %s every '%s'", trig.id, cron_expr
        )
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
        logger.info("AD-707: cancelled cron trigger %s", trigger_id)
        return True

    def list_triggers(self) -> list[WorkflowCronTrigger]:
        return list(self._triggers.values())

    async def _load(self) -> None:
        if self._db is None:
            return
        async with self._db.execute(
            "SELECT id, user_input, cron_expr, created_at, last_fired_at, "
            "fire_count, enabled FROM workflow_cron_triggers WHERE enabled=1"
        ) as cursor:
            async for row in cursor:
                self._triggers[row[0]] = WorkflowCronTrigger(
                    id=row[0],
                    user_input=row[1],
                    cron_expr=row[2],
                    created_at=row[3],
                    last_fired_at=row[4],
                    fire_count=row[5],
                    enabled=bool(row[6]),
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
                    "AD-707: trigger %s replay failed; skipping fire-count update",
                    trig.id,
                    exc_info=True,
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
    """A trigger is due iff the next cron fire after last_fired_at is <= now.

    First evaluation uses ``created_at`` as the base so a freshly-registered
    "every minute" trigger does not fire instantly.
    """
    try:
        from croniter import croniter

        base = trig.last_fired_at if trig.last_fired_at > 0 else trig.created_at
        return croniter(trig.cron_expr, base).get_next(float) <= now
    except Exception:
        logger.debug("AD-707: cron eval failed for %s", trig.id, exc_info=True)
        return False
