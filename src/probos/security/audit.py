"""AD-456: AuditLog -- append-only hash-chained record.

v1 in-memory only. Each entry includes the SHA-256 of the prior entry
(hash chain). Tamper detection via ``verify_chain()``. Persistence to SQLite
deferred to AD-456d.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from probos.events import EventType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AuditEntry:
    """One hash-chained audit record."""

    sequence: int
    timestamp: float
    category: str
    detail: str
    prior_hash: str
    entry_hash: str


@dataclass
class AuditLog:
    """In-memory hash-chained log.

    Append-only. Each entry's hash includes the prior entry's hash so any
    tampering breaks the chain. ``verify_chain()`` re-derives every hash and
    confirms continuity.
    """

    entries: list[AuditEntry] = field(default_factory=list)
    emit_event: Any | None = None

    GENESIS_HASH: str = "0" * 64

    def append(self, *, category: str, detail: str) -> AuditEntry:
        prior_hash = self.entries[-1].entry_hash if self.entries else self.GENESIS_HASH
        sequence = len(self.entries)
        ts = time.time()
        payload = {
            "sequence": sequence,
            "timestamp": ts,
            "category": category,
            "detail": detail,
            "prior_hash": prior_hash,
        }
        entry_hash = self._hash(payload)
        entry = AuditEntry(
            sequence=sequence,
            timestamp=ts,
            category=category,
            detail=detail,
            prior_hash=prior_hash,
            entry_hash=entry_hash,
        )
        self.entries.append(entry)
        if self.emit_event is not None:
            try:
                self.emit_event(
                    EventType.AUDIT_RECORDED,
                    {
                        "sequence": sequence,
                        "category": category,
                        "entry_hash": entry_hash,
                    },
                )
            except Exception:
                logger.warning(
                    "AD-456: AUDIT_RECORDED emit failed (sequence=%d, category=%s)",
                    sequence, category, exc_info=True,
                )
        return entry

    def verify_chain(self) -> bool:
        """Re-derive every entry hash; return True if chain is intact."""
        prior = self.GENESIS_HASH
        for entry in self.entries:
            payload = {
                "sequence": entry.sequence,
                "timestamp": entry.timestamp,
                "category": entry.category,
                "detail": entry.detail,
                "prior_hash": entry.prior_hash,
            }
            recomputed = self._hash(payload)
            if recomputed != entry.entry_hash or entry.prior_hash != prior:
                return False
            prior = entry.entry_hash
        return True

    def _hash(self, payload: dict[str, Any]) -> str:
        canonical = json.dumps(payload, sort_keys=True).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()
