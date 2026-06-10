/* Voice output — browser SpeechSynthesis (zero dependencies) */

import { applyEmotionalModulation } from './voiceModulation';
import { deriveAgentSignals } from '../components/profile/avatarSignals';
import { useStore } from '../store/useStore';
import { injectLipSyncFrames } from './useLipSyncCapture';

let voicesLoaded = false;
let cachedVoice: SpeechSynthesisVoice | null = null;

/** AD-718: Per-call voice override. All fields optional. */
export interface VoiceProfile {
  voice_name?: string;   // exact SpeechSynthesisVoice name; falls back to global default if missing
  pitch?: number;        // 0.0–2.0; default 0.9 (matches v0 behaviour)
  rate?: number;         // 0.1–10.0; default 0.95 (matches v0)
  volume?: number;       // 0.0–1.0; default 0.8 (matches v0)
  /** AD-718c: optional per-agent wake phrase (≤ 50 chars). Empty = no
   *  per-agent wake; system-wide "Computer" still works via @callsign. */
  wake_phrase?: string;
  /** AD-718e: ISO 639-1 / BCP 47 short tag for the preferred language.
   *  When set, voice fallback prefers voices whose ``lang`` starts with
   *  this prefix before degrading to en. Defaults to 'en' server-side. */
  language?: string;
}

/** AD-718 / AD-721 hook: subscribers fire on every utterance lifecycle event.
/** AD-721: SpeechEvent lifecycle for TTS playback. Listeners drive avatar
 *  mouth animation, lip-sync capture, and viseme handoff.
 *  v1 emits 'start' and 'end' only; 'boundary' is reserved for AD-721b phoneme work.
 *
 *  BF-293: ``source`` distinguishes the server-streamed Piper path (visemes
 *  already injected; consumers MUST NOT re-capture or re-upload) from the
 *  browser SpeechSynthesisUtterance fallback path (no server visemes;
 *  consumers MAY capture audio for server-side rhubarb processing). */
export type SpeechEventType = 'start' | 'end' | 'boundary';
export type SpeechEventSource = 'server' | 'browser';
export interface SpeechEvent {
  type: SpeechEventType;
  agent_id?: string;     // present iff caller passed one to speakResponse
  utterance: SpeechSynthesisUtterance;
  /** BF-293: which TTS path produced this event. Defaults to 'browser' for
   *  back-compat with any listener that didn't read this field. */
  source?: SpeechEventSource;
}
type SpeechListener = (e: SpeechEvent) => void;

const _speechListeners = new Set<SpeechListener>();

/** AD-718: Subscribe to TTS playback lifecycle events. Returns unsubscribe fn. */
export function onSpeechEvent(fn: SpeechListener): () => void {
  _speechListeners.add(fn);
  return () => { _speechListeners.delete(fn); };
}

function _fire(e: SpeechEvent): void {
  // Tier-2 log-and-degrade: a buggy listener must not break TTS.
  for (const fn of _speechListeners) {
    try { fn(e); } catch (err) { console.warn('[voice] listener error', err); }
  }
}

/** AD-718: Look up a voice by exact name without mutating the global cache. */
function _resolveVoiceByName(name: string): SpeechSynthesisVoice | null {
  if (!name || !('speechSynthesis' in window)) return null;
  const v = speechSynthesis.getVoices().find(x => x.name === name);
  return v ?? null;
}

/** AD-718e: Resolve a voice that matches the profile's language prefix.
 *  Returns null when no match exists; caller then falls back to
 *  ``findPreferredVoice`` (which prefers en). Empty / undefined language
 *  returns null so the existing AD-718 behaviour is preserved. */
function _resolveVoiceByLanguage(lang: string | undefined): SpeechSynthesisVoice | null {
  if (!lang || !('speechSynthesis' in window)) return null;
  const norm = lang.toLowerCase().split(/[_-]/)[0];
  if (!norm) return null;
  const voices = speechSynthesis.getVoices();
  return voices.find(v => v.lang.toLowerCase().startsWith(norm)) ?? null;
}

