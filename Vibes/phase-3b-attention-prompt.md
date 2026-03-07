# ProbOS — Phase 3b-2: Attention Mechanism

## Context

You are continuing development of **ProbOS**, a probabilistic agent-native operating system runtime. The codebase lives in `d:\ProbOS` and uses Python 3.12, asyncio, pydantic, aiosqlite, httpx, Rich, pytest, and pytest-asyncio. The toolchain is `uv`. Run tests with `uv run pytest tests/ -v`.

**Current state: 351/351 tests pass.** Do not break any existing tests.

Read `PROGRESS.md` for the full architectural history, all 50 architectural decisions (AD-1 through AD-50), and the complete test inventory. Read existing source files before modifying them.

---

## What Exists

### Layers built (bottom-up):
1. **Substrate** — `BaseAgent` ABC, `AgentRegistry`, `AgentSpawner`, `ResourcePool`, `HeartbeatAgent`, `EventLog`
2. **Mesh** — `SignalManager`, `IntentBus`, `CapabilityRegistry`, `HebbianRouter` (SQLite-backed), `GossipProtocol`
3. **Consensus** — `QuorumEngine` (confidence-weighted), `TrustNetwork` (Bayesian Beta), `RedTeamAgent`, `FileWriterAgent` (propose-then-commit)
4. **Cognitive** — `MockLLMClient`/`OpenAICompatibleClient` (tiered routing), `WorkingMemoryManager` (bounded context), `IntentDecomposer` (NL→TaskDAG with reflect), `DAGExecutor` (parallel/sequential with consensus gating), `EpisodicMemory` (SQLite + keyword-overlap recall)
5. **Experience** — `panels.py` (Rich rendering functions), `ExecutionRenderer` (real-time DAG display), `ProbOSShell` (13 slash commands, NL routing)

### Agents (22 total at boot):
- 2× `SystemHeartbeatAgent` (pool: system)
- 3× `FileReaderAgent` (pool: filesystem) — `read_file`, `stat_file`
- 3× `FileWriterAgent` (pool: filesystem_writers) — `write_file` + consensus
- 3× `DirectoryListAgent` (pool: directory) — `list_directory`
- 3× `FileSearchAgent` (pool: search) — `search_files`
- 3× `ShellCommandAgent` (pool: shell) — `run_command` + consensus
- 3× `HttpFetchAgent` (pool: http) — `http_fetch` + consensus
- 2× `RedTeamAgent` (red team, not on intent bus)

### Key files to read first:
- `src/probos/types.py` — all dataclasses and enums
- `src/probos/config.py` — pydantic config models
- `config/system.yaml` — runtime configuration
- `src/probos/runtime.py` — `ProbOSRuntime` orchestrator
- `src/probos/cognitive/decomposer.py` — `IntentDecomposer`, `DAGExecutor`, `SYSTEM_PROMPT`
- `src/probos/cognitive/working_memory.py` — `WorkingMemoryManager`, `WorkingMemorySnapshot`
- `src/probos/substrate/pool.py` — `ResourcePool`
- `src/probos/mesh/intent.py` — `IntentBus`
- `src/probos/experience/shell.py` — `ProbOSShell`
- `src/probos/experience/renderer.py` — `ExecutionRenderer`
- `src/probos/experience/panels.py` — Rich panel rendering functions

---

## What to Build: Attention Mechanism

Per the original architecture (Layer 4 in `Vibes/probabilistic-os.jsx` and `Vibes/probos-claude-code-prompt.md`):

> **Attention Mechanism (replaces process scheduler):** Instead of time-sliced scheduling, implement an attention system. Agents compete for compute resources by signaling urgency and relevance. The attention mechanism allocates resources proportional to: task urgency × user focus × deadline proximity × dependency chain position. Background tasks get sparse, intermittent attention.

### Design

Build `src/probos/cognitive/attention.py` containing an `AttentionManager` class that replaces the current "all agents get equal access" model with a prioritized attention budget.

#### Core Concepts

