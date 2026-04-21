# AD-646: Universal Cognitive Baseline — Research Document

**Date:** 2026-04-19  
**Author:** Architect  
**Status:** Research complete, ready for AD  
**Depends on:** AD-644 (Situation Awareness), AD-645 (Artifact-Mediated Chain)  
**Related:** AD-641g (NATS Pipeline), AD-632 (Cognitive Chain Architecture)

---

## Problem Statement

When a ProbOS agent processes a Ward Room notification through the cognitive chain, it produces responses like:

> "I've been conducting routine wellness checks through private consultations across all departments."

When the *same agent* responds to the *same question* ("How is the crew doing?") through the one-shot DM path, it produces:

> "157/118/85 unread messages across three agents... cognitive load at 40-75% of crisis threshold... Reed showing potential fixation pattern with 7 iterations on architecture topic."

The chain path — which was designed to produce *better* responses through multi-step reasoning — produces *worse* responses than the one-shot path. The composition brief tuning (AD-645) improved proactive duty cycles but not Ward Room responses.

### Root Cause

The chain pipeline has a **data starvation problem**, not a reasoning problem.

The one-shot `_build_user_message()` path (lines 3407-3511 of cognitive_agent.py) injects the agent's full cognitive state directly into the LLM prompt:

| Data Source | One-Shot DM | One-Shot Ward Room | Chain (proactive_think) | Chain (ward_room_notification) |
|---|---|---|---|---|
| Temporal awareness | ✅ | ✅ | ✅ | ❌ |
| Working memory | ✅ | ✅ | ✅ | ❌ |
| Cognitive zone | ✅ | ✅ | ✅ | ❌ |
| Episodic memories | ✅ | ✅ | ✅ | ❌ |
| Source attribution | ✅ | ✅ | ✅ | ❌ |
| Introspective telemetry | ✅ (conditional) | ✅ (conditional) | ✅ | ❌ |
| Self-monitoring | — | — | ✅ | ❌ |
| Ontology/orientation | — | — | ✅ | ❌ |
| Confabulation guard | — | — | ✅ | ❌ |
| Thread metadata | — | ✅ | — | ✅ |
| Agent credibility | — | — | — | ✅ |
| Unread counts | — | — | ✅ | ❌ |
| Infrastructure status | — | — | ✅ | ❌ |
| Alerts/events | — | — | ✅ | ❌ |

The ward_room chain's QUERY step only fetches `thread_metadata` and `credibility`. The agent enters ANALYZE knowing the thread content but *nothing about itself* — no working memory, no temporal awareness, no episodic recall. It cannot cite specific findings because the findings aren't in the prompt.

### Design Flaw: Intent-Specific Context Assembly

The current architecture treats context assembly as an intent-specific concern:

```
proactive_think → _gather_context() → context_parts → _build_cognitive_state() → observation
ward_room_notification → (nothing) → observation with thread_metadata only
direct_message → _build_user_message() → inline context injection
```

Each intent path independently decides what context to include. AD-644 Phase 2 added innate faculties to the proactive path by building `_build_cognitive_state()`, but this method depends on `context_parts` — a dict populated by `proactive.py`'s `_gather_context()` function. Ward Room notifications don't pass through proactive.py, so `context_parts` is empty, and most innate faculties return nothing.

The result: every new intent type that becomes chain-eligible will need its own AD-644-style migration. The fix scales linearly with intent count instead of being applied once.

---

## Analysis

### What's Universal vs Intent-Specific

Reviewing the 23-item AD-644 parity checklist and the one-shot path's `_build_user_message()`, the data sources divide cleanly:

**Universal (agent always knows this, regardless of intent):**

