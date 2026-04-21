# Agent Situation Awareness Architecture

**Research Document — ProbOS Cognitive Architecture**
**Date:** 2026-04-18
**Author:** Sean Galliher (Architect)
**Status:** Research Complete → AD-644 Scoped
**Related ADs:** AD-632 (Cognitive Chain), AD-643a (Intent Routing), AD-504 (Self-Monitoring),
AD-502 (Temporal Context), AD-573 (Working Memory), AD-576 (Infrastructure Awareness),
AD-630 (Subordinate Stats), AD-618 (SOP Bill System)

---

## 1. Problem Statement

ProbOS crew agents running through the cognitive chain (QUERY → ANALYZE → COMPOSE →
EVALUATE → REFLECT) are producing `["silent"]` on virtually every cycle — including
scheduled duty cycles where silence is incorrect. The crew has been running for days
with zero duty reports.

**Root cause:** When `proactive_think` was added to `_CHAIN_ELIGIBLE_INTENTS`, the
chain path bypassed `_build_prompt_text()` — a 290-line monolithic prompt builder that
had accumulated ~20 context injections across 15+ ADs. These injections provided the
agent's temporal awareness, self-monitoring data, duty context, Ward Room activity,
infrastructure status, subordinate stats, working memory, and more.

The chain's ANALYZE step (`_build_situation_review_prompt`) receives standing orders
via `compose_instructions()` (system prompt) but receives virtually no dynamic data
(user prompt). The `situation_content` comes from `context.get("context", "")` — which
is an empty string for `proactive_think` because the IntentMessage stores dynamic data
in `params.context_parts`, not in `context`.

**Result:** ANALYZE sees standing orders (who you are and what your rules are) but has
no situation data (what is happening around you, what you were just doing, whether you
have a duty to perform). It correctly concludes: "I have nothing to respond to" →
`intended_actions: ["silent"]` → chain short-circuits at line 1918. The agent is
conscious but blind.

### The `_build_prompt_text` Accumulation Pattern

The monolithic prompt builder grew organically across 15+ ADs:

| AD | Injection | Lines | Purpose |
|----|-----------|-------|---------|
| AD-419 | Duty cycle header | 3328-3334 | "This is a scheduled duty" |
| AD-502 | Temporal awareness | 3347-3353 | Current time, uptime, last action |
| AD-573 | Working memory | 3355-3360 | Recent cognitive state |
| BF-034 | Cold-start note | 3362-3366 | "Fresh start after reset" |
| AD-576 | Infrastructure status | 3368-3374 | LLM/comms array health |
| AD-429 | Ontology identity | 3376-3392 | Callsign, dept, reports-to, peers |
| AD-630 | Subordinate stats | 3394-3406 | Direct report activity (Chiefs) |
| AD-567g | Orientation supplement | 3408-3412 | New crew onboarding guidance |
| AD-429b | Skill profile | 3414-3418 | Agent's declared skills |
| AD-540 | Episodic memories | 3420-3428 | Past experiences |
| AD-568d | Source attribution | 3430-3446 | Cognitive proprioception |
| — | Recent alerts | 3448-3454 | Bridge alerts |
| — | Recent events | 3456-3462 | System events |
| AD-413 | Ward Room activity | 3464-3488 | Recent department discussion |
| BF-110 | Active games | 3490-3506 | Board state, turn indicator |
| AD-504 | Self-monitoring data | 3508-3593 | Recent posts, similarity, zone |
| AD-588 | Introspective telemetry | 3595-3599 | Runtime metrics snapshot |

Each injection was independently reasonable. The accumulation created a design where
the agent's entire situation awareness lived in one function that the chain path
skipped entirely. This was not a deliberate architectural choice — it was an
accidental accretion. The cognitive chain (AD-632) was designed to replace the
single-call path, but the context it needed was never migrated.

---

## 2. Theoretical Foundations

### 2.1 Endsley's Situation Awareness Model (Human Factors)

**Endsley (1995), "Toward a Theory of Situation Awareness in Dynamic Systems"**

The canonical model for operator awareness in military, aviation, and maritime
domains. Three hierarchical levels:

- **Level 1 — Perception:** Detection of relevant elements in the environment.
  What entities, events, and conditions are present?

- **Level 2 — Comprehension:** Understanding the meaning and significance of
  perceived elements in relation to operator goals. What does this situation mean?

- **Level 3 — Projection:** Ability to predict future states based on current
  comprehension. What will happen next, and what should I do?

**ProbOS mapping:**

| SA Level | ProbOS Mechanism | Current State |
|----------|-----------------|---------------|
| L1 Perception | QUERY step + observation context | Minimal — 2 of ~17 data sources |
| L2 Comprehension | ANALYZE step (LLM reasoning) | Works, but starved of L1 input |
| L3 Projection | ANALYZE → `intended_actions` | Defaults to `["silent"]` due to L1 gap |

