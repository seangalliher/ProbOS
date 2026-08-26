# AD-1271 / BF-735: scaffolding is not work, and the count must say so

**Status:** Ready to build
**Closes:** #1194 (BF-735)
**Dependencies:** none — AD-1128 already removed the producer
**Estimated tests:** 8 new (6 Python, 2 TS), 0 modified

---

## Problem

36 work items titled `Room workspace` are the *entire* open column on the live vessel. They were created by AD-1084's `ensureRoomTask` purely to mint a `task_id` for the FILES rail to bind to. The producer is dead (AD-1128, `3969c80b`, 2026-07-21) and its absence is guarded, so the population is closed at 36 and cannot grow.

Two things are wrong, and only one of them is the rows.

**1. The rows are not work, but every work query counts them.** `WorkItemStore.list_work_items(status="open")` is the single query boundary and it has five Captain-facing consumers, not one:

| Consumer | Anchor | What the Captain sees |
|---|---|---|
| Captain's Log | `naval/captains_log.py:201` | `f"Open work items: {len(items)}"` → **"Open work items: 36"** |
| Plan of the Day | `naval/plan_of_day.py:145` | "Active work items" |
| Ship State Snapshot | `onboarding/ship_state_snapshot.py:236` | open items in the boot snapshot |
| Quartermaster sweep | `agents/quartermaster.py:164`, `:441` | reconciler scan set |
| Work board | `routers/workforce.py:163` | BACKLOG column |

Filtering the board fixes one of five. The issue itself predicted this failure of its own Option 2 — *"every consumer then has to know better."*

**2. Four of the 36 hold abandoned work; 32 hold nothing.** 32 rows are inert (`steps` empty, `metadata` `{}`). 4 carry real Captain-visible 3-step checklists with `submitted`/`pending`/`done` statuses and `metadata.steps_gate_completion: true`, last touched 58 days ago.

## Solution

Two independent axes, decided separately.

**Provenance — uniform.** All 36 came from `ensureRoomTask` inside its lifetime. A Captain later typing a checklist into one does not change where the row came from. Flag **all 36** `metadata.ui_scaffold = true`.

**Work state — not uniform.** Cancel the **4** that hold abandoned work. Leave the 32 `open`; once every work query excludes scaffolding, their status is a vestigial column, not a claim.

**The filter lives at the store.** `list_work_items` gains `include_scaffold: bool = False` and a SQL predicate. All five narrators become honest at once and none of them learns the word "scaffolding".

### Non-goals, and why

- **Do not delete.** All 36 ids are live in `chat_threads.task_id`. Delete orphans the link and 404s the rail.
- **Do not clear `chat_threads.task_id`.** Clearing is a regression on 36 rooms: `WorkspaceFilesRail.attach.test.tsx:63` pins that "+ Attach" *hides* when `taskId` is unset; `isWorkspaceRoom.ts:23` treats a set `task_id` as the authoritative workspace marker; `chatFilters.ts:52` excludes `task_id` rooms from the Chats list, so clearing pops 36 rooms into it.
- **Do not mark the 32 `done`.** `task` has no `open → done` edge (`workforce.py:173-182`); only `in_progress → done`, and `open → in_progress` is `requires_assignment=True`. Structurally unreachable without inventing an assignee.
- **Do not touch AD-1084's seam.** The producer is already gone.
- **Do not filter in `WorkBoard.tsx`.** The board is a consumer, not the boundary.

---

## Section 1 — the store contract (`src/probos/workforce.py`)

Filter in **SQL**, beside the other scalar columns — not in memory after the fetch. `tags` is filtered post-`LIMIT` and the code flags that as a wart; AD-1176 moved `project_id` into SQL for exactly this reason (`workforce.py:2214-2217`).

```
===SEARCH===
        tags: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
        project_id: str | None = None,
    ) -> list[WorkItem]:
        """List work items with optional filters. Ordered by priority ASC, created_at DESC."""
===REPLACE===
        tags: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
        project_id: str | None = None,
        include_scaffold: bool = False,
    ) -> list[WorkItem]:
        """List work items with optional filters. Ordered by priority ASC, created_at DESC.

        AD-1271: rows carrying ``metadata["ui_scaffold"] = true`` are excluded by
        default. They are UI bindings that were minted as work items to hold a
        ``task_id`` (AD-1084's ``ensureRoomTask``), not units of work, and five
        Captain-facing narrators count whatever this returns. Excluding here
        rather than at each caller keeps the Captain's Log, Plan of the Day, the
        boot snapshot, the Quartermaster sweep and the board honest without any
        of them knowing the word "scaffolding". ``include_scaffold=True`` is the
        escape hatch for tooling that must see them.
        """
===END REPLACE===
```

