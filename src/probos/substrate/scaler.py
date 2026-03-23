"""PoolScaler — monitors demand and dynamically adjusts pool sizes.

Runs a background loop that:
1. Reads per-pool demand from IntentBus
2. Computes demand-to-capacity ratio per pool
3. Scales up pools that are consistently over-demanded
4. Scales down pools that are consistently under-demanded
5. Respects min_pool_size, max_pool_size, and cooldown periods
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, TYPE_CHECKING

from probos.config import PoolConfig, ScalingConfig

if TYPE_CHECKING:
    from probos.mesh.intent import IntentBus  # AD-399: allowed edge — TYPE_CHECKING + DI
    from probos.substrate.pool import ResourcePool

logger = logging.getLogger(__name__)


class PoolScaler:
    """Monitors demand and dynamically adjusts pool sizes."""

    def __init__(
        self,
        pools: dict[str, ResourcePool],
        intent_bus: IntentBus,
        pool_config: PoolConfig,
        scaling_config: ScalingConfig,
        pool_intent_map: dict[str, list[str]],
        excluded_pools: set[str] | None = None,
        trust_network: Any = None,
        consensus_pools: set[str] | None = None,
        consensus_min_agents: int = 3,
    ) -> None:
        self.pools = pools
        self.intent_bus = intent_bus
        self.pool_config = pool_config
        self.scaling_config = scaling_config
        self.pool_intent_map = pool_intent_map
        self.excluded_pools = excluded_pools or set()
        self.trust_network = trust_network
        self.consensus_pools = consensus_pools or set()
        self.consensus_min_agents = consensus_min_agents

        self._last_scale_time: dict[str, float] = {}  # pool_name -> monotonic time
        self._scaling_events: list[dict[str, Any]] = []
        self._task: asyncio.Task[None] | None = None
        self._stopped = False

    async def start(self) -> None:
        """Start the background scaling loop."""
        self._stopped = False
        self._task = asyncio.create_task(
            self._scaling_loop(), name="pool-scaler"
        )
        logger.debug("PoolScaler started")

    async def stop(self) -> None:
        """Stop the scaling loop."""
        self._stopped = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.debug("PoolScaler stopped")

    async def request_surge(self, pool_name: str, extra: int = 1) -> bool:
        """Request temporary scale-up for escalation retries.

        Respects max_pool_size. Returns True if surge was granted.
        Bypasses cooldown (surges are emergency requests).
        Records a scaling event with reason='surge'.
        """
        pool = self.pools.get(pool_name)
        if pool is None:
            return False

        granted = False
        for _ in range(extra):
            new_id = await pool.add_agent()
            if new_id is None:
                break
            pool.target_size = pool.current_size
            granted = True
            self._record_event(pool_name, "up", "surge")
            logger.debug(
                "Surge scale-up: %s -> %d agents", pool_name, pool.current_size
            )

        return granted

    async def scale_down_idle(self) -> None:
        """Scale each non-excluded pool down by one step, respecting min_pool_size.

        Called during dream cycles (system has been idle).
        Respects cooldown. Reason='idle'.
        """
        for pool_name, pool in self.pools.items():
            if pool_name in self.excluded_pools:
                continue
            if pool.min_size == pool.max_size:
                continue
            if not self._cooldown_ok(pool_name):
                continue
            # Consensus-requiring pools must not shrink below min_votes
            if pool_name in self.consensus_pools:
                if pool.current_size <= self.consensus_min_agents:
                    continue
            removed = await pool.remove_agent(trust_network=self.trust_network)
            if removed:
                pool.target_size = pool.current_size
                self._last_scale_time[pool_name] = time.monotonic()
                self._record_event(pool_name, "down", "idle")
                logger.debug(
                    "Idle scale-down: %s -> %d agents", pool_name, pool.current_size
                )

    async def _scaling_loop(self) -> None:
        """Periodic evaluation loop (runs every observation_window_seconds / 2)."""
        interval = self.scaling_config.observation_window_seconds / 2
        while not self._stopped:
            try:
                await asyncio.sleep(interval)
                await self._evaluate_and_scale()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Scaler loop error: %s", e)

    async def _evaluate_and_scale(self) -> None:
        """Core scaling logic for one evaluation cycle."""
        per_pool = self.intent_bus.per_pool_demand(self.pool_intent_map)

        for pool_name, pool in self.pools.items():
            if pool_name in self.excluded_pools:
                continue
            if pool.min_size == pool.max_size:
                continue

            ratio = self._compute_demand_ratio(pool_name, pool)

            if ratio > self.scaling_config.scale_up_threshold:
                await self._scale_up(pool, reason="demand")
            elif ratio < self.scaling_config.scale_down_threshold:
                await self._scale_down(pool, reason="low_demand")

    def _compute_demand_ratio(self, pool_name: str, pool: ResourcePool) -> float:
        """Compute demand-to-capacity ratio for a pool.

        demand_ratio = broadcasts targeting this pool in window / pool.current_size
        """
        per_pool = self.intent_bus.per_pool_demand(self.pool_intent_map)
        broadcasts = per_pool.get(pool_name, 0)
        if pool.current_size == 0:
            return float(broadcasts) if broadcasts > 0 else 0.0
        return broadcasts / pool.current_size

    async def _scale_up(self, pool: ResourcePool, reason: str = "demand") -> bool:
        """Add one agent to pool. Returns True if successful."""
        if not self._cooldown_ok(pool.name):
            return False
        new_id = await pool.add_agent()
        if new_id is None:
            return False
        pool.target_size = pool.current_size
        self._last_scale_time[pool.name] = time.monotonic()
        self._record_event(pool.name, "up", reason)
        logger.debug(
            "Scale up: %s -> %d agents (reason=%s)",
            pool.name, pool.current_size, reason,
        )
        return True

    async def _scale_down(self, pool: ResourcePool, reason: str = "low_demand") -> bool:
        """Remove one agent from pool. Returns True if successful."""
        if not self._cooldown_ok(pool.name):
            return False
        # Consensus-requiring pools must not shrink below min_votes
        if pool.name in self.consensus_pools:
            if pool.current_size <= self.consensus_min_agents:
                return False
        removed = await pool.remove_agent(trust_network=self.trust_network)
        if removed is None:
            return False
        pool.target_size = pool.current_size
        self._last_scale_time[pool.name] = time.monotonic()
        self._record_event(pool.name, "down", reason)
        logger.debug(
            "Scale down: %s -> %d agents (reason=%s)",
            pool.name, pool.current_size, reason,
        )
        return True

    def _cooldown_ok(self, pool_name: str) -> bool:
        """Check if enough time has passed since the last scaling event for this pool."""
        last = self._last_scale_time.get(pool_name)
        if last is None:
            return True
        elapsed = time.monotonic() - last
        return elapsed >= self.scaling_config.cooldown_seconds

    def _record_event(self, pool_name: str, direction: str, reason: str) -> None:
        """Record a scaling event."""
        self._scaling_events.append({
            "pool": pool_name,
            "direction": direction,
            "reason": reason,
            "time": time.monotonic(),
            "pool_size": self.pools[pool_name].current_size if pool_name in self.pools else 0,
        })

    def scaling_status(self) -> dict[str, Any]:
        """Return current scaling state for each pool."""
        result: dict[str, Any] = {}
        for pool_name, pool in self.pools.items():
            ratio = self._compute_demand_ratio(pool_name, pool)
            last_event = None
            for evt in reversed(self._scaling_events):
                if evt["pool"] == pool_name:
                    last_event = evt
                    break

            cooldown_remaining = 0.0
            last_time = self._last_scale_time.get(pool_name)
            if last_time is not None:
                remaining = self.scaling_config.cooldown_seconds - (time.monotonic() - last_time)
                cooldown_remaining = max(0.0, remaining)

            result[pool_name] = {
                "current_size": pool.current_size,
                "min_size": pool.min_size,
                "max_size": pool.max_size,
                "target_size": pool.target_size,
                "demand_ratio": round(ratio, 3),
                "excluded": pool_name in self.excluded_pools,
                "last_event": {
                    "direction": last_event["direction"],
                    "reason": last_event["reason"],
                } if last_event else None,
                "cooldown_remaining": round(cooldown_remaining, 1),
            }
        return result
