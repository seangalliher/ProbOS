# AD-501: TaskTracker Deprecation & NotificationQueue Separation

**Status:** Drafted (Wave 10)
**Risk:** medium (32 existing tests touch TaskTracker; require triage)
**Depends on:** AD-496 (`WorkItemStore` — COMPLETE)
**Closes:** GitHub issue #88

---

## Solution Overview

`task_tracker.py` carries two concerns: `NotificationQueue` (live, used) and `TaskTracker` (orphaned — wired into runtime but no code creates tasks through it). Wave 10 cleans this up:

- **v1 ships 4 of 5 capabilities** (per convention #14 aggressive pre-deferral):
  1. Move `NotificationQueue` + `AgentNotification` to new `src/probos/notifications.py` (live code; preserves all behavior).
  2. Deprecate `TaskTracker` class — remove from runtime init, remove from `build_state_snapshot()`.
  3. Triage 32 tests in `tests/test_task_tracker.py` — keep notification tests (renamed/moved); remove orphaned task-tracker tests.
  4. Update any `api.py` references.
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

Grep for all `from probos.task_tracker import NotificationQueue` and `from probos.task_tracker import AgentNotification` — change to `from probos.notifications import ...`. Verify-first: count call sites with `grep -rn "from probos.task_tracker"`.

### Section 3 — Remove TaskTracker from runtime.py

- Line 69: `from probos.task_tracker import NotificationQueue, TaskTracker` → `from probos.notifications import NotificationQueue`
- Line 234: `task_tracker: TaskTracker | None` → remove field from frozen dataclass
- Line 543: `self.task_tracker: TaskTracker | None = None` → remove
- Line 1058: `"tasks": self.task_tracker.snapshot() if self.task_tracker else []` → remove key from `build_state_snapshot` dict
- Line 1526: `self.task_tracker = struct.task_tracker` → remove restore line

### Section 4 — Delete `src/probos/task_tracker.py`

After Sections 1-3, the file is reduced to `TaskType`/`StepStatus`/`TaskStatus`/`TaskStep`/`AgentTask`/`TaskTracker` — all orphaned. Verify no remaining importers via grep, then delete the file.

### Section 5 — Test triage

`tests/test_task_tracker.py` (~32 tests). Three categories:
- **NotificationQueue/AgentNotification tests** — move to `tests/test_notifications.py`, update imports, keep all assertions.
- **TaskTracker structural tests** — delete (test orphaned class).
- **Integration tests with runtime.task_tracker** — delete or refactor to use WorkItemStore (decide per-test).

Verify-first: run `pytest tests/test_task_tracker.py --collect-only -q` to enumerate test names before triage.

### Section 6 — Update `api.py` if any

Grep `src/probos/api.py` for `task_tracker` / `TaskTracker` references. Remove or redirect.

## What This Does NOT Change

- WorkItemStore (AD-496) — already shipped, untouched.
- Notification semantics — move-only; behavior preserved.
- BuildQueue migration to WorkItems — deferred to AD-501b.
- Proactive loop's interaction with notifications (currently via NotificationQueue) — preserved as-is.

## Test Plan

| # | Test | Purpose |
|---|---|---|
| 1 | `test_notifications_module_exists` | Import `from probos.notifications import NotificationQueue, AgentNotification` succeeds |
| 2 | `test_notification_queue_enqueue_dequeue` | Behavior preserved post-move |
| 3 | `test_notification_queue_priority_ordering` | (existing test, moved) |
| 4 | `test_agent_notification_dataclass_fields` | Frozen-dataclass contract preserved |
| 5 | `test_runtime_no_task_tracker_attribute` | `hasattr(runtime, "task_tracker")` is False |
| 6 | `test_build_state_snapshot_no_tasks_key` | `"tasks" not in runtime.build_state_snapshot()` |
| 7 | `test_task_tracker_module_deleted` | `import probos.task_tracker` raises ImportError |
| 8 | `test_existing_notification_consumers_unbroken` | Find one consumer site (e.g., `proactive.py`) and assert it still works |

Plus the moved/renamed tests from `test_task_tracker.py` (NotificationQueue tests retained).

Total: ~8 new + ~10-15 retained from triage = ~18-23 tests.

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
- Triage 32 tests: keep notification tests in new `tests/test_notifications.py`; delete orphaned task-tracker tests.

**Why:** AD-496 WorkItemStore is the canonical work surface. TaskTracker's continued presence is technical debt that confuses Builder agents about the canonical work model.

**Deferred:** BuildQueue migration to WorkItems → AD-501b. Roadmap says "evaluate" not "implement"; AD-498 stability for build-modeling is a separate forcing function.

**Cross-links:** AD-496 (WorkItemStore), AD-498 (Work Type Registry).
```

3. **docs/development/roadmap.md:** flip AD-501 status to `partial — v1 ships notification separation + TaskTracker deletion; BuildQueue migration deferred to AD-501b`.

## Verified Against Codebase (2026-05-03)

```
grep -n "class NotificationQueue\|class AgentNotification\|class TaskTracker" src/probos/task_tracker.py
  149: class AgentNotification:
  177: class NotificationQueue:
  260: class TaskTracker:

grep -n "task_tracker\|TaskTracker" src/probos/runtime.py
   69: from probos.task_tracker import NotificationQueue, TaskTracker
  234: task_tracker: TaskTracker | None
  543: self.task_tracker: TaskTracker | None = None
 1058: "tasks": self.task_tracker.snapshot() if self.task_tracker else [],
 1526: self.task_tracker = struct.task_tracker

grep -rn "from probos.task_tracker" src/  (Builder verifies count + sites at build time)
```

## Acceptance Criteria

- `src/probos/notifications.py` exists with NotificationQueue + AgentNotification.
- `src/probos/task_tracker.py` deleted.
- `runtime.py` has no `task_tracker` references; `build_state_snapshot()` has no `"tasks"` key.
- All importers updated; full pytest gate green.
- ~18-23 tests pass (mix of new + retained-from-triage).
- DECISIONS.md entry under Era V.
- GH issue #88 closes when commit lands.
