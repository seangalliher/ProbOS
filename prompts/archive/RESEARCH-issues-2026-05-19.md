# Prior-art research — 2026-05-19 live-use triage

Three issues triaged from Captain's report after using Waves 175-179 in
production. Per ProbOS license policy: MIT/Apache absorbable directly;
AGPL pattern-only; closed/commercial systems architecture-only.

---

## Issue A — BF-317 — Share-screen button under-discoverable in DM thread

**Captain:** *"I should be able to start a screen sharing session from the
agent 1:1 Chat screen."*

**Live-code finding.** The button **is** in `WardRoomThreadDetail.tsx` —
function `onShareScreen` at line 188, button rendered at line ~397 with
`data-testid="wardroom-dm-share-screen-button"`. It is gated on
`isDm && targetAgentId` (DM threads only). It is a 14×14 stroke SVG of a
monitor, no text label, `aria-label="share screen to agent"`,
`title="Share screen to agent (one-shot)"` (tooltip-only).

The bug is **discoverability**, not absence. Captain didn't find it
because the icon is the same color and size as the paperclip beside it,
no label, and looks like another attach affordance.

### Prior-art absorption sources

| Source | License | Pattern | Absorb? |
|---|---|---|---|
| Slack web — composer toolbar | Closed | Toolbar buttons are 20×20 with hover label, screen-share + camera + recording are visually distinct (filled vs outline). Hovering shows label text. Discord, Teams use a similar pattern. | Architecture only — make the share button visually distinct from attach (e.g. desk-monitor vs paperclip) and surface a permanent text label on first session OR persistent tooltip. |
| GitHub Copilot Chat composer | Closed | Single "tool palette" expands to show all attach/screen/voice options when clicked. Reduces toolbar crowding. | Architecture only — consider a `[+]` palette for sub-affordances if more land in WardRoomThreadDetail. |
| Discord — DM screenshare button (v1 web) | Closed | Distinct icon (monitor with arrow), hover-label, position separated from message attach. | Architecture only. |

### Recommendation

This is a UX polish bug. v1 = label + size + position. Forward marker
for full palette pattern if more affordances queue up.

---

## Issue B — AD-746 — Camera + screen source policy

**Captain:** *"When I'm sharing my camera and the screen at the same time
they are fighting for attention. I should be able to set which one is the
priority or we need a way of merging them together in one context."*

**Symptom hypothesis.** Both AD-733-2 (screen) and AD-733a (camera)
emit `vision_observation` with `params.source ∈ {camera, screen}`. Both
land in the same `VisionConsumer`. Per-frame describes alternate; WM
interleaves; episodic anchors fire from both; the AD-733c-6 vision-call
budget burns twice as fast.

### Design space (Captain explicitly open to multiple)

1. **Priority knob** — per-source priority in `PerceptionConfig`. The
   low-priority source describes only on novelty spike OR only when
   bound to a specific agent.
