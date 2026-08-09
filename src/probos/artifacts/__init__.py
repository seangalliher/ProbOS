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
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

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
CREATE INDEX IF NOT EXISTS idx_artifacts_creator ON artifacts (created_by, created_at);
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
        self._version_committed_callback: Callable[[Artifact], None] | None = None
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def set_version_committed_callback(
        self,
        callback: Callable[[Artifact], None] | None,
    ) -> None:
        self._version_committed_callback = callback

    def _notify_version_committed(self, artifact: Artifact) -> None:
        callback = self._version_committed_callback
        if callback is None:
            return
        try:
            callback(artifact)
        except Exception:
            logger.warning(
                "Artifact %s version %d committed but its live-refresh callback "
                "failed; clients will repair on reconnect",
                artifact.id,
                artifact.version,
                exc_info=True,
            )

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
        artifact = Artifact(
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
        self._notify_version_committed(artifact)
        return artifact

    def reconcile_exact_version(
        self,
        *,
        thread_id: str,
        name: str,
        content_hash: str,
        mime: str,
        size_bytes: int,
        created_by: str,
    ) -> Artifact:
        """Create v1 for an empty chain or reuse its one exact row."""
        created: Artifact | None = None
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                rows = conn.execute(
                    "SELECT * FROM artifacts WHERE thread_id = ? AND name = ? "
                    "ORDER BY version ASC",
                    (thread_id, name),
                ).fetchall()
                if len(rows) > 1:
                    raise ValueError("artifact_exact_match_ambiguous")
                if len(rows) == 1:
                    artifact = _row(rows[0])
                    if (
                        artifact.content_hash != content_hash
                        or artifact.mime != mime
                        or artifact.size_bytes != size_bytes
                        or artifact.created_by != created_by
                    ):
                        raise ValueError("artifact_exact_match_conflict")
                    conn.execute("COMMIT")
                    return artifact

                created = Artifact(
                    id=self._id_factory(),
                    thread_id=thread_id,
                    name=name,
                    version=1,
                    content_hash=content_hash,
                    mime=mime,
                    size_bytes=size_bytes,
                    created_by=created_by,
                    created_at=self._clock(),
                )
                conn.execute(
                    "INSERT INTO artifacts (id, thread_id, name, version, "
                    "content_hash, mime, size_bytes, created_by, created_at, "
                    "supersedes) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        created.id,
                        created.thread_id,
                        created.name,
                        created.version,
                        created.content_hash,
                        created.mime,
                        created.size_bytes,
                        created.created_by,
                        created.created_at,
                        created.supersedes,
                    ),
                )
                conn.execute("COMMIT")
            except BaseException:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
        if created is None:
            raise ValueError("artifact_exact_match_create_failed")
        self._notify_version_committed(created)
        return created

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

    def list_thread_latest(
        self,
        thread_id: str,
        *,
        limit: int | None = None,
    ) -> list[Artifact]:
        """Return the latest version of every distinct artifact name in
        ``thread_id``, ordered by most-recently-created descending. This
        is the default "Artifacts pane" listing.
        """
        query = """
                SELECT a.* FROM artifacts a
                INNER JOIN (
                    SELECT name, MAX(version) AS max_version
                    FROM artifacts WHERE thread_id = ?
                    GROUP BY name
                ) m ON a.name = m.name AND a.version = m.max_version
                WHERE a.thread_id = ?
                ORDER BY a.created_at DESC
                """
        params: tuple[object, ...] = (thread_id, thread_id)
        if limit is not None:
            if type(limit) is not int or limit < 1:
                raise ValueError("artifact_list_limit_invalid")
            query += " LIMIT ?"
            params = (*params, limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [_row(r) for r in rows]

    def list_recent_by_creator(
        self,
        created_by: str,
        *,
        limit: int | None = None,
    ) -> list[Artifact]:
        """AD-1227: the latest version of everything ``created_by`` has made,
        newest first, across every thread.

        Mirrors ``list_thread_latest`` but pivots on the creator rather than the
        thread, so an agent can be told what it has produced without asking
        semantic recall (BF-739: "what have I produced?" is not a similarity
        question and loses to an unbounded population of competing episodes).

        Grouping is by ``(thread_id, name)``, not ``name``: artifact names are
        only unique within a thread, so grouping by name alone would collapse
        two different threads' artifacts that happen to share one.

        A blank ``created_by`` returns ``[]`` and is NOT a wildcard — the same
        ownership rule ``recall_artifact_tool`` enforces; an anonymous caller
        must not enumerate the ship's output.
        """
        if not str(created_by or "").strip():
            return []
        query = """
                SELECT a.* FROM artifacts a
                INNER JOIN (
                    SELECT thread_id, name, MAX(version) AS max_version
                    FROM artifacts WHERE created_by = ?
                    GROUP BY thread_id, name
                ) m ON a.thread_id = m.thread_id AND a.name = m.name
                       AND a.version = m.max_version
                WHERE a.created_by = ?
                ORDER BY a.created_at DESC
                """
        params: tuple[object, ...] = (created_by, created_by)
        if limit is not None:
            if type(limit) is not int or limit < 1:
                raise ValueError("artifact_list_limit_invalid")
            query += " LIMIT ?"
            params = (*params, limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [_row(r) for r in rows]

    def find_by_hash_prefix(
        self, prefix: str, *, created_by: str,
    ) -> Artifact | None:
        """AD-1227: resolve a content-hash PREFIX to one of ``created_by``'s
        artifacts, newest first.

        The AD-1226 memory cue and the AD-1227 register both print a 12-char
        prefix, because a 64-char hash does not belong in a prompt line. Without
        this, ``recall_artifact`` could only turn a prefix back into bytes via
        the 50-episode ``recent_for_agent`` window, so an artifact whose episode
        had aged out was named in the prompt and then unreadable.

        Scoped to the creator in SQL: a prefix is short enough that an unscoped
        lookup could collide across agents, and the register is the agent's own.
        Requires 8 characters, matching the tool's own floor.
        """
        prefix = str(prefix or "").strip().lower()
        if len(prefix) < 8 or not str(created_by or "").strip():
            return None
        # Hex-only, so the LIKE pattern below cannot carry a wildcard. Rejecting
        # is correct where stripping would silently search for a different hash.
        if any(ch not in "0123456789abcdef" for ch in prefix):
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM artifacts WHERE created_by = ? AND content_hash LIKE ? "
                "ORDER BY created_at DESC LIMIT 1",
                (created_by, prefix + "%"),
            ).fetchone()
        return _row(row) if row else None

    def count_thread_latest(self, thread_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(DISTINCT name) AS n FROM artifacts WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
        return int(row["n"] if row else 0)

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
