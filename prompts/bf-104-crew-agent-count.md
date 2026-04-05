# BF-104: Display Crew Agent Count, Not Total Agent Count

## Priority: Medium | Scope: Small | Type: Bug Fix

## Problem

ProbOS displays "62 agents" in the shell prompt, status panels, and API responses. This conflates infrastructure agents, utility agents, and crew agents into a single number. Per AD-398's three-tier agent architecture, only crew agents are sovereign individuals — infrastructure and utility agents are tools and services. When a user thinks "agents" they mean crew.

The shell prompt showing `[62 agents | health: 0.95] probos>` is misleading — the actual crew is ~12-15 agents.

## Design

Add a `crew_count` property to the registry (or compute it where needed) using the existing `is_crew_agent()` helper. Display crew count as the primary number. Show total as secondary context where appropriate.

**Key principle:** "Crew" is the headline number. "Total services" is supplementary.

## Changes Required

### 1. Registry — add `crew_count` helper

**File:** `src/probos/substrate/registry.py`

Add a method that returns the count of crew agents:

```python
def crew_count(self) -> int:
    """Count of sovereign crew agents (excludes infrastructure/utility)."""
    from probos.crew_utils import is_crew_agent
    return sum(1 for a in self._agents.values() if is_crew_agent(a))
```

Note: `is_crew_agent()` may need the ontology. Check the current signature — if it requires ontology, the method should accept it as a parameter or access it from a stored reference. Grep `is_crew_agent` usage to confirm the calling pattern.

### 2. Shell prompt — show crew count

**File:** `src/probos/experience/shell.py` (~line 150)

Change:
```python
count = self.runtime.registry.count
```
To show crew count as primary:
```python
crew = self.runtime.registry.crew_count()
count = self.runtime.registry.count
# Display: [12 crew | 62 total | health: 0.95] probos>
```

Format: `[{crew} crew | health: {health:.2f}] probos>`

Drop the total from the prompt — keep it clean. Total is visible via `/status`.

### 3. Status panel — distinguish crew vs total

**File:** `src/probos/experience/panels.py` (~line 85)

Change:
```python
lines.append(f"  Agents:  {status.get('total_agents', 0)}")
```
To:
```python
lines.append(f"  Crew:    {status.get('crew_agents', 0)}  (total services: {status.get('total_agents', 0)})")
```

### 4. Runtime status dict — add crew_agents

**File:** `src/probos/runtime.py` (~line 2439)

Add `crew_agents` to the status dict:
```python
"crew_agents": self.registry.crew_count(),
"total_agents": self.registry.count,
```

### 5. /ping command — show crew count

**File:** `src/probos/experience/commands/commands_status.py` (~line 73)

Update the display line to show crew vs total:
```python
console.print(f"Crew: {crew_active} active / {crew_total} crew (health: {health_score:.2f})")
```

Where `crew_active` filters `active_agents` through `is_crew_agent()`.

### 6. API /health endpoint — add crew_agents

**File:** `src/probos/routers/system.py` (~line 26)

Add `crew_agents` alongside existing `agents`:
```python
"crew_agents": status.get("crew_agents", 0),
"agents": status.get("total_agents", 0),  # keep for backwards compat
```

### 7. Working memory context — show crew count

**File:** `src/probos/cognitive/working_memory.py` (~line 39)

Change:
```python
sections.append(f"Agents: {self.agent_summary.get('total', 0)} total")
```
To:
```python
sections.append(f"Crew: {self.agent_summary.get('crew', 0)} agents")
```

This requires `agent_summary` to include a `crew` key — trace where `agent_summary` is built and add crew count there.

## Do NOT Change

- **Federation self-model** (`runtime.py` ~line 2562): Keep total agent count for federation gossip — other instances need full picture
- **Shutdown log** (`startup/shutdown.py` line 317): Already has crew-filtered count at line 68 for session records; leave the final log line as-is for debugging
- **`/agents` roster** (`panels.py` ~line 316): This already shows per-pool breakdown, which is the right granularity for that view

## Verification

Before implementing, grep for `is_crew_agent` to confirm its signature and any ontology dependency. Match the calling pattern used elsewhere (e.g., in `commands_qualification.py`, `drift_detector.py`).

## Tests

- Test `registry.crew_count()` returns correct count with mixed agent types
- Test status dict includes both `crew_agents` and `total_agents`
- Test shell prompt format shows crew count
- No existing tests should break — `total_agents` is preserved everywhere

## Acceptance Criteria

- Shell prompt shows `[12 crew | health: 0.95] probos>` (crew count, not 62)
- `/status` shows `Crew: 12 (total services: 62)`
- `/ping` shows crew active/total
- API `/health` includes `crew_agents` field
- All existing tests pass
