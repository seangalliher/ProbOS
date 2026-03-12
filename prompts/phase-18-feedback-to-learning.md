# Phase 18 — Feedback-to-Learning Loop

## Context

You are building Phase 18 of ProbOS, a probabilistic agent-native OS runtime. Read `PROGRESS.md` for full architectural context. Current state: **1227/1227 tests passing + 11 skipped. Latest AD: AD-215.**

Phase 16 introduced DAG Proposal Mode (`/plan`, `/approve`, `/reject`). Phase 18 closes the loop: user signals after execution — approval, rejection, correction — feed into Hebbian weight updates, trust adjustments, and tagged episodic memory. Currently, `/approve` executes the DAG and `/reject` discards it, but neither signal trains the system. Escalation outcomes (Tier 3) are recorded but don't modify routing or trust. This phase wires human judgment into the learning substrate.

Human feedback is the **highest-quality training signal available** — it's a deliberate judgment from a cognitive participant, not an automated consensus outcome. The system should learn faster from human feedback than from agent-to-agent interactions.

---

## Pre-Build Audit

Before writing any code, verify:

1. **Latest AD number in PROGRESS.md** — confirm AD-215 is the latest. Phase 18 AD numbers start at **AD-216**. If AD-215 is NOT the latest, adjust all AD numbers in this prompt upward accordingly.
2. **Test count** — confirm 1227 tests pass before starting: `uv run pytest tests/ -v`
3. **Read these files thoroughly:**
   - `src/probos/runtime.py` — understand `_execute_dag()`, `process_natural_language()`, `execute_proposal()`, `reject_proposal()`, `_last_execution`, `_pending_proposal_text`, episodic episode storage. Execution results include a `TaskDAG` where each node has `status`, `result` (which may contain `agent_id`), and intent metadata
   - `src/probos/mesh/routing.py` — understand `HebbianRouter`: `record_interaction(source_id, target_id, success, rel_type)`, weight update formula (`weight = weight * decay + reward`), `preferred_targets()`. The `rel_type` field supports `"intent"` (intent→agent) and `"agent"` (agent→agent) connection types
   - `src/probos/consensus/trust.py` — understand `TrustNetwork`: `record_observation(agent_id, success)` updates Beta(alpha, beta). Success increments alpha, failure increments beta. `get_score()` returns mean of Beta distribution
   - `src/probos/cognitive/episodic.py` — understand `EpisodicMemory.store()`, `Episode` fields (query, dag_summary, outcomes, reflection, agent_ids, timestamp). Episodes are recalled by the decomposer during planning via `recall_similar()`
   - `src/probos/cognitive/dreaming.py` — understand how the DreamingEngine uses episodes for Hebbian strengthening/weakening and trust consolidation. Human feedback should influence dreaming too
   - `src/probos/experience/shell.py` — understand the `/plan`, `/approve`, `/reject` command flow and general command dispatch pattern
   - `src/probos/types.py` — understand `Episode`, `TaskNode`, `TaskDAG`, `IntentResult`

---

## What To Build

### Step 1: `/feedback` Command (AD-216)

**File:** `src/probos/experience/shell.py`

**AD-216: `/feedback good|bad` command for post-execution human signal.** A new slash command that lets the user rate the most recent execution:

- `/feedback good` — the user is satisfied with the result
- `/feedback bad` — the user is dissatisfied with the result
- `/feedback` (no argument) — print usage: `"Usage: /feedback good|bad — rate the last execution"`

The command operates on `runtime._last_execution` (the most recent executed DAG). If no execution has occurred yet, print `"No recent execution to rate."`.

Each execution can only be rated once. Track this with a `_last_feedback_applied: bool` flag on the runtime (reset to `False` at the start of each new execution in `_execute_dag()` and `process_natural_language()`). If the user tries to rate twice, print `"Feedback already recorded for this execution."`.

**Update `/help` to include `/feedback`.**

**Run tests after this step: `uv run pytest tests/ -v` — all 1227 existing tests must still pass.**

