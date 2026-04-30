# AD-447: Phase Gates for PoolGroup

**Status:** Ready for builder
**Dependencies:** AD-438 (Ontology-Based Task Routing)
**Estimated tests:** ~8

---

## Problem

`PoolGroupRegistry` (`substrate/pool_group.py`) tracks logical groupings
of pools (core, medical, security, etc.) but has no startup ordering
constraints. All pool groups are registered in `fleet_organization.py`
and pools are started in an arbitrary order.

Some pool groups should start before others — core infrastructure pools
must be healthy before department-specific crews can function (they need
the filesystem, search, and intent bus). Currently, if a department pool
starts before its dependencies are ready, agents may fail on first action.

AD-447 adds phase gates to PoolGroupRegistry, allowing startup ordering
by phase level. Each pool group is assigned a phase (1-4), and groups
in later phases wait for earlier phases to complete.

## Fix

### Section 1: Add `startup_phase` to PoolGroup

**File:** `src/probos/substrate/pool_group.py`

SEARCH:
```python
@dataclass
class PoolGroup:
    """A logical grouping of related resource pools (a crew team)."""

    name: str
    display_name: str
    pool_names: set[str] = field(default_factory=set)
    exclude_from_scaler: bool = False
```

REPLACE:
```python
@dataclass
class PoolGroup:
    """A logical grouping of related resource pools (a crew team)."""

    name: str
    display_name: str
    pool_names: set[str] = field(default_factory=set)
    exclude_from_scaler: bool = False
    startup_phase: int = 1  # AD-447: 1=infrastructure, 2=department, 3=specialist, 4=utility
```

### Section 2: Add phase gate methods to PoolGroupRegistry

**File:** `src/probos/substrate/pool_group.py`

Add after the existing `status()` method (line 109):

```python
    # ------------------------------------------------------------------
    # AD-447: Phase Gates
    # ------------------------------------------------------------------

    def groups_by_phase(self) -> dict[int, list[PoolGroup]]:
        """Return groups organized by startup phase (AD-447).

        Phase 1: Infrastructure (core systems, always first)
        Phase 2: Department crews (security, engineering, medical, etc.)
        Phase 3: Specialist pools (self-mod, science specialists)
        Phase 4: Utility and optional pools
        """
        phases: dict[int, list[PoolGroup]] = {}
        for group in self.all_groups():
            phase = group.startup_phase
            if phase not in phases:
                phases[phase] = []
            phases[phase].append(group)
        return dict(sorted(phases.items()))

    def get_phase_pools(self, phase: int) -> set[str]:
        """Return all pool names belonging to groups in the given phase."""
        result: set[str] = set()
        for group in self._groups.values():
            if group.startup_phase == phase:
                result.update(group.pool_names)
        return result

    def max_phase(self) -> int:
        """Return the highest phase number across all groups."""
        if not self._groups:
            return 0
        return max(g.startup_phase for g in self._groups.values())

    def phase_summary(self) -> dict[str, Any]:
        """Return a summary of phase assignments for diagnostics."""
        phases = self.groups_by_phase()
        return {
            f"phase_{phase}": {
                "groups": [g.name for g in groups],
                "pool_count": sum(len(g.pool_names) for g in groups),
            }
            for phase, groups in phases.items()
        }
```

### Section 3: Assign phases to existing pool groups

**File:** `src/probos/startup/fleet_organization.py`

Update each `PoolGroup(...)` registration to include `startup_phase`:

**Core systems — Phase 1:**

SEARCH:
```python
    pool_groups.register(PoolGroup(
        name="core",
        display_name="Core Systems",
        pool_names={"system", "filesystem", "filesystem_writers", "directory", "search", "shell", "http", "introspect", "medical_vitals", "red_team", "system_qa"},
        exclude_from_scaler=True,
    ))
```

