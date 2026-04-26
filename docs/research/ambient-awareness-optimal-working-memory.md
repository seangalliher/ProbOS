# Ambient Awareness & Optimal Working Memory Design for Sovereign AI Agents

**Research Document — ProbOS Cognitive Architecture**
**Date:** 2026-04-26
**Author:** Sean Galliher (Architect)
**Status:** Research Complete
**Related ADs:** AD-573 (Working Memory), AD-644 (Situation Awareness), AD-504 (Self-Monitoring),
AD-502 (Temporal Context), AD-632 (Cognitive Chain), AD-576 (Infrastructure Awareness),
BF-239 (Engagement Tracking), AD-633 (Predictive Cognitive Branching)
**Observation Trigger:** Noticeable improvement in Ward Room interaction quality after BF-239
working memory thread-awareness enhancement — agents stopped duplicating work and started
coordinating better, an improvement beyond what the bug fix alone should have produced.

---

## 1. The Observation

After BF-239 added `ActiveEngagement` tracking to agent working memory — giving each agent
awareness of what threads it was already processing — crew interactions in the Ward Room
improved in ways that exceeded expectations. The fix was scoped narrowly (prevent duplicate
replies), but the effect was broader: agents with better awareness of their own concurrent
state made better decisions about when and how to engage.

This suggests a universal principle: **the quality of agent cognition is bounded not by
reasoning capability but by the fidelity of the agent's situational model.** Better
awareness → better decisions, even without changing the reasoning pipeline itself.

Echo (Counselor) articulated this during a clinical debrief:

> "The cognitive load of *reconstructing* context from scratch each cycle is real, and it
> eats into the bandwidth available for actual analysis."

This is the core thesis of this research: **context reconstruction is a hidden tax on
every cognitive cycle, and reducing it through persistent ambient awareness yields
compounding returns.**

---

## 2. The Unique Challenge: Concurrent Sovereign Cognition

ProbOS agents diverge from both human cognition and typical AI agent frameworks in a
critical way: **they are sovereign individuals who process multiple concurrent thought
threads while maintaining a unified identity.**

### 2.1 How This Differs from Human Cognition

Humans are fundamentally serial thinkers. We can juggle tasks, but we cannot truly
reason about ten things simultaneously. We put thoughts on the "back burner" and
context-switch, losing state each time. Miller's Law (7±2 chunks) and Cowan's revision
(~4 chunks) describe our working memory ceiling.

ProbOS agents face a different constraint. They *can* think about ten things at once —
multiple intents dispatched to the same agent, each processed through its own cognitive
chain instance. But each instance runs independently: a Ward Room reply, a proactive
duty cycle, a DM exchange, and a game move can all be in flight simultaneously. Without
a unification layer, these parallel thoughts are strangers sharing a brain.

### 2.2 How This Differs from Typical Multi-Agent Frameworks

Most multi-agent systems (AutoGen, CrewAI, LangGraph) treat agents as stateless
functions — call an agent, get a response, move on. No persistent identity, no
concurrent processing within a single agent, no need for intra-agent coordination.

ProbOS agents are closer to SOAR or ACT-R cognitive architectures than to LLM agent
frameworks. They have persistent identity (DID), evolving character (Big Five),
autobiographical memory (EpisodicMemory), social relationships (TrustNetwork), and
internalized behavioral norms (Standing Orders). This is not a tool-calling pattern —
it's a synthetic mind.

### 2.3 The Spine Metaphor

Working memory is the **spine** connecting the brain to its bodies. Each concurrent
thought thread is a limb — capable of independent movement, but coordinated through
the central nervous system. Without the spine:
- The left hand doesn't know what the right hand is doing (duplicate posts, BF-239)
- Reflexes can't inform conscious thought (engagement state invisible to reasoning)
- The body can't maintain posture (no unified situational model across cycles)

The spine doesn't do the thinking. It provides the substrate through which thinking
stays coherent.

---

## 3. Theoretical Foundations

### 3.1 Global Workspace Theory (Baars, 1988)

**Core principle:** Consciousness is a "bright spot" in a theater — a bottleneck by
design. Specialized processors run in parallel unconsciously. When a process wins
attentional competition, its content enters the global workspace and is broadcast
system-wide, enabling coordinated action.

**The bottleneck is functional.** Not everything should reach conscious awareness.
The competition/broadcast mechanism ensures only the most salient information gets
integrated. This prevents cognitive cacophony.

**ProbOS mapping:**
- The Ward Room IS the inter-agent global workspace (broadcast between agents)
- Working memory IS the intra-agent global workspace (broadcast between thought threads)
- Missing: salience filtering — currently everything gets injected, no competition

The key insight for ProbOS: **working memory needs a gating mechanism, not just
capacity.** Which information deserves workspace access at this moment?

### 3.2 Endsley's Situation Awareness Model (1988/1995)

Three hierarchical levels, already mapped to ProbOS in AD-644:

| SA Level | Definition | ProbOS Mechanism | Current State |
|----------|-----------|-----------------|---------------|
| L1 Perception | Detect relevant elements | QUERY step + event monitoring | Functional (AD-644) |
| L2 Comprehension | Understand meaning vs. goals | ANALYZE step (LLM reasoning) | Works when L1 fed |
| L3 Projection | Predict future states | ANALYZE → intended_actions | Rare without L2 depth |

