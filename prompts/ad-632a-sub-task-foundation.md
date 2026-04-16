# AD-632a: Sub-Task Foundation — Protocol, Executor, Journal, Config

**Issue:** #230 (AD-632a), parent umbrella #227 (AD-632)
**Depends on:** AD-631 ✅, AD-625 ✅, AD-626 ✅, AD-596a-e ✅, AD-531-539 ✅
**Absorbs:** `dag_node_id` population (dead column since AD-432 — schema exists,
never written in production)
**Principles:** SRP, Open/Closed, DIP, Law of Demeter, Fail Fast, Defense in Depth

## Problem

ProbOS crew agents handle everything in a single `_decide_via_llm()` call
(cognitive_agent.py line 1176). One LLM invocation must simultaneously:
comprehend the situation, recall relevant context, apply skill instructions,
compose a response, and self-verify — all in a single prompt.

This creates two failure modes:

1. **Cognitive Overload** — when prompt length (context + augmentation skills +
   standing orders + working memory) exceeds the LLM's effective attention
   window, instruction compliance degrades. The LLM quietly drops the lowest-
   salience instructions (typically skill guidance and self-verification).

2. **No Iterative Refinement** — if the single-call output is malformed or low-
   quality, there is no correction loop. The output goes directly to
   `act()` → Ward Room / notebook / DM.

The three-level cognitive escalation model (research:
`docs/research/cognitive-sub-task-protocol.md`) solves this:

| Level | Mechanism | LLM Calls | Status |
|-------|-----------|-----------|--------|
| 1 | Cognitive JIT Replay | 0 | Complete (AD-531-539) |
| 2 | Single-Call Reasoning | 1 | Complete (current) |
| **3** | **Sub-Task Protocol** | **2-4** | **This AD** |

AD-632a builds the **foundation infrastructure** for Level 3. It defines the
protocol, executor engine, journal integration, and configuration. It does NOT
implement specific sub-task handlers (AD-632b-e) or activation triggers
(AD-632f).

## Scope Boundary — What This AD Does and Does NOT Cover

**In scope (AD-632a):**
- `SubTaskType` enum (5 types)
- `SubTaskSpec` frozen dataclass (what to do)
- `SubTaskResult` frozen dataclass (what happened)
- `SubTaskChain` dataclass (ordered spec list + config)
- `SubTaskHandler` protocol (handler function contract)
- `SubTaskExecutor` class (engine that runs chains)
- `_execute_sub_task_chain()` method on CognitiveAgent
- CognitiveJournal recording with `dag_node_id` population
- `SubTaskConfig` in SystemConfig
- `SUB_TASK_COMPLETED` and `SUB_TASK_CHAIN_COMPLETED` events

**Out of scope (deferred):**
- Query handler → AD-632b
- Analyze handler → AD-632c
- Compose handler → AD-632d
- Evaluate/Reflect handlers → AD-632e
- Activation triggers (skill annotation, complexity heuristic, quality
  fallback) → AD-632f
- Cognitive JIT integration (learning from decomposition) → AD-632g
- Parallel sub-task dispatch → AD-632h

## Design

### 1. New File: `src/probos/cognitive/sub_task.py`

Contains all sub-task protocol infrastructure.

#### SubTaskType Enum

```python
class SubTaskType(str, Enum):
    """Five sub-task types per SOAR + DECOMP synthesis."""
    QUERY = "query"         # Deterministic data retrieval (0 LLM calls)
    ANALYZE = "analyze"     # Focused LLM comprehension (1 call, narrow prompt)
    COMPOSE = "compose"     # LLM response generation with skill (1 call)
    EVALUATE = "evaluate"   # LLM criteria-based quality check (1 call)
    REFLECT = "reflect"     # LLM self-critique (1 call)
```

`str, Enum` for JSON serialization (matches `EventType` pattern in events.py).

