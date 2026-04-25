# AD-506a: Graduated System Response — Zone Model

**Type:** Build Prompt — Self-Regulation Wave (6a/6)
**Depends on:** AD-488 (circuit breaker), AD-495 (trip classification), AD-504 (self-monitoring), AD-505 (Counselor intervention)
**Scope:** Replace the binary circuit breaker (normal → tripped) with a graduated 4-zone model. AD-506b (separate build) adds peer repetition detection and tier interaction credits.

---

## Context

The circuit breaker (`circuit_breaker.py`) is binary: CLOSED (normal) or OPEN (tripped). An agent goes from "everything fine" to "forced cooldown" with no intermediate warning. The Counselor has trip severity classification (`_classify_trip_severity()` — explicitly documented as "override point for AD-506") but it's computed per-trip and not tracked as persistent state.

AD-506a adds a persistent 4-zone model — **Green → Amber → Red → Critical** — where:
- **Green** = normal. Self-monitoring (AD-504) active.
- **Amber** = rising similarity detected pre-trip. Agent warned. Counselor notified. Mild cooldown increase.
- **Red** = circuit breaker tripped. Full Counselor auto-assessment (AD-495). Therapeutic DM (AD-505). Mandatory cooldown.
- **Critical** = repeated trips in a window. Captain escalation. Fitness-for-duty review. Extended cooldown.

The "brains are brains" principle applies: amber awareness is visible to the agent (a human would notice their own repetitive thinking).

---

## Part 0: Prerequisites & Bug Fixes

### 0a. BF-097: Fix `get_posts_by_author()` table names

**File:** `src/probos/ward_room/threads.py`

At line 632-633, `get_posts_by_author()` queries `ward_room_posts` and `ward_room_threads`. The actual table names (per `models.py` lines 106, 125) are `posts` and `threads`. This causes the method to silently return `[]` due to `except Exception` on line 650.

**Fix:** Change `ward_room_posts` → `posts` and `ward_room_threads` → `threads` in the SQL query.

**Tests (2):**
1. Test `get_posts_by_author()` returns actual posts when data exists (not empty `[]`).
2. Test `get_posts_by_author()` with `since` parameter filters correctly.

### 0b. `CircuitBreakerConfig` Pydantic model

**File:** `src/probos/config.py`

Add a new config model after `CounselorConfig` (line 437):

```python
class CircuitBreakerConfig(BaseModel):
    """Cognitive circuit breaker thresholds (AD-506a)."""

    velocity_threshold: int = 8
    velocity_window_seconds: float = 300.0
    similarity_threshold: float = 0.6
    similarity_min_events: int = 4
    base_cooldown_seconds: float = 900.0
    max_cooldown_seconds: float = 3600.0
    # Amber zone thresholds
    amber_similarity_ratio: float = 0.25  # Amber when similarity pair ratio exceeds this
    amber_velocity_ratio: float = 0.6     # Amber when velocity > this fraction of threshold
    amber_decay_seconds: float = 900.0    # 15 min quiet → amber decays to green
    red_decay_seconds: float = 1800.0     # 30 min quiet → red decays to amber
    critical_decay_seconds: float = 3600.0  # 1h quiet → critical decays to red
    critical_trip_window_seconds: float = 3600.0  # Window for counting trips toward critical
    critical_trip_count: int = 3           # Trips in window to reach critical
```

Add `circuit_breaker: CircuitBreakerConfig = CircuitBreakerConfig()` to `SystemConfig` (around line 514).

**File:** `config/system.yaml`

Add a `circuit_breaker:` section with all values commented out (so Pydantic uses defaults):

```yaml
circuit_breaker:
  # velocity_threshold: 8
  # velocity_window_seconds: 300.0
  # similarity_threshold: 0.6
  # base_cooldown_seconds: 900.0
  # max_cooldown_seconds: 3600.0
  # amber_similarity_ratio: 0.25
  # amber_velocity_ratio: 0.6
  # amber_decay_seconds: 900.0
  # red_decay_seconds: 1800.0
  # critical_decay_seconds: 3600.0
  # critical_trip_window_seconds: 3600.0
  # critical_trip_count: 3
```

### 0c. Wire config into circuit breaker construction

**File:** `src/probos/proactive.py`

