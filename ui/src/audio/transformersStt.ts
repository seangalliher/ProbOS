/**
 * BF-301 (#775) — transformers.js Whisper STT consumer.
 *
 * Replaces the AD-705a whisper.cpp WASM path (abandoned upstream — HF tag
 * deleted, CDN dead, npm package incomplete). Uses ``@huggingface/transformers``
 * v3 ``pipeline('automatic-speech-recognition', 'Xenova/whisper-tiny.en')``
 * running inside a dedicated Web Worker for thread isolation. Browser
 * Cache API persists model shards on first use; subsequent loads hit cache.
 *
 * No-argument APIs retain a shared legacy capture domain. ProfileChatTab
 * passes one fresh optional scope through arm and subscriptions so each
 * explicit capture owns its PCM window, worker jobs and delivery lifetime.
 *
 * New surface vs. AD-705a: ``onTransformersProgress(handler)`` exposes
 * the first-load download status so the UI can render a progress bar
 * during initial model fetch.
 *
 * Privacy invariant (AD-733c-7 extended, AD-705a load-bearing): audio
 * bytes NEVER leave the browser via this module. The model fetch
 * traffic is HF CDN ↔ browser for ONNX weights only — never operator
 * audio. The transcript STRING is the sole output crossing the wire.
 *
 * Honest-degrade paths:
 *   - Worker model fetch fails → ``{status: 'error'}`` progress event;
 *     no transcripts emitted; ProfileChatTab cancels its owned local
 *     capture and returns to idle without inventing recognized text.
 *   - VAD subscription absent → arm() succeeds idempotently; no frames
 *     collected; no transcripts emitted.
 */
import {
  subscribePcm,
  type PcmTapHandler,
} from './voiceActivity';

const SAMPLE_RATE = 16000;
// Hard ceiling on collected audio per utterance — guards against a
// missed speech_end signal eating unbounded memory. ~30 s of 16 kHz
// f32 mono = ~1.9 MB. Matches whisperStt.ts.
const MAX_UTTERANCE_SAMPLES = SAMPLE_RATE * 30;
// BF-310: pre-roll buffer length. The VAD's minSpeechMs=400 ms means
// onSpeechStart fires ~400 ms AFTER speech actually began — without a
// pre-roll, whisper sees audio that starts mid-word and routinely
// hallucinates ("Testing" → "as retail"). Keep a 600 ms rolling
// pre-buffer at all times; prepend it to the utterance when
// speech_start fires so whisper gets the word onset.
const PREROLL_SAMPLES = Math.floor(SAMPLE_RATE * 0.6);

const DEFAULT_MODEL = 'Xenova/whisper-tiny.en';

export interface TransformersProgressEvent {
  status: 'initiate' | 'download' | 'progress' | 'done' | 'ready' | 'error';
  name?: string;
  file?: string;
  loaded?: number;
  total?: number;
  progress?: number;
}

type TranscriptListener = (text: string) => void;
type TranscribingListener = (active: boolean) => void;
type ProgressListener = (event: TransformersProgressEvent) => void;

export type TransformersCaptureScope = symbol;

export interface TransformersJobIdentity {
  readonly captureId: string;
  readonly jobId: string;
}

export interface TransformersTranscribeRequest extends TransformersJobIdentity {
  readonly type: 'transcribe';
  readonly samples: Float32Array;
  readonly sampleRate: number;
}

export type TransformersJobEvent = TransformersJobIdentity & {
  readonly sequence: number;
} & (
  | { type: 'transcript'; text: string; isPartial: boolean }
  | { type: 'transcribing'; active: boolean }
  | { type: 'complete'; outcome: 'success' | 'error' }
);

interface Registration<Value> {
  scope: TransformersCaptureScope | undefined;
  owner: Engaged | null;
  listener: ((value: Value) => void) | null;
  jobs: Set<string>;
  processing: boolean;
}

interface Engaged {
  readonly captureId: string;
  readonly scope: TransformersCaptureScope | undefined;
  active: boolean;
  speaking: boolean;
  unsubscribe: () => void;
  ringBuffers: Float32Array[];
  ringSampleCount: number;
  preroll: Float32Array[];
  prerollCount: number;
  jobs: Set<string>;
}

interface WorkerSession {
  readonly worker: Worker;
  detach: () => void;
}

