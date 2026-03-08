# Phase 7: Escalation Cascades & Error Recovery

**Goal:** When a DAG node fails or consensus rejects an intent, the system should escalate rather than silently marking the node as "failed." The escalation follows a 3-tier cascade: retry with a different agent → LLM arbitration → user consultation. This fulfils the original vision's "Escalation Cascades" principle:

> *"When consensus can't be reached, the question escalates. Low-level disagreement → mid-level arbitration → cognitive layer reasoning → user consultation. Like how subconscious conflicts surface into conscious awareness only when unresolvable."*

---

## Context

Right now, the `DAGExecutor._execute_node()` method catches exceptions and marks nodes as `"failed"` with an error string. No retry. No escalation. No user consultation. The consensus pipeline (`runtime.submit_intent_with_consensus()`) returns a dict with `REJECTED` or `INSUFFICIENT` outcome, and the executor treats these the same as success — it stores the result and marks the node `"completed"` even when consensus rejected it. The user sees a green checkmark for a rejected write.

This phase adds:
1. An `EscalationManager` that orchestrates the 3-tier cascade
2. `EscalationResult` type to track escalation outcomes
3. Wiring in the DAG executor so failed/rejected nodes escalate before being marked "failed"
4. An interactive user consultation prompt in the shell for Tier 3
5. Event log entries and panel rendering for escalation events

---

## Deliverables

### 1. Add `EscalationTier` enum and `EscalationResult` type — `src/probos/types.py`

```python
class EscalationTier(Enum):
    """Escalation cascade levels."""
    RETRY = "retry"              # Tier 1: retry with a different agent
    ARBITRATION = "arbitration"  # Tier 2: ask the LLM to judge
    USER = "user"                # Tier 3: ask the user

@dataclass
class EscalationResult:
    """Outcome of an escalation attempt."""
    tier: EscalationTier
    resolved: bool                          # Did this tier resolve the issue?
    original_error: str = ""                # What triggered escalation
    resolution: Any = None                  # The successful result (if resolved)
    reason: str = ""                        # Human-readable explanation
    agent_id: str = ""                      # Which agent resolved it (Tier 1)
    attempts: int = 0                       # How many retry attempts were made
    user_approved: bool | None = None       # User's decision (Tier 3 only)
```

### 2. Create `src/probos/consensus/escalation.py` — `EscalationManager`

The escalation manager orchestrates the 3-tier cascade. It receives a failed node context and tries progressively more expensive resolution strategies.

**Constructor:**

```python
class EscalationManager:
    def __init__(
        self,
        runtime: Any,          # ProbOSRuntime (for submitting retries)
        llm_client: Any,       # For Tier 2 arbitration
        max_retries: int = 2,  # Max Tier 1 retry attempts
        user_callback: Callable | None = None,  # Tier 3: async callback to prompt user
    )
```

**Public API:**

| Method | Signature | Description |
|---|---|---|
| `escalate` | `async (node: TaskNode, error: str, context: dict) -> EscalationResult` | Run the full cascade. Returns when resolved or fully exhausted. |
| `set_user_callback` | `(callback: Callable[[str, dict], Awaitable[bool | None]]) -> None` | Set the Tier 3 user prompt callback. |

**`escalate()` implementation:**

**Tier 1 — Retry with different agent:**
- If the original error is a transient failure (exception, timeout, agent error — NOT a consensus rejection), retry the same intent through the runtime.
- Up to `max_retries` attempts. Each attempt goes through the same `submit_intent()` or `submit_intent_with_consensus()` path, so a different agent from the pool may handle it.
- If any retry succeeds, return `EscalationResult(tier=RETRY, resolved=True, resolution=<result>, attempts=N)`.
- If all retries fail, proceed to Tier 2.

