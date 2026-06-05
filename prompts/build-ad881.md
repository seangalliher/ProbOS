# Build AD-881 — Liveness ≠ progress: detect live-but-stalled assignees

**Repo:** OSS (`d:\ProbOS`). **Issue: #847.** **Epic:** AD-877→884 Quartermaster hardening.
**Highest committed AD: AD-876** (Wave 232). This is **AD-881**. One AD = one commit.
**Depends on:** AD-877 (the attempt guard — a stalled-reroute MUST be subject to it so it can't thrash).
**Ship as a documented, config-gated, default-off (0) first cut.**

---

## Problem

The reconciler reclaims only items whose assignee is **absent** from the registry
(`WorkItemReconciler.resolve_live_agent` returns None). An assignee that is **live but silently stuck** (no
progress) is never reclaimed.

## Verify-first finding (documented limitation — drives the default-off scope)

- **`updated_at` is "last board mutation", not a heartbeat.** `WorkItemStore.update_work_item`
  (workforce.py:1130) sets `updated_at = time.time()` on **every** update and emits `WORK_ITEM_UPDATED`. So
  `updated_at` advances on claim / status transition / assignment changes routed through `update_work_item`,
  but **does not** advance from agent-internal "I'm still working" progress that never touches the board. A
  genuinely-stuck-but-claimed agent leaves `updated_at` frozen at claim time.
- → `now - updated_at` is a **coarse** staleness signal: good enough to catch "claimed long ago, never
  progressed", but it is NOT a true liveness heartbeat. This is why the feature ships **default-off (0)** and
  the limitation is documented in DECISIONS.md. **Do not** add heartbeat plumbing (out of scope).

## Build (config-gated, default-off)

### 1. Config — `WorkBoardReconcilerConfig` (config.py:4543)

```python
stall_timeout_seconds: int = Field(default=0, ge=0, le=86400)  # 0 = disabled
```

### 2. Stall classification — sweep + `WorkItemReconciler.classify`

The stall signal needs the item's `updated_at` and the result of the existing liveness check. Implement so
the reconciler stays pure and the timestamp comparison lives where the other timestamp logic is:

- Pass the stall threshold into `classify` (e.g. `classify(wi, *, is_dispatchable, stall_timeout_seconds=0)`)
  OR compute the stall decision in the sweep before calling the normal classify — pick the path that keeps
  `WorkItemReconciler` pure (no clock import beyond `time.time()` which it can take as the staleness input).
  **Preferred:** sweep computes `is_stalled` and passes it in, since the agent already imports `time`.
- Rule: when `stall_timeout_seconds > 0`, an item with `status == "in_progress"` whose assignee **IS live**
  (`resolve_live_agent` returns an id) AND whose `updated_at < now - stall_timeout_seconds` is classified
  `clear_and_reroute` with `reason="stalled"`.
- This decision flows through the **AD-877 attempt guard** exactly like any other `clear_and_reroute`: it
  increments `reconcile_attempts`, honours backoff, and quarantines at the threshold — so a chronically
  stalled item can't thrash. Add `counts["stalled"] += 1` (init to 0) when a stall-reroute fires.

### 3. Wiring — `_wire_board_reconciler` + constructor

Inject `agent._stall_timeout_seconds = cfg.stall_timeout_seconds`; add `stall_timeout_seconds=0` constructor
kwarg storing the same private attr.

## Tests (≥6) — `tests/test_ad881_stall_detection.py`

**BF-287:** real `WorkItemStore` + real `AgentRegistry` (so `resolve_live_agent` actually resolves a live
agent). Seed an `in_progress` item assigned to a registered (live) agent.

1. `stall_timeout_seconds=0` → a live-but-old item is **never** reclaimed (disabled default).
2. Enabled + `updated_at` older than threshold + assignee live → `clear_and_reroute`, reason `stalled`,
   `counts['stalled']` incremented.
3. Enabled + fresh `updated_at` (recent) → not reclaimed.
4. Enabled + assignee **absent** → still classified by the normal absent-assignee path (not double-counted as
   `stalled`).
5. Stall-reroute respects AD-877: repeated stalls increment `reconcile_attempts` and quarantine at the
   threshold.
6. Boundary: `updated_at` exactly `now - stall_timeout_seconds` → not stalled (strict `<` older-than).

## Do not

- Add heartbeat/progress plumbing or new timestamps — use `updated_at` only.
- Reclaim `open`/non-`in_progress` items as stalled (stall only applies to claimed/in-progress work).
- Default `stall_timeout_seconds` to anything but `0`.

## Tracking

- PROGRESS.md banner → next free Wave. DECISIONS.md AD-881 newest-first under `## Era V — Civilization`,
  **explicitly recording** that `updated_at` is last-mutation (not heartbeat) and the feature is a default-off
  coarse first cut pending a real progress signal.

## Acceptance

- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad881_stall_detection.py -q -n 0 -p no:cacheprovider` green.
- Corruption pre-check. Verify compliance with `.github/copilot-instructions.md`.

## Verified against codebase (2026-06-05)

- workforce.py:598/1130 `updated_at` default_factory=time.time; `update_work_item` sets `updated_at=time.time()` every call.
- cognitive/work_reconciler.py `resolve_live_agent(assigned_to)->str|None`, `classify(wi,*,is_dispatchable)->ReconcileDecision`, `_TERMINAL={"done","failed","cancelled"}`.
- config.py:4543 `WorkBoardReconcilerConfig`.
