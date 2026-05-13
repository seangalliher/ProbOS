# Review: AD-736 — Mic-permission UX polish
**Verdict:** ⚠️ Conditional
**State-machine extension is sound; mount-point file is unspecified and the prompt punts to the Builder — fix before build.**

Reviewer: Architect (Pass 1, 2026-05-13). Prompt file: `prompts/ad-705d-mic-permission-ux.md`.

---

## Required (must fix before building)

1. **Mount-point file for `<MicPermissionHint />` is unspecified.**
   Section 0 file table reads "`ui/src/HXIShell.tsx` (or wherever the HXI root mounts top-level overlays)" and Section 2 ends with "Builder: confirm by grepping `<StatusBar`, `<HXIShell`, `<TopBar`, or `<App>` for the most appropriate parent". I verified: **`HXIShell.tsx` does not exist** (`file_search ui/src/HXIShell*` → 0 files). The actual HXI root is [`ui/src/App.tsx`](ui/src/App.tsx#L169), where `<DecisionSurface />` is mounted at line 169 (verified via `grep "DecisionSurface />"`). The prompt should specify `ui/src/App.tsx` as the mount file and the exact insertion point (e.g., adjacent to `<DecisionSurface />`). Punting to the Builder violates the verify-first standing order; this is exactly the kind of "find it yourself" instruction that produces drift between architect intent and shipped code.

2. **`_ingestTranscript` line reference is off by ~13 lines.**
   Prompt Section 1d says "In `_ingestTranscript` ([wakeWord.ts:262+]...)". Actual location is **line 249** (verified via `grep _ingestTranscript`). The function name is correct and the SEARCH context (`if (_bargedIn) return;`) is unambiguous, but the line reference will mislead a reader doing a quick scan. State "around line 249" or omit the line number.

## Recommended

1. **`_teardown` is referenced but its SEARCH/REPLACE is not shown.**
   Section 1e says "In `_teardown` (called by `stopWakeWordLoop`), add at the end" but provides no SEARCH context — only the new code. The Builder will have to grep for `_teardown` and visually locate the end. Provide a concrete SEARCH block matching the last 3-5 lines of `_teardown` so the insertion is unambiguous.

2. **`audio-capture` SR error string is unverified.**
   Section 1c introduces handling for `err === 'audio-capture'`. The SpeechRecognition Web API spec lists `'audio-capture'` as a valid error name, but the prompt's Verified-Against-Codebase block does NOT confirm `speechInput.ts` passes this error string through verbatim. Verify [ui/src/audio/speechInput.ts](ui/src/audio/speechInput.ts#L102) emits the raw `event.error` string before the build, or the new branch is dead code.

3. **Listener-error log severity inconsistency with the codebase's logging standard.**
   The `_setMicPermission` fan-out catches listener exceptions with `console.warn`. Per copilot-instructions §"Logging Standards", warnings should include *what failed, why it matters, what happens next*. Current message is `'[wakeWord] mic listener error', err` — minimal but adequate. Acceptable; just flag for the closure note.

4. **`role="status"` + dismiss button is mildly ambiguous for assistive tech.**
   The `<div role="status">` announces the message once politely (good), but the `×` dismiss is rendered inside the status region. Screen readers may or may not announce the button. Recommend `aria-label="Voice input unavailable"` on the outer `<div>` and keep `<button aria-label="Dismiss hint">` as-is. Minor a11y polish.

5. **`enumerateDevices` requires HTTPS or `localhost` in modern browsers.**
   `navigator.mediaDevices` is gated behind a secure context. If a Captain accesses the HXI over plain HTTP on a non-loopback host (LAN bridge UI), `navigator.mediaDevices` is `undefined` and the optional-chain skips the probe — the loop continues to the SR error path, which is correct. Add a one-line comment to that effect in Section 1b so the secure-context dependency is documented, and the existing `if (mediaDevices && ...)` guard is recognised as load-bearing.

## Nits

1. **Test 5 (`test_granted_on_first_transcript`) phrasing.**
   "Drive the loop to `armed` via `_simulateWakeFire` (or by injecting a transcript via the stubbed SR)." `_simulateWakeFire` is not defined or referenced anywhere in the prompt. Recommend stating the exact stub mechanism (likely `speechInput.startListening` is mocked and the test invokes the transcript callback directly).

2. **`isDenied = state === 'denied'` is computed twice.** Minor; the JSX could read `state === 'denied'` directly instead of binding a local. Style preference.

3. **`localStorage` key namespace.** `hxi_mic_hint_dismissed` is a single value. If future mic states (e.g., `unavailable_dismissed`, `granted_dismissed`) ever want dismissal, the schema is per-state. Section 7 forward markers don't anticipate this. Optional: `hxi_mic_hint_dismissed_v1` or `hxi_mic_hint:denied`. Minor.

4. **`SHIFT_BOUND` styling — irrelevant** (that's AD-737; cross-prompt noise filtered out).

## Verified

- **`WakeWordState` and `WakeFallbackReason` enums at lines 32-37 / 38-40** match the prompt's reference exactly ✓.
- **SR support gate at lines 145-150** (actual ~148-156) — the SEARCH block is unambiguous ✓.
- **`onError 'not-allowed'` / `'service-not-allowed'` handler around line 234** — the SEARCH block matches; prompt says 230-238, actual `_emitFallbackToast` line is 234 ✓.
- **`_emitFallbackToast` at line 463** — verified (prompt says 463-471) ✓.
- **`onSpeechEvent` import path and lifecycle pattern** [ui/src/audio/voice.ts:33-46](ui/src/audio/voice.ts) — matches the prompt's "state-machine pattern to mirror" claim ✓.
- **`DecisionSurface.tsx` exists and carries the SVG icon family** at [ui/src/components/DecisionSurface.tsx](ui/src/components/DecisionSurface.tsx) — verified via `file_search` ✓.
- **HXI Design Principle #3 honoured.** Inline SVG mic glyph; the slash-line variant for `unavailable` matches the muted-speaker convention; the dismiss `×` is U+00D7, not an emoji ✓.
- **AD-731 invariant preserved.** No bus / RPC / attachment changes ✓.
- **Four-state machine is well-scoped.** `pending`/`granted`/`denied`/`unavailable` map to actionable Captain guidance distinctly. The state is a sub-state of `WakeWordState` (which can be `off` for non-mic reasons too), keeping concerns separated.
- **Boundary tests per copilot-instructions standard.** State-machine tests cover SR-unsupported (error), no-audio-device (edge), denied (error), granted (happy), plus the optional sync-fire-on-subscribe (boundary). Component tests cover both render-states and persistence. Adequate.
- **License posture clean.** Apache 2.0, no external absorption, no new deps. `navigator.mediaDevices.enumerateDevices` is a Web platform standard.
- **Tier-2 log-and-degrade applied correctly.** `enumerateDevices` failure logs warn + continues; listener errors log warn + don't propagate. Both are appropriate per the three-tier model.

---

## Re-review pass record

_None yet — first pass conditional._

---

### Re-review (pass-2, 2026-05-13)

**Verdict:** ✅ Approved
**Both pass-1 Required findings resolved; mount-point and line reference both verified byte-for-byte against HEAD.**

#### Required
_None._

#### Recommended
_None new._ (Pass-1 deferred R1-R5 remain accept-as-shipped per architect's revision note.)

#### Nits
_None new._

#### Verified
- **R1 — Mount-point corrected.** Section 0 file table now names `ui/src/App.tsx` with a justification pointing at the pass-1 review. Section 2 ("Mount the component") provides explicit SEARCH/REPLACE against the four-line block `<GlassLayer />` / `<IntentSurface />` / `<DecisionSurface />` / `<AgentTooltip />`. **Verified byte-for-byte against [ui/src/App.tsx:167-170](ui/src/App.tsx#L167-L170)** — exact match including whitespace and indentation. Import line addition is also concrete.
- **R2 — `_ingestTranscript` line reference corrected.** Section 1d now provides an explicit SEARCH block:
  ` `function _ingestTranscript(transcript: string): void {\n  if (_bargedIn) return;\n  if (_state === 'off') return;` `
  **Verified byte-for-byte against [ui/src/audio/wakeWord.ts:249-251](ui/src/audio/wakeWord.ts#L249-L251)** — exact match.
- **Verified Against Codebase block updated.** Line 513 confirms `App.tsx:169` as the insertion anchor; lines 514 references the overlay region.
- **No scope change.** Section 1 wake-word state-machine edits, the four-state machine semantics, and the test plan (5 + 2 tests) are unchanged from pass-1.
- **All pass-1 Verified items still hold.** Wake-word enum locations, SR support gate, `_emitFallbackToast`, and HXI Design Principle #3 compliance are unaffected by the revision.
