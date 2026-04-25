# Phase 19 — Shapley Value Trust Attribution + Trust-Weighted Capability Matching

## Context

You are building Phase 19 of ProbOS, a probabilistic agent-native OS runtime. Read `PROGRESS.md` for full architectural context. Current state: **1272/1272 tests passing + 11 skipped. Latest AD: AD-222.**

This phase implements two game-theoretic improvements that make ProbOS's trust and agent selection systems meaningfully smarter:

1. **Shapley Value Trust Attribution** — when a consensus outcome succeeds or fails, agents who were *decisive* (removing them would have changed the outcome) get proportionally more trust credit than agents who were *redundant* (the outcome would have been the same without them). Currently all participating agents get equal credit.

2. **Trust-Weighted Capability Matching** — when agents self-select for an intent, the system prefers agents whose capability claims are backed by trust history. Currently `CapabilityRegistry` scores by descriptor similarity alone. An agent claiming "I can analyze data" with trust 0.9 should outscore an identical claim with trust 0.3.

Both are wiring changes between existing subsystems — no new infrastructure needed.

---

## Pre-Build Audit

Before writing any code, verify:

1. **Latest AD number in PROGRESS.md** — confirm AD-222 is the latest. Phase 19 AD numbers start at **AD-223**. If AD-222 is NOT the latest, adjust all AD numbers in this prompt upward accordingly.
2. **Test count** — confirm 1272 tests pass before starting: `uv run pytest tests/ -v`
3. **Read these files thoroughly:**
   - `src/probos/consensus/quorum.py` — understand `QuorumEngine.evaluate()` and `evaluate_values()`. Understand the `Vote` type, confidence weighting, how approval threshold works, what the return value (`ConsensusResult`) contains. The Shapley computation needs access to the vote list
   - `src/probos/consensus/trust.py` — understand `TrustNetwork.record_observation(agent_id, success)`, `get_score(agent_id)`, Beta(alpha, beta) mechanics. The Shapley value multiplies into the trust update
   - `src/probos/mesh/capability.py` — understand `CapabilityRegistry`, the tiered matching system (exact → substring → semantic → keyword), how scores are returned. The trust-weighting multiplies into the match score
   - `src/probos/types.py` — understand `Vote` (agent_id, approved, confidence), `ConsensusResult` (approved, votes, confidence), `ConsensusOutcome`
   - `src/probos/runtime.py` — understand where consensus results are processed and trust is updated after execution. Find where `trust_network.record_observation()` is called after consensus outcomes — that's the Shapley integration point
   - `src/probos/cognitive/decomposer.py` — understand how the DAG executor uses the intent bus, which calls capability matching during agent selection

---

## What To Build

### Step 1: Shapley Value Computation (AD-223)

**File:** `src/probos/consensus/shapley.py` (new)

**AD-223: `compute_shapley_values()` — per-agent marginal contribution to consensus outcomes.** The Shapley value for agent *i* in a coalition *N* is:

```
φᵢ = Σ_{S ⊆ N\{i}} [ |S|! · (|N|-|S|-1)! / |N|! ] · [ v(S ∪ {i}) - v(S) ]
```

Where `v(S)` is the outcome function: does the subset S achieve quorum?

For ProbOS's consensus, `v(S)` = 1 if the votes in subset S would pass the quorum threshold (same threshold logic as `QuorumEngine.evaluate()`), 0 otherwise. For confidence-weighted voting, this means recomputing the weighted sum for each subset.

```python
def compute_shapley_values(
    votes: list[Vote],
    approval_threshold: float,
    use_confidence_weights: bool = True,
) -> dict[str, float]:
    """Compute per-agent Shapley values for a consensus outcome.
    
    Returns: {agent_id: shapley_value} where values sum to 1.0 for the 
    winning coalition (agents who voted with the majority) and represent 
    each agent's marginal contribution to achieving/preventing the outcome.
    
    For a 3-agent quorum: 6 permutations (tractable).
    For a 5-agent quorum: 120 permutations (tractable).
    For a 7-agent quorum: 5040 permutations (still tractable for consensus).
    """
```

Implementation approach — brute-force over all permutations (NOT subsets). The permutation formulation is cleaner for implementation:

```
φᵢ = (1/|N|!) · Σ_{all permutations π} [ v(S_π^i ∪ {i}) - v(S_π^i) ]
```

