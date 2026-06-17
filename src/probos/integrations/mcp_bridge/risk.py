"""AD-1019b: MCP tool risk classification — the graduated "keys" governance model.

A tool's risk tier determines what gating its *invocation* requires (enforced at
the invoke path by AD-1019c — this module only classifies + stores):

- ``OPEN``      — a hammer (0 keys): free use once authorized. Default.
- ``CONFIRM``   — a sidearm (1 key): single operator confirmation before invoke.
- ``CONSENSUS`` — a torpedo (2 keys): multi-agent quorum vote (reuses the
  existing ``requires_consensus`` machinery).

Maps directly onto ProbOS's **Safety Budget** (risk-proportional consensus) and
**Reversibility Preference** (gate the irreversible) axioms: authorization is the
gate for the common case; only weapons need keys.

Resolution is two-level: a per-tool override (if set) wins; otherwise the
server's ``default_risk``; otherwise ``OPEN``. ``resolve_tool_risk`` is pure;
``McpToolRiskStore`` persists per-tool overrides (config, not audit — no
soft-revoke).
"""

from __future__ import annotations

import logging
import time
import uuid
from enum import Enum
from typing import Any

from probos.protocols import ConnectionFactory

logger = logging.getLogger(__name__)


class McpToolRisk(str, Enum):
    """Graduated risk tier for an MCP tool (the "keys" model)."""

    OPEN = "open"
    CONFIRM = "confirm"
    CONSENSUS = "consensus"


def resolve_tool_risk(
    server_default: McpToolRisk, tool_override: McpToolRisk | None
) -> McpToolRisk:
    """Resolve the effective risk tier for a tool (pure; no I/O).

    A per-tool override wins; otherwise the server default. Uses an explicit
    ``is not None`` check (NOT ``or``) so an override is honored even though enum
    members are truthy/falsy-agnostic.
    """
    return tool_override if tool_override is not None else server_default


_SCHEMA = """
CREATE TABLE IF NOT EXISTS mcp_tool_risk (
    id TEXT PRIMARY KEY,
    server_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    risk TEXT NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(server_id, tool_name)
);
CREATE INDEX IF NOT EXISTS idx_mtr_server ON mcp_tool_risk(server_id);
"""


class McpToolRiskStore:
    """Persistent per-tool risk overrides (AD-1019b).

    A small config store (set / get / clear / list) mirroring the
    ConnectionFactory + WAL + in-memory cache lifecycle, ``db_path=""``
    cache-only for tests. An override is configuration, not an audit record, so
    there is NO soft-revoke — ``clear_risk`` hard-deletes and ``set_risk``
    upserts (one row per ``(server_id, tool_name)``).
    """

    def __init__(
        self,
        db_path: str = "",
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        self._db_path = db_path
        self._db: Any = None
        # cache keyed by (server_id, tool_name) -> McpToolRisk
        self._cache: dict[tuple[str, str], McpToolRisk] = {}
        self._connection_factory = connection_factory
        if self._connection_factory is None:
            from probos.storage.sqlite_factory import default_factory

            self._connection_factory = default_factory

    async def start(self) -> None:
        if self._db_path:
            self._db = await self._connection_factory.connect(self._db_path)
            await self._db.execute("PRAGMA journal_mode=WAL")
            await self._db.execute("PRAGMA busy_timeout=5000")
            await self._db.execute("PRAGMA synchronous=NORMAL")
            await self._db.executescript(_SCHEMA)
            await self._db.commit()
            await self._load_cache()

    async def stop(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def _load_cache(self) -> None:
        self._cache.clear()
        if not self._db:
            return
        async with self._db.execute(
            "SELECT server_id, tool_name, risk FROM mcp_tool_risk"
        ) as cur:
            async for row in cur:
                try:
                    self._cache[(row[0], row[1])] = McpToolRisk(row[2])
                except ValueError:
                    logger.warning(
                        "AD-1019b: unknown risk %r for %s/%s; ignoring override",
                        row[2], row[0], row[1],
                    )

    async def set_risk(
        self, server_id: str, tool_name: str, risk: McpToolRisk
    ) -> None:
        """Upsert the per-tool risk override (replaces any existing row)."""
        if self._db:
            await self._db.execute(
                "INSERT INTO mcp_tool_risk (id, server_id, tool_name, risk, updated_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(server_id, tool_name) DO UPDATE SET risk = excluded.risk, updated_at = excluded.updated_at",
                (str(uuid.uuid4()), server_id, tool_name, risk.value, time.time()),
            )
            await self._db.commit()
        self._cache[(server_id, tool_name)] = risk

    def get_risk_sync(self, server_id: str, tool_name: str) -> McpToolRisk | None:
        """Sync read of the per-tool override (zero I/O); ``None`` when unset."""
        return self._cache.get((server_id, tool_name))

    async def clear_risk(self, server_id: str, tool_name: str) -> bool:
        """Hard-delete the per-tool override. Returns True if one existed."""
        existed = (server_id, tool_name) in self._cache
        if self._db:
            await self._db.execute(
                "DELETE FROM mcp_tool_risk WHERE server_id = ? AND tool_name = ?",
                (server_id, tool_name),
            )
            await self._db.commit()
        self._cache.pop((server_id, tool_name), None)
        return existed

    def list_sync(self) -> list[dict[str, str]]:
        """All overrides as serializable dicts (for AD-1019d authoring UI)."""
        return [
            {"server_id": sid, "tool_name": tname, "risk": risk.value}
            for (sid, tname), risk in self._cache.items()
        ]
