# AD-1148 — Tool-result bounds and truncation discipline (cognitive / swe_harness)

**Issue: #1073 · Epic #1068 · depends on AD-1146 (#1071, landed in-tree) · pairs with AD-1142 (#1063).**
**Repo: OSS (`d:\ProbOS`). AD ceiling: AD-1146 assigned (#1071); AD-1147/1149/1150 assigned (#1072/#1074/#1075). This AD = **AD-1148** (#1073). No new BF.**

Bound each tool result before it enters the agentic loop's message history. The durable trace keeps the full output. Default-OFF.

---

## Why / context

Tool results enter the conversation with **no size bound at all**.

```python
@dataclass(frozen=True)
class ToolCallResult:
    id: str
    output: str = ""      # no cap
    is_error: bool = False
    duration_ms: float = 0.0
```
`src/probos/cognitive/swe_harness/tool_call.py:29`

and the loop serializes results verbatim into history (`agentic_loop.py`, both the legacy text path and the AD-1146 structured `role:"tool"` path).

A single `run_python` printing a large dataframe, an `http_fetch` of a big page, or a `read_page` on a long document can consume the entire context window in one iteration. Claude Code and Cursor both bound individual tool results.

This is the cheapest large win available: it protects every downstream consumer, including AD-1142's compaction, which currently has to summarize damage that should never have entered.

---

## Pinned design decisions

### DD-1 — Head + tail preservation, never tail-only
Many tools print their summary line **last** and their header **first**. Truncating either end alone destroys the useful part. Keep a head slice and a tail slice with an explicit elision marker between them.

### DD-2 — The durable trace keeps the FULL output
`_persist_tool_trace` (`src/probos/cognitive/agentic_dispatch.py`) already persists the complete tool trace. Truncation applies to the **working context only**. This preserves Nooplex §3.3 Transparency ("all operations produce observable traces") and mirrors the constraint already placed on AD-1142. **Assert this directly in a test.**

### DD-3 — Truncation is visible to the model
The elision marker must state that content was omitted and how much, so the agent can re-query more narrowly instead of silently reasoning on partial data. Gap-regex safe: the marker text must NOT match `_CAPABILITY_GAP_RE` (`src/probos/cognitive/decomposer.py:33`) — no "can't", "cannot", "unable to", "not available". Use "do not" / plain declarative phrasing. **Assert with the real regex.**

### DD-4 — Applies to error results too
An exception traceback can be enormous. Bound `is_error=True` results by the same rule.

### DD-5 — Bound at the point of entry, not inside the tool
Truncate where the result is converted into message content in `agentic_loop.py`, so it covers **both** the legacy text path and the AD-1146 structured path, and every tool uniformly. Do NOT modify `ToolCallResult`'s field set (it is frozen and consumed elsewhere) and do NOT change the `Tool` protocol.

### DD-6 — Default-OFF
New config field, default `0`/unset meaning unbounded ⇒ byte-identical to today.

---

## Build

1. **Pure helper** in `agentic_loop.py` (or a small sibling module): `truncate_tool_output(text, *, max_chars, head_chars, tail_chars) -> str`. Pure, fully annotated, unit-testable. No-op when `max_chars <= 0` or the text already fits.
2. **Apply at both message-construction sites** — the legacy `tool_result_text` join and the AD-1146 `build_tool_result_messages` path.
3. **Config** — add to the existing `AgenticLoopConfig` (`src/probos/config.py`, added by AD-1146) rather than a new class. Fields: `tool_result_max_chars: int = 0` (0 = unbounded), plus head/tail split. Thread through the two `AgenticLoop` construction sites already wired by AD-1146.
4. **Tests** — `tests/test_ad1148_tool_result_bounds.py`.

## Acceptance

- A result exceeding the cap is truncated with **both** head and tail preserved and an explicit elision marker between them.
- Total bounded length respects the configured cap.
- A result at or under the cap is returned **unchanged** (identity, not a copy with a marker).
- Error results (`is_error=True`) are bounded by the same rule.
- **DD-2:** the persisted tool trace retains the FULL untruncated output — asserted directly, not inferred.
- **DD-3:** the elision marker does not match `_CAPABILITY_GAP_RE` — asserted using the real imported regex.
- Applies on both the legacy and the AD-1146 structured paths.
- Default (`tool_result_max_chars = 0`) ⇒ message content byte-identical to today.
- `AgenticResult` fields and the `stopped_reason` vocabulary unchanged (`crew_executor.py:258` maps them exactly).
- `ToolCallResult` and the `Tool` protocol unchanged.
- Verify compliance with `.github/copilot-instructions.md`.

## Validation plan — targeted only

- **Focused:** `tests/test_ad1148_tool_result_bounds.py -q -n 0`
- **Adjacent ONCE:** `tests/test_ad1146_multiturn_messages.py tests/test_ad545_agentic_loop.py tests/test_ad547_session_compactor.py tests/test_ad1066_code_execution_tool.py -q -n 0`
- **Do NOT run the full suite.**

## Do NOT build here

❌ Semantic summarization of results (that is compaction, AD-1142 #1063). ❌ Per-tool custom caps beyond one optional override. ❌ Changing `ToolCallResult` or the `Tool` protocol. ❌ Changing `_persist_tool_trace`. ❌ Parallel execution (#1072). ❌ Prompt caching (#1074). ❌ Any Σ-epic work. ❌ New `stopped_reason` values. ❌ A new AD or BF number.

## Files (verify each at build)

- `src/probos/cognitive/swe_harness/agentic_loop.py` — helper + both application sites.
- `src/probos/config.py` — extend `AgenticLoopConfig`.
- `tests/test_ad1148_tool_result_bounds.py` (NEW).

## Done-when

Acceptance green; focused + adjacent gates green; default-OFF byte-identity proven; full trace retention asserted; **verify compliance with `.github/copilot-instructions.md`.**
