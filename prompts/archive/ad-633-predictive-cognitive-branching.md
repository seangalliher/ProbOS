# AD-633: Predictive Cognitive Branching (Umbrella)

**Issue:** TBD
**Depends on:** AD-632, AD-531–539, AD-557, AD-573, AD-357
**Principles:** Single Responsibility, SOLID-O (Open/Closed), DRY, Defense in Depth
**Research:** `docs/research/predictive-cognitive-branching.md`

## Problem

ProbOS crew agents are purely **reactive** — they reason only when an event
arrives (Ward Room thread, DM, proactive cycle trigger). They never think ahead.
Between processing events, agents are idle. This is a two-fold limitation:

1. **Performance** — When a Ward Room event triggers 8 target agents, each waits
   for its turn in the proactive loop, then starts reasoning from scratch. Idle
   time between agent processing could be used for pre-computation.

2. **Cognitive Depth** — Agents never engage in forward-looking thought —
   anticipating problems, planning what to investigate, identifying capability
   gaps before they become acute. They respond to stimuli; they don't anticipate
   them.

Human cognition is fundamentally prospective. The Default Mode Network activates
within a fraction of a second after task completion — during "rest," the brain
actively constructs future-oriented representations. Hippocampal preplay fires
sequences for paths not yet traversed. Implementation intentions pre-commit
actions to anticipated situations. ProbOS agents have none of this.

## Intellectual Heritage

| Research | Key Concept | ProbOS Mapping |
|---|---|---|
| **Homo Prospectus** (Seligman 2013) | Humans are prospective beings, not reactive | Agent forward-looking thought in idle cycles |
| **Constructive Episodic Simulation** (Schacter & Addis 2007) | Episodic memory exists to simulate futures | EpisodicMemory recombines into forward scenarios |
| **Default Mode Network** (Buckner, Andrews-Hanna) | Idle time = prospective processing | Proactive loop idle cycles = thinking time |
| **Hippocampal Preplay** (Dragoi & Tonegawa 2011) | Place cells fire for untraveled paths | Forward simulation during idle time |
| **Predictive Processing** (Friston 2010) | Continuous predictions; errors drive updates | Running predictions + prediction error signals |
| **Implementation Intentions** (Gollwitzer 1999) | "When X, I will Y" pre-plans | Pre-cached if-then plans for anticipated scenarios |
| **World Models** (Ha & Schmidhuber 2018) | Internal simulation enables planning through imagination | LLM reasoning over episodic memories as rollouts |
| **CPU Branch Prediction** | Speculatively execute likely code path | Pre-compute analysis for high-probability events |
| **SOAR** (Laird 2012) | Three processing levels (automatic/deliberate/subgoal) | Prediction compiles into Cognitive JIT procedures |

### Three Functions of Predictive Branching

The research reveals three distinct functions, not just performance optimization:

```
Function 1: Pre-Computation (CPU Branch Prediction analog)
  Speculatively execute likely sub-tasks during idle time.
  Performance optimization — same output, faster delivery.

Function 2: Anticipatory Reasoning (Prospection / DMN analog)
  Forward-looking thought during idle cycles.
  "Given what I've seen, what might need my attention next?"
  Produces new awareness, not just faster responses.

Function 3: Goal Origination (Constructive Simulation / Preplay analog)
  Agents generate novel goals from observation.
  "I keep seeing config drift. We need an audit skill."
  Emergent goal-setting through speculative thought.
```

### Preplay vs Replay

Both use the same episodic memory substrate. Dreams look backward at
experience; predictive branches look forward at possibility.

```
Dream Consolidation (Replay)     Predictive Branching (Preplay)
 Steps 1-12, during sleep          During idle cycles, awake
 "What happened -> strengthen"     "What might happen -> prepare"
```

## Scope

### What This AD Covers (Umbrella)

