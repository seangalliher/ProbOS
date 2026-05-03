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

## Second-Pass Review (2026-05-02)

**Verdict:** ✅ Approved

Convergence reached. The Required no-theater violation is resolved via fix-option (b) — the unwired `WardRoomEndorsementListener` is wholesale-deferred to grandchild `AD-641b-iv`, and v1 ships the router only. Both Recommended applied; both Nits dispositioned cleanly.

### Resolution Audit

| Pass-1 Required | Status | Evidence in revised prompt |
|---|---|---|
| #1 — Listener wholesale-deferred (fix-option b) | ✅ Resolved | Comprehensive defer applied across all 7 prompt surfaces:<br>• **Solution Overview:** v1-deliverables now reads "router only — 2 of 6 capabilities ship"; deferred grandchildren count rises to 4 with `AD-641b-iv` added (explicit forcing function: ProbOS event-bus subscribe API OR direct emit-side wiring at `messages.py:597`).<br>• **Dependencies header:** dropped consumer claim; added mesh-router API divergence note.<br>• **Section 1 (`__init__.py`):** dropped `WardRoomEndorsementListener` import + `__all__` entry. Confirmed: only `WardRoomHebbianRouter` exported.<br>• **Section 3:** former listener implementation block replaced with deferral stub explaining v1 signal source (direct `record_contribution()` calls) + forcing function.<br>• **Section 5 (startup wiring):** dropped listener construction + `else` reset. Confirmed by reading: only `runtime.ward_room_hebbian_router` is set.<br>• **Section 6 (tests):** test count drops from ~14 to ~11; tests 12/13/14 (listener `handle_event` tests) removed.<br>• **Acceptance Criteria:** explicit forbid-line: "`WardRoomEndorsementListener` is NOT shipped (deferred to AD-641b-iv); no `listener.py` file under `src/probos/cognitive/ward_room_hebbian/`; no `ward_room_endorsement_listener` attribute is set on the runtime in v1." |

| Pass-1 Recommended | Status | Notes |
|---|---|---|
| R1 — `top_contributors` filters zero-weight | ✅ Applied | Section 2 router code: `if t == str(topic) and weight > 0.0`. Test 10 description updated to assert zero-weight filter explicitly. |
| R2 — mesh router API divergence documented | ✅ Applied | Solution Overview bullet 1: "mesh routes `(source_agent → target_agent)` co-activation while Ward Room routes `(topic → agent)` contribution. Method names differ accordingly (`record_contribution` vs `record_interaction`, `decay` vs `decay_all`); this is documented divergence, not duplication." Footer revision pass adds `grep -n "def record_interaction\|def decay_all\|def get_weight" src/probos/mesh/routing.py` confirming live mesh API at `routing.py:96, 142, 188`. |

| Pass-1 Nit | Status | Notes |
|---|---|---|
| N1 — `test_listener_rejects_unknown_endorsement_value` | 📦 Moot (deferred) | Test ships with AD-641b-iv when the listener lands. Removal noted in revision summary. |
| N2 — calibrated-strength signal | 📦 Deferred (judgment) | `signal: float` signature kept; calibrated-strength endorsements ship with AD-641b-iv (or successor) when listener lands. Documented in revision summary. |

### Listener-Defer Completeness Audit (pass-2 verification point #1)

Per the dispatch's high-priority verification list, all 6 sub-checks pass:

| Check | Status | Evidence |
|---|---|---|
| Listener no longer constructed in `__init__` or Section 2/3 code | ✅ | Section 2 router has no listener; Section 3 is deferral stub (text only, no code block). |
| Section 3 is deferral stub | ✅ | "The original Section 3 introduced a `WardRoomEndorsementListener` ... wholesale-deferred to grandchild AD-641b-iv." |
| Section 5 startup wiring no longer references listener | ✅ | Only `runtime.ward_room_hebbian_router = WardRoomHebbianRouter(...)` is wired; no listener assignment. |
| Test count dropped from 14 to 11 | ✅ | Section 6 lists 11 tests (1-11); revision summary explicitly states "Test count drops from ~14 to ~11. Tests 12/13/14 wholesale-removed." |
| Solution Overview / Dependencies / v1-deliverables don't claim listener ships in v1 | ✅ | Solution Overview bullet 2 dropped; v1-deliverables reads "router only — 2 of 6 capabilities ship"; Dependencies header rewritten to drop consumer claim. |
| Listener references confined to deferred section + revision bullet + acceptance forbid-line | ✅ | Confirmed by inline footer self-check grep in revision: "only appears in Section 3 deferral stub, Required-#1 revision bullet, and acceptance-criteria forbid-line — all intentional." |

### Cross-Prompt Dependency

The single phantom flagged by the pre-check (`runtime.observability_bridge` in 641b) is the legitimate cross-prompt anchor-prose reference in Section 5 startup-wiring placement instruction ("after AD-449's `runtime.mcp_bridge` or AD-641a's `runtime.observability_bridge` if 641a lands first"). Documentation only; no functional dependency. Pass-1 already classified this correctly. Builder order 641a → 641b → 641f stands as soft preference, not hard requirement.

### Wave 9B Implication Scan (pass-2 verification point #5)

Verified by grep:

```
grep -n "listener|EndorsementListener|handle_event|ward_room_endorsement_listener" prompts/ad-641c-ward-room-thread-priority.md
  (no matches)

grep -n "listener|EndorsementListener|handle_event|ward_room_endorsement_listener" prompts/ad-641e-learned-shortcut-abstraction.md
  (no matches)
```

Neither Wave 9B prompt depends on the deferred listener. Listener defer is isolated to 641b. **No Wave 9B pre-flight concern.**

### New Findings

None.

### Verified Against Revised Codebase Claims

- No event-bus subscribe API exists: `grep -rn "event_log\.subscribe\|register_handler\|add_event_handler\|subscribe_event" src/probos/` returns 0 matches. ✅ confirms no-theater rationale.
- Mesh router API divergence: `src/probos/mesh/routing.py:96` (`record_interaction`), `:142` (`get_weight`), `:188` (`decay_all`) confirmed live. ✅
- `WARD_ROOM_ENDORSEMENT` emit anchor: `src/probos/ward_room/messages.py:597` confirmed live. ✅ (forcing-function anchor for AD-641b-iv).

### Convention Audit (delta from pass-1)

| # | Convention | Pass-1 | Pass-2 |
|---|---|---|---|
| 6 | verify-first | ⚠️ (R2 gap) | ✅ resolved (footer revision pass) |
| 7 | **No theater** | ❌ (listener no caller) | ✅ resolved (listener deferred) |
| 12 | Solution Overview drift | ⚠️ (claimed listener integration) | ✅ resolved (overview reframed to router-only) |
| 14 | Aggressive pre-deferral | ✅ (3/3) | ✅ (2 v1 / 4 deferred) |

All 19 conventions ✅.

### Disposition

641b converges to ✅ via the cleanest fix-option (defer-to-grandchild). The router half — Hebbian math, in-memory storage, real event emission, public attribute wiring — was already honest in pass-1; the revision strips the unwired listener half rather than papering over it. The forcing function for AD-641b-iv is concrete and architecturally sound (the listener ships when ProbOS introduces an event-bus subscribe API OR when the emit-side at `messages.py:597` is modified to call the listener directly). Approve for build.
