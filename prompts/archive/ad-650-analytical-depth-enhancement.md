# AD-650: Analytical Depth Enhancement — Build Prompt

**AD:** 650  
**Issue:** #294  
**Parent:** AD-632 (Cognitive Sub-Tasks)  
**Related:** AD-645 (composition briefs), AD-646/646b (cognitive baseline/parity), AD-649 (communication context)  
**Scope:** ~120 lines across 2 files. Zero new modules.

---

## Problem

The cognitive communication chain (QUERY → ANALYZE → COMPOSE) reaches functional parity with the one-shot path on register and tone (AD-649), but consistently underperforms on **analytical depth**. One-shot produces deeper philosophical insights, counterarguments, and meaning extraction. The chain produces broader factual coverage but shallower reasoning.

**Root cause (diagnosed through A/B testing + research):** The composition brief is an **information bottleneck**. ANALYZE performs reasoning then compresses it into 5 structured fields (`situation`, `key_evidence`, `response_should_cover`, `tone`, `sources_to_draw_on`). Conditional logic ("because X, therefore Y matters more than Z") is lost in compression. COMPOSE only sees the compressed summary, not the reasoning that produced it.

**Evidence from 7 A/B comparison tests (chain vs one-shot):**
- Chain wins on **breadth**: more crew references, callbacks to prior conversation, cumulative case-building
- One-shot wins on **depth**: counterarguments ("fresh eyes" perspective on crew reset), coined vocabulary ("cognitive load clustering"), diagnostic lens (using game behavior to read leadership styles)
- Chain wins on **intellectual honesty**: references real observations vs one-shot fabricating examples
- Bold headers regress on multi-point Ward Room responses (suppression only in `private_conversation` and DM modes)

**Research grounding (5 sources):**
1. **Chain-of-Thought (Wei et al.):** Intermediate reasoning tokens are load-bearing. Stripping reasoning and passing only conclusions degrades downstream quality. ANALYZE's brief strips the "because" relationships.
2. **DSPy (Stanford):** Structured intermediates outperform unstructured, but field descriptions are optimization targets, not fixed design. The brief's fields need enrichment.
3. **"Lost in the Middle" (Liu et al.):** LLMs attend to beginning and end of context, less to the middle. Brief positioning matters.
4. **Self-Refine (Madaan et al.):** Iterative refinement helps surface quality but cannot recover information never passed through the bottleneck. Fix the handoff first.
5. **OpenMythos / COCONUT (Recurrent-Depth Transformer):** Original input re-injection at every recurrence step prevents representation drift. COMPOSE already receives original context (confirmed), so the bottleneck is purely brief content, not context availability.

**Design principle (LLM Independence):** The one-shot path produces depth because the LLM reasons and composes simultaneously — reasoning shapes word choice in real-time. The chain must make this depth explicit and prescriptive so it transfers across LLMs. A less capable model with a rich brief should outperform a more capable model with a thin brief.

---

## What Already Exists

- `composition_brief` has 5 fields: `situation`, `key_evidence`, `response_should_cover`, `tone`, `sources_to_draw_on` (analyze.py ~L.175-189, ~L.360-377, ~L.433-444)
- DM mode has an additional `register` field inside `composition_brief` (analyze.py ~L.441-444)
- The "Include your reasoning process" instruction is embedded in the `tone` sub-field description, not a standalone field
- COMPOSE receives original context via `context.get("context", "")` as `## Content` (compose.py L.267-269) AND the brief as `## Composition Brief` (compose.py L.271-301)
- Bold-header suppression exists ONLY in `private_conversation` branch (compose.py L.93) and DM mode (compose.py L.154-156). General Ward Room branch has NO suppression.
- ANALYZE's brief is described to the LLM as "A plan for composing your response" — framing it as planning, not reasoning
- The compose user prompt has ~20 sections (compose.py L.261-445). The brief is a small fraction of what COMPOSE sees.

---

## Fix

Three parts across 2 files. No new modules, no new dependencies.

### Part A: Narrative Reasoning Field in ANALYZE (analyze.py)

**Rationale:** The structured brief fields capture "what" but lose "because X, therefore Y." Adding a narrative reasoning field preserves the conditional logic that one-shot generates spontaneously. Research (CoT, DSPy) confirms that narrative reasoning transfers more semantic depth than structured fields alone.

#### A1. Thread analysis mode — add `analytical_reasoning` to composition_brief

