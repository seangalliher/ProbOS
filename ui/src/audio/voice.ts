/* Voice output — browser SpeechSynthesis (zero dependencies) */

import { applyEmotionalModulation } from './voiceModulation';
import { deriveAgentSignals } from '../components/profile/avatarSignals';
import { useStore } from '../store/useStore';

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
 *  so AD-721 can route mouth animation to the right avatar. */
export function speakResponse(
  text: string,
  profile?: VoiceProfile,
  agent_id?: string,
): void {
  if (!('speechSynthesis' in window)) return;

  // Cancel any ongoing speech
  speechSynthesis.cancel();

  const utterance = new SpeechSynthesisUtterance(text);

  // AD-718d: when an agent_id is supplied, modulate pitch/rate/volume
  // from the live AgentSignals selector. Tier-2 log-and-degrade — any
  // signals-read failure falls back to the unmodulated baseline; speech
  // must NEVER fail because of modulation.
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
      // fall through with unmodulated profile
    }
  }

  utterance.rate   = effective.rate   ?? 0.95;
  utterance.pitch  = effective.pitch  ?? 0.9;
  utterance.volume = effective.volume ?? 0.8;

  const named = profile?.voice_name ? _resolveVoiceByName(profile.voice_name) : null;
  const voice = named ?? findPreferredVoice();
  if (voice) utterance.voice = voice;

  utterance.onstart = () => _fire({ type: 'start', agent_id, utterance });
  utterance.onend   = () => _fire({ type: 'end',   agent_id, utterance });
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