#### SubTaskSpec (Frozen Dataclass)

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
```

`frozen=True` because specs are immutable definitions. `context_keys` is a tuple
(not list) for hashability. `tier` allows sub-task-specific tier routing — e.g.,
"fast" for QUERY/EVALUATE, "deep" for COMPOSE — overriding the agent's
`_resolve_tier()`.

#### SubTaskResult (Frozen Dataclass)

```python
@dataclass(frozen=True)
class SubTaskResult:
    """Output of a single sub-task execution."""
    sub_task_type: SubTaskType
    name: str
    result: dict                  # Structured output (handler-specific)
    tokens_used: int = 0          # Prompt + completion tokens
    duration_ms: float = 0.0      # Wall clock time
    success: bool = True
    error: str = ""               # Empty if success, error message if not
    tier_used: str = ""           # Actual LLM tier used
```

Use `dict` for `result` field (not a frozen type) — frozen dataclass with a
mutable field is acceptable here because SubTaskResult is created once and never
mutated. `result` content is handler-defined (AD-632b-e).

#### SubTaskChain (Dataclass)

```python
@dataclass
class SubTaskChain:
    """Ordered sequence of sub-task specifications with execution config."""
    steps: list[SubTaskSpec]
    chain_timeout_ms: int = 30000   # Total chain timeout (30s default)
    fallback: str = "single_call"   # Degradation strategy on failure
    source: str = ""                # What triggered this chain (skill, heuristic, quality)
```

Not frozen — chains may be constructed dynamically by activation triggers
(AD-632f). `fallback` supports only `"single_call"` for now (future: "partial",
"retry").

#### SubTaskHandler Protocol

```python
@runtime_checkable
class SubTaskHandler(Protocol):
    """Contract for sub-task handler functions.

    Handlers receive the sub-task spec, parent observation context, and
    accumulated results from prior steps. They return a SubTaskResult.
    """
    async def __call__(
        self,
        spec: SubTaskSpec,
        context: dict,
        prior_results: list[SubTaskResult],
    ) -> SubTaskResult: ...
```

Follows `typing.Protocol` with `@runtime_checkable` (matches
`StateProvider` in `observable_state.py` line 31). Handlers receive three args:
- `spec`: the step specification
- `context`: parent observation dict (filtered to `spec.context_keys`)
- `prior_results`: results from all preceding steps (enables Analyze→Compose
  data flow)

This is DIP — executor depends on the protocol, not concrete handlers (AD-632b-e
register concrete handlers without modifying the executor).

#### SubTaskExecutor

```python
class SubTaskExecutor:
    """Executes sub-task chains with timeout enforcement, journal recording,
    and fallback on failure.

    Open/Closed: Handlers are registered by type. Adding new sub-task types
    (AD-632b-e) requires zero changes to this class.
    """
