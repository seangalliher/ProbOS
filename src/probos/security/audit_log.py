"""AD-754: local assistant audit log for delegated actions."""

from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from probos.security.pii_redaction import PIIRedactor


@dataclass(frozen=True)
class AuditEntry:
    timestamp: datetime
    action: str
    resource: str
    actor: str
    success: bool
    reason: str | None
    session_id: str


class AuditLog:
    """SQLite-backed assistant audit log with retention and redaction."""

    def __init__(self, db_path: str, retention_days: int = 90) -> None:
        self._db_path = Path(db_path)
        self._retention_days = max(1, retention_days)

    async def log_intent(
        self,
        intent: str,
        resource: str,
        actor: str,
        success: bool,
        reason: str | None = None,
        session_id: str = "local",
    ) -> None:
        """Record one delegated intent execution."""
        await self._insert_entry(
            action=intent,
            resource=resource,
            actor=actor,
            success=success,
            reason=reason,
            session_id=session_id,
        )

    async def log_credential_operation(self, op: str, key: str) -> None:
        """Record credential operations (store/retrieve/delete)."""
        await self._insert_entry(
            action=f"credential_{op}",
            resource=key,
            actor="assistant",
            success=True,
            reason=None,
            session_id="local",
        )

    async def query(self, days_back: int = 7) -> list[AuditEntry]:
        """Return recent entries for diagnostics and explainability."""
        await self._ensure_schema()
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, days_back))

        def _query() -> list[AuditEntry]:
            conn = sqlite3.connect(self._db_path)
            try:
                rows = conn.execute(
                    """
                    SELECT timestamp, action, resource, actor, success, reason, session_id
                    FROM assistant_audit_log
                    WHERE timestamp >= ?
                    ORDER BY timestamp DESC
                    """,
                    (cutoff.isoformat(),),
                ).fetchall()
                return [
                    AuditEntry(
                        timestamp=datetime.fromisoformat(row[0]),
                        action=row[1],
                        resource=row[2],
                        actor=row[3],
                        success=bool(row[4]),
                        reason=row[5],
                        session_id=row[6],
                    )
                    for row in rows
                ]
            finally:
                conn.close()

        return await asyncio.to_thread(_query)

    async def mark_deleted(self, resource_marker: str) -> int:
        """Mark matching audit resources as deleted after erasure."""
        await self._ensure_schema()

        def _mark() -> int:
            conn = sqlite3.connect(self._db_path)
            try:
                cur = conn.execute(
                    """
                    UPDATE assistant_audit_log
                    SET resource = '[DELETED]'
                    WHERE resource LIKE ?
                    """,
                    (f"%{resource_marker}%",),
                )
                conn.commit()
                return int(cur.rowcount)
            finally:
                conn.close()

        return await asyncio.to_thread(_mark)

    async def _insert_entry(
        self,
        *,
        action: str,
        resource: str,
        actor: str,
        success: bool,
        reason: str | None,
        session_id: str,
    ) -> None:
        await self._ensure_schema()
        await self._prune_expired()

        now = datetime.now(timezone.utc).isoformat()
        redacted_resource = PIIRedactor.redact_all(resource)
        redacted_reason = PIIRedactor.redact_all(reason) if reason else None

        def _insert() -> None:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute(
                    """
                    INSERT INTO assistant_audit_log
                    (timestamp, action, resource, actor, success, reason, session_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (now, action, redacted_resource, actor, int(success), redacted_reason, session_id),
                )
                conn.commit()
            finally:
                conn.close()

        await asyncio.to_thread(_insert)

    async def _ensure_schema(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        def _create() -> None:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS assistant_audit_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        action TEXT NOT NULL,
                        resource TEXT NOT NULL,
                        actor TEXT NOT NULL,
                        success INTEGER NOT NULL,
                        reason TEXT,
                        session_id TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_assistant_audit_ts ON assistant_audit_log(timestamp)"
                )
                conn.commit()
            finally:
                conn.close()

        await asyncio.to_thread(_create)

    async def _prune_expired(self) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._retention_days)

        def _prune() -> None:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute(
                    "DELETE FROM assistant_audit_log WHERE timestamp < ?",
                    (cutoff.isoformat(),),
                )
                conn.commit()
            finally:
                conn.close()

        await asyncio.to_thread(_prune)
