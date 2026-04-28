# AD-667: Named Working Memory Buffers

**Status:** Ready for builder
**Priority:** High (enables AD-668 through AD-672)
**Depends:** None (AD-666 Sensorium Formalization is conceptual — no code prerequisite)
**Unlocks:** AD-668 (Buffer Metabolism), AD-669 (Attention Gating), AD-670 (Sensorium Rendering), AD-671 (Chain Buffer Routing), AD-672 (Buffer Diagnostics)

**Files:**
- `src/probos/cognitive/agent_working_memory.py` — primary changes
- `src/probos/config.py` — new buffer budget fields
- `tests/test_agent_working_memory.py` — new tests appended

## Problem

AgentWorkingMemory (AD-573) stores all cognitive state in five flat ring buffers (`_recent_actions`, `_recent_observations`, `_recent_conversations`, `_recent_events`, `_recent_reasoning`) plus engagements and cognitive state. The `render_context()` method renders everything into a single blob with priority-based eviction. There is no way for a chain step to request only the information it needs — ANALYZE does not need social history, COMPOSE does not need duty progress. Every pathway gets the full dump, wasting token budget and diluting signal.

Named buffers solve this by grouping entries into four semantic domains — Duty, Social, Ship, Engagement — each with its own token budget. Chain steps can then request `render_buffers(["duty", "engagement"])` to get only relevant context.

## Scope

- Add a `NamedBuffer` dataclass to hold a named group of entries with its own token budget.
- Create four named buffer instances inside `AgentWorkingMemory`.
- Route existing `record_*` methods to the appropriate named buffer.
- Add `render_buffers()` for selective buffer access.
- Keep existing `render_context()` fully backward-compatible (renders all buffers, same priority eviction).
- Add per-buffer token budget fields to `WorkingMemoryConfig`.
- Update `to_dict()` / `from_dict()` for named buffer serialization.
- Approximately 200 lines in agent_working_memory.py, 20 lines in config.py, 15 tests.
- **No new modules.** No changes to cognitive_agent.py call sites (those come in AD-671).

### Design Principles

- **Backward compatibility is sacred.** Every existing call to `render_context()`, `record_action()`, `to_dict()`, `from_dict()`, `has_engagement()`, etc. must continue to work identically. Tests in `tests/test_agent_working_memory.py` must still pass without modification.
- **Named buffers are an overlay.** The existing ring buffers (`_recent_actions`, etc.) become internal storage within the named buffers, but the public write API signatures do not change.
- **No call site changes.** cognitive_agent.py, proactive.py, ward_room_router.py are NOT touched. They continue calling `render_context()`. Selective buffer access (AD-671) is a future AD.

---

## Section 1: NamedBuffer Dataclass

Add a new dataclass after `ActiveEngagement` (around line 65) in `agent_working_memory.py`.

```python
@dataclass
class NamedBuffer:
    """A named semantic group of working memory entries with its own token budget."""

    name: str  # "duty", "social", "ship", "engagement"
    token_budget: int  # per-buffer ceiling
    _entries: deque[WorkingMemoryEntry] = field(default_factory=lambda: deque(maxlen=20))

    def append(self, entry: WorkingMemoryEntry) -> None:
        """Add an entry to this buffer."""
        self._entries.append(entry)

    def render(self, *, budget: int | None = None) -> str:
        """Render this buffer's entries within its token budget.

        Returns empty string if no entries. Evicts oldest entries
        first if total exceeds budget.
        """
        ...implementation...

    @property
    def entries(self) -> list[WorkingMemoryEntry]:
        """Read-only snapshot of current entries."""
        return list(self._entries)

    def __len__(self) -> int:
        return len(self._entries)
```

Implementation notes for `render()`:
- Use `budget or self.token_budget` as the effective ceiling.
- Iterate entries newest-first, accumulating token estimates.
- Once budget exceeded, stop (oldest entries are evicted).
- Format each entry as `"  - ({age} ago) {content}"` — same style as existing render_context.
- Prefix the output with the buffer name as a header: `"[{name.title()}]:"`.
- Return empty string if no entries fit the budget.

