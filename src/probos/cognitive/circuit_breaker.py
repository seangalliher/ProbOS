"""AD-488: Cognitive Circuit Breaker — metacognitive loop detection.

Monitors per-agent cognitive event patterns for rumination signatures
and intervenes with forced cooldown + attention redirection.
Not punishment — health protection.

AD-506a: Graduated 4-zone model (Green → Amber → Red → Critical).
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from probos.cognitive.similarity import jaccard_similarity

logger = logging.getLogger(__name__)


class BreakerState(Enum):
    """Circuit breaker state machine."""
    CLOSED = "closed"       # Normal operation
    OPEN = "open"           # Tripped — agent on forced cooldown
    HALF_OPEN = "half_open" # Recovery probe — allow one think


class CognitiveZone(Enum):
    """Graduated cognitive health zone (AD-506a)."""
    GREEN = "green"       # Normal — self-monitoring active
    AMBER = "amber"       # Rising similarity — pre-trip warning
    RED = "red"           # Circuit breaker tripped — intervention active
    CRITICAL = "critical" # Repeated trips — Captain escalation


@dataclass
class CognitiveEvent:
    """A recorded cognitive event for loop analysis."""
    timestamp: float
    event_type: str          # "proactive_think", "ward_room_post", "episode_store"
    content_fingerprint: set  # Word set for Jaccard comparison
    agent_id: str
    infrastructure_degraded: bool = False  # AD-576: event during LLM brownout


@dataclass
class AgentBreakerState:
    """Per-agent circuit breaker state."""
    state: BreakerState = BreakerState.CLOSED
    tripped_at: float = 0.0
    trip_count: int = 0       # Lifetime trip counter
    cooldown_seconds: float = 900.0  # 15 min default, escalates
    events: deque = field(default_factory=lambda: deque(maxlen=50))
    last_probe_at: float = 0.0
    # AD-506a: Zone tracking
    zone: CognitiveZone = CognitiveZone.GREEN
    zone_entered_at: float = 0.0
    zone_history: list[tuple[str, float]] = field(default_factory=list)  # (zone_value, timestamp), max 20
    trip_timestamps: list[float] = field(default_factory=list)  # monotonic timestamps for critical window
    last_signals: dict = field(default_factory=dict)  # Cached signals from last _compute_signals()
    # AD-506b: Last zone transition for recovery detection
    last_zone_transition: tuple[str, str] | None = None  # (old, new) or None if no change


class CognitiveCircuitBreaker:
    """Monitors cognitive event patterns and trips on rumination detection.

    Standard circuit breaker pattern:
      CLOSED  → agent thinks normally
      OPEN    → agent on forced cooldown, proactive thinks blocked
      HALF_OPEN → single probe think allowed; if healthy → CLOSED, if loop → OPEN

    AD-506a adds a graduated 4-zone model on top:
      GREEN   → normal, self-monitoring active
      AMBER   → rising similarity pre-trip, agent warned
      RED     → circuit breaker tripped
      CRITICAL → repeated trips, Captain escalation
    """

    def __init__(
        self,
        *,
        config: Any = None,
        velocity_threshold: int = 8,
        velocity_window_seconds: float = 300.0,    # 5 minutes
        similarity_threshold: float = 0.6,
        similarity_min_events: int = 4,
        base_cooldown_seconds: float = 900.0,      # 15 minutes
        max_cooldown_seconds: float = 3600.0,       # 1 hour
        # AD-506a: Zone parameters
        amber_similarity_ratio: float = 0.25,
        amber_velocity_ratio: float = 0.6,
        amber_decay_seconds: float = 900.0,
        red_decay_seconds: float = 1800.0,
        critical_decay_seconds: float = 3600.0,
        critical_trip_window_seconds: float = 3600.0,
        critical_trip_count: int = 3,
    ) -> None:
        if config:
            self._velocity_threshold = config.velocity_threshold
            self._velocity_window = config.velocity_window_seconds
            self._similarity_threshold = config.similarity_threshold
            self._similarity_min_events = config.similarity_min_events
            self._base_cooldown = config.base_cooldown_seconds
            self._max_cooldown = config.max_cooldown_seconds
            self._amber_similarity_ratio = config.amber_similarity_ratio
            self._amber_velocity_ratio = config.amber_velocity_ratio
            self._amber_decay = config.amber_decay_seconds
            self._red_decay = config.red_decay_seconds
            self._critical_decay = config.critical_decay_seconds
            self._critical_trip_window = config.critical_trip_window_seconds
            self._critical_trip_count = config.critical_trip_count
        else:
            self._velocity_threshold = velocity_threshold
            self._velocity_window = velocity_window_seconds
            self._similarity_threshold = similarity_threshold
            self._similarity_min_events = similarity_min_events
            self._base_cooldown = base_cooldown_seconds
            self._max_cooldown = max_cooldown_seconds
            # AD-506a: Zone parameters
            self._amber_similarity_ratio = amber_similarity_ratio
            self._amber_velocity_ratio = amber_velocity_ratio
            self._amber_decay = amber_decay_seconds
            self._red_decay = red_decay_seconds
            self._critical_decay = critical_decay_seconds
            self._critical_trip_window = critical_trip_window_seconds
            self._critical_trip_count = critical_trip_count
        self._agents: dict[str, AgentBreakerState] = {}
        self._trip_reasons: dict[str, str] = {}  # AD-495: per-agent trip reason

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
        infrastructure_degraded: bool = False,  # AD-576
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
            infrastructure_degraded=infrastructure_degraded,  # AD-576
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

    def _compute_signals(self, agent_id: str) -> dict:
        """Analyze recent events and return signal strengths.

        Returns dict with:
            velocity_count: int — events in window
            velocity_ratio: float — fraction of velocity threshold
            similarity_ratio: float — fraction of similar pairs (0.0-1.0)
            velocity_fired: bool — velocity threshold exceeded
            similarity_fired: bool — similarity threshold exceeded
            reason: str — human-readable trip reason
        """
        state = self._get_state(agent_id)
        now = time.monotonic()

        velocity_fired = False
        similarity_fired = False
        reason = ""

        # --- Signal 1: Velocity (event burst) ---
        window_start = now - self._velocity_window
        recent = [e for e in state.events if e.timestamp >= window_start]
        # AD-576: Exclude infrastructure-correlated events from cognitive signal computation
        recent_cognitive = [e for e in recent if not e.infrastructure_degraded]
        velocity_count = len(recent_cognitive)
        velocity_ratio = velocity_count / self._velocity_threshold if self._velocity_threshold > 0 else 0.0

        if velocity_count >= self._velocity_threshold:
            velocity_fired = True
            reason = f"velocity ({velocity_count} events in {self._velocity_window:.0f}s)"

        # --- Signal 2: Similarity (content rumination) ---
        similarity_ratio = 0.0
        if len(recent_cognitive) >= self._similarity_min_events:
            fingerprints = [e.content_fingerprint for e in recent_cognitive if e.content_fingerprint]
            if len(fingerprints) >= self._similarity_min_events:
                similar_pairs = 0
                total_pairs = 0
                for j in range(len(fingerprints)):
                    for k in range(j + 1, len(fingerprints)):
                        total_pairs += 1
                        sim = jaccard_similarity(fingerprints[j], fingerprints[k])
                        if sim >= self._similarity_threshold:
                            similar_pairs += 1
                if total_pairs > 0:
                    similarity_ratio = similar_pairs / total_pairs
                    if similarity_ratio >= 0.5:
                        similarity_fired = True
                        if velocity_fired:
                            reason += f" + rumination ({similar_pairs}/{total_pairs} pairs)"
                        else:
                            reason = f"rumination ({similar_pairs}/{total_pairs} pairs above {self._similarity_threshold} threshold)"

        signals = {
            "velocity_count": velocity_count,
            "velocity_ratio": velocity_ratio,
            "similarity_ratio": similarity_ratio,
            "velocity_fired": velocity_fired,
            "similarity_fired": similarity_fired,
            "reason": reason,
        }

        # Cache signals on state for get_status() access
        state.last_signals = signals
        return signals

    def _update_zone(self, agent_id: str, signals: dict, tripped: bool) -> tuple[CognitiveZone, CognitiveZone]:
        """Update the agent's cognitive zone based on signals. Returns (old_zone, new_zone)."""
        state = self._get_state(agent_id)
        now = time.monotonic()
        old_zone = state.zone

        if tripped:
            # Record trip timestamp for critical window tracking
            state.trip_timestamps.append(now)
            # Prune old timestamps outside critical window
            cutoff = now - self._critical_trip_window
            state.trip_timestamps = [t for t in state.trip_timestamps if t >= cutoff]

            # Check for critical: enough trips in window
            if len(state.trip_timestamps) >= self._critical_trip_count:
                new_zone = CognitiveZone.CRITICAL
            else:
                new_zone = CognitiveZone.RED
        else:
            # Not tripped — check for amber signals or decay
            amber_signals = (
                signals.get("similarity_ratio", 0.0) > self._amber_similarity_ratio
                or signals.get("velocity_ratio", 0.0) > self._amber_velocity_ratio
            )

            if amber_signals and state.zone in (CognitiveZone.GREEN, CognitiveZone.AMBER):
                new_zone = CognitiveZone.AMBER
            elif state.zone == CognitiveZone.GREEN:
                new_zone = CognitiveZone.GREEN
            else:
                # Decay logic — check if enough time has passed
                elapsed = now - state.zone_entered_at
                if state.zone == CognitiveZone.CRITICAL and elapsed >= self._critical_decay:
                    new_zone = CognitiveZone.RED
                elif state.zone == CognitiveZone.RED and elapsed >= self._red_decay:
                    new_zone = CognitiveZone.AMBER
                elif state.zone == CognitiveZone.AMBER and elapsed >= self._amber_decay and not amber_signals:
                    new_zone = CognitiveZone.GREEN
                else:
                    new_zone = state.zone  # No change

        if new_zone != old_zone:
            state.zone = new_zone
            state.zone_entered_at = now
            state.zone_history.append((new_zone.value, now))
            # Cap zone_history at 20 entries
            if len(state.zone_history) > 20:
                state.zone_history = state.zone_history[-20:]
            # AD-506b: Cache transition for recovery detection
            state.last_zone_transition = (old_zone.value, new_zone.value)
            logger.info(
                "AD-506a: Zone transition %s -> %s for %s",
                old_zone.value, new_zone.value, agent_id,
            )
        else:
            state.last_zone_transition = None

        return old_zone, new_zone

    def check_and_trip(self, agent_id: str) -> bool:
        """Analyze recent events and trip breaker if rumination detected.

        Call this AFTER a proactive think completes. Returns True if breaker
        tripped (so caller can take recovery actions).

        Detection signals (any one is sufficient):
        1. Velocity: >N events in M-minute window
        2. Similarity: >threshold Jaccard overlap across recent events
        """
        state = self._get_state(agent_id)

        # Compute signals (extracted for zone reuse)
        signals = self._compute_signals(agent_id)
        tripped = signals["velocity_fired"] or signals["similarity_fired"]

        if tripped:
            # AD-495: Record canonical trip reason for event enrichment
            if signals["velocity_fired"] and signals["similarity_fired"]:
                self._trip_reasons[agent_id] = "velocity+rumination"
            elif signals["similarity_fired"]:
                self._trip_reasons[agent_id] = "rumination"
            else:
                self._trip_reasons[agent_id] = "velocity"
            self._trip(agent_id, signals["reason"])

        # AD-506a: Update zone based on signals
        self._update_zone(agent_id, signals, tripped)

        if tripped:
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
            "trip_reason": self._trip_reasons.get(agent_id, "unknown"),  # AD-495
            # AD-506a: Zone information
            "zone": state.zone.value,
            "zone_entered_at": state.zone_entered_at,
            "zone_history": [(z, t) for z, t in state.zone_history[-5:]],
            "similarity_ratio": state.last_signals.get("similarity_ratio", 0.0),
            "velocity_ratio": state.last_signals.get("velocity_ratio", 0.0),
        }

    def get_zone(self, agent_id: str) -> str:
        """Return current cognitive zone for an agent."""
        return self._get_state(agent_id).zone.value

    def get_last_zone_transition(self, agent_id: str) -> tuple[str, str] | None:
        """Return (old_zone, new_zone) from the most recent check, or None if no change."""
        return self._get_state(agent_id).last_zone_transition

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
        self._trip_reasons.pop(agent_id, None)

    def reset_all(self) -> None:
        """Reset all breaker states."""
        self._agents.clear()
        self._trip_reasons.clear()
