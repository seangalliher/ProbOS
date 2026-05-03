# AD-500: DutyScheduleTracker → WorkItem Migration (Producer Side)

**Status:** Drafted (Wave 10) — Revised 2026-05-03 (scope reframe per pass-1 review)
**Risk:** medium (down from HIGH after scope reframe — producer-only ships v1; consumer migration deferred)
**Depends on:** AD-496 (WorkItemStore — COMPLETE), AD-498 (Work Type Registry — COMPLETE; `duty` work type pre-registered at `workforce.py:206`)
**Closes:** GitHub issue #87 (partial — consumer migration tracked under AD-500a-1)

---

## Solution Overview

DutyScheduleTracker currently fires duties via the proactive loop's `_think_for_agent()` directly. After AD-498, the canonical surface for scheduled work is the `duty` work type with state machine + booking lifecycle. Wave 10 begins migrating DutyScheduleTracker to the WorkItem surface — **producer side only**.

**Pass-1 review surfaced Hard-stop #5 (proactive loop entanglement):** 6 unaddressed `record_execution` call sites at `proactive.py:817/887/900/913/930/1050` plus `_think_for_agent` self-selecting the duty at `:715`. The original v1 scope (which moved the proactive loop to a WorkItemStore poll) was structurally under-specified. Per the architect's recommendation (Recommended #5) and Wave 5 convention #3 (coordinator-then-dispatch at the AD-scoping level), v1 is reframed to ship **only the producer**.