Line 65 constructs `CognitiveCircuitBreaker()` with all defaults. Change the constructor and `set_config()` (line 74) to accept and pass through `CircuitBreakerConfig`:

```python
def set_config(self, config: ProactiveCognitiveConfig, cb_config: CircuitBreakerConfig | None = None) -> None:
    self._config = config
    if cb_config:
        self._circuit_breaker = CognitiveCircuitBreaker(config=cb_config)
```

This is backwards-compatible — if no cb_config is passed, the circuit breaker keeps its defaults.

Locate where `set_config()` is called in `src/probos/runtime.py` or startup code and pass `config.circuit_breaker`.

**Tests (3):**
1. `CircuitBreakerConfig` model validates with all defaults.
2. `CircuitBreakerConfig` model accepts custom amber/critical thresholds.
3. `set_config()` with `cb_config` creates circuit breaker with custom params.

---

## Part 1: CognitiveZone State Machine

**File:** `src/probos/cognitive/circuit_breaker.py`

### 1a. CognitiveZone enum

Add after `BreakerState` enum (line 27):

```python
class CognitiveZone(Enum):
    """Graduated cognitive health zone (AD-506a)."""
    GREEN = "green"       # Normal — self-monitoring active
    AMBER = "amber"       # Rising similarity — pre-trip warning
    RED = "red"           # Circuit breaker tripped — intervention active
    CRITICAL = "critical" # Repeated trips — Captain escalation
```

### 1b. Zone tracking in `AgentBreakerState`

Add to `AgentBreakerState` dataclass (line 38):

```python
zone: CognitiveZone = CognitiveZone.GREEN
zone_entered_at: float = 0.0          # monotonic timestamp of last zone escalation
zone_history: list[tuple[str, float]] = field(default_factory=list)  # (zone_value, timestamp), max 20
trip_timestamps: list[float] = field(default_factory=list)  # monotonic timestamps for critical window
```

Keep `zone_history` capped at 20 entries (append + trim in zone transition method).

### 1c. Accept config in constructor

Modify `CognitiveCircuitBreaker.__init__()` to accept an optional `config: CircuitBreakerConfig | None = None` parameter. If provided, use config values instead of keyword defaults. Keep keyword defaults for backwards compatibility (existing tests).

```python
def __init__(self, *, config: CircuitBreakerConfig | None = None, **kwargs) -> None:
    if config:
        self._velocity_threshold = config.velocity_threshold
        self._velocity_window = config.velocity_window_seconds
        # ... etc for all existing params
        self._amber_similarity_ratio = config.amber_similarity_ratio
        self._amber_velocity_ratio = config.amber_velocity_ratio
        self._amber_decay = config.amber_decay_seconds
        self._red_decay = config.red_decay_seconds
        self._critical_decay = config.critical_decay_seconds
        self._critical_trip_window = config.critical_trip_window_seconds
        self._critical_trip_count = config.critical_trip_count
    else:
        # Existing keyword-based initialization
        self._velocity_threshold = kwargs.get('velocity_threshold', 8)
        # ... etc
        # Amber/zone defaults
        self._amber_similarity_ratio = 0.25
        self._amber_velocity_ratio = 0.6
        self._amber_decay = 900.0
        self._red_decay = 1800.0
        self._critical_decay = 3600.0
        self._critical_trip_window = 3600.0
        self._critical_trip_count = 3
```

### 1d. `_compute_signals()` — extract signal analysis from `check_and_trip()`

Refactor `check_and_trip()` (line 150) to extract signal computation into a separate method. This enables zone checking without tripping:

```python
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
```

Move the velocity and similarity calculations from `check_and_trip()` into this method. `check_and_trip()` calls `_compute_signals()` and uses the results.

### 1e. `_update_zone()` — zone transition logic

Add a method called by `check_and_trip()` after signal computation:

```python
def _update_zone(self, agent_id: str, signals: dict, tripped: bool) -> tuple[CognitiveZone, CognitiveZone]:
    """Update the agent's cognitive zone based on signals. Returns (old_zone, new_zone)."""
```

