# Review: AD-467 — Operations Crew (Resource / Scheduler / Coordinator)

**Reviewer:** Architect (verify-first review of own draft)
**Date:** 2026-05-01
**Verdict:** ⚠️ **Conditional** — `ResourceAllocatorAgent` uses phantom attribute `active_count` on `ResourcePool` (live attribute is `current_size`). Defensive `getattr(..., 0)` masks the bug — capacity always reports active=0. Mechanical fix.

Section 7 SEARCH/REPLACE blocks correctly anchor on the AD-457 engineering crew block (verified live at `runtime.py:630-632` and `agent_fleet.py:148-164`). Pool naming `operations_<role>` follows the established `medical_<role>` / `engineering_<role>` convention. Anchor-chain fallback complete.

---

## Required (must fix before building)

### 1. `ResourcePool.active_count` is a phantom attribute

Section 2 `ResourceAllocatorAgent.collect_metrics()`:

```python
target = int(getattr(pool_obj, "target_size", 0) or 0)
active = int(getattr(pool_obj, "active_count", 0) or 0)
```

Verified — `ResourcePool` has `target_size` (✅) but NOT `active_count`:

```
grep -n "active_count\|current_size\|def __init__" src/probos/substrate/pool.py
  26: def __init__(
  53: def current_size(self) -> int:
  187: if self.current_size >= self.max_size:
  207: if self.current_size <= self.min_size:
  245: "current_size": len(self._agent_ids),
```

The live attribute is `current_size` (a `@property` at line 53). The defensive `getattr(pool_obj, "active_count", 0)` silently returns 0 — meaning every pool's capacity report shows `active=0`. The `RESOURCE_ALLOCATED` event then fires with always-empty capacity data. This is theater dressed as observation.

**Action:** Replace `active_count` with `current_size`:

```python
active = int(getattr(pool_obj, "current_size", 0) or 0)
```

`current_size` is a `@property` (`pool.py:53`) so `getattr` is correct usage — but the attribute name must match.

Alternatively, the same `ResourcePool.to_dict()` at `pool.py:244-245` exposes both `target_size` and `current_size` as a dict — using that path would be more idiomatic:

```python
try:
    info = pool_obj.to_dict()
    capacity[pool_name] = {
        "active": info.get("current_size", 0),
        "target": info.get("target_size", 0),
    }
except Exception:
    continue
```

Either fix is acceptable; the second is more durable to future ResourcePool changes.

### 2. `getattr(pool_obj, "active_count", 0)` is the AD-467-introduced phantom — anti-pattern flagged in copilot-instructions.md

The defensive `getattr(...)` for an API the prompt does NOT introduce is exactly the anti-pattern in `.github/copilot-instructions.md`:

> Defensive `getattr(obj, "method", None)` for APIs defined in the same prompt.

In this case the API is NOT defined in the same prompt — it doesn't exist at all. The defensive guard with default 0 silently masks the missing API. After Required #1 fix the guard is fine for `current_size` (which exists).

**Action:** part of Required #1 — the fix removes the anti-pattern by using a real attribute.

---

## Recommended

### 1. `_emit_interval_seconds = 60.0` overlaps with `interval = 30.0`

Section 2:

```python
def __init__(
    self,
    pool: str = "operations_resource",
    interval: float = 30.0,
    **kwargs: Any,
) -> None:
    ...
    self._emit_interval_seconds: float = kwargs.get("emit_interval_seconds", 60.0)
```

The agent runs `collect_metrics` every 30 seconds (heartbeat) but only emits `RESOURCE_ALLOCATED` every 60 seconds. The reasoning is to cap event-bus traffic. Document the rationale in the docstring — operators reading the code will wonder why two intervals exist.

Better: collapse to a single `emit_interval_seconds` field; let the heartbeat run at its own cadence and only emit when the throttle window expires.

### 2. `SchedulerAgent._task_cadences` defaults are placeholders without consumers