| # | Faculty | Source | Current Location |
|---|---------|--------|-----------------|
| 1 | Temporal awareness | `_build_temporal_context()` | Agent method (self-contained) |
| 2 | Working memory | `_working_memory.render_context()` | Agent attribute (self-contained) |
| 3 | Cognitive zone | `_working_memory.get_cognitive_zone()` | Agent attribute (self-contained) |
| 4 | Episodic memories | `recent_memories` in observation | Populated by `perceive()` in all paths |
| 5 | Source attribution | `_source_attribution` in observation | Populated by `perceive()` in all paths |
| 6 | Trust/agency/rank | `_agent_metrics` | Agent attributes (self-contained) |
| 7 | Ontology identity | `_ontology_context` | Agent attribute via `_compose_dm_instructions()` |
| 8 | Confabulation guard | Source framing from memory classification | Populated by `perceive()` |

Items 1-3 and 6-7 are *agent-intrinsic* — they read from the agent's own state, not from external services. They require zero async calls and zero `context_parts` data. The only reason they don't work for ward_room is that `_build_cognitive_state()` is called with an empty `context_parts` dict.

Items 4-5 and 8 are already populated by `perceive()` for all intent types — they flow through `observation` naturally.

**Intent-specific (depends on what triggered the cycle):**

| # | Percept | Source | When Relevant |
|---|---------|--------|--------------|
| 1 | Thread metadata | WardRoomService | ward_room_notification |
| 2 | Agent credibility | WardRoomService | ward_room_notification |
| 3 | Unread counts | WardRoomService | proactive_think |
| 4 | Infrastructure status | VitalsMonitor | proactive_think |
| 5 | Recent alerts | AlertConditionService | proactive_think |
| 6 | Recent events | EventBus | proactive_think |
| 7 | Subordinate stats | TrustNetwork | proactive_think (chiefs only) |
| 8 | Cold-start note | Runtime state | proactive_think |
| 9 | Active game | RecreationService | proactive_think |

**Dependent on external services (needs `context_parts` from proactive loop):**

| # | Faculty | Source | Dependency |
|---|---------|--------|-----------|
| 1 | Self-monitoring | `context_parts["self_monitoring"]` | proactive.py gathers this |
| 2 | Notebook index/content | `context_parts["self_monitoring"]["notebook_index"]` | proactive.py gathers this |
| 3 | Introspective telemetry | `context_parts["introspective_telemetry"]` | proactive.py gathers this |
| 4 | Orientation supplement | `context_parts["orientation"]` | proactive.py gathers this |

These four are the tricky ones. They're conceptually universal (an agent should always know its notebooks, its telemetry, its orientation) but their data is currently gathered by proactive.py, not by the agent itself.

### The `context_parts` Problem

`_build_cognitive_state()` (line 2977) takes `context_parts: dict` as input and reads:
- `context_parts.get("self_monitoring")` → self-monitoring data
- `context_parts.get("introspective_telemetry")` → telemetry
- `context_parts.get("orientation")` → orientation supplement

For proactive_think, `context_parts` is populated by proactive.py's `_gather_context()` which calls VitalsMonitor, AlertConditionService, WardRoomService, etc. For ward_room_notification, `context_parts` is empty because the Ward Room router dispatches directly to the agent via IntentBus without going through proactive.py.

The fix is NOT to route Ward Room notifications through proactive.py — that would conflate reactive responses with proactive cycles. The fix is to separate "gathering the agent's self-knowledge" from "gathering environmental perception."

### Endsley SA Model Alignment

This maps to Endsley's three SA levels:

- **Level 1 (Perception):** Environmental scan — intent-specific. Proactive cycle scans broadly; Ward Room path scans a specific thread.
- **Level 0 (Proprioception):** Self-knowledge — universal. Agent knows its own state regardless of what triggered the cycle. This is what's missing.

AD-644 correctly identified four categories but implemented them tied to the proactive path rather than as a universal baseline.

---

## Proposed Design

### Principle: Base + Extension

```
┌─────────────────────────────────────────┐
│  Universal Cognitive Baseline           │  ← Runs for ALL chain executions
│  (temporal, working memory, episodic,   │
│   source attribution, ontology,         │
│   trust/rank, cognitive zone)           │
├─────────────────────────────────────────┤
│  Intent Extensions                      │  ← Registered per intent type
│  proactive_think: SA sweep, self-mon    │
│  ward_room_notification: thread context │
│  direct_message: session history        │
│  (future intents: their own extensions) │
└─────────────────────────────────────────┘
```