---

### Step 2: Feedback Engine (AD-217, AD-218)

**File:** `src/probos/cognitive/feedback.py` (new)

**AD-217: `FeedbackEngine` — applies human feedback signals to trust, Hebbian routing, and episodic memory.** A new module that encapsulates all feedback-to-learning logic.

```python
class FeedbackEngine:
    """Applies human feedback signals to the learning substrate."""
    
    def __init__(
        self,
        trust_network: TrustNetwork,
        hebbian_router: HebbianRouter,
        episodic_memory: EpisodicMemory | None = None,
        event_log: EventLog | None = None,
        feedback_hebbian_reward: float = 0.10,  # 2x normal Hebbian reward (0.05)
        feedback_trust_weight: float = 1.5,     # Stronger than normal observation
    ):
```

Core methods:

- `async apply_execution_feedback(dag: TaskDAG, positive: bool, original_text: str) -> FeedbackResult` — the main entry point. Extracts participating agent IDs from the executed DAG's node results, then:
  1. **Hebbian updates** — for each node in the DAG, if the node has a result with an `agent_id`, record a Hebbian interaction between the intent name and the agent_id with `rel_type="intent"`. Use `feedback_hebbian_reward` (default 0.10 — double the normal 0.05) because human feedback is a higher-quality signal. Positive feedback → `success=True`, negative → `success=False`.
  2. **Trust updates** — for each participating agent, call `trust_network.record_observation(agent_id, success=positive)`. The observation weight is amplified by `feedback_trust_weight` (default 1.5) — record multiple observations to amplify the signal. Concretely: for weight 1.5, record 1 observation (the integer floor) plus a fractional probability of a 2nd observation. Or simpler: just call `record_observation()` once per agent — the dedicated feedback reward factor distinguishes it from normal execution feedback. **Keep it simple: one `record_observation()` call per agent.** The amplification is in the Hebbian reward, not trust micro-manipulation.
  3. **Episodic memory** — store a feedback-tagged episode with metadata that the decomposer can use in future planning context. See AD-218.
  4. **Event log** — record `feedback_positive` or `feedback_negative` event.

- `async apply_rejection_feedback(proposal_text: str, dag: TaskDAG) -> FeedbackResult` — when the user rejects a proposal via `/reject`. No agents executed, so no per-agent trust/Hebbian updates. Instead:
  1. **Episodic memory** — store a rejection-tagged episode so the decomposer sees "user rejected a plan like this before" in future context. The episode records the original text, the proposed plan, and the `human_feedback: "rejected_plan"` tag.
  2. **Event log** — record `feedback_plan_rejected` event.

**AD-218: Feedback-tagged episodes.** Episodes created by the FeedbackEngine carry a `human_feedback` field in their metadata:

- `human_feedback: "positive"` — user approved the execution result
- `human_feedback: "negative"` — user disapproved the execution result
- `human_feedback: "rejected_plan"` — user rejected the proposed plan before execution

The episode's `query` field contains the original user text. The `dag_summary` contains the intent names and structure. The `outcomes` field contains `"human_positive"`, `"human_negative"`, or `"plan_rejected"`. The `agent_ids` field contains participating agent IDs (empty for rejected plans).

These tagged episodes are recalled by the decomposer via `recall_similar()` just like any other episode. When the decomposer is planning a similar task, the feedback episode appears in the PAST EXPERIENCE section of the LLM prompt. A `"human_negative"` episode for a similar query signals "this approach didn't satisfy the user — try something different." A `"rejected_plan"` episode signals "the user didn't want this kind of plan."

**`FeedbackResult` dataclass:**

```python
@dataclasses.dataclass
class FeedbackResult:
    feedback_type: str  # "positive", "negative", "rejected_plan"
    agents_updated: list[str]  # agent IDs that received trust/Hebbian updates
    episode_stored: bool
    original_text: str
```

**Run tests: all 1227 must pass.**

