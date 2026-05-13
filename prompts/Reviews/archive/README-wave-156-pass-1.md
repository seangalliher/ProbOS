# Wave 156 — Pass 1 Sweep Summary

**Date:** 2026-05-13
**Reviewer:** Architect
**Scope:** First-pass review of three Wave 156 prompts (HXI ergonomics + agent expression).

---

## Per-prompt verdict

| AD | Prompt | Verdict | One-line justification |
|---|---|---|---|
| AD-735 | [ad-718f-per-agent-volume.md](../ad-718f-per-agent-volume.md) | ✅ Approved | Backend chain verified shipped; SEARCH blocks match HEAD; single-file UI insert mirroring Pitch/Rate pattern. One JSDOM clamp-test nit and one inconsistency in test count phrasing. |
| AD-736 | [ad-705d-mic-permission-ux.md](../ad-705d-mic-permission-ux.md) | ⚠️ Conditional | State machine is sound, but the mount-point file for `<MicPermissionHint />` is unspecified (prompt names `HXIShell.tsx`, which does not exist; actual root is `App.tsx`). One off-by-13 line reference; missing SEARCH for `_teardown` insertion. |
| AD-737 | [ad-722a-3-emotion-taxonomy.md](../ad-722a-3-emotion-taxonomy.md) | ⚠️ Conditional | Highest-risk prompt. Dataclass and prompt-builder pieces are clean, but `fired.append(f"custom_{intent}")` silently breaks `compute_divergence` scoring (`startswith("intent_")` filter strips custom names → match_score = 0.0 for every custom-emotion reply). Additionally `apply_divergence_check` integration is described in prose only — no SEARCH/REPLACE provided for the most subtle change in the prompt. |

---

## Total Required findings

**6 Required across the three prompts**, distributed:

- AD-735: **0 Required**
- AD-736: **2 Required** (mount-point file; off-by-13 line reference)
- AD-737: **3 Required** (`custom_*` rule-name filter break; missing `apply_divergence_check` SEARCH/REPLACE; custom-name case normalisation test gap)

Recommendations: **14 total** (AD-735: 2, AD-736: 5, AD-737: 7).

Nits: **9 total** (AD-735: 3, AD-736: 3, AD-737: 3).

---

## Highest-risk prompt

**AD-737 — Per-agent custom emotion taxonomy.**

Three reasons:

