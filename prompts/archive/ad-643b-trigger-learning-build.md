# AD-643b Build Prompt: Skill Trigger Learning — Awareness + Feedback

**Issue:** #284
**Parent:** AD-643a (intent-driven skill activation — COMPLETE)
**Scope:** Phase 1 (trigger awareness) + Phase 2 (post-hoc feedback)
**Phase 3 (graduation) deferred** — triggers are few today; build when scale warrants.

## Context

AD-643a introduced two-phase chain execution: ANALYZE produces `intended_actions`,
skills load only for matching `probos-triggers`. This works when agents correctly
declare their intended actions.

**Problem observed (2026-04-18):** Lyra (systems_analyst) declared
`['ward_room_reply']` but wrote a notebook during COMPOSE. The `notebook-quality`
skill never loaded. Pathologist declared `['ward_room_post', 'notebook']` correctly
and both skills loaded — but this was the exception, not the rule.

**Root cause:** Agents don't know what trigger tags exist, so they can't declare
actions they don't know about. When they miss a trigger, there's no feedback loop.

## Design Summary

Two mechanisms:

1. **Trigger Awareness** — inject a scoped trigger list into the ANALYZE prompt
   so agents know what action tags will load quality skills.
2. **Post-Hoc Feedback** — after the chain completes, detect undeclared actions
   in the COMPOSE output. If found, run a **re-reflect** step: a REFLECT-only
   partial chain with feedback injected. The re-reflection output flows to episodic
   memory, creating the learning loop.

### Why re-reflect instead of mid-chain injection?

The chain executor (`SubTaskExecutor`) runs steps sequentially, passing accumulated
`prior_results` to each handler. COMPOSE reads QUERY+ANALYZE results from
`prior_results`. If we split COMPOSE into its own partial chain, it loses access
to triage results (the executor starts `results = []` for each chain).

Re-reflect avoids this problem entirely:
- Run the full chain as-is (QUERY→ANALYZE→COMPOSE→EVALUATE→REFLECT)
- After chain completes, detect undeclared actions in the compose output
- If found, run a REFLECT-only chain with feedback in the observation
- Re-reflect output replaces the original in the decision dict
- No changes to chain execution model or compose.py

---

## Change 1: `src/probos/cognitive/skill_catalog.py` — `get_eligible_triggers()`

Add a new method to `CognitiveSkillCatalog` (after `find_triggered_skills()`,
around line 458).

### Method:

```python
def get_eligible_triggers(
    self,
    department: str | None = None,
    agent_rank: str | None = None,
) -> dict[str, list[str]]:
    """AD-643b: Return {action_tag: [skill_names]} for eligible skills.

    Filters by department and rank. Used to inject trigger awareness
    into ANALYZE so agents know what actions load quality skills.
    """
    result: dict[str, list[str]] = {}
    for entry in self._cache.values():
        if entry.activation not in ("augmentation", "both"):
            continue
        if not entry.triggers:
            continue
        # Department gate
        if department and entry.department != "*" and entry.department != department:
            continue
        # Rank gate
        if agent_rank:
            agent_rank_order = _RANK_ORDER.get(agent_rank, 0)
            if _RANK_ORDER.get(entry.min_rank, 0) > agent_rank_order:
                continue
        for tag in entry.triggers:
            result.setdefault(tag, []).append(entry.name)
    return result
```

### Engineering notes:

- Reuses `_RANK_ORDER` dict (line 28) — same as `find_triggered_skills()`
- Read-only filter over `self._cache` — no DB access
- The `triggers` field is populated by `parse_skill_file()` (line 144)

---

## Change 2: `src/probos/cognitive/cognitive_agent.py` — Pass triggers to observation

In `_execute_chain_with_intent_routing()` (line 1760), after the context injection
block and BEFORE Phase 1 triage, add trigger awareness.

### Insert location: After `observation["_formatted_memories"]` assignment
(~line 1821), before `# --- Phase 1: Build and execute triage ---`.

