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
* AD-791a adds ``IntentMessage.thread_id`` so chat-routed intents carry
  conversation provenance through the bus; non-chat intents leave it
  ``None``. (The earlier docstring referenced ``activation/task_event.py``
  which is a different ``TaskEvent.thread_id`` namespace.)

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

-- AD-793 (Wave 196): projects substrate — long-lived context groups
-- that own N chat threads + pinned attachment refs. The threads side
-- already carries the FK column (chat_threads.project_id, AD-791a).
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',          -- injected as preamble; empty allowed
    pinned_attachment_ids TEXT NOT NULL DEFAULT '[]', -- JSON list[str] of SHA-256 refs
    archived INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    last_active_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_projects_archived ON projects (archived);
CREATE INDEX IF NOT EXISTS idx_projects_last_active ON projects (last_active_at);

-- AD-986d: transcript-purge tombstones. When the retention reaper hard-deletes
-- a room's recording, it leaves a tiny tombstone here (no message bodies) so a
-- participant who still holds a subjective memory of the room can be honestly
-- told "the recording was purged" instead of silently falling back to its lossy
-- recollection. Manual delete_thread() does NOT tombstone (deliberate removal).
CREATE TABLE IF NOT EXISTS chat_thread_tombstones (
    id TEXT PRIMARY KEY,                  -- the purged thread's id
    title TEXT NOT NULL,
    participants TEXT NOT NULL,           -- JSON list[str], the purged room's roster
    last_active_at REAL NOT NULL,         -- the room's final activity (pre-purge)
    purged_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tombstones_purged ON chat_thread_tombstones (purged_at);
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
    # AD-791a: additive columns absorbed from huggingface/chat-ui shape.
    # ``preprompt`` is an OVERLAY on the agent's birth-certificate
    # instructions, not a replacement (see AD-791a Section 0). ``model``
    # is an optional per-thread LLM tier override (e.g. "deep");
    # NULL = use the agent's natural routing tier. ``metadata`` is a
    # JSON-shaped dict for flexible per-thread tags (is_default,
    # last-summarized timestamp, archive reason, etc.).
    preprompt: str | None = None
    model: str | None = None
    metadata: dict = field(default_factory=dict)

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
            "preprompt": self.preprompt,
            "model": self.model,
            "metadata": dict(self.metadata),
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


@dataclass
class ChatThreadTombstone:
    """AD-986d: the durable trace of a purged room's recording.

    Written by the retention reaper when a transcript is hard-deleted. Carries
    no message bodies — only enough to honestly tell a participant "the
    recording for this room was purged" (and when), so a still-held subjective
    memory is not silently treated as the whole picture.
    """

    id: str
    title: str
    participants: list[str]
    last_active_at: float
    purged_at: float

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "participants": list(self.participants),
            "last_active_at": self.last_active_at,
            "purged_at": self.purged_at,
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
            # AD-791a: idempotent additive-column migration. SQLite has no
            # ``ADD COLUMN IF NOT EXISTS``, so we PRAGMA-introspect first.
            _migrate_v2(conn)

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
        metadata: dict | None = None,
    ) -> ChatThread:
        thread_id = self._id_factory()
        now = self._clock()
        parts = list(participants)
        # AD-918: optional creation metadata (e.g. {"created_by_agent": <id>}).
        # None preserves the pre-AD-918 read shape — NULL and "{}" both
        # decode to {} via _row_to_thread, so existing callers are unaffected.
        meta = dict(metadata or {})
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO chat_threads (id, title, participants, project_id, task_id, "
                "pinned, archived, personality_override, workspace_root, "
                "created_at, last_active_at, metadata) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
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
                    json.dumps(meta),
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
            metadata=meta,
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
        task_id: str | None = None,
        limit: int = 100,
    ) -> list[ChatThread]:
        clauses: list[str] = []
        params: list = []
        if not include_archived:
            clauses.append("archived = 0")
        if project_id is not None:
            clauses.append("project_id = ?")
            params.append(project_id)
        if task_id is not None:  # AD-925: idempotency lookup for the task room
            clauses.append("task_id = ?")
            params.append(task_id)
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

    # ---------- AD-794 / AD-809: title-lock + personality helpers ----------

    def set_personality_override(
        self, thread_id: str, *, override: str | None
    ) -> None:
        """AD-809: update ``chat_threads.personality_override``.

        Pass ``override=None`` to clear; pass a non-empty string to set.
        Silent no-op when the thread row is missing (caller is the
        ``/personality`` slash command which has already resolved the
        thread for the current turn).
        """
        with self._connect() as conn:
            conn.execute(
                "UPDATE chat_threads SET personality_override = ? WHERE id = ?",
                (override, thread_id),
            )

    def set_title(
        self, thread_id: str, title: str, *, lock: bool = False
    ) -> None:
        """AD-794: update the thread title.

        When ``lock=True``, also writes ``metadata.title_locked = true``
        atomically so subsequent first-turn auto-naming attempts skip
        this thread. The read-modify-write of the JSON ``metadata``
        column uses ``BEGIN IMMEDIATE`` for race safety, matching the
        AD-791a ``get_or_create_default_for_agent`` pattern.
        """
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                if lock:
                    row = conn.execute(
                        "SELECT metadata FROM chat_threads WHERE id = ?",
                        (thread_id,),
                    ).fetchone()
                    existing: dict = {}
                    if row and row["metadata"]:
                        try:
                            existing = json.loads(row["metadata"]) or {}
                        except (json.JSONDecodeError, TypeError):
                            existing = {}
                    existing["title_locked"] = True
                    conn.execute(
                        "UPDATE chat_threads SET title = ?, metadata = ? "
                        "WHERE id = ?",
                        (title, json.dumps(existing), thread_id),
                    )
                else:
                    conn.execute(
                        "UPDATE chat_threads SET title = ? WHERE id = ?",
                        (title, thread_id),
                    )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def set_meeting_active(
        self, thread_id: str, active: bool
    ) -> "ChatThread | None":
        """AD-920: set/clear ``metadata.meeting_active`` on a thread.

        A meeting is a live MODE of a group chat — the thread stays the
        transcript; this flag is what the UI gallery and (future) voice
        path read to know the meeting is open. Scoped writer (NOT a
        generic metadata PATCH) so callers cannot clobber sibling keys
        such as ``created_by_agent`` (AD-918) or ``title_locked``
        (AD-794). ``active=True`` sets the flag; ``active=False`` removes
        the key entirely (clean "not in a meeting"). The read-modify-
        write of the JSON ``metadata`` column uses ``BEGIN IMMEDIATE``
        for race safety, matching ``set_title(lock=True)``.

        Returns the updated thread, or ``None`` when the row is missing.
        """
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT metadata FROM chat_threads WHERE id = ?",
                    (thread_id,),
                ).fetchone()
                if row is None:
                    conn.execute("ROLLBACK")
                    return None
                existing: dict = {}
                if row["metadata"]:
                    try:
                        existing = json.loads(row["metadata"]) or {}
                    except (json.JSONDecodeError, TypeError):
                        existing = {}
                if active:
                    existing["meeting_active"] = True
                else:
                    existing.pop("meeting_active", None)
                conn.execute(
                    "UPDATE chat_threads SET metadata = ? WHERE id = ?",
                    (json.dumps(existing), thread_id),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return self.get_thread(thread_id)

    def is_title_locked(self, thread_id: str) -> bool:
        """AD-794: True when ``metadata.title_locked`` is set.

        Defensive against malformed JSON (architect R2): any decode or
        type error degrades to ``False`` rather than raising — auto-
        naming will be a no-op on the next call instead of bringing
        down the chat turn.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT metadata FROM chat_threads WHERE id = ?", (thread_id,)
            ).fetchone()
        if not row or not row["metadata"]:
            return False
        try:
            return bool(json.loads(row["metadata"]).get("title_locked"))
        except (json.JSONDecodeError, TypeError, AttributeError):
            return False

    # ---------- AD-913: participant management ----------

    def add_participant(self, thread_id: str, agent_id: str) -> ChatThread | None:
        """AD-913: add an agent to a thread's participant set (idempotent).

        Returns the updated ``ChatThread``, or ``None`` when the thread row
        is missing. Adding an agent already present is a no-op (no
        duplicate, no ``last_active_at`` bump). The read-modify-write of the
        JSON ``participants`` column runs under ``BEGIN IMMEDIATE`` for race
        safety, matching the ``set_title(lock=True)`` pattern.
        """
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT participants FROM chat_threads WHERE id = ?",
                    (thread_id,),
                ).fetchone()
                if row is None:
                    conn.execute("COMMIT")
                    return None
                current = json.loads(row["participants"]) if row["participants"] else []
                if agent_id not in current:
                    current.append(agent_id)
                    conn.execute(
                        "UPDATE chat_threads SET participants = ?, last_active_at = ? "
                        "WHERE id = ?",
                        (json.dumps(current), self._clock(), thread_id),
                    )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return self.get_thread(thread_id)

    def remove_participant(self, thread_id: str, agent_id: str) -> ChatThread | None:
        """AD-913: remove an agent from a thread's participant set (idempotent).

        Returns the updated ``ChatThread``, or ``None`` when the thread row
        is missing. Removing an agent that is not present is a no-op (no
        write, no ``last_active_at`` bump). Removes every copy defensively
        in case a pre-existing duplicate slipped in. ``BEGIN IMMEDIATE``
        read-modify-write per ``set_title(lock=True)``.
        """
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT participants FROM chat_threads WHERE id = ?",
                    (thread_id,),
                ).fetchone()
                if row is None:
                    conn.execute("COMMIT")
                    return None
                current = json.loads(row["participants"]) if row["participants"] else []
                if agent_id in current:
                    current = [p for p in current if p != agent_id]
                    conn.execute(
                        "UPDATE chat_threads SET participants = ?, last_active_at = ? "
                        "WHERE id = ?",
                        (json.dumps(current), self._clock(), thread_id),
                    )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return self.get_thread(thread_id)

    def maybe_auto_name(
        self, thread_id: str, body: str, *, force: bool = False
    ) -> "ChatThread | None":
        """AD-794: idempotent auto-name from a message body.

        Returns the renamed thread when naming fired; ``None`` when
        conditions weren't met.

        ``force=False`` (default — used by the first-turn auto-trigger
        wired in ``agent_chat``): the thread must have no prior
        messages (first-turn only), be single-participant, and have
        an unlocked title. Subsequent turns naturally accumulate
        messages, so a second auto-name attempt on the same thread
        no-ops without needing a per-thread "already renamed" flag.

        ``force=True`` (used by ``POST /api/threads/{id}/auto-name`` to
        preserve its pre-AD-794 always-rename behavior): only the
        title-lock check applies; any other state is renamed.

        Both modes respect the title_locked flag — manual operator
        rename via PATCH is always authoritative.
        """
        from probos.threads.naming import suggest_title

        thread = self.get_thread(thread_id)
        if thread is None:
            return None
        if self.is_title_locked(thread_id):
            return None

        suggested = suggest_title(body)
        if not suggested or suggested == "New thread":
            return None

        if not force:
            # First-turn auto-trigger pre-conditions: single-
            # participant + zero prior messages (anything else means
            # the thread has been used and its title — whether the
            # callsign default or an operator-chosen name — should be
            # left alone).
            if len(thread.participants) != 1:
                return None
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM chat_thread_messages "
                    "WHERE thread_id = ?",
                    (thread_id,),
                ).fetchone()
            if row and int(row["n"]) > 0:
                return None

        if suggested == thread.title:
            return None
        self.set_title(thread_id, suggested, lock=False)
        return self.get_thread(thread_id)

    def delete_thread(self, thread_id: str) -> bool:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM chat_thread_messages WHERE thread_id = ?", (thread_id,)
            )
            cur = conn.execute("DELETE FROM chat_threads WHERE id = ?", (thread_id,))
            return cur.rowcount > 0

    # ---------- AD-986d: retention purge + tombstones ----------

    def purge_thread(self, thread_id: str) -> bool:
        """Hard-delete a room's recording, leaving an AD-986d tombstone.

        Unlike :meth:`delete_thread` (a deliberate Captain removal, no trace),
        this is the *automatic retention* path: the thread row + every message
        body are deleted, but a tiny :class:`ChatThreadTombstone` (id, title,
        participants, last_active_at, purged_at) is written first so a
        participant who still holds a subjective memory of the room can be told
        the recording is gone. Returns ``True`` if a thread was purged.
        """
        thread = self.get_thread(thread_id)
        if thread is None:
            return False
        now = self._clock()
        with self._connect() as conn:
            # Tombstone first (so a crash mid-purge never deletes without a trace).
            conn.execute(
                "INSERT OR REPLACE INTO chat_thread_tombstones "
                "(id, title, participants, last_active_at, purged_at) "
                "VALUES (?,?,?,?,?)",
                (
                    thread.id,
                    thread.title,
                    json.dumps(list(thread.participants)),
                    thread.last_active_at,
                    now,
                ),
            )
            conn.execute(
                "DELETE FROM chat_thread_messages WHERE thread_id = ?", (thread_id,)
            )
            conn.execute("DELETE FROM chat_threads WHERE id = ?", (thread_id,))
        return True

    def purge_threads_older_than(
        self, cutoff_ts: float, *, exclude_pinned: bool = True, limit: int = 500
    ) -> list[str]:
        """Purge non-pinned rooms whose last activity predates ``cutoff_ts``.

        The retention reaper's workhorse. Selects candidate ids inside a bounded
        window (oldest-first), then purges each via :meth:`purge_thread` (so each
        gets a tombstone). Pinned rooms are exempt by default. Archived rooms ARE
        eligible — an archived-and-stale room is the prime purge candidate.
        Returns the list of purged thread ids.
        """
        clauses = ["last_active_at < ?"]
        params: list = [cutoff_ts]
        if exclude_pinned:
            clauses.append("pinned = 0")
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT id FROM chat_threads WHERE {' AND '.join(clauses)} "
                "ORDER BY last_active_at ASC LIMIT ?",
                (*params, max(1, limit)),
            ).fetchall()
        purged: list[str] = []
        for r in rows:
            if self.purge_thread(r["id"]):
                purged.append(r["id"])
        return purged

    def tombstones_for_participant(
        self, agent_ids: Iterable[str], *, limit: int = 8
    ) -> list[ChatThreadTombstone]:
        """AD-986d: purge tombstones for rooms ANY of ``agent_ids`` took part in,
        most-recently-purged first.

        Sovereign scope mirrors :meth:`threads_for_participant` — a crew agent is
        only ever told about the purge of a room it actually participated in.
        Bounded scan of a recent window.
        """
        ids = {a for a in (agent_ids or ()) if a}
        if not ids:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM chat_thread_tombstones "
                "ORDER BY purged_at DESC LIMIT ?",
                (200,),
            ).fetchall()
        out: list[ChatThreadTombstone] = []
        for r in rows:
            t = _row_to_tombstone(r)
            if set(t.participants) & ids:
                out.append(t)
                if len(out) >= max(1, limit):
                    break
        return out


    # ---------- AD-791a: implicit default-thread helpers ----------

    def find_default_for_agent(self, agent_id: str) -> ChatThread | None:
        """Find the implicit default 1:1 thread for an agent.

        Convention (AD-791a Section 5.1): a default thread is the oldest
        non-archived, non-project-bound row whose sole participant is the
        given ``agent_id``. The Captain is implicit \u2014 there is only ever
        one Captain per ProbOS instance, so ``participants = [agent_id]``
        uniquely identifies the Captain-to-agent 1:1 thread.

        Returns ``None`` if no such thread exists. Callers should use
        ``get_or_create_default_for_agent`` instead unless they want
        explicit no-create semantics.
        """
        participants_json = json.dumps([agent_id])
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM chat_threads "
                "WHERE participants = ? AND archived = 0 AND project_id IS NULL "
                "ORDER BY created_at ASC LIMIT 1",
                (participants_json,),
            ).fetchone()
        return _row_to_thread(row) if row else None

    def create_default_for_agent(
        self, agent_id: str, agent_callsign: str
    ) -> ChatThread:
        """Create the default 1:1 thread for an agent with ``metadata.is_default=True``.

        Title defaults to the agent's callsign (e.g. ``"Ezri"``). Not
        race-safe on its own \u2014 callers handling concurrent first-turn
        requests should use ``get_or_create_default_for_agent``.
        """
        thread_id = self._id_factory()
        now = self._clock()
        metadata = {"is_default": True}
        meta_json = json.dumps(metadata)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO chat_threads "
                "(id, title, participants, project_id, task_id, pinned, archived, "
                " personality_override, workspace_root, created_at, last_active_at, "
                " preprompt, model, metadata) "
                "VALUES (?,?,?,NULL,NULL,0,0,NULL,NULL,?,?,NULL,NULL,?)",
                (
                    thread_id,
                    agent_callsign,
                    json.dumps([agent_id]),
                    now,
                    now,
                    meta_json,
                ),
            )
        return ChatThread(
            id=thread_id,
            title=agent_callsign,
            participants=[agent_id],
            project_id=None,
            task_id=None,
            pinned=False,
            archived=False,
            personality_override=None,
            workspace_root=None,
            created_at=now,
            last_active_at=now,
            preprompt=None,
            model=None,
            metadata=metadata,
        )

    def get_or_create_default_for_agent(
        self, agent_id: str, agent_callsign: str
    ) -> ChatThread:
        """Atomic find-or-create: returns the implicit default 1:1 thread.

        Wraps the lookup-then-insert in ``BEGIN IMMEDIATE`` so two
        concurrent first-turn requests for the same ``agent_id`` cannot
        both insert. The second transaction blocks on the RESERVED lock
        held by the first, then on retry finds the row inserted by the
        first transaction and returns it.

        AD-791a Section 5.3: race-safe shim entry point. The 1:1 chat
        router (``routers/agents.py::agent_chat``) MUST use this rather
        than the bare ``find`` + ``create`` pair.
        """
        participants_json = json.dumps([agent_id])
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT * FROM chat_threads "
                    "WHERE participants = ? AND archived = 0 "
                    "AND project_id IS NULL "
                    "ORDER BY created_at ASC LIMIT 1",
                    (participants_json,),
                ).fetchone()
                if row is not None:
                    conn.execute("COMMIT")
                    return _row_to_thread(row)
                thread_id = self._id_factory()
                now = self._clock()
                metadata = {"is_default": True}
                meta_json = json.dumps(metadata)
                conn.execute(
                    "INSERT INTO chat_threads "
                    "(id, title, participants, project_id, task_id, pinned, "
                    " archived, personality_override, workspace_root, "
                    " created_at, last_active_at, preprompt, model, metadata) "
                    "VALUES (?,?,?,NULL,NULL,0,0,NULL,NULL,?,?,NULL,NULL,?)",
                    (
                        thread_id,
                        agent_callsign,
                        participants_json,
                        now,
                        now,
                        meta_json,
                    ),
                )
                conn.execute("COMMIT")
                return ChatThread(
                    id=thread_id,
                    title=agent_callsign,
                    participants=[agent_id],
                    project_id=None,
                    task_id=None,
                    pinned=False,
                    archived=False,
                    personality_override=None,
                    workspace_root=None,
                    created_at=now,
                    last_active_at=now,
                    preprompt=None,
                    model=None,
                    metadata=metadata,
                )
            except Exception:
                conn.execute("ROLLBACK")
                raise

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

    # AD-792: search + recents helpers for the sidebar.

    def search_threads(self, query: str, *, limit: int = 50) -> list[ChatThread]:
        """Case-insensitive LIKE search over thread title.

        v1 keeps it simple; AD-791b adds an FTS5 index covering both
        titles and message bodies. Empty query returns no rows so the
        UI can keep the input live without flooding the list.
        """
        q = query.strip()
        if not q:
            return []
        pat = f"%{q}%"
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM chat_threads WHERE title LIKE ? COLLATE NOCASE "
                "ORDER BY pinned DESC, last_active_at DESC LIMIT ?",
                (pat, max(1, min(limit, 200))),
            ).fetchall()
        return [_row_to_thread(r) for r in rows]

    def recents(self, *, limit: int = 20) -> list[ChatThread]:
        """Most-recently active non-archived threads, regardless of pin
        state. Used by the sidebar's "Recents" group below the pins.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM chat_threads WHERE archived = 0 "
                "ORDER BY last_active_at DESC LIMIT ?",
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [_row_to_thread(r) for r in rows]

    def threads_for_participant(
        self, agent_ids: Iterable[str], *, limit: int = 8
    ) -> list[ChatThread]:
        """AD-986b: non-archived threads where ANY of ``agent_ids`` is a
        participant, most-recently-active first.

        Sovereign scope for transcript-grounded recall — an agent may only
        consult transcripts of rooms it took part in. ``agent_ids`` is the set
        of the agent's OWN identifiers (id / sovereign_id); membership is the
        same id space stored in ``participants``. Bounded: scans a recent window
        and returns at most ``limit`` matches.
        """
        ids = {a for a in (agent_ids or ()) if a}
        if not ids:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM chat_threads WHERE archived = 0 "
                "ORDER BY last_active_at DESC LIMIT ?",
                (200,),
            ).fetchall()
        out: list[ChatThread] = []
        for r in rows:
            t = _row_to_thread(r)
            if set(t.participants) & ids:
                out.append(t)
                if len(out) >= max(1, limit):
                    break
        return out



