# AD-641f: Engineering Chief Ship's Systems Observability — Sensor Bundle (v1)

**Status:** Ready for builder
**Wave:** 9A (parallel-safe — independent of other 641 children at source-file level; ships an Engineering-tier sensor without touching `EngineeringAgent` directly)
**Dependencies:** Reads `runtime.spawner.pools` (verified pattern from AD-467 `ResourceAllocatorAgent`). Reads `runtime.capability_registry.agent_count` at `src/probos/mesh/capability.py:98` (verified). Reads `runtime.gossip.view_size` at `src/probos/mesh/gossip.py:119` (verified). Reads `runtime.gossip.get_view()` at `src/probos/mesh/gossip.py:99` (verified). Builds an Engineering-targeted observation surface — `EngineeringAgent` at `src/probos/cognitive/engineering_officer.py:37` is the consumer (verified).
**Estimated tests:** ~13
**Risk:** MEDIUM — read-only sensor bundle; the value is in the structured surface, not in modifying brain internals.

---

## Problem

The Engineering Officer (LaForge) needs read access to **Category D** brain internals (pool scaling events, capability registry summary, gossip state count) to perform Chief Moderation duties — but Category D is "brain-only" by default. AD-641 design doc Category B+D notes that LaForge is the documented exception: "Engineering Chief (LaForge) may eventually need observability into Category D systems as part of the Chief Moderation / Ship's Engineer role. This would be Category B (read-only) exposure, not Category C or integration."

`grep -rn "class EngineeringSensorBundle\|class ChiefEngineerSensors\|engineering_sensors" src/probos/` returns no matches.

The roadmap entry (line 7056) names AD-641f as "Engineering Chief Observability — LaForge-specific: read access to Category D internals (pool scaling events, gossip state, capability registry). Chief Moderation prerequisite."

## Solution Overview

One new module under `src/probos/cognitive/engineering_sensors/` (new package; AD-641f OWNS `__init__.py` creation):

1. **`EngineeringSensorBundle`** (`bundle.py`) — frozen dataclass with `pool_summary`, `capability_summary`, `gossip_summary`, `captured_at`. The structured observation surface for the Engineering tier.
2. **`EngineeringSensorService`** (`service.py`) — coordinator. Public API: `take_snapshot() -> EngineeringSensorBundle`, `report() -> None` (emits `ENGINEERING_SENSOR_REPORT` with snapshot summary). Holds an optional periodic-task reference (named `engineering_sensor_report`) when started; stop() cancels cleanly.

This is **a focused observation surface**, not an extension of any consensus or routing layer. AD-641f does NOT modify `runtime.spawner`, `runtime.capability_registry`, or `runtime.gossip`. It does NOT modify `EngineeringAgent` — the agent reads `runtime.engineering_sensor_service.take_snapshot()` voluntarily once a future grandchild AD wires the read into its instructions.