2. **Source fusion** — both frames composed into ONE multimodal LLM
   call ("here's the user's face; here's their screen — describe the
   joint context"). Single describe, single WM entry, coherent context.
3. **Per-agent source binding** — extend AD-733c-5 / AD-742c per-agent
   registry. Counselor binds to camera, Operations binds to screen.
   Each agent's WM is mono-source per binding. Captain "talks to the
   agent that sees what's relevant."

### Prior-art absorption sources

| Source | License | Pattern | Absorb? |
|---|---|---|---|
| Anthropic Claude — computer-use Beta | Closed (MIT quickstart) | One viewport per turn (full desktop screenshot). Camera not supported. No multi-source fusion. | Architecture-only — Claude's single-source bias supports the **per-agent binding** option B. |
| OpenAI Operator (ChatGPT desktop agent) | Closed | Screen-only; camera is separate "advanced voice with vision" mode. The two modes are NEVER concurrent in one turn. Implicit per-mode binding. | Architecture-only — same lesson: **the industry default is one source per turn**, not fusion. |
| GitHub Copilot Vision (preview) | Closed | One image per attach; multi-image is "carousel" not fusion. | Architecture-only. |
| LiveKit Agents — `MultiModalContext` | Apache 2.0 | Multi-track context: camera + screen + audio carried as parallel input streams; the Agent SDK exposes `participant.tracks` as a list and lets the developer choose to send all or filter. Per-track confidence/priority is the developer's choice. | **Pattern absorb** — model the per-source policy as data on `VisionObservation` (`source`, `priority`, `binding`) and let consumers filter. |
| Pipecat — `VisionAggregator` | BSD-2-Clause | Aggregates multiple vision frames within a debounce window into ONE multimodal message to the LLM. **This is exactly fusion option B.** | **Pattern absorb directly** — the aggregator-with-debounce pattern is the cleanest fusion implementation. |
| `livekit/agents` voice + screen reference example | Apache 2.0 | Sample app pins one agent to camera, another to screen — proves option C scales. | **Pattern absorb** — per-agent source binding via the existing AD-742c registry. |

### Recommendation

**v1 = Option B (fusion) + Option C (per-agent binding) as a layered
solution. Defer Option A (raw priority knob) as forward marker.**

Rationale:
- Captain explicitly open to "merge into one context" — Pipecat's
  `VisionAggregator` is the canonical pattern.
- Per-agent binding already exists structurally (AD-742c
  `bound_agent_ids`, AD-733c-5 `PerceptionEngagementRegistry`) — extend
  the binding from `device_id` to a `source` list.
- Fusion + binding eliminates the budget-burn symptom (one describe
  per debounce window instead of two) AND eliminates the WM-incoherence
  symptom (Counselor's WM has only camera frames, Operations has only
  screen frames — each is coherent).
- Pure priority knob without fusion would still leave the budget-burn
  symptom; with fusion, priority becomes redundant.

**Forward markers:**
- AD-746-1 — Raw priority knob (preempt fusion when one source dominates).
- AD-746-2 — Cross-modal salience scorer (which source carries more novelty).
- AD-746-3 — Audio as a third fused source (mic context join).

---

## Issue C — BF-318 (bug) + AD-747 (feature) — Voice conversation UX

**Captain:** *"I have to press the microphone button every time I want to
use voice to speak to the agent, it also doesn't seem to work
consistently. I want to be able to have a natural conversation where the
mic stays on and we can just have a conversation."*

### Bug — BF-318 — mic singleton conflict

**Live-code finding.** Three mic-acquisition paths fight over the same
device:

| Path | Module | Acquisition |
|---|---|---|
| Press-to-talk | `IntentSurface.tsx:2281` → `speechInput.ts:startListening()` | Browser `SpeechRecognition` API (singleton `activeRecognition`) |
| Wake-word continuous (transcript-fallback) | `wakeWord.ts:_startContinuousRecognition` → `speechInput.ts:startListening()` | Same browser `SpeechRecognition` singleton |
| VAD | `voiceActivity.ts:startVoiceActivity` | Dedicated `getUserMedia({audio:true})` MediaStream |

**Root cause.** `speechInput.ts` has a module-level `activeRecognition`.
Calling `startListening()` while another session is active calls
`.abort()` on the previous one. So when Captain clicks the mic button
while wake-word is running, wake-word's session is aborted; on stop,
wake-word tries to restart via the `onend` handler but races with
`IntentSurface`'s teardown — sometimes the restart wins, sometimes the
mic icon shows but no transcripts arrive (because `activeRecognition`
got cleared between callback creation and start).

**Fix shape.** Token-arbitrated SR ownership: a single
`speechRecognitionArbiter` module owns the singleton, hands out
"recognition leases" with priorities (press-to-talk > wake-word), and
on release re-arms whoever's queued. Press-to-talk button preempts
wake-word; on stop, wake-word resumes. Tests assert no race.

### Feature — AD-747 — always-on natural conversation mode

The pieces exist:
- VAD detects speech bounds (AD-733c-7)
- Whisper STT transcribes between VAD speech_start / speech_end (AD-705a)
- Per-agent engagement registry tracks the active agent (AD-733c-5)
- Wake-word path provides "no DM open" fallback (AD-733c-3)

What's missing: a controller that **owns the conversation lifecycle** —
when a DM thread is active, the mic stays hot, VAD gates STT, STT
transcripts auto-submit to that DM's agent, and barge-in interrupts
agent TTS playback.

### Prior-art absorption sources

| Source | License | Pattern | Absorb? |
|---|---|---|---|
| LiveKit Agents (`livekit/agents`) | Apache 2.0 | `VoicePipelineAgent` class owns the full duplex: VAD-gated STT → LLM → TTS → barge-in detection. Turn-taking via VAD + silence timeout (~700 ms after speech_end). Mic stays hot for the whole conversation; explicit "end call" or N-second silence ends it. | **Direct pattern absorb** — the `ConversationController` shape is the canonical reference. Their barge-in (user speaks during agent TTS → agent TTS interrupts immediately) is the exact UX Captain wants. |
| Pipecat (`pipecat-ai/pipecat`) | BSD-2-Clause | Same lifecycle, slightly different abstraction (frame-based pipeline). VAD → STT → LLM → TTS is a `Pipeline` of `FrameProcessor`s. Barge-in via VAD interrupt frame propagating upstream to cancel TTS. | **Direct pattern absorb** — secondary reference, similar shape. |
| ChatGPT Advanced Voice Mode | Closed | Always-on while in voice session. VAD with ~600 ms silence end-of-turn detection. Barge-in supported (interrupts assistant TTS instantly). "Tap to end call" UI affordance. No wake-word required mid-session. | **Architecture-only** — the UX choices (end-of-call button, barge-in, no wake-word mid-conversation) are validated by hundreds of millions of users. Adopt directly. |
| Pi.ai voice mode | Closed | Similar UX. Slight difference: Pi has a more aggressive VAD threshold to avoid mid-utterance interruption. Long pauses (>2 s) considered turn-end. | Architecture-only — defaults for VAD parameters. |
| Gemini Live | Closed | Bidirectional streaming over WebRTC. Server-side VAD. Mid-utterance interruption supported. | Architecture-only — confirms barge-in as table-stakes. |
| Vapi | Closed | Production telephony agent platform. Documented architecture: VAD → STT → LLM → TTS with explicit "interruption sensitivity" knob (low/medium/high) operator-configurable. End-of-call detection via silence timer OR explicit goodbye phrase classifier. | Architecture-only — the "interruption sensitivity" knob is a useful pattern. |
| Hume EVI | Closed | Adds prosody features — interrupts only on confident speech (not background noise). | Architecture-only — forward-marker for AD-747-N (prosody-gated barge-in). |

### Recommendation

**v1 (AD-747) — ConversationController owning duplex when a DM is open.**
- Subscribe to AD-733c-5 active-agent state. When `activeAgent !== null`
  AND `vad_engagement_enabled` AND `offline_stt_enabled`:
  - Mic-arbiter acquires recognition lease for the conversation.
  - VAD gates STT (already wired via `whisperStt.ts`).
  - On STT transcript, auto-submit to active agent's DM thread via
    existing `agent_chat` keyboard path.
  - On agent TTS playback start, monitor VAD for barge-in; if speech
    detected during TTS, interrupt TTS via existing `voice.ts`
    `stopSpeaking()` and rearm STT.
  - End-of-conversation via N-second silence (default 30 s) OR
    explicit "end conversation" button.
- Press-to-talk button becomes optional (still available for users who
  prefer push, but the default UX is the new always-on mode).

**Forward markers:**
- AD-747-1 — Prosody-gated barge-in (Hume EVI pattern; reduces false
  interrupts from background noise).
- AD-747-2 — Cross-agent conversation handoff (Captain pivots from DM
  with Counselor to DM with Operations mid-conversation).
- AD-747-3 — "Interruption sensitivity" operator knob (Vapi pattern).
- AD-747-4 — Telephony-style "end of call" classifier (detect goodbye
  phrases as natural end-of-session).
- AD-747-5 — Server-side streaming STT (forward marker per AD-705a-4
  streaming decode).

### v1 vs forward-marker matrix

| Capability | v1 | Forward marker |
|---|---|---|
| Mic-arbiter for SR singleton | BF-318 | — |
| VAD-gated STT in DM | AD-747 | — |
| Auto-submit transcript to active agent | AD-747 | — |
| Barge-in (VAD interrupts TTS) | AD-747 | AD-747-1 (prosody-gated) |
| End-of-conversation timer | AD-747 (default 30 s) | AD-747-4 (goodbye classifier) |
| Press-to-talk button | Preserved (becomes optional) | — |
| Interruption sensitivity knob | — | AD-747-3 |
| Cross-agent handoff | — | AD-747-2 |

---

## License posture summary

Zero new pip / npm deps required for any of the three issues. All
absorption is pattern-level: LiveKit Agents (Apache 2.0) and Pipecat
(BSD-2-Clause) are the only repos we'd directly study for code shape;
both are permissive and citation-only suffices. Closed-source systems
(ChatGPT/Claude/Operator/Pi/Gemini/Vapi/Hume) are architecture-only —
their UX choices validate the design space, but no code crosses the
boundary.
