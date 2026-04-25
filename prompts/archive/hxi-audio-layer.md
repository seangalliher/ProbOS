# HXI Audio Layer — "Make It Alive"

## Context

The HXI visual refinement is complete — the canvas now has bloom, connections, depth, tooltips, onboarding, and atmospheric polish. This pass adds **audio** to make the cognitive mesh feel alive through sound, not just sight.

Three layers, in order of priority:

1. **Ambient system sounds** — the mesh has a sonic heartbeat (Web Audio API, zero dependencies)
2. **Voice output** — ProbOS speaks its responses (Piper TTS, local, free)
3. **Voice input** — talk to ProbOS instead of typing (browser SpeechRecognition API, zero dependencies)

**Current state:** 1532/1532 Python tests passing. This pass adds a Python `/api/tts` endpoint (for Layer 2) and TypeScript audio code.

**No new AD numbers.** This is experiential polish within the HXI scope.

---

## Layer 1: Ambient System Sounds (TypeScript — Web Audio API)

**File:** `ui/src/audio/soundEngine.ts` (new)

The mesh has a sonic texture. Sounds are procedurally generated via Web Audio API oscillators — no audio files to download or bundle.

### Sound events

| System Event | Sound | Implementation |
|-------------|-------|----------------|
| **Heartbeat** | Low, soft thump at ~1.2s intervals. Gentle bass hit with fast attack, slow release | `OscillatorNode` (sine, 55Hz) → `GainNode` envelope (attack 10ms, release 300ms) |
| **Intent routing** | Soft ascending chime when a request enters the mesh | Two oscillators (sine 440Hz + 660Hz) with quick fade, slight delay between them |
| **Consensus formation** | Harmonic convergence — three tones resolving to unison | Three oscillators starting at different frequencies, gliding to a single frequency over 500ms |
| **Self-mod agent spawn** | Rising shimmer — ascending frequency sweep with sparkle | Oscillator sweep (200Hz → 800Hz over 600ms) with slight vibrato + high-frequency shimmer overlay |
| **Dream mode enter** | Warm pad fade-in — ambient drone that shifts lower and warmer | Low-pass filtered noise + sine pad (80Hz), cross-fading in over 3 seconds |
| **Dream mode exit** | Pad fades out over 2 seconds, replaced by heartbeat at normal tempo | Reverse of dream enter |
| **Trust update (positive)** | Barely perceptible rising pitch ping | Very quiet sine ping (880Hz, 50ms duration, gain 0.05) |
| **Error/failure** | Low muted dissonant note | Two detuned oscillators (200Hz + 207Hz), fast decay |

### Architecture

```typescript
class SoundEngine {
  private ctx: AudioContext | null = null;
  private masterGain: GainNode | null = null;
  private muted: boolean = false;
  private volume: number = 0.3; // default 30%

  init(): void {
    // AudioContext requires user gesture to start
    // Call on first user interaction (click/keypress)
    this.ctx = new AudioContext();
    this.masterGain = this.ctx.createGain();
    this.masterGain.gain.value = this.volume;
    this.masterGain.connect(this.ctx.destination);
  }

  setVolume(v: number): void { ... }
  setMuted(m: boolean): void { ... }
  
  playHeartbeat(): void { ... }
  playIntentRouting(): void { ... }
  playConsensus(): void { ... }
  playSelfModSpawn(): void { ... }
  playDreamEnter(): void { ... }
  playDreamExit(): void { ... }
  playTrustPing(positive: boolean): void { ... }
  playError(): void { ... }
}

export const soundEngine = new SoundEngine();
```

### Wiring into the store

**File:** `ui/src/store/useStore.ts` — extend `handleEvent()`:

```typescript
// In the event handler switch:
case 'system_mode':
  if (event.data.mode === 'dreaming') soundEngine.playDreamEnter();
  if (event.data.previous === 'dreaming') soundEngine.playDreamExit();
  break;
case 'consensus':
  soundEngine.playConsensus();
  break;
case 'trust_update':
  soundEngine.playTrustPing(event.data.success);
  break;
case 'self_mod_success':
  soundEngine.playSelfModSpawn();
  break;
```

Start the heartbeat loop when connected:
```typescript
// On state_snapshot received (connection established):
soundEngine.init(); // AudioContext needs user gesture — init on first interaction instead
setInterval(() => soundEngine.playHeartbeat(), 1200);
```

**Important:** `AudioContext` requires a user gesture (click, keypress) before it can play audio. Initialize the sound engine on the first chat input submission or canvas click, NOT on page load. Show a subtle "🔊" indicator in the status bar once audio is active.

### UI Controls

**Volume + mute controls** in the status bar (bottom):
- 🔊 icon — click to mute/unmute
- Small volume slider (range 0-1, default 0.3)
- Store preference in `localStorage` so it persists

**Sound must be OFF by default** — respect users who don't want surprise audio. Show a subtle "🔇 Enable sound" button in the status bar. Click initializes AudioContext and starts the heartbeat.

