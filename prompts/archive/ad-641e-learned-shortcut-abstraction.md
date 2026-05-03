# AD-641e: LearnedShortcut Shared Abstraction — Protocol over WorkflowCache (v1)

**Status:** Ready for builder
**Wave:** 9B (cross-cutting — defines a Protocol that `WorkflowCache` adopts; future Cognitive JIT will adopt the same surface when it lands)
**Dependencies:** Adapts existing `WorkflowCache` at `src/probos/cognitive/workflow_cache.py:17` (verified). Wired at `runtime.workflow_cache` (verified at `runtime.py:195, 351, 356`). The mesh-side Cognitive JIT service does not yet exist as a runtime-instantiated service (verified absent: `grep -rn "cognitive_jit\|CognitiveJITService\|class JITService" src/probos/` returns no matches); v1 ships the abstraction with one real adopter (WorkflowCache) — JIT side is `AD-641e-i` once the JIT service lands.
**Estimated tests:** ~12
**Risk:** MEDIUM-HIGH — touches WorkflowCache through a new Protocol layer; existing public API of `WorkflowCache` MUST remain unchanged (Open/Closed). Convention #14: aggressive pre-deferral; v1 ships the Protocol + WorkflowCache adapter; JIT adopter and persistence deferred.

---

## Problem

The brain has two parallel "learned shortcut" systems per the AD-641 design doc Category C:

- **`WorkflowCache`** (`src/probos/cognitive/workflow_cache.py:17`) — session-scoped LRU cache of `user_input -> TaskDAG` mappings. Bypasses LLM on repeat queries.
- **Cognitive JIT** (referenced as AD-531-539 in design doc; verified ABSENT from `src/probos/` today) — would extract permanent procedures from successful execution; lifecycle is "forever."

Both are "learned shortcuts" but at different timescales and abstraction levels. The design doc says: "Could share a common storage abstraction without merging logic." Today, no shared abstraction exists.

`grep -rn "class LearnedShortcutBackend\|class LearnedShortcutRegistry\|LearnedShortcutProtocol" src/probos/` returns no matches.

The roadmap entry (line 7056) names AD-641e as "Cognitive JIT ↔ Workflow Cache Shared Abstraction — Common storage/retrieval interface for both 'learned shortcuts' systems. Neither merges into the other. Shared query patterns, separate stores."

## Solution Overview

One new module under `src/probos/cognitive/learned_shortcuts/` (new package; AD-641e OWNS `__init__.py` creation):

1. **`LearnedShortcutBackend`** Protocol (`protocol.py`) — `typing.Protocol` defining the shared surface: `lookup(key: str) -> Any | None`, `store(key: str, value: Any) -> None`, `evict(key: str) -> bool`, `size` property, `kind` property (e.g., `"workflow_cache"` / `"cognitive_jit"`). Each backend retains its own data; the Protocol is the common interface.
2. **`LearnedShortcutRegistry`** (`registry.py`) — coordinator that holds zero-or-more registered backends and provides a unified observation surface: `register(backend)`, `lookup_first(key) -> tuple[backend_kind, value] | None`, `total_size` property, `kinds` property. Read-side fan-out (queries every backend until first hit); write-side stays per-backend (no merging).
3. **`WorkflowCacheBackend`** (`workflow_cache_adapter.py`) — thin `LearnedShortcutBackend` adapter wrapping the existing `WorkflowCache` instance. Public API of `WorkflowCache` itself is unchanged (Open/Closed).

This is **a Protocol layer over existing infrastructure**, per design doc Category C. AD-641e does NOT modify `WorkflowCache.store/lookup/lookup_fuzzy`, does NOT add new persistence, does NOT introduce JIT logic.

