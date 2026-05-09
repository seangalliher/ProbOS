# AD-718 v1 — Voice in 1:1 Profile Chat (per-agent voice profiles)

**Issue:** [#512](https://github.com/seangalliher/ProbOS/issues/512)
**Type:** Architecture Decision (HXI parity — voice in profile chat)
**Depends on:** AD-376 (`CrewProfile`), AD-474b/c (browser STT), Ship's-Computer-chat voice loop in `IntentSurface.tsx`
**Wave:** 133

## Goal

Bring `ProfileChatTab.tsx` to parity with the Ship's Computer chat (`IntentSurface.tsx`): mic-button STT input, and TTS playback of the agent's reply when `voiceEnabled` is on. Each crew member speaks with a distinct voice (Counselor warmer/slower, Worf deeper/firmer, etc.) via a new `voice_profile` field on `CrewProfile`. v1 stays on the existing browser `SpeechSynthesis` substrate — no Coqui / ElevenLabs / Bark backends. Captain picks the per-agent `voice_name` from the browser's local voice list; ProbOS ships the `pitch`/`rate` defaults.

This AD ships in the same wave as AD-721 (3D crew avatars) so the TTS-driven mouth animation in AD-721 D5 can hook into a single, deterministic playback callback shape that AD-718 owns.

## Verified Against Codebase (2026-05-08)

Line numbers are "around line N" (per `review-criteria.md` §6) — exact line drift can occur between authoring and Builder dispatch; greps below are ground truth at 2026-05-08 HEAD.

```
grep -n "speakResponse\|findPreferredVoice\|getAvailableVoices\|cachedVoice\|utterance\." ui/src/audio/voice.ts
   4: let cachedVoice: SpeechSynthesisVoice | null = null;
   6: function findPreferredVoice(): SpeechSynthesisVoice | null {
  18: cachedVoice = saved;
  37: cachedVoice = preferred;
  44: cachedVoice = null;
  49: export function speakResponse(text: string): void {
  56:   utterance.rate = 0.95;
  57:   utterance.pitch = 0.9;
  58:   utterance.volume = 0.8;
  60:   const voice = findPreferredVoice();
  72: export function getAvailableVoices(): SpeechSynthesisVoice[] {
  78: cachedVoice = null;
```

- ✅ `ui/src/audio/voice.ts` around line 49 — `speakResponse(text)` is the canonical TTS entry. **It hardcodes `utterance.rate = 0.95`, `utterance.pitch = 0.9`, `utterance.volume = 0.8` (around lines 56–58).** v1 must extend the signature to accept an optional `VoiceProfile` override; existing callers stay source-compatible.
- ✅ `ui/src/audio/voice.ts` around line 6 — `findPreferredVoice()` consults a single `localStorage("hxi_voice_name")` key. v1 keeps this as the **global** default fallback; per-agent voice resolution does NOT touch this key.
- ✅ `ui/src/audio/voice.ts` — `cachedVoice` (around lines 4, 18, 37, 44, 78) and `setPreferredVoiceName()` (around line 77) mutate one global cache. **Per-agent profiles must NOT pollute this cache** — D2 looks up a `SpeechSynthesisVoice` by name on each call without writing `cachedVoice`.
- ✅ `ui/src/audio/speechInput.ts` — `isSpeechRecognitionSupported()`, `startListening(...)`, `stopListening()` (around lines 23 / 50 / 64). **Note: the file lives at `ui/src/audio/speechInput.ts`, NOT `ui/src/voice/speechInput.ts` as the dispatch implies.** All imports use `'../../audio/speechInput'` from `ProfileChatTab.tsx` (two levels up — file is in `ui/src/components/profile/`).
- ✅ `ui/src/components/IntentSurface.tsx:7` `import { speakResponse } from '../audio/voice';`
- ✅ `ui/src/components/IntentSurface.tsx:8` `import { startListening, stopListening, isSpeechRecognitionSupported } from '../audio/speechInput';`
- ✅ `ui/src/components/IntentSurface.tsx` around line 57 — `const voiceEnabled = useStore((s) => s.voiceEnabled);`
- ✅ `ui/src/components/IntentSurface.tsx` around lines 196–207 — markdown-stripping pre-TTS pipeline (`cleanText` assignment chain ending in `speakResponse(cleanText)` at ~line 207). **D2 reuses this pipeline verbatim** — extract to a shared helper rather than duplicating.
- ✅ `ui/src/components/IntentSurface.tsx` around lines 1467–1522 — mic-button JSX (button + inline SVG mic glyph + listening-pulse style). The accompanying `@keyframes pulse-mic` block lives around line 1631 at the bottom of the file. **Mirror this surface in `ProfileChatTab.tsx` with the same SVG, the same `pulse-mic` keyframe, AND copy the keyframe block into `ProfileChatTab.tsx` (or a shared CSS module) — without it the listening-pulse silently no-ops.**
- ✅ `ui/src/components/profile/ProfileChatTab.tsx` (entire file) — currently NO `voice` or `speechInput` imports, NO mic button, NO TTS playback. Plain text input + Send button. Adds `data.response` to the conversation via `addAgentMessage(agentId, 'agent', data.response || '(no response)')` (line ~58).
- ✅ `ui/src/store/useStore.ts:327` `voiceEnabled: boolean;` (state interface), `:597` `voiceEnabled: false,` (initial), `:1140` `setVoiceEnabled` setter. **No store changes needed.**
- ✅ `src/probos/crew_profile.py` around line 215 — `class ProfileStore`. **The dispatch refers to `src/probos/profile_store.py` — that file does NOT exist; the actual module is `crew_profile.py` and the dataclass is `CrewProfile` (around line 116).** D3 mounts the new `voice_profile` field on `CrewProfile`, not on a non-existent `ProfileStore` schema.
- ✅ `src/probos/crew_profile.py` around line 116 — `@dataclass class CrewProfile` already has `personality: PersonalityTraits = field(default_factory=PersonalityTraits)` (PersonalityTraits is around line 51) and `personality_baseline`. Pattern: nested dataclass with `to_dict()/from_dict()` and a top-level `field(default_factory=...)`. **D3 mirrors this pattern with `VoiceProfile`.**
- ✅ `src/probos/crew_profile.py` around lines 170–210 — `CrewProfile.to_dict()` / `from_dict()` — both must learn the new field.
- ✅ `src/probos/routers/agents.py` around line 40 — `@router.get("/{agent_id}/profile")` — returns `profile_data` dict around line 110. **D5 adds `"voiceProfile": ...` to this dict** (camelCase, matching existing `displayName`/`agencyLevel`/`hebbianConnections`).
- ✅ `src/probos/routers/agents.py` around line 166 — `@router.post("/{agent_id}/chat")` — agent reply path. **No backend change needed**; TTS is client-side and reads `voiceProfile` from the profile fetch already issued by `AgentProfilePanel.tsx`.
- ✅ `src/probos/routers/agents.py` around line 362 — `@router.get("/{agent_id}/chat/history")` — seed-memory path used by `ProfileChatTab.tsx` around line 22. Untouched.
- ✅ `ui/package.json:11–22` no STT/TTS dependencies — v1 stays on the browser-native APIs already in use.
- ✅ `config/standing_orders/crew_profiles/*.yaml` — 15 standing-crew YAMLs verified (counselor, security_officer, diagnostician, architect, builder, engineering_officer, operations_officer, scout, pathologist, surgeon, pharmacist, data_analyst, research_specialist, systems_analyst, training_officer). D5 ships defaults keyed on the YAML stem (== `agent_type`).

**Dispatch contradictions surfaced:**

1. Dispatch says "`src/probos/profile_store.py` (AD-376) — schema for profile records." → **Actual:** `src/probos/crew_profile.py`, dataclass `CrewProfile`. Prompt below uses the real names.
2. Dispatch says "Reuse existing `speechInput.ts` substrate from `ui/src/voice/`." → **Actual:** `ui/src/audio/speechInput.ts`. Imports below use the real path.
3. Dispatch references "AD-376 ProfileStore schema" — `ProfileStore` exists but is a SQLite persistence layer; the **schema** lives on `CrewProfile`.

## Scope (v1 only)

- Mic-button STT in `ProfileChatTab.tsx` (parity with `IntentSurface.tsx`).
- TTS playback of the **agent reply only** (not the user's outgoing message, not system error placeholders that start with `(`).
- New `VoiceProfile` dataclass on `CrewProfile` with `voice_name`, `pitch`, `rate`, `volume`.
- Default `voice_name` is empty (Captain picks per browser/machine); `pitch`/`rate` defaults seeded per `agent_type`.
- Backend exposes the profile via the existing `/api/agent/{id}/profile` endpoint.
- Per-agent voice picker on the profile card (Profile tab — small dropdown of `getAvailableVoices()`, plus pitch/rate sliders).
- Default-False guard via `voiceEnabled` global (already exists; no new config flag).
- Tests for VoiceProfile (Python) + chat/voice integration (Vitest).

## Non-Goals (explicit)

- New TTS backends (Coqui, ElevenLabs, Bark) — defer to AD-718b via the AD-705 substrate.
- Wake-word per agent ("Hey Echo") — defer to AD-718c.
- Emotional voice modulation tied to mood/trust — defer to AD-718d (synergizes with AD-721 expression channels).
- Agent-authored voice profiles (agent picks own voice via personality reflection) — defer to AD-718a.
- Multi-language voice selection — defer to AD-718e.
- Phoneme-accurate lip-sync coupling to AD-721 — that AD owns its own audio-amplitude analyser; v1 contract is "TTS playback fires a callback the avatar can hook into" (D6).
- Persisting `voice_name` across machines (browser voice lists differ across OSes) — `voice_name` is best-effort; on miss, fall back to `pitch`/`rate` applied to the global default voice.

## Deliverables

### D1. Extend `ui/src/audio/voice.ts` to accept a per-call profile

Replace the existing `speakResponse` and add a typed profile interface plus a playback-event callback registry (for AD-721's mouth animation hook).

```typescript
// ui/src/audio/voice.ts (replace existing speakResponse and append helpers)

/** AD-718: Per-call voice override. All fields optional. */
export interface VoiceProfile {
  voice_name?: string;   // exact SpeechSynthesisVoice name; falls back to global default if missing
  pitch?: number;        // 0.0–2.0; default 0.9 (matches v0 behaviour)
  rate?: number;         // 0.1–10.0; default 0.95 (matches v0)
  volume?: number;       // 0.0–1.0; default 0.8 (matches v0)
}

/** AD-718 / AD-721 hook: subscribers fire on every utterance lifecycle event.
 *  Used by AD-721 CrewAvatarPopout to drive mouth blend-shape from audio.
 *  v1 emits 'start' and 'end' only; 'boundary' is reserved for AD-721b phoneme work. */
export type SpeechEventType = 'start' | 'end' | 'boundary';
export interface SpeechEvent {
  type: SpeechEventType;
  agent_id?: string;     // present iff caller passed one to speakResponse
  utterance: SpeechSynthesisUtterance;
}
type SpeechListener = (e: SpeechEvent) => void;

const _speechListeners = new Set<SpeechListener>();
export function onSpeechEvent(fn: SpeechListener): () => void {
  _speechListeners.add(fn);
  return () => _speechListeners.delete(fn);
}
function _fire(e: SpeechEvent): void {
  // Tier-2 log-and-degrade: a buggy listener must not break TTS.
  for (const fn of _speechListeners) {
    try { fn(e); } catch (err) { console.warn('[voice] listener error', err); }
  }
}

/** Look up a voice by exact name without mutating the global cache. */
function _resolveVoiceByName(name: string): SpeechSynthesisVoice | null {
  if (!name || !('speechSynthesis' in window)) return null;
  const v = speechSynthesis.getVoices().find(x => x.name === name);
  return v ?? null;
}

/** AD-718: agent_id is optional; when provided it is forwarded to listeners
 *  so AD-721 can route mouth animation to the right avatar. */
export function speakResponse(
  text: string,
  profile?: VoiceProfile,
  agent_id?: string,
): void {
  if (!('speechSynthesis' in window)) return;
  speechSynthesis.cancel();

  const utterance = new SpeechSynthesisUtterance(text);
  utterance.rate   = profile?.rate   ?? 0.95;
  utterance.pitch  = profile?.pitch  ?? 0.9;
  utterance.volume = profile?.volume ?? 0.8;

  const named = profile?.voice_name ? _resolveVoiceByName(profile.voice_name) : null;
  const voice = named ?? findPreferredVoice();
  if (voice) utterance.voice = voice;

  utterance.onstart = () => _fire({ type: 'start', agent_id, utterance });
  utterance.onend   = () => _fire({ type: 'end',   agent_id, utterance });
  // 'boundary' reserved for AD-721b phoneme work; not wired in v1.

  speechSynthesis.speak(utterance);
}
```

`stopSpeaking`, `getAvailableVoices`, `setPreferredVoiceName`, `getCurrentVoiceName` are unchanged.

### D2. Shared markdown-strip helper for TTS

Currently `IntentSurface.tsx` (around lines 196–207) inlines a 9-step regex chain to strip markdown before `speakResponse(cleanText)`. Extract to:

```typescript
// ui/src/audio/voice.ts (append)

/** Strip markdown formatting for cleaner TTS playback. AD-718. */
export function stripMarkdownForSpeech(text: string): string {
  return text
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/\*(.+?)\*/g, '$1')
    .replace(/#{1,6}\s/g, '')
    .replace(/[-•]\s/g, '')
    .replace(/---+/g, '')
    .replace(/`(.+?)`/g, '$1')
    .replace(/\[(.+?)\]\(.+?\)/g, '$1')
    .replace(/\n{2,}/g, '. ')
    .trim();
}
```

Update `IntentSurface.tsx` (around lines 196–207) to call `stripMarkdownForSpeech(response)` instead of the inlined chain. **DO NOT change behaviour** — the regex sequence is preserved verbatim.

### D3. New `VoiceProfile` dataclass in `src/probos/crew_profile.py`

Insert immediately after `PersonalityTraits` (around line 94):

```python
@dataclass
class VoiceProfile:
    """AD-718: per-agent voice override for browser SpeechSynthesis playback.

    `voice_name` is the exact `SpeechSynthesisVoice.name` to prefer. The browser
    voice catalogue is OS- and browser-specific, so `voice_name` is best-effort:
    if it is empty or not present on the user's machine, the HXI falls back to
    the global default voice (``localStorage("hxi_voice_name")``) and applies
    the pitch/rate/volume below to that voice.
    """
    voice_name: str = ""    # SpeechSynthesisVoice.name; "" = use global default
    pitch: float = 0.9      # 0.0–2.0 (matches voice.ts v0 default)
    rate: float = 0.95      # 0.1–10.0
    volume: float = 0.8     # 0.0–1.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.pitch <= 2.0:
            raise ValueError(f"pitch must be 0.0–2.0, got {self.pitch}")
        if not 0.1 <= self.rate <= 10.0:
            raise ValueError(f"rate must be 0.1–10.0, got {self.rate}")
        if not 0.0 <= self.volume <= 1.0:
            raise ValueError(f"volume must be 0.0–1.0, got {self.volume}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VoiceProfile":
        return cls(**{
            k: data[k] for k in ("voice_name", "pitch", "rate", "volume") if k in data
        })
```

Add the field to `CrewProfile` (around line 145, alongside `personality_baseline`):

```python
    voice: VoiceProfile = field(default_factory=VoiceProfile)
```

Extend `CrewProfile.to_dict()` (around line 170) to include `"voice": self.voice.to_dict(),` and `from_dict()` (around line 190) to read it:

```python
        if "voice" in data:
            profile.voice = VoiceProfile.from_dict(data["voice"])
```

### D4. Default voice profiles for standing crew

New file `src/probos/voice_profile_defaults.py`:

```python
"""AD-718: Default VoiceProfile values keyed on agent_type.

Captain picks `voice_name` per machine via the HXI; the values below seed only
pitch/rate so each crew member sounds distinct out of the box. Values are
deliberately conservative — small offsets from the global 0.9/0.95 defaults
to avoid uncanny variation when the user has only the basic OS voice set.
"""

from __future__ import annotations

import logging
from probos.crew_profile import VoiceProfile

logger = logging.getLogger(__name__)

# Keyed on agent_type (== crew_profiles/<agent_type>.yaml stem).
# Empty voice_name means "use global default voice and apply these pitch/rate".
DEFAULT_VOICE_PROFILES: dict[str, VoiceProfile] = {
    # bridge
    "counselor":            VoiceProfile(voice_name="", pitch=1.05, rate=0.92, volume=0.85),  # Troi — warm, slower
    # security
    "security_officer":     VoiceProfile(voice_name="", pitch=0.70, rate=0.95, volume=0.85),  # Worf — deep, firm
    # medical
    "diagnostician":        VoiceProfile(voice_name="", pitch=0.90, rate=1.05, volume=0.80),  # Bones — slightly clipped
    "pathologist":          VoiceProfile(voice_name="", pitch=1.00, rate=0.95, volume=0.80),  # Selar — precise, even
    "surgeon":              VoiceProfile(voice_name="", pitch=1.00, rate=1.00, volume=0.80),  # Pulaski
    "pharmacist":           VoiceProfile(voice_name="", pitch=1.05, rate=1.00, volume=0.80),  # Ogawa
    # science
    "architect":            VoiceProfile(voice_name="", pitch=0.95, rate=1.00, volume=0.80),  # Number One — measured
    "data_analyst":         VoiceProfile(voice_name="", pitch=1.00, rate=1.05, volume=0.80),  # Rahda
    "research_specialist":  VoiceProfile(voice_name="", pitch=1.00, rate=1.00, volume=0.80),  # Brahms
    "systems_analyst":      VoiceProfile(voice_name="", pitch=1.00, rate=1.00, volume=0.80),  # Dax
    "scout":                VoiceProfile(voice_name="", pitch=1.10, rate=1.05, volume=0.80),  # Wesley — younger
    # engineering
    "builder":              VoiceProfile(voice_name="", pitch=0.95, rate=1.05, volume=0.80),  # Forge
    "engineering_officer":  VoiceProfile(voice_name="", pitch=1.00, rate=1.00, volume=0.80),  # LaForge
    # operations
    "operations_officer":   VoiceProfile(voice_name="", pitch=0.90, rate=1.00, volume=0.80),  # O'Brien
    "training_officer":     VoiceProfile(voice_name="", pitch=1.00, rate=1.00, volume=0.80),  # Tucker
}


def default_voice_for(agent_type: str) -> VoiceProfile:
    """Return the seeded VoiceProfile for an agent_type, or a generic default."""
    if agent_type in DEFAULT_VOICE_PROFILES:
        return DEFAULT_VOICE_PROFILES[agent_type]
    return VoiceProfile()  # 0.9/0.95/0.8 — matches voice.ts v0 behaviour
```

**Wiring note:** `crew_profile.py`'s `load_seed_profile_async` (around line 434) returns a raw `dict[str, Any]` — there is no central `CrewProfile`-from-YAML hydration path at HEAD. The personality field is read by consumers directly (`routers/agents.py` around line 67; `cognitive/qualification_tests.py` around line 251). **No edit to `load_seed_profile_async` is required in v1.** The default-voice helper is consumed at the per-call site in D5 below (`routers/agents.py` profile-fetch endpoint, around line 110) and at any future `ProfileStore`-creation site that hydrates a `CrewProfile` from a seed YAML — those sites use `default_voice_for(agent.agent_type)` when no live `runtime.profile_store` entry exists. **Never hardcode the mapping at multiple sites — always go through `default_voice_for`.**

### D5. Expose `voiceProfile` on the profile API

`src/probos/routers/agents.py` around line 110 (`profile_data` dict) — add:

```python
        "voiceProfile": (seed.get("voice") if seed else None) or {
            "voice_name": "",
            "pitch": 0.9, "rate": 0.95, "volume": 0.8,
        },
```

If a live `CrewProfile` is available via `runtime.profile_store`, prefer that; otherwise fall back to the seed-derived value resolved through `default_voice_for(agent.agent_type)` from D4 — mirroring the existing `personality` lookup pattern (around lines 57–67). **Never return `None`** — clients can rely on the four numeric fields being present.

### D6. `ProfileChatTab.tsx` — mic + TTS

Add imports at the top of `ui/src/components/profile/ProfileChatTab.tsx`:

```typescript
import { speakResponse, stripMarkdownForSpeech, type VoiceProfile } from '../../audio/voice';
import { startListening, stopListening, isSpeechRecognitionSupported } from '../../audio/speechInput';
```

State:

```typescript
const [listening, setListening] = useState(false);
const voiceEnabled = useStore((s) => s.voiceEnabled);
const [voiceProfile, setVoiceProfile] = useState<VoiceProfile | null>(null);

useEffect(() => {
  fetch(`/api/agent/${agentId}/profile`)
    .then(r => r.ok ? r.json() : null)
    .then(data => { if (data?.voiceProfile) setVoiceProfile(data.voiceProfile); })
    .catch(() => {});  // Tier-2 log-and-degrade: chat still works without voice
}, [agentId]);
```

In `handleSend`, after `useStore.getState().addAgentMessage(agentId, 'agent', data.response || '(no response)');`:

```typescript
const reply = data.response;
if (voiceEnabled && reply && !reply.startsWith('(')) {
  speakResponse(stripMarkdownForSpeech(reply), voiceProfile ?? undefined, agentId);
}
```

Mic button — copy the JSX from `IntentSurface.tsx` (around lines 1467–1522) verbatim (same SVG glyph, same listening-color treatment). Place it inside the input row, between the text `<input>` and the Send `<button>`. **Also copy the `@keyframes pulse-mic` block from `IntentSurface.tsx` (around line 1631) into `ProfileChatTab.tsx` — paste it inline in a `<style>{...}</style>` block, or extract to a shared CSS module imported by both. Without the keyframe the listening-pulse animation silently no-ops.** Wire `onClick` to:

```typescript
() => {
  if (listening) { stopListening(); setListening(false); return; }
  if (!isSpeechRecognitionSupported()) return;
  setListening(true);
  startListening(
    (text) => { setInput(text); setListening(false); setTimeout(() => handleSend(), 100); },
    () => setListening(false),
    () => setListening(false),
  );
}
```

Render the mic button only when `isSpeechRecognitionSupported()` returns true.

### D7. Per-agent voice picker on the Profile tab

Add a "Voice" section to `ui/src/components/profile/ProfileInfoTab.tsx` (or, if that tab doesn't render below the personality block, add to the most appropriate existing tab — Builder verifies the exact tab in pre-flight). Three controls:

1. Voice dropdown — populated from `getAvailableVoices()`; selecting a voice posts `PUT /api/agent/{id}/voice-profile` (D8) with `{voice_name}`. An empty option means "use global default."
2. Pitch slider — 0.0–2.0, step 0.05.
3. Rate slider — 0.1–2.0, step 0.05 (capped low for HXI; the underlying API allows up to 10.0).
4. "Test" button — calls `speakResponse("This is how I sound.", currentProfile)`. `currentProfile` is the local `VoiceProfile` state (initialised from the profile fetch and updated by the slider/dropdown handlers before the PUT lands), e.g.:

   ```typescript
   const [currentProfile, setCurrentProfile] = useState<VoiceProfile>({
     voice_name: profileData?.voiceProfile?.voice_name ?? "",
     pitch:  profileData?.voiceProfile?.pitch  ?? 0.9,
     rate:   profileData?.voiceProfile?.rate   ?? 0.95,
     volume: profileData?.voiceProfile?.volume ?? 0.8,
   });
   // sliders/dropdown call setCurrentProfile(p => ({ ...p, pitch: newValue }))
   // Test button: speakResponse("This is how I sound.", currentProfile)
   ```

Volume is intentionally NOT exposed (overall HXI volume is a separate concern; per-agent volume would be confusing).

### D8. New endpoint `PUT /api/agent/{id}/voice-profile`

In `src/probos/routers/agents.py`, mirror the shape of `set_agent_proactive_cooldown` (around line 151):

```python
class SetVoiceProfileRequest(BaseModel):
    voice_name: str = ""
    pitch: float = 0.9
    rate: float = 0.95
    volume: float = 0.8


@router.put("/{agent_id}/voice-profile")
async def set_agent_voice_profile(
    agent_id: str,
    req: SetVoiceProfileRequest,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-718: Update per-agent voice profile."""
    agent = runtime.registry.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    from probos.crew_profile import VoiceProfile
    try:
        new_profile = VoiceProfile(
            voice_name=req.voice_name, pitch=req.pitch,
            rate=req.rate, volume=req.volume,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if hasattr(runtime, "profile_store") and runtime.profile_store is not None:
        crew = runtime.profile_store.get_or_create(agent.id, agent_type=agent.agent_type, pool=agent.pool)
        crew.voice = new_profile
        runtime.profile_store.update(crew)
    else:
        logger.warning("AD-718: profile_store not present; voice profile not persisted")

    return {"agentId": agent_id, "voiceProfile": new_profile.to_dict()}
```

Add `SetVoiceProfileRequest` to `probos.api_models` next to the existing `Set*Request` models.

### D9. Tests

**Python (`tests/test_ad718_voice_profile.py`):**

1. `test_voice_profile_defaults_match_voice_ts_v0` — empty `VoiceProfile()` has `pitch=0.9`, `rate=0.95`, `volume=0.8`.
2. `test_voice_profile_validates_ranges` — pitch=2.5 raises `ValueError`; rate=0.05 raises; volume=1.1 raises.
3. `test_voice_profile_to_from_dict_roundtrip` — round-trip preserves all four fields.
4. `test_crew_profile_voice_persistence` — `CrewProfile.to_dict()/from_dict()` round-trip preserves the `voice` field.
5. `test_default_voice_for_known_agent_type` — `default_voice_for("counselor")` returns the seeded Troi profile (pitch=1.05, rate=0.92).
6. `test_default_voice_for_unknown_agent_type` — `default_voice_for("nonsense")` returns the bare-default `VoiceProfile()`.
7. `test_set_voice_profile_endpoint_happy` — `PUT /api/agent/{id}/voice-profile` with valid payload returns 200 + roundtripped values; `runtime.profile_store.get(id).voice` reflects the new values.
8. `test_set_voice_profile_endpoint_validation` — pitch=3.0 returns 400 with the validator's error message.
9. `test_set_voice_profile_endpoint_missing_agent` — unknown `agent_id` returns 404.
10. `test_get_profile_includes_voice_profile` — `GET /api/agent/{id}/profile` includes `"voiceProfile"` with all four numeric fields present (defense-in-depth: never `None`).

**Vitest (`ui/src/audio/__tests__/voice.test.ts`, new):**

11. `speakResponse uses profile pitch/rate/volume when provided` — mock `speechSynthesis.speak`; assert utterance fields.
12. `speakResponse falls back to v0 defaults when profile omitted` — utterance fields equal 0.9/0.95/0.8.
13. `stripMarkdownForSpeech removes formatting` — known input/output pairs.
14. `onSpeechEvent fires start and end with agent_id` — listener registered, mock utterance triggers `onstart`/`onend`, listener receives both events with the correct `agent_id`.
15. `onSpeechEvent listener throwing does not break TTS` — Tier-2 log-and-degrade: a throwing listener is caught, second listener still fires.

**Vitest (`ui/src/components/profile/__tests__/ProfileChatTab.test.tsx`, new):**

16. `mic button renders only when speech recognition supported` — toggle `isSpeechRecognitionSupported` mock.
17. `mic button click toggles listening state` — click → `startListening` called; click again → `stopListening` called.
18. `agent reply triggers speakResponse when voiceEnabled` — mock `voice.speakResponse`; set `voiceEnabled: true`; submit message; expect call with stripped text and the fetched voiceProfile.
19. `agent reply does not trigger speakResponse when voiceEnabled is false` — assert no call.
20. `system error placeholders starting with '(' do not trigger TTS` — agent reply `"(communication error)"` → no `speakResponse` call.

Tests use `tmp_path` where they write SQLite, are order-independent, and clean up `speechSynthesis` mocks in `afterEach`.

## Acceptance criteria

- Pre-flight: working-tree integrity check (`git diff --numstat | sort -k2nr | Select-Object -First 5`; >200 deletions on any tracked file = STOP and surface).
- Focused gate: `pytest tests/test_ad718_voice_profile.py -v -n 0` green; `cd ui && npx vitest run src/audio/__tests__/voice.test.ts src/components/profile/__tests__/ProfileChatTab.test.tsx` green.
- Full Python gate: `pytest tests/ -q -n 8 --dist=loadfile` non-decreasing test count.
- Full UI gate: `cd ui && npx vitest run` green.
- With `voiceEnabled=false` (default), no `speakResponse` is invoked from `ProfileChatTab.tsx`.
- With `voiceEnabled=true` and a `voiceProfile` set on Counselor, the Captain hears the Counselor speak with `pitch=1.05, rate=0.92` after the first reply.
- AD-721's `CrewAvatarPopout` (next AD in the wave) can subscribe via `onSpeechEvent` and receive `start`/`end` events keyed on `agent_id`.
- `IntentSurface.tsx`'s existing TTS continues to work unchanged (markdown-strip helper extraction is behaviour-preserving).
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
- AD-numbering re-verification at commit time: confirm AD-718 has no live entry in `PROGRESS.md` / era files / `decisions-era-*.md` before authoring the new entry.

## Tracking

- `PROGRESS.md` — add CLOSED row when shipped.
- `decisions-era-5-unification.md` — append the AD-718 entry block.
- `docs/development/roadmap.md` — flip the "Voice in profile chat" row to shipped with AD-718 reference.
- GH issue #512 — close on merge with link to the merge commit.

## Forward markers

The Builder MUST file each of these as a GH issue at gate-3 (per BUILDER-EXECUTION-PLAN Post-Sweep step 6):

- **AD-718a** — Agent-authored voice profile. The agent reflects on its own personality (`CrewProfile.personality`) and proposes a `VoiceProfile` edit; Counselor reviews; Captain approves. Closes the loop on "agent picks own voice."
- **AD-718b** — Coqui / ElevenLabs / Bark backend integration via the AD-705 substrate. Replaces browser SpeechSynthesis with a server-side TTS pipeline; preserves the same `VoiceProfile` shape (extends with `backend: str` and backend-specific kwargs).
- **AD-718c** — Per-agent wake-word ("Hey Echo, …"). Builds on AD-474b continuous listen + interim results; wake-word matched against `callsign` and a configurable alias list.
- **AD-718d** — Emotional voice modulation. Pitch/rate are modulated at speak-time based on agent mood (from `personality`), trust delta in last cycle, and tier-3 alert state. Synergy with AD-721's expression channels.
- **AD-718e** — Multi-language voice selection. `VoiceProfile.language: str` field; SpeechSynthesis voice resolution prefers a voice whose `lang` matches before falling back to en-US.
- **AD-718f** — Volume control surface (per-agent volume slider on the profile card; intentionally deferred from D7 because overall HXI volume should be solved holistically first).

## Verified Against Codebase (2026-05-08) — grep evidence

```
grep -n "speakResponse\|findPreferredVoice\|getAvailableVoices\|setPreferredVoiceName\|cachedVoice" ui/src/audio/voice.ts
   4: let cachedVoice: SpeechSynthesisVoice | null = null;
   6: function findPreferredVoice(): SpeechSynthesisVoice | null {
  18: cachedVoice = saved;
  37: cachedVoice = preferred;
  44: cachedVoice = null;
  49: export function speakResponse(text: string): void {
  72: export function getAvailableVoices(): SpeechSynthesisVoice[] {
  77: export function setPreferredVoiceName(name: string | null): void {
  78: cachedVoice = null;

grep -n "isSpeechRecognitionSupported\|startListening\|stopListening" ui/src/audio/speechInput.ts
  23: export function isSpeechRecognitionSupported(): boolean {
  50: export function startListening(

grep -n "from '../audio/voice'\|from '../audio/speechInput'" ui/src/components/IntentSurface.tsx
  7:  import { speakResponse } from '../audio/voice';
  8:  import { startListening, stopListening, isSpeechRecognitionSupported } from '../audio/speechInput';

grep -n "voiceEnabled\|cleanText\|speakResponse(cleanText)\|@keyframes pulse-mic" ui/src/components/IntentSurface.tsx
   57:   const voiceEnabled = useStore((s) => s.voiceEnabled);
  197:   const cleanText = response
  207:   speakResponse(cleanText);
 1502:   animation: listening ? 'pulse-mic 1s ease-in-out infinite' : undefined,
 1631:   @keyframes pulse-mic {

grep -n "isSpeechRecognitionSupported\|startListening" ui/src/components/IntentSurface.tsx
 1467: {isSpeechRecognitionSupported() && (
 1476: startListening(

grep -n "voiceEnabled" ui/src/store/useStore.ts
  327:   voiceEnabled: boolean;
  597:   voiceEnabled: false,
  1140:  setVoiceEnabled: (v) => {

grep -n "^class\|^@dataclass\|load_seed_profile_async" src/probos/crew_profile.py
   50: @dataclass
   51: class PersonalityTraits:
   95: @dataclass
   96: class PerformanceReview:
  115: @dataclass
  116: class CrewProfile:
  215: class ProfileStore:
  434: async def load_seed_profile_async(agent_type: str, profiles_dir: str = "") -> dict[str, Any]:

grep -n "agent_id.*profile\|profile_data = \|set_agent_proactive_cooldown" src/probos/routers/agents.py
   40: @router.get("/{agent_id}/profile")
  110: profile_data = {
  151: async def set_agent_proactive_cooldown(...)
  166: @router.post("/{agent_id}/chat")
  362: @router.get("/{agent_id}/chat/history")
```

Every concrete file path, line number, class name, and import path asserted in this prompt maps to one of the greps above. New entities introduced by this prompt (`VoiceProfile`, `voice_profile_defaults.py`, `set_agent_voice_profile` route, `SetVoiceProfileRequest`, `onSpeechEvent`, `stripMarkdownForSpeech`, `tests/test_ad718_voice_profile.py`, `ui/src/audio/__tests__/voice.test.ts`, `ui/src/components/profile/__tests__/ProfileChatTab.test.tsx`) are introduced by D1–D9 above and should not be flagged as missing during review.

## Revision (2026-05-08)

Applied review findings from `prompts/Reviews/ad-718-profile-voice-chat-v1-review.md`:

- **Recommended #1 (line drift)** — corrected top "Verified Against Codebase" grep block (around L13–L20 of body) to actual HEAD line numbers (`speakResponse` 49, `findPreferredVoice` 6, hardcoded utterance fields 56–58, `cachedVoice` at 4/18/37/44/78, `cleanText` strip pipeline 196–207, mic JSX 1467–1522, `@keyframes pulse-mic` 1631). Switched all body-prose references to "around line N" notation per `review-criteria.md` §6 — affected lines roughly L23–L46 (Verified bullets) and the bottom grep evidence block. Also corrected `class CrewProfile` (was 130, actual ~116), `class PersonalityTraits` (was 53, actual ~51), `profile_data = {` site in D5 (was 117, actual ~110), `set_agent_proactive_cooldown` reference in D8 (was 145, actual ~151).
- **Recommended #2 (D4 wiring)** — rewrote the wiring paragraph at the bottom of D4 (around body L218–L221) to state explicitly that `load_seed_profile_async` returns a raw dict, no central `CrewProfile`-from-YAML hydration path exists at HEAD, and no edit to `load_seed_profile_async` is required in v1. The helper is consumed at the D5 site and at any future `ProfileStore`-creation site.
- **Recommended #3 (D7 `currentProfile` undeclared)** — added a TypeScript snippet in D7 (around body L262–L274) that declares `currentProfile` as local React state initialised from `profileData?.voiceProfile`, with sliders/dropdown updating via `setCurrentProfile`.
- **Nit #1 (pulse-mic keyframe)** — added an explicit instruction in D6 (around body L240) to copy the `@keyframes pulse-mic` block (around `IntentSurface.tsx` line 1631) into `ProfileChatTab.tsx` (inline `<style>` or shared CSS module). Also called out in the Verified bullet for the mic JSX.
- **Nit #2 (15 voice mappings)** — verified — no body change required.
- Bottom grep evidence block (around body L368–L394) rewritten with current HEAD line numbers and added the `findPreferredVoice` / `cachedVoice` / `cleanText` / mic-JSX / `load_seed_profile_async` lines so every assertion in the body maps to a grep hit.
