# Phase 16 — DAG Proposal Mode

## Context

You are building Phase 16 of ProbOS, a probabilistic agent-native OS runtime. Read `PROGRESS.md` for full architectural context. Current state: **1145/1145 tests passing + 11 skipped. Latest AD: AD-203.**

ProbOS currently treats the user as a command issuer — type text, the system decomposes, executes, and presents results. The user never sees the plan before execution. This phase introduces **DAG Proposal Mode**: the user can ask ProbOS to show its plan before executing it. The user reviews the proposed DAG, can approve (execute), reject (discard), or remove nodes, then approve the modified plan. This is the first step toward the Noöplex's Guided Decomposition collaboration mode (§5) — the human becomes a cognitive participant in planning, not just a command issuer.

**Scope is bounded.** This phase is DAG proposal + approve/reject/remove. It is NOT the feedback-to-learning loop (Hebbian/trust updates from user signals) — that's a follow-on phase.

---

## Pre-Build Audit

Before writing any code, verify:

1. **Latest AD number in PROGRESS.md** — confirm AD-203 is the latest. Phase 16 AD numbers start at **AD-204**. If AD-203 is NOT the latest, adjust all AD numbers in this prompt upward accordingly.
2. **Test count** — confirm 1145 tests pass before starting: `uv run pytest tests/ -v`
3. **Pre-build cleanup:** Verify `StrategyRecommender._compute_text_similarity()` in `src/probos/cognitive/strategy.py`. If it reimplements bag-of-words instead of using the shared `compute_similarity()` from `probos.mesh.capability`, replace it with an import of the shared function. This is a bug fix, not a new AD. `compute_similarity()` is already imported in `strategy.py` per AD-175, so if a second similarity function was added in Phase 15b, remove it and route callers through the existing import. Run tests after this fix.
4. **Read these files thoroughly:**
   - `src/probos/types.py` — understand `TaskNode` fields (id, intent, params, depends_on, status, result, background, escalation_result) and `TaskDAG` fields (nodes, response, reflect)
   - `src/probos/cognitive/decomposer.py` — understand `IntentDecomposer.decompose()` return value (TaskDAG), the `response` field for conversational replies, `is_capability_gap()`, the workflow cache fast-path
   - `src/probos/runtime.py` — understand `process_natural_language()` flow: decompose → check capability gap → check self-mod → execute DAG → reflect → store episode. This is the flow that proposal mode intercepts
   - `src/probos/experience/shell.py` — understand the REPL loop, slash command pattern, NL input routing, user approval callback pattern (self-mod approval AD-123)
   - `src/probos/experience/renderer.py` — understand `ExecutionRenderer`, DAG display (currently debug-only AD-90), event callback
   - `src/probos/experience/panels.py` — understand rendering patterns, `render_dag_result()`
   - `src/probos/cognitive/prompt_builder.py` — understand `IntentDescriptor` and how the decomposer knows which intents require consensus

---

## What To Build

### Step 1: Runtime Proposal API (AD-204, AD-205)

**File:** `src/probos/runtime.py`

**AD-204: `propose()` method on `ProbOSRuntime`.** Add `async def propose(self, text: str, on_event=None) -> TaskDAG` that decomposes natural language into a `TaskDAG` without executing it. This method:

1. Runs the same pre-decomposition steps as `process_natural_language()`: attention focus update, dream scheduler activity tracking, pre-warm intent sync, episodic recall for context
2. Calls `self.decomposer.decompose()` to get the `TaskDAG`
3. Does NOT execute the DAG — no `DAGExecutor`, no consensus, no reflect, no episode storage
4. Stores the result as `self._pending_proposal: TaskDAG | None`
5. Returns the `TaskDAG` to the caller

If the decomposer returns a conversational response (`dag.response` is set, no nodes), return it as-is — the shell will display the response and there's nothing to propose. If the decomposer returns a capability gap, return it as-is — the shell can trigger self-mod from a proposal just like from normal execution.

**AD-205: `execute_proposal()` and `reject_proposal()` on `ProbOSRuntime`.** Two methods to resolve a pending proposal:

- `async def execute_proposal(self, on_event=None) -> TaskDAG | None` — executes `self._pending_proposal` through the normal DAG execution pipeline (executor, consensus, reflect, episode storage). Clears `_pending_proposal` after execution. Returns the executed DAG with results, or `None` if no pending proposal. This reuses the existing execution path in `process_natural_language()` — extract the execution portion into a private method `_execute_dag()` that both `process_natural_language()` and `execute_proposal()` call.

- `def reject_proposal(self) -> bool` — discards `self._pending_proposal`, returns `True` if there was a proposal to reject, `False` if none pending.

