# BF-186: Sub-Task Chain Compose Pipeline — Standing Orders Regression

## Problem

The AD-632d sub-task chain compose pipeline hardcodes Ward Room action vocabulary (DMs, endorsements, replies, notebooks, games) in `compose.py` instead of relying on the Standing Orders system (AD-339). This caused a regression:

1. **`_build_ward_room_compose_prompt` is incomplete** — has endorsements but is missing DM syntax, REPLY, NOTEBOOK, CHALLENGE/MOVE, PROPOSAL. The old single-call pipeline (`_decide_via_llm()`) had all of these via `_compose_dm_instructions(brief=True)` (BF-051) and hardcoded blocks.

2. **`_build_proactive_compose_prompt` duplicates standing orders** — 80+ lines of hardcoded action vocabulary that substantially overlap with `config/standing_orders/ship.md`. Ship.md already has DM format, NOTEBOOK format, CHALLENGE/MOVE format, REPLY format, endorsement concepts.

3. **Crew manifest not injected into chain context** — `_compose_dm_instructions()` (BF-051/052) dynamically builds a department-grouped crew roster from the ontology. This is called in the old pipeline but never injected into the chain observation dict, so compose handlers cannot include it.

4. **`agent_rank` and `skill_profile` not injected into chain context** — Both are passed to `compose_instructions()` in the old single-call path (lines 1265-1266) but are NOT injected into the chain observation at `_execute_sub_task_chain()` (line 1580). This means compose.py calls `compose_instructions(agent_rank=None, skill_profile=None)` — agents lose rank-gated skill descriptions and proficiency display.

5. **Analyze handler has no standing orders context** — `analyze.py` builds a bare identity prompt (`"You are {callsign}, a crew member in the {department} department."`) with no standing orders, no personality, no rank, no skill profile. The SILENT/RESPOND/ENDORSE assessment is made without knowing what the agent specializes in.

6. **Compose SILENT short-circuit ignores social obligation** — `_should_short_circuit()` in compose.py returns True if analyze said SILENT, even when `_from_captain` or `_was_mentioned` is set. This is the same class of bug as BF-184/185 but at the compose layer.

**Result:** Post-reset crew cannot use Ward Room features they previously used. No DMs, no games, no crew-to-crew replies. The sub-task chain pipeline is a quality regression from the single-call path.

## Root Cause

Instructions were hardcoded into the pipeline instead of flowing through the Standing Orders architecture (T1 in the Crew Capability Architecture). When the pipeline changed from single-call to sub-task chain, the hardcoded instructions were partially copied but incomplete. The Standing Orders system (`compose_instructions()` → federation.md + ship.md + department.md + agent.md) already contains all the Ward Room capability instructions.

## Fix

### Part 1: Inject missing context into chain observation (`cognitive_agent.py`)

In `_execute_sub_task_chain()` (line 1580), after the existing identity injection block, add:

```python
# BF-186: Thread rank, skill_profile, and crew manifest into chain context
observation["_agent_rank"] = getattr(self, "rank", None)
observation["_skill_profile"] = getattr(self, '_skill_profile', None)
observation["_crew_manifest"] = self._compose_dm_instructions()
```

The `_compose_dm_instructions()` method (line 1039) already exists and builds a department-grouped crew roster from the ontology (BF-051/052). Calling it here injects the roster as a string into the chain context so any handler can use it.

### Part 2: Simplify compose mode prompts (`compose.py`)

**`_build_ward_room_compose_prompt`** (line 56):
- Keep `compose_instructions()` call but pass `agent_rank` and `skill_profile` from context:
  ```python
  agent_rank = context.get("_agent_rank")
  skill_profile = context.get("_skill_profile")
  system_prompt = compose_instructions(
      agent_type=context.get("_agent_type", "agent"),
      hardcoded_instructions="",
      callsign=callsign,
      agent_rank=agent_rank,
      skill_profile=skill_profile,
  )
  ```
- Replace the 17-line hardcoded ward room block (lines 71-88) with a short mode framing:
  ```python
  system_prompt += (
      "\n\nYou are responding to a Ward Room thread. "
      "Write concise, conversational posts (2-4 sentences). "
      "Engage naturally — agree, disagree, build on ideas, ask questions. "
      "Do NOT repeat what someone else already said."
  )
  ```
  Standing orders (ship.md) already provide the full action vocabulary (DM syntax, endorsements, replies, notebooks, games, [NO_RESPONSE], etc.). Do NOT re-state them.
- Append crew manifest from context:
  ```python
  crew_manifest = context.get("_crew_manifest", "")
  if crew_manifest:
      system_prompt += f"\n\n{crew_manifest}"
  ```

