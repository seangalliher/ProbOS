# AD-641a: Observability Bridge — Brain Sensors → Ward Room System Feeds (v1)

**Status:** Ready for builder
**Wave:** 9A (parallel-safe — independent of 641b/c/d/e/f at source-file level)
**Dependencies:** Reads `runtime.attention` (verified at `runtime.py:197, 359` — `AttentionManager` instance is wired as `runtime.attention`, NOT `runtime.attention_manager`). Reads existing `WardRoomService.create_post` at `src/probos/ward_room/service.py:400` (verified). Reads spawned `VitalsMonitorAgent` heartbeats via `runtime.event_log.query()`. Polls `runtime.spawner` pool sizes (verified pattern from AD-467 `ResourceAllocatorAgent`).
**Estimated tests:** ~14
**Risk:** MEDIUM — read-only bridge; no brain modification. Asyncio task hygiene applies (convention: hold task references).

---

## Problem

The Ship's Computer (Brain) maintains rich operational state — vitals, pool health, attention priorities, Hebbian weights — but the Crew (Ward Room agents) cannot see any of it. Per the AD-641 design doc (`docs/research/ad-641-brain-enhancement-design.md` Category B), the integration model is **read-only observability**: crew read sensors, the brain owns the state.

`grep -rn "class ObservabilityBridge\|brain_sensor\|sensor_bridge" src/probos/` returns no matches.

`grep -n "vitals_monitor\|attention_manager\|hebbian_router" src/probos/runtime.py` confirms the brain-side state is on the runtime but no consumer-facing surface exists.

The roadmap entry (line 7056) names AD-641a as "Observability Bridge — System channel(s) in Ward Room that surface brain state (VitalsMonitor, pool health, attention priorities). Read-only. Push-based (brain publishes, crew subscribe)."

## Solution Overview

One new module under `src/probos/cognitive/observability/` (new package; AD-641a OWNS `__init__.py` creation, mirroring AD-457/459/466/467/469/475 precedents):

1. **`ObservabilityBridge`** (`bridge.py`) — coordinator that polls 3 brain sensors at a configurable cadence and publishes a single Ward Room system post per cycle. Public API: `start()`, `stop()`, `take_snapshot() -> ObservabilityBridgeSnapshot`. Holds a single named `asyncio.Task` reference (per convention: fire-and-forget tasks silently swallow exceptions).
2. **`ObservabilityBridgeSnapshot`** (frozen dataclass) — captures `vitals_summary`, `pool_health`, `attention_priorities`, `captured_at`. The snapshot is the public observation surface; agents that want richer brain state read this dataclass, not raw runtime internals (Law of Demeter).

This is **policy + diagnostics layered on existing surfaces.** AD-641a does NOT modify `VitalsMonitorAgent`, does NOT modify `AttentionManager`, does NOT modify `runtime.spawner`. Push-based: bridge polls and posts; crew read by subscribing to the system channel or by calling `take_snapshot()`.

