# AD-500: DutyScheduleTracker → WorkItem Migration

**Status:** Drafted (Wave 10)
**Risk:** HIGH (breaking change to proactive loop)
**Depends on:** AD-496 (WorkItemStore — COMPLETE), AD-498 (Work Type Registry — COMPLETE)
**Closes:** GitHub issue #87

---

## Solution Overview

DutyScheduleTracker currently fires duties via the proactive loop's `_think_for_agent()` directly. After AD-498, the canonical surface for scheduled work is the `duty` work type with state machine + booking lifecycle. Wave 10 migrates DutyScheduleTracker to generate `duty`-typed `WorkItem`s instead of triggering thinks directly.

**v1 ships 3 of 5 capabilities** (per convention #14 aggressive pre-deferral):
1. DutyScheduleTracker generates `WorkItem(type="duty")` from `DutyDefinition` config on schedule.
2. Proactive loop checks for active duty-type WorkItems via `WorkItemStore` instead of calling `get_due_duties()` directly.
3. Booking lifecycle tracks duty execution time and token consumption (via existing AD-498 booking surface).

**Deferred:**
- AD-500b: AD-498 templates for common duty patterns (scout_report, security_audit). v1 ships generic duty WorkItems; templates can be folded in later when patterns crystallize.
- AD-500c: Migration of 7 default duties in `config/system.yaml` to AD-498 templates. v1 keeps the existing `DutyDefinition` config; the WorkItem generation is a thin wrapper. Template migration is a separate refactor.

## Dependencies

- AD-496 (WorkItemStore) — COMPLETE. Used to enqueue duty WorkItems.
- AD-498 (Work Type Registry) — COMPLETE. Provides `duty` work type definition + state machine.
- `src/probos/duty_schedule.py:27` (`class DutyScheduleTracker`) — receives the migration.
- `src/probos/duty_schedule.py:47` (`get_due_duties()`) — DEPRECATED in v1 path; kept as fallback for tests; flagged for AD-500c removal.
- `src/probos/proactive.py` — caller of `get_due_duties()`; switches to `WorkItemStore` poll.
- `src/probos/workforce.py:559` (`class WorkItem`), `:905` (`class WorkItemStore`) — consumed.

**Breaking change to proactive loop.** Test surface is wide; verify-first against existing proactive tests before drafting test plan.

## Sections

### Section 1 — Add `duty` work type to AD-498 registry (if not already)

Verify-first: grep `workforce.py` for any existing `duty` WorkType registration. If absent, register `duty` as a built-in work type with appropriate state machine (analogous to existing types). If present, no-op.

### Section 2 — Extend DutyScheduleTracker to enqueue WorkItems

`DutyScheduleTracker.__init__` receives `runtime` reference (or `work_item_store` directly per dependency injection convention #5).

New method: `async def emit_due_duties_as_work_items(self, agent_type: str) -> list[str]`:
- Calls `get_due_duties(agent_type)` (existing).
- For each `DutyDefinition`, constructs a `WorkItem(type="duty", agent_id=..., payload={...})`.
- Enqueues via `runtime.work_item_store.add(work_item)`.
- Returns list of WorkItem IDs created.
- Emits `DUTY_WORK_ITEM_CREATED` event per item (Section 0).

`get_due_duties()` itself is preserved (used by tests; flagged for AD-500c removal).

### Section 3 — Switch proactive loop to WorkItem poll

In `proactive.py`, find the call site of `get_due_duties()`. Currently fires `_think_for_agent()` directly. Switch to:

1. Call `tracker.emit_due_duties_as_work_items(agent_type)` (instead of `get_due_duties()`).
2. Poll `runtime.work_item_store.list_work_items(work_type="duty", assigned_to=agent_id, status="pending", limit=...)` for active duty WorkItems. (Verify `list_work_items` signature at `workforce.py:1066-1076` — supports `status`/`assigned_to`/`work_type`/`limit` filters.)
3. For each duty WorkItem: open booking, call `_think_for_agent()`, close booking.

Verify-first: read `proactive.py` to find the exact call site + surrounding loop structure. Confirm the booking lifecycle methods used (`start_booking` at `workforce.py:1371`, `complete_booking` at `:1424`).

### Section 4 — Section 0 EventTypes

- `DUTY_WORK_ITEM_CREATED` (new) — emitted when DutyScheduleTracker enqueues a duty WorkItem.

Verify no collision with existing events.py (post-Wave 9 — should have no `DUTY_*` events yet but grep to confirm).

### Section 5 — Config: `DutyConfig.use_work_items` toggle (transitional)

Add a Pydantic config flag `DutyConfig.use_work_items: bool = True` (default True; new behavior). Setting `False` reverts to direct `_think_for_agent()` path.

This is the transitional escape hatch per Wave 5 convention #3 (coordinator-then-dispatch). Tests can opt out; if a v1 user hits an issue, they can revert without code changes. The flag is removable in AD-500c once the WorkItem path is proven stable.

## What This Does NOT Change

- 7 default duties in `config/system.yaml` — preserved as `DutyDefinition` entries; AD-500c migrates to AD-498 templates.
- AD-498 template patterns for common duties (scout_report, security_audit) — deferred to AD-500b.
- `get_due_duties()` — kept as-is (used by tests + opt-out path); removed in AD-500c.
- Booking lifecycle — uses existing AD-498 surface; no new APIs.
- `_think_for_agent()` itself — only its caller changes.

## Test Plan

| # | Test | Purpose |
|---|---|---|
| 1 | `test_duty_work_type_registered` | `runtime.workforce.get_work_type("duty")` returns a definition |
| 2 | `test_emit_due_duties_creates_work_items` | DutyScheduleTracker enqueues WorkItems for each due duty |
| 3 | `test_emit_due_duties_emits_event` | `DUTY_WORK_ITEM_CREATED` fires per item |
| 4 | `test_emit_due_duties_returns_ids` | Method returns list of WorkItem IDs created |
| 5 | `test_proactive_loop_polls_work_item_store` | Mock `work_item_store.list_work_items` is called with `work_type="duty"`, `status="pending"`, `assigned_to=agent_id` |
| 6 | `test_proactive_loop_opens_booking_per_duty` | Each duty WorkItem opens a booking |
| 7 | `test_proactive_loop_closes_booking_after_think` | Booking closes after `_think_for_agent` completes |
| 8 | `test_proactive_loop_closes_booking_on_exception` | Booking closes even when think raises |
| 9 | `test_use_work_items_false_reverts_to_legacy` | Setting `DutyConfig.use_work_items=False` calls `_think_for_agent` directly |
| 10 | `test_no_dual_dispatch` | When `use_work_items=True`, NO direct `_think_for_agent` call from the legacy path |
| 11 | `test_existing_get_due_duties_preserved` | `get_due_duties()` still callable for tests |
| 12 | `test_default_7_duties_emit_work_items` | Each of 7 default duties from `config/system.yaml` produces a WorkItem |

Total: ~12 new tests.

Plus regression check on existing duty/proactive tests — must remain green.

## Tracking

1. **PROGRESS.md:** prepend AD-500 entry.
2. **DECISIONS.md:** add entry under Era V:

```markdown
### AD-500: DutyScheduleTracker → WorkItem Migration (2026-05-03)

**Problem:** DutyScheduleTracker fires duties via direct `_think_for_agent()` calls, bypassing the AD-496 WorkItemStore + AD-498 work-type-registry surface that all other scheduled work uses. Two parallel tracking surfaces lead to inconsistency in observability, booking lifecycle, and token cost attribution.

**Decision:** Migrate DutyScheduleTracker to enqueue `WorkItem(type="duty")` items via `runtime.work_item_store.create_work_item(...)`. Proactive loop polls `WorkItemStore.list_work_items(work_type="duty", status="pending", assigned_to=agent_id)` and opens AD-498 bookings around each `_think_for_agent()` call. Provide `DutyConfig.use_work_items: bool = True` transitional flag (per Wave 5 coordinator-then-dispatch convention #3); flag removable in AD-500c when stable.

**Why:** Single canonical work surface (WorkItemStore + work types) for all scheduled work. Booking lifecycle gives free observability + token cost attribution per duty execution. AD-500c can then migrate the 7 default duty configs to AD-498 templates.

**Breaking change:** Proactive loop call site for duties switches from direct `_think_for_agent` to WorkItem poll. Wide test surface; transitional flag mitigates rollout risk.

**Deferred:**
- AD-500b: AD-498 templates for common duty patterns (scout_report, security_audit).
- AD-500c: 7 default duties in `config/system.yaml` migrated to AD-498 templates; `get_due_duties()` removed; `use_work_items` flag removed.

**Cross-links:** AD-496 (WorkItemStore), AD-498 (Work Type Registry), AD-419 (DutyScheduleTracker), proactive.py.
```

3. **docs/development/roadmap.md:** flip AD-500 status to `partial — v1 ships WorkItem migration + transitional flag; templates and config migration deferred to AD-500b/c`.

## Verified Against Codebase (2026-05-03)

```
grep -n "class DutyScheduleTracker\|get_due_duties\|DutyDefinition" src/probos/duty_schedule.py
  19: class DutyStatus:
  27: class DutyScheduleTracker:
  47: def get_due_duties(self, agent_type: str) -> list[Any]:

grep -n "class WorkType\|class WorkItem\|class WorkItemStore\|def list_work_items\|def create_work_item\|def start_booking\|def complete_booking" src/probos/workforce.py
   97: class WorkTypeTransition:
  106: class WorkTypeDefinition:
  248: class WorkTypeRegistry:
  559: class WorkItem:
  905: class WorkItemStore(EventEmitterMixin):
  992: async def create_work_item(self, **kwargs: Any) -> WorkItem:
 1066: async def list_work_items(self, status, assigned_to, work_type, parent_id, priority, tags, limit, offset)
 1371: async def start_booking(self, booking_id: str) -> Booking | None:
 1424: async def complete_booking(self, booking_id: str, tokens_consumed: int = 0)

Note: there is NO `get_pending` method on WorkItemStore. The pending-duty filter pattern uses
`list_work_items(work_type="duty", status="pending", assigned_to=agent_id)`.

(Builder verifies proactive.py call site of get_due_duties at build time)
```

## Acceptance Criteria

- `DutyScheduleTracker.emit_due_duties_as_work_items()` exists and produces WorkItems.
- Proactive loop polls `WorkItemStore.list_work_items(work_type="duty", status="pending")` instead of `get_due_duties()` (when `use_work_items=True`).
- AD-498 booking opens/closes around each duty `_think_for_agent` call.
- `DUTY_WORK_ITEM_CREATED` EventType added.
- `DutyConfig.use_work_items` config flag exists (default True).
- 12 new tests pass; existing duty/proactive tests green.
- DECISIONS.md entry under Era V.
- GH issue #87 closes when commit lands.

## Hard-Stops (signal to architect)

- Proactive loop's existing duty handling has more state than the dispatch assumes — surface for re-bundling.
- AD-498 doesn't yet have a `duty` work type registered AND adding one requires architectural decisions beyond Section 1 (state machine, transitions) — surface; may need AD-498 extension prompt first.
- Existing tests assume `get_due_duties()` is the only duty entry point and break under WorkItem path even with `use_work_items=False` opt-out — surface; transitional flag may need wider scope.
