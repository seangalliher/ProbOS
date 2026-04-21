# AD-644 Phase 1 Build Prompt: Duty Context Restoration

**Issue:** #285
**Parent:** AD-644 (Agent Situation Awareness Architecture)
**Scope:** Phase 1 only — duty context + agent metrics into chain path
**Priority:** Critical — duty cycles produce zero reports (regression from AD-632)

## Context

When `proactive_think` was added to `_CHAIN_ELIGIBLE_INTENTS` (AD-632), the chain
path bypassed `_build_prompt_text()` — a 290-line function with ~23 context
injections. The chain's ANALYZE step receives standing orders (system prompt) but
the user prompt has NO dynamic data: `observation["context"]` is an empty string
for proactive_think.

**Result:** ANALYZE always returns `intended_actions: ["silent"]`. Zero duty reports
in days of operation. This is a regression, not a missing feature.

**Phase 1 fixes the critical subset:** duty context and agent metrics. When an agent
has a scheduled duty, ANALYZE must know about it. When an agent is doing free-form
review, ANALYZE must know that too. Both ANALYZE and COMPOSE need trust/agency/rank
to frame responses correctly.

**Phases 2-5** (innate faculties, QUERY extensions, standing orders, deprecation)
follow separately. Phase 1 is the minimum viable fix.

## Architecture

**Data flow:** `proactive.py` already gathers all context into `params`. The chain's
`_execute_chain_with_intent_routing()` enriches the observation dict with agent
metadata (identity, trust, rank, memories). Phase 1 adds two new observation keys:

- `_active_duty` — duty dict from `params.duty`, or `None`
- `_agent_metrics` — trust/agency/rank display string

Both ANALYZE and COMPOSE handlers already receive the full observation dict (neither
specifies `context_keys` in their `SubTaskSpec`). All `_`-prefixed keys pass through
the context filter. The handlers just need to read and render these keys.

**Engineering principles:**
- **Open/Closed:** No new dispatch modes. Existing prompt builders updated.
- **DRY:** Observation dict set once in cognitive_agent.py. Both handlers read it.
- **Law of Demeter:** Extract from `params` dict (already in scope), set on flat keys.
- **Fail-fast:** Keys default to `None`/empty. Handlers render conditionally.

---

## Change 1: `src/probos/cognitive/cognitive_agent.py` — Observation Injection

**Location:** `_execute_chain_with_intent_routing()`, after the BF-186 block
(line ~1842, after `observation["_crew_manifest"] = ...`), before BF-189 memory
pre-formatting.

**Add this block:**

```python
        # AD-644 Phase 1: Duty context + agent metrics for chain prompts
        _params = observation.get("params", {})
        _duty = _params.get("duty")
        if _duty:
            observation["_active_duty"] = _duty
        # Agent metrics — trust/agency/rank for self-awareness in chain path
        _trust_display = _params.get("trust_score", "?")
        _agency_display = _params.get("agency_level", "?")
        _rank_display = _params.get("rank", "?")
        observation["_agent_metrics"] = (
            f"Your trust: {_trust_display} | "
            f"Agency: {_agency_display} | "
            f"Rank: {_rank_display}"
        )
```

**Note:** `_params` is already defined earlier at line 1813. Do NOT redeclare it.
Use the existing variable. Insert this block AFTER line 1842 (after `_crew_manifest`),
before the BF-189 comment block. The `_params` variable at line 1813 is the same
`observation.get("params", {})` dict — reuse it.

**Important:** The `_params` variable already exists at line 1813:
```python
_params = observation.get("params", {})
```
Do NOT redeclare `_params`. Reference the existing one. If the variable scope
doesn't reach the insertion point (it does — same method), just use
`observation.get("params", {})` directly.

---

## Change 2: `src/probos/cognitive/sub_tasks/analyze.py` — Situation Review Prompt

**Location:** `_build_situation_review_prompt()` function (line 118).

**What changes:** The user prompt must render duty context and agent metrics BEFORE
the assessment questions. The situation content section (`## Current Situation`)
currently renders an empty string — replace it with structured context.

**Replace the user_prompt construction (lines 157-174) with:**