```python
self._task_cadences: dict[str, float] = kwargs.get(
    "task_cadences",
    {
        "operations_audit": 3600.0,
        "operations_summary": 86400.0,
    },
)
```

These two task names have no consumer in v1. The prompt's "What This Does NOT Change" notes this:

> v1 emits `TASK_SCHEDULED`, `WORKFLOW_STARTED`, `RESOURCE_ALLOCATED` events, but no production handler currently consumes them.

OK for v1 — operator dashboards and AD-467b will wire consumers. But the task names should match the language the operator/Captain would use. `operations_audit` is generic; `runtime_audit` or `pool_capacity_review` is more specific. Cosmetic, builder discretion.

### 3. `CoordinatorAgent.start_workflow` returns False on duplicate, but no event emit

Section 4:

```python
if workflow_name in self._active_workflows:
    return False
```

On rejection, no event fires. The operator querying "why did my workflow start fail?" gets no audit trail. Add a `WORKFLOW_REJECTED` event (new EventType) or reuse `WORKFLOW_STARTED` with a `rejected: bool` field.

For v1 this is a Recommended-class enhancement. The current behavior is "log to logger.info" which is observable but not in the audit log surface.

### 4. `to_dict()` integration in Required #1 fix — verify ResourcePool.to_dict() exists

Required #1 alternative fix uses `pool_obj.to_dict()`. Verified:

```
grep -n "def to_dict" src/probos/substrate/pool.py
  238: def to_dict(self) -> dict[str, Any]:
```

✅ `to_dict()` exists. Builder may prefer this path for durability against future ResourcePool changes.

### 5. Test 7 (`test_resource_allocator_collect_metrics_emits_capacity`) — verify after Required #1 fix

```
"capacity dict populated, emit fires after first cycle"
```

After Required #1 fix, the test must assert `capacity[pool_name]["active"]` reflects `current_size`, not 0. Update the test to use a fake pool with a real `current_size` value.

---

## Nits

### 1. Footer line drift on `runtime.emit_event`

Footer says line 775; actual is 785 (verified). Off by 10. Update.

### 2. `SchedulerAgent.intent_descriptors: list[IntentDescriptor]` annotation

Type annotation `list[IntentDescriptor]` on the class attribute is correct. Mirrors AD-457 `MaintenanceAgent` precedent. ✅

### 3. `CoordinatorAgent._active_workflows: dict[str, dict[str, Any]]` — not exposed publicly

The internal state is private. No public read API for `active_workflows` beyond the heartbeat metric. Operators/HXI will want to query active workflows directly — defer to AD-467b WorkflowDefinition API endpoint scope (already documented).

### 4. AD-467 introduces 3 EventTypes; AD-528 introduces 2. Total Wave 7 EventType count

Cross-prompt summary: 3 + 2 + 3 + 2 + 2 = 12 new EventTypes across Wave 7. All distinct. ✅

---

## Verified

### Public-attribute wiring (Wave-5 convention #1) — ✅ N/A

AD-467 agents are pool-spawned (no runtime attribute). The runtime attribute path is N/A; agents are accessed via `runtime.pools["operations_*"]`. Consistent with AD-457 precedent.

### stdlib-only persistence (Wave-5 convention #2) — ✅ Applied

No new pyproject deps. Uses `time`, `dataclasses` — all stdlib.

### Coordinator-then-dispatch (Wave-5 convention #3) — ✅ Applied

v1 ships 3 agents that emit events. Consumer wiring (WorkflowDefinition API, Response-Time Scaling, LLM Cost Tracker) deferred to AD-467b/c/d. ✅

### Superset-filter discipline (Wave-5 convention #4) — ✅ Applied

No insertion into existing flows. Three new agents in net-new `operations_*` pool family.

### `init_<phase>` startup signatures (Wave-5 convention #5) — ✅ Applied

Section 7 wiring placed in `runtime.py` and `agent_fleet.py` (which receives `runtime` directly). ✅

