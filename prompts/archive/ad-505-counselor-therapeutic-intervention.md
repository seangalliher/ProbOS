# AD-505: Counselor Therapeutic Intervention

**Objective:** Give the Counselor Tier 2 intervention capability — proactive 1:1 DMs to agents showing cognitive drift, formal recommendations via BridgeAlert, COUNSELOR_GUIDANCE directives injected into agent prompts, cooldown adjustment with clinical rationale, and forced dream cycle integration. Self-Regulation Wave item 5/6.

**Philosophy:** "Advise, don't command." The Counselor reaches out, assesses, recommends. Only mechanical interventions (cooldown adjustment, forced dream) are auto-executed. Directives are advisory. Everything is visible to the Captain.

**Principles compliance:** SOLID (Counselor single responsibility = crew cognitive wellness; new capabilities extend existing class, don't fragment it), Law of Demeter (Counselor calls injected service references, not `runtime.x.y.z`), Fail Fast (log-and-degrade if ward_room or directive_store unavailable), DRY (reuse existing BridgeAlert pipeline, DM pipeline, directive creation API).

---

## Part 0: Fix Ward Room Router Wiring + Add New Dependencies

**Pre-existing bug (BF-096):** In `src/probos/startup/finalize.py` line 186, `getattr(runtime, 'ward_room_router', None)` checks the runtime attribute, but `runtime.ward_room_router` is not set until after `finalize_startup()` returns (runtime.py line 1186). The local variable `ward_room_router` (created at finalize.py line 84) is the correct reference.

**File: `src/probos/startup/finalize.py`**

1. Fix the ward_room_router wiring at line 186 — pass the local `ward_room_router` variable instead of `getattr(runtime, 'ward_room_router', None)`:

```python
ward_room_router=ward_room_router if runtime.ward_room else None,  # AD-505: fixed wiring
```

2. Add four new parameters to the `counselor_agent.initialize()` call (after the ward_room_router line):

```python
ward_room=runtime.ward_room,  # AD-505: for DM channel creation
directive_store=getattr(runtime, 'directive_store', None),  # AD-505
dream_scheduler=getattr(runtime, 'dream_scheduler', None),  # AD-505
proactive_loop=proactive_loop,  # AD-505: for cooldown adjustment
```

Note: `directive_store` and `dream_scheduler` ARE already set on `runtime` before finalize runs (structural_services.py sets directive_store; dreaming.py sets dream_scheduler). Verify by checking `runtime.py` line 1145 (`self.directive_store = struct.directive_store`) and line 1112 (`self.dream_scheduler = dream_result.dream_scheduler`). These run in earlier startup phases. `proactive_loop` is the local variable from finalize.py itself.

**File: `src/probos/cognitive/counselor.py`**

3. Update `__init__()` (around line 419-426) to declare new instance variables:

```python
self._ward_room: Any = None          # AD-505: WardRoomService for DM creation
self._directive_store: Any = None     # AD-505: for COUNSELOR_GUIDANCE directives
self._dream_scheduler: Any = None     # AD-505: for forced dream cycles
self._proactive_loop: Any = None      # AD-505: for cooldown adjustment
self._dm_cooldowns: dict[str, float] = {}  # AD-505: agent_id -> monotonic timestamp of last DM
```

4. Update `initialize()` (line 430) to accept and store the new parameters:

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
    ward_room_router: Any = None,
    ward_room: Any = None,           # AD-505
    directive_store: Any = None,      # AD-505
    dream_scheduler: Any = None,      # AD-505
    proactive_loop: Any = None,       # AD-505
) -> None:
```

In the body, after the existing attribute assignments (around line 453), add:

```python
self._ward_room = ward_room
self._directive_store = directive_store
self._dream_scheduler = dream_scheduler
self._proactive_loop = proactive_loop
```

---

## Part 1: Therapeutic DM Capability

**File: `src/probos/cognitive/counselor.py`**

Add `_send_therapeutic_dm()` method after `_post_assessment_to_ward_room()` (after line ~876):

```python
DM_COOLDOWN_SECONDS = 3600  # 1 hour between DMs to same agent

