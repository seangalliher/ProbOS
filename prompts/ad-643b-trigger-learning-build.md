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
2. **Post-Hoc Feedback** — after COMPOSE, detect undeclared actions in the output.
   Inject feedback into REFLECT so the miss flows to episodic memory and the agent
   recalls it in future triage.

---

## Change 1: `src/probos/cognitive/skill_catalog.py` — `get_eligible_triggers()`

Add a new method to `CognitiveSkillCatalog` (after `find_triggered_skills()`,
around line 458).

### Method signature:

```python
def get_eligible_triggers(
    self,
    department: str | None = None,
    agent_rank: str | None = None,
) -> dict[str, list[str]]:
```

### Behavior:

- Iterate `self._cache.values()`
- Include only entries where `entry.activation in ("augmentation", "both")`
- Include only entries where `entry.triggers` is non-empty
- Apply the same department gate as `find_triggered_skills()`:
  `department is None OR entry.department == "*" OR entry.department == department`
- Apply the same rank gate as `find_triggered_skills()`:
  `_RANK_ORDER.get(entry.min_rank, 0) <= _RANK_ORDER.get(agent_rank, 0)`
  (use 0 as default for both lookups)
- Build result dict: `{action_tag: [skill_name, ...]}` — one entry per unique
  action tag, listing all skills that trigger on it
- Return the dict

### Example output:

```python
{
    "ward_room_reply": ["communication-discipline"],
    "ward_room_post": ["communication-discipline"],
    "endorse": ["communication-discipline"],
    "notebook": ["notebook-quality"],
    "leadership_review": ["leadership-feedback"],
}
```

### Engineering notes:

- Reuse the existing `_RANK_ORDER` dict (line 28) for rank comparisons
- This is a read-only filter over `self._cache` — no DB access needed
- The `triggers` field is already populated by `parse_skill_file()` (line 144)

---

## Change 2: `src/probos/cognitive/cognitive_agent.py` — Pass triggers to observation

In `_execute_chain_with_intent_routing()` (line 1760), after the context injection
block and BEFORE the Phase 1 triage execution, add trigger awareness:

### Insert location: After line ~1821 (after `observation["_formatted_memories"]`
assignment), before the `# --- Phase 1: Build and execute triage ---` comment.

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

- `observation["_agent_rank"]` is set at line ~1812 as `getattr(self, "rank", None)`
  which may be a `Rank` enum — handle `.value` extraction
- The catalog is accessed via `self._cognitive_skill_catalog` (same pattern as
  line 1890 in the existing Phase 2 skill loading)
- `_eligible_triggers` is a dict[str, list[str]] — ANALYZE will format it

---

## Change 3: `src/probos/cognitive/sub_tasks/analyze.py` — Trigger awareness in prompt

Modify BOTH `_build_thread_analysis_prompt()` and `_build_situation_review_prompt()`
to inject trigger awareness into the `intended_actions` instruction.

### 3a: `_build_thread_analysis_prompt()` (lines 92-96)

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

### 3b: `_build_situation_review_prompt()` (lines 152-155)

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

### 3c: New helper function — add at module level (before the prompt builders)

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
        + "\n".join(lines)
    )
```

### Engineering notes:

- `context` is the `observation` dict passed through — `_eligible_triggers` was
  set in Change 2
- The arrow character (`→`) is the Unicode right arrow U+2192 — use `\u2192` in
  the source string to avoid encoding issues
- If `_eligible_triggers` is empty/missing, the function returns empty string —
  prompt is unchanged (backward compat)
- Both prompt builders receive `context` as their first parameter

---

## Change 4: `src/probos/cognitive/cognitive_agent.py` — Detect undeclared actions

Add a new static method to `CognitiveAgent` (near `_extract_intended_actions`,
around line 1507).

### Method:

```python
@staticmethod
def _detect_undeclared_actions(
    compose_output: str,
    intended_actions: list[str],
) -> list[str]:
    """AD-643b: Detect actions in COMPOSE output not declared in intended_actions.

    Scans for known action markers and returns any that weren't declared.
    Used to provide feedback for trigger learning.
    """
    if not compose_output:
        return []

    declared = set(intended_actions)
    undeclared = []

    # Map output markers to action tags
    # These patterns match the same markers used by proactive.py action extraction
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

- Patterns are simplified versions of the full regex in `proactive.py` — we only
  need to detect presence, not extract content
- `ward_room_post` is NOT detectable post-hoc from markers because the compose
  output IS the post. Ward room posts are detected by the compose mode, not by
  output markers. Skip this tag.