---

### Step 3: Wire into Runtime (AD-219)

**File:** `src/probos/runtime.py`

**AD-219: FeedbackEngine creation and wiring.** 

1. Create `FeedbackEngine` in `ProbOSRuntime.start()` (after trust_network, hebbian_router, and episodic_memory are available). Store as `self.feedback_engine`.

2. Add `async def record_feedback(self, positive: bool) -> FeedbackResult | None`:
   - If `_last_execution` is None, return None
   - If `_last_feedback_applied` is True, return None
   - Call `self.feedback_engine.apply_execution_feedback(self._last_execution, positive, original_text)`
   - Set `_last_feedback_applied = True`
   - Return the result

3. Add `_last_feedback_applied: bool = False` to runtime state. Reset to `False` at the top of `_execute_dag()` and `process_natural_language()`.

4. Update `reject_proposal()`: after discarding the proposal, if `feedback_engine` is available, call `feedback_engine.apply_rejection_feedback(self._pending_proposal_text, self._pending_proposal)`. This wires `/reject` into the learning loop automatically — no separate feedback command needed for rejections.

5. Store `_last_execution_text: str | None` to track the original user text for the most recent execution (needed for feedback episode creation). Set this at the start of `process_natural_language()` and `execute_proposal()`.

**Run tests: all 1227 must pass.**

---

### Step 4: Wire Shell Commands (AD-220)

**File:** `src/probos/experience/shell.py`

**AD-220: `/feedback` command wired to runtime.** 

- `/feedback good` calls `runtime.record_feedback(positive=True)`. Displays: `"✓ Feedback recorded — trust and routing updated for N agents"` (where N is `len(result.agents_updated)`).
- `/feedback bad` calls `runtime.record_feedback(positive=False)`. Displays: `"✓ Negative feedback recorded — trust and routing adjusted for N agents"`.
- Handle None return (no execution or already rated) with appropriate messages.

Also update the `/reject` command handler: after calling `runtime.reject_proposal()`, display `"Proposal discarded. Feedback recorded for future planning."` (instead of just `"Proposal discarded."`) when feedback was applied.

**Run tests: all 1227 must pass.**

---

### Step 5: Extracting Agent IDs from Executed DAGs (AD-221)

**File:** `src/probos/cognitive/feedback.py`

**AD-221: Agent ID extraction from executed TaskDAG.** The `FeedbackEngine` needs to identify which agents participated in an execution. Agent IDs come from the DAG's node results. Read the actual `TaskNode` and `IntentResult` structures carefully to determine exactly where `agent_id` lives in the executed DAG.

The extraction logic:

```python
def _extract_agent_ids(self, dag: TaskDAG) -> list[str]:
    """Extract unique agent IDs from an executed DAG's node results."""
    agent_ids = []
    for node in dag.nodes:
        if node.result and isinstance(node.result, dict):
            agent_id = node.result.get("agent_id")
            if agent_id and agent_id not in agent_ids:
                agent_ids.append(agent_id)
        elif hasattr(node.result, "agent_id"):
            if node.result.agent_id and node.result.agent_id not in agent_ids:
                agent_ids.append(node.result.agent_id)
    return agent_ids
```

**Important:** Read the actual code to understand how `IntentResult` is stored on `TaskNode.result` — it may be serialized to dict, or it may be the raw `IntentResult` object. Handle both cases. Also handle nodes that failed or were never executed (no result).

Similarly, extract intent names from nodes for Hebbian routing:

```python
def _extract_intent_agent_pairs(self, dag: TaskDAG) -> list[tuple[str, str]]:
    """Extract (intent_name, agent_id) pairs for Hebbian updates."""
    pairs = []
    for node in dag.nodes:
        intent = node.intent
        agent_id = self._get_agent_id_from_node(node)
        if intent and agent_id:
            pairs.append((intent, agent_id))
    return pairs
```

**Run tests: all 1227 must pass.**

---

### Step 6: Event Log Integration (AD-222)

