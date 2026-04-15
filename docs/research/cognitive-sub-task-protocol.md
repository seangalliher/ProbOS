# Cognitive Sub-Task Protocol — Research Synthesis

**Date:** 2026-04-15
**Author:** Sean Galliher (Architect)
**Status:** Research complete, AD scoped
**Related ADs:** AD-632 (umbrella), AD-531–539 (Cognitive JIT), AD-596 (Skill Catalog),
AD-625–631 (Communication Discipline lineage), AD-618 (Bill System SOPs)

---

## 1. Problem Statement

ProbOS crew agents currently handle every task — Ward Room thread analysis, DM
response composition, proactive situation review, duty execution — in a **single
LLM call**. The entire cognitive pipeline is:

```
perceive() → recall() → decide() [ONE LLM call] → act() → store()
```

The `_decide_via_llm()` method assembles a massive prompt (standing orders +
personality + temporal context + working memory + episodic memories + oracle
knowledge + thread content + augmentation skill + self-monitoring) and asks the
model to **simultaneously** analyze input, reason about it, compose a response,
and emit structured actions (ENDORSE, REPLY, DM, NOTEBOOK, PROPOSAL) — all in
one generation pass.

This architecture has two failure modes:

**A. Cognitive Overload**: When the combined prompt exceeds the model's effective
attention window, instruction compliance degrades. AD-631's observation — agents
ignoring skill instructions, using banned openers, failing to endorse — is
partially attributable to asking the model to attend to too many concerns
simultaneously.

**B. No Iterative Refinement**: If the LLM output is malformed, partially
correct, or misses information, there is no retry or correction loop. The
regex-based post-processing either extracts valid structured actions or silently
drops them. An agent cannot "think again" about a thread after its initial
analysis reveals something unexpected.

### What This Is NOT

This research does not propose replacing the ship's existing multi-agent
architecture. ProbOS uses 55+ sovereign agents with distinct identities — that's
inter-agent collaboration. This research addresses **intra-agent task
decomposition** — a single crew agent breaking its own reasoning into focused
sub-steps before producing its final output.

