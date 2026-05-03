# Wave 9A Review Pass 2 — Sweep Summary

**Reviewer:** Architect
**Date:** 2026-05-02
**Pass:** 2 of 2
**Prompts re-reviewed:** 3 (AD-641a, AD-641b, AD-641f)
**Convergence target:** 3 ✅ — **MET**

## Verdict Table

| # | Prompt | Pass-1 | Pass-2 | Required-still-open | New findings |
|---|---|---|---|---|---|
| 1 | [`ad-641f-engineering-chief-observability.md`](../ad-641f-engineering-chief-observability.md) | ✅ Approved | ✅ Approved | 0 | 0 |
| 2 | [`ad-641a-observability-bridge.md`](../ad-641a-observability-bridge.md) | ⚠️ Conditional | ✅ Approved | 0 | 0 |
| 3 | [`ad-641b-ward-room-hebbian.md`](../ad-641b-ward-room-hebbian.md) | ❌ Not Ready | ✅ Approved | 0 | 0 |
| | **Totals** | 1 ✅ / 1 ⚠️ / 1 ❌ | **3 ✅ / 0 ⚠️ / 0 ❌** | **0** | **0** |

**Convergence target met.** Tolerance reservation (convention #15) released back unused — no ⚠️ verdicts in pass-2.

## Resolution Audit Summary

| Prompt | Required resolved | Recommended applied | Nits dispositioned | Architect-discretion repairs |
|---|---|---|---|---|
| 641f | n/a (0) | 3/3 | 2/2 | 0 |
| 641a | 1/1 | 3/3 | 3/3 | **3** (critical: async `query_structured`, `event=` param, dict row shape) |
| 641b | 1/1 | 2/2 | 2/2 (1 moot, 1 deferred) | 0 |

### Architect-Discretion Verify-First Repairs (641a)

The 641a revision caught and fixed three latent live-API mismatches that pass-1 review missed. These would have surfaced at first Builder test run; catching them in spec saved cycles:

1. `take_snapshot` is async (sync caller would have raised `TypeError: object coroutine ... can't be awaited`).
2. `query_structured(event=...)` parameter — original draft used `query(event_type=...)` which doesn't exist (would have raised `TypeError: unexpected keyword argument`).
3. Row shape — rows are dicts with `data` key, not objects with `.payload` (would have raised `AttributeError`).

This is the value-add the revision pass exists to surface. No new findings — these are discoveries, not regressions.

## Phantom-API Pre-check Output

```
=== prompts/ad-641a-observability-bridge.md ===
  Clean — no phantom symbols detected.

=== prompts/ad-641b-ward-room-hebbian.md ===
  1 phantom symbol(s):
    - runtime.observability_bridge

=== prompts/ad-641f-engineering-chief-observability.md ===
  Clean — no phantom symbols detected.

Total phantom candidates: 1
```

**Disposition:** The single 641b phantom (`runtime.observability_bridge`) is the legitimate cross-prompt anchor-prose reference in Section 5 startup-wiring placement instruction ("after AD-449's `runtime.mcp_bridge` or AD-641a's `runtime.observability_bridge` if 641a lands first"). Documentation only — 641b never functionally consumes the bridge. Pass-1 already classified this correctly. **0 real phantoms.**

## Recommended Builder Order

**641a → 641b → 641f**

Rationale: 641a INTRODUCES `runtime.observability_bridge`; 641b's anchor-prose reference is satisfied if 641a lands first (cleaner finalize.py append history). The dependency is soft — Builder may interleave if expedient — but the anchor-first order produces the most legible commit log. 641f is independent and may land any time.

## Wave 9B Implication Note (verification point #5)

**No cascading concern from the AD-641b listener defer.** Verified by grep:

```
grep -n "listener|EndorsementListener|handle_event|ward_room_endorsement_listener" \
  prompts/ad-641c-ward-room-thread-priority.md \
  prompts/ad-641e-learned-shortcut-abstraction.md
  (no matches in either)
```

Neither Wave 9B prompt depends on `WardRoomEndorsementListener` or `runtime.ward_room_endorsement_listener`. The listener defer is isolated to 641b's grandchild `AD-641b-iv`. **No Wave 9B pre-flight revision required.**

The dispatching architect should still note for Wave 9B drafting: any new prompt proposing a listener that consumes `WARD_ROOM_ENDORSEMENT` events must either (a) modify the emit-side at `src/probos/ward_room/messages.py:597` to call the listener directly, OR (b) wait for AD-641b-iv (which itself waits for either a generic event-bus subscribe API or the same emit-side wiring). This is the canonical no-theater pattern lesson from Wave 9A pass-1.

## Pattern Lessons (for future waves)

1. **Verify-first repairs catch latent bugs.** 641a's revision found three live-API mismatches the pass-1 review missed. Future review checklists should explicitly grep async/sync signatures and parameter names of any method called via `await` in a prompt.
2. **Defer-to-grandchild is the cleanest fix for no-theater violations.** 641b's listener was unwired in v1 because no event-bus subscribe API exists. Defer was 10 lines of prompt edits and produced an honest 2-capability v1 with explicit forcing function for the grandchild.
3. **Anchor-prose cross-prompt deps are not phantom APIs.** `runtime.observability_bridge` in 641b's Section 5 startup-wiring placement instruction is documentation, not code. The phantom-API pre-check correctly flags it; architect judgment correctly classifies it as a false positive. This is the canonical Wave 8.5 pattern.

## Convergence

**3 ✅ / 0 ⚠️ / 0 ❌ — wave 9A approved for build.** Builder may proceed with the 3 prompts in the recommended order (641a → 641b → 641f).

The tolerance reservation (convention #15) was consumed by 641a in pass-1 (Section 4 prose-block gap) but is **released back unused in pass-2** because all three prompts converge to ✅ without any ⚠️ verdicts.
