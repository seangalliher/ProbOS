# AD-576: LLM Unavailability Awareness — EPS Power Brownout Protocol

## Type
Enhancement (Graceful Degradation / Westworld Principle Compliance)

## Priority
High — direct crew cognitive distress observed in production

## Prerequisites
- BF-069 (LLM health tracking) — COMPLETE
- AD-504 (agent self-monitoring) — COMPLETE
- AD-506a (graduated zones) — COMPLETE

## Problem

When the LLM backend (Copilot Proxy at `127.0.0.1:8080`) goes down, crew agents have **zero awareness** of their infrastructure dependencies. They experience empty proactive cycles and misattribute them as personal cognitive health issues — e.g., Cortez self-diagnosing "repetitive cognitive pattern" and escalating to CMO. This is a **Westworld Principle violation**: agents should know what they depend on.

**Five gaps in the current infrastructure:**

| # | Gap | Location |
|---|-----|----------|
| 1 | **Silent empty responses** — `complete()` returns `LLMResponse(content="", error=...)` when all tiers fail. `_decide_via_llm()` never checks `response.error`. Agents process empty output as if they had nothing to say. | `llm_client.py:223`, `cognitive_agent.py:1325` |
| 2 | **No agent-facing infrastructure context** — `_llm_failure_count` is tracked in `proactive.py:168` but never injected into agent context. Agents can't distinguish "I had nothing to say" from "the LLM was down." | `proactive.py:451-567` |
| 3 | **Self-monitoring misattribution** — Empty/failed cycles can trigger circuit breaker → Counselor intervention → unnecessary clinical response for what is really an infrastructure issue. | `circuit_breaker.py`, `counselor.py` |
| 4 | **`LLM_HEALTH_CHANGED` event defined but never emitted** — Dead event type since BF-069 added it. No reactive event subscription pathway for LLM status transitions. | `events.py:135` |
| 5 | **No recovery notification** — BridgeAlerts exist for `llm_offline`/`llm_degraded` (BF-069 via VitalsMonitor) but there is no recovery alert. Crew never learns the LLM is back. | `bridge_alerts.py:308` |

**Starship metaphor:** EPS Power Brownout. When the ship's power fluctuates, the Ship's Computer announces the event. The crew doesn't assume their consoles are broken — they wait for restoration. On recovery: "EPS power restored, all sections nominal."

### Also Fixed: BF-116 — Dead Proactive Context (circuit_breaker_redirect) + AD-567g Completion (orientation_supplement)

`circuit_breaker_redirect` is gathered at `proactive.py:1081` (`context["circuit_breaker_redirect"] = redirect`) but never consumed in `cognitive_agent.py:_build_user_message()`. Dead code — remove.

`orientation_supplement` is gathered at `proactive.py:785` but also never consumed in `_build_user_message()`. However, this is NOT dead code — it's an **incomplete AD-567g implementation** (built same day). The gathering side is correct; the rendering block in `_build_user_message()` was never wired. Fix by adding the consumer, not removing the producer. The supplement provides diminishing cognitive grounding for young agents ("ORIENTATION ACTIVE: Ground observations in evidence...") that fades after the orientation window expires.

### Also Fixed: BF-117 — Convergence Bridge Alert Delivery Broken

`proactive.py:_emit_convergence_bridge_alert()` (line 2105) and `_emit_divergence_bridge_alert()` (line 2119) use:
```python
ba_svc = getattr(self._runtime, '_bridge_alerts', None)
deliver_fn = getattr(self._runtime, '_deliver_bridge_alert', None)
```

But runtime has `bridge_alerts` (public, no underscore) and has no `_deliver_bridge_alert` attribute at all. Both methods silently no-op. Fix attribute names to match reality: `self._runtime.bridge_alerts` and use `self._runtime.ward_room_router.deliver_bridge_alert(alert)` (the pattern runtime.py itself uses, e.g., line 1601).

## Architecture

### Deliverables

