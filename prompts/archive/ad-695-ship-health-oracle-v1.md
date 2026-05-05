# AD-695 v1 — Ship Health Oracle Tier + Threshold Bridge Alerts

**Status:** ready-for-build
**Dependencies:** AD-462e (Oracle, public `runtime.oracle`), AD-641a (ObservabilityBridge — shipped Wave 9A; posting already disabled BF-258), AD-466 / AD-459 (DegradationManager), AD-410 (BridgeAlertService + WardRoomRouter.deliver_bridge_alert), AD-686/AD-688/AD-692 (current Oracle tier list — episodic, records, operational, archive, semantic, graph).
**Estimated tests:** 13 (≥12 floor).
**Closes:** GH issue #389.
**Layer:** OSS.

---

## Problem

Three converging strands need to land together so the Crew can read ship health through the same channel they read every other knowledge surface:

1. **No Oracle tier surfaces operational telemetry.** Crew agents that want vitals / pool / attention / degradation state today must reach into private runtime attributes (`runtime._emergent_detector`, `runtime.attention._queue`, etc.) — no public, score-ranked, provenance-tagged surface.
2. **AD-641a Observability Bridge wrote spam into a non-existent thread.** BF-258 already disabled the `_publish_once` Ward Room post (the loop now only emits `OBSERVABILITY_SNAPSHOT_PUBLISHED` events; no consumer). The bridge is a heart with no pulse — it ticks every 60 s and produces nothing actionable.
3. **No threshold-driven bridge alerts for system health.** `BridgeAlertService` already supports vitals / trust / convergence / cascade etc., but there is no `check_pool_saturation` / `check_degradation` / `check_attention_depth` family. Captain only learns about pool saturation when something downstream fails.

Component 3 of the GH issue is satisfied at HEAD by BF-258; this AD does **not** re-disable. We replace the now-dormant publish loop with a threshold-check loop.

---

## Solution overview

Three additive components, all in OSS:

1. **Oracle Tier 7 "health"** — `OracleService._query_health(query_text, *, k)` reads vitals + pool stats + attention queue + degradation status from `runtime`, scores each metric by query keyword overlap, returns `OracleResult` with `provenance="[health: <metric>]"`. Append `"health"` to the default `active_tiers` list (becomes 7th tier after `graph`).
2. **`ThresholdAlertService`** — new module `src/probos/cognitive/threshold_alerts.py`. Invoked periodically by the bridge loop. Reads the same runtime telemetry, fires `BridgeAlert` objects for breaches, posts via `runtime.ward_room_router.deliver_bridge_alert(alert)`, dedups within `dedup_window_seconds`. Returns the list of alerts that fired (for testing).
3. **Bridge loop becomes a threshold loop** — `ObservabilityBridge._publish_once` switches its no-op (post-BF-258) for `await runtime.threshold_alerts.check_and_alert()` when `runtime.threshold_alerts` is wired. `take_snapshot()` retains its current shape — it is consumed by both the new Oracle tier and the threshold service.

Health tier is **read-only**; `ThresholdAlertService` is **alert-only**. Neither service mutates runtime telemetry.

---

## Verified Against Codebase (HEAD `50d43fe`, 2026-05-04)

