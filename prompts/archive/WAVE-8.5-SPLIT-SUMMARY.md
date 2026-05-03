# Wave 8.5 — AD-641 Northstar Umbrella Split: Dispatch Summary

**Date:** 2026-05-02
**Architect:** Wave 8.5 dispatch
**Output:** 6 sub-AD build prompts + this summary; ready for Wave 9A/9B/9C dispatch.
**Source files touched:** None (architect output only — markdown).
**Pre-check exit:** 1 (10 candidates flagged; **0 real phantoms** after review; 10 false positives documented below).

---

## Final Scope Table

The dispatch suggested a Ship's-Computer-persona/voice scoping. Verify-first against `docs/development/roadmap.md:7056` and `docs/research/ad-641-brain-enhancement-design.md` revealed AD-641's actual umbrella decomposition is **Brain↔Crew Integration**, not persona/voice. The roadmap explicitly names six sub-ADs already (641a-f). I followed the umbrella's own decomposition rather than the dispatch's suggested split. AD-641g (NATS pipeline) is independently scoped and out of this Wave 8.5 split.

| Sub-AD | Sub-wave | Risk | Title | v1 capabilities | Deferred to grandchild |
|---|---|---|---|---|---|
| 641a | 9A | medium | Observability Bridge | 3 brain feeds (vitals / pool health / attention) → Ward Room system posts; named asyncio task; emit `OBSERVABILITY_SNAPSHOT_PUBLISHED` | 641a-i: Hebbian feed; 641a-ii: HXI surfaces; 641a-iii: Captain alert routing |
| 641b | 9A | medium | Ward Room Hebbian Learning | Separate `WardRoomHebbianRouter` instance; `record_contribution`/`get_weight`/`top_contributors`/`decay`; endorsement listener wires `WARD_ROOM_ENDORSEMENT` events | 641b-i: SQLite persistence; 641b-ii: WR Router integration; 641b-iii: adaptive decay |
| 641c | 9B | medium-high | Ward Room Thread Priority | 4 priority factors (Captain involvement, unresolved-question marker, cross-department, recency 24h half-life); pure scorer + service adapter | 641c-i: HXI rendering; 641c-ii: auto-archival; 641c-iii: Hebbian-fed priority bump |
| 641d | 9C | high | Crew Deliberation Protocol | `DeliberationSession` lifecycle (initiate→argue→endorse→resolve); Captain-only resolve; 3 outcomes (ADOPTED/REJECTED/DEFERRED) | 641d-i: multi-Captain quorum; 641d-ii: Counselor mediation; 641d-iii: structured argument schema; 641d-iv: Hebbian feedback |
| 641e | 9B | medium-high | LearnedShortcut Shared Abstraction | `LearnedShortcutBackend` Protocol (`@runtime_checkable`); `WorkflowCacheBackend` adapter (real); `LearnedShortcutRegistry` with read-side fan-out | 641e-i: Cognitive JIT adapter (when JIT service lands); 641e-ii: cross-store eviction; 641e-iii: persistent backend |
| 641f | 9A | medium | Engineering Chief Observability | 3 sensor surfaces (pool / capability / gossip aggregates); `EngineeringSensorBundle` + service; named periodic-report task | 641f-i: per-peer gossip introspection; 641f-ii: capability registry mutation surface; 641f-iii: cross-pool failover |

**Each sub-AD ships 3-4 v1 capabilities and defers 3-4 grandchildren** — convention #14 (aggressive pre-deferral) applied uniformly.

---

## Inter-Prompt Dependency Graph

```
                         (no upstream deps within Wave 9)
                                    |
        ┌───────────────────────────┼───────────────────────────┐
        |                           |                           |
   AD-641a                      AD-641b                      AD-641f
   Observability                Ward Room                    Engineering
   Bridge                       Hebbian                      Sensors
        |                           |                           |
        |                           |                           |
        ▼ (soft consumer dep)       ▼ (soft consumer dep)       ▼
   AD-641c <-----independent-------|                            |
   Thread Priority                 |                            |
        |                          |                            |
        |                          |                            |
        ▼ (Captain workflow uses thread priority for ordering)  |
   AD-641d                                                      |
   Deliberation                                                 |
        |                                                       |
        ▼ (no dep on 641a/b/f at source-file level)             |
   AD-641e <-------------- independent -----------------────────|
   LearnedShortcut Abstraction
```