```python
# AD-643b: Inject eligible trigger awareness for ANALYZE prompt
catalog = getattr(self, '_cognitive_skill_catalog', None)
if catalog:
    _dept = observation.get("_department")
    _rank_val = observation.get("_agent_rank")
    if hasattr(_rank_val, 'value'):
        _rank_val = _rank_val.value
    eligible = catalog.get_eligible_triggers(
        department=_dept,
        agent_rank=_rank_val,
    )
    if eligible:
        observation["_eligible_triggers"] = eligible
```

### Engineering notes:

- `observation["_agent_rank"]` may be a `Rank` enum — extract `.value`
- The catalog is `self._cognitive_skill_catalog` (same as line 1890)

---

## Change 3: `src/probos/cognitive/sub_tasks/analyze.py` — Trigger awareness in prompt

### 3a: New helper function — add at module level, before `_build_thread_analysis_prompt`

```python
def _format_trigger_awareness(context: dict) -> str:
    """AD-643b: Format eligible triggers for ANALYZE prompt injection."""
    eligible = context.get("_eligible_triggers")
    if not eligible:
        return ""
    lines = []
    for tag, skills in sorted(eligible.items()):
        skill_names = ", ".join(skills)
        lines.append(f"   - {tag} \u2192 loads: {skill_names}")
    return (
        "   Declare ALL actions you plan to take so quality skills load:\n"
        + "\n".join(lines) + "\n"
    )
```

### 3b: `_build_thread_analysis_prompt()` (lines 92-96)

**Current code:**
```python
f"6. **intended_actions**: Based on your contribution_assessment, what\n"
f"   specific actions will you take? List as a JSON array from:\n"
f"   ward_room_reply, endorse, silent.\n"
f"   If RESPOND: [\"ward_room_reply\"]. If ENDORSE: [\"endorse\"].\n"
f"   If both: [\"ward_room_reply\", \"endorse\"]. If SILENT: [\"silent\"].\n\n"
```

**Replace with:**
```python
f"6. **intended_actions**: Based on your contribution_assessment, what\n"
f"   specific actions will you take? List as a JSON array from:\n"
f"   ward_room_reply, endorse, silent.\n"
f"   If RESPOND: [\"ward_room_reply\"]. If ENDORSE: [\"endorse\"].\n"
f"   If both: [\"ward_room_reply\", \"endorse\"]. If SILENT: [\"silent\"].\n"
f"{_format_trigger_awareness(context)}\n"
```

### 3c: `_build_situation_review_prompt()` (lines 152-155)

**Current code:**
```python
"5. **intended_actions**: What actions will you take? List as a JSON array from:\n"
"   ward_room_post, ward_room_reply, endorse, notebook, leadership_review,\n"
"   proposal, dm, silent. Include ALL that apply.\n"
"   Examples: [\"ward_room_post\", \"notebook\"], [\"endorse\"], [\"silent\"]\n\n"
```

**Replace with:**
```python
"5. **intended_actions**: What actions will you take? List as a JSON array from:\n"
"   ward_room_post, ward_room_reply, endorse, notebook, leadership_review,\n"
"   proposal, dm, silent. Include ALL that apply.\n"
"   Examples: [\"ward_room_post\", \"notebook\"], [\"endorse\"], [\"silent\"]\n"
f"{_format_trigger_awareness(context)}\n"
```

### Engineering notes:

- `context` in both builders is the observation dict — `_eligible_triggers` set
  by Change 2
- The `\u2192` is Unicode right arrow (→) — avoids encoding issues
- If `_eligible_triggers` is empty/missing, returns empty string (backward compat)

---

## Change 4: `src/probos/cognitive/cognitive_agent.py` — `_detect_undeclared_actions()`

Add a new static method near `_extract_intended_actions` (around line 1507).

```python
@staticmethod
def _detect_undeclared_actions(
    compose_output: str,
    intended_actions: list[str],
) -> list[str]:
    """AD-643b: Detect actions in COMPOSE output not declared in intended_actions.

    Scans for known action markers and returns undeclared action tags.
    Patterns match the markers used by proactive.py action extraction.
    """
    if not compose_output:
        return []

    declared = set(intended_actions)
    undeclared = []

    import re
    markers = {
        "notebook": re.compile(r'\[NOTEBOOK\s', re.IGNORECASE),
        "endorse": re.compile(r'\[ENDORSE\s', re.IGNORECASE),
        "proposal": re.compile(r'\[PROPOSAL\]', re.IGNORECASE),
        "dm": re.compile(r'\[DM\s', re.IGNORECASE),
        "ward_room_reply": re.compile(r'\[REPLY\s', re.IGNORECASE),
    }

    for action_tag, pattern in markers.items():
        if action_tag not in declared and pattern.search(compose_output):
            undeclared.append(action_tag)

    return undeclared
```