```
grep -n "class OracleService" src/probos/cognitive/oracle_service.py
  113: class OracleService:
grep -n "active_tiers = tiers" src/probos/cognitive/oracle_service.py
  187:        active_tiers = tiers or [
  188:            "episodic", "records", "operational", "archive", "semantic", "graph",
grep -n "class OracleResult" src/probos/cognitive/oracle_service.py
  23: class OracleResult:
grep -n "async def _query_semantic" src/probos/cognitive/oracle_service.py
  447:    async def _query_semantic(
grep -n "async def _query_graph" src/probos/cognitive/oracle_service.py
  483:    async def _query_graph(
grep -n "def attach_knowledge_graph" src/probos/cognitive/oracle_service.py
  153:    def attach_knowledge_graph(self, knowledge_graph: Any) -> None:

grep -n "class ObservabilityBridge" src/probos/cognitive/observability/bridge.py
  36: class ObservabilityBridge:
grep -n "async def take_snapshot" src/probos/cognitive/observability/bridge.py
  84:    async def take_snapshot(self) -> ObservabilityBridgeSnapshot:
grep -n "async def _publish_once" src/probos/cognitive/observability/bridge.py
  119:    async def _publish_once(self) -> None:
grep -n "BF-258" src/probos/cognitive/observability/bridge.py
  121:        # BF-258: Ward Room posting disabled. AD-641a design review determined
  124:        # take_snapshot() retained for future Oracle "health" tier integration.

grep -n "class BridgeAlertService" src/probos/bridge_alerts.py
  44: class BridgeAlertService:
grep -n "class AlertSeverity" src/probos/bridge_alerts.py
  23: class AlertSeverity(str, Enum):
grep -n "class BridgeAlert\b" src/probos/bridge_alerts.py
  30: class BridgeAlert:
grep -n "async def deliver_bridge_alert" src/probos/ward_room_router.py
  1031:    async def deliver_bridge_alert(self, alert: Any) -> None:

grep -n "class DegradationManager" src/probos/degradation/manager.py
  32: class DegradationManager:
grep -n "def status" src/probos/degradation/manager.py
  79:    def status(self) -> DegradationStatus:
grep -n "class StressLevel" src/probos/degradation/policy.py
  10: class StressLevel(str, Enum):
grep -n "runtime.degradation_manager = DegradationManager" src/probos/startup/finalize.py
  1052:    runtime.degradation_manager = DegradationManager(

grep -n "class AttentionManager" src/probos/cognitive/attention.py
  24: class AttentionManager:
grep -n "def get_queue_snapshot" src/probos/cognitive/attention.py
  183:    def get_queue_snapshot(self) -> list[AttentionEntry]:
grep -n "def queue_size" src/probos/cognitive/attention.py
  193:    def queue_size(self) -> int:

grep -n "def info" src/probos/substrate/pool.py
  234:    def info(self) -> dict:    # returns {name, agent_type, target_size, current_size, agents}

grep -n "self.bridge_alerts = comm.bridge_alerts" src/probos/runtime.py
  1613:        self.bridge_alerts = comm.bridge_alerts
grep -n "self.ward_room_router = fin.ward_room_router" src/probos/runtime.py
  1693:        self.ward_room_router = fin.ward_room_router
grep -n "self.attention = AttentionManager" src/probos/runtime.py
  361:        self.attention = AttentionManager(

grep -n "ObservabilityBridgeConfig" src/probos/config.py
  1298: class ObservabilityBridgeConfig(BaseModel):
grep -n "observability_bridge: ObservabilityBridgeConfig" src/probos/config.py
  2161:    observability_bridge: ObservabilityBridgeConfig = Field(...)
grep -n "runtime.observability_bridge = ObservabilityBridge" src/probos/startup/finalize.py
  1337:        runtime.observability_bridge = ObservabilityBridge(
```

**AD-641a spam-loop location**: `src/probos/cognitive/observability/bridge.py:119` — `_publish_once`. BF-258 already removed the `create_post()` call; what remains is an `EventType.OBSERVABILITY_SNAPSHOT_PUBLISHED` emit with **no consumer**. AD-695 replaces the loop body with a threshold-alert call (event emit is preserved alongside).

**Runtime attribute audit** for collision:
- `runtime.threshold_alerts` — does **not** exist at HEAD (verified by grep). Safe to introduce.
- `runtime.observability_bridge` already exists (AD-641a).
- `runtime.bridge_alerts` already exists (AD-410). Distinct concept (alert constructor service, no scheduling); ThresholdAlertService consumes it indirectly via `BridgeAlert` constructor reuse.

**Phantom-API pre-check (script)**: 0 phantoms expected. All new symbols (`ThresholdAlertService`, `_query_health`, `runtime.threshold_alerts`, `ThresholdAlertConfig`) are introduced by this prompt. Standard FP class — same as Waves 27/36/37/38/41/42.

---

## Section 0 — New EventTypes

**No new EventTypes.** `THRESHOLD_ALERT_FIRED` would be useful but is out of scope; the existing `bridge_alert` event-log entry written by `WardRoomRouter.deliver_bridge_alert` (`ward_room_router.py:1075`) is sufficient for v1 traceability.

---

## Section 1 — `ThresholdAlertService` module

Create `src/probos/cognitive/threshold_alerts.py`:

