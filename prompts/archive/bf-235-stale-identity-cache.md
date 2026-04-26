# BF-235: Clear Stale Identity Caches on Stasis Resume

**Status:** Ready for builder  
**Priority:** High  
**Tracker:** PROGRESS.md, roadmap.md, DECISIONS.md  
**Issue:** #338

---

## Problem

After stasis resume, five agents (Medical + Bridge) render wrong callsign, CMO reference, and peers in their system prompts. The stale identity persists 13+ hours — essentially indefinitely until the next `probos reset`. Crew-originated diagnosis by Vance, Chapel, Anvil, and Reed.

### Root Cause

Two module-level `@lru_cache` decorators in `standing_orders.py` are **never invalidated on stasis resume**:

1. **`_load_file()` (line 92)** — caches standing order file contents. If a standing order file changes on disk between stasis shutdown and resume, the old content persists.

2. **`_build_personality_block()` (line 130)** — caches the personality & identity section keyed by `(agent_type, department, callsign_override)`. Since the cache key includes the callsign, this cache won't produce wrong callsigns *for the same agent*. However, it caches the *entire personality block* which may embed stale peer/CMO references if the block text is identical but context has changed.

The existing `clear_cache()` function (line 203) clears both caches but is **only called when directives are issued/revoked/amended** from the shell (`commands_directives.py` lines 131, 254, 289). It is never called during startup or stasis recovery.

Additionally, the module-level **decision cache** (`_DECISION_CACHES` in `cognitive_agent.py` line 22) survives across stasis because it's an in-process dict. While decision cache entries have TTLs (max ~3600s), they can serve stale responses for up to an hour after resume. The `evict_cache_for_type()` classmethod (line 4858) exists but has **zero callers** anywhere in the codebase.

### Why 13+ Hours?

The `@lru_cache` on `_build_personality_block` and `_load_file` has no TTL — entries persist for the entire process lifetime. Even though the decision cache has TTLs (up to 3600s), the personality block and file caches feed `compose_instructions()` which is called on every `decide()` cycle. So even after decision cache entries expire and new LLM calls are made, the *system prompt* still contains the stale personality/identity from the `@lru_cache`.

### Prior Art Absorbed

- **BF-101:** Callsign consistency — `_resolve_callsign()` fallback to identity registry birth certificate. Ensures the *callsign parameter* is correct, but doesn't prevent the *composed instructions cache* from serving stale results.
- **BF-049:** Ontology callsign sync — `update_assignment_callsign()` updates the ontology after naming ceremony. Correct at the ontology level, but `_build_personality_block` `@lru_cache` can still serve pre-update entries.
- **BF-057:** Warm boot identity restoration — skips naming ceremony when birth cert exists, restores callsign from identity registry. Addresses callsign *lookup* but not the cached *personality block* that uses it.
- **BF-083:** Agent identity grounding — `callsign_override` parameter on `_build_personality_block`. Ensures correct callsign is *passed in*, but doesn't clear the cache if a prior call already cached a stale entry with the same key.
- **BF-144:** Authoritative stasis timestamps — provides correct temporal context in orientation. Does not address identity cache.

### Dedup Stack Context (Identity)

BF-235 is the missing link in the identity restoration chain:
1. **BF-057** — Restores callsign from birth certificate on warm boot
2. **BF-101** — Fallback callsign resolution from identity registry
3. **BF-049** — Updates ontology after naming ceremony
4. **BF-083** — Passes runtime callsign to personality builder
5. **BF-235** — Clears all identity/instructions caches on stasis resume (THIS FIX)

---

## Implementation

### 1. Clear identity caches and evict decision caches on stasis resume

**File:** `src/probos/startup/finalize.py`

Cache invalidation is a **lifecycle response** — it must fire whenever the process resumes from stasis, regardless of whether warm-boot orientation rendering is enabled. Insert a new block **before** the existing `AD-567g` orientation guard (around line 677). The existing orientation block remains unchanged.

`is_crew_agent` is already imported at line 17 (`from probos.crew_utils import is_crew_agent`) — reuse it, do not re-import.

**Insert immediately before the existing `# AD-567g:` comment (around line 677):**

