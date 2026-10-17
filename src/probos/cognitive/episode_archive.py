"""AD-1340 S1: the episode archive -- cold, text-only storage for evicted episodes.

Dream pruning (Step 12) and capacity eviction move an episode here, in full,
before removing it from the live retrieval indexes (ChromaDB, FTS5, the
participant index, the activation log). Ordinary recall never reads this
store. Erasure (AD-754) is the only path that removes an archived episode.

The payload is the raw ChromaDB record ``{id, document, metadata}`` exactly as
``collection.get(include=["documents", "metadatas"])`` returned it, serialised
as canonical JSON and zlib-compressed, so a restore is byte-equal. Every
connection sets ``PRAGMA secure_delete=ON`` and verifies it, so an erased
row's bytes are overwritten rather than left in free pages.
"""

from __future__ import annotations

import json
import logging
import time
import zlib
from collections.abc import AsyncIterator, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from probos.cognitive.eviction_audit import (
    DISPOSITION_ARCHIVED,
    DISPOSITION_DELETED,
    DISPOSITION_ERASED,
)
from probos.types import EvictionDisposition

__all__ = [
    "ARCHIVE_FILENAME",
    "ARCHIVE_REASONS",
    "EVICTION_MODES",
    "ArchiveRecord",
    "EpisodeArchive",
    "EpisodeArchiveConflict",
    "EpisodeArchiveError",
    "EpisodeArchiveIntegrityError",
    "EpisodeArchiveUnavailable",
    "EpisodeErasureIncomplete",
    "EvictionDisposition",
    "decode_payload",
    "encode_payload",
    "primary_agent_id",
    "resolve_disposition",
]

logger = logging.getLogger(__name__)

ARCHIVE_FILENAME = "episode_archive.db"
ARCHIVE_SCHEMA_VERSION = 1
PAYLOAD_FORMAT_ZLIB_JSON = 1
#: The closed set of reasons that archive without a warning.
ARCHIVE_REASONS: frozenset[str] = frozenset(
    {"activation_decay", "activation_decay_aggressive", "capacity", "activation_pruning"}
)
#: ``memory.eviction_disposition`` values.
EVICTION_MODES: frozenset[str] = frozenset({"archive", "delete"})
_SQL_CHUNK = 500

AuditDisposition = Literal["archived", "erased", "deleted"]

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS episode_archive (
    episode_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    episode_timestamp REAL NOT NULL,
    reason TEXT NOT NULL,
    archived_at REAL NOT NULL,
    payload_format INTEGER NOT NULL,
    payload BLOB NOT NULL,
    PRIMARY KEY (episode_id, content_hash)
);

