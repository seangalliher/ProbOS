# AD-501: TaskTracker Deprecation & NotificationQueue Separation

**Status:** Drafted (Wave 10) — Revised 2026-05-03 per pass-1 review
**Risk:** medium (30 orphaned tests in `tests/test_task_tracker.py`; existing `tests/test_notifications.py` needs 1-line import update)
**Depends on:** AD-496 (`WorkItemStore` — COMPLETE)
**Closes:** GitHub issue #88

---

## Solution Overview

`task_tracker.py` carries two concerns: `NotificationQueue` (live, used) and `TaskTracker` (orphaned — wired into runtime but no code creates tasks through it). Wave 10 cleans this up:

- **v1 ships 4 of 5 capabilities** (per convention #14 aggressive pre-deferral):
  1. Move `NotificationQueue` + `AgentNotification` to new `src/probos/notifications.py` (live code; preserves all behavior).
  2. Deprecate `TaskTracker` class — remove from runtime init, remove from `build_state_snapshot()`.
  3. Update import in EXISTING `tests/test_notifications.py` (1 line at `:7`) and DELETE the entire orphaned `tests/test_task_tracker.py` (30 tests, all targeting orphaned classes).
  4. Update `tests/conftest.py` import + mock path.
- **Deferred to AD-501b:** BuildQueue migration to WorkItems. Roadmap notes "evaluate" — not "implement" — and AD-498 stability for build-modeling is a separate forcing function.

## Dependencies

- AD-496 (WorkItemStore) — COMPLETE. Replaces TaskTracker's role conceptually.
- `runtime.py:69` (`from probos.task_tracker import NotificationQueue, TaskTracker`) — split into two imports.
- `runtime.py:234,543` (`task_tracker: TaskTracker | None`) — remove field.
- `runtime.py:1058` (`build_state_snapshot()` references `task_tracker.snapshot()`) — drop tasks key from snapshot.
- `runtime.py:1526` (`self.task_tracker = struct.task_tracker`) — remove restore line.

## Sections

### Section 1 — Create `src/probos/notifications.py`

Move `NotificationQueue` (`task_tracker.py:177-258`) and `AgentNotification` (`task_tracker.py:149-175`) verbatim. Imports adjusted as needed. Keep `__init__.py` re-exports if any.

### Section 2 — Update imports across codebase

Grep for all `from probos.task_tracker import NotificationQueue` and `from probos.task_tracker import AgentNotification` — change to `from probos.notifications import ...`. Verify-first: count call sites with `grep -rn "from probos.task_tracker"` against BOTH `src/probos/` AND `tests/`.

**Known import sites (verified 2026-05-03):**
- `src/probos/runtime.py:69` — `from probos.task_tracker import NotificationQueue, TaskTracker` (split into `from probos.notifications import NotificationQueue`; drop `TaskTracker`).
- `tests/conftest.py:158` — `from probos.task_tracker import NotificationQueue` → `from probos.notifications import NotificationQueue`.
- `tests/conftest.py:200` — `rt.notification_queue = MagicMock(spec=NotificationQueue)` — symbol reference; works after the import update on `:158`.
- `tests/test_notifications.py:7` — existing file, `from probos.task_tracker import AgentNotification, NotificationQueue` → `from probos.notifications import AgentNotification, NotificationQueue` (1-line edit).
- `tests/test_ad580_alert_feedback.py:258` — `runtime.notification_queue = MagicMock()` — no `NotificationQueue` import; no change needed (listed for grep-completeness).

**No other importers in `src/probos/` or `tests/` per `grep -rn "from probos.task_tracker"` at HEAD.** `src/probos/api.py` does NOT import `task_tracker` (verified — no matches).

### Section 3 — Remove TaskTracker from runtime.py

- Line 69: `from probos.task_tracker import NotificationQueue, TaskTracker` → `from probos.notifications import NotificationQueue`
- Line 234: `task_tracker: TaskTracker | None` → remove field from frozen dataclass
- Line 237: `notification_queue: NotificationQueue` field STAYS — only the import on line 69 changes the resolved type. Field declaration unaffected.
- Line 543: `self.task_tracker: TaskTracker | None = None` → remove
- Line 1058: `"tasks": self.task_tracker.snapshot() if self.task_tracker else []` → remove key from `build_state_snapshot` dict
- Line 1526: `self.task_tracker = struct.task_tracker` → remove restore line

### Section 4 — Delete `src/probos/task_tracker.py`

After Sections 1-3, the file is reduced to `TaskType`/`StepStatus`/`TaskStatus`/`TaskStep`/`AgentTask`/`TaskTracker` — all orphaned. Verify no remaining importers via grep, then delete the file.

### Section 5 — Test triage

**Verified-first triage (2026-05-03):** `pytest tests/test_task_tracker.py --collect-only -q` returns **30 tests collected**, all under three orphan-class test classes:
- `TestTaskStep` (5 tests) — orphaned `TaskStep` dataclass.
- `TestAgentTask` (9 tests) — orphaned `AgentTask` dataclass.
- `TestTaskTracker` (16 tests) — orphaned `TaskTracker` class.

**ZERO notification tests live in `test_task_tracker.py`.** All notification coverage already lives in EXISTING `tests/test_notifications.py` (12 tests under `TestAgentNotification` and `TestNotificationQueue`).

**Action — binary, not graded:**
1. **Augment EXISTING `tests/test_notifications.py`:** update line 7 import only (`from probos.task_tracker` → `from probos.notifications`). Keep all 12 existing tests verbatim.
2. **DELETE entire `tests/test_task_tracker.py`** (all 30 tests are orphan-class structural tests with no live counterpart).
3. **Add ~8 new tests** per the Test Plan below (covering migration invariants).

**Net delta to total test count: `+8 new − 30 deleted = −22`.** The full pytest gate count drops by 22 from this prompt; do NOT mistake this for a regression.

### Section 6 — Update `routers/` and `api.py` if any

Verify-first grep against `src/probos/api.py` AND `src/probos/routers/**`. As of 2026-05-03 HEAD:
- `src/probos/api.py` — **0 hits** for `task_tracker` / `TaskTracker`. No change needed.
- `src/probos/routers/**` — 13 hits, ALL referring to the FastAPI dep `get_task_tracker` (defined at `routers/deps.py:23`) which injects `app.state.track_task` (a background-task callable). **This is unrelated to the `TaskTracker` class being deprecated** — naming overlap only. **DO NOT touch routers/**.

See "What This Does NOT Change" below for the explicit guard.

## What This Does NOT Change

- WorkItemStore (AD-496) — already shipped, untouched.
- Notification semantics — move-only; behavior preserved.
- BuildQueue migration to WorkItems — deferred to AD-501b.
- Proactive loop's interaction with notifications (currently via NotificationQueue) — preserved as-is.
- **`routers/deps.py:23 get_task_tracker` and downstream `track_task: Callable = Depends(get_task_tracker)` references in `routers/{design,chat,build,system}.py`** — UNRELATED naming overlap. These inject `app.state.track_task` (a FastAPI background-task callable), NOT the `TaskTracker` class. Do not touch.

## Test Plan

| # | Test | Purpose |
|---|---|---|
| 1 | `test_notifications_module_exists` | Import `from probos.notifications import NotificationQueue, AgentNotification` succeeds |
| 2 | `test_notification_queue_enqueue_dequeue` | Behavior preserved post-move |
| 3 | `test_notification_queue_priority_ordering` | (existing test, moved) |
| 4 | `test_agent_notification_dataclass_fields` | Frozen-dataclass contract preserved |
| 5 | `test_runtime_no_task_tracker_attribute` | `hasattr(runtime, "task_tracker")` is False |
| 6 | `test_build_state_snapshot_no_tasks_key` | `"tasks" not in runtime.build_state_snapshot()` |
| 7 | `test_task_tracker_module_deleted` | `import probos.task_tracker` raises `ModuleNotFoundError` (subclass of `ImportError`; assert the more specific class) |
| 8 | `test_existing_notification_consumers_unbroken` | Find one consumer site (e.g., `proactive.py`) and assert it still works |

**Existing `tests/test_notifications.py` retains all 12 tests** (1-line import update only; no test additions/removals).

**Total net:** 8 new tests + 12 retained-in-place + 30 deleted = **−22 tests** in the full pytest gate after this prompt.

## Tracking

1. **PROGRESS.md:** prepend AD-501 entry.
2. **DECISIONS.md:** add entry under Era V:

```markdown
### AD-501: TaskTracker Deprecation & NotificationQueue Separation (2026-05-03)

**Problem:** `task_tracker.py` carried two unrelated concerns. `NotificationQueue` is live and used by the proactive loop; `TaskTracker` is wired into runtime but no code path creates tasks through it. WorkItemStore (AD-496) is the canonical work-tracking surface now.

**Decision:** Split `task_tracker.py`:
- Move `NotificationQueue` + `AgentNotification` to new `src/probos/notifications.py` (move-only; no behavior change).
- Delete `task_tracker.py` (orphaned `TaskType`/`StepStatus`/`TaskStatus`/`TaskStep`/`AgentTask`/`TaskTracker` removed).
- Remove `runtime.task_tracker` field and `build_state_snapshot()` `"tasks"` key.
- Update existing `tests/test_notifications.py` import (1 line); delete entire orphaned `tests/test_task_tracker.py` (30 tests, all targeting orphan classes).

**Why:** AD-496 WorkItemStore is the canonical work surface. TaskTracker's continued presence is technical debt that confuses Builder agents about the canonical work model.

**Deferred:** BuildQueue migration to WorkItems → AD-501b. Roadmap says "evaluate" not "implement"; AD-498 stability for build-modeling is a separate forcing function.

**Cross-links:** AD-323 (origin of `AgentNotification`), AD-496 (WorkItemStore), AD-498 (Work Type Registry).
```

3. **docs/development/roadmap.md:** flip AD-501 status to `partial — v1 ships notification separation + TaskTracker deletion; BuildQueue migration deferred to AD-501b`.

## Verified Against Codebase (2026-05-03, post-revision)

```
grep -n "class NotificationQueue\|class AgentNotification\|class TaskTracker" src/probos/task_tracker.py
  149: class AgentNotification:
  177: class NotificationQueue:
  260: class TaskTracker:

grep -n "task_tracker\|TaskTracker\|notification_queue" src/probos/runtime.py
   69: from probos.task_tracker import NotificationQueue, TaskTracker
  234: task_tracker: TaskTracker | None
  237: notification_queue: NotificationQueue       # field stays; type resolves via new import
  543: self.task_tracker: TaskTracker | None = None
 1058: "tasks": self.task_tracker.snapshot() if self.task_tracker else [],
 1526: self.task_tracker = struct.task_tracker

grep -rn "from probos.task_tracker" src/ tests/
  src/probos/runtime.py:69
  tests/conftest.py:158
  tests/test_notifications.py:7    (existing — 1-line update)
  tests/test_task_tracker.py       (file DELETED entirely)

grep -n "NotificationQueue" tests/conftest.py
  158: from probos.task_tracker import NotificationQueue
  200: rt.notification_queue = MagicMock(spec=NotificationQueue)

pytest tests/test_task_tracker.py --collect-only -q
  30 tests collected (all under TestTaskStep / TestAgentTask / TestTaskTracker — all orphan classes)

pytest tests/test_notifications.py --collect-only -q
  12 tests collected (TestAgentNotification + TestNotificationQueue — already exist; live target for the migration)

grep -n "task_tracker\|TaskTracker" src/probos/api.py
  (no matches — file exists but does not reference task_tracker)

grep -rn "task_tracker\|TaskTracker" src/probos/routers/
  13 matches — ALL references to FastAPI dep `get_task_tracker` (routers/deps.py:23 injects
  `app.state.track_task` callable). UNRELATED to the `TaskTracker` class being deprecated.
```

## Acceptance Criteria

- `src/probos/notifications.py` exists with NotificationQueue + AgentNotification.
- `src/probos/task_tracker.py` deleted.
- `runtime.py` has no `task_tracker` references; `build_state_snapshot()` has no `"tasks"` key.
- `tests/conftest.py:158` import updated; `tests/test_notifications.py:7` import updated; `tests/test_task_tracker.py` deleted entirely.
- `src/probos/routers/**` UNTOUCHED (the `get_task_tracker` FastAPI dep is unrelated).
- 8 new tests pass; 12 existing notification tests still pass; 30 orphan tests removed (full gate net delta: −22).
- DECISIONS.md entry under Era V.
- GH issue #88 closes when commit lands.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Revision (2026-05-03)

Applies all 5 Required + 3 Recommended + 2 Nit findings from `prompts/Reviews/ad-501-tasktracker-deprecation-review.md` (pass-1 verdict ⚠️ Conditional).

**Required findings resolved:**
1. **Test count 32 → 30.** Front-matter Risk line, Solution Overview, Section 5, Test Plan total, Acceptance Criteria, and verify-first footer all updated. `pytest tests/test_task_tracker.py --collect-only -q` confirmed 30 tests.
2. **`tests/test_notifications.py` already exists.** Section 5 reframed from "create new file / move tests" to "augment existing file with 1-line import update at line 7; keep all 12 existing tests verbatim". Section 2 lists the explicit edit.
3. **Zero notification tests in `test_task_tracker.py`.** Section 5 reframed to binary "DELETE the entire file". Net delta now stated as `+8 new − 30 deleted = −22` (was misleading `+18 to +23`).
4. **`tests/conftest.py:158, :200` enumerated.** Section 2 lists both lines explicitly under "Known import sites".
5. **`api.py` and `routers/` clarification.** Section 6 retitled "Update `routers/` and `api.py` if any"; documents that `api.py` has 0 hits and that the 13 `routers/` hits are all the unrelated FastAPI dep `get_task_tracker`. "What This Does NOT Change" gains an explicit guard against touching routers/.

**Recommended findings resolved:**
1. `runtime.py:237` `notification_queue: NotificationQueue` field declaration explicitly noted in Section 3 as "field stays; only the import on line 69 changes".
2. Section 6 reframed to grep `routers/**` with documented evidence (13 hits, all unrelated).
3. `tests/test_ad580_alert_feedback.py:258` listed in Section 2 grep audit (no change needed; included for completeness).

**Nit findings resolved:**
1. AD-323 cross-link added to DECISIONS.md template.
2. Test 7 specified as `pytest.raises(ModuleNotFoundError)` (subclass of `ImportError`; more specific assertion).

**Closing self-check (per Wave 9 closing self-check convention):**
- `grep -i "32 tests\|create new src/probos/notifications.py\|create.*test_notifications.py"` against shipping content of this prompt — 0 hits.
- Solution Overview / Section 5 / Test Plan / Acceptance Criteria are mutually consistent on the −22 net delta.
- No phantom APIs introduced (all line numbers and class names regrep-confirmed at HEAD).