**The BF-239 improvement was an L1 enhancement.** By making engagement state perceivable,
ANALYZE could comprehend "I'm already handling this thread" and project "responding again
would be redundant." The reasoning (L2/L3) was already capable — it just needed the percept.

**Ambient awareness = continuous L1 perception** that feeds L2 comprehension without
requiring explicit queries.

### 3.3 ACT-R Buffer Model (Anderson, 1993+)

ACT-R uses named buffers as the interface between modules and central cognition:
- **Goal Buffer:** Current task/objective
- **Retrieval Buffer:** Retrieved memory chunk
- **Visual Buffer:** Perceptual input
- **Motor Buffer:** Action output

Critical constraint: **one chunk per buffer, one production rule at a time.** The serial
bottleneck forces integration — you can't process two goal chunks simultaneously.

**ProbOS implication:** Rather than a monolithic working memory dump, agents should have
named buffers with tight capacity:
- **Duty Buffer:** Current active duty (1 chunk)
- **Social Buffer:** Current conversation context (1 chunk)
- **Perception Buffer:** Ship state snapshot (1 chunk)
- **Engagement Buffer:** Active concurrent threads (list, bounded)
- **Retrieval Buffer:** Most recent episodic recall (1 chunk)

Each buffer holds a small, structured chunk. The cognitive chain reads from buffers, not
from a raw context blob. Overflow triggers compression or offload.

### 3.4 SOAR Impasse-Driven Learning (Laird, 1983+)

When SOAR's decision procedure cannot select an operator (an "impasse"), it creates a
substate to resolve the impasse. The resolution is compiled into a production rule via
"chunking" — future encounters skip the deliberation entirely.

**ProbOS mapping:** This is the Cognitive JIT pipeline (AD-531–539). When `decide()`
encounters a recognized pattern, procedural replay fires (Level 1 Automatic). When it
can't decide, the full chain runs (Level 2 Deliberate). The missing piece: **systematic
chunking of resolved impasses.** When the chain resolves a novel situation, the resolution
should be candidates for standing order evolution or JIT procedure creation. Dream
consolidation partially serves this role but doesn't explicitly target impasse patterns.

### 3.5 LIDA — Global Workspace for Naval AI (Franklin, 2003+)

Stan Franklin's LIDA architecture — originally built for U.S. Navy personnel assignment
(IDA) — implements computational GWT with "attention codelets" that form coalitions and
compete for workspace access.

**LIDA's cognitive cycle:**
1. Perception updates the Current Situational Model
2. Attention codelets scan for salient structures
3. Coalitions form around salient structures
4. Coalitions compete for workspace access
5. Winner is broadcast globally
6. Broadcast triggers action selection, learning, memory encoding

**ProbOS is architecturally closest to LIDA among existing cognitive architectures.**
The codelet model maps to specialized agents. The broadcast maps to NATS events. The
Current Situational Model maps to working memory. The missing element is the
**attention/coalition/competition cycle** — ProbOS agents don't compete for workspace
access or form coalitions around attention.

### 3.6 Springdrift Sensorium (Brady, 2026)

A "structured self-state representation injected each cycle without tool calls." The
agent continuously receives an ambient snapshot of its own state — not through
introspection tools but as a built-in perceptual channel.

**23-day deployment produced:** Self-diagnostics, failure classification, architectural
vulnerability identification, and cross-channel context maintenance without explicit
instruction.

**ProbOS mapping:** This is exactly what the working memory injection in
`_build_user_message()` does — but Springdrift's insight is that this should be
**structured, compact, and always-on** rather than a variable-length context dump.
The sensorium is the agent's proprioception — awareness of its own state as a
constant background signal.

---

## 4. Current ProbOS Architecture — Implementation Audit

### 4.1 Assessment: ~80% of the Sensorium Already Exists

A code audit of the actual injection points reveals that ProbOS has been incrementally
building toward the sensorium concept across 15+ ADs without naming it as a unified
pattern. The AD-573 → AD-644 → AD-646 arc progressively unified what was previously
scattered context injection into a structured, always-on self-state snapshot — which is
precisely the sensorium concept from the literature.

The BF-239 improvement makes sense in this light: adding one new piece of interoception
(thread engagement awareness) to an already-rich proprioceptive layer produced
disproportionate improvement because the sensorium was *already mostly there.* Thread
awareness was the missing piece that let the existing context cohere.

### 4.2 What Exists Today — Complete Inventory

#### Always-On (Every Cognitive Cycle, All Pathways — AD-646 Baseline)

