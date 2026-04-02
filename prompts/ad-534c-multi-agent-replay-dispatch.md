# AD-534c: Multi-Agent Replay Dispatch — Build Prompt

**Depends on:** AD-534 (Replay-First Dispatch) ✅, AD-532d (Compound Procedures) ✅, AD-534b (Fallback Learning) ✅
**Scope:** OSS
**Defers to:** AD-535 (Graduated Compilation) — step postcondition validation, per-step execution model

## Context

AD-532d introduced compound procedure extraction: when a dream cycle detects a success cluster involving 2+ agents, it extracts a `Procedure` with per-step `agent_role` assignments (e.g., `"security_analysis"`, `"engineering_diagnostics"`). Today, `_format_procedure_replay()` renders these role annotations as `[role]` text markers, but **no dispatch logic exists**. The entire compound procedure replays through the single agent that matched the intent — defeating the purpose of multi-agent collaboration.

AD-534c bridges this gap: detect compound procedures during replay, resolve `agent_role` to live agents, dispatch each step to the appropriate agent, collect results, and assemble the compound replay. Graceful degradation to single-agent replay when agents are unavailable.

**Key constraint:** Cognitive JIT's value is zero-token replay. Dispatched steps are pre-formatted text, NOT new LLM calls. Target agents receive step content and return it — no `decide()` or LLM invocation on the receiving side.

## Design Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | **Store `resolved_agent_type` on ProcedureStep during compound extraction.** Runtime fallback via capability-based lookup if stored type unavailable. | Free-form `agent_role` strings like `"security_analysis"` require mapping to concrete `agent_type`s (pools). Doing this at extraction time (when `origin_agent_ids` are known) avoids runtime LLM calls. Runtime fallback via `AgentRegistry.get_by_capability()` handles cases where the stored type is no longer available. |
| 2 | **New `_execute_compound_replay()` method on CognitiveAgent.** | Keeps orchestration in the cognitive layer alongside `_check_procedural_memory()` and `_format_procedure_replay()`. Avoids polluting the single-agent path. Compound detection in `_check_procedural_memory()` routes to this method. |
| 3 | **Dispatch via IntentBus.send() with `compound_step_replay` intent.** Target agent's handler receives pre-formatted step text and returns it. | IntentBus.send() already supports targeted delivery via `target_agent_id`. Lightweight — no Ward Room persistence overhead, no WorkItem scheduling overhead. |
| 4 | **Unavailability → degrade to single-agent text replay.** Log as near-miss for AD-534b capture. | If ANY required agent is unavailable, the compound procedure can't execute as designed. Fall back to current behavior (format all steps as text, replay through originating agent). This is safe — the text replay already works. Near-miss capture (AD-534b) records the degradation for future analysis. |
| 5 | **Zero-token dispatch.** Target agents receive step text, return acknowledgment. No LLM calls on receiving side. | The whole point of Cognitive JIT. Compound replay should cost zero tokens for ALL participating agents. The orchestrating agent formats and routes; target agents receive and acknowledge. |
| 6 | **Result threading deferred to AD-535.** AD-534c dispatches steps sequentially and collects results, but does NOT validate `expected_output` → `expected_input` postconditions between steps. | AD-535 (Graduated Compilation) is the proper home for per-step postcondition validation. AD-534c focuses on the dispatch mechanism. |
| 7 | **Role-to-agent resolution: extraction-time mapping + runtime fallback chain.** | Three-stage resolution: (a) `resolved_agent_type` stored at extraction time, (b) `AgentRegistry.get_by_pool()` at runtime, (c) `AgentRegistry.get_by_capability()` fuzzy fallback. If all fail → single-agent degradation. |

## Part 0 — ProcedureStep.resolved_agent_type Field

**File:** `src/probos/cognitive/procedures.py`

Add a new field to `ProcedureStep` (after `agent_role` at line 40):

```python
resolved_agent_type: str = ""  # AD-534c: concrete agent_type for dispatch, "" = unresolved
```

