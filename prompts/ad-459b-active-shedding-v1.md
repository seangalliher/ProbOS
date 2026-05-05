# AD-459b — Saucer Separation v2: Active Shedding Hooks

**Status:** Drafted, awaiting Builder
**Dependencies:** AD-459 v1 (Wave 6 — `DegradationManager` + `ServiceTierRegistry` + `SheddingPolicy`; COMPLETE).
**Estimated tests:** +12 (ceiling +15)
**Closes:** GH issue #396

## Problem

`src/probos/degradation/manager.py` ships AD-459 v1 as a **read-only coordinator**: subsystems are expected to **self-poll** `runtime.degradation_manager.is_shed("dream_scheduler")` from inside their own loops and skip work when shed. At HEAD `8fa370f`, **no subsystem actually polls the manager** — `DreamScheduler` (`src/probos/cognitive/dreaming.py:2774`) and `ProactiveCognitiveLoop` (`src/probos/proactive.py:146`) keep cycling regardless of degradation level. The classification is honest but inert.

The architectural mistake is the contract direction: pushing degradation awareness to every subsystem author is fragile (each new subsystem is one missed `is_shed` check away from a degraded-mode regression) and inverts the dependency arrow — subsystems should not need to import `from probos.degradation`.

AD-459b inverts the contract. Subsystems **register** with the manager. The manager **invokes** lifecycle callbacks on tier transitions. Subsystem authors no longer need to know about degradation.

## Solution

Six additive edits + one `degradation/__init__.py` re-export:

1. **`events.py`** — add 2 EventTypes after the existing `SERVICE_TIER_RESTORED` row.
2. **`config.py`** — add `auto_pause_enabled: bool = False` to `DegradationConfig`.
3. **`src/probos/degradation/subsystem.py` (NEW)** — `SheddableSubsystem` Protocol + `LifecycleAdapter` helper.
4. **`src/probos/degradation/manager.py`** — add `register_subsystem`, `unregister_subsystem`, `registered_subsystems` public methods + 2 private `_invoke_pause` / `_invoke_resume` helpers + `_subsystems` dict + `_lifecycle_tasks` set on the constructor.
5. **`src/probos/degradation/__init__.py`** — re-export `SheddableSubsystem` and `LifecycleAdapter`.
6. **`startup/finalize.py`** — extend the existing AD-459 if-block to register `dream_scheduler` + `proactive_loop` adopters when `auto_pause_enabled=True` and the subsystems are non-None.
7. **`tests/test_ad459b_active_shedding.py` (NEW)** — 12 tests minimum.

No modification of `DreamScheduler`, `ProactiveCognitiveLoop`, or `runtime.py`.

---

## Section 0 — `src/probos/events.py` (add 2 EventTypes)

**File:** `src/probos/events.py`

**SEARCH** (locks the AD-459 EventType pair + the AD-458 row immediately following):

```python
    SERVICE_TIER_DEGRADED = "service_tier_degraded"  # AD-459
    SERVICE_TIER_RESTORED = "service_tier_restored"  # AD-459
    PREFLIGHT_FAILED = "preflight_failed"  # AD-458
```

**REPLACE** (re-emits the AD-459 pair + 2 new AD-459b rows + the AD-458 anchor):

```python
    SERVICE_TIER_DEGRADED = "service_tier_degraded"  # AD-459
    SERVICE_TIER_RESTORED = "service_tier_restored"  # AD-459
    SUBSYSTEM_PAUSED = "subsystem_paused"  # AD-459b
    SUBSYSTEM_RESUMED = "subsystem_resumed"  # AD-459b
    PREFLIGHT_FAILED = "preflight_failed"  # AD-458
```

---

## Section 1 — `src/probos/config.py` (add 1 field, update docstring)

**File:** `src/probos/config.py`

**SEARCH** (locks the entire `DegradationConfig` body verbatim — verified at HEAD line 1282-1289):

