"""AD-722f: per-agent avatar-telemetry sampling state machine.

Three tiers with priority resolution: HIGH > NORMAL > LOW. Triggers are
reference-counted per agent — concurrent enters of the same trigger
type are tolerated (rare but possible: two DMs in flight, or a chain
spawned during a DM). The current tier is the highest active trigger.

Trigger surfaces (Wave 141):
  - ``enter_dm`` / ``exit_dm`` — wired at routers/agents.py:agent_chat
    (entry around the existing ``observe_self_avatar()`` call;
    exit around the existing ``mark_reply_emitted`` call).
  - ``enter_chain`` / ``exit_chain`` — wired at cognitive_agent.py around
    the ``_execute_chain_with_intent_routing`` call site (line ~1394).

Trigger surfaces NOT wired in Wave 141 (forward markers):
  - ``enter_subscriber`` / ``exit_subscriber`` — Wave 142 / AD-722b WebSocket
    subscribe/unsubscribe. Method names reserved here for forward-marker
    discoverability; bodies are NOT defined in this AD.

Per AD-722 addendum (h): WR (ward_room_notification) does NOT trigger
state changes. The state machine does not expose ``enter_wr``/``exit_wr``;
a test asserts their absence.

State is volatile by design — restart resets every agent to LOW.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from threading import Lock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from probos.config import SamplingRatesConfig

logger = logging.getLogger(__name__)


# Tier names (string literals — match the tier names exposed in the
# AvatarTelemetrySnapshot.sampling_tier field).
TIER_HIGH = "high"
TIER_NORMAL = "normal"
TIER_LOW = "low"


class AvatarSamplingStateMachine:
    """Per-agent reference-counted trigger registry → tier resolution.

    Thread-safe (Lock-guarded) for the FastAPI / asyncio thread-pool
    crossover; trigger entries originate from request handlers (sync
    section of FastAPI) and chain entries from agent code (asyncio
    coroutine). Lock contention is microscopic — typical agent has
    0-2 active triggers at any moment.
    """

    def __init__(self, rates: "SamplingRatesConfig") -> None:
        self._rates = rates
        # nested dict: agent_id -> {trigger_name: refcount}
        self._counts: dict[str, dict[str, int]] = defaultdict(
            lambda: {"dm": 0, "chain": 0},
        )
        self._lock = Lock()

    # ── Trigger surfaces (Wave 141) ─────────────────────────────────

    def enter_dm(self, agent_id: str) -> None:
        with self._lock:
            self._counts[agent_id]["dm"] += 1

    def exit_dm(self, agent_id: str) -> None:
        with self._lock:
            n = self._counts[agent_id]["dm"]
            if n <= 0:
                # Spurious exit (e.g. handler exception path between
                # observe_self_avatar and mark_reply_emitted). Tier-2
                # log-and-degrade — clamp to 0.
                logger.warning(
                    "AD-722f: spurious exit_dm for agent=%s (count was %d); clamping to 0",
                    agent_id, n,
                )
                self._counts[agent_id]["dm"] = 0
                return
            self._counts[agent_id]["dm"] = n - 1

    def enter_chain(self, agent_id: str) -> None:
        with self._lock:
            self._counts[agent_id]["chain"] += 1

    def exit_chain(self, agent_id: str) -> None:
        with self._lock:
            n = self._counts[agent_id]["chain"]
            if n <= 0:
                logger.warning(
                    "AD-722f: spurious exit_chain for agent=%s (count was %d); clamping to 0",
                    agent_id, n,
                )
                self._counts[agent_id]["chain"] = 0
                return
            self._counts[agent_id]["chain"] = n - 1

    # ── Read surface ────────────────────────────────────────────────

    def current_tier(self, agent_id: str) -> str:
        """Resolve the active tier for an agent. HIGH > NORMAL > LOW."""
        with self._lock:
            counts = self._counts.get(agent_id)
            if counts is None:
                return TIER_LOW
            if counts.get("dm", 0) > 0:
                return TIER_HIGH
            if counts.get("chain", 0) > 0:
                return TIER_NORMAL
            return TIER_LOW

    def current_rate_ms(self, agent_id: str) -> int:
        """Resolve the active sampling rate (ms) for an agent."""
        tier = self.current_tier(agent_id)
        if tier == TIER_HIGH:
            return self._rates.high_ms
        if tier == TIER_NORMAL:
            return self._rates.normal_ms
        return self._rates.low_ms

    def snapshot_counts(self, agent_id: str) -> dict[str, int]:
        """Test-only introspection. Returns a copy of the trigger counts."""
        with self._lock:
            counts = self._counts.get(agent_id)
            if counts is None:
                return {"dm": 0, "chain": 0}
            return dict(counts)
