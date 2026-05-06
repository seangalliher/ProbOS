# WAVE 71 DISPATCH — AD-644b Phase 5 Deprecation (NO-BUILD CLOSE)

**Wave id:** 71
**Single AD:** AD-644b
**Closes:** #415
**HEAD at draft:** `fe71048`
**Builder required:** false

## Verdict

Verify-first against HEAD `fe71048` reveals the deprecation target is **already gone**.

| Claim in #415 | Live state |
|---|---|
| `_build_prompt_text` proactive_think block at `sub_task.py:3319-3607` | `sub_task.py` is now 620 lines total; no such function exists |
| Inventory non-chain consumers | `Get-ChildItem -Recurse -Include *.py -Path src,tests \| Select-String "_build_prompt_text"` → 0 hits |
| Route to chain path or replacement | already done; chain path is the only path |
| Remove legacy code | already removed |

## Reframe decision

**5→0 no-build close**, mirroring Wave 68 (AD-572b-e). The five subtasks of #415 (deprecate, inventory, route, remove, test) all map to operations that have no live target. No code change, no test change, no roadmap change beyond marking #415 closed.

## Probable history

The 290-line block was almost certainly removed during one of:
- Wave 14-30 sub_task.py refactors (chain extraction, AD-632 series)
- AD-644 phases 1-4 (commit f10369d, the issue's own anchor)
- AD-647b/c chain registry waves (which restructured the chain path end-to-end)

Verifying which wave removed it is not necessary for closure — current state is what matters.

## Captain workflow

1. Append wave-71 entry to `prompts/wave-plan.yaml` with `status: done`, `builder_required: false`, `prompt_paths: []`.
2. Commit `Wave 71 close: AD-644b _build_prompt_text already removed (no-build close, #415)`.
3. Archive this dispatch to `prompts/archive/`.
4. Close GH #415 with the verify-first evidence above.

## Commercial-leak audit

Clean. Wave 71 contains zero pricing, revenue, customer-count, professional-services, GTM, or competitive language. No `*(Commercial)*` deferral.