REPLACE:
```python
    pool_groups.register(PoolGroup(
        name="core",
        display_name="Core Systems",
        pool_names={"system", "filesystem", "filesystem_writers", "directory", "search", "shell", "http", "introspect", "medical_vitals", "red_team", "system_qa"},
        exclude_from_scaler=True,
        startup_phase=1,  # AD-447: infrastructure first
    ))
```

**Bridge — Phase 1:**

SEARCH:
```python
    pool_groups.register(PoolGroup(
        name="bridge",
        display_name="Bridge",
        pool_names={"counselor"},
        exclude_from_scaler=True,
    ))
```

REPLACE:
```python
    pool_groups.register(PoolGroup(
        name="bridge",
        display_name="Bridge",
        pool_names={"counselor"},
        exclude_from_scaler=True,
        startup_phase=1,  # AD-447: bridge is infrastructure
    ))
```

**Department crews — Phase 2 (security, engineering, operations, medical):**

Add `startup_phase=2` to these four registrations:
- `security` pool group
- `engineering` pool group
- `operations` pool group
- `medical` pool group

**Science and self-mod — Phase 3:**

Add `startup_phase=3` to:
- `science` pool group
- `self_mod` pool group

**Utility — Phase 4:**

Add `startup_phase=4` to:
- `utility` pool group

## Tests

**File:** `tests/test_ad447_phase_gates_pool_group.py`

8 tests:

1. `test_pool_group_startup_phase_default` — create `PoolGroup()`, verify
   `startup_phase == 1` (default)
2. `test_pool_group_custom_phase` — create with `startup_phase=3`, verify value
3. `test_groups_by_phase` — register groups with phases 1, 2, 3, verify
   `groups_by_phase()` returns sorted dict
4. `test_get_phase_pools` — register 2 groups in phase 2, verify
   `get_phase_pools(2)` returns union of pool names
5. `test_max_phase` — register groups with phases 1-4, verify `max_phase() == 4`
6. `test_max_phase_empty` — empty registry, verify `max_phase() == 0`
7. `test_phase_summary` — register groups, verify `phase_summary()` structure
   includes group names and pool counts per phase
8. `test_core_is_phase_1` — integration test: import `fleet_organization`,
   verify core and bridge groups are phase 1 (use mock runtime/pools)

## What This Does NOT Change

- `PoolGroupRegistry.register()` unchanged — phase is just a new field on PoolGroup
- `excluded_pools()` unchanged
- `group_health()` / `status()` unchanged
- Pool startup ordering is NOT enforced by this AD — phase gates provide
  the metadata, but actual startup sequencing requires caller changes (future AD)
- `ResourcePool.start()` unchanged
- Does NOT add inter-phase health checks
- Does NOT add phase gate events

## Tracking

- `PROGRESS.md`: Add AD-447 as COMPLETE
- `docs/development/roadmap.md`: Update AD-447 status

## Acceptance Criteria

- `PoolGroup` has `startup_phase` field (default 1)
- `groups_by_phase()` returns groups organized by phase
- `get_phase_pools()` returns pool names for a given phase
- `max_phase()` returns highest phase number
- Existing pool groups in fleet_organization.py have appropriate phases assigned
- All 8 new tests pass
- Full test gate: `pytest tests/ -q -n auto` — no regressions
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`

## Verified Against Codebase (2026-04-29)

```
# PoolGroup dataclass
grep -n "class PoolGroup" src/probos/substrate/pool_group.py
  18: @dataclass class PoolGroup

# PoolGroupRegistry
grep -n "class PoolGroupRegistry" src/probos/substrate/pool_group.py
  27: class PoolGroupRegistry

# Pool group registrations
grep -n "pool_groups.register" src/probos/startup/fleet_organization.py
  46, 54, 61, 70, 78, 86, 94, 102, 110 — 9 total registrations

# No existing phase gates
grep -rn "startup_phase\|phase_gate" src/probos/ → no matches
```
