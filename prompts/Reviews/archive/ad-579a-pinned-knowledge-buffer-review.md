# Review: AD-579a Pinned Knowledge Buffer (Re-review #2)

**Prompt:** prompts/ad-579a-pinned-knowledge-buffer.md
**Reviewer:** Architect
**Date:** 2026-04-27 (third pass)
**Verdict:** ✅ Approved
**Previous Verdict:** ❌ Not Ready

## Improvements Since Prior Review
- **Dataclass field-ordering bug FIXED.** All non-default fields (`fact`, `source`, `pinned_at`, `ttl_seconds`) precede the defaulted fields (`id`, `priority`). The class will now construct without `TypeError`.
- Three pin sources documented as accepted strings; future wiring deferred per scope.
- Priority 0 section in `render_context()` cleanly inserted.
- Explicit "Do Not Build" includes SQLite persistence, HXI endpoints, LLM-based pin suggestion — sharp scope.

## Required
None.

## Recommended
- The frozen dataclass uses `field(default_factory=...)` for `id`. Verify `from dataclasses import field` is in scope (the prompt says `from dataclasses import dataclass, field` ✓).

## Nits
- "Three pin sources" listed as accepted but `source` is just `str` — not a StrEnum. Future tightening could constrain it.

## Recommendation
Ship it.