CREATE TABLE IF NOT EXISTS archive_access (
    id INTEGER PRIMARY KEY,
    episode_id TEXT NOT NULL,
    accessed_at REAL NOT NULL,
    accessor TEXT NOT NULL,
    purpose TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_archive_access_episode
    ON archive_access(episode_id);
"""


class EpisodeArchiveError(Exception):
    """Base class for episode-archive failures."""


class EpisodeArchiveUnavailable(EpisodeArchiveError):
    """The archive is not open (never started, failed to open, or stopped)."""


class EpisodeArchiveIntegrityError(EpisodeArchiveError):
    """A stored row does not decode to the record its key columns name."""


class EpisodeArchiveConflict(EpisodeArchiveError):
    """A restore named an id that is already live."""


class EpisodeErasureIncomplete(EpisodeArchiveError):
    """Erasure could not clear every copy of an episode."""


def resolve_disposition(
    reason: str,
    explicit: EvictionDisposition | None,
    mode: str,
) -> AuditDisposition:
    """The one owner of the eviction policy (AD-1340 Decision 4, as amended).

    ERASE comes only from an explicit ``EvictionDisposition.ERASE``; no reason
    string produces it, because the AD-754 erasure route passes a caller-chosen
    free-text reason. Any other eviction archives (``mode="archive"``) or
    deletes (``mode="delete"``). A reason outside :data:`ARCHIVE_REASONS` is
    logged and still archives: losing data is the worse failure.
    """
    if mode not in EVICTION_MODES:
        raise ValueError("eviction_disposition_mode_invalid")
    if explicit is EvictionDisposition.ERASE:
        return DISPOSITION_ERASED
    if explicit is not None and explicit is not EvictionDisposition.ARCHIVE:
        raise TypeError("eviction_disposition_invalid")
    if reason not in ARCHIVE_REASONS:
        logger.warning("AD-1340: unknown eviction reason %r; archiving, never erasing", reason)
    if mode == "delete":
        return DISPOSITION_DELETED
    return DISPOSITION_ARCHIVED


def primary_agent_id(metadata: Mapping[str, Any]) -> Any:
    """First entry of ``agent_ids_json``, else ``"unknown"`` -- the AD-541f audit rule."""
    try:
        agent_ids = json.loads(metadata.get("agent_ids_json", "[]"))
        return agent_ids[0] if agent_ids else "unknown"
    except (json.JSONDecodeError, TypeError, KeyError, IndexError):
        return "unknown"


def _episode_timestamp(metadata: Mapping[str, Any]) -> float:
    try:
        return float(metadata.get("timestamp", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _chunks(items: Sequence[str], size: int) -> Iterator[list[str]]:
    for start in range(0, len(items), size):
        yield list(items[start:start + size])


@dataclass(frozen=True)
class ArchiveRecord:
    """One raw ChromaDB record, exactly as the live store held it."""

    episode_id: str
    document: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        value = self.metadata.get("content_hash", "")
        return value if isinstance(value, str) else ""

    @property
    def archive_ref(self) -> str:
        return f"episode_archive:{self.episode_id}:{self.content_hash}"


def encode_payload(record: ArchiveRecord) -> bytes:
    """Canonical JSON of ``{id, document, metadata}``, then zlib."""
    payload_metadata = dict(record.metadata)
    canonical = json.dumps(
        {"document": record.document, "id": record.episode_id, "metadata": payload_metadata},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return zlib.compress(canonical.encode("utf-8"), 6)


def decode_payload(
    episode_id: str,
    content_hash: str,
    payload_format: int,
    payload: bytes,
) -> ArchiveRecord:
    """Decode one stored payload and prove it is the record its key names."""
    if payload_format != PAYLOAD_FORMAT_ZLIB_JSON:
        raise EpisodeArchiveIntegrityError("episode_archive_payload_format_unknown")
    try:
        data = json.loads(zlib.decompress(payload).decode("utf-8"))
    except (zlib.error, UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        raise EpisodeArchiveIntegrityError("episode_archive_payload_undecodable") from exc
    if (
        not isinstance(data, dict)
        or set(data) != {"document", "id", "metadata"}
        or not isinstance(data["document"], str)
        or not isinstance(data["metadata"], dict)
    ):
        raise EpisodeArchiveIntegrityError("episode_archive_payload_shape")
    record = ArchiveRecord(
        episode_id=data["id"], document=data["document"], metadata=data["metadata"],
    )
    if record.episode_id != episode_id or record.content_hash != content_hash:
        raise EpisodeArchiveIntegrityError("episode_archive_payload_key_mismatch")
    return record


async def _rollback_quietly(db: Any) -> None:
    try:
        await db.execute("ROLLBACK")
    except Exception:
        logger.debug("AD-1340: archive rollback failed (no open transaction?)", exc_info=True)


async def _close_quietly(db: Any) -> None:
    try:
        await db.close()
    except Exception:
        logger.debug("AD-1340: archive close failed", exc_info=True)


class EpisodeArchive:
    """Cold store for evicted episodes. Owned and started by ``EpisodicMemory``.

    Not a recall surface: nothing on the default recall paths calls it.
    S2 adds the recorded lookups (by agent and time, by cue).
    """

    def __init__(self, db_path: str, connection_factory: Any = None) -> None:
        if not isinstance(db_path, str) or not db_path.strip():
            raise ValueError("episode_archive_path_invalid")
        if connection_factory is None:
            from probos.storage.sqlite_factory import default_factory
            connection_factory = default_factory
        self._db_path = db_path
        self._factory = connection_factory
        self._db: Any = None

    @property
    def is_open(self) -> bool:
        return self._db is not None

    async def start(self) -> None:
        """Open, enable and verify ``secure_delete``, then create the schema."""
        if self._db is not None:
            return
        db = await self._factory.connect(self._db_path)
        try:
            await db.execute("PRAGMA secure_delete=ON")
            cursor = await db.execute("PRAGMA secure_delete")
            row = await cursor.fetchone()
            if not row or int(row[0]) != 1:
                raise EpisodeArchiveUnavailable("episode_archive_secure_delete_unavailable")
            cursor = await db.execute("PRAGMA user_version")
            row = await cursor.fetchone()
            version = int(row[0]) if row else 0
            if version not in (0, ARCHIVE_SCHEMA_VERSION):
                raise EpisodeArchiveUnavailable("episode_archive_schema_unknown")
            await db.executescript(_SCHEMA)
            await db.execute(f"PRAGMA user_version = {ARCHIVE_SCHEMA_VERSION}")
            await db.commit()
        except BaseException:  # close on every exit, cancellation included, then re-raise
            await _close_quietly(db)
            raise
        self._db = db

    async def stop(self) -> None:
        db, self._db = self._db, None
        if db is not None:
            await _close_quietly(db)

    def _require_open(self) -> Any:
        if self._db is None:
            raise EpisodeArchiveUnavailable("episode_archive_not_open")
        return self._db

    async def archive(self, records: Iterable[ArchiveRecord], *, reason: str) -> frozenset[str]:
        """Insert each record once per ``(episode_id, content_hash)`` and commit.

        Returns the ids whose row is present after the commit (read back): the
        only ids the caller may delete from the live store. A record that cannot
        be encoded is skipped with a warning and stays live. A failed write is
        rolled back and raises.
        """
        db = self._require_open()
        now = time.time()
        rows: list[tuple[Any, ...]] = []
        for record in records:
            try:
                payload = encode_payload(record)
            except (TypeError, ValueError):
                logger.warning(
                    "AD-1340: episode %s could not be encoded for the archive; it stays live",
                    record.episode_id, exc_info=True,
                )
                continue
            rows.append((
                record.episode_id, record.content_hash, primary_agent_id(record.metadata),
                _episode_timestamp(record.metadata), reason, now, PAYLOAD_FORMAT_ZLIB_JSON, payload,
            ))
        if not rows:
            return frozenset()
        try:
            await db.executemany(
                "INSERT INTO episode_archive (episode_id, content_hash, agent_id, episode_timestamp, "
                "reason, archived_at, payload_format, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(episode_id, content_hash) DO NOTHING",
                rows,
            )
            await db.commit()  # the archive commit: nothing leaves the live store before this returns
        except Exception:
            await _rollback_quietly(db)
            raise
        return await self._present([(row[0], row[1]) for row in rows])

    async def _present(self, pairs: list[tuple[str, str]]) -> frozenset[str]:
        db = self._require_open()
        wanted = set(pairs)
        found: set[str] = set()
        ids = list(dict.fromkeys(pair[0] for pair in pairs))
        for chunk in _chunks(ids, _SQL_CHUNK):
            marks = ",".join("?" * len(chunk))
            cursor = await db.execute(
                f"SELECT episode_id, content_hash FROM episode_archive WHERE episode_id IN ({marks})",
                chunk,
            )
            for episode_id, content_hash in await cursor.fetchall():
                if (episode_id, content_hash) in wanted:
                    found.add(episode_id)
        return frozenset(found)

    async def get_records(self, episode_ids: Sequence[str]) -> list[ArchiveRecord]:
        """Service read (restore, erasure): the latest archived record per id, in input order."""
        db = self._require_open()
        wanted = list(dict.fromkeys(eid for eid in episode_ids if eid))
        best: dict[str, tuple[float, ArchiveRecord]] = {}
        for chunk in _chunks(wanted, _SQL_CHUNK):
            marks = ",".join("?" * len(chunk))
            cursor = await db.execute(
                "SELECT episode_id, content_hash, archived_at, payload_format, payload "
                f"FROM episode_archive WHERE episode_id IN ({marks})",
                chunk,
            )
            for episode_id, content_hash, archived_at, payload_format, payload in await cursor.fetchall():
                record = decode_payload(episode_id, content_hash, payload_format, payload)
                current = best.get(episode_id)
                if current is None or archived_at > current[0]:
                    best[episode_id] = (archived_at, record)
        return [best[eid][1] for eid in wanted if eid in best]

    async def archived_keys(self, episode_ids: Sequence[str]) -> list[tuple[str, str, Any, float]]:
        """``(episode_id, content_hash, agent_id, episode_timestamp)`` per row, no decode.

        Erasure audits from these columns, so a corrupt payload never blocks an erase.
        """
        db = self._require_open()
        wanted = list(dict.fromkeys(eid for eid in episode_ids if eid))
        keys: list[tuple[str, str, Any, float]] = []
        for chunk in _chunks(wanted, _SQL_CHUNK):
            marks = ",".join("?" * len(chunk))
            cursor = await db.execute(
                "SELECT episode_id, content_hash, agent_id, episode_timestamp "
                f"FROM episode_archive WHERE episode_id IN ({marks})",
                chunk,
            )
            keys.extend(tuple(row) for row in await cursor.fetchall())
        return keys

    async def iter_records(self, *, page_size: int = 500) -> AsyncIterator[ArchiveRecord]:
        """Every archived row, paged by key (erasure cascades)."""
        if page_size < 1:
            raise ValueError("episode_archive_page_size_invalid")
        last = ("", "")
        while True:
            db = self._require_open()
            cursor = await db.execute(
                "SELECT episode_id, content_hash, payload_format, payload FROM episode_archive "
                "WHERE (episode_id, content_hash) > (?, ?) ORDER BY episode_id, content_hash LIMIT ?",
                (last[0], last[1], page_size),
            )
            rows = await cursor.fetchall()
            if not rows:
                return
            for episode_id, content_hash, payload_format, payload in rows:
                yield decode_payload(episode_id, content_hash, payload_format, payload)
            last = (rows[-1][0], rows[-1][1])

    async def record_access(self, episode_id: str, *, accessor: str, purpose: str) -> None:
        db = self._require_open()
        try:
            await db.execute(
                "INSERT INTO archive_access (episode_id, accessed_at, accessor, purpose) "
                "VALUES (?, ?, ?, ?)",
                (episode_id, time.time(), accessor, purpose),
            )
            await db.commit()
        except Exception:
            await _rollback_quietly(db)
            raise

    async def erase(self, episode_ids: Sequence[str]) -> frozenset[str]:
        """Delete every archive row and access row for these ids; return the ids that had rows."""
        db = self._require_open()
        wanted = list(dict.fromkeys(eid for eid in episode_ids if eid))
        present = {key[0] for key in await self.archived_keys(wanted)}
        try:
            for chunk in _chunks(wanted, _SQL_CHUNK):
                marks = ",".join("?" * len(chunk))
                await db.execute(f"DELETE FROM episode_archive WHERE episode_id IN ({marks})", chunk)
                await db.execute(f"DELETE FROM archive_access WHERE episode_id IN ({marks})", chunk)
            await db.commit()
        except Exception:
            await _rollback_quietly(db)
            raise
        return frozenset(present)
