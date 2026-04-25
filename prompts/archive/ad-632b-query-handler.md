# AD-632b: Query Sub-Task Handler (Deterministic Data Retrieval)

**Issue:** #232
**Depends on:** AD-632a (COMPLETE — sub_task.py foundation)
**Absorbs:** None (wraps existing service APIs, does not replace them)
**Principles:** Single Responsibility, Open/Closed, Interface Segregation, DIP, Fail Fast

## Problem

The Sub-Task Protocol (AD-632a) defines five sub-task types and an executor
engine, but no handlers exist yet. The system is **disabled** (`SubTaskConfig.enabled = False`,
config.py line 255 class / line 258 field) because there are no handlers to execute.

The QUERY sub-task type is the simplest handler — deterministic data retrieval
with zero LLM calls. It is the **first step** in every proposed sub-task chain
(Ward Room thread response, proactive think cycle, duty execution). Without it,
no chain can execute because QUERY steps are `required: True` by default.

QUERY follows the MRKL principle: route each sub-task to the **cheapest capable
handler**. Thread reply counting is a SQL query, not an LLM judgment. Endorsement
target lookup is a dictionary check. Only sub-tasks requiring genuine reasoning
should invoke the LLM. QUERY is the handler for everything that doesn't need one.

## Design

### Handler Architecture

Create a single handler class `QueryHandler` that implements the
`SubTaskHandler` protocol (sub_task.py line 80-92):

```python
async def __call__(
    self,
    spec: SubTaskSpec,
    context: dict,
    prior_results: list[SubTaskResult],
) -> SubTaskResult
```

The handler receives the observation context dict (same dict passed to
`_execute_sub_task_chain` at cognitive_agent.py line 1447-1449) and uses
`spec.context_keys` to determine which query operations to perform.

### Query Operations (Dispatched by context_keys)

The handler is a **multiplexer**: `spec.context_keys` tells it which data
to retrieve. Each query operation maps to exactly one ProbOS service method.
The handler does NOT call all services — it calls only what the chain spec
requests via `context_keys`.

Operations to implement in AD-632b (Ward Room + trust + comm stats scope):

| Operation Key | Service | Method | Returns |
|---------------|---------|--------|---------|
| `thread_metadata` | WardRoomService | `get_thread(thread_id, **kwargs)` | `{reply_count, contributors, post_ids, department}` |
| `thread_activity` | WardRoomService | `get_recent_activity(channel_id, since, limit=10)` | `{posts: [{id, author, timestamp, type}]}` |
| `comm_stats` | WardRoomService | `get_agent_comm_stats(agent_id, since=None)` | `{posts, replies, endorsements, dms_sent, ...}` |
| `credibility` | WardRoomService | `get_credibility(agent_id)` | `WardRoomCredibility` (convert to dict) |
| `unread_counts` | WardRoomService | `get_unread_counts(agent_id)` | `{channel_id: count, ...}` |
| `unread_dms` | WardRoomService | `get_unread_dms(agent_id, limit=3, exchange_limit=0)` | `[{from, text, timestamp}]` |
| `trust_score` | TrustNetwork | `get_score(agent_id: AgentID)` **(sync)** | `float` |
| `trust_summary` | TrustNetwork | `summary()` **(sync)** | `list[dict[str, Any]]` |
| `posts_by_author` | WardRoomService | `get_posts_by_author(author_callsign, limit=5, since=None, thread_id=None)` | `[{id, text, timestamp, thread_id}]` |

**Future operations (AD-632b does NOT implement these — noted for Open/Closed
compliance so the design accommodates them):**

| Operation Key | Service | AD |
|---------------|---------|-----|
| `episodic_recall` | EpisodicMemory | AD-632b+ (future) |
| `journal_chain` | CognitiveJournal | AD-632b+ (future) |
| `notebook_entries` | RecordsStore | AD-632b+ (future) |
| `emergence_snapshot` | EmergenceMetricsEngine | AD-632b+ (future) |
| `introspective_state` | IntrospectiveTelemetryService | AD-632b+ (future) |

These require no code changes to add later — just register new operation
keys in the query dispatch table. Open/Closed.

