# AD-418: Post-Reset Routing Degradation

## Context

`PersistentTaskStore` (`scheduled_tasks.db`) survives `probos reset` by design — scheduled tasks persist. But `probos reset` deletes `hebbian_weights.db` (all routing weights go to zero). When a survived scheduled task fires post-reset, `_fire_task()` calls `process_natural_language(task.intent_text)`, which goes through the full NL pipeline. With zero Hebbian weights, `HebbianRouter.get_preferred_targets()` returns candidates in arbitrary order (all tied at 0.0). A task that previously routed reliably to LaForge for engineering scans now routes semi-randomly.

There is currently:
- No `agent_hint` field on `PersistentTask` to guide routing post-reset
- No warning about active scheduled tasks during the reset confirmation
- No capability-based fallback when Hebbian weights are zero

## Changes

### Step 1: Add `agent_hint` field to PersistentTask

**File:** `src/probos/persistent_tasks.py`

**1a. Add field to the dataclass** (after `enabled: bool = True`, line 49):

```python
    agent_hint: str | None = None     # AD-418: preferred agent_type for routing bias
```

**1b. Add column to the schema** (`_SCHEMA`, after the `enabled` column):

```sql
    agent_hint TEXT
```

**1c. Add idempotent migration** in `start()` — after schema creation, add:

```python
        # AD-418: Migrate agent_hint column
        try:
            await self._db.execute("ALTER TABLE scheduled_tasks ADD COLUMN agent_hint TEXT")
            await self._db.commit()
        except Exception:
            pass  # Column already exists
```

**1d. Update `create_task()`** — add `agent_hint: str | None = None` parameter. Pass it into the `PersistentTask(...)` constructor and the INSERT statement.

**1e. Update the INSERT statement** in `create_task()` — add `agent_hint` to the column list and values tuple.

**1f. Update `_task_to_dict()`** — add `"agent_hint": task.agent_hint` to the dict.

**1g. Update `_row_to_task()`** — add `agent_hint=row["agent_hint"]` (with a fallback for rows without the column: use `row["agent_hint"] if "agent_hint" in row.keys() else None`).

### Step 2: Thread `agent_hint` through `_fire_task` → `process_natural_language`

**File:** `src/probos/persistent_tasks.py`

**2a. In `_fire_task()`** (line 393), pass the hint alongside the intent text:

```python
        try:
            result = await self._process_fn(
                task.intent_text,
                channel_id=task.channel_id,
                agent_hint=task.agent_hint,   # AD-418
            )
```

**File:** `src/probos/runtime.py`

**2b. Add `agent_hint` parameter to `process_natural_language()`** (line 1959):

```python
    async def process_natural_language(
        self,
        text: str,
        on_event: ... = None,
        auto_selfmod: bool = True,
        conversation_history: ... = None,
        agent_hint: str | None = None,       # AD-418
    ) -> dict[str, Any]:
```

**2c. Use the hint in the working memory / routing context.** Find where `hebbian_router.get_preferred_targets()` is called or where the DAG node's intent is broadcast. The hint should bias agent selection. The cleanest approach:

Search for where intent broadcast results are collected and agents are selected. In the DAG execution path, after the IntentBus returns results, if `agent_hint` is set and the hinted agent type responded, prefer its result. Alternatively, include the hint in the working memory context so the LLM decomposer can emit a `target_agent_id` in the TaskDAG nodes.

**The simplest effective approach:** Store `agent_hint` on the runtime instance scope for the current request, and use it in the IntentBus broadcast to prioritize the hinted agent's response when multiple agents respond.

Add to `process_natural_language()` body, near the top:

```python
        # AD-418: Store hint for this request
        self._current_agent_hint = agent_hint
```

Then in the DAG execution path where intent results are collected, if `_current_agent_hint` matches an agent_type that responded, prefer that result. Clear the hint at the end of the method:

```python
        self._current_agent_hint = None
```

**2d. HebbianRouter hint integration.** In `HebbianRouter.get_preferred_targets()` in `src/probos/mesh/routing.py`, add an optional `hint` parameter:

```python
    def get_preferred_targets(
        self,
        source: AgentID,
        candidates: list[AgentID],
        rel_type: str | None = None,
        hint: str | None = None,           # AD-418
    ) -> list[AgentID]:
```

If `hint` is provided and a candidate's ID contains the hint string (or matches the agent_type), give it a synthetic weight boost:

```python
        if hint:
            for i, (agent_id, score) in enumerate(scored):
                if hint in agent_id:
                    scored[i] = (agent_id, score + 1.0)  # Boost above any learned weight
```

This ensures the hinted agent is preferred even with zero learned weights, but can still be outweighed by strong negative learned signals in the future.