### Engineering notes:

- `ward_room_post` is NOT detectable post-hoc — the compose output IS the post
- `leadership_review` has no output marker — skip
- `silent` is short-circuited earlier — never in compose output
- `re` is already imported at module level in cognitive_agent.py
- Static method, pure function — easy to test

---

## Change 5: `src/probos/cognitive/sub_tasks/reflect.py` — Feedback injection

### 5a: New helper function — add at module level (near top, after imports)

```python
def _format_trigger_feedback(feedback: dict) -> str:
    """AD-643b: Format undeclared action feedback for REFLECT prompt."""
    undeclared = feedback.get("undeclared_actions", [])
    missed = feedback.get("missed_skills", [])
    if not undeclared:
        return ""
    actions_str = ", ".join(undeclared)
    skills_str = ", ".join(missed) if missed else "none"
    return (
        "\n## Skill Trigger Feedback\n\n"
        "You took actions without declaring them in your intended_actions "
        "during triage:\n"
        f"- Undeclared actions: {actions_str}\n"
        f"- Quality skills that did NOT load: {skills_str}\n\n"
        "In future triage, include these action tags in your intended_actions "
        "so the relevant quality skills load and improve your output.\n"
    )
```

### 5b: Inject into all three REFLECT prompt builders

In `_build_ward_room_reflect_prompt()`, after the evaluate verdict insertion
(lines 134-137), add:

```python
    # AD-643b: Inject undeclared action feedback
    undeclared_feedback = context.get("_undeclared_action_feedback")
    if undeclared_feedback:
        user_prompt += _format_trigger_feedback(undeclared_feedback)
```

Apply the same injection in:
- `_build_proactive_reflect_prompt()` — after evaluate verdict (~lines 207-214)
- `_build_general_reflect_prompt()` — after evaluate verdict (~lines 287-291)

### Engineering notes:

- `context` is the observation dict flowing through the chain
- For the re-reflect partial chain (Change 6), `_undeclared_action_feedback`
  is set in observation before the chain runs — so REFLECT will see it

---

## Change 6: `src/probos/cognitive/cognitive_agent.py` — Re-reflect on undeclared actions

This is the key change. In `_execute_chain_with_intent_routing()`, replace the
current Phase 2 block with three-phase execution.

### Current code (lines 1927-1929):

```python
        if has_comm_action and execute_steps:
            # Re-execute full chain with skills now loaded.
            # Triage re-runs but that's 1 QUERY (0 tokens) + 1 ANALYZE call.
            # Total overhead: ~200 tokens. Acceptable for correctness.
            return await self._execute_sub_task_chain(full_chain, observation)
```

### Replace with:

```python
        if has_comm_action and execute_steps:
            # Phase 2a: Execute full chain with skills loaded
            chain_result = await self._execute_sub_task_chain(full_chain, observation)

            # Phase 2b: Detect undeclared actions in compose output
            if chain_result and intended_actions:
                compose_text = chain_result.get("llm_output", "")
                undeclared = self._detect_undeclared_actions(compose_text, intended_actions)
                if undeclared:
                    # Find which skills would have loaded
                    missed_skills = []
                    if catalog:
                        for tag in undeclared:
                            triggered = catalog.find_triggered_skills(
                                [tag], intent,
                                department=department, agent_rank=rank_val,
                            )
                            missed_skills.extend(e.name for e in triggered)
                    missed_skills = list(set(missed_skills))

                    logger.info(
                        "AD-643b: %s took undeclared actions %s, missed skills %s",
                        self.agent_type, undeclared, missed_skills,
                    )

                    # Store feedback in observation for episode enrichment
                    observation["_undeclared_action_feedback"] = {
                        "undeclared_actions": undeclared,
                        "missed_skills": missed_skills,
                    }

                    # Phase 2c: Re-reflect with feedback
                    chain_result = await self._re_reflect_with_feedback(
                        full_chain, observation, chain_result,
                    )

            return chain_result
```

