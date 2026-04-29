# Review: AD-445 — Decision Queue & Pause/Resume

**Verdict:** ⚠️ Conditional
**Re-review (2026-04-29 second pass): ⚠️ Conditional (effectively ✅ once AD-680 lands).** Both Required items resolved; only the AD-680-dependent `hasattr` Recommended remains.

**Headline:** Missing event type; governance directory must be created explicitly.

## Required

1. **`EventType.DECISION_QUEUE_PAUSED` does not exist.** Add to [src/probos/events.py](src/probos/events.py) near other governance events.
2. **`src/probos/governance/` does not exist.** Builder must create `src/probos/governance/__init__.py` (empty) before adding `decision_queue.py`. Add an explicit instruction step to the prompt; do not assume the directory.

## Recommended

1. The emit_fn wiring uses `hasattr(runtime, 'emit_event')`. Per AD-680, `runtime.emit_event` is a stable public method — call it directly without the `hasattr` defensive guard, or document why it's needed (cross-version support during AD-680 transition).

## Nits

- `QueuedDecision.state` and `resolved_at` are reassigned — confirm the dataclass is intentionally non-frozen.
- `DecisionQueue.pause_reason` exposes `_pause_reason` via property — public API exposure is the correct pattern.

## Verified

- `InitiativeEngine` exists at [src/probos/initiative.py:1](src/probos/initiative.py#L1) with `RemediationProposal` and `ActionGate`.
- `startup/finalize.py` wiring patterns at [lines 200-300](src/probos/startup/finalize.py#L200) match the proposed insertion.
- No conflicts with existing initiative code.

---

## Second-Pass Re-review (2026-04-29)

**Verdict:** ⚠️ Conditional (Required items fixed; one Recommended outstanding).

| Prior Item | Status | Evidence |
|---|---|---|
| Add `EventType.DECISION_QUEUE_PAUSED` | ✅ Fixed | Section 2 SEARCH/REPLACE inserts after `TOOL_PERMISSION_DENIED` at [events.py:164](src/probos/events.py#L164). |
| Explicit `governance/__init__.py` creation | ✅ Fixed | Section 1 now states: "If AD-676 has not been built first, the builder must create `src/probos/governance/__init__.py` (empty file)." |
| Drop `hasattr(runtime, 'emit_event')` defensive guard (Recommended) | ⚠️ Not addressed | Section 3 still has `emit_fn=runtime.emit_event if hasattr(runtime, 'emit_event') else None`. Since AD-680 has now landed (commit `73945d0`), the guard is dead code. |

Note: AD-680 is now ON MAIN. Strip the `hasattr` guard before building, or it ships as a permanent always-true branch. Otherwise ready.

---

## Third-Pass Re-review (2026-04-29)

**Verdict:** ✅ Approved.

| Prior Item | Status |
|---|---|
| `hasattr(runtime, 'emit_event')` guard | ✅ Removed — Section 3 wires `emit_fn=runtime.emit_event` directly. |

Ready for builder.
