# Review: AD-572e — Task Awareness in Captain DM Context

**Verdict:** ✅ Approved
**Headline:** Final AD-572 child. Mirror-pattern conformant; one small Section-2 divergence from Combo C and one phantom-fallback nit.

Tolerance check (convention #15, relaxed): 0 Required ≤ 1 ⚠️ permitted. Approved without revision pass needed for blockers; Recommended items folded by author at discretion.

---

## Required (must fix before building)

None.

## Recommended (should fold)

1. **Section 2: mirror Combo C's `isinstance(...)` injection guard, not `setdefault`.** Combo C at `src/probos/proactive.py:1192-1193` uses:

   ```python
   if isinstance(context.get("captain_engagement"), dict):
       context["captain_engagement"]["wardroom_activity_summary"] = summary
   ```

   This semantic only injects when `snapshot()` already populated `captain_engagement` (line 1184). The prompt's draft uses `context.setdefault("captain_engagement", {})["task_awareness"] = task_summary`, which would create the key even when `snapshot()` failed silently. Diverges from canonical mirror. Replace `setdefault` with the Combo C `isinstance` guard for true pattern conformance.

2. **Section 2: add `hasattr(engagement_provider, "task_awareness")` forward-compat guard.** Combo C wraps the call in `if hasattr(engagement_provider, "wardroom_activity_summary"):` (proactive.py:1189). The AD-572e draft calls `provider.task_awareness(agent.id)` unconditionally. For rolling-deploy and downgrade safety (and pure mirror conformance), wrap in `hasattr`.

3. **Section 2: reuse `engagement_provider` local from line 1181, don't re-fetch.** The draft shows `provider = getattr(self._runtime, "captain_engagement_provider", None)` as a fresh local. Combo C's `wardroom_activity_summary` block (proactive.py:1189-1196) is nested inside the same `if engagement_provider is not None and hasattr(...)` block from line 1182. AD-572e should slot in as a sibling block right after Combo C's, reusing `engagement_provider` and `context["captain_engagement"]`. Reduces reader confusion (two `captain_engagement_provider` fetches in one loop iteration).

   Suggested final shape (replaces Section 2 code):

   ```python
   # AD-572e: Task awareness in Captain DM context
   if hasattr(engagement_provider, "task_awareness"):
       try:
           task_summary = await engagement_provider.task_awareness(agent.id)
           if isinstance(context.get("captain_engagement"), dict):
               context["captain_engagement"]["task_awareness"] = task_summary
       except Exception:
           logger.debug("AD-572e: task_awareness injection failed", exc_info=True)
   ```

## Nits

1. **Section 1: phantom `.type` fallback.** Draft line `"type": getattr(item, "work_type", "") or getattr(item, "type", "") or "",`. `WorkItem` (workforce.py:559-585) has only `work_type`. The `or getattr(item, "type", "")` second fallback is unreachable. Drop it:

   ```python
   "type": getattr(item, "work_type", "") or "",
   ```

2. **Test #9 description:** "Verify the join key is agent_id (NOT agent_type)" — accurate, but test name should assert that the kwarg passed to `list_work_items` is the agent's UUID-form `id` (matching `WorkItem.assigned_to` semantic at workforce.py:563: "agent UUID or pool ID"), not the type string. Recommend renaming to `test_task_awareness_passes_agent_uuid_to_assigned_to_filter` for clarity.

3. **Section 2 verify-first hint:** Prompt says "verify location by grep — likely in `src/probos/proactive.py` near where `wardroom_activity_summary` was added in Combo C". Architect-located injection site is **proactive.py:1181-1196**, inside the `engagement_provider` block immediately after the Combo C `wardroom_activity_summary` injection. Add this exact citation to Section 2 to remove Builder ambiguity.

## Verified Improvements

- **Mirror-pattern conformance (high-priority point #1):** `task_awareness()` is async, defensive (catches all, logs at debug, returns `{}`), returns structured dict. Matches Combo C `wardroom_activity_summary` shape at captain_engagement.py:118-159. ✅
- **WorkItemStore signature drift (high-priority point #2):** `list_work_items(status, assigned_to, work_type, parent_id, priority, tags, limit, offset)` confirmed at workforce.py:1066-1076. No drift since Wave 10/12/16. AD-572e kwargs (`status="open", assigned_to=agent_id, limit=10`) all valid. ✅
- **WorkItem field names (high-priority point #3):** `id`, `title`, `work_type` are direct dataclass fields on `WorkItem` (workforce.py:559-567), NOT nested under `metadata`. The Wave 10 `metadata` lesson does not apply. ✅
- **Combo C injection site located (high-priority point #4):** `src/probos/proactive.py:1181-1196`. Canonical pattern uses `getattr(rt, "captain_engagement_provider", None)` → `hasattr(provider, "wardroom_activity_summary")` → try/except → `isinstance(context.get("captain_engagement"), dict)` guard. ✅
- **Public-attribute discipline (high-priority point #5):** Helper is method on existing `CaptainEngagementProvider` class. No new public attributes; no new wiring; constructor surface unchanged. ✅
- **Defensive error handling matches sibling helpers** (Combo A `snapshot`, Combo C `wardroom_activity_summary`).
- **No new EventTypes** — observational only, leverages existing `CAPTAIN_DM_PRIORITY_QUEUED`.
- **No new Pydantic config** — Section 3 explicitly states this.
- **Read-only WorkItemStore consumer** — no writes, no schema changes.
- **AD-572d-i scope discipline** — Section 4 of "What This Does NOT Change" explicitly preserves the deferred interruptible-wait pattern.
- **23 standing conventions audit** — no violations:
  - Default-False on transitional flags: N/A (no flags introduced)
  - Frozen dataclass field ordering: N/A (no new dataclasses)
  - Bare mutable Pydantic defaults: N/A (no new config)
  - Layer discipline: cognitive→workforce read-only is allowed (cross-cutting)
  - Async hygiene: helper is async; await present at injection site
  - Phantom API: 0 (pre-check confirmed)
  - Episodic completeness, consensus gating, trust storage: N/A (read-only consumer)

## Verified Against Codebase (2026-05-03)

```
grep -n "class CaptainEngagementProvider\|def snapshot\|async def wardroom_activity_summary" src/probos/cognitive/captain_engagement.py
   23: class CaptainEngagementProvider:
   38:     def snapshot(self) -> dict[str, int]:
  118:     async def wardroom_activity_summary(self) -> dict[str, Any]:

grep -n "async def list_work_items\|class WorkItem\b" src/probos/workforce.py
  559: class WorkItem:
 1066:     async def list_work_items(

read src/probos/workforce.py L559-L585
  -> id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
  -> title: str = ""
  -> work_type: str = "task"
  (no `.type` field)

grep -n "captain_engagement_provider\|wardroom_activity_summary" src/probos/proactive.py
 1181:     engagement_provider = getattr(rt, "captain_engagement_provider", None)
 1189:     if hasattr(engagement_provider, "wardroom_activity_summary"):
 1191:         summary = await engagement_provider.wardroom_activity_summary()
 1193:         context["captain_engagement"]["wardroom_activity_summary"] = summary
 1196:         "AD-572c: wardroom_activity_summary failed", exc_info=True,
```

## Disposition

Approved as-is. Author's discretion on the 3 Recommended items; Nit #1 (phantom `.type` fallback) should be folded since it costs one line. No revision pass required to clear blockers. If author folds Recommended #1-3 + Nit #1, Builder gets a cleaner mirror; if not, the v1 still ships correctly because `setdefault` is functionally safe (just semantically divergent).