This is an **umbrella AD** that defines the predictive branching protocol and
identifies sub-ADs for incremental delivery. The protocol applies exclusively
to **cognitive crew agents** that call `_decide_via_llm()`. Deterministic
utility agents (Ship's Computer services) are not candidates.

### What This AD Does NOT Cover

- Cognitive Sub-Task Protocol changes (AD-632 is prerequisite, not modified)
- Dream consolidation changes (existing replay pipeline is unchanged)
- Multi-agent coordination (prediction sharing is a future sub-AD)
- Standing order changes (implementation intentions are stored separately)
- Cognitive JIT pipeline changes (AD-531-539, already complete)
- Ward Room routing changes

## Design

### 1. Prediction Engine

The prediction engine determines **what** to speculate about. It uses
deterministic signals only — no LLM call for the prediction decision itself.

**Prediction confidence sources:**

| Signal | Source | Example |
|---|---|---|
| Hebbian routing weight | HebbianRouter | "I respond to Engineering topics 85% of the time" |
| Historical engagement | Ward Room stats | "I've replied to 3/4 security threads this watch" |
| Department relevance | Ontology | "This thread is in my department" |
| Captain interaction | Event type | "Captain DM -> near 100% response probability" |
| Circuit breaker state | CircuitBreaker | "If tripped -> prediction: won't respond" |
| Active engagement | WorkingMemory | "I'm in an active game -> predict game-related response" |
| Watch section pattern | Temporal context | "First watch typically has higher Engineering activity" |

**PredictionRequest dataclass:**
```python
@dataclass(frozen=True)
class PredictionRequest:
    agent_id: str              # parent agent sovereign ID
    stimulus_type: str         # "ward_room_thread", "dm", "proactive_pattern"
    stimulus_ref: str          # thread_id, channel_id, or pattern description
    confidence: float          # 0.0-1.0 from deterministic signals
    tier: SpeculationTier      # ZERO_COST, CHEAP, STANDARD, ANTICIPATORY
    created_at: datetime
    expires_at: datetime       # TTL — discard if unused by this time
```

### 2. Speculation Tiers (Token Cost Management)

Four tiers with escalating cost, gated by prediction confidence:

| Tier | Cost | Trigger Threshold | Example |
|---|---|---|---|
| **ZERO_COST** | Deterministic queries | Any department-relevant event | Query thread metadata, reply counts |
| **CHEAP** | Fast-tier LLM call | >70% engagement prediction | Lightweight analysis summary |
| **STANDARD** | Standard-tier LLM call | >85% engagement + complex thread | Full Analyze sub-task pre-computation |
| **ANTICIPATORY** | Standard-tier, self-originated | Idle cycle with no pending events | "What should I be thinking about?" |

```python
class SpeculationTier(Enum):
    ZERO_COST = "zero_cost"        # deterministic only
    CHEAP = "cheap"                # fast-tier LLM
    STANDARD = "standard"          # standard-tier LLM
    ANTICIPATORY = "anticipatory"  # self-originated reasoning
```

### 3. Speculation Executor

Runs speculative work and caches results. Integrates with AD-632 sub-task
types (Query, Analyze) for the actual computation.

**SpeculativeResult dataclass:**
```python
@dataclass
class SpeculativeResult:
    prediction_id: str          # links to PredictionRequest
    agent_id: str
    result: dict                # structured output (same as SubTaskResult)
    tier: SpeculationTier
    tokens_used: int            # for budget accounting
    duration_ms: int
    created_at: datetime
    expires_at: datetime        # cache TTL
    consumed: bool = False      # True when used by decision pipeline
    flushed: bool = False       # True when prediction was wrong
```

**Cache location:** Agent Working Memory (AD-573). Pre-computed results are
stored as WorkingMemory entries with type `"speculative"` and consumed by
`_decide_via_llm()` if the predicted event materializes.

### 4. Speculation Budget

Separate from operational token budget (AD-617b). Speculative work has its
own budget that doesn't compete with operational reasoning.

```python
@dataclass
class SpeculationBudgetConfig:
    enabled: bool = False                  # disabled by default
    hourly_token_cap: int = 5000           # separate from operational budget
    max_pending_speculations: int = 3      # per agent
    flush_rate_threshold: float = 0.30     # reduce budget if >30% flushed
    budget_reduction_factor: float = 0.5   # halve budget on high flush rate
    min_confidence_for_llm: float = 0.70   # below this, zero-cost only
```

Budget enforcement:
- Per-agent speculative token budget per hour (separate pool)
- Max pending speculations per agent (avoids unbounded queue)
- Flush rate tracked — agents with >30% flush rate have budgets reduced
- Configurable per-agent based on prediction accuracy history

### 5. Decision Pipeline Integration

When `_decide_via_llm()` is invoked, it checks Working Memory for relevant
speculative results before starting fresh reasoning:

```python
# Pseudocode — actual implementation in sub-ADs
async def _decide_via_llm(self, observation):
    # Check for pre-computed speculation
    spec_result = self._consume_speculation(observation)
    if spec_result:
        # Use pre-computed analysis, skip to Compose
        observation["_pre_analysis"] = spec_result.result
        # Token saving: skip Analyze sub-task
    
    # Continue with normal/sub-task pipeline
    ...
```

### 6. Prediction Accuracy Tracking

Feedback loop that improves prediction quality over time:

```python
@dataclass
class PredictionOutcome:
    prediction_id: str
    predicted_engagement: bool   # "I predicted I would respond"
    actual_engagement: bool      # "I actually responded"
    prediction_accuracy: float   # 1.0 if correct, 0.0 if wrong
    response_similarity: float   # cosine similarity if both exist
```

Accuracy metrics:
- Hit rate: predictions consumed / predictions generated
- Flush rate: predictions discarded / predictions generated
- Time-to-consume: how quickly predictions are used
- Quality delta: difference between speculative and actual analysis

### 7. Anticipatory Reasoning Mode (Goal Origination)

When an agent has idle cycles and no pending events, it engages in
forward-looking thought using the **Anticipatory** tier:

```
1. Recall recent observations (episodic memory, last N episodes)
2. Identify patterns or gaps (LLM analysis with narrow prompt)
3. Construct a future scenario ("If pattern X continues, then Y")
4. Evaluate: does this require action? A new skill? A proposal?
5. If actionable -> generate a PROPOSAL or skill gap report
```

**Anticipatory prompt (example):**
```
You are {agent_callsign}, {agent_role} in {department}.

Recent observations from your episodic memory:
{recent_episodes_summary}

Current department activity patterns:
{department_activity_summary}

Think forward:
1. What patterns do you notice across your recent observations?
2. What might need your attention in the next watch section?
3. Are there capability gaps — situations you keep encountering
   but don't have good tools or procedures for?
4. Is there anything worth proposing to the rest of the crew?

Respond in structured format:
- PATTERNS: [list of observed patterns]
- ANTICIPATIONS: [list of anticipated situations]
- GAPS: [list of capability gaps, if any]
- PROPOSALS: [list of proposals, if any]
- NONE: [if nothing warrants forward thought]
```

**Goal origination output:**
- **Skill gap identification:** Agent identifies recurring situations without
  adequate skillset → generates structured skill gap report
- **Proactive alerting:** Agent identifies trends → generates early warning
  before thresholds are hit
- **Cross-department insight:** Agent notices correlations across department
  boundaries → posts structured PROPOSAL to Ward Room

### 8. Conversational Pre-Rehearsal

A key application of predictive branching for Ward Room communication quality.
Agents mentally rehearse contributions before posting — separating deliberation
from composition so communication skill criteria get focused attention.

**Four-step pre-rehearsal process:**

```
1. READ: During idle time, pre-read Ward Room thread (zero-cost Query)
2. REHEARSE: Mentally draft a contribution (Cheap/Standard tier)
   - What would I say here?
   - Does this add genuine novelty to the thread?
3. EVALUATE: Self-check against communication discipline criteria
   - Am I repeating what someone already said?
   - Would an endorsement be more appropriate than a reply?
   - Does my opening avoid banned patterns?
4. PRE-DECIDE: Commit to RESPOND, ENDORSE, or SILENT
   - Cache the pre-decision in Working Memory
   - If RESPOND: cache the draft analysis for the Compose step
```

**Why this complements structural enforcement (AD-625-631):**

Current communication quality layers:
- Structural enforcement (AD-629 reply gates, department caps)
- Skill instructions (AD-625/627/631 communication discipline skill)
- Self-verification (AD-631 pre-submit check)

Pre-rehearsal adds: **cognitive deliberation during idle time.** The comm
skill criteria are applied when the agent has focused attention — no thread
parsing, no action tag emission, no competing concerns. Same insight as
AD-632's Compose sub-task: skill instructions in focused context outperform
instructions in crowded context.

**Perspective-taking:** The agent simulates how its post will look alongside
existing thread contributions. "Three people already made this point. If I
post the same thing, it adds noise, not signal." This is social forecasting
— predicting the reception of one's own action.

**Pre-rehearsal prompt (example):**
```
You are {agent_callsign}, {agent_role} in {department}.

Ward Room thread you may need to respond to:
{thread_content}

Review this thread and mentally rehearse your contribution:
1. What points have already been made? By whom?
2. Do you have something GENUINELY NEW to add?
3. Would endorsing an existing post be more valuable than replying?
4. If you were to respond, what would your opening sentence be?
   (Avoid: "Looking at...", "I notice...", "I can confirm...")
5. Will your response add signal or noise to this thread?

Pre-decision:
- RESPOND: I have a novel contribution (describe it briefly)
- ENDORSE: Post [id] is strong and I agree (cite which post)
- SILENT: Nothing to add / outside my scope
```

### 9. Preplay Dream Step

A new dream consolidation step that performs forward simulation using
consolidated memories. Unlike replay (strengthening past), preplay
anticipates (constructing future).

**Dream Step 13 (Preplay):**
```python
# After Step 12 (pruning), before dream report
# Use consolidated memories to simulate anticipated situations
async def _dream_step_preplay(self, agent_id, consolidated):
    # Construct forward scenarios from consolidated patterns
    # Generate implementation intentions ("when X, I will Y")
    # Store as pre-cached plans in Working Memory
    ...
```

### 10. Prediction Error as Emergence Signal

When an agent's predictions consistently diverge from reality, that's a
signal worth attending to — it means the environment is changing in ways
the agent hasn't modeled.

Connection to AD-557 (Emergence Metrics): prediction error rate feeds into
emergence detection. High collective prediction error across multiple agents
= genuine novelty in the system.

### 11. Invariants

**I1. Token isolation:** Speculative tokens are tracked separately from
operational tokens. Budget exhaustion in speculation does NOT affect the
agent's ability to respond to real events.

**I2. No speculation on Captain directives:** Captain interactions always
receive fresh, full reasoning. Never serve pre-computed analysis for Captain.

**I3. Speculation is disposable:** Every speculative result has a TTL. If
unused, it's garbage collected. No accumulation of stale predictions.

**I4. No nesting:** Speculations do not spawn sub-speculations. A prediction
triggers at most one speculative computation.

**I5. Prediction accuracy is observable:** Hit rate, flush rate, and accuracy
are recorded in CognitiveJournal and available for Counselor review.

**I6. Single-agent scope:** Predictions are private to the predicting agent.
No prediction sharing between agents (future sub-AD may extend this).

**I7. Earned Agency gating:** Speculation budgets scale with trust tier
(AD-357). Ensigns get zero or minimal speculation budget. Senior officers
get full anticipatory reasoning capability.

## Sub-AD Breakdown

### AD-633a: Prediction Engine Foundation

**Core infrastructure** — PredictionRequest dataclass, SpeculationTier enum,
PredictionEngine that evaluates deterministic confidence signals from
HebbianRouter, Ward Room stats, ontology department relevance, circuit
breaker state, and Working Memory engagement. Produces ranked prediction
queue per agent. Configuration in SystemConfig.

**Scope:** Prediction evaluation + confidence scoring + queue management
**Files:** `cognitive/prediction.py` (new), `config.py`
**Tests:** Confidence scoring from each signal source, queue ordering,
tier assignment, edge cases (tripped circuit breaker, zero Hebbian data)

### AD-633b: Speculation Executor + Cache

**Speculative execution and caching** — SpeculativeResult dataclass,
SpeculationExecutor that dispatches to AD-632 sub-task handlers (Query,
Analyze) in speculative mode. Results cached in AgentWorkingMemory as
speculative entries with TTL. Cache eviction on expiry or consumption.
CognitiveJournal recording for speculative work.

**Scope:** Executor + Working Memory cache integration + journal accounting
**Files:** `cognitive/speculation.py` (new), `cognitive/agent_working_memory.py`
**Tests:** Speculative execution, cache storage/retrieval, TTL expiry,
consumption marking, journal token attribution

### AD-633c: Speculation Budget Management

**Token cost governance** — SpeculationBudgetConfig in SystemConfig.
Per-agent hourly speculative token budget (separate from AD-617b operational
budget). Flush rate tracking with automatic budget reduction for inaccurate
predictors. Earned Agency tier gating (AD-357). Budget exhaustion logging.
Max pending speculations enforcement.

**Scope:** Budget tracking + flush rate feedback + Earned Agency integration
**Files:** `cognitive/prediction.py`, `config.py`
**Tests:** Budget enforcement, flush rate reduction, tier gating, budget
exhaustion, budget reset

### AD-633d: Decision Pipeline Integration

**Consuming speculative results** — `_decide_via_llm()` checks Working Memory
for relevant speculative results before starting fresh reasoning. If a valid
pre-computed analysis exists, it's injected as `_pre_analysis` in the
observation dict, allowing the sub-task chain (AD-632) to skip the Analyze
step. Confidence threshold for consumption. Consumed/flushed tracking.

**Scope:** Pipeline integration point + consumption logic + fallback
**Files:** `cognitive_agent.py`, `cognitive/speculation.py`
**Tests:** Speculation consumption, confidence thresholds, stale result
rejection, fallback to fresh analysis, pre-analysis injection

### AD-633e: Prediction Accuracy Tracking

**Feedback loop** — PredictionOutcome recording when predicted events
materialize (or don't). Hit rate, flush rate, time-to-consume, quality
delta metrics. Accuracy history used by budget manager (AD-633c) to adjust
budgets. CognitiveJournal integration. Self-monitoring metric
(AD-504 connection).

**Scope:** Outcome recording + accuracy metrics + journal + self-monitoring
**Files:** `cognitive/prediction.py`, `cognitive/journal.py`
**Tests:** Outcome recording, metric computation, budget feedback,
self-monitoring integration

### AD-633f: Anticipatory Reasoning Mode

**Forward-looking thought during idle cycles** — Anticipatory tier activation
when agent has no pending events in proactive cycle. Two modes: (1) **Goal
origination** — episodic memory pattern recognition, skill gap identification,
PROPOSAL generation. (2) **Conversational pre-rehearsal** — pre-read Ward Room
threads, rehearse contribution, evaluate against communication skill criteria,
pre-decide RESPOND/ENDORSE/SILENT. Pre-rehearsal results cached in Working
Memory for consumption when the thread event triggers `_decide_via_llm()`.
Communication skill (AD-625/631) criteria applied during focused rehearsal
context rather than competing with thread parsing.

**Scope:** Anticipatory prompt + idle cycle trigger + output processing +
conversational pre-rehearsal + comm skill integration
**Files:** `cognitive/prediction.py`, `proactive.py`
**Tests:** Idle cycle detection, anticipatory prompt generation, structured
output parsing, PROPOSAL generation, skill gap reporting, pre-rehearsal
pre-decision output (respond/endorse/silent), comm discipline criteria
application during rehearsal

### AD-633g: Preplay Dream Step

**Forward simulation during dream consolidation** — New dream Step 13
(Preplay) that uses consolidated memories to construct forward scenarios.
Generates implementation intentions ("when X, I will Y") stored in Working
Memory for the next wake cycle. Preplay uses same episodic memory substrate
as replay but with future-oriented prompts.

**Scope:** Dream step 13 + implementation intention storage + wake loading
**Files:** `cognitive/dreaming.py`, `cognitive/agent_working_memory.py`
**Tests:** Preplay step execution, implementation intention generation,
Working Memory persistence, wake cycle loading

### AD-633h: Prediction Error as Emergence Signal

**Connecting prediction failures to emergence detection** — When multiple
agents' predictions fail simultaneously, that's a signal of genuine novelty.
Prediction error rate feeds into EmergenceMetricsEngine (AD-557) as a new
signal source. PREDICTION_ERROR_SPIKE event type for Bridge Alerts when
collective prediction accuracy drops below threshold.

**Scope:** Emergence metrics integration + event emission + Bridge Alert
**Files:** `cognitive/prediction.py`, `cognitive/emergence_metrics.py`,
`events.py`
**Tests:** Collective prediction error detection, emergence signal emission,
Bridge Alert triggering

### AD-633i: Cognitive JIT Compilation of Predictions

**Repeated predictions become learned procedures** — When an agent repeatedly
predicts the same scenario and prepares the same response, the pattern
crystallizes into a Cognitive JIT procedure (AD-531-539). "Every time
Engineering reports high latency, I check the last three maintenance
windows" → learned Level 1 procedure. Implementation intentions (AD-633g)
are candidates for procedure extraction.

**Scope:** Pattern detection + procedure extraction + Cognitive JIT bridge
**Files:** `cognitive/prediction.py`, `cognitive/procedure_extraction.py`
**Tests:** Pattern detection, procedure extraction from predictions,
implementation intention compilation

## Implementation Order

```
AD-633a (Prediction Engine) -> AD-633b (Executor + Cache) ->
AD-633c (Budget Management) -> AD-633d (Pipeline Integration) ->
AD-633e (Accuracy Tracking) -> AD-633f (Anticipatory Reasoning) ->
AD-633g (Preplay Dream Step) -> AD-633h (Emergence Signal) ->
AD-633i (Cognitive JIT Compilation)
```

AD-633a-d form the minimum viable protocol (pre-computation function).
AD-633e adds the feedback loop. AD-633f adds anticipatory reasoning (goal
origination function). AD-633g-i are advanced capabilities.

## Prerequisites

| Prerequisite | Why |
|---|---|
| AD-632 (Cognitive Sub-Task Protocol) | Speculative work dispatches to sub-task handlers (Query, Analyze) |
| AD-531-539 (Cognitive JIT) | AD-633i compiles repeated predictions into procedures |
| AD-557 (Emergence Metrics) | AD-633h feeds prediction errors into emergence detection |
| AD-573 (Working Memory) | Speculative results cached in Working Memory |
| AD-357 (Earned Agency) | Speculation budgets gated by trust tier |

## Do NOT Change

- Dream consolidation Steps 1-12 (existing replay pipeline is unchanged)
- Cognitive Sub-Task Protocol (AD-632 is used, not modified)
- Ward Room routing logic — predictions don't affect routing
- Agent identity/trust/memory models — predictions are working state
- Inter-agent communication patterns — predictions are private
- Standing orders — behavioral rules remain in standing orders
- The existing single-call path — it remains the default
- Operational token budgets (AD-617b) — speculation has separate budget

## Test Strategy

Each sub-AD has its own test file. The umbrella test concerns:

1. **Pre-computation correctness**: Speculative analysis matches what the
   agent would have produced in real-time (quality delta < threshold)
2. **Budget enforcement**: Speculative tokens tracked separately, budget
   limits respected, flush rate feedback works
3. **Cache lifecycle**: Results stored, consumed, expired, garbage collected
4. **Prediction accuracy**: Hit/flush rates computed correctly, feedback
   adjusts budgets
5. **Anticipatory output**: Forward reasoning produces actionable structured
   output (patterns, gaps, proposals)
6. **Preplay integration**: Dream Step 13 generates implementation intentions,
   loaded on wake cycle
7. **Emergence signal**: Collective prediction errors detected and reported
8. **Cognitive JIT**: Repeated predictions compile into procedures
9. **Existing behavior preserved**: Agents without speculation enabled
   behave identically (regression)
10. **Captain directive bypass**: Captain interactions always get fresh
    reasoning, never pre-computed

## Verification Checklist

- [ ] PredictionEngine evaluates deterministic confidence signals
- [ ] SpeculationTier assignment based on confidence thresholds
- [ ] SpeculationExecutor dispatches to AD-632 sub-task handlers
- [ ] Speculative results cached in Working Memory with TTL
- [ ] Separate speculative token budget (not competing with operational)
- [ ] Flush rate tracking reduces budgets for inaccurate predictors
- [ ] Earned Agency gates speculation budgets by trust tier
- [ ] `_decide_via_llm()` consumes pre-computed speculations when valid
- [ ] Captain interactions bypass speculation (always fresh reasoning)
- [ ] Prediction outcomes recorded for accuracy feedback
- [ ] Anticipatory reasoning activates during idle cycles only
- [ ] Conversational pre-rehearsal produces pre-decisions (respond/endorse/silent) for anticipated Ward Room threads
- [ ] Pre-rehearsal applies communication discipline criteria in focused context
- [ ] Skill gap identification produces structured reports
- [ ] PROPOSAL generation from anticipatory reasoning
- [ ] Dream Step 13 (Preplay) generates implementation intentions
- [ ] Implementation intentions loaded into Working Memory on wake
- [ ] Prediction error rate feeds EmergenceMetricsEngine (AD-557)
- [ ] Collective prediction error triggers Bridge Alert
- [ ] Repeated predictions compile into Cognitive JIT procedures
- [ ] CognitiveJournal records all speculative work with trace IDs
- [ ] Existing tests pass (no regression)

## Open Questions (From Research)

1. **Speculation scope:** Should agents speculate only about their department,
   or also about cross-department patterns (bridge officers)?
2. **Prediction sharing:** If Agent A predicts something relevant to Agent B,
   should the prediction be shared? Private until confirmed?
3. **Goal origination governance:** Self-originated goals need guardrails.
   Captain approval? Department Chief review? Or autonomous PROPOSAL posting?
4. **Prediction horizon:** How far ahead? Next event? Next watch section?
5. **Hallucination risk:** Forward simulation uses LLM reasoning over episodic
   memories — same substrate that produces confabulation. Ground in observable
   data only?

## Research References

See `docs/research/predictive-cognitive-branching.md` for full survey:
- Homo Prospectus (Seligman et al., 2013) — prospective cognition
- Constructive Episodic Simulation (Schacter & Addis, 2007)
- Default Mode Network (Buckner, Andrews-Hanna)
- Hippocampal Preplay (Dragoi & Tonegawa, 2011)
- Predictive Processing / Active Inference (Friston, 2010)
- Implementation Intentions (Gollwitzer, 1999)
- World Models (Ha & Schmidhuber, 2018)
- CPU Branch Prediction (hardware analog)
- SOAR chunking (Laird, 2012) — prediction compilation
- Inner speech / social simulation (Vygotsky) — conversational pre-rehearsal