```python
class DegradationConfig(BaseModel):
    """Saucer separation / graceful degradation (AD-459).

    v1 has no operator-tunable fields — the manager is always wired and
    the default policy is the only policy. AD-459b will add fields for
    custom policies, stress-level transition thresholds, and operator
    override (e.g., shed-ESSENTIAL emergency override).
    """
```

**REPLACE** (re-emits the class + updated docstring + 1 new field):

```python
class DegradationConfig(BaseModel):
    """Saucer separation / graceful degradation (AD-459 / AD-459b).

    AD-459 v1 shipped the read-only coordinator (always-wired, no
    operator-tunable fields). AD-459b adds active subsystem pause/resume
    hooks gated by ``auto_pause_enabled`` (default False per Wave-10
    convention #14 — transitional flag, default off until validated in
    rehearsal). When True, finalize.py registers ``dream_scheduler`` and
    ``proactive_loop`` adopters via ``LifecycleAdapter``; the manager
    invokes their pause/resume callbacks on tier-mask transitions.

    Future: custom policies, stress-level thresholds, operator override
    for shed-ESSENTIAL emergency mode.
    """

    auto_pause_enabled: bool = False
```

---

## Section 2 — `src/probos/degradation/subsystem.py` (NEW file)

**File:** `src/probos/degradation/subsystem.py`

Create the file with this exact content:

```python
"""AD-459b: SheddableSubsystem Protocol + LifecycleAdapter helper.

The Protocol defines the contract DegradationManager invokes on tier-mask
transitions: ``async pause()`` when the subsystem's tier enters the shed
mask, ``async resume()`` when it leaves. Both methods MUST be idempotent.

The LifecycleAdapter wraps existing ``start()`` / ``stop()`` methods
(sync or async) so subsystems do not need to learn the Protocol. Adoption
is one-line at finalize time:

    runtime.degradation_manager.register_subsystem(
        "dream_scheduler",
        LifecycleAdapter(
            "dream_scheduler",
            on_pause=runtime.dream_scheduler.stop,
            on_resume=runtime.dream_scheduler.start,
        ),
    )
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class SheddableSubsystem(Protocol):
    """Contract for subsystems that can be paused/resumed by DegradationManager.

    Both methods MUST be idempotent. Calling ``pause()`` on an already-paused
    subsystem MUST be a no-op (not an error). Same for ``resume()``.
    """

    async def pause(self) -> None: ...

    async def resume(self) -> None: ...


class LifecycleAdapter:
    """Adapts existing ``start()`` / ``stop()`` callables to SheddableSubsystem.

    Both ``on_pause`` and ``on_resume`` may be sync or async callables.
    Dispatch uses ``asyncio.iscoroutinefunction(...)`` (BF-254 pattern).

    Tracks an internal ``_paused`` bool to enforce idempotency: pause() on
    a paused subsystem is a no-op + DEBUG log; resume() on a running
    subsystem is a no-op + DEBUG log.
    """

    def __init__(
        self,
        name: str,
        *,
        on_pause: Callable[[], Any],
        on_resume: Callable[[], Any],
    ) -> None:
        self._name = name
        self._on_pause = on_pause
        self._on_resume = on_resume
        self._paused = False

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_paused(self) -> bool:
        return self._paused

    async def pause(self) -> None:
        if self._paused:
            logger.debug("AD-459b: %s already paused; no-op", self._name)
            return
        await self._invoke(self._on_pause)
        self._paused = True

    async def resume(self) -> None:
        if not self._paused:
            logger.debug("AD-459b: %s already running; no-op", self._name)
            return
        await self._invoke(self._on_resume)
        self._paused = False

    @staticmethod
    async def _invoke(callable_: Callable[[], Any]) -> None:
        if asyncio.iscoroutinefunction(callable_):
            await callable_()
        else:
            callable_()
```

---

## Section 3 — `src/probos/degradation/manager.py` (extend)

**File:** `src/probos/degradation/manager.py`

