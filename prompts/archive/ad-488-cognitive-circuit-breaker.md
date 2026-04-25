# AD-488: Cognitive Circuit Breaker — Metacognitive Loop Detection

**Priority:** High
**Scope:** 2 new source files, 2 modified source files, 1 new test file
**Estimated tests:** 15–18

## Context

Agents get stuck in recursive metacognitive loops: thinking about what they were thinking, observing their own observations, ruminating on rumination. The overnight Instance 5 sea trial (2026-03-27) provided direct evidence:

- **Pulse** (Diagnostician) self-diagnosed "recursive metacognitive processing" and proposed an "observation quarantine protocol." Accumulated **837 episodes in 5 minutes** before BF-048 fixed the rate limiter to fail-closed.
- **Medical agents** (Ogawa, Selar, Remedy) consistently show episode flooding and recursive loops, while Security does not — the problem is **trait-dependent**.
- **Sage** (Counselor) independently analyzed: *"Medical agents are probably cycling through differential diagnoses... the perfectionist streak that makes them excellent doctors becomes a cognitive trap."*

Current guardrails are **reactive symptom mitigation** — rate limiters (BF-039: 20 episodes/hr), similarity gates (BF-032/062: Jaccard word+bigram), cold-start dampening (3x cooldown for 10 min), self-post filters. None detect the **underlying metacognitive loop** or intervene cognitively.

Human brains solve this via attention shifting, fatigue signals, and social interruption. AD-488 implements the AI equivalent.

---

## Existing Infrastructure (DO NOT duplicate)

These guardrails already work. AD-488 operates at a **different layer** — detecting cognitive spirals and intervening before the downstream throttles fire:

| Guardrail | Location | What it does |
|---|---|---|
| Episode rate limit (20/hr) | `episodic.py:215-235` | Caps storage — symptom mitigation |
| Episode content dedup (Jaccard 0.8) | `episodic.py:237-261` | Prevents identical episodes — not paraphrases |
| Proactive post similarity (Jaccard+bigram 0.5) | `proactive.py:563-623` | Suppresses similar Ward Room posts |
| Cold-start dampening (3x cooldown) | `proactive.py:158-160` | Slows all agents for 10 minutes |
| Self-post filter (BF-032) | `proactive.py:464` | Excludes own posts from context |
| Ward Room loop prevention (5 layers) | `runtime.py:3194-3392` | Thread depth caps, per-round limits |
| `should_store()` selective encoding | `episodic.py:115-168` | Filters what becomes an episode |
| `[NO_RESPONSE]` suppression | `proactive.py:243`, `runtime.py:3370` | Drops empty responses |

---

## Architecture

AD-488 introduces a lightweight `CognitiveCircuitBreaker` that monitors per-agent cognitive event patterns and intervenes when loops are detected. It lives alongside the proactive loop (not inside it) and is consulted before each proactive think.

### Four Components:

1. **Event Tracker** — Records cognitive events (proactive thinks, Ward Room posts, episode stores) per agent with timestamps and content fingerprints. In-memory ring buffer, not persisted.

2. **Rumination Detector** — Analyzes the event buffer for loop signatures: high event density + high content similarity within a sliding window. Three signals:
   - **Velocity**: >N events in M minutes (raw burst)
   - **Similarity**: >80% Jaccard overlap across recent events (paraphrase loop)
   - **Self-reference depth**: Agent references its own prior output (meta-loop)

3. **Circuit Breaker State Machine** — Per-agent state: `CLOSED` (normal) → `OPEN` (tripped, agent on cooldown) → `HALF_OPEN` (probe single think to test recovery). Standard circuit breaker pattern.

4. **Recovery Actions** — When tripped: forced cooldown (configurable, default 15 min), Counselor notification via bridge alert, agent's next proactive context includes a "shift attention" directive, proactive frequency halved for the recovery period.

---

## Implementation

### File 1: NEW — `src/probos/cognitive/circuit_breaker.py`

```python
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
```

---

### File 2: MODIFY — `src/probos/proactive.py`

#### 2a. Import the circuit breaker

At line 14 (after the `IntentMessage` import), add:

```python
from probos.cognitive.circuit_breaker import CognitiveCircuitBreaker
```

#### 2b. Add circuit breaker to `__init__`

In `ProactiveCognitiveLoop.__init__()` (after line 53, after `self._duty_tracker`), add:

```python
self._circuit_breaker = CognitiveCircuitBreaker()
```

#### 2c. Add accessor for runtime wiring

After the `set_config` method (around line 60), add:

```python
@property
def circuit_breaker(self) -> CognitiveCircuitBreaker:
    """Expose circuit breaker for runtime wiring and API access."""
    return self._circuit_breaker
```

#### 2d. Add circuit breaker gate in `_run_cycle`

