# AD-632d: Compose Sub-Task Handler (Skill-Augmented Response Composition)

**Issue:** TBD (will be created)
**Depends on:** AD-632a (COMPLETE — sub_task.py foundation), AD-632c (COMPLETE — AnalyzeHandler)
**Absorbs:** Composition patterns from `cognitive_agent.py` lines 1243-1337 (WR/DM/proactive system prompts), skill injection from `_frame_task_with_skill()` (lines 2029-2068), action vocabulary from federation.md lines 243-303, `_load_augmentation_skills()` (lines 1972-2027)
**Principles:** Single Responsibility, Open/Closed, DIP, Fail Fast, Law of Demeter

## Problem

The Sub-Task Protocol has Query (AD-632b, deterministic data retrieval) and
Analyze (AD-632c, focused LLM comprehension) handlers. Both work. But the
chain cannot produce a final agent response because no COMPOSE handler exists.

Today, `_execute_sub_task_chain()` (cognitive_agent.py:1480-1504) looks for
`SubTaskType.COMPOSE` results and extracts `result["output"]` as `llm_output`.
If no COMPOSE results exist, it concatenates all results — producing analysis
JSON where conversational text belongs. This is the gap.

The Compose handler is the **final LLM call** in the MVP chain
(Query → Analyze → **Compose**). It receives the Analyze handler's structured
analysis as input and produces the agent's actual Ward Room post, DM reply,
or proactive observation. This is where:

1. **Skill instructions** land (not in Analyze — focused attention principle)
2. **Action vocabulary** is injected ([REPLY], [ENDORSE], [DM], [NOTEBOOK], etc.)
3. **Personality and standing orders** shape the voice
4. The agent decides whether to respond at all (SILENT → [NO_RESPONSE])

Completing this handler **completes the MVP sub-task chain** and allows
flipping `SubTaskConfig.enabled = True`.

## Design

### Module Location

`src/probos/cognitive/sub_tasks/compose.py`

### Handler Architecture

Create `ComposeHandler` implementing the `SubTaskHandler` protocol
(sub_task.py line 80-92):

```python
class ComposeHandler:
    def __init__(self, *, llm_client: Any, runtime: Any) -> None:
        self._llm_client = llm_client
        self._runtime = runtime

    async def __call__(
        self,
        spec: SubTaskSpec,
        context: dict,
        prior_results: list[SubTaskResult],
    ) -> SubTaskResult:
        ...
```

Constructor takes `llm_client` and `runtime` via keyword-only args (DIP,
matches AnalyzeHandler signature at analyze.py:196).

### Composition Modes (Open/Closed Dispatch)

Three modes, dispatched via `spec.prompt_template`:

| Mode | `prompt_template` value | Source pattern |
|------|------------------------|----------------|
| Ward Room response | `"ward_room_response"` | cognitive_agent.py:1243-1261 |
| Direct message reply | `"dm_response"` | cognitive_agent.py:1339-1347 |
| Proactive observation | `"proactive_observation"` | cognitive_agent.py:1266-1337 |

Default mode: `"ward_room_response"` (most common path).

Dispatch table follows the same Open/Closed pattern as AnalyzeHandler
(`_ANALYSIS_MODES` at analyze.py:176-182):

```python
_COMPOSITION_MODES: dict[str, CompositionModeBuilder] = {
    "ward_room_response": _build_ward_room_compose_prompt,
    "dm_response": _build_dm_compose_prompt,
    "proactive_observation": _build_proactive_compose_prompt,
}
```

### Prompt Builder Signature

Each mode builder is a module-level function returning `(system_prompt, user_prompt)`:

```python
def _build_ward_room_compose_prompt(
    context: dict,
    prior_results: list[SubTaskResult],
    callsign: str,
    department: str,
) -> tuple[str, str]:
```

Same signature as AnalyzeHandler builders (analyze.py:30-35) for consistency.

### System Prompt Construction