1. **Silent scoring corruption.** The `custom_X` rule-name choice produces a working pipeline that ALWAYS reports maximum divergence for any custom emotion. Tests as currently written (Section 5, test 6) assert the broken shape (`"custom_professional_concern"` in `fired_rules`) and will pass — masking the real failure. Without a fix, every Counselor "professional_concern" reply would weaken her trust score and Hebbian edges; the feature would actively HARM agents that opt in. This is exactly the type of architectural-seam-hidden-behind-passing-tests pattern the user-memory warns about (the 2026-05-12 ten-guard vision arc).
2. **Under-specified integration.** The most subtle change (threading `custom_emotions` through `apply_divergence_check`'s three internal calls — parse, modulate, score) is described in prose only. Past waves have shown that prose-described "Builder: grep and find" instructions produce drift between architect intent and shipped code. This is the kind of gap that produced 6 BFs in the BF-265 → AD-731 → BF-274 wave-151/152 sequence (also user-memory lesson).
3. **Cross-layer blast radius.** AD-735 touches one file; AD-736 touches three files in one subsystem. AD-737 touches FOUR files across substrate (`crew_profile`), the avatar pipeline (`divergence_detector`, `telemetry`), and the cognitive layer (`cognitive_agent`). Any miss compounds.

---

## Cross-prompt concerns

1. **None of the three prompts share files or call paths.** Parallel-safe at the file level. Build order in WAVE-156-DISPATCH (AD-735 → AD-736 → AD-737) is appropriate; could be done in any order.

2. **HXI mount-point convention is fragile.** AD-736 punts on the mount file; the live HXI root is `App.tsx` (confirmed). Future HXI overlay ADs should standardise on App.tsx as the named mount point until a true `HXIShell.tsx` is introduced. Worth a one-line note in the wave dispatch file's "Inputs" section so future architect drafts don't repeat the mistake. (This is a wave-dispatch finding, not a prompt finding.)

3. **All three prompts honour the AD-731 invariant** and HXI Design Principle #3 (no emoji; inline SVG). Verified.

4. **All three prompts have explicit boundary tests** (happy + error/edge) per copilot-instructions, with AD-737's set being the weakest (Test 6 needs to be rewritten per Required #1 above).

5. **Verify-first discipline applied unevenly.** AD-735 has the strongest "Verified Against Codebase" block (every concrete claim grep-checked). AD-737's block claims `parse_intent_self_tag` is in `routers/agents.py` but the actual single call site is inside `divergence_detector.py` itself (line 356, in `apply_divergence_check`). AD-736's verified block doesn't mention the mount-point file at all because the prompt doesn't know what it is.

6. **No phantom APIs introduced into production code.** All Required findings are about *under-specification* or *integration shape*, not invented method signatures. The phantom-API-precheck script the dispatch references should pass cleanly. (Recommend the Builder still run it per wave standing orders.)

7. **AD-734 pre-commit hook will not fire** for any of these prompts (no chat router / LLM client / system.yaml touch). Dispatch correctly notes this.

8. **License posture clean across the wave.** No external absorption, no new deps, all-internal Apache 2.0.

---

## Recommendation

**REVISE the prompts.** Do NOT proceed to build until:

1. **AD-737 Section 3b** is updated to either (a) append both rule names (`intent_concerned` AND `custom_professional_concern`) — recommended fix — or (b) pre-resolve `intent` to the parent in `apply_divergence_check` before calling `compute_divergence`. Whichever the architect picks, Test 6 in Section 5 must assert the corrected shape and a NEW test must verify `match_score` is non-zero for a fully-correct custom-emotion reply (the divergence score should mirror the parent's).
2. **AD-737 Section 2c** is rewritten with explicit SEARCH/REPLACE for `apply_divergence_check` showing the three threaded calls (parse, modulate, score) and the pre-resolution of `intent` for `compute_divergence`.
3. **AD-736 Section 0 and Section 2** are updated to name `ui/src/App.tsx` as the mount file and provide a concrete SEARCH context (e.g., the line containing `<DecisionSurface />` at line 169) as the insertion anchor.
4. **AD-735** is OK to ship as-is, modulo two minor cleanups: (a) reword test 4 to not rely on JSDOM's HTML constraint validation, (b) align test-count language in Section 2.

After these revisions, a 5-minute pass-2 re-review should suffice for AD-736. AD-737's pass-2 should re-verify the divergence-scoring fix end-to-end (the architect should write the new test assertion in the revision itself, not leave it to the Builder).

**Wave 156 stays parallel-safe**, so all three revised prompts can ship in one consolidated PR (one commit per AD), as originally planned in `WAVE-156-DISPATCH.md`.

---

## Verified against codebase (audit trail)

```
AD-735 backend chain:
  src/probos/crew_profile.py:108            VoiceProfile.volume = 0.8                ✓
  src/probos/crew_profile.py:124            validator 0.0 <= volume <= 1.0           ✓
  src/probos/routers/agents.py:237          @router.put("/{agent_id}/voice-profile") ✓
  ui/src/audio/voice.ts:139                 utterance.volume = effective.volume ?? 0.8  ✓
  ui/src/components/profile/ProfileInfoTab.tsx:333-360   Pitch/Rate sliders SEARCH block matches ✓
  ui/src/components/profile/__tests__/                   NEW directory; does not yet exist (Builder creates) ✓

AD-736 wake-word state machine:
  ui/src/audio/wakeWord.ts:32-37            WakeWordState enum                       ✓
  ui/src/audio/wakeWord.ts:38-40            WakeFallbackReason enum                  ✓
  ui/src/audio/wakeWord.ts:145-150          SR support gate (actual ~148-156)        ✓
  ui/src/audio/wakeWord.ts:234              onError 'not-allowed' _emitFallbackToast ✓
  ui/src/audio/wakeWord.ts:249              _ingestTranscript (prompt says 262+ — OFF BY 13)
  ui/src/audio/wakeWord.ts:463              _emitFallbackToast                       ✓
  ui/src/HXIShell.tsx                       DOES NOT EXIST                           ✗ (Required #1)
  ui/src/App.tsx:169                        <DecisionSurface /> mount — true HXI root ✓

AD-737 emotion taxonomy:
  src/probos/avatars/divergence_detector.py:33-44   EmotionalIntent (8 values)        ✓
  src/probos/avatars/divergence_detector.py:36-37   "AD-722a-3 (#612)" forward marker ✓
  src/probos/avatars/divergence_detector.py:86-89   _TAG_RE accepts [a-zA-Z_]+        ✓
  src/probos/avatars/divergence_detector.py:173     parse_intent_self_tag             ✓
  src/probos/avatars/divergence_detector.py:249     compute_divergence applied_set filter `startswith("intent_")` (Required #1)
  src/probos/avatars/divergence_detector.py:356     parse_intent_self_tag CALLER     ✓ (NOT in routers/agents.py as prompt claims)
  src/probos/avatars/divergence_detector.py:378     apply_voice_modulation CALLER inside apply_divergence_check (Required #2)
  src/probos/avatars/telemetry.py:97                _REQUIRED_INTENT_EMOTIONS         ✓ (preserved)
  src/probos/avatars/telemetry.py:184-188           AD-722a-3 forward marker         ✓
  src/probos/avatars/telemetry.py:396               apply_voice_modulation signature ✓
  src/probos/avatars/telemetry.py:725               caller in snapshot_for_agent     ✓
  src/probos/cognitive/cognitive_agent.py:3170-3196 _build_intent_self_tag_instruction ✓
  src/probos/runtime.py:410                         self.profile_store = ProfileStore(...)  ✓

Wave-level invariants:
  No bus / RPC / IntentMessage.params touches in any prompt                          ✓ (AD-731 preserved)
  No modulation_manifest.json edits                                                   ✓
  No _REQUIRED_INTENT_EMOTIONS / EmotionalIntent expansion                            ✓
  No emoji in any HXI surface; all glyphs are inline SVG with strokeWidth: 1.5       ✓
  No new dependencies in pyproject.toml or ui/package.json                            ✓
```
