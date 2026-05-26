"""AD-797: artifacts substrate — versioned, content-addressable artifacts.

An artifact is a *named, versioned* output produced by an agent or the
operator inside the scope of a chat thread (AD-791). The bytes live in
the existing ``AttachmentStore`` (AD-720 content-addressable SHA-256
store); this module is a thin metadata layer that gives those bytes a
human-meaningful name + a version chain.

Tables:
    artifacts:
        id, thread_id (FK chat_threads), name, version, content_hash,
        mime, size_bytes, created_by, created_at, supersedes

Constraints:
    * (thread_id, name, version) is unique.
    * Versions are auto-assigned: the next ``add_version`` for a given
      (thread_id, name) increments from MAX(version) + 1.
    * ``supersedes`` points at the previous version's id (or NULL for v1).

What v1 does NOT do:
    * Diff / merge across versions (AD-797a).
    * Cross-thread artifact sharing (AD-797b).
    * GC sweep of dangling content_hash blobs (rides on AD-733-1 reaper).
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

_SCHEMA = """
CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    name TEXT NOT NULL,
    version INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    mime TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    created_by TEXT NOT NULL,
    created_at REAL NOT NULL,
    supersedes TEXT,
    UNIQUE (thread_id, name, version)
);
CREATE INDEX IF NOT EXISTS idx_artifacts_thread ON artifacts (thread_id, name, version);
CREATE INDEX IF NOT EXISTS idx_artifacts_hash ON artifacts (content_hash);
"""


@dataclass
class Artifact:
    id: str
    thread_id: str
    name: str
    version: int
    content_hash: str
    mime: str
    size_bytes: int
    created_by: str
    created_at: float
    supersedes: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "thread_id": self.thread_id,
            "name": self.name,
            "version": self.version,
            "content_hash": self.content_hash,
            "mime": self.mime,
            "size_bytes": self.size_bytes,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "supersedes": self.supersedes,
        }


class ArtifactStore:
    """SQLite-backed metadata store for AD-797 artifacts."""

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
        return conn

    def add_version(
        self,
        *,
        thread_id: str,
        name: str,
        content_hash: str,
        mime: str,
        size_bytes: int,
        created_by: str,
    ) -> Artifact:
        """Add a new version of ``(thread_id, name)``.

        The version is auto-assigned as ``MAX(version) + 1`` for the
        existing (thread_id, name) chain (starting at 1). ``supersedes``
        is set to the id of the previous version.
        """
        artifact_id = self._id_factory()
        now = self._clock()
        with self._connect() as conn:
            # BF-324 (Wave 197): wrap SELECT MAX + INSERT in BEGIN IMMEDIATE
            # so two concurrent add_version calls on the same
            # (thread_id, name) cannot collide on the
            # UNIQUE (thread_id, name, version) constraint. Matches the
            # AD-791a / AD-793 transaction pattern.
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT id, version FROM artifacts "
                    "WHERE thread_id = ? AND name = ? "
                    "ORDER BY version DESC LIMIT 1",
                    (thread_id, name),
                ).fetchone()
                if row is None:
                    version = 1
                    supersedes = None
                else:
                    version = row["version"] + 1
                    supersedes = row["id"]
                conn.execute(
                    "INSERT INTO artifacts (id, thread_id, name, version, content_hash, "
                    "mime, size_bytes, created_by, created_at, supersedes) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        artifact_id,
                        thread_id,
                        name,
                        version,
                        content_hash,
                        mime,
                        size_bytes,
                        created_by,
                        now,
                        supersedes,
                    ),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return Artifact(
            id=artifact_id,
            thread_id=thread_id,
            name=name,
            version=version,
            content_hash=content_hash,
            mime=mime,
            size_bytes=size_bytes,
            created_by=created_by,
            created_at=now,
            supersedes=supersedes,
        )

    def get(self, artifact_id: str) -> Artifact | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM artifacts WHERE id = ?", (artifact_id,)
            ).fetchone()
        return _row(row) if row else None

    def latest(self, *, thread_id: str, name: str) -> Artifact | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM artifacts WHERE thread_id = ? AND name = ? "
                "ORDER BY version DESC LIMIT 1",
                (thread_id, name),
            ).fetchone()
        return _row(row) if row else None

    def list_versions(self, *, thread_id: str, name: str) -> list[Artifact]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM artifacts WHERE thread_id = ? AND name = ? "
                "ORDER BY version ASC",
                (thread_id, name),
            ).fetchall()
        return [_row(r) for r in rows]

    def list_thread_latest(self, thread_id: str) -> list[Artifact]:
        """Return the latest version of every distinct artifact name in
        ``thread_id``, ordered by most-recently-created descending. This
        is the default "Artifacts pane" listing.
        """
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT a.* FROM artifacts a
                INNER JOIN (
                    SELECT name, MAX(version) AS max_version
                    FROM artifacts WHERE thread_id = ?
                    GROUP BY name
                ) m ON a.name = m.name AND a.version = m.max_version
                WHERE a.thread_id = ?
                ORDER BY a.created_at DESC
                """,
                (thread_id, thread_id),
            ).fetchall()
        return [_row(r) for r in rows]

    def delete(self, artifact_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM artifacts WHERE id = ?", (artifact_id,))
            return cur.rowcount > 0

    def find_first_by_hash(self, content_hash: str) -> Artifact | None:
        """AD-797 (Wave 197): return the earliest-created Artifact whose
        ``content_hash`` matches, or ``None`` if no row exists.

        Used by the project-pinned merge in
        ``routers/artifacts.list_thread_artifacts`` to surface artifacts
        pinned at the project scope but originally created in a different
        thread. First-by-time is deterministic; AD-797h is the forward
        marker for canonical cross-thread artifact identity.

        Uses the existing ``idx_artifacts_hash`` index.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM artifacts WHERE content_hash = ? "
                "ORDER BY created_at ASC LIMIT 1",
                (content_hash,),
            ).fetchone()
        return _row(row) if row else None


def _row(row: sqlite3.Row) -> Artifact:
    return Artifact(
        id=row["id"],
        thread_id=row["thread_id"],
        name=row["name"],
        version=row["version"],
        content_hash=row["content_hash"],
        mime=row["mime"],
        size_bytes=row["size_bytes"],
        created_by=row["created_by"],
        created_at=row["created_at"],
        supersedes=row["supersedes"],
    )