- `def remove_proposal_node(self, node_index: int) -> TaskNode | None` — removes a node by index (0-based position in `dag.nodes`). Returns the removed node, or `None` if index is out of range. After removal, clean up dependency references: iterate remaining nodes and remove the deleted node's `id` from their `depends_on` lists. Does NOT cascade-remove dependent nodes — if a downstream node loses a dependency, it simply becomes earlier in the execution order. The user can see this in the updated proposal display and remove additional nodes if needed.

**Key:** `_execute_dag()` is a refactor, not new behavior. Extract the portion of `process_natural_language()` from "execute the DAG" through "store episode" into a private method. Both `process_natural_language()` and `execute_proposal()` call it. This avoids code duplication and ensures proposal execution has identical behavior to normal execution (consensus, escalation, reflect, episodic storage, workflow cache).

**Run tests after this step: `uv run pytest tests/ -v` — all 1145 existing tests must still pass. The refactor of `process_natural_language()` must not change its behavior.**

---

### Step 2: Proposal Panel (AD-206)

**File:** `src/probos/experience/panels.py`

**AD-206: `render_dag_proposal()` panel.** A Rich rendering function that displays a proposed `TaskDAG` as a readable, numbered plan. The user needs to understand what will happen before approving.

Display format — a Rich Table with:
- **#** — node index (0-based, used for `/plan remove N`)
- **Intent** — the intent name (e.g., `read_file`, `write_file`, `run_command`)
- **Params** — key parameters, truncated if long
- **Depends On** — which other node indices this node depends on (map node IDs to indices for readability)
- **Consensus** — whether this intent requires consensus (look up from the runtime's intent descriptors, or infer from known consensus-gated intents: `write_file`, `run_command`, `http_fetch`)
- **Reflect** — whether reflect is requested

Wrap in a Rich Panel with a title like `"Proposed Plan — /approve to execute, /reject to discard, /plan remove N to remove a step"`.

If the DAG has a `reflect` field set to `True`, note this below the table: `"Post-execution reflection: enabled"`.

Keep this simple and readable. The goal is a quick scan, not a comprehensive debug view. The existing debug-mode DAG display (AD-90) shows raw JSON — this is the human-friendly version.

**Run tests: all 1145 must pass.**

---

### Step 3: Shell Commands (AD-207, AD-208)

**File:** `src/probos/experience/shell.py`

**AD-207: `/plan <text>` command.** A new slash command that triggers proposal mode:

1. User types `/plan read my config file and summarize it`
2. Shell calls `runtime.propose(text)`
3. If the result has `response` (conversational), display it normally — nothing to propose
4. If the result is a capability gap, trigger self-mod flow (same as normal NL routing)
5. Otherwise, render the proposed DAG using `render_dag_proposal(dag)` from panels
6. Print usage hint: `"Use /approve to execute, /reject to discard, or /plan remove N to remove a step"`

**AD-208: `/approve`, `/reject`, `/plan remove <N>` commands.**

- `/approve` — calls `runtime.execute_proposal(on_event=renderer.on_event)`. If no pending proposal, print `"No pending proposal. Use /plan <text> to create one."`. If there is one, execute through the normal renderer flow (spinner, progress, results, reflect) — reuse the existing `ExecutionRenderer` patterns. After execution, display results as usual.

- `/reject` — calls `runtime.reject_proposal()`. Print `"Proposal discarded."` or `"No pending proposal."`.

- `/plan remove <N>` — calls `runtime.remove_proposal_node(int(N))`. If successful, re-render the updated proposal using `render_dag_proposal()`. If the index is invalid, print `"Invalid node index. Use /plan to see current proposal."`. If no pending proposal, print `"No pending proposal."`.

- `/plan` (no arguments) — if there's a pending proposal, re-display it. If not, print usage: `"Usage: /plan <text> to propose a plan"`.

**Shell REPL integration:** Add `/plan`, `/approve`, and `/reject` to the command dispatch. Normal NL input should NOT be affected — typing text without `/plan` still executes immediately through the existing `process_natural_language()` path. A pending proposal does not block normal input. If the user types normal text while a proposal is pending, the proposal stays pending (not silently discarded). The user can `/reject` it later or it gets replaced by a new `/plan`.

**Update `/help` output** to include the new commands.

**Run tests: all 1145 must pass.**

---

### Step 4: Event Log Integration (AD-209)

**File:** `src/probos/runtime.py`

**AD-209: Proposal lifecycle events.** Log proposal lifecycle to the event log:

- `proposal_created` — when `propose()` returns a non-empty DAG (not conversational, not capability gap). Data: `{text: str, node_count: int}`
- `proposal_approved` — when `execute_proposal()` starts execution. Data: `{node_count: int}`
- `proposal_rejected` — when `reject_proposal()` discards. Data: `{node_count: int}`
- `proposal_node_removed` — when `remove_proposal_node()` succeeds. Data: `{removed_intent: str, remaining_count: int}`

Use the existing `EventLog` append pattern. Category: `"cognitive"` (same as other decomposer events).

**Run tests: all 1145 must pass.**

---

### Step 5: Tests (target: 1180+ total)

Write comprehensive tests across these test files:

**`tests/test_dag_proposal.py`** (new) — ~25 tests:

*Runtime propose/execute/reject:*
- `propose()` returns TaskDAG without executing
- `propose()` stores `_pending_proposal`
- `propose()` with conversational response does not create pending proposal
- `propose()` replaces existing pending proposal
- `execute_proposal()` executes the pending DAG
- `execute_proposal()` clears `_pending_proposal` after execution
- `execute_proposal()` returns None when no pending proposal
- `execute_proposal()` runs through consensus pipeline (same as normal execution)
- `execute_proposal()` stores episode in episodic memory
- `execute_proposal()` stores in workflow cache on success
- `execute_proposal()` runs reflect step when `dag.reflect=True`
- `reject_proposal()` clears `_pending_proposal`
- `reject_proposal()` returns False when no pending proposal
- `process_natural_language()` still works identically (refactor didn't break it)
- `_execute_dag()` shared by both `process_natural_language()` and `execute_proposal()`

*Node removal:*
- `remove_proposal_node()` removes node by index
- `remove_proposal_node()` returns removed TaskNode
- `remove_proposal_node()` returns None for invalid index
- `remove_proposal_node()` returns None when no pending proposal
- `remove_proposal_node()` cleans up dependency references in remaining nodes
- Removing a node that others depend on updates their `depends_on` lists
- Removing last node leaves empty `nodes` list (still a valid proposal — `/approve` on empty proposal is a no-op or returns immediately)

*Panel rendering:*
- `render_dag_proposal()` returns Rich Panel
- `render_dag_proposal()` shows correct node count
- `render_dag_proposal()` maps node IDs to readable indices in dependency column
- `render_dag_proposal()` with empty nodes list renders gracefully

*Event log:*
- `proposal_created` event logged on `propose()`
- `proposal_approved` event logged on `execute_proposal()`
- `proposal_rejected` event logged on `reject_proposal()`
- `proposal_node_removed` event logged on `remove_proposal_node()`

**Update existing tests if needed** — check:
- `tests/test_experience.py` — if it tests `process_natural_language()` end-to-end, verify the refactored `_execute_dag()` path still passes
- `tests/test_runtime.py` (or wherever runtime tests live) — same concern

**Run final test suite: `uv run pytest tests/ -v` — target 1180+ tests passing (1145 existing + ~35 new). All 11 skipped tests remain skipped.**

---

## AD Summary

| AD | Decision |
|----|----------|
| AD-204 | `propose()` on ProbOSRuntime: decomposes NL to TaskDAG without executing. Stores as `_pending_proposal`. Same pre-decomposition steps as `process_natural_language()` (attention, dreaming, episodic context) |
| AD-205 | `execute_proposal()` / `reject_proposal()` / `remove_proposal_node()`. Execution via shared `_execute_dag()` private method (refactored from `process_natural_language()`). Node removal cleans dependency references without cascading |
| AD-206 | `render_dag_proposal()` panel: numbered table with intent, params, dependencies (as indices), consensus flag, reflect flag. Human-readable plan display |
| AD-207 | `/plan <text>` shell command triggers proposal mode. Handles conversational responses and capability gaps same as normal NL routing |
| AD-208 | `/approve`, `/reject`, `/plan remove N` commands. `/plan` with no args re-displays pending proposal. Normal NL input unaffected — pending proposals persist until explicitly resolved |
| AD-209 | Proposal lifecycle events: `proposal_created`, `proposal_approved`, `proposal_rejected`, `proposal_node_removed`. Category: `cognitive` |

---

## Do NOT Build

- **Feedback-to-learning loop** (Hebbian/trust updates from user approval/rejection signals) — follow-on phase
- **Node parameter modification** (editing params on a proposed node) — future enhancement
- **Node addition** (inserting new nodes into a proposed DAG) — future enhancement
- **Constraint injection** (adding constraints like "use only local agents") — future enhancement
- **Interactive Execution mode** (pause/inject/redirect mid-flight) — future phase, needs DAG executor mutations
- **Goal management** (persistent goals, conflict arbitration) — future phase
- **CollaborationEvent type** — deferred until HXI implementation
- **Changes to the decomposer** — `decompose()` API unchanged; the proposal mode operates entirely at the runtime/shell level
- **Changes to existing slash commands** — all existing commands work identically
- **Auto-proposal mode** (all inputs go through proposal first) — `/plan` is opt-in

---

## Milestone

Demonstrate the following end-to-end:

1. User types `/plan read the file /tmp/test.txt and write a summary to /tmp/summary.txt`
2. ProbOS decomposes this into a TaskDAG with nodes: `read_file` → `write_file` (with reflect)
3. The proposed plan is displayed as a numbered table showing both steps, their params, dependency chain, and consensus requirements (`write_file` requires consensus)
4. User types `/plan remove 1` to remove the write step
5. Updated proposal re-displays showing only the read step
6. User types `/reject` to discard
7. User types `/plan read /tmp/test.txt` — simpler plan, single read_file node
8. User types `/approve` — ProbOS executes the single-node DAG through normal pipeline (mesh broadcast, agent selection, consensus if needed, result display)
9. Results display identically to normal execution (same renderer, same reflect, same episode storage)
10. Event log shows: `proposal_created`, `proposal_node_removed`, `proposal_rejected`, `proposal_created`, `proposal_approved`

---

## Update PROGRESS.md When Done

Add Phase 16 section with:
- AD decisions (AD-204 through AD-209)
- Files changed/created table
- Test count (target: 1180+)
- Update the Current Status line at the top
- Update the What's Been Built tables for changed files
- Add `/plan`, `/approve`, `/reject` to the shell command list
- Mark the DAG Proposals portion of the "Human-Agent Collaboration" roadmap item as complete (feedback-to-learning still pending)

**Add the following new roadmap entry** after the existing "Multi-Participant Federation" entry and before "Abstract Representation Formation":

> - [ ] **MCP Federation Adapter — Protocol Bridge at the Mesh Boundary.** ProbOS federation currently uses ZeroMQ for node-to-node communication — fast, programmatic, but requires both endpoints to be ProbOS instances. An MCP (Model Context Protocol) adapter layer would expose each node's capabilities as MCP tool definitions, enabling discovery and invocation by any MCP-speaking system (VS Code extensions, other agent frameworks, third-party meshes). The principle: programmatic inside the brain, protocol between brains. The mesh boundary is the skull boundary.
>   - **`MCPServer` capability exposure** — maps `NodeSelfModel` capabilities to MCP tool schemas. Each `IntentDescriptor` becomes an MCP tool with its params, description, and consensus requirements as metadata. The mapping is mechanical: ProbOS already broadcasts structured capability profiles via Ψ gossip; MCP tool definitions are a different serialization of the same information. The server refreshes tool definitions when the runtime's intent descriptors change (new designed agents, new skills).
>   - **Inbound intent translation** — MCP tool calls are translated to `IntentMessage` and dispatched through `intent_bus.broadcast(federated=True)`. The existing loop prevention flag prevents re-federation. MCP-originated intents go through the same governance pipeline as any federated intent: consensus, red team verification, escalation. The MCP adapter is a transport, not a trust bypass.
>   - **MCP client trust** — MCP clients are treated as federated peers with configurable trust. New MCP clients start with probationary trust (same `Beta(alpha, beta)` prior as new agents — AD-110). Trust updates based on outcome quality of intents they submit. Destructive intents (write_file, run_command) from MCP clients always require full consensus regardless of accumulated trust. The `validate_remote_results` config flag applies.
>   - **Outbound MCP client** — allows ProbOS to discover and invoke capabilities on external MCP servers. External tool definitions are translated to `IntentDescriptor` and registered as federated capabilities. The `FederationRouter` can then route intents to MCP-connected systems alongside ZeroMQ-connected ProbOS nodes, using the same scoring logic. External capabilities carry federated trust discount (same δ factor from Trust Transitivity roadmap item).
>   - **Transport coexistence** — ZeroMQ remains the primary intra-Noöplex transport (fast, binary, low-latency). MCP serves the boundary between independent cognitive ecosystems. Both transports feed into the same `FederationRouter` and `intent_bus`. A node can simultaneously connect to ProbOS peers via ZeroMQ and to external systems via MCP. The `FederationBridge` becomes transport-polymorphic: a transport interface with ZeroMQ and MCP implementations.
>   - **Noöplex alignment** — this directly implements §3.2's embedding alignment at the protocol level: MCP tool schemas are the shared vocabulary, each mesh's internal representation is sovereign. §4.3.4's governance negotiation maps to MCP capability exposure: meshes choose what to expose (tool definitions), what trust to extend (authentication), and what constraints apply (consensus metadata). The long-term vision: if the Noöplex scales to heterogeneous meshes across organizations, MCP (or its successor) becomes the lingua franca for Layer 3/4 cross-mesh communication.
