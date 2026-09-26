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

AD-1228: an optional record observer (``set_record_observer``) is told of each
sample as it is recorded, so a standing interest in high self-similarity is
evaluated when the score is produced instead of by polling this ring.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Callable

logger = logging.getLogger(__name__)


class SelfSimilarityHistory:
    """Per-agent ring of ``(timestamp, similarity)`` self-similarity samples."""

    def __init__(self, cap: int = 20) -> None:
        self._cap = max(1, int(cap))
        self._history: dict[str, deque[tuple[float, float]]] = {}
        self._observer: Callable[[str, float], None] | None = None

    def set_record_observer(self, observer: Callable[[str, float], None] | None) -> None:
        """AD-1228: call ``observer(agent_id, sim)`` after each recorded sample; None detaches."""
        self._observer = observer

    def record(self, agent_id: str, sim: float, ts: float | None = None) -> None:
        """Append one ``(timestamp, similarity)`` sample for ``agent_id``."""
        ring = self._history.get(agent_id)
        if ring is None:
            ring = deque(maxlen=self._cap)
            self._history[agent_id] = ring
        value = float(sim)
        ring.append((float(ts if ts is not None else time.time()), value))
        observer = self._observer
        if observer is not None:
            try:
                observer(agent_id, value)
            except Exception:
                logger.warning(
                    "AD-1228: the self-similarity record observer failed for %s; the sample "
                    "is recorded and the next one is still observed",
                    agent_id, exc_info=True,
                )

    def recent(self, agent_id: str, n: int = 20) -> list[tuple[float, float]]:
        """Return up to the last ``n`` samples (oldest first), or [] if none."""
        ring = self._history.get(agent_id)
        if not ring:
            return []
        if n <= 0:
            return []
        return list(ring)[-n:]