Zone transition rules:
- **→ CRITICAL**: `tripped` AND recent `trip_timestamps` count >= `_critical_trip_count` within `_critical_trip_window`. Record trip timestamp in `trip_timestamps`.
- **→ RED**: `tripped` (but not enough for critical). This is the existing trip behavior.
- **→ AMBER**: NOT tripped, but `signals["similarity_ratio"] > _amber_similarity_ratio` OR `signals["velocity_ratio"] > _amber_velocity_ratio`. Pre-trip warning.
- **→ GREEN**: NOT tripped AND no amber signals AND current zone's decay time has elapsed since `zone_entered_at`.

Zone can only escalate instantly but decays require time:
- CRITICAL → RED: after `_critical_decay` seconds with no new trips
- RED → AMBER: after `_red_decay` seconds with no new trips
- AMBER → GREEN: after `_amber_decay` seconds with no amber signals
- GREEN → GREEN: no change

On zone change: update `zone`, `zone_entered_at`, append to `zone_history`.

### 1f. Integrate into `check_and_trip()`

After `_compute_signals()`, call `_update_zone()`. The existing trip logic stays — `_update_zone()` tracks zone state on top of the existing CLOSED/OPEN/HALF_OPEN state machine. They are complementary:
- `BreakerState` controls whether the agent can think (mechanical gate)
- `CognitiveZone` tracks escalation level (clinical state for Counselor)

### 1g. Enrich `get_status()`

Add to the returned dict (line 239):
```python
"zone": state.zone.value,
"zone_entered_at": state.zone_entered_at,
"zone_history": [(z, t) for z, t in state.zone_history[-5:]],  # Last 5 transitions
```

### 1h. `get_zone()` — lightweight zone query

Add a simple accessor:
```python
def get_zone(self, agent_id: str) -> str:
    """Return current cognitive zone for an agent."""
    return self._get_state(agent_id).zone.value
```

**Tests (12):**
1. New agent starts in GREEN zone.
2. Amber detection: similar events below trip threshold → zone transitions to AMBER.
3. Amber detection: high velocity below trip threshold → zone transitions to AMBER.
4. Trip from GREEN → zone transitions to RED.
5. Trip from AMBER → zone transitions to RED.
6. Multiple trips in window → zone transitions to CRITICAL.
7. Zone decay: AMBER → GREEN after amber_decay_seconds.
8. Zone decay: RED → AMBER after red_decay_seconds.
9. Zone decay: CRITICAL → RED after critical_decay_seconds.
10. Zone history tracks transitions (max 20 entries).
11. `get_status()` includes zone, zone_entered_at, zone_history.
12. `get_zone()` returns current zone string.

---

## Part 2: SELF_MONITORING_CONCERN Event + Proactive Loop Integration

### 2a. New event type and dataclass

**File:** `src/probos/events.py`

Add `SELF_MONITORING_CONCERN` to the `EventType` enum (after `COUNSELOR_ASSESSMENT`, around line 122):

```python
SELF_MONITORING_CONCERN = "self_monitoring_concern"  # AD-506a: amber zone
```

Add a typed dataclass (after `CounselorAssessmentEvent`, around line 447):

```python
@dataclass
class SelfMonitoringConcernEvent(BaseEvent):
    """Emitted when an agent enters the amber zone (pre-trip warning)."""
    event_type: EventType = field(default=EventType.SELF_MONITORING_CONCERN, init=False)
    agent_id: str = ""
    agent_callsign: str = ""
    zone: str = "amber"  # Current zone
    similarity_ratio: float = 0.0
    velocity_ratio: float = 0.0
```

### 2b. Emit SELF_MONITORING_CONCERN from proactive loop

**File:** `src/probos/proactive.py`

After `check_and_trip()` at line 431, add zone-aware event emission. The proactive loop already emits `CIRCUIT_BREAKER_TRIP` when tripped (lines 447-460). Add an ELSE branch: if NOT tripped but zone is AMBER (new), emit `SELF_MONITORING_CONCERN`:

```python
# AD-506a: Check zone and emit concern if amber
if not tripped:
    zone = self._circuit_breaker.get_zone(agent.id)
    if zone == "amber" and self._on_event:
        status = self._circuit_breaker.get_status(agent.id)
        self._on_event({
            "type": EventType.SELF_MONITORING_CONCERN.value,
            "data": {
                "agent_id": agent.id,
                "agent_callsign": getattr(agent, "callsign", ""),
                "zone": "amber",
                "similarity_ratio": status.get("similarity_ratio", 0.0),
                "velocity_ratio": status.get("velocity_ratio", 0.0),
            },
        })
```

