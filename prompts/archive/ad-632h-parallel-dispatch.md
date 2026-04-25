# AD-632h: Parallel Sub-Task Dispatch

## Context

AD-632h is the final sub-AD in the Cognitive Sub-Task Protocol umbrella (AD-632). It adds
parallel execution of independent sub-task steps within chains. When steps have no data
dependencies on each other (e.g., EVALUATE and REFLECT both depend only on COMPOSE output),
they should be dispatched concurrently via `asyncio.gather()` to reduce wall-clock latency.

This closes the loop on the three-level cognitive escalation model:
- Level 1: Cognitive JIT replay (0 LLM calls)
- Level 2: Single-call LLM reasoning (1 call)
- Level 3: Sub-task protocol (2-4 focused calls, now with parallelism)

## Prior Work to Build On

1. **Sub-task executor** (`sub_task.py:245-343`): `_execute_steps()` iterates sequentially over
   `chain.steps`. Each handler receives `(spec, step_context, list(results))`. Journal recorded
   per step with `dag_node_id = st:{chain_id}:{step_index}:{type}`.
2. **SubTaskSpec** (`sub_task.py:42-51`): Frozen dataclass with `sub_task_type`, `name`,
   `prompt_template`, `context_keys`, `tier`, `timeout_ms`, `required`. **No** `depends_on`
   field currently.
3. **Existing chains** (`cognitive_agent.py:1487-1553`): Both `ward_room_notification` and
   `proactive_think` use `QUERY → ANALYZE → COMPOSE → EVALUATE(opt) → REFLECT(opt)`.
   EVALUATE and REFLECT are independent of each other — both only need COMPOSE output.
4. **Transporter Pattern** (`builder.py:~938-1006`): Wave-based parallel execution via
   `asyncio.gather()`. `ChunkSpec.depends_on: list[str]` + `get_ready_chunks(completed)`.
   This is the established codebase pattern for DAG-based parallelism.
5. **TaskDAG** (`types.py:269-295`): `TaskNode.depends_on: list[str]` + `get_ready_nodes()`.
   Same wave pattern used in decomposer for intent-level parallelism.
6. **LLM rate limiting** (`llm_client.py:142`): AD-617 per-tier token bucket rate limiter
   already governs concurrent LLM requests. No duplicate rate limiting needed in the executor.
7. **SubTaskChainCompletedEvent** (`events.py:697-710`): Already tracks `total_duration_ms`
   as wall-clock time. Parallelism naturally reduces this without event changes.
8. **Handler protocol** (`sub_task.py:80-93`): `SubTaskHandler.__call__(spec, context,
   prior_results)` — for parallel steps in the same wave, they receive the same
   `prior_results` snapshot (all results from completed waves).

## Key Design Decisions

### Dependency model: explicit `depends_on` vs. implicit ordering

Use **explicit `depends_on`** on `SubTaskSpec`, matching the `ChunkSpec` and `TaskNode` patterns
already in the codebase. Steps with no `depends_on` entries are treated as depending on all prior
steps (backward compatibility — existing chains without `depends_on` remain sequential).

### Wave execution model

Same pattern as Transporter and TaskDAG: collect ready steps (dependencies satisfied) → dispatch
wave via `asyncio.gather()` → collect results → repeat. This is the established codebase
convention — no novel execution model needed.

### What can run in parallel today?

Current chains: `QUERY → ANALYZE → COMPOSE → [EVALUATE ‖ REFLECT]`

- QUERY: no dependencies (always wave 1)
- ANALYZE: depends on QUERY
- COMPOSE: depends on ANALYZE
- EVALUATE: depends on COMPOSE only
- REFLECT: depends on COMPOSE only
- EVALUATE and REFLECT are **independent** — same wave

This saves one LLM call's worth of wall-clock time per chain (EVALUATE and REFLECT run
concurrently instead of sequentially). For a 15s timeout per step, that's up to 15s saved.

### Rate limiting

LLMClient (AD-617) already has per-tier token bucket rate limiting. Two concurrent LLM calls
from the same chain will naturally be governed. No executor-level rate limiting needed.

### Failure handling in parallel waves

