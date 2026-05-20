# BF-318 — `speechRecognitionArbiter` priority-queue leases

**Status:** drafted (Wave 180, builds **second**; **hard prerequisite for
AD-747**).
**Issue:** [#683](https://github.com/seangalliher/ProbOS/issues/683).
**Prior-art:** `prompts/RESEARCH-issues-2026-05-19.md` (Issue C, "Bug —
BF-318 — mic singleton conflict"; LiveKit Agents `VoicePipelineAgent`
lease pattern as architecture absorbed under Apache 2.0).
**Estimated work:** half-day.
**Dependencies:** none upstream. **AD-747 consumes the new arbiter API.**
**License posture:** zero new deps; pure new browser-side module +
in-place wiring. **0-line diff on all 5 license files.**

---

## Problem

Three independent acquisition paths fight over the same browser
`SpeechRecognition` singleton with no arbitration:

| Path | Module | Acquisition |
|---|---|---|
| Press-to-talk | `ui/src/components/IntentSurface.tsx` → `startListening()` | Browser `SpeechRecognition` singleton (`activeRecognition` at `ui/src/audio/speechInput.ts:28`) |
| Wake-word continuous transcript-fallback | `ui/src/audio/wakeWord.ts:322` `_startContinuousRecognition()` → `startListening()` | Same singleton |
| VAD | `ui/src/audio/voiceActivity.ts:195` `startVoiceActivity()` | Dedicated `getUserMedia({audio:true})` MediaStream (separate device path; **not** in conflict) |

Root cause: `ui/src/audio/speechInput.ts:28` declares
`let activeRecognition: SpeechRecognitionInstance | null = null`. Every
call to `startListening()` (line 49) immediately invokes
`stopListening()` (line 130) which `.abort()`s the previous session
(line 134) and clears `activeRecognition = null` (line 135). When the
Captain clicks the mic button while wake-word's continuous SR is
running, wake-word's session is aborted; on stop, wake-word's `onend`
handler tries to restart via `_startContinuousRecognition` and races
with `IntentSurface`'s teardown. Race outcomes:
- Wake-word restart wins → press-to-talk transcripts get routed to
  wake-word's callback.
- Press-to-talk teardown wins → the mic icon shows armed, but
  `activeRecognition` was cleared between callback creation and
  `recognition.start()`, so no transcripts arrive.

VAD is **not** part of the conflict (separate `getUserMedia` stream);
it is documented above only to demarcate scope.

## Scope (v1)

One new browser-side module + minimal wiring updates:

1. **New `ui/src/audio/speechRecognitionArbiter.ts`** — single owner of
   the `SpeechRecognition` singleton. Exposes:
   - `acquire(opts: { holder: string; priority: number; onAcquired?: () =>
     void; onPreempted?: (by: string) => void; onReleased?: () => void }):
     Lease | null` — returns a lease handle OR `null` if a higher-priority
     holder already owns the device.
   - `release(lease: Lease): void` — releases the lease; if any queued
     lower-priority requests are waiting, the next one is awarded and its
     `onAcquired` fires.
   - `currentHolder(): { holder: string; priority: number } | null` —
     read-only observer (HXI / tests).
   - Preemption: when a higher-priority `acquire` arrives, the current
     holder's `onPreempted` fires, the lease is invalidated, and the
     higher-priority lease is granted.
   - Priority constants: `PRIORITY_PRESS_TO_TALK = 100`,
     `PRIORITY_CONVERSATION = 75` (reserved for AD-747),
     `PRIORITY_WAKE_WORD = 50`.

2. **`ui/src/audio/speechInput.ts`** — `startListening()` calls
   `arbiter.acquire(...)` with `priority=PRIORITY_PRESS_TO_TALK`
   (default — overridable via new optional `priority` field on
   `ListenOptions`). On `onPreempted`, calls the existing internal
   abort + clear path. The module-level `activeRecognition` stays;
   the arbiter owns ordering, `speechInput` owns the underlying
   recognition instance.

3. **`ui/src/audio/wakeWord.ts`** — `_startContinuousRecognition`
   (line 322) calls `startListening` with explicit
   `priority=PRIORITY_WAKE_WORD`. The existing `onend` restart path
   checks `arbiter.currentHolder()` before re-arming — if a higher
   holder is active, wake-word stays parked and re-arms via
   `onReleased`.

4. **Public API for AD-747.** Export the arbiter module surface
   (`acquire`, `release`, `currentHolder`, the priority constants, and
   the `Lease` type) so AD-747's `ConversationController` can request
   `PRIORITY_CONVERSATION` leases cleanly.

The arbiter is the single source of truth for SR ownership;
`speechInput.ts:activeRecognition` becomes an implementation detail
behind it.

## Non-scope

- NO change to `voiceActivity.ts` (`getUserMedia` audio stream — different
  device path, not in conflict).
- NO change to `whisperStt.ts` (subscribes to VAD PCM ring; doesn't
  touch SR).
- NO change to backend (zero pytest delta).
- NO change to wake-word ONNX detection path (`wakeWord.ts:_loadOnnxRuntime`
  unchanged; only the transcript-fallback continuous-SR path uses the
  arbiter).
- NO change to `IntentSurface.tsx` business logic — the existing
  `speechInput.startListening()` call gains the priority default
  automatically via the new optional parameter.
- NO change to AD-733c-3 `/api/perception/engage` wake-word fire-and-
  forget — still fires on wake event, independently of the arbiter
  lease.

## File targets

| File | Change |
|---|---|
| `ui/src/audio/speechRecognitionArbiter.ts` | **NEW.** ~120 lines: types (`Lease`, `LeaseRequest`), priority constants, module-level state (current holder + queue), `acquire` / `release` / `currentHolder`, `_resetForTests`. |
| `ui/src/audio/speechInput.ts` | Add `priority?: number` to `ListenOptions`; in `startListening`, request a lease before instantiating the SR object; abort + clear on `onPreempted`. ~15-line surgical edit. |
| `ui/src/audio/wakeWord.ts` | `_startContinuousRecognition` (line 322) passes `priority=PRIORITY_WAKE_WORD`; `onend` checks the holder before re-arming; wake-word installs an `onReleased` listener to re-arm when the higher holder finishes. ~25-line edit. |
| `ui/src/audio/__tests__/speechRecognitionArbiter.test.ts` | **NEW.** +6 vitest (see Test targets). |

**Zero backend changes.** Zero new deps.

## Test targets

**+6 vitest** in `ui/src/audio/__tests__/speechRecognitionArbiter.test.ts`:

1. `acquire returns lease when no current holder` — first call resolves
   with a lease; `currentHolder()` reflects the new owner.
2. `lower-priority acquire while held returns null and queues` —
   `acquire(priority=50)` while a `priority=100` lease is active returns
   `null` AND queues the request; on `release(100)`, the queued holder
   gets a lease and its `onAcquired` fires.
3. `higher-priority acquire preempts current holder` —
   `acquire(priority=100)` while `priority=50` is active fires
   `onPreempted("press_to_talk")` on the wake-word holder AND grants the
   new lease in the same tick.
4. `release fires onReleased on queued waiters` — wake-word's
   `onReleased` callback fires when press-to-talk releases, allowing
   wake-word's re-arm path to fire deterministically.
5. `same-priority second acquire returns null (no preemption ties)` —
   two `priority=75` requests cannot oust each other; the second
   queues until release.
6. `release with stale lease is a no-op` — calling `release(lease)`
   after the holder was preempted does NOT pop the queue or affect
   the current holder. Idempotency contract.

The 6 tests give the arbiter full boundary coverage (happy + queue +
preempt + release-fan-out + tie + idempotency). No fakes-of-fakes —
the arbiter has zero dependencies, so tests are pure logic.

Existing `ui/src/__tests__/speechInput.test.ts` and
`ui/src/__tests__/wakeWord.fallback.test.ts` MUST stay green after
the wiring updates. If a pre-existing test assumes
`activeRecognition` is touched without arbiter consent, that test
is updated to acquire a lease first.

## Acceptance criteria

1. `cd ui; npx vitest run -t "speechRecognitionArbiter"` — 6 new tests
   pass.
2. `cd ui; npx vitest run` — full vitest gate green. No regression in
   `speechInput.test.ts` or `wakeWord.fallback.test.ts`.
3. `cd ui; npm run build` — exit 0.
4. **Manual HXI smoke**: with wake-word's continuous SR armed
   (transcript fallback path active), click the press-to-talk mic
   button. Wake-word's transcript stream MUST stop, press-to-talk MUST
   capture transcripts cleanly, and on press-to-talk release, wake-word
   MUST resume without manual re-arm.
5. **No race**: spam press-to-talk start/stop 5 times in quick
   succession; transcripts arrive on every successful capture; the
   mic icon never enters the "armed but no transcripts" stuck state.
6. **AD-747 API surface ready**: the arbiter exports `PRIORITY_CONVERSATION =
   75` and the `Lease` type is in the module's public exports — verified
   by grep, not just by export count.
7. Verify all changes comply with the Engineering Principles in
   `.github/copilot-instructions.md`.

## Forward markers

None filed by BF-318 itself. The arbiter contract is the AD-747
seam — see `prompts/ad-747-conversation-controller.md`.

## Verified Against Codebase (2026-05-19)

```
grep -n "activeRecognition" ui/src/audio/speechInput.ts
  28: let activeRecognition: SpeechRecognitionInstance | null = null;
  117:     activeRecognition = null;
  126:   activeRecognition = recognition;
  133:   if (activeRecognition) {
  134:     try { activeRecognition.abort(); } catch { /* already stopped */ }
  135:     activeRecognition = null;
  140:   return activeRecognition !== null;

grep -n "startListening\|stopListening" ui/src/audio/speechInput.ts
  49: export function startListening(
  61:   stopListening();
  130: export function stopListening(): void {

grep -n "_startContinuousRecognition\|startListening" ui/src/audio/wakeWord.ts
  17:   startListening,
  248:   _startContinuousRecognition();
  322: function _startContinuousRecognition(): void {
  323:   startListening(

grep -n "startVoiceActivity\|getUserMedia" ui/src/audio/voiceActivity.ts
  195: export async function startVoiceActivity(opts: VadOptions = {}): Promise<boolean> {
  209:     if (!md || typeof md.getUserMedia !== 'function') {
  213:     stream = await md.getUserMedia({ audio: true });
```

All anchors confirmed at HEAD (`4beaba7e`).
