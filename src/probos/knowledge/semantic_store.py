"""Semantic work layer persistence (AD-750).

SQLite-backed store for personal tasks, meetings, commitments, and threads.
Uses an abstract _StoreBackend Protocol so the commercial overlay can swap
SQLite for Postgres without changing business logic (Cloud-Ready Storage rule).
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import threading
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

from probos.types import (
    Commitment,
    Meeting,
    SemanticEntity,
    Task,
    WorkThread,
)

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entities (
    id          TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    owner_id    TEXT NOT NULL,
    created_at  REAL NOT NULL,
    modified_at REAL NOT NULL,
    content     TEXT NOT NULL,
    payload     TEXT NOT NULL  -- JSON-serialised subclass fields
);

CREATE INDEX IF NOT EXISTS idx_entities_type   ON entities (entity_type);
CREATE INDEX IF NOT EXISTS idx_entities_owner  ON entities (owner_id);
CREATE INDEX IF NOT EXISTS idx_entities_mtime  ON entities (modified_at);

CREATE VIRTUAL TABLE IF NOT EXISTS entities_fts USING fts5(
    id UNINDEXED,
    content,
    payload,
    tokenize = 'unicode61'
);

CREATE TABLE IF NOT EXISTS entity_links (
    source_id   TEXT NOT NULL,
    target_id   TEXT NOT NULL,
    link_type   TEXT NOT NULL,
    created_at  REAL NOT NULL,
    PRIMARY KEY (source_id, target_id, link_type)
);

CREATE INDEX IF NOT EXISTS idx_links_source ON entity_links (source_id);
CREATE INDEX IF NOT EXISTS idx_links_target ON entity_links (target_id);
"""


# ------------------------------------------------------------------
# Abstract backend protocol (enables SQLite → Postgres swap)
# ------------------------------------------------------------------


class _StoreBackend(Protocol):
    """Minimal database backend interface. Implementations are sync."""

    def setup(self, schema_sql: str) -> None:
        """Initialize schema."""
        ...

    def run(self, sql: str, params: tuple = ()) -> None:
        """Execute a write statement and commit."""
        ...

    def run_many(self, sql: str, params_seq: list[tuple]) -> None:
        """Execute a write with multiple parameter sets and commit."""
        ...

    def query(self, sql: str, params: tuple = ()) -> list[Any]:
        """Execute a read statement and return all rows."""
        ...

    def close(self) -> None:
        """Release resources."""
        ...


class _SQLiteBackend:
    """Concrete SQLite backend using stdlib sqlite3."""

    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()

    def setup(self, schema_sql: str) -> None:
        with self._lock:
            self._conn.executescript(schema_sql)
            self._conn.commit()

    def run(self, sql: str, params: tuple = ()) -> None:
        with self._lock:
            self._conn.execute(sql, params)
            self._conn.commit()

    def run_many(self, sql: str, params_seq: list[tuple]) -> None:
        with self._lock:
            self._conn.executemany(sql, params_seq)
            self._conn.commit()

    def query(self, sql: str, params: tuple = ()) -> list[Any]:
        with self._lock:
            cursor = self._conn.execute(sql, params)
            return cursor.fetchall()

    def close(self) -> None:
        self._conn.close()


# ------------------------------------------------------------------
# Serialisation helpers
# ------------------------------------------------------------------


def _dt_to_float(dt: datetime | None) -> float | None:
    """Convert datetime to epoch float, or None."""
    if dt is None:
        return None
    return dt.timestamp()


def _float_to_dt(ts: float | None) -> datetime | None:
    """Convert epoch float to UTC datetime, or None."""
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def _entity_to_row(entity: SemanticEntity) -> tuple:
    """Serialise a SemanticEntity into the (id, entity_type, ..., payload) row."""
    base_fields = {
        "id", "entity_type", "owner_id", "created_at", "modified_at", "content",
    }
    d = asdict(entity)
    payload: dict[str, Any] = {}
    for k, v in d.items():
        if k not in base_fields:
            # Convert datetime values to epoch float for JSON storage
            if isinstance(v, datetime):
                payload[k] = v.timestamp()
            else:
                payload[k] = v

    return (
        entity.id,
        entity.entity_type,
        entity.owner_id,
        entity.created_at.timestamp(),
        entity.modified_at.timestamp(),
        entity.content,
        json.dumps(payload),
    )