### Step 3: Reset warning about active scheduled tasks

**File:** `src/probos/__main__.py`

**3a. In `_cmd_reset()`** (line 520), after loading config but before the confirmation prompt (line 535), count active scheduled tasks:

```python
    # AD-418: Check for active scheduled tasks that survive reset
    scheduled_db = data_dir / "scheduled_tasks.db"
    active_task_count = 0
    if scheduled_db.is_file():
        import sqlite3
        try:
            conn = sqlite3.connect(str(scheduled_db))
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT COUNT(*) as cnt FROM scheduled_tasks "
                "WHERE enabled = 1 AND status = 'pending' AND schedule_type != 'once'"
            )
            row = cursor.fetchone()
            active_task_count = row["cnt"] if row else 0
            conn.close()
        except Exception:
            pass  # DB may not exist or have wrong schema
```

**3b. Modify the confirmation prompt** to include the warning when tasks exist:

```python
    if not args.yes:
        task_warning = ""
        if active_task_count > 0:
            task_warning = (
                f"\n⚠  {active_task_count} active scheduled task(s) will continue to fire "
                "post-reset with degraded routing (Hebbian weights wiped). "
                "Consider adding agent_hint to critical tasks or disabling them first.\n"
            )
        answer = input(
            "This will permanently delete all learned state "
            "(designed agents, trust, routing weights, episodes, workflows, QA reports, "
            "Ward Room history, event log, cognitive journal, DAG checkpoints)."
            f"{task_warning}"
            "\nContinue? [y/N]: "
        ).strip().lower()
```

**3c. Add post-reset summary** — after the "Reset complete" message (line 630), add:

```python
    if active_task_count > 0:
        console.print(
            f"  [yellow]⚠ {active_task_count} scheduled task(s) active — "
            "routing may be degraded until Hebbian weights rebuild.[/yellow]"
        )
```

### Step 4: Update the API to accept `agent_hint`

**File:** `src/probos/api.py`

**4a. Add `agent_hint` to `ScheduledTaskRequest`** (line 242):

```python
class ScheduledTaskRequest(BaseModel):
    """Request to create a persistent scheduled task (Phase 25a)."""
    intent_text: str
    name: str = ""
    schedule_type: str = "once"
    execute_at: float | None = None
    interval_seconds: float | None = None
    cron_expr: str | None = None
    channel_id: str | None = None
    max_runs: int | None = None
    created_by: str = "captain"
    webhook_name: str | None = None
    agent_hint: str | None = None            # AD-418
```

**4b. Pass `agent_hint` in `create_scheduled_task()`** (line 1669):

```python
            task = await runtime.persistent_task_store.create_task(
                intent_text=req.intent_text,
                schedule_type=req.schedule_type,
                name=req.name,
                execute_at=req.execute_at,
                interval_seconds=req.interval_seconds,
                cron_expr=req.cron_expr,
                channel_id=req.channel_id,
                max_runs=req.max_runs,
                created_by=req.created_by,
                webhook_name=req.webhook_name,
                agent_hint=req.agent_hint,    # AD-418
            )
```

**4c. Add `PATCH /api/scheduled-tasks/{task_id}/hint` endpoint** for updating the hint on existing tasks:

```python
    class UpdateAgentHintRequest(BaseModel):
        agent_hint: str | None = None

    @app.patch("/api/scheduled-tasks/{task_id}/hint")
    async def update_task_agent_hint(
        task_id: str, req: UpdateAgentHintRequest,
    ) -> dict[str, Any]:
        """AD-418: Update a scheduled task's agent_hint for routing bias."""
        if not runtime.persistent_task_store:
            return JSONResponse(status_code=503, content={"error": "Persistent task store not enabled"})
        task = await runtime.persistent_task_store.get_task(task_id)
        if not task:
            return JSONResponse(status_code=404, content={"error": "Task not found"})
        # Direct DB update
        async with runtime.persistent_task_store._db.execute(
            "UPDATE scheduled_tasks SET agent_hint = ? WHERE id = ?",
            (req.agent_hint, task_id),
        ) as _:
            pass
        await runtime.persistent_task_store._db.commit()
        updated = await runtime.persistent_task_store.get_task(task_id)
        return runtime.persistent_task_store._task_to_dict(updated)
```

### Step 5: process_natural_language `channel_id` parameter

The `_fire_task` already passes `channel_id` to `process_natural_language`, but check that `process_natural_language` actually accepts `channel_id` as a keyword argument. If it doesn't (it currently only has `text`, `on_event`, `auto_selfmod`, `conversation_history`), then `_fire_task` is passing it via `**kwargs` or it's being silently ignored.

Search for how `channel_id` is handled in `process_natural_language()`. If it's not there, skip — the scheduled task system already works. We just need to ensure `agent_hint` follows the same pattern.