interface PendingJob {
  readonly session: WorkerSession;
  readonly owner: Engaged;
  readonly jobId: string;
  sequence: number;
  final: boolean;
  transcripts: Set<Registration<string>>;
  processing: Set<Registration<boolean>>;
}

let _session: WorkerSession | null = null;
let _nextIdentity = 0;
const _captures = new Map<TransformersCaptureScope | undefined, Engaged>();
const _jobs = new Map<string, PendingJob>();
const _transcriptListeners = new Set<Registration<string>>();
const _transcribingListeners = new Set<Registration<boolean>>();
const _progressListeners: Set<ProgressListener> = new Set();
const _retiringWorkers = new Map<Worker, ReturnType<typeof setTimeout>>();
let _workerOverride: (() => Worker) | null = null;
let _model = DEFAULT_MODEL;

/**
 * Test seam — vitest stubs the Worker boundary with a MessageChannel-
 * backed fake. Production code MUST NOT import ``Worker`` from anywhere
 * mockable; this is the only injection point.
 */
export function _setTransformersWorkerOverride(
  factory: (() => Worker) | null,
): void {
  _workerOverride = factory;
}

/** Test seam — reset module-scoped state between tests. */
export function _resetTransformersStt(): void {
  terminateTransformersStt();
  for (const [worker, timer] of _retiringWorkers) {
    clearTimeout(timer);
    _safely(() => worker.terminate());
  }
  _retiringWorkers.clear();
  for (const registration of _transcriptListeners) _releaseRegistration(registration);
  for (const registration of _transcribingListeners) _releaseRegistration(registration);
  _transcriptListeners.clear();
  _transcribingListeners.clear();
  _progressListeners.clear();
  _workerOverride = null;
  _model = DEFAULT_MODEL;
}

/** Test seam: true while any legacy or explicitly scoped capture is armed. */
export function _isArmed(): boolean {
  return _captures.size > 0;
}

/**
 * Override the model id used on next ``armTransformersStt``. Call sites
 * may read ``voiceHealth.model`` and call this before arming to honor
 * operator-configured ``cognitive.transformers_model``.
 */
export function _setTransformersModel(model: string): void {
  if (typeof model === 'string' && model.length > 0) {
    _model = model;
  }
}

function _safely(operation: () => void): void {
  try { operation(); } catch {
    console.warn('Local STT callback or cleanup failed; other capture owners remain active.');
  }
}

function _releaseRegistration<Value>(registration: Registration<Value>): void {
  registration.listener = null;
  registration.owner = null;
  registration.jobs.clear();
  registration.processing = false;
}

function _updateProcessing(registration: Registration<boolean>): void {
  const active = registration.jobs.size > 0;
  if (!registration.listener || registration.processing === active) return;
  registration.processing = active;
  const listener = registration.listener;
  _safely(() => listener(active));
}

function _settleJob(job: PendingJob): void {
  if (_jobs.get(job.jobId) !== job) return;
  _jobs.delete(job.jobId);
  job.owner.jobs.delete(job.jobId);
  const registrations = [...job.processing];
  for (const registration of job.transcripts) registration.jobs.delete(job.jobId);
  for (const registration of registrations) registration.jobs.delete(job.jobId);
  job.transcripts.clear();
  job.processing.clear();
  for (const registration of registrations) _updateProcessing(registration);
}

function _cancelCapture(owner: Engaged): void {
  if (!owner.active) return;
  owner.active = false;
  if (_captures.get(owner.scope) === owner) _captures.delete(owner.scope);
  const unsubscribe = owner.unsubscribe;
  owner.unsubscribe = () => {};
  owner.ringBuffers = [];
  owner.ringSampleCount = 0;
  owner.preroll = [];
  owner.prerollCount = 0;
  owner.speaking = false;
  const processingCallbacks: TranscribingListener[] = [];
  if (owner.scope !== undefined) {
    for (const registration of _transcriptListeners) {
      if (registration.owner !== owner) continue;
      _transcriptListeners.delete(registration);
      _releaseRegistration(registration);
    }
    for (const registration of _transcribingListeners) {
      if (registration.owner !== owner) continue;
      if (registration.processing && registration.listener) processingCallbacks.push(registration.listener);
      _transcribingListeners.delete(registration);
      _releaseRegistration(registration);
    }
  }
  for (const jobId of [...owner.jobs]) {
    const job = _jobs.get(jobId);
    if (job) _settleJob(job);
  }
  _safely(unsubscribe);
  for (const listener of processingCallbacks) _safely(() => listener(false));
}