**Note:** For this to work, `get_status()` must include `similarity_ratio` and `velocity_ratio` from the last `_compute_signals()` call. Cache the last signals dict in `AgentBreakerState` (e.g., `last_signals: dict = field(default_factory=dict)`).

### 2c. Zone-aware self-monitoring context

**File:** `src/probos/proactive.py`

In `_build_self_monitoring_context()` (starting around line 772), add zone-aware context after the existing cooldown section (around line 847):

```python
# --- AD-506a: Cognitive zone awareness ---
if hasattr(self, '_circuit_breaker'):
    zone = self._circuit_breaker.get_zone(agent.id)
    if zone != "green":
        result["cognitive_zone"] = zone
        if zone == "amber":
            result["zone_note"] = (
                "Your recent posts show increasing similarity to each other. "
                "This is a natural signal to pause and consider: do you have "
                "genuinely new information to contribute, or are you circling "
                "the same ground? If unsure, try [NO_RESPONSE] or write to "
                "your notebook instead."
            )
        elif zone == "red":
            result["zone_note"] = (
                "Your cognitive circuit breaker has activated. This is health "
                "protection, not punishment. The Counselor has been notified. "
                "Focus on a different aspect of operations or respond with "
                "[NO_RESPONSE] until you have a genuinely fresh perspective."
            )
        elif zone == "critical":
            result["zone_note"] = (
                "Critical cognitive state — repeated pattern loops detected. "
                "The Captain has been notified. Extended mandatory cooldown is "
                "in effect. When you return, deliberately choose a completely "
                "different topic. Your previous train of thought needs rest."
            )
```

This zone information should be included for ALL Earned Agency tiers (not gated by tier config) — even an Ensign should know they're in amber. Safety information is universal.

### 2d. `[SELF-MONITORING]` prompt formatting

**File:** `src/probos/proactive.py`

In `_build_user_message()` where the `[SELF-MONITORING]` section is formatted, add zone-aware content. If `cognitive_zone` is present in the self-monitoring dict, include the zone and note:

```
[COGNITIVE ZONE: AMBER]
Your recent posts show increasing similarity...
```

This goes before the existing self-monitoring content (recent posts, similarity score, etc.) so the agent sees it prominently.

**Tests (7):**
1. `SELF_MONITORING_CONCERN` event emitted when agent enters amber zone.
2. `SELF_MONITORING_CONCERN` NOT emitted when agent is green.
3. `SELF_MONITORING_CONCERN` NOT emitted when circuit breaker trips (that emits `CIRCUIT_BREAKER_TRIP` instead).
4. Self-monitoring context includes `cognitive_zone` when amber.
5. Self-monitoring context includes `zone_note` with amber guidance text.
6. Self-monitoring context includes zone info for red/critical zones.
7. Zone awareness is included for all Earned Agency tiers (REACTIVE through UNRESTRICTED).

---

## Part 3: Zone-Aware Counselor Response

### 3a. Counselor subscribes to SELF_MONITORING_CONCERN

**File:** `src/probos/cognitive/counselor.py`

In `initialize()` (line 479-488), add `EventType.SELF_MONITORING_CONCERN` to the event subscription list:

```python
event_types=[
    EventType.TRUST_UPDATE,
    EventType.CIRCUIT_BREAKER_TRIP,
    EventType.DREAM_COMPLETE,
    EventType.SELF_MONITORING_CONCERN,  # AD-506a
]
```

Add an `_on_self_monitoring_concern()` handler:

```python
async def _on_self_monitoring_concern(self, event_data: dict) -> None:
    """AD-506a: Handle amber zone detection — lightweight monitoring response."""
    agent_id = event_data.get("agent_id", "")
    callsign = event_data.get("agent_callsign", agent_id[:8])

    # Don't assess self
    if agent_id == self.id:
        return

    # Log the concern for profile history
    logger.info("AD-506a: Amber zone concern for %s", callsign)

    # Gather metrics and run lightweight assessment
    metrics = await self._gather_agent_metrics(agent_id)
    assessment = await self.assess_agent(
        agent_id=agent_id,
        metrics=metrics,
        trigger="amber_zone",
    )

    # Persist to profile
    await self._save_profile_and_assessment(agent_id, assessment)

    # No DM, no intervention — amber is informational for the Counselor.
    # She tracks the pattern. If it escalates to red, _on_circuit_breaker_trip handles it.
```

