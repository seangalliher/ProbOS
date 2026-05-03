# Review: AD-501 — TaskTracker Deprecation & NotificationQueue Separation

**Verdict:** ⚠️ Conditional
**One-line headline.** Migration mechanics for runtime.py and task_tracker.py are accurate; test-triage scope is materially wrong (test_notifications.py already exists, test_task_tracker.py contains zero notification tests, count is 30 not 32).

---

## Required (must fix before building)

1. **Test count: 30, not 32.** `pytest tests/test_task_tracker.py --collect-only -q` reports `30 tests collected`. Prompt's verify-first footer claims 32; Solution Overview, Section 5, and Acceptance Criteria all reference 32. Update all four call sites to 30.

2. **`tests/test_notifications.py` ALREADY EXISTS.** Section 5 says "NotificationQueue/AgentNotification tests — move to `tests/test_notifications.py`, update imports, keep all assertions" — but the file already exists at HEAD with 12 notification tests (`test_to_dict`, `test_notify_creates_notification`, ..., `test_acknowledge_emits_ack_event`) importing `from probos.task_tracker import AgentNotification, NotificationQueue`. The actual work is a one-line import update at `tests/test_notifications.py:7`, not a move. Re-frame Section 5.

3. **`tests/test_task_tracker.py` contains ZERO notification tests.** All 30 collected tests live under `TestTaskStep` (5), `TestAgentTask` (9), `TestTaskTracker` (16) — every one tests an orphaned class. Section 5's "three categories" framing implies a triage; the real triage is binary: delete the entire file. Update Section 5 + Test Plan total: target is `~12 retained in existing test_notifications.py + ~8 new = ~20 total`, but **net delta is `+8 new − 30 deleted = −22`** (the prompt currently implies +18 to +23 net new, which is wrong by ~40 tests and would mask the deletion in the test count gate).

4. **`conftest.py:158, 200` import path not covered in prompt.** `tests/conftest.py:158` has `from probos.task_tracker import NotificationQueue` and `:200` has `rt.notification_queue = MagicMock(spec=NotificationQueue)`. Section 2 ("Update imports across codebase") covers this in principle but the conftest path is not enumerated in the verify-first footer — Builder may grep `src/` only and miss `tests/`. Add `tests/conftest.py` to Section 2 explicitly.

5. **`api.py` reference is stale; routers/get_task_tracker is unrelated.** Section 6 says "Update api.py if any" — `src/probos/api.py` does not exist; the API surface lives in `src/probos/routers/`. **More importantly:** `routers/deps.py:23` has `def get_task_tracker(request) -> Callable` injecting `app.state.track_task` (a background-task callable). This is **NOT** the `TaskTracker` class being deprecated — naming overlap only. Builder may misread and remove the FastAPI dep. Add an explicit "What This Does NOT Change" bullet: "`routers/deps.py:23 get_task_tracker` and downstream `track_task: Callable = Depends(get_task_tracker)` in routers/{design,chat,build,system}.py — unrelated naming; injects `app.state.track_task` (background-task callable), not `TaskTracker` class."

## Recommended

1. **`runtime.py:237` field declaration** (`notification_queue: NotificationQueue` in `_RuntimeStruct` frozen dataclass) is impacted by the import change on line 69 but the field stays. Verify-first footer lists 69/234/543/1058/1526 but misses 237. Add explicit note in Section 3: "Line 237 `notification_queue: NotificationQueue` field stays; only the import on line 69 changes."

2. **Section 6 should be "Update routers/ if any" + grep-evidence** rather than "Update api.py if any". The grep `from probos.task_tracker` should be run against `src/probos/routers/**` and the result documented in the footer.

3. **`tests/test_ad580_alert_feedback.py:258` references `runtime.notification_queue = MagicMock()`** — works without changes (no import of NotificationQueue type), but worth listing in Section 2's grep audit so the count is exhaustive.

## Nits

- Cross-link AD-323 (origin of `AgentNotification` — see `tests/test_notifications.py:1` docstring) in DECISIONS.md entry "Cross-links" line for lineage.
- Test 7 (`test_task_tracker_module_deleted`) is brittle: `pytest.raises(ImportError)` on `import probos.task_tracker`. Add `with pytest.raises(ModuleNotFoundError)` for specificity (subclass of ImportError, but more precise on cause).

## Verified

- `task_tracker.py:149,177,260` (AgentNotification / NotificationQueue / TaskTracker class lines) confirmed exact.
- `runtime.py:69,234,543,1058,1526` confirmed exact for task_tracker references.
- `runtime.py:237,552` carry NotificationQueue field declaration + `__init__` instantiation — preserved across migration.
- TaskType / StepStatus / TaskStatus / TaskStep / AgentTask in `task_tracker.py:14/22/29/38/69` are the orphaned siblings deleted alongside TaskTracker.
- No EventType collision (AD-501 introduces no new EventTypes).
- WorkItemStore (AD-496) is the canonical replacement surface; TaskTracker has no live caller — confirmed via `grep self.task_tracker` returns only the runtime field, snapshot read, and warm-boot restore (all 3 lines flagged for removal).
- Hard-stop #3 (NotificationQueue hidden state on TaskTracker) is **not triggered**: NotificationQueue is fully self-contained (`task_tracker.py:177-258`), no shared `_lock`, `_registry`, or composition with TaskTracker. Clean separation is structurally safe.
- Hard-stop #4 (cross-prompt source-file conflict on `runtime.py`): AD-501 modifies lines 69/234/543/1058/1526; AD-500 modifies `proactive.py` and adds new code to `config.py`/`workforce.py`/`events.py` — **no conflict on runtime.py** between the two prompts.
