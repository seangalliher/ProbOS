# Review: AD-738a — Orchestrator commit-count audit + voice.ts test-affordance gating
**Verdict:** ✅ Approved
**One-line headline.** Clean two-section hygiene prompt + atomic forward-marker renumbering; PowerShell here-string interpolation is correct on inspection.

## Required (must fix before building)
*(none)*

## Recommended
1. **PowerShell here-string fragility (Section 1).** The audit block emits `` `$expected = ($wave.prompt_paths | Measure-Object).Count `` — the backtick escapes `$expected` to literal at function time, while `$wave.prompt_paths` interpolates at function time (correct). The architect's intent is "bake the expected count into the printed text and have the user evaluate `$actual` after paste." This works, but `$wave.prompt_paths` is array-like; `($wave.prompt_paths | Measure-Object).Count` returns `5` for a 5-element array — verify the wave-plan loader actually unpacks it as an array (not a single concatenated string). If the loader produces a single string, `Measure-Object | .Count` returns 1. Builder should smoke this against the live Wave-158 wave entry before merging. (One-line proof: `pwsh -c "$w = @{prompt_paths=@('a','b','c')}; ($w.prompt_paths | Measure-Object).Count"` should print `3`.)

## Nits
- `_resetTtsStatusForTests` is at line 143, not 142 (prompt's range "~142–147" covers it).
- ProfileChatTab.tsx note — N/A for this prompt; that file is touched by AD-738e-1.

## Verified
- `Format-Gate2` at [wave-orchestrator.ps1#L327](scripts/wave-orchestrator.ps1#L327) — current body matches prompt's "CURRENT" block exactly.
- `_resetTtsStatusForTests` at [voice.ts#L143](ui/src/audio/voice.ts#L143); current function body matches prompt's replace target.
- 6 Vitest call sites in `voice.serverTts.test.tsx` all run under Vitest default MODE='test' — backward compat preserved. ✓
- `roadmap.md` lines 361–364 match the prompt's verified state exactly (AD-738a/b/c/d rows).
- `DECISIONS.md:2446` "Forward markers." paragraph matches prompt's quoted verbatim text. ✓
- Slot-reuse hard-rule compliance: the four AD-738a/b/c/d slots were forward-marker placeholders, never shipped — renumbering to AD-738f/g/h/i is acceptable under the copilot-instructions interpretation ("renumbering placeholders is acceptable"). The renumber is *append-only* in DECISIONS.md (preserves audit history) and edits the roadmap table in place (adds "renumbered from AD-738a" suffix for traceability).
- License: all-internal. No pip/npm deps. ✓
- HXI: `_resetTtsStatusForTests` is invisible test affordance — no chrome added. ✓
- Section 3 must land before Prompts 3/4 — flagged in WAVE-158-DISPATCH "Cross-prompt collision notes" and dependency order is enforced by numeric prompt order. ✓
- Vitest's `vi.stubEnv` is available since Vitest 0.34; ProbOS uses 1.x — supported.

### Re-review (pass-2): unchanged, verdict re-affirmed ✅