### Verify-first for anchors (Wave-5 convention #6) — ⚠️ Required #1

The footer claims `getattr(pool_obj, "active_count", 0)` is a defensive read of an existing attribute. Verified — `active_count` does NOT exist on ResourcePool. Required #1.

The footer is missing the critical grep:

```
grep -n "active_count\|current_size" src/probos/substrate/pool.py
```

This grep would have caught the phantom.

### No-theater discipline (Wave-5 convention #7) — ⚠️ Required #1

Before fix: capacity reporting silently shows `active=0` always. After fix: real values. Required #1 resolution moves AD-467 from soft-theater to real-work.

### TYPE_CHECKING cross-layer imports (Wave-6 note) — ✅ N/A

Three agents are HeartbeatAgent subclasses (substrate); no cross-layer imports.

### ASCII-only source comments (Wave-6 note) — ✅ Applied

Verified — no unicode arrows / em-dashes in source code blocks.

### Anchor-chain fallback (Wave-6 note) — ✅ Applied

Section 6 anchor chain terminates at `orders: OrdersConfig = OrdersConfig()  # AD-440`. ✅ Five fallback levels documented.

### Section 0 EventTypes — ✅ Clean

`RESOURCE_ALLOCATED`, `TASK_SCHEDULED`, `WORKFLOW_STARTED` — verified absent in `events.py`. No collision with other Wave 7 prompts.

### Directory ownership — ✅ Documented

AD-467 explicitly owns `src/probos/agents/operations/__init__.py` creation (mirrors AD-457).

### Section 7 SEARCH/REPLACE anchors — ✅ Verified live

```
grep -n "register_template..performance_monitor\|register_template..maintenance\|register_template..damage_control" src/probos/runtime.py
  630: self.spawner.register_template("performance_monitor", PerformanceMonitorAgent)
  631: self.spawner.register_template("maintenance", MaintenanceAgent)
  632: self.spawner.register_template("damage_control", DamageControlAgent)
```

✅ AD-467's Section 7a SEARCH anchor matches verbatim.

```
view src/probos/startup/agent_fleet.py:148-164
  148: # AD-457: Engineering crew -- Performance / Maintenance / Damage Control
  149: if config.engineering.enabled:
  150: eng_cfg = config.engineering
  ...
  164: ... interval=interval,
```

✅ AD-467's Section 7b SEARCH anchor matches verbatim.

### Pool naming convention — ✅ Applied

`operations_resource`, `operations_scheduler`, `operations_coordinator` — matches `medical_<role>` and `engineering_<role>` convention. Avoids collision with `operations_officer` (AD-398 cognitive officer at `runtime.py:620`). ✅

### Tier classification — ⚠️ Cosmetic

The dispatch's high-priority verification noted: "The 3 operations agents (Resource Allocator, Scheduler, Coordinator) are utility-tier per the AD-457 precedent." But AD-467's Section 2-4 set `tier = "core"` on all three, matching AD-457's three agents (which also use `tier = "core"`). Consistent with the AD-457 precedent on tier; the dispatch's "utility-tier" language was inaccurate. AD-467 follows the existing AD-457 pattern correctly.

### `ResourcePool.target_size` exists — ✅ Verified

`pool.py:42 self.target_size = target_size or config.default_pool_size`. Used at line 78, 145, 244. ✅

### Cross-AD dependencies — ✅ Documented

AD-467d LLM Cost Tracker explicitly waits on AD-463 ModelRegistry. Documented in "What This Does NOT Change."

### Test plan — ⚠️ 13 tests but Test 7 needs Required #1 update

After Required #1 fix, Test 7 must reflect the new attribute name (`current_size`). Update.

---

## Verdict Summary

**Two blocking issues (one underlying cause):**
1. `ResourcePool.active_count` is phantom — use `current_size` (`pool.py:53`).
2. Defensive `getattr(..., 0)` masks the missing attribute — anti-pattern flagged in copilot-instructions.md. Resolved by Required #1 fix.

