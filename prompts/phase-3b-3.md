# Phase 3b-3: Cross-Request Attention, Preemption & Background Demotion

**Goal:** Extend `AttentionManager` so it persists focus across requests, preempts low-priority running tasks when urgent work arrives, and demotes background-flagged tasks to yield compute budget to foreground work.

---

## Context

Phase 3b-2 delivered `AttentionManager` with per-DAG priority scoring (`urgency × relevance × deadline_factor × dep_bonus`), budget-limited batching, and focus keyword storage that is **infrastructure only** — keywords are stored but never consumed. The `is_background` flag on `AttentionEntry` exists but is inert.

This phase is large. It is split into **two sub-phases**. This prompt covers **3b-3a only** (cross-request focus + background demotion). Preemption of already-running tasks is deferred to 3b-3b.

---

## Deliverables

### 1. Extend `src/probos/types.py`

Add a `FocusSnapshot` dataclass after `AttentionEntry`:

```python
@dataclass
class FocusSnapshot:
    keywords: list[str] = field(default_factory=list)
    context: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
```

No other type changes.

### 2. Modify `src/probos/cognitive/attention.py`

Extend `AttentionManager` with three capabilities:

**a) Focus history ring buffer**

- Add `_focus_history: list[FocusSnapshot]` (bounded, max 10 entries).
- `update_focus()` appends a `FocusSnapshot` to the ring buffer (evict oldest when full) in addition to setting `_focus_keywords` / `_focus_context` as today.
- Add `focus_history` property returning a copy of the list.

**b) Relevance scoring from focus**

- Add `_compute_relevance(entry: AttentionEntry) -> float` that computes keyword overlap between `entry.intent` tokens and the union of `_focus_keywords` from the last 3 snapshots. Return `max(overlap_ratio, 0.3)` so unfocused tasks still get a floor score.
- Call `_compute_relevance` inside `_compute_single` and **multiply** it into the existing formula: `score = urgency × relevance × deadline_factor × dep_bonus`. Today `relevance` is always 1.0 — now it varies.

**c) Background demotion**

- In `_compute_single`, if `entry.is_background is True`, multiply the final score by `0.25`. This pushes background tasks to the bottom of the batch.

Public API additions:

| Method / Property | Signature | Returns |
|---|---|---|
| `focus_history` | `@property` | `list[FocusSnapshot]` |
| `_compute_relevance` | `(entry: AttentionEntry) -> float` | `float` (0.3–1.0) |

Everything else stays unchanged.

### 3. Modify `src/probos/cognitive/decomposer.py`

In `_attention_batch()`, pass the user's original NL text as urgency context:

- `DAGExecutor.__init__` already receives `attention: AttentionManager | None`. No constructor change needed.
- In `_attention_batch()`, when creating `AttentionEntry` objects, set `relevance` to the value returned by `self.attention._compute_relevance(entry)` **after** submitting — or better, let `_compute_single` handle it (it already will after step 2b). No change needed here if `_compute_single` calls `_compute_relevance` internally.

Actually, **the only change** in decomposer.py is: when building the `AttentionEntry` in `_attention_batch()`, propagate `is_background` if the `TaskNode` has a `background` field. Today `TaskNode` has no such field, so add one:

In `src/probos/types.py`, add to `TaskNode`:

```python
background: bool = False
```

Then in `_attention_batch()`, change the entry construction:

```python
entry = AttentionEntry(
    task_id=node.id,
    intent=node.intent,
    urgency=0.5,
    dependency_depth=dep_depth.get(node.id, 0),
    is_background=node.background,
)
```

### 4. Modify `config/system.yaml` and `src/probos/config.py`

Add to `CognitiveConfig`:

```python
focus_history_size: int = 10
background_demotion_factor: float = 0.25
```

Add matching entries under `cognitive:` in `config/system.yaml`:

```yaml
focus_history_size: 10
background_demotion_factor: 0.25
```

Pass these into `AttentionManager` from `runtime.py` (modify the constructor call in `ProbOSRuntime.__init__`):

```python
self.attention = AttentionManager(
    max_concurrent=cog_cfg.max_concurrent_tasks,
    decay_rate=cog_cfg.attention_decay_rate,
    focus_history_size=cog_cfg.focus_history_size,
    background_demotion_factor=cog_cfg.background_demotion_factor,
)
```

Update `AttentionManager.__init__` to accept and store `focus_history_size` and `background_demotion_factor`.

### 5. Modify `src/probos/experience/panels.py`

Extend `render_attention_panel()` to show focus history below the queue table. For each `FocusSnapshot` in `attention.focus_history`, display timestamp and top 5 keywords. No new function — just extend the existing one.

### 6. Create `tests/test_attention_cross_request.py`

New test file with all tests for Phase 3b-3a behavior.

---

## Build Order

