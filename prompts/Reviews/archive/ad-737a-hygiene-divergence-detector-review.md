# Review: AD-737a — Hygiene follow-ups for `divergence_detector.py`
**Verdict:** ✅ Approved
**One-line headline.** Solid hygiene prompt; verify-first claims hold against HEAD; behavior-equivalence proof is clean.

## Required (must fix before building)
*(none)*

## Recommended
1. **Cross-prompt synergy with AD-738e-1.** AD-738e-1 Section 6 spends 18 lines re-resolving `intent_emotion` → v1 in `routers/agents.py` because `DivergenceResult.intent_emotion` stores the *custom* name (line ~456). Since this prompt already touches `apply_divergence_check`, consider adding a `resolved_v1_emotion: str | None` field to `DivergenceResult` here as part of the single-pass collapse — AD-738e-1's chat-router resolution then collapses to ~3 lines. Not blocking (the two prompts are independently correct), but it's the cheaper merge.

## Nits
- Line number "around line 448" for the inline `import dataclasses as _dc` matches grep ✓. Line "around 391–412" for the double-parse — actual sites are line 392 and 410 per grep, prompt's stated range covers them.
- "76-caller estimate in the GH issue is wrong" — verified by grep: 2 production sites both inside `apply_divergence_check`, 13 test-site references. The architect's caller audit is correct.

## Verified
- `parse_intent_self_tag` has exactly 2 production call sites, both in `apply_divergence_check` ([divergence_detector.py#L392](src/probos/avatars/divergence_detector.py#L392), [divergence_detector.py#L410](src/probos/avatars/divergence_detector.py#L410)).
- Behavior-equivalence proof matches `_resolve_intent_name` short-circuit logic ([divergence_detector.py#L94-L107](src/probos/avatars/divergence_detector.py#L94)).
- No `ProbOSRuntime` Protocol exists today — concrete class only at `runtime.py:200`. Architect picks (b) "document, not promote" correctly.
- `getattr(runtime, "profile_store", None)` pattern verified at line 345 and 397 (prompt asserts line 397; matches grep).
- Slot-reuse note: Wave-156 closure block at DECISIONS.md:2391 reserved `AD-737a` as forward marker (TS-side parity), now superseded — acceptable per copilot-instructions ("renumbering placeholders is acceptable").
- License: all-internal, no deps. ✓
- Test plan covers happy + custom-resolve + unknown paths plus the call-counter assertion for the single-pass guarantee.
- No UI gate needed (no `ui/src/**` touched). ✓
- "What This Does NOT Change" section enumerates adjacent test files explicitly. ✓

### Re-review (pass-2): unchanged, verdict re-affirmed ✅