In `_run_cycle()`, AFTER the cooldown gate (after line 162, `if time.monotonic() - last < cooldown: continue`) and BEFORE the ACM activation check (line 164), add:

```python
            # AD-488: Circuit breaker gate — skip agents in cognitive cooldown
            if not self._circuit_breaker.should_allow_think(agent.id):
                breaker_status = self._circuit_breaker.get_status(agent.id)
                logger.debug(
                    "AD-488: %s circuit breaker OPEN (trip #%d, cooldown %.0fs remaining)",
                    getattr(agent, 'callsign', agent.agent_type),
                    breaker_status['trip_count'],
                    breaker_status['cooldown_seconds'] - (time.monotonic() - breaker_status['tripped_at']),
                )
                continue
```

#### 2e. Add attention redirect to proactive context

In `_gather_context()`, find where the context parts are assembled (the `context_parts` list). After the standing orders / duty context but before the final return, add:

```python
        # AD-488: Attention redirect after circuit breaker recovery
        redirect = self._circuit_breaker.get_attention_redirect(agent.id)
        if redirect:
            context_parts.append(redirect)
```

Find the appropriate insertion point — it should be near the end of `_gather_context()` so the redirect is the last thing the agent reads.

#### 2f. Record events and check breaker after think

In `_think_for_agent()`, AFTER the proactive think succeeds and the text is processed (after the Ward Room post, after action extraction, near the end of the method), add:

```python
        # AD-488: Record cognitive event and check for rumination
        self._circuit_breaker.record_event(
            agent.id,
            "proactive_think",
            text[:500] if text else "",
        )
        if self._circuit_breaker.check_and_trip(agent.id):
            # Breaker tripped — fire bridge alert for Counselor awareness
            if self._on_event:
                callsign = getattr(agent, 'callsign', agent.agent_type)
                self._on_event({
                    "type": "bridge_alert",
                    "source": "circuit_breaker",
                    "severity": "warning",
                    "title": f"Circuit Breaker: {callsign}",
                    "detail": (
                        f"{callsign}'s cognitive circuit breaker has activated "
                        f"(trip #{self._circuit_breaker.get_status(agent.id)['trip_count']}). "
                        "Repetitive thought patterns detected. "
                        "Forced cooldown applied — not punishment, health protection."
                    ),
                })
```

Also record events for `[NO_RESPONSE]` outcomes (at the no-response handling block, around line 257). Add after the no-response episode storage:

```python
        # AD-488: Record no-response as event (rapid no-responses can also indicate loops)
        self._circuit_breaker.record_event(agent.id, "no_response", "")
```

**Note:** Empty content fingerprint means no-responses won't trigger the similarity signal, but they WILL count toward the velocity signal. Rapid `[NO_RESPONSE]` bursts (thinking a lot but saying nothing) are also a loop symptom.

#### 2g. Record Ward Room post events

In the section where text is posted to the Ward Room (around lines 295-330), after the successful post, add:

```python
            # AD-488: Record Ward Room post as cognitive event
            self._circuit_breaker.record_event(
                agent.id,
                "ward_room_post",
                text[:500] if text else "",
            )
```

---

### File 3: MODIFY — `src/probos/api.py`

Add a diagnostic endpoint for circuit breaker status. Place after the existing `/api/system/services` endpoint:

```python
@app.get("/api/system/circuit-breakers")
async def system_circuit_breakers() -> dict[str, Any]:
    """AD-488: Circuit breaker status for all tracked agents."""
    if not hasattr(runtime, 'proactive_loop') or not runtime.proactive_loop:
        return {"breakers": []}
    cb = runtime.proactive_loop.circuit_breaker
    statuses = cb.get_all_statuses()
    # Enrich with callsigns
    for s in statuses:
        agent = runtime.registry.get(s["agent_id"])
        if agent:
            s["callsign"] = getattr(agent, 'callsign', agent.agent_type)
    return {"breakers": statuses}
```

---

### File 4: MODIFY — (optional) `src/probos/runtime.py`

No modifications required. The circuit breaker lives inside the ProactiveCognitiveLoop and is created automatically. The API accesses it via `runtime.proactive_loop.circuit_breaker`.

If the runtime needs to reset circuit breaker state on ship reset, add a call in the reset path — but since the ProactiveCognitiveLoop is recreated on restart, this happens automatically.

---

## What's NOT in this AD (by design)

1. **Correlation IDs / trace threading → AD-492** — Cross-layer correlation IDs are a significant cross-cutting concern (touching `types.py`, `cognitive_agent.py`, `episodic.py`, `ward_room.py`, `proactive.py`, `journal.py`). The circuit breaker works without them — it uses per-agent event buffers instead of trace chains. AD-492 adds chain depth as a third detection signal.

