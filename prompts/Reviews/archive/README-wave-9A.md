# Wave 9A Review Pass 1 — Sweep Summary

**Reviewer:** Architect
**Date:** 2026-05-02
**Pass:** 1 of 2
**Prompts reviewed:** 3 (AD-641a, AD-641b, AD-641f)

## Verdict Table

| # | Prompt | Verdict | Required | Recommended | Nits |
|---|---|---|---|---|---|
| 1 | [`ad-641f-engineering-chief-observability.md`](../ad-641f-engineering-chief-observability.md) | ✅ Approved | 0 | 3 | 2 |
| 2 | [`ad-641a-observability-bridge.md`](../ad-641a-observability-bridge.md) | ⚠️ Conditional | 1 | 3 | 3 |
| 3 | [`ad-641b-ward-room-hebbian.md`](../ad-641b-ward-room-hebbian.md) | ❌ Not Ready | 1 | 2 | 2 |
| | **Totals** | 1 ✅ / 1 ⚠️ / 1 ❌ | **2** | **8** | **7** |

## Tolerance ledger (convention #15)

Wave 9A allows 1 ⚠️ on the highest-risk prompt. Reservation **consumed** by 641a (Section 4 prose-block gap, mechanical Builder-friendliness fix). 641b cannot use the reservation; it requires a substantive revision before pass-2.

## Cross-prompt verification (high-priority dispatch points)

### 1. `runtime.observability_bridge` cross-prompt direction — verified clean

| Claim | Verified | Evidence |
|---|---|---|
| AD-641a INTRODUCES `runtime.observability_bridge` as public attribute | ✅ | Section 4 wires `runtime.observability_bridge = ObservabilityBridge(...)` |
| AD-641b READS `runtime.observability_bridge` and does NOT introduce | ✅ partial | Reference in 641b is anchor-prose only — no functional consumption. The Wave 9A dispatch description's "consumer dep" framing is overstated; there is no source-code dependency. |
| Builder order 641a → 641b in dispatch | ✅ | Documented in dispatch Stage 5; cross-prompt dep is soft (anchor-only). Either order works. |

The "soft consumer dep" terminology from Wave 8.5 is the correct framing. Hard-stop #4 (dependency direction inverted) does not trigger.

### 2. Verify-first footer compliance per prompt

| Prompt | Footer present | Concrete claims grep-confirmed | Gaps |
|---|---|---|---|
| 641f | ✅ | 7/7 | none |
| 641a | ✅ | 9/11 | `event_log.query` signature (R1), `SystemConfig.mcp` field placement (R3) |
| 641b | ✅ | 7/7 | mesh `HebbianRouter` API shape comparison (R2) |

### 3. Section 0 EventType collision check

| EventType | Prompt | Pre-existing in `events.py`? | Collision with sibling? |
|---|---|---|---|
| `OBSERVABILITY_SNAPSHOT_PUBLISHED` | 641a | ❌ no | ❌ no |
| `OBSERVABILITY_BRIDGE_FAILED` | 641a | ❌ no | ❌ no |
| `WARD_ROOM_HEBBIAN_UPDATED` | 641b | ❌ no | ❌ no |
| `WARD_ROOM_HEBBIAN_DECAYED` | 641b | ❌ no | ❌ no |
| `ENGINEERING_SENSOR_REPORT` | 641f | ❌ no | ❌ no |

Verified by:

```
grep -n "OBSERVABILITY\|WARD_ROOM_HEBBIAN\|ENGINEERING_SENSOR" src/probos/events.py
  (no matches — all 5 are introduced by Wave 9A)
```

No collisions. Hard-stop #3 does not trigger.

### 4. Aggressive pre-deferral (convention #14)

| Prompt | v1 capabilities | Deferred grandchildren | Compliance |
|---|---|---|---|
| 641a | 3 (vitals / pool / attention) | 3 (Hebbian feed, HXI, Captain alert) | ✅ — R2 suggests bumping to 4 grandchildren (`AttentionManager.snapshot()`) |
| 641b | 3 (router math, in-mem storage, listener-construction) | 3 (SQLite, router integration, decay tuning) | ⚠️ — under fix-option-b drops to 2 v1 / 4 deferred |
| 641f | 3 (pool / capability / gossip) | 3 (per-peer gossip, registry mutation, failover) | ✅ |

All three respect the 3-4 v1 / 3-4 deferred discipline. None absorb >5 capabilities — no theater-by-overload risk.

### 5. Wave 8 conventions #17 / #18 / #19

| Convention | 641a | 641b | 641f |
|---|---|---|---|
| #17 (per-instance mutable state in `__init__`) | ✅ | ✅ | ✅ |
| #18 (httpx.Response mocks) | ✅ N/A | ✅ N/A | ✅ N/A (no httpx in any of the three) |
| #19 (session-id in headers) | ✅ N/A | ✅ N/A | ✅ N/A (no JSON-RPC) |

All three are clean on the Wave 8-derived conventions.

## Top failure modes

A single failure mode dominates pass-1: **Solution Overview drift on listener / wiring half-shipped (#7 + #12)**. Specifically:

- 641b's listener half ships an object with no caller — the no-theater violation. Solution Overview promises an integrated signal source; Section 5 constructs an unconnected listener. Fix-option-b (defer to grandchild) cleans this up cleanly without expanding scope.
- 641a's Section 4 wiring is prose-only — not a theater violation, but a Builder-friendliness gap. Sibling prompts (641b, 641f) provide python code blocks; 641a relies on Builder reverse-engineering the house pattern.

Both are fixable in revision pass without architectural changes. **Pattern lesson for future Wave dispatches:** when a prompt promises "wired to X events" in its Solution Overview, the audit checklist should explicitly verify the runtime has a subscribe/dispatch mechanism for X — there is no global event-bus subscription API in ProbOS today (every event consumer is constructor-injected via `on_event` callback or `emit_event_fn`). Future prompts proposing event-driven listeners must either (a) modify the emitting code to call the listener directly, (b) defer the listener wholesale, or (c) introduce the subscription mechanism in a separate cross-cutting AD.

## Pass-2 expectations

If revision applies cleanly:

| Prompt | Expected pass-2 verdict | Predicted issues |
|---|---|---|
| 641f | ✅ Approved (confirms recommendations applied) | none — already approved |
| 641a | ✅ Approved (after Section 4 code block + R2 grandchild + R1/R3 grep additions) | none expected |
| 641b | ✅ Approved (after fix-option-b: defer listener, ship router-only v1) | re-verify Solution Overview alignment with 2-cap v1 |

Convergence target: 3 ✅ + 0 ⚠️. Tolerance reservation should be released back unused once 641a's Section 4 has a real code block.

## Recommended Builder order (post-revision)

1. **AD-641f** (independent, lowest blast radius, already approved)
2. **AD-641a** (introduces `runtime.observability_bridge`)
3. **AD-641b** (router-only after fix-option-b; finalize anchor sequencing prefers 641a first but is no longer functionally required)

Hard ordering constraint: **none.** Wave 8.5's "all three parallel-safe" classification holds.

## Files Created (this commit)

```
prompts/Reviews/ad-641f-engineering-chief-observability-review.md
prompts/Reviews/ad-641a-observability-bridge-review.md
prompts/Reviews/ad-641b-ward-room-hebbian-review.md
prompts/Reviews/README-wave-9A.md   (this file)
```

No source files modified.