This field is populated at extraction time when `origin_agent_ids` are available, and consumed at replay time for dispatch routing.

**Update `_build_steps_from_data()`** (line 518) to parse the new field:
```python
resolved_agent_type=s.get("resolved_agent_type", ""),
```

**Update `to_dict()`** on ProcedureStep to include the new field.

**Update `extract_compound_procedure_from_cluster()`** (line 856): After steps are built, resolve each step's `agent_role` to a concrete `agent_type`. The function already receives `cluster` which has `participating_agents` (list of agent IDs). Agent IDs encode the agent type (they follow the pattern `{agent_type}-{uuid}`). Map from `agent_role` → best-matching `agent_type` from the cluster's participating agents.

Add a helper function:

```python
def _resolve_agent_roles(
    steps: list[ProcedureStep],
    participating_agent_ids: list[str],
) -> list[ProcedureStep]:
    """Map agent_role strings to concrete agent_types using cluster participant info.

    Agent IDs encode their type: 'security-abc123' → agent_type='security'.
    Builds a {agent_id_prefix: agent_type} map from participating_agent_ids,
    then uses fuzzy token matching to map each step's agent_role to the best
    matching agent_type.

    Steps with empty agent_role or no match get resolved_agent_type = "".
    """
```

The matching strategy: tokenize both `agent_role` (e.g., `"security_analysis"` → `{"security", "analysis"}`) and each `agent_type` (e.g., `"security_officer"` → `{"security", "officer"}`). Best overlap wins. This is simple, deterministic, and zero-cost.

## Part 1 — Compound Procedure Detection in _check_procedural_memory()

**File:** `src/probos/cognitive/cognitive_agent.py`

In `_check_procedural_memory()`, after the procedure is loaded and `_format_procedure_replay()` is called (around line 222), add compound detection logic:

```python
# AD-534c: detect compound procedure (any step has agent_role set)
is_compound = any(
    getattr(step, "agent_role", "") for step in procedure.steps
)
```

When `is_compound` is True, add a key to the returned decision dict:

```python
return {
    "action": "execute",
    "llm_output": replay_output,  # text fallback if compound dispatch fails
    "cached": True,
    "procedure_id": procedure.id,
    "procedure_name": procedure.name,
    "compound": True,  # AD-534c
    "procedure": procedure,  # AD-534c: needed for step dispatch
}
```

When `is_compound` is False, return the existing dict (no `"compound"` key, no `"procedure"` key).

## Part 2 — _execute_compound_replay() Method

**File:** `src/probos/cognitive/cognitive_agent.py`

Add a new method on `CognitiveAgent`:

```python
async def _execute_compound_replay(
    self, procedure: Any, text_fallback: str
) -> dict:
    """AD-534c: Dispatch compound procedure steps to appropriate agents.

    Resolves each step's agent_role to a live agent via:
      1. resolved_agent_type → AgentRegistry.get_by_pool()
      2. Fallback: agent_role → AgentRegistry.get_by_capability()
      3. If resolution fails for ANY step → degrade to single-agent text replay

    Dispatches steps sequentially via IntentBus.send() with
    'compound_step_replay' intent. Target agents receive pre-formatted
    step text and return it (zero tokens).

    Returns:
        dict with "success", "result" (assembled output),
        "compound_dispatched" (bool), "steps_dispatched" (int)
    """
```

**Resolution logic:**

```python
# Build dispatch plan: list of (step, target_agent_id)
dispatch_plan = []
for step in procedure.steps:
    role = getattr(step, "agent_role", "")
    if not role:
        # No role assigned — this step stays with the orchestrating agent
        dispatch_plan.append((step, None))
        continue

    agent_id = self._resolve_step_agent(step)
    if agent_id is None:
        # Can't resolve — degrade to single-agent text replay
        logger.warning(
            "AD-534c: Cannot resolve agent for role '%s' in procedure '%s'. "
            "Degrading to single-agent replay.",
            role, procedure.name,
        )
        # Record near-miss for AD-534b
        self._last_fallback_info = {
            "procedure_id": procedure.id,
            "procedure_name": procedure.name,
            "rejection_type": "compound_agent_unavailable",
            "rejection_reason": f"No agent available for role '{role}'",
        }
        return {"success": True, "result": text_fallback, "compound_dispatched": False, "steps_dispatched": 0}

    dispatch_plan.append((step, agent_id))
```

