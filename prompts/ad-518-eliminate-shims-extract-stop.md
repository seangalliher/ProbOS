# AD-518: Eliminate runtime.py Delegation Shims + Extract stop()

## Context

After AD-515/516/517, `runtime.py` is 3,216 lines with 86 methods. Of those, **34 are pure delegation shims** (~170 lines) — methods that do nothing but forward to an AD-515 extracted service (e.g., `self._dream_adapter.recall_similar()`). These exist only for backwards compatibility and bloat the class interface. Additionally, `stop()` is 257 lines of sequential shutdown — the mirror image of the `start()` that was already extracted in AD-517.

## Objective

1. **Eliminate 34 delegation shims** by updating all callers to reference the extracted service directly.
2. **Extract `stop()` into `src/probos/startup/shutdown.py`** to mirror the startup phase structure.
3. **Remove 2 stale class-level constants** (`_WARD_ROOM_COOLDOWN_SECONDS`, `_WARD_ROOM_CREW`) that now live in `ward_room_router.py`.

**Target:** runtime.py reduced from 3,216 to ~2,750 lines (~−15%).

## Design Principles

1. **Zero behavior changes.** Every test must pass.
2. **Callers access services directly.** `runtime._dream_adapter.recall_similar()` not `runtime.recall_similar()`.
3. **Public services get public attributes.** Rename `self._dream_adapter` → `self.dream_adapter` (etc.) where callers need access. Keep underscore only if truly internal.
4. **stop() mirrors start().** Use the same pattern: a short method in runtime.py calling phase functions.

## Part A: Eliminate Delegation Shims

### Shims to Remove

For each group below: find ALL callers across the codebase (tests included), update them to call the service directly, then delete the shim from runtime.py.

#### A1. Dream Adapter shims (11 methods, ~58 lines)

| Shim method | Replace with |
|-------------|-------------|
| `runtime.recall_similar(...)` | `runtime.dream_adapter.recall_similar(...)` |
| `runtime._on_pre_dream(...)` | `runtime.dream_adapter.on_pre_dream(...)` |
| `runtime._on_post_dream(...)` | `runtime.dream_adapter.on_post_dream(...)` |
| `runtime._on_post_micro_dream(...)` | `runtime.dream_adapter.on_post_micro_dream(...)` |
| `runtime._store_strategies(...)` | `runtime.dream_adapter.store_strategies(...)` |
| `runtime._on_gap_predictions(...)` | `runtime.dream_adapter.on_gap_predictions(...)` |
| `runtime._on_contradictions(...)` | `runtime.dream_adapter.on_contradictions(...)` |
| `runtime._refresh_emergent_detector_roster()` | `runtime.dream_adapter.refresh_emergent_detector_roster()` |
| `runtime._periodic_flush()` | `runtime.dream_adapter.periodic_flush()` |
| `runtime._periodic_flush_loop()` | `runtime.dream_adapter.periodic_flush_loop()` |
| `runtime._build_episode(...)` | `runtime.dream_adapter.build_episode(...)` |

**Rename:** `self._dream_adapter` → `self.dream_adapter` (public attribute).

**Special case:** `_build_episode` (line 2675) has a fallback path for when `_dream_adapter` is None. Keep this fallback logic by checking `if self.dream_adapter:` at the call site, or move the fallback into `DreamAdapter.build_episode()` itself.

#### A2. Self-Mod Manager shims (10 methods, ~62 lines)

| Shim method | Replace with |
|-------------|-------------|
| `runtime.apply_correction(...)` | `runtime.self_mod_manager.apply_correction(...)` |
| `runtime._apply_agent_correction(...)` | `runtime.self_mod_manager.apply_agent_correction(...)` |
| `runtime._apply_skill_correction(...)` | `runtime.self_mod_manager.apply_skill_correction(...)` |
| `runtime._find_designed_record(...)` | `runtime.self_mod_manager.find_designed_record(...)` |
| `runtime._was_last_execution_successful()` | `runtime.self_mod_manager.was_last_execution_successful()` |
| `runtime._format_execution_context()` | `runtime.self_mod_manager.format_execution_context()` |
| `runtime._register_designed_agent(...)` | `runtime.self_mod_manager.register_designed_agent(...)` |
| `runtime._unregister_designed_agent(...)` | `runtime.self_mod_manager.unregister_designed_agent(...)` |
| `runtime._create_designed_pool(...)` | `runtime.self_mod_manager.create_designed_pool(...)` |
| `runtime._set_probationary_trust(...)` | `runtime.self_mod_manager.set_probationary_trust(...)` |

**Rename:** `self._self_mod_manager` → `self.self_mod_manager` (public attribute).

**Special case:** `apply_correction` (line 2333) sets `self._last_execution` and `self._last_execution_text` before delegating. Move these state updates INTO `SelfModManager.apply_correction()` — it should own that state.

#### A3. Ward Room Router shims (8 methods, ~54 lines)

