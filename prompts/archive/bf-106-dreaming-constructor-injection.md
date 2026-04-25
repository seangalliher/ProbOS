# BF-106: DreamingEngine Late-Init — Constructor Injection + Public Setters

**Issue:** [#19](https://github.com/seangalliher/ProbOS/issues/19)
**Status:** Ready for builder
**Priority:** Low
**Files:** `src/probos/cognitive/dreaming.py`, `src/probos/startup/dreaming.py`, `src/probos/startup/finalize.py`, `src/probos/runtime.py`, `tests/test_bf106_dreaming_di.py` (NEW)

## Problem

`DreamingEngine` has three dependencies set via private attribute monkey-patching in `finalize.py` (lines 96–101) instead of proper dependency injection:

```python
# finalize.py lines 96-101
engine._ward_room = runtime.ward_room
engine._get_department = lambda aid: runtime.ontology.get_agent_department(aid)
engine._records_store = runtime._records_store
```

This violates Law of Demeter and dependency injection principles. `DreamingEngine.__init__` already accepts `ward_room`, `get_department`, and `records_store` as optional parameters (lines 68–73 of `dreaming.py`) — the constructor supports them, they just aren't wired through.

## Root Cause Analysis

Startup phase ordering:

| Dependency | Available at | DreamingEngine created at | Can forward via constructor? |
|---|---|---|---|
| `records_store` | Phase 4 (line 1257 of `runtime.py`) | Phase 5 (line 1408) | **YES** |
| `ward_room` | Phase 7 (line 1489 of `runtime.py`) | Phase 5 (line 1408) | **NO** — genuinely unavailable |
| `ontology` (for `get_department`) | Phase 7 (line 1537 of `runtime.py`) | Phase 5 (line 1408) | **NO** — genuinely unavailable |

**Fix strategy:**
1. `records_store` → constructor injection (available at Phase 5)
2. `ward_room` → public setter method on DreamingEngine (unavailable until Phase 7)
3. `get_department` → public setter method on DreamingEngine (unavailable until Phase 7)

This follows the AD-567d pattern where `activation_tracker` is cleanly forwarded through `init_dreaming()` → DreamingEngine constructor.

## What This Does NOT Change

- `DreamingEngine.__init__` parameter list — already has `ward_room`, `get_department`, `records_store` as optional `None` defaults (lines 68–73). No signature changes needed.
- `DreamScheduler` — no changes, it doesn't touch these dependencies.
- `MockNATSBus` or any NATS code — unrelated.
- Onboarding service patches in `finalize.py` (lines 272–275) — separate concern (BF-106 scope is DreamingEngine only).
- `_ward_room_router_ref` patch in `finalize.py` (line 154) — separate concern (WardRoomRouter late binding).

---

## Section 1: Add public setter methods to DreamingEngine

**File:** `src/probos/cognitive/dreaming.py`

Add three public setter methods after the `__init__` method (after line 107, before the first existing method). Place them immediately after the instance variable assignments block:

```python
    def set_ward_room(self, ward_room: Any) -> None:
        """BF-106: Late-bind ward_room (available after Phase 7)."""
        self._ward_room = ward_room

    def set_get_department(self, get_department: Any) -> None:
        """BF-106: Late-bind department lookup (available after Phase 7)."""
        self._get_department = get_department

    def set_records_store(self, records_store: Any) -> None:
        """BF-106: Late-bind records store. No-op if already set via constructor."""
        if self._records_store is None:
            self._records_store = records_store
```

**Why all three even though `records_store` is constructor-injected:** `set_records_store` provides symmetry and a clean API if future startup reordering changes phase availability. The constructor injection is the primary path; the setter is a conditional backstop (no-op if already set) so finalize.py can't silently clobber a constructor-injected value during tests.

---

## Section 2: Forward `records_store` through `init_dreaming()`

**File:** `src/probos/startup/dreaming.py`

### 2a: Add parameter to `init_dreaming()`

Add `records_store: Any = None,` parameter after the `activation_tracker` parameter (line 55):

Current (line 55):
```python
    activation_tracker: Any = None,  # AD-567d: activation-based lifecycle
) -> tuple[DreamingResult, bool]:
```

Change to:
```python
    activation_tracker: Any = None,  # AD-567d: activation-based lifecycle
    records_store: Any = None,  # BF-106: Ship's Records for notebook consolidation
) -> tuple[DreamingResult, bool]:
```

### 2b: Pass `records_store` to DreamingEngine constructor

In the `DreamingEngine()` constructor call (lines 96–116), add `records_store=records_store,` after the `behavioral_metrics_engine` line:

Current (lines 114–116):
```python
            activation_tracker=activation_tracker,
            behavioral_metrics_engine=behavioral_metrics_engine,
        )
```

Change to:
```python
            activation_tracker=activation_tracker,
            behavioral_metrics_engine=behavioral_metrics_engine,
            records_store=records_store,  # BF-106: constructor injection
        )
```

---

## Section 3: Wire `records_store` at the runtime call site

**File:** `src/probos/runtime.py`

In the `init_dreaming()` call (lines 1408–1430), add `records_store=self._records_store,` after the `activation_tracker` line:

Current (line 1429–1430):
```python
            activation_tracker=self._activation_tracker,  # AD-567d
        )
```

Change to:
```python
            activation_tracker=self._activation_tracker,  # AD-567d
            records_store=self._records_store,  # BF-106: available from Phase 4
        )
```

**Note:** `self._records_store` is set at line 1257 (Phase 4 cognitive init), before `init_dreaming()` at line 1408 (Phase 5). This is safe.

---

## Section 4: Replace monkey-patching with setter calls in finalize.py

**File:** `src/probos/startup/finalize.py`

Replace the three private attribute assignments (lines 96–101) with public setter calls.

Current (lines 93–101):
```python
    if runtime.dream_scheduler and runtime.dream_scheduler.engine:
        engine = runtime.dream_scheduler.engine
        if runtime.ward_room:
            engine._ward_room = runtime.ward_room
        if runtime.ontology:
            engine._get_department = lambda aid: runtime.ontology.get_agent_department(aid)
        # AD-551: Wire records_store for notebook consolidation
        if hasattr(runtime, '_records_store') and runtime._records_store:
            engine._records_store = runtime._records_store
```

Replace with:
```python
    if runtime.dream_scheduler and runtime.dream_scheduler.engine:
        engine = runtime.dream_scheduler.engine
        # BF-106: Late-bind Phase 7 dependencies via public setters
        if runtime.ward_room:
            engine.set_ward_room(runtime.ward_room)
        if runtime.ontology:
            engine.set_get_department(
                lambda aid: runtime.ontology.get_agent_department(aid)
            )
        # BF-106: records_store is now constructor-injected (AD-551 wiring path,
        # moved from finalize.py to init_dreaming). Setter is no-op if already
        # set via constructor — only fires if Phase 4 had it as None.
        if hasattr(runtime, '_records_store') and runtime._records_store:
            engine.set_records_store(runtime._records_store)
```

**Design note:** The `records_store` setter call in finalize.py is kept as a conditional backstop. The primary injection path is now the constructor (Section 2–3). `set_records_store` is a no-op if `_records_store` was already set via constructor, so it can't silently clobber a test-injected value. Only fires if Phase 4 had `None`.

---

## Section 5: Tests

**File:** `tests/test_bf106_dreaming_di.py` (NEW)

```python
"""Tests for BF-106: DreamingEngine dependency injection."""

from __future__ import annotations

from unittest.mock import MagicMock

from probos.cognitive.dreaming import DreamingEngine
```

```python
# ---------------------------------------------------------------------------
# Tests: BF-106 — DreamingEngine dependency injection
# ---------------------------------------------------------------------------


class TestDreamingEngineDI:
    """BF-106: Verify DreamingEngine uses setters instead of monkey-patching."""

    def _make_engine(self, **kwargs):
        """Create a minimal DreamingEngine with mocked required args."""
        return DreamingEngine(
            router=MagicMock(),
            trust_network=MagicMock(),
            episodic_memory=MagicMock(),
            config=MagicMock(),
            **kwargs,
        )

    def test_set_ward_room(self):
        """BF-106: set_ward_room sets _ward_room."""
        engine = self._make_engine()
        assert engine._ward_room is None

        mock_wr = MagicMock()
        engine.set_ward_room(mock_wr)
        assert engine._ward_room is mock_wr

    def test_set_get_department(self):
        """BF-106: set_get_department sets _get_department."""
        engine = self._make_engine()
        assert engine._get_department is None

        dept_fn = lambda aid: "science"
        engine.set_get_department(dept_fn)
        assert engine._get_department is dept_fn

    def test_set_records_store(self):
        """BF-106: set_records_store sets _records_store."""
        engine = self._make_engine()
        assert engine._records_store is None

        mock_rs = MagicMock()
        engine.set_records_store(mock_rs)
        assert engine._records_store is mock_rs

    def test_records_store_via_constructor(self):
        """BF-106: records_store can be passed via constructor."""
        mock_rs = MagicMock()
        engine = self._make_engine(records_store=mock_rs)
        assert engine._records_store is mock_rs

    def test_ward_room_via_constructor(self):
        """BF-106: ward_room can be passed via constructor."""
        mock_wr = MagicMock()
        engine = self._make_engine(ward_room=mock_wr)
        assert engine._ward_room is mock_wr

    def test_defaults_are_none(self):
        """BF-106: All three late-bind attrs default to None."""
        engine = self._make_engine()
        assert engine._ward_room is None
        assert engine._get_department is None
        assert engine._records_store is None

    def test_set_records_store_noop_if_already_set(self):
        """BF-106: set_records_store is no-op if constructor-injected."""
        mock_rs = MagicMock()
        engine = self._make_engine(records_store=mock_rs)
        other_rs = MagicMock()
        engine.set_records_store(other_rs)
        assert engine._records_store is mock_rs  # Original preserved

    def test_finalize_uses_setters_not_private_attrs(self):
        """BF-106: finalize.py should not write to private _ward_room/_get_department."""
        import inspect
        from probos.startup import finalize
        src = inspect.getsource(finalize)
        assert "engine._ward_room =" not in src
        assert "engine._get_department =" not in src
        assert "engine._records_store =" not in src
```

### Existing test impact

- All existing tests that create `DreamingEngine` with mocked args — **no change needed**. The three params already default to `None`.
- `test_dreaming.py` (if it exists) — **no change needed**. Constructor signature unchanged.
- `test_ad637a_nats_foundation.py` — **no change needed**. Unrelated to DreamingEngine.

---

## Verification

```bash
# Targeted tests — new BF-106 tests
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf106_dreaming_di.py -v

# Existing dreaming tests (must not break)
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -k "dreaming" -v

# Full suite
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q
```

---

## Tracking

### PROGRESS.md
Add line:
```
BF-106 CLOSED. DreamingEngine late-init dependencies monkey-patched in finalize.py — `_ward_room`, `_records_store`, `_get_department` set via private attrs. Fix: `records_store` forwarded through init_dreaming() constructor (available Phase 4→5). `ward_room` and `get_department` get public setter methods (genuinely unavailable until Phase 7). finalize.py now calls setters instead of reaching into private attrs. 8 new tests. Issue #19.
```

### DECISIONS.md
Add entry:
```
**BF-106: DreamingEngine dependency injection — constructor for Phase 4, setters for Phase 7.** Three monkey-patched private attrs in finalize.py replaced with clean injection. `records_store` forwarded through `init_dreaming()` constructor (available at Phase 5 from Phase 4 cognitive init). `ward_room` and `get_department` (from ontology) genuinely unavailable until Phase 7 — these get public setter methods instead. Follows AD-567d (ActivationTracker) pattern for constructor injection. Establishes the template: constructor injection where startup-phase ordering allows, public setter methods where it doesn't. Generalizes the AD-654c/d Law of Demeter discipline to startup wiring.
```

### docs/development/roadmap.md
Update Bug Tracker row for BF-106 status from `Open` to `Closed`:
```
| BF-106 | DreamingEngine late-init dependencies monkey-patched in finalize.py | Closed | #19 |
```