**v1 scope (no-theater discipline; convention #7 + #14 — 3 of 6 capabilities ship):**

- **3 sensor surfaces wired:** pool-summary (current/target sizes per pool), capability-summary (`agent_count` and intent counts), gossip-summary (`view_size` and peer count).
- **Real `take_snapshot()` + `report()`** with real event emission.
- **`runtime.engineering_sensor_service`** public attribute wired in finalize.

**3 wholesale-deferred to grandchild ADs:**

- **Detailed gossip introspection (per-peer state)** — `AD-641f-i`. v1 returns aggregate counts; per-peer state is its own AD.
- **Capability registry mutation surface (Engineering can suggest re-registrations)** — `AD-641f-ii`. v1 is read-only.
- **Cross-pool failover proposal** — `AD-641f-iii`. v1 reports state; remediation belongs to a separate AD.

---

## Section 0: Event Types

Add to `src/probos/events.py`:

```
ENGINEERING_SENSOR_REPORT = "engineering_sensor_report"  # AD-641f
```

Verified absent: `grep -n "ENGINEERING_SENSOR_REPORT" src/probos/events.py` returns no matches.

---

## Section 1: Package init

**File:** `src/probos/cognitive/engineering_sensors/__init__.py` (new — AD-641f OWNS directory creation)

```python
"""AD-641f: Engineering Chief Ship's Systems Observability."""

from probos.cognitive.engineering_sensors.bundle import EngineeringSensorBundle
from probos.cognitive.engineering_sensors.service import EngineeringSensorService

__all__ = [
    "EngineeringSensorBundle",
    "EngineeringSensorService",
]
```

---

## Section 2: `EngineeringSensorBundle`

**File:** `src/probos/cognitive/engineering_sensors/bundle.py` (new)

```python
"""AD-641f: EngineeringSensorBundle -- frozen sensor snapshot."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EngineeringSensorBundle:
    captured_at: float
    pool_summary: dict[str, dict[str, Any]] = field(default_factory=dict)
    capability_summary: dict[str, Any] = field(default_factory=dict)
    gossip_summary: dict[str, Any] = field(default_factory=dict)
```

---

## Section 3: `EngineeringSensorService`

**File:** `src/probos/cognitive/engineering_sensors/service.py` (new)

```python
"""AD-641f: EngineeringSensorService -- read-only observation for LaForge.

v1 surfaces three Category D sensors as a structured bundle:
  - pool_summary    -- per-pool current/target sizes
  - capability_summary -- agent_count + capability count
  - gossip_summary  -- view_size + peer count

Optional periodic report() emits ENGINEERING_SENSOR_REPORT.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from probos.cognitive.engineering_sensors.bundle import EngineeringSensorBundle
from probos.events import EventType

logger = logging.getLogger(__name__)


class EngineeringSensorService:
    """Public API:
    - take_snapshot() -> EngineeringSensorBundle
    - report()        -> None  (one-shot emit)
    - start()         -> None  (begin periodic emit)
    - stop()          -> None  (cancel periodic task)
    """

    def __init__(
        self,
        *,
        runtime: Any,
        emit_event: Any | None = None,
        report_interval_seconds: float = 60.0,
    ) -> None:
        self._runtime = runtime
        self._emit_event = emit_event
        self._interval = max(1.0, float(report_interval_seconds))
        self._task: asyncio.Task[None] | None = None
        self._stopping = False

    def take_snapshot(self) -> EngineeringSensorBundle:
        return EngineeringSensorBundle(
            captured_at=time.time(),
            pool_summary=self._collect_pools(),
            capability_summary=self._collect_capabilities(),
            gossip_summary=self._collect_gossip(),
        )

    def report(self) -> None:
        snap = self.take_snapshot()
        if self._emit_event is None:
            return
        try:
            self._emit_event(
                EventType.ENGINEERING_SENSOR_REPORT,
                {
                    "captured_at": snap.captured_at,
                    "pools": list(snap.pool_summary.keys()),
                    "capability_agents": snap.capability_summary.get("agent_count", 0),
                    "gossip_view_size": snap.gossip_summary.get("view_size", 0),
                },
            )
        except Exception:
            logger.warning("AD-641f: report emit failed", exc_info=True)

    async def start(self) -> None:
        if self._task is not None:
            return
        loop = asyncio.get_running_loop()
        self._stopping = False
        self._task = loop.create_task(
            self._report_loop(), name="engineering_sensor_report",
        )

    async def stop(self) -> None:
        self._stopping = True
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except (asyncio.CancelledError, Exception):
            pass
        finally:
            self._task = None

    async def _report_loop(self) -> None:
        try:
            while not self._stopping:
                try:
                    self.report()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.warning(
                        "AD-641f: periodic report failed; continuing",
                        exc_info=True,
                    )
                await asyncio.sleep(self._interval)
        except asyncio.CancelledError:
            return

    def _collect_pools(self) -> dict[str, dict[str, Any]]:
        spawner = getattr(self._runtime, "spawner", None)
        if spawner is None:
            return {}
        pools = getattr(spawner, "pools", {}) or {}
        out: dict[str, dict[str, Any]] = {}
        for name, pool in pools.items():
            current = getattr(pool, "current_size", None)
            target = getattr(pool, "target_size", None)
            out[str(name)] = {
                "current_size": current if current is not None else 0,
                "target_size": target if target is not None else 0,
            }
        return out

    def _collect_capabilities(self) -> dict[str, Any]:
        registry = getattr(self._runtime, "capability_registry", None)
        if registry is None:
            return {"agent_count": 0, "intents": []}
        agent_count = int(getattr(registry, "agent_count", 0) or 0)
        try:
            all_caps = registry.get_all_capabilities() or {}
            intents = sorted({str(k) for k in all_caps.keys()})
        except Exception:
            intents = []
        return {"agent_count": agent_count, "intents": intents}

    def _collect_gossip(self) -> dict[str, Any]:
        gossip = getattr(self._runtime, "gossip", None)
        if gossip is None:
            return {"view_size": 0, "peer_count": 0}
        view_size = int(getattr(gossip, "view_size", 0) or 0)
        try:
            view = gossip.get_view() or {}
            peer_count = len(view)
        except Exception:
            peer_count = 0
        return {"view_size": view_size, "peer_count": peer_count}
```

---

## Section 4: Configuration

**File:** `src/probos/config.py`

Add Pydantic model after the most recent addition:

```python
class EngineeringSensorsConfig(BaseModel):
    """AD-641f: Engineering Chief Observability configuration."""

    enabled: bool = True
    report_interval_seconds: float = 60.0
    auto_start_periodic_report: bool = False
```

Add `engineering_sensors: EngineeringSensorsConfig = Field(default_factory=EngineeringSensorsConfig)` to `SystemConfig`.

Verified absent: `grep -n "EngineeringSensorsConfig\|engineering_sensors:" src/probos/config.py` returns no matches.

---

## Section 5: Startup wiring

**File:** `src/probos/startup/finalize.py`

Append after the most recent finalize wiring block:

```python
# AD-641f: Engineering Sensor Service
es_cfg = getattr(getattr(runtime, "config", None), "engineering_sensors", None)
if es_cfg is not None and es_cfg.enabled:
    runtime.engineering_sensor_service = EngineeringSensorService(
        runtime=runtime,
        emit_event=runtime.emit_event,
        report_interval_seconds=es_cfg.report_interval_seconds,
    )
    if es_cfg.auto_start_periodic_report:
        # Hold the start task on runtime so it isn't garbage-collected.
        runtime._engineering_sensor_start_task = asyncio.create_task(
            runtime.engineering_sensor_service.start(),
            name="engineering_sensor_start",
        )
else:
    runtime.engineering_sensor_service = None
```

---

## Section 6: Tests

**File:** `tests/test_ad641f_engineering_sensors.py` (new)

Cover (~13 tests):

1. `test_event_type_engineering_sensor_report_exists`
2. `test_engineering_sensors_config_defaults`
3. `test_bundle_is_frozen_dataclass`
4. `test_take_snapshot_with_no_runtime_state_returns_empty_dicts` — runtime stub with no spawner/registry/gossip.
5. `test_collect_pools_reads_current_and_target_size`
6. `test_collect_capabilities_returns_agent_count_and_sorted_intents`
7. `test_collect_gossip_returns_view_size_and_peer_count`
8. `test_report_emits_engineering_sensor_report` — confirm payload contains expected keys.
9. `test_report_no_emit_when_emit_event_none`
10. `test_start_creates_named_task` — `_task.get_name() == "engineering_sensor_report"`.
11. `test_stop_cancels_task_and_resets_to_none`
12. `test_report_interval_minimum_enforced` — `report_interval_seconds=0.0` → clamped to 1.0.
13. `test_report_swallows_emit_exceptions` — `emit_event.side_effect = RuntimeError`; service stays alive.

Per convention #11 — service tests use real runtime stubs (SimpleNamespace) over MagicMock so attribute access is deterministic.

---

## What This Does NOT Change (Explicit Scope Boundaries)

1. **`EngineeringAgent`** — not modified. Agent reads `runtime.engineering_sensor_service.take_snapshot()` voluntarily; instructions wiring is a future grandchild AD.
2. **`runtime.spawner` / `Pool`** — read-only consumers of `current_size` / `target_size`. No source edits.
3. **`runtime.capability_registry`** — read-only via `agent_count` and `get_all_capabilities()`. No source edits.
4. **`runtime.gossip`** — read-only via `view_size` and `get_view()`. No source edits.
5. **Per-peer gossip introspection** — wholesale-deferred to AD-641f-i.
6. **Capability registry mutation** — wholesale-deferred to AD-641f-ii.
7. **Cross-pool failover** — wholesale-deferred to AD-641f-iii.

---

## Engineering Principles Compliance

- **Single Responsibility:** Bundle is data. Service collects + reports.
- **Open/Closed:** New sensor (Hebbian summary, future) is a new private `_collect_*` method; existing collectors unchanged.
- **Dependency Inversion:** Service constructor takes `runtime` and `emit_event`; no global imports.
- **Law of Demeter:** Walks public attribute names with defensive `getattr`. Does not reach into private state.
- **Async hygiene:** `start()` stores task as `self._task` with `name="engineering_sensor_report"` per Wave 5 convention. `stop()` cancels and awaits.
- **Fail Fast / Log-and-Degrade:** Emit failures swallowed; report loop continues on exception.

---

## Verification

```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad641f_engineering_sensors.py -v -n 0
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_engineering_officer.py tests/test_ad467_operations.py -v -n 0
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile
```

---

## Tracking

1. **PROGRESS.md** — Prepend AD-641f CLOSED entry with v1 scope summary + 3 deferred grandchildren.
2. **DECISIONS.md** — No entry required.
3. **docs/development/roadmap.md** — Update line 7056 reflecting AD-641f CLOSED.

---

## Acceptance Criteria

- 13/13 focused tests pass at `-n 0`.
- Full parallel gate non-decreasing.
- `runtime.engineering_sensor_service` is a public attribute (or `None` when disabled).
- `ENGINEERING_SENSOR_REPORT` is a member of `EventType`.
- `EngineeringSensorBundle` is frozen.
- `EngineeringAgent` is unchanged.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-02)

