# AD-586: Task-Contextual Standing Orders — Orthogonal 5th Dimension

**Status:** Ready for builder
**Issue:** #143
**Dependencies:** Standing orders system (compose_instructions in standing_orders.py), CognitiveSkillCatalog (AD-596b)
**Estimated tests:** 12

---

## Problem

Standing orders define both identity and task capabilities. The `compose_instructions()` function loads all tiers (federation, ship, department, agent, directives, skills) into every cognitive cycle regardless of the current task. When working on a build task, an agent loads all standing orders including irrelevant ones about social interaction, dream analysis, etc. No mechanism activates task-specific instructions only when relevant.

The current tier hierarchy is:
1. Federation (immutable)
2. Ship (instance config)
3. Department (engineering, medical, etc.)
4. Agent (individual learned practices)
5. Active Directives (AD-386, from DirectiveStore)
6. Skill Profile (AD-596b/625, from CognitiveSkillCatalog)

There is no task-contextual tier.

## Solution

Add a `TaskContext` class that classifies intents into task types and renders task-specific standing orders from markdown files. Insert this as Tier 5.5 (between Agent Standing Orders and Active Directives) in `compose_instructions()`. Only inject task orders when an explicit `task_type` parameter is provided.

---

## Implementation

### 1. TaskContext Class

**New file:** `src/probos/cognitive/task_context.py`

```python
class TaskContext:
    def __init__(
        self,
        config: "TaskContextConfig",
        orders_dir: Path | None = None,
    ) -> None:
```

- `orders_dir` defaults to `config/task_orders/` relative to the project root (same pattern as `_DEFAULT_ORDERS_DIR` in standing_orders.py).
- Store `config` and resolved `orders_dir`.

Methods:

**`classify_task(intent_name: str) -> str`**
Pure mapping, no LLM. Returns one of: `"build"`, `"analyze"`, `"communicate"`, `"diagnose"`, `"review"`, `"general"`.

Classification rules (hardcoded dict):
```python
_INTENT_TASK_MAP: dict[str, str] = {
    "build_code": "build",
    "build_queue_item": "build",
    "code_review": "review",
    "self_mod": "build",
    "design": "build",
    "analyze_code": "analyze",
    "analyze_metrics": "analyze",
    "proactive_think": "analyze",
    "ward_room_notification": "communicate",
    "direct_message": "communicate",
    "diagnose": "diagnose",
    "vitals_check": "diagnose",
    "smoke_test": "diagnose",
}
```
Any intent not in the map returns `"general"`.

**`get_task_orders(task_type: str) -> str`**
Load `{orders_dir}/{task_type}.md` if it exists, return its content truncated to `config.max_tokens` characters. If the file does not exist, return empty string. Log warning on missing file only for non-"general" types.

**`render_task_context(task_type: str) -> str`**
If `task_type == "general"` or no orders found, return empty string. Otherwise return:
```
## Task Context ({task_type})
{orders_content}
```

### 2. TaskContextConfig

**File:** `src/probos/config.py`

Add `TaskContextConfig(BaseModel)` before `SystemConfig`:
```python
class TaskContextConfig(BaseModel):
    """Task-contextual standing orders configuration (AD-586)."""
    enabled: bool = True
    orders_dir: str = "config/task_orders"
    max_tokens: int = 500
```

Add to `SystemConfig`:
```python
task_context: TaskContextConfig = TaskContextConfig()
```

### 3. Insert Tier 5.5 into compose_instructions

**File:** `src/probos/cognitive/standing_orders.py`

Add a module-level reference for the TaskContext instance (same pattern as `_directive_store` and `_skill_catalog`):
```python
_task_context: Any = None
```

**Architectural note:** This follows the existing `_directive_store` / `_skill_catalog` module-level setter pattern in `standing_orders.py`. If refactoring to runtime injection, do so in a separate AD that also migrates the existing globals.

Add setter:
```python
def set_task_context(ctx: Any) -> None:
    """Wire the TaskContext for tier 5.5 composition (AD-586)."""
    global _task_context
    _task_context = ctx
```

Modify `compose_instructions()` signature — add two new keyword-only parameters:
```python
def compose_instructions(
    agent_type: str,
    hardcoded_instructions: str,
    *,
    orders_dir: Path | None = None,
    department: str | None = None,
    callsign: str | None = None,
    agent_rank: str | None = None,
    skill_profile: object | None = None,
    task_type: str | None = None,        # AD-586: task classification
    task_context: Any | None = None,      # AD-586: override TaskContext instance
) -> str:
```

In the body, after the Agent Standing Orders tier (Tier 5) section and before the Active Directives tier (Tier 6), insert:
```python
# Tier 5.5: Task-contextual standing orders (AD-586)
task_ctx = task_context or _task_context
if task_type and task_ctx and hasattr(task_ctx, "render_task_context"):
    try:
        task_section = task_ctx.render_task_context(task_type)
        if task_section:
            parts.append(task_section)
    except Exception:
        logger.debug("AD-586: Failed to render task context for %s", task_type)
```

**Important:** Clear the `lru_cache` on `_load_file` — this is already a concern since the function caches by path. The task orders files are loaded through the `TaskContext` class directly (not via `_load_file`), so no cache issue.

### 4. Wire into CognitiveAgent

**File:** `src/probos/cognitive/cognitive_agent.py`