**Dispatch loop:**

```python
results = []
for step, target_agent_id in dispatch_plan:
    step_text = self._format_single_step(step)

    if target_agent_id is None:
        # Local step — no dispatch needed
        results.append(step_text)
        continue

    # Dispatch via IntentBus
    intent = IntentMessage(
        intent="compound_step_replay",
        params={
            "step_text": step_text,
            "procedure_id": procedure.id,
            "step_number": step.step_number,
        },
        target_agent_id=target_agent_id,
        ttl_seconds=10.0,
    )

    intent_result = await self._intent_bus.send(intent)

    if intent_result and intent_result.success:
        results.append(intent_result.result or step_text)
    else:
        # Step dispatch failed — degrade to text
        logger.warning(
            "AD-534c: Step %d dispatch to '%s' failed. Using text fallback.",
            step.step_number, target_agent_id,
        )
        results.append(step_text)

assembled = "\n\n".join(results)
return {
    "success": True,
    "result": assembled,
    "compound_dispatched": True,
    "steps_dispatched": sum(1 for _, tid in dispatch_plan if tid is not None),
}
```

## Part 3 — _resolve_step_agent() Helper

**File:** `src/probos/cognitive/cognitive_agent.py`

```python
def _resolve_step_agent(self, step: Any) -> str | None:
    """AD-534c: Resolve a ProcedureStep to a live agent ID.

    Three-stage resolution:
      1. resolved_agent_type → AgentRegistry.get_by_pool()
      2. agent_role → AgentRegistry.get_by_capability() (fuzzy)
      3. Return None if both fail

    Returns the agent_id of a live agent, or None.
    """
```

This method needs access to `AgentRegistry`. The agent already has access to the runtime (via `self._runtime` or similar). Check how existing code accesses the registry — follow the pattern from `proactive.py` or `ward_room_router.py`.

**Stage 1:** If `step.resolved_agent_type` is non-empty, call `registry.get_by_pool(step.resolved_agent_type)`. Return the first live agent's ID.

**Stage 2:** If stage 1 fails, try `registry.get_by_capability(step.agent_role)`. Return the first live agent's ID.

**Stage 3:** Return `None` (triggers single-agent degradation).

**Important:** Skip self — if the resolved agent is the orchestrating agent itself, that step can be executed locally (append `None` to dispatch plan, same as no-role steps).

## Part 4 — _format_single_step() Helper

**File:** `src/probos/cognitive/cognitive_agent.py`

Extract single-step formatting from `_format_procedure_replay()` (lines 275-290) into a reusable helper:

```python
def _format_single_step(self, step: Any) -> str:
    """AD-534c: Format a single ProcedureStep for dispatch or local replay."""
    role = getattr(step, "agent_role", "")
    if role:
        line = f"**Step {step.step_number} [{role}]:** {step.action}"
    else:
        line = f"**Step {step.step_number}:** {step.action}"

    if getattr(step, "expected_output", ""):
        line += f"\n  Expected: {step.expected_output}"

    return line
```

Update `_format_procedure_replay()` to use `_format_single_step()` internally (DRY).

## Part 5 — compound_step_replay Intent Handler

**File:** `src/probos/cognitive/cognitive_agent.py`

Add `"compound_step_replay"` to `CognitiveAgent._handled_intents` (or whatever the intent registration mechanism is).

Add a handler method:

```python
async def _handle_compound_step_replay(self, intent: IntentMessage) -> IntentResult:
    """AD-534c: Handle a dispatched compound procedure step.

    Zero-token operation — receives pre-formatted step text and returns it.
    No LLM invocation. The orchestrating agent formatted the step;
    this agent acknowledges receipt and returns the content.
    """
    step_text = intent.params.get("step_text", "")
    procedure_id = intent.params.get("procedure_id", "")
    step_number = intent.params.get("step_number", 0)

    logger.debug(
        "AD-534c: Agent %s received compound step %d from procedure %s",
        self.id, step_number, procedure_id,
    )

    return IntentResult(
        intent_id=intent.id,
        agent_id=self.id,
        success=True,
        result=step_text,
        confidence=1.0,
    )
```

**Wiring:** Ensure this handler is invoked when the agent receives a `compound_step_replay` intent via IntentBus.send(). Check how existing intent handlers are wired — likely through the `handle_intent()` method's dispatch logic or through `IntentBus.subscribe()`.

If CognitiveAgent uses a dispatch table or if-chain in `handle_intent()`, add a branch for `compound_step_replay` that calls `_handle_compound_step_replay()` and returns early (bypassing decide/act/report flow).

## Part 6 — Integration in handle_intent()

**File:** `src/probos/cognitive/cognitive_agent.py`

In `handle_intent()` (line 687), after `decide()` returns a decision dict, check for compound dispatch:

```python
decision = await self.decide(observation)

# AD-534c: compound procedure dispatch
if decision.get("compound") and decision.get("procedure"):
    compound_result = await self._execute_compound_replay(
        decision["procedure"], decision.get("llm_output", "")
    )

    if compound_result.get("compound_dispatched"):
        # Record completion via procedure store (AD-534b metrics)
        if hasattr(self, "_procedure_store") and self._procedure_store:
            await self._procedure_store.record_completion(decision["procedure_id"])

        # Emit task execution event (AD-532e)
        # ... (follow existing pattern at lines 768-779)

        return IntentResult(
            intent_id=intent.id,
            agent_id=self.id,
            success=True,
            result=compound_result["result"],
            confidence=1.0,
        )
    # else: compound_dispatched=False means degradation occurred,
    # compound_result["result"] is the text fallback — continue with
    # normal act() flow using it as llm_output
    decision["llm_output"] = compound_result["result"]
    decision["compound"] = False  # prevent re-entry

# existing act() call
result = await self.act(decision)
```

## Part 7 — IntentBus Access

**File:** `src/probos/cognitive/cognitive_agent.py`

`_execute_compound_replay()` needs access to `IntentBus` and `AgentRegistry`. Check how CognitiveAgent currently gets these — likely via the runtime or via constructor injection.

If not already available, add optional constructor parameters:

```python
def __init__(self, ..., intent_bus=None, agent_registry=None):
    ...
    self._intent_bus = intent_bus
    self._agent_registry = agent_registry
```

Update the startup wiring (wherever CognitiveAgent instances are created) to pass these. Follow the existing pattern from how `procedure_store` was wired.

**Guard:** If `self._intent_bus` is None or `self._agent_registry` is None, compound dispatch is not available — degrade to single-agent text replay with a debug log.

## Part 8 — Config Constants

**File:** `src/probos/config.py`

Add after the AD-534b section (after line 59):

```python
# AD-534c: Multi-agent replay dispatch
COMPOUND_STEP_TIMEOUT_SECONDS: float = 10.0  # Per-step dispatch timeout
```

Use this constant as the `ttl_seconds` on the dispatched `IntentMessage` instead of a hardcoded `10.0`.

## Part 9 — Tests

**File:** `tests/test_multi_agent_replay_dispatch.py` (NEW)

### Test Class 1: TestResolvedAgentType (8 tests)

