# AD-532d: Multi-Agent Compound Procedures — Build Prompt

**Depends on:** AD-532 ✅, AD-533 ✅, AD-534 ✅

**Goal:** When a success-dominant episode cluster spans multiple agents, extract a compound procedure with agent role assignments per step. This captures collaborative workflows (e.g., Security analyzes → Engineering implements → Builder deploys) as replayable procedures.

**Principles compliance:** SOLID (single responsibility — compound extraction is its own function), DRY (reuses `_format_episode_blocks()`, `_parse_procedure_json()`, `_build_steps_from_data()`), Open/Closed (new function, no modification of existing extraction paths), Fail Fast (log-and-degrade on extraction failure), Cloud-Ready (no schema migration — steps stored in JSON `content_snapshot`).

---

## Part 0: ProcedureStep Enhancement

**File:** `src/probos/cognitive/procedures.py`

### 0a. Add `agent_role` field to `ProcedureStep`

Add an optional `agent_role: str = ""` field to the `ProcedureStep` dataclass. Empty string means "any agent" (backward compatible with all existing procedures).

This is a **functional role descriptor** (e.g., `"security_analysis"`, `"engineering_implementation"`), NOT a specific callsign. Roles are resilient to agent changes (resets, crew rotation).

### 0b. Update `ProcedureStep.to_dict()`

Include `"agent_role": self.agent_role` in the returned dict.

### 0c. Update `_build_steps_from_data()`

Parse the optional `agent_role` from each step's JSON data:

```python
agent_role=s.get("agent_role", ""),
```

This is the single enhancement point — all extraction paths (CAPTURED, FIX, DERIVED, NEGATIVE, COMPOUND) flow through `_build_steps_from_data()`. Only COMPOUND populates `agent_role`, but the parser handles it uniformly. Backward compatible: existing procedures and other extraction prompts produce steps without `agent_role`, which defaults to `""`.

---

## Part 1: Compound Extraction Prompt & Function

**File:** `src/probos/cognitive/procedures.py`

### 1a. `_COMPOUND_SYSTEM_PROMPT`

Create a new system prompt constant for multi-agent compound procedure extraction. Key instructions for the LLM:

1. **Identify the collaborative workflow pattern** across the episodes — which agents contributed what, in what order
2. **Assign a functional `agent_role`** per step — generalize from specific agent names/IDs in the episodes to descriptive roles (e.g., agent "worf" → role "security_analysis", agent "laforge" → role "engineering_diagnostics"). Do not use callsigns as roles.
3. **Capture handoff points** — Step N's `expected_output` should match Step N+1's `expected_input` when the role changes between steps (cross-agent handoff)
4. **Preserve sequential ordering** — steps should reflect the temporal ordering agents took across episodes
5. Include `"agent_role"` in each step JSON object

Use the same JSON schema as `_SYSTEM_PROMPT`, with the addition of `"agent_role"` per step. Include the same AD-541b READ-ONLY constraints:
- Reference episode IDs, do not reconstruct narratives
- Extract the COMMON collaborative pattern, not any single episode's exact steps
- If no common multi-agent pattern can be extracted, return `{"error": "no_compound_pattern"}`

### 1b. `extract_compound_procedure_from_cluster()`

New async function with signature:

```python
async def extract_compound_procedure_from_cluster(
    cluster: Any,  # EpisodeCluster
    episodes: list[Any],  # Episode objects in this cluster
    llm_client: Any,  # BaseLLMClient
) -> Procedure | None:
```

Implementation follows the same pattern as `extract_procedure_from_cluster()`:
1. Build user prompt with `_format_episode_blocks(episodes)` — episodes already include `ep.agent_ids` per episode, giving the LLM full agent attribution context
2. Add cluster metadata: cluster_id, success_rate, intent_types, **participating_agents** (include agent IDs so the LLM can map them to roles)
3. Call LLM with `_COMPOUND_SYSTEM_PROMPT` + user prompt, tier `"standard"`
4. Parse with `_parse_procedure_json()`
5. Build steps with `_build_steps_from_data()` (now handles `agent_role`)
6. Construct `Procedure` with:
   - `origin_agent_ids=cluster.participating_agents`
   - `origin_cluster_id=cluster.cluster_id`
   - `provenance=[ep.id for ep in episodes]`
   - `extraction_date=time.time()`
   - `evolution_type="CAPTURED"`
   - `intent_types=cluster.intent_types`
7. Return `None` on any failure (log-and-degrade)