```python
"""AD-695: Threshold Alert Service — health metric threshold → bridge alert.

Replaces the AD-641a continuous Ward Room posting loop (disabled by BF-258)
with a threshold-driven loop. Reads the same runtime telemetry the
ObservabilityBridge collects, but ONLY emits a BridgeAlert when a metric
crosses a configurable boundary.

Dedup is per-(threshold_id, related_pool|severity) within a sliding window
to avoid alert spam during sustained degradation.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from probos.bridge_alerts import AlertSeverity, BridgeAlert

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ThresholdAlert:
    """The structured record returned to callers (for testing/audit).

    Distinct from BridgeAlert: BridgeAlert is the delivery payload, ThresholdAlert
    is the threshold-evaluation outcome.
    """

    threshold_id: str
    severity: str           # "info" | "advisory" | "alert"
    metric: str             # e.g. "pool_saturation", "degradation_tier", "attention_queue_depth"
    value: float
    threshold: float
    title: str
    detail: str
    fired_at: float = field(default_factory=time.time)
    related_pool: str | None = None


class ThresholdAlertService:
    """Periodic threshold checker that posts BridgeAlerts on breaches.

    Runtime DI: receives ``runtime`` and reads:
      - runtime.spawner.pools[name].info() (current_size / target_size)
      - runtime.attention.queue_size
      - runtime.degradation_manager.status() (StressLevel, shed_tiers)
      - runtime.observability_bridge.take_snapshot() (vitals_summary;
        optional, log-and-degrade if absent)

    Posts alerts via runtime.ward_room_router.deliver_bridge_alert(alert).
    Dedup is keyed on threshold_id + related_pool/None within ``dedup_window_seconds``.
    Never raises into the caller — collector failures are tier-2 log-and-degrade.
    """

    def __init__(
        self,
        runtime: Any,
        *,
        pool_saturation_floor: float = 0.9,
        degradation_min_severity: str = "degraded",
        attention_queue_depth: int = 20,
        dedup_window_seconds: float = 300.0,
    ) -> None:
        self._runtime = runtime
        self._pool_saturation_floor = float(pool_saturation_floor)
        self._degradation_min_severity = str(degradation_min_severity).lower()
        self._attention_queue_depth = int(attention_queue_depth)
        self._dedup_window = max(1.0, float(dedup_window_seconds))
        # Dedup ring: dedup_key -> last fired wall-clock timestamp.
        self._recent: dict[str, float] = {}

    async def check_and_alert(self) -> list[ThresholdAlert]:
        """Run all thresholds once. Returns the alerts that actually fired
        (deduped). Posts each fired alert to the ward room (best-effort)."""
        fired: list[ThresholdAlert] = []
        # Each check is independently log-and-degrade.
        for check in (
            self._check_pool_saturation,
            self._check_degradation,
            self._check_attention_queue_depth,
        ):
            try:
                fired.extend(check())
            except Exception:
                logger.warning(
                    "AD-695: threshold check %s raised; continuing",
                    getattr(check, "__name__", "<unknown>"),
                    exc_info=True,
                )
        # Deliver each alert to the ward room. Failure to deliver does NOT
        # remove the alert from the returned list.
        for ta in fired:
            try:
                await self._deliver(ta)
            except Exception:
                logger.warning(
                    "AD-695: ward-room delivery failed for threshold alert %s",
                    ta.threshold_id,
                    exc_info=True,
                )
        return fired

    # -------------------------- checks --------------------------

    def _check_pool_saturation(self) -> list[ThresholdAlert]:
        spawner = getattr(self._runtime, "spawner", None)
        if spawner is None:
            return []
        pools = getattr(spawner, "pools", None) or {}
        out: list[ThresholdAlert] = []
        for name, pool in pools.items():
            current = getattr(pool, "current_size", 0) or 0
            target = getattr(pool, "target_size", 0) or 0
            if target <= 0:
                continue
            saturation = float(current) / float(target)
            if saturation < self._pool_saturation_floor:
                continue
            dedup_key = f"pool_saturation:{name}"
            if not self._should_fire(dedup_key):
                continue
            out.append(ThresholdAlert(
                threshold_id=dedup_key,
                severity="advisory",
                metric="pool_saturation",
                value=saturation,
                threshold=self._pool_saturation_floor,
                title=f"Pool {name} at {saturation:.0%} saturation",
                detail=(
                    f"Pool '{name}' running {current}/{target} agents "
                    f"({saturation:.0%}); ≥{self._pool_saturation_floor:.0%} "
                    "threshold breached."
                ),
                related_pool=str(name),
            ))
        return out

    def _check_degradation(self) -> list[ThresholdAlert]:
        dm = getattr(self._runtime, "degradation_manager", None)
        if dm is None:
            return []
        try:
            status = dm.status()
        except Exception:
            return []
        level_str = getattr(getattr(status, "stress_level", None), "value", None)
        if not isinstance(level_str, str):
            return []
        # StressLevel ordering: NORMAL < ELEVATED < DEGRADED < CRITICAL.
        order = {"normal": 0, "elevated": 1, "degraded": 2, "critical": 3}
        floor = order.get(self._degradation_min_severity, 2)
        cur = order.get(level_str.lower(), 0)
        if cur < floor:
            return []
        dedup_key = f"degradation:{level_str.lower()}"
        if not self._should_fire(dedup_key):
            return []
        sev = "alert" if cur >= 3 else "advisory"
        shed_count = len(getattr(status, "shed_services", []) or [])
        return [ThresholdAlert(
            threshold_id=dedup_key,
            severity=sev,
            metric="degradation_tier",
            value=float(cur),
            threshold=float(floor),
            title=f"Degradation level {level_str}",
            detail=(
                f"DegradationManager reports stress_level={level_str} "
                f"with {shed_count} shed service(s)."
            ),
        )]

    def _check_attention_queue_depth(self) -> list[ThresholdAlert]:
        attn = getattr(self._runtime, "attention", None)
        if attn is None:
            return []
        depth_attr = getattr(attn, "queue_size", None)
        depth = int(depth_attr) if isinstance(depth_attr, int) else 0
        if depth < self._attention_queue_depth:
            return []
        dedup_key = "attention_queue_depth"
        if not self._should_fire(dedup_key):
            return []
        return [ThresholdAlert(
            threshold_id=dedup_key,
            severity="advisory",
            metric="attention_queue_depth",
            value=float(depth),
            threshold=float(self._attention_queue_depth),
            title=f"Attention queue depth {depth}",
            detail=(
                f"Attention queue at depth {depth}; threshold "
                f"{self._attention_queue_depth}. Backlog may indicate "
                "overload or stuck tasks."
            ),
        )]

    # -------------------------- helpers --------------------------

    def _should_fire(self, dedup_key: str) -> bool:
        now = time.time()
        last = self._recent.get(dedup_key)
        if last is not None and now - last < self._dedup_window:
            return False
        self._recent[dedup_key] = now
        # Prune entries older than 2x the dedup window.
        cutoff = now - self._dedup_window * 2
        self._recent = {k: v for k, v in self._recent.items() if v > cutoff}
        return True

    async def _deliver(self, ta: ThresholdAlert) -> None:
        wrr = getattr(self._runtime, "ward_room_router", None)
        if wrr is None:
            logger.debug(
                "AD-695: no ward_room_router; threshold alert %s not posted",
                ta.threshold_id,
            )
            return
        try:
            severity_enum = AlertSeverity(ta.severity)
        except ValueError:
            severity_enum = AlertSeverity.ADVISORY
        ba = BridgeAlert(
            id=str(uuid.uuid4()),
            severity=severity_enum,
            source="threshold_alerts",
            alert_type=ta.threshold_id,
            title=ta.title,
            detail=ta.detail,
            department=None,
            dedup_key=ta.threshold_id,
            related_pool=ta.related_pool,
        )
        await wrr.deliver_bridge_alert(ba)
```

