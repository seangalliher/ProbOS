# Review: AD-672 Agent Concurrency Management

**Prompt:** `prompts/ad-672-agent-concurrency-management.md`
**Reviewer:** Architect
**Date:** 2026-04-27 (revision 2)
**Verdict:** ✅ **Approved — ready for builder.**

Previous review (2026-04-27) blocked on three Required items (mutable dict default, queue overflow, event flooding). All resolved.

---

## Required (must fix before building)

_None._

## Recommended (should fix)

1. **`_classify_concurrency_priority` lives at module level.** It accesses `intent.params` keys (`is_captain`, `was_mentioned`, `is_dm_channel`). Verify these param keys exist on `IntentMessage.params` in the live perceive path, or document where they are populated. If they don't exist yet, the classifier silently returns 5 (default) for everything.
2. **Queue overflow returns `[NO_RESPONSE]`** as `IntentResult.success=True`. Reconsider — a shed intent is not a successful intent. Use `success=False` with a typed reason field, or define a new `result` sentinel that downstream consumers (trust scoring, learning loop) recognize as "shed by concurrency limiter, do not penalize agent."
3. **`slot()` is the preferred API but raw `acquire/release` remains exposed.** Prompt acknowledges this; consider marking the raw methods as `_acquire`/`_release` or adding a runtime warning when called outside a context manager.

## Nits

4. **Tracker section missing** (PROGRESS.md / roadmap / DECISIONS).
5. **No "Do not build" section** — add: "do not implement work-stealing across agents", "do not modify the global LLM semaphore", "do not expose queue contents in default telemetry payloads".
6. **`_capacity_warning_cooldown: 30.0` seconds** hardcoded as instance attr. Move to `ConcurrencyConfig` for tunability.
7. **`uuid.uuid4().hex[:12]` for thread_id** — collision probability is acceptable but document the choice (or use a monotonic counter for guaranteed uniqueness within a single agent's lifetime).

## Verified

- ✅ **Acceptance Criteria block present** with test count (18 tests) and Engineering Principles compliance line.
- ✅ **Mutable dict default resolved.** `role_overrides` now uses `Field(default_factory=lambda: {...})`. `Field` import block included with conditional skip note.
- ✅ **Queue overflow defined.** `acquire()` raises `ValueError` when queue is full; `handle_intent` wrapper catches and returns `[NO_RESPONSE]` with full-context warning log per Fail Fast.
- ✅ **Capacity warning debounced** with 30s cooldown — addresses event flooding under sustained load.
- ✅ **Typed `AgentCapacityApproachingEvent` dataclass** added matching the standard pattern.
- ✅ **Future cancellation handled.** `release()` skips cancelled futures via `if next_item.future.cancelled(): continue` loop and only resolves live futures.
- ✅ **Priority queue implementation specified.** `list.sort(key=lambda q: (-q.priority, q.queued_at))` with explicit rationale (small queue size makes O(n log n) negligible vs heapq complexity).
- ✅ **`asynccontextmanager` slot()** is the documented preferred API with usage example.
- ✅ **Decorative ceiling note** added to `default_max_concurrent` field comment.
- ✅ **`asyncio.get_running_loop()` (not `get_event_loop()`)** for future creation.
- ✅ **Cancellation re-raised** in `_emit_capacity_warning`.
- ✅ **`_lock` async lock** guards reentrant await gaps in `acquire`/`release`.
- ✅ **`snapshot()` diagnostic** for /api endpoints.
- ✅ **`arbitrate()`** for resource-key conflict resolution returns yielding thread_id (caller decides how to cancel).
- ✅ **Role rationale documented** ("bridge agents handle high-stakes decisions sequentially; operations agents handle high-throughput routine tasks").
- ✅ **Startup wiring** in `cognitive_services.py` follows existing `set_sub_task_executor` pattern with role lookup via `pool_group`.

---

## Recommendation

Ship. The Recommended items are real concerns but not build-blockers — items 1 and 2 in particular should be tracked as follow-ups so they don't get lost. The redesign cleanly addresses every previous Required concern.