function _emitProgress(event: TransformersProgressEvent): void {
  for (const cb of _progressListeners) {
    try {
      cb(event);
    } catch {
      // Tier-2.
    }
  }
}

function _defaultWorkerFactory(): Worker {
  // Vite-native: `new Worker(new URL(..., import.meta.url), { type: 'module' })`.
  // Vite 6 emits an ES-module worker chunk; rollupOptions in vite.config.ts
  // colocates this with the @huggingface/transformers bundle as `stt-vendor`.
  return new Worker(
    new URL('./transformersWorker.ts', import.meta.url),
    { type: 'module' },
  );
}

function _dispatch(owner: Engaged, buffers: Float32Array[]): void {
  const session = _session;
  if (!owner.active || !session) return;
  const total = buffers.reduce((count, buffer) => count + buffer.length, 0);
  if (!total) return;
  const merged = new Float32Array(total);
  let offset = 0;
  for (const buffer of buffers) {
    merged.set(buffer, offset);
    offset += buffer.length;
  }
  const jobId = String(++_nextIdentity);
  const eligible = <Value>(registration: Registration<Value>): boolean =>
    registration.listener !== null && registration.scope === owner.scope &&
    (owner.scope === undefined || registration.owner === owner);
  const job: PendingJob = {
    session, owner, jobId, sequence: 0, final: false,
    transcripts: new Set([..._transcriptListeners].filter(eligible)),
    processing: new Set([..._transcribingListeners].filter(eligible)),
  };
  _jobs.set(jobId, job);
  owner.jobs.add(jobId);
  for (const registration of job.transcripts) registration.jobs.add(jobId);
  for (const registration of job.processing) registration.jobs.add(jobId);
  for (const registration of [...job.processing]) _updateProcessing(registration);
  if (!owner.active || _session !== session || _jobs.get(jobId) !== job) return;
  const request: TransformersTranscribeRequest = {
    type: 'transcribe', captureId: owner.captureId, jobId,
    samples: merged, sampleRate: SAMPLE_RATE,
  };
  try {
    session.worker.postMessage(request, [merged.buffer]);
  } catch {
    _settleJob(job);
    console.warn('Local STT dispatch failed; the job was settled without recognized text.');
  }
}

function _buildTapHandler(owner: Engaged): PcmTapHandler {
  return {
    onFrame(frame, sampleRate) {
      if (!owner.active || sampleRate !== SAMPLE_RATE || !(frame instanceof Float32Array) || !frame.length) return;
      if (!owner.speaking) {
        owner.preroll.push(new Float32Array(frame));
        owner.prerollCount += frame.length;
        while (owner.prerollCount > PREROLL_SAMPLES) {
          const first = owner.preroll[0];
          const excess = owner.prerollCount - PREROLL_SAMPLES;
          if (first.length <= excess) {
            owner.preroll.shift();
            owner.prerollCount -= first.length;
          } else {
            owner.preroll[0] = first.slice(excess);
            owner.prerollCount -= excess;
          }
        }
        return;
      }
      const count = Math.min(frame.length, MAX_UTTERANCE_SAMPLES - owner.ringSampleCount);
      if (!count) return;
      owner.ringBuffers.push(frame.slice(0, count));
      owner.ringSampleCount += count;
    },
    onSpeechStart() {
      if (!owner.active || owner.speaking) return;
      owner.speaking = true;
      owner.ringBuffers = owner.preroll;
      owner.ringSampleCount = owner.prerollCount;
      owner.preroll = [];
      owner.prerollCount = 0;
    },
    onSpeechEnd() {
      if (!owner.active) return;
      owner.preroll = [];
      owner.prerollCount = 0;
      if (!owner.speaking) return;
      owner.speaking = false;
      const buffers = owner.ringBuffers;
      owner.ringBuffers = [];
      owner.ringSampleCount = 0;
      _dispatch(owner, buffers);
    },
  };
}