---

## Section 2 — Pydantic config

Insert `ThresholdAlertConfig` adjacent to `ObservabilityBridgeConfig` in `src/probos/config.py` (after line 1303), and a corresponding field on `SystemConfig` adjacent to `observability_bridge` (after line 2161).

**SEARCH** (config.py around line 1298):

```python
class ObservabilityBridgeConfig(BaseModel):
    """AD-641a: Observability Bridge configuration."""

    enabled: bool = True
    publish_interval_seconds: float = 60.0
    system_channel: str = "system_observability"


class WardRoomHebbianConfig(BaseModel):
```

**REPLACE** with:

```python
class ObservabilityBridgeConfig(BaseModel):
    """AD-641a: Observability Bridge configuration."""

    enabled: bool = True
    publish_interval_seconds: float = 60.0
    system_channel: str = "system_observability"


class ThresholdAlertConfig(BaseModel):
    """AD-695: Threshold-driven bridge alerts.

    Default-False — opt-in until a node operator chooses to surface health
    breaches into the ward room. Replaces the AD-641a continuous-posting
    loop with on-breach-only notifications.
    """

    enabled: bool = False
    pool_saturation_floor: float = Field(default=0.9, ge=0.0, le=1.0)
    degradation_min_severity: str = "degraded"
    attention_queue_depth: int = Field(default=20, ge=0)
    dedup_window_seconds: float = Field(default=300.0, ge=1.0)


class WardRoomHebbianConfig(BaseModel):
```

**SEARCH** (config.py around line 2161):

```python
    observability_bridge: ObservabilityBridgeConfig = Field(default_factory=ObservabilityBridgeConfig)  # AD-641a
```

**REPLACE** with:

```python
    observability_bridge: ObservabilityBridgeConfig = Field(default_factory=ObservabilityBridgeConfig)  # AD-641a
    threshold_alerts: ThresholdAlertConfig = Field(default_factory=ThresholdAlertConfig)  # AD-695
```

---

## Section 3 — Wire ThresholdAlertService in finalize

Insert wiring in `src/probos/startup/finalize.py` immediately AFTER the AD-641a observability bridge block (after line 1354 `runtime.observability_bridge = None`).

**SEARCH** anchor (the closing `else:` of the AD-641a block, then the next block):

```python
        logger.info("AD-641a: ObservabilityBridge wired (channel=%s, interval=%.0fs)",
                    ob_cfg.system_channel, ob_cfg.publish_interval_seconds)
    else:
        runtime.observability_bridge = None

    # AD-641b: Ward Room Hebbian Router (router only; listener deferred to AD-641b-iv)
```

**REPLACE** with:

```python
        logger.info("AD-641a: ObservabilityBridge wired (channel=%s, interval=%.0fs)",
                    ob_cfg.system_channel, ob_cfg.publish_interval_seconds)
    else:
        runtime.observability_bridge = None

    # AD-695: Threshold Alert Service — replaces AD-641a continuous posting
    ta_cfg = getattr(getattr(runtime, "config", None), "threshold_alerts", None)
    if ta_cfg is not None and ta_cfg.enabled:
        from probos.cognitive.threshold_alerts import ThresholdAlertService
        runtime.threshold_alerts = ThresholdAlertService(
            runtime,
            pool_saturation_floor=ta_cfg.pool_saturation_floor,
            degradation_min_severity=ta_cfg.degradation_min_severity,
            attention_queue_depth=ta_cfg.attention_queue_depth,
            dedup_window_seconds=ta_cfg.dedup_window_seconds,
        )
        logger.info(
            "AD-695: ThresholdAlertService wired "
            "(pool>=%.0f%%, degradation>=%s, attention>=%d, dedup=%.0fs)",
            ta_cfg.pool_saturation_floor * 100,
            ta_cfg.degradation_min_severity,
            ta_cfg.attention_queue_depth,
            ta_cfg.dedup_window_seconds,
        )
    else:
        runtime.threshold_alerts = None

    # AD-641b: Ward Room Hebbian Router (router only; listener deferred to AD-641b-iv)
```

