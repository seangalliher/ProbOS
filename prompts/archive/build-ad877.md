# Build AD-877 — Reconcile-attempt tracking + dead-letter quarantine (thrash guard)

**Repo:** OSS (`d:\ProbOS`). **Issue: #847.** **Epic:** AD-877→884 Quartermaster hardening.
**Highest committed AD: AD-876** (Wave 232). This is **AD-877**. One AD = one commit.
**Depends on:** nothing (first in the epic). **Blocks:** AD-881 (reuses the attempt guard).

---

## Problem

`QuartermasterAgent.reconcile()` ([src/probos/agents/quartermaster.py](../src/probos/agents/quartermaster.py))
acts on `clear_and_reroute` decisions by calling `self._store.unassign_work_item(id, ...)` then
re-dispatching. If the item's *next* assignee is also not live (no agent of that type / a real capability
gap), the sweep clears-and-reroutes the **same item every cycle forever** — no counter, no backoff, no
terminal state. This is unbounded thrash.

## Verify-first findings (already confirmed — do not re-litigate)

- **There is no store-side quarantine status.** `WorkItemStatus` (workforce.py:41) has
  `DRAFT/OPEN/SCHEDULED/IN_PROGRESS/REVIEW/DONE/FAILED/CANCELLED/BLOCKED` — **no `quarantined`**. There is no
  `quarantine_work_item` store method. AD-528b's quarantine lives in `cognitive/ground_truth.py`
  (`RejectionGate`), which **merges a payload into `WorkItem.metadata[key]`** and emits
  `EventType.WORK_ITEM_QUARANTINED`. Its docstring states a `quarantined` *status* is "deferred to AD-528b-5".
  → **AD-877 uses the metadata-flag pattern, NOT a status.**
- **`update_work_item` REPLACES `metadata`, it does not merge.** `WorkItemStore.update_work_item`
  (workforce.py:1130) JSON-encodes the value you pass for `metadata` and overwrites the column. You MUST
  read-modify-write: `item = await store.get_work_item(id)`; `md = dict(item.metadata)`; mutate `md`;
  `await store.update_work_item(id, metadata=md)`. `metadata` is NOT in `_IMMUTABLE_FIELDS`, so this is legal.
- `EventType.WORK_ITEM_QUARANTINED = "work_item_quarantined"` already exists (events.py:304). Reuse it.
- `runtime.emit_event` (runtime.py:1257) is **sync** — the agent calls `self._emit(...)` with **no await**.

## Build

### 1. Config — `WorkBoardReconcilerConfig` (config.py:4543)

Add two fields (transitional, bounded, defaults preserve current behavior is NOT possible here since this is
the thrash fix — pick conservative defaults):

```python
max_reconcile_attempts: int = Field(default=3, ge=1, le=20)
reconcile_backoff_seconds: int = Field(default=600, ge=0, le=86400)
```

These are read by `_wire_board_reconciler` and injected onto the agent (see §3) — do **not** read config
inside the agent.

### 2. Reconciler / sweep behavior (quartermaster.py `reconcile()`)

Read the current `reconcile()` body first. Apply these rules per item, **before** acting on a
`clear_and_reroute` decision:

- **Quarantine-skip (highest precedence):** if `wi["metadata"].get("quarantined")` is truthy, treat the item
  as `skip`, increment `counts["quarantined_skipped"]`, continue. (A quarantined item is never re-routed.)
- **Backoff-skip:** if `reconcile_backoff_seconds > 0` and the item's
  `wi["metadata"].get("last_reconcile_at", 0)` is within `reconcile_backoff_seconds` of `time.time()`, skip
  with `counts["backoff_skipped"] += 1`, continue.
- **Attempt tracking (only on `clear_and_reroute`):** before re-routing, read
  `attempts = int(wi["metadata"].get("reconcile_attempts", 0))`.
  - If `attempts + 1 >= self._max_reconcile_attempts`: **do not re-route.** Quarantine the item instead:
    read-modify-write `metadata` to set `quarantined=True`, `quarantine_reason="max_reconcile_attempts"`,
    `quarantined_at=time.time()`, `reconcile_attempts=attempts + 1`; `await self._store.update_work_item(id,
    metadata=md)`; emit `EventType.WORK_ITEM_QUARANTINED` via `self._emit(...)` with
    `{"work_item_id": id, "reason": "max_reconcile_attempts", "attempts": attempts + 1}`;
    `counts["quarantined"] += 1`; continue.
  - Otherwise re-route as today, **and** in the same `update_work_item` call that unassigns / before
    re-dispatch, persist `reconcile_attempts = attempts + 1` and `last_reconcile_at = time.time()` into
    `metadata` (read-modify-write). The existing `unassign_work_item` call clears `assigned_to`; the attempt
    counter persists on the item across cycles via `metadata`.