1. **LLM status state machine** in `ProactiveCognitiveLoop` with transition event emission
2. **Bridge Alert on transitions** — degraded, offline, and recovery
3. **Infrastructure context injection** into `_gather_context()` → rendered in `_build_user_message()`
4. **Circuit breaker infrastructure-correlation tagging** — skip infra-caused events in signal computation
5. **Counselor infrastructure gating** — suppress clinical intervention during LLM brownout
6. **`LlmHealthChangedEvent` typed dataclass** — wire the dead `LLM_HEALTH_CHANGED` event
7. **BF-116 fix** — remove dead `circuit_breaker_redirect` context path + wire missing `orientation_supplement` rendering in `_build_user_message()` to complete AD-567g
8. **BF-117 fix** — correct convergence/divergence bridge alert delivery attribute names
9. **Tests** — 25+ new tests

### Non-goals

- No retry/backoff changes (existing tier fallback is sufficient)
- No automatic alert condition escalation (YELLOW/RED is a Captain decision)
- No changes to `VitalsMonitor` (it already detects LLM health — this AD wires the proactive loop properly)
- No changes to `llm_client.py` (health tracking is sufficient; the gap is consumption)
- No agent behavioral changes (agents still attempt proactive cycles — they just know why they fail)

## Implementation

### File 1: `src/probos/events.py`

#### Change A: Add `LlmHealthChangedEvent` dataclass

Insert after `PeerRepetitionDetectedEvent` (currently at line ~528):

```python
@dataclass
class LlmHealthChangedEvent(BaseEvent):
    """AD-576: Emitted on LLM backend status transitions."""
    event_type: EventType = field(default=EventType.LLM_HEALTH_CHANGED, init=False)
    old_status: str = ""       # "operational", "degraded", "offline"
    new_status: str = ""       # "operational", "degraded", "offline"
    consecutive_failures: int = 0
    downtime_seconds: float = 0.0  # Time since first failure (0 on recovery)
```

**Signature verification:**
- `BaseEvent` — confirmed at `events.py`, has `event_type: EventType`, `timestamp: float`, `to_dict() -> dict`
- `EventType.LLM_HEALTH_CHANGED` — confirmed at `events.py:135`

### File 2: `src/probos/proactive.py`

#### Change A: Add LLM status state machine

In `__init__` (line 151 area), after `self._llm_failure_count: int = 0` (line 168), add:

```python
self._llm_status: str = "operational"  # AD-576: "operational" | "degraded" | "offline"
self._llm_offline_since: float = 0.0   # AD-576: monotonic timestamp of first failure
```

Remove the dead variable at line 169:
```python
# DELETE: self._llm_failure_streak: int = 0  # BF-069: consecutive cycles with failure
```

#### Change B: Add `_update_llm_status()` method

Add as a new private method on `ProactiveCognitiveLoop` (after the existing `llm_failure_count` property, line ~2367):

```python
async def _update_llm_status(self, failure: bool) -> None:
    """AD-576: Update LLM status state machine and emit events on transitions.

    State transitions:
        operational -> degraded (failure_count >= 1)
        degraded -> offline (failure_count >= 3, matches _UNREACHABLE_THRESHOLD)
        offline -> degraded (first success after offline)
        degraded -> operational (success resets counter to 0)
    """
    old_status = self._llm_status

    if failure:
        if self._llm_failure_count >= 3:
            new_status = "offline"
        else:
            new_status = "degraded"
        if self._llm_offline_since == 0.0:
            self._llm_offline_since = time.monotonic()
    else:
        new_status = "operational"
        self._llm_offline_since = 0.0

    if old_status == new_status:
        return

    self._llm_status = new_status

    # Emit typed event on transition
    if self._on_event:
        from probos.events import LlmHealthChangedEvent
        downtime = (time.monotonic() - self._llm_offline_since) if self._llm_offline_since else 0.0
        try:
            event = LlmHealthChangedEvent(
                old_status=old_status,
                new_status=new_status,
                consecutive_failures=self._llm_failure_count,
                downtime_seconds=downtime if new_status == "operational" else 0.0,
            )
            self._on_event(event.to_dict())
        except Exception:
            logger.debug("AD-576: LLM health event emission failed", exc_info=True)

    # Emit Bridge Alerts on transition
    await self._emit_llm_status_bridge_alert(old_status, new_status)
```

**Signature verification:**
- `self._on_event: Callable[[dict], Any] | None` — confirmed at `proactive.py:150`
- `self._llm_failure_count: int` — confirmed at `proactive.py:168`

#### Change C: Add `_emit_llm_status_bridge_alert()` method

Add directly after `_update_llm_status()`:

```python
async def _emit_llm_status_bridge_alert(self, old_status: str, new_status: str) -> None:
    """AD-576: Emit Bridge Alert on LLM status transitions."""
    rt = self._runtime
    if not rt or not hasattr(rt, 'bridge_alerts') or not rt.bridge_alerts:
        return
    if not hasattr(rt, 'ward_room_router') or not rt.ward_room_router:
        return

    from probos.bridge_alerts import AlertSeverity, BridgeAlert

    downtime_str = ""
    if new_status == "operational" and self._llm_offline_since:
        elapsed = time.monotonic() - self._llm_offline_since
        minutes = int(elapsed // 60)
        seconds = int(elapsed % 60)
        downtime_str = f" ({minutes}m {seconds}s total downtime)" if minutes else f" ({seconds}s total downtime)"

    alert_map = {
        "offline": BridgeAlert(
            id=f"llm_status_{int(time.time())}",
            severity=AlertSeverity.ALERT,
            source="proactive_loop",
            alert_type="llm_offline",
            title="Communications Array Offline",
            detail=(
                "The LLM backend is unreachable. All crew cognitive functions are"
                " suspended. Proactive cycles will continue but produce no output"
                " until the array is restored. This is an infrastructure issue —"
                " not a crew performance concern."
            ),
            department=None,
            dedup_key="llm_offline",  # Same key as BF-069 VitalsMonitor for dedup
        ),
        "degraded": BridgeAlert(
            id=f"llm_status_{int(time.time())}",
            severity=AlertSeverity.ADVISORY,
            source="proactive_loop",
            alert_type="llm_degraded",
            title="Communications Array Degraded",
            detail=(
                "The LLM backend is experiencing intermittent connectivity."
                f" {self._llm_failure_count} consecutive failures."
                " Crew cognition may be temporarily impaired."
                " This is an infrastructure issue — not a crew performance concern."
            ),
            department=None,
            dedup_key="llm_degraded",  # Aligned with BF-069 pattern
        ),
        "operational": BridgeAlert(
            id=f"llm_status_{int(time.time())}",
            severity=AlertSeverity.INFO,
            source="proactive_loop",
            alert_type="llm_restored",
            title="Communications Array Restored",
            detail=(
                "LLM backend connectivity has been re-established."
                " All crew cognitive functions resuming normal operations."
                + downtime_str
            ),
            department=None,
            dedup_key="llm_restored",  # New — no BF-069 equivalent (recovery is new)
        ),
    }

    alert = alert_map.get(new_status)
    if not alert:
        return

    try:
        await rt.ward_room_router.deliver_bridge_alert(alert)
    except Exception:
        logger.debug("AD-576: LLM status bridge alert delivery failed", exc_info=True)
```

**Signature verification:**
- `rt.bridge_alerts` — confirmed at `runtime.py:385` (public attribute, type `BridgeAlertService | None`)
- `rt.ward_room_router` — confirmed at `runtime.py` (public attribute)
- `rt.ward_room_router.deliver_bridge_alert(alert)` — confirmed at `ward_room_router.py:547`
- `BridgeAlert(id, severity, source, alert_type, title, detail, department, dedup_key)` — confirmed at `bridge_alerts.py:29-42`
- `AlertSeverity.ALERT / ADVISORY / INFO` — confirmed at `bridge_alerts.py:22-25`

#### Change D: Wire status machine into `_think_for_agent()` failure/success paths

At the **failure path** (line ~451-464), after `self._llm_failure_count += 1` (line 452), add:

```python
            # AD-576: Update LLM status state machine
            await self._update_llm_status(failure=True)
```

Insert this line AFTER `self._llm_failure_count += 1` (line 452) and BEFORE the `# BF-069: Log failure details` block (line 453).

At the **success path** (line ~567), after `self._llm_failure_count = 0` (line 567), add:

```python
        # AD-576: Update LLM status on recovery
        if self._llm_status != "operational":
            await self._update_llm_status(failure=False)
```

The `if` guard prevents calling `_update_llm_status()` on every success — only on recovery transitions.

#### Change E: Inject infrastructure context into `_gather_context()`

In `_gather_context()`, AFTER the self-monitoring block (line ~1092) and BEFORE the Night Orders block (line ~1094), add:

```python
        # AD-576: Infrastructure awareness context
        if self._llm_status != "operational":
            context["infrastructure_status"] = {
                "llm_status": self._llm_status,
                "consecutive_failures": self._llm_failure_count,
                "message": (
                    "The ship's communications array (LLM backend) is currently"
                    f" {self._llm_status}. If you receive an empty or degraded"
                    " response, this is an infrastructure issue — not a reflection"
                    " of your cognitive state. Do not self-diagnose based on empty"
                    " cycles during this period."
                ),
            }
```

#### Change F: Tag circuit breaker events as infrastructure-correlated

At the **failure path** in `_think_for_agent()` (line ~451-464), the method currently returns at line 464 without recording a circuit breaker event. This is correct — no change needed here. Failed LLM calls don't reach `record_event()`.

However, at the `[NO_RESPONSE]` path (line ~529), the circuit breaker DOES record:
```python
self._circuit_breaker.record_event(agent.id, "no_response", "")
```

This is correct behavior — a `[NO_RESPONSE]` means the LLM succeeded but the agent chose silence. DO NOT tag these as infrastructure-correlated.

The tagging instead needs to happen for the **success path events** (lines 570-579) during **partial degradation** — when some agents succeed and some fail within the same cycle. During partial degradation (`self._llm_status == "degraded"`), agents who DO succeed might produce output that appears repetitive because the degraded backend is giving inconsistent/truncated responses. Add the infrastructure flag to the `record_event` calls:

At lines 570-579 (the circuit breaker recording block after successful post), modify to:

```python
        # AD-488: Record cognitive event and check for rumination
        self._circuit_breaker.record_event(
            agent.id,
            "proactive_think",
            response_text[:500] if response_text else "",
            infrastructure_degraded=(self._llm_status != "operational"),  # AD-576
        )
        # AD-488: Record Ward Room post as cognitive event
        self._circuit_breaker.record_event(
            agent.id,
            "ward_room_post",
            response_text[:500] if response_text else "",
            infrastructure_degraded=(self._llm_status != "operational"),  # AD-576
        )
```

#### Change G: Remove dead `circuit_breaker_redirect` context path (BF-116)

**Remove `circuit_breaker_redirect`** at line 1078-1081. Delete the block:

```python
# AD-488: Attention redirect after circuit breaker recovery
redirect = self._circuit_breaker.get_attention_redirect(agent.id)
if redirect:
    context["circuit_breaker_redirect"] = redirect
```

**Do NOT remove the `get_attention_redirect()` method from `circuit_breaker.py`** — only remove the dead call site in `_gather_context()`.

**Update existing test:** `tests/test_circuit_breaker.py` lines 382-384 assert `"circuit_breaker_redirect" in context`. This test must be updated: change the assertion to verify `"circuit_breaker_redirect" NOT in context` (since BF-116 removes it). The test name is in the class near line 370 — update the test docstring to reference BF-116.

**Do NOT remove the `orientation_supplement` block** (lines 755-787). This is a valid AD-567g data path — the fix is to add the rendering consumer (see File 4, Change B below).

#### Change H: Fix convergence/divergence bridge alert delivery (BF-117)

In `_emit_convergence_bridge_alert()` (line ~2105), replace:

```python
ba_svc = getattr(self._runtime, '_bridge_alerts', None)
deliver_fn = getattr(self._runtime, '_deliver_bridge_alert', None)
if not ba_svc or not deliver_fn:
    return

alerts = ba_svc.check_realtime_convergence(conv_result)
for alert in alerts:
    try:
        await deliver_fn(alert)
    except Exception:
        logger.debug("AD-554: Bridge alert delivery failed", exc_info=True)
```

With:

```python
rt = self._runtime
if not rt or not hasattr(rt, 'bridge_alerts') or not rt.bridge_alerts:
    return
if not hasattr(rt, 'ward_room_router') or not rt.ward_room_router:
    return

alerts = rt.bridge_alerts.check_realtime_convergence(conv_result)
for alert in alerts:
    try:
        await rt.ward_room_router.deliver_bridge_alert(alert)
    except Exception:
        logger.debug("AD-554: Bridge alert delivery failed", exc_info=True)
```

Apply the **identical pattern** to `_emit_divergence_bridge_alert()` (line ~2117).