**Tier 2 — LLM arbitration:**
- Send the original intent, the error(s), and any partial results to the LLM with a special `ARBITRATION_PROMPT` system prompt.
- The LLM decides: `{"action": "approve", "reason": "..."}` (accept partial result), `{"action": "reject", "reason": "..."}` (mark as failed), or `{"action": "modify", "params": {...}, "reason": "..."}` (suggest modified params for retry).
- If `"approve"`, return `EscalationResult(tier=ARBITRATION, resolved=True, reason=llm_reason)`.
- If `"modify"`, retry once with the LLM's modified params. If that succeeds, return resolved. If not, proceed to Tier 3.
- If `"reject"`, proceed to Tier 3.
- If no `llm_client` is available (MockLLMClient or None), skip Tier 2 and go to Tier 3.

**Tier 3 — User consultation:**
- If `user_callback` is set, call it with the intent description and context. The callback is expected to return `True` (approve/accept), `False` (reject/abort), or `None` (skip, treat as unresolved).
- If `user_callback` is None, return an unresolved EscalationResult.
- Return `EscalationResult(tier=USER, resolved=<user_decision is not None>, user_approved=<user_decision>)`.

**Key constraint:** Escalation must be **bounded**. Tier 1 retries have a `max_retries` cap. Tier 2 gets one LLM call (plus one optional retry with modified params). Tier 3 gets one user prompt. The entire cascade can be disabled per-intent by the caller.

### 3. Add `ARBITRATION_PROMPT` constant — `src/probos/consensus/escalation.py`

```python
ARBITRATION_PROMPT = """You are the escalation arbiter for ProbOS, a probabilistic agent-native OS.

An agent operation has failed or consensus was rejected. You must decide what to do.

You will receive:
- The original intent (what was attempted)
- The error or rejection reason
- Any partial results from agents
- The consensus outcome (if applicable)

Respond with ONLY a JSON object:
{
    "action": "approve" | "reject" | "modify",
    "reason": "Brief explanation of your decision",
    "params": {}  // Only if action is "modify" — the corrected parameters to retry with
}

Rules:
- "approve" if the partial results are acceptable despite the error
- "reject" if the operation is fundamentally flawed and should not be retried
- "modify" if you can suggest corrected parameters that might succeed
- Be conservative — when in doubt, reject and let the user decide
"""
```

### 4. Update `MockLLMClient` — `src/probos/cognitive/llm_client.py`

Add a pattern for arbitration requests:

```python
# In MockLLMClient.__init__, add pattern:
# If system prompt contains "escalation arbiter", return a default arbitration response
```

The pattern should:
- Match when system prompt contains `"escalation arbiter"`
- Return `{"action": "reject", "reason": "MockLLMClient cannot arbitrate — escalating to user"}` by default
- This ensures Tier 2 always falls through to Tier 3 in tests, making test behavior deterministic

### 5. Update `DAGExecutor._execute_node()` — `src/probos/cognitive/decomposer.py`

Wire escalation into the existing error handling. The executor currently has three code paths:

1. **`write_file` with consensus** → `submit_write_with_consensus()`
2. **Other intents with consensus** → `submit_intent_with_consensus()`
3. **No consensus** → `submit_intent()`

**Changes:**

**a)** Add an optional `escalation_manager: EscalationManager | None = None` field on `DAGExecutor.__init__()`.

**b)** In the `except Exception` block (currently just marks node as "failed"): if `self.escalation_manager` is not None, call `await self.escalation_manager.escalate(node, str(e), context)`. If the escalation resolves, update `node.result`, `node.status = "completed"`, and `results[node.id]` with the escalation result. If not resolved, keep the existing "failed" behavior.

**c)** For consensus paths (code paths 1 and 2): after getting the result, check if `consensus.outcome` is `REJECTED` or `INSUFFICIENT`. If so, and if `self.escalation_manager` is not None, escalate with the consensus rejection as the error. If escalation resolves (e.g., user approves), update the node status accordingly. If not, mark the node as "failed" instead of "completed".