1. **Attention Score** — Each pending task/intent gets a score computed as:
   ```
   score = urgency × relevance × deadline_factor × dependency_depth_bonus
   ```
   Where:
   - `urgency` — from `IntentMessage.urgency` (0.0–1.0), default 0.5
   - `relevance` — fixed at 1.0 for this phase (all nodes in a single DAG share the same user context; cross-request relevance scoring is Phase 3b-3)
   - `deadline_factor` — increases as the task approaches its TTL expiry (1.0 at creation → higher as TTL drains)
   - `dependency_depth_bonus` — tasks that unblock the most downstream dependencies get a small bonus

2. **Attention Budget** — A configurable concurrency limit (e.g., `max_concurrent_tasks: 8`). Tasks are scheduled from highest attention score to lowest until the budget is exhausted. Remaining tasks wait.

3. **Focus Tracking (infrastructure only)** — The `AttentionManager` stores the current request's keywords via `update_focus()`, but does NOT use them for per-DAG scoring in this phase. Focus tracking is infrastructure for future cross-request attention (Phase 3b-3+), where concurrent user requests compete for resources. Within a single DAG, all nodes share the same user context so focus-based boosting is meaningless. Store the state, expose it via `/attention`, but don't wire it into `compute_scores()` yet.

4. **Background Demotion** — Deferred to Phase 3b-3. Without cross-request attention, there are no "background" vs "foreground" tasks to distinguish within a single DAG execution.

5. **Preemption** — Deferred. Preemption (signaling low-priority tasks to yield when a high-urgency task arrives) is a Phase 3b-3 concern. Don't build it.

#### Implementation Plan

**Step 1: Types** — Add to `src/probos/types.py`:
```python
@dataclass
class AttentionEntry:
    """A task competing for attention resources."""
    task_id: str
    intent: str
    urgency: float = 0.5
    relevance: float = 0.5
    deadline_factor: float = 1.0
    dependency_depth: int = 0
    is_background: bool = False
    score: float = 0.0  # Computed
    created_at: datetime
    ttl_seconds: float = 30.0
```

**Step 2: Config** — Add to `CognitiveConfig` in `config.py` and `config/system.yaml`:
```yaml
cognitive:
  max_concurrent_tasks: 8
  attention_decay_rate: 0.95  # Per-second decay for stale tasks
  # background_priority_cap and focus_boost are Phase 3b-3 (cross-request attention)
```

**Step 3: AttentionManager** — `src/probos/cognitive/attention.py`:
- `submit(entry: AttentionEntry)` — add a task to the attention queue
- `compute_scores()` — recalculate all scores based on current time, focus, dependencies
- `get_next_batch(budget: int) -> list[AttentionEntry]` — return the top-N tasks to execute
- `update_focus(intent: str, context: str)` — store the current request's keywords (infrastructure for future cross-request attention; not used in scoring this phase)
- `mark_completed(task_id: str)` — remove from queue, potentially unblock dependents
- `mark_failed(task_id: str)` — remove from queue
- `get_queue_snapshot() -> list[AttentionEntry]` — for display/debugging
- `current_focus` property — what the system is currently focused on

**Step 4: Wire into DAGExecutor** — Modify `DAGExecutor._execute_dag()` in `decomposer.py`:
- Currently, all ready nodes execute in parallel via `asyncio.gather()` with no limit.
- Change: ready nodes are submitted to the `AttentionManager`, which computes scores and returns a batch capped at `max_concurrent_tasks`.
- Remaining ready nodes wait for the next cycle.
- The `on_event` callback should emit `attention_score` data with node events.

**Step 5: Wire into Runtime** — In `runtime.py`:
- Create `AttentionManager` during `__init__`.
- Pass it to `DAGExecutor`.
- Call `attention.update_focus()` at the start of `process_natural_language()`.
- Include attention queue info in the working memory snapshot.

**Step 6: Experience** — 
- Add `/attention` slash command to `shell.py` showing the current attention queue with scores.
- Add `render_attention_panel()` to `panels.py` — shows queued tasks sorted by score, with current focus displayed.
- The renderer should show attention scores in debug mode.

**Step 7: Tests** — Add `tests/test_attention.py`:

