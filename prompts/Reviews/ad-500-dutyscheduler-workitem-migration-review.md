# Review: AD-500 — DutyScheduleTracker → WorkItem Migration

**Verdict:** ❌ Not Ready
**One-line headline.** HIGH-risk migration draft has 2 Wave 9B-pattern phantoms (`work_item_store.add` and `DutyConfig`), an unspecified constructor signature change, and 6 unaddressed `record_execution` call sites; the `_think_for_agent` integration model is materially under-specified.

---

## Required (must fix before building)

1. **PHANTOM METHOD: `runtime.work_item_store.add(work_item)`.** Section 2 (Section "Extend DutyScheduleTracker to enqueue WorkItems") says: *"Enqueues via `runtime.work_item_store.add(work_item)`"*. **No `add()` method exists on `WorkItemStore`.** Verified at `workforce.py:992`: `async def create_work_item(self, **kwargs: Any) -> WorkItem`. The DECISIONS.md template at the bottom of the prompt correctly says `create_work_item(...)` — internal inconsistency. **This is a recurrence of the Wave 9B structural-defect pattern (wrong method shape / phantom kwargs)** — convention #21 from Wave 9 retrospective addendum. Builder must call `await runtime.work_item_store.create_work_item(work_type="duty", assigned_to=..., title=..., payload=...)`, not `add(work_item)`. Update Section 2 + verify-first footer.

2. **PHANTOM CLASS: `DutyConfig`.** Section 5, tests #9 and #10, DECISIONS.md template, and Acceptance Criteria all reference `DutyConfig.use_work_items`. **No `DutyConfig` class exists.** Verified at `config.py:1387-1412`: real classes are `DutyDefinition`, `DutyScheduleConfig`, and the field `duty_schedule: DutyScheduleConfig` lives on `ProactiveCognitiveConfig`. The flag belongs on either `DutyScheduleConfig` (most natural) or `ProactiveCognitiveConfig`. Pick one and update all six call sites in the prompt. **This is the second Wave 9B-pattern recurrence in this prompt (wrong class / missing field).**

3. **`DutyScheduleTracker.__init__` signature change unspecified.** Section 2 says "`DutyScheduleTracker.__init__` receives `runtime` reference (or `work_item_store` directly per dependency injection convention #5)." Verified at `duty_schedule.py:35`: current signature is `def __init__(self, schedules: dict[str, list[Any]])`. The constructor must change, and the call site at `proactive.py:398` (`self._duty_tracker = DutyScheduleTracker(config.schedules)`) must change. The prompt does not specify (a) the new exact signature, (b) the updated call site, or (c) which dep is injected (runtime vs work_item_store). Convention #5 is referenced but not applied. Pick `work_item_store: WorkItemStore` as the narrow dep, specify the constructor and update `proactive.py:398`.

