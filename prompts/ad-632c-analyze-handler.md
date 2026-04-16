# AD-632c: Analyze Sub-Task Handler (Focused LLM Comprehension)

**Issue:** #233
**Depends on:** AD-632a (COMPLETE — sub_task.py foundation), AD-632b (COMPLETE — QueryHandler)
**Absorbs:** None — greenfield handler, wraps existing LLM client
**Principles:** SRP, Open/Closed, DIP, ISP, Law of Demeter, Fail Fast, Defense in Depth

## Problem

The Sub-Task Protocol (AD-632a) defines five sub-task types and an executor
engine. AD-632b delivered the QUERY handler (deterministic, zero LLM calls).
No LLM-calling handler exists yet — the ANALYZE sub-task type, which is the
first LLM step in every proposed chain (Query → **Analyze** → Compose), has
no implementation.

The ANALYZE handler performs **focused thread/context comprehension** — a
narrow LLM call that reads input and produces structured analysis WITHOUT
composing a response. This separation is the core value of the Sub-Task
Protocol:

- **Current (Level 2):** One LLM call simultaneously parses thread, recalls
  context, reasons about novelty, composes response, and emits structured
  actions. When prompt length exceeds the model's effective attention window,
  the lowest-salience instructions (typically skill guidance) get dropped.

- **With ANALYZE (Level 3):** The analysis step focuses entirely on
  comprehension — "what has been said? what's new? what's my department's
  angle?" — with a narrow prompt free of response formatting, action
  vocabulary, and skill instructions. The downstream COMPOSE step (AD-632d)
  then receives the structured analysis and focuses entirely on response
  generation with skill compliance.

This is the DECOMP principle (Khot et al., ICLR 2023): "individual reasoning
steps embedded in complex contexts are harder to learn than the same steps in
isolation." The Analyze handler isolates the comprehension step.

## Design

### Handler Architecture

Create a single handler class `AnalyzeHandler` that implements the
`SubTaskHandler` protocol (sub_task.py line 80-92):

```python
async def __call__(
    self,
    spec: SubTaskSpec,
    context: dict,
    prior_results: list[SubTaskResult],
) -> SubTaskResult
```

Unlike `QueryHandler` (deterministic, zero LLM calls), the `AnalyzeHandler`
makes **exactly one LLM call** per invocation. It constructs a focused
analysis prompt, calls the LLM via `BaseLLMClient.complete()`, parses the
structured JSON response, and returns a `SubTaskResult` with the analysis
in the `result` dict.

### Constructor

```python
class AnalyzeHandler:
    def __init__(
        self,
        *,
        llm_client: Any,      # BaseLLMClient — for the LLM call
        runtime: Any,          # ProbOSRuntime — for department/personality lookup
    ) -> None:
```

Two dependencies injected via constructor (DIP):
- `llm_client`: the `BaseLLMClient` instance (same one agents use). Needed
  to make the LLM call. Accessed via `runtime.llm_client` or passed directly.
- `runtime`: for resolving agent metadata (department, callsign, personality
  block). Accessed via `getattr()` with defensive checks (Law of Demeter).

The handler does NOT hold a reference to any specific agent — it serves all
cognitive crew agents. Agent-specific context (department, callsign) comes
from the `context` dict and `agent_id`/`agent_type` resolution at call time.

### Analysis Modes

The handler supports multiple **analysis modes** selected by
`spec.prompt_template`. Each mode defines what kind of comprehension the LLM
should perform:

| Mode Key | Use Case | Structured Output Keys |
|----------|----------|----------------------|
| `thread_analysis` | Ward Room thread comprehension | `topics_covered`, `gaps`, `endorsement_candidates`, `contribution_assessment`, `novel_posts` |
| `situation_review` | Proactive think cycle — broad situation assessment | `active_threads`, `pending_actions`, `priority_topics`, `department_relevance` |
| `dm_comprehension` | Direct message understanding | `sender_intent`, `key_questions`, `required_actions`, `emotional_tone` |

The mode key is stored in `spec.prompt_template` (sub_task.py line 47).
The handler dispatches to a prompt-building function based on this key. This
is Open/Closed — new analysis modes are added by registering new prompt
builders in a dispatch dict, zero changes to `__call__()`.