### Section 3a — extend imports

**SEARCH** (locks the existing top-of-file import block):

```python
"""AD-459: Degradation manager — read-only shedding coordinator (v1).

v1 surfaces the policy decision via `is_shed(service_name)` and `is_tier_shed(tier)`.
Subsystems consult these and self-degrade. v1 does NOT mutate any subsystem
state directly. Active shedding (subsystem hooks) is deferred to AD-459b.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from probos.degradation.policy import SheddingPolicy, StressLevel
from probos.degradation.registry import ServiceTier, ServiceTierRegistry
from probos.events import EventType
```

**REPLACE** (updated docstring + adds `asyncio` import + adds `SheddableSubsystem` import):

```python
"""AD-459 / AD-459b: Degradation manager — shedding coordinator.

AD-459 v1 surfaced the policy decision via ``is_shed(service_name)`` and
``is_tier_shed(tier)``. Subsystems consulted these and self-degraded.

AD-459b adds active shedding: subsystems register via
``register_subsystem(name, subsystem)`` and the manager invokes their
``pause()`` / ``resume()`` callbacks on tier-mask transitions. Every
invocation is fire-and-forget (``asyncio.create_task(...)``) and wrapped
in tier-2 log-and-degrade — a subsystem-side failure NEVER propagates.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from probos.degradation.policy import SheddingPolicy, StressLevel
from probos.degradation.registry import ServiceTier, ServiceTierRegistry
from probos.degradation.subsystem import SheddableSubsystem
from probos.events import EventType
```

### Section 3b — extend `__init__`

**SEARCH** (locks the existing `__init__` body verbatim):

```python
    def __init__(
        self,
        *,
        registry: ServiceTierRegistry,
        policy: SheddingPolicy,
        emit_event: Any | None = None,
    ) -> None:
        self._registry = registry
        self._policy = policy
        self._emit_event = emit_event
        self._level = StressLevel.NORMAL
        self._updated_at = time.time()
```

**REPLACE** (adds `_subsystems` and `_lifecycle_tasks`):

```python
    def __init__(
        self,
        *,
        registry: ServiceTierRegistry,
        policy: SheddingPolicy,
        emit_event: Any | None = None,
    ) -> None:
        self._registry = registry
        self._policy = policy
        self._emit_event = emit_event
        self._level = StressLevel.NORMAL
        self._updated_at = time.time()
        # AD-459b: registered subsystems (by service_name) + fire-and-forget
        # task references per Standing Order on async hygiene.
        self._subsystems: dict[str, SheddableSubsystem] = {}
        self._lifecycle_tasks: set[asyncio.Task[None]] = set()
```

### Section 3c — extend `set_stress_level` (stays sync; adds task scheduling)

**SEARCH** (locks the existing `set_stress_level` body verbatim):

```python
    def set_stress_level(self, level: StressLevel) -> None:
        if level == self._level:
            return
        previous = self._level
        self._level = level
        self._updated_at = time.time()
        prev_shed = self._policy.shed_tiers(previous)
        new_shed = self._policy.shed_tiers(level)
        for tier in new_shed - prev_shed:
            self._emit_tier_change(tier, shed=True)
        for tier in prev_shed - new_shed:
            self._emit_tier_change(tier, shed=False)
```

**REPLACE** (re-emits the AD-459 v1 body verbatim; appends AD-459b subsystem-task scheduling):

