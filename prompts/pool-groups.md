# AD-291: Pool Groups — Crew Team Abstraction

## Objective

Add a lightweight `PoolGroup` abstraction that groups related pools into named teams. This makes the starship crew structure a first-class runtime concept without changing how `ResourcePool` works internally. Each pool still holds agents of one type with its own lifecycle — the group is purely organizational.

Currently pools are a flat `dict[str, ResourcePool]` with informal grouping via naming conventions (`medical_*`). This build formalizes that into a `PoolGroup` that surfaces through status, scaling, and HXI.

## Architecture

```
PoolGroup("medical")
    ├→ medical_vitals       (VitalsMonitorAgent × 1)
    ├→ medical_diagnostician (DiagnosticianAgent × 1)
    ├→ medical_surgeon       (SurgeonAgent × 1)
    ├→ medical_pharmacist    (PharmacistAgent × 1)
    └→ medical_pathologist   (PathologistAgent × 1)

PoolGroup("core")
    ├→ system               (SystemHeartbeatAgent × 2)
    ├→ filesystem           (FileReaderAgent × 3)
    ├→ filesystem_writers   (FileWriterAgent × 3)
    ├→ directory            (DirectoryListAgent × 3)
    ├→ search               (FileSearchAgent × 3)
    ├→ shell                (ShellCommandAgent × 3)
    ├→ http                 (HttpFetchAgent × 3)
    └→ introspect           (IntrospectionAgent × 3)

PoolGroup("bundled")
    ├→ web_search, page_reader, weather, news, translator
    ├→ summarizer, calculator, todo_manager, note_taker
    └→ scheduler

PoolGroup("consensus")
    └→ quorum               (RedTeamAgent — special, spawned outside pool system)

PoolGroup("self_mod")
    ├→ skills               (SkillBasedAgent)
    └→ system_qa            (SystemQAAgent)
```

## Files to Create

### `src/probos/substrate/pool_group.py`

**Class:** `PoolGroup`

A thin, read-only grouping of related pools. No lifecycle management — just organizational metadata.

```python
@dataclass
class PoolGroup:
    """A logical grouping of related resource pools (a crew team)."""
    name: str                    # e.g., "medical", "core", "bundled"
    display_name: str            # e.g., "Medical", "Core Systems", "Bundled Agents"
    pool_names: set[str]         # pool names belonging to this group
    exclude_from_scaler: bool = False  # if True, all pools in group are excluded from scaling
```

**Class:** `PoolGroupRegistry`

Manages all pool groups. Stored on the runtime.

```python
class PoolGroupRegistry:
    def __init__(self) -> None:
        self._groups: dict[str, PoolGroup] = {}
        self._pool_to_group: dict[str, str] = {}  # reverse index: pool_name → group_name

    def register(self, group: PoolGroup) -> None:
        """Register a pool group. Builds reverse index."""
        self._groups[group.name] = group
        for pool_name in group.pool_names:
            self._pool_to_group[pool_name] = group.name

    def get_group(self, name: str) -> PoolGroup | None:
        """Get a group by name."""

    def group_for_pool(self, pool_name: str) -> str | None:
        """Get the group name for a given pool, or None if ungrouped."""

    def excluded_pools(self) -> set[str]:
        """Return the union of all pool names in groups with exclude_from_scaler=True."""

    def all_groups(self) -> list[PoolGroup]:
        """Return all registered groups, sorted by name."""

    def group_health(self, group_name: str, pools: dict[str, ResourcePool]) -> dict[str, Any]:
        """Aggregate health across all pools in a group.
        Returns:
        {
            "name": str,
            "display_name": str,
            "total_agents": int,
            "healthy_agents": int,
            "pools": {pool_name: {"current_size": int, "target_size": int, "agent_type": str}},
            "health_ratio": float,  # healthy / total
        }
        """

    def status(self, pools: dict[str, ResourcePool]) -> dict[str, Any]:
        """Return status for all groups. Used by runtime.status()."""
```