| Shim method | Replace with |
|-------------|-------------|
| `runtime._deliver_bridge_alert(...)` | `runtime.ward_room_router.deliver_bridge_alert(...)` |
| `runtime._route_ward_room_event(...)` | `runtime.ward_room_router.route_event(...)` |
| `runtime._find_ward_room_targets(...)` | `runtime.ward_room_router.find_targets(...)` |
| `runtime._find_ward_room_targets_for_agent(...)` | `runtime.ward_room_router.find_targets_for_agent(...)` |
| `runtime._handle_propose_improvement(...)` | `runtime.ward_room_router.handle_propose_improvement(...)` |
| `runtime._extract_endorsements(...)` | `runtime.ward_room_router.extract_endorsements(...)` |
| `runtime._process_endorsements(...)` | `runtime.ward_room_router.process_endorsements(...)` |
| `runtime._cleanup_ward_room_tracking(...)` | `runtime.ward_room_router.cleanup_tracking(...)` |

**Rename:** `self._ward_room_router` → `self.ward_room_router` (public attribute).

**Also remove:** Class-level constants `_WARD_ROOM_COOLDOWN_SECONDS` (if present) and `_WARD_ROOM_CREW` (if present) — these now live in `ward_room_router.py`.

#### A4. Onboarding shims (2 methods, ~9 lines)

| Shim method | Replace with |
|-------------|-------------|
| `runtime._wire_agent(...)` | `runtime.onboarding.wire_agent(...)` |
| `runtime._run_naming_ceremony(...)` | `runtime.onboarding.run_naming_ceremony(...)` |

**Rename:** `self._onboarding` → `self.onboarding` (public attribute).

#### A5. Warm Boot shim (1 method, ~4 lines)

| Shim method | Replace with |
|-------------|-------------|
| `runtime._restore_from_knowledge()` | `runtime.warm_boot.restore()` |

**Rename:** `self._warm_boot` → `self.warm_boot` (public attribute).

#### A6. Crew Utils shim (1 method, ~3 lines)

| Shim method | Replace with |
|-------------|-------------|
| `runtime._is_crew_agent(agent)` | `from probos.crew_utils import is_crew_agent; is_crew_agent(agent)` |

Callers should import the function directly instead of going through runtime.

### How to Find All Callers

For each shim, search the entire codebase:

```bash
# Example for recall_similar
grep -rn "recall_similar\|_on_pre_dream\|_on_post_dream" src/ tests/ --include="*.py"
```

Check:
- `src/probos/runtime.py` itself (internal calls between methods)
- `src/probos/startup/` (startup phase modules reference runtime methods)
- `src/probos/routers/` (API routers)
- `tests/` (test mocking and assertions)
- `src/probos/` other modules (agents, cognitive, etc.)

**Tests are the trickiest part.** Many tests mock `runtime.recall_similar` or `runtime._wire_agent`. These mocks must be updated to target the service attribute, e.g., `runtime.dream_adapter.recall_similar`.

## Part B: Extract `stop()` into `src/probos/startup/shutdown.py`

### Current stop() structure (257 lines, 32 numbered steps)

Create a single `async def shutdown(runtime)` function that mirrors start(). Unlike startup phases which are split across 8 files, shutdown is simpler — one file is sufficient since there are no complex return values.

```python
# src/probos/startup/shutdown.py
"""Graceful shutdown sequence (AD-518)."""

import logging
logger = logging.getLogger(__name__)

async def shutdown(runtime: "ProbOSRuntime") -> None:
    """Shut down all ProbOS subsystems in reverse startup order."""
    # ... move all 257 lines here
```

**Note:** `stop()` needs the full runtime reference (touches 30+ attributes). Unlike startup which creates new services and returns them, shutdown just calls `.stop()` or `.close()` on existing services. Passing individual deps would mean 30+ parameters with no benefit.

After extraction, `stop()` in runtime.py becomes:

```python
async def stop(self) -> None:
    """Stop all subsystems."""
    from probos.startup.shutdown import shutdown
    await shutdown(self)
```

## General Rules

1. **Zero behavior changes.** Pure structural refactor.
2. **Search before deleting.** Every shim MUST have zero remaining callers before removal.
3. **Update __init__ attribute names.** When renaming `self._dream_adapter` → `self.dream_adapter`, update the declaration in `__init__` AND all assignments in startup phase modules.
4. **Update type annotations.** Where `self._dream_adapter: DreamAdapter | None` becomes `self.dream_adapter: DreamAdapter | None`.
5. **Test after each group.** Complete A1 (dream shims) → test → A2 (self-mod shims) → test → etc.
6. **Don't change method signatures on the extracted services.** Only change how they're accessed (through runtime attribute vs shim).

## Build Order

1. Part A1: Dream Adapter shims — find callers, update, remove 11 shims, rename attr
2. Part A2: Self-Mod Manager shims — find callers, update, remove 10 shims, rename attr
3. Part A3: Ward Room Router shims — find callers, update, remove 8 shims, rename attr
4. Part A4: Onboarding shims — find callers, update, remove 2 shims, rename attr
5. Part A5: Warm Boot shim — find callers, update, remove 1 shim, rename attr
6. Part A6: Crew Utils shim — find callers, update, remove 1 shim
7. Part B: Extract stop() → shutdown.py, test
8. Clean up stale constants, final test

## Success Criteria

- 34 delegation shims removed from runtime.py
- `stop()` reduced to ~3 lines (delegation to `shutdown.py`)
- 5 private service attributes renamed to public (`_dream_adapter` → `dream_adapter`, etc.)
- runtime.py reduced by ~400+ lines
- All existing tests pass (with caller updates)
- No new shims introduced
