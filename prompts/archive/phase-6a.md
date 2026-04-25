# Phase 6a: Introspection & Self-Awareness

**Goal:** Give ProbOS the ability to reason about itself — inspect its own agents, explain its decisions, show execution traces, and let users ask "why did you do that?" This deepens the Experience layer and makes the cognitive pipeline transparent.

---

## Context

ProbOS now has a mature cognitive layer (attention, episodic memory, dreaming, workflow cache) and 7 agent types. But the system is opaque — users can see `/status` and `/agents` but can't ask natural language questions about the system itself. The decomposer only knows about file/directory/shell/http intents. There's no way to say "which agent handled my last request?" or "why did you choose file_reader over file_search?"

The original vision says: *"The user never sees agents, layers, or infrastructure. They experience a fluid, continuous interaction surface."* But right now, ProbOS has two modes — slash commands (rigid) and NL (can only do file/shell/http operations). This phase bridges them by adding **introspection intents** that let the LLM reason about ProbOS's own state.

---

## Deliverables

### 1. Update `src/probos/substrate/agent.py` — Optional runtime reference

Add `runtime: Any | None = None` to `BaseAgent.__init__()` kwargs. Store as `self._runtime = runtime`. Default `None`. This is a minimal change that doesn't affect any existing agent — the kwarg is ignored unless an agent subclass reads it.

Also add `**kwargs` passthrough to `BaseAgent.__init__()` so that `AgentSpawner.spawn()` can forward arbitrary kwargs to agent constructors. Check whether `spawn()` already supports `**kwargs` passthrough. If it does, no change needed there. If it doesn't, add `**kwargs` to `spawner.spawn()` and forward them to the agent constructor call. **Pick one approach and implement it — do not leave this ambiguous.**

### 2. Create `src/probos/agents/introspect.py` — `IntrospectionAgent`

A new agent type that handles self-referential queries. It reads from runtime internals (registry, trust, Hebbian weights, episodic memory, attention, workflow cache) and returns structured information.

**Capability:** `introspect`

**Supported intents:**

| Intent | Params | Description |
|--------|--------|-------------|
| `explain_last` | `{}` | Explain what happened in the most recent NL request — which agents were involved, what DAG was executed, outcome |
| `agent_info` | `{"agent_type": "file_reader"}` or `{"agent_id": "abc..."}` | Return details about a specific agent type or instance — pool, trust score, confidence, Hebbian connections |
| `system_health` | `{}` | Return a structured health assessment — degraded pools, low-trust agents, attention queue depth, cache hit rate |
| `why` | `{"question": "..."}` | Answer a "why" question about ProbOS behavior by consulting episodic memory, Hebbian weights, and trust scores |

**Implementation:**

The agent stores `self._runtime` from the constructor kwarg and uses it in `act()`.

For each intent:

- **`explain_last`**: Read `runtime._previous_execution` (see §3 below for the snapshot pattern). Format as: input text, intents executed (intent name + params for each node), agent IDs involved, outcomes (success/failure per node), total duration if available. If `_previous_execution` is `None`, check episodic memory for the most recent episode as fallback. If neither is available, return `"No execution history available."` Include enough structured detail that the reflect step can synthesize a natural-language explanation.

- **`agent_info`**: Query the registry for agents matching the type or ID. For each matching agent, include: agent ID, pool membership, current state, confidence score, trust score from trust network, Hebbian weight summary (top 3 incoming connections by weight, top 3 outgoing connections by weight, total connection count). Format as a structured dict with an `agents` list.

- **`system_health`**: Compute and return a dict with:
  - `pool_health`: for each pool, `{"name": ..., "active": N, "target": M, "ratio": N/M}`
  - `trust_outliers`: agents with trust < 0.3 (flagged as "low trust") or > 0.9 (flagged as "high trust")
  - `attention_depth`: number of pending entries in the attention queue (0 if no attention manager)
  - `cache_stats`: `{"size": workflow_cache.size, "entries": len(workflow_cache.entries())}`
  - `hebbian_density`: `total_weights / (agent_count * agent_count)` — how connected the mesh is
  - `overall_health`: same average-confidence computation as the shell prompt uses
  - `dreaming`: `{"enabled": bool, "last_report": summary or None}`