```python
    # BF-235: Always clear identity caches on stasis resume, regardless of
    # whether warm-boot orientation rendering is enabled. The caches are stale
    # because of the stasis boundary, not because of orientation policy.
    if runtime._lifecycle_state == "stasis_recovery":
        from probos.cognitive.standing_orders import clear_cache as clear_standing_orders_cache
        clear_standing_orders_cache()
        logger.info("BF-235: Cleared standing orders cache for stasis recovery")

        # BF-235: Evict decision caches so next decide() uses fresh instructions.
        from probos.cognitive.cognitive_agent import CognitiveAgent
        _evicted_total = 0
        for agent in runtime.registry.all():
            if is_crew_agent(agent, runtime.ontology):
                _evicted = CognitiveAgent.evict_cache_for_type(agent.agent_type)
                _evicted_total += _evicted
        if _evicted_total:
            logger.info("BF-235: Evicted %d decision cache entries for stasis recovery", _evicted_total)

```

The existing `AD-567g` block (line 677–733) is left **completely unchanged** — it still guards orientation rendering behind `config.orientation.warm_boot_orientation`. BF-235's invalidation fires unconditionally on `stasis_recovery`, then orientation rendering fires conditionally.

### 3. Add `clear_cache()` call to cold start path as defensive measure

**File:** `src/probos/startup/finalize.py`

On cold start (`probos reset`), the process is fresh — but a defensive `clear_cache()` at the top of `finalize_startup()` makes the test surface uniform (Tests 5/6 pass on cold-start runs too, reducing flakiness if `_lifecycle_state` is misconfigured). Insert immediately after the local variable declarations and before any `runtime.registry.all()` iteration.

Find the block of local variable initializations at the top of `finalize_startup()` (around lines 37–42: `conn_manager = None`, `night_orders_mgr = None`, etc.), and the `# --- Proactive Cognitive Loop (Phase 28b) ---` comment that follows (around line 44). Insert the defensive clear between the variable declarations and the proactive loop block:

**Insert after `ward_room_router = None` / `self_mod_manager = None` (around line 42), before `# --- Proactive Cognitive Loop ---` (around line 44):**

```python
    # BF-235: Defensive cache clear on any startup (cold or warm).
    # Ensures no stale standing orders or personality blocks from a
    # previous finalization pass within the same process. Also makes
    # the test surface uniform — stasis tests and cold-start tests
    # both start from a clean cache.
    from probos.cognitive.standing_orders import clear_cache as clear_standing_orders_cache
    clear_standing_orders_cache()
```

### 4. Log identity block at orientation time for diagnostic traceability

**File:** `src/probos/startup/finalize.py`

Inside the stasis recovery orientation loop (around line 696-730), after `set_orientation()` is called, add a debug log that shows what callsign and identity the agent received. This provides post-hoc traceability for diagnosing future identity issues.

**Current code (around line 727-731):**
```python
                    agent.set_orientation(
                        runtime._orientation_service.render_warm_boot_orientation(_ctx),
                        _ctx,
                    )
```

**New code:**
```python
                    _rendered = runtime._orientation_service.render_warm_boot_orientation(_ctx)
                    agent.set_orientation(_rendered, _ctx)
                    logger.debug(
                        "BF-235: %s orientation set — callsign=%s",
                        agent.agent_type,
                        getattr(agent, 'callsign', '?'),
                    )
```

---

## What This Does NOT Change

- **`_build_personality_block` logic** — The function itself is unchanged. Only its `@lru_cache` is cleared at the right time.
- **`_load_file` logic** — Unchanged. Only its `@lru_cache` is cleared.
- **`clear_cache()` function** — Already exists, unchanged. We're adding callers.
- **`evict_cache_for_type()` method** — Already exists, unchanged. We're adding callers.
- **CallsignRegistry** — Loaded once at startup from YAML. The registry is re-created on each startup (fresh object), so it doesn't carry stale data across stasis. Not the source of this bug.
- **OrientationService** — Orientation rendering is unchanged. It receives correct data; the issue was that `compose_instructions()` served stale cached data downstream.
- **Naming ceremony flow** — BF-049/BF-083 paths unchanged.
- **Consolidation anomaly detection** — If consolidation anomalies were correlated with stale identity, they should cease once identity is correct. No changes to `emergent_detector.py`.

