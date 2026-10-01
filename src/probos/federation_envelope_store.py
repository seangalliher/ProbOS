"""AD-1197: the federation envelope store -- key holds, replay windows and the send epoch.

Owns ``federation_envelopes.db`` (store ``federation.envelope-replay``): the newest key
events held for each federation source node (at most 32) and the id of every key
verified for it, one replay window per source and channel (``direct`` or
``broadcast``), and this node's send epoch. Every write is one ``BEGIN IMMEDIATE``
transaction that refuses to move state backwards: a hold only advances, never changes
DID and never forgets a key id, a window only moves forward, and the epoch only
increments. Nothing is ever deleted.

Public material only -- key-event histories, key ids, counters and 64-bit window
masks; never a private key, an envelope signature or a message body. Nothing here
reads a clock.
"""

from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from probos.protocols import ConnectionFactory

ENVELOPE_DB_NAME = "federation_envelopes.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS envelope_senders (
    source_node TEXT PRIMARY KEY,
    did TEXT NOT NULL,
    key_seq INTEGER NOT NULL CHECK (key_seq >= 0),
    key_head TEXT NOT NULL,
    key_events_json TEXT NOT NULL,
    key_ids_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS envelope_windows (
    source_node TEXT NOT NULL,
    channel TEXT NOT NULL CHECK (channel IN ('direct', 'broadcast')),
    key_seq INTEGER NOT NULL CHECK (key_seq >= 0),
    epoch INTEGER NOT NULL CHECK (epoch >= 1),
    hwm INTEGER NOT NULL CHECK (hwm >= 1),
    mask TEXT NOT NULL CHECK (length(mask) = 16),
    PRIMARY KEY (source_node, channel)
);
CREATE TABLE IF NOT EXISTS envelope_send_epoch (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    epoch INTEGER NOT NULL CHECK (epoch >= 1)
);
"""
_UPSERT_SENDER = (
    "INSERT INTO envelope_senders (source_node, did, key_seq, key_head, key_events_json, key_ids_json) "
    "VALUES (?, ?, ?, ?, ?, ?) "
    "ON CONFLICT(source_node) DO UPDATE SET key_seq = excluded.key_seq, key_head = excluded.key_head, "
    "key_events_json = excluded.key_events_json, key_ids_json = excluded.key_ids_json "
    "WHERE excluded.did = envelope_senders.did AND excluded.key_seq > envelope_senders.key_seq"
)
_SELECT_KEY_IDS = "SELECT key_ids_json FROM envelope_senders WHERE source_node = ?"
_SELECT_WINDOW = "SELECT key_seq, epoch, hwm, mask FROM envelope_windows WHERE source_node = ? AND channel = ?"
_UPSERT_WINDOW = (
    "INSERT INTO envelope_windows (source_node, channel, key_seq, epoch, hwm, mask) VALUES (?, ?, ?, ?, ?, ?) "
    "ON CONFLICT(source_node, channel) DO UPDATE SET key_seq = excluded.key_seq, epoch = excluded.epoch, "
    "hwm = excluded.hwm, mask = excluded.mask"
)
_NEXT_EPOCH = (
    "INSERT INTO envelope_send_epoch (singleton, epoch) VALUES (1, 1) "
    "ON CONFLICT(singleton) DO UPDATE SET epoch = envelope_send_epoch.epoch + 1"
)
_SELECT_EPOCH = "SELECT epoch FROM envelope_send_epoch WHERE singleton = 1"
_SELECT_SENDERS = "SELECT source_node, did, key_seq, key_head, key_events_json FROM envelope_senders"
_SELECT_WINDOWS = "SELECT source_node, channel, key_seq, epoch, hwm, mask FROM envelope_windows"


class EnvelopeStateConflict(Exception):
    """A write would move a key hold or a replay window backwards; nothing was written."""


@dataclass(frozen=True)
class StoredSender:
    """The newest key events held for one source node (at most 32), as committed."""

    did: str
    key_seq: int
    key_head: str
    key_events_json: str


@dataclass(frozen=True)
class StoredWindow:
    """One replay window, ordered by ``(key_seq, epoch, hwm)``; bit ``i`` of ``mask`` marks ``hwm - i`` seen."""

    key_seq: int
    epoch: int
    hwm: int
    mask: int


def _moves_forward(stored: StoredWindow, new: StoredWindow) -> bool:
    """Whether ``new`` is ahead of ``stored``: a higher triple, or the same triple with no stored bit lost."""
    if (new.key_seq, new.epoch, new.hwm) != (stored.key_seq, stored.epoch, stored.hwm):
        return new.key_seq > stored.key_seq or (
            new.key_seq == stored.key_seq and (new.epoch, new.hwm) > (stored.epoch, stored.hwm)
        )
    return new.mask & stored.mask == stored.mask


def _key_ids_from(text: str, source: str) -> frozenset[str]:
    """The key ids recorded for ``source``, decoded; ``ValueError`` for anything but a list of strings."""
    ids = json.loads(text)
    if type(ids) is not list or not all(type(kid) is str for kid in ids):  # AD-1197 A-2 a recorded set reads back whole or not at all
        raise ValueError(f"the key ids recorded for {source[:64]!r} are not a list of strings")
    return frozenset(ids)


class EnvelopeStore:
    """Durable key holds, replay windows and the send epoch behind one node's envelope guard (AD-1197)."""

    def __init__(self, db_path: str | Path, *, connection_factory: ConnectionFactory | None = None) -> None:
        self._db_path = str(db_path)
        self._db: Any = None
        self._connection_factory = connection_factory
        if self._connection_factory is None:
            from probos.storage.sqlite_factory import default_factory

            self._connection_factory = default_factory

    async def start(self) -> None:
        """Open the database and apply the schema; a failure after connecting closes it before re-raising."""
        db = await self._connection_factory.connect(self._db_path)
        try:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA busy_timeout=5000")
            await db.execute("PRAGMA synchronous=NORMAL")
            await db.executescript(_SCHEMA)
            await db.commit()
        except BaseException:
            with contextlib.suppress(Exception):
                await db.close()
            raise
        self._db = db

    async def stop(self) -> None:
        """Close the database. Stopping a stopped store does nothing."""
        db, self._db = self._db, None
        if db is not None:
            await db.close()

    async def next_send_epoch(self) -> int:
        """Increment and commit this node's send epoch, then return it (1 on a new store)."""
        db = self._require()
        try:
            await db.execute("BEGIN IMMEDIATE")
            await db.execute(_NEXT_EPOCH)
            async with db.execute(_SELECT_EPOCH) as cursor:
                row = await cursor.fetchone()
            await db.commit()
        except BaseException:
            with contextlib.suppress(Exception):
                await db.execute("ROLLBACK")
            raise
        return int(row[0])

    async def load(self) -> tuple[dict[str, StoredSender], dict[tuple[str, str], StoredWindow]]:
        """Every held sender by source node, and every replay window by ``(source node, channel)``."""
        db = self._require()
        senders: dict[str, StoredSender] = {}
        async with db.execute(_SELECT_SENDERS) as cursor:
            for source, did, key_seq, key_head, key_events_json in await cursor.fetchall():
                senders[source] = StoredSender(did, int(key_seq), key_head, key_events_json)
        windows: dict[tuple[str, str], StoredWindow] = {}
        async with db.execute(_SELECT_WINDOWS) as cursor:
            for source, channel, key_seq, epoch, hwm, mask in await cursor.fetchall():
                windows[(source, channel)] = StoredWindow(int(key_seq), int(epoch), int(hwm), int(mask, 16))
        return senders, windows

    async def key_ids(self, source: str) -> frozenset[str]:
        """The id of every key recorded for ``source``; empty for a source never held (AD-1197 A-2)."""
        db = self._require()
        async with db.execute(_SELECT_KEY_IDS, (source,)) as cursor:
            row = await cursor.fetchone()
        return frozenset() if row is None else _key_ids_from(row[0], source)  # AD-1197 A-2 the recorded key ids

    async def record(
        self, source: str, channel: str, sender: StoredSender | None, window: StoredWindow,
        key_ids: frozenset[str] = frozenset(),
    ) -> None:
        """Commit a grown hold (when ``sender`` is given) and an advanced window in one transaction.

        ``key_ids`` goes with ``sender``: the id of every key verified for the source, never
        fewer than were recorded (AD-1197 A-2). Raises :class:`EnvelopeStateConflict`, writing
        nothing, when the hold, its key ids or the window would move backwards, and ``ValueError``
        for key ids without a hold; any other failure also rolls the whole transaction back.
        """
        if key_ids and sender is None:  # AD-1197 A-2 key ids are recorded only with their hold
            raise ValueError("key ids are recorded only with the hold they were verified for")
        db = self._require()
        try:
            await db.execute("BEGIN IMMEDIATE")
            if sender is not None:
                async with db.execute(_SELECT_KEY_IDS, (source,)) as cursor:
                    row = await cursor.fetchone()
                if row is not None and not key_ids >= _key_ids_from(row[0], source):  # AD-1197 A-2 a recorded key id is never forgotten
                    raise EnvelopeStateConflict(f"the key ids recorded for {source[:64]!r} cannot be forgotten")
                cursor = await db.execute(
                    _UPSERT_SENDER,
                    (source, sender.did, sender.key_seq, sender.key_head, sender.key_events_json, json.dumps(sorted(key_ids))),  # AD-1197 A-2 the key ids commit with the hold
                )
                if cursor.rowcount != 1:  # AD-1197 a refused update is a conflict
                    raise EnvelopeStateConflict(f"the key history held for {source[:64]!r} cannot move backwards")
            async with db.execute(_SELECT_WINDOW, (source, channel)) as cursor:
                row = await cursor.fetchone()
            if row is not None and not _moves_forward(StoredWindow(row[0], row[1], row[2], int(row[3], 16)), window):  # AD-1197 replay state never moves back
                raise EnvelopeStateConflict(f"the replay window for {source[:64]!r} cannot move backwards")
            await db.execute(
                _UPSERT_WINDOW, (source, channel, window.key_seq, window.epoch, window.hwm, f"{window.mask:016x}"),
            )
            await db.commit()
        except BaseException:
            with contextlib.suppress(Exception):
                await db.execute("ROLLBACK")
            raise

    def _require(self) -> Any:
        if self._db is None:
            raise RuntimeError("the envelope store is not running")
        return self._db