**v1 scope (no-theater discipline; convention #7 + #14 — 3 of 6 capabilities ship):**

- **3 brain sensors wired into v1:** vitals (from latest `VitalsMonitorAgent` heartbeat in event_log), pool health (from `runtime.spawner` pool sizes), attention priorities (from `runtime.attention` queue snapshot — note: attribute is `runtime.attention`, NOT `runtime.attention_manager`).
- Real periodic posts to a configurable Ward Room system channel.
- `ObservabilityBridgeSnapshot` is real and serialized into post body.

**3 wholesale-deferred to grandchild ADs:**

- **Hebbian-weight feed** — `AD-641a-i`. Reading `runtime.hebbian_router._weights` requires a public-API addition (currently private); needs convention #1 (public-attribute discipline) on the Hebbian side first.
- **Structured HXI surfaces (panels/widgets)** — `AD-641a-ii`. v1 emits to Ward Room as text posts; HXI rendering is its own surface.
- **Captain alert routing on threshold breach** — `AD-641a-iii`. v1 publishes data; alerting policy + Captain DM dispatch belongs to a separate AD.

---

## Section 0: Event Types

Add to `src/probos/events.py` (after `MCP_BRIDGE_FAILED` at line 224):

```
OBSERVABILITY_SNAPSHOT_PUBLISHED = "observability_snapshot_published"  # AD-641a
OBSERVABILITY_BRIDGE_FAILED = "observability_bridge_failed"  # AD-641a
```

Verified absent: `grep -n "OBSERVABILITY_SNAPSHOT_PUBLISHED\|OBSERVABILITY_BRIDGE_FAILED" src/probos/events.py` returns no matches.

---

## Section 1: Package init

**File:** `src/probos/cognitive/observability/__init__.py` (new — AD-641a OWNS directory creation)

```python
"""AD-641a: Observability Bridge -- brain sensors -> Ward Room system feeds."""

from probos.cognitive.observability.bridge import (
    ObservabilityBridge,
    ObservabilityBridgeSnapshot,
)

__all__ = [
    "ObservabilityBridge",
    "ObservabilityBridgeSnapshot",
]
```

---

## Section 2: `ObservabilityBridge` + Snapshot

**File:** `src/probos/cognitive/observability/bridge.py` (new)

```python
"""AD-641a: Observability Bridge -- read-only sensor surface from brain to crew.

The Ship's Computer (brain) owns operational state (vitals, pools, attention).
The Crew (Ward Room agents) read that state via this bridge -- never directly.
Per the AD-641 design doc, this is the interface between nervous system and
consciousness.

Push-based: bridge polls sensors at a configurable cadence, posts a snapshot
summary into a Ward Room system channel, and emits OBSERVABILITY_SNAPSHOT_PUBLISHED
so subscribers can consume the structured payload.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from probos.events import EventType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ObservabilityBridgeSnapshot:
    """Frozen sensor snapshot. The public observation surface for crew agents."""

    captured_at: float
    vitals_summary: dict[str, Any] = field(default_factory=dict)
    pool_health: dict[str, dict[str, Any]] = field(default_factory=dict)
    attention_priorities: list[dict[str, Any]] = field(default_factory=list)


class ObservabilityBridge:
    """v1 read-only sensor bridge.

    Public API:
      - start() -> None  -- begin periodic publishing
      - stop()  -> None  -- cancel publish task
      - take_snapshot() -> ObservabilityBridgeSnapshot  -- one-shot read
    """

    def __init__(
        self,
        *,
        runtime: Any,
        ward_room: Any | None,
        emit_event: Any | None = None,
        publish_interval_seconds: float = 60.0,
        system_channel: str = "system_observability",
    ) -> None:
        self._runtime = runtime
        self._ward_room = ward_room
        self._emit_event = emit_event
        self._interval = max(1.0, float(publish_interval_seconds))
        self._channel = system_channel
        self._task: asyncio.Task[None] | None = None
        self._stopping = False

    async def start(self) -> None:
        if self._task is not None:
            return
        loop = asyncio.get_running_loop()
        self._stopping = False
        self._task = loop.create_task(
            self._publish_loop(), name="observability_bridge",
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

    def take_snapshot(self) -> ObservabilityBridgeSnapshot:
        return ObservabilityBridgeSnapshot(
            captured_at=time.time(),
            vitals_summary=self._collect_vitals(),
            pool_health=self._collect_pool_health(),
            attention_priorities=self._collect_attention(),
        )

    async def _publish_loop(self) -> None:
        try:
            while not self._stopping:
                try:
                    await self._publish_once()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # log-and-degrade
                    logger.warning(
                        "AD-641a: observability publish failed; will retry next cycle: %s",
                        exc,
                    )
                    if self._emit_event is not None:
                        try:
                            self._emit_event(
                                EventType.OBSERVABILITY_BRIDGE_FAILED,
                                {"reason": str(exc)},
                            )
                        except Exception:
                            pass
                await asyncio.sleep(self._interval)
        except asyncio.CancelledError:
            return

    async def _publish_once(self) -> None:
        snap = self.take_snapshot()
        if self._ward_room is None:
            return
        body = self._format_post(snap)
        await self._ward_room.create_post(
            thread_id=self._channel,
            author_id="system",
            author_callsign="System",
            body=body,
        )
        if self._emit_event is not None:
            self._emit_event(
                EventType.OBSERVABILITY_SNAPSHOT_PUBLISHED,
                {
                    "captured_at": snap.captured_at,
                    "pools": list(snap.pool_health.keys()),
                    "attention_count": len(snap.attention_priorities),
                },
            )

    def _format_post(self, snap: ObservabilityBridgeSnapshot) -> str:
        lines = ["[Brain Observability Snapshot]"]
        if snap.vitals_summary:
            lines.append(f"vitals: {snap.vitals_summary}")
        if snap.pool_health:
            lines.append(f"pools: {snap.pool_health}")
        if snap.attention_priorities:
            lines.append(
                f"attention top-{len(snap.attention_priorities)}: "
                f"{snap.attention_priorities}"
            )
        return "\n".join(lines)

    def _collect_vitals(self) -> dict[str, Any]:
        event_log = getattr(self._runtime, "event_log", None)
        if event_log is None:
            return {}
        try:
            recent = event_log.query(
                event_type=EventType.AGENT_STATE.value, limit=5,
            )
        except Exception:
            return {}
        for entry in reversed(list(recent or [])):
            payload = getattr(entry, "payload", None) or {}
            if payload.get("agent_type") == "vitals_monitor":
                return dict(payload)
        return {}

    def _collect_pool_health(self) -> dict[str, dict[str, Any]]:
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

    def _collect_attention(self) -> list[dict[str, Any]]:
        attn = getattr(self._runtime, "attention", None)
        if attn is None:
            return []
        queue = getattr(attn, "_queue", {}) or {}
        items: list[dict[str, Any]] = []
        for task_id, entry in queue.items():
            score = getattr(entry, "score", None)
            items.append(
                {"task_id": str(task_id), "score": float(score) if score is not None else 0.0},
            )
        items.sort(key=lambda x: x["score"], reverse=True)
        return items[:5]
```

---

## Section 3: Configuration

**File:** `src/probos/config.py`

Add a new Pydantic model after the `MCPConfig` block (which is the most recent addition; verify by grep before applying):

```python
class ObservabilityBridgeConfig(BaseModel):
    """AD-641a: Observability Bridge configuration."""

    enabled: bool = True
    publish_interval_seconds: float = 60.0
    system_channel: str = "system_observability"
```

Add `observability_bridge: ObservabilityBridgeConfig = Field(default_factory=ObservabilityBridgeConfig)` to `SystemConfig` (mirror placement after `mcp` field).

Verified absent: `grep -n "ObservabilityBridgeConfig\|observability_bridge" src/probos/config.py` returns no matches.

---

## Section 4: Startup wiring

**File:** `src/probos/startup/finalize.py`

Add after the `runtime.mcp_bridge` wiring block (which AD-449 added). Use the SEARCH/REPLACE pattern matching the live source character-for-character. Anchor on the `runtime.mcp_bridge =` block; insert AD-641a wiring directly after.

Wire `runtime.observability_bridge = ObservabilityBridge(runtime=runtime, ward_room=getattr(runtime, "ward_room", None), emit_event=runtime.emit_event, publish_interval_seconds=cfg.publish_interval_seconds, system_channel=cfg.system_channel)` when `cfg.enabled` is True; assign `None` otherwise. Schedule `runtime.observability_bridge.start()` via `asyncio.create_task(...)` and store the task on `runtime` so it isn't garbage-collected (Convention: hold task references; per Wave 5 convention).

---

## Section 5: Tests

**File:** `tests/test_ad641a_observability_bridge.py` (new)

Cover (~14 tests):

1. `test_event_type_observability_snapshot_published_exists` — enum value asserts.
2. `test_event_type_observability_bridge_failed_exists` — enum value asserts.
3. `test_observability_bridge_config_defaults` — `enabled=True`, `publish_interval_seconds=60.0`, `system_channel="system_observability"`.
4. `test_snapshot_is_frozen_dataclass` — `dataclasses.replace` returns new instance.
5. `test_take_snapshot_with_no_runtime_state_returns_empty_collections` — runtime stub with no `event_log`/`spawner`/`attention_manager`.
6. `test_collect_vitals_picks_latest_vitals_monitor_state` — `event_log.query` returns mixed events; helper picks vitals_monitor entry.
7. `test_collect_pool_health_reads_current_and_target_size` — stub `spawner.pools` with two pools.
8. `test_collect_attention_returns_top_5_by_score_desc` — stub queue with 7 entries.
9. `test_publish_once_calls_ward_room_create_post` — `AsyncMock(spec=WardRoomService)`.
10. `test_publish_once_emits_observability_snapshot_published` — confirm payload contains `captured_at`, `pools`, `attention_count`.
11. `test_publish_loop_emits_failed_on_exception` — `ward_room.create_post.side_effect = RuntimeError`; expect `OBSERVABILITY_BRIDGE_FAILED`.
12. `test_start_creates_named_task` — `bridge._task.get_name() == "observability_bridge"` (convention: hold + name task references).
13. `test_stop_cancels_task_cleanly` — task cancelled and `_task` reset to `None`.
14. `test_publish_interval_minimum_enforced` — `publish_interval_seconds=0.0` clamped to 1.0 in `__init__`.

Per convention #18, all `WardRoomService` mocks must be `AsyncMock(spec=WardRoomService)` so `create_post` is auto-async (BF-250 lesson).

---

## What This Does NOT Change (Explicit Scope Boundaries)

1. **`VitalsMonitorAgent`** — observed only via `event_log.query`; agent code unchanged.
2. **`AttentionManager`** — observed via existing `_queue` attribute (read-only). No public-API extension required in v1; future grandchild AD may add `snapshot()` public method to replace the `_queue` read.
3. **`runtime.spawner` / `Pool`** — observed via existing `current_size` / `target_size` properties (verified at `pool.py:53` per AD-467 precedent).
4. **`HebbianRouter`** — wholesale-deferred to AD-641a-i.
5. **HXI surfaces** — wholesale-deferred to AD-641a-ii.
6. **Captain alert routing** — wholesale-deferred to AD-641a-iii.
7. **NATS publishing** — bridge uses Ward Room post API today; NATS migration belongs to AD-641g (already independently scoped).

---

## Engineering Principles Compliance

- **Single Responsibility:** `ObservabilityBridge` polls and publishes. Snapshot is data only. No business logic mixed.
- **Open/Closed:** Adding a new sensor (e.g., Hebbian weights in AD-641a-i) is a new private `_collect_*` method; existing sensors unchanged.
- **Dependency Inversion:** Constructor injection — runtime, ward_room, emit_event are all parameters; nothing imported by global lookup.
- **Law of Demeter:** Crew read `ObservabilityBridgeSnapshot` (a flat dataclass), not `runtime.attention_manager._queue`. This is the entire point of the bridge.
- **Fail Fast / Log-and-Degrade:** Publish loop catches exceptions, emits `OBSERVABILITY_BRIDGE_FAILED`, logs at warning, continues next cycle (degraded operation acceptable).
- **DRY:** No duplication of pool/attention collection — wraps existing surfaces.
- **Async hygiene:** `create_task` result stored as `self._task` and given `name="observability_bridge"` per Wave 5 task-reference convention. `stop()` cancels and awaits cleanup.

---

## Verification

After building, run:

```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad641a_observability_bridge.py -v -n 0
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad467_operations.py tests/test_ad469_eps.py tests/test_unread_dms.py -v -n 0
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile
```

---

## Tracking

1. **PROGRESS.md** — Prepend AD-641a CLOSED entry with v1 scope summary + 3 deferred grandchildren.
2. **DECISIONS.md** — No entry required unless a non-trivial design choice is made during build (the bridge pattern is itself documented in `ad-641-brain-enhancement-design.md`).
3. **docs/development/roadmap.md** — Update line 7056 AD-641 row to reflect AD-641a CLOSED (`*(partial — 641a complete)*`).

---

## Acceptance Criteria

- 14/14 focused tests pass at `-n 0`.
- Full parallel gate non-decreasing (`pytest tests/ -q -n 8 --dist=loadfile`).
- `ObservabilityBridge` is wired at `runtime.observability_bridge` (or `None` if `enabled=False`).
- `OBSERVABILITY_SNAPSHOT_PUBLISHED` and `OBSERVABILITY_BRIDGE_FAILED` are members of `EventType`.
- `_task` is named `observability_bridge` and held as instance attribute.
- Snapshot is frozen.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-02)