**File:** `src/probos/cognitive/feedback.py`

**AD-222: Feedback events in event log.**

- `feedback_positive` — user rated execution positively. Data: `{agents: list[str], intent_count: int, text: str}`
- `feedback_negative` — user rated execution negatively. Data: `{agents: list[str], intent_count: int, text: str}`
- `feedback_plan_rejected` — user rejected a proposed plan. Data: `{intent_count: int, text: str}`
- `feedback_hebbian_update` — Hebbian weights updated from feedback. Data: `{pairs: list[tuple[str, str]], positive: bool}`
- `feedback_trust_update` — trust updated from feedback. Data: `{agents: list[str], positive: bool}`

Category: `"cognitive"`.

**Run tests: all 1227 must pass.**

---

### Step 7: Tests (target: 1260+ total)

Write comprehensive tests across these test files:

**`tests/test_feedback_engine.py`** (new) — ~22 tests:

*Feedback application:*
- `apply_execution_feedback()` with positive=True updates Hebbian weights (strengthens)
- `apply_execution_feedback()` with positive=False updates Hebbian weights (weakens)
- `apply_execution_feedback()` with positive=True boosts trust for participating agents
- `apply_execution_feedback()` with positive=False penalizes trust for participating agents
- `apply_execution_feedback()` stores feedback-tagged episode
- `apply_execution_feedback()` returns FeedbackResult with correct agents_updated
- `apply_execution_feedback()` uses `feedback_hebbian_reward` (0.10, not default 0.05)
- `apply_execution_feedback()` with empty DAG (no nodes) returns empty agents list
- `apply_execution_feedback()` with failed nodes (no agent_id) skips those nodes
- `apply_execution_feedback()` deduplicates agent IDs (same agent in multiple nodes)

*Rejection feedback:*
- `apply_rejection_feedback()` stores rejection-tagged episode
- `apply_rejection_feedback()` does NOT update trust (no agents executed)
- `apply_rejection_feedback()` does NOT update Hebbian weights
- `apply_rejection_feedback()` returns FeedbackResult with `feedback_type="rejected_plan"`
- `apply_rejection_feedback()` episode has `human_feedback: "rejected_plan"` in metadata

*Agent ID extraction:*
- `_extract_agent_ids()` extracts from dict results
- `_extract_agent_ids()` extracts from IntentResult objects
- `_extract_agent_ids()` handles missing results (pending/failed nodes)
- `_extract_agent_ids()` deduplicates
- `_extract_intent_agent_pairs()` returns correct (intent, agent_id) pairs

*Episode tagging:*
- Positive feedback episode has `human_feedback: "positive"` 
- Negative feedback episode has `human_feedback: "negative"`

**`tests/test_feedback_runtime.py`** (new) — ~12 tests:

*Runtime integration:*
- `record_feedback()` returns None when no execution
- `record_feedback()` returns None when already rated
- `record_feedback(positive=True)` calls feedback engine
- `record_feedback(positive=False)` calls feedback engine
- `_last_feedback_applied` resets on new `process_natural_language()`
- `_last_feedback_applied` resets on new `_execute_dag()`
- `reject_proposal()` calls `apply_rejection_feedback()` when feedback engine available
- `reject_proposal()` works without feedback engine (backward compat)
- `_last_execution_text` tracks original text
- `/feedback good` via shell displays correct message
- `/feedback bad` via shell displays correct message
- `/feedback` with no args displays usage

**Run final test suite: `uv run pytest tests/ -v` — target 1260+ tests passing (1227 existing + ~34 new). All 11 skipped tests remain skipped.**

---

## AD Summary