---

## Section 4 — Replace ObservabilityBridge `_publish_once` body

`_publish_once` at `src/probos/cognitive/observability/bridge.py:119` currently takes a snapshot and emits the `OBSERVABILITY_SNAPSHOT_PUBLISHED` event. AD-695 keeps the snapshot and the event, and adds a guarded call to the threshold service.

**SEARCH** (bridge.py around line 119–133):

```python
    async def _publish_once(self) -> None:
        snap = await self.take_snapshot()
        # BF-258: Ward Room posting disabled. AD-641a design review determined
        # continuous telemetry posting is architecturally wrong (telemetry is not
        # discourse). Crew queries system health via Oracle (AD-695).
        # take_snapshot() retained for future Oracle "health" tier integration.
        if self._emit_event is not None:
            self._emit_event(
                EventType.OBSERVABILITY_SNAPSHOT_PUBLISHED,
                {
                    "captured_at": snap.captured_at,
                    "pools": list(snap.pool_health.keys()),
                    "attention_count": len(snap.attention_priorities),
                },
            )
```

**REPLACE** with:

```python
    async def _publish_once(self) -> None:
        snap = await self.take_snapshot()
        # AD-695: Ward Room posting REMOVED (BF-258). The bridge is now a
        # cadence trigger for ThresholdAlertService — alerts post to the
        # ward room ONLY when metrics breach thresholds. Snapshot collection
        # retained for the Oracle "health" tier (AD-695) and event-log
        # subscribers.
        ta = getattr(self._runtime, "threshold_alerts", None)
        if ta is not None:
            try:
                await ta.check_and_alert()
            except Exception:
                logger.warning(
                    "AD-695: threshold_alerts.check_and_alert failed; will retry next cycle",
                    exc_info=True,
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
```

---

## Section 5 — Oracle Tier 7 "health"

### 5a. Append `"health"` to default tiers

**SEARCH** (oracle_service.py around line 187):

```python
        active_tiers = tiers or [
            "episodic", "records", "operational", "archive", "semantic", "graph",
        ]
```

**REPLACE** with:

```python
        active_tiers = tiers or [
            "episodic", "records", "operational", "archive", "semantic", "graph", "health",
        ]
```

### 5b. Dispatch slot

**SEARCH** (oracle_service.py — the post-graph `_expand_via_graph` block; insert dispatch BEFORE the expansion call):

```python
        # AD-688: Post-merge graph expansion — 1-hop enrichment of top-K
        # results from all tiers. Runs BEFORE the final sort/truncate so
        # expansion results compete on score in the merged ranking.
        try:
            expansion_results = await self._expand_via_graph(all_results, top_k=5)
            all_results.extend(expansion_results)
        except Exception:
            logger.debug("Oracle: graph expansion failed", exc_info=True)
```

**REPLACE** with:

```python
        # Tier 7: Ship Health (AD-695) — observable runtime telemetry
        # (vitals, pools, attention, degradation) as queryable OracleResults.
        if "health" in active_tiers:
            try:
                tier_results = await self._query_health(query_text, k=k_per_tier)
                all_results.extend(tier_results)
            except Exception:
                logger.debug("Oracle: Tier 7 (health) query failed", exc_info=True)

        # AD-688: Post-merge graph expansion — 1-hop enrichment of top-K
        # results from all tiers. Runs BEFORE the final sort/truncate so
        # expansion results compete on score in the merged ranking.
        try:
            expansion_results = await self._expand_via_graph(all_results, top_k=5)
            all_results.extend(expansion_results)
        except Exception:
            logger.debug("Oracle: graph expansion failed", exc_info=True)
```

### 5c. Add `attach_health_provider` setter + `_query_health` method

OracleService at HEAD reaches `runtime` only via injected providers, never directly. AD-695 mirrors that pattern: a `health_provider` is anything with these duck-typed accessors:

- `spawner.pools` (dict of pool objects exposing `current_size` / `target_size`)
- `attention.queue_size` and `attention.get_queue_snapshot()` (read-only)
- `degradation_manager.status()` (DegradationStatus with `.stress_level.value`, `.shed_services`)
- `observability_bridge` (optional; if present, `take_snapshot()` augments vitals)

The runtime itself satisfies this protocol — wiring passes `runtime` directly. Keeps the layer clean while letting tests inject a `SimpleNamespace` stub.

**Section 5c-i: ctor + attach setter.** SEARCH (oracle_service.py around lines 121–142):

