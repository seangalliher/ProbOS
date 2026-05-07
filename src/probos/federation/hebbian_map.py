"""AD-479c: FederationHebbianMap — intent × peer Hebbian routing weights.

Mirrors the AD-271 / AD-274 ``HebbianRouter`` ConnectionFactory pattern at
``src/probos/mesh/routing.py:39`` but keys on ``(intent_name, peer_node_id)``
instead of ``(source_agent, target_agent, rel_type)``. Persists weights to
the ``federation_hebbian_weights`` SQLite table on the same connection
factory used by ``HebbianRouter``.

Successful federation outcomes increment weight by ``reward``; failures
multiply by ``decay_rate``. Weights clamp to ``[0.0, 1.0]``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from probos.protocols import ConnectionFactory, DatabaseConnection

logger = logging.getLogger(__name__)


_FedKey = tuple[str, str]  # (intent_name, peer_node_id)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS federation_hebbian_weights (
    intent_name TEXT NOT NULL,
    peer_node_id TEXT NOT NULL,
    weight REAL NOT NULL,
    PRIMARY KEY (intent_name, peer_node_id)
)
"""


class FederationHebbianMap:
    """AD-479c: intent × peer Hebbian weights for federation routing."""

    def __init__(
        self,
        *,
        decay_rate: float = 0.995,
        reward: float = 0.05,
        db_path: str | Path | None = None,
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        self.decay_rate = decay_rate
        self.reward = reward
        self.db_path = str(db_path) if db_path else None
        self._weights: dict[_FedKey, float] = {}
        self._connection_factory = connection_factory
        if self._connection_factory is None:
            from probos.storage.sqlite_factory import default_factory
            self._connection_factory = default_factory
        self._db: DatabaseConnection | None = None

    async def init(self) -> None:
        """Initialize — load weights from SQLite if configured.

        Idempotent: calling twice does not error and does not duplicate rows.
        """
        if self.db_path is None or self._connection_factory is None:
            return
        if self._db is None:
            self._db = await self._connection_factory.connect(self.db_path)
            await self._db.execute(_SCHEMA)
            await self._db.commit()
        cursor = await self._db.execute(
            "SELECT intent_name, peer_node_id, weight FROM federation_hebbian_weights"
        )
        try:
            rows = await cursor.fetchall()
        finally:
            close = getattr(cursor, "close", None)
            if callable(close):
                try:
                    await close()
                except Exception:
                    pass
        self._weights.clear()
        for intent_name, peer_node_id, weight in rows:
            self._weights[(intent_name, peer_node_id)] = float(weight)

    async def close(self) -> None:
        """Close the underlying connection if open."""
        if self._db is not None:
            await self._db.close()
            self._db = None

    def score(self, intent_name: str, peer_node_id: str) -> float:
        """Return the current weight for an (intent, peer) pair, default 0.0."""
        return self._weights.get((intent_name, peer_node_id), 0.0)

    def record_outcome(
        self,
        *,
        intent_name: str,
        peer_node_id: str,
        success: bool,
    ) -> None:
        """Update the weight for an (intent, peer) pair.

        Success: ``new = current + reward``. Failure: ``new = current * decay_rate``.
        Result is clamped to ``[0.0, 1.0]``.
        """
        key: _FedKey = (intent_name, peer_node_id)
        current = self._weights.get(key, 0.0)
        if success:
            new = current + self.reward
        else:
            new = current * self.decay_rate
        self._weights[key] = max(0.0, min(1.0, new))

    async def persist(self) -> None:
        """Persist all in-memory weights back to SQLite."""
        if self.db_path is None or self._connection_factory is None:
            return
        if self._db is None:
            self._db = await self._connection_factory.connect(self.db_path)
            await self._db.execute(_SCHEMA)
            await self._db.commit()
        for (intent_name, peer_node_id), weight in self._weights.items():
            await self._db.execute(
                "INSERT INTO federation_hebbian_weights "
                "(intent_name, peer_node_id, weight) VALUES (?, ?, ?) "
                "ON CONFLICT (intent_name, peer_node_id) DO UPDATE SET weight=excluded.weight",
                (intent_name, peer_node_id, weight),
            )
        await self._db.commit()

    def all_weights(self) -> dict[_FedKey, float]:
        """Return a defensive copy of the full weight map."""
        return dict(self._weights)