In the `decide()` method (around line 1246), where `compose_instructions()` is called to build the system prompt, add task classification:

Locate the call to `compose_instructions()`. Before that call, classify the task:
```python
# AD-586: Classify current task for contextual standing orders
_task_type = None
if self._task_context is not None:
    intent_name = observation.get("intent", "")
    _task_type = self._task_context.classify_task(intent_name)
```

Pass `task_type=_task_type` to `compose_instructions()`.

Add a setter on CognitiveAgent:
```python
def set_task_context(self, ctx: Any) -> None:
    """AD-586: Wire task context for contextual standing orders."""
    self._task_context = ctx
```

**Builder:** Initialize `self._task_context: Any = None` in `CognitiveAgent.__init__()` (in the `**kwargs` extraction section). Check with `if self._task_context is not None:` -- do NOT use `hasattr()`.

### 5. Create Default Task Order Files

**New directory:** `config/task_orders/`

Create five files:

**`config/task_orders/build.md`:**
```markdown
Focus on code quality and correctness. Follow SOLID principles. Every change must have tests. Run targeted tests after each step. Do not expand scope beyond what is specified.
```

**`config/task_orders/analyze.md`:**
```markdown
Ground analysis in evidence. Cite specific data points. Structure reasoning as hypothesis-evidence-conclusion. Distinguish correlation from causation. State confidence levels.
```

**`config/task_orders/communicate.md`:**
```markdown
Express personality naturally. Match the register to the channel (formal on bridge, casual in social). Listen before responding. Build on others' contributions rather than repeating.
```

**`config/task_orders/diagnose.md`:**
```markdown
Use systematic isolation. Start with the most likely cause. Gather evidence before concluding. Check recent changes first. Document the diagnostic path for others.
```

**`config/task_orders/general.md`:**
(empty file — no additional orders for unclassified tasks)

### 6. Wire During Startup

**File:** `src/probos/startup/finalize.py`

Add a helper function:
```python
def _wire_task_context(*, runtime: Any, config: "SystemConfig") -> int:
    """AD-586: Wire TaskContext for contextual standing orders."""
    if not config.task_context.enabled:
        return 0

    from probos.cognitive.task_context import TaskContext
    from probos.cognitive.standing_orders import set_task_context
    from probos.cognitive.cognitive_agent import CognitiveAgent as _CA

    ctx = TaskContext(config=config.task_context)
    set_task_context(ctx)

    wired_count = 0
    for pool in runtime.pools.values():
        for agent_ref in pool.healthy_agents:
            agent = agent_ref
            registry = getattr(runtime, "registry", None)
            if not isinstance(agent_ref, _CA) and registry is not None:
                agent = registry.get(agent_ref)
            if isinstance(agent, _CA) and hasattr(agent, "set_task_context"):
                agent.set_task_context(ctx)
                wired_count += 1
    return wired_count
```

Call from `finalize_startup()` after existing wiring calls. Log the count.

---

## Tests

**File:** `tests/test_ad586_task_context.py`

12 tests:

1. `test_classify_build_task` — `classify_task("build_code")` returns `"build"`
2. `test_classify_analyze_task` — `classify_task("proactive_think")` returns `"analyze"`
3. `test_classify_communicate_task` — `classify_task("ward_room_notification")` returns `"communicate"`
4. `test_classify_diagnose_task` — `classify_task("diagnose")` returns `"diagnose"`
5. `test_classify_general_default` — `classify_task("unknown_intent_xyz")` returns `"general"`
6. `test_get_task_orders` — with a temp dir containing a `build.md` file, verify `get_task_orders("build")` returns its content
7. `test_render_task_context` — verify rendered output includes `## Task Context (build)` header and orders content
8. `test_compose_instructions_with_task` — call `compose_instructions()` with `task_type="build"` and a `TaskContext`, verify task section appears in output
9. `test_tier_ordering` — verify task context section appears between Agent Standing Orders (Tier 5) and Active Directives (Tier 6) in composed output
10. `test_config_disabled` — when `config.enabled = False`, the startup wiring function returns 0
11. `test_missing_task_file_graceful` — `get_task_orders("nonexistent")` returns empty string without raising
12. `test_max_tokens_truncation` — orders longer than `max_tokens` are truncated

Use `tmp_path` for task order directories. No mocking of file system.

---

## What This Does NOT Change

- No LLM-based task classification (intent mapping is a hardcoded dict)
- No per-agent task order customization (same orders for all agents of same task type)
- No task order evolution via dream consolidation
- No changes to the existing 7 tiers — this inserts between tiers 5 and 6
- No changes to `_load_file()` cache — task orders load through TaskContext, not the standing orders cache
- No changes to `_AGENT_DEPARTMENTS` mapping
- No changes to the proactive cognitive path (proactive_think is classified as "analyze" but the orders are only injected when task_type is explicitly passed)

---

## Tracking

- `PROGRESS.md`: Add AD-586 as CLOSED
- `DECISIONS.md`: Add entry — "AD-586: Task-contextual standing orders. Tier 5.5 inserted between Agent Orders and Active Directives. Six task types (build/analyze/communicate/diagnose/review/general) classified from intent name via hardcoded dict. Markdown files in config/task_orders/."
- `docs/development/roadmap.md`: Update AD-586 row status

## Acceptance Criteria

- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
