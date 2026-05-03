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


---

## Second-Pass Review (2026-05-03)

**Verdict:** ✅ Approved
**One-line headline.** All 5 Required + 3 Recommended + 2 Nit findings resolved against revised content; verify-first regrep confirms test counts and import paths match HEAD; pre-check clean; zero new findings.

### Resolution Audit — Required

| Pass-1 Required | Status | Evidence in revised prompt |
|---|---|---|
| 1. Test count 30 not 32 | ✅ Resolved | Front-matter L4 ("30 orphaned tests"), Solution Overview bullet 3 ("30 tests"), Section 5 ("30 tests collected"), Test Plan total ("30 deleted = −22"), Acceptance Criteria ("30 orphan tests removed"), verify-first footer ("30 tests collected"). `pytest --collect-only` confirms 30. |
| 2. `test_notifications.py` already exists | ✅ Resolved | Solution Overview bullet 3 ("Update import in EXISTING `tests/test_notifications.py`"), Section 2 explicit edit ("`tests/test_notifications.py:7` — existing file, 1-line edit"), Section 5 ("Augment EXISTING `tests/test_notifications.py`"), Test Plan footer ("Existing `tests/test_notifications.py` retains all 12 tests"). |
| 3. Zero notification tests in `test_task_tracker.py` | ✅ Resolved | Section 5 reframed to binary "DELETE the entire `tests/test_task_tracker.py`"; net delta corrected to `+8 new − 30 deleted = −22` (was misleading +18 to +23). Solution Overview, Test Plan, Acceptance Criteria all consistent. |
| 4. `conftest.py:158, 200` not enumerated | ✅ Resolved | Section 2 "Known import sites" now lists `tests/conftest.py:158` and `:200` explicitly with the symbol-reference note. |
| 5. `api.py` stale + routers/get_task_tracker unrelated | ✅ Resolved | Section 6 retitled "Update `routers/` and `api.py` if any"; documents `api.py` 0 hits and 13 `routers/` hits as unrelated FastAPI dep. "What This Does NOT Change" gains explicit guard against touching `routers/deps.py:23 get_task_tracker`. |

### Resolution Audit — Recommended

| Pass-1 Recommended | Status | Notes |
|---|---|---|
| 1. `runtime.py:237` field declaration note | ✅ Applied | Section 3 line item: "Line 237: `notification_queue: NotificationQueue` field STAYS — only the import on line 69 changes the resolved type." |
| 2. Section 6 routers/ grep evidence | ✅ Applied | Section 6 documents 13 hits with explanation; verify-first footer shows the routers/ grep result. |
| 3. `test_ad580_alert_feedback.py:258` | ✅ Applied | Section 2 lists this site under "Known import sites" with the no-change-needed note. |

### Resolution Audit — Nits

| Pass-1 Nit | Status | Notes |
|---|---|---|
| 1. AD-323 cross-link | ✅ Applied | DECISIONS.md template Cross-links line lists AD-323. |
| 2. Test 7 `ModuleNotFoundError` specificity | ✅ Applied | Test Plan row 7: "raises `ModuleNotFoundError` (subclass of `ImportError`; assert the more specific class)". |

### New Findings (introduced during revision)

None.

### Verified Against Revised Codebase Claims

- `pytest tests/test_task_tracker.py tests/test_notifications.py --collect-only -q` → 42 collected (30 + 12) ✓ matches Section 5 claims.
- `grep -n "class DutyScheduleConfig" src/probos/config.py` → 1397 ✓ (no impact on AD-501 but confirmed in shared workspace state).
- Closing self-check grep `"32 tests|create new src/probos/notifications|create.*test_notifications.py"` against shipping content of revised prompt → 0 hits in shipping sections (only the closing-self-check meta-line itself). ✓
- Phantom-API pre-check (`./scripts/phantom-api-precheck.ps1`) → 0 phantoms detected. ✓

### Convergence

Pass-1 ⚠️ Conditional (5 R / 3 Rec / 2 N) → Pass-2 ✅ Approved (0 R / 0 Rec / 0 N). Convergence achieved. Builder may proceed per dispatch order (AD-501 first).