If `spec.prompt_template` is empty or unrecognized, the handler falls back
to `thread_analysis` as the default mode (Fail Fast with sensible default).

### Prompt Construction

The Analyze handler builds **two prompt components** matching the
`LLMRequest` interface (types.py line 186-197):

**System prompt (narrow):**
```
You are {callsign}, a {role} in the {department} department.

Your task is to ANALYZE the following content. Do NOT compose a response.
Do NOT suggest what to say. Only analyze what has been said and identify
what is relevant to your department's expertise.

Respond with a JSON object containing your structured analysis. No
conversational text outside the JSON block.
```

The system prompt is deliberately narrow — it includes agent identity
(callsign, department, role) for perspective but **excludes**:
- Standing orders (those are for behavior, not comprehension)
- Augmentation skill instructions (those go to Compose, AD-632d)
- Action vocabulary (ENDORSE/REPLY/DM — those are for response generation)
- Self-monitoring enforcement (zone awareness — that's for Compose)

**User prompt (content-focused):**
For `thread_analysis` mode:
```
## Thread Content

{thread_content}

## Context

{episodic_memories_if_any}
{query_results_from_prior_steps}

## Analysis Required

Analyze this thread from your department's perspective ({department}):

1. **topics_covered**: List each post's core claim or contribution (one
   sentence per post). Include the author callsign.
2. **novel_posts**: Which posts contain genuinely NEW information vs
   restating what others said? List post indices or author callsigns.
3. **gaps**: What has NOT been addressed that your department ({department})
   could contribute? Be specific — what analysis, data, or perspective
   is missing?
4. **endorsement_candidates**: Which posts are strong, novel contributions
   worth endorsing? List callsigns. Empty list if none qualify.
5. **contribution_assessment**: One of: "RESPOND" (you have something new
   to add), "ENDORSE" (agree with existing analysis, nothing new), or
   "SILENT" (topic outside your scope or fully covered).

Return a JSON object with these 5 keys. No other text.
```

### Context Consumption

The handler consumes data from the `context` dict (the observation) and
from `prior_results` (output of preceding QUERY step):

**From `context` dict:**
- `context["context"]` — raw thread text (the conversation content)
- `context["params"]` — thread metadata (channel_name, title, author, etc.)
- `context["recent_memories"]` — episodic memories (if present)
- `context["intent"]` — intent type for mode selection

**From `prior_results`:**
- If a QUERY step ran first, its `SubTaskResult.result` dict contains
  structured data (`thread_metadata`, `comm_stats`, etc.). The Analyze
  handler should incorporate any available query results into the user prompt
  as factual context — e.g., "This thread has 5 replies from 3 contributors."

**Explicitly excluded from the analysis prompt:**
- `context["_augmentation_skill_instructions"]` — goes to Compose (AD-632d)
- `context["cognitive_skill_instructions"]` — goes to Compose
- `context["_source_attribution"]` — goes to Compose

### LLM Call

The handler constructs and executes an `LLMRequest`:

```python
from probos.types import LLMRequest

request = LLMRequest(
    prompt=user_prompt,
    system_prompt=system_prompt,
    tier=spec.tier,                # Use spec's tier, NOT _resolve_tier()
    temperature=0.0,               # Deterministic analysis
    max_tokens=1024,               # Analysis is shorter than full response
)

response = await self._llm_client.complete(request)
```

Key design decisions:
- `tier=spec.tier` — the SubTaskSpec's tier field overrides the agent's
  default. This allows chains to route Analyze to a "fast" tier and Compose
  to a "deep" tier.
- `temperature=0.0` — analysis should be deterministic/reproducible.
- `max_tokens=1024` — analysis output is structured JSON, typically shorter
  than a full response. Saves tokens.

### Response Parsing

The handler extracts structured JSON from the LLM response using the existing
`extract_json()` utility (probos/utils/json_extract.py line 17):

```python
from probos.utils.json_extract import extract_json

try:
    analysis = extract_json(response.content)
except ValueError:
    # LLM returned non-JSON — fail the sub-task
    return SubTaskResult(
        sub_task_type=SubTaskType.ANALYZE,
        name=spec.name,
        result={},
        tokens_used=response.tokens_used,
        duration_ms=duration,
        success=False,
        error="Failed to parse analysis JSON from LLM response",
        tier_used=response.tier,
    )
```

The parsed JSON dict becomes `SubTaskResult.result`. No validation of
specific keys is performed at this layer — the Analyze handler's job is to
get a structured response from the LLM. Key validation (if needed) is the
responsibility of downstream consumers (Compose handler, AD-632d) or future
schema enforcement.

### Agent Identity Resolution

The handler needs agent identity (callsign, department, role) to build the
analysis prompt. Since handlers don't receive the agent object directly
(ISP — handlers depend on the narrow `SubTaskHandler` protocol, not the
full agent interface), identity comes from two sources:

1. **`context` dict** — the executor passes `agent_id` and `agent_type` as
   keyword args to `execute()` (sub_task.py line 167). These are NOT in the
   handler's `context` parameter — they are used by the executor for journal
   recording.

2. **Resolution via runtime** — the handler looks up identity from runtime:

```python
# Resolve agent identity for prompt context
agent = None
if self._runtime and hasattr(self._runtime, 'registry'):
    agents = self._runtime.registry.get_by_type(agent_type)
    if agents:
        agent = agents[0]

callsign = getattr(agent, 'callsign', agent_type) if agent else agent_type
department = getattr(agent, 'department', None)
if department is None and agent:
    from probos.cognitive.standing_orders import get_department
    department = get_department(agent.agent_type) or "unassigned"
```

**Problem:** The handler's `__call__` signature receives only `(spec, context,
prior_results)` — no `agent_id` or `agent_type`. The executor passes
these to `execute()` but they don't flow to the handler.

**Solution:** The `context` dict already contains `intent` and `params`.
For `ward_room_notification`, `params` contains `channel_name` and
`author_callsign`. The handler should also receive agent identity via
`context` keys. The activation trigger (AD-632f) that builds the
`SubTaskChain` will inject `_agent_id`, `_agent_type`, `_callsign`, and
`_department` into the observation dict before passing it to
`_execute_sub_task_chain()`. For AD-632c, add these keys to the observation
in `_execute_sub_task_chain()` (cognitive_agent.py line 1431+) so they are
available to all handlers:

```python
# In CognitiveAgent._execute_sub_task_chain():
# Inject agent identity into context for handler access
observation["_agent_id"] = self.id
observation["_agent_type"] = self.agent_type
observation["_callsign"] = getattr(self, 'callsign', self.agent_type)
_dept = getattr(self, 'department', None)
if _dept is None:
    from probos.cognitive.standing_orders import get_department
    _dept = get_department(self.agent_type) or "unassigned"
