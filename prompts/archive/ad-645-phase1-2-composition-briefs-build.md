# AD-645 Phase 1+2: Composition Briefs + COMPOSE Context Enrichment

**AD:** AD-645 (Artifact-Mediated Cognitive Chain)
**Phase:** 1+2 of 5
**Status:** Ready for builder
**Issue:** #287
**Depends on:** AD-644 Phase 1-4 complete (23/23 parity)
**Scope:** 2 files modified (`analyze.py`, `compose.py`), 1 test file created, zero new modules

---

## Context

The cognitive chain (QUERY → ANALYZE → COMPOSE → EVALUATE → REFLECT) produces flatter, less confident responses than the one-shot `_build_user_message()` path — even after AD-644 achieved full context parity. Root cause: ANALYZE compresses its situational understanding into a routing slip (~200 tokens of JSON), then COMPOSE works from that summary rather than the source material.

**Evidence:** Same agent (Ezri/Counselor), same question ("How is the crew doing?"):
- **One-shot:** Rich, confident — references fixation patterns across 4 departments, message backlog disparities, systemic vs individual framing
- **Chain:** Hedging — says "I need access to current trust scores" despite having them in context, offers to pull data rather than using it

**Fix:** Replace ANALYZE's routing-slip output with a **composition brief** — a structured plan that tells COMPOSE what to write about, what evidence to reference, what tone to use. Additionally pass environmental SA keys to COMPOSE so it has both the focused plan AND the raw material.

---

## Phase 1: ANALYZE Output Enrichment (Composition Brief)

### File: `src/probos/cognitive/sub_tasks/analyze.py`

#### Change 1: Increase max_tokens

ANALYZE's `max_tokens=1024` (line 419) is tight for the existing routing slip. The composition brief adds ~300-400 tokens. Increase to `1536`.

```python
# Line 419: Change
max_tokens=1024,
# To:
max_tokens=1536,
```

#### Change 2: Update `_build_situation_review_prompt()` (lines 118-285)

Add the `composition_brief` field to the assessment schema requested in the user prompt. The brief is an additional JSON key alongside the existing 5 keys.

Find the "Assessment Required" section at the end of the user prompt (approximately line 267). Replace the assessment schema with:

```python
    user_prompt = (
        f"{duty_section}"
        f"{innate_section}"
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
        "6. **composition_brief**: A plan for composing your response. Include:\n"
        "   - **situation**: What is happening? (1-2 sentences)\n"
        "   - **key_evidence**: Specific observations, data points, or memories you\n"
        "     should reference in your response. Be concrete — cite what you see\n"
        "     in the situation data above, not generalities.\n"
        "   - **response_should_cover**: What your response needs to address (bullet list).\n"
        "   - **tone**: How should the response be framed? Consider audience, formality,\n"
        "     and your relationship with the recipient.\n"
        "   - **sources_to_draw_on**: Which knowledge sources are relevant (episodic\n"
        "     memories, Ward Room observations, duty data, training knowledge).\n"
        "   If intended_actions is [\"silent\"], composition_brief should be null.\n"
        f"{_format_trigger_awareness(context)}\n"
        "Return a JSON object with these 6 keys. No other text."
    )
```

#### Change 3: Update `_build_thread_analysis_prompt()` (lines 46-115)

Add the `composition_brief` field to the thread analysis schema. Find the assessment section and add key 7:

```python
        f"6. **intended_actions**: Based on your contribution_assessment, what\n"
        f"   specific actions will you take? List as a JSON array from:\n"
        f"   ward_room_reply, endorse, silent.\n"
        f"   If RESPOND: [\"ward_room_reply\"]. If ENDORSE: [\"endorse\"].\n"
        f"   If both: [\"ward_room_reply\", \"endorse\"]. If SILENT: [\"silent\"].\n"
        f"7. **composition_brief**: A plan for composing your response. Include:\n"
        f"   - **situation**: What is being discussed? (1-2 sentences)\n"
        f"   - **key_evidence**: Specific points from the thread, your memories, or\n"
        f"     your expertise that you should reference. Be concrete.\n"
        f"   - **response_should_cover**: What your reply needs to address.\n"
        f"   - **tone**: How should the reply be framed for this thread?\n"
        f"   - **sources_to_draw_on**: Which knowledge sources are relevant.\n"
        f"   If contribution_assessment is \"SILENT\", composition_brief should be null.\n"
        f"{_format_trigger_awareness(context)}\n"
        f"Return a JSON object with these 7 keys. No other text."
```

**Important:** Replace the existing lines 6 (`intended_actions`) and the final "Return a JSON object with these 6 keys" line. The `intended_actions` definition stays the same — only add key 7 after it and update the count from 6 to 7.