```
===SEARCH===
        if priority is not None:
            conditions.append("priority = ?")
            params.append(priority)
        where = " AND ".join(conditions) if conditions else "1=1"
===REPLACE===
        if priority is not None:
            conditions.append("priority = ?")
            params.append(priority)
        if not include_scaffold:
            # SQL-side, not post-fetch: the LIMIT must apply after the filter.
            conditions.append(
                "(metadata IS NULL OR json_extract(metadata, '$.ui_scaffold') IS NOT 1)"
            )
        where = " AND ".join(conditions) if conditions else "1=1"
===END REPLACE===
```

`json_extract` against a JSON text column has precedent at `knowledge/semantic_store.py:333-384`. `IS NOT 1` (not `!= 1`) so `NULL` — the absent-key case — does not swallow the row.

**Safety property to state in the commit message:** default-exclude only removes rows that carry the flag, and zero rows carry it before the migration runs. All 17 call sites and their existing tests are unaffected by this change alone.

---

## Section 2 — keep the producer dead (`ui/src/components/workspace/__tests__/WorkspaceFilesRail.test.tsx`)

The guard exists and passes. It needs a reason attached so a future tidy-up does not read it as a redundant negative assertion.

```
===SEARCH===
  it('todosApi no longer exports passive ensureRoomTask', () => {
    expect('ensureRoomTask' in todosApi).toBe(false);
===REPLACE===
  // BF-735: this guard is load-bearing. ensureRoomTask (AD-1084) minted one
  // permanent open work item per Captain-created room; 36 accumulated before
  // AD-1128 removed it. Re-exporting it reopens a closed population.
  it('todosApi no longer exports passive ensureRoomTask', () => {
    expect('ensureRoomTask' in todosApi).toBe(false);
===END REPLACE===
```

---

## Section 3 — the one-off migration script (`scripts/bf735_retire_room_scaffolding.py`)

**New file.** Not a startup migration — see Rationale below.

Requirements:

1. **Resolve the data directory from config, never from the repo layout.** `d:\ProbOS\data` is a stale decoy; the live store is under `%LOCALAPPDATA%\ProbOS\data`.
2. **Dry-run by default.** `--apply` to write. Print every selected row (id, title, status, created_at, step count) before any write.
3. **Select by join, not by title alone.** The population is exactly the rows that are (a) `title = 'Room workspace'`, (b) `status = 'open'`, (c) `assigned_to IS NULL`, and (d) whose id appears in `chat_threads.task_id`. The join is what makes the match specific.
4. **Assert its own premise, and abort if it fails.** If the selection is not exactly **36** rows, print the count and exit non-zero without writing. A migration that silently matched 3 rows or 300 proves nothing about the population it claims to be closing. Same for the partition: assert exactly **4** rows have a non-empty `steps` list and exactly **32** have an empty one.
5. **Two writes, in this order:**
   - all 36 → merge `ui_scaffold: true` into `metadata` (owned-key merge; do not clobber `steps_gate_completion` or `facilitator`)
   - the 4 with steps → `status = 'cancelled'`
6. **Idempotent.** Re-running after a successful apply selects 0 rows already flagged and exits 0 with "nothing to do".
7. **Do not touch `chat_threads`.** No link is cleared. No row is deleted.
8. Vessel must be down. Say so in the docstring and in `--help`.

`open → cancelled` is legal for the 4 despite being unassigned and gated:
- `WorkTypeTransition("open", "cancelled")` carries no `requires_assignment` (`workforce.py:175`).
- The `steps_gate_completion` refusal is scoped to `new_status == "done"` only (`workforce.py:3142-3145`).

Prefer driving the cancel through `transition_work_item` so the `WORK_ITEM_STATUS_CHANGED` event and snapshot refresh fire normally. If the script runs against a bare DB with no runtime, raw SQL is acceptable — but then it must not pretend an event was emitted.

---

## Tests

**`tests/test_ad1271_scaffold_filter.py`** (new, 6 tests)