**Run after this section:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_agent_working_memory.py -v` (existing tests must still pass, no new tests yet)

---

## Section 2: Named Buffer Instances in AgentWorkingMemory

Modify `AgentWorkingMemory.__init__()` (around line 78) to create four named buffer instances. Keep all existing ring buffer attributes — they become the backing storage inside the named buffers.

Add these new constructor parameters after the existing ones:

```python
def __init__(
    self,
    *,
    token_budget: int = 3000,
    max_recent_actions: int = 10,
    max_recent_observations: int = 5,
    max_recent_conversations: int = 5,
    max_events: int = 10,
    max_recent_reasoning: int = 5,
    # AD-667: Per-buffer token budgets
    duty_budget: int = 600,
    social_budget: int = 800,
    ship_budget: int = 800,
    engagement_budget: int = 800,
) -> None:
```

After the existing ring buffer initialization (around line 95), create the named buffers:

```python
# AD-667: Named semantic buffers
self._named_buffers: dict[str, NamedBuffer] = {
    "duty": NamedBuffer(name="duty", token_budget=duty_budget),
    "social": NamedBuffer(name="social", token_budget=social_budget),
    "ship": NamedBuffer(name="ship", token_budget=ship_budget),
    "engagement": NamedBuffer(name="engagement", token_budget=engagement_budget),
}
```

Important: the existing `_recent_actions`, `_recent_observations`, etc. ring buffers remain. They are the authoritative storage. The named buffers provide a **parallel index** — entries are written to both the legacy ring buffer AND the appropriate named buffer. This ensures `render_context()` continues to work from the legacy buffers unchanged.

Add a public accessor:

```python
def get_buffer(self, name: str) -> NamedBuffer | None:
    """AD-667: Get a named buffer by name."""
    return self._named_buffers.get(name)

@property
def buffer_names(self) -> list[str]:
    """AD-667: List available buffer names."""
    return list(self._named_buffers.keys())
```

**Run after this section:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_agent_working_memory.py -v`

---

## Section 3: Buffer-Aware Write API

Modify each `record_*` method to also append the entry to the appropriate named buffer. The entry is the same `WorkingMemoryEntry` object — it exists in both the legacy ring buffer and the named buffer.

Routing table:

| Method | Legacy buffer | Named buffer |
|--------|--------------|-------------|
| `record_action()` | `_recent_actions` | **duty** |
| `record_observation()` | `_recent_observations` | **ship** |
| `record_conversation()` | `_recent_conversations` | **social** |
| `record_event()` | `_recent_events` | **ship** |
| `record_reasoning()` | `_recent_reasoning` | **duty** |

For each method, after the existing `self._recent_X.append(entry)` call, add:

```python
self._named_buffers["duty"].append(entry)  # or "social", "ship" per table
```

You will need to capture the `WorkingMemoryEntry` into a local variable before appending, since the same object goes to both places. For example, in `record_action()` (around line 111):

```python
def record_action(
    self, summary: str, *, source: str, metadata: dict[str, Any] | None = None,
    knowledge_source: str = "unknown",
) -> None:
    """Record an action the agent just took (any pathway)."""
    _meta = dict(metadata) if metadata else {}
    if self._correlation_id and "correlation_id" not in _meta:
        _meta["correlation_id"] = self._correlation_id
    entry = WorkingMemoryEntry(
        content=summary,
        category="action",
        source_pathway=source,
        metadata=_meta,
        knowledge_source=knowledge_source,
    )
    self._recent_actions.append(entry)
    self._named_buffers["duty"].append(entry)  # AD-667
```

Apply the same pattern to all five `record_*` methods.

For active engagements, also route to the engagement buffer. In `add_engagement()` (around line 182), after adding to `_active_engagements`, also create a `WorkingMemoryEntry` summary and append to the engagement buffer:

```python
def add_engagement(self, engagement: ActiveEngagement) -> None:
    """Register an active engagement (game, task, etc.)."""
    self._active_engagements[engagement.engagement_id] = engagement
    # AD-667: Mirror to engagement buffer
    self._named_buffers["engagement"].append(WorkingMemoryEntry(
        content=engagement.summary,
        category="engagement",
        source_pathway="system",
        metadata={"engagement_id": engagement.engagement_id,
                  "engagement_type": engagement.engagement_type},
    ))
```