Where `S_π^i` is the set of agents appearing before *i* in permutation *π*.

For each permutation, iterate through agents in order. Track the running coalition. When adding agent *i*, check if the outcome changes (coalition without *i* fails quorum, coalition with *i* passes, or vice versa). If it changes, *i*'s marginal contribution for this permutation is 1. Average over all permutations.

**Optimization:** For small N (3-7 agents in typical quorums), brute-force `itertools.permutations` is fine — 5040 iterations at worst. Do NOT over-engineer with approximation algorithms.

**Normalization:** Raw Shapley values sum to `v(N)` (1 if quorum passed, 0 if not). Normalize to [0, 1] range so they can be used as trust update multipliers. An agent with Shapley value 0.0 was completely redundant. An agent with Shapley value 1.0 was the sole decisive voter.

**Edge cases:**
- Unanimous approval: all agents equally decisive → equal Shapley values (same as current behavior)
- Single agent: Shapley = 1.0 (trivially decisive)
- Agent voted against the majority: Shapley = 0.0 for the winning outcome (they didn't contribute)
- All agents voted the same way (unanimous): equal split

**Run tests after this step: `uv run pytest tests/ -v` — all 1272 existing tests must still pass.**

---

### Step 2: Wire Shapley into Trust Updates (AD-224)

**File:** `src/probos/consensus/quorum.py` and/or `src/probos/runtime.py`

**AD-224: Shapley-weighted trust updates after consensus.** Find where trust is updated after consensus outcomes. Read the actual code to locate this — it's likely in the runtime's execution path or the DAG executor's consensus handling.

Currently, after a consensus outcome, each participating agent gets `trust_network.record_observation(agent_id, success)` — one observation per agent, equal weight.

Change this: compute Shapley values for the vote set, then use the Shapley value as a multiplier on the trust update. Agents with high Shapley values (decisive) get a stronger signal. Agents with low Shapley values (redundant) get a weaker signal.

The simplest approach: call `record_observation()` conditionally based on the Shapley value. If Shapley ≥ 0.5, record an observation. If Shapley < 0.5, skip (the agent was redundant). A more nuanced approach: record `round(shapley * N)` observations (proportional). Keep it simple — the goal is to differentiate decisive from redundant, not to compute precise credit allocation.

**Recommended approach:** Add an optional `weight: float = 1.0` parameter to `TrustNetwork.record_observation()`. When weight > 1.0, the observation has stronger effect (increment alpha or beta by `weight` instead of 1). When weight < 1.0, weaker effect. The Shapley value feeds directly as the weight. This is backward-compatible — all existing callers pass weight=1.0 (default), preserving current behavior.

If adding a weight parameter to `TrustNetwork` feels too invasive, the alternative is: compute Shapley values in the quorum/runtime layer, and only call `record_observation()` for agents with Shapley > a threshold (e.g., > 0.1). Both approaches work — pick whichever integrates cleanly with the existing code.

**The `ConsensusResult` should carry Shapley values.** Add a `shapley_values: dict[str, float] | None` field to `ConsensusResult` (default None for backward compat). The quorum engine populates it when evaluating. Downstream consumers (trust updates, event log, introspection) can use it.

**Run tests: all 1272 must pass. Existing quorum and trust tests must not break — Shapley with equal votes produces equal values, which behaves identically to the current equal-weight system.**

---

### Step 3: Trust-Weighted Capability Matching (AD-225)

**File:** `src/probos/mesh/capability.py`

**AD-225: Capability match scores weighted by agent trust.** The `CapabilityRegistry` currently scores matches by descriptor similarity alone. Add an optional `trust_scores: dict[str, float] | None` parameter to the matching method (whatever it's called — `find_matches()`, `match()`, `get_matches()` — read the actual code).

When `trust_scores` is provided, the final match score for each agent is:

```
final_score = capability_score * (0.5 + 0.5 * trust_score)
```

This means:
- Trust 1.0 → score multiplied by 1.0 (no change — fully trusted agents keep their full capability score)
- Trust 0.5 → score multiplied by 0.75 (modest penalty)
- Trust 0.0 → score multiplied by 0.5 (halved — untrusted agents still match, but at half weight)

The `0.5 + 0.5 * trust` formula ensures trust never *eliminates* a match (floor at 50%), only *discounts* it. A low-trust agent that's the only one capable of handling an intent still gets selected — it just ranks lower if there's a trusted competitor.

**When `trust_scores` is None (backward compat), no trust weighting is applied.** All existing callers pass None by default.

**The runtime or intent bus needs to pass trust scores into the capability registry call.** Find where agent selection happens during intent dispatch — it's likely in the intent bus or the runtime's execution pipeline. Read the actual code to locate the call site, then wire `trust_network.get_score()` for each candidate agent into the capability match.

**Run tests: all 1272 must pass. Existing capability matching tests must not break — they don't pass trust_scores, so behavior is identical.**

---

### Step 4: Wire Trust Scores into Agent Selection (AD-226)

**File:** `src/probos/runtime.py` or `src/probos/mesh/intent.py` (wherever agent selection happens)

**AD-226: Intent dispatch uses trust-weighted capability matching.** When the intent bus broadcasts an intent and agents self-select, the selection/ranking should incorporate trust scores.

Read the actual agent selection code path to understand where capability matching feeds into routing decisions. The key wiring point is wherever `CapabilityRegistry.find_matches()` (or equivalent) is called during intent dispatch. Pass `trust_scores={agent_id: trust_network.get_score(agent_id) for agent_id in candidate_agents}` to get trust-weighted results.

**Important:** Agent self-selection via `handle_intent()` happens independently — agents decide for themselves whether to handle an intent. Trust-weighted capability matching affects **ranking** when multiple agents respond, not whether an agent responds at all. If only one agent can handle an intent, trust weighting doesn't change the outcome.

If the capability registry isn't involved in the runtime's agent selection path (agents self-select and the quorum engine evaluates), then trust-weighted matching applies at the quorum evaluation stage — confidence-weighted voting already partially achieves this. In that case, document that the wiring point is already covered by AD-19 (confidence-weighted voting) and the new Shapley attribution (AD-224), and the capability registry trust-weighting is only relevant for the StrategyRecommender and future mesh routing. Adapt accordingly — don't force a connection that doesn't exist in the architecture.

**Run tests: all 1272 must pass.**

---

### Step 5: `/trust` Panel Update (AD-227)

**File:** `src/probos/experience/panels.py`

**AD-227: Trust panel shows Shapley attribution info.** Update the trust display (rendered by `/trust` or `/weights` or wherever trust info appears) to include:
- Last Shapley values from the most recent consensus outcome (if available)
- A column or annotation indicating whether each agent was "decisive" or "redundant" in the last consensus

This is a display-only change. Read the existing trust panel code to understand the current format and add a column or section for Shapley info. If `ConsensusResult.shapley_values` is populated, show it. If not (no consensus has occurred), show nothing.

**Run tests: all 1272 must pass.**

---

### Step 6: Tests (target: 1310+ total)

Write comprehensive tests across these test files:

**`tests/test_shapley.py`** (new) — ~20 tests:

*Core computation:*
- 3 agents, unanimous approval → equal Shapley values (each ~0.33)
- 3 agents, 2-of-3 approval, one dissenter → the 2 approvers split credit, dissenter gets 0
- 3 agents, 2-of-3 threshold, one agent is decisive (removing them flips outcome) → higher Shapley value
- 5 agents, 3-of-5 threshold → compute correctly
- Single agent → Shapley = 1.0
- All agents reject → Shapley values for rejectors (they "decided" the rejection)
- Confidence-weighted voting: high-confidence decisive voter gets more credit than low-confidence one
- Empty vote list → empty Shapley dict
- Shapley values sum to ≤ 1.0 (normalized)
- Shapley values are all ≥ 0.0

*Edge cases:*
- Agent voted against the majority → Shapley 0.0 for the majority outcome
- Two agents with identical votes → equal Shapley values
- Very close vote (just barely passes threshold) → the marginal voter has high Shapley value

*Integration with ConsensusResult:*
- `ConsensusResult` carries `shapley_values` field
- `shapley_values` is None by default (backward compat)
- QuorumEngine populates `shapley_values` when evaluating

**`tests/test_trust_weighted_capability.py`** (new) — ~12 tests:

*Trust weighting:*
- Match without trust_scores → same behavior as before
- Match with trust_scores → scores multiplied by trust factor
- Trust 1.0 → no score change
- Trust 0.0 → score halved (floor at 0.5 factor)
- Trust 0.5 → score × 0.75
- Higher trust agent ranks above lower trust agent with same capability score
- Trust weighting doesn't eliminate matches (floor at 50%)
- Multiple agents with different trust → correct ordering

*Shapley-weighted trust updates:*
- Decisive agent gets stronger trust update
- Redundant agent gets weaker trust update
- Equal votes → equal trust updates (same as before)
- Trust weight parameter on `record_observation()` works correctly (if this approach is chosen)

**Update existing tests if needed** — check:
- `tests/test_quorum.py` — ensure `ConsensusResult` new field doesn't break existing assertions
- `tests/test_trust.py` — ensure `record_observation` weight parameter (if added) doesn't break existing callers
- `tests/test_capability.py` — ensure trust_scores parameter doesn't break existing match tests

**Run final test suite: `uv run pytest tests/ -v` — target 1310+ tests passing (1272 existing + ~38 new). All 11 skipped tests remain skipped.**

---

## AD Summary

| AD | Decision |
|----|----------|
| AD-223 | `compute_shapley_values()`: brute-force permutation algorithm for small coalitions (3-7 agents). Marginal contribution = does adding agent *i* change the quorum outcome? Normalized to [0, 1]. Edge cases: unanimous → equal split, dissenter → 0.0 |
| AD-224 | Shapley-weighted trust updates: decisive agents get stronger trust signal, redundant agents get weaker. `ConsensusResult` carries `shapley_values: dict[str, float] | None`. Weight parameter on `record_observation()` or conditional call based on Shapley threshold |
| AD-225 | Trust-weighted capability matching: `final_score = capability_score * (0.5 + 0.5 * trust_score)`. Floor at 50% — trust discounts but never eliminates matches. Optional `trust_scores` parameter for backward compat |
| AD-226 | Trust scores wired into agent selection during intent dispatch. If the architecture routes through capability matching, trust_scores are passed. If agents self-select and quorum handles quality, document that AD-19 + AD-224 already cover this |
| AD-227 | Trust panel shows Shapley attribution: decisive/redundant indicator per agent from most recent consensus outcome |

---

## Do NOT Build

- **Approximate Shapley** (sampling-based estimation for large coalitions) — ProbOS quorums are 3-7 agents; brute-force is fine
- **Shapley for non-consensus outcomes** (applying to Hebbian or feedback) — Shapley is specifically about coalition games; consensus is the coalition
- **Trust-weighted decomposition** (decomposer preferring trusted agents when building DAGs) — the decomposer builds intent-level plans, not agent-level assignments; agent selection happens at dispatch time
- **Changes to the Hebbian router** — Hebbian routing already encodes learned affinity. Trust-weighted matching is a separate, complementary signal
- **Changes to the FeedbackEngine** — feedback trust updates use a flat weight (Phase 18). Shapley applies to consensus outcomes, not human feedback
- **New slash commands** — no new commands; Shapley info appears in existing trust/status displays
- **Changes to the dreaming engine** — dream consolidation uses its own trust update mechanics (AD-58). Shapley applies to real-time consensus, not replay

---

## Milestone

Demonstrate the following:

**Shapley Value:**
1. Three agents vote on a consensus outcome with threshold 0.6
2. Agent A (confidence 0.9) approves, Agent B (confidence 0.3) approves, Agent C (confidence 0.8) rejects
3. The outcome is approved (weighted approval > 0.6)
4. Shapley computation shows Agent A was decisive (removing A would flip the outcome), Agent B was redundant (removing B still passes)
5. Agent A gets a stronger trust boost than Agent B
6. `/trust` (or equivalent panel) shows Shapley attribution

**Trust-Weighted Matching:**
7. Two agents both claim capability for `read_file`
8. Agent X has trust 0.9, Agent Y has trust 0.3
9. Capability matching with trust weighting ranks X above Y
10. Without trust weighting (backward compat), both rank equally

---

## Update PROGRESS.md When Done

Add Phase 19 section with:
- AD decisions (AD-223 through AD-227)
- Files changed/created table
- Test count (target: 1310+)
- Update the Current Status line at the top
- Update the What's Been Built tables for new/changed files
- Mark the Shapley Value Trust Attribution roadmap item as complete
- Mark the Trust-Weighted Capability Matching roadmap item as complete
- Update the QuorumEngine description to mention Shapley values
- Update the CapabilityRegistry description to mention trust-weighted matching
- Update the TrustNetwork description to mention weighted observations (if applicable)