```python
    def __init__(
        self,
        *,
        episodic_memory: Any = None,
        records_store: Any = None,
        knowledge_store: Any = None,
        archive_store: Any = None,  # AD-524
        trust_network: Any = None,
        hebbian_router: Any = None,
        expertise_directory: Any = None,
        semantic_layer: Any = None,  # AD-686 (Tier 5)
        knowledge_graph: Any = None,  # AD-688 (Tier 6)
    ) -> None:
        self._episodic_memory = episodic_memory
        self._records_store = records_store
        self._knowledge_store = knowledge_store
        self._archive_store = archive_store
        self._trust_network = trust_network
        self._hebbian_router = hebbian_router
        self._expertise_directory = expertise_directory
        self._semantic_layer = semantic_layer  # AD-686 (Tier 5)
        self._knowledge_graph = knowledge_graph  # AD-688 (Tier 6)
```

**REPLACE** with:

```python
    def __init__(
        self,
        *,
        episodic_memory: Any = None,
        records_store: Any = None,
        knowledge_store: Any = None,
        archive_store: Any = None,  # AD-524
        trust_network: Any = None,
        hebbian_router: Any = None,
        expertise_directory: Any = None,
        semantic_layer: Any = None,  # AD-686 (Tier 5)
        knowledge_graph: Any = None,  # AD-688 (Tier 6)
        health_provider: Any = None,  # AD-695 (Tier 7)
    ) -> None:
        self._episodic_memory = episodic_memory
        self._records_store = records_store
        self._knowledge_store = knowledge_store
        self._archive_store = archive_store
        self._trust_network = trust_network
        self._hebbian_router = hebbian_router
        self._expertise_directory = expertise_directory
        self._semantic_layer = semantic_layer  # AD-686 (Tier 5)
        self._knowledge_graph = knowledge_graph  # AD-688 (Tier 6)
        self._health_provider = health_provider  # AD-695 (Tier 7)
```

**Section 5c-ii: setter.** SEARCH (oracle_service.py — the existing `attach_knowledge_graph` method):

```python
    def attach_knowledge_graph(self, knowledge_graph: Any) -> None:
        """AD-688: Late-bind the KnowledgeEdgeStorage.

        Used by the runtime because `SQLiteKnowledgeEdgeStore` is constructed
        in the communication phase (after the cognitive phase that builds
        `OracleService`). Idempotent — last write wins. Mirrors
        `attach_semantic_layer` shape exactly.
        """
        self._knowledge_graph = knowledge_graph
```

**REPLACE** with:

```python
    def attach_knowledge_graph(self, knowledge_graph: Any) -> None:
        """AD-688: Late-bind the KnowledgeEdgeStorage.

        Used by the runtime because `SQLiteKnowledgeEdgeStore` is constructed
        in the communication phase (after the cognitive phase that builds
        `OracleService`). Idempotent — last write wins. Mirrors
        `attach_semantic_layer` shape exactly.
        """
        self._knowledge_graph = knowledge_graph

    def attach_health_provider(self, health_provider: Any) -> None:
        """AD-695: Late-bind the runtime health provider.

        Health provider is duck-typed against ``runtime``: must expose
        ``spawner.pools``, ``attention``, ``degradation_manager``, and
        optionally ``observability_bridge``. Used because spawner / attention /
        degradation manager are wired in the structural-services phase
        AFTER the cognitive phase that builds OracleService. Idempotent —
        last write wins.
        """
        self._health_provider = health_provider
```

**Section 5c-iii: `_query_health` method.** Insert AFTER `_query_graph` (the graph helper block ends; place new method before whatever is next — locate by searching for the closing `return results` of `_query_graph` and append the new method to the class). For a stable anchor, append AFTER the existing `_expand_via_graph` method (whichever comes last among graph helpers in the file at build time).