**v1 scope (no-theater discipline; convention #7 + #14 — 3 of 6 capabilities ship):**

- **Real `LearnedShortcutBackend` Protocol** — typed, enforced via `@runtime_checkable`.
- **Real `WorkflowCacheBackend` adapter** — wraps existing `runtime.workflow_cache`; exercised in tests.
- **Real `LearnedShortcutRegistry`** — registers WorkflowCacheBackend at startup; emits `LEARNED_SHORTCUT_REGISTERED` per backend registration.

**3 wholesale-deferred to grandchild ADs:**

- **Cognitive JIT backend (`CognitiveJITBackend` adapter)** — `AD-641e-i`. Depends on the Cognitive JIT service landing (separate AD; not in scope for 641e).
- **Cross-store eviction policy (e.g., LRU across all backends)** — `AD-641e-ii`. v1 forwards `evict(key)` per-backend; cross-store policy belongs to a follow-up.
- **Persistent backend (SQLite-backed lookup)** — `AD-641e-iii`. Both adopters are in-memory in v1; persistence is its own AD.

---

## Section 0: Event Types

Add to `src/probos/events.py`:

```
LEARNED_SHORTCUT_REGISTERED = "learned_shortcut_registered"  # AD-641e
LEARNED_SHORTCUT_HIT = "learned_shortcut_hit"  # AD-641e
```

Verified absent: `grep -n "LEARNED_SHORTCUT_REGISTERED\|LEARNED_SHORTCUT_HIT" src/probos/events.py` returns no matches.

---

## Section 1: Package init

**File:** `src/probos/cognitive/learned_shortcuts/__init__.py` (new — AD-641e OWNS directory creation)

```python
"""AD-641e: LearnedShortcut shared abstraction -- Protocol over learned-shortcut backends."""

from probos.cognitive.learned_shortcuts.protocol import LearnedShortcutBackend
from probos.cognitive.learned_shortcuts.registry import LearnedShortcutRegistry
from probos.cognitive.learned_shortcuts.workflow_cache_adapter import (
    WorkflowCacheBackend,
)

__all__ = [
    "LearnedShortcutBackend",
    "LearnedShortcutRegistry",
    "WorkflowCacheBackend",
]
```

---

## Section 2: `LearnedShortcutBackend` Protocol

**File:** `src/probos/cognitive/learned_shortcuts/protocol.py` (new)

```python
"""AD-641e: LearnedShortcutBackend -- shared Protocol for learned-shortcut systems.

Both WorkflowCache and (future) Cognitive JIT adopt this Protocol. They keep
separate storage and tuning; the Protocol is the read-side abstraction.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LearnedShortcutBackend(Protocol):
    """Read-side interface for learned-shortcut backends."""

    @property
    def kind(self) -> str:
        """Backend identifier, e.g. 'workflow_cache' / 'cognitive_jit'."""
        ...

    @property
    def size(self) -> int:
        """Current number of stored entries."""
        ...

    def lookup(self, key: str) -> Any | None:
        """Return the stored value or None if not found."""
        ...

    def store(self, key: str, value: Any) -> None:
        """Store an entry under key."""
        ...

    def evict(self, key: str) -> bool:
        """Remove the entry under key. Returns True if an entry was removed."""
        ...
```

---

## Section 3: `WorkflowCacheBackend` adapter

**File:** `src/probos/cognitive/learned_shortcuts/workflow_cache_adapter.py` (new)

```python
"""AD-641e: WorkflowCacheBackend -- adapter wrapping the existing WorkflowCache.

The underlying WorkflowCache (AD-274; preexisting) is unchanged; this adapter
exposes the LearnedShortcutBackend Protocol surface so the registry can
observe and coordinate across backend kinds.
"""

from __future__ import annotations

from typing import Any


class WorkflowCacheBackend:
    """LearnedShortcutBackend adapter for WorkflowCache."""

    def __init__(self, *, workflow_cache: Any) -> None:
        self._cache = workflow_cache

    @property
    def kind(self) -> str:
        return "workflow_cache"

    @property
    def size(self) -> int:
        # WorkflowCache.size is a @property (verified at workflow_cache.py:115);
        # getattr() invokes the property descriptor, so the `or 0` is purely
        # defensive against a None return -- it is not a method-vs-property guard.
        return int(getattr(self._cache, "size", 0) or 0)

    def lookup(self, key: str) -> Any | None:
        if not key:
            return None
        # WorkflowCache.lookup uses 'user_input' as parameter name and returns
        # TaskDAG | None. The adapter maps the Protocol's 'key' to that.
        try:
            return self._cache.lookup(key)
        except Exception:
            return None

    def store(self, key: str, value: Any) -> None:
        if not key:
            return
        try:
            self._cache.store(key, value)
        except Exception:
            pass

    def evict(self, key: str) -> bool:
        # WorkflowCache currently does not expose a public evict() method;
        # v1 returns False (eviction is not supported on this backend yet).
        # AD-641e-ii will add cross-backend eviction including a public
        # evict() addition to WorkflowCache.
        return False
```

---

## Section 4: `LearnedShortcutRegistry`

**File:** `src/probos/cognitive/learned_shortcuts/registry.py` (new)

Read-side semantics (per design doc Category C, "separate stores"):
the registry does **not** coalesce or merge values across backends.
`lookup_first()` walks backends in registration order and returns the
**first** non-None hit; later backends are not consulted on that key.
This preserves each backend's independent storage semantics and keeps
the coordinator stateless. Future fan-out / fan-in policies belong
to AD-641e-ii (cross-store eviction) or a dedicated coordinator AD.

```python
"""AD-641e: LearnedShortcutRegistry -- coordinator for backends.

Read-side fan-out: lookup_first() walks registered backends in registration
order and returns the FIRST non-None hit (no merging). Write-side stays
per-backend; the registry does not multicast stores (that would violate the
design doc's 'separate stores' principle).
"""

from __future__ import annotations

import logging
from typing import Any

from probos.cognitive.learned_shortcuts.protocol import LearnedShortcutBackend
from probos.events import EventType

logger = logging.getLogger(__name__)


class LearnedShortcutRegistry:
    """Coordinates registered LearnedShortcutBackend instances."""

    def __init__(self, *, emit_event: Any | None = None) -> None:
        self._emit_event = emit_event
        self._backends: list[LearnedShortcutBackend] = []

    @property
    def kinds(self) -> list[str]:
        return [b.kind for b in self._backends]

    @property
    def total_size(self) -> int:
        return sum(int(b.size or 0) for b in self._backends)

    def register(self, backend: LearnedShortcutBackend) -> bool:
        if backend is None:
            return False
        for existing in self._backends:
            if existing.kind == backend.kind:
                return False  # idempotent: same kind already registered
        self._backends.append(backend)
        if self._emit_event is not None:
            try:
                self._emit_event(
                    EventType.LEARNED_SHORTCUT_REGISTERED,
                    {"kind": backend.kind, "size": int(backend.size or 0)},
                )
            except Exception:
                logger.debug(
                    "LearnedShortcutRegistry: emit LEARNED_SHORTCUT_REGISTERED failed",
                    exc_info=True,
                )
        return True

    def lookup_first(self, key: str) -> tuple[str, Any] | None:
        if not key:
            return None
        for backend in self._backends:
            value = backend.lookup(key)
            if value is not None:
                if self._emit_event is not None:
                    try:
                        self._emit_event(
                            EventType.LEARNED_SHORTCUT_HIT,
                            {"kind": backend.kind, "key": str(key)},
                        )
                    except Exception:
                        logger.debug(
                            "LearnedShortcutRegistry: emit LEARNED_SHORTCUT_HIT failed",
                            exc_info=True,
                        )
                return (backend.kind, value)
        return None
```

---

## Section 5: Configuration

**File:** `src/probos/config.py`

Add Pydantic model after the most recent addition:

```python
class LearnedShortcutsConfig(BaseModel):
    """AD-641e: LearnedShortcut Registry configuration."""

    enabled: bool = True
    register_workflow_cache: bool = True
```

Add `learned_shortcuts: LearnedShortcutsConfig = Field(default_factory=LearnedShortcutsConfig)` to `SystemConfig`.

Verified absent: `grep -n "LearnedShortcutsConfig\|learned_shortcuts:" src/probos/config.py` returns no matches.

---

## Section 6: Startup wiring

**File:** `src/probos/startup/finalize.py`

Append after the most recent finalize wiring block:

```python
# AD-641e: LearnedShortcut Registry
ls_cfg = getattr(getattr(runtime, "config", None), "learned_shortcuts", None)
if ls_cfg is not None and ls_cfg.enabled:
    runtime.learned_shortcut_registry = LearnedShortcutRegistry(
        emit_event=runtime.emit_event,
    )
    if ls_cfg.register_workflow_cache:
        wf = getattr(runtime, "workflow_cache", None)
        if wf is not None:
            runtime.learned_shortcut_registry.register(
                WorkflowCacheBackend(workflow_cache=wf),
            )
else:
    runtime.learned_shortcut_registry = None
```

---

## Section 7: Tests

**File:** `tests/test_ad641e_learned_shortcuts.py` (new)

Cover (~14 tests):

1. `test_event_type_learned_shortcut_registered_exists`
2. `test_event_type_learned_shortcut_hit_exists`
3. `test_learned_shortcuts_config_defaults`
4. `test_protocol_runtime_checkable_recognizes_workflow_cache_backend` -- `isinstance(WorkflowCacheBackend(workflow_cache=stub), LearnedShortcutBackend)` is True.
4b. `test_protocol_runtime_checkable_recognizes_minimal_stub` -- hand-rolled minimal class with the 5 Protocol members (`kind`, `size`, `lookup`, `store`, `evict`) is recognized as `LearnedShortcutBackend` via structural typing. Strengthens the Open/Closed claim independent of `WorkflowCacheBackend`.
5. `test_workflow_cache_backend_kind_and_size` -- wraps stub `WorkflowCache(size=3)`; asserts `kind=='workflow_cache'`, `size==3`.
6. `test_workflow_cache_backend_lookup_delegates`
7. `test_workflow_cache_backend_evict_returns_false_in_v1` -- documents the deferral.
8. `test_registry_register_emits_event_with_kind_and_size`
9. `test_registry_register_idempotent_for_same_kind`
10. `test_registry_lookup_first_returns_first_hit_and_emits_hit`
11. `test_registry_lookup_first_returns_none_when_no_backend_has_key`
12. `test_registry_total_size_sums_backends`
13. `test_existing_workflow_cache_public_api_unchanged` -- imports `WorkflowCache`, asserts `{store, lookup, lookup_fuzzy, size}` are present and callable / property as appropriate. Open/Closed regression guard.

Per convention #11 -- registry tests use real `WorkflowCacheBackend` wrapping a stub `WorkflowCache` rather than mocking the Protocol. The stub satisfies the Protocol structurally.

---

## What This Does NOT Change (Explicit Scope Boundaries)

1. **`WorkflowCache.store/lookup/lookup_fuzzy`** — unchanged. Adapter wraps; no edits to existing module.
2. **Cognitive JIT** — does not exist as a service today; not introduced by this AD. `AD-641e-i` adds the JIT adapter once the JIT service lands.
3. **`runtime.workflow_cache`** — unchanged; remains the canonical reference. The new registry is an additional observation surface.
4. **Persistence** — wholesale-deferred to AD-641e-iii.
5. **Cross-backend eviction policy** — wholesale-deferred to AD-641e-ii.

---

## Engineering Principles Compliance

- **Single Responsibility:** Protocol defines surface. Registry coordinates. Adapter bridges existing class.
- **Open/Closed:** Adding a new backend (JIT adapter, SQLite adapter) is a new adapter class implementing the Protocol — registry unchanged, WorkflowCache unchanged.
- **Interface Segregation:** Protocol has 5 members; consumers depend only on what they use.
- **Dependency Inversion:** `LearnedShortcutRegistry` depends on the Protocol, not on `WorkflowCache` concretely.
- **Law of Demeter:** Registry calls only Protocol methods; never reaches into adapter internals.
- **DRY:** WorkflowCache code is unchanged; adapter wraps without duplication.

---

## Verification

```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad641e_learned_shortcuts.py -v -n 0
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_workflow_cache.py -v -n 0   # regression
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile
```

---

## Tracking

1. **PROGRESS.md** — Prepend AD-641e CLOSED entry with v1 scope summary + 3 deferred grandchildren.
2. **DECISIONS.md** — Optional: brief entry noting v1 ships Protocol + one real adopter; JIT adapter genuinely-deferred (no theater) until JIT service lands.
3. **docs/development/roadmap.md** — Update line 7056 reflecting AD-641e CLOSED.

---

## Acceptance Criteria

- 13/13 focused tests pass at `-n 0` (12 v1 + 1 regression guard; 4b is renumbered as #4-stub but counted in the 13).
- Full parallel gate non-decreasing.
- `runtime.learned_shortcut_registry` is a public attribute (or `None` when disabled).
- 2 new EventTypes are members of `EventType`.
- `WorkflowCache` source unchanged (verified by `tests/test_workflow_cache.py` regression + new test #13 public-API guard).
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-02)

```
grep -n "class WorkflowCache\b\|def store\|def lookup\|def lookup_fuzzy" src/probos/cognitive/workflow_cache.py
  src/probos/cognitive/workflow_cache.py:17: class WorkflowCache:
  src/probos/cognitive/workflow_cache.py:29:     def store(self, user_input: str, dag: TaskDAG) -> None:
  src/probos/cognitive/workflow_cache.py:56:     def lookup(self, user_input: str) -> TaskDAG | None:
  src/probos/cognitive/workflow_cache.py:67:     def lookup_fuzzy(

grep -n "self\.workflow_cache" src/probos/runtime.py
  src/probos/runtime.py:195: workflow_cache: WorkflowCache
  src/probos/runtime.py:351: self.workflow_cache = WorkflowCache()
  src/probos/runtime.py:356: workflow_cache=self.workflow_cache,

grep -rn "cognitive_jit\|CognitiveJITService\|class JITService" src/probos/
  (no matches; Cognitive JIT service is referenced in roadmap.md design doc but does not exist
  as a runtime-instantiated service today; AD-641e-i adds the adapter once it lands)

grep -n "class LearnedShortcutBackend\|class LearnedShortcutRegistry\|LearnedShortcutProtocol" src/probos/
  (no matches; new module)

grep -n "LEARNED_SHORTCUT_REGISTERED\|LEARNED_SHORTCUT_HIT" src/probos/events.py
  (no matches; introduced by this prompt)
```

---

## Revision (2026-05-02)

Pass-1 review verdict: ✅ Approved (0 Required, 3 Recommended, 3 Nits).
This revision folds in all Recommended items and Nits since they are pure quality nudges with no scope expansion.

| Review item | Disposition | Change |
|---|---|---|
| R1 | Applied | Section 3 `WorkflowCacheBackend.size` gets a comment noting that `WorkflowCache.size` is a `@property` (verified at `workflow_cache.py:115`) and that the `or 0` is defensive against a `None` return, not a method-vs-property guard. |
| R2 | Applied | Test plan adds `test_protocol_runtime_checkable_recognizes_minimal_stub` (numbered 4b) using a hand-rolled stub class with the 5 Protocol members. Tests `@runtime_checkable` structural-typing independent of `WorkflowCacheBackend`. |
| R3 | Applied | Section 4 prelude documents read-side fan-out semantics: `lookup_first()` walks backends in registration order, returns FIRST non-None hit, no merging across backends. Both the prose and the inline docstring now state this explicitly. |
| N1 | Applied | Section 3 module docstring replaces "AD: existing" with "AD-274; preexisting". |
| N2 | Applied | Registry `register()` and `lookup_first()` except-Exception blocks now `logger.debug("LearnedShortcutRegistry: emit ... failed", exc_info=True)` instead of bare `pass`. Helps future BF triage. |
| N3 | Applied | Test plan adds #13 `test_existing_workflow_cache_public_api_unchanged` -- imports `WorkflowCache` and asserts the `{store, lookup, lookup_fuzzy, size}` public surface is intact. Makes the Open/Closed claim mechanically testable rather than asserted in prose only. |

Acceptance test count updated from 12 to 13 (1 added) -- 4b is structurally a sibling of #4 but counted in the 13. The Verification section's pytest invocation is unchanged.

### Beyond-review structural defect sweep

Re-ran the Wave 9A defect-class sweep against this prompt's revision. The pass-1 review's architect-discretion sweep table covered async/sync, kwarg, row-shape, and phantom-API classes. No additional defects discovered.

### Closing self-check

- Grep for OLD names in this revision: `Select-String "AD: existing" prompts/ad-641e-learned-shortcut-abstraction.md` -> 0 hits (replaced with `AD-274; preexisting`).
- Grep for old test count: `Select-String "12/12 focused tests pass" prompts/ad-641e-learned-shortcut-abstraction.md` -> 0 hits (replaced with `13/13`).
- Grep for old `except Exception: pass` in registry block -> 0 hits in the registry code-block of this prompt; both are now `logger.debug(... exc_info=True)`.
- Solution Overview / Dependencies / v1-deliverables headers unchanged -- the revision is additive (test #4b, #13, comments, logger calls) and does not change the 3-of-6 ship vs 3-deferred split.