**Critical difference from AnalyzeHandler:** Compose uses the **full system
prompt** including personality, standing orders, and identity — not the narrow
identity-only prompt Analyze uses.

Use `compose_instructions()` from `probos.cognitive.standing_orders`
(standing_orders.py:208-217) to build the full prompt:

```python
from probos.cognitive.standing_orders import compose_instructions, get_department

composed = compose_instructions(
    agent_type=context.get("_agent_type", "agent"),
    hardcoded_instructions="",
    callsign=context.get("_callsign", "agent"),
    agent_rank=None,  # rank not needed for composition
)
```

Then **append the mode-specific instructions** — these are the Ward Room
posting rules, DM conversation rules, or proactive observation rules that
currently live inline in cognitive_agent.py (lines 1243-1337).

### Skill Injection

If `context.get("_augmentation_skill_instructions")` is non-empty, inject
skill guidance into the system prompt using XML framing. This replicates the
pattern from `_frame_task_with_skill()` (cognitive_agent.py:2029-2068):

```python
if skill_instructions:
    composed += "\n"
    composed += f'<active_skill name="{skill_name}" activation="augmentation">\n'
    if proficiency_context:
        composed += f"<proficiency_tier>{proficiency_context}</proficiency_tier>\n"
    composed += "<skill_instructions>\n"
    composed += (
        "Follow these instructions internally when processing the "
        "content below. Your response must contain ONLY your final "
        "output — no reasoning steps, phase headers, or self-evaluation "
        "artifacts.\n\n"
    )
    composed += skill_instructions
    composed += "\n</skill_instructions>\n"
    composed += "</active_skill>\n"
```

The skill name comes from `context.get("_augmentation_skills_used", [])` —
if present, use the first entry's `.name`. Otherwise derive from mode label.

### Action Vocabulary Per Mode

Each mode builder appends its relevant action tags to the system prompt.
Replicate the existing patterns:

**Ward Room response** (from cognitive_agent.py:1250-1261):
- `[NO_RESPONSE]` — if nothing meaningful to add
- `[ENDORSE post_id UP/DOWN]` — vote on posts
- DM syntax via `_compose_dm_instructions(brief=True)` — but since we don't
  have access to the agent method, include DM instructions inline if
  `context.get("_dm_available", False)` is truthy

**DM response** (from cognitive_agent.py:1339-1347):
- No action tags — just conversational response
- No structured output formats

**Proactive observation** (from cognitive_agent.py:1266-1337):
- `[NO_RESPONSE]` — nothing noteworthy
- `[ENDORSE post_id UP/DOWN]` — vote on posts
- `[REPLY thread_id]...[/REPLY]` — contribute to existing thread
- `[NOTEBOOK topic-slug]...[/NOTEBOOK]` — extended analysis
- `[DM @callsign]...[/DM]` — private message
- `[PROPOSAL]...[/PROPOSAL]` — improvement proposal
- `[CHALLENGE @callsign game]` — recreation
- `[MOVE position]` — game move

### User Prompt Construction

The user prompt carries:

1. **Analysis results** from prior ANALYZE step (the most recent successful
   `SubTaskResult` with `sub_task_type == SubTaskType.ANALYZE`). Format as
   a clear section the LLM can reference:

```
## Analysis

{json.dumps(analysis_result, indent=2)}
```

2. **Original content** from `context.get("context", "")` — the Ward Room
   thread text, DM content, or activity summary that was analyzed.

3. **SILENT short-circuit**: If the Analyze result contains
   `contribution_assessment == "SILENT"` or `should_respond == false`,
   the Compose handler should **skip the LLM call entirely** and return
   `{"output": "[NO_RESPONSE]"}` with `tokens_used=0`. This saves a
   wasted LLM call when analysis already determined silence is appropriate.

### LLM Call Parameters