function findPreferredVoice(): SpeechSynthesisVoice | null {
  if (cachedVoice) return cachedVoice;
  if (!('speechSynthesis' in window)) return null;
  const voices = speechSynthesis.getVoices();
  if (voices.length === 0) return null;
  voicesLoaded = true;

  // Check user preference first
  const savedName = localStorage.getItem('hxi_voice_name');
  if (savedName) {
    const saved = voices.find(v => v.name === savedName);
    if (saved) {
      cachedVoice = saved;
      return saved;
    }
  }

  // Auto-detect best available (Edge neural first)
  const preferred = voices.find(v =>
    v.lang.startsWith('en') && v.name.includes('Online (Natural)')
  ) || voices.find(v =>
    v.lang.startsWith('en') && v.name.includes('Online')
  ) || voices.find(v =>
    v.lang.startsWith('en') && (
      v.name.includes('Google US English') ||
      v.name.includes('Google UK English') ||
      v.name.includes('Natural') ||
      v.name.includes('Samantha')
    )
  ) || voices.find(v => v.lang.startsWith('en')) || null;

  cachedVoice = preferred;
  return preferred;
}

// Preload voices (some browsers load them async)
if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
  speechSynthesis.addEventListener('voiceschanged', () => {
    cachedVoice = null;
    findPreferredVoice();
  });
}

/** AD-718: agent_id is optional; when provided it is forwarded to listeners
 *  so AD-721 can route mouth animation to the right avatar.
 *  AD-738: try server-streamed Piper TTS first when the cached one-time
 *  status probe reports backend=piper; fall back to SpeechSynthesisUtterance
 *  on any failure. Public surface unchanged — still synchronous, still fires
 *  'start'/'end' events. Default config (backend=browser) takes the fallback
 *  path with ZERO POST traffic per utterance. */

/** AD-738: cached server-feature probe. Populated on first speakResponse call;
 *  invalidated on any non-200 response so a runtime restart with backend=piper
 *  lights up without a browser refresh. */
type TtsStatus = { enabled: boolean; backend: 'browser' | 'piper' | string };
let _ttsStatus: TtsStatus | null = null;
let _ttsStatusInflight: Promise<TtsStatus | null> | null = null;

async function _fetchTtsStatus(): Promise<TtsStatus | null> {
  if (_ttsStatus !== null) return _ttsStatus;
  if (_ttsStatusInflight !== null) return _ttsStatusInflight;
  _ttsStatusInflight = (async () => {
    try {
      const resp = await fetch('/api/avatars/tts/status', { method: 'GET' });
      if (!resp.ok) {
        _ttsStatus = { enabled: false, backend: 'browser' };
        return _ttsStatus;
      }
      const data = await resp.json();
      _ttsStatus = {
        enabled: !!(data && data.enabled),
        backend: (data && typeof data.backend === 'string') ? data.backend : 'browser',
      };
      return _ttsStatus;
    } catch {
      _ttsStatus = { enabled: false, backend: 'browser' };
      return _ttsStatus;
    } finally {
      _ttsStatusInflight = null;
    }
  })();
  return _ttsStatusInflight;
}

/** AD-738: invalidate cache on any failure during the POST path so a runtime
 *  config change (browser → piper or vice versa) is picked up without refresh. */
function _invalidateTtsStatus(): void { _ttsStatus = null; }

/** AD-972: prewarm the one-time TTS backend probe so the FIRST meeting
 *  utterance is not gated on the ``/api/avatars/tts/status`` round-trip. The
 *  probe is cached (and inflight-deduped) by ``_fetchTtsStatus``, so this is
 *  idempotent and safe to call whenever a meeting opens. Fire-and-forget;
 *  never throws. */
export function prewarmTts(): void {
  try { void _fetchTtsStatus(); } catch { /* Tier-2: prewarm is best-effort */ }
}

/** AD-738: TEST-ONLY hook to reset the module-level probe cache between tests.
 *  AD-738a (Wave 158): gated behind ``import.meta.env.MODE === 'test'``.
 *  Vitest sets MODE='test' at module load. Production builds (``vite build``)
 *  set MODE='production' so this becomes a no-op — accidental production
 *  callers cannot reset the cache and disturb the zero-HTTP-per-utterance
 *  guarantee. The function is still exported so existing test imports
 *  resolve without a binding error. */
export function _resetTtsStatusForTests(): void {
  if (import.meta.env.MODE !== 'test') return;
  _ttsStatus = null;
  _ttsStatusInflight = null;
  _activeAudio = null;
}

/** AD-738: track the active <audio> so a second speakResponse cancels the first. */
let _activeAudio: HTMLAudioElement | null = null;

/** BF-283 (2026-05-13): expose the active audio's playback position so the
 *  CrewVRM viseme sampler can anchor to the audio clock instead of wall
 *  clock. ``audio.currentTime`` already accounts for ``playbackRate``, so
 *  AD-735 volume / AD-737 emotion rate modulation never drift the visemes.
 *  Returns ``null`` when no Piper-backed audio is playing — caller falls
 *  back to its wall-clock path (used by the heuristic schedule). */
