"""AD-791: chat-threads substrate.

Threads are the unit of multi-turn conversation in ProbOS. Every chat
exchange — DM with an agent, all-hands huddle, a project-scoped
backlog discussion — belongs to a thread. Until AD-791, /api/agent/
{id}/chat treated each agent as having a single implicit "default
1:1 thread" with the Captain. AD-791 makes threads first-class:

* Persistent SQLite-backed `chat_threads` table with title,
  participants (agent IDs), optional project_id / task_id linkage,
  pinned + archived flags, personality_override (AD-809),
  workspace_root (AD-799).
* Append-only `chat_thread_messages` table for the turn log.
* REST CRUD via ``probos.routers.threads``.
* IntentMessage.thread_id already exists (activation/task_event.py),
  so emitters can set it once threads exist.

What v1 deliberately does NOT do:
* Refactor /api/agent/{id}/chat to require a thread_id — that's a
  follow-up wiring AD; v1 keeps the legacy implicit-thread path.
* Migrate historical episodic memory into threads.
* Rename / merge / split threads.

Forward markers: AD-791a (back-compat shim), AD-791b (search +
fulltext), AD-791c (archival lifecycle policy).
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_threads (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    participants TEXT NOT NULL,           -- JSON list[str]
    project_id TEXT,
    task_id TEXT,
    pinned INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0,
    personality_override TEXT,            -- AD-809
    workspace_root TEXT,                  -- AD-799
    created_at REAL NOT NULL,
    last_active_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_threads_project ON chat_threads (project_id);
CREATE INDEX IF NOT EXISTS idx_threads_last_active ON chat_threads (last_active_at);
CREATE INDEX IF NOT EXISTS idx_threads_archived ON chat_threads (archived);

CREATE TABLE IF NOT EXISTS chat_thread_messages (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    author_id TEXT NOT NULL,
    role TEXT NOT NULL,                   -- "captain" | "agent" | "system"
    body TEXT NOT NULL,
    created_at REAL NOT NULL,
    metadata TEXT,                        -- JSON dict
    FOREIGN KEY (thread_id) REFERENCES chat_threads (id)
);
CREATE INDEX IF NOT EXISTS idx_messages_thread ON chat_thread_messages (thread_id, created_at);
"""


@dataclass
class ChatThread:
    id: str
    title: str
    participants: list[str]
    created_at: float
    last_active_at: float
    project_id: str | None = None
    task_id: str | None = None
    pinned: bool = False
    archived: bool = False
    personality_override: str | None = None
    workspace_root: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "participants": list(self.participants),
            "project_id": self.project_id,
            "task_id": self.task_id,
            "pinned": self.pinned,
            "archived": self.archived,
            "personality_override": self.personality_override,
            "workspace_root": self.workspace_root,
            "created_at": self.created_at,
            "last_active_at": self.last_active_at,
        }


@dataclass
class ChatThreadMessage:
    id: str
    thread_id: str
    author_id: str
    role: str
    body: str
    created_at: float
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "thread_id": self.thread_id,
            "author_id": self.author_id,
            "role": self.role,
            "body": self.body,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }


class ChatThreadStore:
    """SQLite-backed thread + message store.

    All methods synchronous — callers from async code should wrap in
    ``loop.run_in_executor`` per the substrate-store convention.
    """

    def __init__(
        self,
        db_path: Path,
        *,
        clock: Callable[[], float] = time.time,
        id_factory: Callable[[], str] = lambda: uuid.uuid4().hex,
    ) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._id_factory = id_factory
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # ---------- threads ----------

    def create_thread(
        self,
        *,
        title: str,
        participants: Iterable[str],
        project_id: str | None = None,
        task_id: str | None = None,
        personality_override: str | None = None,
        workspace_root: str | None = None,
    ) -> ChatThread:
        thread_id = self._id_factory()
        now = self._clock()
        parts = list(participants)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO chat_threads (id, title, participants, project_id, task_id, "
                "pinned, archived, personality_override, workspace_root, "
                "created_at, last_active_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    thread_id,
                    title,
                    json.dumps(parts),
                    project_id,
                    task_id,
                    0,
                    0,
                    personality_override,
                    workspace_root,
                    now,
                    now,
                ),
            )
        return ChatThread(
            id=thread_id,
            title=title,
            participants=parts,
            project_id=project_id,
            task_id=task_id,
            pinned=False,
            archived=False,
            personality_override=personality_override,
            workspace_root=workspace_root,
            created_at=now,
            last_active_at=now,
        )

    def get_thread(self, thread_id: str) -> ChatThread | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM chat_threads WHERE id = ?", (thread_id,)
            ).fetchone()
        return _row_to_thread(row) if row else None

    def list_threads(
        self,
        *,
        include_archived: bool = False,
        project_id: str | None = None,
        limit: int = 100,
    ) -> list[ChatThread]:
        clauses: list[str] = []
        params: list = []
        if not include_archived:
            clauses.append("archived = 0")
        if project_id is not None:
            clauses.append("project_id = ?")
            params.append(project_id)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM chat_threads {where} "
                "ORDER BY pinned DESC, last_active_at DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
        return [_row_to_thread(r) for r in rows]

    def update_thread(
        self,
        thread_id: str,
        *,
        title: str | None = None,
        pinned: bool | None = None,
        archived: bool | None = None,
        personality_override: str | None = None,
        workspace_root: str | None = None,
        project_id: str | None = None,
        task_id: str | None = None,
    ) -> ChatThread | None:
        sets: list[str] = []
        params: list = []
        for col, val in (
            ("title", title),
            ("pinned", None if pinned is None else int(pinned)),
            ("archived", None if archived is None else int(archived)),
            ("personality_override", personality_override),
            ("workspace_root", workspace_root),
            ("project_id", project_id),
            ("task_id", task_id),
        ):
            if val is not None:
                sets.append(f"{col} = ?")
                params.append(val)
        if not sets:
            return self.get_thread(thread_id)
        params.append(thread_id)
        with self._connect() as conn:
            cur = conn.execute(
                f"UPDATE chat_threads SET {', '.join(sets)} WHERE id = ?", params
            )
            if cur.rowcount == 0:
                return None
        return self.get_thread(thread_id)

    def delete_thread(self, thread_id: str) -> bool:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM chat_thread_messages WHERE thread_id = ?", (thread_id,)
            )
            cur = conn.execute("DELETE FROM chat_threads WHERE id = ?", (thread_id,))
            return cur.rowcount > 0

    # ---------- messages ----------

    def append_message(
        self,
        thread_id: str,
        *,
        author_id: str,
        role: str,
        body: str,
        metadata: dict | None = None,
    ) -> ChatThreadMessage | None:
        if self.get_thread(thread_id) is None:
            return None
        msg_id = self._id_factory()
        now = self._clock()
        meta_json = json.dumps(metadata or {})
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO chat_thread_messages (id, thread_id, author_id, role, body, "
                "created_at, metadata) VALUES (?,?,?,?,?,?,?)",
                (msg_id, thread_id, author_id, role, body, now, meta_json),
            )
            conn.execute(
                "UPDATE chat_threads SET last_active_at = ? WHERE id = ?",
                (now, thread_id),
            )
        return ChatThreadMessage(
            id=msg_id,
            thread_id=thread_id,
            author_id=author_id,
            role=role,
            body=body,
            created_at=now,
            metadata=metadata or {},
        )

    def list_messages(
        self,
        thread_id: str,
        *,
        limit: int = 200,
        before: float | None = None,
    ) -> list[ChatThreadMessage]:
        clauses = ["thread_id = ?"]
        params: list = [thread_id]
        if before is not None:
            clauses.append("created_at < ?")
            params.append(before)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM chat_thread_messages WHERE {' AND '.join(clauses)} "
                "ORDER BY created_at ASC LIMIT ?",
                (*params, limit),
            ).fetchall()
        return [_row_to_message(r) for r in rows]


def _row_to_thread(row: sqlite3.Row) -> ChatThread:
    return ChatThread(
        id=row["id"],
        title=row["title"],
        participants=json.loads(row["participants"]) if row["participants"] else [],
        project_id=row["project_id"],
        task_id=row["task_id"],
        pinned=bool(row["pinned"]),
        archived=bool(row["archived"]),
        personality_override=row["personality_override"],
        workspace_root=row["workspace_root"],
        created_at=row["created_at"],
        last_active_at=row["last_active_at"],
    )


def _row_to_message(row: sqlite3.Row) -> ChatThreadMessage:
    try:
        meta = json.loads(row["metadata"]) if row["metadata"] else {}
    except (json.JSONDecodeError, TypeError):
        meta = {}
    return ChatThreadMessage(
        id=row["id"],
        thread_id=row["thread_id"],
        author_id=row["author_id"],
        role=row["role"],
        body=row["body"],
        created_at=row["created_at"],
        metadata=meta,
    )