If a **required** step fails in a parallel wave, all results from the wave are still collected
(don't cancel siblings — `asyncio.gather(return_exceptions=True)`), but the chain aborts after
the wave completes. Optional step failures in a parallel wave don't abort.

### Journal recording for parallel steps

Parallel steps in the same wave get different `step_index` values (their position in the
original `chain.steps` list, not their wave position). Journal `dag_node_id` format is unchanged:
`st:{chain_id}:{step_index}:{type}`. This preserves the ordering semantics even though execution
was concurrent.

## Engineering Principles

- **SOLID-O**: Extend `_execute_steps()` behavior, not modify-and-break. Existing sequential
  chains (no `depends_on`) produce identical results.
- **SOLID-S**: Step readiness computation is a separate function (`_get_ready_steps()`), not
  inlined in the execution loop.
- **DRY**: Reuse the established wave+gather pattern from Transporter/TaskDAG. Don't invent a
  new parallel execution model.
- **Law of Demeter**: Steps declare dependencies by name, not by reaching into other steps'
  internals.
- **Fail Fast**: Required step failure in a wave → chain aborts after wave completes. Don't
  silently continue.
- **Defense in Depth**: Validate `depends_on` references at chain construction time (fail early
  if a step depends on a non-existent step name). Also validate no cycles.
- **Backward Compatibility**: Chains without `depends_on` produce identical sequential behavior.

## Implementation

### File 1: `src/probos/cognitive/sub_task.py` — Parallel Executor

**1a. Add `depends_on` to `SubTaskSpec`** (line 51):

```python
@dataclass(frozen=True)
class SubTaskSpec:
    """Specification for a single sub-task step."""
    sub_task_type: SubTaskType
    name: str                           # Human-readable label ("analyze-thread")
    prompt_template: str = ""           # Template for LLM sub-tasks (QUERY has none)
    context_keys: tuple[str, ...] = ()  # Keys to extract from parent context
    tier: str = "standard"              # LLM tier override for this step
    timeout_ms: int = 15000             # Per-step timeout (15s default)
    required: bool = True               # If True, failure aborts chain
    depends_on: tuple[str, ...] = ()    # NEW: Step names this step depends on
```

**1b. Add `validate_chain()` function** — validates chain before execution:

```python
def validate_chain(chain: SubTaskChain) -> list[str]:
    """Validate chain step dependencies. Returns list of errors (empty = valid).

    Checks:
    1. All depends_on references point to existing step names
    2. No circular dependencies
    3. No self-references
    """
```

Logic:
1. Build a set of all step names. Check each `depends_on` entry exists in the set.
2. Check no step depends on itself.
3. Topological sort (Kahn's algorithm — already used in `BuildBlueprint.validate_chunk_dag()`).
   If the sorted count != step count, there's a cycle.
4. Return error strings for any violations.

**1c. Add `_get_ready_steps()` method** on `SubTaskExecutor`:

```python
def _get_ready_steps(
    self,
    chain: SubTaskChain,
    completed: set[str],
) -> list[tuple[int, SubTaskSpec]]:
    """Return steps whose dependencies are all satisfied.

    Returns list of (original_step_index, spec) tuples.
    Steps with empty depends_on AND no explicit dependencies default to
    depending on all prior steps (backward compatibility).
    """
```

Logic:
1. For each step not yet completed:
   - If `spec.depends_on` is non-empty: ready if all named deps are in `completed`
   - If `spec.depends_on` is empty (default): ready if ALL steps before it in the list are in
     `completed` (preserves sequential behavior for existing chains)
2. Return ready steps as `(step_index, spec)` tuples.

**1d. Modify `_execute_steps()`** — wave-based execution:

Replace the sequential `for step_index, spec in enumerate(chain.steps):` loop with:

```python
async def _execute_steps(self, chain, context, chain_id, results, *, 
                         agent_id, agent_type, intent, intent_id, journal):
    """Execute steps respecting dependencies. Independent steps run in parallel."""
    completed: set[str] = set()
    results_by_name: dict[str, SubTaskResult] = {}
    has_explicit_deps = any(spec.depends_on for spec in chain.steps)
    
    while len(completed) < len(chain.steps):
        ready = self._get_ready_steps(chain, completed)
        if not ready:
            # Deadlock — deps can't be satisfied (validation should catch this)
            break
        
        if len(ready) == 1:
            # Single step — execute directly (no gather overhead)
            step_index, spec = ready[0]
            result = await self._execute_single_step(
                spec, step_index, context, list(results),
                chain_id=chain_id, agent_id=agent_id, agent_type=agent_type,
                intent=intent, intent_id=intent_id, journal=journal,
            )
            results.append(result)
            results_by_name[spec.name] = result
            completed.add(spec.name)
            if not result.success and spec.required:
                raise SubTaskStepError(spec.name, spec.sub_task_type, result.error)
        else:
            # Multiple ready steps — parallel dispatch
            prior = list(results)  # Snapshot for all parallel handlers
            wave_tasks = [
                self._execute_single_step(
                    spec, step_index, context, prior,
                    chain_id=chain_id, agent_id=agent_id, agent_type=agent_type,
                    intent=intent, intent_id=intent_id, journal=journal,
                )
                for step_index, spec in ready
            ]
            wave_results = await asyncio.gather(*wave_tasks, return_exceptions=True)
            
            # Process wave results
            required_failure = None
            for (step_index, spec), result in zip(ready, wave_results):
                if isinstance(result, Exception):
                    if isinstance(result, SubTaskStepError):
                        if spec.required:
                            required_failure = result
                        result = SubTaskResult(
                            sub_task_type=spec.sub_task_type, name=spec.name,
                            success=False, error=str(result),
                        )
                    else:
                        if spec.required:
                            required_failure = SubTaskStepError(
                                spec.name, spec.sub_task_type, str(result),
                            )
                        result = SubTaskResult(
                            sub_task_type=spec.sub_task_type, name=spec.name,
                            success=False, error=str(result),
                        )
                results.append(result)
                results_by_name[spec.name] = result
                completed.add(spec.name)
            
            if required_failure is not None:
                raise required_failure
```

**1e. Extract `_execute_single_step()`** — refactor from the existing step execution body:

```python
async def _execute_single_step(
    self,
    spec: SubTaskSpec,
    step_index: int,
    context: dict,
    prior_results: list[SubTaskResult],
    *,
    chain_id: str,
    agent_id: str,
    agent_type: str,
    intent: str,
    intent_id: str,
    journal: Any | None,
) -> SubTaskResult:
    """Execute a single sub-task step with context filtering, timeout, and journal recording."""
```

This extracts the existing per-step body (lines 260-342) into its own method. Content is
identical — handler lookup, context filtering, `asyncio.wait_for()`, timeout handling,
optional step failure handling, journal recording. No behavior change for sequential execution.

**1f. Add validation call in `execute()`**: Before `_execute_steps()`, call `validate_chain()`.
If errors, log warning and fall through (fail-open — don't block execution for validation
errors, just warn). This follows the fail-open pattern used in AD-632e.

### File 2: `src/probos/cognitive/cognitive_agent.py` — Chain Dependency Declarations

**In `_build_chain_for_intent()`** (line 1478), add `depends_on` to EVALUATE and REFLECT steps:

For `ward_room_notification` chain:
```python
SubTaskSpec(
    sub_task_type=SubTaskType.EVALUATE,
    name="evaluate-reply",
    prompt_template="ward_room_quality",
    required=False,
    depends_on=("compose-reply",),        # NEW
),
SubTaskSpec(
    sub_task_type=SubTaskType.REFLECT,
    name="reflect-reply",
    prompt_template="ward_room_reflection",
    required=False,
    depends_on=("compose-reply",),        # NEW
),
```

For `proactive_think` chain:
```python
SubTaskSpec(
    sub_task_type=SubTaskType.EVALUATE,
    name="evaluate-observation",
    prompt_template="proactive_quality",
    required=False,
    depends_on=("compose-observation",),  # NEW
),
SubTaskSpec(
    sub_task_type=SubTaskType.REFLECT,
    name="reflect-observation",
    prompt_template="proactive_reflection",
    required=False,
    depends_on=("compose-observation",),  # NEW
),
```

QUERY, ANALYZE, and COMPOSE keep `depends_on=()` (empty) — backward-compatible sequential
behavior since they have no explicit deps and default to "depends on all prior steps".

### File 3: No changes to `events.py`, `startup/`, or `dreaming.py`

- `SubTaskChainCompletedEvent` already reports wall-clock `total_duration_ms` — parallelism
  naturally reduces this.
- No new events needed — parallelism is an executor optimization, not a new capability.
- No startup wiring changes — executor is already wired.

## What This Does NOT Do

1. **No new chain types** — uses existing chains with dependency annotations
2. **No executor-level rate limiting** — LLMClient AD-617 handles this
3. **No changes to chain completion events** — wall-clock savings visible automatically
4. **No changes to `_execute_sub_task_chain()`** — executor API unchanged
5. **No changes to handler protocol** — handlers are unaware of parallelism
6. **No changes to AD-632g chain metadata** — `chain_source`, `chain_steps` unaffected
7. **No speculative parallelism** — only explicitly declared independent steps run in parallel

## Tests — `tests/test_ad632h_parallel_dispatch.py`

Target: 25-35 tests across 6 classes.

### Class 1: TestDependsOnField (4 tests)
- SubTaskSpec with `depends_on=()` creates successfully (default)
- SubTaskSpec with `depends_on=("step-a",)` creates successfully
- SubTaskSpec is frozen (immutable)
- `depends_on` serializes to tuple (not list)

### Class 2: TestChainValidation (5 tests)
- Valid chain (linear deps) → no errors
- Valid chain (parallel EVALUATE + REFLECT) → no errors
- Invalid: depends_on references non-existent step → error
- Invalid: circular dependency (A→B, B→A) → error
- Invalid: self-reference → error

### Class 3: TestGetReadySteps (6 tests)
- No deps (empty `depends_on` on all steps) → sequential: first step ready, then second, etc.
- Explicit deps: EVALUATE + REFLECT both depend on COMPOSE → both ready after COMPOSE completes
- Mixed: some steps with deps, some without → correct readiness
- All steps completed → returns empty list
- No steps completed, first step has no deps → first step ready
- Chain with `depends_on` only on later steps, early steps have none → early steps sequential

### Class 4: TestParallelExecution (6 tests)
- EVALUATE and REFLECT run concurrently (measure wall-clock: should be ~1x step time, not 2x)
- Sequential chain (no `depends_on`) → identical behavior to pre-632h
- Single-step wave → no `asyncio.gather` overhead (direct execution)
- Parallel steps receive same `prior_results` snapshot
- Three-step parallel wave works correctly
- Wave execution order: QUERY → ANALYZE → COMPOSE → [EVALUATE ‖ REFLECT]

### Class 5: TestParallelFailureHandling (5 tests)
- Required step fails in parallel wave → chain aborts after wave completes
- Optional step fails in parallel wave → chain continues
- Both parallel steps fail (one required, one optional) → required failure raised
- Exception in parallel step → converted to SubTaskResult with `success=False`
- `SubTaskStepError` in parallel step → re-raised correctly as chain error

### Class 6: TestParallelJournalRecording (4 tests)
- Parallel steps get correct `step_index` (original list position, not wave position)
- `dag_node_id` format unchanged: `st:{chain_id}:{step_index}:{type}`
- Journal records for parallel steps both created (one per step)
- Journal recording failure in one parallel step doesn't affect sibling

### Class 7: TestBackwardCompatibility (4 tests)
- Existing chain (no `depends_on` fields) → executes identically to pre-632h
- Chain with all steps having empty `depends_on` → sequential execution
- `SubTaskChainCompletedEvent` fields unchanged
- Handler protocol signature unchanged (handlers don't see parallelism)

## Acceptance Criteria

1. Independent steps (EVALUATE + REFLECT) execute concurrently via `asyncio.gather()`
2. Dependent steps execute sequentially (wave ordering)
3. Wall-clock `total_duration_ms` reduced for chains with parallel waves
4. Journal `dag_node_id` preserves original step indices
5. Required step failure in parallel wave aborts chain after wave completes
6. Chains without `depends_on` produce identical sequential behavior (backward compatible)
7. Chain validation catches invalid deps (non-existent, circular, self-reference)
8. All new tests pass; existing AD-632a-g test suites unaffected

## Tracking

- **PROGRESS.md**: Add AD-632h status entry
- **DECISIONS.md**: Record parallel dispatch design decisions
- **roadmap.md**: Update AD-632 umbrella (632h COMPLETE) + add standalone AD-632h block
- **GitHub**: Close issue #243 when complete

## Dependencies

- AD-632a (foundation — SubTaskChain, SubTaskSpec, SubTaskExecutor)
- AD-632e (Evaluate + Reflect handlers — the parallel candidates)
- AD-632f (activation triggers — chain.source field)
- AD-617 (LLM rate limiting — governs concurrent LLM calls)
