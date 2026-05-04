# AD-572e: Task Awareness in Captain DM Context

**Status:** Drafted (Wave 18)
**Risk:** low (read-only consumer; additive helper on existing `CaptainEngagementProvider`)
**Depends on:** Combo A AD-572b (`CaptainEngagementProvider`, shipped at commit 16c4ea4), Combo C AD-572c (`wardroom_activity_summary`, shipped at commit ffda515), AD-496 (`WorkItemStore`, shipped)
**Closes:** Updates GH issue #109 (final AD-572 child); leaves issue open until any remaining items resolve

---

## Solution Overview

Combo A (Wave 8) shipped `CaptainEngagementProvider.snapshot()` with `alerts_pending`/`wardroom_activity_60s`/`dm_queue_depth` (572b). Combo C (Wave 13) shipped `wardroom_activity_summary()` (572c). Combo C also shipped 572d via the deferred `AD-572d-i` (Captain Priority Queue — proactive interruptible-wait pattern still missing). 

**AD-572e** is the final 572-series child still open: **task awareness in Captain DM context**. v1 ships **per-agent open-WorkItem summary** that augments Captain DM proactive context — when the Captain DMs an agent, the agent's proactive context surfaces "you have N open work items: [titles]" so the agent can ground its response in current commitments.

**v1 ships 1 of 1 capability** (no further sub-deferrals — task awareness is a single read-only helper):