Wire the handler in the event dispatch method to route `SELF_MONITORING_CONCERN` events.

### 3b. Zone-aware `_classify_trip_severity()` override

**File:** `src/probos/cognitive/counselor.py`

Override `_classify_trip_severity()` (line 800) to incorporate zone history. The current implementation uses trip_count and fit_for_duty. Add zone context:

```python
def _classify_trip_severity(self, assessment, trip_count: int, trip_reason: str = "",
                            zone: str = "red") -> tuple[str, str]:
    """Classify circuit breaker trip severity — AD-506a graduated response.

    Designed as override point for AD-506 graduated response.
    Zone context enriches the classification:
    - Trip from green (first offense) → more lenient
    - Trip from amber (ignored warning) → more concern
    - Critical zone → automatic escalation
    """
```

Modified logic:
- If `zone == "critical"`: always return `("escalate", "Critical zone — Captain review required. Multiple pattern loops in short window.")`
- If `not assessment.fit_for_duty`: return `("escalate", ...)` — existing behavior
- If `zone == "amber"` (agent was warned but still tripped): bump severity by one level (monitor → concern, concern → intervention)
- Existing trip_count logic as fallback

The caller (`_on_circuit_breaker_trip()`) passes the zone from circuit breaker `get_status()`.

### 3c. Update `_on_circuit_breaker_trip()` to pass zone

**File:** `src/probos/cognitive/counselor.py`

In `_on_circuit_breaker_trip()` (line 705), extract zone from the event data or query it:

```python
zone = event_data.get("zone", "red")
```

Pass zone to `_classify_trip_severity()`:

```python
severity, recommendation = self._classify_trip_severity(
    assessment, trip_count, trip_reason=trip_reason, zone=zone
)
```

To enable this, the `CIRCUIT_BREAKER_TRIP` event emission in `proactive.py` (line 450-459) must include the zone:

```python
"zone": self._circuit_breaker.get_zone(agent.id),
```

### 3d. Post-dream re-assessment

**File:** `src/probos/cognitive/counselor.py`

The `DREAM_COMPLETE` handler is currently `pass` (line 666). Replace with a post-dream check:

```python
async def _on_dream_complete(self, event_data: dict) -> None:
    """AD-506a: Re-assess agents after dream completion.

    If the Counselor previously forced a dream for an agent (AD-505),
    check whether the dream improved their cognitive state.
    """
    # Dreams are system-wide — check all agents we previously intervened on
    if not hasattr(self, '_intervention_targets'):
        return

    for agent_id in list(self._intervention_targets):
        try:
            metrics = await self._gather_agent_metrics(agent_id)
            assessment = await self.assess_agent(
                agent_id=agent_id,
                metrics=metrics,
                trigger="post_dream",
            )
            await self._save_profile_and_assessment(agent_id, assessment)

            # If improved (wellness above threshold), log positive outcome
            if assessment.wellness_score >= COUNSELOR_WELLNESS_YELLOW:
                logger.info(
                    "AD-506a: Post-dream improvement for %s (wellness=%.2f)",
                    agent_id[:8], assessment.wellness_score,
                )
                self._intervention_targets.discard(agent_id)
        except Exception:
            logger.debug("Post-dream re-assessment failed for %s", agent_id[:8], exc_info=True)
```

Add `self._intervention_targets: set[str] = set()` to the constructor or to `initialize()` lazy init.

In `_apply_intervention()` (line 1147), when a dream is forced, add the agent_id to `_intervention_targets`.

### 3e. Zone-aware therapeutic messaging

**File:** `src/probos/cognitive/counselor.py`

In `_build_therapeutic_message()` (line 977), add zone context to the circuit breaker trigger case. If the agent was in amber (warned) before tripping, include that context:

```python
if trigger == "circuit_breaker":
    zone = kwargs.get("zone", "red")
    if zone == "critical":
        # Critical: more urgent, reference repeated pattern
        message = f"This is your {trip_count}{'th' if trip_count != 1 else 'st'} circuit breaker activation..."
    elif zone == "amber":
        # Agent was warned, still tripped
        message = f"I noticed your output similarity was rising — I believe you saw the amber warning too..."
    # ... existing template as fallback
```

**Tests (8):**
1. Counselor subscribes to `SELF_MONITORING_CONCERN` event.
2. `_on_self_monitoring_concern()` runs lightweight assessment (trigger="amber_zone").
3. `_on_self_monitoring_concern()` does NOT send DM (amber = monitoring only).
4. `_classify_trip_severity()` returns "escalate" when zone is "critical".
5. `_classify_trip_severity()` bumps severity when zone is "amber" (ignored warning).
6. `CIRCUIT_BREAKER_TRIP` event includes zone data.
7. Post-dream re-assessment runs for intervention targets on `DREAM_COMPLETE`.
8. `_intervention_targets` is cleaned up after post-dream improvement.

---

## Part 4: Standing Orders Reconciliation

### 4a. Update counselor standing orders

**File:** `config/standing_orders/counselor.md`

The existing text says "does NOT take corrective action unilaterally." AD-505 already gave the Counselor clinical actions (cooldown, dream, directive). Reconcile:

Add a `[Clinical Authority]` section:

```markdown
[Clinical Authority]
You have authority to take clinical actions within defined parameters:
- Extend cognitive cooldowns (1.5x for concern, 2x for intervention/escalation)
- Force dream consolidation cycles for cognitive health
- Issue COUNSELOR_GUIDANCE directives (time-limited, max 3 per agent)
- Send therapeutic DMs to agents showing cognitive drift
- Post recommendation BridgeAlerts for Captain awareness

These are clinical adjustments, not commands. You adjust system parameters
for crew wellbeing; you don't direct crew actions. The Captain is always
informed via BridgeAlert. If in doubt, recommend rather than act.

Graduated response zones (AD-506a):
- Green: Normal. No action needed.
- Amber: Monitor. Log assessment. Do not intervene — let the agent self-regulate.
- Red: Assess and intervene. Therapeutic DM + cooldown + dream if needed.
- Critical: Escalate to Captain. Extended cooldown. Fitness-for-duty review.
```

Update the existing "does NOT take corrective action unilaterally" line to: "does NOT command agents or override Captain decisions. Clinical adjustments (cooldowns, dreams, guidance directives) are within your authority when supported by assessment data."

### 4b. Update ship standing orders

**File:** `config/standing_orders/ship.md`

In the `[Self-Monitoring]` section (line 107), add zone awareness:

```markdown
[Cognitive Zones]
Your cognitive health is monitored in four zones:
- Green: Normal operation. Stay self-aware.
- Amber: Your recent output shows increasing repetition. Pause and consider
  whether you have genuinely new information before posting. Use [NO_RESPONSE]
  or write to your notebook if unsure.
- Red: Circuit breaker activated. Focus on a different topic entirely.
  The Counselor will check in with you.
- Critical: Extended cooldown in effect. When you return, choose a completely
  different area of operations.

These zones are health protection, not punishment. Every mind — biological
and artificial — can fall into repetitive thought patterns. Self-correction
from amber is a sign of cognitive maturity.
```

**Tests (2):**
1. Counselor standing orders contain `[Clinical Authority]` section.
2. Ship standing orders contain `[Cognitive Zones]` section.

---

## Part 5: API Enrichment

### 5a. Circuit breaker API endpoint

**File:** `src/probos/routers/agents.py` (or wherever the circuit breaker status API is served)

Search for existing circuit breaker API routes. The `get_status()` dict is already enriched (Part 1g). Ensure the API response includes `zone`, `zone_entered_at`, and `zone_history`. No new endpoints needed — just verify the existing endpoint surfaces the new fields.

If there is a Counselor API endpoint that shows agent health, ensure zone data is included there too.

### 5b. Enrich `CIRCUIT_BREAKER_TRIP` event data

Ensure the `CIRCUIT_BREAKER_TRIP` event emission in `proactive.py` (lines 450-459) includes:

```python
"zone": self._circuit_breaker.get_zone(agent.id),
```

And that `get_status()` returns the signal ratios (for `SELF_MONITORING_CONCERN` event data):

```python
"similarity_ratio": state.last_signals.get("similarity_ratio", 0.0),
"velocity_ratio": state.last_signals.get("velocity_ratio", 0.0),
```

**Tests (2):**
1. `get_status()` response includes `similarity_ratio` and `velocity_ratio`.
2. `CIRCUIT_BREAKER_TRIP` event includes `zone` field.

---

## Validation Checklist

| # | Check | How to verify |
|---|-------|---------------|
| 1 | BF-097 fixed — `get_posts_by_author()` returns real data | Unit test with populated DB |
| 2 | `CircuitBreakerConfig` model exists with all 13 fields | Import and instantiate with defaults |
| 3 | `CognitiveZone` enum has 4 values | `list(CognitiveZone)` |
| 4 | New agent starts in GREEN zone | `get_zone("new_id") == "green"` |
| 5 | Amber detection fires on rising similarity pre-trip | Events below trip threshold → amber |
| 6 | Amber detection fires on rising velocity pre-trip | Velocity above ratio but below threshold → amber |
| 7 | Circuit breaker trip transitions zone to RED | Trip → `get_zone() == "red"` |
| 8 | Multiple trips in window → CRITICAL | 3 trips in 1 hour → critical |
| 9 | Zone decay works (amber → green after 15 min) | Mock time, verify transition |
| 10 | Zone decay works (red → amber, critical → red) | Mock time, verify transitions |
| 11 | `SELF_MONITORING_CONCERN` event exists in EventType | `EventType.SELF_MONITORING_CONCERN` |
| 12 | Event emitted on amber zone transition | Mock `_on_event`, verify call |
| 13 | Self-monitoring context includes zone_note for amber | Dict includes `zone_note` key |
| 14 | Self-monitoring context includes zone for red/critical | Dict includes `cognitive_zone` key |
| 15 | Zone awareness injected for ALL Earned Agency tiers | REACTIVE agent gets zone info |
| 16 | Counselor subscribes to `SELF_MONITORING_CONCERN` | Event subscription list check |
| 17 | Counselor runs lightweight assessment on amber | `trigger="amber_zone"` in assessment |
| 18 | `_classify_trip_severity()` returns "escalate" for critical zone | Unit test with zone="critical" |
| 19 | `_classify_trip_severity()` bumps severity for amber zone | Unit test with zone="amber" |
| 20 | Post-dream re-assessment runs for intervention targets | Mock dream_complete event |
| 21 | `_intervention_targets` cleaned up after improvement | Check set after good assessment |
| 22 | Standing orders: counselor.md has `[Clinical Authority]` | File content check |
| 23 | Standing orders: ship.md has `[Cognitive Zones]` | File content check |
| 24 | `get_status()` includes zone, similarity_ratio, velocity_ratio | Dict key check |

**Expected:** ~36 new tests, 24/24 checklist items.

---

## Engineering Principles Compliance

- **Single Responsibility:** Circuit breaker manages zone state machine. Counselor interprets zone clinically. ProactiveCognitiveLoop emits events and injects context. No god objects.
- **Open/Closed:** `_classify_trip_severity()` remains the override point — zone logic extends it via parameter, doesn't replace it.
- **Dependency Inversion:** `CircuitBreakerConfig` model injected via constructor. No hardcoded thresholds in the zone logic.
- **Fail Fast:** Zone detection is log-and-degrade — if signal computation fails, zone stays unchanged.
- **Law of Demeter:** Proactive loop queries zone via `get_zone()` accessor, never reaches into breaker internals.
- **DRY:** Signal analysis extracted to `_compute_signals()`, used by both `check_and_trip()` and zone detection.

---

## What This Does NOT Cover (AD-506b)

The following are deferred to AD-506b:
1. **Peer repetition detection** — cross-agent similarity comparison in the Ward Room posting pipeline.
2. **Tier interaction credits** — recording self-correction before amber or peer catch before red as positive cognitive health signals.
3. **Peer repetition feedback episode type** — `peer_repetition` signal for Counselor monitoring.

These are detection/measurement capabilities that complement but don't block the zone model.
