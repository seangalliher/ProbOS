# AD-267: Self-Mod Progress Stepper in HXI

## Problem

When a user clicks "Build Agent," the self-mod pipeline takes 10-30 seconds. During this time, the HXI only shows "Starting agent design..." as a chat message. There's no visual indication of progress. The user sits waiting with no feedback until the agent is deployed or fails.

## Design

Add progress events from the backend and render them as an animated stepper in the HXI chat area. The pipeline has 5 distinct stages — show each one lighting up as it completes.

### Pipeline stages (from `self_mod.py` handle_unhandled_intent):

1. **Designing** — LLM generates agent source code
2. **Validating** — CodeValidator static analysis + import approval
3. **Testing** — SandboxRunner functional test
4. **Deploying** — Register agent type + create pool + set trust
5. **Executing** — Auto-retry original request through new agent

## Backend changes

### File: `src/probos/api.py` — `_run_selfmod()` function

The current flow calls `rt.self_mod_pipeline.handle_unhandled_intent()` as a single await — we can't inject progress events mid-pipeline. Instead, we'll add progress events **around** the pipeline call, and add a **callback mechanism** to emit events during the pipeline.

**Approach:** Add an `on_progress` callback parameter to `handle_unhandled_intent()` in `self_mod.py`. The callback is an async function that receives `(step_name: str, step_number: int, total_steps: int)`. In `api.py`, wire this to emit `self_mod_progress` events.

### File: `src/probos/cognitive/self_mod.py` — `handle_unhandled_intent()`

Add an optional `on_progress` parameter:

```python
async def handle_unhandled_intent(
    self,
    intent_name: str,
    intent_description: str,
    parameters: dict[str, str],
    requires_consensus: bool = False,
    execution_context: str = "",
    on_progress: Callable[[str, int, int], Awaitable[None]] | None = None,
) -> DesignedAgentRecord | None:
```

Insert progress callbacks at each stage boundary:

```python
# Before step 1 (design):
if on_progress:
    await on_progress("designing", 1, 5)

source_code = await self._designer.design_agent(...)

# Before step 2 (validate):
if on_progress:
    await on_progress("validating", 2, 5)

errors = self._validator.validate(source_code)
...

# Before step 3 (sandbox):
if on_progress:
    await on_progress("testing", 3, 5)

sandbox_result = await self._sandbox.test_agent(...)

# Before step 4 (register + pool):
if on_progress:
    await on_progress("deploying", 4, 5)

await self._register_fn(agent_class)
await self._create_pool_fn(agent_type, pool_name, 1)
await self._set_trust_fn(pool_name)
```

**Important:** Only add progress calls for stages that are reached. If validation fails, stages 3-5 never fire — that's correct, the stepper shows where it stopped.

### File: `src/probos/api.py` — `_run_selfmod()`

Wire the progress callback:

```python
async def _on_progress(step: str, current: int, total: int) -> None:
    step_labels = {
        "designing": "🔨 Designing agent code...",
        "validating": "🔍 Validating & security scanning...",
        "testing": "🧪 Sandbox testing...",
        "deploying": "🚀 Deploying to mesh...",
    }
    rt._emit_event("self_mod_progress", {
        "intent": req.intent_name,
        "step": step,
        "step_label": step_labels.get(step, step),
        "current": current,
        "total": total,
        "message": step_labels.get(step, f"Step {current}/{total}: {step}"),
    })

record = await rt.self_mod_pipeline.handle_unhandled_intent(
    intent_name=req.intent_name,
    intent_description=req.intent_description,
    parameters=req.parameters,
    execution_context=exec_context,
    on_progress=_on_progress,
)
```

After auto-retry starts (after emit `self_mod_success`), also emit a progress event for step 5:

```python
rt._emit_event("self_mod_progress", {
    "intent": req.intent_name,
    "step": "executing",
    "step_label": "⚡ Executing your request...",
    "current": 5,
    "total": 5,
    "message": "⚡ Executing your request...",
})
```

## Frontend changes

### File: `ui/src/store/useStore.ts`

Add state for self-mod progress:

In the `HXIState` interface, add:
```typescript
selfModProgress: { step: string; current: number; total: number; label: string } | null;
```

Initialize to `null` in the store defaults.

Handle the new event in `handleEvent`:
```typescript
case 'self_mod_progress': {
    const step = data.step as string;
    const current = data.current as number;
    const total = data.total as number;
    const label = (data.step_label || data.message || '') as string;
    set({ selfModProgress: { step, current, total, label } });
    // Also add as a chat message for the transcript
    if (label) {
        get().addChatMessage('system', label);
    }
    break;
}
```

Clear progress on `self_mod_success`, `self_mod_failure`, and `self_mod_retry_complete`:
```typescript
case 'self_mod_success': {
    soundEngine.playSelfModSpawn();
    set({ selfModProgress: null });  // <-- add this
    ...
}
case 'self_mod_failure': {
    set({ selfModProgress: null });  // <-- add this
    ...
}
case 'self_mod_retry_complete': {
    set({ selfModProgress: null });  // <-- add this
    ...
}
```

### File: `ui/src/store/types.ts`

No changes needed — the progress state is just store-level, not a separate type.

### File: `ui/src/components/IntentSurface.tsx`

The progress steps will show up as individual chat messages (system role), which is the simplest approach that works with the existing chat rendering. Each step message replaces the previous one in the chat, giving a natural scrolling progress indicator.

**No new component needed.** The chat messages already render system messages. The emoji prefixes (🔨 🔍 🧪 🚀 ⚡) provide visual distinctiveness. The sequence tells the story:

```
🔨 Designing agent code...
🔍 Validating & security scanning...
🧪 Sandbox testing...
🚀 Deploying to mesh...
✅ GetCryptoPriceAgent deployed! [capability report]
⚡ Executing your request...
[actual result]
```

## Tests

### File: `tests/test_hxi_events.py` (or `tests/test_self_mod.py`)

Add 2 tests:

1. `test_selfmod_progress_callback_called` — create a pipeline with a mock `on_progress`, run `handle_unhandled_intent()`, verify callback was called with `("designing", 1, 5)`, `("validating", 2, 5)`, `("testing", 3, 5)`, `("deploying", 4, 5)`

2. `test_selfmod_progress_callback_optional` — verify `handle_unhandled_intent()` still works without `on_progress` (backward compat)

## PROGRESS.md

Update:
- Status line (line 3) test count
- Add AD-267 section before `## Active Roadmap`:

```
### AD-267: Self-Mod Progress Stepper

**Problem:** Self-mod pipeline takes 10-30 seconds with no visual progress feedback in the HXI. User sees "Starting agent design..." then waits with no indication of what's happening.

| AD | Decision |
|----|----------|
| AD-267 | Added `on_progress` async callback to `handle_unhandled_intent()`. Backend emits `self_mod_progress` events at each pipeline stage (designing → validating → testing → deploying → executing). HXI renders each step as a chat message with emoji prefix. No new UI component — leverages existing chat message rendering. Progress state cleared on success/failure |

**Files changed:**

| File | Change |
|------|--------|
| `src/probos/cognitive/self_mod.py` | Added optional `on_progress` callback parameter to `handle_unhandled_intent()`, called at each pipeline stage |
| `src/probos/api.py` | Wire `_on_progress` callback to emit `self_mod_progress` events with step labels |
| `ui/src/store/useStore.ts` | Added `selfModProgress` state, handle `self_mod_progress` event, clear on completion |

NNNN/NNNN tests passing (+ 11 skipped). N new tests.
```

## Constraints

- Do NOT create a new React component — use existing chat message rendering
- Do NOT modify the self-mod pipeline logic — only add the callback calls at stage boundaries
- Do NOT change any canvas/Three.js code
- Do NOT modify `agent_designer.py`, `code_validator.py`, `sandbox.py`
- The `on_progress` parameter MUST be optional with default `None` for backward compat
- Progress callbacks are fire-and-forget — exceptions in the callback must not break the pipeline
- Run tests after each edit: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`
- Report the final test count