**5 Recommended findings:** docstring polish, naming clarity, audit completeness, alternative fix path, test update.

**4 Nits:** cosmetic.

**Wave-5/6 conventions:** all applied except convention #6 (verify-first slipped on `active_count` phantom) and convention #7 (theater consequence of #6). Required #1 resolves both.

**Build-readiness after fix:** ~10 minutes architect time. Single-line change in Section 2 (or 4-line change for the `to_dict()` alternative).

**Recommended build order:** AD-467 fourth in Wave 7 (after AD-466, AD-456, AD-528). Owns `agents/operations/` directory creation; anchors on Wave-6 AD-457 blocks.

---

## Second-Pass Review (2026-05-01)

**Verdict:** ✅ **Approved** — phantom `active_count` replaced with real `current_size` (`@property` at `pool.py:53`); defensive `getattr(..., 0)` preserved per superset-filter discipline; no new issues introduced.

### Resolution Audit

| Pass-1 Required | Status | Evidence in revised prompt |
|---|---|---|
| R#1: ResourcePool.active_count phantom | ✅ Resolved | Section 2 line 144: `active = int(getattr(pool_obj, "current_size", 0) or 0)`. Inline comment cites verification: "ResourcePool.current_size is a @property at pool.py:53; ResourcePool.target_size is an instance attribute at pool.py:42." Verified at `substrate/pool.py:53`. |
| R#2: defensive getattr anti-pattern | ✅ Resolved | The `getattr(..., 0)` is now correct usage — `current_size` exists as a `@property` on real ResourcePool instances; the defensive default handles test stubs that may not include the attribute. NOT a phantom mask. |

| Pass-1 Recommended | Status | Notes |
|---|---|---|
| rec#1: emit-throttle interval rationale | ✅ Applied | Section 2 docstring documents the two-interval design. |
| rec#2: _task_cadences default names | 📦 Deferred | Naming acceptable for v1; AD-467b consumers may rename. |
| rec#3: WORKFLOW_REJECTED EventType | 📦 Deferred | Scope expansion; AD-467b can add. |
| rec#4: to_dict() alternative | ✅ Applied | Documented in Builder note as alternative. |
| rec#5: Test 7 update | ✅ Applied | Test 7 description rewritten: "fake runtime with 2 pools; each pool exposes `current_size` and `target_size` attributes -> `capacity` dict populated with real `{active, target}` integers (e.g., `{"active": 3, "target": 5}`)." |

| Pass-1 Nits | Status | Notes |
|---|---|---|
| nit#1: footer line drift | ✅ Applied | `runtime.emit_event` line corrected. |
| nit#2, #3, #4 | ✅ N/A | Cosmetic. |

### New Findings (introduced during revision)

None.

### Verified Against Revised Codebase Claims

- `ResourcePool.current_size` `@property` at `substrate/pool.py:53` — confirmed.
- `ResourcePool.target_size` instance attribute at `substrate/pool.py:42` — confirmed.
- `ResourcePool.to_dict()` at `substrate/pool.py:244` — confirmed; documented as alternative path in Section 2 Builder note.
- All references in revised prompt body use `current_size` (zero `active_count` references in Section 2 code).
- Defensive `getattr(..., 0)` is preserved (handles test-stub edge cases per Wave 5 superset-filter discipline #4).
- Section 7a SEARCH/REPLACE anchor (`runtime.py:630-632`) verified post-Wave 6.
- Section 7b SEARCH/REPLACE anchor (`agent_fleet.py:148-164`) verified post-Wave 6.

### Cross-Cutting Convention Audit

| Cross-cutting fix | Applied? | Evidence |
|---|---|---|
| Phantom-API fix: AD-467 active_count | ✅ Applied | `current_size` substituted; defensive guard preserved. |

### Verdict

**✅ Approved.** Build-ready as AD-467 fourth in Wave 7. Single-line mechanical fix applied cleanly.
