# Wave 9B Review Pass 2 — Sweep Summary

**Reviewer:** Architect
**Date:** 2026-05-02
**Pass:** 2 of 2
**Prompts re-evaluated:** 2 (AD-641c, AD-641e)
**Order:** AD-641e → AD-641c (per dispatch — smallest blast radius first).

## Verdict Table

| # | Prompt | Pass-1 | Pass-2 | Required still open | New findings | Recommended Builder order |
|---|---|---|---|---|---|---|
| 1 | [`ad-641e-learned-shortcut-abstraction.md`](../ad-641e-learned-shortcut-abstraction.md) → [review](ad-641e-learned-shortcut-abstraction-review.md) | ✅ Approved | ✅ Approved | 0 | 0 (1 micro-inconsistency Nit, non-blocking) | **1st** (purely cognitive layer; smallest blast radius) |
| 2 | [`ad-641c-ward-room-thread-priority.md`](../ad-641c-ward-room-thread-priority.md) → [review](ad-641c-ward-room-thread-priority-review.md) | ❌ Not Ready | ✅ Approved | 0 | 0 (1 editorial nit, 1 Builder-discretion item, both non-blocking) | **2nd** (cross-cutting; touches event_log + ward_room + config + startup) |
| | **Totals** | | **2 ✅ / 0 ⚠️ / 0 ❌** | **0** | **0 substantive** | |

## Convergence Target

**Met.** Pass-2 forecast was 2 ✅ / 0 ⚠️ / 0 ❌; pass-2 actual is 2 ✅ / 0 ⚠️ / 0 ❌. The relaxed-tolerance reservation (1 ⚠️ allowed on highest-risk prompt) was **not consumed**.

## Per-Prompt Resolution Audit (compact)

### AD-641e (✅ Approved → ✅ Approved)