**Wave 9A (parallel-safe — can build concurrently):** 641a, 641b, 641f. Each owns its own new package directory; no cross-edits to existing source files beyond the standard `events.py` / `config.py` / `startup/finalize.py` triplet (each appended to the bottom — sequencing is by anchor not by content overlap).

**Wave 9B (cross-cutting — build after 9A lands):** 641c, 641e. 641c reads thread state but doesn't touch the brain side; 641e wraps `WorkflowCache` via a new Protocol. Both ship without modifying existing source modules.

**Wave 9C (high-risk — build last):** 641d. Captain-facing protocol (callsign-based gate identical to BF-257 v1 pattern). Soft dependency on 641c for thread-ordering ergonomics, but 641d ships independently if 641c is deferred.

**No hard ordering constraints.** Each sub-AD's startup-wiring section appends to `finalize.py` after the most-recent block — sequencing is content-anchored. If Wave 9 builds in 641a→641b→641f→641c→641e→641d order, anchors stack cleanly; if a different order is chosen, anchors still stack because each section adds independent `runtime.X` attributes.

---

## Pre-Check Output (phantom-api-precheck.ps1, first mandatory use)

```
=== prompts/ad-641a-observability-bridge.md ===
  2 phantom symbol(s):
    - runtime.attention_manager       [false positive — see below]
    - runtime.observability_bridge    [false positive — introduced by Section 4]

=== prompts/ad-641b-ward-room-hebbian.md ===
  3 phantom symbol(s):
    - runtime.ward_room_hebbian_router    [false positive — Section 5]
    - runtime.observability_bridge        [false positive — prose mention; introduced by AD-641a]
    - runtime.ward_room_endorsement_listener [false positive — Section 5]

=== prompts/ad-641c-ward-room-thread-priority.md ===
  1 phantom symbol(s):
    - runtime.thread_priority_service [false positive — Section 5]

=== prompts/ad-641d-crew-deliberation-protocol.md ===
  1 phantom symbol(s):
    - runtime.deliberation_protocol [false positive — Section 4]

=== prompts/ad-641e-learned-shortcut-abstraction.md ===
  1 phantom symbol(s):
    - runtime.learned_shortcut_registry [false positive — Section 6]

=== prompts/ad-641f-engineering-chief-observability.md ===
  2 phantom symbol(s):
    - runtime.engineering_sensor_service       [false positive — Section 5]
    - runtime._engineering_sensor_start_task   [false positive — Section 5; private start-task ref]

=== Summary ===
Prompts scanned: 6
Total phantom candidates flagged: 10
Real phantoms after architect review: 0
Architect-judged false positives: 10
```

### Pre-check classification table

| Flag | Prompt | Type | Reason |
|---|---|---|---|
| `runtime.attention_manager` | 641a | False positive (negative framing) | The prompt explicitly says **the attribute is `runtime.attention`, NOT `runtime.attention_manager`**. The grep regex catches the substring inside negative framing. |
| `runtime.observability_bridge` | 641a | False positive (self-introduced) | Section 4 wires `runtime.observability_bridge =` for the first time. |
| `runtime.ward_room_hebbian_router` | 641b | False positive (self-introduced) | Section 5 wires it. |
| `runtime.observability_bridge` | 641b | False positive (cross-prompt prose) | Section 5 prose mentions "after AD-641a's `runtime.observability_bridge` if 641a lands first". The symbol is introduced by sibling prompt 641a; this is not a phantom. |
| `runtime.ward_room_endorsement_listener` | 641b | False positive (self-introduced) | Section 5. |
| `runtime.thread_priority_service` | 641c | False positive (self-introduced) | Section 5. |
| `runtime.deliberation_protocol` | 641d | False positive (self-introduced) | Section 4. |
| `runtime.learned_shortcut_registry` | 641e | False positive (self-introduced) | Section 6. |
| `runtime.engineering_sensor_service` | 641f | False positive (self-introduced) | Section 5. |
| `runtime._engineering_sensor_start_task` | 641f | False positive (self-introduced) | Section 5; the held start-task instance reference (Wave 5 task-handle convention). |

### One real verify-first slip caught and fixed before commit

During my own architect review the pre-check correctly flagged `runtime.attention_manager` as not present in `src/probos/runtime.py`. I had originally written 641a's `_collect_attention()` against `runtime.attention_manager`, but the live attribute is `runtime.attention` (verified at `runtime.py:197, 359`). I fixed Section 2's code, the Dependencies header, the v1 scope bullet, and the Verified Against Codebase footer to use `runtime.attention`. The pre-check still flags the symbol because the prompt's negative-framing prose (clarifying the wrong-vs-right name for Builder) contains the substring; this is the script's expected behavior.