Test the `AttentionManager` in isolation:
1. `test_submit_and_retrieve` — submit 3 tasks, get_next_batch returns them sorted by score
2. `test_budget_limit` — submit 10 tasks with budget=3, only top 3 returned
3. `test_urgency_affects_score` — higher urgency → higher score
4. `test_deadline_factor_increases_near_expiry` — task near TTL expiry gets boosted
5. `test_dependency_depth_bonus` — task unblocking others gets higher score
6. `test_focus_stores_keywords` — `update_focus()` stores keywords, retrievable via `current_focus`
7. `test_background_flag_accepted` — `is_background` flag is stored but does not affect scoring in this phase
8. `test_mark_completed_removes` — completed task no longer in queue
9. `test_mark_failed_removes` — failed task no longer in queue
10. `test_empty_queue` — get_next_batch on empty returns empty list
11. `test_focus_update_stores_state` — `update_focus()` stores keywords without affecting scores
12. `test_queue_snapshot` — returns current state of all queued tasks

Integration tests (in `tests/test_cognitive_integration.py` or a new file):
13. `test_dag_executor_respects_attention_budget` — DAG with 5 independent nodes and budget=2 executes in batches
14. `test_attention_scores_in_event_callback` — on_event payloads include attention score
15. `test_nl_updates_focus` — `process_natural_language()` stores focus keywords in attention manager

Experience tests (in `tests/test_experience.py`):
16. `test_attention_command` — `/attention` renders the attention panel
17. `test_render_attention_panel` — renders with queued tasks
18. `test_render_attention_panel_empty` — renders empty state

---

## Rules

1. **Read before write.** Always read a file before modifying it. Understand the existing patterns.
2. **All 351 existing tests must continue to pass.** Run `uv run pytest tests/ -v` after changes and fix any regressions.
3. **Follow existing code patterns.** Study how other cognitive components (working memory, decomposer, episodic memory) are structured. Match the style — imports, docstrings, type hints, async patterns.
4. **No heavyweight dependencies.** The attention mechanism is lightweight — it's a priority queue with scoring, not a new framework.
5. **Config-driven.** All tunable parameters go in `CognitiveConfig` and `config/system.yaml`. Don't hardcode magic numbers.
6. **Backward compatible.** `DAGExecutor` must still work when `AttentionManager` is `None` (the default for existing tests). Guard with `if self.attention:`.
7. **Test thoroughly.** Write tests matching the patterns in existing test files (pytest-asyncio, `@pytest.mark.asyncio`, fixtures in `conftest.py`). Aim for 18+ new tests.
8. **Update PROGRESS.md** when done — add the new section for Phase 3b-2, update test count, add architectural decisions (AD-51+), add new files to the "What's Been Built" tables.
9. **Keep it simple.** The attention mechanism should be ~150-250 lines of core logic. Don't over-engineer. This is a priority scheduler with brain-inspired scoring, not a full preemptive multitasking kernel.
10. **Event integration.** The `on_event` callback pattern is already established in `DAGExecutor`. Extend it — don't replace it.

---

## Architectural Constraints

- The `AttentionManager` does NOT own async execution. It is a **priority scorer and budgeter**. The `DAGExecutor` still owns the `asyncio.gather()` calls — it just asks the attention manager "which nodes should I run next?" instead of running all ready nodes.
- The attention mechanism operates **per-DAG** (within a single `process_natural_language` call). Cross-request attention (managing multiple concurrent user requests) is a future concern — don't build it yet.
- Focus tracking **stores keywords but does not score with them** this phase. It is infrastructure for cross-request attention in Phase 3b-3. Don't add embedding models or heavyweight NLP.
- Preemption is a **Phase 3b-3 concern**. Don't build it.
- The concurrency limit caps how many nodes execute simultaneously in `asyncio.gather()`, not how many agents exist. Agent pools are managed by `ResourcePool`, which is unchanged.
- This phase demonstrates **priority-based batching of parallel nodes** — the attention mechanism's value is visible when a DAG has more ready nodes than the concurrency budget allows.

---

## Success Criteria

- [ ] `AttentionManager` class works in isolation with comprehensive tests
- [ ] `DAGExecutor` respects attention budget when `AttentionManager` is provided
- [ ] Existing tests unchanged and passing (351 + new tests all green)
- [ ] `/attention` command shows queue state
- [ ] Debug mode shows attention scores
- [ ] `PROGRESS.md` updated with Phase 3b-2, new test count, new AD entries
- [ ] `uv run pytest tests/ -v` — all tests pass