async def _send_therapeutic_dm(
    self,
    agent_id: str,
    callsign: str,
    message: str,
) -> bool:
    """Send a 1:1 therapeutic DM to an agent. Rate-limited to 1 per agent per hour."""
    if not self._ward_room:
        return False

    # Rate limit: 1 DM per agent per hour
    import time as _time
    now = _time.monotonic()
    last_dm = self._dm_cooldowns.get(agent_id, 0.0)
    if now - last_dm < self.DM_COOLDOWN_SECONDS:
        return False

    try:
        # Create or get existing DM channel between Counselor and target
        channel = await self._ward_room.get_or_create_dm_channel(
            agent_a_id=self.id,
            agent_b_id=agent_id,
            callsign_a=self.callsign,
            callsign_b=callsign,
        )

        # Post the therapeutic message as a thread
        await self._ward_room.create_thread(
            channel_id=channel.id,
            author_id=self.id,
            title=f"[Counselor check-in with @{callsign}]",
            body=message,
            author_callsign=self.callsign,
            thread_mode="discuss",  # Agent can reply
        )

        self._dm_cooldowns[agent_id] = now
        logger.info(f"AD-505: Sent therapeutic DM to {callsign}")
        return True

    except Exception:
        logger.warning(f"AD-505: Failed to send therapeutic DM to {callsign}", exc_info=True)
        return False
```

Key design points:
- Uses the existing DM pipeline (`get_or_create_dm_channel` + `create_thread`)
- `thread_mode="discuss"` so the agent can reply (unlike BridgeAlerts which use `"inform"`)
- Rate-limited via `_dm_cooldowns` dict (monotonic time, 1 hour)
- Log-and-degrade: returns False if ward_room unavailable or rate-limited

---

## Part 2: Therapeutic DM Templates + Triggers

**File: `src/probos/cognitive/counselor.py`**

Add `_build_therapeutic_message()` method:

```python
def _build_therapeutic_message(
    self,
    callsign: str,
    assessment: CounselorAssessment,
    trigger: str,
) -> str:
    """Build a therapeutic DM message from assessment data."""
    parts = [f"@{callsign}, I wanted to check in with you.\n"]

    if trigger == "circuit_breaker":
        parts.append(
            "I noticed your circuit breaker was activated, which usually means "
            "you've been focusing intensely on a particular topic. That kind of "
            "dedication is valuable, but it can also mean something feels unresolved.\n"
        )
    elif trigger == "sweep":
        parts.append(
            "During my routine wellness review, I noticed some patterns in your "
            "recent activity that I wanted to discuss with you.\n"
        )
    elif trigger == "trust_update":
        parts.append(
            "I noticed a significant change in your trust dynamics recently "
            "and wanted to check how you're doing.\n"
        )

    if assessment.concerns:
        parts.append("Specifically, I'm noticing:\n")
        for concern in assessment.concerns[:3]:  # Cap at 3
            parts.append(f"- {concern}\n")

    if assessment.recommendations:
        parts.append("\nMy suggestions:\n")
        for rec in assessment.recommendations[:3]:
            parts.append(f"- {rec}\n")

    parts.append(
        "\nIf there's something you keep thinking about, consider writing it to "
        "your notebook — sometimes getting a thought down helps release it from "
        "active focus. I'm here if you want to discuss further."
    )

    return "".join(parts)
```

Add `_maybe_send_therapeutic_dm()` helper that checks severity and sends if warranted:

```python
async def _maybe_send_therapeutic_dm(
    self,
    agent_id: str,
    callsign: str,
    assessment: CounselorAssessment,
    trigger: str,
) -> None:
    """Send a therapeutic DM if the assessment warrants it."""
    # Only DM for concerning assessments
    if assessment.fit_for_duty and assessment.wellness_score >= COUNSELOR_WELLNESS_YELLOW:
        return  # Agent is fine, no DM needed

    message = self._build_therapeutic_message(callsign, assessment, trigger)
    await self._send_therapeutic_dm(agent_id, callsign, message)
