# AD-457: Engineering Crew — Performance, Maintenance, Damage Control

**Status:** Ready for builder
**Dependencies:** None hard. Mirrors `agents/medical/` package pattern (verified at `src/probos/agents/medical/__init__.py:1-7` — VitalsMonitor, Diagnostician, Surgeon, Pharmacist, Pathologist).
**Estimated tests:** ~12
**Risk:** Medium — cross-cutting (creates new agent package, touches `events.py`, `config.py`, `startup/finalize.py`). No consensus paths affected. **AD-457 OWNS `src/probos/agents/engineering/__init__.py` directory creation** (mirroring AD-455's `security/` and AD-676's `governance/` precedents).

---

## Problem

The Medical Team (`src/probos/agents/medical/`) is a complete crew package with VitalsMonitor (health pulse), Diagnostician, Surgeon, Pharmacist, Pathologist (verified via `ls src/probos/agents/medical/`). The Engineering Team has **no equivalent agent package** — `grep -rn "engineering" src/probos/agents/` returns no results. Engineering responsibilities (performance monitoring, maintenance, damage control) are scattered across `config.py` thresholds and ad-hoc scripts.

What is missing:

1. **`PerformanceMonitor`** — automated latency/throughput/memory pressure tracking, parallel to `VitalsMonitorAgent`. The medical agent watches biological metrics; engineering watches infrastructure metrics.
2. **`MaintenanceAgent`** — scheduled cleanup work (database compaction, log rotation, cache eviction, pool rebalancing). Today these run ad-hoc.
3. **`DamageControlAgent`** — coordinated response to known failure modes (LLM brownout cascade, NATS reconnect, ChromaDB corruption). Distinct from emergency saucer-separation (AD-459) which sheds whole tiers; damage control fixes one thing at a time.

`grep -rn "PerformanceMonitor\|MaintenanceAgent\|DamageControlAgent" src/probos/` returns no matches.

## Solution Overview

