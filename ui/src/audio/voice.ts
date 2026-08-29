/* Voice output — browser SpeechSynthesis (zero dependencies) */

import { applyEmotionalModulation } from './voiceModulation';
import { deriveAgentSignals } from '../components/profile/avatarSignals';
import { useStore } from '../store/useStore';
import { injectLipSyncFrames } from './useLipSyncCapture';
import { splitIntoSentences, runSentenceQueue } from './voiceChunking';
import {
  speechQueueState,
  type SpeechClass,
  type SpeechQueueEntry,
  type SpeechQueueState,
} from './speechQueueStore';

export type { SpeechClass } from './speechQueueStore';

/** AD-1291 (was BF-764's `SPEECH_JOIN_TIMEOUT_MS`, moved here with the queue).
 *  Ceiling on how long the arbiter waits for one entry's terminal 'end' before
 *  moving on. It must never fire on a legitimate utterance -- doing so would
 *  reintroduce the overlap this fixes -- so it is generous. Its only job is to
 *  stop a lost 'end' from wedging every later entry, because a silent queue is
 *  a worse defect than the clipped audio being fixed. Exported so the component
 *  and its tests read ONE constant rather than two that can drift apart. */
export const SPEECH_JOIN_TIMEOUT_MS = 45000;

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
/** AD-1291: 'dropped' is ADDITIVE. Every existing consumer filters on `type`
 *  with `===` / `!==`, so the new variant is inert to all nine of them. It is
 *  deliberately NOT folded into 'end': the BF-764 drain, BF-290 and the AD-921
 *  meeting sequencer all read 'end' as "audio finished", and a dropped
 *  utterance never started. */