### Service Access Pattern

The `QueryHandler` receives a **runtime reference** at construction time
(constructor injection per DIP). It does NOT reach through the context dict
to find services. The context dict carries the observation — the runtime
provides the services.

```python
class QueryHandler:
    def __init__(self, runtime) -> None:
        self._runtime = runtime
```

Service access follows the existing defensive pattern (cognitive_agent.py
passim):

```python
ward_room = getattr(self._runtime, 'ward_room', None)
if ward_room is None:
    return SubTaskResult(..., success=False, error="WardRoomService not available")
```

### Registration

Registration happens during startup. The sub-task executor should be wired
**inline in `runtime.py`** following the pattern used by `procedure_store`
(runtime.py lines 1169-1181) and `introspective_telemetry` (runtime.py lines
1160-1167). These are wired after the cognitive_services startup phase
completes, NOT in a `startup/*.py` module.

**Create startup wiring** — inline in `runtime.py` (around lines 1160-1181,
after the cognitive_services phase) that:

1. Creates the `SubTaskExecutor` (if SubTaskConfig.enabled is True)
2. Creates the `QueryHandler` with the runtime reference
3. Calls `executor.register_handler(SubTaskType.QUERY, handler)`
4. Calls `agent.set_sub_task_executor(executor)` for each cognitive agent

**Important:** `TrustNetwork.get_score()` and `TrustNetwork.summary()` are
**synchronous** methods (not async). The QueryHandler must call them without
`await`. Wrap in `asyncio.to_thread()` if they might block, or call directly
since they are in-memory lookups.

### Result Format

All query operations return a `SubTaskResult` with:

- `sub_task_type = SubTaskType.QUERY`
- `name = spec.name` (e.g., `"query-thread-metadata"`)
- `result = {"operation_key": structured_data}` — the operation key maps
  to the query operation, the value is the service method's return value
  converted to a plain dict (no ProbOS-internal objects in the result)
- `tokens_used = 0` (always — QUERY is deterministic)
- `duration_ms` — wall clock time for the service call(s)
- `success = True/False`
- `error = ""` or error message on failure
- `tier_used = ""` (no LLM tier — deterministic)

When multiple operation keys are requested in `spec.context_keys`, the
handler executes ALL of them and returns a merged result dict:

```python
result = {
    "thread_metadata": {...},
    "comm_stats": {...},
}
```

### Error Handling — Fail Fast, Degrade Gracefully

Three tiers per ProbOS error handling policy:

1. **Missing service** (ward_room is None, trust_network is None): Return
   `SubTaskResult(success=False, error="...")`. The executor will either
   abort (if `spec.required=True`) or skip (if optional). Log at DEBUG.

2. **Service method exception** (DB timeout, connection error): Catch,
   return `SubTaskResult(success=False, error=str(exc))`. Log at WARNING.
   Do NOT swallow silently — the calling chain needs to know.

3. **Partial failure** (one operation key fails, others succeed): If the
   spec has multiple `context_keys` and one fails, include the successful
   results in `result` and set `success=False` with the error message.
   This lets the chain decide whether to continue with partial data.

### Token Accounting

QUERY steps report `tokens_used = 0` always. The journal recording skip
at sub_task.py line 311 already handles this:

```python
if spec.sub_task_type != SubTaskType.QUERY and journal is not None:
```

No changes needed. The chain event (`SUB_TASK_CHAIN_COMPLETED`) will
correctly report `total_tokens = 0` for Query-only steps.

### SubTaskConfig.enabled

This AD does **NOT** flip `enabled` to `True`. The Query handler alone
is insufficient for a useful chain — chains need ANALYZE and/or COMPOSE
handlers to produce output. Enabling happens when AD-632c/d deliver
those handlers. The Query handler should still be fully functional and
testable when registered manually.

## Files to Create

| File | Content |
|------|---------|
| `src/probos/cognitive/sub_tasks/__init__.py` | Package init — exports `QueryHandler` |
| `src/probos/cognitive/sub_tasks/query.py` | `QueryHandler` class + query operation functions |

## Files to Modify