### Change 1: Extract Universal Baseline from `_build_cognitive_state()`

Split `_build_cognitive_state()` into two methods:

**`_build_cognitive_baseline()`** — agent-intrinsic, zero dependencies on `context_parts`:
- Temporal awareness (`_build_temporal_context()` — already self-contained)
- Working memory (`_working_memory.render_context()` — already self-contained)
- Cognitive zone (from working memory — already self-contained)
- Trust/agency/rank metrics (from agent attributes — already self-contained)
- Ontology identity (from `_compose_dm_instructions()` — already self-contained)
- Orientation supplement (can be made self-contained — agent knows its own birth time)

**`_build_cognitive_extensions(context_parts)`** — depends on externally-gathered data:
- Self-monitoring (cognitive zone from VitalsMonitor, recent posts, self-similarity, cooldowns)
- Notebook index/content
- Introspective telemetry
- Confabulation guard details

### Change 2: Call Baseline Before Any Chain Execution

In `_execute_chain_with_intent_routing()`, call `_build_cognitive_baseline()` unconditionally (before intent-specific logic). Call `_build_cognitive_extensions(context_parts)` only when `context_parts` is non-empty (proactive path).

Current flow (line 1867-1875):
```python
# AD-644 Phase 2: Everything in one call, depends on context_parts
_cognitive_state = self._build_cognitive_state(_context_parts)
observation.update(_cognitive_state)

# AD-644 Phase 3: Environmental perception (also depends on context_parts)
_situation = self._build_situation_awareness(_context_parts)
observation.update(_situation)
```

Proposed flow:
```python
# Universal baseline — always runs, no external dependencies
_baseline = self._build_cognitive_baseline()
observation.update(_baseline)

# Intent-specific extensions — only when context_parts available
if _context_parts:
    _extensions = self._build_cognitive_extensions(_context_parts)
    observation.update(_extensions)
    _situation = self._build_situation_awareness(_context_parts)
    observation.update(_situation)
```

### Change 3: Update Thread Analysis Prompt to Consume Baseline Keys

`_build_thread_analysis_prompt()` currently reads: `_agent_type`, `_agent_rank`, `_skill_profile`, `context`, `_formatted_memories`, `_eligible_triggers`.

Add consumption of baseline keys: `_temporal_context`, `_working_memory_context`, `_ontology_context`, `_agent_metrics`. These render into an "Agent State" section in the thread analysis prompt, giving ANALYZE the self-knowledge it needs to cite findings.

### Change 4: Update Ward Room Compose Prompt Similarly

`_build_proactive_compose_prompt()` already consumes baseline keys (AD-645 Phase 2). The ward_room compose prompt (`_build_ward_room_compose_prompt()` or equivalent) needs the same treatment — add duty framing, source attribution, confabulation guard from baseline keys.

---

## Self-Monitoring Gap

Self-monitoring (cognitive zone from VitalsMonitor, recent posts, self-similarity, cooldowns, notebook index) is the biggest remaining gap after the baseline split. This data is gathered by proactive.py because VitalsMonitor runs on a cycle. For the ward_room path, the agent won't have fresh self-monitoring data.

Three approaches:

1. **Cache last self-monitoring snapshot on the agent.** Proactive cycles already run frequently. Cache the self-monitoring dict on the agent instance. Ward Room chains read the cached version. Stale but available.

2. **Lightweight self-monitoring query.** Add a QUERY operation (`self_monitoring`) that fetches cognitive zone + recent posts from VitalsMonitor on demand. More expensive per Ward Room chain, but fresh data.

3. **Defer to working memory.** Working memory already has cognitive zone and recent actions. Self-monitoring data that's more specific (self-similarity, cooldowns, notebook index) can wait for the next proactive cycle. The baseline's working memory context covers most of it.