```python
request = LLMRequest(
    prompt=user_prompt,
    system_prompt=system_prompt,
    tier=spec.tier,
    temperature=0.3,   # Non-zero for natural, varied responses
    max_tokens=2048,    # Higher than Analyze (1024) — full responses
)
```

- **Temperature 0.3** — enough variation for natural conversation, low enough
  for consistency. Analyze uses 0.0 (deterministic); Compose needs creativity.
- **max_tokens 2048** — accommodates full responses with action tags, notebooks,
  proposals. Ward Room posts are 2-4 sentences, but [NOTEBOOK] blocks can be long.

### Result Format

The Compose handler returns its result in a specific shape that
`_execute_sub_task_chain()` expects (cognitive_agent.py:1488):

```python
SubTaskResult(
    sub_task_type=SubTaskType.COMPOSE,
    name=spec.name,
    result={"output": llm_response_text},  # <-- key: "output"
    tokens_used=response.tokens_used,
    duration_ms=duration,
    success=True,
    tier_used=response.tier,
)
```

The `"output"` key is mandatory — `_execute_sub_task_chain()` reads
`result.get("output", "")` at line 1488 to build `llm_output`.

**Do NOT parse action tags in the handler.** The existing `act()` methods on
domain agents already parse [ENDORSE], [REPLY], [DM], etc. The Compose handler
outputs raw text; `act()` handles parsing. Keep responsibilities clean (SRP).

### Error Handling

Follow AnalyzeHandler's pattern exactly (analyze.py:211-294):

1. Guard: `llm_client is None` → return failure SubTaskResult
2. Unknown mode → log warning, fall back to `_DEFAULT_MODE`
3. LLM call exception → catch, log, return failure SubTaskResult
4. No response content → return `{"output": ""}` as success (let `act()` decide)

Do NOT use bare `except Exception: pass`. All exceptions must either produce
a failure SubTaskResult with error message (fail fast) or propagate.

### Registration and Wiring

**In `src/probos/cognitive/sub_tasks/__init__.py`:**

Add import and export:
```python
from probos.cognitive.sub_tasks.compose import ComposeHandler
__all__ = ["AnalyzeHandler", "ComposeHandler", "QueryHandler"]
```

**In `src/probos/startup/finalize.py`:**

Register the ComposeHandler alongside existing handlers. Find the existing
handler registration block (grep for `SubTaskType.ANALYZE` or `AnalyzeHandler`
in finalize.py) and add:

```python
from probos.cognitive.sub_tasks import ComposeHandler
executor.register_handler(SubTaskType.COMPOSE, ComposeHandler(
    llm_client=llm_client,
    runtime=runtime,
))
```

### SubTaskConfig.enabled Flip

**Do NOT flip `SubTaskConfig.enabled` to True in this AD.** The MVP chain
(Query → Analyze → Compose) is now code-complete, but enabling it requires:
- Integration test with a real chain execution path
- Verification that `act()` correctly processes Compose output
- Confirmation that no domain agent `act()` breaks with the new output shape

Flipping enabled is a **follow-up AD** (AD-632e or equivalent) that wires
chains into `decide()` and verifies end-to-end. This AD delivers the handler
only.

## Files

| File | Action | Purpose |
|------|--------|---------|
| `src/probos/cognitive/sub_tasks/compose.py` | CREATE | ComposeHandler + 3 mode prompt builders |
| `src/probos/cognitive/sub_tasks/__init__.py` | EDIT | Add ComposeHandler import/export |
| `src/probos/startup/finalize.py` | EDIT | Register ComposeHandler with executor |
| `tests/test_ad632d_compose_handler.py` | CREATE | Unit tests |

## Tests

### Test File: `tests/test_ad632d_compose_handler.py`

Target: 25-35 tests covering:

**Handler construction & guards:**
- `test_compose_handler_implements_protocol` — isinstance check against SubTaskHandler
- `test_compose_handler_no_llm_client` — returns failure SubTaskResult
- `test_compose_handler_no_runtime` — handler works without runtime (composes without standing orders enrichment)