1. **Types first** (`types.py`) — add `FocusSnapshot` dataclass and `TaskNode.background` field.
2. **Config** (`config.py`, `system.yaml`) — add `focus_history_size`, `background_demotion_factor`.
3. **Attention core** (`attention.py`) — focus history ring buffer, `_compute_relevance`, background demotion factor. Wire config values.
4. **Runtime wiring** (`runtime.py`) — pass new config fields to `AttentionManager` constructor.
5. **Decomposer** (`decomposer.py`) — propagate `node.background` to `AttentionEntry.is_background`.
6. **Panels** (`panels.py`) — extend attention panel with focus history.
7. **Tests** (`test_attention_cross_request.py`) — all tests below.
8. **Run full suite** — `uv run pytest tests/ -v` — all 369 existing + new tests must pass.

---

## Test Specification — `tests/test_attention_cross_request.py`

### Focus history tests

1. **`test_focus_history_records_snapshots`** — Call `update_focus()` 3 times with different text. Assert `focus_history` has 3 entries with correct keywords.
2. **`test_focus_history_ring_buffer_evicts`** — Call `update_focus()` 12 times (exceeds max 10). Assert `len(focus_history) == 10` and oldest 2 are gone.
3. **`test_focus_history_empty_initially`** — New `AttentionManager` has empty `focus_history`.

### Cross-request relevance tests

4. **`test_relevance_boosts_matching_tasks`** — Call `update_focus("read file test.txt")`. Submit two tasks: one with `intent="read_file"`, another with `intent="http_fetch"`. Assert `read_file` task gets higher score than `http_fetch` task.
5. **`test_relevance_floor_prevents_zero`** — Submit a task with intent keywords that have zero overlap with focus. Assert `_compute_relevance(entry) >= 0.3`.
6. **`test_relevance_uses_recent_focus_only`** — Fill history with 10 unrelated entries, then call `update_focus` 3 times with "read file". Only the last 3 should affect relevance. Submit a `read_file` task. Assert relevance > 0.3.

### Background demotion tests

7. **`test_background_task_scored_lower`** — Submit two identical tasks (same intent, urgency). One has `is_background=True`. Assert background task score is ≈ 0.25× the foreground task score.
8. **`test_background_tasks_sort_below_foreground`** — Submit 3 foreground tasks and 2 background tasks. call `get_next_batch(budget=5)`. Assert all foreground tasks appear before background tasks.
9. **`test_background_demotion_factor_configurable`** — Create `AttentionManager(background_demotion_factor=0.5)`. Submit a background task. Assert demotion uses 0.5, not 0.25.

### TaskNode background field tests

10. **`test_task_node_background_default_false`** — `TaskNode(id="t1", intent="read_file")` has `background == False`.
11. **`test_task_node_background_set_true`** — `TaskNode(id="t1", intent="read_file", background=True)` has `background == True`.

### Config tests

12. **`test_config_focus_history_size`** — Load default config, assert `cognitive.focus_history_size == 10`.
13. **`test_config_background_demotion_factor`** — Load default config, assert `cognitive.background_demotion_factor == 0.25`.

### Integration test

14. **`test_attention_batch_propagates_background`** — Create a `DAGExecutor` with an `AttentionManager`. Build a `TaskDAG` with two ready nodes, one with `background=True`. Call `_attention_batch()`. Assert the foreground node appears first in the returned list.

**Total: 14 new tests. Target: 383/383 (369 existing + 14 new).**

---

## Milestone Test

**End-to-end scenario:** Create an `AttentionManager`. Call `update_focus("read config files")` three times to simulate prior requests about files. Submit 5 `AttentionEntry` objects: 2 with `intent="read_file"` (foreground), 1 with `intent="read_file"` (background), 1 with `intent="http_fetch"` (foreground), 1 with `intent="run_command"` (foreground). Call `get_next_batch(budget=3)`.

**Expected:** The batch contains both foreground `read_file` tasks (boosted by focus relevance) and one of the non-file foreground tasks. The background `read_file` task and the lowest-scoring foreground task are excluded. This proves cross-request focus, relevance scoring, background demotion, and budget limiting all work together.

This should be test #14 above (the integration test), or add it as test #15 if you keep #14 as a decomposer-level test. Either way, this scenario must pass.

---

## Rules

1. Do NOT add preemption (cancelling already-running tasks). That is Phase 3b-3b.
2. Do NOT change `_execute_dag` control flow beyond propagating `is_background`. The execution loop stays the same.
3. Do NOT add new slash commands. The existing `/attention` command and `render_attention_panel` are extended, not replaced.
4. All existing 369 tests must continue to pass unchanged.
5. Use `field(default_factory=list)` for mutable defaults in dataclasses.
6. Import `FocusSnapshot` from `probos.types` wherever needed.
7. Keep `_compute_relevance` as a regular method (not a `@staticmethod`) because it reads `self._focus_history`.
8. The `relevance` field on `AttentionEntry` stays at its default `1.0` — `_compute_single` computes the effective relevance internally rather than mutating the entry.
9. Run `uv run pytest tests/ -v` after every file change to catch regressions early.
10. Update `PROGRESS.md` when done: add Phase 3b-3a section, new AD entries, update test counts, mark Phase 3b-3a complete in "What's Next".