The chain architecture maps perfectly to Endsley's levels. QUERY gathers percepts
(L1), ANALYZE comprehends them (L2) and projects actions (L3), COMPOSE executes.
The problem is not architectural — it's that L1 is nearly empty. ANALYZE cannot
comprehend what it cannot perceive.

**Key insight:** Endsley distinguishes SA from the **decision** that follows it.
SA is the prerequisite — the mental model of "what is happening" — that informs
the decision. ProbOS's ANALYZE is both SA builder (L1→L2→L3) and decision maker
(`intended_actions`). The chain separates the decision from execution (COMPOSE),
but not from perception. This is correct for single-agent cognition — the agent
builds SA and decides in the same cognitive step.

### 2.2 Wickens' Multiple Resource Theory (Attention)

**Wickens (2002), "Multiple Resources and Performance Prediction"**

Operators have limited attentional resources distributed across modalities.
Overloading a single channel degrades performance even when total cognitive
load is manageable.

**ProbOS relevance:** `_build_prompt_text` loaded all 17 context injections
into a single undifferentiated prompt — the cognitive equivalent of playing
all instruments at once. The chain architecture provides natural attention
channels (QUERY → ANALYZE → COMPOSE), but only if each channel receives
appropriate input. Currently QUERY receives two data points and ANALYZE
gets the full standing orders — an inverted load distribution.

### 2.3 Klein's Recognition-Primed Decision Model (NDM)

**Klein (1993), "A Recognition-Primed Decision (RPD) Model of Rapid Decision Making"**

Experienced operators don't analytically weigh options — they pattern-match
the situation against experience and select the first workable option. The
quality of the decision depends on the quality of the situational assessment,
not the depth of deliberation.

**ProbOS mapping:** This is exactly the ANALYZE → `intended_actions` pipeline.
ANALYZE pattern-matches the situation (with episodic memory providing experience)
and selects actions. The chain's COMPOSE step is the execution of the selected
action, not a separate decision. But RPD requires rich situation assessment —
Klein's firefighters see the fire, feel the heat, hear the structure. ProbOS's
agents currently see nothing.

### 2.4 Neisser's Perceptual Cycle (Cognitive Psychology)

**Neisser (1976), "Cognition and Reality"**

Perception is not passive reception but an active cycle: schema (expectations)
→ exploration (directed search) → sampling (what you find) → schema update.
The observer's existing mental model determines what they look for, which
determines what they find, which updates the model.

**ProbOS mapping:** This is the QUERY → ANALYZE loop. Standing orders and
episodic memory provide the **schema** (what the agent expects and cares
about). QUERY provides **exploration** (directed data gathering). ANALYZE
performs **sampling** (selecting what matters) and **schema update** (changing
`intended_actions`). The architecture embodies the perceptual cycle, but QUERY
currently explores almost nothing.

### 2.5 BDI Architecture (Multi-Agent Systems)

**Rao & Georgeff (1995), "BDI Agents: From Theory to Practice"**

Already in ProbOS's intellectual lineage (AD-643a). The BDI model maps:

- **Beliefs:** What the agent knows about the world — situation awareness
- **Desires:** What the agent wants to achieve — standing orders, duty schedule
- **Intentions:** What the agent has committed to doing — `intended_actions`

The chain currently provides desires (standing orders) and produces intentions
(`intended_actions`), but beliefs are nearly empty. The belief revision cycle
(perception → belief update → intention formation) requires percepts to function.

### 2.6 SOAR Cognitive Architecture (AI)

**Laird (2012), "The Soar Cognitive Architecture"**

Already referenced in ProbOS cognitive sub-task protocol research. SOAR
distinguishes:

- **Working Memory:** Active situation model (what's happening now)
- **Long-Term Memory:** Procedural + semantic + episodic (what you know)
- **Perception:** Input from the environment that updates working memory
- **Elaboration:** Applying rules to the situation model

ProbOS already has working memory (AD-573), episodic memory (AD-540),
procedural memory (Cognitive JIT AD-531+), and elaboration (ANALYZE).
What's missing is perception — the pipeline that updates working memory
from the environment each cycle.

---

## 3. The Naval Analogy: What Makes a Watch Stander Present

A sailor standing watch on a naval vessel has access to information through
four distinct cognitive categories:

### 3.1 Innate Faculties

Things a watch stander has simply by being a conscious, present human:

- **Temporal awareness:** What time it is, how long they've been on watch.
  A sailor doesn't need a briefing to know the time.
- **Working memory:** What they were just doing, what happened 5 minutes ago.
  A sailor remembers they just answered a phone call.
- **Self-awareness:** How they're feeling — fatigue, alertness, confidence.
  A sailor knows if they're struggling.
- **Episodic memory:** Experiences from their career that inform judgment.
  A sailor remembers the last time they saw this reading.
- **Identity:** Who they are, what they're qualified for, their rank.
  A sailor doesn't need reminding of their name.

These are **faculties of being an agent**, not information provided by the
ship. A crew member who lacks these isn't standing watch — they're unconscious.

**ProbOS mapping:** Temporal awareness (AD-502), working memory (AD-573),
self-monitoring state (AD-504), episodic memory (AD-540), identity/orientation
(AD-429/567g). All currently live in `_build_prompt_text`. Some (identity,
episodic memory) already flow through the chain. The rest don't.

### 3.2 Situation Awareness (Perception of the Ship)

Things a watch stander knows because they are *physically present* on the ship:

- **Status boards:** Glancing at engineering status, navigation displays, reactor
  plant parameters. The watch stander doesn't request this data — it's on the
  bulkhead in front of them.
- **Ward Room / bridge activity:** Hearing conversations, knowing what's being
  discussed. The OOD hears the navigator report the course change.
- **Crew status:** Knowing who's on watch, who's qualified, who reported for duty.
  The EOOW knows which watch section is on duty.
- **Ship's status:** Alert condition, current operations, recent events. The
  quarterdeck watch knows the ship is in port because they can see the pier.
- **Alerts and announcements:** 1MC broadcasts, alarm bells, status changes.
  The entire crew hears "General Quarters, General Quarters."

These are **percepts from being present**, not briefings or procedures. The ship
makes this information available to anyone who's on board and paying attention.

**ProbOS mapping:** Ward Room activity (AD-413), infrastructure status (AD-576),
subordinate stats (AD-630), recent alerts/events, cold-start context (BF-034).
All gathered by `_gather_context()` in the proactive loop, stuffed into
`params.context_parts`, and then ignored by the chain.

### 3.3 Watch Station Duties

Structured obligations tied to the current watch station:

- **Watch station requirements:** The Engineering Officer of the Watch (EOOW) is
  required to log main engine readings every hour, tour the main spaces every 2
  hours, and report engineering status to the Officer of the Deck (OOD). These are
  specified in the Watch, Quarter, and Station Bill (WQSB).
- **Planned Maintenance System (PMS) cards:** Specific procedural checklists
  assigned to this watch station for this watch period.
- **Turnover notes:** Specific items from the outgoing watch stander.

These are **assigned obligations**, not percepts or faculties. The watch stander
consults their WQSB entry and PMS schedule. Without them, they might not know
they need to do something — but they'd still be conscious and aware.

**ProbOS mapping:** Duty schedule (config/system.yaml `duty_schedule`), SOP Bills
(AD-618, future). Currently the duty dict is passed in `params.duty` but never
reaches the ANALYZE prompt. The chain doesn't know the agent has a duty.

### 3.4 Standing Orders and Regulations

Internalized policies governing behavior:

- **Standing orders:** "If you detect a fire, sound the alarm before investigating."
  The watch stander has memorized these. They're not consulted mid-action.
- **Regulations:** SORM, OPNAVINST, fleet directives. Training, not reference.
- **Rules of engagement:** When to escalate, when to act independently.

These are **internalized guidance** that the watch stander carries in their head.
They don't read standing orders every cycle — they've learned them.

**ProbOS mapping:** Standing orders system (AD-339), 7-tier hierarchy via
`compose_instructions()`. This already works correctly in the chain's system
prompt. No fix needed.

### 3.5 The Insight

`_build_prompt_text` conflated all four categories into a single undifferentiated
blob injected into the user prompt. The cognitive chain provides the right
structure to separate them, but during the transition, all four categories were
dropped instead of migrated.

The correct architecture gives each category a distinct mechanism:

```
┌──────────────────────────────────────────────────────────────┐
│  COGNITIVE AGENT — One Proactive Cycle                        │
│                                                              │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  INNATE FACULTIES  (always present)                     │ │
│  │  Temporal awareness, working memory, self-monitoring,   │ │
│  │  identity, episodic memory                              │ │
│  │  ── Part of the agent's cognitive state ──              │ │
│  │  Mechanism: populated into observation dict by the      │ │
│  │  agent itself (perceive / pre-chain enrichment)         │ │
│  └─────────────────────────────────────────────────────────┘ │
│                          │                                   │
│                          ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  SITUATION AWARENESS  (perceived from ship)             │ │
│  │  Ward Room activity, infrastructure status, alerts,     │ │
│  │  subordinate stats, crew status                         │ │
│  │  ── The ship makes this visible ──                      │ │
│  │  Mechanism: QUERY step operations                       │ │
│  │  (extend _QUERY_OPERATIONS registry)                    │ │
│  └─────────────────────────────────────────────────────────┘ │
│                          │                                   │
│                          ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  WATCH STATION DUTIES  (assigned obligations)           │ │
│  │  Duty cycle context, PMS cards, SOP Bills               │ │
│  │  ── What you were told to do ──                         │ │
│  │  Mechanism: duty context in observation dict,           │ │
│  │  ANALYZE prompt renders duty instructions               │ │
│  └─────────────────────────────────────────────────────────┘ │
│                          │                                   │
│                          ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  STANDING ORDERS  (internalized guidance)               │ │
│  │  Behavioral rules, communication protocols,             │ │
│  │  self-monitoring rules, cognitive zones                  │ │
│  │  ── Who you are and how you behave ──                   │ │
│  │  Mechanism: compose_instructions() → system prompt      │ │
│  │  (already works correctly)                              │ │
│  └─────────────────────────────────────────────────────────┘ │
│                          │                                   │
│                          ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │           ANALYZE (Endsley L2+L3)                       │ │
│  │  Comprehends situation, forms intended_actions          │ │
│  │  Now receives all four categories of input              │ │
│  └─────────────────────────────────────────────────────────┘ │
│                          │                                   │
│                          ▼                                   │
│              COMPOSE → EVALUATE → REFLECT                    │
└──────────────────────────────────────────────────────────────┘
```

---

## 4. Design: Four-Category Context Architecture

### 4.1 Category 1 — Innate Faculties

**What:** Cognitive state the agent possesses by virtue of being an agent.
**When populated:** Before the chain runs, by the agent itself.
**Mechanism:** A new method `_build_cognitive_state()` on CognitiveAgent that
populates the observation dict with innate state. Runs for **every** chain
execution, not just proactive_think. These are faculties of consciousness.

| Faculty | Source | Observation Key |
|---------|--------|-----------------|
| Current time | `time.time()` | `_temporal_context` |
| System uptime | `runtime._start_time_wall` | (included in temporal) |
| Last action time | Agent's last act timestamp | (included in temporal) |
| Working memory | `self._working_memory.render_context()` | `_working_memory` |
| Self-monitoring state | `context_parts.self_monitoring` | `_self_monitoring` |
| Cognitive zone | From self_monitoring | (included in self_monitoring) |
| Recent posts | From self_monitoring | (included in self_monitoring) |
| Self-similarity score | From self_monitoring | (included in self_monitoring) |
| Notebook index | From self_monitoring | (included in self_monitoring) |
| Memory state | Episode count, lifecycle | (included in self_monitoring) |
| Source attribution DATA | `_source_attribution` (episodic_count, procedural_count, oracle_used) | `_source_attribution` |
| Introspective telemetry | AD-588 metrics snapshot | `_introspective_telemetry` |
| Trust / agency / rank | `params.trust_score`, `params.agency_level`, `params.rank` | `_agent_metrics` |
| Ontology identity | AD-429 `context_parts.ontology` (reports_to, peers, alert condition) | `_ontology_context` |
| Orientation supplement | AD-567g time-gated onboarding context | `_orientation_supplement` |
| No-memory confabulation guard | Warning when episodic memories empty | `_confabulation_guard` |
| Comm proficiency guidance | Cognitive JIT `_get_comm_proficiency_guidance()` | `_comm_proficiency` |

**Source attribution note:** Source attribution has two parts: (1) *policy* — "ground
your responses in identified sources" — which belongs in standing orders (Category 4).
(2) *data* — the agent's awareness of what sources it actually has available right now
(episodic count, procedural count, oracle access) — which is an innate faculty. The
data component is listed here; the policy component is in Category 4.

**Ontology identity note:** Basic identity (callsign, department, rank) already flows
through `compose_instructions()` / standing orders. The *dynamic* ontology — chain of
command (reports_to, direct_reports, peers) and vessel state (alert condition) — is
situational context that changes with crew composition and ship state. It belongs here
as an innate faculty because the agent always knows who they report to and who their
peers are, regardless of intent.

**Orientation supplement note:** AD-567g provides diminishing onboarding context for
young agents (< N cycles). Time-gated: fades as agent gains experience. Belongs in
innate faculties because it's a property of the agent's maturity, not an external
percept. Implementation: read `context_parts.orientation_supplement`, inject when
present, omit when absent (self-removing by design).

**No-memory confabulation guard note:** When an agent has zero episodic memories, the
old path injected: "You have no stored episodic memories yet. Do not reference or
invent past experiences you do not have." This is a grounded self-knowledge guardrail
(Westworld Principle) — the agent must know what it doesn't know. Without this, LLMs
confabulate past experiences.

**Note:** Episodic memory and basic identity/orientation already flow through the chain
via `_formatted_memories` and `compose_instructions()` respectively. No changes
needed for those.

**Design principle:** These keys are set on the observation dict in
`_execute_chain_with_intent_routing()` alongside the existing agent identity
injections (lines 1802-1865). They are part of what makes the agent *present*.

### 4.2 Category 2 — Situation Awareness

**What:** Dynamic data about the ship's current state, perceived by the agent.
**When populated:** During the QUERY step, via `_QUERY_OPERATIONS`.
**Mechanism:** Extend the QUERY handler's operation registry with new operations.
Update the proactive_think chain's `context_keys` to request them.

| Percept | QUERY Operation Key | Source Service |
|---------|-------------------|----------------|
| Ward Room activity | `ward_room_activity` | WardRoomService |
| Recent alerts | `recent_alerts` | AlertEngine |
| Recent events | `recent_events` | EventBus |
| Infrastructure status | `infrastructure_status` | LLMClient health |
| Subordinate stats | `subordinate_stats` | WardRoomService + Ontology |
| Cold-start note | `cold_start_context` | Runtime lifecycle |
| Alert condition | `alert_condition` | AlertConditionService |
| Active games | `active_games` | GameService |

**Design principle:** QUERY operations are deterministic (zero LLM calls), follow
the existing dispatch-table pattern, and are registered in `_QUERY_OPERATIONS` —
new operations added without touching `__call__()`. Open/Closed.

**Chain spec update:**
```python
# Current (2 keys):
context_keys=("unread_counts", "trust_score"),

# After AD-644 (extended):
context_keys=(
    "unread_counts", "trust_score",
    "ward_room_activity", "recent_alerts",
    "infrastructure_status", "subordinate_stats",
    "cold_start_context", "alert_condition",
),
```

### 4.3 Category 3 — Watch Station Duties

**What:** Active duty assignment, if any.
**When populated:** Before the chain runs, from `params.duty`.
**Mechanism:** The proactive loop already passes `duty` in the IntentMessage's
`params`. The chain's observation enrichment reads it and sets `_active_duty`.
ANALYZE prompt renders duty context when present.

**Observation keys:**

| Key | Value |
|-----|-------|
| `_active_duty` | `{"duty_id": "...", "description": "...", "is_scheduled": True}` or `None` |

**ANALYZE prompt behavior when duty is active:**
- Replaces generic "assess the situation" with duty-specific instructions
- Biases away from `["silent"]` — the agent has an *obligation* to report
- Duty description becomes the focus of analysis
- Maps to WQSB: the agent knows what their watch station requires

**ANALYZE prompt behavior when no duty (free-form):**
- Current situation_review behavior: assess, justify any response
- Silence remains the expected default for free-form cycles
- Maps to a sailor on watch with no specific PMS due — they monitor, but
  don't generate unnecessary reports

### 4.4 Category 4 — Standing Orders (no changes needed)

The chain's system prompt already receives the full standing orders hierarchy
via `compose_instructions()`. Self-monitoring rules, cognitive zone descriptions,
communication protocols, action vocabulary — all present.

**Two additions to standing orders markdown (zero code changes):**

1. **Source attribution POLICY** (AD-568d) — currently only in `_build_prompt_text`.
   Move the policy guidance ("Ground your responses in identified sources. Do not
   present training knowledge as personal experience.") to
   `config/standing_orders/ship.md`. Note: the *data* component (episodic_count,
   procedural_count, oracle_used) is in Category 1 innate faculties — the agent
   sees what sources it has. The *policy* tells it how to use them.

2. **Duty reporting expectations** — add to ship standing orders: "When executing
   a scheduled duty, produce a structured report of your findings. Silence during
   a duty cycle requires explicit justification."

---

## 5. Prompt Template Updates

### 5.1 ANALYZE Prompt (`_build_situation_review_prompt`)

The `_build_situation_review_prompt` in `analyze.py` currently renders only:
- `context.get("context", "")` — situation content (empty for proactive_think)
- Prior QUERY results (unread_counts, trust_score)
- `_formatted_memories` — episodic recall

After AD-644, it renders all four categories. The prompt template becomes the
**rendering layer** that assembles the agent's situation model for the LLM.

### Proposed prompt structure for `situation_review`:

```
## Your Current State (Innate Faculties)
{temporal_context}
{trust_score} | {agency_level} | {rank}
{ontology_context — reports_to, peers, alert condition}
{working_memory}
{self_monitoring — zone, recent posts, similarity}
{source_attribution — episodic_count, procedural_count, oracle_used}
{confabulation_guard — if no episodic memories}
{orientation_supplement — if young agent, time-gated}

## Ship Status (Situation Awareness — from QUERY)
{ward_room_activity}
{infrastructure_status}
{recent_alerts}
{recent_events}
{subordinate_stats}  (if Chief)
{alert_condition}
{cold_start_context}  (if system recently started)
{active_game}  (if game in progress)

## Active Duty  (if duty assigned)
[Duty: {description}]
This is a scheduled duty. Assess your area of responsibility and report findings.
--- OR ---
## Proactive Review  (no duty)
No scheduled duty. Post only if you observe something genuinely noteworthy.

## Episodic Memories
{formatted_memories}

## Assessment Required
{existing analysis questions — topics, gaps, contribution_assessment, intended_actions}
```

**Key difference from `_build_prompt_text`:** The prompt template is structured
and labeled. Each section has a clear cognitive category. The LLM receives a
situation model with named sections rather than an undifferentiated wall of text.
This aligns with Wickens' multiple resource theory — structured input reduces
cognitive channel interference.

### 5.2 COMPOSE Prompt (`_build_proactive_compose_prompt` / `_build_user_prompt`)

**This is a second consumer of the same data.** The COMPOSE step also needs
situation context — not just ANALYZE's output. Currently `_build_user_prompt()`
in `compose.py` reads `context.get("context", "")` (empty) and renders ANALYZE
results + QUERY data + memories. But COMPOSE also needs:

- **Duty/free-form framing** — COMPOSE must know whether to produce a duty report
  ("Compose a Ward Room post with your findings") or a free-form observation
  ("If something genuinely warrants attention, compose a brief observation").
  This comes from Category 3 (`_active_duty`).

- **Comm proficiency guidance** — `_get_comm_proficiency_guidance()` provides
  Cognitive JIT skill injection for communication quality. Currently injected by
  `_build_prompt_text` via `_frame_task_with_skill()` when Ward Room activity is
  present. COMPOSE is the natural home for this — it's about *how to communicate*,
  not *what to analyze*.

- **Source attribution data** — COMPOSE must render source awareness so the agent
  attributes correctly in its output.

- **No-memory confabulation guard** — if the agent has no episodic memories, COMPOSE
  must include the guard to prevent fabricating past experiences in the output.

**Design principle:** COMPOSE reads from the same observation dict as ANALYZE. The
observation dict is set once in `_execute_chain_with_intent_routing()`. Both
prompts are rendering layers over the same data — they just emphasize different
aspects (ANALYZE: "assess this", COMPOSE: "produce output from this").

**Implementation:** `_build_proactive_compose_prompt` reads innate faculties and
duty context from the observation dict (which already flows through the chain).
No new data gathering needed — just prompt template updates.

---

## 6. Composability and Scaling

### 6.1 The Four Categories Scale Independently

Each category has a different growth dynamic:

- **Innate faculties:** Fixed set. Working memory, temporal awareness, self-monitoring
  are architectural features. New faculties are rare (maybe 1-2 per era).
- **Situation awareness:** Grows with ship capabilities. New QUERY operations added
  as new services come online. Each is a function in a dispatch table — O(1) to add.
- **Watch station duties:** Grows with the SOP Bill system (AD-618). New duty types
  add new duty contexts. The ANALYZE template renders them uniformly.
- **Standing orders:** Grows with policy evolution. Markdown files, no code changes.

This is fundamentally more scalable than `_build_prompt_text`, where every new
context injection required modifying a 290-line function with 17 conditional blocks.

### 6.2 Composability with NATS Pipeline (AD-641g)

When the cognitive chain is decoupled via NATS subjects:

- **QUERY becomes a persistent subscriber.** Ward Room activity, alerts, infrastructure
  status are NATS events that QUERY naturally consumes. No polling needed.
- **Innate faculties travel with the message.** The agent's cognitive state is attached
  to the message payload as it moves through `chain.{agent_id}.analyze`.
- **Duty context is a triggering event.** The duty scheduler publishes to
  `duty.{agent_id}.due`, which triggers a chain execution with duty context attached.

The four-category model maps directly to NATS message sources:
1. Innate → agent-local state, attached at message creation
2. Situation → NATS subscriptions (events from ship services)
3. Duty → NATS trigger from scheduler
4. Standing orders → loaded once, cached, refreshed on change

### 6.3 Composability with SOP Bills (AD-618)

When the SOP Bill system replaces the hardcoded duty schedule:

- **Bills define the duty context.** A Bill's `trigger: schedule:<cron>` fires the
  duty. The Bill's steps define what the agent should do. Category 3 (Watch Station)
  is populated from the Bill spec, not from `config/system.yaml`.
- **Bills can modify perception.** A Bill step might require specific QUERY operations
  ("check pool health", "review recent DMs"). The Bill extends Category 2 for its
  execution context.
- **Bills are composable.** Multiple Bills can be active simultaneously. The agent
  sees all active duties and prioritizes.

### 6.4 Composability with Intent Routing (AD-643a)

The intent routing system already works with this model:

- **ANALYZE produces `intended_actions` from situation awareness.** With richer
  input, ANALYZE makes better action decisions.
- **Trigger awareness (AD-643b) scopes available actions.** The agent sees only
  actions relevant to their department/rank, reducing decision space.
- **Skills load after intent routing.** Category 2 data (Ward Room posts, alerts)
  informs the action choice, then skills load to help execute.

---

## 7. Implementation Phases

### Phase 1 — Duty Context Restoration (Critical Fix)

Minimum viable fix to restore duty cycle functionality:

1. Pass `params.duty` into observation dict as `_active_duty`
2. Pass `params.trust_score`, `params.agency_level`, `params.rank` into `_agent_metrics`
3. Update `_build_situation_review_prompt` to render duty context and agent metrics
4. Update `_build_proactive_compose_prompt` to render duty framing
5. When `_active_duty` is present, ANALYZE knows the agent has an obligation

**Scope:** 3 files modified (cognitive_agent.py, analyze.py, compose.py). ~50 lines.
**Validates:** Duty cycles produce reports instead of `["silent"]`.

### Phase 2 — Innate Faculties

Populate innate cognitive state into the observation dict:

1. Add `_build_cognitive_state()` method to CognitiveAgent
2. Call it in `_execute_chain_with_intent_routing()` alongside existing identity injection
3. Populate: `_temporal_context`, `_working_memory`, `_self_monitoring`,
   `_source_attribution` (data), `_introspective_telemetry`, `_ontology_context`,
   `_orientation_supplement`, `_confabulation_guard`, `_comm_proficiency`
4. Update ANALYZE prompt template to render all innate faculties
5. Update COMPOSE prompt template to render source attribution, confabulation guard,
   comm proficiency, and duty/free-form framing from observation dict

**Scope:** 3 files modified (cognitive_agent.py, analyze.py, compose.py). ~120 lines.
**Validates:** Agents have temporal awareness, self-monitoring, ontology, source
attribution data, confabulation guards, and comm proficiency in chain path.

### Phase 3 — Situation Awareness (QUERY Extensions)

Extend the QUERY step with new operations:

1. Register new operations in `_QUERY_OPERATIONS`: ward_room_activity,
   infrastructure_status, subordinate_stats, recent_alerts, recent_events,
   cold_start_context, active_game
2. Update proactive_think chain's `context_keys`
3. Update ANALYZE prompt template to render QUERY results

**Scope:** 2 files modified (query.py, cognitive_agent.py). ~120 lines.
**Validates:** Agents perceive ship status through QUERY step.

### Phase 4 — Standing Orders Additions

Add missing policies to standing orders markdown:

1. Source attribution POLICY → `ship.md` (the behavioral guidance, not the data)
2. Duty reporting expectations → `ship.md`

**Scope:** 1 file modified (config/standing_orders/ship.md). ~10 lines.
**Validates:** Chain system prompt includes previously-missing policies.

### Phase 5 — `_build_prompt_text` Deprecation Path

Once all four categories flow through the chain:

1. Verify chain path produces equivalent or better output than single-call path
2. Mark `_build_prompt_text` proactive_think block as deprecated
3. Eventually remove when `_CHAIN_ELIGIBLE_INTENTS` covers all intent types

**Note:** `_build_prompt_text` still serves non-chain intents. Only the
proactive_think block is replaced by this work.

### Parity Checklist

Complete inventory of `_build_prompt_text` proactive_think block (lines 3319-3607)
mapped to AD-644 categories. Every item must have a destination:

| # | `_build_prompt_text` Item | AD-644 Category | Phase | Observation Key |
|---|--------------------------|-----------------|-------|-----------------|
| 1 | Duty/free-form header framing | Cat 3 — Watch Station | 1 | `_active_duty` |
| 2 | Trust / agency / rank display | Cat 1 — Innate | 1 | `_agent_metrics` |
| 3 | Temporal awareness (AD-502) | Cat 1 — Innate | 2 | `_temporal_context` |
| 4 | Working memory (AD-573) | Cat 1 — Innate | 2 | `_working_memory` |
| 5 | Cold-start system note (BF-034) | Cat 2 — SA | 3 | `cold_start_context` |
| 6 | Infrastructure status (AD-576) | Cat 2 — SA | 3 | `infrastructure_status` |
| 7 | Ontology identity (AD-429) — reports_to, peers, alert | Cat 1 — Innate | 2 | `_ontology_context` |
| 8 | Subordinate stats (AD-630) | Cat 2 — SA | 3 | `subordinate_stats` |
| 9 | Orientation supplement (AD-567g) | Cat 1 — Innate | 2 | `_orientation_supplement` |
| 10 | Skill profile (AD-429b) | Already flows | — | (existing chain path) |
| 11 | Episodic memories (AD-540) | Already flows | — | `_formatted_memories` |
| 12 | No-memory confabulation guard | Cat 1 — Innate | 2 | `_confabulation_guard` |
| 13 | Source attribution DATA (AD-568d) | Cat 1 — Innate | 2 | `_source_attribution` |
| 14 | Source attribution POLICY (AD-568d) | Cat 4 — Standing Orders | 4 | ship.md |
| 15 | Recent alerts | Cat 2 — SA | 3 | `recent_alerts` |
| 16 | Recent events | Cat 2 — SA | 3 | `recent_events` |
| 17 | Comm proficiency guidance (Cog JIT) | Cat 1 — Innate | 2 | `_comm_proficiency` |
| 18 | Ward Room activity (AD-413) | Cat 2 — SA | 3 | `ward_room_activity` |
| 19 | Active game state (BF-110) | Cat 2 — SA | 3 | `active_game` |
| 20 | Self-monitoring (AD-504/506) | Cat 1 — Innate | 2 | `_self_monitoring` |
| 21 | Introspective telemetry (AD-588) | Cat 1 — Innate | 2 | `_introspective_telemetry` |
| 22 | Final duty/free-form instructions | Cat 3 — Watch Station | 1 | `_active_duty` |
| 23 | Duty reporting expectations (policy) | Cat 4 — Standing Orders | 4 | ship.md |

**COMPOSE template parity:** Items 1, 2, 12, 13, 17, 22 also need rendering in
`_build_proactive_compose_prompt` (Phase 1 for duty framing, Phase 2 for the rest).

---

## 8. What This Does NOT Do

- **Does not change the chain architecture.** QUERY → ANALYZE → COMPOSE → EVALUATE
  → REFLECT sequence is unchanged. We're feeding the chain, not restructuring it.

- **Does not replace the proactive loop.** `_gather_context()` continues to gather
  dynamic data. The change is in how that data reaches the chain — through the
  observation dict and QUERY operations, not through `_build_prompt_text`.

- **Does not implement SOP Bills.** Duty context comes from the existing
  `duty_schedule` config. AD-618 is the long-term replacement.

- **Does not implement NATS decoupling.** The chain remains synchronous. AD-641g
  is the long-term evolution.

- **Does not add new data sources.** Every injection listed already exists in
  `_build_prompt_text` / `_gather_context()`. This is a migration, not new features.

---

## 9. Research Sources

### Human Factors / Cognitive Science
- Endsley, M. R. (1995). "Toward a Theory of Situation Awareness in Dynamic Systems." *Human Factors*, 37(1), 32-64.
- Wickens, C. D. (2002). "Multiple Resources and Performance Prediction." *Theoretical Issues in Ergonomics Science*, 3(2), 159-177.
- Klein, G. A. (1993). "A Recognition-Primed Decision (RPD) Model of Rapid Decision Making." In Klein et al. (Eds.), *Decision Making in Action: Models and Methods*. Ablex.
- Neisser, U. (1976). *Cognition and Reality: Principles and Implications of Cognitive Psychology*. W. H. Freeman.
- Flavell, J. H. (1979). "Metacognition and Cognitive Monitoring." *American Psychologist*, 34(10), 906-911.

### Multi-Agent Systems
- Rao, A. S., & Georgeff, M. P. (1995). "BDI Agents: From Theory to Practice." *Proceedings of ICMAS-95*.

### Cognitive Architectures
- Laird, J. E. (2012). *The Soar Cognitive Architecture*. MIT Press.
- Anderson, J. R. (2007). *How Can the Human Mind Occur in the Physical Universe?* (ACT-R). Oxford University Press.

### Naval
- OPNAVINST 3120.32D — Ship's Organization and Regulations Manual (SORM)
- NAVEDTRA 43100 — Personnel Qualification Standards (PQS)
- Navy Watch Quarter and Station Bill (WQSB) procedures

### ProbOS Internal
- `docs/research/cognitive-sub-task-protocol.md` — Three cognitive processing levels, SOAR mapping
- `docs/research/metacognitive-architecture.md` — Grounded self-knowledge, source monitoring
- `docs/research/crew-capability-architecture.md` — Four-tier capability model, Navy personnel mapping
- `docs/research/standard-operating-procedures.md` — SOP Bill system design (AD-618)
- AD-632 (Cognitive Chain), AD-643a/b (Intent Routing + Trigger Learning)
- AD-504/506 (Self-Monitoring + Self-Regulation Wave)
- AD-502 (Temporal Context), AD-573 (Working Memory)
