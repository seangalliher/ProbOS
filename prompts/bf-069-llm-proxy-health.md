# Build Prompt: BF-069 — LLM Proxy Health Monitoring & Alerting

**Ticket:** BF-069
**Priority:** High (silent failures leave the Captain blind)
**Scope:** LLM client health tracking, VitalsMonitor extension, Bridge alerts, system services endpoint, proactive loop failure visibility
**Principles Compliance:** Fail Fast (log-and-degrade, not swallow), Defense in Depth (detect at source + monitor + alert + surface), HXI Cockpit View (Captain needs the stick)

---

## Context

When the Copilot proxy (127.0.0.1:8080) goes down or returns empty responses, the entire crew stops thinking proactively with **zero indication to the Captain.** The proactive loop silently swallows failures (`proactive.py` line 349: `if not result or not result.success or not result.result: return`). The shell chat returns "(Empty response)". No bridge alert fires. No system panel indicator changes.

The only visibility today is:
- Boot-time `check_connectivity()` — called once, never again
- Reactive `check_connectivity()` in `routers/chat.py` — only on empty chat response, diagnostic only
- Logger warnings in `llm_client.py` exception handlers — visible only in logs, not surfaced to crew or Captain

**This is the smoke detector, not the fire suppression system.** BF-069 is detection + alerting + visibility. Automated response (service shedding, failover) is AD-459 (Saucer Separation). Performance telemetry (token tracking, latency) is AD-461 (Ship's Telemetry). Capacity management is AD-469 (EPS). Do NOT build any of those concerns here.

---

## Deliverables

### 1. LLM Health Tracking in `llm_client.py`

**File:** `src/probos/cognitive/llm_client.py`

Add lightweight health state tracking to `OpenAICompatibleClient`. No new dependencies.

**(a) Per-tier failure counter:**

Add to `__init__()` (near `self._tier_status` at line 82):
```python
self._consecutive_failures: dict[str, int] = {t: 0 for t in ("fast", "standard", "deep")}
self._last_success: dict[str, float] = {}  # tier -> monotonic timestamp
self._last_failure: dict[str, float] = {}  # tier -> monotonic timestamp
```

**(b) Update counters in `complete()`:**

In the success path (line 240-248, after `self._cache[cache_key] = response`):
```python
self._consecutive_failures[attempt_tier] = 0
self._last_success[attempt_tier] = time.monotonic()
```

In each exception handler (lines 249-263), after the existing `logger.warning()`:
```python
self._consecutive_failures[attempt_tier] += 1
self._last_failure[attempt_tier] = time.monotonic()
```

**(c) `get_health_status()` method:**

Add a new public method to `OpenAICompatibleClient`:
```python
def get_health_status(self) -> dict[str, Any]:
    """Return per-tier and overall LLM health status.

    Per-tier status:
    - "operational": 0 consecutive failures, last connectivity check passed
    - "degraded": 1-2 consecutive failures OR last check unreachable but not confirmed down
    - "unreachable": 3+ consecutive failures

    Overall status:
    - "operational": all configured tiers operational
    - "degraded": at least one tier operational, at least one unreachable
    - "offline": all tiers unreachable
    """
```

Return shape:
```python
{
    "tiers": {
        "fast": {"status": "operational"|"degraded"|"unreachable", "consecutive_failures": int, "last_success": float|None, "last_failure": float|None},
        "standard": {...},
        "deep": {...},
    },
    "overall": "operational"|"degraded"|"offline",
}
```

Tier status logic:
- `"operational"`: `consecutive_failures == 0`
- `"degraded"`: `0 < consecutive_failures < 3`
- `"unreachable"`: `consecutive_failures >= 3`

Overall status logic:
- `"operational"`: ALL tiers are `"operational"`
- `"offline"`: ALL tiers are `"unreachable"`
- `"degraded"`: anything else

The threshold of 3 consecutive failures should be a class-level constant `_UNREACHABLE_THRESHOLD = 3`.

**(d) Also add `get_health_status()` to `BaseLLMClient`:**

Abstract method returning a default healthy status. `MockLLMClient` should return `{"tiers": {...all operational...}, "overall": "operational"}`.

**(e) Reset counters on successful connectivity check:**

In `check_connectivity()` (line 142-162), when a tier is found reachable, reset its consecutive failure counter:
```python
if results[tier]:
    self._consecutive_failures[tier] = 0
    self._last_success[tier] = time.monotonic()
```

---

### 2. VitalsMonitor Extension

**File:** `src/probos/agents/medical/vitals_monitor.py`

Extend VitalsMonitor to include LLM health in its metrics collection and threshold checks.

**(a) Add LLM health to `collect_metrics()`** (line 58):

After the existing emergence metrics block (line ~124), add:
```python
# BF-069: LLM proxy health
llm_health = {"overall": "unknown", "tiers": {}}
llm_client = getattr(rt, 'llm_client', None)
if llm_client and hasattr(llm_client, 'get_health_status'):
    llm_health = llm_client.get_health_status()
metrics["llm_health"] = llm_health
```

**(b) Add LLM threshold checks to `_check_thresholds()`** (line 204):

After the existing system health check block, add:
```python
# BF-069: LLM proxy health alerts
llm_health = metrics.get("llm_health", {})
llm_overall = llm_health.get("overall", "unknown")
if llm_overall == "offline":
    await rt.intent_bus.broadcast(Intent(
        intent="medical_alert",
        entities={"alert": "LLM proxy offline — all tiers unreachable", "severity": "critical"},
    ))
elif llm_overall == "degraded":
    unreachable_tiers = [
        t for t, info in llm_health.get("tiers", {}).items()
        if info.get("status") == "unreachable"
    ]
    if unreachable_tiers:
        await rt.intent_bus.broadcast(Intent(
            intent="medical_alert",
            entities={"alert": f"LLM proxy degraded — tier(s) unreachable: {', '.join(unreachable_tiers)}", "severity": "warning"},
        ))
```

---

### 3. BridgeAlertService Extension

**File:** `src/probos/bridge_alerts.py`

Add a new signal processor for LLM health, following the existing `check_vitals()` / `check_trust_change()` pattern.

**(a) Add `check_llm_health()` method:**

```python
def check_llm_health(self, llm_health: dict) -> list[BridgeAlert]:
    """BF-069: Evaluate LLM proxy health and emit bridge alerts."""
    alerts = []
    overall = llm_health.get("overall", "unknown")
    tiers = llm_health.get("tiers", {})

    if overall == "offline":
        key = "llm_offline"
        if self._should_emit(key):
            alerts.append(BridgeAlert(
                id=str(uuid.uuid4()),
                severity=AlertSeverity.ALERT,
                title="Communications Array Offline",
                detail="All LLM tiers unreachable. Crew cognitive functions suspended. Check Copilot proxy at 127.0.0.1:8080.",
                department=None,
                dedup_key=key,
            ))
    elif overall == "degraded":
        unreachable = [t for t, info in tiers.items() if info.get("status") == "unreachable"]
        if unreachable:
            key = f"llm_degraded_{'_'.join(sorted(unreachable))}"
            if self._should_emit(key):
                alerts.append(BridgeAlert(
                    id=str(uuid.uuid4()),
                    severity=AlertSeverity.ADVISORY,
                    title="Communications Array Degraded",
                    detail=f"LLM tier(s) unreachable: {', '.join(unreachable)}. Remaining tiers operational. Fallback routing active.",
                    department=None,
                    dedup_key=key,
                ))

    return alerts
```

**(b) Wire into the runtime vitals check cycle:**

Find where `bridge_alert_service.check_vitals()` is called in the runtime or VitalsMonitor and add a corresponding `check_llm_health()` call.

Search for `check_vitals` calls in the codebase — likely in `runtime.py` or in the VitalsMonitor listener callback. Add the LLM health check alongside it:

```python
# After existing check_vitals call:
llm_client = getattr(runtime, 'llm_client', None)
if llm_client and hasattr(llm_client, 'get_health_status'):
    llm_alerts = bridge_alert_service.check_llm_health(llm_client.get_health_status())
    for alert in llm_alerts:
        await ward_room_router.deliver_bridge_alert(alert)
```

The exact wiring location depends on where the existing `check_vitals → deliver_bridge_alert` pipeline runs. Find it and follow the same pattern.

---

### 4. System Services Endpoint

**File:** `src/probos/routers/system.py`

**(a) Add LLM proxy to `/api/system/services`** (line 42-65):

After the existing service checks list, add:
```python
# BF-069: LLM proxy health
llm_client = getattr(runtime, 'llm_client', None)
if llm_client and hasattr(llm_client, 'get_health_status'):
    health = llm_client.get_health_status()
    overall = health.get("overall", "unknown")
    # Map to existing status vocabulary: online/degraded/offline
    if overall == "operational":
        llm_status = "online"
    elif overall == "degraded":
        llm_status = "degraded"
    else:
        llm_status = "offline"
    services.append({"name": "LLM Proxy", "status": llm_status})
else:
    services.append({"name": "LLM Proxy", "status": "offline"})
```

**(b) Add per-tier detail endpoint** (new):

Add a new endpoint for detailed LLM health:
```python
@router.get("/system/llm-health")
async def llm_health(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """BF-069: Detailed LLM proxy health status per tier."""
    llm_client = getattr(runtime, 'llm_client', None)
    if llm_client and hasattr(llm_client, 'get_health_status'):
        return llm_client.get_health_status()
    return {"tiers": {}, "overall": "unknown"}
```

**(c) HXI auto-support:**

The existing `BridgeSystem.tsx` polls `/api/system/services` every 10 seconds and renders status dots. Adding "LLM Proxy" to the services list means it will automatically appear in the HXI. The existing rendering logic uses green for "online" — verify it handles "degraded" (yellow) and "offline" (red). If the frontend only supports "online"/"offline", add "degraded" handling:

In the status dot rendering logic, if it currently does:
```tsx
color={status === 'online' ? 'green' : 'red'}
```

Change to:
```tsx
color={status === 'online' ? 'green' : status === 'degraded' ? 'yellow' : 'red'}
```

Search for the status dot rendering in `BridgeSystem.tsx` and make this change only if needed.

---

### 5. Proactive Loop Failure Visibility

**File:** `src/probos/proactive.py`

**(a) Add failure tracking:**

Add to `ProactiveCognitiveLoop.__init__()`:
```python
self._llm_failure_count: int = 0
self._llm_failure_streak: int = 0  # consecutive cycles with at least one failure
```

**(b) Log and count failures in `_process_agent()`** (line 349):

Currently:
```python
if not result or not result.success or not result.result:
    return
```

Change to:
```python
if not result or not result.success or not result.result:
    self._llm_failure_count += 1
    # Check if this is an LLM error vs a [NO_RESPONSE]
    error_detail = ""
    if result and hasattr(result, 'error') and result.error:
        error_detail = str(result.error)
    elif result and not result.success:
        error_detail = "agent returned unsuccessful result"
    if error_detail:
        logger.warning(
            "Proactive think failed for %s: %s (consecutive failures: %d)",
            agent.agent_type, error_detail, self._llm_failure_count,
        )
    return
```

**(c) Reset streak on success:**

After a successful proactive thought is posted (after the `_post_to_ward_room` call, around line 419):
```python
self._llm_failure_count = 0
```

**(d) Expose failure count for VitalsMonitor:**

Add a property:
```python
@property
def llm_failure_count(self) -> int:
    """BF-069: Number of consecutive proactive loop failures."""
    return self._llm_failure_count
```

**Note:** The proactive loop failure count is complementary to the LLM client's per-tier tracking. The LLM client tracks network-level failures per tier. The proactive loop tracks end-to-end cognitive failures (which may include LLM errors, empty responses from the agent, or processing errors). Both feed into the overall health picture.

---

### 6. Event Type (optional but recommended)

**File:** `src/probos/events.py`

Add to the `EventType` enum after `FRAGMENTATION_WARNING`:
```python
LLM_HEALTH_CHANGED = "llm_health_changed"  # BF-069: LLM proxy status transition
```

Emit this event from `OpenAICompatibleClient.complete()` when overall status transitions (e.g., operational → degraded, degraded → offline, offline → operational). This requires:
- Storing `_previous_overall_status: str = "unknown"` in `__init__`
- After updating failure counters, computing current overall status
- If it differs from previous, emitting the event via the event bus (which requires the client to have an optional event bus reference)

**If wiring the event bus into `llm_client.py` is complex**, defer the event emission. The VitalsMonitor polling every 5 seconds is sufficient for BF-069. The event would be a refinement for instant detection (sub-second) but is not required for the core fix. Use your judgement.

---

## Scope Boundaries — Do NOT Build

| Concern | Why Not | Future AD |
|---------|---------|-----------|
| Retry logic / exponential backoff in `complete()` | Response pathway, not detection | AD-459 |
| Automatic failover to backup providers | Response pathway | AD-459 |
| Service tier shedding (Saucer Separation) | Response pathway | AD-459 |
| Token consumption tracking / latency metrics | Performance telemetry | AD-461 |
| Department LLM budgets / capacity management | Resource management | AD-469 |
| LLM network circuit breaker (stop retrying) | Related but separate — BF-069 is alerting, circuit breaker is behavioral | Future BF or AD-459 |

---

## Test Requirements

### Test file: `tests/test_bf069_llm_health.py`

**LLM Client Health Tracking (9 tests):**
1. `test_health_status_all_operational` — fresh client, no failures → all tiers operational, overall operational
2. `test_health_status_single_tier_degraded` — 1-2 failures on one tier → that tier degraded, overall degraded
3. `test_health_status_single_tier_unreachable` — 3+ failures on one tier → that tier unreachable, overall degraded
4. `test_health_status_all_unreachable` — 3+ failures on all tiers → overall offline
5. `test_failure_counter_resets_on_success` — successful call resets consecutive failures to 0
6. `test_failure_counter_increments_on_connect_error` — httpx.ConnectError increments counter
7. `test_failure_counter_increments_on_timeout` — httpx.TimeoutException increments counter
8. `test_failure_counter_increments_on_http_error` — httpx.HTTPStatusError increments counter
9. `test_connectivity_check_resets_counters` — successful `check_connectivity()` resets failure counters

**VitalsMonitor Extension (4 tests):**
10. `test_vitals_includes_llm_health` — `collect_metrics()` includes `llm_health` key
11. `test_vitals_threshold_llm_offline_alert` — LLM offline triggers medical_alert with severity critical
12. `test_vitals_threshold_llm_degraded_alert` — LLM degraded triggers medical_alert with severity warning
13. `test_vitals_no_alert_when_operational` — LLM operational triggers no medical_alert

**BridgeAlertService Extension (5 tests):**
14. `test_bridge_alert_llm_offline` — overall offline → ALERT severity, "Communications Array Offline"
15. `test_bridge_alert_llm_degraded` — overall degraded with unreachable tiers → ADVISORY severity
16. `test_bridge_alert_llm_operational_no_alert` — overall operational → no alerts
17. `test_bridge_alert_llm_dedup` — same alert suppressed within cooldown period
18. `test_bridge_alert_llm_dedup_different_tiers` — different tier combinations get different dedup keys

**System Endpoint (3 tests):**
19. `test_system_services_includes_llm_proxy` — `/api/system/services` includes "LLM Proxy" entry
20. `test_system_services_llm_status_mapping` — operational→online, degraded→degraded, offline→offline
21. `test_llm_health_endpoint` — `/api/system/llm-health` returns per-tier detail

**Proactive Loop Failure Visibility (4 tests):**
22. `test_proactive_failure_count_increments` — failed proactive think increments counter
23. `test_proactive_failure_count_resets_on_success` — successful post resets counter to 0
24. `test_proactive_failure_logged` — failed result logs a warning
25. `test_proactive_failure_count_property` — `llm_failure_count` property returns current count

**Total: 25 tests**

---

## Build Checklist

1. Read this entire prompt before starting
2. Read all files referenced in this prompt
3. Implement Deliverable 1 (LLM health tracking in llm_client.py)
4. Implement Deliverable 2 (VitalsMonitor extension)
5. Implement Deliverable 3 (BridgeAlertService extension)
6. Implement Deliverable 4 (System services endpoint + HXI)
7. Implement Deliverable 5 (Proactive loop failure visibility)
8. Implement Deliverable 6 (Event type) only if wiring is clean
9. Write all 25 tests in `tests/test_bf069_llm_health.py`
10. Run targeted tests: `python -m pytest tests/test_bf069_llm_health.py -v`
11. Run related tests: `python -m pytest tests/ -k "llm or vitals or bridge_alert or system" -v`
12. Fix any failures
13. Commit with message: `BF-069: LLM proxy health monitoring & alerting (25 tests)`

---

## Notes on BF-069 and Adjacent ADs

This fix creates the **detection + alerting foundation** that three future ADs will build on:
- **AD-459** (Saucer Separation) will use `get_health_status()` for its separation trigger ("LLM unreachable >30s")
- **AD-461** (Ship's Telemetry) will add performance metrics alongside the health status (latency, tokens)
- **AD-469** (EPS) will use tier health status for capacity-aware routing

Design the `get_health_status()` API so these consumers can use it without modification. The return shape defined above is intentionally simple and extensible.
