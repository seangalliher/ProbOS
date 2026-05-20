# AD-747 — ConversationController (always-on natural conversation mode)

**Status:** drafted (Wave 180, builds **fourth and last**; **strict
build order — BF-318 MUST ship first**).
**Issue:** [#684](https://github.com/seangalliher/ProbOS/issues/684).
**Prior-art:** `prompts/RESEARCH-issues-2026-05-19.md` (Issue C, "Feature
— AD-747"; LiveKit Agents `VoicePipelineAgent` Apache 2.0 absorbed at
the pattern level; Pipecat BSD-2-Clause as secondary reference;
ChatGPT advanced voice mode validates 30 s silence-timeout default).
**Estimated work:** 1-1.5 days.
**Dependencies:**
- **BF-318** (mic arbiter) — HARD prerequisite. AD-747 acquires
  `PRIORITY_CONVERSATION = 75` leases through the arbiter.
- AD-705a (offline STT via whisper.cpp WASM, shipped Wave 179).
- AD-733c-7 / AD-733c-7-5 (VAD: server endpoint + browser SPEECH
  badge, shipped Waves 176 + 177).
- AD-733c-5 (per-agent perception engagement registry; provides
  active-agent state, shipped Wave 176).
- AD-744 (the share-screen path; not a strict dep but the active-DM
  context AD-747 listens to is the same one AD-744 reads).

**License posture:** zero new pip / npm deps; pattern absorbed under
Apache 2.0 (LiveKit) + BSD-2-Clause (Pipecat). **0-line diff on all 5
license files.**

---

## Problem

Captain reported: *"I have to press the microphone button every time I
want to use voice to speak to the agent, it also doesn't seem to work
consistently. I want to be able to have a natural conversation where
the mic stays on and we can just have a conversation."*

The substrate already exists:
- VAD detects speech bounds (AD-733c-7, AD-733c-7-5).
- Whisper STT transcribes between VAD `speech_start` / `speech_end`
  (AD-705a; `ui/src/audio/whisperStt.ts:154` `armWhisperStt`).
- Active-agent state via AD-733c-5 (`PerceptionEngagementRegistry`)
  plus the DM context in `WardRoomThreadDetail.tsx:71` `targetAgentId`.
- BF-318 (this wave) gives clean mic arbitration with a
  `PRIORITY_CONVERSATION = 75` lease.

What's missing: a controller that **owns the conversation lifecycle**.
When the Captain has a DM thread open with an agent:
- The mic stays hot (no press-to-talk required).
- VAD gates STT (already wired).
- STT transcripts auto-submit to the open DM's agent via the existing
  `agent_chat` keyboard path.
- Barge-in: if the Captain speaks while the agent is mid-TTS, the
  agent's TTS interrupts immediately and STT re-arms.
- 30 s of silence releases the conversation (matches ChatGPT advanced
  voice mode default) — wake-word resumes.
- Press-to-talk button is preserved (still available for users who
  prefer push) but visually demoted when conversation_mode_enabled.

## Scope (v1)

### Layer 1 — New module `ui/src/audio/conversationController.ts`

The controller owns the duplex. Public surface:

- `armConversationMode(opts: { agentId: string; onStateChange?:
  (state: ConversationState) => void }): () => void` — arms the
  conversation; returns disarm callable. Idempotent (re-arming with the
  same agentId is a no-op).
- `disarmConversationMode(): void` — clean teardown (release lease,
  cancel silence timer, unsubscribe).
- `getConversationState(): ConversationState` —
  `'inactive' | 'listening' | 'transcribing' | 'submitted' |
  'agent_speaking' | 'silence_pending'`.
- `onConversationState(listener: (state: ConversationState) => void):
  () => void` — subscribe.

### State machine

```
inactive
  → (arm called + arbiter grants PRIORITY_CONVERSATION lease)
listening               ← VAD armed, whisper armed
  → (VAD speech_start)
listening (speaking)    ← VAD says user is speaking
  → (VAD speech_end + whisper transcript arrives)
transcribing            ← brief: while whisper finalizes
  → (transcript fetch posts to agent_chat)
submitted               ← waiting for agent reply
  → (agent reply arrives + TTS begins)
agent_speaking          ← monitor VAD for barge-in
  → (VAD speech_start during TTS)
[ barge-in: voice.ts:stopSpeaking() → listening ]
  → (agent_speaking → TTS finishes naturally)
silence_pending         ← idle timer running (30 s default)
  → (silence timer expires)
inactive                ← release lease, wake-word resumes
```

### Wiring

- **Active-agent gate**: subscribe to AD-733c-5 store (or DM-thread
  active state); arm when `activeAgentId !== null` AND
  `conversation_mode_enabled` AND
  `vad_engagement_enabled` AND `offline_stt_enabled`. Disarm on
  active-agent change OR thread close.
- **Mic arbitration** (BF-318): on arm, call
  `arbiter.acquire({ holder: 'conversation', priority:
  PRIORITY_CONVERSATION, onPreempted: () => disarm() })`. When
  press-to-talk preempts, the controller disarms cleanly; on release
  (Captain finishes press-to-talk), the controller re-acquires.
- **STT transcript subscription**: `whisperStt.onTranscript(...)` and
  on transcript fire `POST /api/agent/${activeAgentId}/chat` with
  the existing message+history payload. Insert the transcript into
  the chat history client-side (mirrors the IntentSurface keyboard
  path). Render a transcript-preview pill (HXI #5) so the Captain
  sees what was heard before submission, with a 750 ms "edit
  window" — if no edit, auto-submit.
- **Barge-in**: register a VAD speech_start listener that, while
  `state === 'agent_speaking'`, calls `voice.stopSpeaking()` and
  transitions back to `listening`. AD-733c-7-5 VAD already fires
  the event; the controller adds the consumer.
- **Silence timer**: when `state === 'submitted'` AND the agent's
  reply has fully played out (TTS `onended` callback), start a 30 s
  timer (`conversation_silence_timeout_ms`). Any state change before
  expiry cancels the timer. On expiry: disarm; show a "Conversation
  ended" inline message; wake-word's `arbiter.onReleased` fires and
  the wake-word loop resumes.
- **Press-to-talk preservation**: the mic button stays in the
  composer. When `conversation_mode_enabled=True`, the button is
  visually demoted (smaller, dim until hover) per HXI #5 progressive
  disclosure. Click still works — the arbiter grants
  `PRIORITY_PRESS_TO_TALK = 100` which preempts the conversation
  lease; the controller's `onPreempted` disarms; on release,
  re-acquires.

### Config

Three new fields on `CognitiveConfig` (sibling slot to the existing
`offline_stt_enabled` AD-705a field):
- `conversation_mode_enabled: bool = False` (default-OFF transitional
  gate per Wave 10 convention #14; hot-reload).
- `conversation_silence_timeout_ms: int = 30000` (ge=1000 le=300000;
  hot-reload; matches ChatGPT advanced voice mode default per
  RESEARCH).
- `conversation_barge_in_enabled: bool = True` (hot-reload; opt-out
  for users with chatty environments — AD-747-1 prosody-gated
  variant is the forward marker for the smarter fix).

### HXI surface

- New badge in `CameraLiveIndicator.tsx` (sibling to SPEECH badge):
  `CONV` text, amber `#f0b060` when armed, dim `#666680` when
  `conversation_mode_enabled=False`. Pulse during
  `agent_speaking` state (HXI #4 — motion communicates state). No
  emoji.
- `IntentSurface.tsx` press-to-talk button visual demotion when
  `conversation_mode_enabled=True`: smaller (16×16 vs 20×20), dim
  until hover, label hidden. The button still functions identically
  via the arbiter preempt path.
- Transcript-preview pill: floats above the composer when
  `state === 'transcribing' | 'submitted'`; shows the whisper
  transcript inline with a 750 ms edit window; "Editing" disables
  the auto-submit.

## Non-scope (v1)

- NO prosody-gated barge-in (forward marker **AD-747-1**, Hume EVI
  pattern). v1 barge-in fires on ANY VAD speech_start during TTS;
  noisy environments can opt out via
  `conversation_barge_in_enabled=False`.
- NO cross-agent conversation handoff mid-conversation (forward
  marker **AD-747-2**). v1 disarms on active-agent change.
- NO Vapi-style "interruption sensitivity" knob (forward marker
  **AD-747-3**).
- NO goodbye-phrase classifier (forward marker **AD-747-4**).
- NO server-side streaming STT (forward marker **AD-747-5**; pairs
  with AD-705a-4).
- NO multi-Captain voice profile binding (forward marker
  **AD-747-6**).
- NO audio fused into AD-746 vision context (forward marker
  **AD-747-7** / AD-746-3).
- NO change to BF-318 arbiter contract — AD-747 strictly **consumes**
  the API; the arbiter is the single source of mic ownership.
- NO change to AD-705a STT transcript shape.
- NO change to backend STT or backend `agent_chat` — AD-747 routes
  through the existing endpoints verbatim.

## File targets

| File | Change |
|---|---|
| `ui/src/audio/conversationController.ts` | **NEW.** ~250 lines: state machine, arbiter lease wiring, VAD + STT subscriptions, silence timer, barge-in. |
| `ui/src/audio/speechRecognitionArbiter.ts` | Consume the existing public surface (no change — BF-318 ships `PRIORITY_CONVERSATION`). |
| `ui/src/components/CameraLiveIndicator.tsx` | New CONV badge between SPEECH and the existing mode badge. ~20 lines. |
| `ui/src/components/IntentSurface.tsx` | Press-to-talk button visual demotion (opacity + size) when conversation_mode_enabled. ~10 lines. |
| `ui/src/components/wardroom/WardRoomThreadDetail.tsx` | Transcript-preview pill rendered above the composer when controller state is `transcribing` or `submitted`. ~30 lines. |
| `ui/src/store/useConversationStore.ts` | **NEW.** Zustand slice (controller state + agent_id mirror). |
| `src/probos/config.py` | `CognitiveConfig`: three new fields. |
| `src/probos/settings/section_registry.py` | Three new `FieldDescriptor`s in the Voice section (AD-741). |

**Zero backend logic changes.** Tests in `tests/` and `ui/src/__tests__/`
per standard layout.

## Test targets

**+6 pytest** in `tests/test_ad747_conversation_config.py`:
1. Config defaults (`enabled=False`, `silence=30000`, `barge_in=True`).
2. Field validators (silence ge=1000 le=300000).
3. AD-741 settings registry includes the three new fields.
4. Hot-reload semantics: changing `conversation_silence_timeout_ms`
   takes effect without restart.
5. AD-731 invariant n/a, but a source-scan asserts the controller
   module path is not present in the backend (frontend-only feature).
6. Source-scan: `conversation_mode_enabled` defaults to False across
   YAML config, Pydantic model, and FieldDescriptor.

**+14 vitest** split across:

`ui/src/audio/__tests__/conversationController.test.ts` (+10):
1. arm grants arbiter lease at PRIORITY_CONVERSATION.
2. arm without active-agent is a no-op.
3. disarm releases lease + cancels silence timer.
4. VAD speech_end + whisper transcript triggers POST to
   `/api/agent/${activeAgentId}/chat`.
5. agent reply transitions controller to agent_speaking.
6. barge-in: VAD speech_start during agent_speaking calls
   `voice.stopSpeaking()` and transitions to listening.
7. barge-in OFF: same VAD event does NOT call stopSpeaking when
   `conversation_barge_in_enabled=False`.
8. silence timer: TTS_onended starts the 30 s timer; expiry disarms.
9. press-to-talk preempt: arbiter onPreempted disarms cleanly.
10. transcript-preview pill: 750 ms edit window before auto-submit;
    editing the pill cancels auto-submit.

`ui/src/components/__tests__/CameraLiveIndicator.convBadge.test.tsx` (+2):
1. CONV badge renders amber when armed.
2. CONV badge pulses when state is agent_speaking.

`ui/src/components/wardroom/__tests__/WardRoomThreadDetail.conversation.test.tsx` (+2):
1. Transcript-preview pill renders above the composer in
   `transcribing` state.
2. Edit interaction cancels auto-submit.

Total: **+6 pytest, +14 vitest.**

## Acceptance criteria

1. `pytest tests/test_ad747_*.py -v -n 0` — 6 new tests pass.
2. Full gate `pytest tests/ -q -n 4 --dist=loadfile` — green.
3. `cd ui; npx vitest run` — full gate green; +14 new tests pass.
4. `cd ui; npm run build` — exit 0.
5. **BF-318 lease invariant preserved** — controller acquires through
   `arbiter.acquire`, never touches `activeRecognition` directly.
6. **AD-733c-7 privacy invariant preserved** — audio bytes never leave
   the browser. Source-scan asserts the controller never serializes
   PCM into a fetch body. (RESEARCH C — same invariant as AD-705a.)
7. **Captain smoke** — with `conversation_mode_enabled=True`, open a
   DM with Counselor. Speak; transcript appears in the pill;
   auto-submits after 750 ms; Counselor's reply plays via TTS; speak
   over the reply mid-sentence — TTS stops mid-word, STT re-arms;
   wait 30 s of silence — controller disarms, wake-word resumes.
8. **Press-to-talk preserved** — clicking the mic button while in
   conversation mode preempts cleanly; on release the conversation
   resumes (or 30 s timer fires from the new idle state).
9. **Wake-word resume invariant** — after 30 s silence disarm, the
   wake-word continuous-SR comes back online without manual
   intervention.
10. Verify all changes comply with the Engineering Principles in
    `.github/copilot-instructions.md`.

## Forward markers

- **AD-747-1** — Prosody-gated barge-in (Hume EVI pattern; suppress
  false interrupts from background noise).
- **AD-747-2** — Cross-agent conversation handoff mid-conversation.
- **AD-747-3** — Vapi-style "interruption sensitivity" knob.
- **AD-747-4** — Goodbye-phrase classifier (telephony pattern;
  natural end-of-conversation detection).
- **AD-747-5** — Server-side streaming STT (pairs with AD-705a-4).
- **AD-747-6** — Multi-Captain voice profile binding.
- **AD-747-7** — Audio fused into AD-746 vision context (third
  modality; pairs with AD-746-3).

## Verified Against Codebase (2026-05-19)

```
grep -n "armWhisperStt\|disarmWhisperStt\|onTranscript" ui/src/audio/whisperStt.ts
  154: export function armWhisperStt(): () => void {
  168: export function disarmWhisperStt(): void {
  184: export function onTranscript(listener: TranscriptListener): () => void {

grep -n "startVoiceActivity\|stopVoiceActivity" ui/src/audio/voiceActivity.ts
  195: export async function startVoiceActivity(opts: VadOptions = {}): Promise<boolean> {
  245: export function stopVoiceActivity(): void {

ls ui/src/audio/voice.ts
  (file present; `stopSpeaking` exported per HEAD inspection)

grep -n "targetAgentId\|isDm" ui/src/components/wardroom/WardRoomThreadDetail.tsx
  69:   const isDm = view === 'dm-detail';
  71:   const targetAgentId = resolveDmTargetAgentId(view, activeChannel, dmChannels);

grep -n "class PerceptionEngagementRegistry" src/probos/perception/engagement_registry.py
  25: class PerceptionEngagementRegistry:
```

All anchors confirmed at HEAD (`4beaba7e`). BF-318's arbiter is the
new dependency this prompt introduces; AD-747 is unblockable until
BF-318 lands.
