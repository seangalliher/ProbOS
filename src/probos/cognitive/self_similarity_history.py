"""AD-903: in-memory self-similarity history ring.

``proactive._build_self_monitoring_context`` computes a per-agent
self-similarity score each proactive cycle (Jaccard over the agent's recent
posts) but only ever held the *latest* snapshot. The Counselor clinical trend
surface needs the recent *trajectory*, so this ring records each computed score
as it is produced.

Pure in-memory and always-on: a fixed-size ``deque`` per agent (no SQLite, no
async, no config). On restart the history starts empty and refills on the next
proactive cycles — correct behavior for a volatile cognitive indicator (mirrors
the ``DutyScheduleTracker`` "fresh start = fresh duties" stance).
"""

from __future__ import annotations

import time
from collections import deque


class SelfSimilarityHistory:
    """Per-agent ring of ``(timestamp, similarity)`` self-similarity samples."""

    def __init__(self, cap: int = 20) -> None:
        self._cap = max(1, int(cap))
        self._history: dict[str, deque[tuple[float, float]]] = {}

    def record(self, agent_id: str, sim: float, ts: float | None = None) -> None:
        """Append one ``(timestamp, similarity)`` sample for ``agent_id``."""
        ring = self._history.get(agent_id)
        if ring is None:
            ring = deque(maxlen=self._cap)
            self._history[agent_id] = ring
        ring.append((float(ts if ts is not None else time.time()), float(sim)))

    def recent(self, agent_id: str, n: int = 20) -> list[tuple[float, float]]:
        """Return up to the last ``n`` samples (oldest first), or [] if none."""
        ring = self._history.get(agent_id)
        if not ring:
            return []
        if n <= 0:
            return []
        return list(ring)[-n:]