```python
    async def _query_health(
        self,
        query_text: str,
        *,
        k: int,
    ) -> list[OracleResult]:
        """AD-695: Tier 7 — runtime telemetry as queryable OracleResults.

        Reads the same surfaces the ObservabilityBridge collects (pool stats,
        attention queue, degradation status), plus an optional vitals_summary
        if observability_bridge is wired. Each metric becomes one OracleResult
        with score = simple keyword overlap against query_text. Returns at
        most ``k`` results, sorted by score desc.
        """
        provider = self._health_provider
        if provider is None:
            logger.debug("Oracle: Tier 7 (health) — no health_provider attached; returning []")
            return []

        query_tokens = {
            tok for tok in query_text.lower().replace("_", " ").split() if len(tok) >= 3
        }

        def _score(content: str) -> float:
            if not query_tokens:
                return 0.5  # uniform when query has no scoreable tokens
            content_tokens = {
                tok for tok in content.lower().replace("_", " ").split() if len(tok) >= 3
            }
            if not content_tokens:
                return 0.0
            overlap = len(query_tokens & content_tokens)
            return overlap / max(1, len(query_tokens))

        results: list[OracleResult] = []

        # Pool stats
        spawner = getattr(provider, "spawner", None)
        pools = getattr(spawner, "pools", None) if spawner is not None else None
        if isinstance(pools, dict):
            for name, pool in pools.items():
                current = getattr(pool, "current_size", 0) or 0
                target = getattr(pool, "target_size", 0) or 0
                content = (
                    f"pool {name} size={current}/{target}"
                )
                score = _score(content)
                if score > 0.0 or not query_tokens:
                    results.append(OracleResult(
                        source_tier="health",
                        content=content,
                        score=score,
                        metadata={"metric": "pool", "pool": str(name),
                                  "current_size": int(current),
                                  "target_size": int(target)},
                        provenance="[health: pool]",
                    ))

        # Attention queue
        attn = getattr(provider, "attention", None)
        if attn is not None:
            depth = int(getattr(attn, "queue_size", 0) or 0)
            content = f"attention queue depth={depth}"
            score = _score(content)
            if score > 0.0 or not query_tokens:
                results.append(OracleResult(
                    source_tier="health",
                    content=content,
                    score=score,
                    metadata={"metric": "attention", "queue_depth": depth},
                    provenance="[health: attention]",
                ))

        # Degradation
        dm = getattr(provider, "degradation_manager", None)
        if dm is not None:
            try:
                status = dm.status()
            except Exception:
                status = None
            if status is not None:
                level = getattr(getattr(status, "stress_level", None), "value", "unknown")
                shed = list(getattr(status, "shed_services", []) or [])
                content = (
                    f"degradation stress_level={level} shed_services={len(shed)}"
                )
                score = _score(content)
                if score > 0.0 or not query_tokens:
                    results.append(OracleResult(
                        source_tier="health",
                        content=content,
                        score=score,
                        metadata={"metric": "degradation",
                                  "stress_level": str(level),
                                  "shed_count": len(shed)},
                        provenance="[health: degradation]",
                    ))

        # Vitals (optional, via observability_bridge.take_snapshot)
        bridge = getattr(provider, "observability_bridge", None)
        if bridge is not None:
            try:
                snap = await bridge.take_snapshot()
            except Exception:
                snap = None
            vitals = dict(getattr(snap, "vitals_summary", {}) or {}) if snap else {}
            if vitals:
                content = "vitals " + " ".join(
                    f"{k_}={v_}" for k_, v_ in vitals.items()
                )
                score = _score(content)
                if score > 0.0 or not query_tokens:
                    results.append(OracleResult(
                        source_tier="health",
                        content=content,
                        score=score,
                        metadata={"metric": "vitals", **vitals},
                        provenance="[health: vitals]",
                    ))

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:k]
```

---

## Section 6 — Wire health provider in runtime

After `runtime.threshold_alerts` is wired in finalize, also stitch the OracleService health provider. Use the same finalize file: insert the stitch immediately AFTER the AD-695 ThresholdAlertService block (after the `runtime.threshold_alerts = None` else-branch).

**SEARCH** (finalize.py — the new block we added in Section 3, plus the next existing block):

```python
    else:
        runtime.threshold_alerts = None

    # AD-641b: Ward Room Hebbian Router (router only; listener deferred to AD-641b-iv)
```

**REPLACE** with:

```python
    else:
        runtime.threshold_alerts = None

    # AD-695: Stitch Tier 7 health provider onto Oracle. ``runtime`` itself
    # satisfies the duck-typed contract (spawner / attention / degradation_manager
    # / observability_bridge). Done here in finalize because OracleService is
    # built in the cognitive phase BEFORE attention / spawner / degradation_manager
    # are fully populated, so late-bind is required.
    oracle_for_health = getattr(runtime, "_oracle_service", None) or getattr(runtime, "oracle", None)
    if oracle_for_health is not None:
        try:
            oracle_for_health.attach_health_provider(runtime)
        except Exception:
            logger.warning(
                "AD-695: failed to attach health provider to OracleService; "
                "Tier 7 health queries will return [] until restart",
                exc_info=True,
            )

    # AD-641b: Ward Room Hebbian Router (router only; listener deferred to AD-641b-iv)
```

---

## Section 7 — Tests