```
grep -n "class EngineeringAgent" src/probos/cognitive/engineering_officer.py
  src/probos/cognitive/engineering_officer.py:37: class EngineeringAgent(CognitiveAgent):

grep -n "agent_count" src/probos/mesh/capability.py
  src/probos/mesh/capability.py:97: @property
  src/probos/mesh/capability.py:98: def agent_count(self) -> int:

grep -n "view_size\|def get_view" src/probos/mesh/gossip.py
  src/probos/mesh/gossip.py:99: def get_view(self) -> dict[AgentID, GossipEntry]:
  src/probos/mesh/gossip.py:118: @property
  src/probos/mesh/gossip.py:119: def view_size(self) -> int:

grep -n "self\.spawner\|self\.capability_registry\|self\.gossip" src/probos/runtime.py
  src/probos/runtime.py:294: self.spawner = AgentSpawner(self.registry)
  src/probos/runtime.py:301: self.capability_registry = CapabilityRegistry(...)
  src/probos/runtime.py:309: self.gossip = GossipProtocol(...)

grep -n "current_size\|target_size" src/probos/substrate/pool.py
  src/probos/substrate/pool.py:53: @property current_size and target_size (per AD-467 precedent)

grep -n "ENGINEERING_SENSOR_REPORT" src/probos/events.py
  (no matches; introduced by this prompt)

grep -n "class EngineeringSensorBundle\|engineering_sensor_service" src/probos/
  (no matches; new module)
```