1. `test_procedure_step_resolved_agent_type_default` — Default is `""`.
2. `test_procedure_step_resolved_agent_type_set` — Can set a value.
3. `test_procedure_step_to_dict_includes_resolved_agent_type` — `to_dict()` includes it.
4. `test_build_steps_from_data_parses_resolved_agent_type` — `_build_steps_from_data()` parses it.
5. `test_build_steps_from_data_missing_resolved_agent_type` — Backward compat: missing field → `""`.
6. `test_procedure_round_trip_with_resolved_agent_type` — `to_dict()`/`from_dict()` round-trip preserves it.
7. `test_resolve_agent_roles_basic` — `_resolve_agent_roles()` maps `"security_analysis"` to agent_type `"security_officer"` from `["security_officer-abc", "engineering_officer-def"]`.
8. `test_resolve_agent_roles_no_match` — Unresolvable role gets `resolved_agent_type=""`.

### Test Class 2: TestCompoundDetection (5 tests)

1. `test_compound_detected_when_steps_have_roles` — `_check_procedural_memory()` sets `decision["compound"]=True` and includes `decision["procedure"]` when any step has `agent_role`.
2. `test_not_compound_when_no_roles` — Normal procedure (no `agent_role` on any step) returns decision without `"compound"` key.
3. `test_compound_not_detected_empty_roles` — Steps with `agent_role=""` are not compound.
4. `test_mixed_roles_still_compound` — If even one step has `agent_role`, the procedure is compound.
5. `test_compound_decision_includes_procedure_object` — The decision dict contains the actual `Procedure` object under `"procedure"` key.

### Test Class 3: TestResolveStepAgent (7 tests)

1. `test_resolve_by_resolved_agent_type` — Stage 1: `resolved_agent_type="security_officer"` → finds agent via `get_by_pool()`.
2. `test_resolve_by_capability_fallback` — Stage 2: `resolved_agent_type=""`, `agent_role="security_analysis"` → finds agent via `get_by_capability()`.
3. `test_resolve_returns_none_on_failure` — Stage 3: no match from either stage → returns `None`.
4. `test_resolve_skips_self` — If the resolved agent is the orchestrating agent itself, returns `None` (step stays local).
5. `test_resolve_picks_live_agent` — Among multiple agents in pool, picks one that `is_alive`.
6. `test_resolve_no_registry_returns_none` — If `_agent_registry` is None, returns `None`.
7. `test_resolve_empty_pool_returns_none` — Pool exists but is empty → falls through to capability check.

### Test Class 4: TestExecuteCompoundReplay (10 tests)

1. `test_compound_replay_dispatches_steps` — Two steps with different roles → two IntentBus.send() calls → assembled result.
2. `test_compound_replay_local_steps` — Steps without `agent_role` execute locally (no dispatch).
3. `test_compound_replay_mixed_local_and_remote` — Mix of local and dispatched steps.
4. `test_compound_replay_degradation_on_unavailable_agent` — Agent resolution fails → returns `compound_dispatched=False`, uses text fallback.
5. `test_compound_replay_step_dispatch_failure` — IntentBus.send() returns failure → uses step text as fallback (does NOT degrade entire replay).
6. `test_compound_replay_no_intent_bus` — `_intent_bus` is None → degrades to text fallback.
7. `test_compound_replay_no_registry` — `_agent_registry` is None → degrades to text fallback.
8. `test_compound_replay_zero_tokens` — Verify that dispatched steps do NOT trigger any LLM calls on receiving agents. Mock LLM client should have zero invocations.
9. `test_compound_replay_result_assembly` — Step results are joined with `"\n\n"`.
10. `test_compound_replay_steps_dispatched_count` — `steps_dispatched` count reflects actual dispatches (not local steps).

### Test Class 5: TestCompoundStepReplayHandler (5 tests)

1. `test_handler_returns_step_text` — Receives step text, returns it in IntentResult.
2. `test_handler_success_true` — IntentResult.success is True.
3. `test_handler_confidence_one` — IntentResult.confidence is 1.0.
4. `test_handler_preserves_procedure_id` — Params include procedure_id.
5. `test_handler_no_llm_invocation` — Mock LLM client has zero calls after handler executes.