**Implementation notes:**
- Pure data structure — no async, no lifecycle, no side effects
- The reverse index (`_pool_to_group`) is rebuilt on each `register()` call
- Pools not assigned to any group are implicitly in an "ungrouped" category for display purposes

## Files to Modify

### `src/probos/runtime.py`

**Changes:**

1. Import `PoolGroup`, `PoolGroupRegistry` from `probos.substrate.pool_group`

2. In `__init__()`, create `self.pool_groups = PoolGroupRegistry()`

3. In `start()`, after all pools are created, register groups:

```python
# Register pool groups (crew teams)
from probos.substrate.pool_group import PoolGroup

self.pool_groups.register(PoolGroup(
    name="core",
    display_name="Core Systems",
    pool_names={"system", "filesystem", "filesystem_writers", "directory", "search", "shell", "http", "introspect"},
    exclude_from_scaler=True,
))

self.pool_groups.register(PoolGroup(
    name="bundled",
    display_name="Bundled Agents",
    pool_names={"web_search", "page_reader", "weather", "news", "translator", "summarizer", "calculator", "todo_manager", "note_taker", "scheduler"},
))

if self.config.medical.enabled:
    self.pool_groups.register(PoolGroup(
        name="medical",
        display_name="Medical",
        pool_names={"medical_vitals", "medical_diagnostician", "medical_surgeon", "medical_pharmacist", "medical_pathologist"},
        exclude_from_scaler=True,
    ))

if self.config.self_mod.enabled:
    self.pool_groups.register(PoolGroup(
        name="self_mod",
        display_name="Self-Modification",
        pool_names={"skills", "system_qa"} if self.config.qa.enabled else {"skills"},
        exclude_from_scaler=True,
    ))
```

4. In the PoolScaler construction (currently line ~530), replace the hardcoded `excluded_pools` set with:

```python
excluded_pools=self.pool_groups.excluded_pools(),
```

This replaces:
```python
excluded_pools={"system", "system_qa", "medical_vitals", "medical_diagnostician", "medical_surgeon", "medical_pharmacist", "medical_pathologist"},
```

5. In `status()`, add `"pool_groups"` to the returned dict:

```python
"pool_groups": self.pool_groups.status(self.pools),
```

### `src/probos/experience/panels.py`

**Changes to `render_status_panel()`:**

Replace the flat pool listing (lines 80-86) with group-organized display:

```python
# Pool Groups
pool_groups = status.get("pool_groups", {})
pools = status.get("pools", {})

if pool_groups:
    lines.append("")
    lines.append("[bold]Crew Teams[/bold]")
    for group_name, group_info in sorted(pool_groups.items()):
        healthy = group_info.get("healthy_agents", 0)
        total = group_info.get("total_agents", 0)
        lines.append(f"  [bold]{group_info.get('display_name', group_name)}[/bold]: {healthy}/{total} agents")
        for pname, pinfo in group_info.get("pools", {}).items():
            lines.append(f"    {pname}: {pinfo.get('current_size', '?')}/{pinfo.get('target_size', '?')} ({pinfo.get('agent_type', '?')})")

# Ungrouped pools (if any exist that aren't in a group)
grouped_pool_names = set()
for g in pool_groups.values():
    grouped_pool_names.update(g.get("pools", {}).keys())
ungrouped = {k: v for k, v in pools.items() if k not in grouped_pool_names}
if ungrouped:
    lines.append("")
    lines.append("[bold]Other Pools[/bold]")
    for name, info in ungrouped.items():
        lines.append(f"  {name}: {info.get('current_size', '?')}/{info.get('target_size', '?')} ({info.get('agent_type', '?')})")
```

### `ui/src/store/types.ts`

Add `PoolGroupInfo` interface:

```typescript
export interface PoolGroupInfo {
  name: string;
  displayName: string;
  totalAgents: number;
  healthyAgents: number;
  healthRatio: number;
  pools: Record<string, PoolInfo>;
}
```

Add `poolGroups` to `StateSnapshot`:

```typescript
export interface StateSnapshot {
  // ... existing fields
  poolGroups?: Record<string, PoolGroupInfo>;
}
```

