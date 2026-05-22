"""AD-815a: TaskSession substrate.

A ``TaskSession`` anchors a unit of cowork-style work (one or many
runs) to:

* an AD-791 ChatThread (the conversation that produced the brief)
* an AD-477 WorkItem (the assignee + kanban surface) — optional, set
  when the chat instruction is promoted to a task via AD-815c
* an on-disk folder layout: ``root_dir/{inputs,outputs,scratch}``
* zero or more ``TaskSessionRun`` rows (one per execution, tracks
  container image used, pip extras installed, exit code)

Lifecycle:
    pending -> running -> completed | failed | cancelled

Recurring sessions (AD-815g) transition completed -> pending again on
the next tick. The first AD-815a substrate writes the table columns
but the scheduler that fires those transitions lands in AD-815g.

Folder layout (relative to the per-thread workspace from AD-799):

    {workspace_root}/task_sessions/{session_id}/
        inputs/    <- Captain uploads, link captures, browser state
        outputs/   <- agent-generated artifacts; auto-registered into
                     AD-797 ArtifactStore
        scratch/   <- container working directory; transient

The substrate is sync sqlite per the AD-791 / AD-797 convention.
Async callers wrap in ``loop.run_in_executor``.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal

Status = Literal["pending", "running", "completed", "failed", "cancelled"]
ScheduleKind = Literal["one_shot", "recurring"]
RecurrencePolicy = Literal["reuse", "new_session_each_run"]


_SCHEMA = """
CREATE TABLE IF NOT EXISTS task_sessions (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    work_item_id TEXT,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    schedule_kind TEXT NOT NULL DEFAULT 'one_shot',
    schedule_cron TEXT,                  -- AD-815g: cron expression
    schedule_timezone TEXT,              -- AD-815g
    recurrence_policy TEXT NOT NULL DEFAULT 'reuse',  -- AD-815g
    recurrence_max_runs INTEGER,         -- AD-815g
    parent_session_id TEXT,              -- set when forked by new_session_each_run policy
    root_dir TEXT NOT NULL,
    container_image TEXT,                -- AD-815d cowork-base by default
    egress_policy TEXT NOT NULL DEFAULT 'bridge',
    created_at REAL NOT NULL,
    last_run_at REAL,
    completed_at REAL
);
CREATE INDEX IF NOT EXISTS idx_task_sessions_thread ON task_sessions (thread_id);
CREATE INDEX IF NOT EXISTS idx_task_sessions_status ON task_sessions (status);
CREATE INDEX IF NOT EXISTS idx_task_sessions_work_item ON task_sessions (work_item_id);

