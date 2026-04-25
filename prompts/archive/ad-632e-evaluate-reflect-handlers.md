# AD-632e: Evaluate & Reflect Sub-Task Handlers (Quality Gates)

**Issue:** TBD (will be created)
**Depends on:** AD-632a (COMPLETE), AD-632c (COMPLETE), AD-632d (COMPLETE), AD-632f (COMPLETE)
**Absorbs:** AD-631 Pre-Submit Check pattern (communication-discipline SKILL.md:117-128), AD-634 Pre-Write Verification Gate pattern (notebook-quality SKILL.md:144-158). Does NOT absorb AD-568e check_faithfulness() or AD-589 check_introspective_faithfulness() — those remain as post-decision heuristics.
**Academic lineage:** Reflexion (Shinn et al., NeurIPS 2023) — same-session self-critique. Tree of Thoughts (Yao et al., NeurIPS 2023) — deliberate evaluation. SOAR reflective meta-reasoning via impasse-driven subgoaling. ACT-R procedural/declarative separation.
**Principles:** Single Responsibility, Open/Closed, DIP, Fail Fast, Law of Demeter

## Problem

The MVP sub-task chain (Query → Analyze → Compose) is live. But there is no
in-chain quality gate — the Compose handler's output goes directly to `act()`
without any structured evaluation or self-critique capability.

Three quality mechanisms exist today, but none operate **within** the chain:

1. **AD-568e `check_faithfulness()`** — post-decision heuristic (no LLM call),
   runs AFTER `decide()` returns. Observational only — logs results, feeds
   Counselor, never blocks or modifies output.
2. **AD-589 `check_introspective_faithfulness()`** — post-decision regex check
   against CognitiveArchitectureManifest. Also observational only.
3. **AD-631 Pre-Submit Check** — baked into skill prompt instructions. Tells the
   LLM to self-check before finalizing, but runs inside the same Compose call
   competing for attention with personality, standing orders, action vocabulary,
   and the actual response content.

The gap: the Pre-Submit Check (AD-631) is the right idea but operates in a
degraded position — competing for attention within a single crowded LLM call.
The cognitive sub-task protocol exists precisely to give focused attention to
focused tasks. Evaluate and Reflect handlers provide that focused attention
for quality gating.

**Research confirmation (cognitive-sub-task-protocol.md:505):** "The skill's
self-verification gate (AD-631) maps to a **Reflect** sub-task."

## Design

### Two Handlers, Distinct Responsibilities

| Handler | Type | Role | LLM? | Fires when |
|---------|------|------|------|------------|
| EvaluateHandler | `SubTaskType.EVALUATE` | Criteria-based quality scoring | 1 call | Chain includes EVALUATE step |
| ReflectHandler | `SubTaskType.REFLECT` | Self-critique and revision | 1 call | Chain includes REFLECT step |

**Evaluate** judges the Compose output against explicit criteria (novelty,
relevance, factual grounding, contribution assessment). Returns a structured
verdict: pass/fail + score + per-criterion results.

**Reflect** receives both Compose output and Evaluate verdict. Performs
self-critique from the agent's perspective — checks the draft against skill
rules, standing orders compliance, and the Pre-Submit Check. Returns either
the original output (approved) or a revised version.

