# AD-495: Counselor Auto-Assessment on Circuit Breaker Trip

## Objective

Upgrade the Counselor's circuit breaker trip handler from a generic assessment to a **trip-aware clinical response** with proper Ward Room posting, escalation logic, and enriched event data. AD-503 built the muscles (event subscriptions, metric gathering, profile persistence). AD-495 makes the circuit breaker → Counselor pipeline clinically meaningful.

**Scope:** 5 changes — enrich event emission, upgrade trip handler, wire Ward Room posting, add escalation classification, fix trigger value. No new services, no new stores, no new agents.

## Engineering Principles

- **SOLID (S):** `_classify_trip_severity()` is a separate method from `_on_circuit_breaker_trip()` — classification logic has one reason to change (escalation thresholds), handler has another (response actions).
- **SOLID (O):** `_classify_trip_severity()` is a method AD-506 can override or extend without modifying the handler.
- **Law of Demeter:** Counselor accesses trip data from the event dict passed to it, not by reaching into the circuit breaker instance.
- **AD-542 (ConnectionFactory):** No new stores. Existing CounselorProfileStore already compliant.
- **BF-090 (no bare swallows):** Every `except` block must log at minimum `logger.debug(...)` with `exc_info=True`.
- **BF-091 (spec=True):** All mocks in tests MUST use `spec=True` or `spec_set=True`.
- **Fail Fast:** Ward Room posting failure is log-and-degrade (assessment still persists + bridge alert still fires). Don't let WR unavailability block the assessment pipeline.

## Part 1: Enrich CircuitBreakerTripEvent Emission

### File: `src/probos/proactive.py`

Find the AD-503 `CIRCUIT_BREAKER_TRIP` emission block (after the `BRIDGE_ALERT` emission in `_think_for_agent()`). Update the emitted data to include `cooldown_seconds` and `trip_reason`:

```python
# AD-503: Emit typed circuit breaker trip event
breaker_status = self._circuit_breaker.get_status(agent.id)
self._on_event({
    "type": EventType.CIRCUIT_BREAKER_TRIP.value,
    "data": {
        "agent_id": agent.id,
        "agent_type": agent.agent_type,
        "callsign": getattr(agent, "callsign", ""),
        "trip_count": breaker_status.get("trip_count", 1),
        "cooldown_seconds": breaker_status.get("cooldown_seconds", 900.0),
        "trip_reason": breaker_status.get("trip_reason", "unknown"),
    },
})
```

### File: `src/probos/cognitive/circuit_breaker.py`

In `check_and_trip()`, when a trip is triggered, record which signal caused it. Add a `trip_reason` field to the state dict returned by `get_status()`:

- If velocity signal tripped: `trip_reason = "velocity"` (too many events in window)
- If similarity signal tripped: `trip_reason = "rumination"` (repetitive content)
- If both: `trip_reason = "velocity+rumination"`

Store `self._trip_reasons[agent_id] = reason` (new dict, same pattern as `self._trip_counts`). Include in `get_status()` return dict.

## Part 2: Upgrade `_on_circuit_breaker_trip()` Handler

### File: `src/probos/cognitive/counselor.py`

Replace the existing thin `_on_circuit_breaker_trip()` with a trip-aware handler:

```python
async def _on_circuit_breaker_trip(self, data: dict[str, Any]) -> None:
    """Handle circuit breaker trip with trip-aware clinical assessment."""
    agent_id = data.get("agent_id", "")
    if not agent_id or agent_id == self.id:
        return

    trip_count = data.get("trip_count", 1)
    cooldown_seconds = data.get("cooldown_seconds", 900.0)
    trip_reason = data.get("trip_reason", "unknown")
    callsign = data.get("callsign", agent_id)

    # Gather current metrics
    metrics = self._gather_agent_metrics(agent_id)

    # Run assessment with circuit_breaker trigger
    assessment = self.assess_agent(
        agent_id,
        current_trust=metrics.get("trust_score", 0.0),
        current_confidence=metrics.get("confidence", 0.0),
        hebbian_avg=metrics.get("hebbian_avg", 0.0),
        success_rate=metrics.get("success_rate", 0.0),
        personality_drift=metrics.get("personality_drift", 0.0),
        trigger="circuit_breaker",
    )

    # Classify severity and enrich assessment
    severity, recommendation = self._classify_trip_severity(
        trip_count, trip_reason, assessment,
    )

    # Add trip-specific concerns
    if trip_count == 1:
        assessment.concerns.append(
            f"First circuit breaker trip (reason: {trip_reason})"
        )
    elif trip_count <= 3:
        assessment.concerns.append(
            f"Repeated circuit breaker trip #{trip_count} (reason: {trip_reason})"
        )
    else:
        assessment.concerns.append(
            f"Frequent circuit breaker trips ({trip_count} total, reason: {trip_reason}) — pattern requires attention"
        )

    # Add trip-specific recommendation
    if recommendation:
        assessment.recommendations.append(recommendation)

    # Add clinical note
    assessment.notes = (
        f"Circuit breaker trip #{trip_count}. "
        f"Reason: {trip_reason}. "
        f"Cooldown: {cooldown_seconds:.0f}s. "
        f"Severity classification: {severity}."
    )

    # Persist
    self._save_profile_and_assessment(agent_id, assessment)

    # Alert bridge (always for circuit breaker trips)
    self._alert_bridge(agent_id, assessment)

    # Post to Ward Room
    await self._post_assessment_to_ward_room(
        agent_id, callsign, assessment, severity, trip_count, trip_reason,
    )

    # Emit counselor assessment event
    if self._emit_event_fn:
        self._emit_event_fn(EventType.COUNSELOR_ASSESSMENT, {
            "agent_id": agent_id,
            "wellness_score": assessment.wellness_score,
            "alert_level": self._cognitive_profiles.get(agent_id, CognitiveProfile()).alert_level,
            "fit_for_duty": assessment.fit_for_duty,
            "concerns_count": len(assessment.concerns),
        })

    logger.info(
        "Circuit breaker assessment: %s trip #%d severity=%s fit_for_duty=%s",
        callsign, trip_count, severity, assessment.fit_for_duty,
    )
```

### New method: `_classify_trip_severity()`

Designed as an override point for AD-506's graduated response:

```python
def _classify_trip_severity(
    self,
    trip_count: int,
    trip_reason: str,
    assessment: CounselorAssessment,
) -> tuple[str, str]:
    """Classify trip severity and generate recommendation.

    Returns (severity, recommendation) tuple.
    Severity levels: "monitor", "concern", "intervention", "escalate".
    Designed as override point for AD-506 graduated response.
    """
    if not assessment.fit_for_duty:
        return "escalate", (
            "Agent not fit for duty. Recommend Captain review and "
            "extended mandatory cooldown until Counselor clears for return."
        )

    if trip_count >= 4:
        return "intervention", (
            "Frequent trips indicate persistent cognitive pattern. "
            "Recommend forced dream cycle for consolidation and "
            "attention redirection to different problem domain."
        )

    if trip_count >= 2:
        return "concern", (
            "Repeated trips suggest unresolved cognitive fixation. "
            "Monitor closely. Consider attention redirection if pattern continues."
        )

    # First trip
    if trip_reason == "rumination":
        return "concern", (
            "First trip due to content repetition. Agent may be fixated "
            "on unresolved concern. Standard cooldown should suffice."
        )

    return "monitor", (
        "First circuit breaker trip. Standard cooldown in effect. "
        "No immediate intervention required."
    )
```

### Helper: `_save_profile_and_assessment()`

Extract the repeated persist pattern from `_on_circuit_breaker_trip()` and `_on_trust_update()` into a shared helper (DRY):

```python
def _save_profile_and_assessment(
    self, agent_id: str, assessment: CounselorAssessment,
) -> None:
    """Persist profile and assessment to store."""
    profile = self._cognitive_profiles.get(agent_id)
    if profile and self._profile_store:
        try:
            self._profile_store.save_profile(profile)
            self._profile_store.save_assessment(assessment)
        except Exception:
            logger.debug(
                "Failed to persist counselor profile for %s",
                agent_id, exc_info=True,
            )
```

Refactor `_on_trust_update()` to also use this helper instead of inline persist code.

## Part 3: Ward Room Posting

### File: `src/probos/cognitive/counselor.py`

