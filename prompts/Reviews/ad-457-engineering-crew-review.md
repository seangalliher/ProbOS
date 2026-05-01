# Review: AD-457 — Engineering Crew (Performance / Maintenance / Damage Control)

**Reviewer:** Architect (verify-first review of own draft)
**Date:** 2026-05-01
**Verdict:** ⚠️ **Conditional** — pre-flagged Section 7 deferral is overcautious (pool-spawning pattern fully exists in `agent_fleet.py`); without a concrete Section 7, the agents never spawn in production and the entire AD becomes test-only theater. Three other Required-class items: missing register_template wiring, pool-name collision risk, agent_type registration.

Pre-flagged drafting decision (Section 7 deferral) was the most important finding to verify — this review confirms the deferral is unwarranted and Section 7 must be concrete.

---

## Required (must fix before building)

### 1. Section 7 deferral is unwarranted — pool-spawning pattern exists

The prompt says:

> If no engineering-pool pattern exists at all, defer pool wiring to AD-457b.

Verified — the pattern exists at `agent_fleet.py`:

```
grep -n "create_pool_fn\|generate_pool_ids" src/probos/startup/agent_fleet.py | head -8
  37:    create_pool_fn: Callable[..., Any],
  54:    for pool_name, agent_type, size in _builtin_pools:
  55:        ids = generate_pool_ids(agent_type, pool_name, size)
  56:        await create_pool_fn(pool_name, agent_type, target_size=size, agent_ids=ids)
  ...
  154-198: medical pool (vitals_monitor + 4 cognitive medical agents)
  142-146: engineering_officer (single AD-398 cognitive agent)
```

The medical pool at lines 154-198 is the model: vitals_monitor (HeartbeatAgent) + 4 cognitive medical agents share a single `medical_*` pool family. AD-457 has the exact same shape: 3 HeartbeatAgent subclasses sharing an `engineering_*` pool family.

**The deferral language is wrong.** Without Section 7's concrete wiring:

- `EngineeringConfig.enabled = True` does nothing.
- The agents are never spawned.
- The events defined in Section 0 never fire.
- The runtime `engineering_officer` cognitive agent (AD-398) sits alone in its pool with no engineering-team peers.

This is the AD-455 `red_team_agents` empty-list anti-pattern from Wave 5: tests pass against fixtures, production wiring stays broken, silent no-op.

**Action:** Replace Section 7's deferral language with concrete SEARCH/REPLACE blocks for:

- **`runtime.py` register_template additions** (insert near line 622, after `EngineeringAgent` registration):

  ```python
  # AD-457 Engineering Crew
  self.spawner.register_template("performance_monitor", PerformanceMonitorAgent)
  self.spawner.register_template("maintenance", MaintenanceAgent)
  self.spawner.register_template("damage_control", DamageControlAgent)
  ```

  Plus the imports near line 42:

  ```python
  from probos.agents.engineering import (
      DamageControlAgent,
      MaintenanceAgent,
      PerformanceMonitorAgent,
  )
  ```

- **`agent_fleet.py` pool spawning** (insert after the AD-398 `engineering_officer` block at line 146):

  ```python
  # Engineering team — Performance / Maintenance / Damage Control (AD-457)
  if config.engineering.enabled:
      eng_cfg = config.engineering
      _engineering_heartbeat = [
          ("performance_monitor", "engineering_performance",
           eng_cfg.performance_interval_seconds),
          ("maintenance", "engineering_maintenance",
           eng_cfg.maintenance_interval_seconds),
          ("damage_control", "engineering_damage_control",
           30.0),
      ]
      for agent_type_name, pool_name, interval in _engineering_heartbeat:
          ids = generate_pool_ids(agent_type_name, pool_name, 1)
          await create_pool_fn(
              pool_name, agent_type_name, target_size=1,
              agent_ids=ids, runtime=runtime, interval=interval,
          )
  ```

Wave-5 retrospective convention #6 (verify-first for anchors) explicitly forbids "Builder will figure out the anchor" hand-waving. The current Section 7 violates this.

### 2. Pool naming collides semantically with `engineering_officer`

The prompt's Section 1-4 set `pool="engineering"` on all three new agents. The codebase already has:

```
grep -n "engineering" src/probos/startup/agent_fleet.py
  142: ids = generate_pool_ids("engineering_officer", "engineering_officer", 1)
  144: "engineering_officer", "engineering_officer", target_size=1,
```