For `update_cognitive_state()` (around line 203), also append a summary to the ship buffer:

```python
def update_cognitive_state(self, **kwargs: Any) -> None:
    """Update cognitive state fields (zone, cooldown, alert condition)."""
    self._cognitive_state.update(kwargs)
    # AD-667: Mirror significant state changes to ship buffer
    if kwargs:
        summary_parts = [f"{k}={v}" for k, v in kwargs.items()]
        self._named_buffers["ship"].append(WorkingMemoryEntry(
            content=f"Cognitive state: {', '.join(summary_parts)}",
            category="cognitive_state",
            source_pathway="system",
        ))
```

**Run after this section:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_agent_working_memory.py -v`

---

## Section 4: Selective render_buffers() Method

Add a new public method after `render_context()` (around line 313). This is the key new API that AD-671 will use for chain step routing.

```python
def render_buffers(
    self,
    names: list[str],
    *,
    budget: int | None = None,
) -> str:
    """AD-667: Render specific named buffers within a total budget.

    Args:
        names: Buffer names to include (e.g., ["duty", "engagement"]).
        budget: Total token budget across all requested buffers.
               If None, uses sum of per-buffer budgets for requested buffers.

    Returns:
        Rendered context string, or empty string if no content.
    """
```

Implementation:
1. Filter `self._named_buffers` to only the requested names. Log a warning and skip any name not found.
2. If `budget` is None, compute it as the sum of the requested buffers' individual `token_budget` values.
3. Allocate budget proportionally: each buffer gets `budget * (buffer.token_budget / sum_of_requested_budgets)`.
4. Render each buffer with its allocated budget using `buffer.render(budget=allocated)`.
5. Combine non-empty renders with `"\n\n"` separator.
6. Wrap in `"--- Working Memory ---\n"` and `"\n--- End Working Memory ---"` (same framing as `render_context()`).
7. Return empty string if all buffers render empty.

**Do NOT modify `render_context()`.** It continues to use the legacy ring buffers and priority eviction system unchanged.

**Run after this section:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_agent_working_memory.py -v`

---

## Section 5: Config Updates

In `src/probos/config.py`, add four new fields to `WorkingMemoryConfig` (around line 681, after `stale_threshold_hours`):

```python
class WorkingMemoryConfig(BaseModel):
    """AD-573: Unified agent working memory configuration."""

    token_budget: int = 3000
    max_recent_actions: int = 10
    max_recent_observations: int = 5
    max_recent_conversations: int = 5
    max_events: int = 10
    proactive_budget: int = 1500
    stale_threshold_hours: float = 24.0
    # AD-667: Per-buffer token budgets (must sum to <= token_budget)
    duty_budget: int = 600
    social_budget: int = 800
    ship_budget: int = 800
    engagement_budget: int = 800
```

No validator needed — the sum constraint is advisory (the sensorium ceiling AD-666 formalizes enforcement). The defaults sum to 3000, matching `token_budget`.

**Run after this section:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_agent_working_memory.py -v`

---

## Section 6: Migration (Backward Compat)

### 6a: to_dict() update

In `to_dict()` (around line 351), add serialization of named buffer state. Append to the returned dict:

```python
"named_buffers": {
    name: {
        "name": buf.name,
        "token_budget": buf.token_budget,
        "entries": [
            {"content": e.content, "category": e.category,
             "source_pathway": e.source_pathway, "timestamp": e.timestamp,
             "metadata": e.metadata, "knowledge_source": e.knowledge_source}
            for e in buf.entries
        ],
    }
    for name, buf in self._named_buffers.items()
},
```

### 6b: from_dict() update

In `from_dict()` (around line 398), after restoring legacy ring buffers and before the stasis awareness marker, add restoration of named buffers:

```python
# AD-667: Restore named buffer entries
for buf_name, buf_data in data.get("named_buffers", {}).items():
    buf = wm._named_buffers.get(buf_name)
    if buf is None:
        continue
    for raw in buf_data.get("entries", []):
        age = now - raw.get("timestamp", 0)
        if age < stale_threshold_seconds:
            buf.append(WorkingMemoryEntry(
                content=raw["content"],
                category=raw.get("category", "unknown"),
                source_pathway=raw.get("source_pathway", "restored"),
                timestamp=raw.get("timestamp", now),
                metadata=raw.get("metadata", {}),
                knowledge_source=raw.get("knowledge_source", "unknown"),
            ))