4. **6 `record_execution` call sites unaddressed.** `grep "record_execution" src/probos/proactive.py` returns 6 hits at lines 817, 887, 900, 913, 930, 1049 — every response/fallback/finally branch records duty execution. The prompt promises "booking lifecycle tracks duty execution time" but does not say what happens to these 6 call sites. They cannot all silently disappear (loss of duty status snapshot via `get_status()`); they cannot all become `complete_booking(...)` without a booking_id-from-duty resolution mechanism. Specify the migration: either (a) keep `record_execution` calls and additionally call `complete_booking` (dual-write), (b) replace each with `complete_booking(booking_id)` and explain how the booking_id is reachable from `duty` at each call site, or (c) change `_duty_tracker.record_execution` internally to also `complete_booking` when `use_work_items=True`. Builder cannot infer the right answer; this is a hard-stop trigger (#1: existing duty handling has more state than the dispatch assumes).

5. **`_think_for_agent` re-selection ambiguity.** The current flow at `proactive.py:714-715` has `_think_for_agent` itself call `self._duty_tracker.get_due_duties(agent.agent_type)` and pick the highest-priority duty. Section 3 says the proactive loop *outside* `_think_for_agent` will "Poll … active duty WorkItems. For each duty WorkItem: open booking, call `_think_for_agent()`, close booking." Two flows now select the duty, with no shared parameter. Either: (a) `_think_for_agent` learns to accept a `duty: WorkItem | DutyDefinition | None` parameter and skip its own selection, or (b) the prompt specifies that the WorkItem poll happens *inside* `_think_for_agent` (replacing the `get_due_duties` call at :715). Without this clarification, Builder ships a double-select with mismatched `record_execution` keys. Specify the parameter wiring.

6. **Test #10 (`test_no_dual_dispatch`) is structurally untestable as drafted.** The dispatch text says "structural, not a runtime check." But "When `use_work_items=True`, NO direct `_think_for_agent` call from the legacy path" can only be verified by (a) source-AST inspection (fragile, brittle) or (b) call-tracking on a mock (runtime check, contradicting the dispatch). Re-spec test #10: either explicitly mark it as a runtime call-counter test on `_think_for_agent` with `mock.assert_not_called()` on the legacy path, or drop it and rely on tests #5-#9 to cover the same invariant. Current shape will block Builder.

## Recommended

1. **`DUTY_WORK_ITEM_CREATED` is redundant** with existing `WORK_ITEM_CREATED` (events.py:87). The work_type is already on the event payload. Adding a duty-discriminated event is theater unless a specific consumer needs to filter at subscribe-time without payload inspection. Drop the new EventType, or justify in Section 4 with the named consumer. (Note: Section 4 placement — conventionally Section 0 in Wave 9+ per the Section 0 EventTypes convention; rename if kept.)

2. **Section 1 is a no-op.** Verified at `workforce.py:206`: `"duty"` work type is already registered with state machine `scheduled → in_progress (auto_creates_booking) → done/failed/blocked`. Section 1 currently says "register if absent". Change to "VERIFIED: `duty` work type registered at `workforce.py:206`. No work needed in Section 1." This removes a phantom build step.

3. **`use_work_items` default value.** Currently default `True` = breaking change in same commit. Convention #14 (aggressive pre-deferral) and convention #3 (coordinator-then-dispatch transitional flag) suggest `False` default in v1, flip to `True` in AD-500c after observation. Re-evaluate the rollout posture.

4. **Test #12 (`test_default_7_duties_emit_work_items`)** loads `config/system.yaml` to enumerate the 7 duties — fixture cost is large and tightly couples the unit test to ops config. Reframe as a `parametrize` over a synthetic 7-duty schedules dict, or move to an integration test under `tests/integration/`.

5. **Hard-stop #5 (proactive.py call site more entangled than assumed) IS triggered.** Findings #4 and #5 above each independently surface this. Recommend: re-frame v1 scope to "Section 2 only — DutyScheduleTracker emits WorkItems on a NEW method, NO change to proactive.py call site". Defer the proactive loop migration to AD-500a-1 once the WorkItem-emit surface is exercised by tests. Reduces breaking-change risk to zero in v1.

## Nits

- Verify-first footer says `def list_work_items(status, assigned_to, work_type, parent_id, priority, tags, limit, offset)` — confirmed at `workforce.py:1066-1076`. ✅
- Acceptance Criteria third bullet: "AD-498 booking opens/closes around each duty `_think_for_agent` call" — depends on Required #5 resolution.
- "DutyDefinition" entries in `config/system.yaml` — verified at `config.py:1387` as `class DutyDefinition(BaseModel)`. The 7 default duties are deferred to AD-500c per Solution Overview. ✅

## Verified

- **Cross-AD dependency on AD-498 SATISFIED.** `duty` WorkType registered at `workforce.py:206-225` with appropriate state machine (`scheduled → in_progress` auto-creates booking, terminal `done/failed`). No AD-498 extension needed; Section 1 is a no-op (see Recommended #2). Hard-stop #2 NOT triggered.
- `workforce.py:559` `class WorkItem`, `:905` `class WorkItemStore`, `:992` `create_work_item`, `:1066-1076` `list_work_items(status, assigned_to, work_type, ..., limit, offset)`, `:1371` `start_booking`, `:1424` `complete_booking` — all confirmed.
- `proactive.py:32` import, `:181` `_duty_tracker` field, `:395-398` `set_duty_schedule`, `:714-715` `get_due_duties` call, `:703` `_think_for_agent` definition — confirmed.
- `duty_schedule.py:27` `class DutyScheduleTracker`, `:35` `__init__(schedules)`, `:47` `get_due_duties`, `:88` `record_execution` — confirmed.
- **EventType collision check CLEAN.** `grep "DUTY" src/probos/events.py` returns zero `DUTY_*` events. `WORK_ITEM_CREATED/UPDATED/STATUS_CHANGED/ASSIGNED/CLAIMED` exist at `events.py:87-91`. No collision risk for `DUTY_WORK_ITEM_CREATED` (but see Recommended #1 for redundancy concern).
- `config.py:1397` `class DutyScheduleConfig`, `:1412` `duty_schedule: DutyScheduleConfig = DutyScheduleConfig()` on `ProactiveCognitiveConfig` — confirmed. `DutyConfig` (per Required #2) does NOT exist.
- Hard-stop #1 (proactive loop entanglement) IS TRIGGERED (Required #4 + #5). Surfaced for re-spec.
- Cross-prompt source-file conflict (Hard-stop #4): AD-500 modifies `proactive.py`, `duty_schedule.py`, `config.py`, `workforce.py` (Section 1 no-op), `events.py` (per Recommended #1, may be dropped). AD-501 modifies `runtime.py`, deletes `task_tracker.py`. **No file overlap.** Sequencing is safe.