```python
    # AD-644 Phase 1: Duty context + agent metrics
    _active_duty = context.get("_active_duty")
    _agent_metrics = context.get("_agent_metrics", "")

    duty_section = ""
    if _active_duty:
        _duty_desc = _active_duty.get("description", _active_duty.get("duty_id", "unknown"))
        duty_section = (
            f"## Active Duty\n\n"
            f"[Duty Cycle: {_duty_desc}]\n"
            f"{_agent_metrics}\n\n"
            f"This is a scheduled duty. Assess your area of responsibility and "
            f"report your findings.\n\n"
        )
    else:
        duty_section = (
            f"## Proactive Review — No Scheduled Duty\n\n"
            f"{_agent_metrics}\n\n"
            f"You have no scheduled duty at this time. Post only if you observe "
            f"something genuinely noteworthy or actionable. "
            f"Silence is professionalism — [NO_RESPONSE] is the expected default.\n\n"
        )

    user_prompt = (
        f"{duty_section}"
        f"## Current Situation\n\n{situation_content}\n\n"
        f"{context_section}"
        f"{memory_section}"
        "## Assessment Required\n\n"
        f"From your department's perspective ({department}), assess:\n\n"
        "1. **active_threads**: List active discussion threads requiring attention.\n"
        "2. **pending_actions**: Actions you need to take or respond to.\n"
        "3. **priority_topics**: Topics ranked by departmental relevance.\n"
        "4. **department_relevance**: How relevant is the current situation to your "
        f"department ({department})? One of: \"HIGH\", \"MEDIUM\", \"LOW\".\n"
        "5. **intended_actions**: What actions will you take? List as a JSON array from:\n"
        "   ward_room_post, ward_room_reply, endorse, notebook, leadership_review,\n"
        "   proposal, dm, silent. Include ALL that apply.\n"
        "   Examples: [\"ward_room_post\", \"notebook\"], [\"endorse\"], [\"silent\"]\n"
        f"{_format_trigger_awareness(context)}\n"
        "Return a JSON object with these 5 keys. No other text."
    )
    return system_prompt, user_prompt
```

**Key behavior change:** When `_active_duty` is present, the prompt says "This is a
scheduled duty. Assess your area of responsibility and report your findings." This
biases ANALYZE away from `["silent"]`. When there's no duty, the existing free-form
framing applies ("Silence is professionalism").

**Note:** Do NOT change the system prompt, context_section, memory_section, or the
assessment questions block. Only add the duty_section before `## Current Situation`.

---

## Change 3: `src/probos/cognitive/sub_tasks/compose.py` — Proactive Compose Prompt

**Location:** `_build_proactive_compose_prompt()` function (line 142).

**What changes:** The system prompt framing must distinguish duty vs free-form.
Currently it always says "reviewing recent ship activity during a quiet moment."
A duty cycle is NOT a quiet moment — the agent has a scheduled obligation.

**Replace lines 157-164 (the comment + system_prompt addition block) with:**

```python
    # AD-644 Phase 1: Duty-aware framing
    _active_duty = context.get("_active_duty")
    if _active_duty:
        _duty_desc = _active_duty.get("description", _active_duty.get("duty_id", "unknown"))
        system_prompt += (
            f"\n\nYou are performing a scheduled duty: {_duty_desc}. "
            "Compose a Ward Room post with your findings (2-4 sentences). "
            "Be specific and actionable. If nothing noteworthy to report, "
            "respond with exactly: [NO_RESPONSE]"
        )
    else:
        system_prompt += (
            "\n\nYou are reviewing recent ship activity during a quiet moment. "
            "If you notice something noteworthy — a pattern, a concern, an insight "
            "related to your expertise — compose a brief observation (2-4 sentences). "
            "This will be posted to the Ward Room as a new thread. "
            "Speak in your natural voice. Be specific and actionable."
        )
```

**Also update `_build_user_prompt()`** (line 215) to include agent metrics. Add
this block after the memories section (after line 243), before the fallback:

```python
    # AD-644 Phase 1: Agent metrics for self-awareness in composition
    _agent_metrics = context.get("_agent_metrics", "")
    if _agent_metrics:
        parts.append(f"## Your Status\n\n{_agent_metrics}")
```

**Note:** This goes BEFORE the `if not parts:` fallback check (line 245). The
metrics section is informational — the agent should know its trust/agency/rank
when composing, just as it does in the `_build_prompt_text` path.

---

## Change 4: Test File — `tests/test_ad644_phase1_duty_context.py`

Create a new test file. Tests should verify:

### Test 1: `test_observation_duty_injection`
- Create a mock observation dict with `params.duty = {"duty_id": "scout_report", "description": "Perform a comprehensive review"}`
- Call `_execute_chain_with_intent_routing` (or verify the injection logic in isolation)
- Assert `observation["_active_duty"]` matches the duty dict
- Assert `observation["_agent_metrics"]` contains trust, agency, rank values

### Test 2: `test_observation_no_duty`
- Create observation with `params.duty = None`
- Verify `"_active_duty"` is NOT in observation dict
- Verify `"_agent_metrics"` IS still present

### Test 3: `test_analyze_prompt_with_duty`
- Call `_build_situation_review_prompt` with context containing `_active_duty` set
- Assert user prompt contains "Active Duty"
- Assert user prompt contains "scheduled duty"
- Assert user prompt contains the duty description
- Assert user prompt contains agent metrics string
- Assert user prompt does NOT contain "Silence is professionalism"

### Test 4: `test_analyze_prompt_without_duty`
- Call `_build_situation_review_prompt` with context where `_active_duty` is absent
- Assert user prompt contains "Proactive Review"
- Assert user prompt contains "Silence is professionalism"
- Assert user prompt contains agent metrics string

### Test 5: `test_compose_prompt_with_duty`
- Call `_build_proactive_compose_prompt` with context containing `_active_duty`
- Assert system prompt contains "performing a scheduled duty"
- Assert system prompt contains the duty description
- Assert system prompt does NOT contain "quiet moment"

### Test 6: `test_compose_prompt_without_duty`
- Call `_build_proactive_compose_prompt` with context where `_active_duty` absent
- Assert system prompt contains "quiet moment"
- Assert system prompt does NOT contain "scheduled duty"

### Test 7: `test_compose_user_prompt_includes_metrics`
- Call `_build_user_prompt` with context containing `_agent_metrics`
- Assert result contains "Your Status"
- Assert result contains the metrics string

### Test 8: `test_analyze_duty_bias_toward_reporting`
Functional test — verify the prompt structure biases ANALYZE toward action:
- Build the full situation review prompt with duty active
- Assert "report your findings" appears in the prompt
- Assert the assessment section still includes `intended_actions`

### Import patterns:

```python
from probos.cognitive.sub_tasks.analyze import _build_situation_review_prompt
from probos.cognitive.sub_tasks.compose import (
    _build_proactive_compose_prompt,
    _build_user_prompt,
)
from probos.cognitive.sub_task import SubTaskResult, SubTaskType
```

For observation injection tests, test the logic in isolation rather than
mocking the full `_execute_chain_with_intent_routing` method. Extract the
injection logic check by building an observation dict with the expected
`params` structure and verifying the output keys.

---

## What NOT to change

- **Do NOT modify `_build_prompt_text()`** — it still serves non-chain intents.
- **Do NOT modify `query.py`** — QUERY extensions are Phase 3.
- **Do NOT modify `sub_task.py`** — the executor is untouched.
- **Do NOT modify `reflect.py`** — REFLECT doesn't need duty context.
- **Do NOT modify standing orders** — that's Phase 4.
- **Do NOT add temporal awareness, working memory, self-monitoring, ontology, or
  any other innate faculty** — those are Phase 2.
- **Do NOT add new QUERY operations** — those are Phase 3.
- **Do NOT break existing chain behavior for `ward_room_notification` intent** —
  the changes are gated on `_active_duty` / `_agent_metrics` being present in
  context, which only happens for proactive_think.

## Validation

After building, run:
```bash
python -m pytest tests/test_ad644_phase1_duty_context.py -v
python -m pytest tests/ -k "analyze or compose or chain" --timeout=30 -x
```

Verify no regressions in existing chain tests. The `ward_room_notification` chain
path must be unaffected — it doesn't set `_active_duty` or `_agent_metrics`.

## Files Modified

| File | Change |
|------|--------|
| `src/probos/cognitive/cognitive_agent.py` | Add `_active_duty` + `_agent_metrics` to observation dict |
| `src/probos/cognitive/sub_tasks/analyze.py` | Render duty/free-form framing + agent metrics in situation_review |
| `src/probos/cognitive/sub_tasks/compose.py` | Duty-aware system prompt + agent metrics in user prompt |
| `tests/test_ad644_phase1_duty_context.py` | 8 new tests |