```

### Trigger insertion points:

**In `_on_circuit_breaker_trip()` (around line 744):**

After `_post_assessment_to_ward_room()` and before emitting `COUNSELOR_ASSESSMENT` event, insert:

```python
# AD-505: Therapeutic DM if severity warrants
if severity in ("concern", "intervention", "escalate"):
    await self._maybe_send_therapeutic_dm(
        agent_id, callsign, assessment, trigger="circuit_breaker"
    )
```

Also, if severity is `"intervention"` or `"escalate"`, call the force dream and cooldown methods (Part 5 and 6 below):

```python
# AD-505: Mechanical interventions for high severity
if severity in ("intervention", "escalate"):
    await self._apply_intervention(agent_id, callsign, assessment, severity)
```

**In `_run_wellness_sweep()` (around line 618):**

After `_save_profile_and_assessment()` and before emitting the event, insert:

```python
# AD-505: Therapeutic DM for concerning sweep results
callsign = getattr(agent, 'callsign', agent_type)
await self._maybe_send_therapeutic_dm(
    agent_id, callsign, assessment, trigger="sweep"
)
```

Note: `agent` is the loop variable from the sweep iteration, `agent_type` is already available. Look up the callsign from `self._registry` or use `getattr(agent, 'callsign', agent_type)`.

**In `_on_trust_update()` (find this method):**

After the existing assessment and alert logic, insert the same pattern:

```python
# AD-505: Therapeutic DM for significant trust changes
if not assessment.fit_for_duty or assessment.wellness_score < COUNSELOR_WELLNESS_YELLOW:
    callsign = self._resolve_callsign(agent_id)
    await self._maybe_send_therapeutic_dm(
        agent_id, callsign, assessment, trigger="trust_update"
    )
```

Add a `_resolve_callsign()` helper:

```python
def _resolve_callsign(self, agent_id: str) -> str:
    """Resolve an agent's callsign from registry."""
    if self._registry:
        agent = self._registry.get(agent_id)
        if agent:
            return getattr(agent, 'callsign', agent.agent_type)
    return agent_id[:8]
```

---

## Part 3: Cooldown Adjustment with Reason

**File: `src/probos/proactive.py`**

1. Add `_cooldown_reasons` dict in `__init__()` (after `_agent_cooldowns` at line 57):

```python
self._cooldown_reasons: dict[str, str] = {}  # agent_id -> reason text (AD-505)
```

2. Update `set_agent_cooldown()` (line 99) to accept an optional `reason` parameter:

```python
def set_agent_cooldown(self, agent_id: str, seconds: float, reason: str = "") -> None:
    self._agent_cooldowns[agent_id] = max(60.0, min(float(seconds), 1800.0))
    if reason:
        self._cooldown_reasons[agent_id] = reason
    elif agent_id in self._cooldown_reasons:
        del self._cooldown_reasons[agent_id]
    self._persist_cooldowns()
```

3. Add `get_cooldown_reason()` method (after `get_agent_cooldown` at line ~95):

```python
def get_cooldown_reason(self, agent_id: str) -> str:
    """Return the reason for a cooldown override, or empty string."""
    return self._cooldown_reasons.get(agent_id, "")
```

4. Add `clear_counselor_cooldown()` method for the Counselor to restore defaults:

```python
def clear_counselor_cooldown(self, agent_id: str) -> None:
    """Remove a Counselor-set cooldown override, restoring the default."""
    if agent_id in self._agent_cooldowns:
        del self._agent_cooldowns[agent_id]
    if agent_id in self._cooldown_reasons:
        del self._cooldown_reasons[agent_id]
    self._persist_cooldowns()