export type SpeechEventType = 'start' | 'end' | 'boundary' | 'dropped';
export type SpeechEventSource = 'server' | 'browser';
export interface SpeechEvent {
  type: SpeechEventType;
  agent_id?: string;     // present iff caller passed one to speakResponse
  utterance: SpeechSynthesisUtterance;
  /** AD-1291: why a 'dropped' event fired. Absent on every other type. A drop
   *  the Captain's tooling cannot observe is the failure this field prevents. */
  reason?: string;
  /** BF-293: which TTS path produced this event. Defaults to 'browser' for
   *  back-compat with any listener that didn't read this field. */
  source?: SpeechEventSource;
  /** BF-767: identity of the ``speakResponse`` call that produced this event
   *  (its AD-1071 generation token, also returned by ``speakResponse``). A
   *  consumer that must know whether an 'end' belongs to ITS utterance has to
   *  compare this, not ``agent_id``: superseding an utterance emits a terminal
   *  'end' carrying the SAME agent_id as the reply that replaced it.
   *  Granularity is per ``speakResponse`` CALL — under AD-1071 sentence
   *  pipelining (default-off) every sentence of one reply shares this id.
   *  Absent only on events from a build/mock that predates this field. */
  utterance_id?: number;
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
type TtsStatus = { enabled: boolean; backend: 'browser' | 'piper' | string; sentence_pipelining_enabled: boolean };
let _ttsStatus: TtsStatus | null = null;
let _ttsStatusInflight: Promise<TtsStatus | null> | null = null;

async function _fetchTtsStatus(): Promise<TtsStatus | null> {
  if (_ttsStatus !== null) return _ttsStatus;
  if (_ttsStatusInflight !== null) return _ttsStatusInflight;
  _ttsStatusInflight = (async () => {
    try {
      const resp = await fetch('/api/avatars/tts/status', { method: 'GET' });
      if (!resp.ok) {
        _ttsStatus = { enabled: false, backend: 'browser', sentence_pipelining_enabled: false };
        return _ttsStatus;
      }
      const data = await resp.json();
      _ttsStatus = {
        enabled: !!(data && data.enabled),
        backend: (data && typeof data.backend === 'string') ? data.backend : 'browser',
        // AD-1071: default-OFF when the field is absent (older runtime).
        sentence_pipelining_enabled: !!(data && data.sentence_pipelining_enabled),
      };
      return _ttsStatus;
    } catch {
      _ttsStatus = { enabled: false, backend: 'browser', sentence_pipelining_enabled: false };
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
  _activeUtteranceId = null;
}

/** AD-738: track the active <audio> so a second speakResponse cancels the first. */
let _activeAudio: HTMLAudioElement | null = null;

/** AD-1071: monotonic generation token. Each speakResponse call bumps it; the
 *  sentence-pipelining queue stops as soon as its captured generation is stale,
 *  so a newer reply cancels the in-flight one cleanly. Byte-identical for the
 *  default single-call path, which never reads it.
 *  BF-767: the same token is now PUBLISHED as ``SpeechEvent.utterance_id`` and
 *  returned by ``speakResponse``, so a consumer can tell its own utterance's
 *  'end' from the superseded one's. Read-only reuse — the pipelining predicate
 *  is unchanged. */
let _speakGeneration = 0;

/** AD-1291: the id of the entry that currently OWNS the device, or null when
 *  nothing is playing. Distinct from `_speakGeneration`, which now advances at
 *  ENQUEUE and so no longer answers "is this utterance still current". */
let _activeUtteranceId: number | null = null;

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

/** BF-767: returns the utterance id this call will stamp on its own
 *  ``SpeechEvent``s, or ``undefined`` when no TTS engine exists at all and
 *  nothing will ever be spoken.
 *
 *  AD-1291 (BF-858): this is now an ENQUEUE. Seven producers share one audio
 *  device and used to cancel one another on arrival; because voice.ts emits the
 *  terminal 'end' carrying the SUPERSEDED id (BF-767) and the BF-764 drain
 *  correlates on exactly that id, a foreign cancel did not merely truncate the
 *  current utterance -- it RESOLVED the drain and advanced it, launching the
 *  next utterance on top of the interloper. A mutual-cancellation cascade, with
 *  BF-764's own correlation guard as the propagation mechanism.
 *
 *  The contract that keeps every existing consumer working:
 *
 *      id at enqueue, audio at dispatch, events at audio.
 *
 *  The id is still minted and returned SYNCHRONOUSLY, because the BF-764 drain
 *  and BF-290 both capture it and correlate before awaiting. `'start'`/`'end'`
 *  still fire only when audio actually plays, because `wakeWord` and the BF-300
 *  PTT gate use them to gate the MICROPHONE -- emitting 'start' at enqueue time
 *  would mute the Captain while the room is silent. And `undefined` still means
 *  only "no engine exists"; a queued utterance returns a real id. */
export function speakResponse(
  text: string,
  profile?: VoiceProfile,
  agent_id?: string,
  emotion?: string,
  speechClass: SpeechClass = 'narration',
): number | undefined {
  if (!('speechSynthesis' in window) && typeof Audio !== 'function') return undefined;

  const id = ++_speakGeneration;
  const state = speechQueueState();

  // The ONLY non-FIFO rule, and it reads a caller-DECLARED class rather than
  // anything about the text: interactive pre-empts narration, FIFO within a
  // class. A narration is by construction narrating text already on screen, so
  // dropping it loses the audio rendition and not the content -- and speaking
  // it AFTER the live turn would narrate stale text as though it were current,
  // which actively misleads about ordering. An interactive utterance is never
  // dropped BY PRE-EMPTION, because nothing else carries it. `flushSpeechQueue`
  // (barge-in, unmount) still clears either class -- that is the Captain or the
  // UI saying stop, not the arbiter ranking utterances -- and every drop on
  // every path fires an observable `dropped` event.
  if (speechClass === 'interactive') {
    for (let i = state.entries.length - 1; i >= 0; i -= 1) {
      const queued = state.entries[i];
      if (queued.speechClass === 'narration' && queued.started === false) {
        state.entries.splice(i, 1);
        _fireDropped(queued, 'preempted-by-interactive');
      }
    }
  }

  state.entries.push({ id, text, profile, agent_id, emotion, speechClass, started: false });
  // Synchronous up to its first real await, so `_playNow` still runs inside
  // this call on an idle queue -- the pre-AD-738 synchronous side-effect
  // contract that callers and tests depend on.
  void _drainSpeechQueue();
  return id;
}

/** AD-1291: every drop is observable. A drop the Captain's tooling cannot see
 *  is the failure mode the `dropped` event exists to prevent. There is no real
 *  `SpeechSynthesisUtterance` for something that never reached the device, so
 *  this carries the text and nothing else -- the same shape the BF-767
 *  no-engine path already emits. */
function _fireDropped(entry: SpeechQueueEntry, reason: string): void {
  _fire({
    type: 'dropped',
    agent_id: entry.agent_id,
    utterance: { text: entry.text } as unknown as SpeechSynthesisUtterance,
    reason,
    utterance_id: entry.id,
  });
}

/** AD-1291: play entries one at a time, awaiting each terminal 'end' before
 *  dispatching the next. Re-entrant-safe: a second caller sees `draining` and
 *  returns, because the running loop picks up whatever it enqueued. */
async function _drainSpeechQueue(): Promise<void> {
  const state = speechQueueState();
  if (state.draining) return;
  state.draining = true;
  try {
    for (;;) {
      if (state.abandoned) return;
      const entry = state.entries[0];
      if (entry === undefined) return;
      entry.started = true;
      await _awaitEntry(state, entry);
      // Re-locate rather than shift(): a flush may have spliced entries out
      // from under us while this one was in flight.
      const index = state.entries.indexOf(entry);
      if (index !== -1) state.entries.splice(index, 1);
    }
  } finally {
    state.draining = false;
  }
}

/** AD-1291: dispatch ONE entry and resolve when its terminal 'end' arrives.
 *  Carries both BF-764 guards verbatim in intent -- a wedged queue turns an
 *  audio-quality defect into a silence defect, which is strictly worse than
 *  the overlap being fixed. */
function _awaitEntry(state: SpeechQueueState, entry: SpeechQueueEntry): Promise<void> {
  return new Promise<void>((resolve) => {
    let settled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const done = (): void => {
      if (settled) return;
      settled = true;
      if (timer !== undefined) clearTimeout(timer);
      if (state.settleActive === done) state.settleActive = null;
      // Deliberately does NOT clear `_activeUtteranceId`. Under AD-1071
      // pipelining every SENTENCE of one reply fires an 'end' carrying the
      // reply's shared id (BF-767), so clearing it here made the first
      // sentence's 'end' fail `runSentenceQueue`'s shouldContinue and silence
      // the rest of the reply. The token is handed over by the next
      // `_playNow` and cleared by `stopSpeaking`; a finished entry's id can
      // never be re-matched because ids are monotonic.
      try { unsub(); } catch { /* Tier-2 */ }
      resolve();
    };
    // Subscribe BEFORE dispatching: the browser path fires its terminal 'end'
    // synchronously, and a listener armed afterwards would miss it and wait out
    // the join timeout. BF-767 measured that exact ordering.
    const unsub = onSpeechEvent((event) => {
      if (event.type !== 'end') return;
      if (event.utterance_id !== entry.id) return;
      done();
    });
    state.settleActive = done;
    // GUARD 1: no engine on this path, so nothing will ever emit an 'end'.
    // Without this the queue wedges on entry one (the BF-290 shape).
    if (!_playNow(entry)) { done(); return; }
    // GUARD 2: a lost 'end' must not strand every later entry. Skipped when the
    // dispatch already settled synchronously, so a normal fast path arms no
    // timer at all.
    if (!settled) timer = setTimeout(done, SPEECH_JOIN_TIMEOUT_MS);
  });
}

/** AD-1291: drop every queued-but-unstarted entry, each with an observable
 *  reason. The IN-FLIGHT entry is deliberately left alone -- stopping audio is
 *  `stopSpeaking`'s job, and its consumers must still receive that utterance's
 *  terminal 'end'.
 *
 *  `agentId` scopes the flush to one surface: an unmounting tab must drop its
 *  OWN backlog without silencing whatever another surface is queueing. */
export function flushSpeechQueue(reason: string, agentId?: string): void {
  const state = speechQueueState();
  for (let i = state.entries.length - 1; i >= 0; i -= 1) {
    const entry = state.entries[i];
    if (entry.started) continue;
    if (agentId !== undefined && entry.agent_id !== agentId) continue;
    state.entries.splice(i, 1);
    _fireDropped(entry, reason);
  }
}

/** AD-1291: the device work for ONE entry, extracted from the old
 *  `speakResponse` body unchanged apart from taking its id rather than minting
 *  one. Returns false when no engine exists on this path, which is GUARD 1's
 *  signal that no 'end' is ever coming. */
function _playNow(entry: SpeechQueueEntry): boolean {
  const { text, profile, agent_id, emotion } = entry;
  const utterance_id = entry.id;
  // Re-checked at DISPATCH, not just at enqueue: the queue introduces a gap in
  // which the engine can disappear, and this is the boundary that must not
  // assume the enqueue-time check still holds.
  if (!('speechSynthesis' in window) && typeof Audio !== 'function') return false;

  // Cancel any in-flight audio from a prior call (server path or browser path).
  // The arbiter has normally already awaited the previous entry's 'end', so
  // this is a no-op; it still matters when GUARD 2 fired, or when something
  // outside the arbiter (barge-in) left audio playing.
  if ('speechSynthesis' in window) {
    speechSynthesis.cancel();
  }
  if (_activeAudio !== null) {
    try { _activeAudio.pause(); } catch { /* ignore */ }
    _activeAudio = null;
  }

  // AD-1071 / AD-1291: the pipelining predicate asks "do I still own the
  // device", not "is my id the newest". Under the arbiter `_speakGeneration`
  // advances at ENQUEUE, so the old `myGen === _speakGeneration` test would
  // have let a merely QUEUED reply truncate the sentence queue of the one
  // actually playing.
  _activeUtteranceId = utterance_id;

  // Fast synchronous path: if fetch is unavailable OR the cached probe
  // already says "not piper", run the browser fallback synchronously.
  if (typeof (globalThis as any).fetch !== 'function') {
    _ttsStatus = { enabled: false, backend: 'browser', sentence_pipelining_enabled: false };
    _speakBrowserFallback(text, profile, agent_id, utterance_id);
    return true;
  }
  if (_ttsStatus !== null && (!_ttsStatus.enabled || _ttsStatus.backend !== 'piper')) {
    _speakBrowserFallback(text, profile, agent_id, utterance_id);
    return true;
  }

  void (async () => {
    // ZERO-HTTP guarantee for default config (Captain decision #9):
    // probe once, cache, and skip the POST entirely when backend != "piper".
    const status = await _fetchTtsStatus();
    if (status === null || !status.enabled || status.backend !== 'piper') {
      _speakBrowserFallback(text, profile, agent_id, utterance_id);
      return;
    }
    // AD-1071: sentence-chunked pipelining (DEFAULT-OFF). When enabled AND the
    // reply has >1 sentence, synthesize + play sentences SEQUENTIALLY so the
    // first audio starts after only the FIRST sentence is synthesized (cutting
    // time-to-first-audio). When OFF (default) OR single-sentence, fall through
    // to the byte-identical single-call path below.
    if (status.sentence_pipelining_enabled) {
      const sentences = splitIntoSentences(text);
      if (sentences.length > 1) {
        await runSentenceQueue(
          sentences,
          (sentence) => _synthesizeAndPlay(sentence, profile, agent_id, emotion, utterance_id),
          () => _activeUtteranceId === utterance_id,
        );
        return;
      }
    }
    // Single-call path (default): one TTS POST for the whole reply.
    await _synthesizeAndPlay(text, profile, agent_id, emotion, utterance_id);
  })();
  return true;
}

/** AD-738 / AD-1071: synthesize ONE utterance via the server Piper backend,
 *  play it, and resolve when playback ENDS — so the AD-1071 sentence queue can
 *  advance to the next sentence. Each call injects its own visemes for lip-sync.
 *  Honest-degrade: on any failure it falls back to the browser path for THIS
 *  utterance and resolves so the caller's queue keeps going. Used by BOTH the
 *  default single-call path (full reply) and the pipelined path (per sentence),
 *  so the default path stays byte-identical. */
async function _synthesizeAndPlay(
  text: string,
  profile: VoiceProfile | undefined,
  agent_id: string | undefined,
  emotion: string | undefined,
  utterance_id: number,
): Promise<void> {
  try {
    // AD-738e-1: pass v1 emotion name (resolved server-side) so the TTS
    // endpoint can apply per-emotion prosody. Omit when undefined — server
    // falls back to defaults. BF-291 / AD-738f: pass per-agent voice_name
    // when set; server resolves against tools/piper/voices/ and falls back
    // to the configured tts.voice_model on miss.
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
      _speakBrowserFallback(text, profile, agent_id, utterance_id);
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
      _speakBrowserFallback(text, profile, agent_id, utterance_id);
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
    await new Promise<void>((resolve) => {
      let _settled = false;
      // BF-655: fireEnd=false is now used ONLY by the play()-reject path below,
      // where the 'play' event never fired so no 'start' was emitted — firing
      // no 'end' there keeps start/end balanced. Every path that DID emit
      // 'start' (ended / error / pause) fires exactly one terminal 'end'.
      const _finish = (fireEnd: boolean) => {
        if (_settled) return;
        _settled = true;
        if (_activeAudio === audio) _activeAudio = null;
        if (fireEnd) _fire({ type: 'end', agent_id, utterance: synth, source: 'server', utterance_id });
        resolve();
      };
      audio.addEventListener('play', () => _fire({ type: 'start', agent_id, utterance: synth, source: 'server', utterance_id }));
      audio.addEventListener('ended', () => _finish(true));
      audio.addEventListener('error', () => _finish(true));
      // BF-655 (refines AD-1071): a newer speakResponse pauses _activeAudio to
      // supersede this utterance. Fire the terminal 'end' (same agent_id,
      // source:'server') — the old utterance is genuinely over, so the
      // modulation icon, avatar head-bob, and PTT gate MUST reset. This is NOT
      // a spurious 'end' (a spurious end would cut a still-playing utterance;
      // pause never does that here). The _settled guard above makes this a
      // no-op if 'ended'/'error' already ran, so there is no double-'end'. The
      // AD-1071 pipelined queue still stops via the _speakGeneration token (not
      // this event), and _finish still resolve()s, so the queue advances/stops
      // exactly as before.
      audio.addEventListener('pause', () => _finish(true));
      // AD-738: feed visemes directly to useLipSyncCapture via the injection setter.
      if (Array.isArray(data.visemes) && data.visemes.length > 0) {
        try {
          injectLipSyncFrames(data.visemes, agent_id);
        } catch {
          // ignore — visemes are best-effort
        }
      }
      audio.play().then(undefined, () => {
        // play() rejected — fall back to browser for THIS utterance, resolve.
        if (_activeAudio === audio) _activeAudio = null;
        _speakBrowserFallback(text, profile, agent_id, utterance_id);
        _finish(false);
      });
    });
  } catch {
    _invalidateTtsStatus();
    _speakBrowserFallback(text, profile, agent_id, utterance_id);
  }
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
  utterance_id?: number,
): void {
  if (!('speechSynthesis' in window)) {
    // BF-767 (review): this path used to return in silence, and the caller had
    // already been handed an ``utterance_id``. Correlating on that id turned a
    // silent no-op into a turn that waits forever -- before the id existed a
    // stray same-agent ``end`` could still unstick it, so narrowing the match
    // narrowed the rescue too. An id is a promise that an ``end`` follows, so
    // pay it here rather than leave the promise unkept.
    //
    // Reachable when ``speechSynthesis`` is absent but ``Audio`` is present:
    // ``speakResponse``'s own guard proceeds if EITHER exists. I could not
    // reproduce that browser shape -- the control in my probe failed, so I am
    // not claiming a measurement -- but the contract is wrong either way and
    // this makes it true on every path, sync and async alike.
    // ``utterance`` is required on SpeechEvent and there is no engine to build
    // a real one from, so this carries the text and nothing else. Every
    // in-tree listener reads ``type`` / ``agent_id`` / ``utterance_id``;
    // ``useLipSyncCapture`` and ``wakeWord`` act on 'end' by stopping and by
    // re-arming the mic, which is correct here -- nothing is going to play.
    _fire({
      type: 'end',
      agent_id,
      utterance: { text } as unknown as SpeechSynthesisUtterance,
      source: 'browser',
      utterance_id,
    });
    return;
  }
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
  utterance.onstart = () => _fire({ type: 'start', agent_id, utterance, source: 'browser', utterance_id });
  // BF-655: onend and onerror share a single-settle guard so exactly one
  // terminal 'end' fires, whichever resolves first. speechSynthesis.cancel()
  // (a newer reply superseding this one) makes many browsers fire onerror
  // ('interrupted' / 'canceled'), NOT onend — without this the PTT gate,
  // modulation icon, and head-bob would latch forever. General onend flakiness
  // (long text, backgrounded tab) is the same class.
  let _ended = false;
  const _fireBrowserEnd = () => {
    if (_ended) return;
    _ended = true;
    _fire({ type: 'end', agent_id, utterance, source: 'browser', utterance_id });
  };
  utterance.onend = _fireBrowserEnd;
  utterance.onerror = _fireBrowserEnd;
  // 'boundary' reserved for AD-721b phoneme work; not wired in v1.
  speechSynthesis.speak(utterance);
}

/** AD-1291: stopping the current utterance must ALSO empty the backlog.
 *
 *  This is a regression the arbiter would otherwise introduce, in the seam
 *  between the new queue and an existing consumer. Before the queue, barge-in
 *  stopped the utterance and nothing followed it. With a queue, cancelling the
 *  current one would immediately dispatch the next -- so the Captain gets
 *  talked over by a backlog at the exact moment they try to speak.
 *
 *  Wired here rather than at each caller on purpose: every barge-in path
 *  already funnels through this function (`conversationController`'s
 *  `_onVadSpeechStart` calls it via `_stopSpeaking`), so one seam covers them
 *  all and no future caller can forget it. `wakeWord.ts` needs no change -- its
 *  speech subscription only sets the `_bargedIn` suppression flag and never
 *  cancels anything. */
export function stopSpeaking(): void {
  flushSpeechQueue('barge-in');
  // Also ends any AD-1071 sentence queue still feeding the device: without
  // this, cancelling the current utterance would let its remaining sentences
  // keep synthesizing over the Captain.
  _activeUtteranceId = null;
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