2. **Novelty Gate Enhancement → AD-493** — Requires an experiential baseline from AD-486 (Holodeck Birth Chamber) Phase 2. Can't build without that prerequisite. The circuit breaker compensates by using velocity + similarity signals instead of novelty scoring.

3. **Trait-adaptive thresholds → AD-494** — Medical agents with perfectionist traits are more vulnerable. AD-494 reads Big Five personality scores and adjusts thresholds per agent. For now, the escalating cooldown naturally adapts — agents that trip repeatedly get longer cooldowns.

4. **Counselor automated assessment → AD-495** — The circuit breaker fires a bridge alert. AD-495 auto-triggers a `counselor_assess` intent for the affected agent, closing the loop between mechanical detection and clinical assessment.

---

## Tests

Create `tests/test_circuit_breaker.py`:

### Core circuit breaker tests:

1. **test_breaker_starts_closed** — New breaker state is CLOSED. `should_allow_think()` returns True.

2. **test_velocity_trips_breaker** — Record N events within the velocity window. Call `check_and_trip()`. Verify breaker state is OPEN.

3. **test_velocity_below_threshold_no_trip** — Record N-1 events within the velocity window. Verify breaker does NOT trip.

4. **test_similarity_trips_breaker** — Record events with >80% Jaccard content overlap (same words, minor variations). Verify breaker trips on similarity signal.

5. **test_dissimilar_events_no_trip** — Record events with genuinely different content. Verify breaker does NOT trip.

6. **test_open_blocks_think** — Trip the breaker. Call `should_allow_think()`. Returns False.

7. **test_cooldown_transitions_to_half_open** — Trip the breaker with short cooldown. Advance time past cooldown. `should_allow_think()` returns True (HALF_OPEN).

8. **test_half_open_recovery_closes** — In HALF_OPEN state, call `check_and_trip()` with no signals firing. Verify state transitions to CLOSED.

9. **test_half_open_re_trips** — In HALF_OPEN state, call `check_and_trip()` with signals still firing. Verify state goes back to OPEN with escalated cooldown.

10. **test_escalating_cooldown** — Trip 3 times. Verify cooldown doubles each time: base → 2x → 4x. Verify max cap is respected.

11. **test_attention_redirect_after_trip** — Trip breaker, advance past cooldown. `get_attention_redirect()` returns the redirect prompt.

12. **test_no_redirect_when_never_tripped** — Fresh agent. `get_attention_redirect()` returns None.

13. **test_reset_agent_clears_state** — Trip breaker, reset agent. Verify state is gone.

### Integration with proactive loop:

14. **test_proactive_skips_open_breaker** — Mock a ProactiveCognitiveLoop with an agent whose breaker is OPEN. Verify `_run_cycle` skips that agent.

15. **test_bridge_alert_on_trip** — Mock `on_event`. Trigger a breaker trip in `_think_for_agent`. Verify bridge alert event with correct severity and detail.

16. **test_no_response_counts_toward_velocity** — Record several empty no-response events. Verify they contribute to velocity signal but not similarity.

17. **test_context_includes_redirect_after_recovery** — After breaker recovery, call `_gather_context()`. Verify the attention redirect string appears in context parts.

### API endpoint test:

18. **test_circuit_breaker_api_returns_statuses** — Call `GET /api/system/circuit-breakers`. Verify response includes breaker states with callsign enrichment.

---

## Verification

After building, manually verify:

1. **Normal operation** — Start ProbOS, wait 2-3 proactive cycles. Verify all agents think normally. `GET /api/system/circuit-breakers` shows all CLOSED with 0 trip counts.

2. **Breaker trip** — Leave instance running overnight. If any agent enters a thought loop, check logs for `AD-488: Circuit breaker TRIPPED` warnings. Check Bridge panel for the alert. Verify the agent's proactive thinks are blocked for the cooldown duration.

3. **Recovery** — After cooldown, agent should resume thinking with the attention redirect prompt in their context. Verify the redirect appears in their next proactive thought quality.

4. **Regression** — `uv run pytest tests/test_circuit_breaker.py -v` — all 18 pass. `uv run pytest` — full suite green.

---

## Important

- Do NOT modify `episodic.py` — the circuit breaker is upstream of episode storage, not inside it
- Do NOT modify `runtime.py` — circuit breaker lives inside ProactiveCognitiveLoop
- Do NOT modify `ward_room.py` — Ward Room loop prevention is a separate system
- Do NOT add correlation IDs — that's a separate cross-cutting AD
- Do NOT add trait-adaptive thresholds yet — the escalating cooldown adapts naturally
- Do NOT remove any existing guardrails (BF-039, BF-032, BF-062) — the circuit breaker is an additional layer, not a replacement
- Keep the circuit breaker **in-memory only** — no persistence needed. Reset on restart is correct behavior (new timeline = clean slate)
- Run targeted tests: `uv run pytest tests/test_circuit_breaker.py -x -v`
