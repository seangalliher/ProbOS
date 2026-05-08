# AD-581-completion v1 — Finish AD-581a/b/d wiring

**Issue:** [#504](https://github.com/seangalliher/ProbOS/issues/504) parent BF; original ADs #469/#470/#471 (closed as substrate-shipped).
**Type:** Bug Fix (completion of partially-shipped AD)
**Depends on:** none — config seam landed 2026-05-08 in this session.
**Wave:** next

## Goal

The AD-581 trio (DepartmentDispatcher / Order Protocol / Routing Confidence Threshold) shipped its **substrate** but skipped the wiring, events, state-machine transitions, and config validators. `tests/test_ad581_hybrid_dispatch.py` collects clean now (after `HybridDispatchConfig` was added to `config.py` 2026-05-08) but **9 of 31 tests still fail**. This prompt closes those gaps.

## Verified Against Codebase (2026-05-08)

- ✅ `src/probos/mesh/department_dispatcher.py` exists, defines `DepartmentDispatcher`, `RoutingDecision`, `RoutingMode`. Reads `_config.min_hebbian_weight`, `confidence_threshold`, `confidence_margin`, `success_rate_window`, `min_samples_for_routing`.
- ✅ `src/probos/mesh/work_item_router.py` exists, defines `WorkItemRouter` that logs `AD-581a: HYBRID_DISPATCH_DIRECT` / `HYBRID_DISPATCH_BROADCAST` events.
- ✅ `src/probos/cognitive/orders.py` exists with `class OrderState(str, Enum)` at line 28 — members `PENDING` (":29"), `ACKNOWLEDGED`, `EXPIRED`, `DECLINED`, `REFUSED`. The class is named `OrderState`, **not** `OrderStatus`. Tests at `tests/test_ad581_hybrid_dispatch.py:23` import `OrderState`. The `decline()` (":239") and `refuse()` (":286") methods already exist and emit `EventType.ORDER_DECLINED` / `EventType.ORDER_REFUSED` (the warnings are logged because the enum members do not exist yet — fixed in D1).
- ✅ `src/probos/config.py` lines 1465-1483 has `HybridDispatchConfig` with the 5 read fields (no validators yet).
- ❌ `events.py` has **no** `ORDER_ISSUED`, `ORDER_DECLINED`, `ORDER_REFUSED`, `HYBRID_DISPATCH_DIRECT`, `HYBRID_DISPATCH_BROADCAST` enum members — emit_event calls all silently fail.
- ✅ `orders.py` order state machine: `OrderState.PENDING` exists at `:29`; `decline()` and `refuse()` already implement the PENDING→DECLINED / PENDING→REFUSED transitions and the emit calls. The only gap is the missing EventType enum members (D1) — once they exist, the existing emit machinery works.
- ❌ `_wire_hybrid_dispatch` finalize wirer not in `startup/finalize.py`.
- ❌ `HybridDispatchConfig` has no Pydantic validators.

## Scope

Close the 9 failing tests in `tests/test_ad581_hybrid_dispatch.py`. Nothing else.

## Deliverables

### D1. Add the 5 missing `EventType` enum values

In `src/probos/events.py`, locate the existing `EventType` enum. **Verify the test expects exact string values** (read `test_event_type_decline_refuse_values` first) and add:

- `ORDER_ISSUED = "order_issued"` (referenced as AD-440)
- `ORDER_DECLINED = "order_declined"` (AD-581b)
- `ORDER_REFUSED = "order_refused"` (AD-581b)
- `HYBRID_DISPATCH_DIRECT = "hybrid_dispatch_direct"` (AD-581a)
- `HYBRID_DISPATCH_BROADCAST = "hybrid_dispatch_broadcast"` (AD-581a)

If any of these already exist, leave them. Match the existing alphabetical/grouping convention in the enum.

### D2. Order state-machine transitions (verify-only)

In `src/probos/cognitive/orders.py`:

- **Verified at HEAD**: `OrderState.PENDING` exists at `:29`; `decline(order_id, declined_by, reason) -> bool` exists at `:239` (PENDING→DECLINED, emits `EventType.ORDER_DECLINED`); `refuse(order_id, refused_by, violation) -> bool` exists at `:286` (PENDING→REFUSED, emits `EventType.ORDER_REFUSED`); `Order.issue()` already emits `EventType.ORDER_ISSUED`. **No code changes required in `orders.py`** — the warnings logged today (`AD-440: ORDER_ISSUED emit failed`, `AD-581b: ORDER_DECLINED emit failed`) are caused exclusively by the missing EventType members from D1. Once D1 lands, the existing emit machinery succeeds and the state-transition tests pass.
- Do NOT rename `OrderState` to `OrderStatus` — the canonical class name is `OrderState`.

### D3. `HybridDispatchConfig` validators

In `src/probos/config.py`, augment `HybridDispatchConfig` with Pydantic `field_validator`s:

- `min_hebbian_weight`, `confidence_threshold`, `confidence_margin` in `[0.0, 1.0]`.
- `success_rate_window >= 1`.
- `min_samples_for_routing >= 0`.
- `confidence_threshold >= confidence_margin` (model-level invariant via `model_validator(mode="after")`).

Keep defaults exactly as currently set. Validators only.

### D4. `_wire_hybrid_dispatch` finalize wirer

In `src/probos/startup/finalize.py`, add a `_wire_hybrid_dispatch(runtime, config)` async function that:

- Returns early if `config.hybrid_dispatch.enabled` is False (add an `enabled: bool = True` field to `HybridDispatchConfig` in D3 if not present).
- Constructs `DepartmentDispatcher(hebbian_router=runtime.hebbian_router, ontology=getattr(runtime, "ontology", None), config=config.hybrid_dispatch)`.
- Constructs `WorkItemRouter(...)` with the dispatcher.
- Subscribes the router to `EventType.WORK_ITEM_CREATED`.
- Logs `Startup [hybrid_dispatch]: wired DepartmentDispatcher + WorkItemRouter` at INFO.

Wire it into the existing finalize phase chain at the appropriate location (after the ontology service is up, before bridge alerts).

### D5. Wire `HybridDispatchConfig` into `SystemConfig`

```python
# in SystemConfig
hybrid_dispatch: HybridDispatchConfig = HybridDispatchConfig()
```

### D6. Verify `WorkItemRouter.on_work_item_created` recovers after D1

The two `test_on_work_item_created_*` failures and the WARNING `"AD-581a: WorkItemRouter.on_work_item_created failed; work_item dispatch skipped"` at `work_item_router.py:161-166` are caused by the inner `self._emit(EventType.HYBRID_DISPATCH_DIRECT, ...)` / `EventType.HYBRID_DISPATCH_BROADCAST` references at `:73` and `:117` raising `AttributeError` because the enum members do not exist yet. Once D1 adds the two members, the inner emit calls succeed and the outer broad-`except` is no longer triggered. The broad `except Exception` at `:161-166` stays — it is the canonical "never block work-item dispatch on telemetry failure" guard and is consistent with the rest of the wave's tier-2 log-and-degrade pattern. **No code change is required in `work_item_router.py`.** Builder confirms the two `test_on_work_item_created_assigned_to_dispatches_direct` and `test_on_work_item_created_low_hebbian_broadcasts` tests pass after D1.

## Non-Goals

- Don't add new behavior beyond what the tests require.
- Don't rename anything.
- Don't touch `BaseAgent`, `IntentMessage`, `RuntimeProtocol`.
- Don't refactor the order state machine beyond adding the two missing transitions.

## Acceptance

- `pytest tests/test_ad581_hybrid_dispatch.py -v -n 0` — **31/31 pass**.
- `pytest tests/ -q -n 16 --dist=loadfile` — full gate green or only environmental flakes.
- `git diff` shows changes only in: `events.py`, `config.py`, `startup/finalize.py`. **No edits to `cognitive/orders.py` or `mesh/work_item_router.py`** (D1 alone fixes the cascading AttributeError chain). No new test files (existing test file already covers this).
- DECISIONS.md gets a single `### AD-581-completion — Wired AD-581 substrate end-to-end` entry.
- Comply with engineering principles in `.github/copilot-instructions.md`.

## Tracking

- Closes [#504](https://github.com/seangalliher/ProbOS/issues/504) when 31/31 pass.
- Append to DECISIONS.md after Builder commit.

## Revision (2026-05-08)

- **Recommended #1 applied**: Confirmed `OrderState.PENDING` existence at `cognitive/orders.py:29`. Discovered (and corrected) a phantom-class-name defect: the prompt referred to `OrderStatus` four times, but the canonical class name is `OrderState` (verified at `orders.py:28` and `tests/test_ad581_hybrid_dispatch.py:23`). All four `OrderStatus` references in Verified-Against-Codebase and D2 are now `OrderState`. D2 was rewritten as a verify-only step — `decline()` (`:239`), `refuse()` (`:286`), and `Order.issue()` already exist with the correct emit machinery; the only gap is the missing EventType enum members from D1.
- **Recommended #2 applied**: Read `mesh/work_item_router.py:62-166` and identified the actual root cause of the `on_work_item_created` warning: the inner `self._emit(EventType.HYBRID_DISPATCH_DIRECT, ...)` and `EventType.HYBRID_DISPATCH_BROADCAST` references at `:73` and `:117` raise `AttributeError` because the enum members do not exist yet, which the outer broad-except at `:161-166` catches. D6 was rewritten as a verify-only step ("D1 alone fixes the cascading AttributeError chain; no code change in `work_item_router.py`"). Acceptance criteria updated to remove `cognitive/orders.py` and `mesh/work_item_router.py` from the expected `git diff` surface.