### Test Class 6: TestHandleIntentCompound (8 tests)

1. `test_handle_intent_compound_dispatch_success` — Compound procedure dispatches successfully, returns IntentResult with assembled text.
2. `test_handle_intent_compound_records_completion` — `record_completion()` called on procedure store after successful compound dispatch.
3. `test_handle_intent_compound_emits_task_event` — `TASK_EXECUTION_COMPLETE` event emitted after compound dispatch.
4. `test_handle_intent_compound_degradation_falls_through` — Degradation (compound_dispatched=False) falls through to normal act() with text fallback.
5. `test_handle_intent_compound_degradation_records_fallback` — Degradation records near-miss fallback info.
6. `test_handle_intent_non_compound_unchanged` — Non-compound procedures follow existing code path (no compound branch).
7. `test_handle_intent_compound_step_replay_intent` — Receiving agent handles `compound_step_replay` intent correctly (bypasses decide/act).
8. `test_handle_intent_compound_step_replay_early_return` — `compound_step_replay` handler returns early, does NOT run decide()/act().

### Test Class 7: TestFormatSingleStep (4 tests)

1. `test_format_with_role` — Role annotation `[role]` appears.
2. `test_format_without_role` — No brackets when role is empty.
3. `test_format_with_expected_output` — Expected output appended.
4. `test_format_without_expected_output` — No "Expected:" line when empty.

### Test Class 8: TestFormatProcedureReplayDRY (3 tests)

1. `test_format_replay_uses_format_single_step` — `_format_procedure_replay()` delegates to `_format_single_step()`.
2. `test_format_replay_compound_output_unchanged` — Output matches existing tests (backward compat).
3. `test_format_replay_non_compound_output_unchanged` — Non-compound procedures format identically to before.

### Test Class 9: TestCompoundReplayEndToEnd (4 tests)

1. `test_end_to_end_extract_store_replay_dispatch` — Extract compound procedure from cluster → save to store → match via find_matching → detect compound → dispatch steps → assembled result.
2. `test_end_to_end_degradation_to_single_agent` — Same pipeline but target agent unavailable → single-agent text replay.
3. `test_end_to_end_near_miss_capture_on_degradation` — Degradation records `compound_agent_unavailable` near-miss type.
4. `test_end_to_end_config_timeout` — Dispatched intents use `COMPOUND_STEP_TIMEOUT_SECONDS` from config.

**Total: 54 tests across 9 test classes.**

## Deferred to AD-535 (Graduated Compilation)

The following are explicitly NOT in scope for AD-534c:

1. **Step postcondition validation** — `expected_output` and `expected_input` fields exist on ProcedureStep but are not validated during dispatch. AD-535 introduces per-step execution with postcondition checks.
2. **Step-level fallback** — If a step fails postcondition validation, AD-535 determines whether to retry, skip, or abort. AD-534c has a simpler model: dispatch failure → use step text, agent unavailability → degrade entire compound.
3. **Compilation levels for compound procedures** — AD-535 raises `PROCEDURE_MIN_COMPILATION_LEVEL` requirements and adds trust-gated promotion criteria. AD-534c works at compilation_level=1.
4. **Cross-step result threading** — Step N's output feeding Step N+1's input with validation is AD-535 territory.

## Files Modified

| File | What Changes |
|------|-------------|
| `src/probos/cognitive/procedures.py` | `ProcedureStep.resolved_agent_type` field, `_resolve_agent_roles()` helper, update `_build_steps_from_data()` and `to_dict()`, update `extract_compound_procedure_from_cluster()` |
| `src/probos/cognitive/cognitive_agent.py` | Compound detection in `_check_procedural_memory()`, `_execute_compound_replay()`, `_resolve_step_agent()`, `_format_single_step()`, `_handle_compound_step_replay()`, `handle_intent()` compound branch, `_intent_bus`/`_agent_registry` access |
| `src/probos/config.py` | `COMPOUND_STEP_TIMEOUT_SECONDS` constant |

