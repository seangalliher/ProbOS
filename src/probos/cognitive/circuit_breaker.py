"""AD-488: Cognitive Circuit Breaker — metacognitive loop detection.

Monitors per-agent cognitive event patterns for rumination signatures
and intervenes with forced cooldown + attention redirection.
Not punishment — health protection.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class BreakerState(Enum):
    """Circuit breaker state machine."""
    CLOSED = "closed"       # Normal operation
    OPEN = "open"           # Tripped — agent on forced cooldown
    HALF_OPEN = "half_open" # Recovery probe — allow one think


@dataclass
class CognitiveEvent:
    """A recorded cognitive event for loop analysis."""
    timestamp: float
    event_type: str          # "proactive_think", "ward_room_post", "episode_store"
    content_fingerprint: set  # Word set for Jaccard comparison
    agent_id: str


@dataclass
class AgentBreakerState:
    """Per-agent circuit breaker state."""
    state: BreakerState = BreakerState.CLOSED
    tripped_at: float = 0.0
    trip_count: int = 0       # Lifetime trip counter
    cooldown_seconds: float = 900.0  # 15 min default, escalates
    events: deque = field(default_factory=lambda: deque(maxlen=50))
    last_probe_at: float = 0.0


class CognitiveCircuitBreaker:
    """Monitors cognitive event patterns and trips on rumination detection.

    Standard circuit breaker pattern:
      CLOSED  → agent thinks normally
      OPEN    → agent on forced cooldown, proactive thinks blocked
      HALF_OPEN → single probe think allowed; if healthy → CLOSED, if loop → OPEN

    Parameters
    ----------
    velocity_threshold : int
        Max events in the velocity window before velocity signal fires.
    velocity_window_seconds : float
        Sliding window for velocity measurement.
    similarity_threshold : float
        Jaccard similarity threshold for rumination detection.
    similarity_min_events : int
        Minimum recent events to compare before similarity signal fires.
    base_cooldown_seconds : float
        Initial cooldown when circuit breaker trips. Escalates on repeated trips.
    max_cooldown_seconds : float
        Maximum cooldown cap.
    """

    def __init__(
        self,
        *,
        velocity_threshold: int = 8,
        velocity_window_seconds: float = 300.0,    # 5 minutes
        similarity_threshold: float = 0.6,
        similarity_min_events: int = 4,
        base_cooldown_seconds: float = 900.0,      # 15 minutes
        max_cooldown_seconds: float = 3600.0,       # 1 hour
    ) -> None:
        self._velocity_threshold = velocity_threshold
        self._velocity_window = velocity_window_seconds
        self._similarity_threshold = similarity_threshold
        self._similarity_min_events = similarity_min_events
        self._base_cooldown = base_cooldown_seconds
        self._max_cooldown = max_cooldown_seconds
        self._agents: dict[str, AgentBreakerState] = {}

    def _get_state(self, agent_id: str) -> AgentBreakerState:
        """Get or create per-agent breaker state."""
        if agent_id not in self._agents:
            self._agents[agent_id] = AgentBreakerState()
        return self._agents[agent_id]

    def record_event(
        self,
        agent_id: str,
        event_type: str,
        content: str,
    ) -> None:
        """Record a cognitive event for pattern analysis.

        Call this after every proactive think, Ward Room post, or episode store
        for crew agents.
        """
        state = self._get_state(agent_id)
        words = set(content.lower().split()) if content else set()
        event = CognitiveEvent(
            timestamp=time.monotonic(),
            event_type=event_type,
            content_fingerprint=words,
            agent_id=agent_id,
        )
        state.events.append(event)

    def should_allow_think(self, agent_id: str) -> bool:
        """Check if the agent is allowed to think proactively.

        Returns True if CLOSED or HALF_OPEN (probe), False if OPEN.
        Also handles state transitions (OPEN → HALF_OPEN after cooldown).
        """
        state = self._get_state(agent_id)
        now = time.monotonic()

        if state.state == BreakerState.CLOSED:
            return True

        if state.state == BreakerState.OPEN:
            # Check if cooldown has elapsed → transition to HALF_OPEN
            elapsed = now - state.tripped_at
            if elapsed >= state.cooldown_seconds:
                state.state = BreakerState.HALF_OPEN
                state.last_probe_at = now
                logger.info(
                    "AD-488: Circuit breaker HALF_OPEN for %s (cooldown %.0fs elapsed)",
                    agent_id, elapsed,
                )
                return True  # Allow one probe think
            return False  # Still cooling down

        if state.state == BreakerState.HALF_OPEN:
            # Only allow if this is the first probe (not a second concurrent think)
            return True

        return True  # Defensive default

    def check_and_trip(self, agent_id: str) -> bool:
        """Analyze recent events and trip breaker if rumination detected.

        Call this AFTER a proactive think completes. Returns True if breaker
        tripped (so caller can take recovery actions).

        Detection signals (any one is sufficient):
        1. Velocity: >N events in M-minute window
        2. Similarity: >threshold Jaccard overlap across recent events
        """
        state = self._get_state(agent_id)
        now = time.monotonic()

        # If HALF_OPEN and we reach this point, the probe succeeded if no signal fires.
        # We'll check signals and either close or re-trip.

        tripped = False
        reason = ""

        # --- Signal 1: Velocity (event burst) ---
        window_start = now - self._velocity_window
        recent = [e for e in state.events if e.timestamp >= window_start]
        if len(recent) >= self._velocity_threshold:
            tripped = True
            reason = f"velocity ({len(recent)} events in {self._velocity_window:.0f}s)"

        # --- Signal 2: Similarity (content rumination) ---
        if not tripped and len(recent) >= self._similarity_min_events:
            # Check pairwise Jaccard of the last N events
            fingerprints = [e.content_fingerprint for e in recent if e.content_fingerprint]
            if len(fingerprints) >= self._similarity_min_events:
                similar_pairs = 0
                total_pairs = 0
                for j in range(len(fingerprints)):
                    for k in range(j + 1, len(fingerprints)):
                        total_pairs += 1
                        union = fingerprints[j] | fingerprints[k]
                        if union:
                            sim = len(fingerprints[j] & fingerprints[k]) / len(union)
                            if sim >= self._similarity_threshold:
                                similar_pairs += 1
                # Trip if majority of pairs are similar
                if total_pairs > 0 and similar_pairs / total_pairs >= 0.5:
                    tripped = True
                    reason = f"rumination ({similar_pairs}/{total_pairs} pairs above {self._similarity_threshold} threshold)"

        if tripped:
            self._trip(agent_id, reason)
            return True

        # If HALF_OPEN and no signals → recovery successful → CLOSED
        if state.state == BreakerState.HALF_OPEN:
            state.state = BreakerState.CLOSED
            logger.info("AD-488: Circuit breaker CLOSED for %s (recovery confirmed)", agent_id)

        return False

    def _trip(self, agent_id: str, reason: str) -> None:
        """Trip the circuit breaker for an agent."""
        state = self._get_state(agent_id)
        state.trip_count += 1
        state.tripped_at = time.monotonic()
        state.state = BreakerState.OPEN

        # Escalating cooldown: base × 2^(trip_count - 1), capped
        cooldown = min(
            self._base_cooldown * (2 ** (state.trip_count - 1)),
            self._max_cooldown,
        )
        state.cooldown_seconds = cooldown

        logger.warning(
            "AD-488: Circuit breaker TRIPPED for %s — %s. "
            "Cooldown: %.0fs. Trip count: %d",
            agent_id, reason, cooldown, state.trip_count,
        )

    def get_status(self, agent_id: str) -> dict:
        """Return breaker status for an agent (for API/diagnostics)."""
        state = self._get_state(agent_id)
        return {
            "agent_id": agent_id,
            "state": state.state.value,
            "trip_count": state.trip_count,
            "cooldown_seconds": state.cooldown_seconds,
            "tripped_at": state.tripped_at,
            "event_count": len(state.events),
        }

    def get_all_statuses(self) -> list[dict]:
        """Return breaker status for all tracked agents."""
        return [self.get_status(aid) for aid in self._agents]

    def get_attention_redirect(self, agent_id: str) -> str | None:
        """Return an attention redirect prompt if breaker recently tripped.

        This is injected into the agent's next proactive context to shift
        their cognitive focus away from the rumination topic.
        """
        state = self._get_state(agent_id)
        if state.trip_count == 0:
            return None
        if state.state == BreakerState.OPEN:
            return None  # Don't generate redirect while still cooling down

        # HALF_OPEN or recently recovered — provide redirect
        elapsed_since_trip = time.monotonic() - state.tripped_at
        if elapsed_since_trip < state.cooldown_seconds * 2:
            return (
                "IMPORTANT: Your cognitive circuit breaker recently activated "
                f"(trip #{state.trip_count}). This means you were repeating "
                "similar thoughts in a loop. This is normal and not a failure — "
                "it happens to all minds, biological and artificial.\n\n"
                "For this cycle, deliberately shift your attention:\n"
                "- Look at a DIFFERENT aspect of the ship's operations\n"
                "- Consider what OTHER departments might need\n"
                "- If you have nothing genuinely new to contribute, respond with [NO_RESPONSE]\n\n"
                "Quality over quantity. One fresh insight is worth more than "
                "ten variations on the same observation."
            )
        return None

    def reset_agent(self, agent_id: str) -> None:
        """Reset an agent's breaker state (e.g., after a ship reset)."""
        if agent_id in self._agents:
            del self._agents[agent_id]

    def reset_all(self) -> None:
        """Reset all breaker states."""
        self._agents.clear()