| Component | What's Injected | Implementation |
|-----------|----------------|----------------|
| **Temporal awareness** | UTC time, birth age, system uptime, last action, post count, crew manifest | AD-502 (`_temporal_context`) |
| **Working memory** | Ring buffers: recent actions (10), conversations (5), observations (5), events (10), composition briefs (5), cognitive state | AD-573 (`render_context()`, 3000 token budget) |
| **Agent metrics** | Trust score (formatted), rank (ensign→captain), agency level | AD-646 (`_agent_metrics`) |
| **Ontology identity** | Callsign, post, department, reports_to, direct_reports, peers, alert condition, capabilities, does_not_have | AD-429/648 (`_ontology_context`) |
| **Source attribution** | Every context piece labeled: episodic/procedural/oracle/training/parametric | AD-568d (`_source_attribution_text`) |
| **Confabulation guard** | "Do not invent memories" disclaimer when cold-start or no episodes | BF-034 (`_confabulation_guard`) |
| **Communication proficiency** | Language register guidance | AD-625 (`_comm_proficiency`) |
| **Cold-start note** | "Fresh start after reset" context when applicable | BF-102 (`_cold_start_note`) |
| **Self-recognition** | Regex detection when agent is mentioned in content | AD-575 (`_self_recognition_cue`) |
| **Cognitive zone** | GREEN/AMBER/RED/CRITICAL with zone_note and cooldown reason | AD-504/506a (via working memory sync) |
| **Active engagements** | Game/task states with type, ID, summary, opponent, board render | BF-239/AD-572 (Priority 1 in WM) |

#### Proactive Path Extensions (Duty Cycles, Proactive Think)