### File 3: `src/probos/cognitive/circuit_breaker.py`

#### Change A: Add `infrastructure_degraded` field to `CognitiveEvent`

At `CognitiveEvent` dataclass (line 39-45), add:

```python
@dataclass
class CognitiveEvent:
    """A recorded cognitive event for loop analysis."""
    timestamp: float
    event_type: str          # "proactive_think", "ward_room_post", "episode_store"
    content_fingerprint: set  # Word set for Jaccard comparison
    agent_id: str
    infrastructure_degraded: bool = False  # AD-576: event during LLM brownout
```

#### Change B: Accept `infrastructure_degraded` parameter in `record_event()`

At `record_event()` (line 139), add parameter:

```python
def record_event(
    self,
    agent_id: str,
    event_type: str,
    content: str,
    infrastructure_degraded: bool = False,  # AD-576
) -> None:
```

And pass it through to the `CognitiveEvent` constructor (currently at line ~151):

```python
event = CognitiveEvent(
    timestamp=time.monotonic(),
    event_type=event_type,
    content_fingerprint=set(content.lower().split()) if content else set(),
    agent_id=agent_id,
    infrastructure_degraded=infrastructure_degraded,  # AD-576
)
```

#### Change C: Filter infrastructure-correlated events in `_compute_signals()`

In `_compute_signals()` (line 191), after filtering `recent` events by time window (line 211), add a filter:

```python
# AD-576: Exclude infrastructure-correlated events from cognitive signal computation
recent_cognitive = [e for e in recent if not e.infrastructure_degraded]
```

Then use `recent_cognitive` instead of `recent` for both velocity and similarity calculations. Specifically:
- Line 212: `velocity_count = len(recent_cognitive)` (was `len(recent)`)
- Line 221: `if len(recent_cognitive) >= self._similarity_min_events:` (was `len(recent)`)
- Line 222: `fingerprints = [e.content_fingerprint for e in recent_cognitive if e.content_fingerprint]` (was `recent`)

**IMPORTANT:** Keep `recent` (unfiltered) for the state events deque — all events are stored. Only the signal computation filters them out.

### File 4: `src/probos/cognitive/cognitive_agent.py`

#### Change A: Render infrastructure status in `_build_user_message()`

In the `proactive_think` branch, AFTER the `system_note` block (lines 2111-2114) and BEFORE the `ontology` block (lines 2117-2132), add:

```python
        # AD-576: Infrastructure awareness
        infra_status = context_parts.get("infrastructure_status")
        if infra_status:
            llm_status = infra_status.get("llm_status", "unknown")
            pt_parts.append(f"[INFRASTRUCTURE NOTE: Communications array {llm_status}]")
            pt_parts.append(infra_status.get("message", ""))
            pt_parts.append("")
```

This insertion point is chosen because infrastructure awareness is more fundamental than identity grounding — the agent should know about power conditions before detailed cognitive context.

#### Change B: Render `orientation_supplement` in `_build_user_message()` (AD-567g completion)

In the `proactive_think` branch, AFTER the `ontology` block (lines 2117-2132) and BEFORE the `skill_profile` block (lines 2135-2138), add:

```python
        # AD-567g: Diminishing orientation supplement for young agents
        orientation_supp = context_parts.get("orientation_supplement")
        if orientation_supp:
            pt_parts.append(orientation_supp)
            pt_parts.append("")
```

This placement follows ontology identity grounding — the agent first learns WHO it is (ontology), then receives cognitive grounding guidance (orientation supplement: "ground observations in evidence, distinguish episodic from parametric"). The supplement is a plain string returned by `OrientationService.render_proactive_orientation()` that diminishes over time (full → brief → minimal → absent after orientation window expires).

**Signature verification:**
- `context_parts.get("orientation_supplement")` — key set at `proactive.py:785`, type `str` (return value of `render_proactive_orientation()`)
- Rendering pattern matches all other `context_parts` consumers in this method (`.get()`, truthy check, append, blank line separator)

### File 5: `src/probos/cognitive/counselor.py`

#### Change A: Gate clinical intervention during LLM brownout

In `_on_self_monitoring_concern()` (line 861), after the early-return guard for self-referencing concerns (line 863-864), add:

```python
        # AD-576: Suppress clinical intervention during infrastructure brownout
        if data.get("infrastructure_correlated"):
            logger.info(
                "AD-576: Suppressing self-monitoring concern for %s — infrastructure-correlated",
                callsign,
            )
            return
```

**How the flag gets there:** The `SELF_MONITORING_CONCERN` event is emitted as a raw dict at `proactive.py:617-626` (inside the `else` branch after circuit breaker check, when zone is "amber"). The emission looks like:

```python
# Line 617-626 (existing):
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

Add the `infrastructure_correlated` flag to the `"data"` dict at line ~624:

```python
# AD-576 addition inside the "data" dict:
"infrastructure_correlated": self._llm_status != "operational",
```

So the modified block becomes:

```python
self._on_event({
    "type": EventType.SELF_MONITORING_CONCERN.value,
    "data": {
        "agent_id": agent.id,
        "agent_callsign": getattr(agent, "callsign", ""),
        "zone": "amber",
        "similarity_ratio": status.get("similarity_ratio", 0.0),
        "velocity_ratio": status.get("velocity_ratio", 0.0),
        "infrastructure_correlated": self._llm_status != "operational",  # AD-576
    },
})
```

### File 6: Tests — `tests/test_ad576_llm_unavailability.py`

Create a new test file with the following test cases:

```
=== LLM Status State Machine ===

1. test_initial_llm_status_is_operational
   - New ProactiveCognitiveLoop, assert _llm_status == "operational"

2. test_status_transition_operational_to_degraded
   - Set _llm_failure_count = 1
   - Call _update_llm_status(failure=True)
   - Assert _llm_status == "degraded"

3. test_status_transition_degraded_to_offline
   - Set _llm_failure_count = 3
   - Call _update_llm_status(failure=True)
   - Assert _llm_status == "offline"

4. test_status_transition_offline_to_operational
   - Set _llm_status = "offline", _llm_offline_since = time.monotonic() - 60
   - Set _llm_failure_count = 0
   - Call _update_llm_status(failure=False)
   - Assert _llm_status == "operational"
   - Assert _llm_offline_since == 0.0

5. test_no_event_when_status_unchanged
   - Set _llm_status = "degraded", _llm_failure_count = 2
   - Call _update_llm_status(failure=True) (stays degraded)
   - Assert _on_event was NOT called

6. test_event_emitted_on_transition
   - Mock _on_event, set _llm_failure_count = 1
   - Call _update_llm_status(failure=True)
   - Assert _on_event called with dict containing type="llm_health_changed", old_status="operational", new_status="degraded"

=== Bridge Alerts ===

7. test_bridge_alert_on_offline
   - Mock runtime with bridge_alerts and ward_room_router
   - Trigger operational → offline transition
   - Assert deliver_bridge_alert called with alert_type="llm_offline", severity=ALERT

8. test_bridge_alert_on_degraded
   - Trigger operational → degraded transition
   - Assert deliver_bridge_alert called with alert_type="llm_degraded", severity=ADVISORY

9. test_bridge_alert_on_recovery
   - Trigger offline → operational transition
   - Assert deliver_bridge_alert called with alert_type="llm_restored", severity=INFO
   - Assert detail contains downtime duration

10. test_no_bridge_alert_when_no_runtime
    - Set _runtime = None
    - Trigger transition
    - Assert no exception raised

=== Infrastructure Context Injection ===

11. test_gather_context_includes_infrastructure_when_degraded
    - Set _llm_status = "degraded", _llm_failure_count = 2
    - Call _gather_context() with mock agent
    - Assert context["infrastructure_status"]["llm_status"] == "degraded"

12. test_gather_context_excludes_infrastructure_when_operational
    - Set _llm_status = "operational"
    - Call _gather_context() with mock agent
    - Assert "infrastructure_status" NOT in context

13. test_build_user_message_renders_infrastructure_note
    - Build proactive_think observation with context_parts["infrastructure_status"]
    - Call _build_user_message()
    - Assert result contains "INFRASTRUCTURE NOTE" and "communications array"

14. test_build_user_message_no_infrastructure_note_when_healthy
    - Build proactive_think observation without infrastructure_status
    - Call _build_user_message()
    - Assert "INFRASTRUCTURE NOTE" NOT in result

=== Circuit Breaker Infrastructure Filtering ===

