"""AD-526d: Game preference tracking.

Per-agent per-game-type play frequency. Read-side analytics surface
exposing the data-collection hook that AD-526e/f/g/h (spectator
commentary, holodeck integration, creative content, chess engine)
will share.

Lifecycle is best-effort (Wave-5 tier-2): swallow exceptions, log,
continue. The tracker is a thin in-memory ring; persistence is
out-of-scope for v1.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from probos.events import EventType

logger = logging.getLogger(__name__)


class GamePreferenceTracker:
    """Tracks per-agent per-game-type play frequency. AD-526d."""

    def __init__(self) -> None:
        self._frequencies: dict[str, dict[str, int]] = {}  # agent_id -> game_type -> count
        self._emit_event_fn: Callable[..., None] | None = None

    # ------------------------------------------------------------------
    # Public API (Wave 5 convention #1: no leading underscore)
    # ------------------------------------------------------------------

    def set_event_callback(
        self, emit_fn: Callable[..., None],
    ) -> None:
        """Late-bind event emission callback (mirror BilletRegistry pattern)."""
        self._emit_event_fn = emit_fn

    def record_game(self, agent_id: str, game_type: str) -> None:
        """Increment play count + emit GAME_PREFERENCE_RECORDED.

        No-op when ``agent_id`` or ``game_type`` is empty. Best-effort
        on event emission failure.
        """
        if not agent_id or not game_type:
            return
        try:
            agent_freqs = self._frequencies.setdefault(agent_id, {})
            agent_freqs[game_type] = agent_freqs.get(game_type, 0) + 1
            new_count = agent_freqs[game_type]
        except Exception:
            logger.warning(
                "AD-526d: record_game(%s,%s) failed; preference not tracked",
                agent_id, game_type, exc_info=True,
            )
            return
        if self._emit_event_fn is not None:
            try:
                self._emit_event_fn(
                    EventType.GAME_PREFERENCE_RECORDED,
                    {
                        "agent_id": agent_id,
                        "game_type": game_type,
                        "count": new_count,
                    },
                )
            except Exception:
                logger.warning(
                    "AD-526d: GAME_PREFERENCE_RECORDED emit failed for %s/%s",
                    agent_id, game_type, exc_info=True,
                )

    def get_preferences(self, agent_id: str) -> dict[str, int]:
        """Return frozen copy of agent's game frequencies (empty dict if unknown)."""
        agent_freqs = self._frequencies.get(agent_id)
        if agent_freqs is None:
            return {}
        return dict(agent_freqs)

    def top_game_for(self, agent_id: str) -> str | None:
        """Most-played game type for agent, or None if no plays recorded."""
        agent_freqs = self._frequencies.get(agent_id)
        if not agent_freqs:
            return None
        return max(agent_freqs.items(), key=lambda kv: kv[1])[0]