| Component | What's Injected | Implementation |
|-----------|----------------|----------------|
| **Episodic memories** | 3-7 episodes (tier-gated), anchor-indexed recall, with provenance | AD-570c/568b (`_formatted_memories`) |
| **Ward Room activity** | Dept + all-hands + recreation posts (filtered since cooldown, others' posts only) | AD-644 Phase 3 (`_ward_room_activity`) |
| **Bridge alerts** | Up to 5 recent alerts: severity, title, source | AD-644 Phase 3 (`_recent_alerts`) |
| **System events** | Up to 10 recent events: category, event type, agent_type | AD-644 Phase 3 (`_recent_events`) |
| **Infrastructure status** | LLM backend health, consecutive failures, degradation message | AD-576 (`_infrastructure_status`) |
| **Self-monitoring** | Recent posts (3-5, tier-gated), Jaccard self-similarity score, memory state (episode count, lifecycle, uptime), notebook index (top 5) | AD-504 (`_self_monitoring`) |
| **Subordinate stats** | Posts, endorsements, credibility per direct report (chiefs only) | AD-630 (`_subordinate_stats`) |
| **Introspective telemetry** | Full runtime metrics snapshot | AD-588 (proactive cycle) |
| **Orientation supplement** | Adaptive reorientation for agents <5min old | AD-567g (`_orientation_supplement`) |
| **Night Orders** | Conn scope, escalation triggers, remaining hours (conn-holder only) | AD-471 |
| **Cognitive skill catalog** | Available triggers, department/rank-gated, proficiency labels | AD-596b |

#### On-Demand (QUERY Step — Zero LLM Cost, Deterministic)

| Query | Data Returned | Implementation |
|-------|--------------|----------------|
| `thread_metadata` | Ward Room thread object | AD-644 QUERY ops |
| `thread_activity` | Recent posts in channel (since timestamp, limit) | AD-644 QUERY ops |
| `comm_stats` | Agent communication statistics | AD-644 QUERY ops |
| `credibility` | Agent credibility score | AD-644 QUERY ops |
| `unread_counts` | Per-channel unread message counts | AD-644 QUERY ops |
| `unread_dms` | Recent unread DMs (limit 3) | AD-644 QUERY ops |
| `trust_score` | Current trust score | AD-644 QUERY ops |
| `trust_summary` | All agents' trust scores | AD-644 QUERY ops |
| `posts_by_author` | Author's recent posts (limit 5) | AD-644 QUERY ops |
| `self_monitoring` | DM self-repetition check, zone note | AD-646b |
| `introspective_telemetry` | Full telemetry (self-referential threads only) | AD-646b |

#### Token Budget Breakdown (Typical Proactive Cycle)

| Component | Approximate Tokens |
|-----------|-------------------|
| Agent working memory | 3,000 |
| Temporal context | 200-300 |
| Agent metrics + ontology | 350-500 |
| Episodic memories | 2,000-4,000 (tier-dependent) |
| Ward Room activity | 500-1,000 |
| Self-monitoring | 300-500 |
| Alerts + events + infrastructure | 200-400 |
| Source attribution + guards | 100-200 |
| **Total typical sensorium** | **~5,000-10,000 tokens per cycle** |

### 4.3 What's Actually Missing (~20%)

Despite this comprehensive stack, five specific gaps remain:

**1. Named buffer architecture (structural)**
Working memory is a prioritized flat list rendered as a monolithic block, not named
buffers. The data exists but the cognitive chain reads "working memory context" — it
can't selectively access "just the duty context" or "just the social context." Priority
tiers (engagements > actions > reasoning > conversations > observations > state > events)
provide implicit structure, but ANALYZE receives the whole block and must parse it.

**2. Salience filtering (selection)**
No scoring mechanism for what enters working memory. Ring buffer eviction is FIFO within
priority tiers — an urgent alert from 30 seconds ago and a routine event from 30 seconds
ago get equal treatment within their tier. There's no `salience = f(relevance, recency,
novelty, urgency, social)` scoring. Events don't compete for attention.

**3. Cross-thread conclusion sharing (coordination)**
`ActiveEngagement` tracks *existence* of concurrent threads (boolean: "am I already
handling this thread?") but doesn't share *conclusions* between threads. Thread A
(Ward Room reply) can't see that Thread B (proactive duty) just concluded "latency
anomaly is queue-pressure related." Each thread reasons from its own initial context
snapshot, unaware of what its siblings determined.

**4. Memory metabolism (maintenance)**
No active decay, triage, or audit of working memory. Ring buffers evict by count
(oldest out), not by relevance decay. A low-value observation from 2 minutes ago
persists alongside a high-value conclusion from 10 minutes ago until the ring is full.
Dream consolidation handles episodic memory but working memory has no metabolic cycle.

| Operation | ProbOS Status |
|-----------|--------------|
| **TRIAGE** | Missing — all events enter at equal priority within their category |
| **DECAY** | Missing — no time-weighted salience reduction |
| **CONSOLIDATE** | Partial — dream consolidation (episodic only, not WM) |
| **AUDIT** | Missing — no consistency checking |
| **FORGET** | Passive only — ring buffer FIFO eviction |

**5. Capacity signaling (load management)**
No concurrency ceiling or load awareness. An agent doesn't know "I'm running 5 threads
and should queue the 6th." No signal to intent routing that an agent is overloaded.
No priority arbitration when two threads compete for the same resource (e.g., both
want to post to the same Ward Room channel).

### 4.4 What's NOT Missing (Correcting the Research Assumptions)

The initial research document assumed several gaps that the audit revealed are already
addressed:

- **"No ambient ship awareness"** — Actually present via AD-644 Phase 3. Agents receive
  Ward Room activity, alerts, events, and infrastructure status every proactive cycle.
  The gap is that this is snapshot-based (at cycle start) rather than continuously
  accumulated, but the data is there.

- **"No structured self-state"** — Actually present via AD-646 cognitive baseline.
  Trust, rank, agency, zone, temporal context, and identity are injected every cycle
  across all pathways. This IS the sensorium — it just wasn't named as such.

- **"No self-monitoring"** — Extensively implemented via AD-504. Recent posts,
  self-similarity scoring, zone tracking, notebook index, memory state — all injected
  on proactive cycles.

- **"No source attribution"** — Comprehensive via AD-568d. Every piece of context
  is labeled with its knowledge source (episodic/procedural/oracle/training).

---

## 5. The Ambient Awareness Principle

### 5.1 Definition

**Ambient awareness** is the continuous, low-cost perception of operational context
that an agent maintains without explicit attention or queries. It is the cognitive
equivalent of peripheral vision — you're not looking at it directly, but you'd notice
if something changed.

For ProbOS agents, ambient awareness encompasses:

| Awareness Domain | What the Agent Knows | How It Knows |
|-----------------|---------------------|-------------|
| **Self-State** | Trust level, zone, health, active duties | Sensorium injection (per-cycle) |
| **Concurrent Threads** | What other thought instances are working on | Working memory engagement registry |
| **Ship State** | System health, active alerts, recent events | Background event accumulation |
| **Social Context** | Who's active, what's being discussed, recent decisions | Ward Room monitoring + peer state |
| **Temporal Context** | Time of day, time since last action, lifecycle phase | AD-502 temporal header |

### 5.2 The Three Layers of Ambient Awareness

**Layer 1 — Proprioception (Self-Awareness)** — ~90% implemented
The agent's awareness of its own state. Extensively implemented: trust, rank, zone,
temporal context, agency level, identity/ontology, source attribution, cognitive skill
catalog, self-monitoring (recent posts, self-similarity, memory state, notebook index),
infrastructure health, communication proficiency. (AD-504, AD-502, AD-573, AD-576,
AD-568d, AD-625, AD-596b). Missing: formal naming as "sensorium" and sensorium-level
health/token metrics.

**Layer 2 — Interoception (Intra-Agent Thread Awareness)** — ~30% implemented
The agent's awareness of its own concurrent processes. BF-239 `ActiveEngagement`
provides thread existence tracking (boolean duplicate prevention). AD-572 renders game/
task board states for active engagements. Missing: cross-thread context sharing,
conclusion propagation, workload awareness, concurrency ceiling.

**Layer 3 — Exteroception (Ship & Social Awareness)** — ~80% implemented
The agent's awareness of the external operational environment. AD-644 Phase 3 injects
Ward Room activity, bridge alerts, system events, and infrastructure status every
proactive cycle. AD-644 QUERY provides 11 on-demand queries (thread metadata, comm
stats, credibility, unread counts, trust scores). Missing: continuous background
accumulation (currently snapshot-based at cycle start), salience-filtered event stream.

### 5.3 Design Principle: Coherence Over Volume

Echo's clinical observation: "The limiting factor isn't volume, it's coherence. An agent
can hold a lot of signals if they're organized around a clear current task. What degrades
performance is unresolved competing priorities."

This aligns with ACT-R's buffer model and GWT's bottleneck principle. The design
principle is:

> **An agent's working memory should contain a small number of coherent, high-fidelity
> chunks organized around the current task — not a comprehensive but diffuse dump of
> everything that recently happened.**

Practically:
- **3-5 structured buffers**, each holding one coherent chunk
- **Salience filtering** that selects what enters each buffer
- **Active eviction** of information that isn't relevant to the current task
- **On-demand retrieval** for anything not in buffers (episodic memory, Ship's Records)

---

## 6. Optimal Working Memory Architecture

### 6.1 The Buffer Model

Inspired by ACT-R, adapted for ProbOS's concurrent processing model:

```
┌─────────────────────────────────────────────────────────┐
│                  Agent Sensorium                         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐ │
│  │  Duty    │ │  Social  │ │  Ship    │ │ Engagement │ │
│  │  Buffer  │ │  Buffer  │ │  Buffer  │ │  Registry  │ │
│  │          │ │          │ │          │ │            │ │
│  │ Current  │ │ Active   │ │ Health,  │ │ Thread A   │ │
│  │ duty,    │ │ thread,  │ │ alerts,  │ │ Thread B   │ │
│  │ deadline │ │ recent   │ │ recent   │ │ Thread C   │ │
│  │ progress │ │ DMs,     │ │ events,  │ │ ...        │ │
│  │          │ │ WR post  │ │ crew     │ │            │ │
│  └──────────┘ └──────────┘ └──────────┘ └────────────┘ │
│                        ↕                                │
│              Salience Filter (GWT gate)                 │
│                        ↕                                │
│  ┌─────────────────────────────────────────────────────┐ │
│  │              Background Event Stream                │ │
│  │   NATS events → accumulate → filter → promote       │ │
│  └─────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