```

If `named_buffers` key is missing from `data` (legacy persistence format), the `data.get("named_buffers", {})` returns empty dict — no restoration needed, named buffers start empty. The legacy ring buffers still restore normally. This is the backward compat path.

### 6c: from_dict forward-fill

When `named_buffers` is absent but legacy ring buffers are present, the named buffers will be empty after restore. This is acceptable — the next `record_*` calls will populate them. Do NOT attempt to retroactively classify legacy entries into named buffers during restore. Keep it simple.

**Run after this section:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_agent_working_memory.py -v`

---

## Section 7: Tests

Add these tests to `tests/test_agent_working_memory.py`. Append a new test class at the end of the file.

```python
class TestNamedBuffers:
    """AD-667: Named working memory buffer tests."""
```

### Required tests (15 tests minimum):

**NamedBuffer dataclass (4 tests):**
1. `test_named_buffer_append_and_len` — append entries, verify `len()` and `entries` property.
2. `test_named_buffer_render_within_budget` — render entries that fit within token budget, verify header and content.
3. `test_named_buffer_render_evicts_oldest` — overfill buffer, verify oldest entries are dropped when rendering.
4. `test_named_buffer_render_empty` — empty buffer renders empty string.

**Buffer routing (5 tests):**
5. `test_record_action_routes_to_duty` — call `record_action()`, verify entry appears in duty buffer.
6. `test_record_observation_routes_to_ship` — call `record_observation()`, verify entry appears in ship buffer.
7. `test_record_conversation_routes_to_social` — call `record_conversation()`, verify entry appears in social buffer.
8. `test_record_event_routes_to_ship` — call `record_event()`, verify entry appears in ship buffer.
9. `test_record_reasoning_routes_to_duty` — call `record_reasoning()`, verify entry appears in duty buffer.

**Selective rendering (3 tests):**
10. `test_render_buffers_single` — render only "duty", verify only duty content appears.
11. `test_render_buffers_multiple` — render ["duty", "engagement"], verify both appear, social/ship do not.
12. `test_render_buffers_unknown_name_warns` — request ["duty", "nonexistent"], verify warning logged (use `caplog`), duty still renders.

**Serialization (2 tests):**
13. `test_to_dict_includes_named_buffers` — populate buffers, call `to_dict()`, verify `named_buffers` key present with correct structure.
14. `test_from_dict_restores_named_buffers` — round-trip: `to_dict()` then `from_dict()`, verify named buffer entries restored.

**Backward compat (1 test):**
15. `test_from_dict_legacy_no_named_buffers` — call `from_dict()` with a dict that has NO `named_buffers` key (pre-AD-667 format), verify it does not crash and named buffers are empty.

**Run after this section:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_agent_working_memory.py -v`

Then run the full suite:
```
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q
```

---

## Section 8: Tracking Updates

### PROGRESS.md
Add under the active section:
```
- [x] AD-667: Named Working Memory Buffers — four semantic buffers (Duty/Social/Ship/Engagement) with per-buffer token budgets
```

### docs/development/roadmap.md
Find the AD-667 row in the roadmap table and update status to COMPLETE.

### DECISIONS.md
Add entry:
```
## AD-667: Named Working Memory Buffers (2026-04-26)
**Decision:** Added four named semantic buffers (Duty, Social, Ship, Engagement) as a parallel index alongside existing ring buffers in AgentWorkingMemory. Entries are dual-written to both legacy ring buffers and the appropriate named buffer. render_context() is unchanged; new render_buffers() method enables selective access. Legacy persistence format gracefully degrades (named buffers start empty on old data).
**Why:** Enables chain steps to request only relevant context (AD-671), reduces token waste, and establishes the buffer abstraction needed for metabolism (AD-668), attention gating (AD-669), and diagnostics (AD-672).
**Alternative rejected:** Replacing ring buffers entirely — too much call-site churn for no immediate benefit. Dual-write adds ~5 lines per record method but preserves full backward compat.
```
