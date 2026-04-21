# AD-645: Artifact-Mediated Cognitive Chain

## Research Document

**Date:** 2026-04-18
**Author:** Architect (Sean Galliher)
**Status:** Research Complete
**Parent:** AD-632 (Cognitive Chain Architecture)
**Related:** AD-644 (Situation Awareness), AD-641g (NATS Pipeline), AD-639 (Chain Personality Tuning), AD-573 (Working Memory)

---

## 1. Problem Statement

The cognitive chain (QUERY → ANALYZE → COMPOSE → EVALUATE → REFLECT) produces measurably flatter, less confident responses than the one-shot `_build_user_message()` path — even after AD-644 achieved full context parity (23/23 items).

**Evidence (2026-04-18):** Same agent (Ezri/Counselor), same question ("How is the crew doing?"), two code paths:

- **One-shot (profile card DM):** Rich, confident assessment referencing specific observations — fixation patterns across 4 departments, message backlog disparities (100+ vs zero), trust stability, systemic vs individual framing. Warm, proactive, clinically grounded.
- **Chain (Ward Room DM):** Hedging, says "I need access to current trust scores" despite having them in context, offers to pull data rather than using what's available, generic rather than specific.

The chain path has the data (AD-644 confirmed) but produces output as if it doesn't. The problem is not missing context — it's **lossy compression at the ANALYZE → COMPOSE handoff**.

---

## 2. Root Cause Analysis

### Current Data Flow

```
QUERY → observation dict (trust, unread, etc.)
  ↓
ANALYZE → reads full context + observation keys → outputs JSON:
  {
    "intended_actions": ["ward_room_reply"],
    "priority_topics": [...],
    "department_relevance": "HIGH"
  }
  ↓
COMPOSE → reads:
  1. ANALYZE result as "## Analysis\n\n{json.dumps(analysis)}"  [~200 tokens]
  2. Original context string                                     [often empty]
  3. _* observation keys (subset: confab, source, comm, temporal, ontology)
  4. _formatted_memories
  5. First QUERY result as "## Prior Data\n\n- {k}: {v}"
  → outputs response text
```

### Where Information Dies

1. **ANALYZE compresses, doesn't brief.** ANALYZE outputs a routing slip (`intended_actions`, `priority_topics`, `department_relevance`) — structured data for programmatic dispatch. It does NOT output a composition plan. The rich situational understanding ANALYZE developed during its LLM call is discarded — only the structured fields survive.

2. **COMPOSE receives a summary, not source material.** The `## Analysis` section gives COMPOSE a JSON dict, not a narrative brief. "department_relevance: HIGH" tells COMPOSE nothing about *why* it's high or *what specific observations* support that assessment.

3. **Environmental context missing from COMPOSE.** Phase 3 SA keys (`_ward_room_activity`, `_recent_alerts`, `_recent_events`, `_infrastructure_status`, `_subordinate_stats`, `_cold_start_note`, `_active_game`) flow to ANALYZE but NOT to COMPOSE. COMPOSE cannot reference specific Ward Room discussions, alert details, or subordinate activity because it never sees them.

4. **One-shot doesn't have this problem.** `_build_user_message()` gives the LLM everything in a single prompt. The LLM simultaneously analyzes and composes, drawing on any detail from any context injection. No handoff, no compression, no information loss.

### The Architect/Builder Analogy

The current chain is like the architect saying "write a build prompt for phase 4" with no research doc, no file references, no design decisions. The builder produces something generic.

The architect/builder workflow that *works*:
1. Architect researches deeply, identifies specific code locations, patterns, design decisions
2. Architect writes a detailed build prompt — the **plan**
3. Builder reads the plan AND has access to the codebase — focused guidance + full context
4. Result: high-quality, targeted implementation

The chain should work the same way:
1. ANALYZE assesses the situation, identifies what matters, forms a composition plan
2. COMPOSE reads the plan AND the raw context — focused guidance + full material
3. Result: high-quality, targeted response that's better than one-shot because it has both assessment and source material

---

## 3. Proposed Design: Composition Briefs

### Core Concept

Replace ANALYZE's routing-slip output with a **composition brief** — a structured markdown artifact that serves as both a plan for COMPOSE and a metacognitive record for the agent.

### ANALYZE Output: The Composition Brief

Current ANALYZE output (situation_review mode):
```json
{
  "active_threads": [...],
  "pending_actions": [...],
  "priority_topics": [...],
  "department_relevance": "HIGH",
  "intended_actions": ["ward_room_reply"]
}
```

