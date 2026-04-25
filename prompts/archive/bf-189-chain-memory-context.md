# BF-189: Chain Pipeline Memory Context Gaps

## Problem

Three memory context gaps exist in the sub-task chain pipeline that don't exist in the single-shot path. These cause confabulation (agents fabricate context instead of using remembered experiences) and degrade memory-grounded response quality.

### Gap 1: Raw list repr instead of formatted memory (Analyze)

`analyze.py` `_build_thread_analysis_prompt()` line 69:
```python
memories = context.get("recent_memories", "")
memory_section = f"## Relevant Memories\n\n{memories}\n\n"
```

`recent_memories` is a `list[dict]` populated by `_recall_relevant_memories()` in `cognitive_agent.py` line 3532. This renders as Python repr (`[{'input': '...', 'source': 'direct', ...}]`), not human-readable text.

**Single-shot path (no issue):** Uses `_format_memory_section()` (line 2593) which produces structured `=== SHIP MEMORY ===` boundaries with provenance markers (`[direct | verified]`), anchor headers (age, channel, department, participants), and confabulation guards (AD-592).

### Gap 2: DM and situation modes have zero memory context (Analyze)

`_build_dm_comprehension_prompt()` (line 145) and `_build_situation_review_prompt()` (line 97) do NOT read `recent_memories` from context at all.

**Single-shot path (no issue):** `_build_user_message()` includes memories for all three intents: `direct_message` (line 2696), `ward_room_notification` (line 2822), `proactive_think` (line 2998).

**Impact:** When an agent analyzes a DM, it has zero memory of prior interactions with the sender. This directly causes the confabulation observed on 2026-04-16 (Reed/Wesley fabricating "thread 50" and "Napkin Protocol") — the agents had no memory to ground against.

### Gap 3: Compose step has no memory context

`compose.py` `_build_user_prompt()` (line 209) reads:
- `context.get("context", "")` — original thread/DM content
- Prior ANALYZE results
- Prior QUERY data

It does NOT read `recent_memories`. The LLM generating the actual response text has no memory grounding — it only sees the Analyze step's structured JSON output, not the raw memories.

**Single-shot path (no issue):** Memory is in the same LLM call that produces the response, so the LLM naturally grounds against recalled episodes.

**Impact:** Even when Analyze correctly processes memories (after Gap 1/2 are fixed), Compose fabricates details because it doesn't see the memories directly. The Analyze JSON summary can't fully convey memory nuance — Compose needs the formatted memory text.

## Root Cause

When the sub-task chain (AD-632) was designed, memory was injected into the observation dict before `decide()`, but the chain handlers were written without consuming it properly. The QUERY step fetches operational data (thread metadata, trust scores) but not episodic memory — episodic recall was already done upstream. The gap is in how Analyze and Compose pass memory through the chain.

## Fix

### Part 1: Format memories in chain context (`cognitive_agent.py`)

In `_execute_sub_task_chain()`, after line 1601 (`_crew_manifest`), pre-format the memories using the existing `_format_memory_section()`:

```python
# BF-189: Pre-format memories for chain handlers (AD-567b/568c/592 compliance)
raw_memories = observation.get("recent_memories", [])
if raw_memories and isinstance(raw_memories, list):
    source_framing = observation.get("_source_framing")
    formatted_lines = self._format_memory_section(raw_memories, source_framing=source_framing)
    observation["_formatted_memories"] = "\n".join(formatted_lines)
else:
    observation["_formatted_memories"] = ""
```

This reuses the existing `_format_memory_section()` method which includes:
- `=== SHIP MEMORY ===` boundaries (AD-567b)
- Anchor headers: age, channel, department, participants, trigger (AD-567b)
- Provenance markers: `[direct | verified]` (AD-568c)
- Source-authority-calibrated confabulation guard (AD-592)
- Temporal preference for contradictory memories (BF-148)

**DRY:** One formatting path for both single-shot and chain. No new formatter.

### Part 2: Fix thread_analysis memory formatting (`analyze.py`)

Replace the raw memory injection in `_build_thread_analysis_prompt()` (lines 68-72):

**Current:**
```python
memories = context.get("recent_memories", "")
memory_section = ""
if memories:
    memory_section = f"## Relevant Memories\n\n{memories}\n\n"
```

**New:**
```python
# BF-189: Use pre-formatted memory text (AD-567b/568c/592 compliant)
formatted_memories = context.get("_formatted_memories", "")
memory_section = ""
if formatted_memories:
    memory_section = f"## Your Episodic Memories\n\n{formatted_memories}\n\n"
```

### Part 3: Add memory to dm_comprehension mode (`analyze.py`)

In `_build_dm_comprehension_prompt()`, add memory section after the context_section (after line 175):

```python
# BF-189: DM analysis needs memory for grounding (prevents confabulation)
formatted_memories = context.get("_formatted_memories", "")
memory_section = ""
if formatted_memories:
    memory_section = f"## Your Episodic Memories\n\n{formatted_memories}\n\n"
```

Include in the user prompt:
```python
user_prompt = (
    f"## Direct Message\n\n{dm_content}\n\n"
    f"{context_section}"
    f"{memory_section}"
    "## Comprehension Required\n\n"
    ...
)
```

### Part 4: Add memory to situation_review mode (`analyze.py`)

Same pattern in `_build_situation_review_prompt()`, add after context_section (after line 128):

```python
# BF-189: Situation review needs memory for context
formatted_memories = context.get("_formatted_memories", "")
memory_section = ""
if formatted_memories:
    memory_section = f"## Your Episodic Memories\n\n{formatted_memories}\n\n"
```

