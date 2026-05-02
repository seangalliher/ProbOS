# AD-467: Operations Crew — Resource Management & Coordination

**Status:** Ready for builder
**Dependencies:** None hard. Mirrors AD-457 `agents/engineering/` package pattern (verified at `src/probos/agents/engineering/__init__.py` shipped Wave 6) and AD-455 `security/` precedent. **AD-467 OWNS `src/probos/agents/operations/__init__.py` directory creation.**
**Estimated tests:** ~13
**Risk:** Medium — cross-cutting (creates new agent package, touches `events.py`, `config.py`, `runtime.py` template registration, `startup/agent_fleet.py` pool spawn). No consensus paths affected.

---

## Problem

The Operations Officer (AD-398) cognitive agent exists at `runtime.py:620` (`register_template("operations_officer", OperationsAgent)`) and `agent_fleet.py:132-138` (single-instance pool), but the Operations Team has no equivalent service agents the way Medical (`agents/medical/`) and Engineering (`agents/engineering/`, AD-457) do. Resource allocation, task scheduling, and cross-team coordination are scattered across `workforce.py`, `routers/scheduled_tasks.py`, and ad-hoc proactive-loop hooks.

`grep -rn "operations" src/probos/agents/` returns no `agents/operations/` package today (verified: `Test-Path src/probos/agents/operations` returns False).

What is missing:

1. **`ResourceAllocatorAgent`** — heartbeat agent that reports cross-pool capacity (active counts, target sizes, saturation). Distinct from VitalsMonitor (per-pool health) and PerformanceMonitor (latency/throughput).
2. **`SchedulerAgent`** — heartbeat agent that emits `TASK_SCHEDULED` events at configured cadence. Distinct from `routers/scheduled_tasks.py` operator-facing API; this is the agent surface that consumes scheduled work.
3. **`CoordinatorAgent`** — emits `WORKFLOW_STARTED` for multi-step task batches. Distinct from `OrderManager` (AD-440 chain-of-command directives); coordinator handles operational batch flows.

`grep -rn "ResourceAllocatorAgent\|SchedulerAgent\|CoordinatorAgent" src/probos/` returns no matches.

## Solution Overview

Create `src/probos/agents/operations/` package with three HeartbeatAgent subclasses (mirrors the Wave 6 AD-457 pattern). All three subclass `HeartbeatAgent` (verified at `substrate/heartbeat.py:18`). Templates registered in `runtime.py` after `engineering_officer` block; pools spawned in `agent_fleet.py` after the AD-457 engineering crew block.

This is **policy + diagnostics layered on substrate primitives.** AD-467 does NOT modify `HeartbeatAgent`, does NOT change pool spawning machinery, does NOT touch `OrderManager` (AD-440), does NOT extend `workforce.BookingJournal`. It populates the operations crew with three task-specific HeartbeatAgent subclasses that emit events at configured cadence.