# ──────────────────────────────────────────────────────────────────────────
# AD-793 (Wave 196): Project substrate.
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class Project:
    """AD-793: long-lived context group owning N chat threads + pinned files.

    The ``description`` is the project's defining contribution: a plain-
    prose "what this project is about" written by the Captain that
    injects as a system-message preamble on every chat turn inside
    threads belonging to the project (see ``routers/agents.py`` AD-793
    block — order is ``visual → project → recall → user``).
    """

    id: str
    name: str
    created_at: float
    last_active_at: float
    description: str = ""
    pinned_attachment_ids: list[str] = field(default_factory=list)
    archived: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "pinned_attachment_ids": list(self.pinned_attachment_ids),
            "archived": self.archived,
            "created_at": self.created_at,
            "last_active_at": self.last_active_at,
        }


class ProjectStore:
    """SQLite-backed Project store. Decoupled from ``ChatThreadStore``
    but shares the same db_path so cascade/unparent operations can
    touch chat_threads in the same database file via a single
    connection.

    Synchronous API — callers from async code should wrap in
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
        # Schema is shipped in ChatThreadStore's _SCHEMA; running it
        # again is idempotent (CREATE TABLE IF NOT EXISTS) and means
        # ProjectStore is self-sufficient even if instantiated before
        # ChatThreadStore in tests.
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # ---------- CRUD ----------

    def create_project(
        self,
        *,
        name: str,
        description: str = "",
        pinned_attachment_ids: list[str] | None = None,
    ) -> Project:
        project_id = self._id_factory()
        now = self._clock()
        pins = list(pinned_attachment_ids or [])
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO projects (id, name, description, "
                "pinned_attachment_ids, archived, created_at, "
                "last_active_at) VALUES (?,?,?,?,?,?,?)",
                (
                    project_id,
                    name,
                    description,
                    json.dumps(pins),
                    0,
                    now,
                    now,  # last_active_at == created_at at creation (spec)
                ),
            )
        return Project(
            id=project_id,
            name=name,
            description=description,
            pinned_attachment_ids=pins,
            archived=False,
            created_at=now,
            last_active_at=now,
        )

    def get_project(self, project_id: str) -> Project | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
        return _row_to_project(row) if row else None

    def list_projects(
        self, *, include_archived: bool = False, limit: int = 100
    ) -> list[Project]:
        clauses: list[str] = []
        params: list = []
        if not include_archived:
            clauses.append("archived = 0")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM projects {where} "
                "ORDER BY last_active_at DESC LIMIT ?",
                (*params, max(1, min(limit, 500))),
            ).fetchall()
        return [_row_to_project(r) for r in rows]

    def update_project(
        self,
        project_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        archived: bool | None = None,
    ) -> Project | None:
        sets: list[str] = []
        params: list = []
        for col, val in (
            ("name", name),
            ("description", description),
            ("archived", None if archived is None else int(archived)),
        ):
            if val is not None:
                sets.append(f"{col} = ?")
                params.append(val)
        if not sets:
            return self.get_project(project_id)
        params.append(project_id)
        with self._connect() as conn:
            cur = conn.execute(
                f"UPDATE projects SET {', '.join(sets)} WHERE id = ?", params
            )
            if cur.rowcount == 0:
                return None
        return self.get_project(project_id)

    def delete_project(
        self, project_id: str, *, cascade: bool = False
    ) -> tuple[bool, int]:
        """Delete a project. Returns ``(deleted, affected_threads)``.

        Default (``cascade=False``): set ``project_id=NULL`` on contained
        threads (unparent), then delete the project row.

        ``cascade=True``: delete contained threads + their messages
        (matches ``ChatThreadStore.delete_thread`` cascade pattern),
        then delete the project row.

        Episodes / AD-541b anchors are preserved in BOTH paths — this
        store only touches the chat_threads + chat_thread_messages +
        projects tables.
        """
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                # Confirm the project exists first so we return a clean
                # (False, 0) when the row is already gone.
                row = conn.execute(
                    "SELECT id FROM projects WHERE id = ?", (project_id,)
                ).fetchone()
                if row is None:
                    conn.execute("COMMIT")
                    return False, 0

                if cascade:
                    thread_rows = conn.execute(
                        "SELECT id FROM chat_threads WHERE project_id = ?",
                        (project_id,),
                    ).fetchall()
                    affected = len(thread_rows)
                    for tr in thread_rows:
                        conn.execute(
                            "DELETE FROM chat_thread_messages "
                            "WHERE thread_id = ?",
                            (tr["id"],),
                        )
                    conn.execute(
                        "DELETE FROM chat_threads WHERE project_id = ?",
                        (project_id,),
                    )
                else:
                    cur = conn.execute(
                        "UPDATE chat_threads SET project_id = NULL "
                        "WHERE project_id = ?",
                        (project_id,),
                    )
                    affected = cur.rowcount

                conn.execute(
                    "DELETE FROM projects WHERE id = ?", (project_id,)
                )
                conn.execute("COMMIT")
                return True, affected
            except Exception:
                conn.execute("ROLLBACK")
                raise

    # ---------- Pin/unpin ----------

    def pin_attachment(
        self, project_id: str, attachment_id: str
    ) -> Project | None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT pinned_attachment_ids FROM projects WHERE id = ?",
                    (project_id,),
                ).fetchone()
                if row is None:
                    conn.execute("COMMIT")
                    return None
                try:
                    pins = json.loads(row["pinned_attachment_ids"]) or []
                except (json.JSONDecodeError, TypeError):
                    pins = []
                if attachment_id not in pins:
                    pins.append(attachment_id)
                    conn.execute(
                        "UPDATE projects SET pinned_attachment_ids = ? "
                        "WHERE id = ?",
                        (json.dumps(pins), project_id),
                    )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return self.get_project(project_id)

    def unpin_attachment(
        self, project_id: str, attachment_id: str
    ) -> Project | None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT pinned_attachment_ids FROM projects WHERE id = ?",
                    (project_id,),
                ).fetchone()
                if row is None:
                    conn.execute("COMMIT")
                    return None
                try:
                    pins = json.loads(row["pinned_attachment_ids"]) or []
                except (json.JSONDecodeError, TypeError):
                    pins = []
                if attachment_id in pins:
                    pins = [a for a in pins if a != attachment_id]
                    conn.execute(
                        "UPDATE projects SET pinned_attachment_ids = ? "
                        "WHERE id = ?",
                        (json.dumps(pins), project_id),
                    )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return self.get_project(project_id)

    # ---------- touch ----------

    def touch(self, project_id: str, *, now: float | None = None) -> None:
        """AD-793: bump ``last_active_at`` for a project.

        Called from the router-layer message-append handler in
        ``routers/threads.py`` so the threads substrate stays decoupled
        from the projects layer. Honest-degrade: missing row no-ops.
        """
        ts = now if now is not None else self._clock()
        with self._connect() as conn:
            conn.execute(
                "UPDATE projects SET last_active_at = ? WHERE id = ?",
                (ts, project_id),
            )


def _row_to_project(row: sqlite3.Row) -> Project:
    try:
        pins = json.loads(row["pinned_attachment_ids"]) or []
    except (json.JSONDecodeError, TypeError):
        pins = []
    return Project(
        id=row["id"],
        name=row["name"],
        description=row["description"] or "",
        pinned_attachment_ids=list(pins),
        archived=bool(row["archived"]),
        created_at=row["created_at"],
        last_active_at=row["last_active_at"],
    )


def _row_to_thread(row: sqlite3.Row) -> ChatThread:
    # AD-791a: read the additive v2 columns defensively. ``PRAGMA
    # table_info``-driven migration guarantees they exist post-init,
    # but row access via column name fails with KeyError if a stale
    # connection was opened before migration ran in another process —
    # so we use ``row.keys()`` membership before indexing.
    keys = set(row.keys())
    preprompt = row["preprompt"] if "preprompt" in keys else None
    model = row["model"] if "model" in keys else None
    raw_meta = row["metadata"] if "metadata" in keys else None
    try:
        metadata = json.loads(raw_meta) if raw_meta else {}
    except (json.JSONDecodeError, TypeError):
        metadata = {}
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
        preprompt=preprompt,
        model=model,
        metadata=metadata,
    )


def _migrate_v2(conn: sqlite3.Connection) -> None:
    """AD-791a: idempotently add v2 columns to chat_threads / chat_thread_messages.

    SQLite has no ``ALTER TABLE ... ADD COLUMN IF NOT EXISTS``, so we
    enumerate existing columns via ``PRAGMA table_info`` and only emit
    DDL for columns that are missing. Safe to call on every
    ``ChatThreadStore.__init__`` — first boot adds the columns, every
    subsequent boot is a no-op.

    Pattern absorbed from ``substrate/event_log.py`` lines 86-124
    (translated from ``aiosqlite`` async to sync ``sqlite3``).
    """
    threads_cols = {row[1] for row in conn.execute("PRAGMA table_info(chat_threads)")}
    messages_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(chat_thread_messages)")
    }

    threads_additions = {
        "preprompt": "ALTER TABLE chat_threads ADD COLUMN preprompt TEXT",
        "model": "ALTER TABLE chat_threads ADD COLUMN model TEXT",
        "metadata": "ALTER TABLE chat_threads ADD COLUMN metadata TEXT",
    }
    for col, ddl in threads_additions.items():
        if col not in threads_cols:
            conn.execute(ddl)

    messages_additions = {
        "parent_message_id": (
            "ALTER TABLE chat_thread_messages ADD COLUMN parent_message_id TEXT"
        ),
        "branch_ordinal": (
            "ALTER TABLE chat_thread_messages ADD COLUMN branch_ordinal "
            "INTEGER NOT NULL DEFAULT 0"
        ),
        "score": (
            "ALTER TABLE chat_thread_messages ADD COLUMN score "
            "INTEGER NOT NULL DEFAULT 0"
        ),
        "interrupted": (
            "ALTER TABLE chat_thread_messages ADD COLUMN interrupted "
            "INTEGER NOT NULL DEFAULT 0"
        ),
    }
    for col, ddl in messages_additions.items():
        if col not in messages_cols:
            conn.execute(ddl)

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_branch "
        "ON chat_thread_messages (thread_id, parent_message_id)"
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


def _row_to_tombstone(row: sqlite3.Row) -> ChatThreadTombstone:
    """AD-986d: hydrate a :class:`ChatThreadTombstone` from a tombstone row."""
    try:
        parts = json.loads(row["participants"]) if row["participants"] else []
    except (json.JSONDecodeError, TypeError):
        parts = []
    return ChatThreadTombstone(
        id=row["id"],
        title=row["title"],
        participants=list(parts) if isinstance(parts, list) else [],
        last_active_at=row["last_active_at"],
        purged_at=row["purged_at"],
    )
