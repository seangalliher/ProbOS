# Review: AD-738b — Per-wave UI gate must include `npm run build`
**Verdict:** ✅ Approved
**One-line headline.** Surgical process-only change; codifies BF-279 lesson into both the standing-rule doc and the orchestrator dispatch text.

## Required (must fix before building)
*(none)*

## Recommended
*(none)*

## Nits
1. The Format-BuildDispatch edit adds ~7 lines of paragraph text inside the here-string. The user's framing asked the architect for "ONE line"; the prompt's actual change is a short paragraph (still surgical, but not literally one line). Functionally equivalent — the prompt frames the rule as a standing reference that should be self-explanatory at GATE 2. Acceptable.
2. The BUILDER-EXECUTION-PLAN bullet references BF-279 with commit SHA `2d685bc5` — verify the SHA is current and didn't get rebased. If the SHA changed, builder updates it before commit. (Builder task; not a prompt defect.)

## Verified
- `## Standing Rules` heading at [BUILDER-EXECUTION-PLAN.md#L24](prompts/BUILDER-EXECUTION-PLAN.md#L24) ✓
- "License policy" bullet at [BUILDER-EXECUTION-PLAN.md#L32](prompts/BUILDER-EXECUTION-PLAN.md#L32) — confirmed as the last bullet before the `---` separator. New bullet inserts cleanly between this and the separator.
- `Format-BuildDispatch` at [wave-orchestrator.ps1#L262](scripts/wave-orchestrator.ps1#L262); current text "Per-prompt:" / "Per-commit gate:" / "Begin in dependency order;" all match the prompt's quoted "CURRENT" block at lines 290-293.
- No code changes (`src/` and `ui/src/` untouched). ✓
- 0 new tests — appropriate for a process-only AD. Manual verification per the prompt's Test Plan section.
- Slot-reuse: AD-738b slot freed by AD-738a Section 3 renumber (old AD-738b → AD-738g). Prompt explicitly assumes the renumber landed first (build order #2 → #3). ✓
- License: all-internal. ✓
- HXI: no UI surface change. ✓
- Wave 158's own Prompts 3/4/5 (UI-touching) will exercise the new rule, providing the forward-effect verification described in the Test Plan.

### Re-review (pass-2): unchanged, verdict re-affirmed ✅