```python
    def set_stress_level(self, level: StressLevel) -> None:
        if level == self._level:
            return
        previous = self._level
        self._level = level
        self._updated_at = time.time()
        prev_shed = self._policy.shed_tiers(previous)
        new_shed = self._policy.shed_tiers(level)
        for tier in new_shed - prev_shed:
            self._emit_tier_change(tier, shed=True)
        for tier in prev_shed - new_shed:
            self._emit_tier_change(tier, shed=False)
        # AD-459b: schedule subsystem pause/resume tasks for tier-mask deltas.
        # Stays fire-and-forget so callers keep the AD-459 v1 sync API.
        self._schedule_subsystem_transitions(
            pause_tiers=new_shed - prev_shed,
            resume_tiers=prev_shed - new_shed,
        )

    def _schedule_subsystem_transitions(
        self,
        *,
        pause_tiers: frozenset[ServiceTier],
        resume_tiers: frozenset[ServiceTier],
    ) -> None:
        """AD-459b: schedule async pause/resume tasks; tier-2 log-and-degrade.

        Skips silently when there is no running event loop (e.g., a sync
        test that does not drive the manager via ``asyncio.run(...)``).
        """
        if not self._subsystems:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.debug(
                "AD-459b: no running event loop; subsystem transitions skipped",
            )
            return
        for tier in pause_tiers:
            for name, subsystem in self._subsystems.items():
                if self._registry.get_tier(name) == tier:
                    self._spawn_lifecycle_task(
                        loop, self._invoke_pause(name, subsystem, tier),
                    )
        for tier in resume_tiers:
            for name, subsystem in self._subsystems.items():
                if self._registry.get_tier(name) == tier:
                    self._spawn_lifecycle_task(
                        loop, self._invoke_resume(name, subsystem, tier),
                    )

    def _spawn_lifecycle_task(
        self, loop: asyncio.AbstractEventLoop, coro: Any,
    ) -> None:
        task = loop.create_task(coro)
        self._lifecycle_tasks.add(task)
        task.add_done_callback(self._lifecycle_tasks.discard)

    async def _invoke_pause(
        self, name: str, subsystem: SheddableSubsystem, tier: ServiceTier,
    ) -> None:
        try:
            await subsystem.pause()
        except Exception:
            logger.warning(
                "AD-459b: %s.pause() failed (tier=%s, level=%s)",
                name, tier.value, self._level.value, exc_info=True,
            )
            return
        self._emit_subsystem_event(EventType.SUBSYSTEM_PAUSED, name, tier)

    async def _invoke_resume(
        self, name: str, subsystem: SheddableSubsystem, tier: ServiceTier,
    ) -> None:
        try:
            await subsystem.resume()
        except Exception:
            logger.warning(
                "AD-459b: %s.resume() failed (tier=%s, level=%s)",
                name, tier.value, self._level.value, exc_info=True,
            )
            return
        self._emit_subsystem_event(EventType.SUBSYSTEM_RESUMED, name, tier)

    def _emit_subsystem_event(
        self, event_type: EventType, name: str, tier: ServiceTier,
    ) -> None:
        if not self._emit_event:
            return
        try:
            self._emit_event(
                event_type,
                {
                    "service": name,
                    "tier": tier.value,
                    "stress_level": self._level.value,
                },
            )
        except Exception:
            logger.warning(
                "AD-459b: %s emit failed (service=%s, tier=%s)",
                event_type.value, name, tier.value, exc_info=True,
            )
```

### Section 3d — add subsystem registry public methods

**SEARCH** (locks the existing `is_tier_shed` method body and the `status()` method that follows — anchor for safe append):

```python
    def is_tier_shed(self, tier: ServiceTier) -> bool:
        return tier in self._policy.shed_tiers(self._level)

    def status(self) -> DegradationStatus:
```

**REPLACE** (re-emits both methods verbatim; inserts 3 new public methods between):