### `ui/src/store/useStore.ts`

In `computeLayout()`, use pool group information to improve agent clustering. Currently agents are sorted by pool name within each tier — enhance to sort by group first, then pool within group. This naturally clusters all medical agents together, all bundled agents together, etc.

```typescript
const byGroupThenPool = (a: string, b: string) => {
  const agentA = agents.get(a);
  const agentB = agents.get(b);
  const groupA = poolToGroup[agentA?.pool || ''] || 'zzz';
  const groupB = poolToGroup[agentB?.pool || ''] || 'zzz';
  if (groupA !== groupB) return groupA.localeCompare(groupB);
  return (agentA?.pool || '').localeCompare(agentB?.pool || '');
};
```

The `poolToGroup` map should be derived from `stateSnapshot.poolGroups` when the snapshot arrives.

### `ui/src/canvas/scene.ts`

Add pool tint colors for the new medical pools. Currently the `POOL_TINT_HEXES` map doesn't include medical pools. Add:

```typescript
medical_vitals: '#c06060',
medical_diagnostician: '#b06870',
medical_surgeon: '#a07078',
medical_pharmacist: '#907880',
medical_pathologist: '#808088',
```

Use a shared tint family (warm reds/pinks) so medical agents are visually identifiable as a team on the canvas.

### `src/probos/api.py`

In the WebSocket `state_snapshot` event, include `pool_groups` data from `runtime.status()`. This already happens implicitly if `runtime.status()` includes the field — verify that the snapshot builder uses the full status dict.

## Testing

Create `tests/test_pool_groups.py`:

### PoolGroup Tests
1. `test_pool_group_creation` — create a PoolGroup, verify fields
2. `test_pool_group_registry_register` — register a group, verify retrieval
3. `test_pool_group_registry_reverse_index` — register group, verify `group_for_pool()` returns correct group
4. `test_pool_group_registry_excluded_pools` — register groups with `exclude_from_scaler=True`, verify `excluded_pools()` returns union
5. `test_pool_group_registry_excluded_pools_mixed` — mix of excluded and non-excluded groups, verify only excluded pools returned
6. `test_pool_group_registry_all_groups` — register multiple groups, verify `all_groups()` returns sorted
7. `test_pool_group_health` — mock pools with agents, verify `group_health()` aggregation
8. `test_pool_group_status` — verify `status()` returns all group summaries
9. `test_ungrouped_pool` — pool not in any group, `group_for_pool()` returns None

### Integration Tests
10. `test_runtime_pool_groups_registered` — boot runtime, verify `pool_groups` has expected groups
11. `test_scaler_excluded_from_groups` — boot runtime, verify PoolScaler exclusions match `pool_groups.excluded_pools()`
12. `test_status_includes_pool_groups` — call `runtime.status()`, verify `"pool_groups"` key present with correct structure
13. `test_status_panel_renders_groups` — call `render_status_panel()` with group data, verify "Crew Teams" heading appears

## Constraints

- `PoolGroup` is read-only after creation — no dynamic add/remove of pools from groups at runtime
- `PoolGroupRegistry` is not persisted — rebuilt at boot from the pool registration code
- Pools can belong to at most one group (enforced by reverse index overwrite — last registration wins)
- Ungrouped pools still work exactly as before — grouping is purely additive
- No changes to `ResourcePool` internals — groups are an overlay, not a modification
- The HXI changes are visual-only — no new WebSocket events needed, just parse the existing snapshot data differently

## Success Criteria

- `PoolGroupRegistry` correctly aggregates health across grouped pools
- `excluded_pools()` replaces the hardcoded set in PoolScaler construction
- `/status` shows pools organized under "Crew Teams" headings instead of a flat list
- HXI canvas clusters agents by group (medical agents near each other, bundled near each other)
- Medical pool tints are visible and cohesive on the canvas
- All 13 tests pass
- All existing tests still pass — no regressions
- Adding a future crew team (e.g., Engineering) requires only: create pools + register one `PoolGroup`
