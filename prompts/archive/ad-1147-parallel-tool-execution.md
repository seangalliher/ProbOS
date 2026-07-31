# AD-1147 — Parallel tool execution in the agentic loop (cognitive / swe_harness)

**Issue: #1072 · Epic #1068 · depends on AD-1146 (#1071, in-tree) and AD-1148 (#1073, in-tree).**
**Repo: OSS (`d:\ProbOS`). This AD = **AD-1147** (#1072). AD-1144–1151 assigned (#1069–#1076). No new BF.**

Execute the independent tool calls from a single LLM response concurrently, bounded, order-preserving, with mutating tools held sequential. Default-OFF.

---

## Why / context

When the LLM emits several tool calls in one response, the loop runs them strictly one at a time:

```python
tool_result_blocks: list[ToolResultBlock] = []
for use in tool_uses:
    ...
    raw_result = await self._executor.invoke(...)
    ...
    tool_result_blocks.append(ToolResultBlock(result=tcr))
```
`src/probos/cognitive/swe_harness/agentic_loop.py` (the `for use in tool_uses:` block)

Anthropic reports parallel tool calling as one of the two changes that "cut research time by up to 90% for complex queries." For ProbOS this compounds: a crew child doing three independent reads pays three full round-trips inside a 25-iteration budget.

---

## Pinned design decisions

### DD-1 — Read-only allowlist in v1; mutating tools stay sequential (LOAD-BEARING)
Tools are **not** uniformly side-effect-free. `run_python` (AD-1066), `write_file`, and `edit_file` (`swe_harness/tools.py:423`, `:467`) mutate state. Parallelising two writes to the same path is a new race that does not exist today.

v1 parallelises only a **read-only allowlist**: `web_search`, `read_page`, `http_fetch`, `search_capabilities`, `event_log_query`. Everything else — including any tool not on the list, and any unrecognised tool id — executes sequentially. **Unknown ⇒ sequential** (fail-safe, not fail-open).

Execution shape: partition the response's tool calls, run the allowlisted subset concurrently, then run the remainder sequentially. Do **not** interleave.

### DD-2 — Order preservation is mandatory
AD-1146 emits `assistant.tool_calls` followed by one `role:"tool"` per call. The result list must stay in **request order** regardless of completion order, or the correlation the whole of AD-1146 exists to establish is scrambled. Use `asyncio.gather` (which preserves input order) and reassemble by index — never by completion.

### DD-3 — Bounded concurrency
Concurrency is a Safety Budget concern. Bound the fan-out with an `asyncio.Semaphore`, mirroring `AgenticDispatchConfig.max_parallel_subtasks` (default 3). New field on `AgenticLoopConfig` (added by AD-1146, extended by AD-1148).

### DD-4 — Per-tool error isolation preserved
Today a raising tool yields an error `ToolCallResult` and the loop continues (`agentic_loop.py`, the `except Exception as exc:` arm). Under `gather`, use `return_exceptions=True` and convert per-call, so one failure does not cancel siblings and produces the same error-result shape as today.

### DD-5 — Cancellation must propagate and reap
`asyncio.CancelledError` must propagate, and in-flight tool tasks must be awaited/cancelled — no orphans (Async Discipline in `.github/copilot-instructions.md`). Do not swallow cancellation into an error result.

### DD-6 — Events keep firing per tool
`AGENTIC_TOOL_CALL_STARTED` / `AGENTIC_TOOL_CALL_COMPLETED` fire once per tool as today. Under concurrency their interleaving is non-deterministic; that is acceptable. `result.tool_calls` and `tool_id_history` must still be appended in **request order** (DD-2).

### DD-7 — Default-OFF
`parallel_tool_calls_enabled: bool = False` ⇒ the existing sequential loop runs verbatim, byte-identical.

---

## Build

1. **Partition helper** — pure, annotated: given the response's tool uses, return `(parallel_subset, sequential_subset)` preserving original indices. Unknown/absent tool id ⇒ sequential.
2. **Concurrent execution path** in `agentic_loop.py` — semaphore-bounded `asyncio.gather(..., return_exceptions=True)`, per-call error conversion identical to today's `except` arm, results reassembled by index.
3. **Config** — extend `AgenticLoopConfig` (`src/probos/config.py`): `parallel_tool_calls_enabled: bool = False`, `max_parallel_tool_calls: int = 3` (ge=1, le=16), and the read-only allowlist as a module constant (not config — it is a safety property, not a tuning knob).
4. Thread through the construction sites AD-1146/AD-1148 already wired (`cognitive/agentic_dispatch.py`, `swe_harness/native_builder.py`, `startup/finalize.py`).
5. **Tests** — `tests/test_ad1147_parallel_tools.py`.

## Acceptance

- Two allowlisted read tools in one response execute **concurrently** — proven by overlapping start/end timestamps captured inside a real fake tool executor, not by mocking `gather`.
- Results are returned in **request order** even when the second tool completes first (force this with asymmetric sleeps).
- A mutating tool (`run_python`/`write_file`/`edit_file`) in the same batch runs **sequentially**; an unrecognised tool id also runs sequentially.
- One tool raising does not cancel siblings; its error result matches today's shape (`is_error=True`, `output` containing the failure text).
- `asyncio.CancelledError` propagates and no tool task is left pending.
- Concurrency never exceeds the configured bound (assert peak observed concurrency).
- `result.tool_calls` and `tool_id_history` are in request order.
- Default-OFF ⇒ sequential path byte-identical; `AgenticResult` fields and `stopped_reason` vocabulary unchanged.
- Interops with AD-1146 structured messages: `role:"tool"` entries align 1:1 and in order with `assistant.tool_calls`.
- Verify compliance with `.github/copilot-instructions.md` (async hygiene especially).

## Validation plan — targeted only

- **Focused:** `tests/test_ad1147_parallel_tools.py -q -n 0`
- **Adjacent ONCE:** `tests/test_ad1146_multiturn_messages.py tests/test_ad1148_tool_result_bounds.py tests/test_ad545_agentic_loop.py tests/test_ad1066_code_execution_tool.py -q -n 0`
- **Do NOT run the full suite.**

## Do NOT build here

❌ Parallelising mutating tools (v1 is read-only allowlist by design). ❌ Cross-iteration or speculative execution. ❌ Changing tool permission checks or `ToolRegistry.check_and_invoke`. ❌ Changing the `Tool` protocol or `ToolCallResult`. ❌ Prompt caching (#1074). ❌ Plan mode (#1075). ❌ Any Σ-epic work. ❌ New `stopped_reason` values. ❌ A new AD or BF number.

## Files (verify each at build)

- `src/probos/cognitive/swe_harness/agentic_loop.py` — partition helper + concurrent path.
- `src/probos/config.py` — extend `AgenticLoopConfig`.
- `src/probos/cognitive/agentic_dispatch.py`, `src/probos/cognitive/swe_harness/native_builder.py`, `src/probos/startup/finalize.py` — thread the new fields.
- `tests/test_ad1147_parallel_tools.py` (NEW).

## Done-when

Acceptance green; focused + adjacent gates green; default-OFF byte-identity proven; concurrency bound and ordering asserted; cancellation clean; **verify compliance with `.github/copilot-instructions.md`.**