In `_build_thread_analysis_prompt()`, find the `composition_brief` field description (around line 175-189). After `sources_to_draw_on`, add a new sub-field:

```
    "analytical_reasoning": "Your thinking about this situation in 2-3 sentences. What does this mean beyond the surface? What's the counterargument or alternative perspective? What would a thoughtful colleague notice that a summary would miss? Write as narrative prose, not bullets."
```

**Important:** This field is narrative, not structured. The prompt must explicitly say "Write as narrative prose, not bullets."

#### A2. Situation review mode — same addition

In `_build_situation_review_prompt()`, find the `composition_brief` field description (around line 360-377). Add the same `analytical_reasoning` sub-field after `sources_to_draw_on`.

#### A3. DM comprehension mode — same addition

In `_build_dm_comprehension_prompt()`, find the `composition_brief` field description (around line 433-444). Add the same `analytical_reasoning` sub-field after `sources_to_draw_on` (which comes after the DM-specific `register` field).

#### A4. Reframe the brief description

In all three modes, change the brief introduction. Thread analysis and situation review currently say `"A plan for composing your response. Include:"` — DM comprehension says `"A plan for composing your reply. Include:"`. Change both variants to:

```
"composition_brief": "Your analytical reasoning and composition plan. Include:"
```

This reframes the brief from pure planning to reasoning + planning.

### Part B: COMPOSE Consumes Narrative Reasoning (compose.py)

**Rationale:** The narrative reasoning must be rendered in a way COMPOSE can use it — positioned for attention (recency research) and framed as analytical scaffolding, not just another data section.

#### B1. Render analytical_reasoning in the composition brief section

In `_build_user_prompt()`, find where `composition_brief` fields are rendered (around line 271-301). After the existing fields are rendered, add:

```python
# AD-650: Narrative reasoning from ANALYZE
_reasoning = brief.get("analytical_reasoning", "")
if _reasoning:
    parts.append(f"\n## Analytical Reasoning\n{_reasoning}")
```

**Position:** Place this AFTER `## Composition Brief` but BEFORE `## Prior Data`. The reasoning should be the last analytical section before environmental data, exploiting recency within the analytical block.

#### B2. Bold-header suppression for ALL Ward Room branches

In `_build_ward_room_compose_prompt()`, find the general Ward Room framing (the `else` branch of the `_comm_context == "private_conversation"` check, around line 95-118). Add to ALL branches:

```
"Prefer natural prose over markdown formatting. Use bold headers only for formal reports, not conversation."
```

Currently, bold-header suppression only exists for `private_conversation` (line 93) and DM mode (lines 154-156). The general Ward Room branch, `bridge_briefing`, `casual_social`, and `ship_wide` all lack this guidance.

#### B3. Depth instruction in compose system prompt

In `_build_ward_room_compose_prompt()`, add to the base Ward Room framing (after "Show your reasoning, not just conclusions"):

```
"If there's another way to see this, mention it briefly. Don't just summarize — interpret."
```

This mirrors what one-shot does spontaneously (counterarguments, meaning extraction) and makes it prescriptive per the LLM Independence Principle.

Add the same instruction to `_build_dm_compose_prompt()` and `_build_proactive_compose_prompt()`.

---

## Verification Checklist

Before marking complete, verify:

1. [ ] `analytical_reasoning` field is present in all 3 ANALYZE modes (thread_analysis, situation_review, dm_comprehension)
2. [ ] Brief description says "analytical reasoning and composition plan" not "plan for composing"
3. [ ] `analytical_reasoning` narrative prose instruction explicitly says "not bullets"
4. [ ] COMPOSE renders `## Analytical Reasoning` section after brief, before Prior Data
5. [ ] `analytical_reasoning` is rendered only when non-empty (graceful fallback for ANALYZE outputs that predate this change)
6. [ ] Bold-header suppression added to ALL Ward Room branches (general, bridge_briefing, casual_social, ship_wide)
7. [ ] "Don't just summarize — interpret" instruction in ward_room, DM, and proactive compose prompts
8. [ ] All existing tests pass (`pytest tests/ -x -q`)
9. [ ] No imports changed, no new modules, no new dependencies

---

## Tests (tests/test_ad650_analytical_depth.py)

Write the following tests:

```python
"""AD-650: Analytical Depth Enhancement tests."""
import pytest
from probos.cognitive.sub_tasks.analyze import (
    _build_thread_analysis_prompt,
    _build_situation_review_prompt,
    _build_dm_comprehension_prompt,
)
from probos.cognitive.sub_tasks.compose import (
    _build_ward_room_compose_prompt,
    _build_dm_compose_prompt,
    _build_proactive_compose_prompt,
    _build_user_prompt,
)
from probos.cognitive.sub_task import SubTaskResult, SubTaskType

# --- Part A: ANALYZE produces analytical_reasoning ---

class TestAnalyzeNarrativeReasoning:
    """Verify ANALYZE prompts include analytical_reasoning field."""

    def test_thread_analysis_prompt_includes_analytical_reasoning(self):
        """Thread analysis composition_brief prompt mentions analytical_reasoning."""
        ctx = {"mode": "thread_analysis", "context": "test", "channel_name": "engineering"}
        prompt = _build_thread_analysis_prompt(ctx, [], "TestAgent", "engineering")
        assert "analytical_reasoning" in prompt
        assert "narrative prose" in prompt.lower() or "not bullets" in prompt.lower()

    def test_situation_review_prompt_includes_analytical_reasoning(self):
        """Situation review composition_brief prompt mentions analytical_reasoning."""
        ctx = {"mode": "situation_review", "context": "test"}
        prompt = _build_situation_review_prompt(ctx, [], "TestAgent", "engineering")
        assert "analytical_reasoning" in prompt
        assert "narrative prose" in prompt.lower() or "not bullets" in prompt.lower()

    def test_dm_comprehension_prompt_includes_analytical_reasoning(self):
        """DM comprehension composition_brief prompt mentions analytical_reasoning."""
        ctx = {"mode": "dm_comprehension", "context": "test", "channel_name": "dm-captain"}
        prompt = _build_dm_comprehension_prompt(ctx, [], "TestAgent", "medical")
        assert "analytical_reasoning" in prompt
        assert "narrative prose" in prompt.lower() or "not bullets" in prompt.lower()

    def test_brief_description_reframed(self):
        """Composition brief is described as 'analytical reasoning and composition plan'."""
        ctx = {"mode": "thread_analysis", "context": "test", "channel_name": "engineering"}
        prompt = _build_thread_analysis_prompt(ctx, [], "TestAgent", "engineering")
        assert "analytical reasoning" in prompt.lower()

# --- Part B: COMPOSE renders and uses analytical_reasoning ---

class TestComposeAnalyticalReasoning:
    """Verify COMPOSE renders analytical_reasoning and has depth instructions."""

    def test_compose_renders_analytical_reasoning_section(self):
        """COMPOSE user prompt includes Analytical Reasoning section when present in brief."""
        ctx = {
            "context": "test thread content",
            "mode": "ward_room_response",
            "channel_name": "engineering",
        }
        prior_analysis = {
            "composition_brief": {
                "situation": "Test situation",
                "key_evidence": "Test evidence",
                "response_should_cover": "Test coverage",
                "tone": "professional",
                "sources_to_draw_on": "episodic memory",
                "analytical_reasoning": "This reveals a deeper pattern of collaborative drift."
            },
            "contribution_assessment": "RESPOND"
        }
        prior_results = [SubTaskResult(
            sub_task_type=SubTaskType.ANALYZE,
            name="analyze-test",
            success=True,
            result=prior_analysis
        )]
        prompt = _build_user_prompt(ctx, prior_results)
        assert "Analytical Reasoning" in prompt
        assert "collaborative drift" in prompt

    def test_compose_graceful_without_analytical_reasoning(self):
        """COMPOSE handles briefs without analytical_reasoning (backward compat)."""
        ctx = {
            "context": "test thread content",
            "mode": "ward_room_response",
            "channel_name": "engineering",
        }
        prior_analysis = {
            "composition_brief": {
                "situation": "Test situation",
                "key_evidence": "Test evidence",
                "response_should_cover": "Test coverage",
                "tone": "professional",
                "sources_to_draw_on": "episodic memory"
                # No analytical_reasoning field
            },
            "contribution_assessment": "RESPOND"
        }
        prior_results = [SubTaskResult(
            sub_task_type=SubTaskType.ANALYZE,
            name="analyze-test",
            success=True,
            result=prior_analysis
        )]
        prompt = _build_user_prompt(ctx, prior_results)
        # Should not crash, should not show empty section
        assert "## Content" in prompt

    def test_bold_header_suppression_all_ward_room_branches(self):
        """Bold-header guidance present in ALL Ward Room branches, not just private."""
        for comm_ctx in ["department_discussion", "bridge_briefing", "casual_social", "ship_wide"]:
            ctx = {
                "context": "test",
                "mode": "ward_room_response",
                "channel_name": "engineering",
                "_communication_context": comm_ctx,
            }
            system, _ = _build_ward_room_compose_prompt(ctx, [], "TestAgent", "engineering")
            assert "bold" in system.lower() or "markdown" in system.lower(), \
                f"No bold-header guidance in {comm_ctx} branch"

    def test_depth_instruction_in_ward_room_compose(self):
        """Ward Room compose prompt includes depth instruction."""
        ctx = {
            "context": "test",
            "mode": "ward_room_response",
            "channel_name": "engineering",
            "_communication_context": "department_discussion",
        }
        system, _ = _build_ward_room_compose_prompt(ctx, [], "TestAgent", "engineering")
        assert "interpret" in system.lower() or "another way to see" in system.lower()

    def test_depth_instruction_in_dm_compose(self):
        """DM compose prompt includes depth instruction."""
        ctx = {
            "context": "test",
            "mode": "dm_response",
            "_dm_recipient": "Captain",
            "_communication_context": "private_conversation",
        }
        system, _ = _build_dm_compose_prompt(ctx, [], "TestAgent", "engineering")
        assert "interpret" in system.lower() or "another way to see" in system.lower()

    def test_depth_instruction_in_proactive_compose(self):
        """Proactive compose prompt includes depth instruction."""
        ctx = {
            "context": "test",
            "mode": "proactive_observation",
        }
        system, _ = _build_proactive_compose_prompt(ctx, [], "TestAgent", "engineering")
        assert "interpret" in system.lower() or "another way to see" in system.lower()

# --- Regression ---

class TestRegressionAD650:
    """Ensure AD-650 doesn't break existing behavior."""

    def test_private_conversation_still_has_anti_format(self):
        """private_conversation branch retains its stronger anti-format instruction."""
        ctx = {
            "context": "test",
            "mode": "ward_room_response",
            "channel_name": "dm-captain",
            "_communication_context": "private_conversation",
        }
        system, _ = _build_ward_room_compose_prompt(ctx, [], "TestAgent", "engineering")
        assert "Do NOT use structured formats" in system

    def test_dm_mode_still_has_anti_format(self):
        """DM compose mode retains its anti-format instruction."""
        ctx = {
            "context": "test",
            "mode": "dm_response",
            "_dm_recipient": "Captain",
            "_communication_context": "private_conversation",
        }
        system, _ = _build_dm_compose_prompt(ctx, [], "TestAgent", "engineering")
        assert "Do NOT use any structured output" in system
```

