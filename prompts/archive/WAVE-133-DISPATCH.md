# WAVE 133 DISPATCH — Chat-experience pair (AD-718 + AD-721)

**Wave:** 133
**Mode:** main
**Depends on:** 132
**Builder required:** yes
**Issues to close:** #512 (AD-718 voice in profile chat), #515 (AD-721 3D crew avatars)
**Date:** 2026-05-08

## Captain's framing

Two complementary chat-experience enhancements. Voice-in-profile-chat completes the symmetry the Captain established with the Ship's Computer chat (already has voice). 3D crew avatars give every agent a visible, expressive presence on their profile card — Counselor (Echo) is the first design partner and is iterating on her own appearance proposals.

These two ADs ship in **one wave** because the synergy is real: when AD-721 lands, the avatar's mouth/expression should react to AD-718's TTS playback. The wirer hooks must be designed together to avoid retrofit.

## Architect must do this scoping research as part of drafting

### Internal surface to plug into (read all before drafting)

**For AD-718 (voice in profile chat):**
- `ui/src/audio/voice.ts` (130+ lines) — current voice substrate. Browser SpeechSynthesis API, zero deps. `speakResponse()` is the canonical entry. Voice selection cached by name in `localStorage("hxi_voice_name")`.
- `ui/src/components/IntentSurface.tsx` lines 7, 57, 195, 1466, 1491 — the existing Ship's Computer chat that already uses voice. Mirror this surface.
- `ui/src/components/profile/ProfileChatTab.tsx` (5511 bytes) — the 1:1 chat that needs voice. Currently NO voice imports.
- `ui/src/store/useStore.ts` — `voiceEnabled` global. Read by IntentSurface.
- `src/probos/profile_store.py` (AD-376) — schema for profile records. Add `voice_profile` field here.

**For AD-721 (3D crew avatars):**
- `ui/src/canvas/agents.tsx`, `animations.tsx`, `clusters.tsx`, `connections.tsx`, `scene.ts` — existing Three.js stack on the cognitive canvas.
- `ui/src/components/CognitiveCanvas.tsx` — main canvas component.
- `ui/src/components/profile/AgentProfilePanel.tsx` — the 2D profile card today. The 3D popout attaches here.
- `pyproject.toml` / `ui/package.json` — verify what 3D libraries are already installed.

### External research (architect MUST fetch + summarize before drafting)