1. **`CaptainEngagementProvider.task_awareness(agent_id)`** — async helper that calls `runtime.work_item_store.list_work_items(status="open", assigned_to=agent_id, limit=10)` and returns a structured summary: `{"open_count": int, "tasks": [{"id", "title", "type"}]}`. Empty dict if work_item_store unavailable.
2. **Proactive context injection** — when proactive cognitive loop builds Captain DM response context, call `await captain_engagement_provider.task_awareness(agent.id)` and inject result into `context["captain_engagement"]["task_awareness"]` (extends Combo C's `context["captain_engagement"]` dict).

## Dependencies

- `runtime.captain_engagement_provider` — public attribute (verified shipped Combo A; mutated Combo C). `CaptainEngagementProvider` class at `src/probos/cognitive/captain_engagement.py:23`.
- `runtime.work_item_store` — read-only consumer. `list_work_items(status, assigned_to, work_type, parent_id, priority, tags, limit, offset)` verified at `workforce.py:1066-1076` (Wave 10/12/16 verified).
- Proactive cognitive loop — context-build phase. Existing pattern: Combo C added `wardroom_activity_summary` injection. AD-572e mirrors that integration.

All reads from existing surfaces; no writes; no new EventTypes; no new public attributes.

## Sections

### Section 0 — EventTypes

No new EventTypes. AD-572e is observational; the existing `CAPTAIN_DM_PRIORITY_QUEUED` (Combo A AD-572b) covers the Captain-engagement signal surface.

### Section 1 — Add `task_awareness()` to `CaptainEngagementProvider`

In `src/probos/cognitive/captain_engagement.py`:

```python
async def task_awareness(self, agent_id: str) -> dict[str, Any]:
    """Return open-WorkItem summary for an agent.

    AD-572e v1. Used by proactive cognitive loop to ground Captain DM
    response context in agent's current commitments.

    Args:
        agent_id: The agent identifier (NOT agent_type; matches WorkItemStore.list_work_items
            assigned_to filter).

    Returns:
        {
            "open_count": int,                # total open WorkItems for agent
            "tasks": [                         # up to 10 most recent
                {"id": str, "title": str, "type": str},
                ...
            ],
        }
        Empty dict {} if work_item_store unavailable or agent_id missing.

    Defensive: catches all exceptions and logs at debug; returns empty dict
    rather than raising (consistent with snapshot() error handling).
    """
    rt = getattr(self, "_runtime", None)
    if rt is None or not agent_id:
        return {}
    work_item_store = getattr(rt, "work_item_store", None)
    if work_item_store is None:
        return {}
    try:
        items = await work_item_store.list_work_items(
            status="open",
            assigned_to=agent_id,
            limit=10,
        )
    except Exception:
        logger.debug("AD-572e: work_item_store query failed", exc_info=True)
        return {}
    return {
        "open_count": len(items),
        "tasks": [
            {
                "id": getattr(item, "id", "") or "",
                "title": getattr(item, "title", "") or "",
                "type": getattr(item, "work_type", "") or getattr(item, "type", "") or "",
            }
            for item in items[:10]
        ],
    }
```

Mirrors Combo C's `wardroom_activity_summary` shape — async helper, defensive read, structured dict return.

### Section 2 — Proactive context integration

In proactive cognitive loop's Captain-DM context-build path (verify location by grep — likely in `src/probos/proactive.py` near where `wardroom_activity_summary` was added in Combo C).

Mirrors Combo C pattern:

```python
# AD-572e: Task awareness in Captain DM context
provider = getattr(self._runtime, "captain_engagement_provider", None)
if provider is not None:
    try:
        task_summary = await provider.task_awareness(agent.id)
        context.setdefault("captain_engagement", {})["task_awareness"] = task_summary
    except Exception:
        logger.debug("AD-572e: task_awareness injection failed", exc_info=True)
```

Verify-first: Builder reads Combo C's wardroom_activity_summary injection site to find the canonical injection point.

### Section 3 — Pydantic config

No new config. `CaptainEngagementProvider` constructor takes `runtime` + `emit_event` + `wardroom_activity_window_s` only; AD-572e v1 inherits the existing config surface.

## What This Does NOT Change

- `CaptainEngagementProvider.snapshot()` — Combo A surface untouched.
- `CaptainEngagementProvider.wardroom_activity_summary()` — Combo C surface untouched.
- `CAPTAIN_DM_PRIORITY_QUEUED` event emission — Combo A behavior preserved.
- WorkItemStore — read-only consumer; no schema or method changes.
- Proactive loop's existing context-build phases — additive injection only.
- AD-572d (Captain Priority Queue) — still deferred to AD-572d-i (interruptible-wait pattern); AD-572e doesn't unblock it.

## Test Plan

| # | Test | Purpose |
|---|---|---|
| 1 | `test_task_awareness_returns_empty_when_runtime_none` | Edge case |
| 2 | `test_task_awareness_returns_empty_when_agent_id_empty` | Edge case |
| 3 | `test_task_awareness_returns_empty_when_work_item_store_missing` | Edge case |
| 4 | `test_task_awareness_returns_empty_on_query_exception` | Defensive error path |
| 5 | `test_task_awareness_returns_open_count_and_tasks` | Happy path |
| 6 | `test_task_awareness_caps_tasks_at_10` | Limit enforcement |
| 7 | `test_task_awareness_extracts_id_title_type_fields` | Field extraction |
| 8 | `test_task_awareness_handles_missing_fields_gracefully` | Missing fields default to "" |
| 9 | `test_task_awareness_calls_list_work_items_with_assigned_to` | Verify the join key is agent_id (NOT agent_type) |
| 10 | `test_task_awareness_calls_list_work_items_with_status_open` | Verify status filter |
| 11 | `test_proactive_loop_injects_task_awareness_into_captain_engagement_context` | Section 2 integration |
| 12 | `test_proactive_loop_handles_provider_missing_gracefully` | Defensive integration |

Total: ~12 tests at `tests/test_ad572e_task_awareness.py`.

## Tracking

1. **PROGRESS.md:** prepend AD-572e entry.
2. **DECISIONS.md:** add entry under Era V:

```markdown
### AD-572e: Task Awareness in Captain DM Context (2026-05-03)

**Problem:** Combo A (Wave 8) shipped `CaptainEngagementProvider.snapshot()` for Captain-engagement signals. Combo C (Wave 13) added `wardroom_activity_summary()` for Ward Room context. Captain DMs to specific agents still lacked task awareness — agents had no current-commitments context when responding to Captain queries about their work.

**Decision:** Add `task_awareness(agent_id)` async helper to existing `CaptainEngagementProvider` (no new class, no new public attribute). Reads `runtime.work_item_store.list_work_items(status="open", assigned_to=agent_id, limit=10)`. Returns structured dict (`open_count`, `tasks: [{id, title, type}]`). Proactive cognitive loop injects result into `context["captain_engagement"]["task_awareness"]` during Captain DM response build (mirrors Combo C's wardroom_activity_summary integration).

**Why:** Final AD-572 child. Bounded scope — single async helper + single proactive-loop integration point. Defensive (returns empty dict on any failure, consistent with sibling helpers). Read-only consumer of WorkItemStore (no writes, no schema changes). Mirrors proven Combo C pattern.

**Cross-links:** AD-572b (CaptainEngagementProvider, Combo A), AD-572c (wardroom_activity_summary, Combo C), AD-496 (WorkItemStore), AD-572d-i (Captain Priority Queue — separately deferred; not unblocked by AD-572e).
```

3. **docs/development/roadmap.md:** flip AD-572e status to `complete — task_awareness helper + proactive injection shipped`. Update AD-572 deferred list (line 4572) to reflect 572b/c/e shipped, 572d-i still deferred.

## Verified Against Codebase (2026-05-03)

```
grep -n "class CaptainEngagementProvider\|def snapshot\|def wardroom_activity_summary" src/probos/cognitive/captain_engagement.py
   23: class CaptainEngagementProvider
  (Combo A shipped snapshot; Combo C added wardroom_activity_summary)

grep -n "list_work_items" src/probos/workforce.py
 1066: async def list_work_items(self, status, assigned_to, work_type, parent_id, priority, tags, limit, offset)

grep -n "captain_engagement_provider\|wardroom_activity_summary" src/probos/proactive.py
  (Builder verifies the Combo C injection site for Section 2 mirroring)

grep -n "runtime.work_item_store\|work_item_store" src/probos/runtime.py
  (Builder verifies runtime attribute name — should match Wave 10 AD-500 + Wave 12 AD-477 verification)
```

## Acceptance Criteria

- `CaptainEngagementProvider.task_awareness(agent_id)` async helper added.
- Proactive cognitive loop integration injects `context["captain_engagement"]["task_awareness"]`.
- 12 tests pass.
- DECISIONS.md entry under Era V.
- AD-572 issue #109 partial-completion comment updated (572e shipped; 572d-i remains deferred).

## Hard-Stops

- `WorkItemStore.list_work_items(status="open", assigned_to=agent_id)` returns wrong shape (e.g., signature drift since Wave 10/12/16 verification) — surface; revision pass would document.
- `CaptainEngagementProvider` class location moved (no longer at `cognitive/captain_engagement.py:23`) — surface.
- Proactive loop's `wardroom_activity_summary` injection site can't be located cleanly — surface; may need different integration pattern.
- `WorkItem.id` / `.title` / `.work_type` field names differ from assumption — Wave 10's `WorkItem(metadata=...)` revealed `metadata` is the data field; verify item identity/title fields at build time.