```

**Constructor:**
```python
def __init__(
    self,
    *,
    config: SubTaskConfig,
    emit_event_fn: Callable | None = None,
) -> None:
```

Dependencies injected via constructor (DIP, Law of Demeter). The executor
does NOT hold references to `runtime`, `cognitive_journal`, or `llm_client` —
those are passed per-invocation by `CognitiveAgent._execute_sub_task_chain()`.

**Key Methods:**

- `register_handler(sub_task_type: SubTaskType, handler: SubTaskHandler) -> None`
  — stores handler in `_handlers: dict[SubTaskType, SubTaskHandler]`. Raises
  `ValueError` on duplicate registration (fail fast).

- `has_handler(sub_task_type: SubTaskType) -> bool` — checks if a handler is
  registered for this type.

- `can_execute(chain: SubTaskChain) -> bool` — returns True only if ALL
  required steps in the chain have registered handlers. This is the gate
  that keeps the system at Level 2 (single-call) until handlers exist.

- `async execute(chain: SubTaskChain, context: dict, *, agent_id: str, agent_type: str, intent: str, intent_id: str, journal: Any | None = None) -> list[SubTaskResult]`
  — the main execution method:

  1. Validate `can_execute(chain)` — if False, raise `SubTaskChainError`
  2. Start chain timer (`asyncio.wait_for` with `chain.chain_timeout_ms`)
  3. For each step in `chain.steps` (sequential — parallel is AD-632h):
     a. Filter `context` to `spec.context_keys` (if non-empty)
     b. Get handler for `spec.sub_task_type` from `_handlers`
     c. Execute handler via `asyncio.wait_for(handler(...), timeout=spec.timeout_ms / 1000)`
     d. Record to journal if `journal` is provided (see Journal section below)
     e. Append result to `results` list
     f. On failure: if `spec.required`, abort chain and raise `SubTaskStepError`.
        If not required, log warning and continue.
  4. Emit `SUB_TASK_CHAIN_COMPLETED` event if `emit_event_fn` is provided
  5. Return `list[SubTaskResult]`

  Catches `asyncio.TimeoutError` for both per-step and chain-level timeouts.
  Catches `Exception` from handlers (defense in depth).

**Exception Classes:**

```python
class SubTaskError(Exception):
    """Base exception for sub-task protocol."""

class SubTaskChainError(SubTaskError):
    """Chain-level error (missing handlers, chain timeout)."""

class SubTaskStepError(SubTaskError):
    """Step-level error (handler failure, step timeout)."""
    def __init__(self, step_name: str, sub_task_type: SubTaskType, cause: str):
        self.step_name = step_name
        self.sub_task_type = sub_task_type
        self.cause = cause
        super().__init__(f"Sub-task '{step_name}' ({sub_task_type.value}) failed: {cause}")
```

### 2. CognitiveAgent Integration: `cognitive_agent.py`

#### New Method: `_execute_sub_task_chain()`

Add after `_decide_via_llm()` (after line ~1398):

```python
async def _execute_sub_task_chain(
    self,
    chain: SubTaskChain,
    observation: dict,
) -> dict | None:
    """AD-632a: Execute a sub-task chain, falling back to None on failure.

    Returns a decision dict if the chain completes successfully, or None
    to signal the caller to fall through to single-call _decide_via_llm().
    """
```

**Implementation:**

1. Check `self._sub_task_executor` exists and `can_execute(chain)` — return
   `None` if not (silent fallback to single-call, backward compatible).

2. Try executing: `results = await self._sub_task_executor.execute(chain, observation, agent_id=self.id, agent_type=self.agent_type, intent=observation.get("intent", ""), intent_id=observation.get("intent_id", ""), journal=self._cognitive_journal)`

3. On success: construct a decision dict from the chain results. Use the last
   COMPOSE step result's output as `llm_output`, or concatenate all results
   if no COMPOSE step exists. Set `"sub_task_chain": True` on the decision
   for downstream accounting.

4. On any `SubTaskError` or `asyncio.TimeoutError`: log at WARNING level with
   `"AD-632a: Sub-task chain failed, falling back to single-call"` prefix.
   Return `None` to trigger fallback.

5. On unexpected `Exception`: log at ERROR level, return `None` for safety.

**Fallback pattern (Fail Fast + graceful degradation):**

```python
# In decide(), between procedural memory check and _decide_via_llm():
if self._pending_sub_task_chain is not None:
    chain = self._pending_sub_task_chain
    self._pending_sub_task_chain = None  # consume once
    chain_result = await self._execute_sub_task_chain(chain, observation)
    if chain_result is not None:
        # Sub-task chain succeeded — use its output
        # Cache the result (same pattern as _decide_via_llm results)
        cache[cache_key] = (chain_result, time.monotonic(), _cache_ttl)
        return chain_result
    # Chain failed — fall through to single-call
    logger.info("AD-632a: Falling back to single-call for %s", self.agent_type)