**DRY:** Reuse `_format_episode_blocks()`, `_parse_procedure_json()`, `_build_steps_from_data()`. Do NOT duplicate any of these helpers.

---

## Part 2: Dream Cycle Routing & Replay Formatting

### 2a. Dream Cycle Step 7 Conditional

**File:** `src/probos/cognitive/dreaming.py`

In the Step 7 success-dominant extraction loop, add a conditional branch at the point where `extract_procedure_from_cluster()` is currently called:

```python
if len(cluster.participating_agents) >= 2:
    procedure = await extract_compound_procedure_from_cluster(
        cluster=cluster,
        episodes=matched_episodes,
        llm_client=self._llm_client,
    )
else:
    procedure = await extract_procedure_from_cluster(
        cluster=cluster,
        episodes=matched_episodes,
        llm_client=self._llm_client,
    )
```

Everything else in the loop body stays identical — store/dedup/logging/error handling. The only change is which extraction function is called based on the number of participating agents.

Add the import for `extract_compound_procedure_from_cluster` alongside the existing `extract_procedure_from_cluster` import.

### 2b. Replay Formatting Enhancement

**File:** `src/probos/cognitive/cognitive_agent.py`

In `_format_procedure_replay()`, enhance the step formatting to include `agent_role` when present:

Current:
```python
lines.append(f"**Step {step.step_number}:** {step.action}")
```

Enhanced:
```python
if step.agent_role:
    lines.append(f"**Step {step.step_number} [{step.agent_role}]:** {step.action}")
else:
    lines.append(f"**Step {step.step_number}:** {step.action}")
```

No multi-agent dispatch orchestration. The replaying agent outputs the full procedure with role annotations. Actual dispatch deferred to AD-534c.

---

## Part 3: Tests

**File:** `tests/test_compound_procedures.py`

### Test Class 1: `TestProcedureStepAgentRole`
1. `test_agent_role_default_empty` — ProcedureStep() has agent_role="" by default
2. `test_agent_role_set` — ProcedureStep(agent_role="security_analysis") stores the role
3. `test_to_dict_includes_agent_role` — to_dict() output contains "agent_role" key
4. `test_to_dict_agent_role_empty` — to_dict() includes agent_role="" when not set
5. `test_build_steps_parses_agent_role` — `_build_steps_from_data()` with agent_role in JSON → step has role
6. `test_build_steps_missing_agent_role_defaults_empty` — `_build_steps_from_data()` without agent_role → step.agent_role == ""
7. `test_build_steps_backward_compatible` — existing step data (no agent_role key) → step.agent_role == ""

### Test Class 2: `TestCompoundSystemPrompt`
8. `test_compound_prompt_exists` — `_COMPOUND_SYSTEM_PROMPT` is a non-empty string
9. `test_compound_prompt_mentions_agent_role` — prompt contains "agent_role"
10. `test_compound_prompt_mentions_handoff` — prompt contains "handoff" or similar collaborative language
11. `test_compound_prompt_read_only_framing` — prompt contains AD-541b READ-ONLY language

