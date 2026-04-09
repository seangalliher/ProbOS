# AD-583: Wrong Convergence Detection

**Status:** Ready for builder
**Type:** Cognitive / Safety
**Depends on:** AD-554 (convergence detection), AD-567f (social verification), AD-557 (emergence metrics), AD-506b (peer repetition)
**Case study:** `memory/case-study-confabulation-echo-chamber.md` — Chapel tic-tac-toe echo chamber (2026-04-08)

## Problem

The system can detect THAT convergence occurred (AD-554), THAT repetition is happening (AD-506b), THAT groupthink risk is elevated (AD-557), and THAT cascade risk exists (AD-567f). But **no component ties these signals together** to determine whether convergence is **correct** (independent collaborative insight, e.g. iatrogenic trust case) or **pathological** (echo chamber, e.g. Chapel tic-tac-toe case).

Current state:
- AD-554 `check_cross_agent_convergence()` treats ALL convergence as positive (ADVISORY alert)
- AD-557 `_on_groupthink_warning()` in Counselor is **log-only** — no corrective action
- AD-567f `check_cascade_risk()` works only in the Ward Room post pathway, not the convergence pathway
- AD-569 `convergence_correctness_rate` is always `None` — ground truth deferred
- `EmergenceSnapshot.provenance_independence` is `None` — reserved for AD-559 but never populated
- Bridge alerts for convergence are always ADVISORY severity — never escalate to ALERT

The case study showed: Medical department (4 agents, 11 posts) amplified Chapel's false diagnosis without any agent independently checking the game board. The system flagged convergence but treated it as positive. What was needed: detect that the convergence had low anchor independence (same information chain) and escalate accordingly.

## Design

### AD-583a: Convergence Independence Scoring

Wire AD-567f's `compute_anchor_independence()` into the AD-554 convergence pathway so every convergence detection includes an independence assessment.

**File:** `src/probos/knowledge/records_store.py`

Modify `check_cross_agent_convergence()` (line 405) to return two additional fields:
- `convergence_independence_score: float` — anchor independence of the converging entries (0.0–1.0)
- `convergence_is_independent: bool` — independence_score >= threshold (default 0.3)

Implementation:
1. Import `compute_anchor_independence` from `probos.cognitive.social_verification`
2. After convergence matches are collected (the `convergence_matches` list at ~line 489), create lightweight episode-like objects from the match data so `compute_anchor_independence()` can score them. Use a minimal `SimpleNamespace` or `@dataclass` with `anchors` and `timestamp` fields extracted from notebook frontmatter (`updated`, `duty_cycle_id`, `channel_id`, `thread_id` if present).
3. Add `convergence_independence_score` and `convergence_is_independent` to the returned dict.

**Config:** Add to `RecordsConfig` in `config.py` (line 471):
- `convergence_independence_threshold: float = 0.3` — below this, convergence is flagged as potentially pathological

**Important:** `compute_anchor_independence()` is a **pure function** (not a method on `SocialVerificationService`). It lives at module level in `social_verification.py` (line 98). Import the function directly — no service dependency needed. This preserves DI.

### AD-583b: Wrong Convergence Event & Alert Escalation

**File:** `src/probos/events.py`

Add new event type and dataclass:
```python
# In EventType enum (after CASCADE_CONFABULATION_DETECTED):
WRONG_CONVERGENCE_DETECTED = "wrong_convergence_detected"  # AD-583

# New dataclass:
@dataclass
class WrongConvergenceDetectedEvent(BaseEvent):
    """AD-583: Convergence with insufficient independent evidence."""
    event_type: EventType = field(default=EventType.WRONG_CONVERGENCE_DETECTED, init=False)
    agents: list[str] = field(default_factory=list)
    departments: list[str] = field(default_factory=list)
    topic: str = ""
    coherence: float = 0.0
    independence_score: float = 0.0
    source: str = ""  # "realtime" or "dream_consolidation"
```

**File:** `src/probos/bridge_alerts.py`

