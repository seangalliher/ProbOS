"""AD-802: SQLite-backed pairing registry.

Persistence layer the AD-701 in-memory `VisitingOfficerRegistry`
explicitly defers (see ``visiting_officers.py:19`` — "Persistence is a
follow-up AD-701b once the cap surface stabilizes"). Storing pairings
durably is exactly that follow-up, shaped slightly differently to also
hold the *pending* (pre-approval) state.

Two tables:

- ``pending_pairings`` — minted by ``mint_pending``; consumed (deleted)
  by ``consume_pending`` on approval; swept periodically by
  ``sweep_expired_pending``.
- ``paired_users`` — written by ``record_pairing`` on approval; queried
  by ``lookup_by_raw_id`` / ``lookup_by_did`` on every inbound channel
  message; removed by ``revoke``.

All methods are synchronous (SQLite). Wrap blocking calls in
``loop.run_in_executor`` from async callers per the
``shell_command.py:_run_sync`` pattern.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Callable

from probos.security.pairing.types import PairedUser, PendingPairing


_SCHEMA = """
CREATE TABLE IF NOT EXISTS pending_pairings (
    channel TEXT NOT NULL,
    raw_id TEXT NOT NULL,
    code TEXT NOT NULL,
    capabilities TEXT NOT NULL,
    ttl_seconds REAL NOT NULL,
    minted_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    PRIMARY KEY (channel, code)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_pending_channel_raw
    ON pending_pairings (channel, raw_id);

CREATE TABLE IF NOT EXISTS paired_users (
    channel TEXT NOT NULL,
    raw_id TEXT NOT NULL,
    did TEXT NOT NULL PRIMARY KEY,
    capabilities TEXT NOT NULL,
    ttl_seconds REAL NOT NULL,
    paired_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_paired_channel_raw
    ON paired_users (channel, raw_id);
"""


def _serialize_caps(caps: tuple[str, ...] | list[str]) -> str:
    return json.dumps(sorted(caps))


def _deserialize_caps(s: str) -> tuple[str, ...]:
    try:
        return tuple(json.loads(s))
    except (json.JSONDecodeError, TypeError):
        return ()


class PairingRegistry:
    """SQLite-backed store for pending and approved pairings."""

    def __init__(
        self,
        db_path: Path,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._db_path = Path(db_path)
        self._clock = clock
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    # ---------- schema bootstrap ----------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            conn.commit()

    # ---------- pending_pairings ----------

    def mint_pending(
        self,
        channel: str,
        raw_id: str,
        code: str,
        capabilities: list[str] | tuple[str, ...],
        *,
        ttl_seconds: float,
    ) -> PendingPairing:
        """Create a pending pairing row. Caller is responsible for code
        generation (the service owns the alphabet + length). If a pending
        row already exists for ``(channel, raw_id)``, this raises
        ``sqlite3.IntegrityError`` — service layer catches and returns
        the existing row for idempotency.
        """
        now = self._clock()
        expires = now + ttl_seconds
        caps_str = _serialize_caps(capabilities)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO pending_pairings
                    (channel, raw_id, code, capabilities, ttl_seconds, minted_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (channel, raw_id, code, caps_str, ttl_seconds, now, expires),
            )
            conn.commit()
        return PendingPairing(
            channel=channel,
            raw_id=raw_id,
            code=code,
            capabilities=tuple(capabilities),
            ttl_seconds=ttl_seconds,
            minted_at=now,
            expires_at=expires,
        )

    def get_pending_by_raw_id(self, channel: str, raw_id: str) -> PendingPairing | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT code, capabilities, ttl_seconds, minted_at, expires_at "
                "FROM pending_pairings WHERE channel = ? AND raw_id = ?",
                (channel, raw_id),
            ).fetchone()
        if row is None:
            return None
        code, caps_str, ttl, minted, expires = row
        return PendingPairing(
            channel=channel,
            raw_id=raw_id,
            code=code,
            capabilities=_deserialize_caps(caps_str),
            ttl_seconds=ttl,
            minted_at=minted,
            expires_at=expires,
        )

    def get_pending(self, channel: str, code: str) -> PendingPairing | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT raw_id, capabilities, ttl_seconds, minted_at, expires_at "
                "FROM pending_pairings WHERE channel = ? AND code = ?",
                (channel, code),
            ).fetchone()
        if row is None:
            return None
        raw_id, caps_str, ttl, minted, expires = row
        return PendingPairing(
            channel=channel,
            raw_id=raw_id,
            code=code,
            capabilities=_deserialize_caps(caps_str),
            ttl_seconds=ttl,
            minted_at=minted,
            expires_at=expires,
        )

    def list_pending(self, channel: str | None = None) -> list[PendingPairing]:
        with self._connect() as conn:
            if channel is None:
                rows = conn.execute(
                    "SELECT channel, raw_id, code, capabilities, ttl_seconds, "
                    "minted_at, expires_at FROM pending_pairings ORDER BY minted_at"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT channel, raw_id, code, capabilities, ttl_seconds, "
                    "minted_at, expires_at FROM pending_pairings "
                    "WHERE channel = ? ORDER BY minted_at",
                    (channel,),
                ).fetchall()
        return [
            PendingPairing(
                channel=r[0],
                raw_id=r[1],
                code=r[2],
                capabilities=_deserialize_caps(r[3]),
                ttl_seconds=r[4],
                minted_at=r[5],
                expires_at=r[6],
            )
            for r in rows
        ]

    def consume_pending(self, channel: str, code: str) -> PendingPairing | None:
        """Atomic SELECT + DELETE. Returns the row if it existed, None
        otherwise. Expired rows are still returned — the service decides
        whether to honor or reject.
        """
        pending = self.get_pending(channel, code)
        if pending is None:
            return None
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM pending_pairings WHERE channel = ? AND code = ?",
                (channel, code),
            )
            conn.commit()
        return pending

    def sweep_expired_pending(self) -> int:
        """Remove pending rows past `expires_at`. Returns the deleted count."""
        now = self._clock()
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM pending_pairings WHERE expires_at < ?",
                (now,),
            )
            conn.commit()
            return cur.rowcount

    # ---------- paired_users ----------

    def record_pairing(
        self,
        channel: str,
        raw_id: str,
        did: str,
        capabilities: list[str] | tuple[str, ...],
        ttl_seconds: float,
    ) -> PairedUser:
        now = self._clock()
        expires = now + ttl_seconds
        caps_str = _serialize_caps(capabilities)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO paired_users
                    (channel, raw_id, did, capabilities, ttl_seconds, paired_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (channel, raw_id, did, caps_str, ttl_seconds, now, expires),
            )
            conn.commit()
        return PairedUser(
            channel=channel,
            raw_id=raw_id,
            did=did,
            capabilities=tuple(capabilities),
            ttl_seconds=ttl_seconds,
            paired_at=now,
            expires_at=expires,
        )

    def lookup_by_raw_id(self, channel: str, raw_id: str) -> PairedUser | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT did, capabilities, ttl_seconds, paired_at, expires_at "
                "FROM paired_users WHERE channel = ? AND raw_id = ?",
                (channel, raw_id),
            ).fetchone()
        if row is None:
            return None
        return PairedUser(
            channel=channel,
            raw_id=raw_id,
            did=row[0],
            capabilities=_deserialize_caps(row[1]),
            ttl_seconds=row[2],
            paired_at=row[3],
            expires_at=row[4],
        )

    def lookup_by_did(self, did: str) -> PairedUser | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT channel, raw_id, capabilities, ttl_seconds, paired_at, expires_at "
                "FROM paired_users WHERE did = ?",
                (did,),
            ).fetchone()
        if row is None:
            return None
        return PairedUser(
            channel=row[0],
            raw_id=row[1],
            did=did,
            capabilities=_deserialize_caps(row[2]),
            ttl_seconds=row[3],
            paired_at=row[4],
            expires_at=row[5],
        )

    def list_paired(self, channel: str | None = None) -> list[PairedUser]:
        with self._connect() as conn:
            if channel is None:
                rows = conn.execute(
                    "SELECT channel, raw_id, did, capabilities, ttl_seconds, "
                    "paired_at, expires_at FROM paired_users ORDER BY paired_at"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT channel, raw_id, did, capabilities, ttl_seconds, "
                    "paired_at, expires_at FROM paired_users "
                    "WHERE channel = ? ORDER BY paired_at",
                    (channel,),
                ).fetchall()
        return [
            PairedUser(
                channel=r[0],
                raw_id=r[1],
                did=r[2],
                capabilities=_deserialize_caps(r[3]),
                ttl_seconds=r[4],
                paired_at=r[5],
                expires_at=r[6],
            )
            for r in rows
        ]

    def all_active_paired(self) -> list[PairedUser]:
        """Rows whose `expires_at > now`. Used by
        `PairingService.restore_active_sessions` on runtime boot.
        """
        now = self._clock()
        return [p for p in self.list_paired() if p.expires_at > now]

    def revoke(self, did: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM paired_users WHERE did = ?", (did,))
            conn.commit()
            return cur.rowcount > 0
