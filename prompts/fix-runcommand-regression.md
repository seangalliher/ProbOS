# URGENT: Regression — run_command Execution Hangs

## Problem

`run_command` (consensus-gated) is hanging during execution. "What time is it?" used to work fine from the CLI — now it hangs at "Executing 1 task(s)..." in BOTH the CLI shell AND the HXI chat. This is a runtime regression, not a frontend issue.

## When it broke

This worked before Phase 23 HXI refinements. The regression was likely introduced by one of:
1. `_emit_event()` instrumentation in `runtime.py` (AD-254) — may have introduced blocking or deadlock in the execution path
2. Event listener registration changes
3. `_safe_serialize()` in `api.py` — may block when serializing large objects during consensus
4. The `asyncio.wait_for(..., timeout=30.0)` wrapper around `process_natural_language()` in `api.py` — may interfere with the event loop
5. Changes to `DreamScheduler` (`_pre_dream_fn` callback)

## How to diagnose

1. **Add debug logging** to the execution path in `runtime.py`:
   - At the start of `_execute_dag()`: `logger.info("_execute_dag starting, %d nodes", len(dag.nodes))`
   - Before consensus in `submit_intent_with_consensus()`: `logger.info("consensus starting for %s", intent.intent)`
   - After consensus: `logger.info("consensus complete for %s", intent.intent)`
   - Before `_emit_event()` calls: check if any `_emit_event()` call is happening inside a critical section or while holding a lock

2. **Check for deadlock**: The `_emit_event()` method calls listeners synchronously. If a listener (like the API bridge) calls `asyncio.create_task()` for WebSocket broadcasting, and the event loop is already busy with the DAG execution, it could deadlock.

3. **Quick test**: Temporarily comment out ALL `_emit_event()` calls in `runtime.py` and see if "what time is it?" works again. If it does, the event emission is causing the hang.

4. **Check consensus gating**: The `run_command` intent requires `use_consensus: true`. Try a non-consensus query that executes an agent — like "read the file at d:/ProbOS/README.md" (read_file, no consensus). If this works but run_command doesn't, the issue is specifically in the consensus execution path.

## Important context for diagnosis

- `run_command` requires consensus → QuorumEngine.evaluate() → 3 shell agents vote → red team verification
- The execution path: `_execute_dag()` → `_execute_node()` → `submit_intent_with_consensus()` → consensus → execute
- Event listeners were added in AD-254: `self._event_listeners` list, `_emit_event()` method
- The API server registers an event listener that broadcasts to WebSocket clients

## Fix approach

If `_emit_event()` is the cause:
- Make event emission fully non-blocking: `asyncio.get_event_loop().call_soon()` instead of direct function calls
- OR move event emission to after the critical consensus/execution section, not during it
- OR add a try/except around each `_emit_event()` call so a listener failure can't block execution

## After fix

1. Test from CLI: `python -m probos` → "what time is it?" → should complete within 10 seconds
2. Test from HXI: same query → should not hang
3. Run full test suite: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q` → all tests must pass
4. Verify the fix doesn't break WebSocket event streaming to the HXI
