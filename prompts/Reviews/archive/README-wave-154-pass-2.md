# Wave 154 — Pass-2 Review Summary

**Reviewer:** Architect. **Date:** 2026-05-12. **Pass:** 2 (post-revision).
**Scope:** 4 prompts (AD-722b-1 deferred from this wave per dispatch scope-reduction note).

## Verdict matrix

| # | Prompt | Pass-1 | Pass-2 | Required findings (pass-2) | One-line justification |
|---|---|---|---|---|---|
| 1 | [ad-724-dm-hardening.md](../ad-724-dm-hardening.md) | ⚠️ | ✅ | 0 | Duplicate `DmSanityGateConfig` extension now spelled out for both `dm_sanity_gate.py:49` and `config.py:3236`; `Field` import addition called out; recommended typing + module-top import folded. One Recommended drift (Solution Overview ↔ Section 3 inconsistency on the second inline strip at proactive.py:3479) — idempotent, not blocking. |
| 2 | [ad-730-1-1-drag-paste-image.md](../ad-730-1-1-drag-paste-image.md) | ✅ | ✅ | 0 | Unchanged from pass-1; verdict re-affirmed. |
| 3 | [ad-720d-1-multi-image-batch.md](../ad-720d-1-multi-image-batch.md) | ⚠️ | ✅ | 0 | Phantom `AttachmentConfig` → `AttachmentsConfig` scrubbed everywhere; all 3 `build_multimodal_messages` callers (chat.py:300, agents.py:914, vision_dispatch.py:294) explicitly enumerated in Section 2 + verification footer; AD-724 region (1106-1145) carved out; loop body verbatim-preservation instruction protects BF-278 ref shape. |
| 4 | [ad-719-718-hxi-polish.md](../ad-719-718-hxi-polish.md) | ✅ | ✅ | 0 | Unchanged from pass-1; verdict re-affirmed. |

**Total pass-2 Required findings across the wave: 0.**

## Final wave verdict (Convention #15, relaxed tolerance)

**APPROVE.** All 4 prompts ✅, zero ❌, zero ⚠️. Threshold for relaxed Convention #15 (✅ APPROVE if 5✅ or up to 1⚠️ on highest-risk only with no ❌) is comfortably met.

## Highest-risk prompt (pass-2)

**AD-720d-1** remains the highest-risk prompt — same as pass-1. Risk shape unchanged:

1. Still changes the return arity of `build_multimodal_messages`, a function the wave-153 vision arc has touched 9 times in 48 hours.
2. Risk is now bounded by the explicit triple-caller enumeration in Section 2 + verification footer; the AD-734 wire-shape contract test still does not catch signature drift, but all 3 callers are pinned to single-line edits in the same commit.
3. The cross-prompt collision risk with AD-724 on `routers/agents.py` is closed by the explicit "Skip lines 1106–1145" carve-out.

AD-724 dropped from "tied for highest risk" to "moderate" because pass-1 Required #1 (duplicate config class) was a fail-fast surface — the gate's own test suite would have raised AttributeError immediately on the focused gate. AD-720d-1's risk surface (signature drift across distant callers) is harder to catch at green-test time.

## Cross-prompt concerns (pass-2)

1. **`routers/agents.py` shared by AD-724 and AD-720d-1.** Resolved. AD-724 owns lines 1106–1145 (sanity-gate retry); AD-720d-1 owns lines 894 (init), 914 (destructure), and 1228–1252 (episode write). Explicit carve-outs in both prompts. Either can land first.
2. **`config.py` shared by AD-724 and AD-720d-1.** Different classes (`DmSanityGateConfig` at line 3236 vs `AttachmentsConfig` at line 1112). Safe.
3. **No UI-prompt collisions** (unchanged from pass-1).
4. **No collisions with in-flight vision-pipeline files** outside what AD-720d-1 owns. AD-734 hook will still fire on the AD-720d-1 commit.

## Recommendation

**ADVANCE to GATE 1 (architect approval to dispatch builder).**

All pass-1 Required findings are genuinely addressed against the live codebase. Both revised prompts now have:

- Unambiguous single-anchor SEARCH/REPLACE targets.
- Verification footers consistent with HEAD greps.
- Explicit cross-prompt carve-outs.
- Folded type-annotation and import-order Recommendeds.

No NEW Required findings were uncovered. The single new pass-2 Recommended (AD-724 Solution Overview ↔ Section 3 drift on the second inline strip) is idempotent-and-safe — Builder may optionally remove proactive.py:3479-3480 for cleanliness but the prompt does not require it.

## Standing-rule reminders for the Builder (post-approval)

- Test gate full: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile`.
- AD-734 pre-commit hook will fire on the AD-720d-1 commit — do not bypass with `--no-verify`.
- Working tree: surface unidentified tracked-file modifications; do not `git stash` / `git reset --hard`.
- Inline-blob anti-pattern: per-attachment timing fields stay small; no base64 in `IntentMessage.params`.
- One commit per AD; commit-message format `AD-NNN(x): <summary> (Wave 154)` with `Closes #NNN`.
- For AD-724: extend BOTH `DmSanityGateConfig` copies identically; add `Field` to the `dm_sanity_gate.py:22` pydantic import; module-top import in `proactive.py`.
- For AD-720d-1: update all 3 `build_multimodal_messages` destructure sites in the same commit; preserve the existing ~95-line loop body verbatim (only the loop header changes); init `per_attachment` at agents.py line 894 alongside `vision_messages`; do NOT touch lines 1106-1145.