**Mode dispatch:**
- `test_ward_room_mode_dispatch` — `spec.prompt_template="ward_room_response"` uses correct builder
- `test_dm_mode_dispatch` — `spec.prompt_template="dm_response"` uses correct builder
- `test_proactive_mode_dispatch` — `spec.prompt_template="proactive_observation"` uses correct builder
- `test_unknown_mode_falls_back_to_default` — logs warning, uses ward_room_response
- `test_empty_mode_uses_default` — no prompt_template → ward_room_response

**SILENT short-circuit:**
- `test_silent_analysis_skips_llm_call` — prior Analyze result has `contribution_assessment: "SILENT"` → output is `[NO_RESPONSE]`, tokens_used=0
- `test_should_respond_false_skips_llm_call` — prior Analyze result has `should_respond: false` → same behavior
- `test_non_silent_analysis_calls_llm` — normal analysis → LLM called

**Skill injection:**
- `test_skill_instructions_injected_into_prompt` — `context["_augmentation_skill_instructions"]` appears in system prompt with XML tags
- `test_no_skill_instructions_no_xml` — no augmentation → no `<active_skill>` in prompt

**Action vocabulary:**
- `test_ward_room_has_endorse_syntax` — system prompt contains `[ENDORSE`
- `test_ward_room_has_no_response` — system prompt contains `[NO_RESPONSE]`
- `test_dm_has_no_action_tags` — DM mode system prompt does NOT contain `[ENDORSE` or `[REPLY`
- `test_proactive_has_full_action_vocabulary` — contains [REPLY], [ENDORSE], [NOTEBOOK], [PROPOSAL]

**Result format:**
- `test_result_has_output_key` — `result.result["output"]` contains the LLM response text
- `test_result_type_is_compose` — `result.sub_task_type == SubTaskType.COMPOSE`
- `test_result_tracks_tokens` — tokens_used from LLM response propagated
- `test_result_tracks_tier` — tier_used from LLM response propagated

**Prior results integration:**
- `test_analysis_json_in_user_prompt` — Analyze SubTaskResult's output appears in user prompt
- `test_no_prior_analysis_still_works` — empty prior_results → compose works (graceful degradation)
- `test_only_successful_analysis_used` — failed Analyze result ignored

**Error handling:**
- `test_llm_call_failure_returns_error` — LLM raises → SubTaskResult with success=False
- `test_empty_llm_response_returns_empty_output` — empty content → `{"output": ""}`, success=True

**Identity injection:**
- `test_callsign_in_system_prompt` — `context["_callsign"]` value appears in composed prompt
- `test_department_in_system_prompt` — `context["_department"]` value appears in composed prompt

### Test Patterns

Follow AnalyzeHandler test patterns from `tests/test_ad632c_analyze_handler.py`:
- Mock `llm_client` with `AsyncMock` returning `MagicMock(content=..., tokens_used=..., tier=...)`
- Use real `SubTaskSpec` and `SubTaskResult` instances (not mocks)
- Import from `probos.cognitive.sub_task` for types
- Import from `probos.cognitive.sub_tasks.compose` for handler
- Use `pytest.mark.asyncio` for async tests

## Verification

```bash
cd d:\ProbOS
python -m pytest tests/test_ad632d_compose_handler.py -v
```

All tests must pass. No existing tests should break (this is purely additive —
new file + 2 small edits to existing files).

## What This Does NOT Do

- Does NOT flip `SubTaskConfig.enabled` — that's a follow-up AD
- Does NOT wire chains into `decide()` — chains are already wired but disabled
- Does NOT parse action tags — `act()` handles that downstream
- Does NOT replace existing composition code in cognitive_agent.py — the handler
  is registered alongside the single-call path, used only when sub-task chains
  are enabled
- Does NOT add Evaluate or Reflect handlers (AD-632e/632f)