These are **optional steps** added to chains that opt in. The default chains
built by `_build_chain_for_intent()` (AD-632f) remain 3-step for now. A
follow-up update to `_build_chain_for_intent()` (included in this AD's scope)
adds the steps with `required=False` so chain failures degrade gracefully
to the Compose output.

### Module Locations

- `src/probos/cognitive/sub_tasks/evaluate.py` — EvaluateHandler
- `src/probos/cognitive/sub_tasks/reflect.py` — ReflectHandler

### Handler Architecture

Both handlers follow the established pattern from AnalyzeHandler (AD-632c)
and ComposeHandler (AD-632d):

```python
class EvaluateHandler:
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

Same constructor signature for ReflectHandler. DIP — depends on abstract
llm_client and runtime, not concrete implementations.

---

## EvaluateHandler

### Evaluation Modes (Open/Closed Dispatch)

Three modes, dispatched via `spec.prompt_template`:

| Mode | `prompt_template` value | Evaluates |
|------|------------------------|-----------|
| Ward Room quality | `"ward_room_quality"` | Novelty, relevance, contribution value |
| Proactive quality | `"proactive_quality"` | Observation value, actionability, insight depth |
| Notebook quality | `"notebook_quality"` | Analytical depth, conclusion presence, threading |

Default mode: `"ward_room_quality"`.

```python
_EVALUATION_MODES: dict[str, EvaluationModeBuilder] = {
    "ward_room_quality": _build_ward_room_eval_prompt,
    "proactive_quality": _build_proactive_eval_prompt,
    "notebook_quality": _build_notebook_eval_prompt,
}
_DEFAULT_MODE = "ward_room_quality"
```

### System Prompt Construction

Evaluate uses a **narrow, criteria-focused prompt** — similar to Analyze
(identity + department only), NOT the full standing orders prompt that Compose
uses. The system prompt should:

1. Identify the agent (callsign, department) for perspective
2. Define the evaluation role: "You are evaluating a draft response for quality"
3. List the criteria for this mode
4. Request structured JSON output

```python
callsign = context.get("_callsign", "agent")
department = context.get("_department", "")
```

### Evaluation Criteria Per Mode

**Ward Room quality** (absorbed from communication-discipline Pre-Submit Check):
1. **Novelty** — Does the response contain at least one fact, metric, or
   conclusion not already present in the thread? (from SKILL.md:119-121)
2. **Opening quality** — Does the first sentence state a conclusion, not a
   process description? No "Looking at…" / "I notice…" / "I can confirm…"
   openers. (from SKILL.md:122-123)
3. **Non-redundancy** — Is this more than confirming what someone already said?
   (from SKILL.md:124-125)
4. **Relevance** — Does the response address the thread topic from this agent's
   departmental perspective?

**Proactive quality:**
1. **Observation value** — Does the observation contain actionable insight, not
   just restating known status?
2. **Action appropriateness** — Are action tags ([REPLY], [NOTEBOOK], [ENDORSE])
   well-targeted and warranted?
3. **Departmental lens** — Does the observation reflect this agent's expertise?
4. **Silence appropriateness** — Should this be [NO_RESPONSE] instead?

**Notebook quality** (absorbed from notebook-quality Pre-Write Verification Gate):
1. **Conclusion presence** — Does the entry contain a conclusion, finding, or
   hypothesis? (from SKILL.md:148-150)
2. **Threading** — Does the entry build on prior notebook entries on this topic?
   (from SKILL.md:151-153)
3. **Differentiation** — Does the entry contain analysis beyond what was said in
   the Ward Room thread? (from SKILL.md:154-156)

### User Prompt Construction

The user prompt carries:

1. **Draft response** from the last successful COMPOSE result in `prior_results`.
   Use `_get_compose_output()` helper (same pattern as compose.py's
   `_get_analysis_result()`).
2. **Analysis context** from the last successful ANALYZE result (the structured
   analysis informing the draft).
3. **Original content** from `context.get("context", "")` — the thread/activity
   that was being responded to.

```
## Draft Response to Evaluate

{compose_output}

## Analysis That Informed This Draft

{json.dumps(analysis_result, indent=2)}

## Original Content

{original_context}
```

### LLM Call Parameters

```python
request = LLMRequest(
    prompt=user_prompt,
    system_prompt=system_prompt,
    tier=spec.tier,
    temperature=0.0,     # Deterministic judgment — no creativity needed
    max_tokens=512,      # Structured verdict, not prose
)
```

### Result Format

```python
SubTaskResult(
    sub_task_type=SubTaskType.EVALUATE,
    name=spec.name,
    result={
        "pass": True/False,
        "score": 0.0-1.0,
        "criteria": {
            "novelty": {"pass": True/False, "reason": "..."},
            "opening_quality": {"pass": True/False, "reason": "..."},
            ...
        },
        "recommendation": "approve" | "revise" | "suppress",
    },
    tokens_used=response.tokens_used,
    duration_ms=duration,
    success=True,
    tier_used=response.tier,
)
```

- `"pass"` — overall verdict (all criteria pass)
- `"score"` — 0.0-1.0 quality score (fraction of criteria passed)
- `"criteria"` — per-criterion pass/fail with reason
- `"recommendation"` — `"approve"` (use as-is), `"revise"` (Reflect should
  rewrite), `"suppress"` (replace with [NO_RESPONSE] or [ENDORSE])

Parse the LLM response with `extract_json()` (same utility used by
AnalyzeHandler at analyze.py:17). Fall back to `{"pass": True, "score": 1.0,
"recommendation": "approve"}` on parse failure — fail-open to avoid blocking
good output on parser errors.

### Short-Circuit: Suppress Recommendation

If Evaluate returns `recommendation == "suppress"`, Reflect can skip the LLM
call entirely and return `{"output": "[NO_RESPONSE]"}` with `tokens_used=0`.
This generalizes the SILENT short-circuit pattern from Compose (compose.py:31-40).

### Error Handling

Follow AnalyzeHandler pattern (analyze.py):
1. Guard: `llm_client is None` → return failure SubTaskResult
2. Unknown mode → log warning, fall back to `_DEFAULT_MODE`
3. LLM call exception → catch, log, return failure SubTaskResult
4. JSON parse failure → log warning, return pass-by-default result (fail-open)

---

## ReflectHandler

### Reflection Modes (Open/Closed Dispatch)

Three modes, dispatched via `spec.prompt_template`:

| Mode | `prompt_template` value | Reflects on |
|------|------------------------|-------------|
| Ward Room reflection | `"ward_room_reflection"` | Communication skill compliance |
| Proactive reflection | `"proactive_reflection"` | Observation depth and value |
| General reflection | `"general_reflection"` | Standing orders compliance |

Default mode: `"ward_room_reflection"`.

```python
_REFLECTION_MODES: dict[str, ReflectionModeBuilder] = {
    "ward_room_reflection": _build_ward_room_reflect_prompt,
    "proactive_reflection": _build_proactive_reflect_prompt,
    "general_reflection": _build_general_reflect_prompt,
}
_DEFAULT_MODE = "ward_room_reflection"
```

### System Prompt Construction

Reflect uses a **focused self-critique prompt**. Not the full standing orders
prompt (that's Compose's job), but identity plus the specific skill rules
being checked:

1. Agent identity (callsign, department)
2. Self-critique role: "You are reviewing your own draft for quality"
3. The relevant Pre-Submit Check criteria (mode-specific)
4. Instruction to either approve the draft unchanged or produce a revised version
5. If skill instructions are present in context
   (`_augmentation_skill_instructions`), include the skill's self-verification
   criteria — this is where AD-631's Pre-Submit Check gets focused attention

### Evaluation Verdict Integration

If the prior EVALUATE result is available, its verdict is included in the
user prompt so Reflect knows what criteria failed:

```
## Evaluation Verdict

{json.dumps(evaluate_result, indent=2)}
```

If no EVALUATE result exists (chain has Reflect without Evaluate), Reflect
operates independently using skill criteria alone.

### Suppress Short-Circuit

If the prior EVALUATE result has `recommendation == "suppress"`, Reflect
skips the LLM call and returns:

```python
SubTaskResult(
    sub_task_type=SubTaskType.REFLECT,
    name=spec.name,
    result={"output": "[NO_RESPONSE]", "revised": False, "suppressed": True},
    tokens_used=0,
    duration_ms=...,
    success=True,
    tier_used="",
)
```

### User Prompt Construction

```
## Your Draft Response

{compose_output}

## Evaluation Verdict (if available)

{evaluate_verdict_json}

## Self-Critique Instructions

Review your draft against these criteria. Either:
(A) Approve: return the draft unchanged as "output"
(B) Revise: return an improved version as "output" with "revised": true
(C) Suppress: if the draft adds no value, return "[NO_RESPONSE]" as "output"

Respond with JSON only.
```

### LLM Call Parameters

```python
request = LLMRequest(
    prompt=user_prompt,
    system_prompt=system_prompt,
    tier=spec.tier,
    temperature=0.1,     # Mostly deterministic, slight revision creativity
    max_tokens=2048,     # Same as Compose — may produce full revised response
)
```

### Result Format

```python
SubTaskResult(
    sub_task_type=SubTaskType.REFLECT,
    name=spec.name,
    result={
        "output": "...",        # Final text (original or revised)
        "revised": True/False,  # Whether the draft was changed
        "reflection": "...",    # Brief self-critique explanation (optional)
    },
    tokens_used=response.tokens_used,
    duration_ms=duration,
    success=True,
    tier_used=response.tier,
)
```

The `"output"` key is critical — `_execute_sub_task_chain()` needs to prefer
this over the COMPOSE result (see Decision Extractor Update below).

If the LLM response contains both JSON with an `output` field and free text,
extract `output` from JSON. If the response is plain text (no JSON wrapper),
treat the entire response as the output with `revised=True`.

### Error Handling

Follow AnalyzeHandler pattern:
1. Guard: `llm_client is None` → return failure SubTaskResult
2. Unknown mode → log warning, fall back to `_DEFAULT_MODE`
3. LLM call exception → catch, log, return failure SubTaskResult
4. Parse failure → return original Compose output unchanged (fail-open,
   `revised=False`) — never lose the Compose output on a Reflect parse error

---

## Decision Extractor Update

`_execute_sub_task_chain()` in cognitive_agent.py (lines 1582-1606) currently
only extracts COMPOSE results:

```python
compose_results = [
    r for r in results
    if r.sub_task_type == SubTaskType.COMPOSE and r.success
]
```

Update to prefer REFLECT output when available:

```python
# AD-632e: Prefer Reflect output (revised/approved), fall back to Compose
from probos.cognitive.sub_task import SubTaskType
reflect_results = [
    r for r in results
    if r.sub_task_type == SubTaskType.REFLECT and r.success
    and r.result.get("output")
]
if reflect_results:
    llm_output = reflect_results[-1].result.get("output", "")
    tier_used = reflect_results[-1].tier_used or (
        compose_results[-1].tier_used if compose_results else ""
    )
else:
    compose_results = [
        r for r in results
        if r.sub_task_type == SubTaskType.COMPOSE and r.success
    ]
    if compose_results:
        llm_output = compose_results[-1].result.get("output", "")
        tier_used = compose_results[-1].tier_used
    else:
        parts = [
            r.result.get("output", str(r.result))
            for r in results if r.success
        ]
        llm_output = "\n".join(parts)
        tier_used = results[-1].tier_used if results else ""
```

Priority: REFLECT > COMPOSE > concatenated fallback.

---

## Chain Update: Add Evaluate + Reflect Steps

Update `_build_chain_for_intent()` in cognitive_agent.py to append optional
Evaluate and Reflect steps to existing chains:

**Ward Room chain** (5 steps):
```python
SubTaskChain(
    steps=[
        SubTaskSpec(
            sub_task_type=SubTaskType.QUERY,
            name="query-thread-context",
            context_keys=("thread_metadata", "credibility"),
        ),
        SubTaskSpec(
            sub_task_type=SubTaskType.ANALYZE,
            name="analyze-thread",
            prompt_template="thread_analysis",
        ),
        SubTaskSpec(
            sub_task_type=SubTaskType.COMPOSE,
            name="compose-reply",
            prompt_template="ward_room_response",
        ),
        SubTaskSpec(
            sub_task_type=SubTaskType.EVALUATE,
            name="evaluate-reply",
            prompt_template="ward_room_quality",
            required=False,           # Graceful degradation
        ),
        SubTaskSpec(
            sub_task_type=SubTaskType.REFLECT,
            name="reflect-reply",
            prompt_template="ward_room_reflection",
            required=False,           # Graceful degradation
        ),
    ],
    source="intent_trigger:ward_room_notification",
)
```

**Proactive chain** (5 steps):
```python
SubTaskChain(
    steps=[
        SubTaskSpec(
            sub_task_type=SubTaskType.QUERY,
            name="query-situation",
            context_keys=("unread_counts", "trust_score"),
        ),
        SubTaskSpec(
            sub_task_type=SubTaskType.ANALYZE,
            name="analyze-situation",
            prompt_template="situation_review",
        ),
        SubTaskSpec(
            sub_task_type=SubTaskType.COMPOSE,
            name="compose-observation",
            prompt_template="proactive_observation",
        ),
        SubTaskSpec(
            sub_task_type=SubTaskType.EVALUATE,
            name="evaluate-observation",
            prompt_template="proactive_quality",
            required=False,
        ),
        SubTaskSpec(
            sub_task_type=SubTaskType.REFLECT,
            name="reflect-observation",
            prompt_template="proactive_reflection",
            required=False,
        ),
    ],
    source="intent_trigger:proactive_think",
)
```

Both Evaluate and Reflect steps use `required=False`. If either handler fails,
the chain degrades to using the Compose output (existing behavior). This is
defense-in-depth — quality gates enhance output but never block it.

---

## Registration and Wiring

### In `src/probos/cognitive/sub_tasks/__init__.py`:

```python
from probos.cognitive.sub_tasks.compose import ComposeHandler
from probos.cognitive.sub_tasks.evaluate import EvaluateHandler
from probos.cognitive.sub_tasks.reflect import ReflectHandler
from probos.cognitive.sub_tasks.query import QueryHandler
from probos.cognitive.sub_tasks.analyze import AnalyzeHandler

__all__ = ["AnalyzeHandler", "ComposeHandler", "EvaluateHandler", "QueryHandler", "ReflectHandler"]
```

### In `src/probos/startup/finalize.py`:

Find the existing handler registration block (line ~196-208) and add:

```python
from probos.cognitive.sub_tasks import EvaluateHandler, ReflectHandler

evaluate_handler = EvaluateHandler(
    llm_client=llm_client,
    runtime=runtime,
)
executor.register_handler(SubTaskType.EVALUATE, evaluate_handler)

reflect_handler = ReflectHandler(
    llm_client=llm_client,
    runtime=runtime,
)
executor.register_handler(SubTaskType.REFLECT, reflect_handler)
```

---

## Logging

Log at INFO level:

```
AD-632e: Evaluate verdict for {agent_type}: pass={pass}, score={score}, recommendation={recommendation}
AD-632e: Reflect for {agent_type}: revised={revised}, suppressed={suppressed}
AD-632e: Reflect short-circuit for {agent_type}: Evaluate recommended suppress
```

---

## What This Does NOT Do

- Does NOT replace AD-568e `check_faithfulness()` — that remains as a
  zero-cost post-decision heuristic on every cycle
- Does NOT replace AD-589 `check_introspective_faithfulness()` — that remains
  as a post-decision regex check
- Does NOT replace AD-592 `_confabulation_guard()` — that remains as a
  pre-decision prompt injection
- Does NOT add complexity heuristic triggers (quality fallback) — Phase 2
- Does NOT make Evaluate/Reflect mandatory — both are `required=False`
- Does NOT add retry loops (Compose → Evaluate fail → re-Compose) — Phase 2
- Does NOT add notebook_quality mode activation (no notebook chain exists yet)

## Files

| File | Action | Purpose |
|------|--------|---------|
| `src/probos/cognitive/sub_tasks/evaluate.py` | CREATE | EvaluateHandler + 3 evaluation mode builders |
| `src/probos/cognitive/sub_tasks/reflect.py` | CREATE | ReflectHandler + 3 reflection mode builders |
| `src/probos/cognitive/sub_tasks/__init__.py` | EDIT | Add EvaluateHandler + ReflectHandler imports |
| `src/probos/startup/finalize.py` | EDIT | Register both handlers with executor |
| `src/probos/cognitive/cognitive_agent.py` | EDIT | Decision extractor update + chain step additions |
| `tests/test_ad632e_evaluate_reflect.py` | CREATE | Unit tests |

## Tests

### Test File: `tests/test_ad632e_evaluate_reflect.py`

Target: 40-50 tests covering:

**EvaluateHandler construction & guards:**
- `test_evaluate_handler_implements_protocol` — isinstance check against SubTaskHandler
- `test_evaluate_handler_no_llm_client` — returns failure SubTaskResult
- `test_evaluate_handler_works_without_runtime` — handler works without runtime

**Evaluate mode dispatch:**
- `test_ward_room_quality_mode` — `prompt_template="ward_room_quality"` dispatches correctly
- `test_proactive_quality_mode` — `prompt_template="proactive_quality"` dispatches correctly
- `test_notebook_quality_mode` — `prompt_template="notebook_quality"` dispatches correctly
- `test_unknown_eval_mode_falls_back` — logs warning, uses ward_room_quality
- `test_empty_eval_mode_uses_default` — no prompt_template → ward_room_quality

**Evaluate criteria (ward_room_quality):**
- `test_eval_novelty_criterion_in_prompt` — system prompt mentions novelty check
- `test_eval_opening_quality_in_prompt` — system prompt mentions opening sentence check
- `test_eval_non_redundancy_in_prompt` — system prompt mentions non-redundancy check
- `test_eval_relevance_in_prompt` — system prompt mentions departmental relevance

**Evaluate result format:**
- `test_eval_result_has_pass_key` — `result.result["pass"]` is bool
- `test_eval_result_has_score` — `result.result["score"]` is 0.0-1.0 float
- `test_eval_result_has_recommendation` — `result.result["recommendation"]` in approve/revise/suppress
- `test_eval_result_type_is_evaluate` — `result.sub_task_type == SubTaskType.EVALUATE`
- `test_eval_result_tracks_tokens` — tokens_used from LLM response propagated

**Evaluate error handling:**
- `test_eval_llm_failure_returns_error` — LLM raises → SubTaskResult with success=False
- `test_eval_json_parse_failure_passes_by_default` — bad JSON → pass=True, score=1.0 (fail-open)

**Evaluate prior result extraction:**
- `test_eval_reads_compose_output` — COMPOSE output appears in user prompt
- `test_eval_reads_analysis_context` — ANALYZE result appears in user prompt
- `test_eval_no_compose_result_still_works` — empty prior_results → handles gracefully

**ReflectHandler construction & guards:**
- `test_reflect_handler_implements_protocol` — isinstance check
- `test_reflect_handler_no_llm_client` — returns failure SubTaskResult

**Reflect mode dispatch:**
- `test_ward_room_reflection_mode` — dispatches correctly
- `test_proactive_reflection_mode` — dispatches correctly
- `test_general_reflection_mode` — dispatches correctly
- `test_unknown_reflect_mode_falls_back` — logs warning, uses ward_room_reflection

**Reflect suppress short-circuit:**
- `test_reflect_suppress_skips_llm` — Evaluate recommendation="suppress" → output is [NO_RESPONSE], tokens_used=0
- `test_reflect_revise_calls_llm` — Evaluate recommendation="revise" → LLM called
- `test_reflect_approve_calls_llm` — Evaluate recommendation="approve" → LLM still called (self-critique may still revise)
- `test_reflect_no_evaluate_result_calls_llm` — no prior Evaluate → LLM called

**Reflect result format:**
- `test_reflect_result_has_output` — `result.result["output"]` contains text
- `test_reflect_result_has_revised_flag` — `result.result["revised"]` is bool
- `test_reflect_result_type_is_reflect` — `result.sub_task_type == SubTaskType.REFLECT`
- `test_reflect_result_tracks_tokens` — tokens_used propagated

**Reflect error handling:**
- `test_reflect_llm_failure_returns_compose_output` — LLM raises → returns original Compose output (fail-open)
- `test_reflect_parse_failure_returns_compose_output` — bad response → returns original unchanged

**Reflect self-critique content:**
- `test_reflect_skill_instructions_in_prompt` — `_augmentation_skill_instructions` appears in system prompt
- `test_reflect_pre_submit_check_in_prompt` — system prompt contains novelty/opening/redundancy criteria
- `test_reflect_plain_text_treated_as_revision` — non-JSON LLM response treated as revised output

**Decision extractor update:**
- `test_extractor_prefers_reflect_over_compose` — REFLECT output wins when both present
- `test_extractor_falls_back_to_compose` — no REFLECT → uses COMPOSE (backward compatible)
- `test_extractor_skips_failed_reflect` — failed REFLECT → uses COMPOSE

**Chain structure:**
- `test_ward_room_chain_has_5_steps` — Q→A→C→E→R
- `test_proactive_chain_has_5_steps` — Q→A→C→E→R
- `test_evaluate_step_not_required` — evaluate SubTaskSpec has required=False
- `test_reflect_step_not_required` — reflect SubTaskSpec has required=False
- `test_evaluate_prompt_template_correct` — ward_room_quality / proactive_quality
- `test_reflect_prompt_template_correct` — ward_room_reflection / proactive_reflection

**Registration:**
- `test_executor_has_evaluate_handler` — SubTaskExecutor.has_handler(EVALUATE) is True
- `test_executor_has_reflect_handler` — SubTaskExecutor.has_handler(REFLECT) is True

### Test Patterns

- Mock `llm_client` with `AsyncMock` returning `MagicMock(content=..., tokens_used=..., tier=...)`
- Use real `SubTaskSpec`, `SubTaskResult`, `SubTaskType`, `SubTaskChain` (not mocks)
- Import from `probos.cognitive.sub_task` for types
- Import from `probos.cognitive.sub_tasks.evaluate` and `.reflect` for handlers
- Use `pytest.mark.asyncio` for async tests
- Build realistic prior_results lists with QUERY, ANALYZE, COMPOSE results
- For decision extractor tests, use `_execute_sub_task_chain` with mocked executor

## Verification

```bash
cd d:\ProbOS
python -m pytest tests/test_ad632e_evaluate_reflect.py -v
python -m pytest tests/test_ad632a_sub_task_foundation.py tests/test_ad632b_query_handler.py tests/test_ad632c_analyze_handler.py tests/test_ad632d_compose_handler.py tests/test_ad632f_activation_triggers.py -v
```

All tests must pass. No existing tests should break.