**v1 scope (no-theater discipline per Wave 5 retrospective convention #7):**

The roadmap entry lists 6 capabilities. v1 ships 3 agents only:

- **ResourceAllocator, Scheduler, Coordinator** — real-work HeartbeatAgent subclasses.

Three deferred to sub-ADs:

- **WorkflowDefinition API endpoint** — REST surface deferred to AD-467b once consumers (Coordinator handlers) are exercised in production.
- **Response-Time Scaling** — deferred to AD-467c (cross-cuts auto-scaler at `substrate/scaler.py`; substantial work).
- **LLM Cost Tracker** — deferred to AD-467d. Depends on AD-463 ModelRegistry (sibling Wave 7) for per-model cost data and AD-460 CognitiveJournal token ledger (already shipped). Scoping after AD-463 lands.

---

## Section 0: Event Types

Add to `src/probos/events.py`:

```
RESOURCE_ALLOCATED = "resource_allocated"  # AD-467
TASK_SCHEDULED = "task_scheduled"  # AD-467
WORKFLOW_STARTED = "workflow_started"  # AD-467
```

Three new values. Verified absent via `grep -n "RESOURCE_ALLOCATED\|TASK_SCHEDULED\|WORKFLOW_STARTED" src/probos/events.py` (no matches).

---

## Section 1: Create `src/probos/agents/operations/` package

**IMPORTANT:** `src/probos/agents/operations/` does NOT exist. Create `src/probos/agents/operations/__init__.py` first — same pattern as `agents/engineering/__init__.py` (AD-457) and `agents/medical/__init__.py`.

```python
"""Operations team pool -- resource allocation, scheduling, coordination (AD-467)."""

from probos.agents.operations.resource_allocator import ResourceAllocatorAgent
from probos.agents.operations.scheduler import SchedulerAgent
from probos.agents.operations.coordinator import CoordinatorAgent

__all__ = [
    "ResourceAllocatorAgent",
    "SchedulerAgent",
    "CoordinatorAgent",
]
```

---

## Section 2: `ResourceAllocatorAgent`

**File:** `src/probos/agents/operations/resource_allocator.py` (new)

```python
"""AD-467: Resource Allocator -- cross-pool capacity reporting."""

from __future__ import annotations

import logging
import time
from typing import Any

from probos.events import EventType
from probos.substrate.heartbeat import HeartbeatAgent
from probos.types import CapabilityDescriptor, IntentDescriptor

logger = logging.getLogger(__name__)


class ResourceAllocatorAgent(HeartbeatAgent):
    agent_type = "resource_allocator"
    tier = "core"
    default_capabilities = [
        CapabilityDescriptor(
            can="resource_allocation",
            detail="Cross-pool capacity reporting and allocation suggestions",
        ),
    ]
    intent_descriptors: list[IntentDescriptor] = [
        IntentDescriptor(
            name="resource_status",
            params={"pool": "pool name (or 'all')"},
            description="Report active/target/saturation for a pool or all pools",
        ),
    ]
    initial_confidence = 0.95

    def __init__(
        self,
        pool: str = "operations_resource",
        interval: float = 30.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(pool=pool, interval=interval, **kwargs)
        self._runtime = kwargs.get("runtime")
        self._last_emit_at: float = 0.0
        self._emit_interval_seconds: float = kwargs.get("emit_interval_seconds", 60.0)

    async def collect_metrics(self) -> dict[str, Any]:
        rt = self._runtime
        metrics: dict[str, Any] = {
            "timestamp": time.time(),
            "agent_id": self.id,
        }
        if rt is None:
            return metrics
        pools = getattr(rt, "pools", {}) or {}
        capacity: dict[str, dict[str, int]] = {}
        for pool_name, pool_obj in pools.items():
            try:
                target = int(getattr(pool_obj, "target_size", 0) or 0)
                active = int(getattr(pool_obj, "active_count", 0) or 0)
                capacity[pool_name] = {
                    "active": active,
                    "target": target,
                }
            except Exception:
                continue
        metrics["capacity"] = capacity
        now = time.time()
        if now - self._last_emit_at >= self._emit_interval_seconds:
            self._emit_allocation(capacity, now)
            self._last_emit_at = now
        return metrics

    def _emit_allocation(self, capacity: dict[str, dict[str, int]], at: float) -> None:
        rt = self._runtime
        if rt is None:
            return
        try:
            rt.emit_event(
                EventType.RESOURCE_ALLOCATED,
                {
                    "capacity": capacity,
                    "reported_at": at,
                    "agent_id": self.id,
                },
            )
        except Exception:
            logger.warning(
                "AD-467: RESOURCE_ALLOCATED emit failed", exc_info=True,
            )
```

---

## Section 3: `SchedulerAgent`

**File:** `src/probos/agents/operations/scheduler.py` (new)

Schedules but does NOT execute tasks -- emits `TASK_SCHEDULED` events for `routers/scheduled_tasks.py` and the proactive loop to consume. Distinct from AD-457 MaintenanceAgent (engineering housekeeping); this is operations-batch scheduling.

```python
"""AD-467: Scheduler -- emits TASK_SCHEDULED events at configured cadence."""

from __future__ import annotations

import logging
import time
from typing import Any

from probos.events import EventType
from probos.substrate.heartbeat import HeartbeatAgent
from probos.types import CapabilityDescriptor, IntentDescriptor

logger = logging.getLogger(__name__)


class SchedulerAgent(HeartbeatAgent):
    agent_type = "scheduler"
    tier = "core"
    default_capabilities = [
        CapabilityDescriptor(
            can="task_scheduling",
            detail="Operations-batch task scheduling via TASK_SCHEDULED events",
        ),
    ]
    intent_descriptors: list[IntentDescriptor] = [
        IntentDescriptor(
            name="schedule_task",
            params={
                "task_kind": "task category name",
                "scheduled_at": "epoch seconds when task should run",
            },
            description="Request a task be scheduled at a specific time",
        ),
    ]
    initial_confidence = 0.95

    def __init__(
        self,
        pool: str = "operations_scheduler",
        interval: float = 60.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(pool=pool, interval=interval, **kwargs)
        self._runtime = kwargs.get("runtime")
        self._task_cadences: dict[str, float] = kwargs.get(
            "task_cadences",
            {
                "operations_audit": 3600.0,    # hourly
                "operations_summary": 86400.0,  # daily
            },
        )
        self._last_scheduled: dict[str, float] = {}

    async def collect_metrics(self) -> dict[str, Any]:
        now = time.time()
        for kind, cadence in self._task_cadences.items():
            last = self._last_scheduled.get(kind, 0.0)
            if now - last >= cadence:
                self._schedule(kind, now)
                self._last_scheduled[kind] = now
        return {"last_scheduled": dict(self._last_scheduled)}

    def _schedule(self, task_kind: str, scheduled_at: float) -> None:
        rt = self._runtime
        if rt is None:
            return
        try:
            rt.emit_event(
                EventType.TASK_SCHEDULED,
                {
                    "task_kind": task_kind,
                    "scheduled_at": scheduled_at,
                    "agent_id": self.id,
                },
            )
        except Exception:
            logger.warning(
                "AD-467: TASK_SCHEDULED emit failed", exc_info=True,
            )
        logger.info("AD-467: scheduled '%s' at %.1f", task_kind, scheduled_at)
```

---

## Section 4: `CoordinatorAgent`

**File:** `src/probos/agents/operations/coordinator.py` (new)

Emits `WORKFLOW_STARTED` events when a coordinated batch of tasks begins. v1 ships the dispatch surface and an in-memory workflow registry; deeper workflow execution stays in the existing handlers (`workforce.py`, scheduled tasks, IntentBus). Coordinator coordinates; it does not re-implement task execution.

```python
"""AD-467: Coordinator -- multi-step workflow start/track via events."""

from __future__ import annotations

import logging
import time
from typing import Any

from probos.events import EventType
from probos.substrate.heartbeat import HeartbeatAgent
from probos.types import CapabilityDescriptor, IntentDescriptor

logger = logging.getLogger(__name__)


class CoordinatorAgent(HeartbeatAgent):
    agent_type = "coordinator"
    tier = "core"
    default_capabilities = [
        CapabilityDescriptor(
            can="workflow_coordination",
            detail="Multi-step workflow dispatch and tracking",
        ),
    ]
    intent_descriptors: list[IntentDescriptor] = [
        IntentDescriptor(
            name="start_workflow",
            params={
                "workflow_name": "workflow identifier",
                "steps": "list of step names",
            },
            description="Start a multi-step workflow",
        ),
    ]
    initial_confidence = 0.95

    def __init__(
        self,
        pool: str = "operations_coordinator",
        interval: float = 60.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(pool=pool, interval=interval, **kwargs)
        self._runtime = kwargs.get("runtime")
        self._active_workflows: dict[str, dict[str, Any]] = {}

    async def collect_metrics(self) -> dict[str, Any]:
        # Coordinator is event-driven, not poll-driven.
        return {
            "active_workflows": len(self._active_workflows),
        }

    def start_workflow(self, workflow_name: str, steps: list[str]) -> bool:
        """Record and emit a workflow start.

        Returns True on accept, False if a workflow with this name is already active.
        """
        if not workflow_name:
            return False
        if workflow_name in self._active_workflows:
            return False
        now = time.time()
        self._active_workflows[workflow_name] = {
            "steps": list(steps),
            "started_at": now,
        }
        rt = self._runtime
        if rt is not None:
            try:
                rt.emit_event(
                    EventType.WORKFLOW_STARTED,
                    {
                        "workflow_name": workflow_name,
                        "step_count": len(steps),
                        "started_at": now,
                        "agent_id": self.id,
                    },
                )
            except Exception:
                logger.warning(
                    "AD-467: WORKFLOW_STARTED emit failed", exc_info=True,
                )
        logger.info("AD-467: workflow '%s' started (%d steps)", workflow_name, len(steps))
        return True

    def complete_workflow(self, workflow_name: str) -> bool:
        return self._active_workflows.pop(workflow_name, None) is not None
```

---

## Section 5: Add EventTypes

**File:** `src/probos/events.py`

SEARCH:
```python
    INFODYNAMIC_REPORT = "infodynamic_report"  # AD-491
```

REPLACE:
```python
    INFODYNAMIC_REPORT = "infodynamic_report"  # AD-491
    RESOURCE_ALLOCATED = "resource_allocated"  # AD-467
    TASK_SCHEDULED = "task_scheduled"  # AD-467
    WORKFLOW_STARTED = "workflow_started"  # AD-467
```

> Builder note: anchor `INFODYNAMIC_REPORT` is verified present (post-AD-491, Wave 6). Fallback to `AGENT_SELF_NAMED = "agent_self_named"  # AD-499` (line 190) if AD-491 hasn't landed.

---

## Section 6: Add `OperationsConfig`

**File:** `src/probos/config.py`

```python
class OperationsConfig(BaseModel):
    """Operations crew configuration (AD-467)."""

    enabled: bool = True
    resource_interval_seconds: float = Field(default=30.0, ge=1.0)
    resource_emit_interval_seconds: float = Field(default=60.0, ge=10.0)
    scheduler_interval_seconds: float = Field(default=60.0, ge=10.0)
    coordinator_interval_seconds: float = Field(default=60.0, ge=10.0)
```

Wire into `SystemConfig`:

SEARCH:
```python
    infodynamic: InfodynamicConfig = InfodynamicConfig()  # AD-491
```

REPLACE:
```python
    infodynamic: InfodynamicConfig = InfodynamicConfig()  # AD-491
    operations: OperationsConfig = OperationsConfig()  # AD-467
```

> Builder note: anchor-chain fallback (next-anchor if predecessor hasn't landed):
> 1. `infodynamic: InfodynamicConfig` (AD-491, post-Wave 6).
> 2. `degradation: DegradationConfig` (AD-459, post-Wave 6).
> 3. `engineering: EngineeringConfig` (AD-457, post-Wave 6).
> 4. `validation_framework: ValidationFrameworkConfig` (AD-451, post-Wave 6).
> 5. `orders: OrdersConfig = OrdersConfig()  # AD-440` (config.py:1593) -- always-available terminal fallback.

---

## Section 7: Wire pool spawn into startup

The pool-spawning pattern is fully established at `agent_fleet.py:154-198` (medical pool) and the AD-457 engineering crew block (post-Wave 6). AD-467 mirrors the engineering crew pattern -- three HeartbeatAgent subclasses sharing an `operations_*` pool family.

### 7a. Register agent templates

**File:** `src/probos/runtime.py`

The new agent classes are registered as templates so the spawner can construct them. Mirrors the Wave 6 AD-457 template-registration block.

SEARCH (around `runtime.py:622+` -- the AD-457 engineering crew template registration block landed in Wave 6):
```python
        self.spawner.register_template("performance_monitor", PerformanceMonitorAgent)
        self.spawner.register_template("maintenance", MaintenanceAgent)
        self.spawner.register_template("damage_control", DamageControlAgent)
```

REPLACE:
```python
        self.spawner.register_template("performance_monitor", PerformanceMonitorAgent)
        self.spawner.register_template("maintenance", MaintenanceAgent)
        self.spawner.register_template("damage_control", DamageControlAgent)

        # AD-467: Operations crew templates
        from probos.agents.operations import (
            CoordinatorAgent,
            ResourceAllocatorAgent,
            SchedulerAgent,
        )
        self.spawner.register_template("resource_allocator", ResourceAllocatorAgent)
        self.spawner.register_template("scheduler", SchedulerAgent)
        self.spawner.register_template("coordinator", CoordinatorAgent)
```

> Verify-first: `register_template` is the public method on `AgentSpawner` (verified at `substrate/spawner.py:25`). The AD-457 block at `runtime.py:622+` landed in Wave 6 commit `b6a44a0`.
>
> Fallback: if AD-457 hasn't landed, anchor on `self.spawner.register_template("engineering_officer", EngineeringAgent)` (verified at `runtime.py:622` pre-Wave-6) and place AD-467 templates immediately after that line.

### 7b. Spawn operations pools at fleet startup

**File:** `src/probos/startup/agent_fleet.py`

Mirrors the Wave 6 AD-457 engineering-pool block. Adds three operations pools after engineering.

SEARCH (the AD-457 engineering block landed in Wave 6):
```python
    # AD-457: Engineering crew -- Performance / Maintenance / Damage Control
    if config.engineering.enabled:
        eng_cfg = config.engineering
        _engineering_heartbeat: list[tuple[str, str, float]] = [
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

REPLACE:
```python
    # AD-457: Engineering crew -- Performance / Maintenance / Damage Control
    if config.engineering.enabled:
        eng_cfg = config.engineering
        _engineering_heartbeat: list[tuple[str, str, float]] = [
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

    # AD-467: Operations crew -- Resource Allocator / Scheduler / Coordinator
    if config.operations.enabled:
        ops_cfg = config.operations
        _operations_heartbeat: list[tuple[str, str, float]] = [
            ("resource_allocator", "operations_resource",
             ops_cfg.resource_interval_seconds),
            ("scheduler", "operations_scheduler",
             ops_cfg.scheduler_interval_seconds),
            ("coordinator", "operations_coordinator",
             ops_cfg.coordinator_interval_seconds),
        ]
        for agent_type_name, pool_name, interval in _operations_heartbeat:
            ids = generate_pool_ids(agent_type_name, pool_name, 1)
            await create_pool_fn(
                pool_name, agent_type_name, target_size=1,
                agent_ids=ids, runtime=runtime, interval=interval,
            )
```

> Verify-first: `create_pool_fn` and `generate_pool_ids` are the existing pool-creation primitives (verified at `agent_fleet.py:37, 55`). Pool naming `operations_<role>` follows the `medical_<role>` / `engineering_<role>` convention.

> Fallback: if AD-457 hasn't landed, anchor on the engineering_officer block at `agent_fleet.py:140-146` and place AD-467 immediately after that block.

---

## Tests

**File:** `tests/test_ad467_operations_crew.py`

13 tests using `_FakeRuntime` stub:

1. `test_event_type_resource_allocated_exists` -- `EventType.RESOURCE_ALLOCATED.value == "resource_allocated"`.
2. `test_event_type_task_scheduled_exists` -- `EventType.TASK_SCHEDULED.value == "task_scheduled"`.
3. `test_event_type_workflow_started_exists` -- `EventType.WORKFLOW_STARTED.value == "workflow_started"`.
4. `test_operations_config_defaults` -- `OperationsConfig()` defaults match documented values.
5. `test_resource_allocator_default_pool_name` -- pool defaults to `"operations_resource"`.
6. `test_resource_allocator_collect_metrics_no_runtime` -- `runtime=None` -> sparse dict, no crash. `@pytest.mark.asyncio`.
7. `test_resource_allocator_collect_metrics_emits_capacity` -- fake runtime with 2 pools -> `capacity` dict populated, emit fires after first cycle. `@pytest.mark.asyncio`.
8. `test_scheduler_default_pool_name` -- pool defaults to `"operations_scheduler"`.
9. `test_scheduler_emits_due_tasks` -- first cycle emits all configured task_cadences. `@pytest.mark.asyncio`.
10. `test_scheduler_skips_recently_scheduled` -- second cycle within cadence window -> no emit. `@pytest.mark.asyncio`.
11. `test_coordinator_start_workflow_emits_event` -- `start_workflow("w1", ["a", "b"])` -> emit fires; returns True.
12. `test_coordinator_start_workflow_rejects_duplicate` -- second `start_workflow("w1", ...)` returns False, no second emit.
13. `test_operations_init_module_exports` -- `from probos.agents.operations import ...` succeeds for all 3 agents.

---

## What This Does NOT Change

- `HeartbeatAgent` substrate is not modified.
- `OperationsAgent` (AD-398 cognitive officer at `runtime.py:620`) is unchanged. AD-467 adds three sibling HeartbeatAgent pools.
- `OrderManager` (AD-440) is unchanged. CoordinatorAgent emits `WORKFLOW_STARTED` for batch flows; orders remain the chain-of-command directive channel.
- `BookingJournal` (`workforce.py:738`) is unchanged. CoordinatorAgent does not write booking entries.
- `routers/scheduled_tasks.py` is unchanged. SchedulerAgent emits events; the operator-facing scheduled-tasks API is a separate surface.
- **WorkflowDefinition API endpoint deferred to AD-467b** -- consumers must be exercised in production before adding the REST surface.
- **Response-Time Scaling deferred to AD-467c** -- cross-cuts `substrate/scaler.py`; substantial work.
- **LLM Cost Tracker deferred to AD-467d** -- depends on AD-463 ModelRegistry (sibling Wave 7) for per-model cost data; scope after AD-463 lands.
- v1 emits `TASK_SCHEDULED`, `WORKFLOW_STARTED`, `RESOURCE_ALLOCATED` events, but no production handler currently consumes them. AD-467b/c/d will wire consumers per capability.
- AD-528 ground-truth verification (sibling Wave 7) operates independently of AD-467 events.

---

## Tracking

- `PROGRESS.md`: add `AD-467 CLOSED. Operations Crew -- ...`
- `docs/development/roadmap.md`: flip AD-467 status from `*(planned)*` to `*(complete)*` near line 4181.
- `DECISIONS.md`: optional entry recording the v1-three-agents + 3-deferred-sub-AD scope decision.

---

## Pre-Commit Sanity Check (HARD RULE)

```pwsh
git diff --cached --stat
```

If any tracker file shows >200 deletions, STOP.

Expected delta:
- `src/probos/agents/operations/__init__.py`: 11 lines (new -- owns directory creation).
- `src/probos/agents/operations/resource_allocator.py`: ~95 lines (new).
- `src/probos/agents/operations/scheduler.py`: ~85 lines (new).
- `src/probos/agents/operations/coordinator.py`: ~95 lines (new).
- `src/probos/events.py`: 3 lines added.
- `src/probos/config.py`: ~10 lines added.
- `src/probos/runtime.py`: ~10 lines added (Section 7a).
- `src/probos/startup/agent_fleet.py`: ~18 lines added (Section 7b).
- `tests/test_ad467_operations_crew.py`: ~240 lines (new).
- `PROGRESS.md`, `roadmap.md`: ~3 lines changed.

---

## Acceptance Criteria

- All 13 tests pass under `pytest tests/test_ad467_operations_crew.py -v -n 0`.
- Full parallel gate non-decreasing.
- 3 new EventTypes appear exactly once in `events.py`.
- `src/probos/agents/operations/__init__.py` exists and re-exports the 3 agents.
- All 3 agents subclass `HeartbeatAgent` (no new substrate primitive).
- Pool spawning is concrete: 3 new `operations_<role>` pools registered at startup.
- Agent templates registered via `runtime.spawner.register_template(...)`.
- v1 ships only `ResourceAllocator`, `Scheduler`, `Coordinator`. WorkflowDefinition API, Response-Time Scaling, and LLM Cost Tracker explicitly deferred to AD-467b/c/d.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-01)

```
ls src/probos/agents/operations/
  (does NOT exist -- AD-467 creates it; verified via Test-Path returning False)

ls src/probos/agents/engineering/
  __init__.py  damage_control.py  maintenance.py  performance_monitor.py
  (AD-457 precedent for the operations package)

grep -n "class HeartbeatAgent" src/probos/substrate/heartbeat.py
  18: class HeartbeatAgent(BaseAgent):

grep -n "engineering_officer\|operations_officer" src/probos/runtime.py
  620: self.spawner.register_template("operations_officer", OperationsAgent)
  622: self.spawner.register_template("engineering_officer", EngineeringAgent)

grep -n "register_template" src/probos/substrate/spawner.py
  25: def register_template(self, type_name: str, agent_class: type[BaseAgent]) -> None:

grep -n "create_pool_fn\|generate_pool_ids" src/probos/startup/agent_fleet.py | head -5
  37: create_pool_fn: Callable[..., Any]
  55: ids = generate_pool_ids(agent_type, pool_name, size)

grep -n "Engineering Officer\|Operations Officer" src/probos/startup/agent_fleet.py
  132: # Operations team -- Operations Officer (AD-398)
  140: # Engineering team -- Engineering Officer (AD-398)

grep -rn "ResourceAllocatorAgent\|SchedulerAgent\|CoordinatorAgent" src/probos/
  (no matches -- AD-467 introduces these names)

grep -n "RESOURCE_ALLOCATED\|TASK_SCHEDULED\|WORKFLOW_STARTED" src/probos/events.py
  (no matches -- names are free)

grep -n "AGENT_SELF_NAMED\|INFODYNAMIC_REPORT" src/probos/events.py
  190: AGENT_SELF_NAMED = "agent_self_named"  # AD-499 (terminal fallback)
  (INFODYNAMIC_REPORT added by AD-491 Wave 6, post commit 1ece9e2)

grep -n "orders: OrdersConfig" src/probos/config.py
  1593: orders: OrdersConfig = OrdersConfig()  # AD-440
  (always-available terminal fallback)

grep -n "class BookingJournal\|workforce\.BookingJournal" src/probos/workforce.py
  738: class BookingJournal:
  (AD-467 reads but does NOT modify -- workflow tracking remains in workforce)

ls src/probos/agents/medical/
  __init__.py  diagnostician.py  pathologist.py  pharmacist.py  surgeon.py  vitals_monitor.py
  (medical pool precedent)
```