### 6.2 Buffer Specifications

**Duty Buffer** — What am I supposed to be doing right now?
- Contents: Current duty type, deadline, progress markers, relevant standing orders
- Update trigger: Duty cycle start, duty completion, new task assignment
- Capacity: 1 active duty + 1 pending
- Source: Duty schedule, Bill system, Standing Orders

**Social Buffer** — What's the current social context?
- Contents: Active conversation thread (if any), recent DMs, Ward Room topic
- Update trigger: New message addressed to agent, thread update, DM received
- Capacity: 1 active thread + recent context (token-budgeted)
- Source: Ward Room, DM handler, intent dispatch

**Ship Buffer** — What's happening on the ship?
- Contents: System health summary, active alerts, recent significant events
- Update trigger: Health status change, new alert, significant event emission
- Capacity: Fixed-size snapshot (not growing log)
- Source: VitalsMonitor, BridgeAlerts, NATS event bus (filtered)

**Engagement Registry** — What are my concurrent selves doing?
- Contents: List of active thought threads with type, target, and status
- Update trigger: Thread start, thread complete, thread blocked
- Capacity: Unbounded (bounded by actual concurrency, typically 1-5)
- Source: Working memory ActiveEngagement tracking

### 6.3 The Salience Filter

Not all events deserve buffer promotion. The salience filter determines what enters
the agent's awareness based on:

1. **Role relevance:** Does this event relate to my department/duties?
2. **Recency:** How recently did this happen? (Exponential decay)
3. **Novelty:** Is this new information or a repeat? (AD-493 Novelty Gate concept)
4. **Urgency:** Is this time-sensitive? (Alert severity, deadline proximity)
5. **Social relevance:** Does this involve agents I have high trust with?

**Scoring:** `salience = w₁·relevance + w₂·recency + w₃·novelty + w₄·urgency + w₅·social`

Events above a threshold promote into the appropriate buffer. Events below threshold
accumulate in the background stream for potential batch review during idle cycles
(connects to AD-633 Predictive Cognitive Branching).

### 6.4 Cross-Thread Conclusion Sharing

When a thought thread reaches a conclusion or makes a decision, that conclusion should
be visible to other concurrent threads of the same agent. This is the "spine" function —
coordination without requiring thread-to-thread messaging.

**Mechanism:** Conclusions are written to a `ConclusionLog` in working memory with:
- `thread_id`: Which thought thread produced this
- `conclusion_type`: decision, observation, escalation, completion
- `summary`: One-line natural language summary
- `timestamp`: When concluded
- `relevance_tags`: Topic tags for filtering

Other threads receive the conclusion log as part of their sensorium injection. They
don't need to act on it, but they can see it — ambient awareness of what their other
selves have determined.

**Example:** Thread A (Ward Room) concludes "I've already posted my analysis of the
latency anomaly." Thread B (Proactive duty) sees this conclusion and can skip
redundant analysis of the same anomaly. Without this sharing, Thread B would
independently re-derive the same analysis.

---

## 7. The Orchestrator Within

### 7.1 Self-Orchestration vs. External Orchestration

In most multi-agent frameworks, an external orchestrator decides what each agent works
on. ProbOS agents are more autonomous — they receive intents and decide how to respond.
But with concurrent processing, the agent needs to be **its own orchestrator.**

This is the divergence from human cognition that makes ProbOS novel. A human puts
thoughts on the back burner because they can't truly parallelize. A ProbOS agent
doesn't need to — it can run all thoughts simultaneously. But it needs:

1. **Workload awareness:** How many threads am I running? Am I at capacity?
2. **Priority arbitration:** If two threads need the same resource (e.g., posting to
   the same channel), which goes first?
3. **Redundancy detection:** Are any of my threads working on the same problem?
4. **Completion tracking:** Which threads have finished? What did they produce?

### 7.2 Diminishing Returns

Echo raised the question: is there a point of diminishing returns on concurrent threads?

**Yes, and the ceiling is probably lower than expected.** Based on the literature:

- **ACT-R:** Strictly serial — one production at a time. The serial bottleneck is
  functional, forcing integration.