```

**File: `src/probos/proactive.py` — self-monitoring context**

5. In `_build_self_monitoring_context()` (around line 755-900), find where `cooldown_increased` is set. Add the cooldown reason to the returned data:

Find the section that builds the cooldown info and add:

```python
reason = self.get_cooldown_reason(agent.id)
if reason:
    context["cooldown_reason"] = reason
```

**File: `src/probos/cognitive/cognitive_agent.py`**

6. In `_build_user_message()`, where self-monitoring context is formatted (look for `[SELF-MONITORING]`), add display of cooldown_reason:

After the existing cooldown display line, add:

```python
if sm_ctx.get("cooldown_reason"):
    parts.append(f"  Counselor note: {sm_ctx['cooldown_reason']}")
```

---

## Part 4: Therapeutic Recommendations via BridgeAlert

**File: `src/probos/cognitive/counselor.py`**

Add `_post_recommendation_to_ward_room()` method:

```python
async def _post_recommendation_to_ward_room(
    self,
    agent_id: str,
    callsign: str,
    assessment: CounselorAssessment,
    actions_taken: list[str],
) -> None:
    """Post a structured recommendation to the Ward Room for Captain visibility."""
    if not self._ward_room_router:
        return

    from probos.bridge_alerts import AlertSeverity, BridgeAlert
    import time as _time

    # Build detail with actions taken and recommendations
    detail_lines = [f"**Agent:** @{callsign}"]
    detail_lines.append(f"**Wellness:** {assessment.wellness_score:.2f}")
    detail_lines.append(f"**Fit for duty:** {'Yes' if assessment.fit_for_duty else 'No'}")

    if assessment.concerns:
        detail_lines.append("\n**Concerns:**")
        for c in assessment.concerns:
            detail_lines.append(f"- {c}")

    if actions_taken:
        detail_lines.append("\n**Actions taken:**")
        for a in actions_taken:
            detail_lines.append(f"- {a}")

    if assessment.recommendations:
        detail_lines.append("\n**Further recommendations (pending Captain review):**")
        for r in assessment.recommendations:
            detail_lines.append(f"- {r}")

    severity = AlertSeverity.ALERT if not assessment.fit_for_duty else AlertSeverity.ADVISORY

    alert = BridgeAlert(
        id=f"counselor-rec-{agent_id}-{int(_time.time())}",
        severity=severity,
        source="counselor",
        alert_type="counselor_recommendation",
        title=f"Counselor Recommendation: @{callsign}",
        detail="\n".join(detail_lines),
        department="medical",
        dedup_key=f"counselor-rec-{agent_id}",
        related_agent_id=agent_id,
    )

    try:
        await self._ward_room_router.deliver_bridge_alert(alert)
    except Exception:
        logger.warning("AD-505: Failed to post recommendation to Ward Room", exc_info=True)
```

---

## Part 5: Counselor Directive Creation

**File: `src/probos/cognitive/counselor.py`**

Add `_issue_guidance_directive()` method:

```python
MAX_ACTIVE_DIRECTIVES_PER_AGENT = 3
DIRECTIVE_DEFAULT_EXPIRY_HOURS = 24

