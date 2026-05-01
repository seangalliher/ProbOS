# Review: AD-459 — Saucer Separation (Graceful Degradation)

**Reviewer:** Architect (verify-first review of own draft)
**Date:** 2026-05-01
**Verdict:** ⚠️ **Conditional** — registry seed names don't match runtime attribute names where the docstring claims they do (`dreaming` vs `dream_scheduler`, `cognitive_agent` is a class not an attribute, `introspection_agent` does not exist as a runtime attribute). The coordinator-then-dispatch v1 pattern is structurally clean. Three Required-class items: docstring-vs-data mismatch, missing fallback anchor on Section 6, dead `enabled=False` path.

Highest blast radius of Wave 6 (touches `runtime.py`, `startup/finalize.py`, alert paths). Read-only v1 design correctly avoids the active-shedding minefield. AD-459b deferral is well-scoped.

---

## Required (must fix before building)

### 1. Registry seed names don't match runtime attribute names

The `ServiceTierRegistry` seed list (Section 2 line 93-107) declares 13 services. The class docstring says:

> Names match attribute names on ProbOSRuntime where possible to make grep-confirmation easy for operators.

Verifying each name against `runtime.<name>`:

| Seed name | Runtime attribute? | Status |
|---|---|---|
| `event_log` | `runtime.event_log` (line 314) | ✅ Match |
| `trust_network` | `runtime.trust_network` (line 335) | ✅ Match |
| `registry` | `runtime.registry` (line 293) | ✅ Match |
| `intent_bus` | `runtime.intent_bus` (line 300) | ✅ Match |
| `hebbian_router` | `runtime.hebbian_router` (line 304) | ✅ Match |
| `cognitive_agent` | (class, not attribute) | ❌ Mismatch |
| `dreaming` | `runtime.dream_scheduler` and `runtime.dream_adapter` exist; `runtime.dreaming` does NOT | ❌ Mismatch |
| `decomposer` | `runtime.decomposer` (line 352) | ✅ Match |
| `proactive_loop` | `runtime.proactive_loop` (line 533) | ✅ Match |
| `emergence_metrics_engine` | `runtime.emergence_metrics_engine` (property at line 951) | ✅ Match |
| `emergent_leadership_detector` | post-AD-439, set at finalize.py:344 | ✅ Match |
| `introspection_agent` | NO matches in runtime.py or finalize.py | ❌ Mismatch |
| `red_team_lead` | post-AD-455, set at finalize.py:422 | ✅ Match |

Three mismatches:

- **`cognitive_agent`** — `CognitiveAgent` is a class (`cognitive/cognitive_agent.py`), not a runtime attribute. There's no single runtime accessor; cognitive agents are spawned into pools. The "logical service name" approach works (subsystems can pass `"cognitive_agent"` when consulting `is_shed`), but the docstring claim "names match attribute names where possible" misleads. Recommend renaming to `cognitive_agents` (plural) and dropping the docstring claim, or replacing with a more concrete substrate name like `agents.medical` / `agents.science` for fine-grained shedding.

- **`dreaming`** — actual runtime attribute is `dream_scheduler` (line 411) and `dream_adapter` (line 483). Either:
  - (a) Rename the seed to `dream_scheduler` (matches reality, but loses the "dreaming" semantic).
  - (b) Keep `dreaming` as a logical name and document the mapping (`dreaming` includes both scheduler and adapter).