```

This integration point is in `decide()` (line 1093), inserted between the
procedural memory check (line 1132) and the `_decide_via_llm()` call (line
1155). This position means:
- Decision cache still checked first (Level 0)
- Procedural memory still checked next (Level 1)
- Sub-task chain checked next (Level 3) — note: Level 3 before Level 2
  because if a chain is pending, it was explicitly requested and takes
  priority over unguided single-call
- Single-call is the fallback (Level 2)

#### New Attribute: `_sub_task_executor`

Add to CognitiveAgent's `__init__` or via a setter method:
```python
self._sub_task_executor: SubTaskExecutor | None = None
self._pending_sub_task_chain: SubTaskChain | None = None
```

The setter follows `set_tool_registry()` pattern (Law of Demeter):
```python
def set_sub_task_executor(self, executor: SubTaskExecutor) -> None:
    """AD-632a: Wire sub-task executor for Level 3 reasoning."""
    self._sub_task_executor = executor
```

`_pending_sub_task_chain` is set by future activation triggers (AD-632f).
In AD-632a, no code sets it — the chain execution path exists but is never
triggered. This is by design (Open/Closed — the Foundation is complete,
activation is a separate AD).

### 3. CognitiveJournal Integration: `dag_node_id` Population

The `dag_node_id` column exists in the journal schema (journal.py line 39)
but has never been written in production (AD-432 placeholder). AD-632a
**absorbs** this gap.

When `SubTaskExecutor.execute()` records sub-task LLM calls to the journal,
it populates `dag_node_id` with a structured identifier:

```
Format: "st:{chain_id}:{step_index}:{sub_task_type}"
Example: "st:a1b2c3d4:0:analyze"
```

- `st:` prefix distinguishes sub-task entries from future DAG node entries
- `chain_id` groups all steps in one chain (first 8 chars of a UUID)
- `step_index` preserves ordering (0-based)
- `sub_task_type` is the SubTaskType value string

The parent call's journal entry (if any) uses `dag_node_id=""` as before.
Parent ↔ sub-task linkage is via shared `intent_id` (already passed through).

This enables:
- `get_reasoning_chain()` queries to include sub-task steps
- `gap_predictor.py` (line 59) to detect per-sub-task-type failure rates
- Future per-step observability dashboards

No schema changes to journal.py. No new columns. Just populating an existing
empty field.

### 4. Config: `SubTaskConfig`

Add to `src/probos/config.py`:

```python
class SubTaskConfig(BaseModel):
    """AD-632a: Sub-task protocol configuration."""

    enabled: bool = False                      # Disabled until handlers exist (AD-632b+)
    chain_timeout_ms: int = 30000              # Default chain timeout (30s)
    step_timeout_ms: int = 15000               # Default per-step timeout (15s)
    max_chain_steps: int = 6                   # Maximum steps per chain (defense in depth)
    fallback_on_timeout: str = "single_call"   # Degradation strategy
```

Register in `SystemConfig` (after line 967):
```python
    sub_task: SubTaskConfig = SubTaskConfig()  # AD-632a
```

### 5. Events: `events.py`

Add two event types to `EventType` enum (after line 156):

```python
    # Sub-task protocol (AD-632a)
    SUB_TASK_COMPLETED = "sub_task_completed"
    SUB_TASK_CHAIN_COMPLETED = "sub_task_chain_completed"
```

Add typed event dataclass:

```python
@dataclass
class SubTaskChainCompletedEvent(BaseEvent):
    """AD-632a: Emitted when a sub-task chain finishes execution."""
    event_type: EventType = field(
        default=EventType.SUB_TASK_CHAIN_COMPLETED, init=False
    )
    agent_id: str = ""
    agent_type: str = ""
    intent: str = ""
    chain_steps: int = 0
    total_tokens: int = 0
    total_duration_ms: float = 0.0
    success: bool = True
    fallback_used: bool = False
    source: str = ""          # What triggered the chain