```
grep -n "class VitalsMonitorAgent\|class AttentionManager\|class WardRoomService" src/probos/
  src/probos/agents/medical/vitals_monitor.py:28: class VitalsMonitorAgent(HeartbeatAgent):
  src/probos/cognitive/attention.py:24: class AttentionManager:
  src/probos/ward_room/service.py:29: class WardRoomService(EventEmitterMixin):

grep -n "self\._queue\|self\.spawner\|attention =\|self\.attention" src/probos/
  src/probos/cognitive/attention.py:42: self._queue: dict[str, AttentionEntry] = {}
  src/probos/runtime.py:197: attention: AttentionManager
  src/probos/runtime.py:359: self.attention = AttentionManager( (NOT attention_manager)

grep -n "current_size\|target_size" src/probos/substrate/pool.py
  src/probos/substrate/pool.py:53: @property current_size and target_size (per AD-467 precedent)

grep -n "OBSERVABILITY" src/probos/events.py
  (no matches; EventTypes are introduced by this prompt)

grep -n "class ObservabilityBridge\|observability_bridge" src/probos/
  (no matches; new module)

grep -n "MCPConfig\|MCPServerConfig" src/probos/config.py
  (added by AD-449; ObservabilityBridgeConfig is the new sibling Pydantic model)

grep -rn "asyncio\.create_task" src/probos/cognitive/
  Multiple existing patterns; new bridge follows convention with named task and instance reference.
```