- **`why`**: Query episodic memory with `recall(question, k=5)`. For each matching episode, extract the agent IDs involved and look up their current trust scores from the trust network AND their top Hebbian connections from the router. Return a dict with `matching_episodes` (list of episode summaries with outcomes) and `agent_context` (dict of agent_id → {trust_score, top_connections}). This gives the reflect step enough material to explain *why* certain agents were selected and whether the system learned from the interaction. If no episodic memory, return `{"matching_episodes": [], "explanation": "No episodic memory available for historical queries."}`.

### 3. Update `src/probos/runtime.py` — Wire introspection + execution snapshot

**a) Import and register template:**
```python
from probos.agents.introspect import IntrospectionAgent
self.spawner.register_template("introspect", IntrospectionAgent)
```

**b) Create introspection pool in `start()`:**
```python
await self.create_pool("introspect", "introspect", target_size=2)
```

When spawning introspect agents, pass `runtime=self` so they can access internals. Use whichever mechanism you implemented in §1 — either `spawner.spawn(..., runtime=self)` with kwargs forwarding, or post-creation assignment by iterating the pool's agents and setting `agent._runtime = self`.

**c) Execution snapshot pattern (CRITICAL — prevents self-overwrite bug):**

Add two fields:
```python
self._last_execution: dict[str, Any] | None = None
self._previous_execution: dict[str, Any] | None = None
```

At the **top** of `process_natural_language()`, before any processing begins:
```python
self._previous_execution = self._last_execution
```

At the **end** of `process_natural_language()`, after all processing completes:
```python
self._last_execution = execution_result
```

**Why this matters:** When the user says "what just happened?", that request itself goes through `process_natural_language()`. If `explain_last` reads `_last_execution` and it's set at the end of the same call, it would read the *introspection result*, not the previous real request. By snapshotting `_previous_execution` at the top, `explain_last` always gets the result from the request *before* the current one.

The `IntrospectionAgent.explain_last` handler reads `runtime._previous_execution`.

**d) Wire the same pattern in `src/probos/experience/renderer.py`:**

This is the AD-34 duplication issue. The shell uses `ExecutionRenderer.process_with_feedback()`, which runs its own pipeline and does NOT call `runtime.process_natural_language()`. So `_last_execution` and `_previous_execution` must also be set in `renderer.py`:

- At the **top** of `process_with_feedback()`:
  ```python
  self.runtime._previous_execution = self.runtime._last_execution
  ```
- At the **end** of `process_with_feedback()`:
  ```python
  self.runtime._last_execution = result
  ```

Without this, interactive shell sessions will never populate the execution history, and `explain_last` will always return "No execution history." This is the same class of bug as AD-52, AD-56, AD-69.

### 4. Update `src/probos/cognitive/decomposer.py` — Add introspection intents to system prompt

**a) Add to the Available intents table:**

```
| explain_last   | {}                                            | Explain what happened in the last request  |
| agent_info     | {"agent_type": "...", "agent_id": "..."}      | Get info about a specific agent            |
| system_health  | {}                                             | Get system health assessment               |
| why            | {"question": "..."}                            | Explain why ProbOS did something           |
```

**b) Add rule 14:** `14. explain_last, agent_info, system_health, why intents should have "use_consensus": false.`

**c) Add examples:**

```
User: "why did you use file_reader for that?"
{"intents": [{"id": "t1", "intent": "why", "params": {"question": "why did you use file_reader for that?"}, "depends_on": [], "use_consensus": false}], "reflect": true}

User: "how healthy is the system?"
{"intents": [{"id": "t1", "intent": "system_health", "params": {}, "depends_on": [], "use_consensus": false}], "reflect": true}

User: "what just happened?"
{"intents": [{"id": "t1", "intent": "explain_last", "params": {}, "depends_on": [], "use_consensus": false}], "reflect": true}

User: "tell me about file_reader agents"
{"intents": [{"id": "t1", "intent": "agent_info", "params": {"agent_type": "file_reader"}, "depends_on": [], "use_consensus": false}], "reflect": true}
```

Note: introspection intents should always have `"reflect": true` so the LLM synthesizes a human-readable answer from the structured data.

### 5. Update `src/probos/cognitive/llm_client.py` — Add MockLLMClient patterns for introspection

Add regex patterns to `MockLLMClient` so that introspection intents work in tests. Register these patterns (in priority order, before the default/fallback pattern):

