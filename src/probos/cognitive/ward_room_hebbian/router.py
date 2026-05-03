"""AD-641b: Ward Room Hebbian Router -- parallel to mesh Hebbian.

Same math, separate instance and storage. Tracks (topic, agent_id) co-activation
weights. Informs Ward Room routing priority hints; does NOT hard-gate routing.
"""

from __future__ import annotations

import logging
from typing import Any

from probos.events import EventType

logger = logging.getLogger(__name__)


_DEFAULT_LEARNING_RATE = 0.10
_DEFAULT_DECAY = 0.99
_MIN_WEIGHT = 0.0
_MAX_WEIGHT = 1.0


class WardRoomHebbianRouter:
    """In-memory Hebbian router for (topic, agent_id) co-activation.

    Public API:
      - record_contribution(topic, agent_id, signal=+1.0) -> float (new weight)
      - get_weight(topic, agent_id) -> float (0.0 if absent)
      - top_contributors(topic, k=5) -> list[tuple[agent_id, weight]]
      - decay() -> int (number of weights modified)
      - weight_count (property) -> int
    """

    def __init__(
        self,
        *,
        emit_event: Any | None = None,
        learning_rate: float = _DEFAULT_LEARNING_RATE,
        decay_factor: float = _DEFAULT_DECAY,
    ) -> None:
        self._emit_event = emit_event
        self._learning_rate = float(learning_rate)
        self._decay_factor = float(decay_factor)
        self._weights: dict[tuple[str, str], float] = {}

    @property
    def weight_count(self) -> int:
        return len(self._weights)

    def record_contribution(
        self, topic: str, agent_id: str, signal: float = 1.0,
    ) -> float:
        if not topic or not agent_id:
            return 0.0
        key = (str(topic), str(agent_id))
        current = self._weights.get(key, 0.0)
        new_weight = current + self._learning_rate * float(signal)
        new_weight = max(_MIN_WEIGHT, min(_MAX_WEIGHT, new_weight))
        self._weights[key] = new_weight
        if self._emit_event is not None:
            try:
                self._emit_event(
                    EventType.WARD_ROOM_HEBBIAN_UPDATED,
                    {
                        "topic": str(topic),
                        "agent_id": str(agent_id),
                        "weight": new_weight,
                        "signal": float(signal),
                    },
                )
            except Exception:
                pass
        return new_weight

    def get_weight(self, topic: str, agent_id: str) -> float:
        return self._weights.get((str(topic), str(agent_id)), 0.0)

    def top_contributors(
        self, topic: str, k: int = 5,
    ) -> list[tuple[str, float]]:
        if k <= 0:
            return []
        # AD-641b revision: filter zero-weight entries so decayed topics don't
        # surface as ghost contributors (per pass-1 R1).
        pairs = [
            (agent, weight)
            for (t, agent), weight in self._weights.items()
            if t == str(topic) and weight > 0.0
        ]
        pairs.sort(key=lambda p: p[1], reverse=True)
        return pairs[: int(k)]

    def decay(self) -> int:
        modified = 0
        for key in list(self._weights.keys()):
            self._weights[key] *= self._decay_factor
            modified += 1
        if modified and self._emit_event is not None:
            try:
                self._emit_event(
                    EventType.WARD_ROOM_HEBBIAN_DECAYED,
                    {
                        "weights_decayed": modified,
                        "factor": self._decay_factor,
                    },
                )
            except Exception:
                pass
        return modified