| Pass-1 item | Tier | Status |
|---|---|---|
| R1 size-property comment | Recommended | ✅ Applied |
| R2 minimal-stub structural-typing test (#4b) | Recommended | ✅ Applied |
| R3 read-side fan-out semantics doc | Recommended | ✅ Applied |
| N1 AD-274 reference replaces "AD: existing" | Nit | ✅ Applied |
| N2 logger.debug instead of bare `pass` | Nit | ✅ Applied |
| N3 #13 `WorkflowCache` public-API regression test | Nit | ✅ Applied |

**0 new substantive findings.** One internal-consistency nit on test count framing (acceptance criteria says "13/13" but Section 6 enumerates 14 test functions if 4b is treated as separate `def`). Resolves cleanly either way during Builder execution. Non-blocking.

### AD-641c (❌ Not Ready → ✅ Approved)

| Pass-1 item | Tier | Status |
|---|---|---|
| R1 phantom kwarg `event_type=` on `EventLog.query` | Required | ✅ Resolved (`query_structured(event=...)` async) |
| R2 async/sync mismatch on `_count_endorsements` | Required | ✅ Resolved (`async def`, awaited) |
| R3 wrong row shape `.payload` vs `data` | Required | ✅ Resolved (`entry["data"]`) |
| R4 flatten posts tree → flat | Required | ✅ Resolved (`_walk` recursive helper; test #15 regression guard) |
| R5 department resolver from `_helpers.py:11` | Required | ✅ Resolved (`resolve_author_department(author_id)`; test #16 regression guard) |
| R6 VAC footer reflects `get_thread` shape | Recommended | ✅ Applied |
| R7 `_build_input` distinct-departments regression test | Recommended | ✅ Applied (test #16) |
| R8 count test arrange uses post-R3 shape | Recommended | ✅ Applied |
| R9 kwargs splat soft coupling documented | Recommended | ✅ Applied (item #6 of "What This Does NOT Change") |
| N1 clock injection on scorer | Nit | 📦 Deferred (documented; ratio-based test) |
| N2 endorsement formula vs docstring mismatch | Nit | ✅ Applied (`1 → 0.393`, etc.) |
| N3 test count 14→16 | Nit | ✅ Applied |

**0 new substantive findings.** Two non-blockers:
- Editorial micro-inconsistency in Revision row R5 prose ("3 to 3" tautology; factor count is the live delta) — does not affect correctness.
- Defensive `try/except Exception` around `resolve_author_department` is over-protective per Convention #11 — Builder discretion to keep or strip.

## Solution Overview Drift Discipline (Convention #12)

641c revision shifted three header surfaces in lockstep — passes the no-theater test:

| Surface | Pre | Post |
|---|---|---|
| Solution Overview line 28 | "4 of 7 capabilities ship" | "5 of 8 capabilities ship" |
| v1 priority factors line 30 | "4 wired" + endorsement density "wired but reads from event_log -- see scope" (silently inert) | "5 priority factors wired and exercising live data" with endorsement density "read from `event_log.query_structured(event=WARD_ROOM_ENDORSEMENT)`" |
| Acceptance criteria | 14/14 tests | 16/16 tests + 3 explicit structural-fix bullets |
| Estimated tests header | ~14 | ~16 |
| What This Does NOT Change | 5 deferrals | 6 deferrals (kwargs-splat soft coupling) |

**No surface still claims shipping content the body does not deliver.** Convention #12 discipline clean.

## Phantom-API Pre-check

```
./scripts/phantom-api-precheck.ps1 prompts/ad-641c-ward-room-thread-priority.md prompts/ad-641e-learned-shortcut-abstraction.md
=== prompts/ad-641c-ward-room-thread-priority.md ===
  Clean — no phantom symbols detected.
=== prompts/ad-641e-learned-shortcut-abstraction.md ===
  Clean — no phantom symbols detected.
=== Summary ===
Prompts scanned: 2
Total phantom candidates: 0
```

**Expected output matched.** 0 phantom candidates, 0 false positives in pass-2 (pass-1 had 2 false positives — `runtime.thread_priority_service` and `runtime.learned_shortcut_registry` — both self-introduced; pre-check now cleanly clears them after Section 5/6 finalize wiring stabilized).

## Cross-conflict Re-scan

| Scan | Result |
|---|---|
| Wave 9A overlap (commits 4476091, a56b6c6, f8e12ea) | ✅ events.py:225-229 / finalize.py:728-784 / 3 Pydantic models — no overlap; appends after most-recent Wave 9A block |
| Listener-class greps (`EndorsementListener|handle_event|ward_room_endorsement_listener`) | ✅ 0 matches in both revised prompts |
| 641c + 641e three-way append on triplet (events.py / config.py / finalize.py) | ✅ distinct EventTypes, distinct Pydantic models, distinct finalize blocks; mechanical sequential append |

## Wave 9A Retrospective Propagation

**Did the Wave 9A retrospective lesson finally propagate?** Mixed — the pattern propagated **into the revision pass**, not into the original draft. Key observations:

- The Wave 9A retrospective in `DECISIONS.md` flagged three latent live-API mismatches (async/sync, kwarg names, dict row shape) as classes that should be explicitly grepped in future review checklists.
- AD-641c's **original draft** reproduced **all three** classes. The pass-1 review caught them — the architect-discretion verify-first sweep is what the retrospective explicitly mandated, and it worked. But the lesson did not propagate into the draft itself.
- AD-641c's **revision pass** repaired all three with grep-confirmed live surfaces. The pattern propagated **as a reactive repair discipline**, not as a proactive drafting discipline.
- AD-641e (purely cognitive layer; no event_log / ward_room consumption) did not exhibit the pattern at all. The blast-radius framing held: prompts touching `event_log.query*` and `ward_room.get_thread` are the surface of risk.

### Recommended pre-check enhancement for Wave 9C

Pass-1 review §"Pattern Lessons" #2 flagged the phantom-API pre-check's method-kwarg blind spot. The current script scans symbol references (`runtime.X`); it does not parse method calls and validate kwargs against live signatures. **Recommendation:** before Wave 9C dispatch, file a tooling AD to extend `scripts/phantom-api-precheck.ps1` to:

1. Parse `event_log.query(*args, **kwargs)`-shape calls in prompt code blocks.
2. Look up the live signature for the called method (when the call target is a known runtime attribute).
3. Validate kwarg names against the signature; flag unknown kwargs as method-kwarg phantoms.

This would have caught R1 (`event_type=` on `EventLog.query`) mechanically. **Surface as Wave 9C dispatch input, not a 9B-blocker.**

The pattern theme #3 from pass-1 — "live API shape vs assumed shape" — is harder to pre-check mechanically because return-shape inference requires actual runtime introspection or a typed API contract. Leave that gap to convention-level discipline (every consumer prompt greps the consumed API's return shape and documents it in VAC).

## Pattern Observation: Tree-vs-Flat Return Shape (NEW for Wave 9 series)

This wave introduced two new structural defect classes not in the Wave 9A retrospective:

1. **Tree-vs-flat shape** (`get_thread` returns `{"thread", "posts": roots_with_children, ...}`, not flat list). Reproduced as 641c R4.
2. **Per-author vs per-row resolution** (post dicts lack `department`; resolution is via `_helpers.resolve_author_department(author_id)`). Reproduced as 641c R5.

Both are downstream consequences of the ward_room API's design choices (tree storage; author-keyed department). Future prompts that consume `ward_room.get_thread` should grep:

- `threads.py:716-748` for the return-shape construction.
- `_helpers.py:11` for the canonical resolver path.

**Recommend adding to the dispatch-time verify-first checklist for Wave 9C+** any time a prompt consumes `ward_room.get_thread` or a similarly tree-shaped API.

## Recommended Builder Order

**641e → 641c** — same as build dispatch order.

- **641e first**: purely cognitive layer; no event_log / ward_room consumption; smallest blast radius. ~13-14 tests; clean append-only.
- **641c second**: cross-cutting (event_log + ward_room + config + startup); regression-guard tests (#14, #15, #16) anchor the structural fixes. ~16 tests.

If 641e build encounters any shortcut-classification false positive in tests, halt and surface; 641c's structural fixes depend on cleanly working live APIs (which 641e does not modify) so 641e success is independent of 641c.

## Convergence Outlook

| Item | Forecast | Actual |
|---|---|---|
| Pass-2 verdicts | 2 ✅ / 0 ⚠️ / 0 ❌ | 2 ✅ / 0 ⚠️ / 0 ❌ |
| Required still open | 0 | 0 |
| Substantive new findings | 0 | 0 |
| Tolerance reservation consumed | No | No |
| Phantom-API pre-check | 0 | 0 |

**Convergence target met. Wave 9B is build-ready.** Both prompts ✅ Approved. Recommend the dispatching architect proceed to build dispatch in 641e → 641c order.

## Cross-Wave Pattern Summary

| Wave | Original Drafts | After Pass-1 | After Pass-2 | Defects Reproduced from Prior Wave |
|---|---|---|---|---|
| 9A | 3 prompts | 1 ✅ / 0 ⚠️ / 2 ❌ | 3 ✅ | n/a (first wave with this defect class) |
| 9B | 2 prompts | 1 ✅ / 0 ⚠️ / 1 ❌ | 2 ✅ | All 3 Wave 9A classes reproduced in 641c original draft |

**Cross-wave lesson:** the retrospective on Wave 9A surfaced the defect classes; the dispatch instruction on Wave 9B explicitly cited them; the architect-discretion sweep caught them in pass-1. The reactive review pipeline works. The proactive drafting pipeline (where the prompt author would grep these surfaces themselves) does not yet — and likely will not without a tooling enhancement (per the recommendation above) or a hard procedural rule that every prompt consuming a live API must include a `grep -n "def <method>" <file>` line per consumed method in its VAC, not just a `grep -n "<symbol>"` symbol reference.

**Recommend** the Wave 9C dispatch attach a "consumer-prompt VAC checklist supplement" requiring grep-for-signature evidence per consumed method, in addition to the existing grep-for-symbol evidence. Current convention #6 (verify-first) is enforced reactively; the supplement would push it left into drafting.