def _issue_guidance_directive(
    self,
    target_agent_type: str,
    content: str,
    expires_hours: float = DIRECTIVE_DEFAULT_EXPIRY_HOURS,
) -> bool:
    """Issue a COUNSELOR_GUIDANCE directive to an agent type."""
    if not self._directive_store:
        return False

    from probos.directive_store import DirectiveType
    from probos.crew_profile import Rank
    import time as _time

    # Rate limit: max N active COUNSELOR_GUIDANCE directives per target
    try:
        active = self._directive_store.get_active_for_agent(target_agent_type)
        counselor_directives = [
            d for d in active
            if d.directive_type == DirectiveType.COUNSELOR_GUIDANCE
        ]
        if len(counselor_directives) >= self.MAX_ACTIVE_DIRECTIVES_PER_AGENT:
            logger.info(
                f"AD-505: Skipping directive for {target_agent_type} — "
                f"{len(counselor_directives)} active COUNSELOR_GUIDANCE already"
            )
            return False

        expires_at = _time.time() + (expires_hours * 3600)

        directive, reason = self._directive_store.create_directive(
            issuer_type="counselor",
            issuer_department="bridge",
            issuer_rank=Rank.COMMANDER,  # Counselor is a bridge officer
            target_agent_type=target_agent_type,
            target_department=None,  # COUNSELOR_GUIDANCE can target any department
            directive_type=DirectiveType.COUNSELOR_GUIDANCE,
            content=content,
            authority=0.8,  # Advisory, not commanding
            priority=4,  # Below Captain orders (3) but above defaults
            expires_at=expires_at,
        )

        if directive:
            logger.info(f"AD-505: Issued COUNSELOR_GUIDANCE to {target_agent_type}: {content[:80]}")
            return True
        else:
            logger.warning(f"AD-505: Directive creation failed for {target_agent_type}: {reason}")
            return False

    except Exception:
        logger.warning("AD-505: Failed to issue guidance directive", exc_info=True)
        return False
```

---

## Part 6: Force Dream + Intervention Orchestrator

**File: `src/probos/cognitive/counselor.py`**

Add `_apply_intervention()` orchestrator method that coordinates mechanical interventions for high-severity assessments:

```python
async def _apply_intervention(
    self,
    agent_id: str,
    callsign: str,
    assessment: CounselorAssessment,
    severity: str,
) -> None:
    """Apply mechanical interventions for high-severity assessments.

    Called when severity is 'intervention' or 'escalate'.
    Actions: extend cooldown, force dream cycle, issue guidance directive.
    All visible to Captain via recommendation BridgeAlert.
    """
    actions_taken = []

    # 1. Extend cooldown (1.5x for intervention, 2x for escalate)
    if self._proactive_loop:
        try:
            current = self._proactive_loop.get_agent_cooldown(agent_id)
            multiplier = 2.0 if severity == "escalate" else 1.5
            new_cooldown = min(current * multiplier, 1800.0)
            reason = (
                f"Counselor intervention: {assessment.concerns[0]}"
                if assessment.concerns else "Counselor intervention: elevated cognitive load"
            )
            self._proactive_loop.set_agent_cooldown(agent_id, new_cooldown, reason=reason)
            actions_taken.append(
                f"Extended cooldown to {new_cooldown:.0f}s ({multiplier}x) — {reason}"
            )
        except Exception:
            logger.warning("AD-505: Failed to extend cooldown", exc_info=True)

    # 2. Force dream cycle (system-wide consolidation)
    if self._dream_scheduler and severity in ("intervention", "escalate"):
        try:
            # Check if already dreaming
            if not self._dream_scheduler.is_dreaming:
                await self._dream_scheduler.force_dream()
                actions_taken.append("Triggered system dream cycle for consolidation")
            else:
                actions_taken.append("Dream cycle already in progress — skipped")
        except Exception:
            logger.warning("AD-505: Failed to trigger dream cycle", exc_info=True)

    # 3. Issue guidance directive (advisory prompt injection)
    if assessment.concerns:
        # Build a specific guidance directive for the agent type
        agent = self._registry.get(agent_id) if self._registry else None
        agent_type = agent.agent_type if agent else agent_id
        concern_summary = assessment.concerns[0]
        directive_content = (
            f"The Counselor has noted: {concern_summary}. "
            "Take extra time between observations. If you notice yourself returning "
            "to the same topic, consider whether you have genuinely new information "
            "to add, or whether writing your thoughts to a notebook would help you "
            "release this focus."
        )
        if self._issue_guidance_directive(agent_type, directive_content):
            actions_taken.append(f"Issued COUNSELOR_GUIDANCE directive: {concern_summary}")

    # 4. Post recommendation BridgeAlert for Captain visibility
    if actions_taken:
        await self._post_recommendation_to_ward_room(
            agent_id, callsign, assessment, actions_taken
        )