## Tests

**File:** `tests/test_persistent_tasks.py` — add new test class `TestAgentHint`.

### Test 1: agent_hint field stored and retrieved
```
Create a PersistentTaskStore, start it.
create_task(intent_text="scan engineering systems", agent_hint="engineering_officer").
get_task(task_id). Assert task.agent_hint == "engineering_officer".
```

### Test 2: agent_hint defaults to None
```
create_task(intent_text="general query").
Assert task.agent_hint is None.
```

### Test 3: agent_hint survives DB restart
```
create_task with agent_hint="security_officer". Stop store. Start new store pointed at same DB.
list_tasks(). Assert the task has agent_hint="security_officer".
```

### Test 4: agent_hint included in _task_to_dict
```
Create task with agent_hint="scout".
d = store._task_to_dict(task). Assert d["agent_hint"] == "scout".
```

### Test 5: _fire_task passes agent_hint to process_fn
```
Create a mock process_fn that captures kwargs.
Create task store with that mock as process_fn.
create_task with agent_hint="engineering_officer".
Fire the task.
Assert process_fn was called with agent_hint="engineering_officer".
```

### Test 6: idempotent migration doesn't fail on second start
```
Create and start store (creates table with agent_hint).
Stop. Start again. Assert no error (ALTER TABLE is idempotent).
```

**File:** `tests/test_routing.py` or wherever HebbianRouter tests live.

### Test 7: get_preferred_targets with hint boosts hinted agent
```
Create HebbianRouter. No weights recorded.
candidates = ["agent_scout", "agent_engineering_officer", "agent_security"]
result = router.get_preferred_targets("task", candidates, hint="engineering_officer")
Assert result[0] == "agent_engineering_officer" (hinted agent first).
```

### Test 8: get_preferred_targets without hint preserves default order
```
Same setup, no hint.
Assert order is stable (no boost applied).
```

### Test 9: hint can be outweighed by strong learned weights
```
Record several successful interactions for scout. Apply hint for "engineering_officer".
Assert scout still wins if its learned weight > 1.0 boost. (This verifies the boost is moderate, not infinite.)
Actually for simplicity, just verify the boost value is exactly 1.0 — if a learned weight exceeds 1.0 the learned agent wins.
```

**File:** `tests/test_reset.py` or new file `tests/test_reset_warning.py`.

### Test 10: _cmd_reset warns about active scheduled tasks
```
This tests the CLI behavior. Create a scheduled_tasks.db in tmp dir with 3 active recurring tasks.
Mock `input()` to return "n" (abort).
Call _cmd_reset with args pointing to tmp dir.
Capture output. Assert "3 active scheduled task(s)" appears in the prompt text.
```

### Test 11: _cmd_reset shows no warning when no tasks exist
```
Same setup but no scheduled_tasks.db.
Mock input() to return "n".
Assert no "active scheduled task" text in output.
```

## Constraints

- **`agent_hint` is optional** — all existing tasks continue to work with `None`. No breaking changes.
- **Schema migration is idempotent** — uses `ALTER TABLE ADD COLUMN` in try/except, same pattern as AD-432.
- **Hint is a bias, not a hard pin** — the hinted agent gets a +1.0 weight boost in `get_preferred_targets()`, not an exclusive lock. If the hint is wrong or the agent is unavailable, other agents still respond normally.
- **The hint value is an `agent_type` string** (e.g., `"engineering_officer"`, `"scout"`, `"security_officer"`), not an agent ID. This survives reset (agent IDs change, agent_types don't).
- **Reset warning uses synchronous sqlite3** (not aiosqlite) because `_cmd_reset` is a synchronous CLI function.
- **`process_natural_language` `agent_hint` parameter** is threaded through but the primary effect is on `HebbianRouter.get_preferred_targets()` where it's used by the working memory assembly and context. The IntentBus self-selection model means the hint influences ranking, not dispatch.
- **`channel_id` pattern** — `_fire_task` already passes `channel_id` as a kwarg. Follow the exact same pattern for `agent_hint`. If `process_natural_language` doesn't accept `channel_id` explicitly, it's probably using `**kwargs`. Add `agent_hint` the same way.

## Run

```bash
cd d:\ProbOS && uv run pytest tests/test_persistent_tasks.py -x -v -k "hint" 2>&1 | tail -30
```

```bash
cd d:\ProbOS && uv run pytest tests/test_routing.py -x -v -k "hint" 2>&1 | tail -30
```

Broader validation:
```bash
cd d:\ProbOS && uv run pytest tests/test_persistent_tasks.py tests/test_routing.py tests/test_runtime.py -x -v 2>&1 | tail -40
```