Add `ward_room_router` parameter to `initialize()`:

```python
async def initialize(
    self,
    *,
    trust_network: Any = None,
    hebbian_router: Any = None,
    registry: Any = None,
    crew_profiles: Any = None,
    episodic_memory: Any = None,
    emit_event_fn: Any = None,
    add_event_listener_fn: Any = None,
    ward_room_router: Any = None,          # AD-495: Ward Room posting
) -> None:
```

Store as `self._ward_room_router = ward_room_router`.

### New method: `_post_assessment_to_ward_room()`

```python
async def _post_assessment_to_ward_room(
    self,
    agent_id: str,
    callsign: str,
    assessment: CounselorAssessment,
    severity: str,
    trip_count: int,
    trip_reason: str,
) -> None:
    """Post circuit breaker assessment to Ward Room Medical channel."""
    if not self._ward_room_router:
        return

    from probos.bridge_alerts import BridgeAlert, AlertSeverity

    # Map internal severity to AlertSeverity
    if severity == "escalate":
        alert_severity = AlertSeverity.ALERT
    elif severity in ("intervention", "concern"):
        alert_severity = AlertSeverity.ADVISORY
    else:
        alert_severity = AlertSeverity.INFO

    # Build clinical detail
    concerns_text = "; ".join(assessment.concerns) if assessment.concerns else "None"
    recs_text = "; ".join(assessment.recommendations) if assessment.recommendations else "Standard cooldown"

    detail = (
        f"**Agent:** {callsign}\n"
        f"**Trip:** #{trip_count} ({trip_reason})\n"
        f"**Wellness:** {assessment.wellness_score:.2f}\n"
        f"**Fit for Duty:** {'Yes' if assessment.fit_for_duty else 'NO'}\n"
        f"**Concerns:** {concerns_text}\n"
        f"**Recommendations:** {recs_text}"
    )

    alert = BridgeAlert(
        id=f"cb-assess-{agent_id}-{int(assessment.timestamp)}",
        severity=alert_severity,
        source="counselor",
        alert_type="circuit_breaker_assessment",
        title=f"Circuit Breaker Assessment: {callsign}",
        detail=detail,
        department="medical",
        dedup_key=f"cb-assess-{agent_id}",
        related_agent_id=agent_id,
    )

    try:
        await self._ward_room_router.deliver_bridge_alert(alert)
    except Exception:
        logger.debug(
            "Failed to post assessment to Ward Room for %s",
            agent_id, exc_info=True,
        )
```

### File: `src/probos/startup/finalize.py`

Update the AD-503 counselor initialization block to pass `ward_room_router`:

```python
await counselor_agent.initialize(
    trust_network=runtime.trust_network,
    hebbian_router=runtime.hebbian_router,
    registry=runtime.registry,
    crew_profiles=getattr(runtime, 'acm', None),
    episodic_memory=runtime.episodic_memory,
    emit_event_fn=runtime._emit_event,
    add_event_listener_fn=runtime.add_event_listener,
    ward_room_router=getattr(runtime, 'ward_room_router', None),  # AD-495
)
```

## Part 4: Fix Trigger Value

### File: `src/probos/cognitive/counselor.py`

In `_on_circuit_breaker_trip()`, the trigger is already set to `"circuit_breaker"` in the Part 2 code above. Verify that `_on_trust_update()` uses `trigger="trust_update"` (not `"event"`). If it currently uses `"event"`, change it to `"trust_update"`.

## Part 5: Tests

### File: `tests/test_counselor_activation.py`

Add the following test classes/methods to the existing test file. All mocks MUST use `spec=True` or `spec_set=True`.

**Test class: `TestCircuitBreakerTripAssessment`**

1. `test_trip_handler_gathers_metrics_and_assesses` — Verify `_on_circuit_breaker_trip()` calls `_gather_agent_metrics()` then `assess_agent()` with `trigger="circuit_breaker"`.

2. `test_first_trip_classified_as_monitor` — trip_count=1, reason="velocity" → severity="monitor".

3. `test_first_rumination_trip_classified_as_concern` — trip_count=1, reason="rumination" → severity="concern".

4. `test_repeated_trips_classified_as_concern` — trip_count=2 → severity="concern".

