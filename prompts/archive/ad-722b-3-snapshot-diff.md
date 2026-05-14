# AD-722b-3 — Fine-grained snapshot-diff for WS push

**AD:** AD-722b-3. **GH issue closed:** [#600](https://github.com/seangalliher/ProbOS/issues/600).
**Parent ADs:** AD-722b (WS push channel, Wave 142), AD-722b-2 (sensorium freshness side-effect, Wave 142).
**Wave:** 159. **Estimated tests:** +6 pytest + 1 vitest. **Estimated wall-time:** ~2h. **Risk:** LOW-MED (changes WS frame shape — backward-compat via `full` frame on reconnect + every Nth tick).

---

## Solution Overview

The WS publish loop (`routers/agents.py:_publish_loop` around line 736) sends a full `snap.to_dict()` on every wake — every interval tick and every `avatar_event_bus.notify()` fire. With AD-722b-2's notify-on-state-change pattern, the same snapshot can broadcast 2–3 times per second when an agent is actively replying. Most fields don't change frame-to-frame; the HXI re-renders for nothing.

v1 already coarse-skips: AD-722b's publish loop only sends after wake (event OR timer). AD-722b-3 layers **field-level diffing on top**: compute per-field delta against last-sent snapshot, skip if empty, send a partial `{"type": "diff", "changed": {...}}` if minor, send a full `{"type": "snapshot", ...}` on first-frame / every Nth tick / numeric-threshold-breached frames.

**Backward compat:**
- New `type` field on every WS frame (`"snapshot"` or `"diff"`). Existing frames don't have `type`; the HXI must default to `"snapshot"` when missing.
- Every Nth tick (config, default 10) sends a `"snapshot"` regardless — late subscribers and any client that missed a diff reconcile.
- First frame on connect is ALWAYS `"snapshot"` (already an invariant of the publish loop's `initial` block).

**Numeric epsilon:** floats need a relative-change threshold to avoid emitting diffs for `last_observed_at` jitter (changes every frame by definition — explicitly skip from diff candidate set).

**Folded:** none.

---

## Files to Modify

| File | Lines | Why |
|---|---|---|
| `src/probos/config.py` | ~1025 (`AvatarTelemetryConfig`) | Add `ws_diff_enabled: bool = True`, `ws_diff_threshold: float = 0.05`, `ws_full_snapshot_every_n: int = 10`. |
| `src/probos/avatars/snapshot_diff.py` | NEW (~120 lines) | Pure-function `compute_diff(prev_dict, next_dict, threshold, skip_fields)` returning `dict[str, Any]` (empty = no diff). |
| `src/probos/routers/agents.py` | ~700-741 (publish loop) | Track `last_sent_snap: dict | None`, `tick_count: int`. Decide per-frame: full vs diff vs skip. Wrap payload with `{"type": ..., "agent_id": ..., ...}`. |
| `ui/src/hooks/useAvatarTelemetry.ts` | If exists — the WS subscriber hook | Apply diffs to last-known snapshot; render only on change. Backward-compat default for frames without `type`. |
| `tests/test_ad722b_3_snapshot_diff.py` | NEW | 6 pytest tests. |
| `ui/src/__tests__/avatarTelemetry.diff.test.ts` | NEW | 1 vitest test for the frontend diff-apply logic. |

Live grep + audit:
- The WS handler at `routers/agents.py:634` calls `websocket.send_json(snap.to_dict())` at lines 708 and 741. Both are diff-eligible after this AD lands.
- `AvatarTelemetrySnapshot.to_dict()` returns a `dict[str, Any]` with 10 top-level keys (see `telemetry.py:380-393` block). Nested objects: `current_signals`, `applied_modulation`, `dsl_summary` (each also a dict). `last_observed_at` is `now` and changes every frame — MUST be in the always-skip set for diff candidacy (but still included on full snapshots).
- The frontend WS subscriber needs grep to locate. Likely under `ui/src/audio/` or `ui/src/hooks/`. If no dedicated hook exists, the inline subscriber in whichever component opens the WS is the target — the Builder MUST grep `avatar-telemetry-stream` under `ui/src/` first and pick the unique consumer.

---

## Section 1 — `AvatarTelemetryConfig` fields

In `src/probos/config.py`, in `AvatarTelemetryConfig`, add (after the AD-722d fields):

```python
    # AD-722b-3: WS frame diffing. Default ON — pure additive perf win.
    # Disable to revert to AD-722b's always-full-snapshot behavior.
    ws_diff_enabled: bool = True
    # Relative-change threshold for numeric fields. Below this, the field
    # is treated as unchanged for diff purposes (frame is suppressed if
    # all numeric deltas are sub-threshold AND no non-numeric changes).
    ws_diff_threshold: float = 0.05
    # Send a full snapshot every N publish-loop wakes regardless of diff,
    # so late-arriving subscribers and any browser that missed a diff
    # reconcile. Set to 1 to disable diff entirely (behaves as full).
    ws_full_snapshot_every_n: int = 10
```

Add a `field_validator` bounding `0.0 <= ws_diff_threshold <= 1.0` and `ws_full_snapshot_every_n >= 1`.

---

## Section 2 — `compute_diff` helper (NEW)

Create `src/probos/avatars/snapshot_diff.py`:

```python
"""AD-722b-3: shallow-merge-friendly diff between two snapshot dicts.

Pure function. Returns a dict of CHANGED top-level fields (with their
new values). Empty dict means no significant change.

Numeric fields use a relative-change threshold; floats below the
threshold count as unchanged. Nested dicts are diffed recursively (one
level deep — matches the snapshot's flat-of-flats shape).

Fields named in ``always_skip`` are excluded from candidate set entirely
(``last_observed_at`` would otherwise change every frame).
"""
from __future__ import annotations

from typing import Any

# These change every frame by nature; never diff-trigger on them.
DEFAULT_SKIP_FIELDS: frozenset[str] = frozenset({"last_observed_at"})


def compute_diff(
    prev: dict[str, Any] | None,
    nxt: dict[str, Any],
    threshold: float = 0.05,
    skip_fields: frozenset[str] = DEFAULT_SKIP_FIELDS,
) -> dict[str, Any]:
    """Compute changed fields. Returns ``{}`` if no significant change."""
    if prev is None:
        # First frame — every field changed; caller should send full.
        return {k: v for k, v in nxt.items() if k not in skip_fields}

    out: dict[str, Any] = {}
    for key, new_val in nxt.items():
        if key in skip_fields:
            continue
        old_val = prev.get(key, _MISSING)
        if old_val is _MISSING:
            out[key] = new_val
            continue
        if _values_differ(old_val, new_val, threshold):
            out[key] = new_val
    return out


_MISSING = object()


def _values_differ(old: Any, new: Any, threshold: float) -> bool:
    if type(old) is not type(new):
        return True
    if isinstance(new, (int, float)) and not isinstance(new, bool):
        try:
            o = float(old)
            n = float(new)
        except (TypeError, ValueError):
            return old != new
        if o == n:
            return False
        denom = max(abs(o), abs(n), 1e-9)
        return (abs(n - o) / denom) >= threshold
    if isinstance(new, dict):
        # One level of nested diff — same threshold applied recursively.
        nested = compute_diff(old, new, threshold, skip_fields=frozenset())
        return bool(nested)
    if isinstance(new, list):
        # Lists: change-detected if length differs OR any positional value
        # differs by the same rule. Cheap, sufficient for tuple fields
        # like degraded_reasons.
        if len(old) != len(new):
            return True
        return any(_values_differ(o, n, threshold) for o, n in zip(old, new))
    return old != new
```

---

## Section 3 — Publish loop wiring

In `src/probos/routers/agents.py:agent_avatar_telemetry_stream` (around line 634), per-connection local state is initialized at the top. Add before the `try:` block where `event_bus.subscribe(...)` is called:

```python
    # AD-722b-3: per-connection diff state. Each WS connection has its
    # own "last sent" tracker so reconnects (which receive the full
    # initial snapshot) don't depend on cross-connection memory.
    last_sent_snap_dict: dict[str, Any] | None = None
    tick_count = 0
```

Replace the initial-send block (~line 707) to emit a `type: "snapshot"` wrapper:

```python
        try:
            initial = await build_telemetry_snapshot(agent_id, runtime)
            agent._last_self_avatar_snap = initial
            initial_dict = initial.to_dict()
            await websocket.send_json(
                {"type": "snapshot", **initial_dict},
            )
            last_sent_snap_dict = initial_dict
        except Exception:
            logger.warning(...)  # existing
```

Replace the per-loop send (~line 741) with the diff-aware path. Find the existing block:

```python
                snap = await build_telemetry_snapshot(agent_id, runtime)
                agent._last_self_avatar_snap = snap
                await websocket.send_json(snap.to_dict())
```

Replace with:

```python
                snap = await build_telemetry_snapshot(agent_id, runtime)
                agent._last_self_avatar_snap = snap
                snap_dict = snap.to_dict()
                tick_count += 1

                cfg_t = getattr(runtime.config, "avatar_telemetry", None)
                if (
                    cfg_t is None
                    or not cfg_t.ws_diff_enabled
                    or (tick_count % cfg_t.ws_full_snapshot_every_n) == 0
                ):
                    # Full snapshot path.
                    await websocket.send_json(
                        {"type": "snapshot", **snap_dict},
                    )
                    last_sent_snap_dict = snap_dict
                else:
                    from probos.avatars.snapshot_diff import compute_diff
                    diff = compute_diff(
                        last_sent_snap_dict,
                        snap_dict,
                        threshold=cfg_t.ws_diff_threshold,
                    )
                    if not diff:
                        # No significant change — skip the send entirely.
                        continue
                    await websocket.send_json({
                        "type": "diff",
                        "agent_id": snap.agent_id,
                        "changed": diff,
                    })
                    # Merge diff into last_sent for next-frame baseline.
                    last_sent_snap_dict = {**(last_sent_snap_dict or {}), **diff}
```

Tier-2 protection: any `compute_diff` exception should fall through to the full-snapshot branch. Wrap the `else:` branch in a `try/except` that falls back to a full send + WARNING log.

---

## Section 4 — Frontend diff-apply

**Builder pre-step:** grep `ui/src/` for `avatar-telemetry-stream` to locate the unique WS consumer. Likely candidates: `ui/src/hooks/useAvatarTelemetry.ts` OR an inline subscriber in `ui/src/components/profile/` or `ui/src/components/avatars/`. Read the consumer; the diff-apply logic goes wherever the `onmessage` handler parses the JSON.

Add to the `onmessage` handler:

```typescript
// AD-722b-3: diff frames merge into last-known snapshot. Frames without
// `type` (legacy / pre-AD-722b-3 servers) default to "snapshot" semantics.
const parsed = JSON.parse(event.data);
const frameType = parsed.type ?? 'snapshot';
if (frameType === 'diff') {
  const merged = { ...lastSnapshotRef.current, ...parsed.changed };
  lastSnapshotRef.current = merged;
  setSnapshot(merged);
  return;
}
// snapshot OR legacy: replace lastSnapshot wholesale.
lastSnapshotRef.current = parsed;
setSnapshot(parsed);
```

The exact `lastSnapshotRef` / `setSnapshot` names depend on the existing hook — Builder MUST mirror the existing variable names. Pattern is consistent with how AD-722b's hook stores state.

If the consumer is an inline subscriber inside a component, refactor is OUT OF SCOPE — extract only if it's already a hook. Otherwise just wire the if/else inline.

---

## Test plan (boundary tests)

Create `tests/test_ad722b_3_snapshot_diff.py` with 6 tests of `compute_diff`:

1. `test_diff_first_frame_returns_all_fields_minus_skip` — `prev=None` → returns all keys except `last_observed_at`.
2. `test_diff_identical_returns_empty` — `prev == next` → `{}`.
3. `test_diff_numeric_below_threshold_skipped` — `prev={"x": 1.0}`, `next={"x": 1.02}`, threshold 0.05 → `{}`.
4. `test_diff_numeric_above_threshold_included` — same with `next={"x": 1.10}` → `{"x": 1.10}`.
5. `test_diff_nested_dict_recurses_one_level` — `current_signals` field change at child level → included in output.
6. `test_diff_skip_fields_excluded_even_when_changed` — `last_observed_at` differs → not in output.

Create `ui/src/__tests__/avatarTelemetry.diff.test.ts` with 1 vitest test:
- Construct a mock WS message handler with the diff-apply branch; feed a snapshot frame then a diff frame; assert merged state matches `{...snapshot, ...changed}`.

No real WS, no real runtime — pure logic tests.

---

## What this does NOT change

- The HTTP `GET /api/agent/{id}/avatar-telemetry` endpoint — always full snapshot.
- The AD-722c JSONL history — always full snapshots (history must be replay-complete).
- The AD-722d Records writer — observes full `AvatarTelemetrySnapshot` (Python object), not WS dicts.
- Connection management / max-per-agent enforcement / popout sampling state.
- `AvatarTelemetrySnapshot` dataclass shape — unchanged.
- `prompts/BUILDER-EXECUTION-PLAN.md` — not edited in this prompt.

---

## Verification commands

```powershell
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad722b_3_snapshot_diff.py -v -n 0
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile
cd ui ; npx vitest run ; npm run build ; cd ..
```

**UI gate REQUIRED (AD-738b):** this prompt edits `ui/src/`, so the per-commit gate MUST run both `npx vitest run` AND `npm run build`.

---

## Tracker updates

- `PROGRESS.md` — append closure line.
- `docs/development/roadmap.md` — mark #600 closed.
- `DECISIONS.md` — append AD-722b-3 entry; document the every-Nth-full-snapshot reconcile design and the `type` field versioning approach.

Commit message:
```
AD-722b-3: WS frame diffing for avatar telemetry

Closes #600
```

---

## License Disposition

**All-internal Apache 2.0.** No new pip deps (stdlib only). No new npm deps. Frontend diff-apply is plain TypeScript object-spread. No model weights, no binaries.

---

## Forward markers

- **AD-722b-3a** — RFC 6902 JSON-Patch payload format instead of shallow-merge dict (trigger: HXI surfaces deeply nested telemetry trees where shallow merge loses information).
- **AD-722b-3b** — server-side last-sent state per-subscriber moved to a `SubscriberState` Protocol so a fan-out broker can serve N clients from one builder.

---

## Acceptance criteria

- All 6 pytest tests + 1 vitest test pass.
- Full gate (pytest `-n 4 --dist=loadfile` AND `vitest run` AND `npm run build`) green.
- Existing AD-722b WS tests continue to pass — diff is opt-in (default-ON but reverts to full on every Nth frame, so a test asserting full-snapshot shape every Nth wake still passes when N=1 or first-frame).
- Frame shape: `{"type": "snapshot", ...flat snapshot fields}` OR `{"type": "diff", "agent_id": ..., "changed": {...}}`.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-14)

```
grep -n "websocket.send_json" src/probos/routers/agents.py
  708:             await websocket.send_json(initial.to_dict())
  741:                 await websocket.send_json(snap.to_dict())

grep -n "def to_dict" src/probos/avatars/telemetry.py
  378:     def to_dict(self) -> dict[str, Any]:
  (returns 10-key dict — see lines 380-393)

grep -n "last_observed_at" src/probos/avatars/telemetry.py
  366:     last_observed_at: float
  388:             "last_observed_at": self.last_observed_at,
```

Frontend WS consumer location: Builder MUST grep `ui/src/` for `avatar-telemetry-stream` and pin the path before drafting Section 4 edits.
