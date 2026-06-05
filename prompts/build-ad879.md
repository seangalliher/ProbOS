# Build AD-879 — Deterministic oldest-first scan ordering + starvation guard

**Repo:** OSS (`d:\ProbOS`). **Issue: #847.** **Epic:** AD-877→884 Quartermaster hardening.
**Highest committed AD: AD-876** (Wave 232). This is **AD-879**. One AD = one commit.
**Depends on:** AD-877 (counts dict). **Build after AD-877.**

---

## Problem

`scan_limit` caps the sweep at 200 items per status. With a backlog >200, the oldest stranded items can
**starve** — they may never make it into the scanned window.

## Verify-first finding (REQUIRED correction to the epic)

- The epic offers a branch "confirm `list_work_items` already returns a deterministic oldest-first order."
  **That branch is FALSE.** `WorkItemStore.list_work_items` (workforce.py:1088) uses
  `ORDER BY priority ASC, created_at DESC` — priority-ascending (critical first, good) but **`created_at DESC`
  = NEWEST-first within a priority band.** Oldest items sort last and starve under a `scan_limit` cap.
- `reconcile()` merges the two status lists into a dict keyed by `item.id`, preserving insertion order.
  → **AD-879 MUST add an explicit oldest-first re-sort of the merged set.** A confirm-only no-op is wrong.

## Build

### `QuartermasterAgent.reconcile()`

- After merging the `open` + `in_progress` items into the keyed dict, build the processing list as:
  `ordered = sorted(merged.values(), key=lambda i: (i.priority, i.created_at))` — priority ascending
  (critical first), then `created_at` ascending (oldest first within a priority band). Iterate `ordered`.
- **Truncation visibility:** if `len(merged) >= self._scan_limit` (the merged set hit the cap),
  set `counts["truncated"] = True` and log one Tier-2 warning:
  `logger.warning("Board reconcile truncated: merged=%d >= scan_limit=%d; oldest items prioritized but backlog growing", len(merged), self._scan_limit)`.
  Default `counts["truncated"] = False` at the top of the sweep.
- Note: each `list_work_items(status=..., limit=self._scan_limit)` already caps per-status at the DB layer;
  the re-sort guarantees that within whatever was fetched, the oldest are processed first. (Full backlog
  drainage beyond `scan_limit` is explicitly out of scope — the `truncated` flag is the signal.)

## Tests (≥5) — `tests/test_ad879_scan_ordering.py`

**BF-287:** real `WorkItemStore`. Seed items with mixed `priority` and `created_at`.

1. Processing order is `(priority asc, created_at asc)` — assert the sequence of ids the sweep acts on
   (capture via a `_Fake` router recording `dispatch_work_item` call order).
2. Two items same priority: older `created_at` processed first.
3. Lower priority number (more critical) processed before higher number regardless of age.
4. `truncated` is `True` when merged count ≥ `scan_limit` (seed `scan_limit` small, e.g. 2, via constructor).
5. `truncated` is `False` for a small backlog; key always present in counts.

## Do not

- Raise the default `scan_limit` (stays 200).
- Change `list_work_items`' SQL ordering (other callers depend on newest-first). Re-sort **in the sweep only**.

## Tracking

- PROGRESS.md banner → next free Wave. DECISIONS.md AD-879 newest-first under `## Era V — Civilization`.

## Acceptance

- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad879_scan_ordering.py -q -n 0 -p no:cacheprovider` green.
- Corruption pre-check. Verify compliance with `.github/copilot-instructions.md`.

## Verified against codebase (2026-06-05)

- workforce.py:1088 `list_work_items` — `ORDER BY priority ASC, created_at DESC` (newest-first within priority).
- quartermaster.py `reconcile()` merges open+in_progress by `item.id`, each `limit=self._scan_limit`.
- workforce.py:591/597 `priority`, `created_at` fields.