- **LIDA:** Multiple codelets run in parallel, but workspace access is serial —
  only one coalition broadcasts at a time.
- **Human analogy:** Even skilled multitaskers degrade above 3-4 concurrent tasks
  (Wickens' Multiple Resource Theory).

**Proposed ProbOS heuristic:** An agent should handle at most **3-5 concurrent threads**
effectively. Beyond that, the working memory overhead of tracking all threads exceeds
the value of parallelism. Excess intents should queue rather than spawn new threads.

This is configurable — a Bridge officer processing strategic decisions may cap at 2-3,
while an Operations agent handling routine dispatches may handle 5-7. The threshold
could be tied to task complexity, not just count.

### 7.3 The Capacity Signal

When an agent approaches its concurrency ceiling, it should emit a signal:

```
AGENT_CAPACITY_APPROACHING: {agent_id, active_threads: 4, max_threads: 5}
```

This enables:
- Intent routing to prefer less-loaded agents (Hebbian + capacity weighting)
- Chiefs to redistribute work across their department
- The agent itself to prioritize and potentially defer low-priority threads

---

## 8. Memory Metabolism

### 8.1 The Missing Operations

ProbOS has sophisticated memory storage but limited memory *management.* The literature
converges on memory as a metabolic process requiring ongoing maintenance:

| Operation | Definition | ProbOS Status |
|-----------|-----------|---------------|
| **TRIAGE** | Score incoming information for relevance and priority | Missing — all events treated equally |
| **DECAY** | Reduce salience of old information over time | Missing — ring buffer eviction only |
| **CONSOLIDATE** | Merge similar entries into generalized patterns | Partial — dream consolidation (episodic) |
| **AUDIT** | Check memory consistency, detect contradictions | Missing |
| **FORGET** | Actively remove low-value information | Missing — only passive ring eviction |

### 8.2 Working Memory Lifecycle

A working memory entry should follow a lifecycle:

```
Event occurs → TRIAGE (score salience) →
  High salience: Promote to buffer → Active use → DECAY over cycles →
    Still relevant: Refresh → Continue
    No longer relevant: CONSOLIDATE into episodic → Remove from WM
  Low salience: Background accumulation → Batch review on idle →
    Pattern detected: Promote to buffer
    No pattern: FORGET
```

### 8.3 Dream Integration

Dream consolidation currently operates on episodic memory. Working memory should
participate:

- **Pre-dream:** Flush active working memory entries to episodic memory as session
  summaries. "Here's what I was thinking about today."
- **During dream:** Working memory patterns (what did I track most? what caused
  context switches?) inform consolidation priorities.
- **Post-dream:** Dream insights seed the next session's working memory priming.
  "Yesterday I learned that latency anomalies correlate with queue pressure."

---

## 9. Relationship to Existing ADs

### 9.1 ADs Already Delivering Sensorium Components (~80%)

These ADs collectively implement the agent sensorium. They were designed independently
but converge on the same pattern — structured, always-on self-state injection.

| AD | What It Delivers | Status |
|----|-----------------|--------|
| AD-573 | **Working memory foundation.** Ring buffers with priority tiers, `render_context()` with 3000-token budget. The structural substrate for all ambient awareness. | Complete |
| AD-644 | **Situation awareness pipeline.** 23 QUERY operations + proactive context injection (Ward Room activity, alerts, events). This IS exteroception (Layer 3). | Complete |
| AD-646 | **Cognitive baseline.** Unified context injection across ALL pathways (DM, Ward Room, proactive). Ensures every thought thread gets the same sensorium snapshot. The unnamed sensorium. | Complete |
| AD-504 | **Self-monitoring.** Recent posts, Jaccard self-similarity, zone tracking, notebook index, memory state. This IS proprioception (Layer 1). | Complete |
| AD-502 | **Temporal context.** UTC time, birth age, uptime, last action, crew manifest. Always-on temporal proprioception. | Complete |
| AD-576 | **Infrastructure status.** LLM health, consecutive failures, degradation signals. Operational proprioception. | Complete |
| AD-568d | **Source attribution.** Every context piece labeled with knowledge source. Epistemic proprioception. | Complete |
| AD-625 | **Communication proficiency.** Language register guidance. Social proprioception. | Complete |
| BF-239 | **Thread engagement tracking.** `ActiveEngagement` in working memory prevents duplicate processing. First interoception (Layer 2) — the observation that triggered this research. | Complete |
| AD-572 | **Game/task state rendering.** Active engagement board states rendered in working memory. Extended interoception. | Complete |

### 9.2 ADs That Extend the Remaining ~20%

These ADs, when implemented, will fill the specific gaps identified in Section 4.3.
The Ambient Awareness wave (AD-666 through AD-672) delivers the core infrastructure;
existing ADs below provide complementary components.

| AD | What It Will Deliver | Gap Addressed |
|----|---------------------|---------------|
| **AD-666** (#347) | **Sensorium formalization.** Name the pattern, consolidate injections, add health metrics. | Phase 1 completion |
| **AD-667** (#348) | **Named buffers.** Duty/Social/Ship/Engagement with per-buffer token budgets. | Gap 1: Named buffers |
| **AD-668** (#349) | **Salience filter.** Scoring function for buffer promotion. | Gap 2: Salience filtering |
| **AD-669** (#350) | **Conclusion sharing.** ConclusionLog for intra-agent thread coordination. | Gap 3: Cross-thread coordination |
| **AD-670** (#351) | **Memory metabolism.** TRIAGE/DECAY/AUDIT/FORGET operations. | Gap 4: Memory metabolism |
| **AD-671** (#352) | **Dream-WM integration.** Bidirectional dream-working memory pipeline. | Gap 4: Memory metabolism |
| **AD-672** (#353) | **Concurrency management.** Ceiling, capacity signals, priority arbitration. | Gap 5: Capacity signaling |
| AD-493 | **Novelty gate.** Novelty scoring component of the salience filter (AD-668). | Gap 2: Salience filtering |
| AD-492 | **Correlation IDs.** Cross-thread trace linking for AD-669 conclusion sharing. | Gap 3: Cross-thread coordination |
| AD-633 | **Predictive branching.** Idle-time consumer of AD-668's background event stream. | Gap 2: Salience filtering |
| AD-632 | **Cognitive chain.** Consumer of AD-667 named buffers. Selective access per step. | Gap 1: Named buffers |

### 9.3 Emerging Connection: The Sensorium Arc

The implementation audit reveals an unplanned but coherent architectural arc:

```
AD-573 (WM foundation) → AD-644 (SA pipeline) → AD-646 (unified baseline)
     ↓                        ↓                        ↓
 Structure              Exteroception            Integration
 "Where to put it"      "What's out there"       "Same for all paths"
                              ↓
                    AD-504 (self-monitoring)
                              ↓
                      Proprioception
                      "What am I doing"
                              ↓
                    BF-239 (thread awareness)
                              ↓
                      Interoception
                      "What are my threads doing"
```

This wasn't designed as a sensorium — it emerged. The research contribution is
naming the pattern and identifying what's missing to complete it.

---

## 10. Proposed Future Work

### Implementation Status Overview

The 5-phase plan is reframed to reflect the implementation audit. Phase 1 is ~80%
complete through organically evolved ADs. The real forward work is Phases 2-5.

### Phase 1: Agent Sensorium — ~80% COMPLETE → AD-666 (#347)

**What exists:** Structured self-state injection across all cognitive pathways (AD-646).
Trust, zone, temporal context, engagement tracking, self-monitoring, infrastructure
status, source attribution, ontology identity — all injected every cycle. This IS the
sensorium; it emerged without being named as such.

**Remaining items (~20% of Phase 1):**
- **Name the pattern.** Formalize the existing context injection as "Agent Sensorium"
  in code and documentation. Currently it's ~15 private methods in `CognitiveAgent`;
  it should be a named, auditable subsystem.
- **Consolidate injection ordering.** The 23+ context injections in `_build_prompt_text`
  grew organically. Audit for redundancy, ordering consistency, and token waste.
- **Add sensorium health metric.** Track injection token count per cycle. Alert if
  sensorium exceeds budget (currently uncapped beyond WM's 3000-token limit).

### Phase 2: Named Buffers with Salience Filtering — AD-667 (#348) + AD-668 (#349)

Replace monolithic working memory rendering with named buffers (Duty, Social, Ship,
Engagement). Key deliverables:

- **Buffer abstraction:** Named buffer interface with per-buffer token budget, update
  triggers, and capacity limits (Section 6.2 specifications).
- **Salience scoring:** `salience = f(relevance, recency, novelty, urgency, social)`
  for event-to-buffer promotion (Section 6.3). Integrates AD-493 (novelty gate) when
  available.
- **Selective access:** Cognitive chain steps can request specific buffers instead of
  receiving the monolithic working memory block. ANALYZE gets duty + engagement;
  COMPOSE gets social + ship.
- **Token budget allocation:** Per-buffer budgets that sum to the sensorium ceiling,
  replacing the current flat 3000-token working memory limit.

**Prerequisite:** Phase 1 completion (naming and consolidation).

### Phase 3: Cross-Thread Conclusion Sharing — AD-669 (#350)

ConclusionLog mechanism for intra-agent coordination (Section 6.4). Key deliverables:

- **ConclusionLog in working memory:** Thread conclusions (decisions, observations,
  escalations, completions) written to a shared log visible to sibling threads.
- **Redundancy detection:** Before starting work, thread checks conclusions from
  siblings for overlapping analysis. Prevents the BF-239-class duplicate response.
- **Correlation ID integration:** Uses AD-492 correlation IDs (when available) to
  link related threads and their conclusions.
- **Conclusion decay:** Conclusions expire after configurable TTL. Old conclusions
  don't pollute future threads' awareness.

**Prerequisite:** Phase 2 (conclusions need the Engagement buffer).

### Phase 4: Memory Metabolism — AD-670 (#351) + AD-671 (#352)

Background working memory maintenance operations (Section 8). Key deliverables:

- **TRIAGE:** Score incoming events for relevance and priority before buffer entry.
- **DECAY:** Time-weighted salience reduction. Recent events outweigh stale ones
  within the same priority tier.
- **AUDIT:** Consistency checking — detect contradictory entries in working memory.
- **FORGET:** Active removal of low-value entries (vs. current passive FIFO eviction).
- **Dream integration:** Pre-dream WM flush to episodic memory. Post-dream WM
  priming from dream insights.

**Prerequisite:** Phase 2 (metabolism operates on named buffers, not flat ring).

### Phase 5: Capacity Management — AD-672 (#353)

Per-agent concurrency control (Section 7). Key deliverables:

- **Concurrency ceiling:** Configurable per-agent max threads (default 3-5, role-tuned).
- **Capacity signal:** `AGENT_CAPACITY_APPROACHING` event for load-aware routing.
- **Priority arbitration:** When two threads compete for the same resource (e.g.,
  posting to the same channel), priority resolution instead of race condition.
- **Queue management:** Excess intents queue with priority ordering rather than
  spawning unbounded threads.

**Prerequisite:** Phase 3 (capacity management needs thread awareness from
conclusion sharing to make informed scheduling decisions).

---

## 11. Key Principles (Universal)

These principles should guide any future working memory or ambient awareness AD:

1. **Coherence over volume.** A small number of high-fidelity, task-relevant chunks
   beats a comprehensive but unfocused context dump. (Echo, GWT, ACT-R)

2. **The bottleneck is functional.** Not everything should reach awareness. Salience
   filtering prevents cognitive cacophony. (GWT, Wickens)

3. **Ambient perception ≠ active attention.** Agents should passively accumulate
   context without consuming cognitive resources. The sensorium is injected, not
   queried. (Springdrift, Endsley L1)

4. **Working memory needs metabolism.** Storage without curation leads to
   entrenchment and noise. Triage, decay, consolidation, and forgetting are
   features, not bugs. (FSFM, Memory as Metabolism)

5. **The spine connects, it doesn't think.** Working memory is infrastructure for
   coherent cognition, not a reasoning system itself. It coordinates threads; the
   threads do the thinking. (Spine metaphor)

6. **Smaller crews with deeper awareness outperform larger crews without it.**
   Quality of memory architecture matters more than agent headcount. (Wu et al. 2026)

7. **Concurrent thought requires self-orchestration.** Agents with parallel threads
   need workload awareness, priority arbitration, redundancy detection, and
   completion tracking — they must orchestrate themselves. (Novel — no prior work
   addresses sovereign AI agents with concurrent cognition and persistent identity.)

---

## 12. Sources

### Cognitive Architecture Foundations
- Baars, B.J. (1988). *A Cognitive Theory of Consciousness.* (Global Workspace Theory)
- Endsley, M.R. (1995). "Toward a Theory of Situation Awareness in Dynamic Systems."
- Anderson, J.R. (1993+). ACT-R Cognitive Architecture.
- Laird, J.E. (2012). *The Soar Cognitive Architecture.*
- Franklin, S. (2003+). LIDA / IDA — Learning Intelligent Distribution Agent.
- Wickens, C.D. (2002). "Multiple Resources and Performance Prediction."
- Klein, G.A. (1993). Recognition-Primed Decision Model.
- Neisser, U. (1976). *Cognition and Reality.*
- Miller, G.A. (1956). "The Magical Number Seven, Plus or Minus Two."
- Cowan, N. (2001). "The Magical Number 4 in Short-Term Memory."

### Recent AI Agent Research (2023-2026)
- Ma et al. (2026). BrainMem: Brain-Inspired Evolving Memory for Embodied Agents.
- Li et al. (2026). Escaping the Context Bottleneck: Active Context Curation via RL.
- Zhu et al. (2026). LightThinker++: From Reasoning Compression to Memory Management.
- Hou et al. (2026). WMF-AM: Working Memory Fidelity-Active Manipulation.
- Yan et al. (2026). AdaMem: Adaptive User-Centric Memory for Long-Horizon Dialogue.
- Brady, S. (2026). Springdrift: Ambient Self-Perception. (arXiv:2604.04660)
- Theater of Mind: Global Workspace Agents. (2026, arXiv:2604.08206)
- CogniPair: GWT for Social LLM Agents. (2025, arXiv:2506.03543)
- Xu, H. (2026). Mesh Memory Protocol.
- Park, J.S. et al. (2023). Generative Agents. (arXiv:2304.03442)
- Wu, S. et al. (2026). Scaling Teams or Scaling Time? Memory in Multi-Agent Systems.
- Nguyen et al. (2026). Dynamic Theory of Mind as Temporal Memory Problem.
- Gu et al. (2026). FSFM: Framework for Selective Forgetting in Agent Memory.
- Miteski, S. (2026). Memory as Metabolism: Companion Knowledge Systems.
- Park, Y.B. (2026). Graph-Native Cognitive Memory with Formal Belief Revision.

### ProbOS Internal Research
- AD-644: Agent Situation Awareness Architecture (Galliher, 2026-04-18)
- AD-504/587/588/589: Metacognitive Architecture — Grounded Self-Knowledge
- AD-632: Cognitive Sub-Task Protocol (SOAR-inspired three-level model)
- AD-633: Predictive Cognitive Branching (prospective reasoning)
- AD-573: Unified Agent Working Memory (implementation spec)
- AD-502: Temporal Context Injection
- BF-239: Ward Room Thread Engagement Tracking (observation trigger)
- Memory Architecture (docs/architecture/memory.md) — Six-layer stack
- Cognitive Architecture (docs/architecture/cognitive.md) — Pipeline overview
