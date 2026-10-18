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

import asyncio
import json
import logging
import math
import time
import zlib
from collections.abc import AsyncIterator, Callable, Iterable, Iterator, Mapping, Sequence
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
    "LOOKUP_DEFAULT_LIMIT",
    "LOOKUP_MAX_LIMIT",
    "LOOKUP_PURPOSE",
    "ArchiveLookupResult",
    "ArchiveRecord",
    "ArchivedEpisode",
    "EpisodeArchive",
    "EpisodeArchiveConflict",
    "EpisodeArchiveError",
    "EpisodeArchiveIntegrityError",
    "EpisodeArchiveLookups",
    "EpisodeArchiveNotFound",
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
#: AD-1340 S2a: lookup bounds, and the access purpose every lookup records.
LOOKUP_DEFAULT_LIMIT = 50
LOOKUP_MAX_LIMIT = 200
LOOKUP_PURPOSE = "lookup"

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

CREATE INDEX IF NOT EXISTS idx_episode_archive_agent_time
    ON episode_archive(agent_id, episode_timestamp);
"""

_LOOKUP_COLUMNS = (
    "a.episode_id, a.content_hash, a.agent_id, a.episode_timestamp, a.archived_at, a.reason, "
    "a.payload_format, a.payload"
)
#: AD-1340 S2a D4: one row per episode id, its latest archived version (the version get_records restores);
#: an exact tie on archived_at keeps the smallest content_hash.
_LATEST_VERSION = (
    "NOT EXISTS (SELECT 1 FROM episode_archive b WHERE b.episode_id = a.episode_id AND "
    "(b.archived_at > a.archived_at OR (b.archived_at = a.archived_at AND b.content_hash < a.content_hash)))"
)
_LOOKUP_BY_ID_SQL = f"SELECT {_LOOKUP_COLUMNS} FROM episode_archive a WHERE a.episode_id = ? AND {_LATEST_VERSION}"
_LOOKUP_BY_AGENT_SQL = (
    f"SELECT {_LOOKUP_COLUMNS} FROM episode_archive a "
    "WHERE a.agent_id = ? AND a.episode_timestamp >= ? AND a.episode_timestamp < ? "
    f"AND {_LATEST_VERSION} "
    "ORDER BY a.episode_timestamp DESC, a.episode_id DESC LIMIT ?"
)
#: AD-1340 S2a D5: an access row is written only while the exact row the lookup read (key and bytes) is stored.
_RECORD_LOOKUP_ACCESS_SQL = (
    "INSERT INTO archive_access (episode_id, accessed_at, accessor, purpose) SELECT ?, ?, ?, ? "
    "WHERE EXISTS (SELECT 1 FROM episode_archive WHERE episode_id = ? AND content_hash = ? AND payload = ?)"
)


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


class EpisodeArchiveNotFound(EpisodeArchiveError, LookupError):
    """AD-1340 S2b: a restore named an id the archive does not hold (still a ``LookupError``, as S1 raised)."""


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


def _require_accessor(accessor: str) -> None:
    if not isinstance(accessor, str) or not accessor.strip():
        raise ValueError("episode_archive_lookup_accessor_invalid")


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


@dataclass(frozen=True)
class ArchivedEpisode:
    """AD-1340 S2a: one archived record a lookup returned, with the key columns it was found by."""

    record: ArchiveRecord
    agent_id: str
    episode_timestamp: float
    archived_at: float
    reason: str


@dataclass(frozen=True)
class ArchiveLookupResult:
    """AD-1340 S2a: what a lookup returned. Every episode here has exactly one committed access row.

    ``undecodable``: matching rows whose payload could not be decoded (not returned, no access row).
    ``withdrawn``: decoded rows erased or replaced before their access row was written (not returned).
    ``truncated``: more rows matched than the limit allowed.
    """

    episodes: tuple[ArchivedEpisode, ...] = ()
    undecodable: int = 0
    withdrawn: int = 0
    truncated: bool = False


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


async def _guarded_read(require_open: Callable[[], Any], sql: str, params: Sequence[Any]) -> list[Any]:
    """AD-1340 S2b (F-140): one unlocked archive read, typed if a stop() closed the archive under it.

    ``stop()`` clears the handle under ``_write_lock`` before it closes the connection, so a read that fails
    while the handle is gone failed because of that stop: it becomes ``EpisodeArchiveUnavailable``, chained to
    the driver error. A failure on an open archive keeps its own type. Rows read across a stop are never
    answered: the re-check after the read is the last statement, so no await follows it. Every unlocked
    archive read goes through here: the four service reads and the S2a lookups.
    """
    db = require_open()
    try:
        cursor = await db.execute(sql, params)  # AD-1340 S2b: an archive read takes no lock (R3)
        rows = list(await cursor.fetchall())
    except Exception as exc:  # AD-1340 S2b: did a stop() close the connection under the read?
        try:
            require_open()  # AD-1340 S2b: a stop() during the read is unavailability (F-140)
        except EpisodeArchiveUnavailable as closed:
            raise closed from exc
        raise  # AD-1340 S2b: any other read failure keeps its own type
    require_open()  # AD-1340 S2b: rows read across a stop() are never answered; no await follows
    return rows


class EpisodeArchiveLookups:
    """AD-1340 S2a: the audited lookup surface of one ``EpisodeArchive`` (``archive.lookups``); S2c adds cue.

    Holds no connection and no lock of its own: it uses the archive's ``_require_open`` and the SAME
    ``_write_lock`` object, so every lookup's access transaction is serialised with the archive's writers.
    Constructed only by ``EpisodeArchive.__init__``.
    """

    def __init__(self, require_open: Callable[[], Any], write_lock: asyncio.Lock) -> None:
        self._require_open = require_open
        self._write_lock = write_lock

    async def lookup_by_id(self, episode_id: str, *, accessor: str) -> ArchiveLookupResult:
        """AD-1340 S2a: the latest archived version of one episode, recorded as one access row.

        A deliberate, audited read, never a recall surface. The read takes no lock; the access row is
        written under ``_write_lock`` and committed before anything is returned.
        """
        if not isinstance(episode_id, str) or not episode_id:
            raise ValueError("episode_archive_lookup_id_invalid")
        _require_accessor(accessor)
        return await self._lookup(_LOOKUP_BY_ID_SQL, (episode_id,), limit=1, accessor=accessor)

    async def lookup_by_agent(
        self,
        agent_id: str,
        *,
        since: float | None = None,
        until: float | None = None,
        limit: int = LOOKUP_DEFAULT_LIMIT,
        accessor: str,
    ) -> ArchiveLookupResult:
        """AD-1340 S2a: archived episodes whose PRIMARY agent is ``agent_id``, ``since <= timestamp < until``.

        Newest first, at most ``limit`` (1..LOOKUP_MAX_LIMIT). The primary agent is the first entry of
        ``agent_ids_json``, else ``"unknown"`` (the AD-541f rule ``archive()`` stores in ``agent_id``): an
        episode whose first participant is another agent is not found by this agent's id. ``None`` is open.
        """
        if not isinstance(agent_id, str) or not agent_id:
            raise ValueError("episode_archive_lookup_agent_invalid")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= LOOKUP_MAX_LIMIT:
            raise ValueError("episode_archive_lookup_limit_invalid")
        lower = -math.inf if since is None else float(since)
        upper = math.inf if until is None else float(until)
        finite = (since is None or math.isfinite(lower)) and (until is None or math.isfinite(upper))
        if not finite or lower >= upper:
            raise ValueError("episode_archive_lookup_range_invalid")
        _require_accessor(accessor)
        return await self._lookup(
            _LOOKUP_BY_AGENT_SQL, (agent_id, lower, upper, limit + 1), limit=limit, accessor=accessor,
        )

    async def _lookup(
        self, sql: str, params: tuple[Any, ...], *, limit: int, accessor: str,
    ) -> ArchiveLookupResult:
        rows = await _guarded_read(self._require_open, sql, params)  # a read: no lock (R3); the locked INSERT below decides
        truncated = len(rows) > limit
        decoded: list[tuple[ArchivedEpisode, bytes]] = []
        undecodable = 0
        for row in rows[:limit]:
            episode_id, content_hash, agent_id, episode_timestamp, archived_at, reason, payload_format, payload = row
            try:
                record = decode_payload(episode_id, content_hash, payload_format, payload)
            except EpisodeArchiveIntegrityError:
                undecodable += 1
                logger.warning(
                    "AD-1340 S2a: archived row %s could not be decoded; the lookup returns the others",
                    episode_id, exc_info=True,
                )
                continue  # AD-1340 S2a: one bad row never hides the others in a lookup
            item = ArchivedEpisode(record, str(agent_id), float(episode_timestamp), float(archived_at), str(reason))
            decoded.append((item, bytes(payload)))
        recorded = await self._record_lookup_access(decoded, accessor=accessor) if decoded else frozenset()
        episodes = tuple(item for item, _ in decoded if (item.record.episode_id, item.record.content_hash) in recorded)
        return ArchiveLookupResult(
            episodes=episodes,
            undecodable=undecodable,
            withdrawn=len(decoded) - len(episodes),
            truncated=truncated,
        )

    async def _record_lookup_access(
        self, decoded: Sequence[tuple[ArchivedEpisode, bytes]], *, accessor: str,
    ) -> frozenset[tuple[str, str]]:
        """One access row per decoded record whose exact row (key and bytes) is still stored, in ONE transaction.

        The INSERT evaluates its own condition inside the lock, so a row erased or replaced since the unlocked
        read gets no access row and is not returned. Any failure rolls the whole batch back and raises: a
        lookup never returns a record whose access row was not committed. Returns the committed keys.
        """
        async with self._write_lock:  # AD-1340 S2a: a lookup's access rows commit alone, after their rows are re-checked
            db = self._require_open()
            now = time.time()
            recorded: set[tuple[str, str]] = set()
            try:
                for item, payload in decoded:
                    eid, chash = item.record.episode_id, item.record.content_hash
                    cursor = await db.execute(_RECORD_LOOKUP_ACCESS_SQL, (eid, now, accessor, LOOKUP_PURPOSE, eid, chash, payload))
                    if cursor.rowcount == 1:
                        recorded.add((eid, chash))
                await db.commit()  # AD-1340 S2a: no lookup returns a record before its access row is committed
            except Exception as exc:
                await _rollback_quietly(db)  # AD-1340 S2a: no access row of a failed lookup survives
                raise EpisodeArchiveError("episode_archive_access_not_recorded") from exc
            return frozenset(recorded)


class EpisodeArchive:
    """Cold store for evicted episodes. Owned and started by ``EpisodicMemory``.

    Not a recall surface: nothing on the default recall paths calls it.
    S2a's recorded lookups live on ``lookups`` (``EpisodeArchiveLookups``); S2c adds cue.
    AD-1340 R3: mutations are serialised by `_write_lock`; reads are not.
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
        # AD-1340 R3: one connection, one transaction at a time. Every mutation (archive with its read-back,
        # record_access, erase) and stop() hold this, so no writer's COMMIT or ROLLBACK can take another's
        # statements. Reads never take it. Lock order: EpisodicMemory's store write lock, then this; this
        # class never reaches the store lock.
        self._write_lock = asyncio.Lock()
        self.lookups = EpisodeArchiveLookups(self._require_open, self._write_lock)  # AD-1340 S2a: the audited read surface

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
        async with self._write_lock:  # AD-1340 R3: never close inside another coroutine's transaction
            db, self._db = self._db, None
        if db is not None:
            await _close_quietly(db)

    def _require_open(self) -> Any:
        if self._db is None:
            raise EpisodeArchiveUnavailable("episode_archive_not_open")
        return self._db

    async def archive(self, records: Iterable[ArchiveRecord], *, reason: str) -> frozenset[str]:
        """Insert each record once per ``(episode_id, content_hash)`` and commit.

        A re-archive under an existing key replaces the stored payload only when
        it differs (AD-1340 R1: a record whose metadata changed after a restore
        must not be dropped on its next eviction); an identical one changes nothing.
        Returns the ids whose row is present with exactly this payload after the
        commit (read back): the
        only ids the caller may delete from the live store. A record that cannot
        be encoded is skipped with a warning and stays live. A failed write is
        rolled back and raises.
        """
        self._require_open()  # fail fast, before encoding
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
        async with self._write_lock:  # AD-1340 R3: archive() writes, commits and reads back alone
            db = self._require_open()
            try:
                await db.executemany(
                    "INSERT INTO episode_archive (episode_id, content_hash, agent_id, episode_timestamp, "
                    "reason, archived_at, payload_format, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(episode_id, content_hash) DO UPDATE SET agent_id = excluded.agent_id, "
                    "episode_timestamp = excluded.episode_timestamp, reason = excluded.reason, "
                    "archived_at = excluded.archived_at, payload_format = excluded.payload_format, "
                    "payload = excluded.payload WHERE episode_archive.payload IS NOT excluded.payload",
                    rows,
                )
                await db.commit()  # the archive commit: nothing leaves the live store before this returns
            except Exception:
                await _rollback_quietly(db)
                raise
            return await self._present({(row[0], row[1]): row[7] for row in rows})

    async def _present(self, wanted: dict[tuple[str, str], bytes]) -> frozenset[str]:
        db = self._require_open()
        found: set[str] = set()
        ids = list(dict.fromkeys(key[0] for key in wanted))
        for chunk in _chunks(ids, _SQL_CHUNK):
            marks = ",".join("?" * len(chunk))
            cursor = await db.execute(
                f"SELECT episode_id, content_hash, payload FROM episode_archive WHERE episode_id IN ({marks})",
                chunk,
            )
            for episode_id, content_hash, payload in await cursor.fetchall():
                if (episode_id, content_hash) in wanted and bytes(payload) == wanted[(episode_id, content_hash)]:
                    found.add(episode_id)
        return frozenset(found)

    async def get_records(self, episode_ids: Sequence[str]) -> list[ArchiveRecord]:
        """Service read (restore): the latest archived record per id, in input order.

        AD-1340 S2b: "latest" is the S2a lookup's own rule (``_LATEST_VERSION``: the greatest ``archived_at``; an
        exact tie keeps the smallest ``content_hash``), applied in SQL, so a restore puts back exactly the version
        a lookup showed. Only that row is decoded; an undecodable latest row raises ``EpisodeArchiveIntegrityError``.
        A stop() during the read raises ``EpisodeArchiveUnavailable``.
        """
        self._require_open()  # AD-1340 S2b: closed is unavailable, even for an empty request
        wanted = list(dict.fromkeys(eid for eid in episode_ids if eid))
        latest: dict[str, ArchiveRecord] = {}
        for chunk in _chunks(wanted, _SQL_CHUNK):
            marks = ",".join("?" * len(chunk))
            rows = await _guarded_read(
                self._require_open,  # AD-1340 S2b: get_records reads through the stop guard
                "SELECT a.episode_id, a.content_hash, a.payload_format, a.payload FROM episode_archive a "
                f"WHERE a.episode_id IN ({marks}) AND {_LATEST_VERSION}",
                chunk,
            )
            for episode_id, content_hash, payload_format, payload in rows:
                latest[episode_id] = decode_payload(episode_id, content_hash, payload_format, payload)
        return [latest[eid] for eid in wanted if eid in latest]

    async def archived_keys(self, episode_ids: Sequence[str]) -> list[tuple[str, str, Any, float]]:
        """``(episode_id, content_hash, agent_id, episode_timestamp)`` per row, no decode.

        Erasure audits from these columns, so a corrupt payload never blocks an erase.
        AD-1340 S2b: a stop() during the read raises ``EpisodeArchiveUnavailable``.
        """
        self._require_open()  # AD-1340 S2b: closed is unavailable, even for an empty request
        wanted = list(dict.fromkeys(eid for eid in episode_ids if eid))
        keys: list[tuple[str, str, Any, float]] = []
        for chunk in _chunks(wanted, _SQL_CHUNK):
            marks = ",".join("?" * len(chunk))
            rows = await _guarded_read(
                self._require_open,  # AD-1340 S2b: archived_keys reads through the stop guard
                "SELECT episode_id, content_hash, agent_id, episode_timestamp "
                f"FROM episode_archive WHERE episode_id IN ({marks})",
                chunk,
            )
            keys.extend(tuple(row) for row in rows)
        return keys

    async def get_versions(self, episode_ids: Sequence[str]) -> list[ArchiveRecord]:
        """Service read (erasure's attachment lookup): EVERY archived row for the ids.

        Ordered by ``episode_id, archived_at, content_hash``. A row that cannot be
        decoded raises ``EpisodeArchiveIntegrityError``. AD-1340 S2b: a stop() during
        the read raises ``EpisodeArchiveUnavailable``.
        """
        self._require_open()  # AD-1340 S2b: closed is unavailable, even for an empty request
        wanted = list(dict.fromkeys(eid for eid in episode_ids if eid))
        versions: list[ArchiveRecord] = []
        for chunk in _chunks(wanted, _SQL_CHUNK):
            marks = ",".join("?" * len(chunk))
            rows = await _guarded_read(
                self._require_open,  # AD-1340 S2b: get_versions reads through the stop guard
                "SELECT episode_id, content_hash, payload_format, payload "
                f"FROM episode_archive WHERE episode_id IN ({marks}) "
                "ORDER BY episode_id, archived_at, content_hash",
                chunk,
            )
            for episode_id, content_hash, payload_format, payload in rows:
                versions.append(decode_payload(episode_id, content_hash, payload_format, payload))
        return versions

    async def iter_records(self, *, page_size: int = 500) -> AsyncIterator[ArchiveRecord]:
        """Every archived row, paged by key (erasure cascades).

        A row that cannot be decoded is logged and skipped so it never hides the
        rows after it; once the scan is complete, ``EpisodeArchiveIntegrityError``
        reports how many were skipped (AD-1340 R1).
        """
        if page_size < 1:
            raise ValueError("episode_archive_page_size_invalid")
        last = ("", "")
        undecodable = 0
        while True:
            rows = await _guarded_read(
                self._require_open,  # AD-1340 S2b: iter_records reads through the stop guard
                "SELECT episode_id, content_hash, payload_format, payload FROM episode_archive "
                "WHERE (episode_id, content_hash) > (?, ?) ORDER BY episode_id, content_hash LIMIT ?",
                (last[0], last[1], page_size),
            )
            if not rows:
                break
            for episode_id, content_hash, payload_format, payload in rows:
                try:
                    record = decode_payload(episode_id, content_hash, payload_format, payload)
                except EpisodeArchiveIntegrityError:
                    undecodable += 1
                    logger.warning(
                        "AD-1340: archived row %s could not be decoded; the scan continues and will report it",
                        episode_id, exc_info=True,
                    )
                    continue  # one bad row never hides the rows after it
                yield record
            last = (rows[-1][0], rows[-1][1])
        if undecodable:
            raise EpisodeArchiveIntegrityError(f"episode_archive_rows_undecodable:{undecodable}")

    async def record_access(self, episode_id: str, *, accessor: str, purpose: str) -> None:
        async with self._write_lock:  # AD-1340 R3: the access row commits alone
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
        async with self._write_lock:  # AD-1340 R3: the erase transaction commits alone
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