5. `test_frequent_trips_classified_as_intervention` — trip_count=4 → severity="intervention".

6. `test_unfit_agent_classified_as_escalate` — fit_for_duty=False → severity="escalate" regardless of trip_count.

7. `test_trip_concerns_added_to_assessment` — Verify circuit breaker-specific concerns appear in `assessment.concerns`.

8. `test_trip_clinical_notes_populated` — Verify `assessment.notes` includes trip_count, reason, cooldown, severity.

9. `test_assessment_persisted_on_trip` — Verify `_save_profile_and_assessment()` called.

10. `test_bridge_alert_always_fires_on_trip` — Verify `_alert_bridge()` called regardless of severity.

11. `test_counselor_assessment_event_emitted` — Verify `COUNSELOR_ASSESSMENT` event emitted with correct fields.

**Test class: `TestWardRoomPosting`**

12. `test_ward_room_post_on_trip` — Verify `deliver_bridge_alert()` called with `BridgeAlert` object, source="counselor", alert_type="circuit_breaker_assessment".

13. `test_ward_room_escalate_uses_alert_severity` — severity="escalate" → `AlertSeverity.ALERT`.

14. `test_ward_room_concern_uses_advisory_severity` — severity="concern" → `AlertSeverity.ADVISORY`.

15. `test_ward_room_monitor_uses_info_severity` — severity="monitor" → `AlertSeverity.INFO`.

16. `test_ward_room_failure_does_not_block_assessment` — `deliver_bridge_alert()` raises → assessment still persisted, bridge alert still fired.

17. `test_ward_room_skipped_when_no_router` — `ward_room_router=None` → no error, posting silently skipped.

**Test class: `TestCircuitBreakerEventEnrichment`**

18. `test_trip_event_includes_cooldown_seconds` — Verify emitted event data contains `cooldown_seconds`.

19. `test_trip_event_includes_trip_reason` — Verify emitted event data contains `trip_reason`.

20. `test_circuit_breaker_records_trip_reason_velocity` — Velocity-only trip → `trip_reason="velocity"`.

21. `test_circuit_breaker_records_trip_reason_rumination` — Similarity-only trip → `trip_reason="rumination"`.

22. `test_circuit_breaker_records_trip_reason_both` — Both signals → `trip_reason="velocity+rumination"`.

**Test class: `TestTriggerValues`**

23. `test_circuit_breaker_trigger_value` — `_on_circuit_breaker_trip()` passes `trigger="circuit_breaker"` to `assess_agent()`.

24. `test_trust_update_trigger_value` — `_on_trust_update()` passes `trigger="trust_update"` to `assess_agent()`.

**Test class: `TestSaveProfileHelper`**

25. `test_save_profile_and_assessment_persists_both` — Verify both `save_profile()` and `save_assessment()` called.

26. `test_save_profile_and_assessment_handles_no_store` — `_profile_store=None` → no error.

27. `test_save_profile_and_assessment_handles_store_error` — Store raises → logged, no propagation.

## Validation Checklist

Run these checks after implementation:

1. `pytest tests/test_counselor_activation.py -v` — all tests pass
2. `pytest tests/ -x --timeout=30` — full suite, no regressions
3. `grep -rn "trigger=\"event\"" src/probos/cognitive/counselor.py` — should return 0 matches (all triggers now specific)
4. `grep -rn "trip_reason" src/probos/cognitive/circuit_breaker.py` — confirms trip reason tracking added
5. `grep -rn "ward_room_router" src/probos/cognitive/counselor.py` — confirms WR wiring
6. `grep -rn "ward_room_router" src/probos/startup/finalize.py` — confirms startup wiring
7. `grep -rn "_classify_trip_severity" src/probos/cognitive/counselor.py` — confirms classification method exists
8. `grep -rn "_save_profile_and_assessment" src/probos/cognitive/counselor.py` — confirms DRY helper exists
9. `grep -rn "spec=True\|spec_set=True" tests/test_counselor_activation.py | wc -l` — count > 0 for every mock
10. `grep -rn "except Exception:" src/probos/cognitive/counselor.py` — every match must have `logger.debug` or `logger.warning` in the next 2 lines (no bare swallows)
