# Wave 9C — Review Pass 1 Sweep Summary

**Date:** 2026-05-02
**Stage:** Stage 1 (Architect: Review Pass 1) of WAVE-9C-DISPATCH.md
**Scope:** 1 sub-AD (AD-641d, HIGH-risk; closes AD-641 umbrella issue #277).
**Tolerance (convention #15):** 1 ⚠️ allowed for the wave; 1 consumed.

---

## Verdict Table

| Sub-AD | Title | Risk | Pass-1 Verdict | Required | Recommended | Nits |
|---|---|---|---|---|---|---|
| AD-641d | Crew Deliberation Protocol | HIGH | ⚠️ Conditional | 4 | 4 | 3 |

**Total findings:** 4 Required + 4 Recommended + 3 Nits = 11.
**Verdict:** ⚠️ Conditional — fixable in one revision pass; convergence to ✅ expected at Stage 3.

---

## Cross-Wave Dependency Verification

| Dep | Source AD | Live Wiring | Verified | AD-641d Direct Calls |
|---|---|---|---|---|
| `runtime.observability_bridge` | AD-641a (commit 4476091) | [src/probos/startup/finalize.py:731](src/probos/startup/finalize.py#L731) | ✓ | **0** (v1 isolation) |
| `runtime.ward_room_hebbian_router` | AD-641b (commit a56b6c6) | [src/probos/startup/finalize.py:754](src/probos/startup/finalize.py#L754) | ✓ | **0** (Hebbian feedback deferred to AD-641d-iv) |
| `runtime.thread_priority_service` | AD-641c (commit c9860c5) | [src/probos/startup/finalize.py:814](src/probos/startup/finalize.py#L814) | ✓ | **0** (no priority interplay in v1) |

**Result.** All three Wave 9A/9B artifacts confirmed shipped at the expected runtime attribute names. AD-641d makes **zero direct calls** into any of them. The v1 isolation discipline mandated by the dispatch is honored exactly. Hard-stop #2 not triggered.

---

## Wave 9B Structural-Defect Pattern Recurrence

| Defect class | Source | Reproduced in AD-641d? | Notes |
|---|---|---|---|
| Async/sync mismatch | Wave 9A pass-2 | **No** | `emit_event` is sync; called sync. `create_thread`/`create_post` are async; awaited. |
| Wrong kwarg names | Wave 9A pass-2 | **No** | `create_thread`/`create_post` kwargs match live signatures verbatim. |
| Wrong row shape (`.payload` vs `["data"]`) | Wave 9A pass-2 | N/A | No `event_log.query*` usage. |
| Tree-vs-flat response shape | Wave 9B pass-1 | N/A | No `ward_room.get_thread` usage. |
| Missing field / per-author resolver | Wave 9B pass-1 | N/A | No department/author resolution. |
| Cross-wave attribute drift (`runtime.X.Y`) | Wave 9C dispatch (new) | N/A | No direct cross-wave attribute access. |

**Total reproductions: 0.** The pattern propagation that caught 5 defects in 641c's original draft did NOT recur in 641d. This is largely because 641d is structurally simple (one new module + one config + one wiring block) and the only live API consumed is `WardRoomService.create_thread` / `create_post` — both of which the author appears to have read directly.

**However:** the Wave 9B retrospective recommendation — *consumer prompts should include per-method-signature grep evidence in VAC, not just symbol existence* — has NOT been adopted by the AD-641d VAC (filed as Recommended #2). The proactive drafting pipeline remains hardened only against simple symbol-existence checks. The next prompt that consumes a tree-shaped or row-shaped API is likely to reproduce the pattern unless this recommendation becomes a hard procedural rule or the phantom-API pre-check is extended.

---

## Section 0 EventType Collision Check

| New type | Already in events.py? | Wave 9A collision? | Wave 9B collision? |
|---|---|---|---|
| `DELIBERATION_INITIATED` | No | No | No |
| `DELIBERATION_ARGUMENT_SUBMITTED` | No | No | No |
| `DELIBERATION_RESOLVED` | No | No | No |

**Wave 9A added (5):** `OBSERVABILITY_SNAPSHOT_PUBLISHED`, `OBSERVABILITY_BRIDGE_FAILED`, `WARD_ROOM_HEBBIAN_UPDATED`, `WARD_ROOM_HEBBIAN_DECAYED`, `ENGINEERING_SENSOR_REPORT`.
**Wave 9B added (3):** `LEARNED_SHORTCUT_REGISTERED`, `LEARNED_SHORTCUT_HIT`, `THREAD_PRIORITY_SCORED`.

**Result.** Three new types, all collision-free. Hard-stop #3 not triggered.

---

## Hard-Stop Audit

| # | Condition | Triggered? | Disposition |
|---|---|---|---|
| 1 | Phantom API not introduced by the prompt | No | Section 0 introduces 3 EventTypes; Section 2 introduces all dataclasses/protocol. |
| 2 | Cross-wave dep claim mismatch | No | Zero direct calls; v1 isolation honored. |
| 3 | EventType collision | No | 3 new types, all absent from events.py. |
| 4 | v1 absorbs >4 capabilities | Borderline | Currently 4 (lifecycle, resolve+outcome, endorse, persistence); Required #3 reduces to 3 by deferring `endorse` to AD-641d-v. Not over the wall. |
| 5 | Conflicts with existing Captain paths | No | `_from_captain` flag and `captain_engagement.py` are queue/quality concerns; deliberation is an explicit RPC-shaped surface with no semantic overlap. |

**Zero hard-stops triggered.** Wave 9C is on track for build dispatch after one revision pass.

---

## Top Failure Modes (if Required not applied before build)

1. **Build will fail at startup.** Section 4 wiring references `DeliberationProtocol` without an inline import. `runtime.deliberation_protocol = DeliberationProtocol(...)` raises `NameError` at finalize_startup(). Required #1.

2. **Test for `default_channel_id` cannot be written meaningfully.** Required #2's dead-code config field has no behavioral pathway to assert against. The Builder will either silently drop the field, or write a test that asserts the config defaults but never that the value reaches `initiate()`. Either is theater.

3. **`endorse()` test (Test #15: `test_endorse_returns_true_for_known_argument_false_for_unknown`) is a tautology.** It tests the validator wrapped around `_sessions[id].arguments`, not endorsement. If endorsement is meant to do anything, the test asserts nothing meaningful. Required #3.

4. **DECISIONS.md entry will be ad-libbed.** Required #4: without an inline draft block, the Builder writes the rationale from scratch, drifting from the dispatch's intent ("documenting arbitration semantics"). Captain-protocol convention violated.

---

## Phantom-API Pre-Check Output

```
=== prompts/ad-641d-crew-deliberation-protocol.md ===
  (not run by reviewer; will run post-revision per Stage 2 dispatch)
```

The architect-discretion sweep (this review) found no phantom symbols. The only candidates would be `runtime.observability_bridge` / `runtime.ward_room_hebbian_router` / `runtime.thread_priority_service` references — but those appear only in the **Dependencies** prose header as context anchors, not in any code block. Same legitimate cross-prompt anchor pattern documented in Wave 9A pass-2 (the `runtime.observability_bridge` anchor in 641b's Section 5). Documentation only. Zero functional consumption. **0 real phantoms predicted.**

---

## Pattern Lessons (for the umbrella retrospective)

1. **HIGH-risk, single-prompt waves benefit from isolation discipline.** AD-641d's "v1 ships nothing that depends on Wave 9A/9B implementations" was the right call — it produced the cleanest cross-wave dep audit of the entire Wave 9 series (zero direct calls). The Hebbian-feedback grandchild defer (AD-641d-iv) is the lever that bought the isolation.

2. **No-theater discipline catches dead config + dead methods.** Three of the four Required findings (#2, #3, partial #1's logger.info) are no-theater violations: a config field that doesn't reach behavior, a method that doesn't do what its docstring claims, a wiring block missing its audit-log line. The convention #14 sweep is the mechanism that catches these; absent it, all three would ship as v1 surface area with no tests proving real behavior.

3. **Captain-protocol DECISIONS.md entries should be drafted by the architect, not described.** Required #4. The Wave 8.5 dispatch convention exists precisely because Captain-arbitration semantics are the kind of decision that drifts under Builder ad-lib. Pre-drafting the entry locks the semantics into the prompt and makes the Builder a copy-paste consumer rather than an interpreter.

4. **Pre-deferral envelope is real.** Currently 4 capabilities + 4 deferred = at the upper edge. Required #3(a) brings it to 3 + 5 = inside the envelope cleanly. The dispatch's "2-3 capabilities, 4-5+ deferred" framing is operationally correct; v1 prompts that drift to 4+ capabilities are signaling that one of them is theater.

---

## Convergence Outlook for Stage 3 (Pass-2)

| Item | Forecast |
|---|---|
| Verdict | ✅ Approved |
| Required still open | 0 |
| New findings | 0 (architect-discretion sweep already done) |
| Tolerance reservation | Consumed in pass-1 (1 ⚠️); not available pass-2 |
| Phantom-API pre-check | 0 |

**Convergence target.** 1 ✅ at pass-2. The 4 Required findings are mechanical, scoped, and the revision pattern is identical to Wave 9A 641a / Wave 9B 641c (apply Required, fold Recommended, judgment-call Nits).

---

## Recommended Next Step

`./scripts/wave-orchestrator.ps1 advance` — proceed to Stage 2 (Architect: Revision Pass).
