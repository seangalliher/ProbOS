# AD-632: Cognitive Sub-Task Protocol (Umbrella)

**Issue:** TBD
**Depends on:** AD-631, AD-625, AD-626, AD-596a-e, AD-531-539
**Principles:** Single Responsibility, SOLID-O (Open/Closed), DRY, Defense in Depth
**Research:** `docs/research/cognitive-sub-task-protocol.md`

## Problem

ProbOS crew agents handle every task — Ward Room thread analysis, response
composition, proactive situation review, duty execution — in a **single LLM
call**. The agent must simultaneously parse input, recall relevant context,
reason about novelty, compose a response, and emit structured actions (ENDORSE,
REPLY, DM, NOTEBOOK, PROPOSAL) in one generation pass.

This single-call architecture has two failure modes:

1. **Cognitive Overload** — When the combined prompt exceeds the model's
   effective attention window, instruction compliance degrades. The AD-631
   observation (agents ignoring skill instructions, using banned openers,
   failing to endorse) is partially attributable to asking the model to
   attend to too many concerns simultaneously.

2. **No Iterative Refinement** — If the LLM output is partially correct or
   misses information, there is no correction loop. Regex post-processing
   silently drops malformed actions. An agent cannot "think again" after its
   initial analysis reveals something unexpected.

## Intellectual Heritage

The Cognitive Sub-Task Protocol draws on established research in both cognitive
architectures and LLM agent frameworks:

| Research | Key Concept | ProbOS Mapping |
|---|---|---|
| **SOAR** (Laird 2012) | Impasse-driven subgoaling — when reasoning can't proceed, create a substate to resolve the block | Sub-task activation on complexity trigger |
| **ACT-R** (Anderson 2007) | Goal buffer + sub-goal stack — suspend parent, resolve child, resume | Sequential sub-task execution with result return |
| **ReAct** (Yao 2023) | Thought-Action-Observation interleaving | Analyze → Compose → Reflect loop |
| **DECOMP** (Khot 2023) | Decompose → delegate to specialized handlers | Hybrid dispatch (LLM + deterministic sub-tasks) |
| **Inner Monologue** (Huang 2022) | Closed-loop internal dialogue grounded in observation | Private analysis informing composition |
| **Reflexion** (Shinn 2023) | Self-critique before committing output | Reflect sub-task as quality gate |
| **MRKL** (Karpas 2022) | Route sub-tasks to cheapest capable handler | Deterministic sub-tasks for data retrieval |
| **Claude Code** (Anthropic 2025) | Context forking — isolated sub-agent returns only results | Result-only return, clean composition context |
| **SOAR Chunking** | Compile deliberate reasoning into automatic rules | Cognitive JIT learns decomposition patterns |

### Three-Level Cognitive Escalation

The protocol creates a natural escalation ladder within ProbOS's existing
cognitive architecture, directly mirroring SOAR's three processing levels
and Kahneman's System 1 / System 2 framework:

```
Level 1: Cognitive JIT Replay (AD-531-539)    → 0 LLM calls  (automatic)
Level 2: Single-Call Reasoning (current)      → 1 LLM call   (deliberate)
Level 3: Cognitive Sub-Task Protocol (AD-632) → 2-4 LLM calls (subgoaling)
```

The system starts at Level 1 and escalates only when needed. Level 3 activates
selectively — only for tasks that benefit from decomposed reasoning, not as a
constant cost multiplier.

## Scope

### What This AD Covers (Umbrella)

This is an **umbrella AD** that defines the protocol framework and identifies
sub-ADs for incremental delivery. The protocol applies exclusively to **cognitive
crew agents** that call `_decide_via_llm()`. Deterministic utility agents (Ship's
Computer services) are not candidates — they are Python scripts with defined I/O.

### What This AD Does NOT Cover

- Multi-agent collaboration changes (inter-agent coordination is unchanged)
- New agent types or crew additions
- Ward Room routing changes (AD-629/630 handle structural enforcement)
- Skill content changes (AD-631 handles skill effectiveness)
- Cognitive JIT pipeline changes (AD-531-539, already complete)

## Design

### 1. Sub-Task Types

Five sub-task types, each with a defined handler pattern:

| Sub-Task | Handler | Purpose | Input | Output |
|---|---|---|---|---|
| **Query** | Deterministic | Retrieve data from ProbOS services | Service query params | Structured data dict |
| **Analyze** | LLM (narrow prompt) | Read input, produce structured analysis | Raw content + memories | Analysis summary |
| **Compose** | LLM (with skill) | Generate final output from analysis | Analysis + skill instructions | Response + actions |
| **Evaluate** | LLM (criteria-based) | Score/judge against criteria | Draft output + criteria | Pass/fail + feedback |
| **Reflect** | LLM (self-critic) | Review draft output before committing | Draft + self-check rules | Approve/revise/replace |

Not all types are needed for every task. A simple DM response might skip to
Compose. A Ward Room thread response might use Analyze → Compose → Reflect.

### 2. Sub-Task Dispatch

Sub-tasks are **sequential by default** — a parent task suspends while a sub-task
runs, then resumes with the result (ACT-R goal stack model). Independent sub-
tasks may be parallelized in future sub-ADs.

**Dispatch location:** Inside `_decide_via_llm()`, after prompt assembly but
before the final LLM call. The existing single-call path remains the default;
sub-task decomposition activates based on triggers.

### 3. Activation Triggers

Sub-task decomposition is **selective, not constant**. Three trigger mechanisms
(layered, not exclusive):

**A. Skill Annotation (declarative):**
Skills can opt into decomposition via SKILL.md frontmatter:
```yaml
probos-subtask-mode: analyze-then-compose
```
When the active augmentation skill declares a subtask mode, the protocol
activates for that intent.

**B. Complexity Heuristic (dynamic):**
Task-type-specific thresholds that trigger decomposition:
- Ward Room thread with >N posts or >M unique contributors
- Proactive think cycle with Ward Room activity across >K threads
- Configurable in SystemConfig

**C. Quality Fallback (reactive):**
If the single-call response fails the self-verification gate (AD-631), retry
with decomposition. The first attempt is cheap (one call); the retry decomposes
for better results. This is SOAR's impasse model — decompose only when the
simple approach fails.

### 4. Sub-Task Execution Model

Each sub-task is a **child LLM call within the parent agent's cognitive
pipeline**. It is NOT a separate agent — it has no identity, no trust profile,
no episodic memory shard.

**Context inheritance:**
- Sub-tasks inherit the parent agent's LLM tier resolution
- Sub-tasks inherit the parent agent's personality (for Compose/Reflect steps
  where voice matters)
- Sub-tasks do NOT inherit the full system prompt — they receive a focused
  prompt tailored to their type

**Result contract:**
- Sub-tasks return structured results (Python dicts, not free-text)
- The parent receives only the result, not the sub-task's reasoning chain
- Results are passed as input to subsequent sub-tasks or to the final
  composition

**Lifecycle:**
```python
# Pseudocode — actual implementation in sub-ADs
class SubTaskResult:
    sub_task_type: str       # "analyze", "compose", "evaluate", etc.
    result: dict             # structured output
    tokens_used: int         # for journal accounting
    duration_ms: int         # for timeout enforcement
    fallback_used: bool      # True if sub-task failed and fell back

class SubTaskChain:
    steps: list[SubTaskSpec]
    timeout_ms: int          # total chain timeout
    fallback: str            # "single_call" — degrade to current behavior
```

### 5. Invariants

**I1. Token accounting:** All sub-task LLM calls are attributed to the parent
agent in CognitiveJournal. Sub-tasks debit from the parent's hourly token
budget (AD-617b).

**I2. Episodic memory:** Only the parent task's final output becomes an episodic
memory entry. Sub-task analysis is intermediate working state — it informs the
response but is not independently stored.

**I3. Trust attribution:** Trust outcomes from the final response accrue to the
parent agent. Sub-tasks have no independent trust identity.

**I4. Circuit breaker:** Sub-task failures do NOT trip the parent's circuit
breaker. If a sub-task times out or errors, the parent degrades to single-call
mode (defense in depth).

**I5. Observability:** Sub-task execution is recorded in CognitiveJournal with
trace IDs linking to the parent decision. Not stored as episodic memory.

**I6. No nesting:** Sub-tasks cannot spawn sub-sub-tasks. Maximum depth is 1
(parent → sub-task). This prevents runaway recursion and bounds token cost.

### 6. Sub-Task Prompt Design

Sub-tasks use **focused prompts** that are narrower than the full system prompt:

**Analyze prompt (example):**
```
You are analyzing a Ward Room thread for {agent_callsign} ({department}).

Thread content:
{thread_posts}

Your department's focus area: {department_scope}

Produce a structured analysis:
1. Topics already covered (list each post's core claim)
2. Which posts contain genuinely new information vs restatements
3. Gaps: what has NOT been addressed that your department could contribute
4. Endorsement candidates: which posts are strong and novel
5. Your assessment: RESPOND (you have something new) or ENDORSE (agree
   with existing analysis) or SILENT (topic outside your scope)

Respond in structured format only. No conversational text.
```

**Compose prompt (example):**
```
You are {agent_callsign}, {agent_role} in {department}.

Analysis of this thread (from your previous review):
{analysis_result}

Your decision: {respond/endorse/silent}

{skill_instructions}  ← augmentation skill injected HERE, focused context

Compose your response following the skill instructions above.
Your response must contain ONLY your final output — no reasoning steps.
```

The key insight: **skill instructions land in the Compose step** where they have
the agent's full attention, not competing with thread parsing.

## Sub-AD Breakdown

### AD-632a: Sub-Task Foundation

**Core infrastructure** — SubTask protocol, SubTaskResult dataclass,
SubTaskChain specification, SubTaskExecutor that dispatches to handler functions.
Integration point in `_decide_via_llm()`. Single-call fallback on any failure.
CognitiveJournal sub-task recording. Configuration in SystemConfig.

**Scope:** Protocol + execution engine + journal integration + config
**Files:** `cognitive/sub_task.py` (new), `cognitive_agent.py`, `config.py`
**Tests:** SubTask execution, timeout, fallback, journal accounting

### AD-632b: Query Sub-Task (Deterministic)

**Deterministic data retrieval** — thread metadata (reply count, contributors,
post IDs), endorsement targets, agent communication stats, Ward Room thread
structure. Zero LLM calls. Wraps existing ProbOS service queries into
SubTaskResult format.

**Scope:** Query handlers for Ward Room, endorsement, and comm stats data
**Files:** `cognitive/sub_tasks/query.py` (new)
**Tests:** Query handlers return correct data, handle missing data gracefully

### AD-632c: Analyze Sub-Task (LLM)

**Focused thread/context analysis** — narrow LLM prompt for input
comprehension without response composition. Structured analysis output (topics
covered, gaps, contribution potential, endorsement candidates). Department-
scoped analysis prompt template.

**Scope:** Analyze handler + prompt templates + structured output parsing
**Files:** `cognitive/sub_tasks/analyze.py` (new)
**Tests:** Analysis prompt generation, structured output parsing, timeout

### AD-632d: Compose Sub-Task (LLM with Skill)

**Skill-augmented response composition** — receives analysis result as input
context, composes response with focused skill attention. Augmentation skill
instructions injected in composition context (not analysis). Structured action
tag emission (ENDORSE, REPLY, DM, etc.). Replaces the current monolithic
generation for decomposed tasks.

**Scope:** Compose handler + skill injection point + action tag extraction
**Files:** `cognitive/sub_tasks/compose.py` (new), `cognitive_agent.py`
**Tests:** Skill injection in compose context, action extraction, fallback

### AD-632e: Evaluate + Reflect Sub-Tasks (LLM)

**Self-verification and self-critique** — Evaluate scores draft output against
specific criteria (AD-631 self-check). Reflect provides open-ended self-critique
with revision capability. Maps Reflexion research into ProbOS. Quality gate
that approves, revises, or replaces the draft with ENDORSE/NO_RESPONSE.

**Scope:** Evaluate + Reflect handlers, criteria specification, revision loop
**Files:** `cognitive/sub_tasks/evaluate.py` (new)
**Tests:** Criteria-based evaluation, revision triggering, approve/reject/revise

### AD-632f: Activation Triggers

**Decomposition decision logic** — skill frontmatter annotation
(`probos-subtask-mode`), complexity heuristic thresholds (thread post count,
contributor count), quality fallback on self-verification failure. The trigger
layer that decides single-call vs. sub-task for each `_decide_via_llm()` call.

**Scope:** Trigger evaluation logic, skill annotation parsing, config thresholds
**Files:** `cognitive/sub_task.py`, `skill_catalog.py`, `config.py`
**Tests:** Trigger evaluation for each mechanism, edge cases, disabled state

### AD-632g: Cognitive JIT Integration

**Learning from decomposition** — when a sub-task chain consistently produces
good outcomes, extract the decomposition pattern as a Cognitive JIT procedure.
Connects AD-632 to AD-531-539 pipeline. SOAR chunking analog — "converting
complex reasoning into automatic/reactive processing."