```python
    def is_tier_shed(self, tier: ServiceTier) -> bool:
        return tier in self._policy.shed_tiers(self._level)

    def register_subsystem(
        self, service_name: str, subsystem: SheddableSubsystem,
    ) -> None:
        """AD-459b: register a subsystem for active pause/resume.

        Raises ValueError if ``service_name`` is not classified in the
        registry — the manager refuses to manage an unclassified subsystem
        because it would not know which tier mask gates the lifecycle.

        Replacing an existing registration logs a WARNING and overwrites
        (mirrors ToolRegistry / ProcessChainRegistry precedent — useful
        for hot-reload and test isolation).
        """
        if self._registry.get_tier(service_name) is None:
            raise ValueError(
                f"AD-459b: service_name {service_name!r} not classified "
                f"in ServiceTierRegistry; classify before registering.",
            )
        if service_name in self._subsystems:
            logger.warning(
                "AD-459b: subsystem %r already registered; replacing",
                service_name,
            )
        self._subsystems[service_name] = subsystem

    def unregister_subsystem(self, service_name: str) -> bool:
        """AD-459b: remove a subsystem; returns False if absent."""
        return self._subsystems.pop(service_name, None) is not None

    def registered_subsystems(self) -> list[str]:
        """AD-459b: sorted list of registered service names (for inspection)."""
        return sorted(self._subsystems.keys())

    def status(self) -> DegradationStatus:
```

---

## Section 4 — `src/probos/degradation/__init__.py` (re-export)

**File:** `src/probos/degradation/__init__.py`

The current file is a 1-line module docstring. Replace its entire contents with:

```python
"""Saucer Separation — Graceful Degradation (AD-459 / AD-459b)."""

from probos.degradation.subsystem import LifecycleAdapter, SheddableSubsystem

__all__ = [
    "LifecycleAdapter",
    "SheddableSubsystem",
]
```

This is a full-file replacement (1-line file → 7-line file). No SEARCH/REPLACE block needed — the Builder writes the entire new content.

---

## Section 5 — `src/probos/startup/finalize.py` (extend AD-459 block)

**File:** `src/probos/startup/finalize.py`

**SEARCH** (locks the entire AD-459 wiring block verbatim — verified at HEAD lines 1188-1200):

```python
    # AD-459: Saucer separation -- graceful degradation
    # v1 always wires the manager (no enabled flag) so consumers can call
    # `runtime.degradation_manager.is_shed(name)` without a None check.
    # Default state is StressLevel.NORMAL (no shedding).
    from probos.degradation.manager import DegradationManager
    from probos.degradation.policy import SheddingPolicy
    from probos.degradation.registry import ServiceTierRegistry
    runtime.degradation_manager = DegradationManager(
        registry=ServiceTierRegistry(),
        policy=SheddingPolicy(),
        emit_event=runtime.emit_event,
    )
    logger.info("AD-459: DegradationManager wired (stress=normal)")
```

**REPLACE** (re-emits the AD-459 block verbatim; appends AD-459b adopter registration gated by `auto_pause_enabled`):

```python
    # AD-459: Saucer separation -- graceful degradation
    # v1 always wires the manager (no enabled flag) so consumers can call
    # `runtime.degradation_manager.is_shed(name)` without a None check.
    # Default state is StressLevel.NORMAL (no shedding).
    from probos.degradation.manager import DegradationManager
    from probos.degradation.policy import SheddingPolicy
    from probos.degradation.registry import ServiceTierRegistry
    runtime.degradation_manager = DegradationManager(
        registry=ServiceTierRegistry(),
        policy=SheddingPolicy(),
        emit_event=runtime.emit_event,
    )
    logger.info("AD-459: DegradationManager wired (stress=normal)")

    # AD-459b: register active-shedding adopters when operator opts in.
    # Default `auto_pause_enabled=False` keeps the AD-459 v1 read-only
    # contract; flipping to True wires DreamScheduler + ProactiveCognitiveLoop
    # adopters whose `start`/`stop` methods are invoked on tier transitions.
    #
    # Source-attribute notes:
    #   * `runtime.dream_scheduler` is set during the dreaming phase (see
    #     runtime.py:1516) BEFORE `finalize_startup` is invoked, so the
    #     attribute is available here.
    #   * `proactive_loop` is the LOCAL variable bound at line ~863 / ~985
    #     of this same function. `runtime.proactive_loop` is NOT yet
    #     assigned at this point — that happens after finalize_startup
    #     returns (runtime.py:1704). Use the local binding.
    if config.degradation.auto_pause_enabled:
        from probos.degradation.subsystem import LifecycleAdapter
        adopters_registered: list[str] = []
        if runtime.dream_scheduler is not None:
            runtime.degradation_manager.register_subsystem(
                "dream_scheduler",
                LifecycleAdapter(
                    "dream_scheduler",
                    on_pause=runtime.dream_scheduler.stop,
                    on_resume=runtime.dream_scheduler.start,
                ),
            )
            adopters_registered.append("dream_scheduler")
        if proactive_loop is not None:
            runtime.degradation_manager.register_subsystem(
                "proactive_loop",
                LifecycleAdapter(
                    "proactive_loop",
                    on_pause=proactive_loop.stop,
                    on_resume=proactive_loop.start,
                ),
            )
            adopters_registered.append("proactive_loop")
        logger.info(
            "AD-459b: active shedding enabled; adopters=%s",
            adopters_registered,
        )
```