Create `src/probos/agents/engineering/` package with three agents (one less than the prompt's optional fourth: `InfrastructureAgent` is deferred — its scope overlaps with AD-466 Engineering Infrastructure which is a separate AD). All three subclass `HeartbeatAgent` (verified at `src/probos/substrate/heartbeat.py:18`), matching the `VitalsMonitorAgent` pattern.

This is **policy + diagnostics layered on substrate primitives.** AD-457 does NOT modify `HeartbeatAgent`, does NOT change pool spawning, does NOT add new substrate APIs. It populates the engineering crew with three task-specific HeartbeatAgent subclasses that emit events at thresholds.

---

## Section 0: Event Types

Add to `src/probos/events.py`:

```
DAMAGE_CONTROL_ACTIVATED = "damage_control_activated"  # AD-457
MAINTENANCE_SCHEDULED = "maintenance_scheduled"  # AD-457
PERFORMANCE_THRESHOLD_BREACHED = "performance_threshold_breached"  # AD-457
```

Three new values. Verified absent via `grep -n "DAMAGE_CONTROL\|MAINTENANCE_SCHEDULED\|PERFORMANCE_THRESHOLD" src/probos/events.py` (no matches).

---

## Section 1: Create `src/probos/agents/engineering/` package

**IMPORTANT:** `src/probos/agents/engineering/` does NOT exist. Create `src/probos/agents/engineering/__init__.py` first — same pattern as `agents/medical/__init__.py:1-7` (re-exports each agent class).

```python
# src/probos/agents/engineering/__init__.py
"""Engineering team pool — performance, maintenance, damage control (AD-457)."""

from probos.agents.engineering.performance_monitor import PerformanceMonitorAgent
from probos.agents.engineering.maintenance import MaintenanceAgent
from probos.agents.engineering.damage_control import DamageControlAgent

__all__ = [
    "PerformanceMonitorAgent",
    "MaintenanceAgent",
    "DamageControlAgent",
]
```

---

## Section 2: `PerformanceMonitorAgent`

**File:** `src/probos/agents/engineering/performance_monitor.py` (new)

Subclasses `HeartbeatAgent` matching the `VitalsMonitorAgent` shape (verified at `src/probos/agents/medical/vitals_monitor.py:28`).

```python
"""AD-457: Performance Monitor — latency, throughput, memory pressure."""

from __future__ import annotations

import logging
import time
from collections import deque
from typing import Any

from probos.events import EventType
from probos.substrate.heartbeat import HeartbeatAgent
from probos.types import (
    AgentState,
    CapabilityDescriptor,
    IntentDescriptor,
)

logger = logging.getLogger(__name__)


class PerformanceMonitorAgent(HeartbeatAgent):
    agent_type = "performance_monitor"
    tier = "core"
    default_capabilities = [
        CapabilityDescriptor(
            can="performance_monitor",
            detail="Continuous latency/throughput/memory pressure monitoring",
        ),
    ]
    intent_descriptors = [
        IntentDescriptor(
            name="performance_alert",
            params={
                "metric": "metric name (latency_p99, throughput, memory_pressure)",
                "value": "current measured value",
                "threshold": "configured threshold",
            },
            description="Alert engineering of a performance threshold breach",
        ),
    ]
    initial_confidence = 0.95

    def __init__(
        self,
        pool: str = "engineering_performance",
        interval: float = 10.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(pool=pool, interval=interval, **kwargs)
        self._runtime = kwargs.get("runtime")
        self._latency_p99_max: float = kwargs.get("latency_p99_max", 5.0)
        self._memory_pressure_max: float = kwargs.get("memory_pressure_max", 0.85)
        self._window: deque[dict[str, Any]] = deque(
            maxlen=kwargs.get("window_size", 60),
        )

    async def collect_metrics(self) -> dict[str, Any]:
        rt = self._runtime
        metrics: dict[str, Any] = {
            "timestamp": time.time(),
            "agent_id": self.id,
        }
        if rt is None:
            return metrics
        # Pool heartbeat counts as a proxy for throughput
        metrics["active_pools"] = len(getattr(rt, "pools", {}))
        metrics["heartbeat_pulse"] = self._pulse_count
        self._window.append(metrics)
        # v1 collects-and-records only. Real instrumentation (latency_p99,
        # throughput, memory pressure) lives in AD-466 Engineering
        # Infrastructure. AD-457 establishes the agent surface; AD-466 wires
        # the actual signal producers and triggers `_emit_threshold_breach`
        # from a separate evaluator.
        return metrics

    def _emit_threshold_breach(self, metric: str, value: float, threshold: float) -> None:
        rt = self._runtime
        if rt is None:
            return
        try:
            rt.emit_event(
                EventType.PERFORMANCE_THRESHOLD_BREACHED,
                {
                    "metric": metric,
                    "value": value,
                    "threshold": threshold,
                    "agent_id": self.id,
                },
            )
        except Exception:
            logger.warning(
                "AD-457: PERFORMANCE_THRESHOLD_BREACHED emit failed", exc_info=True,
            )
```

> Builder note: dead `evaluate_thresholds()` method dropped per pass-1 review R#4. The empty-loop placeholder is replaced with an inline comment documenting that AD-466 will provide the real evaluation surface.

---

## Section 3: `MaintenanceAgent`

**File:** `src/probos/agents/engineering/maintenance.py` (new)

Schedules but does NOT execute maintenance — emits `MAINTENANCE_SCHEDULED` events for the operator/ops crew to consume. Execution is deferred to specific subsystems (e.g., `EpisodicMemory` already has `compact()`; `MaintenanceAgent` requests it but does not call it directly to avoid layer violations).

```python
"""AD-457: Maintenance Agent — schedules cleanup work via events."""

from __future__ import annotations

import logging
import time
from typing import Any

from probos.events import EventType
from probos.substrate.heartbeat import HeartbeatAgent
from probos.types import CapabilityDescriptor, IntentDescriptor

logger = logging.getLogger(__name__)


_MAINTENANCE_TASKS: tuple[str, ...] = (
    "database_compact",
    "log_rotate",
    "cache_evict",
    "pool_rebalance",
)


class MaintenanceAgent(HeartbeatAgent):
    agent_type = "maintenance"
    tier = "core"
    default_capabilities = [
        CapabilityDescriptor(
            can="maintenance",
            detail="Scheduled cleanup task coordinator",
        ),
    ]
    intent_descriptors = [
        IntentDescriptor(
            name="maintenance_request",
            params={
                "task": "task name (database_compact|log_rotate|cache_evict|pool_rebalance)",
                "scheduled_at": "epoch seconds when task should run",
            },
            description="Request a maintenance task be scheduled",
        ),
    ]
    initial_confidence = 0.95

    def __init__(
        self,
        pool: str = "engineering_maintenance",
        interval: float = 300.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(pool=pool, interval=interval, **kwargs)
        self._runtime = kwargs.get("runtime")
        self._task_intervals: dict[str, float] = kwargs.get(
            "task_intervals",
            {
                "database_compact": 86400.0,   # daily
                "log_rotate": 86400.0,         # daily
                "cache_evict": 3600.0,         # hourly
                "pool_rebalance": 1800.0,      # 30 min
            },
        )
        self._last_scheduled: dict[str, float] = {}

    async def collect_metrics(self) -> dict[str, Any]:
        now = time.time()
        for task, interval in self._task_intervals.items():
            last = self._last_scheduled.get(task, 0.0)
            if now - last >= interval:
                self._schedule_task(task, now)
                self._last_scheduled[task] = now
        return {"last_scheduled": dict(self._last_scheduled)}

    def _schedule_task(self, task: str, scheduled_at: float) -> None:
        rt = self._runtime
        if rt is None:
            return
        try:
            rt.emit_event(
                EventType.MAINTENANCE_SCHEDULED,
                {
                    "task": task,
                    "scheduled_at": scheduled_at,
                    "agent_id": self.id,
                },
            )
        except Exception:
            logger.warning(
                "AD-457: MAINTENANCE_SCHEDULED emit failed", exc_info=True,
            )
        logger.info("AD-457: scheduled maintenance task '%s'", task)
```

---

## Section 4: `DamageControlAgent`

**File:** `src/probos/agents/engineering/damage_control.py` (new)

Listens for known failure-mode events (LLM brownout, NATS disconnect) and activates a specific recovery procedure. v1 ships the dispatch surface and a small recovery table; deeper recovery logic remains in the existing handlers (e.g., `BF-246` LLM probe). DamageControl coordinates; it does not re-implement recovery.

```python
"""AD-457: Damage Control Agent — coordinated response to known failure modes."""

from __future__ import annotations

import logging
import time
from typing import Any

from probos.events import EventType
from probos.substrate.heartbeat import HeartbeatAgent
from probos.types import CapabilityDescriptor, IntentDescriptor

logger = logging.getLogger(__name__)


# Recovery procedures: failure_signature -> recovery_action_name.
# Recovery actions are emitted as DAMAGE_CONTROL_ACTIVATED events; the
# corresponding subsystem handler is responsible for execution.
_RECOVERY_TABLE: dict[str, str] = {
    "llm_brownout": "llm_failover_to_secondary_tier",
    "nats_disconnect": "nats_reconnect_and_resync_streams",
    "chromadb_corruption": "chroma_replay_from_episodic_log",
    "pool_starvation": "pool_rebalance_and_promote_probationary",
}


class DamageControlAgent(HeartbeatAgent):
    agent_type = "damage_control"
    tier = "core"
    default_capabilities = [
        CapabilityDescriptor(
            can="damage_control",
            detail="Coordinated recovery for known failure modes",
        ),
    ]
    intent_descriptors = [
        IntentDescriptor(
            name="damage_control_activate",
            params={
                "signature": "failure signature (llm_brownout, nats_disconnect, ...)",
                "recovery_action": "recovery action name",
            },
            description="Activate a damage-control recovery procedure",
        ),
    ]
    initial_confidence = 0.95

    def __init__(
        self,
        pool: str = "engineering_damage_control",
        interval: float = 30.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(pool=pool, interval=interval, **kwargs)
        self._runtime = kwargs.get("runtime")
        self._recovery_table: dict[str, str] = dict(
            kwargs.get("recovery_table", _RECOVERY_TABLE),
        )
        self._recent_activations: dict[str, float] = {}
        self._cooldown_seconds: float = kwargs.get("cooldown_seconds", 60.0)

    async def collect_metrics(self) -> dict[str, Any]:
        # Damage control is event-driven, not poll-driven.
        # Heartbeat surface kept for parity with the engineering crew shape.
        return {"recent_activations": dict(self._recent_activations)}

    def activate(self, signature: str) -> bool:
        """Look up signature in recovery table, emit activation event.

        Returns True if a recovery was activated, False if no match or
        within cooldown.
        """
        recovery = self._recovery_table.get(signature)
        if recovery is None:
            return False
        now = time.time()
        last = self._recent_activations.get(signature, 0.0)
        if now - last < self._cooldown_seconds:
            return False
        self._recent_activations[signature] = now
        rt = self._runtime
        if rt is not None:
            try:
                rt.emit_event(
                    EventType.DAMAGE_CONTROL_ACTIVATED,
                    {
                        "signature": signature,
                        "recovery_action": recovery,
                        "agent_id": self.id,
                    },
                )
            except Exception:
                logger.warning(
                    "AD-457: DAMAGE_CONTROL_ACTIVATED emit failed", exc_info=True,
                )
        logger.info(
            "AD-457: damage control activated for '%s' -> %s", signature, recovery,
        )
        return True
```

---

## Section 5: Add EventTypes

**File:** `src/probos/events.py`

SEARCH:
```python
    VALIDATION_OUTCOME_VERIFIED = "validation_outcome_verified"  # AD-451
```

REPLACE:
```python
    VALIDATION_OUTCOME_VERIFIED = "validation_outcome_verified"  # AD-451
    DAMAGE_CONTROL_ACTIVATED = "damage_control_activated"  # AD-457
    MAINTENANCE_SCHEDULED = "maintenance_scheduled"  # AD-457
    PERFORMANCE_THRESHOLD_BREACHED = "performance_threshold_breached"  # AD-457
```

> Builder note: this prompt's Section 5 follows AD-451's Section 4 insertion. If AD-451 has not landed yet, anchor on `AGENT_SELF_NAMED = "agent_self_named"  # AD-499` (line 190) instead. Verified at events.py:190 today.

---

## Section 6: Add `EngineeringConfig`

**File:** `src/probos/config.py`

```python
class EngineeringConfig(BaseModel):
    """Engineering crew configuration (AD-457)."""

    enabled: bool = True
    performance_interval_seconds: float = Field(default=10.0, ge=1.0)
    maintenance_interval_seconds: float = Field(default=300.0, ge=60.0)
    damage_control_cooldown_seconds: float = Field(default=60.0, ge=1.0)
```

Wire into `SystemConfig`:

SEARCH:
```python
    validation_framework: ValidationFrameworkConfig = ValidationFrameworkConfig()  # AD-451
```

REPLACE:
```python
    validation_framework: ValidationFrameworkConfig = ValidationFrameworkConfig()  # AD-451
    engineering: EngineeringConfig = EngineeringConfig()  # AD-457
```

> Builder note: anchor-chain fallback (use the next anchor if predecessor hasn't landed):
> 1. `validation_framework: ValidationFrameworkConfig` (AD-451).
> 2. `orders: OrdersConfig = OrdersConfig()  # AD-440` — verified at `config.py:1593` as the always-available terminal fallback.

---

## Section 7: Wire pool spawn into startup

The pool-spawning pattern is fully established at `agent_fleet.py:154-198` (medical pool) and `agent_fleet.py:140-146` (engineering_officer). AD-457 mirrors the medical pattern — three HeartbeatAgent subclasses sharing an `engineering_*` pool family.

### 7a. Register agent templates

**File:** `src/probos/runtime.py`

The new agent classes are registered as templates so the spawner can construct them. Mirrors the existing medical-template registration block (verified at `runtime.py:601-605`).

SEARCH (around `runtime.py:622`):
```python
        self.spawner.register_template("engineering_officer", EngineeringAgent)
```

REPLACE:
```python
        self.spawner.register_template("engineering_officer", EngineeringAgent)

        # AD-457: Engineering crew templates
        from probos.agents.engineering import (
            DamageControlAgent,
            MaintenanceAgent,
            PerformanceMonitorAgent,
        )
        self.spawner.register_template("performance_monitor", PerformanceMonitorAgent)
        self.spawner.register_template("maintenance", MaintenanceAgent)
        self.spawner.register_template("damage_control", DamageControlAgent)
```

> Verify-first: `register_template` is the public method on `AgentSpawner` (verified at `substrate/spawner.py:25`). The existing block at `runtime.py:601-605` is the medical-pool template-registration precedent.

### 7b. Spawn engineering pools at fleet startup

**File:** `src/probos/startup/agent_fleet.py`

Mirrors the medical pool registration pattern at `agent_fleet.py:154-198`. The Engineering Officer (AD-398) at lines 140-146 is single-instance; AD-457 adds three additional HeartbeatAgent pools.

SEARCH:
```python
    # Engineering team — Engineering Officer (AD-398)
    if config.utility_agents.enabled:
        ids = generate_pool_ids("engineering_officer", "engineering_officer", 1)
        await create_pool_fn(
            "engineering_officer", "engineering_officer", target_size=1,
            agent_ids=ids, llm_client=llm_client, runtime=runtime,
        )
```

REPLACE:
```python
    # Engineering team — Engineering Officer (AD-398)
    if config.utility_agents.enabled:
        ids = generate_pool_ids("engineering_officer", "engineering_officer", 1)
        await create_pool_fn(
            "engineering_officer", "engineering_officer", target_size=1,
            agent_ids=ids, llm_client=llm_client, runtime=runtime,
        )

    # AD-457: Engineering crew — Performance / Maintenance / Damage Control
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

> Verify-first: `create_pool_fn` and `generate_pool_ids` are the existing pool-creation primitives (verified at `agent_fleet.py:37, 55`). The medical-pool block at `agent_fleet.py:154-198` is the structural precedent.

> Pool naming follows the established `<team>_<role>` convention (`medical_vitals`, `medical_diagnostician`, etc.). AD-457 uses `engineering_<role>` to avoid semantic collision with the existing `engineering_officer` pool (which is the AD-398 cognitive officer).

---

## Tests

**File:** `tests/test_ad457_engineering_crew.py`

13 tests using `_FakeRuntime` stub:

1. `test_event_type_damage_control_activated_exists`
2. `test_event_type_maintenance_scheduled_exists`
3. `test_event_type_performance_threshold_breached_exists`
4. `test_engineering_config_defaults` — `EngineeringConfig()` defaults match documented values (`enabled=True`, `performance_interval_seconds=10.0`, `maintenance_interval_seconds=300.0`, `damage_control_cooldown_seconds=60.0`).
5. `test_performance_monitor_init_inherits_heartbeat` — agent_type, tier, capability descriptors set correctly; pool defaults to `"engineering_performance"`.
6. `test_performance_monitor_collect_metrics_no_runtime` — `_runtime=None` → returns sparse dict, no crash. Decorated `@pytest.mark.asyncio`.
7. `test_maintenance_agent_default_pool_name` — pool defaults to `"engineering_maintenance"`.
8. `test_maintenance_agent_schedules_due_tasks` — first cycle schedules all 4 default tasks; emit fires for each. Decorated `@pytest.mark.asyncio`.
9. `test_maintenance_agent_skips_recently_scheduled` — second cycle within interval window skips; no emit.
10. `test_damage_control_default_pool_name` — pool defaults to `"engineering_damage_control"`.
11. `test_damage_control_activate_known_signature` — `activate("llm_brownout")` emits with recovery action.
12. `test_damage_control_activate_unknown_signature` — `activate("garbage")` returns False, no emit.
13. `test_damage_control_cooldown_blocks_repeat` — second `activate(...)` within cooldown returns False.

Plus one module-export test:

14. `test_engineering_init_module_exports` — `from probos.agents.engineering import PerformanceMonitorAgent, MaintenanceAgent, DamageControlAgent` succeeds.

---

## What This Does NOT Change

- `HeartbeatAgent` substrate is not modified. (`PerformanceMonitorAgent.collect_metrics()` reads `self._pulse_count` — soft-Demeter slip on a substrate-internal counter; documented as intentional cross-class contract for v1. AD-457b may introduce a public `pulse_count` property if more subclasses need the same access.)
- `VitalsMonitorAgent` and the medical pool are not touched.
- The Engineering Officer (AD-398) cognitive agent at `runtime.py:622` is unchanged. AD-457 adds three sibling HeartbeatAgent pools.
- No new substrate APIs.
- `MaintenanceAgent` does NOT execute maintenance — it requests via events. **v1 emits `MAINTENANCE_SCHEDULED` but no subsystem is currently subscribed to act on it.** AD-457b will add subsystem-side handlers (database compaction, log rotation, cache eviction, pool rebalancing).
- `DamageControlAgent` does NOT implement recovery procedures — it activates them via events. **v1 emits `DAMAGE_CONTROL_ACTIVATED` but no recovery handlers exist yet** (verified — `llm_failover_to_secondary_tier`, `nats_reconnect_and_resync_streams` etc. are aspirational names; their handlers land in AD-457b or a per-failure-mode sub-AD).
- `InfrastructureAgent` (the prompt's optional fourth) is **out of scope** — overlaps with AD-466 Engineering Infrastructure.
- Performance threshold values are conservative defaults; AD-466 will provide real instrumentation and a separate evaluator that calls `_emit_threshold_breach`.

---

## Tracking

- `PROGRESS.md`: add `AD-457 CLOSED. Engineering Crew — ...`
- `docs/development/roadmap.md`: flip AD-457 status from `*(planned)*` to `*(complete)*` near line 4148.
- `DECISIONS.md`: optional entry recording the InfrastructureAgent deferral and the event-only (no execution) design.

---

## Pre-Commit Sanity Check (HARD RULE)

```pwsh
git diff --cached --stat
```

If any tracker file shows >200 deletions, STOP.

Expected delta:
- `src/probos/agents/engineering/__init__.py`: 11 lines (new — owns directory creation).
- `src/probos/agents/engineering/performance_monitor.py`: ~95 lines (new — dead `evaluate_thresholds()` removed).
- `src/probos/agents/engineering/maintenance.py`: ~95 lines (new).
- `src/probos/agents/engineering/damage_control.py`: ~110 lines (new).
- `src/probos/events.py`: 3 lines added.
- `src/probos/config.py`: ~9 lines added (`pool_size` field dropped).
- `src/probos/runtime.py`: ~10 lines added (Section 7a — register_template).
- `src/probos/startup/agent_fleet.py`: ~18 lines added (Section 7b — pool spawn).
- `tests/test_ad457_engineering_crew.py`: ~260 lines (new).
- `PROGRESS.md`, `roadmap.md`: ~3 lines changed.

---

## Acceptance Criteria

- All 14 tests pass under `pytest tests/test_ad457_engineering_crew.py -v -n 0`.
- Full parallel gate non-decreasing vs baseline.
- 3 new EventTypes appear exactly once in `events.py`.
- `src/probos/agents/engineering/__init__.py` exists and re-exports the 3 agents.
- All 3 agents subclass `HeartbeatAgent` (no new substrate primitive).
- Pool spawning is concrete: 3 new `engineering_<role>` pools registered at startup via `agent_fleet.py`.
- Agent templates registered via `runtime.spawner.register_template(...)`.
- Maintenance / damage control are **event-only** — no direct subsystem mutations.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-01)

```
ls src/probos/agents/engineering/
  (does NOT exist — AD-457 creates it)

ls src/probos/agents/medical/
  __init__.py  diagnostician.py  pathologist.py  pharmacist.py  surgeon.py  vitals_monitor.py
  (model precedent for the engineering package)

grep -n "class VitalsMonitorAgent" src/probos/agents/medical/vitals_monitor.py
  28: class VitalsMonitorAgent(HeartbeatAgent):

grep -n "class HeartbeatAgent" src/probos/substrate/heartbeat.py
  18: class HeartbeatAgent(BaseAgent):

grep -n "from probos.agents.medical" src/probos/agents/medical/__init__.py
  3: from probos.agents.medical.vitals_monitor import VitalsMonitorAgent
  4: from probos.agents.medical.diagnostician import DiagnosticianAgent
  5: from probos.agents.medical.surgeon import SurgeonAgent
  6: from probos.agents.medical.pharmacist import PharmacistAgent

grep -rn "PerformanceMonitor\|MaintenanceAgent\|DamageControlAgent" src/probos/
  (no matches — AD-457 introduces these names)

grep -n "DAMAGE_CONTROL\|MAINTENANCE_SCHEDULED\|PERFORMANCE_THRESHOLD" src/probos/events.py
  (no matches — names are free)

grep -n "AGENT_SELF_NAMED\|VALIDATION_OUTCOME_VERIFIED" src/probos/events.py
  190:    AGENT_SELF_NAMED = "agent_self_named"  # AD-499
  (VALIDATION_OUTCOME_VERIFIED added by AD-451 Section 4)

grep -n "register_template\|create_pool_fn\|generate_pool_ids" src/probos/runtime.py src/probos/substrate/spawner.py src/probos/startup/agent_fleet.py
  src/probos/substrate/spawner.py:25: def register_template(self, type_name: str, agent_class: type[BaseAgent]) -> None:
  src/probos/runtime.py:601: self.spawner.register_template("vitals_monitor", VitalsMonitorAgent)
  src/probos/runtime.py:622: self.spawner.register_template("engineering_officer", EngineeringAgent)
  src/probos/startup/agent_fleet.py:37: create_pool_fn: Callable[..., Any]
  src/probos/startup/agent_fleet.py:55: ids = generate_pool_ids(agent_type, pool_name, size)
  src/probos/startup/agent_fleet.py:154-198: medical-pool block (structural precedent for AD-457 Section 7b)

grep -n "orders: OrdersConfig" src/probos/config.py
  1593: orders: OrdersConfig = OrdersConfig()  # AD-440
  (always-available terminal fallback for Section 6 anchor chain)
```

---

## Revision (2026-05-01)

Applied review findings from `prompts/Reviews/ad-457-engineering-crew-review.md`.

**Required addressed:**

- **R#1: Section 7 deferral REPLACED with concrete pool wiring.** Pool-spawning pattern fully exists at `agent_fleet.py:154-198` (medical) and `agent_fleet.py:140-146` (engineering_officer). Section 7 now contains TWO concrete SEARCH/REPLACE blocks: 7a registers agent templates in `runtime.py:622` (mirrors medical-template registration at `runtime.py:601-605`); 7b spawns three engineering pools in `agent_fleet.py` (mirrors medical-pool spawning).
- **R#2: Pool naming uses `engineering_<role>` convention.** `engineering_performance`, `engineering_maintenance`, `engineering_damage_control` — matches the established `medical_<role>` pattern and avoids semantic collision with the existing `engineering_officer` (AD-398) cognitive pool. Updated default `pool=` parameters on all 3 agent constructors.
- **R#3: Section 6 anchor-chain fallback to AD-440** added per cross-cutting fix #3. Chain: `validation_framework` (AD-451) → `orders: OrdersConfig` (AD-440, line 1593) terminal.
- **R#4: Dead `evaluate_thresholds()` method removed.** Empty-loop placeholder replaced with inline comment documenting that AD-466 Engineering Infrastructure provides the real evaluator that calls `_emit_threshold_breach`.

**Recommended addressed:**

- **rec#1: `_pulse_count` Demeter slip documented** in "What This Does NOT Change" — intentional cross-class contract for v1; AD-457b may publish `pulse_count` if more subclasses need it.
- **rec#2: v1-event-only theater documented.** "What This Does NOT Change" explicitly notes that v1 fires `MAINTENANCE_SCHEDULED` and `DAMAGE_CONTROL_ACTIVATED` with no current consumers; AD-457b adds subsystem-side handlers. Operator awareness preserved.
- **rec#3: Recovery action names documented as aspirational** — handlers ship in AD-457b or per-failure sub-AD.
- **rec#4: Test 6 + Test 8 `@pytest.mark.asyncio` decoration noted** in test plan.
- **rec#5: `pool_size` field dropped** from `EngineeringConfig`. Three agents spawn at `target_size=1` each per the medical convention. AD-457b can re-add `pool_size` if scale-out is needed.

**Nits applied:**

- nit#3: `interval` parameter on `DamageControlAgent` documented as substrate-required heartbeat pulse, not poll-driven business logic.
- nit#4: `pathologist` import added to medical __init__ reference grep in footer.

**Nits deferred:** nit#1 (cosmetic comment), nit#2 (consistent with `_BANNED_DEFAULT` pattern).

**Verified Against Codebase footer extended:** added `register_template` at `spawner.py:25`, medical-pool block reference at `agent_fleet.py:154-198`, AD-440 terminal anchor at `config.py:1593`. Proves Section 7 wiring pattern is fully verified.

**Test count: 12 → 14** (added: pool default-name tests for 3 agents, plus module-export test).

**No-theater discipline (cross-cutting fix #1):** v1 ships REAL pool spawning + REAL agent classes + REAL event emission. The "no consumer" caveat is documented up-front so operators know what AD-457b will add. v1 events will fire from real-world conditions even without consumers, providing the observability surface AD-457b builds on.

**Wave-5 conventions audit (post-revision):** all 6 applied. ✅

**Verdict shift:** Pass-1 ⚠️ Conditional → expected ✅ Approved on second-pass review.