| File | Change |
|------|--------|
| `src/probos/runtime.py` | Add inline sub-task executor wiring after cognitive_services phase (~lines 1160-1181), following `procedure_store` / `introspective_telemetry` pattern |

## Files to Verify (NOT Modify)

| File | Why Verify |
|------|------------|
| `src/probos/cognitive/sub_task.py` | Confirm `SubTaskHandler` protocol (line 80-92), `SubTaskType.QUERY` (line 31), `SubTaskSpec.context_keys`, journal skip at line 311 |
| `src/probos/config.py` | Confirm `SubTaskConfig` at line 255, `enabled: bool = False` at line 258 |
| `src/probos/events.py` | Confirm `SubTaskChainCompletedEvent` at line 697 |
| `src/probos/ward_room/service.py` | Confirm method signatures: `get_thread(thread_id, **kwargs)` line 361, `get_recent_activity(channel_id, since, limit=10)` line 335, `get_agent_comm_stats(agent_id, since=None)` line 296, `get_credibility(agent_id)` line 410 (returns `WardRoomCredibility`), `get_unread_counts(agent_id)` line 422, `get_unread_dms(agent_id, limit=3, exchange_limit=0)` line 433, `get_posts_by_author(author_callsign, limit=5, since=None, thread_id=None)` line 340 |
| `src/probos/consensus/trust.py` | Confirm `get_score(agent_id: AgentID) -> float` (line 385, **sync**), `summary() -> list[dict]` (line 460, **sync**) |

## Do NOT Change

- `src/probos/cognitive/sub_task.py` — AD-632a foundation is complete, no changes needed
- `src/probos/config.py` — do NOT flip `enabled` to True
- `src/probos/events.py` — event types are already defined
- `src/probos/ward_room/service.py` — wrap existing APIs, do not modify them
- `src/probos/consensus/trust.py` — wrap existing APIs, do not modify them

## Engineering Principles Compliance

| Principle | Application |
|-----------|-------------|
| **SRP** | `QueryHandler` has one responsibility: deterministic data retrieval. Each query operation is a focused function. No LLM calls, no response composition, no analysis. |
| **Open/Closed** | New query operations are added by registering new operation keys in the dispatch table — zero changes to `QueryHandler.__call__()` or `SubTaskExecutor`. The dispatch table is a dict mapping operation key → async function. |
| **DIP** | `QueryHandler` depends on the runtime abstraction (constructor injection), not on concrete service classes. It accesses services via `getattr(self._runtime, 'service_name', None)`. |
| **ISP** | `QueryHandler` implements the narrow `SubTaskHandler` protocol (3 params, 1 return). It does not depend on `SubTaskExecutor` internals or the full cognitive agent interface. |
| **Liskov** | `QueryHandler` satisfies the `SubTaskHandler` protocol contract — it can replace any handler in the executor's registry for `SubTaskType.QUERY` without violating expectations. |
| **Law of Demeter** | `QueryHandler` accesses `self._runtime.ward_room` (one dot), never `self._runtime.ward_room._db.execute()`. Service methods are the public API boundary. |
| **Fail Fast** | Missing services → immediate failure result (not silent degradation). Service exceptions → caught, wrapped in error result, logged. No `except Exception: pass`. |
| **Defense in Depth** | Input validation on operation keys (unknown key → error, not silent skip). Timeout enforcement via `SubTaskSpec.timeout_ms` (already in executor). Result serialization validates dict-only output (no ProbOS objects leaking into result). |
| **DRY** | Wraps existing service methods — does not reimplement their logic. Query operations share a common dispatch + error handling pattern via the dispatch table. |

## Test Requirements

### Unit Tests (`tests/test_ad632b_query_handler.py`)

All tests use mocked runtime services — no real DB, no real Ward Room.

1. **TestQueryHandlerProtocol**
   - `test_implements_sub_task_handler` — `isinstance(handler, SubTaskHandler)` is True
   - `test_returns_sub_task_result` — return type is `SubTaskResult`
   - `test_tokens_always_zero` — `.tokens_used == 0` for all operations
   - `test_tier_always_empty` — `.tier_used == ""` for all operations
   - `test_sub_task_type_is_query` — `.sub_task_type == SubTaskType.QUERY`

