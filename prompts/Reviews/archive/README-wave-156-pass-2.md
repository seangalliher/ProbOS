# Wave 156 — Pass 2 Sweep Summary

**Date:** 2026-05-13
**Reviewer:** Architect
**Scope:** Second-pass review of three Wave 156 prompts after revision.

---

## Per-prompt pass-2 verdict

| AD | Prompt | Pass-1 | Pass-2 | One-line justification |
|---|---|---|---|---|
| AD-735 | [ad-718f-per-agent-volume.md](../ad-718f-per-agent-volume.md) | ✅ | ✅ | Both Recommended cleanups landed (Test 4 rewrite + test-count phrasing). One cosmetic nit: duplicate Revision section (corrupted markdown twin) — delete-on-commit, no implementation impact. |
| AD-736 | [ad-705d-mic-permission-ux.md](../ad-705d-mic-permission-ux.md) | ⚠️ | ✅ | Both Required findings resolved. Mount-point re-anchored to `App.tsx` with byte-accurate SEARCH against [App.tsx:167-170](../../ui/src/App.tsx#L167-L170); `_ingestTranscript` line 249 SEARCH block matches [wakeWord.ts:249-251](../../ui/src/audio/wakeWord.ts#L249-L251) byte-for-byte. |
| AD-737 | [ad-722a-3-emotion-taxonomy.md](../ad-722a-3-emotion-taxonomy.md) | ⚠️ | ✅ | All three Required findings resolved. Dual-tag (`intent_concerned` + `custom_X`) + pre-resolution (`resolved_v1` via `_resolve_intent_name`) verified mathematically against live `compute_divergence` filter ([divergence_detector.py:260-262](../../src/probos/avatars/divergence_detector.py#L260-L262)). Test 8 pins the v2-parity invariant end-to-end. `apply_divergence_check` SEARCH/REPLACE matches [line 355-388](../../src/probos/avatars/divergence_detector.py#L355-L388). |

---

## Final wave verdict

**✅ APPROVE — advance to GATE 1.**

Per Convention #15 (relaxed): 3/3 ✅ with 0 ⚠️ on highest-risk. The wave clears the bar with margin.

Pass-2 found zero new Required findings across all three prompts. The single net-new finding is a cosmetic nit (duplicate Revision block in AD-735) that does not affect implementation and can be cleaned up by the Builder during commit (or left in — it is below the threshold of a fix-before-build issue).

---

## Highest-risk prompt

**AD-737 — Per-agent custom emotion taxonomy.** Unchanged from pass-1.

The revision addressed the highest-stakes architectural risk in the wave: the silent scoring corruption introduced by appending `custom_X` (instead of `intent_X`) to `fired_rules`. The dual-tag + pre-resolution fix is mathematically sound and verified end-to-end:

1. `apply_voice_modulation` emits both `intent_concerned` AND `custom_professional_concern`.
2. `apply_divergence_check` pre-resolves `professional_concern` → `concerned` via `_resolve_intent_name` before calling `compute_divergence`.
3. Live `compute_divergence`'s `startswith("intent_")` filter strips the custom tag at scoring time, leaving `applied_set = frozenset({"intent_concerned"})`.
4. `expected = INTENT_EXPECTED_RULES["concerned"] = frozenset({"intent_concerned"})`.
5. Jaccard = 1.0 → `match_score = 1.0`, `magnitude = 0.0`.
6. `dataclasses.replace(result, intent_emotion=intent)` restores the agent's vocabulary on the returned `DivergenceResult`.

Test 8 (`test_custom_emotion_divergence_score_equals_parent`) asserts this invariant directly against `apply_divergence_check`. Test 6's rationale comment was also updated to flag the `match_score = 0.0` failure mode if either half of the fix is skipped.

AD-737 remains the highest-risk prompt by blast radius (four files across substrate / cognitive cross-cutting / cognitive) and by subtlety of the scoring math, but the prompt is now correctly specified for the Builder.

---

## Cross-prompt concerns

1. **No new cross-prompt regressions.** All three revisions are surgical — file lists unchanged, scope unchanged, AD-731 invariant unchanged, v1 manifest invariant unchanged, no new dependencies.

2. **Parallel-safety preserved.** No file overlap between the three prompts. Build order in `WAVE-156-DISPATCH.md` (AD-735 → AD-736 → AD-737) remains appropriate.

3. **Verify-first discipline applied uniformly in pass-2.** All three Required findings from pass-1 had concrete file:line evidence; all three revisions provided concrete file:line counter-evidence in their "Verified Against Codebase" updates.

4. **Phantom-API risk eliminated for the wave.** AD-737's "single call site is in `routers/agents.py`" claim from pass-1 was a phantom — corrected in the revision to point at `divergence_detector.py:356` (the actual call site). No remaining phantom APIs in any of the three prompts.

5. **HXI Design Principle #3 honoured across the wave.** AD-735 inline SVG speaker glyph, AD-736 inline SVG mic glyph + `×` (U+00D7 typography), AD-737 no UI change. No emoji introduced.

6. **License posture clean.** Apache 2.0 across the wave; no external absorption.

---

## Recommendation

**ADVANCE to GATE 1.** The three revised prompts are build-ready as a parallel-safe wave.

Pre-commit hygiene reminders for the Builder:
- AD-735: delete the duplicate Revision block (lines 290-296 of the prompt) before commit, or leave it — cosmetic only.
- AD-736: confirm SR-error `'audio-capture'` string passes through `speechInput.ts` verbatim before relying on the new branch (pass-1 Recommended #2 — non-blocking but worth a 30-second grep).
- AD-737: run the new test 8 first if a single regression test is needed to sanity-check the dual-tag + pre-resolution wiring before the rest of the suite.

The wave is parallel-safe at the file level; all three may ship in one consolidated PR (one commit per AD) as originally planned in `WAVE-156-DISPATCH.md`.

---

## Verified against codebase (pass-2 audit trail)

```
AD-735:
  Section 2 test list (line 158-167)        5 tests total; one with two assertions     ✓
  Section 2 lead-in                         "5 tests total" phrasing applied           ✓
  Section 1 SEARCH/REPLACE                  unchanged from pass-1                      ✓
  Revision section at line 279              canonical                                  ✓
  Revision section at line 290              DUPLICATE (corrupted twin) — cosmetic nit  ✓

AD-736:
  Section 0 file table                      ui/src/App.tsx named with justification    ✓
  Section 2 mount SEARCH/REPLACE            byte-for-byte vs App.tsx:167-170           ✓
  Section 1d _ingestTranscript SEARCH       byte-for-byte vs wakeWord.ts:249-251       ✓
  Section "Verified Against Codebase"       App.tsx:169 + wakeWord.ts:249 confirmed    ✓
  Test plan (5 + 2 tests)                   unchanged from pass-1                      ✓

AD-737:
  Section 2c SEARCH block (line 322-355)    byte-for-byte vs divergence_detector.py:356-388 ✓
  Section 2c REPLACE block                  custom_emotions threaded through 4 sites
                                            (lookup, parse, modulate, compute+restore) ✓
  Section 3b REPLACE block                  fired.extend([rule["rule_name"],
                                            f"custom_{intent}"]) — dual tag           ✓
  _resolve_intent_name (Section 2a)         defined; short-circuits to v1 if v1, else
                                            looks up custom_emotions[name].inherits   ✓
  compute_divergence filter (live)          startswith("intent_") at
                                            divergence_detector.py:260-262             ✓
  INTENT_EXPECTED_RULES["concerned"] (live) frozenset({"intent_concerned"})            ✓
  Test 8 assertion                          result_custom.match_score ==
                                            result_parent.match_score (+ magnitude,
                                            signed_divergence, intent_emotion split)  ✓
  Test 6 critical-rationale comment         "BOTH intent_concerned AND
                                            custom_professional_concern; the
                                            startswith filter strips custom_X"        ✓
  routers/agents.py phantom claim           explicitly corrected in revision          ✓

Wave-level invariants (unchanged from pass-1):
  No bus / RPC / IntentMessage.params touches                                          ✓
  No modulation_manifest.json edits                                                    ✓
  No EmotionalIntent / _REQUIRED_INTENT_EMOTIONS expansion                             ✓
  No new dependencies in pyproject.toml or ui/package.json                             ✓
  HXI Design Principle #3 honoured (inline SVG, no emoji)                              ✓
  AD-731 attachment invariant honoured                                                 ✓
```
