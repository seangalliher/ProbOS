# Review: AD-721b-2 — Browser-side real-audio capture for lip-sync
**Verdict:** ⚠️ Conditional
**Hook activation contradicts itself between Section 2c (careful gating) and Section 3a (hardcoded `enabled: true`); audio mime acceptance is the same cross-prompt risk as AD-721b-1 #2.**

## Required (must fix before building)

1. **Hook activation contradiction.** Section 2c spends a paragraph discussing how to gate the hook on the operator's `lipsync.backend` setting ("Verify at build time whether an existing endpoint exposes operator config (e.g. `GET /api/system/config` …)"), but Section 3a then hardcodes `useLipSyncCapture({ enabled: true, agentId })` in `CrewVRM.tsx`. With `enabled: true` hardcoded, every utterance on every browser tries capture → MediaRecorder spin-up → 0 bytes → empty frames → fallback. Correctness is preserved (honest-degrade), but: (a) the test "useLipSyncCapture does not capture when disabled" verifies a code path that's never exercised in production, (b) every utterance pays the AudioContext + MediaRecorder allocation cost, (c) the `enabled` parameter is dead. Lock one of the two paths now: either hardcode `enabled: false` in Section 3a until a follow-up AD adds the config-fetch surface, or wire to an existing source. **Verified: `GET /api/system/config` does NOT exist** ([src/probos/routers/system.py](src/probos/routers/system.py#L22-L284) — 22 endpoints, none expose general config). The Builder will pick whatever is easiest and that decision won't be reviewed.

2. **`audio/webm` mime acceptance — cross-prompt with AD-721b-1.** Capture defaults to `audio/webm` (Section 1, `mimeType ?? 'audio/webm'`). Upload calls `POST /api/chat/attachments/multipart`, which delegates to `_validate_and_store_attachment` and validates against `AttachmentsConfig.allowed_mimes`. If the existing allow-list rejects `audio/webm`, **every capture upload silently 415s** and the hook returns empty frames forever — indistinguishable from "browser doesn't route SpeechSynthesis." This is the same cross-prompt issue flagged in the AD-721b-1 review (Required #2); the canonical fix belongs in AD-721b-1, but AD-721b-2 must verify and call out the dependency in Section 0 ("Do NOT touch" → "must coordinate with AD-721b-1's allow-list change"). Otherwise the wave can ship green tests and produce zero user-visible change.

## Recommended

1. **AudioContext leak risk on rapid-fire utterances.** The hook constructs a new `AudioContext` per `'start'` event. Browsers cap concurrent AudioContexts at ~6 (Chromium); a cancelled-then-restarted utterance flow could leak before `finally { ctx?.close() }` runs (the `inflight` promise is fire-and-forget, never awaited from the cleanup return). Recommended: add a `currentCtxRef` in the hook that closes any prior context when a new `'start'` arrives, and a stress test that fires 10 starts in rapid succession and asserts no console errors / no orphaned contexts. The current `mounted` flag protects React state but not the `AudioContext` resource.

2. **`captureUtteranceAudio` is awaited inside an async IIFE inside the listener (Section 2 hook body).** `inflight` is captured but never awaited from the cleanup function. If a caller unmounts mid-capture, the cleanup returns immediately, the IIFE keeps running until `setTimeout` fires (up to 30s default `maxDurationMs`), and the recorder/context cleanup happens then. This is correct under the `mounted=false` guard but means the test `useLipSyncCapture cleans up subscription on unmount` (#8) needs to verify behaviour up to 30s — flaky in CI. Recommended: shorten `maxDurationMs` injection for tests OR cancel the inflight via an `AbortController` on cleanup.

3. **Test #5 (`useLipSyncCapture does not capture when disabled`)** is meaningful only if the production caller can pass `enabled: false`. With Required #1's hardcoded `true`, this test guards a configuration path that doesn't exist. Either lift `enabled` to a real config fetch (preferred) or note this test is purely defensive scaffolding for a future AD.

4. **`fire({ type: 'start', ...})` helper at `ui/src/__tests__/ModulationIndicator.test.tsx:35`** is cited as the test pattern. Verify the helper still has the `(type, agent_id, utterance)` signature and exports the way the new test files expect — the cross-test reference is fragile if `ModulationIndicator.test.tsx` evolves.

5. **Activation probe via `uploadAudioForLipSync` with a "tiny synthetic blob"** (Section 2c, second alternative) is a footgun: it would create a real attachment in the store on every page load and call rhubarb on noise. Strike this option from the prompt or replace with "ship `enabled: false` and add a `GET /api/avatars/lipsync/status` config-introspection endpoint in the same prompt."

## Nits

1. Regression test path: `ui/src/__tests__/CrewVRM.realAudioFallback.test.tsx` puts the new file at workspace-root tests, but the existing CrewVRM test lives at `ui/src/components/profile/__tests__/CrewVRM.expressionResting.test.tsx`. Co-locate for consistency.

2. `console.info` / `console.warn` direct calls — fine for browser code, but worth noting whether HXI has a structured frontend logger that could be used instead (consistency with backend `logger.warning` discipline). Not a blocker.

3. Section 1's `LipSyncResponse.backend` union `'rhubarb' | 'heuristic' | 'disabled'` — the hook checks `resp.backend !== 'rhubarb'` to short-circuit. Sensible, but a future fourth backend value (e.g., `'whisper'`) would need a hook update. Consider `resp.backend === 'rhubarb'` as the only positive case (already the pattern) and document.

4. Forward marker AD-721b-2.3 ("Server-streamed TTS path") is correctly noted as a material architecture change but the wording "obsoletes the browser-capture problem entirely" understates that the entire `lipSyncCapture.ts` module becomes dead code. Worth a comment in the module header that the capture path is transitional.

## Verified

- ✅ AD-731 invariant explicitly tested by test #3: "**CRITICAL: assert the lipsync request body is JSON with the ref, NOT a base64 blob (AD-731 invariant).**"
- ✅ `onSpeechEvent` exists at [ui/src/audio/voice.ts](ui/src/audio/voice.ts#L35) with the `(type, agent_id, utterance)` shape the hook expects.
- ✅ `buildHeuristicTrack` consumer at [ui/src/components/profile/CrewVRM.tsx](ui/src/components/profile/CrewVRM.tsx#L322) — confirmed; surgical insertion point in Section 3b is realistic.
- ✅ `_VISEME_TARGETS` exported at [ui/src/audio/lipSyncTrack.ts](ui/src/audio/lipSyncTrack.ts#L262) (`export const _VISEME_TARGETS = VISEME_TARGETS;`) — Section 3b's `_VISEME_TARGETS[active.viseme as VisemeKey]` will resolve.
- ✅ `ZERO_WEIGHTS` at [ui/src/audio/lipSyncTrack.ts](ui/src/audio/lipSyncTrack.ts#L63) is **not** exported (verified). Prompt acknowledges and provides local-fallback guidance ("if `ZERO_WEIGHTS` is not exported... define a local const inside CrewVRM rather than touching the shared module") — correct.
- ✅ Honest-degrade chain documented end-to-end: capture-fail → upload-fail → server-degraded → empty frames → AD-721b v1 heuristic → AD-721 D5 amplitude.
- ✅ `mounted` ref pattern for unmount-safe setState — correct React pattern.
- ✅ `setTimeout` safety bound (30s default) on utterance-end wait prevents hang if browser `onend` never fires.
- ✅ `AudioContext.close()` in `finally` block — present (modulo Recommended #1 about rapid-fire leaks).
- ✅ No new npm dependencies added — uses only browser stdlib (Web Audio, MediaRecorder, fetch, FormData).
- ✅ No emoji in any code, comment, or test added (HXI Design Principle #3 honored).
- ✅ No new UI component / chrome added — capture is invisible to the user (correct per HXI Design Principle #6: motion communicates state, capture infrastructure has no visual surface).
- ✅ License Disposition complete: Web Audio + MediaRecorder are W3C/WHATWG standards, no concern; new TS code Apache 2.0; no external code absorbed.
- ✅ "What this does NOT change" section explicitly enumerates 7 adjacent systems left untouched.
- ✅ Forward markers AD-721b-2.1/2.2/2.3 + AD-721b-3 properly documented with deferral rationale.
- ✅ Phase ordering (review-criteria #10): N/A — pure UI hook + consumer wiring, no Python startup phases involved.
- ✅ Multipart upload path [src/probos/routers/chat.py](src/probos/routers/chat.py#L756) (`@router.post("/chat/attachments/multipart")`) confirmed exists; prompt's wire to it is realistic.

---

### Re-review (pass-2) — 2026-05-12

**Verdict:** ✅ Approved
**Both pass-1 Required findings cleanly addressed. The "always-on, server-side honest-degrade" framing is consistent end-to-end. No new Required introduced. One revision-table miscount and one Section-4 header undercount remain at Recommended tier.**

#### Pass-1 Required — verification

| # | Finding | Resolution in revision | Live-codebase / prompt verification |
|---|---|---|---|
| R3 | Hook activation contradiction (Section 2c careful-gating vs Section 3a hardcoded `enabled: true`); orphaned `GET /api/system/config` reference | Took option (b) from pass-1 reviewer's recommendations: hardcoded `enabled: true`. Captain Decision #3 rewritten as "Always-on capture; honest-degrade end-to-end on the server." Section 2c rewritten as purely documentary (4 numbered chain-points: capture-fail → server-fail → degraded-empty → CrewVRM-fallback). Synthetic-blob probe footgun struck. The orphaned `GET /api/system/config` reference is removed. | ✅ Verified: `grep -n "system/config\|api/system/config" prompts/ad-721b-2-browser-real-audio-capture.md` returns zero hits. The `enabled: false` code path is preserved in the hook signature with a comment noting future-use intent (e.g. an HXI Captain-facing toggle). Test #5 (`useLipSyncCapture does not capture when disabled`) was dropped from Section 4 per Recommended #3. The remaining tests still exercise the always-on path correctly. |
| R4 | Mime cross-prompt dependency on AD-721b-1 must be called out | New "Coordination with AD-721b-1 (mime allow-list seam)" sub-section between Section 0 intro and the "Do NOT touch" list. Build order asserted: AD-721b-1 first, AD-721b-2 second. `config.py` and `attachments/mime.py` added to "Do NOT touch". | ✅ Verified: AD-721b-1 Section 0.5 owns both gates (allow-list + magic-byte), and the dispatch already enforces Group A → Group B build order. The cross-prompt seam is now explicit and unambiguous. |

#### New Required findings

**None.** The revision is surgical: the `lipSyncCapture.ts` and `useLipSyncCapture.ts` source bodies are unchanged from pass-1 (verified in the prompt body). Only the framing prose, Section 2c, the regression-test path (co-located per Nit #1), and the dropped "disabled" test changed.

#### "Always-on, server-side honest-degrade" framing — consistency audit

| Location | Statement | Aligned? |
|---|---|---|
| Captain Decision #3 | "Always-on capture; honest-degrade end-to-end on the server. The hook is hardcoded `enabled: true`. Every utterance attempts capture." | ✅ |
| Section 2c | "The hook is hardcoded `enabled: true` at the call site. No config-fetch endpoint is added by this prompt. Honest-degrade chains end-to-end on the server side." | ✅ |
| Section 3a code-comment | "AD-721b-2: real-audio capture path. Always-on — honest-degrade chains end-to-end on the server" | ✅ |
| Section 3a code | `useLipSyncCapture({ enabled: true, agentId })` | ✅ |
| Section 4 test list | Test #5 dropped (was "does not capture when disabled" — now Test #5 is "exposes empty frames when capture returns null", an always-on degraded path) | ✅ |
| Forward markers | No probe-endpoint forward marker. The Captain-toggle use case is mentioned only in the in-code comment of `useLipSyncCapture.ts`. | ✅ |

No orphaned references to `GET /api/system/config`, no probe-via-synthetic-blob alternative, no contradictions between Captain decisions and Section 3a wiring.

#### Internal consistency — Solution Overview / Files-touched / verification footer

- ✅ **Files-touched table** lists `CrewVRM.realAudioFallback.test.tsx` at the co-located path (`ui/src/components/profile/__tests__/`) per Nit #1. The pass-1 root-tests path is gone.
- ✅ **"Do NOT touch" list** now includes `src/probos/config.py` and `src/probos/attachments/mime.py` (R4 cross-prompt boundary).
- ✅ **Coordination** sub-section explicitly references AD-721b-1's Section 0.5 as the allow-list owner, build-order requirement, and consequence-of-skip ("every capture upload silently 415s").
- ✅ **Verified Against Codebase** footer pre-existing checks (onSpeechEvent, buildHeuristicTrack, currentTrackRef, _VISEME_TARGETS, multipart endpoint at chat.py:757) all still hold per pass-1; revision did not invalidate them.
- ✅ **Acceptance criteria** still asserts AD-731 invariant testing (test #3 — body is JSON ref, not base64).
- ✅ **License Disposition** unchanged (correct — no new external code absorbed).

#### Recommended (cosmetic, not blocking)

1. **Test count miscount in revision table.** The revision table claims "Test count drops 7 → 6 (3 pure + 3 hook + 1 regression)". Section 4 actually lists **8 tests** (4 pure + 3 hook + 1 regression: tests numbered 1-8). The dropped "does not capture when disabled" test reduces the count from a pre-revision 9 → 8, not 7 → 6. The math in the revision table is wrong, but the actual test list in Section 4 is internally coherent (tests 1-8 with subsection counts 4 + 3 + 1 = 8).

2. **Header / Section-4 / acceptance criteria undercount.** Header says "≥ 6 new Vitest"; Section 4 heading says "≥ 7 new Vitest"; acceptance criteria says "All ≥ 6 new Vitest tests pass". Actual enumerated count is 8. All three lower-bound figures are conservative; Builder writing the 8 listed tests satisfies all three. Nice-to-fix but not a defect.

3. **Recommended-tier deferrals from pass-1 explicitly noted as deferred.** The revision table closes with "Recommended #1 (AudioContext leak risk on rapid-fire utterances), Recommended #2 (AbortController on cleanup), and Recommended #4 (test-pattern fragility note) are deferred to AD-721b-2.1+ as stress/hardening follow-ups; they do not block the wave." This is acceptable scoping; the leak risk is operationally bounded by the always-on `setTimeout(maxMs)` safety bound, and the test-pattern fragility is a future-test concern not a build defect. Forward markers should mention these in `AD-721b-2.1` if filed.

#### Verified (pass-2 spot-check)

- ✅ `grep -n "Revision \(2026-05-12\)" prompts/ad-721b-2-browser-real-audio-capture.md` returns 1 hit at line 605 (matches AD-721b-1's pattern).
- ✅ `grep -n "GET /api/system/config\|/api/system/config" prompts/ad-721b-2-browser-real-audio-capture.md` returns zero hits (orphan reference removed).
- ✅ `grep -n "enabled: true" prompts/ad-721b-2-browser-real-audio-capture.md` shows the hook call site `useLipSyncCapture({ enabled: true, agentId })` in Section 3a — single source of activation truth.
- ✅ Captain Decision #3 explicitly enumerates the four-step honest-degrade chain (capture-fail → server-fail → degraded-empty → CrewVRM-fallback). Matches Section 2c verbatim. Matches Section 3a code-comment.
- ✅ Coordination sub-section makes the cross-prompt dependency on AD-721b-1 Section 0.5 unambiguous.
- ✅ Co-located test path matches existing `CrewVRM.expressionResting.test.tsx` location.
- ✅ AD-731 invariant test #3 body remains: "**CRITICAL: assert the lipsync request body is JSON with the ref, NOT a base64 blob (AD-731 invariant).**"
- ✅ Acceptance criteria includes the standing line: "Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`."
- ✅ Forward markers AD-721b-2.1/2.2/2.3 + AD-721b-3 unchanged.
