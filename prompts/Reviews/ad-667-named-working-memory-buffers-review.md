# Review: AD-667 Named Working Memory Buffers

**Prompt:** `prompts/ad-667-named-working-memory-buffers.md`
**Reviewer:** Architect
**Date:** 2026-04-27
**Verdict:** ✅ Approved with minor cleanup.

---

## Required (must fix before building)

_None._

## Recommended (should fix)

1. **Line-number hints for `agent_working_memory.py` edits.** This file is small enough today that line numbers may hold, but use SEARCH/REPLACE blocks anchored on real text to future-proof.
2. **Per-buffer budgets specified as literals.** Move to `WorkingMemoryConfig.named_buffer_budgets: dict[str, int] = Field(default_factory=lambda: {...})` so tuning doesn't require code changes.

## Nits

3. **`render_buffers()` selective API** — document the precedence when a caller requests multiple buffers (concatenated in order? interleaved by timestamp?).
4. **15 tests** — specify the legacy-ring-buffer-still-works test explicitly.

## Verified

- **"Backward compatibility is sacred"** stated explicitly. Parallel-index pattern (legacy ring buffers preserved alongside named buffers) is the right call.
- Four named buffers (duty/social/ship/engagement) map to identifiable cognitive concerns — not arbitrary.
- `NamedBuffer` dataclass is appropriately minimal.
- Scope boundaries clear: this AD does not score (that's AD-668), does not decay (AD-670), does not coordinate threads (AD-669).
- Dependencies on unimplemented ADs (AD-668 salience filter) acknowledged with forward-compat note.

---

## Recommendation

Ship after the SEARCH/REPLACE conversion. This is solid architecture work.