### New method: `_re_reflect_with_feedback()`

Add this method to `CognitiveAgent` (near `_execute_chain_with_intent_routing`):

```python
async def _re_reflect_with_feedback(
    self,
    full_chain,
    observation: dict,
    original_result: dict,
) -> dict:
    """AD-643b: Run a REFLECT-only chain with undeclared action feedback.

    After detecting undeclared actions in compose output, re-run REFLECT
    with feedback injected into the observation. The re-reflect output
    replaces the original chain result, ensuring the feedback flows into
    episodic memory via the reflection.

    Returns the updated decision dict (or original if re-reflect fails).
    """
    from probos.cognitive.sub_task import SubTaskChain, SubTaskType

    reflect_steps = [
        s for s in full_chain.steps
        if s.sub_task_type == SubTaskType.REFLECT
    ]
    if not reflect_steps:
        return original_result

    reflect_chain = SubTaskChain(
        steps=reflect_steps,
        chain_timeout_ms=30000,  # 30s — single step, generous timeout
        fallback="skip",
        source=f"{full_chain.source}:re_reflect",
    )

    try:
        reflect_results = await self._sub_task_executor.execute(
            reflect_chain,
            observation,
            agent_id=self.id,
            agent_type=self.agent_type,
            intent=observation.get("intent", ""),
            intent_id=observation.get("intent_id", ""),
            journal=self._cognitive_journal,
        )

        # Extract re-reflect output
        for r in reversed(reflect_results):
            if r.sub_task_type == SubTaskType.REFLECT and r.success and r.result:
                new_output = r.result.get("output", "")
                if new_output:
                    logger.info(
                        "AD-643b: Re-reflect updated output for %s",
                        self.agent_type,
                    )
                    return {
                        **original_result,
                        "llm_output": new_output,
                        "chain_source": f"{original_result.get('chain_source', '')}:re_reflect",
                    }

    except Exception as exc:
        logger.warning(
            "AD-643b: Re-reflect failed for %s, keeping original: %s",
            self.agent_type, exc,
        )

    return original_result
```

### Engineering notes:

- **Re-reflect receives the observation dict** which now has
  `_undeclared_action_feedback` set — the REFLECT handler reads it (Change 5)
- **REFLECT runs without prior_results** (new partial chain, empty results list).
  This means `_get_compose_output(prior_results)` returns empty and
  `_get_evaluate_result(prior_results)` returns None. The REFLECT prompt will
  have no draft response or evaluation verdict — it runs on feedback only.
  This is acceptable because:
  - The original REFLECT already ran with full context
  - Re-reflect's purpose is specifically to capture the trigger feedback
  - The re-reflect output replaces the original, carrying the learning signal
- **If re-reflect fails, the original result is preserved** — graceful degradation
- **`catalog`, `department`, `rank_val`** are already in scope from the skill
  loading block above (~line 1890)
- The re-reflect adds one LLM call (~100-200 tokens) ONLY when undeclared
  actions are detected — not on every chain execution

### IMPORTANT — REFLECT without prior_results consideration:

REFLECT's prompt builders construct user prompts from compose output and evaluate
verdict via `prior_results`. With an empty `prior_results` list, the REFLECT
prompt will lack the draft response section. To handle this gracefully:

In `reflect.py`, in each `_build_*_reflect_prompt()` function, the user prompt
starts with compose output:

```python
compose_output = _get_compose_output(prior_results)
```

When compose_output is empty (re-reflect case), the prompt should still work —
it will just have the skill instructions + trigger feedback without a draft to
critique. The feedback section (Change 5) provides the content REFLECT needs.

However, to make re-reflect more useful, pass the original compose output via
observation. In Change 6, before calling `_re_reflect_with_feedback()`, add:

```python
                    # Provide compose output for re-reflect context
                    observation["_re_reflect_compose_output"] = compose_text
```

Then in `reflect.py`, modify `_get_compose_output()` to fall back to observation:

**Current (line 31-36):**
```python
def _get_compose_output(prior_results: list[SubTaskResult]) -> str:
    """Extract the most recent successful Compose output."""
    for pr in reversed(prior_results):
        if pr.sub_task_type == SubTaskType.COMPOSE and pr.success and pr.result:
            return pr.result.get("output", "")
    return ""
```

**Replace with:**
```python
def _get_compose_output(
    prior_results: list[SubTaskResult],
    context: dict | None = None,
) -> str:
    """Extract the most recent successful Compose output.

    Falls back to observation key for AD-643b re-reflect chains where
    prior_results may not contain compose output.
    """
    for pr in reversed(prior_results):
        if pr.sub_task_type == SubTaskType.COMPOSE and pr.success and pr.result:
            return pr.result.get("output", "")
    # AD-643b: Fallback for re-reflect partial chains
    if context:
        return context.get("_re_reflect_compose_output", "")
    return ""
```

Update ALL call sites of `_get_compose_output()` to pass context:
- `_build_ward_room_reflect_prompt()` — line ~129
- `_build_proactive_reflect_prompt()` — line ~207
- `_build_general_reflect_prompt()` — line ~283

Each currently calls:
```python
compose_output = _get_compose_output(prior_results)
```
Change to:
```python
compose_output = _get_compose_output(prior_results, context)
```

Similarly, update `_get_evaluate_result()` to accept context but no fallback
needed — re-reflect doesn't need the evaluate verdict; the trigger feedback
replaces it as the review focus.

---

## Change 7: Episode enrichment with trigger feedback

In `_store_action_episode()` (line ~4001), add undeclared action feedback to
episode outcomes when present.

### In the outcomes dict construction (~line 4080):

**Current code:**
```python
        outcomes=[{
            "intent": intent.intent,
            "success": report.get("success", False),
            "response": result_text,
            "agent_type": self.agent_type,
            "source": source or "intent_bus",
            **(observation.get("_chain_metadata") or {}),
        }],
```

**Replace with:**
```python
        _outcome = {
            "intent": intent.intent,
            "success": report.get("success", False),
            "response": result_text,
            "agent_type": self.agent_type,
            "source": source or "intent_bus",
            **(observation.get("_chain_metadata") or {}),
        }
        # AD-643b: Enrich with trigger feedback
        _trigger_fb = observation.get("_undeclared_action_feedback")
        if _trigger_fb:
            _outcome["undeclared_actions"] = _trigger_fb.get("undeclared_actions", [])
            _outcome["missed_skills"] = _trigger_fb.get("missed_skills", [])
```

Then use `_outcome`:
```python
        outcomes=[_outcome],
```

---

## Backward Compatibility

- **No `_eligible_triggers` in observation** → `_format_trigger_awareness()`
  returns empty string → ANALYZE prompt unchanged
- **No `_undeclared_action_feedback` in observation** → REFLECT prompt unchanged,
  no re-reflect, episode outcomes unchanged
- **Skills without `probos-triggers`** → `get_eligible_triggers()` skips them
- **Non-intent-routing path** → `_execute_sub_task_chain()` untouched
- **AD-639 low-trust agents** → Original REFLECT skipped, but re-reflect is a
  separate chain execution. Check: does AD-639 skip REFLECT via the executor
  or via the reflect handler? If via handler (checking `_chain_trust_band`
  in reflect.py), re-reflect will also be skipped for low-trust agents.
  **This is acceptable** — low-trust agents get Phase 1 awareness, and
  re-reflect would waste tokens on agents whose reflections are already skipped.
- **`_get_compose_output()` signature change** — new optional `context` param
  with default `None` — backward compatible, existing calls without context
  continue to work

## Known Limitations (Not in Scope)

1. **`ward_room_post` not detectable post-hoc** — compose output IS the post
2. **Pure non-comm paths skip the chain** — agent declaring only `['notebook']`
   uses single-call. No REFLECT, no re-reflect. Phase 1 awareness is the
   mechanism for these cases.
3. **Over-declaration tracking deferred** — Phase 3 diagnostic
4. **Re-reflect adds one LLM call** — only when undeclared actions detected,
   ~100-200 tokens. Net savings from AD-643a (~225K/session) far exceed this.

---

## Test Requirements