Add method `check_wrong_convergence()`:
```python
def check_wrong_convergence(self, conv_result: dict) -> list[BridgeAlert]:
    """AD-583: Escalate convergence with low anchor independence."""
    alerts: list[BridgeAlert] = []
    if not conv_result.get("convergence_detected"):
        return alerts
    if conv_result.get("convergence_is_independent", True):
        return alerts  # Independent convergence — no escalation

    topic = conv_result.get("convergence_topic", "unknown")
    agents = conv_result.get("convergence_agents", [])
    departments = conv_result.get("convergence_departments", [])
    independence = conv_result.get("convergence_independence_score", 0.0)
    key = f"wrong_convergence:{topic}"

    if self._should_emit(key):
        a = BridgeAlert(
            id=str(uuid.uuid4()),
            severity=AlertSeverity.ALERT,  # Escalated from ADVISORY
            source="convergence_monitor",
            alert_type="wrong_convergence_detected",
            title="Possible Echo Chamber Detected",
            detail=(
                f"{len(agents)} agents from {len(departments)} departments "
                f"converged on '{topic}' but anchor independence is only "
                f"{independence:.0%}. Claims may be echoing rather than "
                f"independently verified."
            ),
            department=None,
            dedup_key=key,
        )
        self._record(a)
        alerts.append(a)
    return alerts
```

### AD-583c: Real-Time Integration (proactive.py)

**File:** `src/probos/proactive.py`

In the AD-554 convergence block (~line 2015), after convergence is detected:

1. Check `conv_result.get("convergence_is_independent", True)` — if `False`:
   a. Emit `WrongConvergenceDetectedEvent` (instead of/in addition to `ConvergenceDetectedEvent`)
   b. Call `check_wrong_convergence()` on bridge alerter (instead of/in addition to `check_realtime_convergence()`)
   c. Log at WARNING level

The original `ConvergenceDetectedEvent` and ADVISORY bridge alert should still fire — AD-583 adds the escalation on top when independence is low. This way both the positive convergence signal and the wrong-convergence warning are visible.

### AD-583d: Counselor Response Upgrade

**File:** `src/probos/cognitive/counselor.py`

1. **Subscribe** to `WRONG_CONVERGENCE_DETECTED` in the event subscription block (alongside existing `GROUPTHINK_WARNING` subscription).

2. **New handler** `_on_wrong_convergence_detected(self, data: dict[str, Any])`:
   - Extract `agents`, `departments`, `topic`, `independence_score`
   - Log at WARNING level
   - If independence_score < 0.1 (near-zero independence): issue a directive to converging agents via `_maybe_send_therapeutic_dm()` with trigger `"wrong_convergence"` and a message encouraging independent verification of the claim
   - Rate-limit: use existing Counselor cooldown mechanics — don't DM the same agent within cooldown window

3. **Upgrade existing `_on_groupthink_warning()`** (line 1321): currently log-only. Add:
   - When `redundancy_ratio > 0.9` (extreme groupthink), log at ERROR level and note that AD-583 wrong convergence detection may provide more targeted response
   - This is minimal — the real corrective action comes from the wrong convergence handler

### AD-583e: Dream Step Integration

**File:** `src/probos/cognitive/dreaming.py`

In Dream Step 7g (batch convergence, ~line 454): after `check_cross_agent_convergence()` returns for each convergence report:
1. Check `convergence_is_independent` field
2. If `False`: emit `WrongConvergenceDetectedEvent` (same as real-time path)
3. Tag the convergence report with `"independence": "low"` in the generated report file

In Dream Step 9 (emergence metrics, ~line 801): populate `EmergenceSnapshot.provenance_independence`:
1. After `compute_emergence_metrics()` returns the snapshot
2. If `self._social_verification` is available (via runtime): compute a ship-wide anchor independence estimate by calling `compute_anchor_independence()` on a sample of recent episodes from episodic memory
3. Set `snapshot.provenance_independence = <computed_value>`
4. This satisfies the AD-559 reservation

