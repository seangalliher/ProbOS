# AD-1146 — AgenticLoop multi-turn message fidelity + tool-call round-trip (cognitive / swe_harness)

**Issue: #1071 · Epic #1068 (agentic harness parity) · blocks #1074 (AD-1149 prompt caching) and should land before #1063 (AD-1142 crew compaction).**
**Repo: OSS (`d:\ProbOS`). AD ceiling at drafting: AD-1133 shipped; AD-1134–1137 (#1053–#1056); AD-1138–1143 Σ epic (#1057–#1064); AD-1144/1145 (#1069/#1070). This AD = **AD-1146**, assigned to #1071. BF ceiling BF-677 shipped (#1067); none minted here.**

Make `AgenticLoop` speak the provider's real multi-turn message protocol — `assistant.tool_calls` followed by `role:"tool"` results keyed by `tool_call_id` — instead of flattening the whole transcript into one prompt string each iteration. Default-OFF; the flattened path stays byte-identical until opted in.

---

## Why / context

`LLMRequest` **already has** the field and `OpenAICompatibleClient` **already posts it verbatim**:

```python
messages: list[dict] | None = None      # src/probos/types.py:257  (AD-720d)
```
```python
if request.messages is not None:
    messages = list(request.messages)   # src/probos/cognitive/llm_client.py:1791
    ...
    if request.system_prompt and not (messages and messages[0].get("role") == "system"):
        messages.insert(0, {"role": "system", "content": request.system_prompt})
payload["messages"] = messages           # ~:1829
```

`AgenticLoop` does not use it. Every iteration it rebuilds one flat string:

```python
# Assemble single-turn LLMRequest. LLMRequest models a single user
# turn at HEAD, so we pack the multi-turn history into the prompt.
assembled_user_prompt = "\n\n".join(
    f"[{m['role']}] {m['content']}" for m in messages[1:]
)
req = LLMRequest(prompt=assembled_user_prompt, system_prompt=system_prompt, ...)
```
`src/probos/cognitive/swe_harness/agentic_loop.py:136-148` — **the comment is stale; `messages` was added by AD-720d after it was written.**

Assistant turns drop their tool calls (`:181-187`) and results come back as an untagged user message (`:249`):

```python
messages.append({"role": "assistant", "content": assistant_text or response.content or ""})
...
tool_result_text = "\n\n".join(
    f"[tool_result:{trb.result.id} error={trb.result.is_error}]\n{trb.result.output}"
    for trb in tool_result_blocks
)
messages.append({"role": "user", "content": tool_result_text})
```

Tool call ids **are** parsed correctly into `ToolUseBlock` (`llm_client.py:1895`) — they are simply never sent back.

**Consequences:** the model cannot reliably correlate its own calls to their results (worst on multi-tool turns, exactly where the reference harnesses are strongest); re-sending the transcript as fresh prompt text makes provider prompt caching impossible (AD-1149 is blocked on this); and role markers leak into content as literal `[assistant] …` text.

---

## Pinned design decisions

### DD-1 — Default-OFF flag; the flattened path stays byte-identical
New `NativeSWEHarnessConfig`-adjacent flag (verify the exact config home at build; `AgenticLoop` is constructed in `cognitive/agentic_dispatch.py:918` and `swe_harness/native_builder.py:79`). When off, `LLMRequest(prompt=...)` is built exactly as today. Assert byte-identity.

### DD-2 — Emit the OpenAI-shaped array when on
- Assistant turn that made tool calls: `{"role": "assistant", "content": <text or "">, "tool_calls": [{"id": <id>, "type": "function", "function": {"name": <name>, "arguments": <json string>}}]}`
- Each result: `{"role": "tool", "tool_call_id": <same id>, "content": <output>}`
- Pass via `LLMRequest(messages=[...])`; leave `prompt=""`.

`ToolCallRequest.arguments` is a parsed dict (`llm_client.py:1895` does `json.loads`), and the OpenAI wire shape expects `arguments` as a **JSON string** — re-serialize with `json.dumps`. Verify the exact `ToolCallRequest` field names at build (`swe_harness/tool_call.py`).

### DD-3 — Do not build the system message; the client already does
`llm_client.py:1791-1810` inserts `system_prompt` at index 0 when absent. Keep passing `system_prompt=system_prompt` and do **not** prepend a system message, or it will be duplicated. The loop's `messages[0]` is already a system entry — exclude it from the outbound array and let the client insert it.

### DD-4 — Preserve `AgenticResult` and the `stopped_reason` vocabulary exactly
`crew_executor.py:258` maps `stopped_reason` to a required status and raises `crew_execution_status_invalid` on anything unmapped. Introduce **no** new values. `AgenticResult` field set is unchanged.

### DD-5 — Compaction must keep working on the new shape
`SessionCompactor.compact(messages, ...)` (`swe_harness/session_compactor.py:44`) consumes the same list. With tool messages present it must not drop the `tool_call_id` correlation or produce an assistant `tool_calls` entry whose matching `role:"tool"` message was summarized away — an orphaned `tool_calls` is a provider-level 400. **FLAG AT BUILD:** either compact only whole assistant+tool groups, or strip `tool_calls` from summarized turns. State which you chose.

### DD-6 — Vision/multimodal path is untouched
AD-720d/AD-730 already use `LLMRequest.messages` for image turns. Do not alter that construction; verify a vision request still round-trips.

---

## Build

1. **Message builders** in `agentic_loop.py` — pure helpers converting `ToolUseBlock`s → an assistant `tool_calls` entry, and `ToolResultBlock`s → `role:"tool"` entries. Pure and unit-testable; full type annotations.
2. **Branch the request assembly** — when the flag is on, build `LLMRequest(messages=<array>, system_prompt=..., tools=..., tool_choice=..., max_tokens=...)`; else the existing `prompt=` path verbatim.
3. **Replace the two append sites** (`:181` assistant, `:249` tool results) with the structured equivalents when the flag is on.
4. **Config flag** — default `False`; wire through the two `AgenticLoop` construction sites.
5. **Tests** — `tests/test_ad1146_multiturn_messages.py`.

## Acceptance

- Flag ON: outbound `LLMRequest.messages` contains a real array; an assistant entry carries `tool_calls` with ids; each result is `{"role":"tool","tool_call_id":<matching id>,"content":...}`.
- **Multi-tool turn:** two tool calls in one response ⇒ two correlated `role:"tool"` entries, ids matching the assistant `tool_calls` array, order preserved.
- `arguments` is a JSON **string** on the wire, not a dict.
- No duplicate system message (DD-3) — asserted on the array actually handed to the client.
- Flag OFF ⇒ `LLMRequest` byte-identical to today (assert `prompt` content and `messages is None`).
- `AgenticResult` fields and `stopped_reason` values unchanged; token accounting unchanged.
- Compaction interop (DD-5): a compaction pass over a history containing tool messages leaves no assistant `tool_calls` without its matching tool result.
- Crew regression: `crew_execution` evidence 14-key set (`crew_executor.py:622`) and `SubtaskResult` fields (`crew_finalizer.py:1909`) untouched.
- Real fixtures per BF-287 — use a real/faithful fake LLM client capturing the outbound `LLMRequest`; no MagicMock at the client boundary.
- Verify compliance with `.github/copilot-instructions.md` (async hygiene, type annotations, logging context).

## Validation plan — targeted only, do NOT run the full suite

- **Focused:** `tests/test_ad1146_multiturn_messages.py -q -n 0`
- **Adjacent (once):** `tests/test_ad545_agentic_loop.py tests/test_ad547_session_compactor.py tests/test_ad1065_conversational_agentic.py tests/test_ad1066_code_execution_tool.py tests/test_ad859a_agentic_executor.py -q -n 0` (verify each exists at build; skip any that do not).
- Use an isolated `PROBOS_DATA_DIR` and `PROBOS_EMBEDDINGS=local` for anything that may boot a runtime.
- The full suite is ~20 minutes and is **not** required for this change.

## Do NOT build here

❌ Parallel tool execution (#1072). ❌ Tool-result truncation (#1073). ❌ Prompt caching (#1074) — this AD only unblocks it. ❌ Plan mode (#1075). ❌ Streaming. ❌ Changing `LLMRequest`/`LLMResponse` field sets. ❌ Changing `SessionCompactor`'s algorithm beyond the DD-5 correctness guard. ❌ Any Σ-epic work. ❌ New `stopped_reason` values. ❌ A new AD or BF number.

## Files (verify each at build)

- `src/probos/cognitive/swe_harness/agentic_loop.py` — message builders, request branch, append sites.
- `src/probos/config.py` — default-False flag (confirm the right config class).
- `src/probos/cognitive/agentic_dispatch.py` + `src/probos/cognitive/swe_harness/native_builder.py` — thread the flag at the two construction sites.
- `tests/test_ad1146_multiturn_messages.py` (NEW).

## Done-when

Acceptance green; focused + adjacent gates green; flag-OFF byte-identity proven; DD-5 choice stated; Architect review repaired; **verify compliance with `.github/copilot-instructions.md`.**