def _row_to_entity(row: Any) -> SemanticEntity | None:
    """Deserialise a database row back to the appropriate SemanticEntity subclass."""
    try:
        payload = json.loads(row["payload"])
        created_at = _float_to_dt(row["created_at"]) or datetime.now(timezone.utc)
        modified_at = _float_to_dt(row["modified_at"]) or datetime.now(timezone.utc)
        etype = row["entity_type"]

        base_kwargs: dict[str, Any] = dict(
            id=row["id"],
            entity_type=etype,
            owner_id=row["owner_id"],
            created_at=created_at,
            modified_at=modified_at,
            content=row["content"],
        )

        if etype == "task":
            due_ts = payload.get("due_date")
            return Task(
                **base_kwargs,
                title=payload.get("title", ""),
                due_date=_float_to_dt(due_ts),
                completed=bool(payload.get("completed", False)),
                delegated_to_agent=payload.get("delegated_to_agent"),
                priority=int(payload.get("priority", 1)),
            )
        if etype == "meeting":
            return Meeting(
                **base_kwargs,
                title=payload.get("title", ""),
                start_time=_float_to_dt(payload.get("start_time")) or created_at,
                end_time=_float_to_dt(payload.get("end_time")) or created_at,
                attendees=payload.get("attendees", []),
                location=payload.get("location"),
            )
        if etype == "commitment":
            return Commitment(
                **base_kwargs,
                description=payload.get("description", ""),
                deadline=_float_to_dt(payload.get("deadline")) or created_at,
                stake_agent=payload.get("stake_agent", ""),
                status=payload.get("status", "open"),
            )
        if etype == "thread":
            return WorkThread(
                **base_kwargs,
                topic=payload.get("topic", ""),
                messages=payload.get("messages", []),
                related_tasks=payload.get("related_tasks", []),
                related_meetings=payload.get("related_meetings", []),
            )
        # Generic fallback
        return SemanticEntity(**base_kwargs)
    except Exception:
        logger.warning(
            "SemanticStore: failed to deserialise row id=%s; skipping",
            row["id"] if row else "?",
            exc_info=True,
        )
        return None


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------


