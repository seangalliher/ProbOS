# Review: AD-585 Tiered Knowledge Loading

**Prompt:** `prompts/ad-585-tiered-knowledge-loading.md`
**Reviewer:** Architect
**Date:** 2026-04-27 (revision 2)
**Verdict:** ✅ **Approved — ready for builder.**

Previous review (2026-04-27) blocked on three Required items. All have been resolved in the rewrite.

---

## Required (must fix before building)

_None._

## Recommended (should fix)

1. **Tier-3 keyword match is naive.** `load_on_demand` does substring matching on episode reflections. Acceptable for v1 but document explicitly that semantic similarity is a follow-up AD so reviewers don't expect richer behavior.
2. **`_load_category` for `"episodes"` ignores the `department` filter** ("All episodes pass for now — future: department tagging"). The TODO is fine as written; consider opening a follow-up AD reference inline so it's tracked.
3. **No tracker section.** Add the standard PROGRESS.md / docs/development/roadmap.md / DECISIONS.md updates per the AD-651 model. This is the only systemic gap left.

## Nits

4. **Acceptance Criteria block missing.** Add the standard block with the test count (31 tests per the test file) and the Engineering Principles compliance line.
5. **Consider a "Do not build" section** explicitly forbidding eager preloading of on-demand and cross-agent cache sharing.
6. **`_summarize_trust` static method** mixes display logic (formatting) with computation. Fine for a single call site; if reused, extract.

## Verified

- ✅ **Loader is no longer dead code.** Section 5 wires `TieredKnowledgeLoader` in `startup/finalize.py` onto every healthy CognitiveAgent via `set_knowledge_loader()`. Iteration pattern matches existing `set_strategy_advisor` wiring.
- ✅ **`KnowledgeTierLoadedEvent` typed dataclass added** in Section 1b matching the `CounselorAssessmentEvent` pattern.
- ✅ **SEARCH/REPLACE blocks throughout** anchored on real code (e.g., `runtime.trust_network.set_event_callback`, `if "_augmentation_skill_instructions" not in observation`).
- ✅ **`Field(default_factory=lambda: {...})` for `intent_knowledge_map`** — mutable-default issue resolved.
- ✅ **`observation["intent"]` access is documented as confirmed valid** — populated from `IntentMessage.intent` in `CognitiveAgent.perceive()` at line 1087, with intent values explicitly listed.
- ✅ **`asyncio.CancelledError` re-raised** in all three tier-load paths and in `_emit_tier_event` per async discipline.
- ✅ **Log-and-degrade with full context** (what failed, why, what next) on every except branch.
- ✅ **`_emit_tier_event` uses typed dataclass** (`KnowledgeTierLoadedEvent`) rather than ad-hoc dict.
- ✅ **On-demand explicitly documented as opt-in** — not auto-triggered in `decide()`, only via explicit `load_on_demand(query)` calls.
- ✅ **Tier ordering is precedence-by-injection** — `setdefault` preserves prior keys, three tiers stack as separate observation entries (`_knowledge_ambient`, `_knowledge_contextual`).
- ✅ **`KnowledgeSourceProtocol`** narrow interface — Dependency Inversion via Protocol.
- ✅ **`Field` import** correctly added if missing.
- ✅ **`_CacheEntry` with `__slots__`** — small, focused, immutable-ish helper.

---

## Recommendation

Ship. The three tracker/acceptance-criteria nits should be added in the same iteration but do not block the build. This is a clean rewrite that addresses every previous Required item.