---

## Section 6 — `tests/test_ad459b_active_shedding.py` (NEW file)

**File:** `tests/test_ad459b_active_shedding.py`

Create the file. Target 12 tests minimum (ceiling 15). Required test names + behaviors:

1. `test_event_type_subsystem_paused_exists` — `EventType.SUBSYSTEM_PAUSED.value == "subsystem_paused"`.
2. `test_event_type_subsystem_resumed_exists` — `EventType.SUBSYSTEM_RESUMED.value == "subsystem_resumed"`.
3. `test_degradation_config_auto_pause_default_false` — `DegradationConfig().auto_pause_enabled is False`.
4. `test_lifecycle_adapter_async_callable_invoked` — wrap an `AsyncMock` for both pause + resume; call `await adapter.pause()`; assert mock awaited; `adapter.is_paused is True`.
5. `test_lifecycle_adapter_sync_callable_invoked` — wrap a `MagicMock` (sync); call `await adapter.pause()`; assert mock called once.
6. `test_lifecycle_adapter_pause_idempotent` — `await adapter.pause()` twice; sync/async on_pause called exactly once; `is_paused is True`.
7. `test_lifecycle_adapter_resume_idempotent` — pause then resume twice; on_resume called exactly once; `is_paused is False`.
8. `test_register_subsystem_rejects_unknown_name` — `pytest.raises(ValueError, match="not classified")` on a name absent from registry.
9. `test_register_subsystem_replaces_with_warning` — register twice with same name + different adapters; `caplog` captures WARNING; `manager.registered_subsystems() == [name]`; second adapter is the one held.
10. `test_unregister_subsystem_returns_true_when_present_else_false` — register; unregister returns True; unregister again returns False.
11. `test_set_stress_level_pauses_cognitive_subsystems_on_high` — register a `dream_scheduler` adapter (uses MagicMock for both callables); `manager.set_stress_level(StressLevel.HIGH)`; await all pending tasks via `await asyncio.gather(*manager._lifecycle_tasks)` (or alternative drain pattern); assert pause callable called once + `EventType.SUBSYSTEM_PAUSED` emitted with `service="dream_scheduler"`. The test runs inside `asyncio.run(...)` so `set_stress_level` finds a running loop.
12. `test_set_stress_level_resumes_on_normal_after_high` — set HIGH, drain tasks, set NORMAL, drain tasks; assert resume called once + `EventType.SUBSYSTEM_RESUMED` emitted; `adapter.is_paused is False`.
13. `test_pause_exception_logs_warning_and_skips_event` — register an adapter whose pause raises RuntimeError; transition to HIGH; drain; assert WARNING captured + `EventType.SUBSYSTEM_PAUSED` NOT in emitted events for that service.
14. `test_no_subsystems_registered_set_stress_level_is_noop_for_subsystems` — `set_stress_level(HIGH)` with zero registered subsystems; assert `manager._lifecycle_tasks` is empty; AD-459 tier-level events still emit normally.
15. `test_set_stress_level_skips_subsystem_tasks_outside_event_loop` — call `set_stress_level(HIGH)` from a sync context (no `asyncio.run`); assert no exception raised; assert `manager._lifecycle_tasks` is empty.