| AD | Decision |
|----|----------|
| AD-216 | `/feedback good\|bad` shell command. Operates on `_last_execution`. One rating per execution (`_last_feedback_applied` flag). Reset on each new execution |
| AD-217 | `FeedbackEngine`: applies human signals to trust, Hebbian routing, and episodic memory. `feedback_hebbian_reward=0.10` (2x normal) because human feedback is higher quality. One `record_observation()` per agent for trust |
| AD-218 | Feedback-tagged episodes: `human_feedback` field in episode metadata (`"positive"`, `"negative"`, `"rejected_plan"`). Recalled by decomposer via `recall_similar()` to influence future planning |
| AD-219 | `FeedbackEngine` created in runtime, wired to `record_feedback()`. `reject_proposal()` auto-applies rejection feedback. `_last_feedback_applied` and `_last_execution_text` state tracking |
| AD-220 | `/feedback` command wired to `runtime.record_feedback()`. `/reject` display updated to indicate feedback was recorded |
| AD-221 | Agent ID extraction from executed DAGs: handles dict results, IntentResult objects, missing results, deduplication. Intent→agent pairs for Hebbian updates |
| AD-222 | Event log: `feedback_positive`, `feedback_negative`, `feedback_plan_rejected`, `feedback_hebbian_update`, `feedback_trust_update`. Category: `cognitive` |

---

## Do NOT Build

- **Automatic feedback prompts** ("Was this helpful? [y/n]" after every execution) — feedback is opt-in via `/feedback`, not forced
- **Correction mode** (`/feedback correct <text>`) where the user provides what the right answer should have been — future enhancement, needs richer episode schema
- **Feedback-weighted dreaming** (dream cycle treats human-feedback episodes differently from normal episodes) — future enhancement, the dreaming engine already replays episodes and applies trust consolidation; feedback-tagged episodes participate in this naturally
- **Goal management** (persistent goals, conflict arbitration) — future phase
- **Interactive Execution mode** (pause/inject/redirect mid-flight) — future phase
- **CollaborationEvent type** — deferred until HXI implementation
- **Changes to the decomposer** — decomposition logic unchanged; feedback influences it indirectly through episodic recall (tagged episodes appear in PAST EXPERIENCE context)
- **Changes to the DreamingEngine** — dreaming already processes all episodes including feedback-tagged ones. No special handling needed now
- **Feedback on escalation outcomes** — Tier 3 escalation already has approve/reject; wiring those into the learning loop is a clean follow-on but out of scope here

---

## Milestone

Demonstrate the following end-to-end:

1. User types `/plan read the file /tmp/test.txt and summarize it`
2. ProbOS proposes a DAG: `read_file` → reflect
3. User types `/approve` — DAG executes successfully
4. User types `/feedback good`
5. System responds: `"✓ Feedback recorded — trust and routing updated for 1 agent"`
6. Hebbian weight for `read_file` → `FileReaderAgent` is strengthened (by 0.10, not 0.05)
7. Trust for the participating FileReaderAgent is boosted
8. A feedback episode is stored with `human_feedback: "positive"` and the original query
9. Event log shows: `feedback_positive`, `feedback_hebbian_update`, `feedback_trust_update`

And separately:

10. User types `/plan delete all system files`
11. ProbOS proposes a DAG with `run_command` (consensus-gated)
12. User types `/reject`
13. System responds: `"Proposal discarded. Feedback recorded for future planning."`
14. A rejection episode is stored with `human_feedback: "rejected_plan"`
15. Next time the user asks something similar, the decomposer sees the rejection episode in PAST EXPERIENCE context
16. No trust or Hebbian updates (no agents executed)

And:

17. User types `/feedback good` again → `"Feedback already recorded for this execution."`
18. User types `/feedback` with no prior execution → `"No recent execution to rate."`

---

## Update PROGRESS.md When Done

Add Phase 18 section with:
- AD decisions (AD-216 through AD-222)
- Files changed/created table
- Test count (target: 1260+)
- Update the Current Status line at the top
- Update the What's Been Built tables for new/changed files
- Mark the Feedback-to-Learning portion of the "Human-Agent Collaboration" roadmap item as complete (DAG Proposals already marked complete from Phase 16)
- Add `/feedback` to the shell command list in the experience layer description