15. test_cognitive_event_has_infrastructure_flag_default_false
    - Create CognitiveEvent without infrastructure_degraded
    - Assert infrastructure_degraded is False

16. test_record_event_passes_infrastructure_flag
    - Call record_event(..., infrastructure_degraded=True)
    - Assert stored event has infrastructure_degraded=True

17. test_compute_signals_excludes_infrastructure_events
    - Record 5 events: 3 with infrastructure_degraded=True, 2 normal
    - Call _compute_signals()
    - Assert velocity_count == 2 (only non-infra events counted)

18. test_compute_signals_includes_normal_events_during_brownout
    - Record 4 infrastructure_degraded=True events + 4 normal similar events
    - Assert similarity computation uses only the 4 normal events

19. test_all_infrastructure_events_produces_zero_signals
    - Record 10 events all with infrastructure_degraded=True
    - Call _compute_signals()
    - Assert velocity_count == 0, similarity_ratio == 0.0

=== Counselor Gating ===

20. test_counselor_suppresses_infrastructure_correlated_concern
    - Call _on_self_monitoring_concern({"agent_id": "a1", "infrastructure_correlated": True, ...})
    - Assert method returns without calling assess_agent()

21. test_counselor_processes_non_infrastructure_concern
    - Call _on_self_monitoring_concern({"agent_id": "a1", "infrastructure_correlated": False, ...})
    - Assert assess_agent() IS called

=== BF-116: Dead Context Removal + AD-567g Completion ===

22. test_gather_context_no_circuit_breaker_redirect
    - Call _gather_context()
    - Assert "circuit_breaker_redirect" NOT in returned context dict

23. test_gather_context_includes_orientation_supplement_for_young_agent
    - Set _orientation_service to mock that returns "ORIENTATION ACTIVE: ..."
    - Agent with _birth_timestamp < orientation_window_seconds ago
    - Call _gather_context()
    - Assert "orientation_supplement" IS in returned context dict

24. test_build_user_message_renders_orientation_supplement
    - Build proactive_think observation with context_parts["orientation_supplement"] = "ORIENTATION: Ground claims in evidence."
    - Call _build_user_message()
    - Assert result contains "ORIENTATION: Ground claims in evidence."

25. test_build_user_message_no_orientation_supplement_when_absent
    - Build proactive_think observation without orientation_supplement in context_parts
    - Call _build_user_message()
    - Assert "ORIENTATION" NOT in result (at least not from this path)

=== BF-117: Convergence Bridge Alert Fix ===

26. test_convergence_bridge_alert_uses_correct_attributes
    - Mock runtime with public bridge_alerts + ward_room_router
    - Call _emit_convergence_bridge_alert() with mock conv_result
    - Assert rt.bridge_alerts.check_realtime_convergence was called
    - Assert rt.ward_room_router.deliver_bridge_alert was called

27. test_divergence_bridge_alert_uses_correct_attributes
    - Same pattern for _emit_divergence_bridge_alert()

=== Integration ===

28. test_failure_cycle_full_flow
    - Simulate 3 consecutive failed _think_for_agent() calls
    - Assert: _llm_failure_count == 3
    - Assert: _llm_status == "offline"
    - Assert: LLM_HEALTH_CHANGED event emitted twice (operational→degraded, degraded→offline)
    - Assert: bridge alert delivery called twice

29. test_recovery_cycle_full_flow
    - Start with _llm_status == "offline"
    - Simulate successful _think_for_agent() call
    - Assert: _llm_failure_count == 0
    - Assert: _llm_status == "operational"
    - Assert: recovery LLM_HEALTH_CHANGED event emitted
    - Assert: recovery bridge alert with downtime in detail
