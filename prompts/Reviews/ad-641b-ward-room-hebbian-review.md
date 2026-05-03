# Review: AD-641b — Ward Room Hebbian Learning

**Reviewer:** Architect
**Date:** 2026-05-02
**Verdict:** ❌ Not Ready (1 Required dead-code violation; 2 Recommended)

## Required (must fix before building)

1. **`WardRoomEndorsementListener` ships with no caller — convention #7 (no theater) violation.** Section 5 constructs `runtime.ward_room_endorsement_listener = WardRoomEndorsementListener(router=...)` but no code path in v1 ever calls `listener.handle_event(payload)`. Verified by grep:

   ```
   grep -rn "event_log\.subscribe\|register_handler\|add_event_handler" src/probos/
     (no matches — runtime has no event-bus subscription API)

   grep -n "WARD_ROOM_ENDORSEMENT" src/probos/ward_room/messages.py
     597: self._emit(EventType.WARD_ROOM_ENDORSEMENT, {...})
     (the event is emitted via EventEmitterMixin, but nothing structural subscribes to it)
   ```

   The Solution Overview promises "endorsement listener wires `WARD_ROOM_ENDORSEMENT` events" and the v1-deliverables bullet says "Real `record_contribution` ... with a real signal source (endorsement events)" — but in v1 as drafted, the listener is a stranded object on `runtime` with no signal source wired. Tests in Section 6 only exercise `handle_event(payload)` directly, which proves the unit but does not prove the integration. Builder will produce 14 passing tests for a listener that never runs.

   **Three acceptable fixes (architect picks one or surfaces to dispatching architect):**

   - **(a)** Modify `src/probos/ward_room/messages.py` to call `runtime.ward_room_endorsement_listener.handle_event(payload)` immediately after the `WARD_ROOM_ENDORSEMENT` emit at line 597, gated on `if runtime.ward_room_endorsement_listener is not None`. Adds one-line touchpoint to `messages.py` (currently in the `What This Does NOT Change` boundary — needs to come out, or the boundary line needs adjustment). Lowest-risk, smallest source diff.
   - **(b)** Defer the listener wholesale to a new grandchild `AD-641b-iv: endorsement event subscription` and ship v1 with the router only. Manual `record_contribution()` calls become the v1 signal source for tests; deferred grandchild adds the listener and its subscription path. Most honest, smallest scope; reduces v1 from "3 capabilities" to "2".
   - **(c)** Reframe the prompt to introduce a generic event-bus subscription API on `runtime` (e.g., `runtime.subscribe_event(EventType.WARD_ROOM_ENDORSEMENT, listener.handle_event)`). This is a substantive cross-cutting addition; should NOT happen as part of 641b — surface to dispatching architect for a separate AD if option (a) and (b) are rejected.

   Recommend option (b): defer the listener to a grandchild AD. It honors `What This Does NOT Change` cleanly, ships honest v1 functionality (the router), and explicitly tracks the gap.

## Recommended

R1. **`top_contributors` does not filter zero-weight entries.** Section 2 returns `[(agent, weight) for (t, agent), weight in self._weights.items() if t == str(topic)]` then sorts desc and slices. After `decay()` runs many times, weights asymptotically approach zero but never delete; `top_contributors` keeps returning ghost entries. Add `if weight > 0` filter to the comprehension. One-line change; relevant for grandchild `AD-641b-iii` (decay cadence) but cheap to ship now.

R2. **No verification that mesh `HebbianRouter` is structurally compatible with the Ward Room version's API shape.** The Solution Overview claims "Same math as mesh Hebbian, separate instance and storage" and the dispatch summary lists `record_contribution` / `get_weight` / `top_contributors` / `decay` as the API. Add a footer grep confirming `class HebbianRouter` exposes corresponding methods (or document divergences explicitly). If mesh router uses `update_weight` and Ward Room uses `record_contribution`, that's a deliberate divergence worth one prose line in Solution Overview.

   ```
   grep -n "def record_contribution\|def update_weight\|def get_weight\|def top_contributors\|def decay" src/probos/mesh/routing.py
   ```

   Either confirm shape match or document divergence in the prompt's Solution Overview.

## Nits

- N1. Section 3 `handle_event` rejects unknown endorsement values silently (returns `False`). For tests-as-documentation purposes, Section 6 should add a 15th test: `test_listener_rejects_unknown_endorsement_value` (e.g., `endorsement="sideways"` returns False with no router call). Defensive boundary coverage per convention #18 spirit.
- N2. Section 2 `record_contribution` accepts `signal: float = 1.0` but the listener (Section 3) only ever passes `1.0` or `-1.0`. The float-typed signature suggests calibrated-strength endorsements (e.g., `0.5` for weak endorsement) but no caller exploits it in v1. Either narrow the signature to `Literal[-1.0, 1.0]` for v1 honesty, or document the deferred capability ("calibrated signal strength — `AD-641b-v`").