function _isJobEvent(value: Record<string, unknown>): value is Record<string, unknown> & TransformersJobEvent {
  if (typeof value.captureId !== 'string' || !/^[A-Za-z0-9_-]{1,128}$/.test(value.captureId) ||
      typeof value.jobId !== 'string' || !/^[A-Za-z0-9_-]{1,128}$/.test(value.jobId) ||
      !Number.isSafeInteger(value.sequence) || (value.sequence as number) < 1) return false;
  return (value.type === 'transcript' && typeof value.text === 'string' && typeof value.isPartial === 'boolean') ||
    (value.type === 'transcribing' && typeof value.active === 'boolean') ||
    (value.type === 'complete' && (value.outcome === 'success' || value.outcome === 'error'));
}

function _validProgress(value: unknown): value is TransformersProgressEvent {
  if (!value || typeof value !== 'object') return false;
  const event = value as Record<string, unknown>;
  return ['initiate', 'download', 'progress', 'done', 'ready', 'error'].includes(event.status as string) &&
    ['name', 'file'].every(key => event[key] === undefined || typeof event[key] === 'string') &&
    ['loaded', 'total', 'progress'].every(key => event[key] === undefined ||
      (typeof event[key] === 'number' && Number.isFinite(event[key]) && event[key] >= 0));
}

function _failWorker(session: WorkerSession): void {
  if (_session !== session) return;
  _session = null;
  session.detach();
  const owners = [..._captures.values()];
  for (const owner of owners) _cancelCapture(owner);
  _safely(() => session.worker.terminate());
  _emitProgress({ status: 'error', name: _model, file: 'Local STT worker unavailable; explicit re-arm can retry.' });
}

function _wireWorker(session: WorkerSession): void {
  const message = (event: MessageEvent): void => {
    if (_session !== session || !event.data || typeof event.data !== 'object') return;
    const msg = event.data as Record<string, unknown>;
    if (msg.type === 'progress' && _validProgress(msg.event)) {
      _emitProgress(msg.event);
      return;
    }
    if (!_isJobEvent(msg)) return;
    const job = _jobs.get(msg.jobId);
    if (!job || job.session !== session || !job.owner.active ||
        job.owner.captureId !== msg.captureId || msg.sequence <= job.sequence) return;
    job.sequence = msg.sequence;
    if (msg.type === 'complete') {
      _settleJob(job);
    } else if (msg.type === 'transcript' && !job.final) {
      if (!msg.isPartial) job.final = true;
      if (msg.isPartial && job.owner.scope !== undefined) return;
      if (!msg.text.trim() && job.owner.scope === undefined) return;
      const recipients = [...job.transcripts].filter(registration => registration.jobs.has(job.jobId));
      for (const registration of recipients) {
        if (_session !== session) break;
        if (job.owner.scope !== undefined && (!job.owner.active || _jobs.get(job.jobId) !== job)) break;
        const listener = registration.listener;
        if (listener) _safely(() => listener(msg.text));
      }
    }
  };
  const failure = (): void => _failWorker(session);
  session.worker.addEventListener('message', message);
  session.worker.addEventListener('error', failure);
  session.worker.addEventListener('messageerror', failure);
  session.detach = () => {
    session.worker.removeEventListener('message', message);
    session.worker.removeEventListener('error', failure);
    session.worker.removeEventListener('messageerror', failure);
  };
}

/**
 * Arm the legacy domain, or the supplied optional capture scope.
 * Repeated active calls are idempotent. A scoped return cancels only its
 * captured generation; an unscoped return keeps legacy disarm semantics.
 *
 * BF-320: the Worker + whisper pipeline is created ONCE per page
 * lifetime and reused across arm/disarm cycles. Subsequent arm calls
 * only re-subscribe the PCM tap; the model stays resident.
 */
export function armTransformersStt(scope?: TransformersCaptureScope): () => void {
  if (scope !== undefined && typeof scope !== 'symbol') throw new TypeError('Capture scope must be a symbol.');
  const existing = _captures.get(scope);
  if (existing) return scope === undefined ? disarmTransformersStt : () => _cancelCapture(existing);
  const owner: Engaged = {
    captureId: String(++_nextIdentity), scope, active: true, speaking: false,
    unsubscribe: () => {}, ringBuffers: [], ringSampleCount: 0,
    preroll: [], prerollCount: 0, jobs: new Set(),
  };
  _captures.set(scope, owner);
  if (scope !== undefined) {
    for (const registration of _transcriptListeners) {
      if (registration.scope === scope && registration.owner === null) registration.owner = owner;
    }
    for (const registration of _transcribingListeners) {
      if (registration.scope === scope && registration.owner === null) registration.owner = owner;
    }
  }
  try {
    if (!_session) {
      const session: WorkerSession = { worker: (_workerOverride ?? _defaultWorkerFactory)(), detach: () => {} };
      _session = session;
      _wireWorker(session);
      try { session.worker.postMessage({ type: 'init', model: _model }); }
      catch { _failWorker(session); }
    }
    if (owner.active) {
      const unsubscribe = subscribePcm(_buildTapHandler(owner));
      if (owner.active) owner.unsubscribe = unsubscribe;
      else _safely(unsubscribe);
    }
  } catch (error) {
    _cancelCapture(owner);
    throw error;
  }
  return scope === undefined ? disarmTransformersStt : () => _cancelCapture(owner);
}