**This is the canonical convention #16 win:** the script caught a real verify-first slip before any review pass began.

### Pre-check calibration recommendation for Wave 9A

The script flagged 10 candidates; 9 were self-introduced symbols and 1 was a negative-framing mention. False-positive rate: 10/10 in this run. Two cheap calibration improvements before Wave 9A:

1. **Suppress symbols introduced via `runtime.X = `** — extend the body-self-introduction regex on line ~126 of `phantom-api-precheck.ps1` to also accept the pattern `runtime\.<name>\s*=\s*` (assignment to a runtime attribute is the most common self-introduction pattern in startup wiring).
2. **Suppress symbols within ±30 characters of `NOT`, `was`, `instead of`, or `should be`** — negative framing is common in revised prompts.

These would have driven the pre-check to **0 candidates** for this Wave 8.5 split with no manual review needed. Recommend tuning before Wave 9A's pre-check run.

---

## Recommended Wave 9 Dispatch Order

### Wave 9A (parallel-safe; dispatch all three concurrently)

1. **AD-641a — Observability Bridge** (estimated ~14 tests, MEDIUM risk)
2. **AD-641b — Ward Room Hebbian Learning** (estimated ~14 tests, MEDIUM risk)
3. **AD-641f — Engineering Chief Observability** (estimated ~13 tests, MEDIUM risk)

All three own their new package directory; no cross-edits to existing source modules beyond the standard triplet (`events.py`, `config.py`, `startup/finalize.py`). Builder can land them in any order.

### Wave 9B (cross-cutting; dispatch after 9A converges)

4. **AD-641c — Ward Room Thread Priority** (estimated ~14 tests, MEDIUM-HIGH risk)
5. **AD-641e — LearnedShortcut Abstraction** (estimated ~12 tests, MEDIUM-HIGH risk)

Both touch existing surfaces (Ward Room, WorkflowCache) but only as read-side consumers via Protocols. No edits to the wrapped classes themselves.

### Wave 9C (high-risk; dispatch after 9B converges)

6. **AD-641d — Crew Deliberation Protocol** (estimated ~15 tests, HIGH risk)