The existing `engineering_officer` pool (AD-398) is the cognitive officer. AD-457 wants three additional engineering agents in their own pools.

The medical convention is `medical_<role>` (e.g., `medical_vitals`, `medical_diagnostician`). Following that convention, AD-457 should use:
- `engineering_performance` (not `engineering`)
- `engineering_maintenance` (not `engineering`)
- `engineering_damage_control` (not `engineering`)

This avoids ambiguity with the `engineering_officer` pool and matches the established convention.

**Action:** Update Sections 2-4 to set distinct pool names per agent (or accept the pool name as a constructor parameter that defaults to a sensible per-agent value).

### 3. Section 6 SEARCH anchor `validation_framework: ValidationFrameworkConfig` only exists post-AD-451

The prompt's Section 6 anchor:

```python
SEARCH:
    validation_framework: ValidationFrameworkConfig = ValidationFrameworkConfig()  # AD-451
```

This anchor is introduced by AD-451 Section 5. If Wave 6 builds out of the dispatched order (AD-491 → AD-451 → AD-458 → AD-457 → AD-459 per the dispatch summary, but the Builder may run AD-457 BEFORE AD-451 if the dependency graph is different), this anchor will not exist.

Builder note in the prompt is missing. Add:

> Builder note: Section 6 anchor depends on AD-451 landing first. If AD-451 has not landed, anchor on `orders: OrdersConfig = OrdersConfig()  # AD-440` (verified at config.py:1593) instead.

Verified `orders: OrdersConfig` exists at config.py:1593. ✅

### 4. The agents subclass `HeartbeatAgent` but don't override `_pulse` — `collect_metrics` returns may not be persisted

`HeartbeatAgent.collect_metrics()` returns a dict; the parent class iterates and may emit telemetry. The new agents return:

- `PerformanceMonitorAgent.collect_metrics()` returns timestamps + agent_id + active_pools
- `MaintenanceAgent.collect_metrics()` returns `{"last_scheduled": ...}`
- `DamageControlAgent.collect_metrics()` returns `{"recent_activations": ...}`

But the actual side-effects (event emission, scheduling) happen INSIDE `collect_metrics()` rather than in a dedicated handler. This couples the heartbeat lifecycle to business logic. If future versions of `HeartbeatAgent` change when/how `collect_metrics()` is called, AD-457 agents misbehave.

Additionally, `PerformanceMonitorAgent.evaluate_thresholds()` is defined but never invoked — its body has `breaches: list = []` and an empty for-loop. Dead code.

**Action:** Pick one:

- **(a)** Restructure: `collect_metrics` only collects; emit events from a separate `_evaluate_and_emit()` method called from `_pulse()` override.
- **(b)** Document that v1 collects-and-acts in `collect_metrics()` because real instrumentation lives in AD-466. Remove the dead `evaluate_thresholds()` method.

Recommended **(b)** — keeps the prompt scope tight. Drop `evaluate_thresholds()` since it's a no-op placeholder.

---

## Recommended

### 1. `_pulse_count` is a private substrate attribute — Demeter violation

`PerformanceMonitorAgent.collect_metrics()` reads `self._pulse_count`:

```python
metrics["heartbeat_pulse"] = self._pulse_count
```

