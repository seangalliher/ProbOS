# AD-733c-7 — Silero VAD secondary engagement trigger

**Issue:** [#678](https://github.com/seangalliher/ProbOS/issues/678)
**Status:** GATE 1 — drafting (Wave 176)
**Depends on:** AD-733c-2 (`PerceptionModeController`), AD-733c-3
(wake-word → engage endpoint shipped Wave 172), AD-733c-5 (per-agent
engagement — built earlier in this wave; VAD routes through the
registry).
**Estimated tests:** +8 pytest, +5 vitest.

---

## Problem

AD-733c-3 shipped wake-word as the only voice-side engagement trigger.
If Captain starts talking to an agent without explicitly saying
"Hello Ezri" first, perception stays AMBIENT — frames continue to
arrive but the supervisor admits them at the ambient (slower) rate.

Silero VAD (MIT, ~1-1.5 MB ONNX) gives frame-level "is_speech" signal
in the browser. Voice activity in front of the camera is a strong
signal "the Captain is interacting with the system" → at minimum,
DORMANT → AMBIENT; combined with the wake-word ONNX pipeline already
loaded by `wakeWord.ts`, it's a cheap upgrade.

## Solution

VAD is a NEW ENGAGEMENT TRIGGER, NOT a strategy plugin. It calls a
new `note_voice_activity()` hook on the per-agent
`PerceptionModeController`. The transition ladder mirrors
`note_dm_activity` (step-wise ramp DORMANT→AMBIENT→ENGAGED) but with
its own cooldown to prevent flap on continuous speech.

### Browser side

- New `ui/src/audio/silero-vad.ts` — lazy-loaded ONNX runtime web
  module (already a transitive dep of `wakeWord.ts`, no new npm dep
  expected — Builder verifies via `npm ls onnxruntime-web` pre-flight).
- New `ui/src/audio/voiceActivity.ts` — pulls audio frames from the
  same getUserMedia stream the wake-word path already opens. Emits
  a debounced "speech_started" / "speech_ended" event pair via
  Zustand store.
- The Silero model file (`silero_vad.onnx`, ~1.5 MB) is operator-
  pullable via a NEW PowerShell script `scripts/silero-vad-fetch.ps1`
  mirroring `piper-voice-fetch.ps1` / `avatar-assets-fetch.ps1`
  shape. Bytes NEVER committed to the repo (`.gitignore` rule).
  License-clean by construction: the model is MIT (verify upstream).
  `THIRD_PARTY_LICENSES.md` stamp added.
- New API call: `POST /api/perception/voice-activity {agent?, source:
  "vad"}` mirrors the AD-733c-3 `/engage` endpoint shape.
  Fire-and-forget from `voiceActivity.ts`.

### Backend side

- New `PerceptionModeController.note_voice_activity()` method:
  ```python
  def note_voice_activity(self) -> tuple[bool, str]:
      """AD-733c-7: VAD-driven engagement trigger.

      Step-wise ramp like note_dm_activity, but VAD-cooled (3s).
      """
  ```
  - Cooldown floor: `VOICE_ACTIVITY_COOLDOWN_S = 3.0` (between
    `PROGRAMMATIC_COOLDOWN_S=1.0` and `WAKE_WORD_COOLDOWN_S=5.0`).
  - Step-wise ramp: DORMANT → AMBIENT (one note); AMBIENT → ENGAGED
    (next note, after dwell).
  - ENGAGED already → no-op (refresh `last_voice_activity_at` only).
  - Returns `(transitioned, reason)` mirroring `note_wake_word`.
- New `POST /api/perception/voice-activity` in `routers/perception.py`:
  - Body: `{agent?: str, source: "vad"}`.
  - Behind `require_crew_scope` (same as `/engage`).
  - Routes to per-agent controller via the AD-733c-5 registry; falls
    back to singleton if registry not wired.
  - Returns `{transitioned: bool, reason: str, mode: str}`.
- New `PerceptionConfig.vad_engagement_enabled` (default-OFF
  transitional gate per convention #14).
- New `PerceptionConfig.vad_min_speech_duration_ms` (default 400,
  `ge=100, le=2000`) — browser-side debounce floor before firing
  the endpoint.

## Cross-AD interaction notes

- **Orthogonal to AD-733c-5** — VAD is a new TRIGGER feeding the
  same per-agent controller. NOT a registry of strategies; the
  controller is the single state owner.
- **Sibling of AD-733c-3 wake-word** — same shape (`/engage` and
  `/voice-activity` are siblings). Wake-word still takes precedence
  for cross-mode jumps (DORMANT → ENGAGED in one step); VAD requires
  the step-wise ramp.
- **Browser pause getUserMedia in DORMANT** — Captain's issue
  mentions this. DEFERRED to forward marker `AD-733c-7-1` because
  the BroadcastChannel signal + race-condition handling is its own
  AD. v1: VAD wakes from DORMANT but does not handle the inverse
  (ENGAGED → DORMANT auto-pause stays the AD-733c-4 idle-drop-back
  path).
- **WardRoom / multi-Captain mics**: NOT in v1. The VAD endpoint
  trusts the source — multi-mic disambiguation is forward marker
  `AD-733c-7-2`.

## Scope

- New file: `ui/src/audio/silero-vad.ts` (~120 lines).
- New file: `ui/src/audio/voiceActivity.ts` (~80 lines).
- New file: `scripts/silero-vad-fetch.ps1` (~50 lines, mirrors
  `piper-voice-fetch.ps1`).
- New method: `PerceptionModeController.note_voice_activity()`.
- New constant: `VOICE_ACTIVITY_COOLDOWN_S = 3.0` next to existing
  `WAKE_WORD_COOLDOWN_S` / `PROGRAMMATIC_COOLDOWN_S`.
- New attribute: `self._last_voice_activity_at: float = 0.0` on
  controller (initialized in `__init__`).
- New endpoint: `POST /api/perception/voice-activity` in
  `routers/perception.py`.
- New config fields: `PerceptionConfig.vad_engagement_enabled` (False),
  `vad_min_speech_duration_ms` (400). Both with FieldDescriptor
  entries.
- Modify: `ui/src/components/perception/CameraLiveIndicator.tsx` —
  add a SPEECH indicator (animated stroke pulse when speech_started).
- Modify: `.gitignore` — `data/silero-vad/` rule.
- Modify: `THIRD_PARTY_LICENSES.md` — Silero VAD entry.

## NOT in scope

- Browser pause `getUserMedia` in DORMANT → AD-733c-7-1 forward marker.
- Multi-mic disambiguation → AD-733c-7-2 forward marker.
- Speaker diarization (whose voice is talking) → AD-733c-7-3 forward
  marker.
- VAD-driven mute (when Captain isn't talking, suppress wake-word
  scoring to save CPU) → AD-733c-7-4 forward marker.
- Audio-frame intent (sending audio bytes server-side for ASR) — VAD
  is BROWSER-LOCAL; bytes never leave the browser. Server only gets
  the boolean "speech detected at ts T."

## Pre-flight grep anchors (Builder MUST verify before locking edits)

1. `src/probos/perception/mode_controller.py:38` (or thereabouts) —
   `WAKE_WORD_COOLDOWN_S` and `PROGRAMMATIC_COOLDOWN_S` constants
   defined. Insert `VOICE_ACTIVITY_COOLDOWN_S` next to them.
2. `src/probos/perception/mode_controller.py:231` — `def
   note_wake_word(self) -> tuple[bool, str]:` is the closest sibling
   shape to mimic.
3. `src/probos/perception/mode_controller.py:101` — `__init__` adds
   `self._last_voice_activity_at = 0.0`.
4. `src/probos/routers/perception.py:293` — `@router.post("/engage"...)`
   is the precedent endpoint. Insert `/voice-activity` adjacent.
5. `src/probos/config.py` — `class PerceptionConfig` (anchor via
   grep). Insert `vad_engagement_enabled` + `vad_min_speech_duration_ms`
   fields after existing AD-733c-3 wake-word fields.
6. `ui/src/audio/wakeWord.ts` — already lazy-loads
   `onnxruntime-web`. Verify it's resident in `package.json`
   (Builder runs `npm ls onnxruntime-web` at pre-flight).
7. `scripts/piper-voice-fetch.ps1` — exact shape to mirror for
   `silero-vad-fetch.ps1` (SHA verification, `.gitignore`-aware
   download dir).
8. `ui/src/components/perception/CameraLiveIndicator.tsx` —
   existing mode badge component to extend.

## Engineering-principles audit

- **SOLID load-bearing**: Single Responsibility — VAD module ONLY
  detects speech and emits a boolean event. Engagement decisions
  stay in the controller.
- **Defaults preserve behavior**: `vad_engagement_enabled=False`
  default → endpoint exists but the browser never calls it; no
  controller state changes.
- **AD-731 invariant**: N/A (no image bytes). Audio bytes are
  browser-local (Web Audio API), NEVER sent to server. Source-scan
  test on `voiceActivity.ts` asserts no `fetch` of audio payloads
  (`/voice-activity` POST body is JSON only).
- **AD-541b memory integrity**: N/A (no episodic writes).
- **Hot-reload posture**:
  - `vad_engagement_enabled` → restart-required (browser
    initialization happens at app boot via `voiceActivity.ts`).
  - `vad_min_speech_duration_ms` → hot-reload (browser polls
    config on next start).
- **Anti-deadlock**: `note_voice_activity` is sync; no async locks.
- **Async discipline**: Browser side uses
  `AudioWorkletProcessor` (no JS tasks); server endpoint is a single
  async handler with no background tasks.
- **License posture**:
  - `silero-vad` (ONNX model): MIT. Operator-pullable via the new
    fetch script; bytes gitignored.
  - `onnxruntime-web` (npm): already resident, MIT-licensed.
  - 0-line diff on `pyproject.toml`. 0-line diff on `package.json`
    AND `package-lock.json` if `onnxruntime-web` already resident.
    `THIRD_PARTY_LICENSES.md` +1 entry for Silero. `.gitignore` +1
    rule.
- **Test scaffolding**: real `SystemConfig()` + real
  `PerceptionModeController` (BF-287). Browser tests via Vitest +
  Web Audio mocks (no real audio device).
- **HXI Principle #3**: SPEECH indicator is a stroke-pulse, no emoji.

## Test plan (+8 pytest, +5 vitest)

`tests/test_ad733c7_vad_engagement.py`:

1. `test_note_voice_activity_dormant_to_ambient` — one note from
   DORMANT → AMBIENT, transitioned=True.
2. `test_note_voice_activity_ambient_to_engaged` — second note (past
   dwell) → ENGAGED.
3. `test_note_voice_activity_engaged_refreshes` — third note while
   ENGAGED → reason="refreshed", transitioned=False.
4. `test_note_voice_activity_cooldown_blocks_within_3s` —
   second call within 3s → reason="cooldown".
5. `test_voice_activity_endpoint_routes_per_agent` — `POST
   /api/perception/voice-activity {agent: "e1"}` transitions Ezri
   only (depends on AD-733c-5).
6. `test_voice_activity_endpoint_unknown_agent_404`.
7. `test_voice_activity_endpoint_disabled_503` — when
   `vad_engagement_enabled=False`, endpoint returns 503
   honest-degrade.
8. `test_ad731_invariant_source_scan_voice_activity_browser_module` —
   pytest source-scan of `voiceActivity.ts` content (read as text,
   `re.search`) asserts no `fetch` URLs carrying audio MIME types.

`ui/src/audio/__tests__/voiceActivity.test.ts` (+5 vitest):

1. `silero-vad.ts` lazy-loads on first call; not loaded at import.
2. Speech-start event fires after debounce floor.
3. Speech-end event fires after silence.
4. `voiceActivity.ts` POSTs to `/api/perception/voice-activity` with
   JSON body only (no audio bytes).
5. `CameraLiveIndicator.tsx` renders SPEECH indicator when store
   says speech_active.

## Tracker updates (Builder)

- `PROGRESS.md` — Wave 176 line.
- `docs/development/roadmap.md` — `AD-733c-7` row + forward markers
  AD-733c-7-1/-2/-3/-4.
- `DECISIONS.md` — at build time.

## Acceptance criteria

1. `vad_engagement_enabled=False` (default) → existing behavior
   bit-for-bit unchanged.
2. With VAD enabled + browser model fetched: speech in front of the
   camera transitions DORMANT → AMBIENT after one detection.
3. Cooldown prevents flap: continuous speech does not spam transitions.
4. Per-agent routing works (AD-733c-5 dependency satisfied).
5. Silero model NOT committed to repo; fetch script downloads to
   `.gitignored` directory; SHA verified.
6. All 8 pytest + 5 vitest pass.
7. `cd ui && npm run build` exit 0; `npm ls onnxruntime-web` confirms
   no version bump.
8. Zero new pip deps. Zero new npm deps. +1 line on
   `THIRD_PARTY_LICENSES.md`. +1 line on `.gitignore`.
9. **Verify all changes comply with the Engineering Principles in
   `.github/copilot-instructions.md`.**