#### Change 4: Update `_build_dm_comprehension_prompt()` (lines 288-339)

Add the `composition_brief` field. Find the comprehension section and add key 5:

```python
        "4. **emotional_tone**: The sender's emotional tone (neutral, urgent, "
        "appreciative, concerned, etc.).\n"
        "5. **composition_brief**: A plan for composing your reply. Include:\n"
        "   - **situation**: What is the sender asking/discussing? (1-2 sentences)\n"
        "   - **key_evidence**: Specific points from the message, your memories, or\n"
        "     your expertise that you should reference. Be concrete.\n"
        "   - **response_should_cover**: What your reply needs to address.\n"
        "   - **tone**: How should you respond given the emotional_tone and your\n"
        "     relationship with the sender?\n"
        "   - **sources_to_draw_on**: Which knowledge sources are relevant.\n\n"
        "Return a JSON object with these 5 keys. No other text."
```

**Important:** Replace the existing "Return a JSON object with these 4 keys" line. Update count from 4 to 5.

---

## Phase 2: COMPOSE Context Enrichment

### File: `src/probos/cognitive/sub_tasks/compose.py`

#### Change 1: Render the composition brief in `_build_user_prompt()` (lines 225-291)

Replace the current ANALYZE rendering (line 238-240):

```python
    # Analysis results from prior ANALYZE step
    analysis = _get_analysis_result(prior_results)
    if analysis:
        parts.append(f"## Analysis\n\n{json.dumps(analysis, indent=2)}")
```

With brief-aware rendering:

```python
    # AD-645: Composition brief from ANALYZE step
    analysis = _get_analysis_result(prior_results)
    if analysis:
        brief = analysis.get("composition_brief")
        if brief and isinstance(brief, dict):
            brief_parts = ["## Composition Brief\n"]
            _situation = brief.get("situation", "")
            if _situation:
                brief_parts.append(f"**Situation:** {_situation}\n")
            _evidence = brief.get("key_evidence")
            if _evidence and isinstance(_evidence, list):
                brief_parts.append("**Key Evidence:**")
                for item in _evidence:
                    brief_parts.append(f"- {item}")
                brief_parts.append("")
            _cover = brief.get("response_should_cover")
            if _cover and isinstance(_cover, list):
                brief_parts.append("**Your response should cover:**")
                for item in _cover:
                    brief_parts.append(f"- {item}")
                brief_parts.append("")
            _tone = brief.get("tone", "")
            if _tone:
                brief_parts.append(f"**Tone:** {_tone}\n")
            _sources = brief.get("sources_to_draw_on", "")
            if _sources:
                brief_parts.append(f"**Sources to draw on:** {_sources}\n")
            parts.append("\n".join(brief_parts))
        else:
            # Fallback: no brief, render analysis as before (backward compat)
            parts.append(f"## Analysis\n\n{json.dumps(analysis, indent=2)}")
```

#### Change 2: Pass environmental SA keys to COMPOSE

After the existing ontology section (approximately line 284-288), add the Phase 3 SA keys that currently only flow to ANALYZE. Add these before the final fallback:

```python
    # AD-645: Environmental situation awareness — COMPOSE needs raw material
    # to draw on alongside the composition brief. These keys already flow
    # to ANALYZE (AD-644 Phase 3); now COMPOSE has them too.
    _ward_room = context.get("_ward_room_activity", "")
    if _ward_room:
        parts.append(f"## Recent Ward Room Activity\n\n{_ward_room}")

    _alerts = context.get("_recent_alerts", "")
    if _alerts:
        parts.append(f"## Recent Alerts\n\n{_alerts}")

    _events = context.get("_recent_events", "")
    if _events:
        parts.append(f"## Recent Events\n\n{_events}")

    _infra = context.get("_infrastructure_status", "")
    if _infra:
        parts.append(f"## Infrastructure Status\n\n{_infra}")

    _sub_stats = context.get("_subordinate_stats", "")
    if _sub_stats:
        parts.append(f"## Subordinate Activity\n\n{_sub_stats}")

    _cold_start = context.get("_cold_start_note", "")
    if _cold_start:
        parts.append(_cold_start)

    _game = context.get("_active_game", "")
    if _game:
        parts.append(f"## Active Game\n\n{_game}")
```

Insert this block AFTER the ontology section and BEFORE the final fallback (`if not parts:`).

---

## What NOT to Do