Proposed ANALYZE output:
```json
{
  "intended_actions": ["ward_room_reply"],
  "composition_brief": {
    "situation": "Captain asked about crew wellness in DM channel.",
    "key_evidence": [
      "Tracked fixation patterns across Engineering, Science, Medical, and Bridge departments",
      "Message backlogs show imbalance: some crew 100+ unread, others zero",
      "Trust networks holding steady, no cognitive health alerts triggered",
      "Recurring communication cycle pattern observed ship-wide over past day"
    ],
    "response_should_cover": [
      "Overall crew status assessment",
      "Specific concerns observed (fixation pattern, message imbalance)",
      "Systemic vs individual framing — this is ship-wide, not one agent",
      "Offer to investigate further if Captain wants details"
    ],
    "tone": "Direct DM with Captain. Clinical but warm. Proactive assessment, not defensive hedging.",
    "sources_to_draw_on": "Episodic memories of recent monitoring, Ward Room observations, subordinate activity stats"
  }
}
```

The `intended_actions` field survives for programmatic routing (AD-643a skill activation). The `composition_brief` is the new artifact — the plan that COMPOSE reads.

### COMPOSE Receives: Brief + Raw Context

COMPOSE's user prompt becomes:

```
## Composition Brief (from your analysis)

**Situation:** Captain asked about crew wellness in DM channel.

**Key Evidence:**
- Tracked fixation patterns across Engineering, Science, Medical, and Bridge departments
- Message backlogs show imbalance: some crew 100+ unread, others zero
- Trust networks holding steady, no cognitive health alerts triggered
- Recurring communication cycle pattern observed ship-wide over past day

**Your response should cover:**
- Overall crew status assessment
- Specific concerns observed (fixation pattern, message imbalance)
- Systemic vs individual framing — this is ship-wide, not one agent
- Offer to investigate further if Captain wants details

**Tone:** Direct DM with Captain. Clinical but warm. Proactive assessment, not defensive hedging.

**Sources to draw on:** Episodic memories of recent monitoring, Ward Room observations, subordinate activity stats

## Your Context
[Ward Room activity, alerts, events, subordinate stats, episodic memories — the raw material]

## Your Identity
[Innate faculties — temporal, ontology, source attribution, confabulation guard, comm proficiency]
```

COMPOSE now has the focused lens (what to write about, what tone, what evidence matters) AND the raw material to draw specific details from. This is the chain being *better* than one-shot — directed attention with full access.

### Environmental Context in COMPOSE

Phase 3 SA keys that currently flow only to ANALYZE must also flow to COMPOSE:

| Key | Currently | Proposed |
|-----|-----------|----------|
| `_ward_room_activity` | ANALYZE only | ANALYZE + COMPOSE |
| `_recent_alerts` | ANALYZE only | ANALYZE + COMPOSE |
| `_recent_events` | ANALYZE only | ANALYZE + COMPOSE |
| `_infrastructure_status` | ANALYZE only | ANALYZE + COMPOSE |
| `_subordinate_stats` | ANALYZE only | ANALYZE + COMPOSE |
| `_cold_start_note` | ANALYZE only | ANALYZE + COMPOSE |
| `_active_game` | ANALYZE only | ANALYZE + COMPOSE |

These are rendered in COMPOSE's `## Your Context` section, giving it the same environmental awareness ANALYZE had.

---

## 4. Artifact Value Beyond Composition

The composition brief is not throwaway — it's a **cognitive artifact** with multiple downstream uses.

### 4.1 Metacognitive Memory — "What Was I Thinking?"

Current episodic memory records WHAT happened: "I posted about crew wellness in DM."
Composition briefs record HOW the agent reasoned: "I identified fixation patterns, prioritized systemic over individual framing, chose clinical-but-warm tone."

This is **metacognitive working memory** — the ability to introspect on your own reasoning process. Extends AD-573 (Working Memory) from "what happened recently" to "how I processed what happened."

**Implementation:** After REFLECT completes, the composition brief is stored as a WorkingMemoryEntry with `category="reasoning"`. The agent can access it via `_working_memory_context` on subsequent cycles. When asked "Why did you say that?", the agent has the answer.

**Privacy boundary (Minority Report Principle):** Composition briefs are the agent's private cognitive workspace. The Counselor does NOT have access to other agents' briefs. If an agent wants to discuss their reasoning with Echo, they do so voluntarily — the same way a person might tell their therapist "I keep focusing on the same concern." Self-awareness, not surveillance.

### 4.2 Dream Consolidation — Reasoning Patterns

Dream consolidation currently extracts patterns from episodic memory (outcomes). With composition briefs in working memory, dreams can extract patterns from **reasoning processes**:

- "You consistently identify systemic issues before individual ones — that's your analytical signature"
- "Your tone calibration adapts well to authority level (Captain vs peer)"
- "Your evidence selection tends to over-index on quantitative metrics vs qualitative observations"