| Pattern regex | Response JSON |
|---------------|---------------|
| `what (just )?happened\|explain.*(last\|previous)\|what did you (just )?do` | `{"intents": [{"id": "t1", "intent": "explain_last", "params": {}, "depends_on": [], "use_consensus": false}], "reflect": true}` |
| `how healthy\|system (health\|status)\|are you ok` | `{"intents": [{"id": "t1", "intent": "system_health", "params": {}, "depends_on": [], "use_consensus": false}], "reflect": true}` |
| `tell me about (.+) agents?\|info.*(agent\|file_reader\|file_writer)` | `{"intents": [{"id": "t1", "intent": "agent_info", "params": {"agent_type": "file_reader"}, "depends_on": [], "use_consensus": false}], "reflect": true}` |
| `why did you\|why.*(choose\|pick\|use\|select)` | `{"intents": [{"id": "t1", "intent": "why", "params": {"question": "<matched text>"}, "depends_on": [], "use_consensus": false}], "reflect": true}` |

Without these patterns, any test that sends an introspection NL query through MockLLMClient will hit the default/fallback pattern and return something unexpected, causing test failures.

### 6. Update `src/probos/experience/shell.py` — Add `/explain` command

Add a `/explain` shortcut that runs the `explain_last` intent directly:
```python
"/explain":   "Explain what happened in the last NL request",
```

Implementation: call `self.runtime.process_natural_language("what just happened?")` and display the result using the standard NL output rendering (same as any other NL command). This lets users type `/explain` instead of "what just happened?" for quick introspection.

Also add `/explain` to the `/help` output.

### 7. Update `tests/test_introspect.py` — New test file

See Test Specification below.

### 8. Run full suite, update PROGRESS.md

After all files are complete, run `uv run pytest tests/ -v`. All 437 existing tests must pass unchanged, plus the new tests. Update PROGRESS.md with:
- Phase 6a section in "What's Been Built"
- New AD entries (AD-71 through AD-7x as needed)
- Updated test count
- Phase 6a marked complete in "What's Next"

---

## Build Order

1. **BaseAgent** (`agent.py`) — add optional `runtime` kwarg and `**kwargs` passthrough
2. **AgentSpawner** (`spawner.py`) — add `**kwargs` forwarding if not already present
3. **IntrospectionAgent** (`introspect.py`) — new agent with 4 intents
4. **MockLLMClient** (`llm_client.py`) — add introspection regex patterns
5. **Decomposer** (`decomposer.py`) — add introspection intents to system prompt
6. **Runtime** (`runtime.py`) — register template, create pool, wire runtime reference, add `_previous_execution` snapshot pattern
7. **Renderer** (`renderer.py`) — wire `_previous_execution` / `_last_execution` in `process_with_feedback()`
8. **Shell** (`shell.py`) — add `/explain` command
9. **Tests** (`test_introspect.py`) — all 19 tests
10. **Run full suite** — `uv run pytest tests/ -v` — all 437 existing + 19 new = **456/456** must pass.
11. **PROGRESS.md** — update.

---

## Test Specification — `tests/test_introspect.py`

### IntrospectionAgent unit tests

1. **`test_introspect_agent_creates_with_runtime`** — Create an IntrospectionAgent with a mock runtime. Assert `agent._runtime` is set.
2. **`test_introspect_agent_creates_without_runtime`** — Create without runtime kwarg. Assert `agent._runtime is None`.
3. **`test_explain_last_with_previous_execution`** — Set up mock runtime with `_previous_execution` containing a result dict (input text, node outcomes). Call `act()` with `explain_last` intent. Assert result contains the previous execution's input text and outcome info.
4. **`test_explain_last_no_previous_execution`** — Mock runtime with `_previous_execution = None` and `episodic_memory = None`. Assert result contains "No execution history".
5. **`test_explain_last_falls_back_to_episodic`** — Mock runtime with `_previous_execution = None` but episodic memory containing one episode. Assert result contains episode info.
6. **`test_agent_info_by_type`** — Mock runtime with registry containing 3 `file_reader` agents. Call `act()` with `agent_info` intent and `agent_type="file_reader"`. Assert result contains 3 agents with trust scores.
7. **`test_agent_info_by_id`** — Mock runtime with a specific agent ID. Call with `agent_id="<id>"`. Assert result contains that agent's info.
8. **`test_agent_info_unknown_type`** — Call with `agent_type="nonexistent"`. Assert result indicates no agents found.
9. **`test_agent_info_includes_hebbian_context`** — Mock runtime with Hebbian weights. Assert result for a matched agent includes top connections.
10. **`test_system_health_returns_structured`** — Mock runtime with pools, trust, attention. Assert result dict contains keys: `pool_health`, `trust_outliers`, `overall_health`, `cache_stats`, `hebbian_density`.
11. **`test_why_queries_episodic_and_hebbian`** — Mock runtime with episodic memory and Hebbian weights. Call with `why` intent and a question. Assert episodic `recall()` was called AND result includes `agent_context` with trust/connection data for agents mentioned in matching episodes.
12. **`test_why_no_episodic`** — Mock runtime without episodic memory. Assert graceful response with empty `matching_episodes`.
13. **`test_introspect_capability_registered`** — Create agent, check capability descriptor includes `introspect`.