---

## Existing Test Impact

Search for tests importing or calling `clear_cache`, `_build_personality_block`, `_load_file`, `evict_cache_for_type`, `compose_instructions`:

- Tests that call `clear_cache()` in setup/teardown: these are unaffected (they already handle cache lifecycle).
- Tests that rely on `_build_personality_block` caching for performance: no behavioral change — cache still works within a session, just gets cleared on startup.
- Tests that mock `finalize_startup`: the new `clear_cache` import executes early in the function. Tests like `test_new_crew_auto_welcome.py` call `finalize_startup()` with mock runtimes — the Section 3 defensive clear at the top will fire but is harmless (clears empty caches). The stasis-specific eviction (Section 1-2) only fires when `_lifecycle_state == "stasis_recovery"`, so non-stasis test paths are unaffected.

The builder should `grep -r "clear_cache\|evict_cache_for_type\|finalize_startup" tests/` and verify no test assertions break.

---

## New Tests

**File:** `tests/test_bf235_stale_identity_cache.py`

Write tests under `pytest` + `pytest-asyncio`. Works under the project's `asyncio_mode = "auto"` configuration.

### Test 1: `test_clear_cache_evicts_personality_block_entries`
- Call `clear_cache()` first to start from a known-empty state.
- Call `_build_personality_block("test_agent", "science", "Atlas")` — observe it caches.
- Assert `_build_personality_block.cache_info().currsize > 0`.
- Call `clear_cache()`.
- Assert `_build_personality_block.cache_info().currsize == 0`.
- This verifies `clear_cache()` actually removes personality block entries.

### Test 2: `test_clear_cache_clears_file_cache`
- Call `clear_cache()` first to start from a known-empty state.
- Use `tmp_path` to create a standing orders file with content "Version 1".
- Call `_load_file(path)` — returns "Version 1".
- Overwrite the file with "Version 2".
- Call `_load_file(path)` — still returns "Version 1" (cached).
- Call `clear_cache()`.
- Call `_load_file(path)` — now returns "Version 2".

### Test 3: `test_evict_cache_for_type_clears_all_entries`
- Save `_DECISION_CACHES` prior state. Use `try/finally` to restore it after the test — this is a module-level dict and must not contaminate other tests.
- Populate `_DECISION_CACHES["test_agent"]` with 3 entries.
- Call `CognitiveAgent.evict_cache_for_type("test_agent")`.
- Assert `_DECISION_CACHES["test_agent"]` is empty.
- Assert return value is 3.

### Test 4: `test_evict_cache_for_type_noop_for_unknown_agent` (regression pin)
- Pin pre-existing behavior: `evict_cache_for_type()` returns 0 for unknown agent types.
- BF-235 depends on this returning 0 (not raising) when iterating crew agents that have no cached decisions.
- Call `CognitiveAgent.evict_cache_for_type("nonexistent_agent")`.
- Assert return value is 0.

### Test 5: `test_stasis_resume_clears_standing_orders_cache`
- Mock `finalize_startup` dependencies (runtime with `_lifecycle_state = "stasis_recovery"`, crew agents in `registry.all()`).
- Patch `clear_cache` as a spy.
- Run the stasis recovery path of `finalize_startup`.
- Assert `clear_cache` was called.

### Test 6: `test_stasis_resume_evicts_decision_caches`
- Set up runtime with `_lifecycle_state = "stasis_recovery"` and crew agents.
- Pre-populate `_DECISION_CACHES` for each crew agent type. Save prior state; use `try/finally` to restore after test.
- Run the stasis recovery path of `finalize_startup`.
- Assert all decision cache entries were evicted.

### Test 7: `test_orientation_diagnostic_log`
- Run stasis recovery orientation loop with a mock agent (requires `_lifecycle_state = "stasis_recovery"`, `_orientation_service`, and `config.orientation.warm_boot_orientation = True`).
- Capture log output.
- Assert log contains "BF-235:" and the agent's callsign.

**Test count: 7 new tests.**

---

## Verification

```bash
# Targeted tests
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf235_stale_identity_cache.py -v

# Standing orders tests still pass
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_standing_orders.py -v

# Finalization tests still pass
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_finalize.py -v

# Full suite
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q
```

