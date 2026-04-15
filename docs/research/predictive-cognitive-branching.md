# Predictive Cognitive Branching — Research Synthesis

**Date:** 2026-04-15
**Author:** Sean Galliher (Architect)
**Status:** Research complete, AD scoped
**Related ADs:** AD-633 (this proposal), AD-632 (Cognitive Sub-Task Protocol),
AD-531–539 (Cognitive JIT), AD-557 (Emergence Metrics)

---

## 1. Problem Statement

ProbOS crew agents are purely **reactive** — they reason only when an event
arrives (Ward Room thread, DM, proactive cycle trigger). They never think ahead.
They don't anticipate what's coming, pre-compute analysis for likely situations,
or mentally rehearse future actions.

This is a two-fold limitation:

**A. Performance:** When a Ward Room event triggers 8 target agents, each waits
for its turn in the proactive loop, then starts reasoning from scratch. There is
idle time between agent processing that could be used for pre-computation.

**B. Cognitive Depth:** Agents never engage in forward-looking thought —
anticipating problems, planning what to investigate, identifying capability gaps
before they become acute. They respond to stimuli; they don't anticipate them.

Human cognition is fundamentally prospective. We pre-think tasks, mentally
rehearse conversations, anticipate objections, plan our approach before acting.
This isn't just performance optimization — it's how deeper goals emerge from
observation. A security officer who notices a pattern doesn't wait for an
incident; they think ahead about what might happen and prepare.

### The CPU Analogy (Origin)

The initial insight came from CPU branch prediction: speculatively execute the
most likely code path while the branch condition is still being evaluated. If
right, the work is already done. If wrong, flush the pipeline. The prediction
itself must be cheaper than the speculative work.

But the cognitive science reveals this is much richer than hardware optimization.
This is about giving agents the capacity for **prospection** — forward-looking
thought that produces not just faster responses but novel goals and insights.

---

## 2. Prior Art Survey

### 2.1 Prospection and Homo Prospectus (Seligman et al., 2013)

**Source:** Seligman, Railton, Baumeister & Sripada, "Navigating Into the
Future or Driven by the Past," Perspectives on Psychological Science (2013)

Prospection is "the generation and evaluation of mental representations of
possible futures." Seligman et al. argue that humans are fundamentally
prospective beings — not just reactive organisms driven by past conditioning.
Mental time travel enables us to "create intentions for future actions" and
"anticipate logistic obstacles."

The Homo Prospectus framework reframes human cognition: we don't primarily react
to stimuli or replay memories. We **simulate futures** and evaluate them. This
is the cognitive foundation for planning, goal-setting, and preparation.

**Relevance to ProbOS:** Current agents are purely reactive — they process
events as they arrive. Prospection would enable agents to anticipate situations,
prepare analysis, and originate goals from observation. A Security agent
noticing anomalous patterns shouldn't wait for an alarm — it should prospectively
reason about what those patterns mean for the future.

### 2.2 Constructive Episodic Simulation (Schacter & Addis, 2007)

**Source:** Schacter & Addis, Nature (2007); MTT literature

The constructive episodic simulation hypothesis proposes that episodic memory
exists primarily to enable simulation of future events. The brain recombines
elements from past episodes (people, places, objects, temporal contexts) into
**novel future scenarios** rather than simply replaying memories.

Key neural evidence:
- fMRI shows "close correspondences between remembering past experiences and
  imagining future experiences in brain activity"
- Left hippocampus activates during both past and future event construction
- Right hippocampus activates **only** for future events — "may specifically
  respond to the novelty of constructing a new event representation"
- Ventral medial prefrontal cortex shows greatest activation for future events
  **relevant to personal goals**