### Decomposer tests

14. **`test_system_prompt_includes_introspection_intents`** — Assert `SYSTEM_PROMPT` contains `explain_last`, `agent_info`, `system_health`, `why`.
15. **`test_decompose_why_question`** — Mock LLM returns a `why` intent. Assert DAG has one node with `intent="why"`.

### Runtime integration tests

16. **`test_runtime_creates_introspect_pool`** — Start runtime, assert `introspect` pool exists with 2 agents.
17. **`test_introspect_agents_have_runtime_ref`** — Start runtime, get introspect agents from registry, assert `_runtime is not None`.
18. **`test_previous_execution_stored_correctly`** — Process two NL requests sequentially ("read the file at /tmp/a.txt" then "read the file at /tmp/b.txt"). Assert `runtime._previous_execution` contains info from the first request (not the second). Then process "what just happened?" and verify `explain_last` returns info about the second request (the one that was `_last_execution` before the introspection call promoted it to `_previous_execution`).

### Shell tests

19. **`test_explain_command_exists_and_dispatches`** — Assert `/explain` is in `COMMANDS` dict. Call `execute_command("/explain")`. Assert it processes without error.

**Total: 19 new tests. Target: 456/456 (437 existing + 19 new).**

---

## Milestone Test

**End-to-end scenario:** Start runtime → process "read the file at /tmp/test.txt" → then process "what just happened?" → the second request should decompose to an `explain_last` intent, the IntrospectionAgent should return details about the read_file execution (not its own execution), and the reflect step should synthesize a human-readable explanation. This proves ProbOS can reason about its own behavior without the self-referential overwrite bug.

---

## Rules

1. `IntrospectionAgent` reads from runtime but DOES NOT modify runtime state. It's purely observational.
2. The `_runtime` reference on `BaseAgent` is optional. All existing agents ignore it. Only `IntrospectionAgent` uses it.
3. Introspection intents should always produce `"reflect": true` in the decomposer examples. The raw structured data from the agent isn't user-friendly — the reflect step turns it into natural language.
4. The introspect pool size is 2 (not 3). Introspection is lightweight and doesn't need the same redundancy as filesystem agents.
5. Do NOT add the `_runtime` reference to any existing agent type. Only `IntrospectionAgent` needs it.
6. `explain_last` reads `runtime._previous_execution` (NOT `_last_execution`). See §3c for the snapshot pattern. Episodic memory is a fallback, not the primary source.
7. All existing 437 tests must continue to pass unchanged.
8. Import `IntrospectionAgent` from `probos.agents.introspect`.
9. Run `uv run pytest tests/ -v` after every file change to catch regressions early.
10. Wire `_previous_execution` and `_last_execution` in BOTH `runtime.py` AND `renderer.py` (AD-34 duplication). Failing to wire the renderer is a known recurring bug pattern (AD-52, AD-56, AD-69). Do not repeat it.
11. Add MockLLMClient patterns for all 4 introspection intents. Without them, tests that route NL through the mock will fail.
12. The `why` handler must include Hebbian weight and trust context for agents mentioned in matching episodes — not just episode summaries. Without this context, the reflect step won't have enough material to explain agent selection.
13. Update `PROGRESS.md` when done: add Phase 6a section, new AD entries, update test counts, mark Phase 6a complete in "What's Next".