---

## Closing Criterion (from Chapel)

Re-orientation must render **correct callsign, CMO, and peers simultaneously** AND consolidation anomaly events must cease in the post-resume window. This fix addresses the root cause (stale caches) — correctness is verifiable in tests. Consolidation anomaly correlation should be monitored post-deploy but is not gated in CI.

**Follow-up:** Open BF-235a in roadmap.md to check consolidation-anomaly signal at T+72h post-deploy. Owner: architect (Sean). Not a build task — observational review.

---

## Engineering Principles Compliance

Verify all changes comply with the Engineering Principles in `docs/development/contributing.md`:

- **SOLID (S):** Cache invalidation is its own concern, separated from orientation rendering. The `if runtime._lifecycle_state == "stasis_recovery"` block does one thing.
- **SOLID (O):** Reuses existing `clear_cache()` and `evict_cache_for_type()` public APIs. No private member patching.
- **Law of Demeter:** `CognitiveAgent.evict_cache_for_type()` is a public classmethod. `runtime._lifecycle_state` is the standard lifecycle check pattern used throughout `finalize.py`.
- **Fail Fast:** Cache invalidation is unconditional on stasis resume — not gated behind optional config. Failures in telemetry logging are swallowed (non-critical).
- **DRY:** `clear_cache()` already clears both `_load_file` and `_build_personality_block` caches. No new clearing logic needed.

---

## Tracker Updates

### PROGRESS.md
Update existing BF-235 line from `OPEN` to `CLOSED`:
```
BF-235 CLOSED. Stale identity block in agent system prompt rendering across stasis boundaries. Root cause: @lru_cache on _build_personality_block() and _load_file() in standing_orders.py never cleared on stasis resume. Fix: unconditional clear_cache() + evict_cache_for_type() on stasis_recovery lifecycle event in finalize.py (not gated behind warm_boot_orientation). Defensive clear on all startups. Diagnostic logging. Crew-originated (Vance, Chapel, Anvil, Reed). 7 new tests. Issue #338.
```

### docs/development/roadmap.md
Update Bug Tracker row:
```
| BF-235 | Stale identity block in agent system prompt rendering across stasis boundaries | High | **Closed** |
| BF-235a | Monitor: consolidation anomaly signal T+72h post-BF-235 deploy | Low | Open |
```

### DECISIONS.md
Add entry:
```
## BF-235: Clear Identity Caches on Stasis Resume

**Date:** 2026-04-25
**Status:** Accepted

Two `@lru_cache` decorators in `standing_orders.py` (`_load_file` and `_build_personality_block`) persist indefinitely within a process. On stasis resume, these caches served stale identity blocks (wrong callsign, CMO, peers) to `compose_instructions()`, which is called on every `decide()` cycle. The module-level `_DECISION_CACHES` dict in `cognitive_agent.py` compounded the issue by serving stale decisions (produced with old system prompts) for up to 3600s.

Fix: call `clear_cache()` and `evict_cache_for_type()` for all crew agents during stasis recovery in `finalize.py`, unconditionally on `_lifecycle_state == "stasis_recovery"` (not gated behind `warm_boot_orientation` config). Added defensive `clear_cache()` on all startups for test surface uniformity. Added diagnostic logging of callsign at orientation time.

This completes the identity restoration chain: BF-057 (callsign from birth cert) → BF-101 (fallback resolution) → BF-049 (ontology sync) → BF-083 (runtime override) → BF-235 (cache invalidation).

**Alternatives considered:**
- Adding TTL to `@lru_cache` — rejected: Python's `lru_cache` doesn't support TTL natively. Adding `cachetools.TTLCache` would introduce a dependency for a problem that only occurs at stasis boundaries.
- Clearing caches inside `set_orientation()` — rejected: `set_orientation` is called in other contexts (cold start, re-orientation commands) where cache invalidation may not be needed. Startup is the right boundary.
- Gating cache invalidation behind `warm_boot_orientation` config — rejected: cache staleness is a lifecycle event (stasis resume), not a rendering policy. If an operator disables warm-boot orientation, the bug would return. Invalidation must be unconditional on stasis resume.
```