export function getActiveAudioTimeMs(): number | null {
  if (_activeAudio === null) return null;
  try {
    return _activeAudio.currentTime * 1000;
  } catch {
    return null;
  }
}

export function speakResponse(
  text: string,
  profile?: VoiceProfile,
  agent_id?: string,
  emotion?: string,
): void {
  if (!('speechSynthesis' in window) && typeof Audio !== 'function') return;

  // Cancel any in-flight audio from a prior call (server path or browser path).
  if ('speechSynthesis' in window) {
    speechSynthesis.cancel();
  }
  if (_activeAudio !== null) {
    try { _activeAudio.pause(); } catch { /* ignore */ }
    _activeAudio = null;
  }

  // Fast synchronous path: if fetch is unavailable OR the cached probe
  // already says "not piper", run the browser fallback synchronously.
  // This preserves the pre-AD-738 synchronous side-effect contract on the
  // default-config path AND avoids an async hop on every warm-cache call.
  if (typeof (globalThis as any).fetch !== 'function') {
    _ttsStatus = { enabled: false, backend: 'browser' };
    _speakBrowserFallback(text, profile, agent_id);
    return;
  }
  if (_ttsStatus !== null && (!_ttsStatus.enabled || _ttsStatus.backend !== 'piper')) {
    _speakBrowserFallback(text, profile, agent_id);
    return;
  }

  void (async () => {
    // ZERO-HTTP guarantee for default config (Captain decision #9):
    // probe once, cache, and skip the POST entirely when backend != "piper".
    const status = await _fetchTtsStatus();
    if (status === null || !status.enabled || status.backend !== 'piper') {
      _speakBrowserFallback(text, profile, agent_id);
      return;
    }
    try {
      // AD-738e-1: pass v1 emotion name (resolved server-side) so the
      // TTS endpoint can apply per-emotion prosody. Omit the field when
      // emotion is undefined — server falls back to defaults.
      // BF-291 / AD-738f: pass per-agent voice_name when set in the
      // profile. Server resolves against tools/piper/voices/ and falls
      // back to the configured tts.voice_model on miss.
      const _body: { text: string; emotion?: string; voice_name?: string } = { text };
      if (typeof emotion === 'string' && emotion.length > 0) {
        _body.emotion = emotion;
      }
      if (profile && typeof profile.voice_name === 'string' && profile.voice_name.length > 0) {
        _body.voice_name = profile.voice_name;
      }
      const resp = await fetch('/api/avatars/tts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(_body),
      });
      if (!resp.ok) {
        _invalidateTtsStatus();
        _speakBrowserFallback(text, profile, agent_id);
        return;
      }
      const data = await resp.json();
      if (
        !data ||
        data.backend === 'disabled' ||
        typeof data.audio_attachment_id !== 'string' ||
        data.audio_attachment_id.length !== 64
      ) {
        // Server flipped to disabled — invalidate so the next call re-probes.
        _invalidateTtsStatus();
        _speakBrowserFallback(text, profile, agent_id);
        return;
      }
      // Build a synthetic utterance object so existing 'start'/'end' listeners
      // (AD-718 / AD-721) keep firing the same shape. agent_id propagates.
      const synth = new SpeechSynthesisUtterance(text);
      const audio = new Audio(`/api/chat/attachments/${data.audio_attachment_id}`);
      _activeAudio = audio;
      const effective = _resolveEffectiveProfile(profile, agent_id);
      audio.volume = Math.max(0, Math.min(1, effective.volume ?? 0.8));
      audio.playbackRate = Math.max(0.25, Math.min(4.0, effective.rate ?? 0.95));
      try { (audio as any).preservesPitch = false; } catch { /* not supported */ }
      const _clearActive = () => { if (_activeAudio === audio) _activeAudio = null; };
      audio.addEventListener('play', () => _fire({ type: 'start', agent_id, utterance: synth, source: 'server' }));
      audio.addEventListener('ended', () => { _clearActive(); _fire({ type: 'end', agent_id, utterance: synth, source: 'server' }); });
      audio.addEventListener('error', () => { _clearActive(); _fire({ type: 'end', agent_id, utterance: synth, source: 'server' }); });
      // AD-738: feed visemes directly to useLipSyncCapture via the new injection setter.
      if (Array.isArray(data.visemes) && data.visemes.length > 0) {
        try {
          injectLipSyncFrames(data.visemes, agent_id);
        } catch {
          // ignore — visemes are best-effort
        }
      }
      try {
        await audio.play();
      } catch {
        _clearActive();
        _speakBrowserFallback(text, profile, agent_id);
      }
    } catch {
      _invalidateTtsStatus();
      _speakBrowserFallback(text, profile, agent_id);
    }
  })();
}

