# AD-922 — Captain voice input to the group (push-to-talk → group fan-out)

**Phase-2 of the "Ad-hoc Crew Collaboration (group chat → meeting)" epic. Frontend-only.**
**Highest committed AD: AD-921 (`fe6fbdfb`, git-confirmed HEAD). No AD-922 commit yet.**
**Target repo: OSS (`d:\ProbOS`).**

---

## One-line summary

In an active meeting, give the Captain a push-to-talk mic that transcribes speech with the
existing offline STT and feeds the transcript into the **same `sendText` handler** the keyboard
uses — which already self-routes to the AD-914 group fan-out (`POST /api/threads/{id}/messages`,
`role:"captain"`) when the thread has ≥2 crew. AD-921 then speaks the replies back: a two-way
voice "call." Meeting-gated, echo-gated, honest-degrades to typing.

| Field | Value |
|---|---|
| Status | Ready to build |
| Layer | Experience (UI) |
| Depends on | AD-920 (`metadata.meeting_active` + `MeetingView`), AD-921 (`useMeetingVoice.speakingAgentId`), AD-917 (`sendText` group branch), AD-705a/BF-301 (`transformersStt`), AD-736 (mic-permission state) |
| New files | `ui/src/audio/useMeetingMic.ts`, `ui/src/components/profile/MeetingMicButton.tsx` |
| Edited files | `ui/src/components/profile/ProfileChatTab.tsx` (additive) |
| Estimated tests | **+14 Vitest** (3 files); **no pytest** (no backend change) |
| UI baseline | AD-921 = **1177 passed / 1 skipped** → target **≥ 1191 / 1** |

---

## The key finding (read before building)

The AD-922 roadmap row says route the Captain's voice "through the AD-914 group fan-out (not the
1:1 `agent_chat` path)." **That routing already exists for the keyboard-and-mic send path.** The
transcript does **not** need a new dispatch branch. Here is why:

- The ProfileChatTab push-to-talk mic button already dispatches transcripts via
  `sendText(text)` — [ProfileChatTab.tsx#L1255-L1257](../ui/src/components/profile/ProfileChatTab.tsx#L1255-L1257) (`setTimeout(() => { void sendText(text); }, 100)`).
- `sendText` itself **contains the AD-917 group-routing branch** — [ProfileChatTab.tsx#L567](../ui/src/components/profile/ProfileChatTab.tsx#L567): it reads `groupThreadId` + `crewParticipantCount >= 2` and routes to `POST /api/threads/{groupThreadId}/messages` with `{author_id:"captain", role:"captain", body, attachment_ids}`, renders `per_agent_replies`, and calls `speakMeetingReplies(...)`. Otherwise it falls through to the byte-identical 1:1 `/api/agent/{id}/chat`.

So AD-922 is **not** "branch the dispatch." It is: **give the meeting a dedicated push-to-talk
control that captures one VAD-bounded utterance and calls `sendText(transcript)`** — which
self-routes to the group and triggers AD-921's voice-back for free.

> The only genuinely 1:1-hardwired voice path is **conversation mode**
> ([conversationController.ts#L295-L305](../ui/src/audio/conversationController.ts#L295-L305) posts directly to
> `/api/agent/{id}/chat`, bypassing `sendText`) and the IntentSurface wake-word path. **Both are
> outside the meeting surface — do NOT touch them** (no AD-705a regression). AD-922 adds a
> meeting-scoped control; it does not change the global conversation/wake-word wiring.

---

## Verified context (live code, AD-921 HEAD)

### STT — reuse, build none (`ui/src/audio/transformersStt.ts`)

`whisperStt.ts` is **DEPRECATED (BF-301, #775)** — all call sites use `transformersStt.ts`. Public surface:

| Symbol | Signature | Line |
|---|---|---|
| `armTransformersStt` | `(): () => void` — idempotent; `subscribePcm` tap; returns disarm | [#L266](../ui/src/audio/transformersStt.ts#L266) |
| `disarmTransformersStt` | `(): void` — detaches PCM tap (worker stays resident) | [#L305](../ui/src/audio/transformersStt.ts#L305) |
| `onTransformersTranscript` | `(l: (text: string) => void) => () => void` | [#L350](../ui/src/audio/transformersStt.ts#L350) |
| `onTransformersTranscribing` | `(l: (active: boolean) => void) => () => void` | [#L358](../ui/src/audio/transformersStt.ts#L358) |

- **VAD-bounded**: `arm` subscribes the PCM tap; Silero VAD `speech_start`/`speech_end`
  ([voiceActivity.ts#L389 `subscribePcm`](../ui/src/audio/voiceActivity.ts#L389)) bound the utterance;
  the transcript fires on `speech_end` → worker → `onTransformersTranscript`.
- **The mic is already open app-wide**: `startVoiceActivity()` is called once in
  [App.tsx#L215](../ui/src/App.tsx#L215). `arm*` only taps that stream — **AD-922 opens NO new mic, calls NO `getUserMedia`.**
- `cognitive.primary_stt` is surfaced as `voiceHealth.primary_stt` (`'transformers' | 'whisper' | 'browser'`) via `GET /api/voice/health`; ProfileChatTab already fetches it ([#L237-L249](../ui/src/components/profile/ProfileChatTab.tsx#L237-L249)). v1 of the meeting mic does not need it.

### Browser-SR fallback (`ui/src/audio/speechInput.ts`)

`isSpeechRecognitionSupported(): boolean` ([#L35](../ui/src/audio/speechInput.ts#L35)),
`startListening(...)` ([#L101](../ui/src/audio/speechInput.ts#L101)), `stopListening()` ([#L239](../ui/src/audio/speechInput.ts#L239)).
The existing per-agent mic uses a whisper-primary → browser-SR **fallback ladder** (voiceHealth +
empty-counters, ~150 lines, [#L1176-L1268](../ui/src/components/profile/ProfileChatTab.tsx#L1176-L1268)).
**v1 of the meeting mic does NOT reproduce that ladder (DRY) — it uses the transformers path + a
support gate + honest-degrade.** Fallback-ladder parity is a deferred follow-up.

### The AD-917 group submit handler — reuse (`ProfileChatTab.tsx`)

`const sendText = useCallback(async (textArg: string) => { ... }, [...])` — [#L567](../ui/src/components/profile/ProfileChatTab.tsx#L567). Self-routes group vs 1:1; already calls `speakMeetingReplies`. **This is the submit AD-922 feeds.**

### Meeting + voice state already present (`ProfileChatTab.tsx`)

- `meetingActive` selector — [#L483-L484](../ui/src/components/profile/ProfileChatTab.tsx#L483) (`metadata.meeting_active`).
- `const { speakReplies: speakMeetingReplies } = useMeetingVoice({ meetingActive });` — [#L488](../ui/src/components/profile/ProfileChatTab.tsx#L488). `useMeetingVoice` **also returns `speakingAgentId`** ([useMeetingVoice.ts#L28-L31](../ui/src/audio/useMeetingVoice.ts#L28)) — `null` between utterances, the agent's id while it speaks. **AD-922 destructures `speakingAgentId` and uses it as the echo gate.**
- `<MeetingView threadId={activeThreadId} />` mounts at [#L812](../ui/src/components/profile/ProfileChatTab.tsx#L812) — the meeting mic mounts next to it.

### Echo gate (concrete) — why `speakingAgentId`, not `ttsActiveRef`

BF-300 gates the per-agent mic on `ttsActiveRef` ([#L136](../ui/src/components/profile/ProfileChatTab.tsx#L136), set via `onSpeechEvent` at [#L371-L378](../ui/src/components/profile/ProfileChatTab.tsx#L371)). **That ref is host-filtered** (`if (event.agent_id && event.agent_id !== agentId) return`), so it stays `false` when a **non-host** meeting agent speaks. AD-921 speaks every reply with its own `agent_id`, so the correct meeting-wide "an agent is speaking" signal is **`speakingAgentId != null`**. AD-922 gates the meeting mic on it (mirror BF-300, meeting-wide).

### Mic permission — reuse (`ui/src/audio/wakeWord.ts`)

`getMicPermissionState(): 'pending' | 'granted' | 'denied' | 'unavailable'` ([#L77](../ui/src/audio/wakeWord.ts#L77)),
`onMicPermissionState(fn) => () => void` ([#L62](../ui/src/audio/wakeWord.ts#L62)). `MicPermissionHint` is mounted in [App.tsx#L227](../ui/src/App.tsx#L227). **AD-922 reads this state to honest-degrade; it requests NO new permission.**

### Push-to-talk control placement

[GroupChatHeader.tsx](../ui/src/components/profile/GroupChatHeader.tsx) holds the meeting Start/End toggle as a **local inline SVG** (not a `Glyphs.tsx` export — avoids the `Glyphs.test.tsx` export-count bump). [MeetingView.tsx](../ui/src/components/profile/MeetingView.tsx) is the avatar gallery and has **no access to `sendText`**. The control needs `sendText` + STT + `meetingActive` + `speakingAgentId`, all of which live in **ProfileChatTab** — so the new button is mounted from ProfileChatTab. No mic glyph exists in `Glyphs.tsx`; use a **local inline mic SVG** (mirror the GroupChatHeader convention).

---

## Solution

Mirror the AD-921 shape (a pure DI hook + a thin presentational control + a small ProfileChatTab edit):

1. **`ui/src/audio/useMeetingMic.ts`** — pure-DI hook owning the capture lifecycle. Injects
   `armTransformersStt` / `disarmTransformersStt` / `onTransformersTranscript`, the mic-permission
   reader, and a `submit(text)` callback. Gates on `meetingActive && !speaking && supported &&
   permission !== 'denied'/'unavailable'`. Click-to-arm; the VAD `speech_end` produces the
   transcript; on the **first non-empty transcript** it calls `submit(text)`, disarms, and clears
   `capturing`; a second click cancels. The transcript listener is **one-shot, stored on a ref**,
   and torn down on every exit path (BF-319 zombie-listener discipline). `submit`, `meetingActive`,
   and `speaking` are read **live via refs** so the hook stays reference-stable (BF-292).

2. **`ui/src/components/profile/MeetingMicButton.tsx`** — thin presentational button (local inline
   mic SVG, amber `#f0b060` while capturing / dim `#666680` idle / muted when speaking or
   unavailable). `data-testid="meeting-mic"`. `aria-pressed={capturing}`. Calls `onToggle` on click.

3. **`ProfileChatTab.tsx`** edit (additive): destructure `speakingAgentId` from the existing
   `useMeetingVoice` call; mount `useMeetingMic({ meetingActive, speaking: speakingAgentId != null,
   submit: sendText })`; render `<MeetingMicButton ... />` next to the `MeetingView` mount, gated on
   `meetingActive`.

No backend change — `POST /api/threads/{id}/messages` already exists (AD-913/914) and `sendText`
already calls it.

---

### Section 1 — NEW `ui/src/audio/useMeetingMic.ts`

A pure-DI React hook. Inject the STT + permission functions (default to the real imports) so the
hook is unit-testable without audio. Contract:

```ts
export interface UseMeetingMicOptions {
  /** True when the active thread's metadata.meeting_active is set. */
  meetingActive: boolean;
  /** True while ANY meeting agent is mid-utterance (useMeetingVoice.speakingAgentId != null).
   *  Echo gate: the mic refuses to arm while agents speak (BF-300, meeting-wide). */
  speaking: boolean;
  /** Where a finished transcript goes. ProfileChatTab passes `sendText`, which self-routes to
   *  the AD-914 group fan-out when the thread has >=2 crew (AD-917). */
  submit: (text: string) => void | Promise<void>;
  /** Test seams — default to the real audio modules. */
  deps?: {
    arm?: () => () => void;                         // armTransformersStt
    disarm?: () => void;                            // disarmTransformersStt
    onTranscript?: (l: (t: string) => void) => () => void; // onTransformersTranscript
    isSupported?: () => boolean;                    // isSpeechRecognitionSupported (proxy for "voice possible")
    micState?: () => string;                        // getMicPermissionState
  };
}

export interface UseMeetingMicResult {
  /** True while a capture is armed and waiting for the VAD-bounded transcript. */
  capturing: boolean;
  /** True when voice input is possible at all (STT/SR available). When false the button hides. */
  supported: boolean;
  /** True when the mic is unusable right now (permission denied/unavailable) — drives the muted visual. */
  blocked: boolean;
  /** Click handler: arm if idle, cancel if capturing. No-ops (honest-degrade) when gated off. */
  toggleCapture: () => void;
}
```

Behaviour:

- `supported = (deps.isSupported ?? isSpeechRecognitionSupported)()` (read once per render; SR
  availability is a sufficient proxy for "the browser can do voice input at all"). When `false`,
  the consumer hides the button entirely — the Captain types, **no regression**.
- `blocked = micState === 'denied' || micState === 'unavailable'` (read via
  `deps.micState ?? getMicPermissionState`, kept live via `onMicPermissionState` subscription in a
  `useEffect` so a late grant/deny updates the visual).
- `toggleCapture()`:
  - If `capturing` → cancel: run the stored unsub, `disarm()`, set `capturing=false`. Return.
  - **Gate (honest-degrade, all no-op):** if `!meetingActiveRef.current || speakingRef.current ||
    !supported || blocked` → return without arming.
  - Else arm: subscribe a **one-shot** transcript listener stored on `transcriptUnsubRef`; on the
    first event, `try { unsub() } finally { transcriptUnsubRef.current = null; disarm(); setCapturing(false) }`,
    and if `text.trim()` is non-empty call `submitRef.current(text.trim())`. Then `arm()`; set
    `capturing=true`.
- Refs: `meetingActiveRef`, `speakingRef`, `submitRef` updated in `useEffect`s each render (BF-292 —
  read live at call time, not from closure). `transcriptUnsubRef` for one-shot teardown (BF-319).
- Cleanup `useEffect` on unmount: if armed, unsub + `disarm()`.
- All STT teardown calls are Tier-2 wrapped (`try { ... } catch { /* Tier-2 */ }`).

> **Why one-shot + teardown matters (BF-319):** the per-agent mic and the meeting mic both subscribe
> the **global** `onTransformersTranscript` set. A straggler transcript that fans to two live
> listeners would call `sendText` twice. One-shot unsub on the first event + teardown on
> cancel/unmount bounds this. (Full mic mutual-exclusion via the `speechRecognitionArbiter` lease is
> an explicit non-goal here — the existing whisper-PTT path doesn't use the arbiter either; deferred.)

### Section 2 — NEW `ui/src/components/profile/MeetingMicButton.tsx`

```tsx
interface MeetingMicButtonProps {
  capturing: boolean;
  blocked: boolean;     // permission denied/unavailable -> muted + disabled
  speaking: boolean;    // an agent is speaking -> muted (echo gate visual)
  onToggle: () => void;
}
```

- Local inline mic SVG only (HXI #3 — `strokeWidth: 1.5`, `strokeLinecap: round`, no emoji, no
  `Glyphs.tsx` export). Color: `#f0b060` (amber) while `capturing`; `#666680` (dim) idle; muted
  treatment when `blocked || speaking`.
- `type="button"`, `data-testid="meeting-mic"`, `aria-pressed={capturing}`,
  `aria-label` = `capturing ? 'Stop talking to the room' : 'Talk to the room'`; `title` reflects the
  same; when `blocked`, `title` = "Microphone unavailable". `disabled={blocked}`.
- `onClick={onToggle}`. Pure presentational — no STT imports.

### Section 3 — EDIT `ui/src/components/profile/ProfileChatTab.tsx` (additive only)

1. Imports: `import { useMeetingMic } from '../../audio/useMeetingMic';` and
   `import { MeetingMicButton } from './MeetingMicButton';`.
2. Change [#L488](../ui/src/components/profile/ProfileChatTab.tsx#L488) to also destructure the speaking seam:
   `const { speakReplies: speakMeetingReplies, speakingAgentId } = useMeetingVoice({ meetingActive });`
3. After `sendText` is defined (it must be in scope), mount the hook:
   `const meetingMic = useMeetingMic({ meetingActive, speaking: speakingAgentId != null, submit: sendText });`
4. Render the button next to the `MeetingView` mount ([#L812](../ui/src/components/profile/ProfileChatTab.tsx#L812)), gated on
   `meetingActive && meetingMic.supported`:
   ```tsx
   {activeThreadId && meetingActive && meetingMic.supported && (
     <MeetingMicButton
       capturing={meetingMic.capturing}
       blocked={meetingMic.blocked}
       speaking={speakingAgentId != null}
       onToggle={meetingMic.toggleCapture}
     />
   )}
   ```
   (Place it inside/adjacent to the meeting region so it reads as part of the meeting surface.)

No other ProfileChatTab logic changes. The per-agent mic button, conversation mode, and the 1:1
path stay byte-identical.

---

## Tests (Vitest only — no pytest)

Follow the established idioms: hook tests with `renderHook`/`act` + `vi.mock` of the audio modules +
**real store** (`useStore.setState`, BF-287); component tests with `render` + no-emoji guard; the
group-routing assertion via the **AD-917 `routeSend` mirror** (the full ProfileChatTab is too heavy
to render — same rationale as
[ProfileChatTab.groupsend.test.tsx](../ui/src/components/profile/__tests__/ProfileChatTab.groupsend.test.tsx)).
Mock STT/VAD/mic — **no real audio**.

### `ui/src/audio/__tests__/useMeetingMic.test.tsx` (≥ 9)

`vi.mock('../transformersStt', ...)`, `vi.mock('../speechInput', ...)`, `vi.mock('../wakeWord', ...)`;
inject a fake `submit`. Cases:

1. `test_transcript_in_meeting_calls_submit_with_text` — arm via `toggleCapture`, fire a mocked
   transcript, assert `submit` was called once with the trimmed text.
2. `test_arm_subscribes_and_disarms_after_transcript` — assert `armTransformersStt` called on
   toggle, `disarmTransformersStt` called after the transcript (capture is one-shot).
3. `test_not_armed_when_meeting_inactive` — `meetingActive=false` → `toggleCapture` no-ops (no
   `arm`, no `submit`).
4. `test_not_armed_while_agent_speaking` — `speaking=true` → no arm (echo gate).
5. `test_blocked_when_mic_denied` — `micState='denied'` → `blocked===true`, `toggleCapture` no-ops.
6. `test_supported_false_when_sr_unavailable` — `isSupported=()=>false` → `supported===false`.
7. `test_second_toggle_cancels_capture` — toggle (arm) → toggle (cancel) → `disarm` called, no
   `submit`, `capturing===false`.
8. `test_empty_transcript_does_not_submit` — fire `''` → `submit` not called, capture cleared.
9. `test_one_shot_listener_torn_down` — after the first transcript, a second mocked transcript does
   NOT call `submit` again (BF-319: listener unsubscribed).

Plus a `?raw` no-emoji guard for `useMeetingMic.ts`
(`expect(source).not.toMatch(/\p{Extended_Pictographic}/u)`).

### `ui/src/components/profile/__tests__/MeetingMicButton.test.tsx` (≥ 4)

`render` the button. Cases: renders `data-testid="meeting-mic"`; `onToggle` fires on click;
`aria-pressed` reflects `capturing`; `disabled` + muted when `blocked`; muted treatment when
`speaking`; `container.innerHTML` has no emoji (`/\p{Extended_Pictographic}/u`).

### `ui/src/components/profile/__tests__/MeetingMic.routing.test.ts` (≥ 1)

Reuse the AD-917 `routeSend` mirror: feed the captured transcript as the message into the mirror with
a **≥2-crew** thread and assert it POSTs to **`/api/threads/{id}/messages`** and **not**
`/api/agent/{id}/chat` (proves a meeting transcript routes to the group). `vi.stubGlobal('fetch', ...)`.

**Floor: +14 across the three files.**

---

## What this does NOT change — Do NOT build

- **NO new dispatch branch / new POST path.** `sendText` already self-routes (AD-917). The meeting
  mic only calls `sendText(transcript)`.
- **NO change to agent voice-out (AD-921).** `useMeetingVoice` / `meetingVoice.ts` are read-only
  here (consume `speakingAgentId`); do not edit them.
- **NO new STT engine, NO new VAD, NO new `getUserMedia`.** Reuse `transformersStt` + the app-wide
  `startVoiceActivity` mic. Do not touch `voiceActivity.ts`, `transformersStt.ts`, `whisperStt.ts`.
- **NO change to the global conversation/wake-word voice wiring.** Do not touch
  `conversationController.ts` or the `IntentSurface.tsx` STT path (those keep their existing 1:1 /
  standard-chat behavior — no AD-705a regression).
- **NO change to the per-agent ProfileChatTab mic button** (the existing PTT/conversation control,
  ~L1130-L1268) beyond leaving it in place.
- **NO browser-SR fallback ladder** in the meeting mic v1 (DRY — deferred).
- **NO mic arbiter / mutual-exclusion lease** (deferred; one-shot teardown bounds cross-fire).
- **NO presence/raise-hand/transcript-writeback** — that is **AD-923**. No who's-speaking gallery
  highlight, no join/leave, no meeting-end summary.
- **NO backend change, NO pytest, NO new config field, NO `Glyphs.tsx` change** (local inline SVG).
- **NO full-duplex barge-in** (Captain interrupting agents' TTS) — the mic is echo-gated OFF while
  agents speak; barge-in is an AD-923 concern.

---

## Tracking

- `docs/development/roadmap.md` — flip the AD-922 row (line 377) to "SHIPPED <date> gate-verified".
- `PROGRESS.md` — prepend an AD-922 block.
- `DECISIONS.md` — add an AD-922 entry (above AD-921) recording: meeting mic feeds `sendText`
  (no new branch), echo-gate via `speakingAgentId`, one-shot listener (BF-319), browser-SR ladder
  deferred.

---

## Acceptance criteria

1. New files `ui/src/audio/useMeetingMic.ts` and `ui/src/components/profile/MeetingMicButton.tsx`;
   additive edits to `ProfileChatTab.tsx` only.
2. In a meeting (`meetingActive`), the meeting mic captures one VAD-bounded utterance and calls
   `sendText(transcript)`; with ≥2 crew the resulting POST hits `/api/threads/{id}/messages`
   (`role:"captain"`), **not** `/api/agent/{id}/chat`.
3. The mic does not arm while an agent is speaking (`speakingAgentId != null`) and honest-degrades
   (no-op, Captain types) when STT/mic is unavailable or permission is denied.
4. Outside a meeting, the meeting mic is not rendered; the existing per-agent mic and 1:1 path are
   byte-identical (no AD-705a regression).
5. **+14 Vitest** across the three named files; no-emoji guard in each; **no pytest**.
6. Full UI suite green (`cd ui && npx vitest run`) at **≥ 1191 passed / 1 skipped**;
   `npm run build` (`tsc -b` + `vite`) green.
7. Staged with explicit paths (NOT `git add -A`); deletion audit clean.
8. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Verified Against Codebase (2026-06-07, HEAD `fe6fbdfb`)

```
git log --oneline -1
  fe6fbdfb AD-921: sequenced meeting voice

grep -n "export function armTransformersStt|disarmTransformersStt|onTransformersTranscript" ui/src/audio/transformersStt.ts
  266: export function armTransformersStt(): () => void {
  305: export function disarmTransformersStt(): void {
  350: export function onTransformersTranscript(listener: TranscriptListener): () => void {

grep -n "startVoiceActivity" ui/src/App.tsx
  215:     void startVoiceActivity();

grep -n "export function subscribePcm" ui/src/audio/voiceActivity.ts
  389: export function subscribePcm(handler: PcmTapHandler): () => void {

grep -n "const sendText = useCallback" ui/src/components/profile/ProfileChatTab.tsx
  567:   const sendText = useCallback(async (textArg: string) => {

grep -n "crewParticipantCount >= 2|/api/threads/.*/messages|void sendText\(text\)" ui/src/components/profile/ProfileChatTab.tsx
  609:       if (_thread && crewParticipantCount >= 2) {
  613:           const res = await fetch(`/api/threads/${groupThreadId}/messages`, {
  1256:                      setTimeout(() => { void sendText(text); }, 100);

grep -n "useMeetingVoice\(\{ meetingActive \}\)|speakingAgentId|meetingActive = useStore" ui/src/components/profile/ProfileChatTab.tsx
  483:   const meetingActive = useStore((s) =>
  488:   const { speakReplies: speakMeetingReplies } = useMeetingVoice({ meetingActive });
  812:       {activeThreadId && meetingActive && <MeetingView threadId={activeThreadId} />}

grep -n "speakingAgentId" ui/src/audio/useMeetingVoice.ts
  28:   /** The agent currently speaking (``null`` between utterances / when idle).
  33:   const [speakingAgentId, setSpeakingAgentId] = useState<string | null>(null);

grep -n "getMicPermissionState|onMicPermissionState|MicPermissionState =" ui/src/audio/wakeWord.ts
  51: export type MicPermissionState =
  62: export function onMicPermissionState(
  77: export function getMicPermissionState(): MicPermissionState {

grep -n "isSpeechRecognitionSupported|export function startListening|stopListening" ui/src/audio/speechInput.ts
  35: export function isSpeechRecognitionSupported(): boolean {
  101: export function startListening(
  239: export function stopListening(): void {

grep -n "ttsActiveRef|event.agent_id !== agentId" ui/src/components/profile/ProfileChatTab.tsx
  136:   const ttsActiveRef = useRef(false);
  371:     const unsub = onSpeechEvent((event) => {
  372:       if (event.agent_id && event.agent_id !== agentId) return;

grep -rn "useMeetingMic|MeetingMicButton" ui/src   # => no matches (greenfield)
```

Every concrete claim above maps to one of these hits. The two new entities (`useMeetingMic`,
`MeetingMicButton`) are introduced by this prompt and are correctly absent at HEAD.