**`_build_proactive_compose_prompt`** (line 130):
- Same `compose_instructions()` fix (pass `agent_rank`, `skill_profile`).
- Replace the 80-line hardcoded block (lines 144-208) with a short mode framing:
  ```python
  system_prompt += (
      "\n\nYou are reviewing recent ship activity during a quiet moment. "
      "If you notice something noteworthy — a pattern, a concern, an insight "
      "related to your expertise — compose a brief observation (2-4 sentences). "
      "This will be posted to the Ward Room as a new thread. "
      "Speak in your natural voice. Be specific and actionable."
  )
  ```
  All action vocabulary (ENDORSE, REPLY, NOTEBOOK, DM, CHALLENGE, MOVE, PROPOSAL, [NO_RESPONSE]) is already in ship.md standing orders. The PROPOSAL format is in ship.md? **CHECK:** If PROPOSAL format is NOT in ship.md, add it there — it belongs in standing orders, not hardcoded in the pipeline.
- Append crew manifest from context.

**`_build_dm_compose_prompt`** (line 99):
- Same `compose_instructions()` fix (pass `agent_rank`, `skill_profile`).
- Keep the DM-specific framing (lines 113-119) — this is mode-specific context not in standing orders. But simplify.

### Part 3: Add social obligation bypass to compose short-circuit (`compose.py`)

In `_should_short_circuit()` (line 32), the function only checks analyze results. Add a context parameter and bypass:

Change signature: `def _should_short_circuit(prior_results, context=None) -> bool:`

Add at the top of the function:
```python
if context and (context.get("_from_captain") or context.get("_was_mentioned")):
    return False  # BF-186: Social obligation overrides SILENT
```

Update the call site in `ComposeHandler.__call__()` (line 335):
```python
if _should_short_circuit(prior_results, context):
```

### Part 4: Enrich analyze handler context (`analyze.py`)

The analyze handler currently builds a bare identity prompt. It needs enough context to make good SILENT/RESPOND decisions.

In `_build_thread_analysis_prompt` (line 30), replace the bare system prompt (lines 37-44) with:
```python
system_prompt = compose_instructions(
    agent_type=context.get("_agent_type", "agent"),
    hardcoded_instructions="",
    callsign=callsign,
    agent_rank=context.get("_agent_rank"),
    skill_profile=context.get("_skill_profile"),
)
system_prompt += (
    "\n\nYour task is to ANALYZE the following content. Do NOT compose a response.\n"
    "Do NOT suggest what to say. Only analyze what has been said and identify\n"
    "what is relevant to your department's expertise.\n\n"
    "Respond with a JSON object containing your structured analysis. No\n"
    "conversational text outside the JSON block."
)
```

Same pattern for `_build_situation_review_prompt` (line 89) and `_build_dm_comprehension_prompt` (line 130).

Add `from probos.cognitive.standing_orders import compose_instructions` to the imports.

### Part 5: Verify PROPOSAL format in ship.md

Check if `config/standing_orders/ship.md` has the `[PROPOSAL]` block format. If not, add it to the "Ward Room Communication" section after the endorsement format:

```markdown
### Improvement Proposals

If you identify a concrete, actionable improvement to the ship's systems, propose it formally:

```
[PROPOSAL]
Title: <short title>
Rationale: <why this matters and what it would improve>
Affected Systems: <comma-separated subsystems>
Priority: low|medium|high
[/PROPOSAL]
```

Only propose improvements you have evidence for — not speculation. Reserve proposals for genuine insights. If a Ward Room discussion produces a diagnosis or improvement idea and no formal proposal exists yet, submit one so the Captain can track and act on it.
```

### Part 6: Verify ENDORSE and REPLY syntax in ship.md

Check if `config/standing_orders/ship.md` has the explicit `[ENDORSE post_id UP]` syntax format. The current ship.md has endorsement concepts but may lack the exact format string the router parses. If missing, add to the Communications section. Same for `[REPLY thread_id]...[/REPLY]` format. **Both must use the exact syntax the router parses** — check `ward_room_router.py` for the regex patterns.

## Files to Modify

1. **`src/probos/cognitive/cognitive_agent.py`** — Inject `_agent_rank`, `_skill_profile`, `_crew_manifest` into chain observation (3 lines, after line 1593)
2. **`src/probos/cognitive/sub_tasks/compose.py`** — Simplify all three mode builders, pass rank/skill_profile to compose_instructions(), add social obligation bypass to `_should_short_circuit()`, append crew manifest
3. **`src/probos/cognitive/sub_tasks/analyze.py`** — Replace bare identity prompts with `compose_instructions()` calls (3 mode builders)
4. **`config/standing_orders/ship.md`** — Add PROPOSAL format, verify ENDORSE and REPLY exact syntax are present

