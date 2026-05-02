# Review: Combo A — 8 Trivial Extensions

**Verdict:** ⚠️ Conditional — phantom-API drift across multiple children + DRY conflict in AD-526c. Most issues are mechanical fixes; no architectural rework needed.

**Date:** 2026-05-02

**Headline:** AD-573b/575b/655 reference attribute names that don't exist; AD-575b's both implementation halves are no-ops in current source (theater per convention #7); AD-526c duplicates an existing public registry surface.

---

## Required (must fix before building)

1. **AD-573b — phantom "frozen dataclass" claim.** The prompt extends `WorkingMemorySnapshot` and asserts `(frozen dataclass)`. Live source at `src/probos/cognitive/working_memory.py:21-22`:

   ```
   21: @dataclass
   22: class WorkingMemorySnapshot:
   ```

   The class is a plain `@dataclass` (not frozen). The proposed `field(default_factory=...)` extensions are valid on a non-frozen dataclass; the issue is the misleading description, not the implementation. **Fix:** drop the "frozen dataclass" parenthetical OR add `frozen=True` to the class decorator (the latter is intrusive — recommend just removing the misleading word).

2. **AD-573b — phantom `runtime.working_memory_manager` attribute.** The prompt's "Public attribute" footer says `runtime.working_memory_manager already exists`. Live source at `src/probos/runtime.py:348`:

   ```
   348: self.working_memory = WorkingMemoryManager(...)
   ```

   The actual public attribute is `runtime.working_memory` (no `_manager` suffix). Builder will write tests against the wrong name. **Fix:** rename in the prompt body to `runtime.working_memory`.

3. **AD-573b — verify-first line-number drift.** The verify-first block claims `78: class WorkingMemorySnapshot`. Live grep returns line 22. **Fix:** correct to line 22.

4. **AD-575b — phantom `runtime.self_summary_provider` interface (theater).** The prompt's `_gather_context` extension consults `getattr(rt, "self_summary_provider", None)` and calls `summary_for(agent.id)`. Verify-first:

   ```
   grep -rn "self_summary_provider\|SelfSummaryProvider\|summary_for\b" src/probos/
   (no matches)
   ```

   The interface does NOT exist. AD-575 (closed parent) did NOT ship it. The defensive `getattr` will always return `None`; the implementation is a permanent no-op. This is theater per convention #7 (no-theater discipline).

   The DM-forwarded-content half is also explicitly described as a no-op in the prompt: *"if no DM-forwarding handler exists in v1 source, this section is a no-op for the DM half"*. Both halves of AD-575b ship nothing real. **Decision required:** either (a) wholesale-defer AD-575b to AD-575c with no v1 deliverable, or (b) reframe the prompt to add the missing surface (`SelfSummaryProvider`) inline, which expands scope materially. Recommend (a).

5. **AD-655 — `EvaluateSubTask` is a phantom class name.** The prompt asserts *"the EvaluateSubTask builder calls retrieve_contrastive_episodes"* and tests reference `test_evaluate_subtask_consults_contrastive_when_runtime_episodic_wired`. Live source at `src/probos/cognitive/sub_tasks/evaluate.py:249`:

   ```
   249: class EvaluateHandler:
   252:     def __init__(self, *, llm_client: Any = None, runtime: Any = None) -> None:
   ```

   The class is `EvaluateHandler` (not `EvaluateSubTask`). The wiring goes into `EvaluateHandler.__call__` or one of the `_EVALUATION_MODES` builder callables. **Fix:** rename in the prompt body and tests to `EvaluateHandler`.

6. **AD-526c — DRY conflict with existing `register_engine` API.** Live source at `src/probos/recreation/service.py:40-58`:

   ```
   40: self._engines: dict[str, GameEngine] = {}
   56: def register_engine(self, engine: GameEngine) -> None:
   60: def get_available_games(self) -> list[str]:
   ```

   `RecreationService` already has `register_engine(engine)` + `get_available_games()` + `_engines` dict. The proposed `register_game(descriptor)` + `list_games()` + `_games` dict duplicates this surface. **Fix options:** (a) drop the second registry; piggyback `GameDescriptor` metadata on the existing `GameEngine` via attributes; (b) explicitly justify why the two surfaces coexist (engines = behavior, descriptors = metadata) and rename methods to avoid ambiguity (`register_game_descriptor`, `list_game_descriptors`). Recommend (a).

7. **Combo Section 0 anchor depends on AD-475 landing first.** The combo's events SEARCH block targets the AD-475 `IDEA_CAPTURED` line. AD-475 is being built in the same wave; the dispatch's recommended build order doesn't guarantee AD-475 lands before Combo A. **Fix:** explicitly state Combo A must be built AFTER AD-475 in the same Wave 8 commit chain, OR provide a fallback anchor that doesn't depend on AD-475 (the prompt does provide a fallback chain — that's good — but the primary anchor should be Wave-7 stable: `MODEL_FALLBACK = "model_fallback"  # AD-463`, line 211).

---

## Recommended

1. **AD-538b: dream-manifest filter site is approximate.** The prompt says *"around `dreaming.py:193` where `recent(k=...)` runs"*. Live grep confirms line 193 calls `await self.episodic_memory.recent(k=min(new_count, 10))`. The filter would slot in between line 193 and `_replay_episodes(episodes)` at line 198. The prompt's description is approximate but reasonable; Builder can locate the seam. Tighten the SEARCH block to exact lines.

2. **AD-572b: `runtime.bridge_alerts` reference is correct** (verified at `runtime.py`). But the snapshot also reads "DM queue depth" and the prompt is hand-wavy about which Ward Room API surfaces this — `runtime.ward_room` has DM tables but no `dm_queue_depth()` method today. Recommend tightening: enumerate exactly which Ward Room methods the snapshot calls, OR documenting that the dm_queue_depth count is a `len(thread_list)` filter applied by the snapshot (not a new API).

3. **AD-576b retry block creates locals every call.** Each `_think_for_agent` invocation re-creates `_BACKOFFS_SECONDS` and `_LLM_ERROR_KEYWORDS` tuples. Recommend hoisting them to module level. (Trivial perf; not a correctness bug.)

4. **AD-655: `retrieve_contrastive_episodes` mid-band definition is hard-coded.** Default `[0.4, 0.65]` band thresholds are not configurable and not justified beyond "Meta-Harness research showed". Recommend a Pydantic config field for the band, defaulted to those values.

5. **AD-526c: DRY (mirrors Required #6).** Once the registry duplication is resolved, AD-526c's "spectators + holodeck integration" deferral language is good (convention #14). Keep the deferral.

6. **AD-656: `DepartmentProfilesConfig.profiles: dict[str, DepartmentCognitiveProfile]` field default.** The prompt uses `Field(default_factory=lambda: {})` which is correct. But the consumer-side wiring in `EvaluateHandler` is described in two sentences without a SEARCH/REPLACE block. Recommend providing one — the consumer wiring is the only real work in AD-656 outside config; without a concrete edit, this child is at risk of becoming theater (Pydantic class with no consumer).

---

## Nits

- **Combo Section 0 expected delta says "5 lines added"** — correct for the 5 named EventTypes. ✅
- **Sequential-discipline note on `proactive.py`** is well-stated (Section header, plus per-child note). The order AD-572b → AD-575b → AD-576b is documented; Builder will follow.
- **AD-526c "RECREATION_GAME_REGISTERED" event name** — fine; no collision.
- **AD-538b emit cadence ("per replay batch, not per episode")** — sensible volume control.
- **AD-655 "AD-647 closed parent"** — verify-first per child does not include the AD-647 status. Per dispatch's per-child verify-first requirement, each child's grep evidence should include its parent's status. Minor — the section's existence as a Combo-A child implies the parent dependency.

---

## Verified (looks good)

- Combo discipline structure is correct (single Section 0, single tracker block, file-conflict serialization documented for `proactive.py`).
- AD-538b's `DreamManifest` stdlib-JSON pattern matches Wave 5 convention #2.
- AD-572b's `runtime.bridge_alerts` reference is real (verified at `runtime.py`).
- AD-526c's `runtime.recreation_service` is real (`runtime.py:445`).
- AD-655's `EpisodicMemory._collection.query` underlying API is real (`episodic.py:1453`).
- AD-656's `DepartmentCognitiveProfile` does not collide with the existing per-agent `CognitiveProfile` at `cognitive/counselor.py:147` (different class names, different scope).
- Combo single-commit message format is documented and unambiguous.
- v1/deferred-scope split per child honors convention #14 (e.g., AD-526c spectators wholesale-deferred at draft time).

---

## Conventions audit

| # | Rule | Status |
|---|---|---|
| 1 | Public-attribute wiring | ⚠️ AD-573b (`working_memory_manager` phantom name) |
| 2 | stdlib-only persistence | ✅ |
| 3 | Coordinator-then-dispatch | ✅ AD-526c spectators/holodeck deferred |
| 4 | Superset-filter | ✅ all children additive |
| 5 | init_<phase> startup | ✅ |
| 6 | Verify-first | ⚠️ AD-573b line-number drift; AD-575b builds on phantom interface |
| 7 | No-theater | ❌ AD-575b ships no real work in v1 source |
| 8 | TYPE_CHECKING + ALLOWED_EXCEPTIONS | N/A (no cross-layer imports) |
| 9 | ASCII-only comments | ✅ |
| 10 | work_item_store vs workforce | N/A |
| 11 | __new__-bypass defensive-getattr | ✅ on real attributes; AD-575b's `getattr` is on phantom name |
| 12 | Solution Overview drift | ✅ |
| 13 | Pool template name collision | N/A (no pools) |
| 14 | Aggressive pre-deferral | ✅ |
| 15 | Tolerance: relaxed | n/a (review tier) |

---

## Combo Pattern Lessons

The combo prompt converges if and only if every child's verify-first is real. Per-child grep evidence catches drift early; this review surfaced 4 phantom-API issues that span children. Refinement for Wave 9+:

- **Per-child verify-first must include grep output for every named entity.** AD-573b/575b would have caught their phantoms at draft time if the verify-first block had run grep on the proposed attribute name.
- **AD-575b is the canonical "phantom interface" failure** — drafted on the assumption that AD-575 (closed parent) shipped a `SelfSummaryProvider`, which it didn't. Future combo drafts should grep the asserted parent-AD interface before extending.

This is the first combo prompt; the lessons here justify the pattern (5 of 8 children are clean) but flag 3 children needing rework before Builder dispatch. The combo pattern survives this review with revisions.