class SemanticStore:
    """SQLite-backed store for personal work semantics.

    All public methods are async; synchronous SQLite operations run via
    run_in_executor to remain compatible with WindowsSelectorEventLoop.

    Accepts an optional ``semantic_search_fn`` callable for ChromaDB-powered
    semantic search — injected to avoid a circular import with episodic.py.
    """

    def __init__(
        self,
        db_path: str,
        owner_id: str,
        backend: _StoreBackend | None = None,
        semantic_search_fn: Callable[[str], list[str]] | None = None,
    ) -> None:
        self._owner_id = owner_id
        self._semantic_search_fn = semantic_search_fn
        self._backend: _StoreBackend = backend or _SQLiteBackend(db_path)
        self._backend.setup(_SCHEMA)
        logger.info(
            "SemanticStore initialised for owner=%s db=%s", owner_id, db_path
        )

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    async def insert_entity(self, entity: SemanticEntity) -> None:
        """Add or update a task/meeting/commitment/thread in the store."""
        row = _entity_to_row(entity)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            self._backend.run,
            """INSERT OR REPLACE INTO entities
               (id, entity_type, owner_id, created_at, modified_at, content, payload)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            row,
        )
        # Update FTS index
        await loop.run_in_executor(
            None,
            self._backend.run,
            """INSERT OR REPLACE INTO entities_fts (id, content, payload)
               VALUES (?, ?, ?)""",
            (entity.id, entity.content, row[-1]),
        )
        logger.debug(
            "SemanticStore: inserted %s id=%s", entity.entity_type, entity.id
        )

    async def link_entities(
        self, source_id: str, target_ids: list[str], link_type: str
    ) -> None:
        """Create cross-references between entities (e.g. task depends on meeting)."""
        now = datetime.now(timezone.utc).timestamp()
        params_seq = [
            (source_id, target_id, link_type, now) for target_id in target_ids
        ]
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            self._backend.run_many,
            """INSERT OR IGNORE INTO entity_links
               (source_id, target_id, link_type, created_at)
               VALUES (?, ?, ?, ?)""",
            params_seq,
        )
        logger.debug(
            "SemanticStore: linked %s → %d targets (type=%s)",
            source_id, len(target_ids), link_type,
        )

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def query_tasks(
        self,
        due_before: datetime | None = None,
        completed: bool = False,
    ) -> list[Task]:
        """List tasks, optionally filtered by completion status and due date."""
        loop = asyncio.get_running_loop()
        if due_before is not None:
            rows = await loop.run_in_executor(
                None,
                self._backend.query,
                """SELECT * FROM entities
                   WHERE entity_type = 'task'
                     AND owner_id = ?
                     AND json_extract(payload, '$.completed') = ?
                     AND (json_extract(payload, '$.due_date') IS NULL
                          OR json_extract(payload, '$.due_date') <= ?)
                   ORDER BY modified_at DESC""",
                (self._owner_id, 1 if completed else 0, due_before.timestamp()),
            )
        else:
            rows = await loop.run_in_executor(
                None,
                self._backend.query,
                """SELECT * FROM entities
                   WHERE entity_type = 'task'
                     AND owner_id = ?
                     AND json_extract(payload, '$.completed') = ?
                   ORDER BY modified_at DESC""",
                (self._owner_id, 1 if completed else 0),
            )
        return [e for row in rows if (e := _row_to_entity(row)) and isinstance(e, Task)]

    async def query_meetings(
        self, date_range: tuple[datetime, datetime]
    ) -> list[Meeting]:
        """List meetings within a date range."""
        start_ts = date_range[0].timestamp()
        end_ts = date_range[1].timestamp()
        loop = asyncio.get_running_loop()
        rows = await loop.run_in_executor(
            None,
            self._backend.query,
            """SELECT * FROM entities
               WHERE entity_type = 'meeting'
                 AND owner_id = ?
                 AND json_extract(payload, '$.start_time') >= ?
                 AND json_extract(payload, '$.start_time') <= ?
               ORDER BY json_extract(payload, '$.start_time') ASC""",
            (self._owner_id, start_ts, end_ts),
        )
        return [
            e for row in rows
            if (e := _row_to_entity(row)) and isinstance(e, Meeting)
        ]

    async def query_commitments(self, status: str = "open") -> list[Commitment]:
        """List commitments filtered by status."""
        loop = asyncio.get_running_loop()
        rows = await loop.run_in_executor(
            None,
            self._backend.query,
            """SELECT * FROM entities
               WHERE entity_type = 'commitment'
                 AND owner_id = ?
                 AND json_extract(payload, '$.status') = ?
               ORDER BY modified_at DESC""",
            (self._owner_id, status),
        )
        return [
            e for row in rows
            if (e := _row_to_entity(row)) and isinstance(e, Commitment)
        ]

    async def search(self, query: str) -> list[SemanticEntity]:
        """Full-text search across all entities (SQLite FTS5 keyword + optional ChromaDB semantic).

        If a ``semantic_search_fn`` was provided at construction, it is called
        first to get a ranked list of entity IDs via ChromaDB, then the keyword
        results are appended (deduped). Otherwise, keyword-only results are
        returned.
        """
        loop = asyncio.get_running_loop()

        # Keyword search via FTS5
        safe_query = query.replace('"', '""')
        fts_rows = await loop.run_in_executor(
            None,
            self._backend.query,
            """SELECT e.* FROM entities e
               JOIN entities_fts fts ON fts.id = e.id
               WHERE entities_fts MATCH ?
                 AND e.owner_id = ?
               ORDER BY rank""",
            (f'"{safe_query}"', self._owner_id),
        )
        keyword_entities: list[SemanticEntity] = [
            e for row in fts_rows if (e := _row_to_entity(row)) is not None
        ]

        if self._semantic_search_fn is None:
            return keyword_entities

        # Optional ChromaDB semantic search
        try:
            semantic_ids: list[str] = self._semantic_search_fn(query)
            seen = {e.id for e in keyword_entities}
            if semantic_ids:
                placeholders = ",".join("?" * len(semantic_ids))
                sem_rows = await loop.run_in_executor(
                    None,
                    self._backend.query,
                    f"""SELECT * FROM entities
                        WHERE id IN ({placeholders}) AND owner_id = ?""",
                    (*semantic_ids, self._owner_id),
                )
                for row in sem_rows:
                    e = _row_to_entity(row)
                    if e and e.id not in seen:
                        keyword_entities.append(e)
                        seen.add(e.id)
        except Exception:
            logger.warning(
                "SemanticStore.search: semantic_search_fn raised; "
                "falling back to keyword results only",
                exc_info=True,
            )

        return keyword_entities

    async def get_linked_entity_ids(
        self, source_id: str, link_type: str | None = None
    ) -> list[str]:
        """Return IDs of entities linked from source_id."""
        loop = asyncio.get_running_loop()
        if link_type:
            rows = await loop.run_in_executor(
                None,
                self._backend.query,
                "SELECT target_id FROM entity_links WHERE source_id = ? AND link_type = ?",
                (source_id, link_type),
            )
        else:
            rows = await loop.run_in_executor(
                None,
                self._backend.query,
                "SELECT target_id FROM entity_links WHERE source_id = ?",
                (source_id,),
            )
        return [row["target_id"] for row in rows]

    def close(self) -> None:
        """Release database resources."""
        self._backend.close()