Captain-facing workflow surface. Callsign-based gate identical to BF-257 (Wave 8 convention; AD-499 ShipNamingPolicy canonical "Captain"). DECISIONS.md entry required (per the prompt's Tracking section) documenting the QuorumEngine-vs-DeliberationProtocol separation.

---

## Acceptance Criteria Status

- [x] 6 sub-AD prompt files at `prompts/ad-641{a,b,c,d,e,f}-*.md`.
- [x] 1 dispatch summary at `prompts/WAVE-8.5-SPLIT-SUMMARY.md`.
- [x] Each sub-AD prompt has all 12 required sections (Title/Status, Problem, Solution Overview, Section 0 EventTypes, Sections 1-N implementation, Tests, What This Does NOT Change, Engineering Principles, Verification, Tracking, Acceptance Criteria, Verified Against Codebase footer).
- [x] All 19 standing conventions applied — see per-sub-AD discussion below.
- [x] phantom-api-precheck.ps1 reports 10 candidates, all documented as false positives.
- [x] Inter-prompt dependency graph documented above.
- [x] Single commit; no source files touched.

### Convention application audit

| Convention | Application |
|---|---|
| **#1 Public-attribute wiring** | Each sub-AD wires `runtime.<service_name>` as a public attribute (no leading underscore on consumer-facing names). 641f's `_engineering_sensor_start_task` is intentionally private — internal task-handle, not consumer-facing. |
| **#2 stdlib persistence** | None of the v1 sub-ADs persist; explicit deferrals to grandchild ADs. 641b's persistence → 641b-i; 641e's → 641e-iii. |
| **#3 Coordinator first, dispatch deferred** | 641d's `DeliberationProtocol` ships the lifecycle skeleton; multi-Captain quorum, Counselor mediation, structured argument schema all deferred. |
| **#4 Superset filter discipline** | 641d's Captain-resolve gate strictly intercepts non-Captain calls; existing Ward Room post API unchanged. |
| **#5 startup `emit_event_fn`** | All sub-AD finalize blocks use `runtime.emit_event` because finalize is in the cross-cutting `finalize.py` module — verified pattern from AD-475/AD-449. |
| **#6 verify-first** | Every concrete claim grepped; one phantom (`runtime.attention_manager` → `runtime.attention`) caught and fixed before commit. |
| **#7 No theater** | 641e's `evict()` honestly returns `False` (deferred to 641e-ii) instead of pretending to evict. 641e-i (JIT adapter) wholesale-deferred since the JIT service does not exist today. |
| **#8 TYPE_CHECKING cross-layer imports** | Not needed — all sub-ADs live in `cognitive/` and import from `events.py` / `config.py` (peer or downward). |
| **#9 ASCII-only source comments** | All comments use `<-`, `->`, `--`. Confirmed in each prompt's code blocks. |
| **#10 work_item_store vs workforce** | Not applicable — none of the sub-ADs touch the workforce surface. |
| **#11 `__new__`-bypass `getattr`** | All `_collect_*` methods on 641a/641c/641f services use `getattr(self._runtime, ..., None)` so `__new__`-constructed test instances don't crash. |
| **#12 Solution Overview drift watch** | Each Solution Overview explicitly enumerates v1 capabilities and deferred grandchildren. No drift between Solution Overview and Section bodies. |
| **#13 Pool template name collision** | Not applicable — none of the sub-ADs create new agent pools. |
| **#14 Aggressive pre-deferral** | Each sub-AD ships 3-4 of 6-8 capabilities; remainder deferred. |
| **#15 Relaxed tolerance** | Wave 9A/B/C dispatch should use relaxed tolerance per convention #15. |
| **#16 Phantom-API pre-check** | Run; 10 candidates, 1 real fix applied, 9 documented false positives, 0 real phantoms remain. |
| **#17 Per-instance mutable state in `__init__`** | All `_dm_response_counts`-equivalent dicts in 641a/641b/641d/641e/641f are initialized in `__init__`, never as class attributes. |
| **#18 Mock all attributes the code reads** | Test plans for 641a/641c/641d explicitly call out `AsyncMock(spec=WardRoomService)` so async methods are auto-async (BF-250 lesson). |
| **#19 Session-id in headers** | Not applicable — no JSON-RPC clients introduced. |

---

## Hard-Stop Surfaces (none triggered)

The dispatch listed 5 potential hard-stops. None triggered:

1. **AD-641 doesn't divide into 6 cleanly** → Did not trigger. The umbrella's own decomposition is exactly 6 sub-ADs (641a-f); 641g is independently scoped.
2. **Northstar paper reveals refactor requirements** → Did not trigger. The design doc's Category B/C/D division is honored without refactor.
3. **Pre-check phantoms not introduced by prompts** → Did not trigger after the `runtime.attention_manager` fix.
4. **Two sub-ADs touch the same source file in mutually-incompatible ways** → Did not trigger. All 6 sub-ADs append to `events.py` / `config.py` / `startup/finalize.py` at the bottom; sequencing is content-anchored.
5. **Section 0 EventType collisions** → Did not trigger. New EventTypes (10 total across 6 prompts) are all uniquely named and absent from `events.py`.

---

## Files Created (this commit)

```
prompts/ad-641a-observability-bridge.md
prompts/ad-641b-ward-room-hebbian.md
prompts/ad-641c-ward-room-thread-priority.md
prompts/ad-641d-crew-deliberation-protocol.md
prompts/ad-641e-learned-shortcut-abstraction.md
prompts/ad-641f-engineering-chief-observability.md
prompts/WAVE-8.5-SPLIT-SUMMARY.md   (this file)
```

No source files modified; no `PROGRESS.md` / `DECISIONS.md` / `roadmap.md` modified per the dispatch's "Output is 7 markdown files only" constraint.

---

## Wave-Over-Wave Convergence Trend

| Wave | Pass-1 Required | First-time-✅ rate | Pre-check used? |
|---|---|---|---|
| Wave 5 | 22 | 5/5 | No |
| Wave 6 | 18 | 5/5 | No |
| Wave 7 | 11 | 5/5 | No |
| Wave 8 | 19 | 6/6 (after 1 revision pass) | No (added in Wave 8 retro) |
| Wave 8.5 | — (this is split, not build) | n/a | **Yes — first mandatory use** |

**Recommendation:** keep convention #16 (mandatory pre-check) for Wave 9A; tune the script per the calibration notes above before Wave 9A's pre-check run to drive the false-positive rate down. Even uncalibrated, the script caught the `runtime.attention_manager` slip — one real-phantom catch on the first run validates the convention.

---

**Wave 8.5 complete. Wave 9A dispatch is unblocked.**