Builder may add boundary tests up to ceiling 15. Test fixtures: import `from probos.config import DegradationConfig`, `from probos.degradation import LifecycleAdapter, SheddableSubsystem`, `from probos.degradation.manager import DegradationManager`, `from probos.degradation.policy import SheddingPolicy, StressLevel`, `from probos.degradation.registry import ServiceTier, ServiceTierRegistry`, `from probos.events import EventType`. Use `unittest.mock.MagicMock` and `unittest.mock.AsyncMock`.

The drain pattern for tests #11-#13:

```python
async def _drain(mgr: DegradationManager) -> None:
    pending = list(mgr._lifecycle_tasks)
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
```

Each async test wraps body in `asyncio.run(_inner())`.

---

## What This Does NOT Change

- **`src/probos/cognitive/dreaming.py`** — `DreamScheduler.start/stop` unchanged.
- **`src/probos/proactive.py`** — `ProactiveCognitiveLoop.start/stop` unchanged.
- **`src/probos/runtime.py`** — no new attributes, no new constructor args, no new method.
- **`src/probos/degradation/registry.py`** — no new classifications. The 11 seed entries are correct as-is.
- **`src/probos/degradation/policy.py`** — `SheddingPolicy.shed_tiers` unchanged; HIGH and CRITICAL still share the shed mask in v1.
- **No capability gate** on `register_subsystem` (deferred AD-459b-4).
- **No audit chain emission** beyond the EventType events (deferred AD-459b-5).
- **No EmergenceMetricsEngine, EmergentLeadershipDetector, RedTeamLead adoption** (deferred AD-459b-1 / -2 / -3).
- **No AD-469 EPS-driven auto-escalation of stress level** (deferred AD-459b-6).
- **No HXI surface for subsystem state** (deferred AD-459b-8).
- **No new public attribute on runtime** — `runtime.degradation_manager` already exists.
- **No DECISIONS.md update** — AD-459b is not a cross-AD architectural inflection.

## Tracking

- `PROGRESS.md` — append `AD-459b v1 CLOSED.` paragraph (Wave 60 / Wave 59 shape).
- `docs/development/roadmap.md:4162` — flip status from `*(Scoped, OSS, Issue #396)*` to `*(complete)*`.
- `prompts/wave-plan.yaml` — `id: 61` `status: done` (during archive step).
- GH issue #396 — closed by Captain post-merge with commit hash.

## Acceptance Criteria

1. Test count delta lands in [+12, +15] inclusive.
2. All 13 existing AD-459 v1 tests in `tests/test_ad459_saucer_separation.py` pass unchanged.
3. All 12+ new AD-459b tests pass.
4. Full gate (`pytest tests/ -q -n 4 --dist=loadfile`) passes with new total in [11316, 11319].
5. `runtime.degradation_manager.register_subsystem(name, subsystem)` is a public method that validates `name` against the registry and raises `ValueError` on unknown names.
6. `LifecycleAdapter` and `SheddableSubsystem` are importable from `probos.degradation`.
7. `EventType.SUBSYSTEM_PAUSED` and `EventType.SUBSYSTEM_RESUMED` are defined and emitted on real (non-failing) transitions.
8. `DegradationConfig.auto_pause_enabled` defaults False; finalize wires zero adopters under default config.
9. With `auto_pause_enabled=True`, finalize wires `dream_scheduler` adopter (when `runtime.dream_scheduler is not None`) and `proactive_loop` adopter (when the **local** `proactive_loop` variable is not None — `runtime.proactive_loop` is not yet assigned at finalize-time).
10. No modification of `DreamScheduler`, `ProactiveCognitiveLoop`, or `runtime.py`.
11. `set_stress_level` signature stays sync (`def set_stress_level(self, level: StressLevel) -> None:`).
12. Pause/resume failures log at WARNING and do NOT propagate.
13. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
14. Pre-commit deletion sanity: max ~5 deletions any single file. The `degradation/__init__.py` 1-line→7-line rewrite is technically a 1-line delete + 7-line add; documented in build report.

