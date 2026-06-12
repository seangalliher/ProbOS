# Build AD-878 — Boot-race grace period + dispatch idempotency guard

**Repo:** OSS (`d:\ProbOS`). **Issue: #847.** **Epic:** AD-877→884 Quartermaster hardening.
**Highest committed AD: AD-876** (Wave 232). This is **AD-878**. One AD = one commit.
**Depends on:** AD-877 (lands first; this AD adds another pre-act skip). **Build after AD-877 + AD-879.**

---

## Problem

The warm-boot sweep fires `startup_delay` (~10s) after boot (`BoardReconcilerTicker._loop`). A freshly-created
item that is **mid-first-dispatch** can look stranded (no live assignee yet) and be reclaimed / re-dispatched
a second time.

## Verify-first findings (confirmed — do not re-litigate)

- **`dispatch_work_item` is NOT idempotent-in-effect.** `WorkItemRouter.dispatch_work_item`
  (mesh/work_item_router.py:68) early-returns only if the item is not dispatchable; otherwise it
  unconditionally builds the decision, emits `HYBRID_DISPATCH_DIRECT`/`HYBRID_DISPATCH_BROADCAST`, and
  `await self._dispatcher.dispatch(task_event)`. It does **not** check current status/assignment. Re-running
  it re-emits events and re-dispatches. (BF-606 makes the downstream `transition_work_item` same-status a
  no-op, so it won't *crash*, but it will duplicate dispatch work.)
- → The correct, minimal guard is a **grace period on item age**, not a rework of the dispatch path. Do not
  touch `dispatch_work_item`.

## Build

### 1. Config — `WorkBoardReconcilerConfig` (config.py:4543)

```python
min_item_age_seconds: int = Field(default=30, ge=0, le=600)
```

### 2. Sweep — `QuartermasterAgent.reconcile()`

Before classifying/acting on any item, skip items younger than the grace period:

- If `self._min_item_age_seconds > 0` and `wi["created_at"] > time.time() - self._min_item_age_seconds`:
  `counts["too_fresh"] += 1`; continue (no classify, no act).
- This skip runs **before** the AD-877 quarantine/backoff/attempt logic (a too-fresh item must not accrue a
  reconcile attempt).
- Initialize `counts["too_fresh"] = 0` at the top of the sweep.

`WorkItem.created_at` is serialized by `to_dict()` (workforce.py:612) so `wi["created_at"]` is present in the
per-item dict the sweep already builds.

### 3. Wiring — `_wire_board_reconciler` (startup/finalize.py:1866) + constructor

Inject `agent._min_item_age_seconds = cfg.min_item_age_seconds` in the finalize injection block, and add a
`min_item_age_seconds=30` constructor kwarg to `QuartermasterAgent.__init__` storing the same private attr.

## Tests (≥6) — `tests/test_ad878_boot_grace_period.py`

**BF-287:** real `WorkItemStore` + real `WorkItem`.

1. Item with `created_at = now` skipped (`too_fresh`), never dispatched.
2. Item older than `min_item_age_seconds` processed normally.
3. Boundary: item exactly `min_item_age_seconds` old → processed (strict `>` skip, so equal is processed).
4. `min_item_age_seconds=0` disables the grace period (fresh item processed).
5. `too_fresh` key present in counts even when 0.
6. A too-fresh `clear_and_reroute` candidate does NOT increment `reconcile_attempts` (interaction with
   AD-877: too-fresh skip precedes attempt tracking).

## Do not

- Modify `dispatch_work_item`, `on_work_item_created`, or the dispatcher.
- Change `startup_delay` or `interval_seconds` defaults.

## Tracking

- PROGRESS.md banner → next free Wave (confirm highest first). DECISIONS.md AD-878 newest-first under
  `## Era V — Civilization`. No standalone docs.

## Acceptance

- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad878_boot_grace_period.py -q -n 0 -p no:cacheprovider` green.
- Corruption pre-check before commit. Verify compliance with `.github/copilot-instructions.md` Engineering Principles.

## Verified against codebase (2026-06-05)

- mesh/work_item_router.py:68 `async def dispatch_work_item` — no status/assignment guard before dispatch.
- mesh/work_item_router.py:159 `on_work_item_created` delegates to `dispatch_work_item`.
- workforce.py:597/612 `created_at` field + serialized in `to_dict()`.
- config.py:4543 `WorkBoardReconcilerConfig`.