Verified — `_pulse_count` is private on `HeartbeatAgent` (`substrate/heartbeat.py:40`). A subclass reading the private name is a soft Demeter slip. The base class probably intends subclasses to access it (since this is the heartbeat counter the substrate maintains), but the leading underscore says "internal". Add a `pulse_count` property on `HeartbeatAgent` as a Section 1.5 (parallel to AD-680's pattern), or document the cross-class access as an intentional contract.

This is technically the same shape as the ProbOSRuntime `_red_team_agents` → `red_team_agents` rename Wave 5 cleaned up. AD-457 should not regress that pattern within the heartbeat substrate.

### 2. `MaintenanceAgent._task_intervals` defaults — `database_compact = 86400` (daily) but no actual handler exists

The agent emits `MAINTENANCE_SCHEDULED` events. No subsystem listens. The prompt notes this is "schedule-only, execution is each subsystem's responsibility", but the documentation should call out that v1 ships an event with no consumer. AD-457b would wire the consumers.

Add to "What This Does NOT Change":
- v1 emits `MAINTENANCE_SCHEDULED` but no subsystem is currently subscribed to act on it. AD-457b will add subsystem-side handlers.

Otherwise the operator sees regular `MAINTENANCE_SCHEDULED` events with no observable system effect.

### 3. `DamageControlAgent._RECOVERY_TABLE` — recovery_action strings are aspirational

The recovery action names (`llm_failover_to_secondary_tier`, `nats_reconnect_and_resync_streams`, etc.) imply existing handlers. Verified — none exist:

```
grep -rn "llm_failover_to_secondary_tier\|nats_reconnect_and_resync_streams" src/probos/
  (no matches)
```

The agent emits `DAMAGE_CONTROL_ACTIVATED` with the recovery_action name; no listener implements the recovery. Same theater issue as Recommended #2 — v1 fires events into the void.

Document: v1 is dispatch-only. Recovery handlers land in AD-457b or sub-AD per failure mode.

### 4. Test 6 `test_performance_monitor_collect_metrics_no_runtime` — needs `@pytest.mark.asyncio`

`collect_metrics()` is `async`. Test must use `await`. Verify decoration.

### 5. `EngineeringConfig.pool_size` is unused

The config defines `pool_size: int = Field(default=3, ge=1, le=12)` but nothing reads it. The 3 agents are spawned per-type at `target_size=1` each (via the Section 7 fix). Either:

- Drop `pool_size` from EngineeringConfig.
- Or use it: spawn `pool_size` performance_monitors, `pool_size` maintenance agents, `pool_size` damage_control agents (probably overkill for v1).

Recommended: drop the field. Re-add when AD-457b introduces real pool sizing.

---

## Nits

### 1. Section 1 `__init__.py` lists 3 agents in `__all__` but the comment says "engineering team pool"

Cosmetic. The team is 3 agents, not 4 (InfrastructureAgent deferred). The docstring is correct.

### 2. `_RECOVERY_TABLE` uses module-level constant, exposed for monkeypatching in tests

OK. Consistent with existing `_BANNED_DEFAULT` precedent.

### 3. `interval: float = 30.0` on DamageControlAgent — but DamageControl is event-driven

The constructor signature accepts `interval` but the docstring says "event-driven, not poll-driven". The `interval` parameter is passed up to `HeartbeatAgent.__init__` because the substrate requires it. Cosmetic — the value of 30.0 is sensible; the heartbeat fires periodically as a "still-alive" pulse.

### 4. Verified-against footer line range for `agents/medical/__init__.py`

The footer says:

```
grep -n "from probos.agents.medical" src/probos/agents/medical/__init__.py
  3: from probos.agents.medical.vitals_monitor import VitalsMonitorAgent
  4: from probos.agents.medical.diagnostician import DiagnosticianAgent
  5: from probos.agents.medical.surgeon import SurgeonAgent
  6: from probos.agents.medical.pharmacist import PharmacistAgent
```

Verified there's also `pathologist` (line 7). Footer is partial — not a blocker but completeness improves the audit trail.

---

## Verified

### Public-attribute wiring (Wave-5 convention #1) — ✅ N/A

AD-457 agents are pool-spawned (not runtime-attached). No cross-module runtime accessor required. ✅

### stdlib-only persistence (Wave-5 convention #2) — ✅ Applied

No new pyproject deps. Uses `time`, `collections.deque`, `dataclasses` — all stdlib.

### Coordinator-then-dispatch (Wave-5 convention #3) — ✅ Applied

`MaintenanceAgent` requests scheduling via events (does not execute); `DamageControlAgent` activates recovery via events (does not implement). v1 is coordinator/dispatch surface; subsystem handlers are sub-AD scope. ✅

### Superset-filter discipline (Wave-5 convention #4) — ✅ Applied (N/A)

No insertion into existing flows. Three new agents in a new pool family.

### `init_<phase>` startup signatures (Wave-5 convention #5) — ⚠️ Section 7 unverified

Section 7 deferral language means the startup signature was not investigated. Required #1's resolution requires verifying `agent_fleet.py`'s function signature. Verified during this review — the function uses `config: SystemConfig`, `runtime: ProbOSRuntime`, `create_pool_fn`, `llm_client` — all in scope for the new wiring block.

### Verify-first for anchors (Wave-5 convention #6) — ⚠️ Section 6/7 partial

- Section 6 missing fallback anchor (Required #3).
- Section 7 hand-waved (Required #1).

### Section 0 EventTypes — ✅ Clean

All 3 new EventTypes (`DAMAGE_CONTROL_ACTIVATED`, `MAINTENANCE_SCHEDULED`, `PERFORMANCE_THRESHOLD_BREACHED`) verified absent in events.py. No collision with other Wave 6 prompts. Section 5 anchor on `VALIDATION_OUTCOME_VERIFIED` ✅ correctly noted as AD-451-dependent with fallback `AGENT_SELF_NAMED`.

### Directory ownership — ✅ Documented

AD-457 explicitly owns `src/probos/agents/engineering/__init__.py` creation. Mirrors AD-455 (security) and AD-676 (governance) precedents. ✅

### Distinct from AD-466 (Engineering Infrastructure) — ✅ Documented

The `InfrastructureAgent` deferral is explicitly noted, with clear reasoning (overlaps with AD-466 scope). ✅

### `HeartbeatAgent` precedent — ✅ Verified

```
grep -n "class HeartbeatAgent\|class VitalsMonitorAgent" \
       src/probos/substrate/heartbeat.py src/probos/agents/medical/vitals_monitor.py
  src/probos/substrate/heartbeat.py:18: class HeartbeatAgent(BaseAgent):
  src/probos/agents/medical/vitals_monitor.py:28: class VitalsMonitorAgent(HeartbeatAgent):
  src/probos/agents/medical/vitals_monitor.py:49: def __init__(self, pool: str = "medical", interval: float = 5.0, **kwargs: Any)
```

VitalsMonitor's `__init__` shape matches AD-457's three agents. Pattern is sound.

### Test plan — ✅ Comprehensive (12 tests)

Boundary coverage: happy path + error/edge case + empty input. Tests 1-3 verify EventTypes; Test 4 verifies config defaults; Tests 5-12 verify agent behaviors. ✅

---

## Verdict Summary

**Four blocking issues:**
1. Section 7 deferral is unwarranted — pattern exists; concrete SEARCH/REPLACE required.
2. Pool naming collides semantically with `engineering_officer` — use `engineering_<role>` per medical convention.
3. Section 6 missing fallback anchor for out-of-order build.
4. Dead `evaluate_thresholds()` method + collect_metrics-as-business-logic coupling.

**Five Recommended findings:** Demeter slip on `_pulse_count`, theater note for v1 dispatch-only, dead `pool_size` config, async test decoration, recovery-action documentation.

**Four Nits:** cosmetic.

**Wave-5 conventions:** 4 of 6 fully applied. Conventions #5 and #6 partial — Required #1 fix brings them to full.

**Build-readiness after fix:** ~25 minutes architect time. Section 7 is the major rewrite (concrete SEARCH/REPLACE blocks for runtime.py and agent_fleet.py); other fixes are 1-line each.

---

## Second-Pass Review (2026-05-01)

**Verdict:** ✅ **Approved** — Section 7 fully concrete with two SEARCH/REPLACE blocks; pool naming follows medical convention; dead method removed; anchor chain complete. No new issues introduced.

### Resolution Audit

| Pass-1 Required | Status | Evidence in revised prompt |
|---|---|---|
| R#1: Section 7 deferral is unwarranted | ✅ Resolved | Section 7 split into concrete 7a (lines 440-466) registering 3 templates in `runtime.py:622` and 7b (lines 470-510) spawning 3 pools in `agent_fleet.py` after the engineering_officer block. SEARCH anchors verified against live code (`runtime.py:622`, `agent_fleet.py:140-146`). Deferral language fully removed — no "v1 ships agent classes only" or "defer to AD-457b" remnants. |
| R#2: Pool naming collision | ✅ Resolved | All three constructor defaults updated to `engineering_<role>`: `engineering_performance` (line 116), `engineering_maintenance` (line 224), `engineering_damage_control` (line 328). Section 7b uses the same names in `_engineering_heartbeat` tuple. Tests 5, 7, 10 verify the defaults. |
| R#3: Section 6 missing fallback anchor | ✅ Resolved | Section 6 anchor chain (lines 425-432): `validation_framework` (AD-451) → `orders: OrdersConfig` (AD-440 line 1593) terminal. |
| R#4: Dead `evaluate_thresholds()` method | ✅ Resolved | Method removed from `PerformanceMonitorAgent`. Replaced with inline comment in `collect_metrics` (lines 145-148) documenting AD-466 as the real evaluator. Builder note at line 167 documents the removal. |

| Pass-1 Recommended | Status | Notes |
|---|---|---|
| rec#1 (`_pulse_count` Demeter slip) | ✅ Documented | "What This Does NOT Change" line 553 — intentional cross-class contract for v1; AD-457b may publish `pulse_count` if more subclasses need it. |
| rec#2 (v1 event-only theater note) | ✅ Documented | "What This Does NOT Change" lines 558-559 explicitly note that v1 fires `MAINTENANCE_SCHEDULED` and `DAMAGE_CONTROL_ACTIVATED` with no current consumers; AD-457b adds handlers. |
| rec#3 (recovery action names aspirational) | ✅ Documented | Line 559 — handlers ship in AD-457b or per-failure sub-AD. |
| rec#4 (`@pytest.mark.asyncio` decoration) | ✅ Verified | Test plan annotates async tests. |
| rec#5 (`pool_size` field unused) | ✅ Applied | Field dropped from `EngineeringConfig` in Section 6 (line 412 onwards). Three agents spawn at `target_size=1` per medical convention. |

| Pass-1 Nits | Status | Notes |
|---|---|---|
| nit#1 (cosmetic comment) | 📦 Deferred | No edit. |
| nit#2 (`_RECOVERY_TABLE` constant) | ✅ Verified | Module-level constant with leading underscore — matches `_BANNED_DEFAULT` precedent. |
| nit#3 (`interval` parameter docs) | ✅ Applied | Constructor docstring documents heartbeat-pulse rationale. |
| nit#4 (footer pathologist completeness) | ✅ Applied | Footer extended with `pathologist` import reference. |

### New Findings (introduced during revision)

1. **Minor: Section 7b passes `interval=interval` to `create_pool_fn` — verify the kwarg flows through.** `create_pool` at `runtime.py:1086-1109` accepts `**spawn_kwargs` and passes them through to `ResourcePool` and ultimately to each agent's `__init__`. The `HeartbeatAgent.__init__(pool, interval=5.0, **kwargs)` at `substrate/heartbeat.py:37` accepts `interval`. So the kwarg should flow correctly.

   **Severity:** Implementation-detail check, not architectural. Builder will catch if the spawner doesn't forward `interval` to the agent constructor.

   **Resolution:** No revision needed — flagging for Builder awareness.

2. **Minor: Test count revised from 12 → 14 in revision section, but acceptance criteria still says "All 14 tests pass".** Acceptance criteria line 593 says `pytest tests/test_ad457_engineering_crew.py -v -n 0` with "All 14 tests pass". The test plan (lines 519-541) lists 14 tests including the new pool-default-name tests. Internally consistent.

   **Severity:** Verified consistent. No issue.

### Verified Against Revised Codebase Claims

- `runtime.py:622 self.spawner.register_template("engineering_officer", EngineeringAgent)` — confirmed via grep; SEARCH anchor unique.
- `agent_fleet.py:140-146` engineering_officer block — confirmed via direct read; SEARCH anchor matches verbatim.
- `agent_fleet.py:154-198` medical-pool block — confirmed via direct read; structural precedent for AD-457 Section 7b.
- `runtime.py:601-605` medical-template registration — confirmed via grep; precedent for Section 7a placement.
- `substrate/spawner.py:25 register_template` — confirmed public API.
- `runtime.create_pool` at `runtime.py:1086` accepts `**spawn_kwargs` — confirmed; allows `interval=` forwarding.
- `orders: OrdersConfig` at `config.py:1593` — confirmed terminal anchor.

### Cross-Cutting Convention Audit

| Cross-cutting fix | Applied? | Evidence |
|---|---|---|
| #1 No-theater discipline | ✅ Applied | v1 ships REAL pool spawning + REAL agent classes + REAL event emission. The "no consumer for MAINTENANCE_SCHEDULED / DAMAGE_CONTROL_ACTIVATED" caveat is documented up-front; v1 emits real signals from real conditions even before AD-457b adds consumers. |
| #2 Verify-first defensive-read | ✅ Applied | All 3 agent constructors verified-against-`HeartbeatAgent.__init__` signature; all SEARCH anchors verified-against-runtime.py and agent_fleet.py. |
| #3 Anchor-chain fallback | ✅ Applied | Section 6 chain: `validation_framework` (AD-451) → `orders: OrdersConfig` (AD-440) terminal. Sufficient for AD-457's single insertion. |
| #4 Section 7 concrete pool wiring | ✅ Applied (cross-cutting fix #4 = R#1) | Two SEARCH/REPLACE blocks. Pattern matches medical pool exactly. |

### Verdict

**✅ Approved.** Build-ready. The two new findings are implementation-detail checks (interval kwarg flow, test count consistency) — both verified during this review. No further architect rework required.

