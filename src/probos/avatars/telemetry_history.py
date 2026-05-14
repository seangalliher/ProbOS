"""AD-722c: append-only JSONL persistence for avatar telemetry snapshots.

One file per agent under {history_dir}/<agent_id>.jsonl. Each line is a JSON
object: {"ts": float, "snap": <AvatarTelemetrySnapshot.to_dict() output>}.
Append-only — no in-place update, no rotation in v1 (AD-722c-1 forward marker
for size-based rotation when files exceed N MiB).

Tier-2 log-and-degrade everywhere — never raises out of public methods. The
WS publish loop and the broadcast trigger MUST NOT block on a write failure.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from probos.avatars.telemetry import AvatarTelemetrySnapshot

logger = logging.getLogger(__name__)

_AGENT_ID_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")


def _sanitize_agent_id(agent_id: str) -> str | None:
    """Boundary defense — agent_id flows into a path component. Reject
    anything outside [A-Za-z0-9_.-]. Returns None on rejection.
    """
    if not isinstance(agent_id, str) or not agent_id:
        return None
    if not _AGENT_ID_RE.match(agent_id):
        return None
    return agent_id


class TelemetryHistoryWriter:
    """Per-agent append-only JSONL writer.

    Serializes writes via an asyncio.Lock keyed per agent_id (writes from
    different agents proceed in parallel; writes from the same agent are
    serialized to avoid interleaved JSON lines).
    """

    def __init__(self, history_dir: str) -> None:
        self._history_dir = Path(history_dir)
        self._locks: dict[str, asyncio.Lock] = {}

    def _path_for(self, agent_id: str) -> Path | None:
        safe = _sanitize_agent_id(agent_id)
        if safe is None:
            return None
        return self._history_dir / f"{safe}.jsonl"

    def _lock_for(self, agent_id: str) -> asyncio.Lock:
        lock = self._locks.get(agent_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[agent_id] = lock
        return lock

    async def append(self, snap: "AvatarTelemetrySnapshot") -> None:
        """Append one snapshot row. Tier-2 — logs+returns on any failure."""
        try:
            path = self._path_for(snap.agent_id)
            if path is None:
                logger.warning(
                    "AD-722c: rejecting telemetry write — invalid agent_id=%r",
                    snap.agent_id,
                )
                return
            lock = self._lock_for(snap.agent_id)
            async with lock:
                # Build line outside the I/O await to keep the lock window tight.
                row = {"ts": time.time(), "snap": snap.to_dict()}
                line = json.dumps(row, separators=(",", ":")) + "\n"
                # Synchronous write inside a thread executor — avoids needing
                # aiofiles and keeps the dependency footprint at zero. Pattern
                # mirrors records_store async-with-blocking-write usage.
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self._sync_append, path, line)
        except Exception:
            logger.warning(
                "AD-722c: telemetry history append failed for agent=%s",
                snap.agent_id, exc_info=True,
            )

    def _sync_append(self, path: Path, line: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)

    async def query(
        self,
        agent_id: str,
        limit: int = 100,
        since: float | None = None,
        retention_days: int = 30,
    ) -> list[dict[str, Any]]:
        """Return up to ``limit`` most recent rows newer than ``since`` (or
        ``now - retention_days`` if since is None). Newest-first.

        Tier-2 — never raises. Missing file → []. Malformed line → skipped.
        """
        try:
            path = self._path_for(agent_id)
            if path is None or not path.exists():
                return []
            cutoff = since if since is not None else (
                time.time() - float(retention_days) * 86400.0
            )
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                None, self._sync_query, path, int(limit), float(cutoff),
            )
        except Exception:
            logger.warning(
                "AD-722c: telemetry history query failed for agent=%s",
                agent_id, exc_info=True,
            )
            return []

    def _sync_query(
        self, path: Path, limit: int, cutoff: float,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                try:
                    row = json.loads(raw)
                except Exception:
                    continue
                ts = row.get("ts")
                if not isinstance(ts, (int, float)) or float(ts) < cutoff:
                    continue
                rows.append(row)
        rows.sort(key=lambda r: float(r.get("ts", 0.0)), reverse=True)
        return rows[: max(0, int(limit))]
