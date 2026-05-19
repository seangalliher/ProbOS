"""AD-742f: SQLite persistence for VisionWorkingMemory ring buffers.

Tier-2 honest-degrade: every method swallows DB exceptions, logs WARNING,
and lets the caller operate in-memory only. The store NEVER raises into the
VisionWorkingMemory hot path — frame describe must not fail because of a
DB lock.

AD-731 invariant: descriptions are text; SHA refs point at AttachmentStore.
NO image bytes in this DB.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from probos.perception.working_memory import VisionObservation

logger = logging.getLogger(__name__)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS vision_observations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id        TEXT NOT NULL,
    timestamp       REAL NOT NULL,
    attachment_ref  TEXT NOT NULL,
    description     TEXT NOT NULL,
    novelty_score   REAL NOT NULL,
    subject_identity TEXT NOT NULL DEFAULT 'unknown',
    session_id      TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_vision_observations_agent_ts
    ON vision_observations (agent_id, timestamp);
"""


class WorkingMemoryStore:
    """Synchronous sqlite3-backed ring persistence.

    Sync rather than aiosqlite because VisionWorkingMemory.append is called
    from synchronous WM code; we don't have an event loop handle there. The
    write path is short (<1 ms) and protected by a module-level lock so
    multiple agents writing concurrently don't fight the connection.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._lock = Lock()
        self._available = False
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self._db_path) as conn:
                conn.executescript(_SCHEMA)
                conn.commit()
            self._available = True
            logger.info("AD-742f: vision WM store ready at %s", self._db_path)
        except Exception:
            logger.warning(
                "AD-742f: WM store init failed at %s; perception WM will be in-memory only",
                self._db_path,
                exc_info=True,
            )

    @property
    def available(self) -> bool:
        return self._available

    def load_for_agent(self, agent_id: str, *, capacity: int) -> list["VisionObservation"]:
        """Newest-last (deque insert order) up to ``capacity`` rows."""
        if not self._available:
            return []
        from probos.perception.working_memory import VisionObservation
        try:
            with self._lock, sqlite3.connect(self._db_path) as conn:
                cursor = conn.execute(
                    "SELECT timestamp, attachment_ref, description, novelty_score, "
                    "subject_identity, session_id FROM vision_observations "
                    "WHERE agent_id = ? ORDER BY timestamp DESC LIMIT ?",
                    (agent_id, int(capacity)),
                )
                rows = list(cursor.fetchall())
        except Exception:
            logger.warning(
                "AD-742f: load_for_agent(%s) failed; returning empty",
                agent_id, exc_info=True,
            )
            return []
        # Reverse so the deque receives oldest-first -> newest-last.
        rows.reverse()
        return [
            VisionObservation(
                timestamp=float(r[0]),
                attachment_ref=str(r[1]),
                description=str(r[2]),
                novelty_score=float(r[3]),
                subject_identity=str(r[4]),
                session_id=str(r[5]),
            )
            for r in rows
        ]

    def append(self, agent_id: str, obs: "VisionObservation", *, capacity: int) -> None:
        """Insert + evict-oldest-beyond-capacity. Best-effort."""
        if not self._available:
            return
        try:
            with self._lock, sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    "INSERT INTO vision_observations "
                    "(agent_id, timestamp, attachment_ref, description, "
                    "novelty_score, subject_identity, session_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        agent_id,
                        float(obs.timestamp),
                        str(obs.attachment_ref),
                        str(obs.description),
                        float(obs.novelty_score),
                        str(obs.subject_identity),
                        str(obs.session_id),
                    ),
                )
                # Evict any rows beyond capacity for THIS agent. Keep the
                # newest ``capacity`` by timestamp; delete the rest.
                conn.execute(
                    "DELETE FROM vision_observations WHERE id IN ("
                    "  SELECT id FROM vision_observations WHERE agent_id = ? "
                    "  ORDER BY timestamp DESC LIMIT -1 OFFSET ?"
                    ")",
                    (agent_id, int(capacity)),
                )
                conn.commit()
        except Exception:
            logger.warning(
                "AD-742f: append(%s) failed; in-memory ring still updated",
                agent_id, exc_info=True,
            )

    def clear_for_agent(self, agent_id: str) -> None:
        """Test helper + operator reset."""
        if not self._available:
            return
        try:
            with self._lock, sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    "DELETE FROM vision_observations WHERE agent_id = ?",
                    (agent_id,),
                )
                conn.commit()
        except Exception:
            logger.warning(
                "AD-742f: clear_for_agent(%s) failed", agent_id, exc_info=True,
            )


__all__ = ["WorkingMemoryStore"]