```

## Files Modified

| File | Change |
|------|--------|
| `src/probos/events.py` | Add `LlmHealthChangedEvent` dataclass |
| `src/probos/proactive.py` | LLM status state machine, `_update_llm_status()`, `_emit_llm_status_bridge_alert()`, infrastructure context in `_gather_context()`, circuit breaker tagging, BF-116 dead context removal, BF-117 convergence alert fix |
| `src/probos/cognitive/cognitive_agent.py` | Render `infrastructure_status` in `_build_user_message()` |
| `src/probos/cognitive/circuit_breaker.py` | `infrastructure_degraded` field on `CognitiveEvent`, `record_event()` parameter, `_compute_signals()` filtering |
| `src/probos/cognitive/counselor.py` | Infrastructure-correlated concern gating in `_on_self_monitoring_concern()` |
| `tests/test_circuit_breaker.py` | BF-116: Update `circuit_breaker_redirect` assertion (lines 382-384) |

## Files NOT Modified / Created

- **NOT modified:** `src/probos/cognitive/llm_client.py` (health tracking is sufficient)
- **NOT modified:** `src/probos/agents/medical/vitals_monitor.py` (already detects LLM health)
- **NOT modified:** `src/probos/bridge_alerts.py` (existing check_llm_health stays — VitalsMonitor path still valid; new alerts created directly in proactive.py)
- **NOT modified:** `src/probos/ontology/` (no alert condition escalation changes)
- **Created:** `tests/test_ad576_llm_unavailability.py`

## Engineering Principles Compliance

| Principle | Compliance |
|-----------|-----------|
| **SRP** | `_update_llm_status()` has one job — state machine transitions. `_emit_llm_status_bridge_alert()` has one job — alert delivery. Infrastructure context injection is a one-block addition to `_gather_context()`. |
| **OCP** | Extends `_gather_context()` and `_build_user_message()` via additive insertion. Circuit breaker extended via new field + filtered computation. No modification of existing control flow. |
| **LSP** | `CognitiveEvent` extended with optional field (default `False`) — all existing callers continue working without changes. `record_event()` new parameter has default — backward compatible. |
| **ISP** | No new interfaces. Infrastructure status is a simple dict — consumers read only what they need. |
| **DIP** | Bridge alert delivery uses the existing `deliver_bridge_alert()` abstraction, not direct Ward Room manipulation. Event emission uses the existing `_on_event` callback. |
| **Law of Demeter** | Uses `rt.ward_room_router.deliver_bridge_alert(alert)` — accessing a direct dependency's public method. Same pattern as `runtime.py:1601`. No reaching through private attributes. BF-117 fixes a LoD violation (`_bridge_alerts` → `bridge_alerts`). |
| **Fail Fast** | All new methods wrap external calls in try/except with `logger.debug()` — log-and-degrade tier. Infrastructure context failure doesn't prevent the proactive cycle from proceeding. |
| **Defense in Depth** | Multiple guard layers: `hasattr(rt, 'bridge_alerts')`, `if not rt`, `if not alert`. Alert dedup protects against storm. Circuit breaker filtering protects against false cognitive signals. |
| **DRY** | Reuses existing `BridgeAlert` dataclass, `deliver_bridge_alert()` method, `_on_event` callback, `SelfMonitoringConcernEvent`. No duplication of alert infrastructure. |
| **Cloud-Ready** | No database changes. Pure in-memory state machine. |

## Dependencies
- BF-069 (LLM health tracking) — COMPLETE
- AD-504 (self-monitoring context) — COMPLETE
- AD-506a (graduated cognitive zones) — COMPLETE
- AD-488 (circuit breaker event recording) — COMPLETE

## Deferred
- **AD-576b:** Proactive cycle frequency adjustment during LLM brownout — reduce cycle frequency when LLM is offline to avoid futile cycles. Low priority since cycles are cheap (no LLM tokens consumed on failure).
- **AD-576c:** Counselor post-recovery wellness check — after LLM restoration, Counselor proactively checks agents who experienced extended brownout for any residual cognitive distress. Connects to AD-505 therapeutic framework.
- **AD-576d:** Alert condition suggestion — Ship's Computer suggests YELLOW alert after sustained LLM outage (>15 min). Captain still decides. Connects to Conn authority model.

## Verification
1. Run targeted tests: `pytest tests/test_ad576_llm_unavailability.py -v` — all must pass
2. Run full test suite: `pytest` — zero regressions
3. **Manual validation:** Stop the Copilot Proxy (`127.0.0.1:8080`). Observe:
   - Bridge Alert "Communications Array Degraded" appears in Ward Room within ~2 proactive cycles
   - Bridge Alert "Communications Array Offline" appears after 3 consecutive failures
   - No Counselor clinical interventions triggered
   - Agent self-monitoring zones remain GREEN (no false trips)
   - Restart the proxy → "Communications Array Restored" appears with downtime duration
   - Agents resume normal proactive output
