# AD-318: SystemSelfModel — Structured Runtime Self-Knowledge

## Context

AD-317 (Ship's Computer Identity) added grounding rules and a `runtime_summary` string to the Decomposer's user prompt. The current `_build_runtime_summary()` in `runtime.py` (line 1252) generates only 3 lines of text:

```
Active pools: 14, Total agents: 54
Departments: Bridge, Engineering, Science, Security, Medical, Communications, Bundled
Registered intents: 38
```

This is too sparse for the Ship's Computer to answer questions like "what agents do you have?", "which department handles trust?", or "what's your current health?" The LLM falls back on training knowledge and confabulates.

**AD-318 replaces this ad-hoc string with a structured `SystemSelfModel` dataclass** — a compact, always-current snapshot of verified runtime facts. Level 2 of the self-knowledge grounding progression: rules (AD-317) → **data** (AD-318) → verification (AD-319) → delegation (AD-320).

## What to Build

### Part 1: `SystemSelfModel` dataclass (new file)

Create `src/probos/cognitive/self_model.py`:

```python
"""SystemSelfModel — structured runtime self-knowledge (AD-318)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class PoolSnapshot:
    """Snapshot of a single pool's state."""
    name: str
    agent_type: str
    agent_count: int
    department: str = ""


@dataclass
class SystemSelfModel:
    """Compact, always-current snapshot of verified runtime facts.

    Level 2 of self-knowledge grounding (AD-318).
    Injected into the Decomposer's user prompt as SYSTEM CONTEXT.
    """

    # Identity
    version: str = ""

    # Topology
    pool_count: int = 0
    agent_count: int = 0
    pools: list[PoolSnapshot] = field(default_factory=list)
    departments: list[str] = field(default_factory=list)
    intent_count: int = 0

    # Health
    system_mode: str = "active"  # active | idle | dreaming
    uptime_seconds: float = 0.0
    recent_errors: list[str] = field(default_factory=list)  # last 5 error summaries
    last_capability_gap: str = ""  # last unhandled intent description

    def to_context(self) -> str:
        """Serialize to compact text for LLM context injection.

        Designed to stay under ~500 chars to fit within context budget.
        """
        lines: list[str] = []

        # Identity + mode
        mode_line = f"System: ProbOS"
        if self.version:
            mode_line += f" {self.version}"
        mode_line += f" | Mode: {self.system_mode}"
        if self.uptime_seconds > 0:
            mins = int(self.uptime_seconds // 60)
            mode_line += f" | Uptime: {mins}m"
        lines.append(mode_line)

        # Topology summary
        lines.append(
            f"Pools: {self.pool_count} | Agents: {self.agent_count} "
            f"| Intents: {self.intent_count}"
        )

        # Departments
        if self.departments:
            lines.append(f"Departments: {', '.join(self.departments)}")

        # Per-pool breakdown (compact: "name(type×count)" format)
        if self.pools:
            pool_parts = []
            for p in self.pools:
                pool_parts.append(f"{p.name}({p.agent_type}×{p.agent_count})")
            lines.append(f"Pool roster: {', '.join(pool_parts)}")

        # Health signals
        if self.last_capability_gap:
            lines.append(f"Last capability gap: {self.last_capability_gap}")
        if self.recent_errors:
            lines.append(f"Recent errors ({len(self.recent_errors)}): {'; '.join(self.recent_errors[:3])}")

        return "\n".join(lines)
```

### Part 2: Build the model from runtime state (new method on runtime.py)

Replace `_build_runtime_summary()` (runtime.py line 1252) with a new method `_build_self_model()` that returns a `SystemSelfModel` instance.

In `runtime.py`, add the import at the top (with the other cognitive imports):
```python
from probos.cognitive.self_model import PoolSnapshot, SystemSelfModel
```

Replace `_build_runtime_summary` (lines 1252-1271) with:

```python
def _build_self_model(self) -> SystemSelfModel:
    """Build structured self-knowledge snapshot (AD-318)."""
    import time as _time

    # Topology
    pools: list[PoolSnapshot] = []
    dept_lookup: dict[str, str] = {}

    # Build department lookup from pool groups
    try:
        for group in self.pool_groups.all_groups():
            for pool_name in group.pool_names:
                dept_lookup[pool_name] = group.display_name
    except Exception:
        pass

    for name, pool in self.pools.items():
        pools.append(PoolSnapshot(
            name=name,
            agent_type=pool.agent_type,
            agent_count=pool.current_size,
            department=dept_lookup.get(name, ""),
        ))

    # Departments
    departments: list[str] = []
    try:
        departments = [g.display_name for g in self.pool_groups.all_groups()]
    except Exception:
        pass

    # System mode
    system_mode = "active"
    try:
        if self.dream_scheduler and self.dream_scheduler.is_dreaming:
            system_mode = "dreaming"
        elif (_time.monotonic() - self._last_request_time) > 30:
            system_mode = "idle"
    except Exception:
        pass

    # Intent count
    intent_count = 0
    try:
        intent_count = len(self.decomposer._intent_descriptors)
    except Exception:
        pass

    return SystemSelfModel(
        pool_count=len(self.pools),
        agent_count=sum(p.current_size for p in self.pools.values()),
        pools=pools,
        departments=departments,
        intent_count=intent_count,
        system_mode=system_mode,
        uptime_seconds=_time.monotonic() - self._start_time,
        recent_errors=list(self._recent_errors),
        last_capability_gap=self._last_capability_gap,
    )
```

### Part 3: Track recent errors and capability gaps on the runtime

Add two new instance attributes in `runtime.py` `__init__` (near line 192 where `_start_time` is set):

```python
self._recent_errors: list[str] = []    # last 5 error summaries (AD-318)
self._last_capability_gap: str = ""    # last unhandled intent (AD-318)
```

Add a helper method to runtime.py:

```python
def _record_error(self, summary: str) -> None:
    """Record a recent error for SystemSelfModel (AD-318)."""
    self._recent_errors.append(summary)
    if len(self._recent_errors) > 5:
        self._recent_errors = self._recent_errors[-5:]
```

Wire these up in `process_natural_language()`:

1. **Capability gap tracking** — Near line 1406 where `is_gap` is set, after the `if is_gap:` block, add:
   ```python
   self._last_capability_gap = text[:100]
   ```
   (Store the first 100 chars of the user request that triggered the gap.)

2. **Error tracking** — In the DAG execution error handling (search for exception handlers in the `_execute_dag` or `process_natural_language` flow), call `self._record_error(str(exc)[:80])` on caught exceptions. Find one or two natural exception handlers — don't add try/except blocks everywhere.

### Part 4: Update the call site

In `runtime.py` at line 1388, change:

```python
runtime_summary = self._build_runtime_summary()
```

to:

```python
self_model = self._build_self_model()
runtime_summary = self_model.to_context()
```

This keeps the Decomposer interface unchanged — it still receives a `runtime_summary` string.

### Part 5: Tests

Create tests in `tests/test_decomposer.py` in a new test class section (after the existing `test_build_runtime_summary` test at line 835).

**Test class: `TestSystemSelfModel` (AD-318)**

1. **`test_self_model_dataclass_defaults`** — Create a bare `SystemSelfModel()`. Verify all defaults: `pool_count=0`, `agent_count=0`, `pools=[]`, `departments=[]`, `intent_count=0`, `system_mode="active"`, `uptime_seconds=0.0`, `recent_errors=[]`, `last_capability_gap=""`.

2. **`test_to_context_minimal`** — Create `SystemSelfModel()` (defaults). Call `to_context()`. Verify output contains `"ProbOS"`, `"Mode: active"`, `"Pools: 0"`, `"Agents: 0"`.

3. **`test_to_context_full`** — Create a fully populated `SystemSelfModel` with 2 pools, 2 departments, version="v0.4.0", uptime=3600, intent_count=38, system_mode="idle", recent_errors=["timeout"], last_capability_gap="run docker". Call `to_context()`. Verify output contains: version, mode, uptime "60m", pool roster with "×" count format, departments, capability gap, recent errors.

4. **`test_pool_snapshot_fields`** — Create a `PoolSnapshot(name="builder", agent_type="builder", agent_count=1, department="Engineering")`. Verify all fields.

5. **`test_build_self_model`** — Mock a `ProbOSRuntime` (similar to existing `test_build_runtime_summary` at line 805). Set up 2 pools with sizes 3 and 2, one pool group, 3 intent descriptors, `_start_time` to `time.monotonic() - 120`, `_recent_errors=["err1"]`, `_last_capability_gap="deploy"`, `_last_request_time` to `time.monotonic()`, `dream_scheduler.is_dreaming=False`. Call `ProbOSRuntime._build_self_model(runtime)`. Verify: `pool_count=2`, `agent_count=5`, `system_mode="active"`, `len(pools)==2`, departments include group name, `recent_errors==["err1"]`, `last_capability_gap=="deploy"`, `uptime_seconds > 0`.

6. **`test_build_self_model_dreaming_mode`** — Same mock but `dream_scheduler.is_dreaming=True`. Verify `system_mode="dreaming"`.

7. **`test_build_self_model_idle_mode`** — Same mock but `_last_request_time = time.monotonic() - 60` (over 30s threshold). Verify `system_mode="idle"`.

8. **`test_record_error_caps_at_five`** — Create a mock runtime with `_recent_errors=[]`. Call `ProbOSRuntime._record_error(runtime, "err")` 7 times. Verify `len(runtime._recent_errors) == 5` and all are `"err"`.

9. **`test_to_context_stays_compact`** — Create a SystemSelfModel with 20 pools, 5 errors, all fields populated. Call `to_context()`. Verify `len(result) < 1000` (stays within context budget).

### Tracking Updates

Update these files:
- `PROGRESS.md` line 3: Change `Phase 32p` to `Phase 32q`, update test count
- `DECISIONS.md`: Add `## Phase 32q: SystemSelfModel (AD-318)` section with status and implementation summary

## Anti-Scope — Do NOT

- Do NOT modify the Decomposer's `decompose()` method signature — it still accepts `runtime_summary: str`. The SystemSelfModel is serialized to text before being passed.
- Do NOT modify `WorkingMemorySnapshot` or `working_memory.py` — the self model goes through `runtime_summary`, not working memory. (Combining them is a future optimization.)
- Do NOT modify `prompt_builder.py` — the PROMPT_PREAMBLE grounding rules already reference SYSTEM CONTEXT and don't need changes.
- Do NOT add reactive update hooks (pub/sub on pool changes) — the model is rebuilt on each `process_natural_language()` call, which is sufficient for now.
- Do NOT include per-agent trust scores or Hebbian weights in the self model — that's already in WorkingMemorySnapshot. Keep SystemSelfModel focused on topology and health.
- Do NOT create any files besides `src/probos/cognitive/self_model.py` and the test additions.