- `leadership_review` has no output marker (it's an internal assessment) — skip
- `silent` is never in compose output (short-circuited earlier) — skip
- The method is static and pure — no side effects, easy to test

---

## Change 5: `src/probos/cognitive/sub_tasks/reflect.py` — Feedback injection

Modify all three REFLECT prompt builders to inject undeclared action feedback
when present.

### 5a: `_build_ward_room_reflect_prompt()` — after evaluate verdict insertion

**Current code (lines 134-137):**
```python
    if eval_result:
        user_prompt += (
            "\n## Evaluation Verdict\n\n"
            + json.dumps(eval_result, indent=2) + "\n"
        )
```

**After this block, add:**
```python
    # AD-643b: Inject undeclared action feedback
    undeclared_feedback = context.get("_undeclared_action_feedback")
    if undeclared_feedback:
        user_prompt += _format_trigger_feedback(undeclared_feedback)
```

### 5b: `_build_proactive_reflect_prompt()` — same pattern

Find the evaluate verdict insertion in the proactive reflect builder (around
lines 207-214). After that block, add the same injection:

```python
    # AD-643b: Inject undeclared action feedback
    undeclared_feedback = context.get("_undeclared_action_feedback")
    if undeclared_feedback:
        user_prompt += _format_trigger_feedback(undeclared_feedback)
```

### 5c: `_build_general_reflect_prompt()` — same pattern

Find the evaluate verdict insertion in the general reflect builder (around
lines 287-291). After that block, add the same injection:

```python
    # AD-643b: Inject undeclared action feedback
    undeclared_feedback = context.get("_undeclared_action_feedback")
    if undeclared_feedback:
        user_prompt += _format_trigger_feedback(undeclared_feedback)
```

### 5d: New helper function — add at module level (near top of reflect.py)

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

### Engineering notes:

- `context` in the reflect prompt builders is the same `observation` dict —
  it flows through the entire chain
- The feedback is injected AFTER the evaluate verdict — this is additional
  context for the reflection, not a replacement
- If `_undeclared_action_feedback` is not in the observation (no undeclared
  actions detected), nothing is injected (backward compat)
- AD-639 low-trust agents skip REFLECT entirely — they won't get feedback.
  This is acceptable: they're in bootstrapping mode and get Phase 1 awareness
  instead.

---

## Change 6: `src/probos/cognitive/cognitive_agent.py` — Wire detection into chain

In `_execute_chain_with_intent_routing()`, AFTER Phase 2 decides to run the full
chain but BEFORE calling `_execute_sub_task_chain()`, detect undeclared actions.

**Problem:** We can't detect undeclared actions before COMPOSE runs — we need
COMPOSE output first. But `_execute_sub_task_chain()` runs the entire chain
(including COMPOSE and REFLECT) as one unit.

**Solution:** Instead of intercepting between COMPOSE and REFLECT (which would
require breaking the chain execution model), detect undeclared actions AFTER
the chain completes and log the finding. The feedback injection into REFLECT
works differently: we set `observation["_undeclared_action_feedback"]` BEFORE
the chain runs, pre-populated with a "check yourself" note based on the
intended_actions. This way REFLECT has the trigger awareness context even
though we can't know the actual compose output yet.

**REVISED APPROACH:** Actually, we CAN'T pre-populate because we don't know
what undeclared actions will be taken. Instead:

**The correct approach is post-chain detection + logging.** The episodic memory
learning happens through a different path: when the agent writes a notebook
without declaring it, the post-chain action episode (via `_store_action_episode()`)
captures what happened. The feedback injection into REFLECT is a FUTURE
enhancement that requires splitting the chain execution — defer to AD-643b-3.

**For this build, implement:**

1. Post-chain detection of undeclared actions (log + metric)
2. Store the finding as part of the action episode reflection

### Insert location: In `_execute_chain_with_intent_routing()`, after the
Phase 2 `_execute_sub_task_chain()` call returns (line ~1929).

**Current code (line 1927-1929):**
```python
        if has_comm_action and execute_steps:
            # Re-execute full chain with skills now loaded.
            return await self._execute_sub_task_chain(full_chain, observation)
```

**Replace with:**
```python
        if has_comm_action and execute_steps:
            # Re-execute full chain with skills now loaded.
            chain_result = await self._execute_sub_task_chain(full_chain, observation)

            # AD-643b: Post-chain undeclared action detection
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
                    # Store in observation for episode capture
                    observation["_undeclared_action_feedback"] = {
                        "undeclared_actions": undeclared,
                        "missed_skills": missed_skills,
                    }

            return chain_result
```

### Engineering notes:

- `chain_result` is a dict with `llm_output` key (the final REFLECT or COMPOSE
  output) — this is the text we scan for action markers
- `catalog`, `department`, `rank_val` are already in scope from the skill loading
  block above (line ~1890)
- The `_undeclared_action_feedback` stored in observation will be available to
  `_store_action_episode()` if it reads observation metadata — but the primary
  value is the log line for debugging
- The REFLECT feedback injection (Change 5) will NOT fire for this build because
  the detection happens AFTER the chain completes. Keep the REFLECT injection
  code in place anyway — it becomes active when we later split chain execution
  or add a re-reflect step.

**IMPORTANT:** Change 5 (REFLECT feedback injection) should still be implemented
as specified above. Even though the `_undeclared_action_feedback` key won't be
populated BEFORE REFLECT runs in this build, the code is forward-compatible:
when AD-643b-3 adds chain splitting or re-reflection, the injection point is
already wired. For now, the primary feedback loop is:

1. Log line alerts the operator (debugging)
2. The observation metadata is available for episode storage enrichment
3. Phase 1 trigger awareness prevents most misses proactively

---

## Change 7: Episode enrichment with trigger feedback

In `_store_action_episode()` (line ~4001), add undeclared action feedback to the
episode outcomes when present.

### Insert location: In the `outcomes` list construction (around line 4080).

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

Then use `_outcome` in the Episode constructor:
```python
        outcomes=[_outcome],
```

### Engineering notes:

- The episode `outcomes` dict is flexible — adding keys is safe
- This enrichment enables future gap detection (AD-539 integration) to identify
  agents with persistent trigger misses
- The episodic reflection field already summarizes the action — no change needed

---

## Backward Compatibility

- **No `_eligible_triggers` in observation** → `_format_trigger_awareness()` returns
  empty string → ANALYZE prompt unchanged
- **No `_undeclared_action_feedback` in observation** → REFLECT prompt unchanged,
  episode outcomes unchanged
- **Skills without `probos-triggers`** → `get_eligible_triggers()` skips them
  (filters for non-empty triggers) → intent-based fallback preserved
- **Non-intent-routing path** → `_execute_sub_task_chain()` is untouched; only
  `_execute_chain_with_intent_routing()` gets the new detection
- **AD-639 low-trust agents** → Skip REFLECT, so feedback injection is moot.
  They still get Phase 1 awareness (trigger list in ANALYZE prompt).

## Known Limitations (Not in Scope)

1. **REFLECT feedback doesn't fire this build.** Detection is post-chain; REFLECT
   already ran. The injection code is forward-compatible for AD-643b-3.
2. **`ward_room_post` is not detectable post-hoc.** The compose output IS the post.
   Over-declaration of `ward_room_post` can't be detected by output markers.
3. **Pure non-comm paths skip the chain.** An agent declaring only `['notebook']`
   uses single-call, not the chain. No REFLECT, no feedback. Phase 1 awareness
   is the primary mechanism for these cases.
4. **Over-declaration tracking deferred.** Detecting when agents declare actions
   they don't take is a Phase 3 diagnostic (design doc specifies this).

---

## Test Requirements

### New test file: `tests/test_trigger_learning.py`

**Skill catalog tests:**
1. `test_get_eligible_triggers_basic` — returns correct action→skill mapping
2. `test_get_eligible_triggers_universal_department` — `department="*"` skills
   appear for all agents
3. `test_get_eligible_triggers_department_filter` — department-specific skills
   only appear for matching agents
4. `test_get_eligible_triggers_rank_filter` — above-rank skills excluded
5. `test_get_eligible_triggers_no_triggers` — skills without `probos-triggers`
   are excluded (not returned)
6. `test_get_eligible_triggers_empty_cache` — empty catalog returns empty dict
7. `test_get_eligible_triggers_multiple_skills_same_trigger` — action tag maps
   to multiple skills

**Trigger awareness formatting tests:**
8. `test_format_trigger_awareness_with_triggers` — produces formatted string
9. `test_format_trigger_awareness_empty` — returns empty string when no triggers
10. `test_format_trigger_awareness_sorted` — output is alphabetically sorted

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
20. `test_format_trigger_feedback_with_actions` — produces formatted block
21. `test_format_trigger_feedback_empty` — returns empty when no undeclared
22. `test_format_trigger_feedback_no_missed_skills` — handles empty skills list

**Integration tests:**
23. `test_chain_with_trigger_awareness_injection` — ANALYZE prompt includes
    trigger list when eligible triggers exist
24. `test_chain_without_trigger_awareness` — no injection when no eligible triggers
25. `test_post_chain_undeclared_detection` — undeclared actions detected after
    chain completes, log line emitted
26. `test_post_chain_no_undeclared` — no detection when all actions declared
27. `test_episode_enrichment_with_undeclared` — episode outcomes include
    `undeclared_actions` and `missed_skills` when present
28. `test_episode_enrichment_without_undeclared` — episode outcomes unchanged
    when no undeclared actions
29. `test_reflect_feedback_key_in_observation` — `_undeclared_action_feedback`
    set in observation dict after detection
30. `test_backward_compat_no_triggers` — skills without triggers don't appear
    in eligible list, intent fallback preserved

---

## Verification Checklist

Before submitting, verify:

- [ ] `get_eligible_triggers()` filters match `find_triggered_skills()` logic
- [ ] `_RANK_ORDER` used consistently (line 28 of skill_catalog.py)
- [ ] `_eligible_triggers` key name consistent across cognitive_agent.py and analyze.py
- [ ] `_undeclared_action_feedback` key name consistent across cognitive_agent.py,
      reflect.py, and episode storage
- [ ] ANALYZE prompt changes don't break existing `intended_actions` parsing
- [ ] `_extract_intended_actions()` still works (no regressions)
- [ ] Rank enum `.value` extraction handles both string and enum cases
- [ ] All new functions have docstrings with AD reference
- [ ] `import re` in `_detect_undeclared_actions()` doesn't cause issues (already
      imported at module level in cognitive_agent.py — verify)
- [ ] No circular imports introduced
- [ ] All 30 tests pass
- [ ] Targeted tests only — no full suite run needed (additive build)