1. `test_list_work_items_excludes_scaffold_by_default` — flagged row absent from `list_work_items()`.
2. `test_list_work_items_include_scaffold_returns_it` — same row present with `include_scaffold=True`.
3. `test_list_work_items_keeps_rows_without_the_flag` — `metadata` `{}` and `metadata` `NULL` both still returned. Pins that `IS NOT 1` does not swallow the absent-key case.
4. `test_scaffold_filter_applies_before_limit` — seed `limit + 1` scaffold rows plus 1 real row, call with a small `limit`, assert the real row is returned. Pins the SQL-vs-memory choice; fails if the filter is moved post-fetch like `tags`.
5. **Seam test (crosses the boundary):** `test_captains_log_open_count_excludes_scaffold` — a flagged `open` row in the store, then `CaptainsLog._collect_work_items_section()` returns `"_(no open work items)_"`, not `"Open work items: 1"`. This is the one test that spans store → narrator. Two tests that each stop at the boundary would prove nothing.
6. `test_unassigned_gated_task_transitions_open_to_cancelled` — `task`, `assigned_to=None`, `metadata.steps_gate_completion=true`, 3 unfinished steps → `transition_work_item(id, "cancelled")` returns the item with `status == "cancelled"`. Pins that the `done`-only carve-out is not widened, which is the exact shape of the 4.

**`tests/test_ad1271_scaffold_filter.py` must not** assert a count of 36 or reference live-vessel data. It tests the contract, not the migration.

**`ui/src/components/workspace/__tests__/WorkspaceFilesRail.cancelled.test.tsx`** (new, 2 tests)

7. `renders steps for a cancelled work item` — `fetchTaskSteps` resolving for a cancelled item still renders the checklist. Pins that cancelling the 4 does not hide their content, which is the entire justification for cancelling rather than leaving them.
8. `keeps the attach button when taskId is set on a cancelled item` — "+ Attach" survives. `POST /work-items/{id}/inputs` has no status gate (`routers/workforce.py:357+`); pin that.

**Do not add** a test asserting the board filters scaffolding. The board does not filter — the store does. A board-level assertion would pin the wrong layer.

---

## Rationale: one-off script, not a guarded startup migration

| | One-off script | Startup migration |
|---|---|---|
| Population | closed at 36, producer dead + guarded | same |
| Schema change | none — writes to existing `metadata` JSON | none, so no `ALTER` forces a boot hook |
| Blast radius | one vessel, one run, human reads the dry-run | every boot, every future vessel, forever |
| Title matching | reviewed by a human once | permanent latent hazard — a Captain naming a real item `Room workspace` and leaving it open+unassigned gets it silently flagged |

A recurring guard defends against a producer that cannot fire. The durable half of this work (the contract + the filter) ships as code; only the *data touch* is the script. That separation is the point.

---

## What This Does NOT Change

- AD-1084's binding seam, or `chat_threads.task_id` for any row.
- `WorkBoard.tsx` column config or `blockedItems` rendering.
- `is_dispatchable` (`mesh/work_item_router.py:59`) or `WorkReconciler.decide` (`cognitive/work_reconciler.py`).
- `GET /work-items/{id}/steps`, `POST /work-items/{id}/inputs`, or `DELETE /work-items/{id}`.
- `list_ws_visible_work_items` — separate query, separate concern, out of scope.
- Crew-session resume. All 36 rooms already 409 `crew_session_thread_task_incompatible` (`crew_session.py:2425`) because the linked item is a `task`; that is unchanged and out of scope.

---

## Tracking

- `PROGRESS.md` — CLOSED entry for BF-735.
- `docs/development/roadmap.md` — Bug Tracker row for BF-735.
- `DECISIONS.md` — AD-1271: work queries exclude UI scaffolding by default; the store is the boundary.

---

## Acceptance Criteria

Mapped to #1194's own list.

| # | Issue acceptance | Disposition |
|---|---|---|
| 1 | Room binds FILES rail without leaving a permanent open work item | **Already satisfied** by AD-1128. Section 2 attaches the reason to the guard so it survives future tidy-ups. |
| 2 | Existing scaffolding rows dealt with explicitly | Section 3: 36 flagged, 4 cancelled, 0 deleted, 0 links cleared. |
| 3 | The board's `open` count reflects work a human could act on | **Widened.** Section 1 makes all five open-count narrators honest, not just the board. |
| 4 | Complies with Engineering Principles | Below. |

Plus:

- `list_work_items` excludes scaffolding in SQL, before `LIMIT`, and `include_scaffold=True` returns it.
- Rows with `metadata` `NULL` or `{}` are unaffected.
- The migration aborts non-zero unless it selects exactly 36 / 4 / 32, and is idempotent on re-run.
- Cancelling a gated, unassigned `task` succeeds; its checklist still renders in its room.
- Full repository gate green. Report the test count.
- Run the `Diff Reviewer` subagent on the staged diff with a different model than the author, and address findings before committing.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-08-26, HEAD `a63d828c`)

```
grep -n "async def list_work_items" src/probos/workforce.py
  2184: async def list_work_items(

grep -n "list_work_items(status=\"open\")" src/probos/
  naval/captains_log.py:201       items = await store.list_work_items(status="open")
  naval/plan_of_day.py:145        items = await store.list_work_items(status="open")
  onboarding/ship_state_snapshot.py:236  ... status="open", limit=_MAX_OPEN_WORK_ITEMS
  agents/quartermaster.py:164,441 open_items = await self._store.list_work_items(status="open", ...)
  routers/workforce.py:163        items = await runtime.work_item_store.list_work_items(

read src/probos/naval/captains_log.py:207
  207: return f"Open work items: {len(items)}"

read src/probos/workforce.py:2214-2217
  2214: # AD-1176: filtered in SQL alongside the other scalar columns, not
  2215: # in memory like ``tags`` -- the LIMIT must apply after the filter.

read src/probos/workforce.py:173-182   (work type "task")
  175: WorkTypeTransition("open", "cancelled"),          <- no requires_assignment
  (no "open" -> "done" edge exists; only in_progress -> done)
  174: WorkTypeTransition("open", "in_progress", requires_assignment=True)

read src/probos/workforce.py:3142-3145
  3142: if (new_status == "done"
  3144:     and (item.metadata or {}).get("steps_gate_completion")   <- "done" only

grep -n "json_extract" src/probos/knowledge/semantic_store.py
  333: AND json_extract(payload, '$.completed') = ?

read src/probos/mesh/work_item_router.py:59-66
  59: def is_dispatchable(...)  -> configured tag OR metadata["dispatchable"]

read src/probos/cognitive/work_reconciler.py:107,128
  107: if not is_dispatchable:      -> "skip"        <- gate fires FIRST
  128: if assignee is None and status == "open":     <- never reached for these

read src/probos/routers/workforce.py:280-297
  280: @router.get("/work-items/{work_item_id}/steps")
  290: item = await runtime.work_item_store.get_work_item(work_item_id)   <- by id, no list filter

read src/probos/routers/workforce.py:357
  357: @router.post("/work-items/{work_item_id}/inputs")   <- no status gate

grep -n "ensureRoomTask" ui/src/components/workspace/__tests__/WorkspaceFilesRail.test.tsx
  732: it('todosApi no longer exports passive ensureRoomTask', () => {
  733:   expect('ensureRoomTask' in todosApi).toBe(false);

grep -n "hides the attach button" ui/src/components/workspace/__tests__/WorkspaceFilesRail.attach.test.tsx
  63: it('hides the attach button when taskId is not set', ...)

read ui/src/components/workspace/isWorkspaceRoom.ts:23
  23: // A set task_id is the authoritative "this is a workspace" marker.

read ui/src/components/workspace/chatFilters.ts:52
  52: if (thread.task_id) return false; // exclude AD-925 task rooms

grep -n "crew_session_thread_task_incompatible" src/probos/cognitive/crew_session.py
  2425, 2433, 2443, 2500, 2515, 2638   <- open_or_resume path only

read ui/src/components/workspace/todosApi.ts:50-51
  51: fetch(`/api/work-items/${encodeURIComponent(taskId)}/steps?limit=1001`)
```

### Absence Verified (2026-08-26)

```
CLAIM: no consumer other than the five listed calls list_work_items with status="open"
RUN:   grep -n "list_work_items(" src/probos/**
FOUND: 36 matches / 17 files. Non-"open" callers filter by parent_id,
       assigned_to, project_id or children — none counts an open board.
HOLDS: yes

CLAIM: the "task" work type has no open -> done transition
RUN:   read src/probos/workforce.py:167-186 (full valid_transitions list)
FOUND: open->in_progress, open->cancelled, open->blocked, in_progress->done,
       in_progress->failed, in_progress->cancelled, in_progress->blocked,
       blocked->in_progress, blocked->cancelled
HOLDS: yes — "done" is reachable only from in_progress
```