```

### 6. Startup Wiring

**No wiring needed in AD-632a.** The `SubTaskExecutor` is instantiated and
wired to agents in AD-632f (activation triggers) when the system is ready
to use it. In AD-632a, the executor exists as importable infrastructure but
is not instantiated at startup.

Rationale: with `SubTaskConfig.enabled = False` and no handlers registered,
wiring the executor would add startup work for zero functional value.
AD-632b-e register handlers, AD-632f enables and wires everything.

## Six Invariants

These invariants are enforced by the executor and must be preserved by all
future sub-ADs:

1. **Token Accounting to Parent** — all sub-task tokens are attributed to the
   parent agent's `agent_id` in the journal. Sub-tasks do not have separate
   identity. Token budget checks (AD-617b) see the aggregate.

2. **Episodic Memory Exclusion** — sub-task intermediate results are NOT
   stored as episodic memories. Only the final composite output (from
   `handle_intent()`) becomes an episode. Sub-task reasoning is transient.
   *Enforcement: SubTaskExecutor never calls `episodic.store()`.*

3. **Trust Attribution to Parent** — any trust outcomes from sub-task-composed
   responses are attributed to the parent agent. Sub-tasks have no trust score.
   *Enforcement: no trust calls in SubTaskExecutor.*

4. **Circuit Breaker Isolation** — sub-task LLM calls do NOT increment the
   circuit breaker's event counter. If they did, a 4-step chain would count
   as 4 events, incorrectly triggering velocity-based trips. Only the parent
   intention counts.
   *Enforcement: sub-task calls bypass `CognitiveCircuitBreaker.record_event()`.*

5. **Observability via CognitiveJournal** — every sub-task LLM call is recorded
   in the journal with a structured `dag_node_id`. Token usage, latency, tier,
   and success/failure are individually tracked.

6. **No Nesting (Max Depth 1)** — sub-tasks cannot spawn sub-sub-tasks. The
   executor enforces this by not passing itself to handlers. Handlers receive
   `(spec, context, prior_results)` — no executor reference.

## Engineering Principles Compliance

| Principle | Application |
|-----------|-------------|
| **SRP** | `SubTaskExecutor` has one job: execute chains. Each handler (AD-632b-e) has one job: execute its sub-task type. `SubTaskSpec` defines what, `SubTaskResult` captures output. Clear separation. |
| **Open/Closed** | `SubTaskExecutor.register_handler()` accepts new sub-task types without modifying the executor. AD-632b-e add handlers, AD-632f adds triggers — neither changes `sub_task.py`. |
| **DIP** | Executor depends on `SubTaskHandler` protocol, not concrete implementations. CognitiveAgent depends on `SubTaskExecutor` interface, receives it via setter injection. |
| **Law of Demeter** | SubTaskExecutor does not reach through `runtime` or `agent`. It receives `journal`, `agent_id`, `agent_type` directly. Handlers receive filtered context, not the full agent object. |
| **Fail Fast** | Duplicate handler registration raises `ValueError`. Missing handlers detected by `can_execute()` before execution starts. Required step failure aborts chain immediately. |
| **Defense in Depth** | Three timeout layers: per-step timeout, chain timeout, and `max_chain_steps` cap. Handler exceptions caught and wrapped. Fallback to single-call on any failure. |
| **ISP** | `SubTaskHandler` protocol is narrow — one async `__call__` method with 3 parameters. Handlers don't need to know about the executor, journal, or agent. |

## Files to Create

| File | Content |
|------|---------|
| `src/probos/cognitive/sub_task.py` | SubTaskType, SubTaskSpec, SubTaskResult, SubTaskChain, SubTaskHandler, SubTaskExecutor, exceptions |

## Files to Modify

| File | Change |
|------|--------|
| `src/probos/cognitive/cognitive_agent.py` | Add `_sub_task_executor` attribute, `set_sub_task_executor()` setter, `_execute_sub_task_chain()` method, integration point in `decide()` |
| `src/probos/config.py` | Add `SubTaskConfig`, register in `SystemConfig` |
| `src/probos/events.py` | Add `SUB_TASK_COMPLETED`, `SUB_TASK_CHAIN_COMPLETED` event types and `SubTaskChainCompletedEvent` dataclass |

## Files to Verify (NOT Modify)

| File | Why Verify |
|------|------------|
| `src/probos/cognitive/journal.py` | Confirm `dag_node_id` column exists (line 39), `record()` accepts it (line 165) — no changes needed |
| `src/probos/cognitive/circuit_breaker.py` | Confirm `CognitiveEvent` is separate from journal — sub-tasks must NOT create CognitiveEvents |
| `src/probos/cognitive/procedures.py` | Confirm `ProcedureStep` has `required_tools` field (AD-423c) — future AD-632g will bridge procedures to sub-task chains |
| `src/probos/cognitive/gap_predictor.py` | Confirm it reads `dag_node_id` from episodes (line 127) — populated journal entries will enable gap detection for sub-task types |

## Do NOT Change

- `journal.py` — schema already has `dag_node_id`, no migration needed
- `proactive.py` — sub-task execution is internal to `decide()`, invisible to the proactive loop
- `standing_orders.py` — no standing order changes
- Any skill files — skill-based activation is AD-632f
- `procedures.py` — Cognitive JIT integration is AD-632g
- `decomposer.py` — intent decomposition is a separate system (macro level)

## Test Requirements

### Unit Tests (`tests/test_ad632a_sub_task_foundation.py`)

#### 1. TestSubTaskType (3 tests)
- `test_enum_values` — all 5 types have correct string values
- `test_enum_is_str` — values are JSON-serializable strings
- `test_enum_members` — QUERY, ANALYZE, COMPOSE, EVALUATE, REFLECT exist

#### 2. TestSubTaskSpec (4 tests)
- `test_construction` — create spec with required fields
- `test_frozen` — assignment raises `FrozenInstanceError`
- `test_defaults` — default timeout, tier, required values
- `test_context_keys_tuple` — context_keys is tuple (hashable)

#### 3. TestSubTaskResult (4 tests)
- `test_construction` — create result with all fields
- `test_frozen` — result is immutable
- `test_success_default` — success=True by default
- `test_error_field` — error string populated on failure

#### 4. TestSubTaskChain (3 tests)
- `test_construction` — chain with step list
- `test_defaults` — 30s timeout, "single_call" fallback
- `test_empty_chain` — empty steps list is valid (executor handles)

#### 5. TestSubTaskExecutor (12 tests)
- `test_register_handler` — register and retrieve handler
- `test_register_duplicate_raises` — duplicate registration raises ValueError
- `test_has_handler` — True when registered, False when not
- `test_can_execute_all_required_registered` — True when all required step
  handlers are registered
- `test_can_execute_missing_required` — False when a required step has no handler
- `test_can_execute_optional_missing` — True when missing handler is non-required
- `test_execute_single_step` — execute chain with one mock handler, verify result
- `test_execute_multi_step` — execute chain with 2 steps, verify prior_results
  passed to second handler
- `test_execute_step_timeout` — handler exceeds step timeout, verify
  SubTaskStepError raised
- `test_execute_chain_timeout` — total chain exceeds chain_timeout_ms, verify
  asyncio.TimeoutError handled
- `test_execute_required_step_failure` — required step fails, chain aborts
- `test_execute_optional_step_failure` — optional step fails, chain continues
  with remaining steps

#### 6. TestSubTaskJournalRecording (4 tests)
- `test_journal_record_called_per_step` — mock journal, verify record() called
  once per LLM sub-task step
- `test_dag_node_id_format` — verify dag_node_id matches
  `"st:{chain_id}:{index}:{type}"` format
- `test_agent_id_attributed_to_parent` — verify agent_id on journal entries is
  the parent agent's ID
- `test_no_journal_on_query_step` — QUERY steps (0 LLM calls) do NOT create
  journal entries

#### 7. TestSubTaskEventEmission (3 tests)
- `test_chain_completed_event` — verify SUB_TASK_CHAIN_COMPLETED event emitted
  on success
- `test_chain_completed_event_on_failure` — verify event emitted with
  success=False on chain failure
- `test_no_event_without_emitter` — no error when emit_event_fn is None

#### 8. TestCognitiveAgentIntegration (5 tests)
- `test_set_sub_task_executor` — setter wires executor attribute
- `test_execute_chain_returns_decision` — mock executor, verify decision dict
  returned with `sub_task_chain: True`
- `test_execute_chain_fallback_on_error` — chain failure returns None, caller
  falls through to single-call
- `test_decide_with_pending_chain` — set `_pending_sub_task_chain`, verify
  `_execute_sub_task_chain()` is called before `_decide_via_llm()`
- `test_decide_without_chain_unchanged` — no pending chain, `decide()` follows
  normal cache→procedural→LLM flow (regression guard)

#### 9. TestSubTaskConfig (3 tests)
- `test_defaults` — enabled=False, timeouts correct
- `test_system_config_integration` — SubTaskConfig accessible via
  `SystemConfig().sub_task`
- `test_max_chain_steps` — default is 6

**Total: 41 tests across 9 classes.**

### Existing Test Verification

```
pytest tests/test_ad632a_sub_task_foundation.py -v
pytest tests/ -k "decide" --tb=short
pytest tests/ -k "journal" --tb=short
pytest tests/ -k "cognitive_agent" --tb=short
```

## Verification Checklist

- [ ] `src/probos/cognitive/sub_task.py` exists and is importable
- [ ] `SubTaskType` enum has 5 members (QUERY, ANALYZE, COMPOSE, EVALUATE, REFLECT)
- [ ] `SubTaskSpec` is frozen, has `context_keys` as tuple
- [ ] `SubTaskResult` is frozen, captures tokens, duration, success, error
- [ ] `SubTaskChain` has steps list + chain_timeout_ms + fallback
- [ ] `SubTaskHandler` is `@runtime_checkable` Protocol
- [ ] `SubTaskExecutor.register_handler()` accepts handlers by type
- [ ] `SubTaskExecutor.can_execute()` checks all required handlers present
- [ ] `SubTaskExecutor.execute()` runs chain, records journal, emits events
- [ ] `SubTaskExecutor.execute()` enforces per-step timeout via `asyncio.wait_for()`
- [ ] `SubTaskExecutor.execute()` enforces chain timeout
- [ ] `SubTaskExecutor.execute()` passes `prior_results` to each handler
- [ ] `SubTaskExecutor` populates `dag_node_id` with `st:{chain_id}:{index}:{type}`
- [ ] `SubTaskExecutor` does NOT create CognitiveEvents (circuit breaker isolation)
- [ ] `SubTaskExecutor` does NOT call episodic memory store (memory exclusion)
- [ ] `CognitiveAgent._execute_sub_task_chain()` returns decision dict or None
- [ ] `CognitiveAgent.decide()` checks `_pending_sub_task_chain` between
      procedural memory and `_decide_via_llm()`
- [ ] `CognitiveAgent.set_sub_task_executor()` follows setter pattern
- [ ] `SubTaskConfig` in SystemConfig with `enabled: bool = False`
- [ ] `SUB_TASK_COMPLETED` and `SUB_TASK_CHAIN_COMPLETED` in EventType enum
- [ ] `SubTaskChainCompletedEvent` dataclass extends BaseEvent
- [ ] No changes to journal.py, proactive.py, standing_orders.py
- [ ] All existing tests still pass (zero regressions)
