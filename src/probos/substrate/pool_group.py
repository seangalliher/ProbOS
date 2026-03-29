"""PoolGroup — logical grouping of related resource pools (AD-291).

A thin, read-only abstraction that groups pools into named crew teams.
No lifecycle management — purely organizational metadata for status,
scaling exclusions, and HXI display.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from probos.substrate.pool import ResourcePool


@dataclass
class PoolGroup:
    """A logical grouping of related resource pools (a crew team)."""

    name: str
    display_name: str
    pool_names: set[str] = field(default_factory=set)
    exclude_from_scaler: bool = False


class PoolGroupRegistry:
    """Manages all pool groups with reverse-index lookup."""

    def __init__(self) -> None:
        self._groups: dict[str, PoolGroup] = {}
        self._pool_to_group: dict[str, str] = {}

    def register(self, group: PoolGroup) -> None:
        """Register a pool group and rebuild the reverse index for it."""
        self._groups[group.name] = group
        for pool_name in group.pool_names:
            self._pool_to_group[pool_name] = group.name

    def get_group(self, name: str) -> PoolGroup | None:
        """Get a group by name."""
        return self._groups.get(name)

    def group_for_pool(self, pool_name: str) -> str | None:
        """Get the group name for a given pool, or None if ungrouped."""
        return self._pool_to_group.get(pool_name)

    # ------------------------------------------------------------------
    # AD-514: Public API
    # ------------------------------------------------------------------

    def get_group_for_pool(self, pool_name: str) -> str | None:
        """Return the group name for a given pool, or None."""
        return self._pool_to_group.get(pool_name)

    def excluded_pools(self) -> set[str]:
        """Return the union of all pool names in groups with exclude_from_scaler=True."""
        result: set[str] = set()
        for group in self._groups.values():
            if group.exclude_from_scaler:
                result.update(group.pool_names)
        return result

    def all_groups(self) -> list[PoolGroup]:
        """Return all registered groups, sorted by name."""
        return sorted(self._groups.values(), key=lambda g: g.name)

    def group_health(
        self, group_name: str, pools: dict[str, ResourcePool]
    ) -> dict[str, Any]:
        """Aggregate health across all pools in a group."""
        group = self._groups.get(group_name)
        if not group:
            return {}

        total_agents = 0
        healthy_agents = 0
        pool_details: dict[str, dict[str, Any]] = {}

        for pname in sorted(group.pool_names):
            pool = pools.get(pname)
            if pool is None:
                continue
            info = pool.info()
            current = info.get("current_size", 0)
            target = info.get("target_size", 0)
            total_agents += target
            healthy_agents += current
            pool_details[pname] = {
                "current_size": current,
                "target_size": target,
                "agent_type": info.get("agent_type", ""),
            }

        return {
            "name": group.name,
            "display_name": group.display_name,
            "total_agents": total_agents,
            "healthy_agents": healthy_agents,
            "pools": pool_details,
            "health_ratio": healthy_agents / total_agents if total_agents > 0 else 1.0,
        }

    def status(self, pools: dict[str, ResourcePool]) -> dict[str, Any]:
        """Return status for all groups. Used by runtime.status()."""
        return {
            group.name: self.group_health(group.name, pools)
            for group in self.all_groups()
        }