**Critical:** Consensus-rejected nodes should NOT be marked "completed" anymore. This is a bug fix — currently a REJECTED write is shown as "completed" with a green checkmark. After this change, REJECTED nodes go through escalation and are marked either "completed" (if escalation resolves) or "failed" (if escalation doesn't resolve).

**d)** Fire `on_event("escalation_start", ...)` and `on_event("escalation_complete", ...)` events so the renderer can display escalation progress.

### 6. Wire `EscalationManager` into runtime — `src/probos/runtime.py`

**a)** Create `EscalationManager` in `start()` after all pools and decomposer are created:

```python
self.escalation_manager = EscalationManager(
    runtime=self,
    llm_client=self.llm_client,
    max_retries=2,
)
```

**b)** Pass `escalation_manager=self.escalation_manager` to `DAGExecutor()` in the `process_natural_language()` method.

**c)** Also pass it in `ExecutionRenderer.process_with_feedback()` where it creates DAGExecutor (the AD-34 dual pipeline pattern).

**d)** Add `escalation_manager` to `status()` output:

```python
"escalation": {
    "enabled": self.escalation_manager is not None,
}
```

### 7. Add user consultation to the shell — `src/probos/experience/shell.py`

**a)** Define a `_user_escalation_callback()` async method on `ProbOSShell`:

```python
async def _user_escalation_callback(self, description: str, context: dict) -> bool | None:
    """Prompt the user for escalation decision."""
    self.console.print(f"\n[yellow bold]⚠ Escalation — agent operation needs your input:[/yellow bold]")
    self.console.print(f"  Intent: [cyan]{context.get('intent', '?')}[/cyan]")
    self.console.print(f"  Issue: {description}")
    self.console.print(f"  [dim]Type 'y' to approve, 'n' to reject, or Enter to skip[/dim]")
    
    # Read user input
    try:
        response = await asyncio.get_event_loop().run_in_executor(
            None, lambda: input("  Decision [y/n/skip]: ").strip().lower()
        )
        if response in ("y", "yes"):
            return True
        elif response in ("n", "no"):
            return False
        else:
            return None  # Skip
    except (EOFError, KeyboardInterrupt):
        return None
```

**b)** When the shell creates the runtime or renderer, set the user callback:

```python
self.runtime.escalation_manager.set_user_callback(self._user_escalation_callback)
```

### 8. Add escalation panel rendering — `src/probos/experience/panels.py`

Add a helper that `render_dag_result()` calls when an escalation occurred:

```python
def _format_escalation(escalation: dict) -> list[str]:
    """Format an escalation result for display."""
    tier = escalation.get("tier", "?")
    resolved = escalation.get("resolved", False)
    reason = escalation.get("reason", "")
    
    colour = "green" if resolved else "red"
    status = "Resolved" if resolved else "Unresolved"
    
    lines = [f"    [yellow]↑ Escalated (Tier: {tier})[/yellow] — [{colour}]{status}[/{colour}]"]
    if reason:
        lines.append(f"      {reason}")
    return lines
```

Update `render_dag_result()` to check for escalation data on nodes and render it.

### 9. Add escalation events to renderer — `src/probos/experience/renderer.py`

The `ExecutionRenderer` needs to handle `escalation_start` and `escalation_complete` events in its `on_event` callback to show escalation progress to the user (e.g., "Escalating: retrying with different agent..." spinner).

### 10. Event log entries — `src/probos/consensus/escalation.py`

The `EscalationManager.escalate()` method should log events via the runtime's event log:

- `category="consensus"`, `event="escalation_start"`: when escalation begins
- `category="consensus"`, `event="escalation_retry"`: each Tier 1 retry attempt
- `category="consensus"`, `event="escalation_arbitration"`: Tier 2 LLM call
- `category="consensus"`, `event="escalation_user"`: Tier 3 user consultation
- `category="consensus"`, `event="escalation_resolved"`: when escalation succeeds
- `category="consensus"`, `event="escalation_exhausted"`: when all tiers fail