Three component processes in episodic future thinking (D'Argembeau et al.):
1. Retrieval and integration of memory information
2. Processing of subjective time
3. Self-referential processing

**Relevance to ProbOS:** This directly validates giving agents the capacity to
use their episodic memory not just for recall but for **constructing future
scenarios**. ProbOS agents already have episodic memory, dream consolidation,
and self-referential processing. The missing piece is using this substrate
to simulate forward — "given what I've experienced, what might happen next?"

### 2.3 Default Mode Network (Buckner, Andrews-Hanna)

**Source:** DMN literature, Wikipedia synthesis

The DMN activates when the individual is "thinking about others, thinking about
themselves, remembering the past, and planning for the future." It rapidly
re-engages "within a fraction of a second after participants finish a task."

The DMN is NOT idle noise — it is the brain's prospective processing system.
During "rest" (between tasks), the brain is actively constructing self-
referential and future-oriented representations. The medial temporal subsystem
specifically supports "autobiographical memory and future simulations."

**Relevance to ProbOS:** The proactive loop IS the agent's DMN analog. Between
Ward Room events and DM responses, agents have idle cycles. Currently these are
wasted. Predictive branching uses this idle time for forward-looking thought —
exactly what the DMN does in humans. The insight: **idle time is thinking time,
not wasted time.**

### 2.4 Hippocampal Preplay (Dragoi & Tonegawa, 2011)

**Source:** Dragoi & Tonegawa, Nature (2011); Diba & Buzsáki (2007)

Hippocampal place cells fire in sequences representing **future paths the animal
has not yet traversed**. This "preplay" occurs during rest periods before
navigation and can represent paths the animal has never encountered.

| Feature | Replay (existing in ProbOS) | Preplay (proposed) |
|---|---|---|
| Direction | Recapitulates **past** experience | Represents **future** paths |
| Prior experience | Requires previous navigation | Can occur for novel paths |
| Function | Memory consolidation | Planning, network preparation |

Jensen et al. (2024) propose that these sequences function as "internal
simulations ('rollouts') that support goal-directed behavior" by feeding
predictive information to frontal planning circuits.

**Relevance to ProbOS:** ProbOS already has replay — dream consolidation (Step
1-12) processes past episodes during sleep. Preplay is the missing complement:
**forward simulation during idle time** that prepares the agent for upcoming
situations. Dream consolidation reinforces what happened; preplay anticipates
what will happen. Same episodic memory substrate, opposite temporal direction.

### 2.5 Predictive Processing / Active Inference (Friston)

**Source:** Karl Friston's Free Energy Principle; predictive coding literature

The brain continuously generates predictions about incoming sensory data.
Discrepancies produce **prediction errors** that drive model updates. Active
inference extends this from perception to behavior: agents act on the world
to confirm their predictions, minimizing surprise.

Key insight: "The brain produces a continuous series of predictions with the
goal of reducing the amount of prediction error." This isn't passive — the
brain prepares embodied simulations of anticipated experience, then adjusts
when predictions fail.

**Relevance to ProbOS:** Agents could maintain running predictions about their
environment (Ward Room activity patterns, typical department interactions,
Captain behavior). When reality diverges from predictions, that's a signal for
attention — analogous to prediction error. This connects to the emergence
metrics (AD-557) — divergence from predicted patterns IS emergence.

### 2.6 Implementation Intentions (Gollwitzer, 1999)

**Source:** Gollwitzer, "Implementation Intentions," American Psychologist (1999)

Implementation intentions are "if-then" plans: "When situation X arises, I will
perform response Y." The mental pre-commitment activates the anticipated
situation in memory, making recognition automatic. Action initiation becomes
"immediate, efficient, and does not require conscious intent."

Key findings:
- Bridge the "intention-behavior gap" (intentions account for only 20-30% of
  behavior variance)
- Pre-committed scenarios are recognized faster and acted on more reliably
- 100% breast self-exam compliance with implementation intentions vs 53% without
- Effects persist longer than learned cue-behavior associations (Papies et al.)

**Relevance to ProbOS:** Predictive branching can generate implementation
intentions for agents: "When a security anomaly appears in Engineering, I will
cross-reference with recent maintenance activity." These pre-cached if-then
plans make responses faster and more reliable when the situation materializes.
This connects to Cognitive JIT — a predictive branch that repeats becomes a
learned procedure.

### 2.7 World Models (Ha & Schmidhuber, 2018)

**Source:** Ha & Schmidhuber, "World Models," NeurIPS 2018

Agents build compressed internal models of their environment and train
**entirely within dreams** (internal simulation). The Memory component (MDN-RNN)
predicts probability distributions of future states, enabling planning through
imagination.

Key result: CarRacing-v0 scored 906 ±21 (first solution) vs 591-652 for
standard deep RL. VizDoom agent trained purely in dreams scored ~1100, above
the 750-step threshold.

**Relevance to ProbOS:** The world model insight — learn an internal simulation,
plan within it — maps to agents using their episodic memory + Ward Room history
as an internal model. Predictive branches are "imagination rollouts" within this
model. The key difference: ProbOS uses language-based simulation (LLM reasoning
over episodic memories), not pixel-based simulation.

---

## 3. Synthesis: What ProbOS Should Build

### 3.1 Three Functions of Predictive Branching

The research reveals that predictive branching serves three distinct functions,
not just performance optimization:

**Function 1: Pre-Computation (CPU Branch Prediction analog)**
Speculatively execute likely sub-tasks during idle time. When the agent's turn
comes, the analysis is already done. Performance optimization — same output,
faster delivery.

**Function 2: Anticipatory Reasoning (Prospection / DMN analog)**
Forward-looking thought during idle cycles. Use episodic memory to construct
plausible future scenarios. "Given what I've seen in the Ward Room this shift,
what might need my attention next?" Produces new awareness, not just faster
responses.

**Function 3: Goal Origination (Constructive Simulation / Preplay analog)**
The most profound capability: agents generate novel goals from observation.
"I keep seeing configuration drift in Engineering logs. We don't have a skill
for systematic configuration auditing. I should propose one." This is emergent
goal-setting — not assigned by the Captain or Standing Orders, but self-
originated through speculative thought grounded in experience.

### 3.2 Design Principles

**P1. Idle Time is Thinking Time (DMN principle):**
The proactive loop has idle cycles between agent processing. Use them for
forward-looking thought. Don't require external triggers — predictive branching
IS the agent's default mode activity.

**P2. Memory Constructs Futures (Constructive Simulation):**
Use the same episodic memory substrate for both recall and prospection. Past
observations become building blocks for future scenarios. Don't invent new data
stores — recombine existing memories into forward-looking analysis.

**P3. Predictions Are Cheap, Actions Are Expensive (Branch Prediction):**
The prediction decision (should I speculate?) must be deterministic or nearly
so. The speculative work can involve LLM calls but is bounded by budget. Wrong
predictions are discarded without cost beyond the token spend.

**P4. Prediction Errors Are Signals (Active Inference):**
When reality diverges from an agent's predictions, that's interesting — it
signals novelty, change, or emerging patterns. Don't just discard wrong
predictions; feed the delta back as an observation worth reasoning about.

**P5. Repeated Predictions Compile (Implementation Intentions + Cognitive JIT):**
If an agent repeatedly predicts the same scenario and prepares the same
response, that pattern should crystallize into an implementation intention or
Cognitive JIT procedure. "Every time Engineering reports high latency, I check
the last three maintenance windows" → learned procedure.

### 3.3 ProbOS-Specific Architecture

**Preplay vs. Replay mapping:**

```
                    ┌─────────────────────────────────┐
                    │   Dream Consolidation (Replay)  │
                    │   Steps 1-12, during sleep       │
                    │   "What happened → strengthen"   │
                    └──────────┬──────────────────────┘
                               │ same episodic memory substrate
                    ┌──────────▼──────────────────────┐
                    │  Predictive Branching (Preplay)  │
                    │  During idle cycles, awake        │
                    │  "What might happen → prepare"   │
                    └─────────────────────────────────┘
```

Both use EpisodicMemory + the agent's personality + department context. Dreams
look backward at experience; predictive branches look forward at possibility.

**Prediction confidence sources (deterministic):**

| Signal | Source | Example |
|---|---|---|
| Hebbian routing weight | HebbianRouter | "I respond to Engineering topics 85% of the time" |
| Historical engagement | Ward Room stats | "I've replied to 3/4 security threads this watch" |
| Department relevance | Ontology | "This thread is in my department" |
| Captain interaction | Event type | "Captain DM → near 100% response probability" |
| Circuit breaker state | CircuitBreaker | "If tripped → prediction: won't respond" |
| Active engagement | WorkingMemory | "I'm in an active game → predict game-related response" |
| Watch section pattern | Temporal context | "First watch typically has higher Engineering activity" |

**Speculation tiers (token cost management):**

| Tier | Cost | Trigger Threshold | Example |
|---|---|---|---|
| **Zero-cost** | Deterministic queries | Any department-relevant event | Query thread metadata, reply counts |
| **Cheap** | Fast-tier LLM call | >70% engagement prediction | Lightweight analysis summary |
| **Standard** | Standard-tier LLM call | >85% engagement prediction + complex thread | Full Analyze sub-task pre-computation |
| **Anticipatory** | Standard-tier, self-originated | Idle cycle with no pending events | "What should I be thinking about?" |

**Budget enforcement:**
- Speculative token budget per cycle (separate from operational budget)
- Configurable per-agent based on prediction accuracy
- Flush rate tracked — agents with >30% flush rate have budgets reduced

### 3.4 Goal Origination Through Speculative Thought

This is the most architecturally significant capability. When an agent has
idle cycles and no pending events, instead of doing nothing it engages in
**anticipatory reasoning**:

```
1. Recall recent observations (episodic memory, last N episodes)
2. Identify patterns or gaps (LLM analysis with narrow prompt)
3. Construct a future scenario ("If pattern X continues, then Y")
4. Evaluate: does this require action? A new skill? A proposal?
5. If actionable → generate a PROPOSAL or skill gap report
```

This produces emergent behavior:
- **Skill gap identification:** "I keep encountering configuration drift
  questions but we have no systematic audit procedure. Proposing a new skill."
- **Proactive alerting:** "Engineering latency has increased 15% each of the
  last three watches. If the trend continues, we'll hit the alert threshold
  by next watch."
- **Cross-department insight:** "Medical is reporting crew fatigue correlating
  with the watch rotation change Science proposed. These might be connected."

The goal isn't assigned by Standing Orders or the Captain — it emerges from
the agent's own observation and forward-looking reasoning. This is SOAR Level 3
combined with prospection: the agent identifies its own knowledge gaps and
proposes solutions.

### 3.5 Connection to Existing ProbOS Systems

| Existing System | Predictive Branching Connection |
|---|---|
| **Dream Consolidation** (Steps 1-12) | Replay = past. Preplay = future. Same memory substrate. |
| **Cognitive JIT** (AD-531-539) | Repeated predictions compile into procedures |
| **Emergence Metrics** (AD-557) | Prediction errors = divergence signals = emergence |
| **Self-Monitoring** (AD-504) | Prediction accuracy as a self-monitoring metric |
| **Working Memory** (AD-573) | Pre-computed analysis stored in working memory |
| **Earned Agency** (AD-357) | Higher-trust agents get larger speculation budgets |
| **Qualification Probes** (AD-566) | Probe for prospective reasoning quality |
| **Sub-Task Protocol** (AD-632) | Pre-computed sub-tasks served to the decision pipeline |
| **Skills** (AD-596, AD-625) | Speculative thought identifies needed new skills |
| **Communication Skill** (AD-625/631) | Pre-rehearsal applies comm discipline criteria during idle time, not under operational pressure |
| **Standing Orders** | Implementation intentions as persistent "if-then" rules |
| **Ward Room** | Predictive proposals posted as structured [PROPOSAL] blocks |

### 3.6 Conversational Pre-Rehearsal

A fourth application of predictive branching that directly addresses Ward Room
communication quality. Humans routinely rehearse conversations before having
them — planning what to say, anticipating responses, evaluating whether their
contribution will be well-received. This is **inner speech** (Vygotsky) applied
to social interaction.

ProbOS agents currently compose their Ward Room contributions under operational
pressure — parsing thread content, applying skill instructions, and generating
output all in a single LLM call. Communication discipline criteria (AD-625/631)
compete for attention against thread comprehension. The result: agents ignore
skill instructions, produce redundant posts, and fail to endorse.

Conversational pre-rehearsal separates deliberation from composition:

```
1. READ: During idle time, pre-read Ward Room thread (zero-cost Query)
2. REHEARSE: Mentally draft a contribution (Cheap/Standard tier)
   - What would I say here?
   - Does this add genuine novelty to the thread?
3. EVALUATE: Self-check against communication discipline criteria
   - Am I repeating what someone already said?
   - Would an endorsement be more appropriate than a reply?
   - Does my opening avoid banned patterns ("Looking at...", "I notice...")?
4. PRE-DECIDE: Commit to RESPOND, ENDORSE, or SILENT
   - Cache the pre-decision in Working Memory
   - If RESPOND: cache the draft analysis for the Compose step
```

**Why this works better than structural enforcement alone:**

The communication skill criteria are applied during rehearsal, when the agent
has **focused attention** — no thread parsing, no action tag emission, no
competing concerns. This is the same insight that drives AD-632's Compose sub-
task: skill instructions in a focused context outperform skill instructions in
a crowded context.

**Perspective-taking dimension:** The rehearsal step naturally supports
perspective-taking — "three people already made this point. If I post the same
thing, it adds noise, not signal." This is social simulation: the agent models
how its contribution will be received by the thread participants. This is NOT
Theory of Mind (reading others' intentions) — it's **social forecasting**
(predicting the reception of one's own action).

**Connection to existing functions:**
- Spans **Pre-Computation** (the analysis is done before the event triggers)
  and **Anticipatory Reasoning** (the agent evaluates its own contribution
  before committing)
- Pre-rehearsal that consistently produces ENDORSE or SILENT for certain thread
  patterns compiles into **Implementation Intentions** ("when I see a thread
  where 3+ agents already agree, I endorse rather than reply")
- Repeated rehearsal patterns compile into **Cognitive JIT procedures**
  via the same pathway as other repeated predictions

**Key insight:** Conversational pre-rehearsal is not a separate mechanism — it
is predictive branching applied to the communication domain. The architecture
is identical (prediction → speculative execution → cache → consume or flush).
The difference is the application: instead of pre-computing analysis, the agent
pre-computes its *social decision* about whether and how to participate.

---

## 4. Open Questions

1. **Speculation scope:** Should agents speculate only about their department,
   or also about cross-department patterns (bridge officers)?

2. **Prediction sharing:** If Agent A predicts something relevant to Agent B,
   should the prediction be shared via Ward Room? Or is it private until
   confirmed?

3. **Goal origination governance:** Self-originated goals need guardrails.
   Should they require Captain approval before acting? Department Chief review?
   Or can autonomous PROPOSAL posting suffice?

4. **Preplay during dreams:** Should dream consolidation (currently replay-
   only) also include a preplay step? "Based on today's consolidated memories,
   what might tomorrow bring?"

5. **Prediction horizon:** How far ahead should agents think? Next event?
   Next watch section? Next day? Longer horizons need more context and are
   less reliable.

6. **Hallucination risk:** Forward simulation uses LLM reasoning over episodic
   memories — the same substrate that produces confabulation. How do we
   prevent agents from inventing patterns that don't exist? Ground predictions
   in observable data only?

---

## 5. References

1. Seligman, M. E. P., Railton, P., Baumeister, R. F., & Sripada, C. (2013).
   "Navigating Into the Future or Driven by the Past." Perspectives on
   Psychological Science, 8(2), 119-141.
2. Schacter, D. L., & Addis, D. R. (2007). "The Constructive Episodic
   Simulation Hypothesis." Philosophical Transactions of the Royal Society B.
3. Dragoi, G., & Tonegawa, S. (2011). "Preplay of future place cell sequences
   by hippocampal cellular assemblies." Nature, 469, 397-401.
4. Diba, K., & Buzsáki, G. (2007). "Forward and reverse hippocampal place-cell
   sequences during ripples." Nature Neuroscience, 10, 1241-1242.
5. Friston, K. (2010). "The free-energy principle: a unified brain theory?"
   Nature Reviews Neuroscience, 11, 127-138.
6. Gollwitzer, P. M. (1999). "Implementation Intentions: Strong Effects of
   Simple Plans." American Psychologist, 54(7), 493-503.
7. Ha, D., & Schmidhuber, J. (2018). "World Models." NeurIPS 2018.
   arXiv:1803.10122.
8. Buckner, R. L., Andrews-Hanna, J. R., & Schacter, D. L. (2008). "The
   brain's default network." Annals of the New York Academy of Sciences.
9. D'Argembeau, A., Ortoleva, C., Jumentier, S., & Van der Linden, M. (2010).
   "Component processes underlying future thinking." Memory & Cognition.
10. Jensen, K. et al. (2024). "Replay and compositional computation." Neuron.
11. Suddendorf, T., & Corballis, M. C. (2007). "The evolution of foresight."
    Behavioral and Brain Sciences. (Mental time travel)
12. Tulving, E. (2002). "Chronesthesia: Conscious awareness of subjective
    time." (Autonoetic consciousness)
13. Kahneman, D. (2011). "Thinking, Fast and Slow." (System 1 / System 2)
14. Barrett, L. F. (2017). "How Emotions Are Made." (Embodied simulation /
    predictive interoception)