This is the agent developing self-knowledge about HOW they think, not just what they've done.

### 4.3 Reinforcement Signal

EVALUATE already scores the response and provides criteria-level feedback (novelty, relevance, grounding, etc.). With the composition brief available, EVALUATE can assess **plan-to-output alignment**:

- Did COMPOSE use the evidence ANALYZE identified?
- Did the response cover what the brief said it should?
- Did the tone match the brief's guidance?

Over time, (brief, response, score) triples accumulate. Agents learn which planning approaches produce high-scoring output. This is natural reinforcement without explicit reward engineering.

### 4.4 Cognitive Forensics

When output quality degrades, the composition brief enables root-cause diagnosis:

- **Perception error:** ANALYZE's brief missed key evidence (brief was wrong)
- **Execution error:** COMPOSE ignored a good brief (composition deviated)
- **Evaluation error:** EVALUATE scored a bad response well (quality gate failed)

Without briefs, you can only observe that the output was bad. With briefs, you can trace *where in the cognitive pipeline* the failure occurred.

### 4.5 Self-Monitoring Enhancement (AD-504)

Current self-monitoring checks "am I repeating myself?" (output patterns). With composition briefs, self-monitoring can check "am I reasoning the same way about different problems?" — a deeper form of cognitive health monitoring.

An agent whose briefs show narrowing focus (fewer evidence types, same framing, same tone) over multiple cycles may be entering a fixation pattern — detectable before it manifests in output.

---

## 5. NATS Alignment (AD-641g)

The composition brief is a natural **NATS message payload**. When AD-641g decouples the chain via NATS subjects:

```
chain.{agent_id}.query.complete     → query results
chain.{agent_id}.analyze.complete   → composition brief (the artifact)
chain.{agent_id}.compose.complete   → composed response
chain.{agent_id}.evaluate.complete  → evaluation score + criteria
chain.{agent_id}.reflect.complete   → final output + reflection
```

The composition brief on `chain.{agent_id}.analyze.complete` is the message that COMPOSE subscribes to. Other consumers can also subscribe:

- **Trigger detection** (AD-643b) subscribes to `analyze.complete` to check `intended_actions`
- **Metrics collection** subscribes to all `*.complete` subjects for pipeline telemetry
- **Counselor** does NOT subscribe (Minority Report Principle) — agents self-report

The artifacts ARE the messages. No separate artifact storage needed — NATS provides the transport, and working memory provides persistence for the agent's own briefs.

### Build Without NATS?

**Yes.** The composition brief is an ANALYZE output format change + COMPOSE input rendering change. It works within the current synchronous chain — `prior_results` already passes ANALYZE's result dict to COMPOSE. The brief is just a richer dict.

NATS changes the transport (function calls → message subjects) but not the artifact format. Building the brief now means:
1. Immediate quality improvement in chain-path responses
2. Natural migration path when NATS arrives — the brief format IS the message schema
3. No throwaway work — everything built now survives the NATS transition

The reverse (build NATS first, then briefs) would mean:
1. NATS with the current thin routing-slip output — same quality problem, different transport
2. Then redesign the message format — two changes instead of one
3. Delayed quality improvement for no architectural benefit

**Recommendation:** Build the composition brief now. It's the higher-value change and it pre-shapes the NATS message format.

---

## 6. Implementation Phases

### Phase 1 — Composition Brief (ANALYZE output enrichment)

Modify ANALYZE's `situation_review` prompt to request a `composition_brief` object alongside `intended_actions`. Update the JSON schema in the ANALYZE prompt. Parse and validate the brief from LLM output.

**Scope:** `analyze.py` — prompt template + response parsing
**Risk:** Low — additive change to ANALYZE output, backward compatible (brief is optional)

### Phase 2 — COMPOSE Context Enrichment

1. Render the composition brief in COMPOSE's user prompt as a readable markdown section
2. Pass Phase 3 SA keys (`_ward_room_activity`, etc.) through to COMPOSE's prompt builder
3. Restructure COMPOSE's user prompt: Brief → Raw Context → Identity

**Scope:** `compose.py` — user prompt builder
**Risk:** Medium — changes COMPOSE's prompt structure, may affect all chain-path responses. A/B testing recommended.

### Phase 3 — Metacognitive Storage

After REFLECT completes, store the composition brief as a `WorkingMemoryEntry(category="reasoning")`. Agent can access prior briefs via `_working_memory_context`. Respects existing token budget and priority eviction.

**Scope:** `cognitive_agent.py` — post-chain storage, `agent_working_memory.py` — new category
**Risk:** Low — additive, uses existing WorkingMemory infrastructure