- Do NOT modify `evaluate.py` or `reflect.py` — those are Phase 4.
- Do NOT modify `cognitive_agent.py` — the observation dict already has all SA keys (AD-644).
- Do NOT modify `sub_task_executor.py` — context filtering already passes all `_*` keys through (line 493).
- Do NOT modify `agent_working_memory.py` — metacognitive storage is Phase 3.
- Do NOT change the ANALYZE temperature (stays at 0.0).
- Do NOT change the COMPOSE temperature (stays at 0.3).
- Do NOT add any schema validation for the composition brief — `extract_json()` handles malformed output gracefully, and the COMPOSE rendering checks `isinstance(brief, dict)` before accessing fields.
- Do NOT modify the `_should_short_circuit()` function — it correctly checks `contribution_assessment` and `intended_actions`, both of which survive alongside the brief.

---

## Tests

Create `tests/test_ad645_composition_briefs.py` with the following tests:

### ANALYZE Tests

1. **test_situation_review_prompt_requests_composition_brief** — Call `_build_situation_review_prompt()` with sample context. Assert the user prompt contains "composition_brief" and all 5 sub-fields (situation, key_evidence, response_should_cover, tone, sources_to_draw_on). Assert it requests "6 keys".

2. **test_thread_analysis_prompt_requests_composition_brief** — Call `_build_thread_analysis_prompt()` with sample context. Assert the user prompt contains "composition_brief" and all 5 sub-fields. Assert it requests "7 keys".

3. **test_dm_comprehension_prompt_requests_composition_brief** — Call `_build_dm_comprehension_prompt()` with sample context. Assert the user prompt contains "composition_brief" and all 5 sub-fields. Assert it requests "5 keys".

4. **test_analyze_max_tokens_increased** — Instantiate the AnalyzeHandler, mock an LLM call, verify `max_tokens=1536` in the LLM request.

### COMPOSE Tests

5. **test_compose_renders_composition_brief** — Create a mock ANALYZE `SubTaskResult` with a `composition_brief` dict containing all 5 fields. Call `_build_user_prompt()`. Assert output contains "## Composition Brief", "**Situation:**", "**Key Evidence:**", "**Your response should cover:**", "**Tone:**", "**Sources to draw on:**".

6. **test_compose_falls_back_without_brief** — Create a mock ANALYZE `SubTaskResult` WITHOUT `composition_brief` key. Call `_build_user_prompt()`. Assert output contains "## Analysis" and the JSON dump (backward compat).

7. **test_compose_handles_null_brief** — Create a mock ANALYZE `SubTaskResult` with `composition_brief: null`. Call `_build_user_prompt()`. Assert fallback to JSON dump.

8. **test_compose_renders_partial_brief** — Create a mock ANALYZE `SubTaskResult` with `composition_brief` containing only `situation` and `tone` (missing other fields). Assert it renders the available fields without error.

9. **test_compose_includes_ward_room_activity** — Set `_ward_room_activity` in context. Call `_build_user_prompt()`. Assert "## Recent Ward Room Activity" appears in output.

10. **test_compose_includes_recent_alerts** — Set `_recent_alerts` in context. Call `_build_user_prompt()`. Assert "## Recent Alerts" appears in output.

11. **test_compose_includes_subordinate_stats** — Set `_subordinate_stats` in context. Call `_build_user_prompt()`. Assert "## Subordinate Activity" appears in output.

12. **test_compose_includes_infrastructure_status** — Set `_infrastructure_status` in context. Call `_build_user_prompt()`. Assert "## Infrastructure Status" appears in output.

13. **test_compose_sa_keys_not_rendered_when_empty** — Call `_build_user_prompt()` with empty context (no SA keys). Assert none of the SA headings appear.

### Integration Tests

14. **test_compose_brief_plus_sa_keys_together** — Create mock ANALYZE result with brief + set SA keys in context. Assert COMPOSE prompt has both the brief section AND the SA sections. Verify ordering: Brief appears before SA context.

15. **test_silent_intended_action_null_brief** — Create mock ANALYZE result with `intended_actions: ["silent"]` and `composition_brief: null`. Assert `_should_short_circuit()` returns True (existing behavior preserved).

---

## Verification

After implementation:

1. `pytest tests/test_ad645_composition_briefs.py -x -q` — all 15 tests pass
2. `pytest tests/test_ad644*.py -x -q` — all 35 AD-644 tests still pass (no regressions)
3. `pytest tests/test_ad639*.py -x -q` — AD-639 chain tuning tests still pass
4. `grep -c "composition_brief" src/probos/cognitive/sub_tasks/analyze.py` — returns 3 (one per mode)
5. `grep -c "Composition Brief" src/probos/cognitive/sub_tasks/compose.py` — returns 1 (render section)
6. `grep -c "_ward_room_activity" src/probos/cognitive/sub_tasks/compose.py` — returns 1 (SA key)