observation["_department"] = _dept
```

This is a small addition to `_execute_sub_task_chain()` that benefits ALL
handlers (Open/Closed). The handler reads `context["_callsign"]` and
`context["_department"]` — simple dict lookup, no agent object coupling.

### Result Format

The handler returns a `SubTaskResult` with:

- `sub_task_type = SubTaskType.ANALYZE`
- `name = spec.name` (e.g., `"analyze-thread"`)
- `result = parsed_analysis_dict` — the structured JSON from the LLM
- `tokens_used = response.tokens_used` — actual LLM token consumption
- `duration_ms` — wall clock time for the full operation
- `success = True/False`
- `error = ""` or error message on failure
- `tier_used = response.tier` — actual tier used by the LLM

The `result` dict for `thread_analysis` mode contains:
```python
{
    "topics_covered": ["...", "..."],
    "novel_posts": ["callsign_a", "callsign_c"],
    "gaps": ["..."],
    "endorsement_candidates": ["callsign_b"],
    "contribution_assessment": "RESPOND"  # or "ENDORSE" or "SILENT"
}
```

### Error Handling — Fail Fast, Degrade Gracefully

Three tiers per ProbOS error handling policy:

1. **LLM client unavailable** (`self._llm_client is None`): Return
   `SubTaskResult(success=False, error="LLM client not available")`. The
   executor aborts (if `spec.required=True`) or skips. Log at WARNING.

2. **LLM call exception** (timeout, API error, model unavailable): Catch
   `Exception`, return `SubTaskResult(success=False, error=str(exc))`.
   Log at WARNING. Do NOT retry — the executor's chain-level timeout and
   fallback handle retry logic.

3. **Parse failure** (LLM returned non-JSON or malformed JSON): Return
   `SubTaskResult(success=False, error="Failed to parse analysis JSON")`.
   Log at WARNING. Include `response.content[:200]` in the error for
   debugging (truncated to avoid log bloat).

### Token Accounting

The Analyze handler reports `tokens_used = response.tokens_used` from the
`LLMResponse`. The executor records this to the CognitiveJournal at
sub_task.py line 314-326 with `dag_node_id = "st:{chain_id}:{index}:analyze"`.
The handler does NOT do its own journal recording — the executor handles it.

### SubTaskConfig.enabled

This AD does **NOT** flip `enabled` to `True`. The Analyze handler alone
is insufficient for a useful chain — chains need a COMPOSE handler (AD-632d)
to produce final output. Enabling happens in AD-632d or AD-632f when the
full Query → Analyze → Compose chain is operational.

## Files to Create

| File | Content |
|------|---------|
| `src/probos/cognitive/sub_tasks/analyze.py` | `AnalyzeHandler` class + analysis mode prompt builders + dispatch table |

## Files to Modify

| File | Change |
|------|--------|
| `src/probos/cognitive/sub_tasks/__init__.py` | Add `AnalyzeHandler` to exports |
| `src/probos/cognitive/cognitive_agent.py` | Inject `_agent_id`, `_agent_type`, `_callsign`, `_department` into observation in `_execute_sub_task_chain()` (line 1431+) |
| `src/probos/startup/finalize.py` | Register `AnalyzeHandler` with `SubTaskExecutor` (add after QueryHandler registration, line 196) |

## Files to Verify (NOT Modify)

| File | Why Verify |
|------|------------|
| `src/probos/cognitive/sub_task.py` | Confirm `SubTaskHandler` protocol (line 80-92), `SubTaskType.ANALYZE` (line 32), `SubTaskSpec.prompt_template` (line 47), context filtering (lines 269-275), handler call site (line 280), journal recording (lines 311-326) |
| `src/probos/types.py` | Confirm `LLMRequest` (line 186-197: prompt, system_prompt, tier, temperature, max_tokens), `LLMResponse` (line 199-211: content, tier, tokens_used, prompt_tokens, completion_tokens, error) |
| `src/probos/utils/json_extract.py` | Confirm `extract_json(content: str) -> dict` (line 17) — used for parsing LLM JSON response |
| `src/probos/cognitive/standing_orders.py` | Confirm `get_department(agent_type: str) -> str | None` (line 66), `_build_personality_block(agent_type, department, callsign_override)` (line 130) — for agent identity resolution |
| `src/probos/cognitive/cognitive_agent.py` | Confirm `_execute_sub_task_chain()` at line 1431, `_extract_thread_metadata()` at line 2057 (static method, potential reuse) |
| `src/probos/cognitive/sub_tasks/query.py` | Confirm `SubTaskResult` construction pattern (lines 237-308) — follow same pattern for consistency |

## Do NOT Change

- `src/probos/cognitive/sub_task.py` — foundation is complete, no changes needed
- `src/probos/config.py` — do NOT flip `enabled` to True
- `src/probos/events.py` — event types already defined
- `src/probos/cognitive/standing_orders.py` — read only, do not modify
- `src/probos/utils/json_extract.py` — use existing utility, do not modify
- Any Ward Room or Trust service files — Analyze handler calls the LLM, not services directly
- Any skill files — skill injection is AD-632d (Compose handler)

## Engineering Principles Compliance

| Principle | Application |
|-----------|-------------|
| **SRP** | `AnalyzeHandler` has one responsibility: focused LLM comprehension. No response composition (Compose), no quality checking (Evaluate), no data retrieval (Query). Each analysis mode's prompt builder is a separate function. |
| **Open/Closed** | New analysis modes are added by registering new prompt builder functions in the dispatch table — zero changes to `__call__()`. `_execute_sub_task_chain()` identity injection benefits all future handlers without further modification. |
| **DIP** | Handler depends on `BaseLLMClient` abstraction (not a concrete client). Receives `llm_client` and `runtime` via constructor injection. Identity resolved from `context` dict keys, not agent object coupling. |
| **ISP** | Handler implements the narrow `SubTaskHandler` protocol (3 params, 1 return). Does not depend on `SubTaskExecutor`, `CognitiveAgent`, or journal internals. |
| **Law of Demeter** | Handler accesses `self._llm_client.complete()` (one dot). Runtime access limited to `registry.get_by_type()` if needed. Agent identity via flat `context` dict keys, not reaching through agent objects. |
| **Fail Fast** | LLM unavailable → immediate failure result. JSON parse failure → immediate failure result. Unrecognized mode → falls back to default `thread_analysis` with logged warning (not silent). |
| **Defense in Depth** | Three error tiers: LLM unavailable, LLM exception, parse failure. Timeout enforcement via `spec.timeout_ms` (in executor). Truncated error content for log safety. Token budget respected via `max_tokens=1024`. |
| **DRY** | Uses existing `extract_json()` utility from `probos.utils.json_extract` — does not reimplement JSON extraction. Uses existing `get_department()` from `standing_orders.py` — does not duplicate department lookup logic. |

## Test Requirements

### Unit Tests (`tests/test_ad632c_analyze_handler.py`)

All tests use a `MockLLMClient` that returns controlled responses — no real
LLM calls. The mock should implement `BaseLLMClient.complete()` returning
`LLMResponse` with configured `content`, `tokens_used`, and `tier`.

#### 1. TestAnalyzeHandlerProtocol (4 tests)
- `test_implements_sub_task_handler` — `isinstance(handler, SubTaskHandler)` is True (runtime_checkable)
- `test_returns_sub_task_result` — return type is `SubTaskResult`
- `test_sub_task_type_is_analyze` — `.sub_task_type == SubTaskType.ANALYZE`
- `test_tokens_reported` — `.tokens_used > 0` (unlike Query which is always 0)

#### 2. TestThreadAnalysisMode (5 tests)
- `test_thread_analysis_parses_json` — mock LLM returns valid JSON, handler parses to `result` dict with expected keys
- `test_thread_analysis_includes_topics` — `result["topics_covered"]` is a list
- `test_thread_analysis_contribution_assessment` — `result["contribution_assessment"]` is one of "RESPOND", "ENDORSE", "SILENT"
- `test_thread_analysis_with_prior_query_results` — prior QUERY result data incorporated into analysis prompt
- `test_thread_analysis_default_mode` — empty `spec.prompt_template` defaults to `thread_analysis`

#### 3. TestSituationReviewMode (3 tests)
- `test_situation_review_parses_json` — valid JSON with `active_threads`, `pending_actions`, `priority_topics`, `department_relevance`
- `test_situation_review_mode_selection` — `spec.prompt_template = "situation_review"` routes to correct prompt builder
- `test_situation_review_context_keys` — handler uses appropriate context keys for proactive_think intent

#### 4. TestDMComprehensionMode (2 tests)
- `test_dm_comprehension_parses_json` — valid JSON with `sender_intent`, `key_questions`, `required_actions`, `emotional_tone`
- `test_dm_comprehension_mode_selection` — `spec.prompt_template = "dm_comprehension"` routes correctly

#### 5. TestLLMCallConstruction (5 tests)
- `test_uses_spec_tier` — `LLMRequest.tier` set from `spec.tier`, NOT hardcoded
- `test_temperature_zero` — `LLMRequest.temperature == 0.0`
- `test_max_tokens_1024` — `LLMRequest.max_tokens == 1024`
- `test_system_prompt_excludes_skill_instructions` — system prompt does NOT contain augmentation skill text
- `test_system_prompt_includes_department` — system prompt mentions agent's department

#### 6. TestAgentIdentityInjection (4 tests)
- `test_context_has_agent_id` — `context["_agent_id"]` available to handler
- `test_context_has_callsign` — `context["_callsign"]` available
- `test_context_has_department` — `context["_department"]` available
- `test_department_fallback_to_standing_orders` — if agent has no `department` attr, falls back to `get_department(agent_type)`

#### 7. TestErrorHandling (4 tests)
- `test_llm_client_none` — `success=False`, `error="LLM client not available"`
- `test_llm_call_exception` — mock LLM raises exception, `success=False`, error message includes exception text
- `test_json_parse_failure` — mock LLM returns non-JSON text, `success=False`, error mentions parse failure
- `test_error_content_truncated` — error message truncates long LLM content to avoid log bloat

#### 8. TestDurationAndTokenTracking (3 tests)
- `test_duration_ms_recorded` — `result.duration_ms > 0`
- `test_tokens_from_llm_response` — `result.tokens_used == response.tokens_used`
- `test_tier_from_llm_response` — `result.tier_used == response.tier`

#### 9. TestContextFiltering (3 tests)
- `test_skill_instructions_excluded` — `_augmentation_skill_instructions` NOT passed to LLM prompt
- `test_cognitive_skill_excluded` — `cognitive_skill_instructions` NOT passed to LLM prompt
- `test_thread_content_included` — `context["context"]` (thread text) IS included in LLM prompt

#### 10. TestExecutorIntegration (4 tests)
- `test_register_with_executor` — `executor.register_handler(SubTaskType.ANALYZE, handler)` succeeds
- `test_executor_can_execute_analyze_chain` — full chain execution with Analyze step
- `test_executor_records_journal` — journal.record() IS called for ANALYZE steps (unlike QUERY which is skipped)
- `test_query_then_analyze_chain` — two-step chain: QUERY feeds data into ANALYZE via `prior_results`

#### 11. TestStartupWiring (2 tests)
- `test_analyze_handler_registered` — after finalize_startup, executor has handler for `SubTaskType.ANALYZE`
- `test_analyze_handler_receives_llm_client` — handler's `_llm_client` is the runtime's LLM client

**Total: 39 tests across 11 classes.**

### Existing test verification

```
pytest tests/test_ad632c_analyze_handler.py -v
pytest tests/test_ad632a_sub_task_foundation.py -v
pytest tests/test_ad632b_query_handler.py -v
pytest tests/ -k "sub_task" --tb=short
pytest tests/ -k "cognitive_agent" --tb=short
```

## Verification Checklist

- [ ] `src/probos/cognitive/sub_tasks/analyze.py` exists and is importable
- [ ] `AnalyzeHandler` implements `SubTaskHandler` protocol (runtime_checkable)
- [ ] `AnalyzeHandler.__init__` accepts `llm_client` and `runtime` via keyword-only constructor injection
- [ ] Analysis mode dispatch via `spec.prompt_template` — not hardcoded
- [ ] Three modes implemented: `thread_analysis`, `situation_review`, `dm_comprehension`
- [ ] Empty/unknown `prompt_template` defaults to `thread_analysis`
- [ ] LLM called via `self._llm_client.complete(LLMRequest(...))` with `tier=spec.tier`
- [ ] `temperature=0.0` and `max_tokens=1024` on LLM request
- [ ] Response parsed via `extract_json()` from `probos.utils.json_extract`
- [ ] `tokens_used` set from `response.tokens_used` (NOT hardcoded 0)
- [ ] `tier_used` set from `response.tier`
- [ ] `duration_ms` calculated via `time.monotonic()` delta
- [ ] System prompt includes agent callsign and department
- [ ] System prompt EXCLUDES augmentation skill instructions
- [ ] System prompt EXCLUDES standing orders and action vocabulary
- [ ] User prompt includes thread content from `context["context"]`
- [ ] User prompt incorporates prior QUERY results from `prior_results` (if any)
- [ ] Agent identity injected into observation in `_execute_sub_task_chain()` (`_agent_id`, `_agent_type`, `_callsign`, `_department`)
- [ ] Department resolved with fallback to `standing_orders.get_department()`
- [ ] LLM client None → `SubTaskResult(success=False)`, not exception
- [ ] LLM exception → caught, wrapped in error result, logged at WARNING
- [ ] JSON parse failure → `SubTaskResult(success=False)`, error content truncated
- [ ] Handler does NOT do journal recording (executor handles it per sub_task.py line 311-326)
- [ ] Handler does NOT create episodic memory entries (invariant I2)
- [ ] Handler does NOT call circuit breaker (invariant I4)
- [ ] `sub_tasks/__init__.py` exports `AnalyzeHandler`
- [ ] `startup/finalize.py` registers `AnalyzeHandler` with executor after QueryHandler
- [ ] `SubTaskConfig.enabled` remains `False` (not flipped in this AD)
- [ ] No changes to sub_task.py, config.py, events.py, standing_orders.py, json_extract.py
- [ ] All existing tests still pass (zero regressions)