**Note:** `EmergenceSnapshot` is NOT frozen (it's a regular `@dataclass`, not `frozen=True`) — direct attribute assignment will work.

## Engineering Principles Compliance

| Principle | How This AD Complies |
|---|---|
| **Single Responsibility** | `compute_anchor_independence()` already exists — we reuse it, not duplicate. Wrong convergence logic is a thin orchestration layer connecting existing signals. |
| **Open/Closed** | Extends `check_cross_agent_convergence()` return dict (additive). Extends bridge alerter with new method (additive). No modification to AD-567f internals. |
| **Dependency Inversion** | Imports `compute_anchor_independence` as a pure function (no service dependency). Counselor subscribes to event (loose coupling). |
| **Law of Demeter** | Accesses runtime attributes via `getattr()` pattern established in proactive.py. No reaching through objects. |
| **Fail Fast** | Independence scoring is non-critical — if notebook frontmatter lacks anchor fields, `compute_anchor_independence()` returns 0.0 (conservative default: flags as potentially pathological — better false positive than false negative). |
| **DRY** | Reuses `compute_anchor_independence()`, `BridgeAlert` pattern, Counselor event subscription pattern, `_should_emit()` dedup. |
| **Cloud-Ready Storage** | No new storage introduced. Operates on existing notebook files and events. |

## Prior Work Absorbed

- **AD-554** (convergence detection): Extended, not replaced. Independence score added to its return dict.
- **AD-567f** (social verification): `compute_anchor_independence()` reused as-is. `_are_independently_anchored()` logic unchanged.
- **AD-557** (emergence metrics): `provenance_independence` field populated (was reserved for AD-559).
- **AD-506b** (peer repetition): Not modified — operates at Ward Room level. AD-583 operates at notebook/convergence level.
- **AD-569** (behavioral metrics): `convergence_correctness_rate` remains deferred (AD-569d). AD-583 provides a heuristic signal (independence) rather than ground truth correctness.
- **BF-124** (cooperation cluster calibration): Not modified — topology-based. AD-583 is content+anchor-based.
- **Case study** (tic-tac-toe echo chamber): Direct motivation. Medical dept 11-post echo chamber would be caught by independence_score ≈ 0.0 (all posts from same Ward Room thread, same duty cycle).

## Deferred

- **AD-583f (Observable State Verification):** Verify convergent claims against observable system state (e.g., game board, metrics). Requires structured observable-state registry — substantial new infrastructure. The tic-tac-toe case study showed this is the deepest gap (agents can't parse observable state), but it's architecturally separate from wrong convergence detection.
- **AD-583g (Convergence Source Tracing):** Full information-chain reconstruction — trace exactly which post introduced the false claim and how it propagated. Would enable automated "Patient Zero" identification. Requires Ward Room thread graph traversal.
- **AD-559 (Provenance Independence):** Full provenance model. AD-583e partially satisfies by populating `provenance_independence` on `EmergenceSnapshot`, but full provenance tracking (per-claim evidence chains) is a larger effort.

## Test Plan — 28 tests in `tests/test_ad583_wrong_convergence.py`

### AD-583a: Convergence Independence Scoring (8 tests)
1. `test_convergence_result_includes_independence_score` — convergence dict has `convergence_independence_score` float field
2. `test_convergence_result_includes_is_independent` — convergence dict has `convergence_is_independent` bool field
3. `test_independent_convergence_high_score` — entries with different duty_cycle_id/channel_id → independence_score > 0.3 → `is_independent=True`
4. `test_dependent_convergence_low_score` — entries from same thread/duty_cycle → independence_score < 0.3 → `is_independent=False`
5. `test_no_convergence_returns_default` — when convergence_detected=False, independence fields still present with defaults (score=0.0, is_independent=True)
6. `test_independence_threshold_config` — custom `convergence_independence_threshold` in RecordsConfig is respected
7. `test_missing_anchor_fields_conservative` — entries without duty_cycle_id/channel_id → independence_score=0.0 (conservative)
8. `test_mixed_independent_dependent` — mix of independent and dependent entries → intermediate score

### AD-583b: Wrong Convergence Event & Alert (6 tests)
9. `test_wrong_convergence_event_type_exists` — `EventType.WRONG_CONVERGENCE_DETECTED` in enum
10. `test_wrong_convergence_event_dataclass` — `WrongConvergenceDetectedEvent` serializes correctly via `to_dict()`
11. `test_wrong_convergence_bridge_alert_fires` — `check_wrong_convergence()` returns ALERT-severity alert when `convergence_is_independent=False`
12. `test_independent_convergence_no_alert` — `check_wrong_convergence()` returns empty when `convergence_is_independent=True`
13. `test_no_convergence_no_alert` — `check_wrong_convergence()` returns empty when `convergence_detected=False`
14. `test_wrong_convergence_dedup` — second call with same topic suppressed by `_should_emit()`

### AD-583c: Real-Time Integration (5 tests)
15. `test_realtime_wrong_convergence_event_emitted` — when realtime convergence detected with low independence, `WRONG_CONVERGENCE_DETECTED` event emitted
16. `test_realtime_independent_convergence_no_escalation` — independent convergence emits only `CONVERGENCE_DETECTED`, not `WRONG_CONVERGENCE_DETECTED`
17. `test_realtime_wrong_convergence_bridge_alert` — wrong convergence triggers ALERT-severity bridge alert
18. `test_realtime_both_events_emitted` — both `CONVERGENCE_DETECTED` (ADVISORY) and `WRONG_CONVERGENCE_DETECTED` (ALERT) fire for wrong convergence
19. `test_realtime_convergence_disabled_no_wrong_check` — when `realtime_convergence_enabled=False`, no wrong convergence check either

### AD-583d: Counselor Response (5 tests)
20. `test_counselor_subscribes_wrong_convergence` — `WRONG_CONVERGENCE_DETECTED` in Counselor event subscriptions
21. `test_counselor_wrong_convergence_handler_logs` — handler logs at WARNING level
22. `test_counselor_wrong_convergence_extreme_sends_dm` — independence_score < 0.1 triggers therapeutic DM to converging agents
23. `test_counselor_wrong_convergence_moderate_no_dm` — independence_score in 0.1-0.3 range: no DM, just log
24. `test_counselor_groupthink_extreme_logs_error` — redundancy_ratio > 0.9 now logs at ERROR level (upgrade from WARNING)

### AD-583e: Dream Step Integration (4 tests)
25. `test_dream_step7g_flags_wrong_convergence` — batch convergence with low independence emits `WRONG_CONVERGENCE_DETECTED`
26. `test_dream_step7g_independent_no_flag` — batch convergence with high independence: no wrong convergence event
27. `test_dream_step9_populates_provenance_independence` — `EmergenceSnapshot.provenance_independence` is a float (not None) after dream step 9
28. `test_dream_step9_provenance_reflects_episodes` — provenance_independence reflects actual anchor independence of sampled episodes

## Build Order

1. AD-583a first — provides the foundation (independence scoring in convergence results)
2. AD-583b second — event type and bridge alert method
3. AD-583c third — real-time pathway wiring
4. AD-583d fourth — Counselor subscription and handlers
5. AD-583e fifth — dream step integration

Each phase: implement → test → verify existing tests still pass.

## Files Modified

| File | Change |
|---|---|
| `src/probos/knowledge/records_store.py` | Add independence scoring to `check_cross_agent_convergence()` return |
| `src/probos/config.py` | Add `convergence_independence_threshold` to `RecordsConfig` |
| `src/probos/events.py` | Add `WRONG_CONVERGENCE_DETECTED` event type + `WrongConvergenceDetectedEvent` dataclass |
| `src/probos/bridge_alerts.py` | Add `check_wrong_convergence()` method |
| `src/probos/proactive.py` | Wire wrong convergence check into real-time convergence block |
| `src/probos/cognitive/counselor.py` | Subscribe to `WRONG_CONVERGENCE_DETECTED`, add handler, upgrade groupthink handler |
| `src/probos/cognitive/dreaming.py` | Flag wrong convergence in Step 7g, populate `provenance_independence` in Step 9 |
| `tests/test_ad583_wrong_convergence.py` | 28 new tests |

## Verified Against Live Codebase

- [x] `compute_anchor_independence()` is a module-level pure function at `social_verification.py:98` — importable directly
- [x] `_are_independently_anchored()` is module-level at `social_verification.py:55` — no service dependency
- [x] `check_cross_agent_convergence()` at `records_store.py:405` — returns dict, additive fields safe
- [x] `RecordsConfig` at `config.py:471` — has `realtime_convergence_*` fields, pattern for new field clear
- [x] `EventType` enum at `events.py:19` — string enum, additive
- [x] `ConvergenceDetectedEvent` at `events.py:555` — pattern for new dataclass
- [x] `BridgeAlertManager.check_realtime_convergence()` at `bridge_alerts.py:496` — pattern for new method
- [x] `AlertSeverity.ALERT` at `bridge_alerts.py:27` — exists, correct severity for escalation
- [x] Real-time convergence block at `proactive.py:2015` — integration point verified
- [x] Counselor groupthink handler at `counselor.py:1321` — log-only, upgrade target verified
- [x] `EmergenceSnapshot.provenance_independence` at `emergence_metrics.py:67` — `None`, regular dataclass (not frozen), assignable
- [x] `self._social_verification` at `runtime.py:1137` — available on runtime
- [x] Dream Step 7g at `dreaming.py:~454` — batch convergence integration point
- [x] Dream Step 9 at `dreaming.py:~801` — emergence metrics integration point
