# BF-014: Rename Bundled Agents → Utility Agents

## Context

The "bundled agents" terminology is a holdover from AD-252. The three-tier agent model (AD-398) uses Core / Utility / Crew. "Bundled" should be "Utility" everywhere for consistency.

The config class has already been renamed to `UtilityAgentsConfig` with a backward-compatible `@property` alias `bundled_agents` on `SystemConfig`. The pool group display name in `runtime.py` has been updated to "Utility Agents". This prompt sweeps the remaining references.

## Changes Required

### 1. `src/probos/runtime.py`

Replace all remaining `bundled_agents` references with `utility_agents`:

```
self.config.bundled_agents.enabled  →  self.config.utility_agents.enabled
```

There are approximately 10 occurrences (lines referencing `self.config.bundled_agents.enabled`). Replace all of them.

After the sweep, the `@property` alias in `config.py` can be removed:

### 2. `src/probos/config.py`

Remove the backward-compat alias from `SystemConfig`:

```python
# REMOVE this:
@property
def bundled_agents(self) -> UtilityAgentsConfig:
    """Backward-compatible alias — use utility_agents instead."""
    return self.utility_agents
```

### 3. `src/probos/agents/bundled.py`

If this file exists, rename it to `src/probos/agents/utility.py`. Update the import in `runtime.py`:

```python
# Old:
from probos.agents.bundled import (...)
# New:
from probos.agents.utility import (...)
```

### 4. Config YAML

In `config/default.yaml` (if it exists), rename the key:

```yaml
# Old:
bundled_agents:
  enabled: true

# New:
utility_agents:
  enabled: true
```

### 5. Tests

Search all test files for `bundled` references and update:
- Variable names: `bundled_pools` → `utility_pools`
- Config references: `config.bundled_agents` → `config.utility_agents`
- Pool group name assertions: `"bundled"` → `"utility"`
- Display name assertions: `"Bundled Agents"` → `"Utility Agents"`

### 6. Documentation

Update references in:
- `docs/` — any mention of "bundled agents"
- `DECISIONS.md` — update AD-252 and related entries
- `roadmap.md` — update phase descriptions

### 7. HXI Store

In `ui/src/store/useStore.ts`, update `GROUP_TINT_HEXES`:

```typescript
// Old:
bundled: '#70a080',
// New:
utility: '#70a080',
```

## Search Commands

Use these to find all references:

```bash
# Python files
rg "bundled" --type py -l

# TypeScript files
rg "bundled" --type ts -l

# Markdown files
rg "bundled" --type md -l

# YAML files
rg "bundled" --glob "*.yaml" -l
```

## Verification

```bash
# No remaining "bundled" references in source (excluding git history, node_modules, prompts/)
rg "bundled" --type py --type ts --type yaml src/ ui/src/ config/ tests/

# All tests pass
uv run pytest tests/ --tb=short -q

# Frontend build
cd ui && npm run build
```

## Commit Message

```
Rename bundled agents to utility agents (BF-014)

Aligns terminology with three-tier agent model (Core/Utility/Crew).
Config, runtime, tests, docs, and HXI store updated.
```