---

## Verified Against Codebase (2026-05-05, HEAD `8fa370f`)

```
grep -n "SERVICE_TIER_RESTORED\|PREFLIGHT_FAILED" src/probos/events.py
  198: SERVICE_TIER_DEGRADED = "service_tier_degraded"  # AD-459
  199: SERVICE_TIER_RESTORED = "service_tier_restored"  # AD-459
  200: PREFLIGHT_FAILED = "preflight_failed"  # AD-458

grep -n "class DegradationConfig" src/probos/config.py
  1282: class DegradationConfig(BaseModel):
  ... docstring through line 1289 ...

grep -n "class DegradationManager\|def set_stress_level\|def is_shed\|def is_tier_shed\|def status" src/probos/degradation/manager.py
  31:  class DegradationManager:
  60:  def set_stress_level(self, level: StressLevel) -> None:
  74:  def is_shed(self, service_name: str) -> bool:
  80:  def is_tier_shed(self, tier: ServiceTier) -> bool:
  83:  def status(self) -> DegradationStatus:

grep -n "_DEFAULT_CLASSIFICATIONS" src/probos/degradation/registry.py
  31-49: _DEFAULT_CLASSIFICATIONS includes "dream_scheduler" + "proactive_loop" classified COGNITIVE

grep -n "AD-459: Saucer separation" src/probos/startup/finalize.py
  1188: # AD-459: Saucer separation -- graceful degradation
  1195: runtime.degradation_manager = DegradationManager(
  1200: logger.info("AD-459: DegradationManager wired (stress=normal)")

grep -n "class DreamScheduler\|def start\|async def stop" src/probos/cognitive/dreaming.py
  2774: class DreamScheduler:
  2816: def start(self) -> None:
  2824: async def stop(self) -> None:

grep -n "class ProactiveCognitiveLoop\|async def start\|async def stop" src/probos/proactive.py
  146:  class ProactiveCognitiveLoop:
  454:  async def start(self) -> None:
  460:  async def stop(self) -> None:

grep -n "dream_scheduler: DreamScheduler\|proactive_loop: ProactiveCognitiveLoop" src/probos/runtime.py
  210: dream_scheduler: DreamScheduler | None
  230: proactive_loop: ProactiveCognitiveLoop | None
  413: self.dream_scheduler: DreamScheduler | None = None
  549: self.proactive_loop: ProactiveCognitiveLoop | None = None
  1516: self.dream_scheduler = dream_result.dream_scheduler   # set BEFORE finalize.py:1188
  1704: self.proactive_loop = fin.proactive_loop              # set BEFORE finalize.py:1188

cat src/probos/degradation/__init__.py
  """Saucer Separation — Graceful Degradation (AD-459)."""
  (single-line file; safe to overwrite)

pytest tests/test_ad459_saucer_separation.py -q --co
  13 tests collected (existing AD-459 v1 baseline; must remain green)

grep -rn "AD-459a" prompts/ DECISIONS.md PROGRESS.md decisions-era-*.md progress-era-*.md
  (no matches — anti-misclassification clause clean)

grep -rn "register_subsystem\|SheddableSubsystem\|SUBSYSTEM_PAUSED\|SUBSYSTEM_RESUMED" src/ tests/
  (no matches — collision-free greenfield for all new public surfaces)
```

All 16 verifying greps confirmed. AD numbering: highest existing AD per PROGRESS.md is AD-695b. AD-459b is correctly the b-tier root for the AD-459 cluster (closes #396); AD-459b-1 through AD-459b-9 are reserved for the deferred adopters and follow-ups documented in the dispatch DLog #13 + AD list at end of "Summary".