---

## Build Order

1. **`EscalationTier` enum and `EscalationResult` type** (`types.py`)
2. **`EscalationManager`** (`escalation.py`) — core cascade logic
3. **`ARBITRATION_PROMPT`** constant in `escalation.py`
4. **`MockLLMClient` arbitration pattern** (`llm_client.py`)
5. **Tests for `EscalationManager`** — unit tests for each tier
6. **Wire into `DAGExecutor._execute_node()`** (`decomposer.py`) — escalation on failure/rejection
7. **Fix consensus-rejected nodes** — mark as "failed" not "completed" when rejected
8. **Wire into runtime** (`runtime.py`) — create EscalationManager, pass to DAGExecutor
9. **Wire into renderer** (`renderer.py`) — pass escalation_manager, handle events
10. **User consultation callback** (`shell.py`) — interactive Tier 3 prompt
11. **Panel rendering** (`panels.py`) — `_format_escalation()` helper
12. **Integration tests** — end-to-end escalation through the full pipeline
13. **Run full suite** — `uv run pytest tests/ -v` — all 477 existing + new tests must pass.
14. **Update PROGRESS.md**

---

## Test Specification

### EscalationManager unit tests — `tests/test_escalation.py`

1. **`test_tier1_retry_succeeds`** — Create an EscalationManager. First call to submit_intent raises an error. Second call succeeds. Assert `escalate()` returns `EscalationResult(tier=RETRY, resolved=True, attempts=2)`.

2. **`test_tier1_all_retries_fail`** — Configure `max_retries=2`. All 3 attempts (original + 2 retries) fail. Assert escalation proceeds to Tier 2 (or Tier 3 if no LLM).

3. **`test_tier1_skipped_for_consensus_rejection`** — When the error is a consensus rejection (not a transient failure), Tier 1 retries should still be attempted (re-submitting may get different agents from the pool).

4. **`test_tier2_approve`** — Mock LLM returns `{"action": "approve", "reason": "Partial results acceptable"}`. Assert `EscalationResult(tier=ARBITRATION, resolved=True)`.

5. **`test_tier2_reject_proceeds_to_tier3`** — Mock LLM returns `{"action": "reject", ...}`. Assert escalation proceeds to Tier 3.

6. **`test_tier2_modify_retries_with_new_params`** — Mock LLM returns `{"action": "modify", "params": {"path": "/fixed/path"}}`. Assert a retry is attempted with the modified params.

7. **`test_tier2_skipped_when_no_llm`** — When `llm_client` is None, Tier 2 is skipped entirely and escalation goes to Tier 3.

8. **`test_tier2_mock_llm_falls_through`** — With MockLLMClient, Tier 2 returns `"reject"` (per the arbitration pattern), so escalation proceeds to Tier 3.

9. **`test_tier3_user_approves`** — Set `user_callback` that returns `True`. Assert `EscalationResult(tier=USER, resolved=True, user_approved=True)`.

10. **`test_tier3_user_rejects`** — Set `user_callback` that returns `False`. Assert `EscalationResult(tier=USER, resolved=True, user_approved=False)`.

11. **`test_tier3_user_skips`** — Set `user_callback` that returns `None`. Assert `EscalationResult(tier=USER, resolved=False, user_approved=None)`.

12. **`test_tier3_no_callback`** — No `user_callback` set. Assert `EscalationResult(tier=USER, resolved=False)`.

13. **`test_full_cascade_all_fail`** — All tiers fail. Assert final result is `resolved=False` with Tier USER.

14. **`test_escalation_bounded`** — Assert that with `max_retries=2`, the total number of submit_intent calls during Tier 1 is at most 2 (not including the original attempt — that's the caller's responsibility).

### DAGExecutor escalation tests — `tests/test_escalation.py`