Test count: 12 tests across 3 classes.

---

## What This Does NOT Do (Out of Scope)

- **Does not change EVALUATE/REFLECT behavior.** Quality enrichment via EVALUATE is a future enhancement (AD-645 Phase 4).
- **Does not add few-shot voice exemplars.** Research supports this but it requires curating per-agent examples — separate effort.
- **Does not change the compose user prompt section ordering.** Brief position (second section) is adequate. Full prompt restructuring is a larger refactor.
- **Does not change QUERY step.** Data gathering is not the bottleneck.
- **Does not add a pre-compose refinement loop.** Self-Refine pattern is valuable but adds latency and complexity — separate AD if warranted after depth results are validated.

---

## Engineering Principles Compliance

- **SOLID (S):** ANALYZE remains responsible for analysis, COMPOSE for composition. No new responsibilities added — existing responsibilities enriched.
- **SOLID (O):** New field added to existing schema (open for extension). No existing fields modified or removed.
- **DRY:** `analytical_reasoning` field description is identical across 3 modes — could be extracted to a constant, but keeping inline matches the existing pattern for `composition_brief` fields.
- **Fail Fast:** `brief.get("analytical_reasoning", "")` — graceful empty-string default for backward compatibility with pre-AD-650 ANALYZE outputs.
- **LLM Independence:** Depth instructions are prescriptive ("What's the counterargument?", "Don't just summarize — interpret") not dependent on emergent LLM capability.
- **Law of Demeter:** No new cross-object reaching. Uses existing `prior_results` → `composition_brief` access pattern.