The deterministic utility agents (Ship's Computer services) are not candidates
for this pattern. They are Python scripts with defined I/O — they don't use LLMs
and don't need decomposed reasoning. This protocol applies exclusively to
cognitive crew agents that call `_decide_via_llm()`.

---

## 2. Prior Art Survey

### 2.1 Claude Code — Context Forking (Anthropic, 2025)

**Source:** Anthropic Claude Code documentation; Mei 2025 analysis

Claude Code's `context: fork` mechanism spawns an isolated sub-agent with a fresh
context window. The sub-agent receives only its task + instructions (no
conversation history), works independently, and returns **only the final
summary** to the parent. All intermediate artifacts (file reads, search results,
reasoning chains) are discarded from the main thread.

**Key architectural properties:**
- Sub-agents cannot spawn sub-agents (no infinite nesting)
- Sub-agents inherit tools/permissions but NOT conversation history
- Different agent types optimize for different roles (Explore = fast/read-only,
  Plan = architecture, general-purpose = full access)
- `context: fork` is a declarative frontmatter field — the skill author decides
  at definition time whether isolation is warranted
- The parent's context stays clean — only the synthesized result comes back

**Relevance to ProbOS:** Claude Code forks primarily to protect context window
budget (a developer's interactive session accumulates many tool results). ProbOS
agents don't have this problem — each `handle_intent()` starts with fresh prompt
assembly. The ProbOS value is different: **focused reasoning** on sub-problems
that benefit from narrower attention, and **iterative refinement** where analysis
informs composition.

### 2.2 ReAct — Reasoning + Acting (Yao et al., ICLR 2023)

**Source:** arXiv:2210.03629

ReAct interleaves reasoning traces and task-specific actions in a thought-action-
observation loop:

```
THOUGHT → ACTION → OBSERVATION → THOUGHT → ACTION → ...
```

Key findings:
- Reasoning without grounding leads to hallucination and error compounding
- Acting without reasoning leads to brittle, non-adaptive behavior
- Interleaving addresses both — produces agents that are more accurate, more
  interpretable, and more robust
- On HotpotQA: "overcomes issues of hallucination and error propagation
  prevalent in chain-of-thought reasoning"
- On ALFWorld/WebShop: surpassed imitation and reinforcement learning by 34%
  and 10% absolute success rate respectively

**Relevance to ProbOS:** ProbOS agents currently do THOUGHT + ACTION in one
pass — they reason and act simultaneously. The ReAct insight suggests separating
the reasoning phase (analyze thread, check what's covered, evaluate novelty)
from the action phase (compose response, select structured actions). The
observation step maps to grounding analysis in actual thread content and episodic
memory before composing.

### 2.3 Decomposed Prompting (Khot et al., ICLR 2023)

**Source:** arXiv:2210.02406

DECOMP breaks complex tasks into simpler sub-tasks delegated to specialized
handlers. Key insight: individual reasoning steps embedded in complex contexts
are harder to learn than the same steps in isolation.

**Architecture:**
1. A decomposer prompt identifies needed sub-steps
2. Each sub-step routes to a specialized handler
3. Handlers can be LLM prompts, trained models, or symbolic functions
4. Sub-tasks can themselves be further decomposed recursively

**Relevance to ProbOS:** This directly validates the principle that a Ward Room
thread analysis is better handled as decomposed sub-tasks (what's been said? →
what's novel? → what's my contribution? → compose response) than as a monolithic
"analyze and respond" prompt. The handler flexibility maps to ProbOS's hybrid
model — some sub-tasks could be deterministic (check reply count, verify
endorsement targets) while others require LLM reasoning (evaluate novelty,
compose analysis).

### 2.4 Inner Monologue (Huang et al., CoRL 2022)

**Source:** arXiv:2207.05608

Inner Monologue creates a closed-loop framework where an LLM planner receives
continuous natural language feedback from the environment, forming an internal
dialogue that grounds each planning step in actual world state.

**Loop:** Plan step → Execute → Textualize feedback (success? scene state?
corrections?) → Replan with feedback

Key finding: "Closed-loop language feedback significantly improves high-level
instruction completion" — without any additional training.

**Relevance to ProbOS:** The "inner monologue" concept maps to a crew agent
maintaining a private reasoning trace as it processes a Ward Room thread. Step 1:
analyze what's been said (observation). Step 2: check if I have something novel
(self-evaluation). Step 3: compose response grounded in steps 1-2 (action). The
feedback loop enables the agent to catch itself before posting redundant content.

### 2.5 Tree of Thoughts (Yao et al., NeurIPS 2023)

**Source:** arXiv:2305.10601

ToT generalizes chain-of-thought by structuring reasoning around "coherent units
of text (thoughts)" that branch into a tree. The model considers multiple
reasoning paths, self-evaluates choices, and can backtrack when necessary.

Key result: Game of 24 — CoT with GPT-4 solved 4% of tasks; ToT achieved 74%
(~19x improvement).

**Relevance to ProbOS:** ToT is likely too expensive for standard Ward Room
interactions (exploring multiple reasoning branches per response is token-
heavy). However, the principle of **deliberate evaluation of alternatives** maps
to high-stakes decisions: Proposal composition, cross-department analysis, duty
execution. A lightweight variant — consider 2-3 response approaches, self-
evaluate, select best — could improve output quality for important tasks without
full tree search cost.

### 2.6 Reflexion (Shinn et al., NeurIPS 2023)

**Source:** arXiv:2303.11366

Reflexion improves LLM agents through verbal self-reflection after task
execution. The agent generates a natural-language self-critique, stores it in
episodic memory, and uses stored reflections to guide future attempts.

Key result: 91% pass@1 on HumanEval coding benchmark (vs GPT-4 baseline of 80%).

**Relevance to ProbOS:** ProbOS already has episodic memory + dream
consolidation. The Reflexion insight is that **same-session self-reflection
before finalizing** (not just between sessions via dreams) catches errors. This
validates AD-631's self-verification gate approach and extends it: a sub-task
could analyze the agent's draft response and provide feedback before it posts.

### 2.7 LATS — Language Agent Tree Search (Zhou et al., 2023)

**Source:** arXiv:2310.04406

LATS unifies reasoning, acting, and planning by wrapping ReAct-style loops
within Monte Carlo tree search. The LM serves simultaneously as policy, value
function, and self-critic. Environmental feedback provides ground-truth signals.

Key result: 92.7% pass@1 on HumanEval (GPT-4); WebShop performance "comparable
to gradient-based fine-tuning" without any weight updates.

**Relevance to ProbOS:** LATS represents the ceiling of what's possible with
inference-time decomposition. For ProbOS, the key takeaway is the **self-critic
role** — using the LLM to evaluate its own candidate responses against criteria
before committing. This is cheaper than full tree search and maps to the self-
verification gate pattern.

### 2.8 SOAR — Impasse-Driven Subgoaling (Laird et al., 1987–present)

**Source:** Soar cognitive architecture (Laird 2012)

SOAR's Universal Subgoaling is the most directly relevant cognitive architecture
pattern. When SOAR's decision procedure cannot move forward (an "impasse"), it
automatically creates a **substate** with its own goal: resolving the block.

**Key properties:**
- Substates stack recursively — if a substate impasses, another is created
- Processing in the substate resolves the parent impasse
- Once resolved, substate structures are removed **except results**
- **Chunking**: reasoning that produced results in a substate is compiled into
  production rules that fire automatically in similar future situations — 
  "converting complex reasoning into automatic/reactive processing"

**Three-level processing model:**
1. Automatic/reactive (compiled productions — analogous to ProbOS's Cognitive
   JIT procedural replay)
2. Deliberate operator selection (standard reasoning — analogous to single
   LLM call `decide()`)
3. Impasse-driven substate reasoning (deliberate decomposition — what this
   AD proposes)

**Relevance to ProbOS:** SOAR's model is the intellectual ancestor of this
proposal. The three processing levels map almost exactly:

| SOAR Level | ProbOS Analog | When Used |
|---|---|---|
| Automatic | Cognitive JIT procedural replay | Known repeatable tasks |
| Deliberate | Single `_decide_via_llm()` call | Standard reasoning |
| Subgoaling | Cognitive Sub-Task Protocol | Complex multi-faceted tasks |

SOAR's chunking → production compilation maps to an important future capability:
if a sub-task decomposition pattern repeatedly produces good results, Cognitive
JIT should learn it as a reusable procedure (AD-531–539 pipeline).

### 2.9 ACT-R — Goal Buffer and Sub-Goal Stacking (Anderson, 2007)

**Source:** ACT-R cognitive architecture

ACT-R maintains a goal buffer that holds the current goal. When a task requires
sub-steps, the current goal is pushed onto a stack and a sub-goal is set as
active. Productions fire based on buffer state, and when the sub-goal completes,
the parent goal is restored.

**Relevance to ProbOS:** The goal-stack model suggests sub-tasks should be LIFO —
a parent task suspends while a sub-task runs, then resumes with the sub-task's
result. This is simpler than tree-structured alternatives and maps naturally to
ProbOS's sequential `handle_intent()` pipeline.

### 2.10 MRKL — Modular Reasoning, Knowledge and Language (Karpas et al., 2022)

**Source:** AI21 Labs, previously cited in AD-631

MRKL validates mixing LLM reasoning with deterministic "expert modules." A
router decides which module handles each sub-task. Already cited in ProbOS's
architecture as validation for the hybrid deterministic + LLM model.

**Relevance to ProbOS:** Sub-tasks in the Cognitive Sub-Task Protocol should not
all require LLM calls. Some sub-tasks are deterministic: "count how many replies
exist in this thread" is a database query, not an LLM judgment. The MRKL
principle — route each sub-task to the cheapest capable handler — should govern
sub-task dispatch.

---

## 3. Synthesis: What ProbOS Should Build

### 3.1 Design Principles

From the research survey, five principles emerge:

**P1. Selective Decomposition (SOAR impasse model):**
Not every task needs decomposition. The cost of sub-task forking (additional LLM
calls, latency) is only justified when the task complexity exceeds what a single
call handles well. The system should decompose **on demand**, not by default.
Triggers: skill activation (augmentation skills benefit from focused sub-tasks),
task complexity heuristics (thread length, action vocabulary size), or explicit
skill annotation.

**P2. Focused Attention per Sub-Task (DECOMP + Inner Monologue):**
Each sub-task should receive only the context relevant to its narrow purpose.
An analysis sub-task gets the thread content + episodic memories. A composition
sub-task gets the analysis result + skill instructions + response format. Neither
needs the other's full context.

**P3. Hybrid Dispatch (MRKL):**
Sub-tasks should route to the cheapest capable handler. Thread reply counting is
a SQL query. Novelty assessment is an LLM judgment. Endorsement target lookup is
a dictionary check. Only sub-tasks requiring genuine reasoning should invoke
the LLM.

**P4. Result-Only Return (Claude Code fork model):**
The parent task receives only the sub-task's structured result, not its reasoning
traces. This keeps the composition step's context clean and focused.

**P5. Learning from Decomposition (SOAR chunking + Cognitive JIT):**
When a decomposition pattern repeatedly produces good outcomes, the system
should learn it. This connects to the existing Cognitive JIT pipeline — a sub-
task decomposition can be extracted as a procedure, replayed without LLM calls
in future similar situations.

### 3.2 ProbOS-Specific Considerations

**Token Budget:**
Sub-task forking is NOT a constant cost multiplier. It activates only when
warranted — when a crew agent is performing a task that benefits from focused
reasoning. The decision of whether to fork is itself a lightweight check, not
an LLM call. Possible triggers:
- Skill annotation (`probos-subtask-mode: analyze-then-compose`)
- Thread complexity threshold (>5 posts, >3 unique contributors)
- Task type heuristics (proactive_think with Ward Room activity → fork;
  simple DM response → no fork)
- Dynamic: if the single-call response fails quality checks (AD-631's self-
  verification gate), retry with decomposition

**Cognitive Journal Accounting:**
Sub-task LLM calls must be attributed to the parent agent for token budget
tracking (AD-617b). A sub-task is not a separate agent — it's the parent agent's
inner reasoning. The CognitiveJournal should record sub-task calls as part of
the parent's session usage.

**Episodic Memory:**
Sub-task reasoning should NOT create separate episodic memories. Only the parent
task's final output becomes an episode. The sub-task analysis is intermediate
working state — it informs the response but isn't independently memorable. This
maps to SOAR: "substate structures are removed except for results."

**Trust Attribution:**
Trust outcomes from the final response accrue to the parent agent. Sub-tasks
have no independent trust identity. A sub-task is the agent's private cognitive
process, not a separate entity in the social fabric.

**Circuit Breaker:**
Sub-task failures should not trip the parent's circuit breaker. If an analysis
sub-task times out, the parent agent should degrade gracefully to single-call
mode (the current behavior). This is defense in depth — the sub-task protocol
is an enhancement, not a requirement.

**Cancellation/Timeout:**
Sub-tasks need bounded execution time. If a sub-task exceeds a configurable
timeout, the parent cancels it and proceeds with single-call fallback. The
proactive loop's per-agent timing budget applies to the total (parent + sub-
tasks), not per sub-task.

**Observability:**
Sub-task chains need trace IDs linking them to the parent decision. The
CognitiveJournal should record: parent intent → sub-task 1 (type, duration,
token count) → sub-task 2 → ... → final decision. This enables debugging
without polluting episodic memory.

**Skill Activation in Sub-Tasks:**
Augmentation skills should inject into the **composition** sub-task (where the
agent formulates its response), not the analysis sub-task (where it evaluates
the thread). This is the entire point — focused attention. The analysis sub-task
gets: "What has been said? What's novel? What's covered?" The composition sub-
task gets: "Given this analysis, compose your response following this skill."

**Concurrent Sub-Tasks:**
Some analysis steps are independent and could run in parallel (check thread
content AND query episodic memory). This is a future optimization — start with
sequential for simplicity, add parallel dispatch when the pattern is proven.

### 3.3 Proposed Sub-Task Types

Drawing from Claude Code's agent types and ProbOS's specific needs:

| Sub-Task Type | Handler | Purpose | Example |
|---|---|---|---|
| **Analyze** | LLM (focused prompt) | Read input, produce structured analysis | "Summarize thread: topics covered, contributors, gaps" |
| **Evaluate** | LLM (criteria-based) | Score/judge against criteria | "Does this draft contain novel information?" (self-check) |
| **Query** | Deterministic | Retrieve data from ProbOS services | Thread reply count, endorsement targets, agent stats |
| **Compose** | LLM (with skill) | Generate final output from analysis | "Given this analysis, compose your Ward Room post" |
| **Reflect** | LLM (self-critic) | Review draft output before committing | "Does this response comply with communication skill?" |

Not all types are needed for every task. A simple DM response might need only
Compose. A Ward Room thread response might need Analyze → Compose → Reflect.
A proactive think cycle might need Query → Analyze → Compose.

---

## 4. Use Cases

### 4.1 Ward Room Thread Response (Primary)

Current: Agent receives thread + all context → single LLM call → REPLY/ENDORSE

Proposed:
```
1. Query (deterministic): thread metadata — reply count, department spread,
   post IDs, endorsement targets
2. Analyze (LLM, focused): "Given this thread, what topics are covered?
   What information is missing? Is there a gap your department can fill?"
   → structured analysis: {topics_covered, gaps, my_contribution_potential}
3. Compose (LLM, with skill): "Given this analysis and your communication
   skill, produce your response or choose ENDORSE/NO_RESPONSE."
   → final output with structured actions
4. Reflect (optional, LLM): "Does your response pass the Pre-Submit Check?"
   → approve or replace with ENDORSE/NO_RESPONSE
```

**Why this helps:** The Analyze step runs with a narrow prompt focused entirely
on thread comprehension — no response formatting instructions, no action
vocabulary, no skill behavioral rules. The Compose step runs with the analysis
result + skill instructions — no raw thread content to re-parse. Each step has
focused attention.

### 4.2 Proactive Think Cycle

Current: Agent receives all departmental context → single LLM call → multiple
possible actions (REPLY, DM, NOTEBOOK, PROPOSAL, ENDORSE, CHALLENGE)

Proposed:
```
1. Query (deterministic): Ward Room activity, unread DMs, duty status,
   active engagements
2. Analyze (LLM, focused): "Review your department's Ward Room activity.
   Identify threads needing your input and topics for new posts."
   → structured analysis: {threads_to_respond, topics_for_new_post, dm_needs}
3. Compose (LLM, with skill): "Based on your analysis, produce your actions."
   → structured output with appropriate action tags
```

### 4.3 Complex Duty Execution (Future — AD-618 Bills)

When Bills (SOPs) define multi-step procedures, sub-tasks enable step-by-step
execution with intermediate evaluation:

```
1. Query: Current step in Bill, required inputs
2. Compose: Execute current step
3. Evaluate: Did the step succeed? Move to next or remediate?
4. Loop until Bill complete
```

### 4.4 Skill-Driven Decomposition

Augmentation skills could declaratively specify their preferred decomposition:

```yaml
probos-subtask-mode: analyze-then-compose
probos-analysis-prompt: |
  Review the Ward Room thread. For each post, identify:
  - The core claim or recommendation
  - Whether it adds new information or restates previous posts
  - Endorsement-worthy posts (strong, novel contribution)
  Report your analysis as a structured summary.
```

This makes the decomposition skill-specific — different skills can define
different analysis prompts tailored to their domain. The protocol provides the
plumbing; the skill provides the cognitive strategy.

---

## 5. Architectural Position in ProbOS

### 5.1 Relationship to Existing Systems

```
                    ┌─────────────────────────────┐
                    │ Cognitive JIT Replay (T3)    │  ← "Automatic" (SOAR L1)
                    │ (AD-531–539)                 │     Zero LLM calls
                    └──────────┬──────────────────┘
                               │ cache miss / no procedure
                    ┌──────────▼──────────────────┐
                    │ Single-Call Reasoning        │  ← "Deliberate" (SOAR L2)
                    │ (_decide_via_llm, current)   │     One LLM call
                    └──────────┬──────────────────┘
                               │ complexity trigger / skill annotation
                    ┌──────────▼──────────────────┐
                    │ Cognitive Sub-Task Protocol  │  ← "Subgoaling" (SOAR L3)
                    │ (AD-632, this proposal)      │     2-4 focused LLM calls
                    └─────────────────────────────┘
```

The three levels form a **cognitive escalation ladder** — the system starts with
the cheapest option and escalates only when needed. This is analogous to SOAR's
three processing levels and Kahneman's System 1 / System 2 distinction.

### 5.2 Relationship to Multi-Agent Collaboration

Sub-tasks are INTRA-agent, not INTER-agent. A sub-task does not have:
- Its own identity (no callsign, no DID, no trust profile)
- Its own episodic memory shard
- Its own standing orders or personality
- Social visibility (other agents cannot see sub-task reasoning)

A sub-task is a private cognitive process — the crew agent's inner monologue.
Other agents see only the final output, just as in human conversation — you
see someone's statement, not their internal deliberation.

### 5.3 Relationship to Skills

Skills become more effective with sub-tasks because:
- The skill's behavioral instructions land in the **Compose** sub-task where
  they have focused attention (not competing with thread parsing)
- The skill's self-verification gate (AD-631) maps to a **Reflect** sub-task
- Skill-specific analysis prompts enable domain-tailored thread evaluation
- Skills can declaratively opt into decomposition via frontmatter

### 5.4 Relationship to Cognitive JIT

If a decomposition pattern (Analyze → Compose) consistently produces good
outcomes for a specific intent type, Cognitive JIT can learn it:
- The analysis prompt becomes a cached template
- The composition prompt becomes a cached template
- The decomposition decision itself becomes a learned production rule
- Eventually, the pattern replays without LLM calls (SOAR chunking analog)

This is the ultimate efficiency play: what starts as an expensive multi-call
decomposition gradually compiles into a deterministic procedure.

---

## 6. Open Questions

1. **Decomposition trigger heuristics**: What signals should trigger sub-task
   decomposition vs. single-call? Thread length? Skill annotation? Historical
   quality scores? Dynamic based on self-verification failure?

2. **Model routing for sub-tasks**: Should analysis sub-tasks use a cheaper/
   faster model (analogous to Claude Code's Explore using Haiku)? Or does
   consistency require the same model throughout?

3. **Context carry-forward**: How much of the analysis result should the
   composition step receive? Full structured analysis? Summary? Both with
   priority framing?

4. **Sub-task observability**: How should sub-task execution appear in logs,
   HXI, and the Cognitive Journal? Hidden by default with drill-down? Always
   visible?

5. **Parallel vs. sequential**: Independent sub-tasks (thread analysis +
   episodic recall) could run concurrently. When should parallelism be used?

6. **Failure modes**: What happens when a sub-task returns unexpected/empty
   results? Retry? Skip? Fall back to single-call?

---

## 7. References

1. Yao, S. et al. (2023). "ReAct: Synergizing Reasoning and Acting in
   Language Models." ICLR 2023. arXiv:2210.03629.
2. Khot, T. et al. (2023). "Decomposed Prompting: A Modular Approach for
   Solving Complex Tasks." ICLR 2023. arXiv:2210.02406.
3. Huang, W. et al. (2022). "Inner Monologue: Embodied Reasoning through
   Planning with Language Models." CoRL 2022. arXiv:2207.05608.
4. Yao, S. et al. (2023). "Tree of Thoughts: Deliberate Problem Solving
   with Large Language Models." NeurIPS 2023. arXiv:2305.10601.
5. Shinn, N. et al. (2023). "Reflexion: Language Agents with Verbal
   Reinforcement Learning." NeurIPS 2023. arXiv:2303.11366.
6. Zhou, A. et al. (2023). "Language Agent Tree Search Unifies Reasoning
   Acting and Planning in Language Models." arXiv:2310.04406.
7. Laird, J. (2012). "The Soar Cognitive Architecture." MIT Press.
8. Anderson, J. R. (2007). "How Can the Human Mind Occur in the Physical
   Universe?" Oxford University Press. (ACT-R)
9. Karpas, E. et al. (2022). "MRKL Systems: A Modular, Neuro-Symbolic
   Architecture that Combines Large Language Models, External Knowledge
   Sources and Discrete Reasoning." AI21 Labs.
10. Lipenkova, J. (2023). "Overcoming the Limitations of Large Language
    Models." Towards Data Science.
11. Mei, S. (2025). "Claude Code's Context Forking and Sub-Agent
    Architecture." Analysis. (shiqimei.github.io)
12. Anthropic (2025). Claude Code Documentation: Skills, Sub-agents,
    Agent Tool. (code.claude.com/docs/en/)
13. Kahneman, D. (2011). "Thinking, Fast and Slow." — System 1/System 2
    framework informing the three-level processing model.