2. **TestThreadMetadata**
   - `test_thread_metadata_returns_structured_data` — correct keys in result
   - `test_thread_metadata_missing_thread_id` — returns error result, not exception
   - `test_thread_metadata_thread_not_found` — `success=False` with error message

3. **TestCommStats**
   - `test_comm_stats_returns_agent_data` — correct structure
   - `test_comm_stats_missing_agent_id` — returns error result
   - `test_comm_stats_with_since_parameter` — since timestamp passed through

4. **TestTrustQueries**
   - `test_trust_score_returns_float` — `result["trust_score"]["score"]` is float
   - `test_trust_summary_returns_list` — `result["trust_summary"]` is list of dicts
   - `test_trust_network_unavailable` — `success=False`, not exception

5. **TestCredibilityAndUnread**
   - `test_credibility_returns_data` — correct structure
   - `test_unread_counts_returns_dict` — channel_id → count mapping
   - `test_unread_dms_returns_list` — list of DM dicts

6. **TestMultipleOperations**
   - `test_multiple_context_keys` — result contains data for all requested keys
   - `test_partial_failure` — some keys succeed, some fail, result has both
   - `test_unknown_operation_key` — returns error for unknown key

7. **TestServiceUnavailable**
   - `test_ward_room_none` — `success=False` when ward_room is None
   - `test_trust_network_none` — `success=False` when trust_network is None
   - `test_runtime_none` — `success=False` when runtime is None

8. **TestContextKeyFiltering**
   - `test_empty_context_keys_runs_nothing` — no operations executed if no keys
   - `test_context_keys_filter_operations` — only requested operations run

9. **TestDurationTracking**
   - `test_duration_ms_recorded` — `result.duration_ms > 0`

10. **TestExecutorIntegration**
    - `test_register_with_executor` — `executor.register_handler(SubTaskType.QUERY, handler)` succeeds
    - `test_executor_can_execute_query_chain` — full chain execution with Query step
    - `test_executor_query_skips_journal` — journal.record() NOT called for QUERY steps

### Existing test verification

```
pytest tests/test_ad632b_query_handler.py -v
pytest tests/test_ad632a_sub_task.py -v
pytest tests/ -k "sub_task" --tb=short
```

## Verification Checklist

- [ ] `src/probos/cognitive/sub_tasks/__init__.py` exports `QueryHandler`
- [ ] `src/probos/cognitive/sub_tasks/query.py` contains `QueryHandler` class
- [ ] `QueryHandler` implements `SubTaskHandler` protocol (runtime_checkable)
- [ ] `QueryHandler.__init__` accepts runtime via constructor injection
- [ ] Query operations dispatch via `spec.context_keys` — not hardcoded
- [ ] All 9 operation keys implemented: `thread_metadata`, `thread_activity`,
      `comm_stats`, `credibility`, `unread_counts`, `unread_dms`,
      `trust_score`, `trust_summary`, `posts_by_author`
- [ ] `tokens_used` is always 0
- [ ] `tier_used` is always empty string
- [ ] Missing service → `SubTaskResult(success=False, error="...")`
- [ ] Service exception → caught, wrapped in error result, logged at WARNING
- [ ] Unknown operation key → error result, not silent skip
- [ ] Startup wiring added inline in `runtime.py` (after cognitive_services phase)
- [ ] `SubTaskConfig.enabled` remains `False` (not flipped in this AD)
- [ ] No modifications to sub_task.py, config.py, events.py
- [ ] Ward Room service methods called with correct signatures (note: `author_callsign` not `callsign`, `exchange_limit` param on `get_unread_dms`, `**kwargs` on `get_thread`)
- [ ] Trust network methods called as **sync** (no `await`) — `get_score(agent_id: AgentID)`, `summary()`
- [ ] `get_credibility()` returns `WardRoomCredibility` object — convert to dict for result
- [ ] All tests pass: `pytest tests/test_ad632b_query_handler.py -v`
- [ ] AD-632a tests still pass: `pytest tests/test_ad632a_sub_task.py -v`
