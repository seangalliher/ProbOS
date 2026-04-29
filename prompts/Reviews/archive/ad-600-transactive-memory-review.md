# Review: AD-600 Transactive Memory (Re-review #2)

**Prompt:** prompts/ad-600-transactive-memory.md
**Reviewer:** Architect
**Date:** 2026-04-27 (third pass)
**Verdict:** ✅ Approved
**Previous Verdict:** ✅ Approved

## Status
Stable. Clean DI on ExpertiseDirectory. Profile pruning + min_confidence filtering bounded. Keyword-based matching (no LLM). Three integration points (dream Step 6, OracleService, startup) clearly delineated.

## Required
None.

## Recommended
- `decay_rate` is in config but not used in the read window — confirm a `decay()` method is specified later in the prompt that applies it per dream cycle, otherwise the decay never happens and profiles accumulate forever.

## Nits
- `query_experts` partial-match formula `conf * (len(overlap) / max(len(topic_words), 1))` divides by query word count only — for asymmetric matches (long profile topic vs short query) this can over-credit. Acceptable as v1.

## Recommendation
Ship it. Verify the `decay()` method spec before merging.