- **`introspection_agent`** — no runtime attribute exists by that name. The `IntrospectionAgent` is spawned into the `introspect` pool. Either rename to `introspect` (the pool name) or drop entirely (it's a Tier 0 utility agent that should arguably never be shed).

**Action:** Pick one consistent strategy:

- **(a)** All seed names match runtime attribute/property names. Drop `cognitive_agent`, `dreaming`, `introspection_agent` from the seed list; ship v1 with 10 verified-against-runtime names.
- **(b)** All seed names are logical service names. Drop the docstring claim. Document the mapping table in the prompt body (which logical name covers which runtime attributes).

Recommended **(a)** — matches the verify-first standing order. Logical names can be added in AD-459b when subsystems formally consume the registry.

### 2. Section 6 missing fallback anchor for out-of-order Wave 6 build

Section 6 anchors on:

```python
SEARCH:
    pre_flight: PreFlightConfig = PreFlightConfig()  # AD-458
```

Builder note acknowledges:

> anchor depends on AD-458 landing first. If not, anchor on the AD-457 `engineering:` line.

But what if AD-457 also hasn't landed? Wave 6 build order (per dispatch summary) is AD-491 → AD-451 → AD-458 → AD-457 → AD-459. If the Builder runs out of order (e.g., AD-459 first to test), no anchor exists.

**Action:** Add the AD-440 fallback anchor:

> Builder note: Section 6 anchors on AD-458 first, AD-457 second, AD-451's `validation_framework:` third, and AD-440's `orders: OrdersConfig` (config.py:1593) as the always-available fallback.

### 3. `DegradationConfig` only declares `enabled: bool = True` — `enabled=False` breaks `is_shed()` callers

`DegradationConfig` has only one field. If `enabled=False`:

```python
if config.degradation.enabled:
    runtime.degradation_manager = DegradationManager(...)
```

Then `runtime.degradation_manager` is unset. Subsystems that consult `runtime.degradation_manager.is_shed(...)` will `AttributeError`. The "v1 read-only coordinator" contract requires that consumers always have a manager to consult.

Either:

- **(a)** Always wire the manager; `enabled=False` means it always returns `False` from `is_shed()` (stress level pinned to NORMAL).
- **(b)** Provide a no-op `_NullDegradationManager` when disabled.

Recommended **(a)** — simpler, no second class needed:

```python
runtime.degradation_manager = DegradationManager(
    registry=ServiceTierRegistry(),
    policy=SheddingPolicy(),
    emit_event=runtime.emit_event,
)
if not config.degradation.enabled:
    # Pin to NORMAL — no shedding ever
    pass  # Default state is already NORMAL
```

But this leaves the manager always-on. The `enabled` flag becomes pointless. Drop the flag entirely from v1 and document in "What This Does NOT Change" — the manager is always wired; subsystems consulting `is_shed()` always get an answer.

**Action:** Remove the `enabled` flag OR document the contract that consumers must defensively check `getattr(runtime, "degradation_manager", None)`. Pick one.

### 4. `SheddingPolicy.shed_tiers()` for HIGH and CRITICAL are identical — operator differentiation is lost

Section 3 line 178-185:

```python
if level == StressLevel.HIGH:
    return frozenset(
        {ServiceTier.NON_ESSENTIAL, ServiceTier.COGNITIVE},
    )
# CRITICAL — same as HIGH; ESSENTIAL never shed
return frozenset(
    {ServiceTier.NON_ESSENTIAL, ServiceTier.COGNITIVE},
)
```

The four-level enum (`NORMAL`, `ELEVATED`, `HIGH`, `CRITICAL`) collapses to three behaviorally distinct outputs. CRITICAL and HIGH are identical. Either:

- **(a)** Drop one level — three-level enum (`NORMAL`, `ELEVATED`, `STRESSED`) is sufficient.
- **(b)** Differentiate CRITICAL — what's the additional shedding behavior? Maybe CRITICAL also drops `cognitive_agent` priority queues, or pauses async tasks below a priority threshold.
- **(c)** Document explicitly: "CRITICAL is reserved for AD-459b which will add an active-shedding hook (e.g., kill long-running agent tasks); HIGH and CRITICAL share the read-only sed mask in v1."

Recommended **(c)** — keeps the enum extensible, documents the v1/v2 split.

---

## Recommended

### 1. `DegradationStatus.shed_services` returns sorted list — but `services_in_tier` order is not sorted

Section 4 line 277-285:

```python
def status(self) -> DegradationStatus:
    shed = self._policy.shed_tiers(self._level)
    services: list[str] = []
    for tier in shed:
        services.extend(self._registry.services_in_tier(tier))
    return DegradationStatus(
        ...,
        shed_services=sorted(services),
        ...
    )
```

The `frozenset.shed_tiers` iteration is non-deterministic in CPython before 3.7+ (now insertion-order guaranteed for sets, but still platform-dependent for frozensets in some scenarios). Sorting at the end makes the output deterministic. ✅ Good.

But: tests should assert on the sorted list, not the iteration order. Test 13 description:

> `test_degradation_manager_is_shed_returns_correct_state` — `is_shed("dreaming")` is True at HIGH, False at NORMAL.

`is_shed("dreaming")` will return `False` regardless of stress level if Required #1 fix removes "dreaming" from the seed list. Update the test to use a verified seed name (e.g., `dream_scheduler`).

### 2. `SheddingPolicy` is `@dataclass(frozen=True)` but stores no fields

```python
@dataclass(frozen=True)
class SheddingPolicy:
    def shed_tiers(self, level: StressLevel) -> frozenset[ServiceTier]:
        ...
```

A frozen dataclass with no fields is functionally equivalent to a regular class with a method. The `@dataclass(frozen=True)` decoration is decorative noise. Either:

- Drop the decorator.
- Add a field: `policy_overrides: dict[StressLevel, frozenset[ServiceTier]] = field(default_factory=dict)` for runtime-extensible policy.

Recommended: drop the decorator. Future extensibility lives in subclasses or constructor args.

### 3. `set_stress_level` does not validate against config-controlled allow-list

Any caller can set the stress level to `CRITICAL`. There's no audit trail or capability gate. v1 is read-only on the shedding side, but the stress level itself is freely mutable. This is acceptable for v1 (deferred to AD-459b for capability-gated stress transitions), but document it explicitly:

> v1 contract: any code with a `runtime.degradation_manager` reference can call `set_stress_level(CRITICAL)`. No capability gate, no audit trail beyond the SERVICE_TIER_DEGRADED emit. AD-459b will add a `set_stress_level` capability gate for production use.

### 4. `_emit_tier_change` swallows exception silently

```python
try:
    self._emit_event(et, ...)
except Exception:
    logger.warning("AD-459: %s emit failed", et.value, exc_info=True)
```

Per copilot-instructions.md three-tier exception handling: this is "log-and-degrade" (tier 2). ✅ Correct for diagnostics.

But the warning should include the tier, level, and shed/restore flag — not just the EventType name:

```python
logger.warning(
    "AD-459: %s emit failed (tier=%s, level=%s, shed=%s)",
    et.value, tier.value, self._level.value, shed,
    exc_info=True,
)
```

### 5. Test 5 (`test_service_tier_registry_register_extends`) — verify the registry preserves seeds

Test description says `register(...)` adds a new classification. Verify the test ALSO asserts that existing seed classifications remain present after registration (i.e., `register` doesn't replace/clobber the seeds). One-line assertion add.

---

## Nits

### 1. `_DEFAULT_CLASSIFICATIONS` is a module-level constant — convention match

```
grep -rn "^_DEFAULT_" src/probos/cognitive/ | head -3
```

Existing pattern (e.g., `_BANNED_DEFAULT` in AD-499) uses leading underscore for module-private constants. ✅ Match.

### 2. `SERVICE_TIER_DEGRADED` and `SERVICE_TIER_RESTORED` are emitted by tier — not by service

The emit payload contains `"tier": tier.value`. Operators wanting "which specific service degraded?" must consult the registry. Acceptable for v1 (tier-level granularity), but document it:

> v1 emits at tier-level granularity. Service-level emits (e.g., "dreaming degraded") are deferred to AD-459b when subsystems hook into the manager directly.

### 3. `SheddingPolicy.shed_tiers` returns `frozenset` — order not guaranteed for emit

When transitioning NORMAL → HIGH, the emit fires for `NON_ESSENTIAL` then `COGNITIVE` (or vice versa). The `for tier in new_shed - prev_shed` iteration order is set-iteration order, not deterministic. Test 11 (`test_degradation_manager_set_stress_level_emits_tier_degraded`) should not assert on the order of emit calls.

Unless the test mocks `emit_event_fn` and asserts via `mock.call_args_list`. If so, sort the list before assertion.

### 4. Footer claim "ESSENTIAL never shed" — verify in test

Test 10 (`test_shedding_policy_critical_never_sheds_essential`) covers the policy invariant. ✅

But the test should also assert: even if a malicious caller sets a custom policy that includes ESSENTIAL in shed_tiers, the manager respects the policy verbatim (no extra ESSENTIAL guard). This is "policy is authority" — the manager doesn't override the policy.

If the design intent is "ESSENTIAL is hardcoded never-shed at the manager level (policy-overridable)", add a `_ESSENTIAL_NEVER_SHED: bool = True` invariant in the manager. Otherwise, document that ESSENTIAL safety is policy-controlled, not manager-controlled.

---

## Verified

### Public-attribute wiring (Wave-5 convention #1) — ✅ Applied

```
runtime.degradation_manager = DegradationManager(...)  # finalize.py
```

No leading underscore. ✅

### stdlib-only persistence (Wave-5 convention #2) — ✅ Applied

No new pyproject deps. Uses `dataclasses`, `enum`, `time`, `logging`, `typing` — all stdlib.

### Coordinator-then-dispatch (Wave-5 convention #3) — ✅ Applied (exemplary)

v1 is exactly the read-only coordinator pattern Wave 5 retrospective codified. `DegradationManager.is_shed()` is the read API; subsystems self-degrade. AD-459b deferral note explicitly documents the future active-shedding work. ✅

This is the canonical Wave 6 application of convention #3.

### Superset-filter discipline (Wave-5 convention #4) — ✅ Applied (N/A)

No insertion into existing flows. Net-new package.

### `init_<phase>` startup signatures (Wave-5 convention #5) — ✅ Applied

`startup/finalize.py` receives `runtime` directly. ✅

### Verify-first for anchors (Wave-5 convention #6) — ⚠️ Required #1 + Required #2

- Section 2 seed names violate verify-first (Required #1).
- Section 6 missing third fallback anchor (Required #2).

### Section 0 EventTypes — ✅ Clean

`SERVICE_TIER_DEGRADED` and `SERVICE_TIER_RESTORED` verified absent in events.py. No collision.

### Directory ownership — ✅ Documented

AD-459 owns `src/probos/degradation/__init__.py` creation. Mirrors AD-455 (security) and AD-676 (governance) precedents. ✅

### `bridge_alerts.AlertSeverity` orthogonality — ✅ Verified

```
grep -n "class AlertSeverity\|class BridgeAlert" src/probos/bridge_alerts.py
  24: class AlertSeverity(str, Enum):
  32: class BridgeAlert:
  47: class BridgeAlertService:
```

Severity-based incident reporting, distinct from AD-459 service tier classification. ✅ No overlap.

### v1 is read-only — ✅ Documented in prompt body and acceptance criteria

> "No subsystem files in `src/probos/cognitive/` are modified — v1 is read-only coordinator."

Verified — no SEARCH/REPLACE blocks in cognitive/ files. ✅

### Test plan — ⚠️ 13 tests, but Test 13 references "dreaming" which won't be in seed list after Required #1 fix

After Required #1 fix toward (a), Test 13 should reference a verified seed name (e.g., `dream_scheduler`).

Boundary coverage: happy + error + edge. ✅

### Cross-prompt anchor chain — ⚠️ Section 6 incomplete (Required #2)

Other anchors (Section 5 EventType anchors on AD-457's `PERFORMANCE_THRESHOLD_BREACHED`) have correct fallback notes. Section 6 needs the third fallback.

---

## Verdict Summary

**Four blocking issues:**
1. Registry seed names don't match runtime attribute names where the docstring claims they do — pick consistent strategy.
2. Section 6 missing AD-440 fallback anchor for out-of-order build.
3. `DegradationConfig.enabled=False` leaves `runtime.degradation_manager` unset — consumers AttributeError.
4. CRITICAL and HIGH stress levels are behaviorally identical — document or differentiate.

**Five Recommended findings:** test verification, decorator noise, capability gate documentation, log context, registry-preserves-seeds test assertion.

**Four Nits:** convention check, payload granularity, test ordering, ESSENTIAL safety invariant.

**Wave-5 conventions:** 5 of 6 fully applied. Convention #6 (verify-first) has Required-class issues that would have been caught by stricter footer audits during drafting.

**Build-readiness after fix:** ~25 minutes architect time. Required #1 is the largest (touches Section 2, Test 4, Test 13, the seed list); others are 1-line fixes.

**Wave 6 highest blast radius — recommend AD-459 ships LAST in build order** (its read-only contract benefits from observing how AD-457's engineering events fire, AD-451's reconciliation events fire, AD-491's entropy events fire). The dispatch summary's recommendation (AD-491 → AD-451 → AD-458 → AD-457 → AD-459) is correct.

---

## Second-Pass Review (2026-05-01)

**Verdict:** ✅ **Approved** — registry seed list purged of phantoms; always-wired contract honored; 4-level anchor chain to AD-440 terminal; HIGH/CRITICAL deferral documented. Read-only v1 design intact; no theater.

### Resolution Audit

| Pass-1 Required | Status | Evidence in revised prompt |
|---|---|---|
| R#1: Registry seed names don't match runtime | ✅ Resolved | Section 2 `_DEFAULT_CLASSIFICATIONS` (lines 92-108) ships 11 verified-against-runtime names. Removed: `cognitive_agent`, `dreaming`, `introspection_agent`. Added: `dream_scheduler` (matches `runtime.py:411`). Docstring rewritten (lines 86-89) to say "Each `service_name` matches an actual public attribute on `ProbOSRuntime` (verified via grep at draft time)" — aligns with reality. Logical-only names explicitly deferred to AD-459b in Sectioncomment lines 91-95. |
| R#2: Section 6 missing AD-440 fallback | ✅ Resolved | Section 6 anchor chain (lines 382-386) — 4 levels: `pre_flight` (AD-458) → `engineering` (AD-457) → `validation_framework` (AD-451) → `orders: OrdersConfig` (AD-440 line 1593) terminal. |
| R#3: `enabled=False` leaves manager unset | ✅ Resolved | Section 6 `DegradationConfig` (lines 354-366) has no fields — placeholder for AD-459b. Section 7 finalize wiring (lines 394-407) is unconditional — no `if config.degradation.enabled:` branch. Comment at lines 396-398 explicitly documents the always-wired contract. Default state is `StressLevel.NORMAL`. |
| R#4: HIGH/CRITICAL identical | ✅ Documented | Section 3 `SheddingPolicy.shed_tiers()` (lines 175-200) explicitly returns the same shed mask for HIGH and CRITICAL, with docstring (lines 184-188) and inline comment (lines 197-199) documenting that AD-459b will add CRITICAL-only active-shedding (cancel tasks, pause queues). 4-level enum preserved for AD-459b extensibility. Builder note at line 202 reinforces. |

| Pass-1 Recommended | Status | Notes |
|---|---|---|
| rec#1 (Test 13 references real seed) | ✅ Applied | Test 13 at line 432: `is_shed("dream_scheduler")` (real seed name) instead of phantom `dreaming`. |
| rec#2 (`@dataclass(frozen=True)` decorator noise) | ✅ Applied | Decorator dropped from `SheddingPolicy` at line 175. Stateless class with no fields. |
| rec#3 (`set_stress_level` no-capability-gate) | ✅ Documented | "What This Does NOT Change" line 449: explicit note that AD-459b adds the gate. |
| rec#4 (`_emit_tier_change` log context) | ✅ Applied | Section 4 `_emit_tier_change` warning (lines 297-301) now includes tier, level, shed flag in the message. |
| rec#5 (Test 5 preserves seeds) | ✅ Applied | Test 5 at line 425 renamed: `test_service_tier_registry_register_extends_and_preserves_seeds`. |

| Pass-1 Nits | Status | Notes |
|---|---|---|
| nit#1 (`_DEFAULT_CLASSIFICATIONS` constant convention) | ✅ Verified | Module-level constant with leading underscore. |
| nit#2 (tier-level granularity) | ✅ Documented | "What This Does NOT Change" line 447: per-service emits deferred to AD-459b. |
| nit#3 (test ordering) | ✅ Applied | Test 11 description at line 430 now asserts on the SET of emitted EventType payloads, not order. `services_in_tier()` now returns `sorted(...)` at line 132 for deterministic output. |
| nit#4 (ESSENTIAL safety invariant) | ✅ Documented | "What This Does NOT Change" line 444: ESSENTIAL never shed by default policy; manager respects policy verbatim. |

### New Findings (introduced during revision)

None of consequence. Spot-checks:

- The 11 v1 seed names verified once more in this review against live runtime.py — all 11 are real public attributes/properties.
- `services_in_tier()` returns `sorted(...)` list (line 132) — Test 6 at line 426 asserts on sorted output. Deterministic across CPython versions.
- `_DEFAULT_CLASSIFICATIONS` is a `tuple` (immutable) at line 96; per-instance copy in `__post_init__` (lines 119-121) protects from accidental shared-state mutation.
- The empty `DegradationConfig` body has only docstrings — Pydantic v2 BaseModel accepts this (no fields, just descriptive text). Verified valid Pydantic.

### Verified Against Revised Codebase Claims

- All 11 seed names verified against `src/probos/runtime.py`:
  - `event_log` (line 314), `trust_network` (line 335), `registry` (line 293), `intent_bus` (line 300), `hebbian_router` (line 304), `decomposer` (line 352), `dream_scheduler` (line 411), `proactive_loop` (line 533), `emergence_metrics_engine` (line 951 property), `emergent_leadership_detector` (post-AD-439 at finalize.py:344), `red_team_lead` (post-AD-455 at finalize.py:422). All confirmed.
- `bridge_alerts.AlertSeverity` orthogonality at `bridge_alerts.py:24` — confirmed via grep; no overlap with AD-459 service tiers.
- `orders: OrdersConfig` at `config.py:1593` — confirmed terminal anchor.

### Cross-Cutting Convention Audit

| Cross-cutting fix | Applied? | Evidence |
|---|---|---|
| #1 No-theater discipline | ✅ Applied | v1 read-only coordinator with REAL signal (`is_shed(name)` returns real answer based on real registry seeds). The "no consumer in cognitive/" caveat is intentional per Wave 5 retrospective convention #3 (coordinator-then-dispatch). AD-459b deferral note explicit for: active-shedding hooks, capability gate, logical-name aliases, per-service emits, CRITICAL-vs-HIGH differentiation. |
| #2 Verify-first defensive-read | ✅ Applied wholesale | All seed names verified-against-runtime.py at draft time and re-verified in second-pass review. |
| #3 Anchor-chain fallback | ✅ Applied (4 levels) | Section 6 chain: `pre_flight` → `engineering` → `validation_framework` → `orders: OrdersConfig` (AD-440 terminal). |

### Verdict

**✅ Approved.** Build-ready. v1 is the canonical Wave 6 application of Wave 5 retrospective convention #3 (coordinator-then-dispatch) — read-only manager today, dispatch hooks in AD-459b. No architect rework required.