### Test Class 3: `TestExtractCompoundProcedure`
12. `test_basic_compound_extraction` — mock LLM returns valid compound JSON with agent_roles → Procedure with steps containing agent_role
13. `test_compound_extraction_origin_agent_ids` — result Procedure has origin_agent_ids matching cluster.participating_agents
14. `test_compound_extraction_llm_decline` — LLM returns `{"error": "no_compound_pattern"}` → returns None
15. `test_compound_extraction_llm_failure` — LLM raises exception → returns None, no crash
16. `test_compound_extraction_malformed_json` — LLM returns bad JSON → returns None
17. `test_compound_extraction_markdown_fences` — LLM wraps JSON in ```json fences → correctly parsed
18. `test_compound_extraction_preserves_intent_types` — intent_types from cluster flow to Procedure
19. `test_compound_extraction_provenance` — episode IDs flow to Procedure.provenance
20. `test_compound_extraction_steps_have_roles` — each extracted step has a non-empty agent_role
21. `test_compound_extraction_uses_format_episode_blocks` — verify the function calls `_format_episode_blocks()` (DRY)

### Test Class 4: `TestDreamCycleCompoundRouting`
22. `test_multi_agent_cluster_uses_compound_extraction` — cluster with 2+ participating_agents → `extract_compound_procedure_from_cluster` called
23. `test_single_agent_cluster_uses_standard_extraction` — cluster with 1 participating_agent → `extract_procedure_from_cluster` called
24. `test_compound_extracted_saved_to_store` — compound procedure saved via ProcedureStore.save()
25. `test_compound_cluster_dedup` — compound cluster_id tracked in `_extracted_cluster_ids`
26. `test_compound_extraction_failure_nonfatal` — compound extraction raises → logs, continues, no crash

### Test Class 5: `TestReplayFormatting`
27. `test_format_replay_with_agent_role` — step with agent_role → output contains `[security_analysis]`
28. `test_format_replay_without_agent_role` — step without agent_role → output does NOT contain brackets
29. `test_format_replay_mixed_roles` — procedure with some steps having roles and some without → correct formatting for each

### Test Class 6: `TestCompoundEndToEnd`
30. `test_full_pipeline_compound` — multi-agent cluster → compound extraction → store → find_matching → replay with role annotations

---

## Cross-Cutting Requirements

- **DRY:** Reuse `_format_episode_blocks()`, `_parse_procedure_json()`, `_build_steps_from_data()`. Do NOT duplicate any helper logic.
- **Backward compatibility:** All existing procedures and tests must continue to work unchanged. `agent_role=""` is the default everywhere.
- **Log-and-degrade:** Compound extraction failure must never crash the dream cycle. Log at debug level, continue.
- **AD-541b framing:** The compound prompt must include READ-ONLY episode constraints.
- **No schema migration:** `agent_role` is stored inside `content_snapshot` JSON via ProcedureStep.to_dict(). No SQLite column additions needed.
- **No multi-agent dispatch:** Replay formats with role annotations but executes as single-agent output. Orchestrated dispatch deferred to AD-534c.

---

## Validation Checklist

### Part 0 — ProcedureStep Enhancement
- [ ] `ProcedureStep.agent_role` field exists with default `""`
- [ ] `ProcedureStep.to_dict()` includes `"agent_role"` key
- [ ] `_build_steps_from_data()` parses `agent_role` from JSON data
- [ ] `_build_steps_from_data()` defaults `agent_role` to `""` when absent
- [ ] Existing procedure extraction (CAPTURED, FIX, DERIVED, NEGATIVE) still works — steps have `agent_role=""`

### Part 1 — Compound Extraction
- [ ] `_COMPOUND_SYSTEM_PROMPT` exists, mentions agent_role, handoffs, READ-ONLY
- [ ] `extract_compound_procedure_from_cluster()` function exists with correct signature
- [ ] Function reuses `_format_episode_blocks()` (DRY)
- [ ] Function reuses `_parse_procedure_json()` (DRY)
- [ ] Function reuses `_build_steps_from_data()` (DRY)
- [ ] Function includes cluster.participating_agents in user prompt for LLM context
- [ ] Result Procedure has `origin_agent_ids = cluster.participating_agents`
- [ ] Result Procedure has `evolution_type = "CAPTURED"`
- [ ] LLM decline (`{"error": ...}`) → returns None
- [ ] LLM exception → returns None, logged at debug
- [ ] Malformed JSON → returns None, no crash

### Part 2 — Dream Cycle & Replay
- [ ] Step 7 routes `len(participating_agents) >= 2` to compound extraction
- [ ] Step 7 routes `len(participating_agents) < 2` to standard extraction
- [ ] Import added for `extract_compound_procedure_from_cluster`
- [ ] Compound procedure saved to ProcedureStore same as standard
- [ ] Compound cluster_id tracked in `_extracted_cluster_ids` (dedup)
- [ ] `_format_procedure_replay()` includes `[agent_role]` annotation when present
- [ ] `_format_procedure_replay()` omits brackets when agent_role is empty
- [ ] Compound extraction failure is log-and-degrade, does not break dream cycle

### Part 3 — Tests
- [ ] All ~30 tests pass
- [ ] No existing tests broken
- [ ] Test coverage: ProcedureStep field, prompt content, extraction function, dream routing, replay formatting, end-to-end

### Cross-Cutting
- [ ] No duplication of `_format_episode_blocks()`, `_parse_procedure_json()`, or `_build_steps_from_data()`
- [ ] No SQLite schema changes in procedure_store.py
- [ ] `agent_role` round-trips through `to_dict()` → JSON → `_build_steps_from_data()` → `ProcedureStep`
- [ ] `pytest tests/test_compound_procedures.py -v` — all green
- [ ] `pytest tests/ -x --timeout=30` — full suite green (pre-existing failures excluded)