CREATE TABLE IF NOT EXISTS task_session_runs (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    started_at REAL NOT NULL,
    ended_at REAL,
    exit_code INTEGER,
    container_image_used TEXT,
    pip_installed_extras TEXT,           -- JSON list[str]
    error TEXT,
    FOREIGN KEY (session_id) REFERENCES task_sessions (id)
);
CREATE INDEX IF NOT EXISTS idx_runs_session ON task_session_runs (session_id, started_at);
"""


@dataclass
class TaskSession:
    id: str
    thread_id: str
    title: str
    status: Status
    root_dir: str
    created_at: float
    schedule_kind: ScheduleKind = "one_shot"
    schedule_cron: str | None = None
    schedule_timezone: str | None = None
    recurrence_policy: RecurrencePolicy = "reuse"
    recurrence_max_runs: int | None = None
    parent_session_id: str | None = None
    work_item_id: str | None = None
    container_image: str | None = None
    egress_policy: str = "bridge"
    last_run_at: float | None = None
    completed_at: float | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "thread_id": self.thread_id,
            "work_item_id": self.work_item_id,
            "title": self.title,
            "status": self.status,
            "schedule_kind": self.schedule_kind,
            "schedule_cron": self.schedule_cron,
            "schedule_timezone": self.schedule_timezone,
            "recurrence_policy": self.recurrence_policy,
            "recurrence_max_runs": self.recurrence_max_runs,
            "parent_session_id": self.parent_session_id,
            "root_dir": self.root_dir,
            "container_image": self.container_image,
            "egress_policy": self.egress_policy,
            "created_at": self.created_at,
            "last_run_at": self.last_run_at,
            "completed_at": self.completed_at,
        }


@dataclass
class TaskSessionRun:
    id: str
    session_id: str
    started_at: float
    ended_at: float | None = None
    exit_code: int | None = None
    container_image_used: str | None = None
    pip_installed_extras: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "exit_code": self.exit_code,
            "container_image_used": self.container_image_used,
            "pip_installed_extras": list(self.pip_installed_extras),
            "error": self.error,
        }


_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}

_VALID_TRANSITIONS: dict[Status, set[Status]] = {
    "pending": {"running", "cancelled"},
    "running": {"completed", "failed", "cancelled"},
    "completed": {"pending"},       # recurring re-arm
    "failed": {"pending"},          # recurring re-arm
    "cancelled": set(),
}


class InvalidStatusTransition(ValueError):
    """Raised when set_status is called with an illegal transition."""


class TaskSessionStore:
    """SQLite-backed TaskSession + run store."""

    def __init__(
        self,
        db_path: Path,
        *,
        workspace_root: Path,
        clock: Callable[[], float] = time.time,
        id_factory: Callable[[], str] = lambda: uuid.uuid4().hex,
    ) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._workspace_root = Path(workspace_root)
        self._workspace_root.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._id_factory = id_factory
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # ---------- sessions ----------

    def create_session(
        self,
        *,
        thread_id: str,
        title: str,
        work_item_id: str | None = None,
        schedule_kind: ScheduleKind = "one_shot",
        schedule_cron: str | None = None,
        schedule_timezone: str | None = None,
        recurrence_policy: RecurrencePolicy = "reuse",
        recurrence_max_runs: int | None = None,
        parent_session_id: str | None = None,
        container_image: str | None = None,
        egress_policy: str = "bridge",
    ) -> TaskSession:
        session_id = self._id_factory()
        now = self._clock()
        root_dir = self._workspace_root / "task_sessions" / session_id
        (root_dir / "inputs").mkdir(parents=True, exist_ok=True)
        (root_dir / "outputs").mkdir(parents=True, exist_ok=True)
        (root_dir / "scratch").mkdir(parents=True, exist_ok=True)

        session = TaskSession(
            id=session_id,
            thread_id=thread_id,
            title=title,
            status="pending",
            root_dir=str(root_dir),
            created_at=now,
            schedule_kind=schedule_kind,
            schedule_cron=schedule_cron,
            schedule_timezone=schedule_timezone,
            recurrence_policy=recurrence_policy,
            recurrence_max_runs=recurrence_max_runs,
            parent_session_id=parent_session_id,
            work_item_id=work_item_id,
            container_image=container_image,
            egress_policy=egress_policy,
        )
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO task_sessions (
                    id, thread_id, work_item_id, title, status, schedule_kind,
                    schedule_cron, schedule_timezone, recurrence_policy,
                    recurrence_max_runs, parent_session_id, root_dir,
                    container_image, egress_policy, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    session.id,
                    session.thread_id,
                    session.work_item_id,
                    session.title,
                    session.status,
                    session.schedule_kind,
                    session.schedule_cron,
                    session.schedule_timezone,
                    session.recurrence_policy,
                    session.recurrence_max_runs,
                    session.parent_session_id,
                    session.root_dir,
                    session.container_image,
                    session.egress_policy,
                    session.created_at,
                ),
            )
        return session

    def get_session(self, session_id: str) -> TaskSession | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM task_sessions WHERE id = ?", (session_id,)
            ).fetchone()
        return _row_to_session(row) if row else None

    def list_sessions(
        self,
        *,
        thread_id: str | None = None,
        status: Status | None = None,
        limit: int = 100,
    ) -> list[TaskSession]:
        clauses: list[str] = []
        params: list = []
        if thread_id is not None:
            clauses.append("thread_id = ?")
            params.append(thread_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM task_sessions {where} ORDER BY created_at DESC LIMIT ?",
                (*params, max(1, min(limit, 500))),
            ).fetchall()
        return [_row_to_session(r) for r in rows]

    def set_status(self, session_id: str, new_status: Status) -> TaskSession | None:
        current = self.get_session(session_id)
        if current is None:
            return None
        if new_status not in _VALID_TRANSITIONS[current.status]:
            raise InvalidStatusTransition(
                f"Cannot transition from {current.status!r} to {new_status!r}"
            )
        now = self._clock()
        completed_at = now if new_status in _TERMINAL_STATUSES else None
        with self._connect() as conn:
            conn.execute(
                "UPDATE task_sessions SET status = ?, completed_at = ? WHERE id = ?",
                (new_status, completed_at, session_id),
            )
        return self.get_session(session_id)

    def set_work_item(self, session_id: str, work_item_id: str | None) -> TaskSession | None:
        if self.get_session(session_id) is None:
            return None
        with self._connect() as conn:
            conn.execute(
                "UPDATE task_sessions SET work_item_id = ? WHERE id = ?",
                (work_item_id, session_id),
            )
        return self.get_session(session_id)

    def cancel(self, session_id: str) -> TaskSession | None:
        current = self.get_session(session_id)
        if current is None or current.status in _TERMINAL_STATUSES:
            return current
        return self.set_status(session_id, "cancelled")

    # ---------- runs ----------

    def start_run(self, session_id: str) -> TaskSessionRun | None:
        session = self.get_session(session_id)
        if session is None:
            return None
        if session.status != "pending":
            raise InvalidStatusTransition(
                f"Cannot start run; session status is {session.status!r}"
            )
        # Transition to running first so concurrent start_run sees the lock.
        self.set_status(session_id, "running")
        run_id = self._id_factory()
        now = self._clock()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO task_session_runs (id, session_id, started_at) "
                "VALUES (?,?,?)",
                (run_id, session_id, now),
            )
            conn.execute(
                "UPDATE task_sessions SET last_run_at = ? WHERE id = ?",
                (now, session_id),
            )
        return TaskSessionRun(id=run_id, session_id=session_id, started_at=now)

    def finish_run(
        self,
        run_id: str,
        *,
        exit_code: int,
        container_image_used: str | None,
        pip_installed_extras: list[str] | None = None,
        error: str | None = None,
    ) -> TaskSessionRun | None:
        now = self._clock()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT session_id FROM task_session_runs WHERE id = ?", (run_id,)
            ).fetchone()
            if row is None:
                return None
            session_id = row["session_id"]
            conn.execute(
                "UPDATE task_session_runs SET ended_at = ?, exit_code = ?, "
                "container_image_used = ?, pip_installed_extras = ?, error = ? "
                "WHERE id = ?",
                (
                    now,
                    exit_code,
                    container_image_used,
                    json.dumps(pip_installed_extras or []),
                    error,
                    run_id,
                ),
            )
        new_status: Status = "completed" if exit_code == 0 else "failed"
        self.set_status(session_id, new_status)
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> TaskSessionRun | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM task_session_runs WHERE id = ?", (run_id,)
            ).fetchone()
        return _row_to_run(row) if row else None

    def list_runs(self, session_id: str, *, limit: int = 100) -> list[TaskSessionRun]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM task_session_runs WHERE session_id = ? "
                "ORDER BY started_at ASC LIMIT ?",
                (session_id, max(1, min(limit, 500))),
            ).fetchall()
        return [_row_to_run(r) for r in rows]

    def rearm(self, session_id: str) -> TaskSession | None:
        """AD-815g re-arms a recurring session for its next tick.

        Allowed only from terminal status; transitions back to pending.
        Cancelled sessions cannot be re-armed.
        """
        current = self.get_session(session_id)
        if current is None or current.status not in {"completed", "failed"}:
            return current
        return self.set_status(session_id, "pending")


def _row_to_session(row: sqlite3.Row) -> TaskSession:
    return TaskSession(
        id=row["id"],
        thread_id=row["thread_id"],
        title=row["title"],
        status=row["status"],
        root_dir=row["root_dir"],
        created_at=row["created_at"],
        schedule_kind=row["schedule_kind"],
        schedule_cron=row["schedule_cron"],
        schedule_timezone=row["schedule_timezone"],
        recurrence_policy=row["recurrence_policy"],
        recurrence_max_runs=row["recurrence_max_runs"],
        parent_session_id=row["parent_session_id"],
        work_item_id=row["work_item_id"],
        container_image=row["container_image"],
        egress_policy=row["egress_policy"],
        last_run_at=row["last_run_at"],
        completed_at=row["completed_at"],
    )


def _row_to_run(row: sqlite3.Row) -> TaskSessionRun:
    try:
        extras = json.loads(row["pip_installed_extras"]) if row["pip_installed_extras"] else []
    except (json.JSONDecodeError, TypeError):
        extras = []
    return TaskSessionRun(
        id=row["id"],
        session_id=row["session_id"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        exit_code=row["exit_code"],
        container_image_used=row["container_image_used"],
        pip_installed_extras=extras,
        error=row["error"],
    )
