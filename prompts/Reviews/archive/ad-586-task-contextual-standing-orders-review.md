# Review: AD-586 Task-Contextual Standing Orders (Re-review #2)

**Prompt:** prompts/ad-586-task-contextual-standing-orders.md
**Reviewer:** Architect
**Date:** 2026-04-27 (third pass)
**Verdict:** ✅ Approved
**Previous Verdict:** ✅ Approved

## Status
Stable. Tier 5.5 insertion is additive and surgical. Architectural note explicitly justifies module-level `_task_context` global as following the existing `_directive_store` / `_skill_catalog` pattern. Late-bind setter on CognitiveAgent. Builder note: "do NOT use `hasattr()`" for the agent attribute. Hardcoded intent→task mapping is explicit and auditable.

## Required
None.

## Recommended
- `hasattr(task_ctx, "render_task_context")` in `compose_instructions()` is wiring code (handles the case where the global is unset or a stub). Acceptable, matching the pattern noted in AD-571's wiring code.

## Nits
- `general.md` is described as an empty file — make sure the Builder actually creates a zero-byte file rather than skipping it (the file's existence is checked).

## Recommendation
Ship it.
