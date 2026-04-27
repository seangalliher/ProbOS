# AD-492: Cognitive Correlation IDs — Cross-Layer Trace Threading

**Status:** Ready for builder
**Priority:** Medium
**Depends:** None (purely additive — all target modules exist)
**Files:** `src/probos/cognitive/cognitive_agent.py` (EDIT), `src/probos/cognitive/agent_working_memory.py` (EDIT), `src/probos/ward_room_pipeline.py` (EDIT), `src/probos/cognitive/journal.py` (EDIT), `src/probos/types.py` (EDIT), `src/probos/events.py` (EDIT), `tests/test_ad492_cognitive_correlation_ids.py` (NEW)

## Problem

When an agent perceives an intent, thinks about it, creates an episode, and posts to Ward Room, there is no correlation ID threading these steps together. Debugging requires manual timestamp correlation across multiple logs and databases.

**Example scenario:** An agent receives a `ward_room_notification` intent. The perceive→decide→act pipeline runs, an episode is stored, a journal entry is written, and a Ward Room post is created. Each step logs independently. To trace the full chain, a developer must manually correlate timestamps across:
- CognitiveJournal SQLite rows (by `intent_id` + `agent_id` + approximate timestamp)
- EpisodicMemory episodes (by `agent_ids` + approximate timestamp)
- Ward Room posts (by `author_id` + approximate timestamp)
- Working memory entries (by `source_pathway` + approximate timestamp)
- Runtime events (by `agent_id` + approximate timestamp)

AD-492 delivers a single `correlation_id` generated at perception time and threaded through every downstream artifact. One ID, one query, full trace.

**What this does NOT include:**
- Distributed tracing (OpenTelemetry spans, Jaeger integration) — future
- Cross-agent correlation (agent A's post triggers agent B's perceive) — the correlation_id is per-cognitive-cycle, not cross-agent. Cross-agent linking would use `intent_id` + `correlation_id` pairs.
- API endpoint to query by correlation_id — future (AD-492b)
- HXI visualization of correlation chains — future

---

## Section 1: Generate Correlation ID at Perception Time

**File:** `src/probos/cognitive/cognitive_agent.py` (EDIT)

### 1a. Import uuid at module level

