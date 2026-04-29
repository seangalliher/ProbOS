# Review: AD-446 — Compensation & Recovery Pattern

**Verdict:** ⚠️ Conditional
**Headline:** Missing event type; depends on AD-445 wiring landing first.

## Required

1. **`EventType.COMPENSATION_TRIGGERED` does not exist.** Add to [src/probos/events.py](src/probos/events.py).

## Recommended

1. Dependency on AD-445 is correct, but the prompt should state explicitly: AD-445 must be built first so `DecisionQueue` is wired in `finalize.py` before this AD adds a peer.
2. `escalation_fn` failures are logged but not retried (correct per the log-and-degrade tier). Document this explicitly in the section docstring so reviewers don't flag it as a missing retry path.

## Nits

- `CompensationRecord` is intentionally non-frozen for history mutation — note this in a comment.
- History stored in-memory only — already noted; correct for MVP.

## Verified

- `RecoveryStrategy` enum defines RETRY / ESCALATE / ROLLBACK / ABANDON.
- Wiring pattern matches existing runtime service conventions.
- AD-445 prerequisite (DecisionQueue) confirmed as planned in the same wave.