Keep the existing per-item Tier-2 try/except degrade (`counts["degraded"] += 1`, continue) wrapping all of
the above. Initialize the new counts keys (`quarantined`, `quarantined_skipped`, `backoff_skipped`) to `0` at
the top of the sweep so the `WORK_ITEM_RECONCILED` payload always carries them.

### 3. Wiring — `_wire_board_reconciler` (startup/finalize.py:1866)

Inject the two new config values onto the agent as private attrs, mirroring the existing injection block
(`agent._scan_limit = cfg.scan_limit` etc.):

```python
agent._max_reconcile_attempts = cfg.max_reconcile_attempts
agent._reconcile_backoff_seconds = cfg.reconcile_backoff_seconds
```

Add matching constructor kwargs (`max_reconcile_attempts=3`, `reconcile_backoff_seconds=600`) to
`QuartermasterAgent.__init__` with the same private-attr storage, so direct construction in tests does not
rely on finalize injection.

## Tests (≥10) — `tests/test_ad877_reconcile_thrash_guard.py`

**BF-287:** use a **real** `WorkItemStore` (`tmp_path`, `await store.start()`) and a real `WorkItem`.
`_Fake*` only for the router/dispatcher boundary. No MagicMock at the store boundary.

1. `reconcile_attempts` increments by 1 on a `clear_and_reroute` item; persisted in `metadata`.
2. `last_reconcile_at` written on re-route.
3. Item reaches `max_reconcile_attempts` → quarantined: `metadata['quarantined'] is True`, NOT re-dispatched.
4. `WORK_ITEM_QUARANTINED` emitted at the threshold (assert via captured emit).
5. Already-quarantined item is `skip` on the next sweep (no unassign, no dispatch) → `quarantined_skipped`.
6. Backoff skip: item with recent `last_reconcile_at` skipped when `reconcile_backoff_seconds>0` →
   `backoff_skipped`.
7. `reconcile_backoff_seconds=0` disables backoff (item processed).
8. counts dict always carries `quarantined`, `quarantined_skipped`, `backoff_skipped` keys (even when 0).
9. `max_reconcile_attempts=1` quarantines on the first `clear_and_reroute`.
10. Per-item exception still degrades (counts['degraded']) and continues the sweep (real store, force one
    item to raise via a `_Fake` router that throws).

## Do not

- Add a new DB column or a `quarantined` `WorkItemStatus` value. Use `metadata`.
- Merge-vs-replace bug: always read-modify-write `metadata` (update_work_item replaces it).
- Change `live_redispatch` or `skip` semantics — this AD only adds the guard on `clear_and_reroute`.

## Tracking

- Bump the PROGRESS.md top banner to the next free Wave number (AD-876 = Wave 232; confirm current highest in
  PROGRESS.md before stamping).
- Add an AD-877 entry to DECISIONS.md, newest-first, under `## Era V — Civilization`.
- No standalone markdown docs.

## Acceptance

- Focused serial gate green: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad877_reconcile_thrash_guard.py -q -n 0 -p no:cacheprovider`.
- Corruption pre-check before commit: `git diff --numstat | sort -k2nr | head`.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Verified against codebase (2026-06-05)

- workforce.py:41 `class WorkItemStatus` — no `quarantined` member.
- workforce.py:1130 `update_work_item` — `metadata` JSON-encoded and overwritten (replace, not merge).
- workforce.py:920 `_IMMUTABLE_FIELDS = {"id","created_at","created_by"}` — `metadata` mutable.
- cognitive/ground_truth.py:289-380 — quarantine = metadata-merge + `WORK_ITEM_QUARANTINED`; "`quarantined` status deferred to AD-528b-5".
- events.py:304 `WORK_ITEM_QUARANTINED = "work_item_quarantined"`.
- config.py:4543 `WorkBoardReconcilerConfig`; runtime.py:1257 `emit_event` is sync.
