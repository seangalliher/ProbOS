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


---

## Second-Pass Review (2026-05-03)

**Verdict:** ✅ Approved
**One-line headline.** Scope reframe to producer-only is structurally clean and consistent across all shipping sections; all 6 Required + 5 Recommended findings resolved; pre-check clean; one minor finding (`metadata` vs `payload` in Section 2 example) is non-blocking because the prompt has a verify-at-build-time note.

### Resolution Audit — Required

| Pass-1 Required | Status | Evidence in revised prompt |
|---|---|---|
| 1. Phantom `runtime.work_item_store.add(work_item)` | ✅ Resolved | Section 2 code block uses `await work_item_store.create_work_item(work_type="duty", ...)`. Verify-first footer confirms `workforce.py:992 async def create_work_item(self, **kwargs)`. Pre-check 0 phantoms. |
| 2. Phantom class `DutyConfig` | ✅ Resolved | Section 3 uses `DutyScheduleConfig` (config.py:1397, regrep-confirmed). Solution Overview, Dependencies, Test row 6, Acceptance Criteria, DECISIONS.md template all consistent. |
| 3. `DutyScheduleTracker.__init__` signature change unspecified | ✅ Resolved via reframe | Constructor signature **unchanged in v1**; dependency injected at call time per convention #5. Section 2 explicit. Constructor migration deferred to AD-500a-1. |
| 4. 6 `record_execution` call sites unaddressed | ✅ Resolved via reframe | All 6 sites at `proactive.py:817/887/900/913/930/1050` explicitly untouched in v1. AD-500a-1 forcing function requires individual mapping before consumer ships. "What This Does NOT Change" lists all 6 lines. |
| 5. `_think_for_agent` re-selection ambiguity | ✅ Resolved via reframe | `_think_for_agent` untouched in v1 (line 703 listed under untouched). AD-500a-1 forcing function requires written specification of parameter-vs-internal-replace before it ships. |
| 6. Test #10 (`no_dual_dispatch`) untestable | ✅ Resolved via reframe | Test dropped (no consumer in v1, no dual-dispatch concern). Test Plan total now 6 (was 12). Invariant moves to AD-500a-1's test plan. |

### Resolution Audit — Recommended

| Pass-1 Recommended | Status | Notes |
|---|---|---|
| 1. `DUTY_WORK_ITEM_CREATED` redundant | ✅ Applied | Section 4 reframed as "Reuse existing `WORK_ITEM_CREATED` (no new events)". No new EventType. Acceptance Criteria explicit: "No new EventType added". |
| 2. Section 1 no-op | ✅ Applied | Section 1 now reads "VERIFIED 2026-05-03: `duty` work type registered at `workforce.py:206-225`. No implementation needed." |
| 3. `use_work_items` default value | ✅ Applied | `use_work_items: bool = False` in Section 3 + DECISIONS.md template ("Why default `False`"). Convention #14 + transitional-flag discipline cited. |
| 4. Test #12 fixture coupling | 📦 Deferred | N/A in v1 — test dropped along with consumer-side scope. Recommendation will move to AD-500a-1 if surfaced there (Revision section explicitly notes this). |
| 5. Hard-stop #5 — full scope reframe | ✅ Applied | Entire scope reframe IS this finding's resolution. v1 ships 2 of 5 capabilities (down from 3). Risk drops HIGH → medium. |

### New Findings (introduced during revision)

1. **`WorkItem` field name in Section 2 example is `payload=` but HEAD shows `metadata=`** (Recommended-class, non-blocking). At `src/probos/workforce.py:583`, `WorkItem` uses `metadata: dict[str, Any] = field(default_factory=dict)`. Section 2's code example uses `payload={"duty_id": ..., "agent_type": ...}`. The prompt's Section 2 line 80 already includes the verify-at-build-time note ("read `workforce.py` near `:559` to confirm whether the parameter is `payload` vs `metadata` vs `params`; ... If the field name differs, use the actual one"), which addresses Hard-stop #5 from the user's review brief. **Suggested one-line improvement (not required):** substitute `payload=` → `metadata=` in the Section 2 example to eliminate the Builder round-trip; HEAD confirms the field name. Test row 2 description ("payload containing `duty_id`") would also benefit from the same substitution. This is non-blocking because the verify-at-build-time instruction is structurally sufficient — Builder will not phantom-implement.

### Verified Against Revised Codebase Claims (NEW in revision)

- `grep -n "async def create_work_item" src/probos/workforce.py` → 992 ✓.
- `grep -n "class DutyScheduleConfig" src/probos/config.py` → 1397 ✓.
- `grep -n '"duty":' src/probos/workforce.py` → 206 ✓.
- `grep -n "class WorkItem\b" src/probos/workforce.py` → 559 ✓; field `metadata: dict[str, Any]` at 583.
- Closing self-check grep `"work_item_store.add|DutyConfig\b|DUTY_WORK_ITEM_CREATED|3 of 5 capabilities|no_dual_dispatch|12 new tests"` against shipping content (Solution Overview, Sections 1-4, What This Does NOT Change, Test Plan, Tracking, Acceptance Criteria) → 0 hits. All matches confined to the Revision section / Deferred Grandchildren / DECISIONS.md template / pass-1 review excerpts (audit trail, expected). ✓
- Phantom-API pre-check (`./scripts/phantom-api-precheck.ps1`) → 0 phantoms detected. ✓
- Solution Overview ("v1 ships 2 of 5 capabilities") consistent with v1-deliverables list (2 items: producer + opt-in flag), Test Plan (6 tests), Acceptance Criteria (no consumer-side claims), title and front-matter (producer-side only). No drift detected.

### Scope Reframe Cleanliness

- Title: "DutyScheduleTracker → WorkItem Migration (Producer Side)" ✓
- Front-matter Status: "Revised 2026-05-03 (scope reframe per pass-1 review)" + Risk dropped to medium ✓
- Solution Overview: "v1 ships 2 of 5" ✓
- Section 3 explicitly removes proactive-loop migration; Deferred section adds AD-500a-1 with explicit forcing function ✓
- v1-deliverables / Acceptance Criteria do NOT claim consumer-side migration; multiple "UNTOUCHED in v1" guards on `proactive.py` ✓
- Test Plan: 6 tests (down from 12) ✓
- DECISIONS.md draft block reflects producer-only with reframe rationale ✓
- "What This Does NOT Change" lists all 6 `record_execution` lines, `_think_for_agent`, `set_duty_schedule`, `_duty_tracker` field, `__init__` signature ✓

### Convergence

Pass-1 ❌ Not Ready (6 R / 5 Rec / 3 N) → Pass-2 ✅ Approved (0 R / 1 Rec-class new finding / 0 N). The single new finding (`metadata` vs `payload`) is non-blocking because the prompt's Section 2 verify-at-build-time note structurally prevents the phantom from shipping. Convention #15 relaxed-tolerance reservation for highest-risk + largest-revision is honored but not invoked — the reframe is clean enough for a clean ✅.

Builder may proceed per dispatch order (AD-501 → AD-500). Optional one-line example correction (`payload=` → `metadata=`) recommended but not required.