At the top of the file, `uuid` is not currently imported at module level (it's used inline as `import uuid as _uuid` in several places). Add a module-level import:

```python
import uuid
```

Add this alongside the existing module-level imports (after `import time`, before `from probos.events import EventType`).

**Builder note:** If `import uuid` already exists at module level, skip this step. If the file uses `import uuid as _uuid` in function-local scope, that's fine — the module-level import is for the new perceive() usage. Both can coexist.

### 1b. Modify `perceive()` to generate and attach `correlation_id`

**Location:** `cognitive_agent.py`, line ~1039, method `perceive(self, intent: Any) -> dict`

Current code:
```python
async def perceive(self, intent: Any) -> dict:
    """Package the intent as an observation for the LLM."""
    if isinstance(intent, IntentMessage):
        return {
            "intent": intent.intent,
            "params": intent.params,
            "context": intent.context,
            "intent_id": intent.id,  # AD-432: Preserve for journal traceability
        }
    # Dict fallback (for compatibility with BaseAgent contract)
    return {
        "intent": intent.get("intent", "unknown") if isinstance(intent, dict) else "unknown",
        "params": intent.get("params", {}) if isinstance(intent, dict) else {},
        "context": intent.get("context", "") if isinstance(intent, dict) else "",
    }
```

Replace with:
```python
async def perceive(self, intent: Any) -> dict:
    """Package the intent as an observation for the LLM.

    AD-492: Generates a correlation_id at perception time to thread
    through the entire cognitive cycle (decide → act → episode → post).
    """
    # AD-492: Generate correlation ID for this cognitive cycle
    correlation_id = uuid.uuid4().hex[:12]

    if isinstance(intent, IntentMessage):
        observation = {
            "intent": intent.intent,
            "params": intent.params,
            "context": intent.context,
            "intent_id": intent.id,  # AD-432: Preserve for journal traceability
            "correlation_id": correlation_id,  # AD-492
        }
    else:
        # Dict fallback (for compatibility with BaseAgent contract)
        observation = {
            "intent": intent.get("intent", "unknown") if isinstance(intent, dict) else "unknown",
            "params": intent.get("params", {}) if isinstance(intent, dict) else {},
            "context": intent.get("context", "") if isinstance(intent, dict) else "",
            "correlation_id": correlation_id,  # AD-492
        }

    # AD-492: Store correlation_id on working memory for cross-reference
    _wm = getattr(self, '_working_memory', None)
    if _wm:
        _wm.set_correlation_id(correlation_id)

    return observation
```

**Key design decisions:**
- `uuid.uuid4().hex[:12]` — 12 hex chars = 48 bits of entropy. Collision probability is negligible for per-agent per-cycle IDs. Short enough to include in logs without noise.
- Stored on the observation dict so it flows naturally through `decide()` and `act()` without method signature changes.
- Also stored on working memory so downstream code (ward room pipeline, episode storage) can access it without threading it through every function parameter.
- `getattr(self, '_working_memory', None)` is defensive — `_working_memory` is always set in `CognitiveAgent.__init__()`, but the guard handles edge cases (stasis restoration, subclass that bypasses `__init__`). `if self._working_memory:` would also work but the `getattr` is safer.

---

## Section 2: Working Memory Correlation ID Storage

**File:** `src/probos/cognitive/agent_working_memory.py` (EDIT)

Add a `_correlation_id` field and accessor methods to `AgentWorkingMemory`.

### 2a. Add field to `__init__`

After the existing `self._last_telemetry_snapshot` line (line ~104), add:

```python
        # AD-492: Current cognitive cycle correlation ID
        self._correlation_id: str | None = None
```

### 2b. Add set/get/clear methods

After the existing `set_telemetry_snapshot()` method (line ~207), add:

```python
    def set_correlation_id(self, correlation_id: str) -> None:
        """AD-492: Set the current cognitive cycle's correlation ID."""
        self._correlation_id = correlation_id

    def get_correlation_id(self) -> str | None:
        """AD-492: Get the current cognitive cycle's correlation ID."""
        return self._correlation_id

    def clear_correlation_id(self) -> None:
        """AD-492: Clear correlation ID after cognitive cycle completes."""
        self._correlation_id = None
```

### 2c. Include correlation_id in WorkingMemoryEntry metadata

Modify `record_action()` (line ~108) to automatically include the current correlation_id in metadata if set:

Current:
```python
    def record_action(
        self, summary: str, *, source: str, metadata: dict[str, Any] | None = None,
        knowledge_source: str = "unknown",
    ) -> None:
        """Record an action the agent just took (any pathway)."""
        self._recent_actions.append(WorkingMemoryEntry(
            content=summary,
            category="action",
            source_pathway=source,
            metadata=metadata or {},
            knowledge_source=knowledge_source,
        ))
```

Replace with:
```python
    def record_action(
        self, summary: str, *, source: str, metadata: dict[str, Any] | None = None,
        knowledge_source: str = "unknown",
    ) -> None:
        """Record an action the agent just took (any pathway)."""
        _meta = dict(metadata) if metadata else {}
        # AD-492: Attach correlation ID if active
        if self._correlation_id and "correlation_id" not in _meta:
            _meta["correlation_id"] = self._correlation_id
        self._recent_actions.append(WorkingMemoryEntry(
            content=summary,
            category="action",
            source_pathway=source,
            metadata=_meta,
            knowledge_source=knowledge_source,
        ))
```

**Builder note:** Do NOT apply the same pattern to `record_observation()`, `record_conversation()`, or `record_event()` — those methods are called from many contexts (proactive loop, DM handler, system events) where a correlation_id may not be set.

`record_reasoning()` IS called from the lifecycle (line ~2419, composition brief recording) but is intentionally excluded — it records metacognitive planning data, not action outcomes. The composition brief's `metadata` dict already carries `composition_brief` context. Threading `correlation_id` into reasoning records is a future enhancement (AD-492b) — this AD focuses on the action/artifact pipeline.

### 2d. Serialization — include correlation_id in `to_dict()` / `from_dict()`

The `_correlation_id` is transient (per-cycle, not persisted across stasis). No changes needed to `to_dict()` / `from_dict()`. It resets naturally to `None` on each new cognitive cycle.

---

## Section 3: Thread Correlation ID Through CognitiveJournal

**File:** `src/probos/cognitive/journal.py` (EDIT)

### 3a. Add `correlation_id` column to schema

In `_SCHEMA_BASE` (line ~20), add a new column after the `procedure_id` line. **Important:** The existing `procedure_id` line (line 41) has NO trailing comma — it is currently the last column before `);`. You must add a trailing comma to the `procedure_id` line before adding the new column.

Change:
```python
    procedure_id     TEXT NOT NULL DEFAULT ''
);
```

To:
```python
    procedure_id     TEXT NOT NULL DEFAULT '',
    correlation_id   TEXT NOT NULL DEFAULT ''
);
```

### 3b. Add migration for existing databases

In the `start()` method (line ~77), add to the migration list after the `procedure_id` migration:

```python
            ("correlation_id", "TEXT NOT NULL DEFAULT ''"),  # AD-492: cognitive correlation ID
```

### 3c. Add index for correlation_id queries

In `_SCHEMA_INDEXES` (line ~49), add after the existing `idx_journal_intent_id` line:

```python
CREATE INDEX IF NOT EXISTS idx_journal_correlation_id ON journal(correlation_id);
```

The full `_SCHEMA_INDEXES` becomes:
```python
_SCHEMA_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_journal_intent_id ON journal(intent_id);
CREATE INDEX IF NOT EXISTS idx_journal_correlation_id ON journal(correlation_id);
"""
```

### 3d. Add `correlation_id` parameter to `record()`

In the `record()` method (line ~145), add `correlation_id: str = ""` to the parameter list after `procedure_id`:

```python
    async def record(
        self,
        *,
        entry_id: str,
        timestamp: float,
        agent_id: str,
        agent_type: str = "",
        tier: str = "standard",
        model: str = "",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        latency_ms: float = 0.0,
        intent: str = "",
        success: bool = True,
        cached: bool = False,
        request_id: str = "",
        prompt_hash: str = "",
        response_length: int = 0,
        intent_id: str = "",
        dag_node_id: str = "",
        response_hash: str = "",
        procedure_id: str = "",
        correlation_id: str = "",  # AD-492: cognitive cycle correlation ID
    ) -> None:
```

Update the INSERT statement to include `correlation_id`:

```python
            await self._db.execute(
                """INSERT OR IGNORE INTO journal
                   (id, timestamp, agent_id, agent_type, tier, model,
                    prompt_tokens, completion_tokens, total_tokens,
                    latency_ms, intent, success, cached, request_id,
                    prompt_hash, response_length,
                    intent_id, dag_node_id, response_hash, procedure_id,
                    correlation_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry_id, timestamp, agent_id, agent_type, tier, model,
                    prompt_tokens, completion_tokens, total_tokens,
                    latency_ms, intent, 1 if success else 0,
                    1 if cached else 0, request_id,
                    prompt_hash, response_length,
                    intent_id, dag_node_id, response_hash, procedure_id,
                    correlation_id,
                ),
            )
```

---

## Section 4: Pass Correlation ID Into Journal Calls

**File:** `src/probos/cognitive/cognitive_agent.py` (EDIT)

There are three locations where `self._cognitive_journal.record()` is called. Add `correlation_id=observation.get("correlation_id", "")` to each.

### 4a. Cache hit journal recording (line ~1145)

Current:
```python
                        await self._cognitive_journal.record(
                            entry_id=_uuid.uuid4().hex,
                            timestamp=time.time(),
                            agent_id=self.id,
                            agent_type=self.agent_type,
                            intent=observation.get("intent", ""),
                            intent_id=observation.get("intent_id", ""),
                            cached=True,
                        )
```

Add `correlation_id`:
```python
                        await self._cognitive_journal.record(
                            entry_id=_uuid.uuid4().hex,
                            timestamp=time.time(),
                            agent_id=self.id,
                            agent_type=self.agent_type,
                            intent=observation.get("intent", ""),
                            intent_id=observation.get("intent_id", ""),
                            cached=True,
                            correlation_id=observation.get("correlation_id", ""),
                        )
```

### 4b. Procedural memory hit journal recording (line ~1169)

Add `correlation_id=observation.get("correlation_id", "")` to the existing call.

### 4c. LLM call journal recording in `_decide_via_llm()` (line ~1445)

Add `correlation_id=observation.get("correlation_id", "")` to the existing call.

---

## Section 5: Thread Correlation ID Into Episode Storage

**File:** `src/probos/types.py` (EDIT)

### 5a. Add `correlation_id` field to Episode dataclass

After the existing `importance` field (line ~425), add:

```python
    # AD-492: Cognitive cycle correlation ID for cross-layer trace threading
    correlation_id: str = ""
```

**Builder note:** `Episode` is a `@dataclass(frozen=True)`. The `= ""` default is required for backward compatibility — existing `Episode()` constructions throughout the codebase don't pass `correlation_id`. The default ensures they continue to work unchanged.

### 5b. Wire correlation_id into `_store_action_episode()`

**File:** `src/probos/cognitive/cognitive_agent.py` (EDIT)

In `_store_action_episode()` (line ~4883), add `correlation_id` to the `Episode()` constructor:

Current (showing relevant section):
```python
            episode = Episode(
                user_input=f"[Action: {intent.intent}] {callsign or self.agent_type}: {str(query_text)[:200]}",
                timestamp=_time.time(),
                agent_ids=[getattr(self, 'sovereign_id', None) or self.id],
                outcomes=[{...}],
                dag_summary=self._build_episode_dag_summary(observation),
                reflection=f"{callsign or self.agent_type} handled {intent.intent}: {result_text[:100]}",
                source=_source,
                anchors=AnchorFrame(...),
            )
```

Add after `anchors=AnchorFrame(...)`:
```python
                correlation_id=observation.get("correlation_id", ""),
```

---

## Section 6: Thread Correlation ID Into Ward Room Posts

**File:** `src/probos/ward_room_pipeline.py` (EDIT)

The `WardRoomPostPipeline.process_and_post()` method does not currently have access to the correlation_id. Rather than modifying the method signature (which would require updating all callers), the pipeline reads it from the agent's working memory.

### 6a. Log correlation_id in Ward Room post creation

In `process_and_post()`, the post creation logic has two paths:
- **`if budget.spent:`** path (lines ~130-151) — action extractor already posted
- **`else:`** path (lines ~152-160) — normal create_post via `self._ward_room.create_post()`

Both paths represent a completed Ward Room post. Log correlation_id for **both paths** by placing the debug log **outside** the if/else, immediately after the else block closes and before the Step 8 comment.

**Exact placement:** After the `else:` block's `create_post()` call (which closes at line ~160) and before the `# Step 8:` comment at line ~162. The new code is at the **same indentation level** as the `if budget.spent:` / `else:` blocks (i.e., inside the outer method body, not inside either branch).

Add:
```python
        # AD-492: Log correlation_id for trace threading
        _wm = getattr(agent, '_working_memory', None) if agent else None
        _corr_id = _wm.get_correlation_id() if _wm else None
        if _corr_id:
            logger.debug(
                "AD-492: Ward Room post in thread %s by %s (correlation_id=%s)",
                thread_id[:8], agent.agent_type, _corr_id,
            )
```

The result should read:
```python
            await self._ward_room.create_post(
                thread_id=thread_id,
                author_id=agent.id,
                body=response_text,
                parent_id=parent_id,
                author_callsign=agent_callsign or agent.agent_type,
            )

        # AD-492: Log correlation_id for trace threading
        _wm = getattr(agent, '_working_memory', None) if agent else None
        _corr_id = _wm.get_correlation_id() if _wm else None
        if _corr_id:
            logger.debug(
                "AD-492: Ward Room post in thread %s by %s (correlation_id=%s)",
                thread_id[:8], agent.agent_type, _corr_id,
            )

        # Step 8: Record response (BF-198 anti-double-posting)
```

Note: `agent` and `thread_id` are both in scope at this indentation level (they are parameters/locals of `process_and_post()`). Verified.

---

## Section 7: Thread Correlation ID Into Event Payloads

**File:** `src/probos/cognitive/cognitive_agent.py` (EDIT)

### 7a. Add correlation_id to TASK_EXECUTION_COMPLETE event

In `_run_cognitive_lifecycle()`, the `TASK_EXECUTION_COMPLETE` event is emitted at line ~2359. Add `correlation_id` to the event payload:

```python
                        _rt._emit_event(EventType.TASK_EXECUTION_COMPLETE, {
                            "agent_id": self.id,
                            "agent_type": getattr(self, 'agent_type', ''),
                            "intent_type": intent.intent,
                            "success": True,
                            "used_procedure": True,
                            "compound_dispatched": True,
                            "steps_dispatched": compound_result.get("steps_dispatched", 0),
                            "correlation_id": observation.get("correlation_id", ""),
                        })
```

### 7b. Add correlation_id to SELF_MODEL_DRIFT event

In `_run_cognitive_lifecycle()`, the `SELF_MODEL_DRIFT` event is emitted at line ~2285. Add `correlation_id` to the payload:

```python
                        _rt._emit_event(EventType.SELF_MODEL_DRIFT, {
                            "agent_id": self.id,
                            "callsign": self.callsign or self.agent_type,
                            "score": _intro_faith.score,
                            "contradictions": _intro_faith.contradictions[:3],
                            "claims_detected": _intro_faith.claims_detected,
                            "correlation_id": observation.get("correlation_id", ""),
                        })
```

### 7c. Add correlation_id to the SECOND TASK_EXECUTION_COMPLETE event (line ~2546)

**CRITICAL:** There are TWO `TASK_EXECUTION_COMPLETE` emits in `_run_cognitive_lifecycle()`. Section 7a covers the compound-dispatch branch at line ~2359. This section covers the **primary** emit at line ~2546 — the general-path completion event that fires for ~90% of cognitive cycles.

Current code at line ~2546:
```python
                _rt._emit_event(EventType.TASK_EXECUTION_COMPLETE, {
                    "agent_id": self.id,
                    "agent_type": getattr(self, 'agent_type', ''),
                    "intent_type": intent.intent,
                    "success": success,
                    "used_procedure": decision.get("cached", False),
                })
```

Add `correlation_id`:
```python
                _rt._emit_event(EventType.TASK_EXECUTION_COMPLETE, {
                    "agent_id": self.id,
                    "agent_type": getattr(self, 'agent_type', ''),
                    "intent_type": intent.intent,
                    "success": success,
                    "used_procedure": decision.get("cached", False),
                    "correlation_id": observation.get("correlation_id", ""),
                })
```

### 7d. Add correlation_id to PROCEDURE_FALLBACK_LEARNING event (line ~2566)

The `PROCEDURE_FALLBACK_LEARNING` event at line ~2566 fires inside the `if success and self._last_fallback_info is not None:` block. Add `correlation_id`:

After the existing `"timestamp": time.time(),` line, add:
```python
                        "correlation_id": observation.get("correlation_id", ""),
```

### 7e. Event threading audit — complete inventory

All four `_emit_event` calls inside `_run_cognitive_lifecycle()` are now covered:

| Line | EventType | Section | Status |
|------|-----------|---------|--------|
| ~2285 | `SELF_MODEL_DRIFT` | 7b | Threaded |
| ~2359 | `TASK_EXECUTION_COMPLETE` (compound dispatch) | 7a | Threaded |
| ~2546 | `TASK_EXECUTION_COMPLETE` (general path) | 7c | Threaded |
| ~2566 | `PROCEDURE_FALLBACK_LEARNING` | 7d | Threaded |

**Builder acceptance check:** After implementation, run:
```bash
grep -n '_emit_event' src/probos/cognitive/cognitive_agent.py
```
Verify every `_emit_event` call inside `_run_cognitive_lifecycle` (between `async def _run_cognitive_lifecycle` and the next `async def` at the same indentation level) includes `correlation_id` in its payload. Report the list.

---

## Section 8: Clear Correlation ID After Cognitive Cycle

**File:** `src/probos/cognitive/cognitive_agent.py` (EDIT)

In `_run_cognitive_lifecycle()`, the correlation_id must remain active through:
- Episode storage (`_store_action_episode()` at line ~2436 — reads from `observation` dict)
- Working memory recording (`_wm.record_action()` at line ~2393)
- All event emits (lines ~2285, ~2359, ~2546, ~2566)
- Ward room self-post (`_self_post_ward_room_response()` at line ~2583)

The clear must happen **after all of those** and **before the final return**.

**Exact placement:** Add the cleanup block immediately before the `return IntentResult(...)` at line ~2585. The anchor is:

```python
        # AD-654a: Agent self-posting for ward_room_notification
        if intent.intent == "ward_room_notification" and success and report.get("result"):
            await self._self_post_ward_room_response(intent, str(report["result"]))

        # AD-492: Clear correlation_id — cycle complete
        _wm = getattr(self, '_working_memory', None)
        if _wm:
            _wm.clear_correlation_id()

        return IntentResult(
            intent_id=intent.id,
            agent_id=self.id,
            success=success,
            result=report.get("result"),
            error=report.get("error"),
            confidence=self.confidence,
        )
```

The new 4-line block goes between the `_self_post_ward_room_response` block (line ~2583) and the `return IntentResult(...)` at line ~2585.

**No try/finally:** The clear is NOT wrapped in try/finally. If `_run_cognitive_lifecycle` raises before reaching the clear, `correlation_id` persists in working memory. This is acceptable because the next `perceive()` call (Section 1b) always overwrites `_correlation_id` via `set_correlation_id()` at cycle start. Test 17 documents this explicitly as accepted behavior.

**Explicitly NOT before `self.update_confidence(success)` at line ~2540** — that placement would clear before the TASK_EXECUTION_COMPLETE emit (line ~2546) and PROCEDURE_FALLBACK_LEARNING emit (line ~2566), breaking the threading for those events.

---

## Section 9: Tests

**File:** `tests/test_ad492_cognitive_correlation_ids.py` (NEW)

### Test infrastructure

- Use `unittest.mock.AsyncMock` for async dependencies
- Stub `CognitiveAgent` with minimal `__init__` — use `type("TestAgent", (CognitiveAgent,), {"agent_type": "test", "instructions": "test"})` pattern
- Mock `_llm_client`, `_cognitive_journal`, `_runtime`, `_working_memory`
- For `AgentWorkingMemory` tests, use the real class (no mocking needed — it's pure in-memory)

### Test categories (21 tests):

**Correlation ID generation (3 tests):**
1. `test_perceive_generates_correlation_id` — call `perceive()` with an `IntentMessage`, verify the returned observation dict has a `correlation_id` key that is a 12-char hex string.
2. `test_perceive_dict_fallback_generates_correlation_id` — call `perceive()` with a plain dict, verify `correlation_id` is present and 12-char hex.
3. `test_perceive_unique_per_call` — call `perceive()` twice, verify the two `correlation_id` values are different.

**Working memory integration (5 tests):**
4. `test_working_memory_set_get_correlation_id` — `set_correlation_id("abc123")`, verify `get_correlation_id()` returns `"abc123"`.
5. `test_working_memory_clear_correlation_id` — set, then clear, verify `get_correlation_id()` returns `None`.
6. `test_working_memory_initial_correlation_id_none` — fresh `AgentWorkingMemory`, verify `get_correlation_id()` is `None`.
7. `test_perceive_sets_working_memory_correlation_id` — call `perceive()` on a `CognitiveAgent` with a working memory, verify the working memory's `get_correlation_id()` matches the observation's `correlation_id`.
8. `test_record_action_includes_correlation_id` — set correlation_id on working memory, call `record_action()`, verify the entry's metadata contains `correlation_id`.

**Journal threading (4 tests):**
9. `test_journal_record_accepts_correlation_id` — call `CognitiveJournal.record()` with `correlation_id="test123"`, query back, verify the row has `correlation_id="test123"`.
10. `test_journal_record_default_correlation_id_empty` — call `record()` without `correlation_id`, verify the row has `correlation_id=""`.
11. `test_journal_schema_has_correlation_id_column` — after `start()`, verify the column exists via `PRAGMA table_info(journal)`.
11b. `test_journal_schema_has_correlation_id_index` — after `start()`, verify the index exists via `PRAGMA index_list(journal)`, asserting `idx_journal_correlation_id` is present. Prevents silent index regression in future schema refactors.

**Episode threading (2 tests):**
12. `test_episode_has_correlation_id_field` — create `Episode(correlation_id="abc")`, verify `episode.correlation_id == "abc"`.
13. `test_episode_default_correlation_id_empty` — create `Episode()`, verify `episode.correlation_id == ""`.

**End-to-end lifecycle (4 tests):**
14. `test_lifecycle_threads_correlation_id_to_journal` — mock `_cognitive_journal.record`, run a minimal `handle_intent()` or `_run_cognitive_lifecycle()`, verify `record()` was called with `correlation_id` matching the value from `perceive()`.
15. `test_lifecycle_threads_correlation_id_to_episode` — mock `episodic_memory.store`, run lifecycle, verify the stored `Episode` has matching `correlation_id`.
16. `test_lifecycle_clears_correlation_id_after_completion` — run lifecycle, verify `working_memory.get_correlation_id()` is `None` after completion.
17. `test_lifecycle_clears_correlation_id_on_exception` — make `decide()` raise, verify `working_memory.get_correlation_id()` is NOT `None` (it persists because the clear is before the return, not in a finally block). This test **documents accepted behavior**: stale correlation_id is overwritten by the next `perceive()` call. No try/finally needed.

**Ward Room pipeline (2 tests):**
18. `test_pipeline_logs_correlation_id` — mock an agent with working memory that has a correlation_id set, call `process_and_post()`, verify debug log contains the correlation_id (use `caplog`).
19. `test_pipeline_no_correlation_id_no_crash` — mock an agent without working memory, call `process_and_post()`, verify no crash and no correlation_id log.

**Serialization (1 test):**
20. `test_correlation_id_not_persisted_in_working_memory_dict` — call `to_dict()` on a working memory with a correlation_id set, verify `correlation_id` is NOT in the dict (it's transient, not persisted).

---

## Engineering Principles Compliance

- **SOLID/S** — Correlation ID generation is `perceive()`'s responsibility. Storage is working memory's. Each consumer (journal, episode, pipeline) receives it passively.
- **SOLID/O** — No existing method signatures are changed (except `journal.record()` which gains an optional kwarg with a default). All additions are backward-compatible.
- **SOLID/D** — Working memory provides the cross-cutting storage; consumers don't reach into `CognitiveAgent` internals to get the ID.
- **Fail Fast** — Correlation ID is best-effort. If working memory is None, the ID still exists in the observation dict. If `get_correlation_id()` returns None, consumers use `""`. Never blocks or raises.
- **Law of Demeter** — Ward Room pipeline accesses `agent._working_memory.get_correlation_id()` — one level deep via public API. No private attribute chains.
- **DRY** — Single generation point (`perceive()`), single storage point (observation dict + working memory). Consumers read, never generate.

---

## Tracker Updates

After all tests pass:

1. **PROGRESS.md** — Add entry:
   ```
   | AD-492 | Cognitive Correlation IDs | Cross-layer trace threading: perceive→decide→act→episode→post→journal. 21 tests. | CLOSED |
   ```

2. **docs/development/roadmap.md** — Update the AD-492 row status to Closed.

3. **DECISIONS.md** — Add entry:
   ```
   ## AD-492: Cognitive Correlation IDs

   **Decision:** Generate a 12-char hex correlation_id at perceive() time and thread it through the observation dict, working memory, CognitiveJournal, Episode storage, Ward Room post logging, and event payloads. Enables single-query tracing of the full cognitive cycle.

   **Rationale:** Manual timestamp correlation across 5+ data stores is the #1 debugging pain point for cognitive pipeline issues. A lightweight correlation ID (no OpenTelemetry overhead, no distributed tracing complexity) solves 90% of the tracing need. The observation dict is the natural carrier — it already flows through perceive→decide→act.

   **Alternative considered:** OpenTelemetry spans with W3C trace context. Rejected as overengineered for a single-process, single-agent pipeline. AD-492 is the minimal viable tracing; OTel can layer on top later if federation requires distributed tracing.
   ```