## Files Created

| File | What |
|------|------|
| `tests/test_multi_agent_replay_dispatch.py` | 54 tests across 9 test classes |

## Validation Checklist

### Part 0 — ProcedureStep.resolved_agent_type
- [ ] Field exists with default `""`
- [ ] `to_dict()` includes it
- [ ] `_build_steps_from_data()` parses it with backward compat (missing → `""`)
- [ ] `from_dict()` round-trip preserves it
- [ ] `_resolve_agent_roles()` maps roles to agent_types using token overlap
- [ ] `_resolve_agent_roles()` handles empty roles gracefully (leaves `""`)
- [ ] `_resolve_agent_roles()` handles no-match gracefully (leaves `""`)
- [ ] `extract_compound_procedure_from_cluster()` calls `_resolve_agent_roles()` after step extraction

### Part 1 — Compound Detection
- [ ] `_check_procedural_memory()` detects compound procedures (any step has non-empty `agent_role`)
- [ ] Compound decision dict includes `"compound": True` and `"procedure"` object
- [ ] Non-compound procedures do NOT have `"compound"` key
- [ ] Empty `agent_role=""` is NOT treated as compound

### Part 2 — _execute_compound_replay()
- [ ] Builds dispatch plan mapping steps to target agents
- [ ] Local steps (no role) stay with orchestrating agent
- [ ] Remote steps dispatched via IntentBus.send()
- [ ] Agent unavailability → degrade to single-agent text replay
- [ ] Sets `_last_fallback_info` on degradation (near-miss capture)
- [ ] Returns `compound_dispatched` flag and `steps_dispatched` count
- [ ] Step dispatch failure → uses step text, does NOT abort entire replay
- [ ] Results assembled with `"\n\n"` join

### Part 3 — _resolve_step_agent()
- [ ] Stage 1: `resolved_agent_type` → `get_by_pool()` → first live agent
- [ ] Stage 2: `agent_role` → `get_by_capability()` → first live agent
- [ ] Stage 3: both fail → returns None
- [ ] Skips self (orchestrating agent)
- [ ] Handles None registry gracefully

### Part 4 — _format_single_step()
- [ ] Extracted from `_format_procedure_replay()`
- [ ] `_format_procedure_replay()` uses it (DRY)
- [ ] Backward compatible — existing test output unchanged

### Part 5 — compound_step_replay Handler
- [ ] Handler registered for `compound_step_replay` intent
- [ ] Returns step text in IntentResult
- [ ] Zero LLM calls
- [ ] Bypasses decide()/act() flow

### Part 6 — handle_intent() Integration
- [ ] Compound branch after decide(), before act()
- [ ] Successful compound dispatch records completion + emits event
- [ ] Degradation falls through to normal act() with text fallback
- [ ] Non-compound procedures follow existing path unchanged

### Part 7 — Wiring
- [ ] `_intent_bus` accessible on CognitiveAgent
- [ ] `_agent_registry` accessible on CognitiveAgent
- [ ] Missing bus/registry → graceful degradation (debug log, text replay)
- [ ] Startup wiring passes intent_bus and registry to CognitiveAgent instances

### Part 8 — Config
- [ ] `COMPOUND_STEP_TIMEOUT_SECONDS = 10.0` in config.py
- [ ] Used as `ttl_seconds` in dispatched IntentMessage

### General
- [ ] All 54 tests pass
- [ ] Existing compound procedure tests still pass (`test_compound_procedures.py`)
- [ ] Existing replay dispatch tests still pass (`test_replay_dispatch.py`)
- [ ] Existing fallback learning tests still pass (`test_fallback_learning.py`)
- [ ] No LLM calls on receiving agents during compound replay
- [ ] `_format_procedure_replay()` output unchanged (backward compat)
- [ ] Full regression suite green (excluding pre-existing worker crashes)
