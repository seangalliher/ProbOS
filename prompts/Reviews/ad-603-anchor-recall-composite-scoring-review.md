# Review: AD-603 Anchor Recall Composite Scoring

**Prompt:** `prompts/ad-603-anchor-recall-composite-scoring.md`
**Reviewer:** Architect
**Date:** 2026-04-27
**Verdict:** ✅ Approved with minor polish.

---

## Required (must fix before building)

_None._

## Recommended (should fix)

1. **Type annotation uses inline comment instead of proper union.** The signature is documented as `list[RecallScore]` "or list[Episode]" via comment. Either:
   - Define a `RecallResult: TypeAlias = list[RecallScore] | list[Episode]` and use it, or
   - Split into two methods (`recall_by_anchor_scored` returning `list[RecallScore]`, keep the legacy method returning `list[Episode]`).
   The current shape requires callers to type-narrow at every usage.

## Nits

2. **Anchor bonus literal `+0.08`** appears in the score formula. Consider lifting to a named constant `_ANCHOR_RECALL_BONUS = 0.08` at module top so future tuning has a discoverable knob.
3. **Acknowledged DRY duplication is justified** but add a `# AD-603: scoring path duplicated intentionally — see DECISIONS.md` marker comment so future readers don't "fix" it.

## Verified

- Strong "What this does NOT include" section — matches AD-651 standard.
- Find/Replace blocks are anchored on real `cognitive_agent.py:4469-4493` content.
- Merge-step ordering is correct: anchor results reranked before truncation, not after.
- Tracker section present (PROGRESS / DECISIONS).
- Test plan covers the four boundary cases (empty anchors, single anchor hit, multi-anchor merge, score-tie tie-breaking).

---

## Recommendation

Ship as-is or with the type alias cleanup. This is a small, focused, well-anchored prompt — model behavior for similar enhancement ADs.