Create `tests/test_ad695_ship_health_oracle.py` with **13 tests** (over the 12 floor by 1; drop targets if drift: #11 or #13).

Test list:

1. `test_oracle_default_active_tiers_includes_health` — instantiate `OracleService()` with no providers, call `.query("anything", tiers=None)` → no exceptions; verify `"health"` is the 7th element of the documented default list (pull constant from method or string-match in source if needed).
2. `test_query_health_returns_empty_when_no_provider` — Oracle with `health_provider=None` → `await svc._query_health("vitals", k=10) == []` and a debug log was emitted.
3. `test_query_health_pool_stats_happy_path` — `SimpleNamespace` provider with `spawner.pools={"medical": SimpleNamespace(current_size=2, target_size=4)}` → one OracleResult with `metric=pool`, `current_size=2`, `target_size=4`, `provenance="[health: pool]"`.
4. `test_query_health_attention_queue_metric` — provider with `attention=SimpleNamespace(queue_size=7, get_queue_snapshot=lambda: [])` → one OracleResult with `metric=attention`, `queue_depth=7`.
5. `test_query_health_degradation_metric` — provider with `degradation_manager` returning a fake `DegradationStatus` (`stress_level=SimpleNamespace(value="degraded")`, `shed_services=["x","y"]`) → result with `metric=degradation`, `stress_level=degraded`, `shed_count=2`.
6. `test_query_health_filters_by_query_keyword` — provider with all three sources but query="pool"; only pool results return non-zero score and rank above attention/degradation.
7. `test_query_health_truncates_to_k` — provider with 5 pools + attention + degradation; `k=2` → exactly 2 results.
8. `test_threshold_alert_config_defaults` — `ThresholdAlertConfig()` → `enabled is False`, `pool_saturation_floor==0.9`, `attention_queue_depth==20`, `dedup_window_seconds==300.0`, `degradation_min_severity=="degraded"`.
9. `test_check_and_alert_pool_saturation_breach_fires` — runtime stub with one pool at 9/10 saturation → returns one `ThresholdAlert` with `metric=="pool_saturation"`, `value==0.9`, `related_pool=="medical"`. `ward_room_router.deliver_bridge_alert` was awaited once with a `BridgeAlert` whose `dedup_key=="pool_saturation:medical"`.
10. `test_check_and_alert_degradation_escalation_fires` — stub `degradation_manager.status()` returns `stress_level.value="critical"` → fires one alert with `severity=="alert"`, `metric=="degradation_tier"`.
11. `test_check_and_alert_attention_queue_depth_fires` — stub `attention.queue_size=25` → fires one alert with `metric=="attention_queue_depth"`, `value==25.0`.
12. `test_check_and_alert_dedup_prevents_repost` — same breaching pool fires once on first call, then `await svc.check_and_alert()` immediately again → second call returns `[]` and `deliver_bridge_alert` NOT awaited a second time. Then advance the dedup window (via monkeypatching `time.time`) and verify it fires again.
13. `test_check_and_alert_no_breach_returns_empty` — runtime stub with healthy pools (5/10), `attention.queue_size=0`, `stress_level.value="normal"` → returns `[]`, `deliver_bridge_alert` not awaited.

**Bridge-loop replacement assertion**: covered by inspection inside test #9/#10 (the call goes through `_publish_once` indirectly; we test the unit `check_and_alert` directly — the `_publish_once` change is small and cosmetic). If reviewer pushes for direct loop-rewiring proof, add test #14: `test_publish_once_calls_threshold_alerts_when_wired` — stub `runtime.threshold_alerts.check_and_alert = AsyncMock()`, call `bridge._publish_once()` once, assert mock awaited.

**Bridge alert format assertion**: covered by tests #9/#10/#11 — each asserts the BridgeAlert handed to `deliver_bridge_alert` includes severity + metric (in detail) + value (in detail). Captain-readable string format is fixture-validated.

Test fixtures: prefer `SimpleNamespace` for stubs (mirrors AD-688 / AD-635 patterns). Use `AsyncMock()` for `ward_room_router` and `observability_bridge.take_snapshot`.

---

## What This Does NOT Change

- **HXI / dashboard integration** of the `health` tier — separate AD (`AD-695b` if data warrants).
- **Historical retention of alerts** beyond the dedup ring — alerts are not persisted to ship's records or event log beyond the `bridge_alert` event row that `deliver_bridge_alert` already writes (existing AD-410 behaviour, untouched).
- **Per-agent health querying** — Oracle context is per-query; agent-scoped vitals deferred.
- **Active shedding hooks** — still AD-459b / AD-396.
- **AD-466 infrastructure restructuring** — package layout untouched.
- **AD-466c full extension scope** — only the threshold-alert + Oracle-tier slices land here. Audit log, retention, configurable thresholds-per-pool deferred.
- **Existing `BridgeAlertService`** — untouched. ThresholdAlertService **constructs** `BridgeAlert` directly; it does not call `BridgeAlertService.check_*`.
- **EventTypes** — no new enum values.

---

## Tracking

- **PROGRESS.md** — prepend AD-695 entry to Era V section with one-paragraph summary (Oracle Tier 7 + ThresholdAlertService + bridge loop replacement; replaces BF-258 dormancy with active threshold checks). Update test count (+13).
- **docs/development/roadmap.md** — flip AD-695 status from "Scoped" to "Complete".
- **DECISIONS.md** — prepend a single AD-695 entry under Era V.
- **GH issue #389** — close (BLOCKED by EMU 403; user closes manually post-build, same as Waves 31–42).

---

## Acceptance Criteria

1. All 13 new tests in `tests/test_ad695_ship_health_oracle.py` pass.
2. Full gate (`pytest tests/ -q -n 8 --dist=loadfile`) passes; test count = baseline + 13 (one known git-debounce xdist flake permitted, same Wave 8/14/15/16/19/22/27/30/31/32/33/37/41/42 environmental pattern).
3. No deletions in any file > 200 lines (pre-commit deletion sanity).
4. `runtime.threshold_alerts` is `None` by default (config disabled). No behavioural change for existing test suite.
5. `runtime.oracle.attach_health_provider(runtime)` is called from finalize.
6. `_publish_once` no longer references `create_post`. Confirms BF-258 is permanently replaced.
7. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

**Single commit**: `Wave 43 build: AD-695 v1 Ship Health Oracle Tier + Threshold Bridge Alerts (#389)`. Push to `origin/main`.