15. **`test_executor_escalates_on_exception`** — DAGExecutor with escalation_manager. Node execution raises an exception. Assert escalation is triggered and, if it resolves, the node is marked "completed".

16. **`test_executor_escalates_on_consensus_rejection`** — Node with `use_consensus=True` gets a REJECTED consensus. Assert escalation is triggered.

17. **`test_executor_no_escalation_without_manager`** — DAGExecutor without escalation_manager. Node fails. Assert node is marked "failed" (existing behavior preserved).

18. **`test_executor_rejected_node_marked_failed`** — Without escalation manager, a consensus-REJECTED node should now be marked "failed" not "completed". (Bug fix test.)

19. **`test_executor_escalation_events_fired`** — With `on_event` callback, assert `escalation_start` and `escalation_complete` events are fired during escalation.

### Runtime escalation wiring — `tests/test_escalation.py`

20. **`test_runtime_creates_escalation_manager`** — Start runtime. Assert `runtime.escalation_manager` is not None.

21. **`test_runtime_status_includes_escalation`** — `runtime.status()` includes `"escalation"` key.

22. **`test_runtime_nl_with_escalation`** — Process NL input through the full pipeline. Assert existing behavior is unchanged when no escalation occurs.

### Panel/rendering tests — `tests/test_escalation.py`

23. **`test_format_escalation_resolved`** — `_format_escalation()` with `resolved=True` produces green "Resolved" text.

24. **`test_format_escalation_unresolved`** — `_format_escalation()` with `resolved=False` produces red "Unresolved" text.

25. **`test_render_dag_result_with_escalation`** — `render_dag_result()` with a node that has escalation data shows the escalation info.

**Total: 25 new tests. Target: 502/502 (477 existing + 25 new).**

---

## Rules

1. All 477 existing tests must pass unchanged. Escalation is additive — it adds new behavior for failure/rejection cases without changing the success path.
2. The existing `node.status = "completed"` for consensus-REJECTED intents is a **bug**. Fix it: REJECTED/INSUFFICIENT consensus should mark the node "failed" (or trigger escalation if available). This may require updating one or two existing tests that check node status after consensus rejection — update them to expect "failed" instead of "completed".
3. `EscalationManager.escalate()` is async. Each tier is attempted sequentially (not in parallel). Tier 1 → Tier 2 → Tier 3. If any tier resolves, stop.
4. Tier 1 retries go through the normal `runtime.submit_intent()` or `runtime.submit_intent_with_consensus()` path. This means different agents may handle the retry due to pool rotation.
5. Tier 2 LLM arbitration uses the `standard` tier. The `ARBITRATION_PROMPT` is the system prompt.
6. Tier 3 user callback is optional. If not set (programmatic use, tests), Tier 3 returns unresolved. Tests should use a mock callback.
7. The `EscalationManager` does NOT log events directly — it returns the result to the caller (DAGExecutor), which logs events via `on_event`. The event log entries listed above are logged by `_execute_node()` through the runtime's event log.
8. `EscalationResult` is stored on `node.escalation_result` (add optional field to `TaskNode`). This allows the renderer and panels to access it.
9. The `_format_escalation()` helper is called from `render_dag_result()` when `node.escalation_result` is not None. It appears below the node's result line.
10. `run_in_terminal` the tests after every file change: `uv run pytest tests/ -v`.
11. Update `PROGRESS.md` when done: add Phase 7 section, new AD entries, update test counts, update "What's Next".
12. Do NOT modify the `REFLECT_PROMPT`, `SYSTEM_PROMPT`, `_LEGACY_SYSTEM_PROMPT`, or `PromptBuilder` logic. Escalation does not change intent decomposition.
13. The `user_callback` in the shell uses `asyncio.get_event_loop().run_in_executor(None, input)` to avoid blocking the event loop. This is the same pattern the shell already uses for user input.
