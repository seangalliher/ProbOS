# Review: AD-722b-3 — WS snapshot diffing

**Verdict:** ✅ Approved
**Pure-function `compute_diff` + per-connection state + every-Nth full reconcile + `type` field versioning is the textbook shape. One file-path hint in the table is wrong but the prompt instructs Builder to grep.**

## Required (must fix before building)
_None._

## Recommended
1. **File table entry `ui/src/hooks/useAvatarTelemetry.ts` does not exist.** The actual WS consumer is `ui/src/components/profile/SelfImageTab.tsx:135` (subscribes to `/api/agent/{id}/avatar-telemetry-stream`). The prompt's text below ("Builder MUST grep `ui/src/` for `avatar-telemetry-stream`") correctly hedges, but the file-table hint will mislead the Builder into searching for a hook that doesn't exist before grepping. Update the file table to cite `SelfImageTab.tsx` directly.
2. **Backward-compat assertion**: existing AD-722b WS tests that assert frame shape (e.g. `assert frame == snap.to_dict()`) will break under the new `{"type": "snapshot", **snap_dict}` wrapper. Dispatch's wave-specific reminder warns reviewer of this drift. The prompt's "What this does NOT change" section should explicitly call out "AD-722b tests asserting frame shape: assertions must include `type: 'snapshot'`" so Builder doesn't treat a green-locally / red-on-gate as a regression.
3. **`compute_diff` recursive nested call uses `skip_fields=frozenset()`** — nested `last_observed_at` would erroneously trigger a diff if any sub-dict ever happened to contain it. Today `current_signals` / `applied_modulation` / `dsl_summary` don't carry a `last_observed_at` key, so safe — but worth a code comment explaining why the recursion drops skip semantics (the skip list is top-level only by design).

## Nits
1. The `_values_differ` type-check `type(old) is not type(new)` is correct but fragile across int/float boundaries (e.g. `1` → `1.0` triggers a diff). The snapshot's numeric fields are float-typed throughout so this won't bite in practice; leave as is.
2. `tick_count % cfg_t.ws_full_snapshot_every_n == 0` fires every Nth tick INCLUDING tick 0 (since `0 % N == 0`). Combined with `initial` send sending a full snapshot, the first per-loop iteration would also send a full snapshot, then again at N, 2N, etc. Counts an extra full frame; not a correctness issue.

## Verified
- `await websocket.send_json` sites at `routers/agents.py:708, 738` — the two replace targets. Other `send_json` calls (681, 690, 753) are session messages, correctly out-of-scope.
- `AvatarTelemetrySnapshot.to_dict()` at `telemetry.py:378` returns flat dict with `last_observed_at` at line 388 — confirmed always-skip candidate.
- WS consumer for telemetry stream: `ui/src/components/profile/SelfImageTab.tsx:135` — single consumer. The diff-apply branch lands there.
- Config additions to `AvatarTelemetryConfig` (`ws_diff_enabled`, `ws_diff_threshold`, `ws_full_snapshot_every_n`) are non-overlapping with AD-722c (`history_*`) and AD-722d (`records_auto_write_*`). All three prompts can edit the same Pydantic model independently.
- AD-722c writer hook calls `_hist.append(snap)` with the `AvatarTelemetrySnapshot` object — the diff wrapper around `send_json` doesn't change what AD-722c receives. Compatible.
- AD-722d writer hook calls `_rw.observe(snap)` with the same snapshot object — also compatible.
- Test plan: 6 pytest + 1 vitest. compute_diff boundary coverage (first frame / identical / below threshold / above threshold / nested / skip) is complete. Vitest covers the frontend merge.
- AD-738b UI gate (BF-279): Builder dispatch requires `npm run build` for any `ui/src/` touch. Verification commands include `cd ui ; npx vitest run ; npm run build ; cd ..`. Correct.
- License: stdlib + plain TypeScript spread. No new deps.

---

**Re-review:** _(pending file-table hint correction)_

### Re-review (pass-2): unchanged, verdict re-affirmed ✅