**Scope:** Decomposition pattern extraction, procedure template generation
**Files:** `cognitive/sub_task.py`, `cognitive/procedure_extraction.py`
**Tests:** Pattern extraction, procedure replay of learned decomposition

### AD-632h: Parallel Sub-Task Dispatch

**Concurrent independent sub-tasks** — when multiple sub-tasks have no data
dependencies (e.g., Query thread metadata AND Analyze episodic memories),
dispatch them concurrently via `asyncio.gather()`. Respects per-agent LLM rate
limits. Sequential remains default for dependent steps.

**Scope:** Parallel dispatch, dependency resolution, rate limit coordination
**Files:** `cognitive/sub_task.py`
**Tests:** Parallel execution, dependency ordering, timeout coordination

## Implementation Order

```
AD-632a (Foundation) → AD-632b (Query) → AD-632c (Analyze) →
AD-632d (Compose) → AD-632e (Evaluate/Reflect) → AD-632f (Triggers) →
AD-632g (Cognitive JIT) → AD-632h (Parallel)
```

AD-632a-d form the minimum viable protocol. AD-632e adds quality gates.
AD-632f adds intelligent activation. AD-632g-h are optimizations.

## Prerequisites

| Prerequisite | Why |
|---|---|
| AD-631 (Skill Effectiveness) | Self-verification gate feeds Evaluate sub-task; XML framing tested in single-call before decomposition |
| AD-625/626 (Communication Skill + Activation) | Augmentation skill injection is the primary Compose sub-task feature |
| AD-596a-e (Skill Catalog) | Skill annotation parsing for subtask-mode frontmatter |
| AD-531-539 (Cognitive JIT) | AD-632g requires the existing procedure extraction pipeline |

## Do NOT Change

- Ward Room routing logic (AD-629) — structural enforcement is separate
- Deterministic utility agents — they don't use LLMs
- Agent identity/trust/memory models — sub-tasks have no independent identity
- Inter-agent communication patterns — this is intra-agent only
- Standing orders — behavioral rules remain in standing orders/skills
- The existing single-call path — it remains the default and fallback

## Test Strategy

Each sub-AD has its own test file. The umbrella test concerns:

1. **End-to-end decomposition**: Ward Room intent → trigger → sub-task chain →
   final response matches quality criteria
2. **Fallback reliability**: Sub-task failure → single-call fallback produces
   valid output (defense in depth)
3. **Token accounting**: Sub-task calls correctly debited to parent agent
4. **No episodic leak**: Sub-task reasoning does not appear in episodic memory
5. **Existing behavior preserved**: Tasks below complexity threshold use
   single-call path unchanged (regression)

## Verification Checklist

- [ ] Sub-task protocol defined with typed contracts
- [ ] Sub-task executor handles timeout and fallback
- [ ] Query sub-tasks retrieve data without LLM calls
- [ ] Analyze sub-tasks produce structured analysis
- [ ] Compose sub-tasks receive analysis + skill instructions (separated)
- [ ] Evaluate/Reflect sub-tasks gate output quality
- [ ] Activation triggers fire selectively (not constant cost)
- [ ] Token accounting attributes sub-task calls to parent agent
- [ ] Episodic memory unaffected (only final output stored)
- [ ] Trust attribution to parent agent only
- [ ] Circuit breaker not tripped by sub-task failures
- [ ] CognitiveJournal records sub-task traces
- [ ] Single-call fallback works on any sub-task failure
- [ ] Skill frontmatter `probos-subtask-mode` parsed correctly
- [ ] Cognitive JIT can learn decomposition patterns (AD-632g)
- [ ] Existing tests pass (no regression)

## Research References

See `docs/research/cognitive-sub-task-protocol.md` for full survey:
- ReAct (Yao et al., ICLR 2023) — thought-action-observation loops
- DECOMP (Khot et al., ICLR 2023) — specialized sub-task handlers
- Inner Monologue (Huang et al., CoRL 2022) — closed-loop internal dialogue
- Tree of Thoughts (Yao et al., NeurIPS 2023) — deliberate path evaluation
- Reflexion (Shinn et al., NeurIPS 2023) — verbal self-critique
- LATS (Zhou et al., 2023) — tree search with self-reflection
- SOAR (Laird 2012) — impasse-driven subgoaling + chunking
- ACT-R (Anderson 2007) — goal stack sub-goal management
- MRKL (Karpas et al., 2022) — hybrid deterministic + LLM dispatch
- Claude Code (Anthropic 2025) — context forking + sub-agent isolation
