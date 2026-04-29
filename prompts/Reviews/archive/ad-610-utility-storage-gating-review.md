# Review: AD-610 Utility-Based Storage Gating (Re-review #2)

**Prompt:** prompts/ad-610-utility-storage-gating.md
**Reviewer:** Architect
**Date:** 2026-04-27 (third pass)
**Verdict:** ✅ Approved
**Previous Verdict:** ✅ Approved

## Status
Stable. Performance budget in Acceptance Criteria. Clean order-of-checks documented in `evaluate()`. Importance≥8 bypass justified. Ring buffer (deque maxlen) bounds memory. EPISODE_REJECTED event emitted on every reject path.

## Required
None.

## Recommended
- Verify `probos.cognitive.similarity.jaccard_similarity` exists. The import is at module top — failure here breaks load. Add a Verify step.

## Nits
- `evaluate()` records the fingerprint only on ACCEPT (`_record_fingerprint` called inside the ACCEPT path). The earlier docstring says "After evaluation, the episode fingerprint is added to the recent buffer regardless of decision". The code matches the cleaner behavior (only ACCEPT'd episodes are tracked); update the docstring to reflect this.

## Recommendation
Ship it.
