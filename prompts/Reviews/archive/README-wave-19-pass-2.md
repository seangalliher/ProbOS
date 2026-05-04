# Wave 19 Pass-2 Review Sweep (2026-05-03)

**Verdict:** 1 ✅ Approved (AD-530 v1).

## Sweep Result

| Prompt | Pass-1 | Pass-2 | Notes |
|---|---|---|---|
| `ad-530-classification-gate-v1.md` | ❌ Not Ready (4 Req + 5 Rec + 4 Nits) | ✅ Approved | Direction inversion verified; all 13 findings resolved; 0 new phantoms; 0 regressions. |

## Tally

- Total Required-still-open across wave: **0** (target: 0). ✅
- New findings introduced by revision: **0** (target: 0). ✅
- Recommended Builder dispatch: single commit against `prompts/ad-530-classification-gate-v1.md` at `0770b52`.

## Safety Bug Catch — Pass-1

The pass-1 review caught a **direction-inversion bug** in the disclosure gate that would have shipped catastrophic data leakage:

- The original `if dst_lvl < src_lvl: BLOCK` matched operator intuition for *clearance* semantics (where higher index = stricter clearance).
- But `_CLASSIFICATION_LEVELS` at `records_store.py:27` encodes *openness* semantics (higher index = more broadly readable, confirmed at line 841 and read_document at lines 716–725).
- Combined with the original unsafe defaults (source default `ship`/2, dest default `ship`/2), the gate would have:
  - Blocked broadly-readable `ship` content from `department` viewers (false-positive flood when AD-530d wires gate into WardRoomService).
  - **Allowed `private` content to leak to `ship` and `fleet` audiences** (catastrophic data exfiltration; the entire reason for the gate's existence).
- Pass-1 also flagged the `api_key_like` regex's UUID/commit-hash collision, which would have turned the event channel into noise.

The revision (commit `0770b52`) correctly inverts the comparison to `dst_lvl > src_lvl` and adopts safe defaults (source→`private`/most-restrictive; dest→`ship`/broadest), which match the records_store openness semantics.

## Architect-Discretion Note

This is the canonical example of a bug class that **AD-685b's automated phantom-API precheck cannot catch.** AD-685b validates *symbol existence* (does the method exist? does the class exist? does the kwarg match?). It does NOT validate *semantic direction* (is the comparison operator correct given the hierarchy's encoding?).

Architect-discretion review remains the right defense for semantic-logic bugs in security-critical code. The pass-2 verdict here was reachable in two passes precisely because pass-1 caught the inversion early — before any source code was written, before any tests synthesized to match the inverted contract, and before any integration site (AD-530d) was scoped against the wrong direction.

**Recommendation:** Wave 19+ continues to gate security-package and authorization-path ADs (anything under `src/probos/security/`, `consensus/trust.py`, `experience/auth.py`, federation egress paths) through full architect review even after AD-685b is fully tooled. The cost of a single inverted comparison shipping is unbounded.

## Convention #15 Tolerance Status

- Pass-1: tolerance breached (4 Required + 5 Recommended on a single prompt).
- Pass-2: tolerance reset; pass-2 itself is clean (0 ⚠).
- Wave 19 sweep total: 0 prompts at ⚠ status, 1 prompt at ✅, 0 prompts at ❌. Wave-level tolerance budget intact for Wave 20+.

## Builder Dispatch

```
Prompt: prompts/ad-530-classification-gate-v1.md (commit 0770b52)
Status: ✅ Approved
Estimated tests: ~20 (Tests 1–18 + 7b + 9b + 16b)
Single commit: AD-530 v1 — Information Classification Enforcement (observational disclosure gate)
```

No further revision needed. Builder may proceed.