**Primary absorption candidate (3D avatars):**
- **`@pixiv/three-vrm`** (1.9k stars, MIT, https://github.com/pixiv/three-vrm) — the canonical VRM 1.0 loader for Three.js. NPM-installable, docs + examples for full lifecycle (load, update, expressions, look-at, spring bones). The avatar standard. **STRONG fit:** ProbOS already uses Three.js; agent-authored appearance fits VRM's design intent (avatar metadata in the file itself); MIT license is clean.
- **`@readyplayerme/visage`** (90 stars, MIT, https://github.com/readyplayerme/visage) — React component wrapper for Ready Player Me avatars on Three.js. Smaller scope, opinionated, but ties to RPM hosted service. Architect must judge whether this is preferable to raw three-vrm or a layer on top of it.

**Tertiary references (architect surfaces in research, defers absorption):**
- **`microsoft/three.js-typescript-boilerplate`-style patterns**: facial blend-shape mapping, idle-loop animations, lip-sync.
- **`pmndrs/drei`** — already common on react-three-fiber stacks. Worth checking if ProbOS already uses it.
- **VRoid Studio** (free avatar authoring tool, exports VRM) — for the agent-authored appearance pipeline.

**Voice (AD-718) external candidates — architect should NOT bring these in for v1, but document as forward markers:**
- **Coqui TTS** (45.2k stars, MPL-2.0): full Python TTS toolkit, multi-speaker, voice cloning. Out of scope: requires Python service + audio routing back to UI; this is AD-705 territory.
- **ElevenLabs Python** (3k stars, MIT): cloud TTS API with per-character voice cloning. Out of scope: requires API key + commercial dependency; document as opt-in upgrade path.
- **Bark** (suno-ai): emotional/multi-speaker open-source TTS. Track only.

For v1 of AD-718, **stay on the existing browser SpeechSynthesis substrate** and add per-agent voice profile (voice name + pitch + rate) selected from the available local voices. Defer Coqui/ElevenLabs to AD-705 and AD-718-1 follow-ups.

## Subagent prompt — Architect (drafting + research pass)

Draft 2 prompts matching the format of `prompts/archive/ad-697-extension-registry-v1.md` and the recently-shipped `prompts/archive/ad-706-browser-tool-v1.md`. Required sections: header (Issue / Type / Depends-on / Wave 133), Goal, Verified Against Codebase (2026-05-08) with file:line citations, Scope, Deliverables (D1..Dn), Non-Goals, Acceptance, Tracking, **Forward markers** (per the new BUILDER-EXECUTION-PLAN convention — every deferred sub-AD must be enumerated for post-build filing).

### Prompt 1: `prompts/ad-718-profile-voice-chat-v1.md`

**Goal:** parity with Ship's Computer chat — mic input + TTS playback in `ProfileChatTab.tsx`, with **per-agent voice profile** so Counselor sounds different from Worf.

**Recommended deliverables (architect adjusts based on verify-first):**

- **D1: Mic button in `ProfileChatTab.tsx`** — mirror the IntentSurface.tsx L1466-L1491 shape. Reuse existing `speechInput.ts` substrate from `ui/src/voice/`.
- **D2: TTS playback gate** — when `voiceEnabled` global is on AND the message is from the agent (not the Captain) AND not a system message, call `speakResponse()` with the agent's voice profile.
- **D3: `voice_profile` field on profile schema** — `src/probos/profile_store.py` adds `voice_profile: dict | None` (`{voice_name, pitch, rate, volume}`). `voice_name` is matched against the user's local SpeechSynthesis voice list at speak-time; if missing, fall back to the global default with a warning logged once per agent per session.
- **D4: HXI Settings surface** — small UI widget on the profile card (or in a config panel) that lets the Captain pick a voice for each agent from the available SpeechSynthesis voices. This replaces "agent picks own voice" for v1; agent-authored voice is a forward marker.
- **D5: Default voice profiles for the standing crew** — Counselor warmer/slower, Worf deeper/firmer, etc. Ship a small mapping in `voice_profile_defaults.py` keyed on agent_type. New agents inherit a per-tier default.
- **D6: Tests** — happy path (mic click → STT → message sent), TTS playback when voiceEnabled, voice profile lookup, fallback when voice not available, multi-agent (different agents speak with different voices on the same page).

**Non-Goals:** new TTS backends (Coqui, ElevenLabs — defer to AD-705), wake-word per agent, voice cloning, multi-language voice selection in v1, agent-authored voice (defer to AD-718a).

**Forward markers** (must materialize as filed issues at gate-3):
- AD-718a — agent-authored voice profile (agent picks its own voice via personality reflection)
- AD-718b — Coqui/ElevenLabs backend integration via AD-705 substrate
- AD-718c — wake-word per agent (so the Captain can say "Hey Echo" instead of clicking)
- AD-718d — emotional voice modulation (pitch/rate driven by agent mood, sync with AD-721 expressions)

### Prompt 2: `prompts/ad-721-3d-crew-avatars-v1.md`

**Goal:** 3D popout avatar from each agent's profile card, with expression + body-language driven by trust/mood/working-state. Counselor (Echo) is the first design partner.

**Recommended deliverables (architect adjusts based on verify-first):**

- **D1: VRM-based avatar loader** — adopt `@pixiv/three-vrm` (1.9k stars, MIT). Verify-first: confirm `three`, `react-three-fiber`, `drei` already in `ui/package.json`; if any missing, add. Add `@pixiv/three-vrm` as a new dep.
- **D2: `appearance.json` field on profile schema** — `src/probos/profile_store.py` adds `appearance: dict | None` (`{vrm_url, expression_overrides, color_palette_hint}`). v1 supports VRM URL pointing to a model in `data/avatars/`. Generic ship defaults at `data/avatars/_defaults/{ensign,lieutenant,commander,senior_officer}.vrm` (or pre-bundled one set if VRM models are not yet authored).
- **D3: `CrewAvatarPopout.tsx`** — new React component that mounts a Three.js scene with the agent's VRM model. Triggered by clicking an "expand" affordance on the profile card. Renders in a popout dialog (modal-style) at fixed size (e.g., 320×480), animated entry.
- **D4: Expression mapping** — map agent runtime signals to VRM blend-shape channels:
  - Trust delta in last cycle → smile / frown
  - Cognitive load (LLM call active) → thinking gesture (look-up + slight head tilt)
  - Working state (idle / responding / blocked) → idle-loop / speaking-loop / concerned-loop
  - Tier-3 alert active → alert-eyes
- **D5: TTS-driven mouth animation** — when AD-718's `speakResponse()` plays audio, drive a simple mouth-open blend-shape channel via the audio amplitude (Web Audio API `AnalyserNode`). Phoneme-accurate lip-sync is a forward marker (AD-721b).
- **D6: Counselor's first appearance** — ship Echo's appearance proposal as the v1 reference. Architect should ask Counselor's intent (warm, approachable, non-uniformed, etc.) — but for v1, the Captain provides her VRM model OR the architect ships a generic warm-toned default and lets Echo iterate.
- **D7: Default appearance fallback** — agents without `appearance.json` get a generic placeholder VRM tinted by their department color.
- **D8: Tests** — VRM loader handles valid + invalid URLs, expression mapping reflects state transitions, mouth animation triggers on TTS playback (mock audio), default fallback when appearance missing, popout open/close lifecycle.

**Non-Goals:** photorealistic rendering, full phoneme-accurate lip-sync (defer to AD-721b), in-app avatar authoring UI (Captain edits `appearance.json` directly for v1), agent-driven appearance authoring (Counselor's iteration is via Captain-mediated edits), VR / spatial scene mode (defer to AD-721c).

**Forward markers** (must materialize as filed issues at gate-3):
- AD-721a — Captain's avatar editor UI (author appearance.json without touching JSON)
- AD-721b — phoneme-accurate lip-sync (ML model or regex-based phoneme estimator)
- AD-721c — VR / spatial-scene avatar mode (room-scale crew)
- AD-721d — agent-authored appearance pipeline (agent reflects on personality and proposes appearance edits)
- AD-721e — full skeletal animation library (idle variations, gestures, hand poses) — Mixamo absorption candidate

### Cross-cutting requirements (apply to BOTH prompts)

1. **Working-tree integrity bullet** in Acceptance: `git diff --numstat | sort -k2nr | head -5`; >200 deletions on tracked file = STOP.
2. **Pre-commit deletion check** (HARD RULE per BUILDER-EXECUTION-PLAN).
3. **AD-numbering re-verification** at commit time.
4. **Default-False on transitional flags** — if you add an `enabled` flag, default False (Wave 10 #14).
5. **Forward-marker filing** — every deferred sub-AD must be filed as a GH issue at gate-3 before push (per Wave 132 retrospective + new BUILDER-EXECUTION-PLAN Post-Sweep step 6).
6. **Phantom-API discipline** — every cited file:line must be verified at HEAD. The drafting Architect surfaces contradictions in the final report.
7. **Test boundary coverage** — each public method needs happy + error + edge case tests per `.github/copilot-instructions.md`.

## McpAppFrame consideration (for AD-721)

`McpAppFrame` (AD-597a, iframe-based) is one option for rendering the 3D popout. Architect should evaluate:
- Pro: reuses existing iframe + bridge surface; isolates Three.js scene from main HXI canvas
- Con: extra communication boundary for expression/state updates; iframe overhead

**Default recommendation: render directly in the React tree** (not iframe-isolated) since the expression channels need fine-grained reactive updates and the 3D scene is small. Keep `McpAppFrame` reserved for the Captain-watch streaming surface (AD-706a) where iframe isolation actually matters.

## Output

- Two prompts at `prompts/ad-718-profile-voice-chat-v1.md` and `prompts/ad-721-3d-crew-avatars-v1.md`.
- Touch nothing else.

## Final report

After both prompts are written, return ONE message containing:
1. One-line summary per prompt.
2. Verify-first findings (any contradictions with the dispatch).
3. Risk classification per prompt.
4. AD-718: chosen voice-profile schema (D3) and the specific default-voice mapping you assigned to standing crew.
5. AD-721: VRM library decision (three-vrm vs Visage), default-fallback strategy when no `appearance.json` exists.
6. Forward markers per prompt (these become filed issues at gate-3).
7. Standing-convention concerns surfaced.
8. Audit trail: upstream URLs / file paths actually fetched/read.

Begin.