Include in the user prompt:
```python
user_prompt = (
    f"## Current Situation\n\n{situation_content}\n\n"
    f"{context_section}"
    f"{memory_section}"
    "## Assessment Required\n\n"
    ...
)
```

### Part 5: Add memory to Compose user prompt (`compose.py`)

In `_build_user_prompt()` (line 209), add memory section after the prior data section:

```python
# BF-189: Compose needs memory grounding to prevent confabulation
formatted_memories = context.get("_formatted_memories", "")
if formatted_memories:
    parts.append(f"## Your Episodic Memories\n\n{formatted_memories}")
```

Add this after the Prior Data block (after line 232) and before the empty-parts fallback (line 234). This ensures Compose has the same memory context that the single-shot LLM call would have received.

**Note:** This goes in `_build_user_prompt()` which is the shared user prompt builder used by ALL three compose modes (ward_room_response, dm_response, proactive_observation). One change covers all modes.

## Files to Modify

1. **`src/probos/cognitive/cognitive_agent.py`** — Pre-format memories in `_execute_sub_task_chain()` (Part 1), 5 lines
2. **`src/probos/cognitive/sub_tasks/analyze.py`** — Fix thread_analysis (Part 2), add to dm_comprehension (Part 3), add to situation_review (Part 4)
3. **`src/probos/cognitive/sub_tasks/compose.py`** — Add memory to `_build_user_prompt()` (Part 5), 3 lines

## Tests

Write tests in `tests/test_bf189_chain_memory_context.py`. Minimum 12 tests:

### Part 1: Memory pre-formatting (3 tests)

1. `test_chain_context_includes_formatted_memories` — When `recent_memories` contains a list of episode dicts, verify `observation["_formatted_memories"]` is a string containing `=== SHIP MEMORY ===`.
2. `test_chain_context_empty_memories` — When `recent_memories` is empty list or missing, verify `_formatted_memories` is empty string.
3. `test_chain_context_preserves_confabulation_guard` — When `recent_memories` is present, verify `_formatted_memories` contains "Do NOT fabricate" (AD-592 guard).

### Part 2: Thread analysis formatting (2 tests)

4. `test_thread_analysis_uses_formatted_memories` — Build thread analysis prompt with `_formatted_memories` in context. Verify user prompt contains `## Your Episodic Memories` and the formatted text, NOT a Python list repr.
5. `test_thread_analysis_no_memories` — Build thread analysis prompt without `_formatted_memories`. Verify no memory section in user prompt.

### Part 3: DM comprehension memory (2 tests)

6. `test_dm_comprehension_includes_memories` — Build DM comprehension prompt with `_formatted_memories`. Verify user prompt contains memory section.
7. `test_dm_comprehension_no_memories` — Build DM comprehension prompt without `_formatted_memories`. Verify no memory section but prompt still valid.

### Part 4: Situation review memory (2 tests)

8. `test_situation_review_includes_memories` — Build situation review prompt with `_formatted_memories`. Verify user prompt contains memory section.
9. `test_situation_review_no_memories` — No memories, prompt still valid.

### Part 5: Compose memory grounding (3 tests)

10. `test_compose_user_prompt_includes_memories` — Call `_build_user_prompt()` with `_formatted_memories` in context. Verify output contains memory section.
11. `test_compose_user_prompt_no_memories` — No `_formatted_memories` in context. Verify prompt works without memory section (no error, no empty header).
12. `test_compose_user_prompt_memory_after_analysis` — Verify memory section appears after analysis results in the prompt, so Compose sees analysis + memories together.

## Prior Work Preserved

- **AD-567b:** Anchor-aware recall formatting — reused via `_format_memory_section()`, not reimplemented.
- **AD-568c:** Source priority framing — `SourceAuthority`, `SourceFraming`, `compute_source_framing()` flow through `_source_framing` in observation. Part 1 passes this through.
- **AD-592:** Confabulation guard — three-tier authority-calibrated guard. Reused via `_format_memory_section()`, not duplicated.
- **BF-148:** Temporal preference for contradictory memories — included in `_confabulation_guard()` output.
- **AD-430c:** Episode storage — not affected. Storage paths (ward_room.py for ward_room_notification, api.py for direct_message) are downstream, not in the chain handlers.

## Engineering Principles

- **DRY:** One memory formatting path (`_format_memory_section()`) for both single-shot and chain. Chain handlers read `_formatted_memories`, single-shot reads `recent_memories` and formats inline. No new formatter.
- **Single Responsibility:** `cognitive_agent.py` formats memories (context preparation). `analyze.py` includes them in analysis prompt (analysis responsibility). `compose.py` includes them in response prompt (composition responsibility).
- **Open/Closed:** New analyze/compose modes automatically get memory if they read `_formatted_memories` from context. No per-mode wiring needed.
- **Defense in Depth:** Memory grounding at BOTH Analyze (decision quality) AND Compose (response quality). Even if Analyze ignores memories, Compose still has them for grounding.
- **Law of Demeter:** Chain handlers read `context.get("_formatted_memories")` — a flat string. They don't know about `_format_memory_section()`, `SourceFraming`, or anchor headers.

## Verification

1. `pytest tests/test_bf189_chain_memory_context.py -x -q`
2. `pytest tests/test_bf186_compose_standing_orders.py tests/test_bf187_bf188_dm_captain_delivery.py -x -q` (regression)
3. `pytest tests/ -x -q -o "addopts="` (full suite)
4. Grep verify: `grep -rn "_formatted_memories" src/probos/` should show exactly 3 files (cognitive_agent.py, analyze.py, compose.py)