```

---

## Part 7: Tests

**File: `tests/test_counselor_therapeutic.py`** (new file)

### Test Class 1: TestTherapeuticDM (8 tests)

1. `test_send_therapeutic_dm_creates_channel_and_thread` — Mock ward_room, verify `get_or_create_dm_channel()` called with counselor ID + target ID, `create_thread()` called with correct channel, author is counselor, thread_mode="discuss".
2. `test_send_therapeutic_dm_rate_limited` — Send DM, immediately send again → second returns False. Advance monotonic past DM_COOLDOWN_SECONDS → third returns True.
3. `test_send_therapeutic_dm_no_ward_room` — `_ward_room = None` → returns False, no crash.
4. `test_send_therapeutic_dm_exception_graceful` — ward_room.create_thread raises → returns False, logged.
5. `test_build_therapeutic_message_circuit_breaker` — Verify message contains circuit breaker language, concerns, recommendations, notebook suggestion.
6. `test_build_therapeutic_message_sweep` — Verify sweep-specific language.
7. `test_build_therapeutic_message_trust_update` — Verify trust change language.
8. `test_maybe_send_dm_skips_healthy_agents` — Agent with fitness=True and wellness >= YELLOW → no DM sent.

### Test Class 2: TestTherapeuticDMTriggers (5 tests)

9. `test_circuit_breaker_trip_sends_dm_on_concern` — Mock trip with severity "concern" → `_send_therapeutic_dm` called.
10. `test_circuit_breaker_trip_no_dm_on_monitor` — Severity "monitor" → no DM sent.
11. `test_circuit_breaker_trip_intervention_applies_intervention` — Severity "intervention" → `_apply_intervention` called.
12. `test_wellness_sweep_sends_dm_for_yellow` — Sweep assessment with wellness < YELLOW → DM sent.
13. `test_trust_update_sends_dm_when_unfit` — Trust update with fit_for_duty=False → DM sent.

### Test Class 3: TestCooldownAdjustment (5 tests)

14. `test_set_agent_cooldown_with_reason` — Set cooldown with reason → `get_cooldown_reason()` returns it.
15. `test_set_agent_cooldown_clears_reason_when_empty` — Set with empty reason → previous reason cleared.
16. `test_clear_counselor_cooldown` — `clear_counselor_cooldown()` removes both cooldown and reason.
17. `test_cooldown_reason_in_self_monitoring` — `_build_self_monitoring_context()` includes `cooldown_reason` when set.
18. `test_cooldown_reason_displayed_in_prompt` — `_build_user_message()` includes "Counselor note: ..." when reason present.

### Test Class 4: TestRecommendationAlert (4 tests)

19. `test_post_recommendation_creates_bridge_alert` — Verify BridgeAlert with `alert_type="counselor_recommendation"`, correct severity mapping, detail includes concerns + actions + recommendations.
20. `test_recommendation_advisory_for_fit_agent` — fit_for_duty=True → ADVISORY severity.
21. `test_recommendation_alert_for_unfit_agent` — fit_for_duty=False → ALERT severity.
22. `test_recommendation_no_router_graceful` — `_ward_room_router = None` → no crash.

### Test Class 5: TestDirectiveCreation (5 tests)

23. `test_issue_guidance_directive_success` — Mock directive_store, verify `create_directive()` called with `COUNSELOR_GUIDANCE`, issuer_type="counselor", correct expiry.
24. `test_issue_guidance_directive_rate_limited` — 3 active COUNSELOR_GUIDANCE → fourth skipped.
25. `test_issue_guidance_directive_no_store` — `_directive_store = None` → returns False.
26. `test_issue_guidance_directive_authorization_failure` — `create_directive()` returns (None, reason) → returns False, logged.
27. `test_directive_has_24h_default_expiry` — Verify `expires_at` is ~24 hours in the future.

### Test Class 6: TestApplyIntervention (6 tests)

28. `test_intervention_extends_cooldown_1_5x` — severity="intervention" → cooldown set to 1.5x, reason includes concern text.
29. `test_escalate_extends_cooldown_2x` — severity="escalate" → cooldown set to 2.0x.
30. `test_intervention_forces_dream_cycle` — `dream_scheduler.force_dream()` called. Verify `is_dreaming` check (skip if already dreaming).
31. `test_intervention_issues_guidance_directive` — Directive created with concern-specific content.
32. `test_intervention_posts_recommendation_alert` — `_post_recommendation_to_ward_room()` called with list of actions taken.
33. `test_intervention_graceful_without_services` — All services None → no crash, empty actions_taken.

### Test Class 7: TestCounselorWiring (4 tests)

34. `test_initialize_accepts_new_parameters` — Verify `ward_room`, `directive_store`, `dream_scheduler`, `proactive_loop` stored on instance.
35. `test_finalize_passes_local_ward_room_router` — Verify finalize.py passes local variable, not getattr (mock test or integration).
36. `test_finalize_passes_new_dependencies` — Verify `ward_room`, `directive_store`, `dream_scheduler`, `proactive_loop` passed to `initialize()`.
37. `test_resolve_callsign_from_registry` — `_resolve_callsign()` returns correct callsign, falls back to agent_id[:8] when registry unavailable.

### Test Class 8: TestIntegration (3 tests)

38. `test_full_circuit_breaker_to_dm_flow` — End-to-end: emit CIRCUIT_BREAKER_TRIP event with trip_count=3 → assessment runs → DM sent → intervention applied → recommendation posted.
39. `test_full_sweep_to_dm_flow` — Wellness sweep with one struggling agent → DM sent to that agent, others skipped.
40. `test_dm_rate_limit_across_triggers` — Circuit breaker trip sends DM → wellness sweep within 1 hour to same agent → second DM skipped (rate limit).

**Total: 40 tests across 8 classes.**

---

## Validation Checklist

1. [ ] `_send_therapeutic_dm()` creates DM channel and thread with Counselor as author
2. [ ] DM rate limiting works (1 per agent per hour)
3. [ ] `_build_therapeutic_message()` produces distinct messages for circuit_breaker / sweep / trust_update triggers
4. [ ] `_maybe_send_therapeutic_dm()` skips healthy agents (fitness=True + wellness >= YELLOW)
5. [ ] DM inserted into `_on_circuit_breaker_trip()` at correct severity levels
6. [ ] DM inserted into `_run_wellness_sweep()` after assessment persistence
7. [ ] DM inserted into `_on_trust_update()` for unfit/low-wellness agents
8. [ ] `set_agent_cooldown()` accepts `reason` parameter, stores in `_cooldown_reasons`
9. [ ] `cooldown_reason` appears in self-monitoring context and prompt formatting
10. [ ] `_post_recommendation_to_ward_room()` creates proper BridgeAlert with `alert_type="counselor_recommendation"`
11. [ ] `_issue_guidance_directive()` creates COUNSELOR_GUIDANCE with 24h expiry, rate-limited to 3 per target
12. [ ] `_apply_intervention()` coordinates cooldown + dream + directive + recommendation for high severity
13. [ ] `finalize.py` passes local `ward_room_router` variable (not `getattr(runtime, ...)`)
14. [ ] `finalize.py` passes `ward_room`, `directive_store`, `dream_scheduler`, `proactive_loop` to Counselor
15. [ ] All 40 tests pass
16. [ ] Full test suite has no new regressions
17. [ ] Counselor can still handle DM intents (existing `act()` passthrough for `direct_message` unchanged)
18. [ ] Counselor standing orders ("advise, don't command") respected — no force actions without clinical rationale