/**
 * Idempotently cancel only the legacy capture domain and its pending jobs.
 * Explicitly scoped captures and the resident worker/model remain active.
 * An accepted legacy reply still reaches its already-eligible live siblings.
 * Use terminateTransformersStt for page-level teardown of every domain.
 */
export function disarmTransformersStt(): void {
  const owner = _captures.get(undefined);
  if (owner) _cancelCapture(owner);
}

/**
 * Fence the current worker and cancel every capture domain immediately.
 * Request graceful shutdown, then terminate that exact worker after 250 ms.
 * Wired to beforeunload; a newly armed replacement is independent.
 */
export function terminateTransformersStt(): void {
  const session = _session;
  _session = null;
  session?.detach();
  for (const owner of [..._captures.values()]) _cancelCapture(owner);
  if (!session) return;
  const worker = session.worker;
  _safely(() => worker.postMessage({ type: 'shutdown' }));
  const timer = setTimeout(() => {
    _retiringWorkers.delete(worker);
    _safely(() => worker.terminate());
  }, 250);
  _retiringWorkers.set(worker, timer);
}

function _subscribe<Value>(
  registrations: Set<Registration<Value>>, listener: (value: Value) => void,
  scope?: TransformersCaptureScope, settledValue?: Value,
): () => void {
  if (typeof listener !== 'function') throw new TypeError('Capture listener must be a function.');
  if (scope !== undefined && typeof scope !== 'symbol') throw new TypeError('Capture scope must be a symbol.');
  const registration: Registration<Value> = {
    scope, listener, owner: scope === undefined ? null : _captures.get(scope) ?? null,
    jobs: new Set(), processing: false,
  };
  registrations.add(registration);
  return () => {
    registrations.delete(registration);
    for (const jobId of registration.jobs) {
      const job = _jobs.get(jobId);
      job?.transcripts.delete(registration as unknown as Registration<string>);
      job?.processing.delete(registration as unknown as Registration<boolean>);
    }
    const notify = registration.processing ? registration.listener : null;
    _releaseRegistration(registration);
    if (notify && settledValue !== undefined) _safely(() => notify(settledValue));
  };
}

/** Subscribe to future jobs in the legacy domain or one optional scope.
 * Scoped listeners receive final text only; legacy listeners retain partials.
 * Registrations never inherit an already-dispatched job. Returns unsubscribe.
 */
export function onTransformersTranscript(listener: TranscriptListener, scope?: TransformersCaptureScope): () => void {
  return _subscribe(_transcriptListeners, listener, scope);
}

/** Subscribe to pending-job state in the legacy domain or one optional scope.
 * Dispatch/completion drive this aggregate, not worker transcribing booleans.
 * Unsubscribing an active registration emits one terminal false.
 */
export function onTransformersTranscribing(listener: TranscribingListener, scope?: TransformersCaptureScope): () => void {
  return _subscribe(_transcribingListeners, listener, scope, false);
}

/**
 * Subscribe to first-load model download progress. Listeners receive
 * the transformers.js progress event shape verbatim — see the type for
 * the discriminated status field.
 */
export function onTransformersProgress(listener: ProgressListener): () => void {
  _progressListeners.add(listener);
  return () => {
    _progressListeners.delete(listener);
  };
}

// BF-320: tear down the resident worker on page unload so the model
// doesn't keep its WebGPU/wasm allocations alive past the page lifetime.
// Guarded for SSR / non-browser test environments without a real window.
if (typeof window !== 'undefined' && typeof window.addEventListener === 'function') {
  window.addEventListener('beforeunload', () => {
    try { terminateTransformersStt(); } catch { /* Tier-2 */ }
  });
}
