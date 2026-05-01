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
        pool: str = "engineering",
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
        return metrics

    async def evaluate_thresholds(self, metrics: dict[str, Any]) -> None:
        breaches: list[tuple[str, float, float]] = []
        # Memory pressure proxy: pulse count plateau
        # (real instrumentation lives in AD-466 Engineering Infrastructure)
        # AD-457 establishes the agent surface; deeper metrics are AD-466 scope.
        for metric, value, threshold in breaches:
            self._emit_threshold_breach(metric, value, threshold)

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
        pool: str = "engineering",
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
        pool: str = "engineering",
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
    pool_size: int = Field(default=3, ge=1, le=12)
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

---

## Section 7: Wire pool spawn into startup

**File:** `src/probos/startup/finalize.py`

Pool registration follows the existing medical-pool pattern (grep `medical_pool` to find the precedent neighborhood). AD-457 spawns one agent per type, all in the `engineering` pool.

> Builder note: this is a **registration-only** wiring. The agents themselves do NOT register intent handlers — they emit events. The pool exists so existing pool monitoring (vitals, metrics) covers it. The exact medical-pool pattern reference depends on which pool-creation pathway is current; the Builder must grep `engineering_pool\|medical_pool` and mirror the chosen pattern. If the project uses `agent_fleet.spawn_*_pool_fn` parameters, add a `spawn_engineering_pool_fn` callback.

If no engineering-pool pattern exists at all, defer pool wiring to AD-457b. v1 then ships the agent classes only; instantiation happens via test stubs and a future operator-spawned pool. Surface to dispatching architect if this seam requires re-architecting `agent_fleet.py`.

---

## Tests

**File:** `tests/test_ad457_engineering_crew.py`

12 tests using `_FakeRuntime` stub:

1. `test_event_type_damage_control_activated_exists`
2. `test_event_type_maintenance_scheduled_exists`
3. `test_event_type_performance_threshold_breached_exists`
4. `test_engineering_config_defaults` — `EngineeringConfig()` defaults match documented values.
5. `test_performance_monitor_init_inherits_heartbeat` — agent_type, tier, capability descriptors set correctly.
6. `test_performance_monitor_collect_metrics_no_runtime` — `_runtime=None` → returns sparse dict, no crash.
7. `test_maintenance_agent_schedules_due_tasks` — first cycle schedules all 4 default tasks; emit fires for each.
8. `test_maintenance_agent_skips_recently_scheduled` — second cycle within interval window skips; no emit.
9. `test_damage_control_activate_known_signature` — `activate("llm_brownout")` emits with recovery action.
10. `test_damage_control_activate_unknown_signature` — `activate("garbage")` returns False, no emit.
11. `test_damage_control_cooldown_blocks_repeat` — second `activate(...)` within cooldown returns False.
12. `test_engineering_init_module_exports` — `from probos.agents.engineering import PerformanceMonitorAgent, MaintenanceAgent, DamageControlAgent` succeeds.

---

## What This Does NOT Change

- `HeartbeatAgent` substrate is not modified.
- `VitalsMonitorAgent` and the medical pool are not touched.
- Pool spawning infrastructure (`agent_fleet.py`) is NOT re-architected — if the existing pattern doesn't fit, Section 7 defers wiring to AD-457b.
- No new substrate APIs.
- `MaintenanceAgent` does NOT execute maintenance — it requests via events.
- `DamageControlAgent` does NOT implement recovery procedures — it activates them via events.
- `InfrastructureAgent` (the prompt's optional fourth) is **out of scope** — overlaps with AD-466 Engineering Infrastructure.
- Performance threshold values are conservative defaults; AD-466 will provide real instrumentation.

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
- `src/probos/agents/engineering/performance_monitor.py`: ~110 lines (new).
- `src/probos/agents/engineering/maintenance.py`: ~95 lines (new).
- `src/probos/agents/engineering/damage_control.py`: ~110 lines (new).
- `src/probos/events.py`: 3 lines added.
- `src/probos/config.py`: ~10 lines added.
- `src/probos/startup/finalize.py`: ~15 lines added (registration-only) OR 0 if Section 7 deferred.
- `tests/test_ad457_engineering_crew.py`: ~240 lines (new).
- `PROGRESS.md`, `roadmap.md`: ~3 lines changed.

---

## Acceptance Criteria

- All 12 tests pass under `pytest tests/test_ad457_engineering_crew.py -v -n 0`.
- Full parallel gate non-decreasing vs baseline.
- 3 new EventTypes appear exactly once in `events.py`.
- `src/probos/agents/engineering/__init__.py` exists and re-exports the 3 agents.
- All 3 agents subclass `HeartbeatAgent` (no new substrate primitive).
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
```
