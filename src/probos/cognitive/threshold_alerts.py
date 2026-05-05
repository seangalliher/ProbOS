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
                    f"({saturation:.0%}); >={self._pool_saturation_floor:.0%} "
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