**Recommendation:** Option 3 for now. Working memory's `render_context()` already includes cognitive zone, recent actions, recent reasoning, and recent conversations. The self-monitoring specifics (self-similarity scores, cooldown history) are self-regulation tools that matter more in the proactive "should I post?" decision than in the reactive "what should I say in this thread?" decision. If we later find agents repeating in Ward Room threads, Option 1 (cache) is a one-line addition.

---

## Impact Assessment

### Token Budget

The universal baseline adds approximately:
- Temporal awareness: ~50 tokens
- Working memory context: ~300-500 tokens (budget-capped at 1500)
- Agent metrics: ~30 tokens
- Ontology context: ~100 tokens

Total: ~500-700 tokens added to ward_room chain's ANALYZE prompt. Well within the 4K prompt budget for Sonnet.

### Performance

Zero additional async calls for the baseline — all data is agent-intrinsic. No new service calls. The working memory read is in-memory (deque traversal). Temporal context is a string format. Negligible latency impact.

### NATS Alignment

When AD-641g decouples the pipeline via NATS, the universal baseline becomes the standard message envelope:

```
Subject: chain.{agent_id}.analyze
Payload: {
    baseline: { temporal, working_memory, ontology, metrics },
    intent_context: { thread_metadata, credibility },  // varies by intent
    prior_results: { query_results }
}
```

The base/extension split maps directly to NATS message structure. Building it now pre-shapes the NATS schema.

### Backward Compatibility

- `_build_cognitive_state()` continues to work — it just delegates to `_build_cognitive_baseline()` + `_build_cognitive_extensions()` internally.
- `_build_situation_awareness()` unchanged — remains intent-specific (proactive only until NATS).
- No changes to chain definitions, SubTaskSpec, or the executor.
- Thread analysis and ward_room compose prompts gain optional sections — absent keys simply produce empty sections.

---

## Comparison to Alternatives

| Approach | Scope | Repeats per intent? | NATS-ready? |
|----------|-------|---------------------|-------------|
| **A. Add query keys per intent** (Option 1 from earlier) | Narrow — just adds unread_counts | Yes | No |
| **B. Copy context building per intent** (AD-644 approach) | Per-intent — each prompt builder adds what it needs | Yes | No |
| **C. Universal baseline + extensions** (this proposal) | Once — baseline is intent-agnostic | No | Yes |
| **D. Full proactive-style gathering for all intents** | Overkill — SA sweep for Ward Room | No | Partially |

Option C is the clear winner: apply once, works for all current and future intents, aligns with NATS message structure.

---

## Implementation Phases

1. **Split `_build_cognitive_state()`** — Extract baseline (self-contained) from extensions (context_parts-dependent). Call baseline unconditionally. ~50 lines changed in cognitive_agent.py.

2. **Update thread analysis prompt** — Add "Agent State" section consuming baseline keys. ~20 lines in analyze.py.

3. **Update ward_room compose prompt** — Add baseline key consumption (duty framing, source attribution). ~20 lines in compose.py.

4. **Verify proactive path unchanged** — Ensure proactive_think still gets full context (baseline + extensions + SA). Regression tests.

5. **Future: Self-monitoring cache** — If ward_room quality needs self-monitoring data, cache last snapshot on agent instance.

Total scope: ~100 lines across 3 files. Zero new modules. Zero new infrastructure.

---

## References

- Endsley, M. R. (1995). "Toward a Theory of Situation Awareness in Dynamic Systems." *Human Factors*, 37(1), 32-64.
- AD-644: Agent Situation Awareness Architecture (4-category model)
- AD-645: Artifact-Mediated Cognitive Chain (composition briefs)
- AD-641g: Asynchronous Cognitive Pipeline via NATS
- AD-632: Cognitive Chain Architecture
- AD-573: Unified Agent Working Memory
- AD-502: Temporal Context Awareness
- AD-504: Agent Self-Monitoring