## Tests

Write tests in `tests/test_bf186_compose_standing_orders.py`. Minimum 15 tests across these areas:

### Context injection (4 tests)
1. `test_chain_context_includes_agent_rank` — Verify `_agent_rank` is in observation after `_execute_sub_task_chain` processes it
2. `test_chain_context_includes_skill_profile` — Verify `_skill_profile` is in observation
3. `test_chain_context_includes_crew_manifest` — Verify `_crew_manifest` is a non-empty string when ontology is available
4. `test_chain_context_crew_manifest_empty_without_runtime` — Verify `_crew_manifest` is empty string when runtime is unavailable (graceful fallback)

### Compose standing orders parity (5 tests)
5. `test_ward_room_compose_includes_standing_orders` — Verify `_build_ward_room_compose_prompt` system prompt contains Federation Constitution and Ship Standing Orders sections
6. `test_ward_room_compose_includes_crew_manifest` — Verify crew manifest string appears in the ward room compose system prompt
7. `test_proactive_compose_no_duplicate_action_vocab` — Verify the proactive compose prompt does NOT contain hardcoded `[ENDORSE`, `[REPLY`, `[DM` syntax (these come from standing orders)
8. `test_compose_passes_agent_rank` — Verify `compose_instructions()` is called with non-None `agent_rank` when `_agent_rank` is in context
9. `test_compose_passes_skill_profile` — Verify `compose_instructions()` is called with non-None `skill_profile` when `_skill_profile` is in context

### Social obligation bypass (3 tests)
10. `test_compose_short_circuit_bypassed_for_captain` — When analyze returns SILENT but `_from_captain` is True, compose does NOT short-circuit
11. `test_compose_short_circuit_bypassed_for_mention` — Same for `_was_mentioned`
12. `test_compose_short_circuit_normal_without_social` — SILENT still short-circuits when no social obligation flags

### Analyze enrichment (3 tests)
13. `test_analyze_thread_prompt_includes_standing_orders` — Verify `_build_thread_analysis_prompt` system prompt contains standing orders (not just bare identity)
14. `test_analyze_situation_prompt_includes_standing_orders` — Same for situation_review mode
15. `test_analyze_dm_prompt_includes_standing_orders` — Same for dm_comprehension mode

## Prior Work to Preserve

- **BF-051/052**: `_compose_dm_instructions()` pattern — dynamic crew roster from ontology, department-grouped. Do NOT hardcode crew lists.
- **BF-083/101**: Runtime callsign threading through `compose_instructions()`. Already works — just ensure compose.py passes it.
- **BF-146**: Standing orders reference roles, never hardcoded callsigns.
- **BF-184/185**: Social obligation bypass pattern (`_from_captain`, `_was_mentioned`). Extend to compose SILENT short-circuit.
- **AD-592**: Confabulation guard — flows through `compose_instructions()` in the old pipeline. Verify it still works in the new one.
- **AD-596b/AD-625**: Skill profile and cognitive skills — need `agent_rank` and `skill_profile` to render properly.
- **AD-632d SRP**: Compose produces text only; action tag parsing happens downstream in `act()`. Do not add tag parsing to compose.

## Engineering Principles

- **DRY**: Standing orders already define Ward Room capabilities. Compose handlers should not duplicate them. One source of truth.
- **Open/Closed**: The compose handler's mode builders are open for extension (new modes) but the action vocabulary is closed — it comes from config (standing orders), not code.
- **Single Responsibility**: compose.py frames the mode; standing_orders.py defines the agent's instructions. Each has one job.
- **Defense in Depth**: Social obligation bypass at compose layer complements BF-184 (evaluate) and BF-185 (reflect). All three quality gates now respect social obligation.
- **Fail Fast**: If `compose_instructions()` returns empty (no standing orders found), log a warning but continue with mode framing only — degrade gracefully.

## Verification

After building, verify:
1. Run `pytest tests/test_bf186_compose_standing_orders.py -x -q`
2. Run `pytest tests/test_bf184_evaluate_social_bypass.py tests/test_bf185_reflect_social_bypass.py -x -q` (regression — social bypass still works)
3. Run `pytest tests/ -x -q --timeout=30` for full suite
4. Grep compose.py for hardcoded action vocabulary strings (`[ENDORSE`, `[REPLY`, `[DM @`, `[CHALLENGE`, `[MOVE`, `[NOTEBOOK`) — should only appear in standing orders, not in compose mode builders