**v1 ships 2 of 5 capabilities** (per convention #14 aggressive pre-deferral):
1. **Producer:** `DutyScheduleTracker.emit_due_duties_as_work_items(agent_type, work_item_store)` method emits one `WorkItem(work_type="duty", ...)` per due `DutyDefinition` via `WorkItemStore.create_work_item(...)`. Returns the list of new WorkItem IDs.
2. **Opt-in flag:** `DutyScheduleConfig.use_work_items: bool = False` (default `False` — no behavior change at first commit; AD-500a-1 flips to `True` after consumer migration is validated).

**Deferred:**
- **AD-500a-1 (NEW):** Proactive loop consumer migration. Wires `_think_for_agent` to consume duty WorkItems via `WorkItemStore.list_work_items(work_type="duty", ...)`, opens AD-498 bookings around the call, triages the 6 `record_execution` sites, and flips `DutyScheduleConfig.use_work_items` default to `True`. **Forcing function:** ships when (a) `use_work_items=False` default has been validated in v1 (zero behavior change confirmed), AND (b) the 6 `record_execution` call sites have been mapped to a booking-lifecycle equivalent (either dual-write, internal redirect, or removal). See "Deferred Grandchildren" below.
- **AD-500b:** AD-498 templates for common duty patterns (scout_report, security_audit). v1 ships generic duty WorkItems; templates can be folded in later when patterns crystallize.
- **AD-500c:** Migration of 7 default duties in `config/system.yaml` to AD-498 templates; `get_due_duties()` removed; `use_work_items` flag removed once consumer surface is canonical.

## Dependencies

- AD-496 (WorkItemStore) — COMPLETE. Used to enqueue duty WorkItems via `create_work_item(**kwargs)` at `workforce.py:992`.
- AD-498 (Work Type Registry) — COMPLETE. `duty` work type already registered at `workforce.py:206` with state machine `scheduled → in_progress (auto_creates_booking) → done/failed/blocked`. **Section 1 is verify-only — no implementation needed.**
- `src/probos/duty_schedule.py:27` (`class DutyScheduleTracker`), `:35` (`__init__(schedules)`), `:47` (`get_due_duties()`), `:91` (`record_execution()`) — receives the new method; existing `__init__` signature **unchanged in v1**.
- `src/probos/config.py:1397` (`class DutyScheduleConfig`) — gains `use_work_items` field.
- `src/probos/workforce.py:559` (`class WorkItem`), `:905` (`class WorkItemStore`), `:992` (`create_work_item`) — consumed by the new producer method.

**No proactive.py changes in v1.** Hard-stop #5 risk (proactive loop entanglement) is contained to AD-500a-1.

## Sections

### Section 1 — Verify `duty` work type registration (no-op)

**VERIFIED 2026-05-03:** `duty` work type registered at `src/probos/workforce.py:206-225` with state machine `scheduled → in_progress (auto_creates_booking) → done/failed/blocked`. Builder action: confirm via `grep -n '"duty":' src/probos/workforce.py`. **No implementation needed.** This section exists only to acknowledge the cross-AD dependency on AD-498 is satisfied.

### Section 2 — Add `emit_due_duties_as_work_items` producer to DutyScheduleTracker

In `src/probos/duty_schedule.py`, add a NEW async method to `DutyScheduleTracker`. The constructor signature is **unchanged** in v1 (`def __init__(self, schedules: dict[str, list[Any]])` at `:35` stays as-is). The dependency is injected at call time, narrowly per convention #5:

```python
async def emit_due_duties_as_work_items(
    self,
    agent_type: str,
    work_item_store: "WorkItemStore",
) -> list[str]:
    """Emit one duty WorkItem per due DutyDefinition. Producer side only.

    Returns list of WorkItem IDs created. Does NOT call record_execution
    (that remains on the legacy path until AD-500a-1).
    """
    due = self.get_due_duties(agent_type)  # existing method at :47, untouched
    work_item_ids: list[str] = []
    for duty in due:
        item = await work_item_store.create_work_item(
            work_type="duty",
            assigned_to=agent_type,           # by agent_type per existing duty contract
            title=getattr(duty, "title", duty.duty_id),
            payload={
                "duty_id": duty.duty_id,
                "agent_type": agent_type,
            },
        )
        work_item_ids.append(item.work_item_id)
    return work_item_ids
```

**Type-only forward reference** for `WorkItemStore` (use `from typing import TYPE_CHECKING` guard) to avoid an import cycle with `workforce.py`. Add at module top:

```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from probos.workforce import WorkItemStore
```

**Verify against `WorkItem` payload field name at build time:** read `workforce.py` near `:559` to confirm whether the parameter is `payload` vs `metadata` vs `params`; `create_work_item(**kwargs)` accepts whatever the dataclass takes. If the field name differs, use the actual one.

`get_due_duties()` and `record_execution()` are **NOT** modified in v1. Both keep their existing semantics for the legacy path (proactive.py:715, plus the 6 `record_execution` sites listed in Dependencies).

### Section 3 — `DutyScheduleConfig.use_work_items` opt-in flag (default False)

In `src/probos/config.py:1397` (`class DutyScheduleConfig(BaseModel)`), add:

```python
use_work_items: bool = False  # AD-500: opt-in for duty WorkItem producer; flips to True in AD-500a-1
```

**Default `False`** per convention #14 (aggressive pre-deferral): v1 ships zero behavior change at first commit. Operators who want to exercise the new producer set this to `True` in their config; the proactive loop continues to use the legacy path either way until AD-500a-1 wires the consumer side.

**Note:** the flag is currently observed by NO consumer in v1 (the producer method is opt-in by virtue of being explicitly called from tests / future AD-500a-1 code). The flag's purpose is to give AD-500a-1 a stable config knob to gate consumer-side rollout when it ships. Tests in this AD verify the field exists and defaults correctly.

### Section 4 — Reuse existing `WORK_ITEM_CREATED` EventType (no new events)

The producer's `create_work_item(work_type="duty", ...)` call in Section 2 already emits the existing `EventType.WORK_ITEM_CREATED` event (verified at `events.py:87`) via `WorkItemStore`'s `EventEmitterMixin` parent. The event payload carries `work_type="duty"` so subscribers can filter at consumption time without needing a discriminated marker.

**Per pass-1 review Recommended #1:** the original draft's `DUTY_WORK_ITEM_CREATED` was redundant theater (no named consumer needed subscribe-time discrimination). **Dropped from v1.** If a duty-specific consumer with a subscribe-time filter need emerges in AD-500a-1, the new EventType can be added there with a justified consumer.

## What This Does NOT Change

- **`src/probos/proactive.py` — UNTOUCHED in v1.** Including `_think_for_agent` at `:703`, the `get_due_duties` call at `:715`, `set_duty_schedule` at `:395`, the 6 `record_execution` call sites at `:817/887/900/913/930/1050`, and the `_duty_tracker` field at `:181`. ALL of these are AD-500a-1 scope.
- `DutyScheduleTracker.__init__` signature at `duty_schedule.py:35` — unchanged. Constructor migration deferred to AD-500a-1 along with the proactive loop.
- 7 default duties in `config/system.yaml` — preserved as `DutyDefinition` entries; AD-500c migrates to AD-498 templates.
- AD-498 template patterns for common duties (scout_report, security_audit) — deferred to AD-500b.
- `get_due_duties()` (`duty_schedule.py:47`) and `record_execution()` (`:91`) — kept as-is; both used by the legacy proactive path AND by the new producer in v1.
- Booking lifecycle integration (`start_booking` / `complete_booking` at `workforce.py:1371,1424`) — deferred to AD-500a-1 (consumer-side concern).
- No new EventType — the producer reuses the existing `WORK_ITEM_CREATED` event with `work_type="duty"` payload.

## Test Plan

| # | Test | Purpose |
|---|---|---|
| 1 | `test_duty_work_type_registered` | Workforce registry lookup for `"duty"` returns a definition. Verify-only assertion against AD-498. |
| 2 | `test_emit_due_duties_creates_work_items_via_create_work_item` | Producer calls `WorkItemStore.create_work_item(work_type="duty", ...)` once per due duty. Mock the store and assert `create_work_item` is called with `work_type="duty"`, `assigned_to=agent_type`, payload containing `duty_id`. |
| 3 | `test_emit_due_duties_returns_work_item_ids` | Method returns `list[str]` of newly-created WorkItem IDs (length matches due-duty count; IDs match what the store returned). |
| 4 | `test_emit_due_duties_emits_work_item_created_event` | Verify the existing `EventType.WORK_ITEM_CREATED` event fires once per emitted item (by listening on the store's emitter). |
| 5 | `test_emit_due_duties_no_due_duties_returns_empty` | When `get_due_duties(agent_type)` returns `[]`, the producer returns `[]` and makes zero `create_work_item` calls. |
| 6 | `test_use_work_items_flag_default_false` | `DutyScheduleConfig().use_work_items is False`. Field exists at the documented location in `config.py:1397` block. |

**Total: 6 new tests** (down from original 12; the dropped 6 were consumer-side and move to AD-500a-1).

Plus regression check on existing duty/proactive tests — must remain green (the producer-only scope adds zero behavior change to existing call paths).

## Deferred Grandchildren

### AD-500a-1: Proactive Loop Duty Migration (Consumer Side)

**Scope:** Wire the proactive loop to consume duty WorkItems produced by AD-500.

**Forcing function (must hold before AD-500a-1 ships):**
1. AD-500's `use_work_items=False` default has been validated in production for at least one wave cycle (zero behavior change confirmed; producer method exercised only by tests or explicit ops opt-in).
2. The 6 `record_execution` call sites at `proactive.py:817/887/900/913/930/1050` have been individually mapped to one of: (a) keep + add `complete_booking` (dual-write), (b) replace with `complete_booking(booking_id)` with explicit booking-id-from-duty resolution, or (c) move into `record_execution` itself as an internal redirect when `use_work_items=True`.
3. The double-select between the outer poll loop and `_think_for_agent`'s self-selection at `proactive.py:715` has a chosen resolution (parameter passing vs replaced-internal-call) with a written specification.

**v1 deliverables (when AD-500a-1 ships):**
- Proactive loop polls `WorkItemStore.list_work_items(work_type="duty", status="pending", assigned_to=agent_type)` (signature confirmed at `workforce.py:1066-1076`).
- Booking lifecycle: `start_booking` / `complete_booking` around each duty `_think_for_agent()` call.
- `_think_for_agent` accepts an explicit `duty: WorkItem | DutyDefinition | None` parameter, skipping its own `get_due_duties` call when the parameter is supplied.
- 6 `record_execution` call sites resolved per the forcing function.
- `DutyScheduleConfig.use_work_items` default flips from `False` to `True` after rollout validation.
- ~6 new tests covering the consumer surface (poll → booking-open → think → booking-close lifecycle).

### AD-500b: AD-498 Templates for Duty Patterns

Defer scout_report / security_audit / heartbeat duty templates to AD-498's template surface. Pre-condition: AD-500a-1 stable.

### AD-500c: Default-Duty Config Migration + Cleanup

Migrate the 7 default duties in `config/system.yaml` from `DutyDefinition` entries to AD-498 templates. Remove `get_due_duties()`, `record_execution()`, and `DutyScheduleConfig.use_work_items` flag. Pre-condition: AD-500a-1 + AD-500b stable.

## Tracking

1. **PROGRESS.md:** prepend AD-500 entry. Note `AD-500a-1` added under Wave 10 deferred grandchildren.
2. **DECISIONS.md:** add entry under Era V:

```markdown
### AD-500: DutyScheduleTracker → WorkItem Producer (2026-05-03)

**Problem:** DutyScheduleTracker fires duties via direct `_think_for_agent()` calls, bypassing the AD-496 WorkItemStore + AD-498 work-type-registry surface that all other scheduled work uses. Two parallel tracking surfaces lead to inconsistency in observability, booking lifecycle, and token cost attribution.

**Decision:** Migrate DutyScheduleTracker to enqueue `WorkItem(work_type="duty")` items via `WorkItemStore.create_work_item(...)` — **producer side only in v1**. Add `DutyScheduleConfig.use_work_items: bool = False` flag (opt-in; default flips to `True` in AD-500a-1 after consumer migration). Constructor signature unchanged in v1 — dependency injected at call time per convention #5.

**Why scope-reframe to producer-only:** Pass-1 review (2026-05-03) surfaced Hard-stop #5 (proactive loop entanglement) — 6 unaddressed `record_execution` call sites and `_think_for_agent` self-selecting the duty made the original consumer-side migration structurally under-specified. Per Wave 5 convention #3 (coordinator-then-dispatch) applied at the AD-scoping level, v1 ships the producer; AD-500a-1 ships the consumer once the surface is exercised by tests and the entanglement is mapped.

**Why default `False`:** Convention #14 (aggressive pre-deferral) + transitional-flag discipline. Default `True` at first commit would be a breaking change in the same commit. Default `False` ships zero behavior change; flag flips in AD-500a-1.

**Why no new EventType:** Existing `EventType.WORK_ITEM_CREATED` (events.py:87) carries `work_type` in payload. A duty-discriminated event was theater per pass-1 review Recommended #1.

**Deferred:**
- AD-500a-1: Proactive loop consumer migration (forcing function: 6 `record_execution` sites mapped, double-select resolved, `use_work_items=False` validated).
- AD-500b: AD-498 templates for common duty patterns.
- AD-500c: 7 default duties migrated to AD-498 templates; `get_due_duties()` / flag removed.

**Cross-links:** AD-419 (DutyScheduleTracker), AD-496 (WorkItemStore), AD-498 (Work Type Registry).
```

3. **docs/development/roadmap.md:** flip AD-500 status to `partial — v1 ships duty WorkItem producer + opt-in flag (default False); proactive loop consumer migration deferred to AD-500a-1; templates and config migration deferred to AD-500b/c`.

## Verified Against Codebase (2026-05-03, post-revision)

```
grep -n "class DutyScheduleTracker\|def __init__\|def get_due_duties\|def record_execution" src/probos/duty_schedule.py
   27: class DutyScheduleTracker:
   35:     def __init__(self, schedules: dict[str, list[Any]]) -> None:   # UNCHANGED in v1
   47:     def get_due_duties(self, agent_type: str) -> list[Any]:         # untouched
   91:     def record_execution(self, agent_type: str, duty_id: str) -> None:  # untouched

grep -n "class WorkType\|class WorkItem\|class WorkItemStore\|def create_work_item\|def list_work_items\|def start_booking\|def complete_booking" src/probos/workforce.py
   97: class WorkTypeTransition:
  106: class WorkTypeDefinition:
  248: class WorkTypeRegistry:
  559: class WorkItem:
  905: class WorkItemStore(EventEmitterMixin):
  992:     async def create_work_item(self, **kwargs: Any) -> WorkItem:
 1066:     async def list_work_items(self, status, assigned_to, work_type, parent_id, priority, tags, limit, offset)  # not used in v1
 1371:     async def start_booking(self, booking_id: str) -> Booking | None:                                         # not used in v1
 1424:     async def complete_booking(self, booking_id: str, tokens_consumed: int = 0)                               # not used in v1

grep -n '"duty"' src/probos/workforce.py
  206:     "duty": WorkTypeDefinition(   # AD-498: duty pre-registered with state machine
  207:         type_id="duty",
  208:         display_name="Duty",
  404:         work_type="duty",
  416:         work_type="duty",

grep -n "class DutyScheduleConfig\|class DutyDefinition\|class ProactiveCognitiveConfig" src/probos/config.py
 1387: class DutyDefinition(BaseModel):
 1397: class DutyScheduleConfig(BaseModel):     # gains `use_work_items: bool = False` in v1
 1403: class ProactiveCognitiveConfig(BaseModel):

grep -n "WORK_ITEM_CREATED\|DUTY_" src/probos/events.py
   87:     WORK_ITEM_CREATED = "work_item_created"   # reused by v1; no new EventType
   (zero DUTY_* events; no new EventType added)

grep -n "_duty_tracker\|set_duty_schedule\|get_due_duties\|_think_for_agent\|record_execution" src/probos/proactive.py
  181: self._duty_tracker: DutyScheduleTracker | None = None    # untouched in v1
  395: def set_duty_schedule(...)                               # untouched
  398: self._duty_tracker = DutyScheduleTracker(config.schedules)  # constructor signature unchanged
  703: async def _think_for_agent(...)                          # untouched in v1
  715: due_duties = self._duty_tracker.get_due_duties(...)       # untouched
  817/887/900/913/930/1050: record_execution call sites          # untouched in v1; AD-500a-1 maps these
  (proactive.py is UNTOUCHED in v1; all entanglement deferred to AD-500a-1)

NO `WorkItemStore.add()` method exists. Producer calls `await work_item_store.create_work_item(work_type="duty", ...)`.
NO `DutyConfig` class exists. Flag lives on `DutyScheduleConfig` at config.py:1397.
```

## Acceptance Criteria

- `DutyScheduleTracker.emit_due_duties_as_work_items(agent_type, work_item_store)` exists and produces WorkItems via `WorkItemStore.create_work_item(work_type="duty", ...)`.
- `DutyScheduleConfig.use_work_items: bool = False` field exists (default `False` — opt-in).
- **`src/probos/proactive.py` is UNTOUCHED** by this prompt (zero diff).
- **`DutyScheduleTracker.__init__` signature is UNCHANGED** by this prompt.
- No new EventType added — producer reuses `WORK_ITEM_CREATED`.
- 6 new tests pass; existing duty/proactive/notification/runtime tests green (zero regressions).
- DECISIONS.md entry under Era V documents the producer-only scope reframe and deferral of consumer migration to AD-500a-1.
- AD-500a-1 listed in PROGRESS.md and roadmap.md with explicit forcing function.
- GH issue #87 partially closed (consumer side tracked under AD-500a-1).
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Hard-Stops (signal to architect)

- `DutyScheduleConfig` does not accept the new field for any reason (Pydantic validation conflict, frozen-model issue) — surface; field placement may need reconsideration.
- `WorkItemStore.create_work_item` rejects `work_type="duty"` with a registry error — surface; AD-498 cross-AD dependency may need extension despite Section 1 verify-only.
- Existing duty/proactive tests fail despite zero proactive.py changes — surface; producer-side coupling may exist via shared fixtures.

## Revision (2026-05-03)

Major scope reframe + 6 Required + 5 Recommended findings from `prompts/Reviews/ad-500-dutyscheduler-workitem-migration-review.md` (pass-1 verdict ❌ Not Ready). Applies the architect's Recommended #5 (full scope reframe) per Wave 5 convention #3 + Wave 8 AD-575b precedent.

**Scope reframe (the architectural change):**
- v1 was originally "3 of 5 capabilities" (producer + consumer + booking lifecycle). Pass-1 review surfaced **Hard-stop #5** (proactive loop entanglement worse than the prompt assumed): 6 unaddressed `record_execution` call sites, `_think_for_agent` self-selecting the duty (double-select with no shared parameter), and an unspecified constructor signature change.
- v1 is now **producer-only — 2 of 5 capabilities**. Consumer migration (proactive loop poll, booking lifecycle, `record_execution` triage, `_think_for_agent` parameter wiring) defers to **AD-500a-1** with an explicit forcing function ("ships when `use_work_items=False` validated AND 6 `record_execution` sites mapped").
- Risk drops from HIGH to medium. Test count drops from 12 to 6. Breaking-change risk in v1 = zero (default `use_work_items=False`, no proactive.py changes).

**Required findings resolved:**
1. **Phantom `runtime.work_item_store.add(work_item)`** — replaced everywhere with `await work_item_store.create_work_item(work_type="duty", assigned_to=..., title=..., payload=...)` (real API at `workforce.py:992`). Verify-first footer regrep-confirmed.
2. **Phantom class `DutyConfig`** — replaced with `DutyScheduleConfig` (real class at `config.py:1397`). All six original call sites in the prompt updated.
3. **`DutyScheduleTracker.__init__` signature change unspecified** — RESOLVED via reframe. Constructor signature is **unchanged in v1**; dependency `work_item_store` injected at call time per convention #5 (narrow injection). Constructor migration deferred to AD-500a-1 with the rest of the consumer-side work.
4. **6 `record_execution` call sites unaddressed** — RESOLVED via reframe. All 6 sites at `proactive.py:817/887/900/913/930/1050` are explicitly **untouched in v1**; their migration is one of AD-500a-1's two forcing-function pre-conditions.
5. **`_think_for_agent` re-selection ambiguity** — RESOLVED via reframe. `_think_for_agent` is untouched in v1; AD-500a-1's forcing function explicitly requires a written specification of the parameter-vs-internal-replace resolution before it ships.
6. **Test #10 (`no_dual_dispatch`) structurally untestable** — RESOLVED via reframe. Test dropped from v1 (no consumer in v1, so no dual-dispatch concern). The invariant moves to AD-500a-1's test plan where the consumer surface exists.

**Plus the implicit Required #7 (Section 1 was a no-op pretending to register a work type):** Section 1 now explicitly says "VERIFIED — `duty` already registered at `workforce.py:206`. No implementation needed." (per pass-1 Recommended #2).

**Default `use_work_items=False`** — applied per pass-1 Recommended #3 + convention #14. Original draft had `True` (breaking-change-on-first-commit). Default flips to `True` in AD-500a-1 after consumer migration is validated.

**Recommended findings resolved:**
1. **`DUTY_WORK_ITEM_CREATED` redundancy** — DROPPED. Existing `EventType.WORK_ITEM_CREATED` (events.py:87) carries `work_type="duty"` in payload; no named consumer needs subscribe-time discrimination. Removed Section 4 EventType addition; reframed Section 4 as "reuse existing event."
2. **Section 1 no-op** — applied (see above).
3. **Default `use_work_items` value** — applied (see above).
4. **Test #12 (`test_default_7_duties_emit_work_items`) couples unit test to ops config** — N/A in v1 (test dropped along with the original consumer-side scope; if it surfaces in AD-500a-1 it will be parametrized over a synthetic schedules dict per the recommendation).
5. **Hard-stop #5 (proactive entanglement)** — applied as the entire scope reframe.

**Beyond-review verify-first repairs (architect-discretion per Wave 9 posture):**
- Added `TYPE_CHECKING` guard for the `WorkItemStore` forward reference in `duty_schedule.py` to avoid an import cycle with `workforce.py`. Documented in Section 2.
- Verified `WorkItem.payload` field name caveat: `create_work_item(**kwargs)` accepts dataclass fields; if the actual `WorkItem` dataclass uses `metadata` or `params` instead of `payload`, Builder uses the actual name (Section 2 includes the verify-at-build-time note).
- Confirmed `_duty_tracker` field at `proactive.py:181` is the only DutyScheduleTracker reference in proactive.py; reframe leaves it intact.

**Closing self-check (per Wave 9 closing self-check + Wave 8 convention #12 — Solution Overview drift discipline):**
- `grep -i "work_item_store.add\|DutyConfig\b\|DUTY_WORK_ITEM_CREATED\|3 of 5 capabilities\|12 new tests"` against shipping content of this prompt — **0 hits** in shipping sections (the only references are in the Revision section explaining what was removed, which is the audit trail).
- `grep -i "default[^_]*True"` against `use_work_items` mentions — 0 hits in shipping content (only the Revision-section explanation of the removed default and the AD-500a-1 forcing-function description that says it "flips to True later").
- Solution Overview / v1-deliverables / Test Plan / Acceptance Criteria are mutually consistent on producer-only scope.
- All file paths and line numbers in verify-first footer regrep-confirmed against HEAD.
- Phantom-API check (mandatory per convention #16): no remaining phantoms — all method shapes verified against `workforce.py` and `config.py` at HEAD.
