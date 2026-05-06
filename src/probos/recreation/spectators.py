"""AD-526e: Spectator Registry — Recreation read-side analytics.

Tracks per-game spectator membership and per-game commentary as a thin
in-memory surface. Mirrors the AD-526d ``GamePreferenceTracker`` shape
(read-side analytics first, producers wired in -1/-2/-3 children).

Public API (Wave-5 convention #1: no leading underscore):

- ``add_spectator(game_id, agent_id) -> bool`` — idempotent; returns True
  on first add per (game_id, agent_id) and emits
  ``RECREATION_SPECTATOR_JOINED``; returns False on duplicate without
  re-emitting.
- ``remove_spectator(game_id, agent_id) -> bool`` — returns True when the
  agent was a spectator (silent no event).
- ``get_spectators(game_id) -> tuple[str, ...]`` — frozen tuple of
  agent_ids in insertion order.
- ``record_commentary(game_id, agent_id, text) -> None`` — empty-suppress
  on missing inputs; emits ``RECREATION_SPECTATOR_COMMENTARY``.
- ``get_commentary(game_id) -> tuple[dict[str, Any], ...]`` — frozen tuple
  of ``{"agent_id": str, "text": str, "timestamp": float}`` entries in
  insertion order.
- ``clear_game(game_id) -> None`` — drop all spectators and commentary
  for a game; intended for the future AD-526e-2 end-of-game wiring.
- ``set_event_callback(emit_fn)`` — late-bind event emission (mirrors
  ``BilletRegistry`` and ``GamePreferenceTracker``).

Lifecycle is best-effort (Wave-5 tier-2): swallow emit-side exceptions,
log, continue. State-mutation exceptions (e.g. non-string agent_id) are
NOT wrapped — they fail loud.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from probos.events import EventType

logger = logging.getLogger(__name__)


class SpectatorRegistry:
    """Per-game spectator membership + commentary log. AD-526e v1."""

    def __init__(self) -> None:
        self._spectators: dict[str, list[str]] = {}  # game_id -> ordered agent_ids
        self._commentary: dict[str, list[dict[str, Any]]] = {}  # game_id -> entries
        self._emit_event_fn: Callable[..., None] | None = None

    # ------------------------------------------------------------------
    # Public API (Wave-5 convention #1: no leading underscore)
    # ------------------------------------------------------------------

    def set_event_callback(
        self, emit_fn: Callable[..., None],
    ) -> None:
        """Late-bind event emission callback (mirror BilletRegistry pattern)."""
        self._emit_event_fn = emit_fn

    def add_spectator(self, game_id: str, agent_id: str) -> bool:
        """Idempotently add ``agent_id`` to the spectator list for ``game_id``.

        Returns True when newly added (and emits
        ``RECREATION_SPECTATOR_JOINED``); False on duplicate without
        re-emitting. No-op + return False on empty inputs.
        """
        if not game_id or not agent_id:
            return False
        agents = self._spectators.setdefault(game_id, [])
        if agent_id in agents:
            return False
        agents.append(agent_id)
        if self._emit_event_fn is not None:
            try:
                self._emit_event_fn(
                    EventType.RECREATION_SPECTATOR_JOINED,
                    {
                        "game_id": game_id,
                        "agent_id": agent_id,
                        "spectator_count": len(agents),
                    },
                )
            except Exception:
                logger.warning(
                    "AD-526e: RECREATION_SPECTATOR_JOINED emit failed for %s/%s",
                    game_id, agent_id, exc_info=True,
                )
        return True

    def remove_spectator(self, game_id: str, agent_id: str) -> bool:
        """Remove ``agent_id`` from the spectator list for ``game_id``.

        Returns True when the agent was present and removed; False when
        the agent was not a spectator. Does NOT emit (mirrors AD-526d's
        no-removal-event pattern).
        """
        if not game_id or not agent_id:
            return False
        agents = self._spectators.get(game_id)
        if agents is None or agent_id not in agents:
            return False
        agents.remove(agent_id)
        return True

    def get_spectators(self, game_id: str) -> tuple[str, ...]:
        """Return frozen tuple of spectator agent_ids in insertion order."""
        agents = self._spectators.get(game_id)
        if agents is None:
            return ()
        return tuple(agents)

    def record_commentary(
        self, game_id: str, agent_id: str, text: str,
    ) -> None:
        """Record a commentary entry for ``game_id``.

        No-op when any input is empty/whitespace-only. Best-effort on event
        emission failure.
        """
        if not game_id or not agent_id or not text or not text.strip():
            return
        entry: dict[str, Any] = {
            "agent_id": agent_id,
            "text": text,
            "timestamp": time.time(),
        }
        entries = self._commentary.setdefault(game_id, [])
        entries.append(entry)
        if self._emit_event_fn is not None:
            try:
                self._emit_event_fn(
                    EventType.RECREATION_SPECTATOR_COMMENTARY,
                    {
                        "game_id": game_id,
                        "agent_id": agent_id,
                        "comment_count": len(entries),
                    },
                )
            except Exception:
                logger.warning(
                    "AD-526e: RECREATION_SPECTATOR_COMMENTARY emit failed for %s/%s",
                    game_id, agent_id, exc_info=True,
                )

    def get_commentary(self, game_id: str) -> tuple[dict[str, Any], ...]:
        """Return frozen tuple of commentary entries in insertion order.

        Each entry is ``{"agent_id": str, "text": str, "timestamp": float}``.
        Caller MUST NOT mutate the returned dicts.
        """
        entries = self._commentary.get(game_id)
        if entries is None:
            return ()
        return tuple(entries)

    def clear_game(self, game_id: str) -> None:
        """Drop all spectators and commentary for ``game_id``.

        Intended for the future AD-526e-2 end-of-game RecreationService
        wiring. Safe to call on unknown ``game_id`` (no-op).
        """
        if not game_id:
            return
        self._spectators.pop(game_id, None)
        self._commentary.pop(game_id, None)