### New test file: `tests/test_trigger_learning.py`

**Skill catalog tests:**
1. `test_get_eligible_triggers_basic` — returns correct action→skill mapping
2. `test_get_eligible_triggers_universal_department` — `department="*"` skills
   appear for all agents
3. `test_get_eligible_triggers_department_filter` — department-specific skills
   only for matching agents
4. `test_get_eligible_triggers_rank_filter` — above-rank skills excluded
5. `test_get_eligible_triggers_no_triggers` — skills without `probos-triggers`
   excluded
6. `test_get_eligible_triggers_empty_cache` — empty catalog returns empty dict
7. `test_get_eligible_triggers_multiple_skills_same_trigger` — action tag maps
   to multiple skills

**Trigger awareness formatting tests:**
8. `test_format_trigger_awareness_with_triggers` — produces formatted string
9. `test_format_trigger_awareness_empty` — returns empty string when no triggers
10. `test_format_trigger_awareness_sorted` — output alphabetically sorted

**Undeclared action detection tests:**
11. `test_detect_notebook_undeclared` — `[NOTEBOOK topic]` detected when not in
    intended_actions
12. `test_detect_endorse_undeclared` — `[ENDORSE post UP]` detected
13. `test_detect_proposal_undeclared` — `[PROPOSAL]` detected
14. `test_detect_dm_undeclared` — `[DM @callsign]` detected
15. `test_detect_reply_undeclared` — `[REPLY thread_id]` detected
16. `test_detect_no_false_positive` — declared action not flagged
17. `test_detect_multiple_undeclared` — multiple undeclared detected
18. `test_detect_empty_output` — empty compose output returns empty list
19. `test_detect_case_insensitive` — markers detected regardless of case

**REFLECT feedback formatting tests:**
20. `test_format_trigger_feedback_with_actions` — produces feedback block
21. `test_format_trigger_feedback_empty` — returns empty when no undeclared
22. `test_format_trigger_feedback_no_missed_skills` — handles empty skills list

**Re-reflect tests:**
23. `test_re_reflect_runs_on_undeclared` — re-reflect chain executes when
    undeclared actions detected
24. `test_re_reflect_skipped_when_all_declared` — no re-reflect when no
    undeclared actions
25. `test_re_reflect_output_replaces_original` — decision dict updated with
    re-reflect output
26. `test_re_reflect_failure_preserves_original` — original result kept on error
27. `test_re_reflect_receives_compose_output` — `_re_reflect_compose_output`
    available in observation
28. `test_get_compose_output_fallback` — `_get_compose_output()` falls back to
    observation key when prior_results empty

**Integration tests:**
29. `test_chain_with_trigger_awareness_injection` — ANALYZE prompt includes
    trigger list
30. `test_chain_without_trigger_awareness` — no injection when no eligible triggers
31. `test_full_loop_undeclared_notebook` — agent writes notebook without declaring
    → detected → re-reflect fires → feedback in output
32. `test_episode_enrichment_with_undeclared` — episode outcomes include
    `undeclared_actions` and `missed_skills`
33. `test_backward_compat_no_triggers` — skills without triggers work via
    intent fallback

---

## Verification Checklist

Before submitting, verify:

- [ ] `get_eligible_triggers()` filter logic matches `find_triggered_skills()`
- [ ] `_RANK_ORDER` used consistently (line 28 of skill_catalog.py)
- [ ] `_eligible_triggers` key name consistent across cognitive_agent.py and analyze.py
- [ ] `_undeclared_action_feedback` key name consistent across cognitive_agent.py,
      reflect.py, and episode storage
- [ ] `_re_reflect_compose_output` key name consistent
- [ ] `_get_compose_output()` signature change is backward compatible (default None)
- [ ] All call sites of `_get_compose_output()` updated to pass context
- [ ] ANALYZE prompt changes don't break existing `intended_actions` parsing
- [ ] `_extract_intended_actions()` still works (no regressions)
- [ ] Rank enum `.value` extraction handles both string and enum cases
- [ ] `re` module available in cognitive_agent.py (check imports)
- [ ] No circular imports introduced
- [ ] All 33 tests pass
- [ ] Targeted tests only — no full suite run needed (additive build)