---

## Layer 2: Voice Output — ProbOS Speaks (Python + TypeScript)

**Python side — `/api/tts` endpoint:**

**File:** `src/probos/api.py` (extend)

Add a TTS endpoint that converts text to audio:

```python
@app.post("/api/tts")
async def text_to_speech(req: TTSRequest) -> StreamingResponse:
    """Convert text to speech audio.
    
    Uses piper-tts if available, falls back to no audio.
    """
```

**Option A — Piper TTS (recommended):**
- Install: `pip install piper-tts` (add to `pyproject.toml` as optional dependency)
- Piper runs locally, no API keys, fast on CPU
- Returns WAV audio as a streaming response
- The frontend plays it via `<audio>` element or Web Audio API

```python
async def _generate_speech(text: str) -> bytes:
    """Generate speech audio using Piper TTS."""
    try:
        import piper
        voice = piper.PiperVoice.load("en_US-lessac-medium")  # natural English voice
        audio_bytes = io.BytesIO()
        voice.synthesize(text, audio_bytes, format="wav")
        return audio_bytes.getvalue()
    except ImportError:
        return b""  # No TTS available
```

**The voice model** needs to be downloaded on first use. Piper models are ~60MB. Add a `probos init` step or lazy download on first `/api/tts` call.

**Option B — Browser SpeechSynthesis (simpler, lower quality):**
Skip the Python endpoint entirely. The frontend calls `speechSynthesis.speak()` with the response text. Zero infrastructure. Sounds robotic but works immediately.

**Recommendation:** Ship **Option B first** (browser SpeechSynthesis) for immediate results, add Piper TTS as an upgrade path. This avoids blocking on model downloads.

**TypeScript side:**

**File:** `ui/src/audio/voice.ts` (new)

```typescript
export function speakResponse(text: string): void {
  if (!('speechSynthesis' in window)) return;
  
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.rate = 0.95;    // slightly slower than default
  utterance.pitch = 0.9;    // slightly deeper
  utterance.volume = 0.8;
  
  // Prefer a natural-sounding voice if available
  const voices = speechSynthesis.getVoices();
  const preferred = voices.find(v => 
    v.name.includes('Google') || v.name.includes('Natural') || v.name.includes('Samantha')
  );
  if (preferred) utterance.voice = preferred;
  
  speechSynthesis.speak(utterance);
}
```

**Wire into chat response handler** in `IntentSurface.tsx`:
```typescript
// After receiving chat response and displaying it:
if (voiceEnabled && responseText) {
  speakResponse(responseText);
}
```

**Voice toggle** in the status bar: 🗣️ icon, click to enable/disable voice output. Off by default. Store in `localStorage`.

---

## Layer 3: Voice Input — Talk to ProbOS (TypeScript only)

**File:** `ui/src/audio/speechInput.ts` (new)

```typescript
export function startListening(onResult: (text: string) => void): void {
  if (!('webkitSpeechRecognition' in window || 'SpeechRecognition' in window)) return;
  
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const recognition = new SpeechRecognition();
  recognition.continuous = false;
  recognition.interimResults = false;
  recognition.lang = 'en-US';
  
  recognition.onresult = (event) => {
    const text = event.results[0][0].transcript;
    onResult(text);
  };
  
  recognition.start();
}
```

**UI:** Add a microphone button (🎤) next to the chat input field. Hold or click to start listening. When speech is recognized, it populates the chat input and auto-submits.

**Visual indicator:** While listening, the microphone icon pulses red. The status bar shows "🎤 Listening..."

---

## Implementation Order

1. **Layer 1: Ambient sounds** — `soundEngine.ts`, wire into store, add mute/volume controls. Test: can you hear the heartbeat?
2. **Layer 2: Voice output** — `voice.ts` with browser SpeechSynthesis, wire into chat response handler, add voice toggle. Test: does ProbOS speak its responses?
3. **Layer 3: Voice input** — `speechInput.ts`, add microphone button, wire into chat input. Test: can you talk to ProbOS?

**After all three: run `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q` to verify no Python regressions.**

---

## Do NOT Change

- No Python runtime behavior changes
- No WebSocket protocol changes
- No new Python tests (audio is experiential, not testable via pytest)
- No changes to agent behavior or decomposer logic
- No external API dependencies for Layer 1 or Layer 3 (Web Audio + SpeechRecognition are browser-native)
- Layer 2 uses browser SpeechSynthesis first — Piper TTS is a future upgrade, NOT required for this pass

## Critical UX Rules

- **Sound OFF by default.** Never surprise users with audio. Require explicit opt-in
- **Volume control always visible.** The mute button must be discoverable
- **Voice output doesn't block UI.** Speech plays asynchronously — the user can keep typing while ProbOS speaks
- **Voice input is optional.** Not all browsers support SpeechRecognition. Graceful fallback to typing
- **AudioContext starts on user gesture only.** No autoplay. The first click/keypress initializes audio