/** AD-738: factor out per-agent modulation resolution so both server and
 *  fallback paths apply AD-735 volume + AD-737 emotion modulation. */
function _resolveEffectiveProfile(
  profile: VoiceProfile | undefined,
  agent_id: string | undefined,
): VoiceProfile {
  let effective: VoiceProfile = profile ?? {};
  if (agent_id) {
    try {
      const store = useStore.getState();
      // deriveAgentSignals takes a structurally-typed slice of the store;
      // cast through unknown because HXIState's NotificationView type is
      // a wider/branded shape than the helper's structural { tier? } guard.
      const signals = deriveAgentSignals(agent_id, store as unknown as Parameters<typeof deriveAgentSignals>[1]);
      effective = applyEmotionalModulation(
        {
          voice_name: profile?.voice_name,
          pitch: profile?.pitch ?? 0.9,
          rate: profile?.rate ?? 0.95,
          volume: profile?.volume ?? 0.8,
        },
        signals,
      );
    } catch {
      /* fall through with unmodulated profile */
    }
  }
  return effective;
}

/** AD-738: fallback path — the pre-AD-738 SpeechSynthesisUtterance flow. */
function _speakBrowserFallback(
  text: string,
  profile?: VoiceProfile,
  agent_id?: string,
): void {
  if (!('speechSynthesis' in window)) return;
  const utterance = new SpeechSynthesisUtterance(text);
  const effective = _resolveEffectiveProfile(profile, agent_id);
  utterance.rate = effective.rate ?? 0.95;
  utterance.pitch = effective.pitch ?? 0.9;
  utterance.volume = effective.volume ?? 0.8;
  const named = profile?.voice_name ? _resolveVoiceByName(profile.voice_name) : null;
  // AD-718e: prefer the profile's language family over the en fallback
  // before degrading to ``findPreferredVoice`` (which still prefers en).
  const langMatch = !named ? _resolveVoiceByLanguage(profile?.language) : null;
  const voice = named ?? langMatch ?? findPreferredVoice();
  if (voice) utterance.voice = voice;
  utterance.onstart = () => _fire({ type: 'start', agent_id, utterance, source: 'browser' });
  utterance.onend = () => _fire({ type: 'end', agent_id, utterance, source: 'browser' });
  // 'boundary' reserved for AD-721b phoneme work; not wired in v1.
  speechSynthesis.speak(utterance);
}

export function stopSpeaking(): void {
  if ('speechSynthesis' in window) {
    speechSynthesis.cancel();
  }
}

export function getAvailableVoices(): SpeechSynthesisVoice[] {
  if (!('speechSynthesis' in window)) return [];
  return speechSynthesis.getVoices().filter(v => v.lang.startsWith('en'));
}

/** BF-291 / AD-738f: enumerate the server-side Piper voice catalog.
 *  Returns `{name, lang, voice, quality, size_mb}[]` when the runtime
 *  backend is `piper` and any voices are installed; returns `null`
 *  otherwise so the picker can fall back to {@link getAvailableVoices}.
 *  Tier-2 log-and-degrade — never throws. */
export interface PiperVoiceEntry {
  name: string;
  lang: string;
  voice: string;
  quality: string;
  size_mb: number;
}
export async function getServerPiperVoices(): Promise<PiperVoiceEntry[] | null> {
  if (typeof fetch !== 'function') return null;
  try {
    const resp = await fetch('/api/avatars/tts/voices', { method: 'GET' });
    if (!resp.ok) return null;
    const data = await resp.json();
    if (!data || data.backend !== 'piper') return null;
    const voices = Array.isArray(data.voices) ? data.voices : [];
    if (voices.length === 0) return null;
    return voices.filter((v: unknown): v is PiperVoiceEntry =>
      typeof v === 'object' && v !== null && typeof (v as PiperVoiceEntry).name === 'string'
    );
  } catch {
    return null;
  }
}

export function setPreferredVoiceName(name: string | null): void {
  cachedVoice = null;
  if (name) {
    localStorage.setItem('hxi_voice_name', name);
  } else {
    localStorage.removeItem('hxi_voice_name');
  }
}

export function getCurrentVoiceName(): string {
  const voice = findPreferredVoice();
  return voice?.name || 'Default';
}

/** AD-718: Strip markdown formatting for cleaner TTS playback. */
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