### Phase 4 — EVALUATE Brief Alignment

Extend EVALUATE to assess plan-to-output alignment: did COMPOSE follow the brief? Add alignment as a criterion alongside novelty, relevance, grounding.

**Scope:** `evaluate.py` — prompt template + criteria
**Risk:** Low — additive criterion, doesn't change pass/fail logic

### Phase 5 — Brief Format as NATS Schema (deferred to AD-641g)

When NATS lands, the composition brief dict becomes the message payload on `chain.{agent_id}.analyze.complete`. COMPOSE subscribes. No format change needed — the brief is already the right shape.

---

## 7. Design Decisions

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| DD-1 | Build briefs before NATS | Yes | Higher-value change; pre-shapes NATS message format; no throwaway work |
| DD-2 | Brief is part of ANALYZE JSON output, not a separate artifact file | For now | Flows through existing `prior_results` mechanism. Separate files when NATS provides proper message persistence |
| DD-3 | SA keys flow to both ANALYZE and COMPOSE | Yes | COMPOSE needs raw material to draw on, not just the brief's summary of it |
| DD-4 | Composition briefs are private to the agent | Yes (Minority Report Principle) | Stored in agent's own working memory. Counselor has no access. Self-reporting only |
| DD-5 | Brief is optional/backward compatible | Yes | Missing brief falls back to current behavior. Gradual rollout possible |
| DD-6 | Metacognitive storage uses existing WorkingMemory | Yes | No new infrastructure. Token budget and eviction already handled |
| DD-7 | EVALUATE alignment is additive, not gating | Yes | New criterion provides signal but doesn't change pass/fail threshold initially |

---

## 8. Theoretical Foundation

### Metacognition (Flavell 1979)

Metacognition = "thinking about thinking." Two components: metacognitive knowledge (knowing how you think) and metacognitive regulation (controlling how you think). Composition briefs provide both — the agent knows what evidence it prioritized (knowledge) and can adjust its planning approach based on feedback (regulation).

### Reflective Practice (Schon 1983)

Professionals improve through reflection-in-action (during) and reflection-on-action (after). The current REFLECT step does reflection-on-action for the response. Composition briefs enable reflection-on-action for the *reasoning process* — a deeper layer of professional development.

### Distributed Cognition (Hutchins 1995)

Cognitive artifacts (charts, checklists, logs) extend cognition beyond the individual mind. The composition brief is a cognitive artifact that extends the chain's cognition across steps — ANALYZE's understanding persists as an artifact that COMPOSE can reference, rather than dying when the ANALYZE LLM call completes.

### Scaffolded Writing (Flower & Hayes 1981)

Expert writers plan before composing — they build a rhetorical plan (audience, purpose, key points, organization) then execute against it. Novice writers skip planning and produce stream-of-consciousness output. The current chain is the novice writer (COMPOSE gets a topic and writes). The proposed chain is the expert writer (COMPOSE gets a plan and executes).

### Working Memory Extension (Baddeley 2000)

Baddeley's model includes the "episodic buffer" — a limited-capacity store that integrates information from multiple sources into coherent episodes. Composition briefs serve as an episodic buffer between chain steps, integrating environmental perception (ANALYZE) with compositional execution (COMPOSE).

---

## 9. What This Does NOT Do

- **Does not change the chain architecture.** QUERY → ANALYZE → COMPOSE → EVALUATE → REFLECT sequence is unchanged. We're enriching the handoff, not restructuring the pipeline.
- **Does not require NATS.** Works within the current synchronous chain. NATS migration is natural but not prerequisite.
- **Does not give the Counselor access to other agents' reasoning.** Minority Report Principle preserved.
- **Does not replace working memory.** Extends it with a new category ("reasoning") alongside existing categories ("action", "observation", "conversation", etc.).
- **Does not add new LLM calls.** Same five steps, same token budget. ANALYZE's output is richer but the call itself is the same.
- **Does not break backward compatibility.** Missing composition brief falls back to current routing-slip behavior.

---

## 10. Success Criteria

1. **A/B quality parity:** Chain-path responses to "How is the crew doing?" are as specific, confident, and evidence-rich as one-shot-path responses. Same agent, same question, comparable quality.
2. **Agents can answer "What was I thinking?":** When asked about a prior response, the agent can reference its composition brief from working memory and explain its reasoning process.
3. **EVALUATE brief alignment:** Score correlation between brief quality and output quality is positive — good plans produce good responses.
4. **No regression in proactive gating:** `[NO_RESPONSE]` rate for free-form proactive cycles remains comparable. Brief enrichment doesn't cause agents to over-respond.