## Verified Against Codebase (2026-05-02)

```
grep -n "class HebbianRouter" src/probos/mesh/routing.py
  39: class HebbianRouter:

grep -n "WARD_ROOM_ENDORSEMENT" src/probos/events.py
  69:  WARD_ROOM_ENDORSEMENT = "ward_room_endorsement"

grep -n "WARD_ROOM_HEBBIAN_UPDATED\|WARD_ROOM_HEBBIAN_DECAYED" src/probos/events.py
  (no matches; introduced by this prompt — not a phantom)

grep -n "self\.ward_room_router" src/probos/runtime.py
  393:  self.ward_room_router: WardRoomRouter | None = None
  1658: self.ward_room_router = fin.ward_room_router

grep -n "WardRoomHebbian\|ward_room_hebbian\|topic_crew" src/probos/
  (no matches; new module — not a phantom)

grep -n "WARD_ROOM_ENDORSEMENT" src/probos/ward_room/messages.py
  597: self._emit(EventType.WARD_ROOM_ENDORSEMENT, {...})

grep -rn "event_log\.subscribe\|register_handler\|add_event_handler\|subscribe_event" src/probos/
  (no matches — confirms there is NO event-bus subscription API; the listener has no caller)
```

Cross-prompt dependency check:

- AD-641b's prompt body references `runtime.observability_bridge` only in Section 5 anchor-prose ("after AD-449's `runtime.mcp_bridge` or AD-641a's `runtime.observability_bridge` if 641a lands first"). This is documentation, not a code dependency. Builder can land 641b in any order relative to 641a — finalize.py append anchors stack independently.
- The Wave 9A dispatch description's framing of 641b as "consumer of `runtime.observability_bridge`" is **overstated**. There is no functional cross-prompt source dep. This is the canonical Wave 8.5-classified false positive.

## Convention audit (19 standing conventions)

| # | Convention | Status |
|---|---|---|
| 1 | Public-attribute wiring | ✅ `runtime.ward_room_hebbian_router` and `runtime.ward_room_endorsement_listener` are public |
| 2 | stdlib persistence | ✅ in-memory v1; SQLite deferred to AD-641b-i |
| 3 | Coordinator first | ✅ router is the coordinator; persistence/integration deferred |
| 4 | Superset filter | ✅ N/A |
| 5 | startup `emit_event_fn` | ✅ uses `runtime.emit_event` |
| 6 | verify-first | ⚠️ — R2 (mesh router shape comparison missing) |
| 7 | **No theater** | ❌ — listener has no caller (Required #1) |
| 8 | TYPE_CHECKING | ✅ N/A |
| 9 | ASCII-only comments | ✅ |
| 10 | work_item_store | ✅ N/A |
| 11 | `__new__`-bypass `getattr` | ✅ N/A (no runtime stub access in core service) |
| 12 | Solution Overview drift | ⚠️ — Solution Overview promises listener wired to events; reality is unwired |
| 13 | Pool template collision | ✅ N/A |
| 14 | Aggressive pre-deferral | ✅ 3 v1 / 3 deferred (would drop to 2 / 4 under fix-option-b) |
| 15 | Relaxed tolerance | — already used by 641a; this prompt cannot use it |
| 16 | Phantom-API pre-check | ✅ ran; 3 false positives documented |
| 17 | Per-instance mutable state in `__init__` | ✅ `_weights`, `_learning_rate`, `_decay_factor` |
| 18 | Mock all attributes | ✅ — listener tests pass real router (convention #11 honored) |
| 19 | Session-id in headers | ✅ N/A |

## Disposition

641b's router half is honest and well-scoped — Hebbian math, in-memory storage, public attribute wiring, real event emission. The router alone would be ✅ Approved. The listener half breaks the no-theater rule (#7) by shipping an object with no caller; the Solution Overview drift (#12) compounds it by claiming integration that doesn't exist. The fix is not architectural — option (b) (defer the listener to grandchild AD-641b-iv, ship router only) takes ~10 lines of prompt edits and resolves both Required and #12-drift cleanly.

Wave 9A's relaxed tolerance reservation (convention #15) is consumed by 641a's Section 4 prose-block fix; 641b cannot use it. Verdict ❌ Not Ready until Section 5/6 + Solution Overview are reframed.

**Hard-stop check (per dispatch §4):** This is a no-theater violation, not a phantom-API surface. Not a hard-stop in the dispatch's strict sense, but the prompt cannot ship as drafted — Builder will produce 14 green tests for dead code, and a future AD will have to rip out the unwired listener anyway. Surface to revision pass.

---
