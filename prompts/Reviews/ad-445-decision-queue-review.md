# Review: AD-445 — Decision Queue & Pause/Resume

**Verdict:** ⚠️ Conditional
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
