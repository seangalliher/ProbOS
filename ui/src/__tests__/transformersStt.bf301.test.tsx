/** BF-301 (#775) — transformers.js STT module boundary tests.
 *
 * Tests the public surface of ``../audio/transformersStt`` against a
 * Request-derived fake replies exercise routing. The separate MessageChannel
 * harness executes the actual worker module with only ASR computation mocked.
 *
 * The ``voiceActivity`` module is mocked so we can drive PcmTapHandler
 * callbacks (onSpeechStart / onFrame / onSpeechEnd) deterministically.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MessageChannel } from 'node:worker_threads';
import type { PcmTapHandler } from '../audio/voiceActivity';
import type { TransformersTranscribeRequest } from '../audio/transformersStt';

const hoisted = vi.hoisted(() => {
  const captured: { handler: any } = { handler: null };
  const handlers = new Set<PcmTapHandler>();
  const subscribePcmMock = vi.fn((handler: any) => {
    captured.handler = handler;
    handlers.add(handler);
    return () => {
      handlers.delete(handler);
      if (captured.handler === handler) captured.handler = null;
    };
  });
  return { captured, handlers, subscribePcmMock, pipeline: vi.fn() };
});

vi.mock('../audio/voiceActivity', () => ({
  subscribePcm: hoisted.subscribePcmMock,
}));
vi.mock('@huggingface/transformers', () => ({ pipeline: hoisted.pipeline }));

import {
  armTransformersStt,
  disarmTransformersStt,
  onTransformersTranscript,
  onTransformersTranscribing,
  onTransformersProgress,
  _setTransformersWorkerOverride,
  _resetTransformersStt,
  _isArmed,
  _setTransformersModel,
  terminateTransformersStt,
} from '../audio/transformersStt';

/** Synchronous, request-derived routing fixture. */
class FakeWorker {
  static instances: FakeWorker[] = [];
  posted: any[] = [];
  terminated = false;
  listeners = new Map<string, Set<(event: MessageEvent) => void>>();

  constructor() {
    FakeWorker.instances.push(this);
  }

  postMessage(message: any, _transfer?: any[]): void {
    this.posted.push(message);
  }

  addEventListener(type: string, listener: (e: MessageEvent) => void): void {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type)!.add(listener);
  }

  removeEventListener(type: string, listener: (e: MessageEvent) => void): void {
    this.listeners.get(type)?.delete(listener);
  }

  terminate(): void {
    this.terminated = true;
  }

  /** Simulate a worker → main thread message. */
  emit(data: any, type = 'message'): void {
    const event = { data } as MessageEvent;
    for (const listener of [...this.listeners.get(type) ?? []]) listener(event);
  }

  reply(request: TransformersTranscribeRequest, sequence: number, event: Record<string, unknown>): void {
    this.emit({ captureId: request.captureId, jobId: request.jobId, sequence, ...event });
  }
}

function dispatch(handler: PcmTapHandler = hoisted.captured.handler, samples = [1, 2]): TransformersTranscribeRequest {
  const worker = FakeWorker.instances[0];
  const before = worker.posted.filter(message => message.type === 'transcribe').length;
  handler.onSpeechStart?.(0);
  handler.onFrame(new Float32Array(samples), 16000);
  handler.onSpeechEnd?.(1);
  const requests = worker.posted.filter(message => message.type === 'transcribe');
  expect(requests).toHaveLength(before + 1);
  return requests[requests.length - 1];
}

function finish(worker: FakeWorker, request: TransformersTranscribeRequest, text: string): void {
  worker.reply(request, 1, { type: 'transcript', text, isPartial: false });
  worker.reply(request, 2, { type: 'complete', outcome: 'success' });
}

beforeEach(() => {
  FakeWorker.instances = [];
  hoisted.subscribePcmMock.mockClear();
  hoisted.captured.handler = null;
  _resetTransformersStt();
  hoisted.handlers.clear();
  _setTransformersWorkerOverride(() => new FakeWorker() as unknown as Worker);
});

afterEach(() => {
  _resetTransformersStt();
  vi.useRealTimers();
});

describe('BF-301 transformersStt worker boundary', () => {
  it('armTransformersStt instantiates worker and posts init with model id', () => {
    armTransformersStt();
    expect(FakeWorker.instances).toHaveLength(1);
    const init = FakeWorker.instances[0].posted[0];
    expect(init.type).toBe('init');
    expect(init.model).toBe('Xenova/whisper-tiny.en');
    expect(_isArmed()).toBe(true);
  });

  it('PCM frames between speech_start / speech_end are concatenated and posted as transcribe', () => {
    armTransformersStt();
    const worker = FakeWorker.instances[0];
    const handler = hoisted.captured.handler;
    expect(handler).toBeTruthy();

    handler.onSpeechStart(0);
    handler.onFrame(new Float32Array([0.1, 0.2, 0.3]), 16000);
    handler.onFrame(new Float32Array([0.4, 0.5]), 16000);
    handler.onSpeechEnd(0);

    const transcribeMsg = worker.posted.find((m) => m.type === 'transcribe');
    expect(transcribeMsg).toBeTruthy();
    expect(transcribeMsg.sampleRate).toBe(16000);
    expect(Array.from(transcribeMsg.samples)).toEqual([0.1, 0.2, 0.3, 0.4, 0.5].map((v) => Math.fround(v)));
  });

  it('worker transcript message dispatches to onTransformersTranscript subscribers', () => {
    armTransformersStt();
    const worker = FakeWorker.instances[0];
    const received: string[] = [];
    onTransformersTranscript((text) => received.push(text));

    finish(worker, dispatch(), 'hello world');
    expect(received).toEqual(['hello world']);
  });

  it('worker transcribing message dispatches to onTransformersTranscribing subscribers', () => {
    armTransformersStt();
    const worker = FakeWorker.instances[0];
    const states: boolean[] = [];
    onTransformersTranscribing((active) => states.push(active));

    const request = dispatch();
    worker.reply(request, 1, { type: 'transcribing', active: true });
    worker.reply(request, 2, { type: 'transcribing', active: false });
    worker.reply(request, 3, { type: 'complete', outcome: 'success' });
    expect(states).toEqual([true, false]);
  });

  it('worker progress message dispatches to onTransformersProgress subscribers', () => {
    armTransformersStt();
    const worker = FakeWorker.instances[0];
    const events: any[] = [];
    onTransformersProgress((event) => events.push(event));

    worker.emit({
      type: 'progress',
      event: { status: 'progress', name: 'Xenova/whisper-tiny.en', progress: 0.42 },
    });
    expect(events).toHaveLength(1);
    expect(events[0].status).toBe('progress');
    expect(events[0].progress).toBe(0.42);
  });

  it('disarmTransformersStt detaches PCM tap but keeps worker resident (BF-320); re-arm reuses worker', () => {
    vi.useFakeTimers();
    armTransformersStt();
    const first = FakeWorker.instances[0];

    disarmTransformersStt();
    // BF-320: disarm no longer posts shutdown or terminates the worker.
    expect(first.posted.some((m) => m.type === 'shutdown')).toBe(false);
    expect(_isArmed()).toBe(false);

    // No grace-period terminate either — worker survives the disarm.
    vi.advanceTimersByTime(300);
    expect(first.terminated).toBe(false);

    armTransformersStt();
    // Same worker is reused — no fresh init / new instance.
    expect(FakeWorker.instances).toHaveLength(1);
    expect(_isArmed()).toBe(true);
  });

  it('_setTransformersModel propagates to next init', () => {
    _setTransformersModel('Xenova/whisper-base.en');
    armTransformersStt();
    expect(FakeWorker.instances[0].posted[0].model).toBe('Xenova/whisper-base.en');
  });

  it('arm is idempotent — second call does not create a new worker', () => {
    armTransformersStt();
    armTransformersStt();
    expect(FakeWorker.instances).toHaveLength(1);
  });

  it('frames received before speech_start are dropped (silence-gate)', () => {
    armTransformersStt();
    const worker = FakeWorker.instances[0];
    const handler = hoisted.captured.handler;

    // No onSpeechStart yet — frames must be dropped.
    handler.onFrame(new Float32Array([0.9, 0.9, 0.9]), 16000);
    handler.onSpeechEnd(0);
    expect(worker.posted.find((m) => m.type === 'transcribe')).toBeUndefined();
    expect(Array.from(dispatch(handler, [7]).samples)).toEqual([7]);
  });
});

describe('issue1367 capture, registration and job ownership', () => {
  it.each(['subscribe-first', 'arm-first'])('supports %s with scoped final-only and legacy partial/final isolation', order => {
    const scope = Symbol();
    const scoped = vi.fn();
    const legacy = vi.fn();
    if (order === 'subscribe-first') onTransformersTranscript(scoped, scope);
    const cancel = armTransformersStt(scope);
    const tap = hoisted.captured.handler;
    if (order === 'arm-first') onTransformersTranscript(scoped, scope);
    onTransformersTranscript(legacy);
    armTransformersStt();
    const scopedJob = dispatch(tap);
    const legacyJob = dispatch();
    const worker = FakeWorker.instances[0];
    for (const job of [scopedJob, legacyJob]) {
      worker.reply(job, 1, { type: 'transcript', text: 'partial', isPartial: true });
      worker.reply(job, 2, { type: 'transcript', text: 'finished', isPartial: false });
      worker.reply(job, 3, { type: 'complete', outcome: 'success' });
    }
    expect(scoped.mock.calls).toEqual([['finished']]);
    expect(legacy.mock.calls).toEqual([['partial'], ['finished']]);
    cancel();
    expect(hoisted.handlers.size).toBe(1);
    expect(worker.terminated).toBe(false);
  });

  it('retires reused-scope generations, callbacks, pending PCM and old cancellation handles', () => {
    const scope = Symbol();
    const oldListener = vi.fn();
    onTransformersTranscript(oldListener, scope);
    const cancel = armTransformersStt(scope);
    const oldTap = hoisted.captured.handler;
    const sameOwnerCancel = armTransformersStt(scope);
    expect(hoisted.handlers.size).toBe(1);
    const oldJob = dispatch(oldTap, [3]);
    oldTap.onFrame(new Float32Array([4]), 16000);
    cancel();
    const newListener = vi.fn();
    onTransformersTranscript(newListener, scope);
    armTransformersStt(scope);
    const newTap = hoisted.captured.handler;
    sameOwnerCancel();
    cancel();
    oldTap.onSpeechStart(0);
    oldTap.onFrame(new Float32Array([99]), 16000);
    oldTap.onSpeechEnd(1);
    expect(hoisted.handlers.size).toBe(1);
    const newJob = dispatch(newTap, [5]);
    expect(Array.from(newJob.samples)).toEqual([5]);
    expect(newJob.captureId).not.toBe(oldJob.captureId);
    expect(newJob.jobId).not.toBe(oldJob.jobId);
    finish(FakeWorker.instances[0], oldJob, 'retired');
    finish(FakeWorker.instances[0], newJob, 'current');
    expect(oldListener).not.toHaveBeenCalled();
    expect(newListener.mock.calls).toEqual([['current']]);
  });

  it.each([undefined, Symbol('scoped')])('new registrations do not inherit dispatched jobs in domain %s', scope => {
    armTransformersStt(scope);
    const oldListener = vi.fn();
    const unsubscribe = onTransformersTranscript(oldListener, scope);
    const request = dispatch();
    unsubscribe();
    const newListener = vi.fn();
    const processing = vi.fn();
    onTransformersTranscript(newListener, scope);
    onTransformersTranscribing(processing, scope);
    finish(FakeWorker.instances[0], request, 'old');
    expect(oldListener).not.toHaveBeenCalled();
    expect(newListener).not.toHaveBeenCalled();
    expect(processing).not.toHaveBeenCalled();
    finish(FakeWorker.instances[0], dispatch(), 'new');
    expect(newListener.mock.calls).toEqual([['new']]);
    expect(processing.mock.calls).toEqual([[true], [false]]);
  });

  it('rejects malformed, unknown, wrong-owner, duplicate and out-of-order replies without changing processing', () => {
    const scope = Symbol();
    const listener = vi.fn();
    const states = vi.fn();
    armTransformersStt(scope);
    onTransformersTranscript(listener, scope);
    onTransformersTranscribing(states, scope);
    const request = dispatch();
    const worker = FakeWorker.instances[0];
    const final = { type: 'transcript', text: 'valid', isPartial: false };
    worker.emit({ ...final });
    worker.reply(request, 100, { ...final, captureId: 'wrong' });
    worker.reply(request, 100, { ...final, jobId: 'unknown' });
    worker.reply(request, 100, { ...final, isPartial: 'false' });
    worker.reply(request, 100, { type: 'transcribing', active: 'false' });
    worker.reply(request, 100, { type: 'complete', outcome: 'invalid' });
    worker.reply(request, NaN, final);
    worker.reply(request, 2, { type: 'transcript', text: 'partial', isPartial: true });
    worker.reply(request, 1, final);
    expect(listener).not.toHaveBeenCalled();
    expect(states.mock.calls).toEqual([[true]]);
    worker.reply(request, 3, final);
    worker.reply(request, 3, final);
    worker.reply(request, 4, { ...final, text: 'second final' });
    worker.reply(request, 5, { type: 'complete', outcome: 'success' });
    worker.reply(request, 6, { type: 'transcribing', active: true });
    expect(listener.mock.calls).toEqual([['valid']]);
    expect(states.mock.calls).toEqual([[true], [false]]);
  });

  it('aggregates overlapping jobs and cancels only the owning capture processing', () => {
    const firstScope = Symbol();
    const secondScope = Symbol();
    const firstStates = vi.fn();
    const secondStates = vi.fn();
    onTransformersTranscribing(firstStates, firstScope);
    const cancel = armTransformersStt(firstScope);
    const firstTap = hoisted.captured.handler;
    onTransformersTranscribing(secondStates, secondScope);
    armTransformersStt(secondScope);
    const secondTap = hoisted.captured.handler;
    const firstJob = dispatch(firstTap);
    const overlapping = dispatch(firstTap);
    const sibling = dispatch(secondTap);
    const worker = FakeWorker.instances[0];
    finish(worker, firstJob, 'first');
    expect(firstStates.mock.calls).toEqual([[true]]);
    cancel();
    expect(firstStates.mock.calls).toEqual([[true], [false]]);
    expect(secondStates.mock.calls).toEqual([[true]]);
    finish(worker, overlapping, 'retired');
    disarmTransformersStt();
    expect(hoisted.handlers.has(secondTap)).toBe(true);
    finish(worker, sibling, 'sibling');
    expect(secondStates.mock.calls).toEqual([[true], [false]]);
    expect(worker.posted.some(message => message.type === 'shutdown')).toBe(false);
  });

  it('handles empty success, terminal failure and listener exceptions without blocking a sibling', () => {
    const firstScope = Symbol();
    const secondScope = Symbol();
    const empty = vi.fn();
    onTransformersTranscript(() => { throw new Error('listener'); }, firstScope);
    onTransformersTranscript(empty, firstScope);
    armTransformersStt(firstScope);
    const firstJob = dispatch();
    const sibling = vi.fn();
    onTransformersTranscript(sibling, secondScope);
    armTransformersStt(secondScope);
    const failed = dispatch();
    const worker = FakeWorker.instances[0];
    finish(worker, firstJob, '');
    worker.reply(failed, 1, { type: 'complete', outcome: 'error' });
    expect(empty.mock.calls).toEqual([['']]);
    expect(sibling).not.toHaveBeenCalled();
    finish(worker, dispatch(), 'survives');
    expect(sibling.mock.calls).toEqual([['survives']]);
  });

  it('fences reentrant cancellation and a new same-scope capture before continuing listener delivery', () => {
    const scope = Symbol();
    let cancel = (): void => {};
    const retired = vi.fn();
    const current = vi.fn();
    onTransformersTranscript(() => {
      cancel();
      onTransformersTranscript(current, scope);
      armTransformersStt(scope);
    }, scope);
    onTransformersTranscript(retired, scope);
    cancel = armTransformersStt(scope);
    finish(FakeWorker.instances[0], dispatch(), 'old accepted');
    expect(retired).not.toHaveBeenCalled();
    expect(current).not.toHaveBeenCalled();
    finish(FakeWorker.instances[0], dispatch(), 'new accepted');
    expect(current.mock.calls).toEqual([['new accepted']]);
  });

  it('does not dispatch after synchronous processing cancellation during job registration', () => {
    const scope = Symbol();
    const cancel = armTransformersStt(scope);
    onTransformersTranscribing(active => { if (active) cancel(); }, scope);
    const tap = hoisted.captured.handler;
    tap.onSpeechStart(0);
    tap.onFrame(new Float32Array([1]), 16000);
    tap.onSpeechEnd(1);
    expect(FakeWorker.instances[0].posted.filter(message => message.type === 'transcribe')).toHaveLength(0);
    expect(hoisted.handlers.size).toBe(0);
  });

  it('copies bounded pre-roll and caps a complete window without retaining a cancelled tail', () => {
    const scope = Symbol();
    const cancel = armTransformersStt(scope);
    const tap = hoisted.captured.handler;
    const source = new Float32Array(10000).fill(2);
    tap.onFrame(source, 16000);
    source.fill(99);
    const request = dispatch(tap, [3]);
    expect(request.samples.length).toBe(9601);
    expect(request.samples[0]).toBe(2);
    expect(request.samples[9599]).toBe(2);
    expect(request.samples[9600]).toBe(3);
    tap.onSpeechStart(0);
    tap.onFrame(new Float32Array(480001).fill(4), 16000);
    tap.onFrame(new Float32Array([8]), 16000);
    tap.onSpeechEnd(1);
    const capped = FakeWorker.instances[0].posted.slice(-1)[0];
    expect(capped.samples.length).toBe(480000);
    expect(capped.samples[479999]).toBe(4);
    tap.onSpeechStart(2);
    tap.onFrame(new Float32Array([9]), 16000);
    cancel();
    armTransformersStt(scope);
    expect(Array.from(dispatch(undefined, [7]).samples)).toEqual([7]);
  });

  it('ignores zero, invalid-rate and empty windows and rejects non-symbol scopes', () => {
    armTransformersStt(Symbol());
    const tap = hoisted.captured.handler;
    tap.onSpeechStart(0);
    tap.onFrame(new Float32Array(), 16000);
    tap.onFrame(new Float32Array([9]), 48000);
    tap.onSpeechEnd(1);
    tap.onSpeechEnd(2);
    expect(FakeWorker.instances[0].posted).toHaveLength(1);
    expect(() => armTransformersStt('invalid' as unknown as symbol)).toThrow(TypeError);
    expect(() => onTransformersTranscript(vi.fn(), null as unknown as symbol)).toThrow(TypeError);
    expect(() => onTransformersTranscribing(null as unknown as (active: boolean) => void)).toThrow(TypeError);
  });

  it('preserves an accepted legacy reply for existing siblings when one listener disarms during delivery', () => {
    const sibling = vi.fn();
    const newcomer = vi.fn();
    armTransformersStt();
    onTransformersTranscript(() => {
      disarmTransformersStt();
      onTransformersTranscript(newcomer);
      armTransformersStt();
    });
    onTransformersTranscript(sibling);
    const job = dispatch();
    finish(FakeWorker.instances[0], job, 'accepted legacy text');
    expect(sibling.mock.calls).toEqual([['accepted legacy text']]);
    expect(newcomer).not.toHaveBeenCalled();
    finish(FakeWorker.instances[0], job, 'retired replay');
    expect(sibling).toHaveBeenCalledTimes(1);
    expect(newcomer).not.toHaveBeenCalled();
  });

  it('clears processing exactly once when a subscription ends before its pending job', () => {
    const states = vi.fn();
    armTransformersStt();
    const unsubscribe = onTransformersTranscribing(states);
    const job = dispatch();
    expect(states.mock.calls).toEqual([[true]]);
    unsubscribe();
    unsubscribe();
    expect(states.mock.calls).toEqual([[true], [false]]);
    finish(FakeWorker.instances[0], job, 'settled after unsubscribe');
    expect(states.mock.calls).toEqual([[true], [false]]);
  });

  it('settles structured-clone dispatch failures without fabricated text and remains reusable', () => {
    const scope = Symbol();
    const listener = vi.fn();
    const states = vi.fn();
    armTransformersStt(scope);
    onTransformersTranscript(listener, scope);
    onTransformersTranscribing(states, scope);
    const worker = FakeWorker.instances[0];
    const post = vi.spyOn(worker, 'postMessage').mockImplementationOnce(() => { throw new DOMException('clone', 'DataCloneError'); });
    const tap = hoisted.captured.handler;
    tap.onSpeechStart(0);
    tap.onFrame(new Float32Array([1]), 16000);
    tap.onSpeechEnd(1);
    expect(states.mock.calls).toEqual([[true], [false]]);
    expect(listener).not.toHaveBeenCalled();
    post.mockRestore();
    finish(worker, dispatch(), 'retry');
    expect(listener.mock.calls).toEqual([['retry']]);
  });

  it.each(['error', 'messageerror'])('settles %s and fences retained old handlers during replacement', eventType => {
    const scope = Symbol();
    const states = vi.fn();
    armTransformersStt(scope);
    onTransformersTranscribing(states, scope);
    const request = dispatch();
    const worker = FakeWorker.instances[0];
    const oldHandler = [...worker.listeners.get('message')!][0];
    worker.emit({}, eventType);
    expect(states.mock.calls).toEqual([[true], [false]]);
    expect(worker.terminated).toBe(true);
    expect([...worker.listeners.values()].every(listeners => listeners.size === 0)).toBe(true);
    const replacement = vi.fn();
    onTransformersTranscript(replacement, scope);
    armTransformersStt(scope);
    oldHandler({ data: { ...request, type: 'transcript', sequence: 1, text: 'old', isPartial: false } } as MessageEvent);
    expect(replacement).not.toHaveBeenCalled();
    expect(FakeWorker.instances).toHaveLength(2);
  });
});

type HarnessEvent = Record<string, any>;

async function actualWorkerHarness(): Promise<{
  requests: HarnessEvent[];
  replies: HarnessEvent[];
  detached: number[];
  handled: ReturnType<typeof vi.fn>;
  closed: ReturnType<typeof vi.fn>;
  send: (request: unknown) => void;
  cleanup: () => Promise<void>;
}> {
  const channel = new MessageChannel();
  const requests: HarnessEvent[] = [];
  const replies: HarnessEvent[] = [];
  const detached: number[] = [];
  const tasks = new Set<Promise<unknown>>();
  const handlers = new Set<(event: MessageEvent) => unknown>();
  const handled = vi.fn();
  const closed = vi.fn();
  const fake = new FakeWorker();
  fake.postMessage = (request: HarnessEvent, transfer?: ArrayBuffer[]): void => {
    channel.port1.postMessage(request, transfer ?? []);
    if (request.type === 'transcribe') detached.push(request.samples.byteLength);
  };
  const scope = {
    addEventListener: (type: string, handler: (event: MessageEvent) => unknown): void => {
      if (type === 'message') handlers.add(handler);
    },
    postMessage: (reply: HarnessEvent): void => { channel.port2.postMessage(reply); },
    close: closed,
  };
  channel.port2.on('message', (request: HarnessEvent) => {
    if (ArrayBuffer.isView(request.samples) && Object.prototype.toString.call(request.samples) === '[object Float32Array]') {
      Object.setPrototypeOf(request.samples, Float32Array.prototype);
    }
    requests.push(request);
    for (const handler of handlers) {
      handled(request.type);
      const task = Promise.resolve(handler({ data: request } as MessageEvent));
      tasks.add(task);
      void task.then(() => tasks.delete(task), () => tasks.delete(task));
    }
  });
  channel.port1.on('message', (reply: HarnessEvent) => {
    replies.push(reply);
    fake.emit(reply);
  });
  vi.stubGlobal('self', scope);
  try {
    vi.resetModules();
    await import('../audio/transformersWorker');
    expect(handlers.size).toBe(1);
    _setTransformersWorkerOverride(() => fake as unknown as Worker);
  } catch (error) {
    channel.port1.close();
    channel.port2.close();
    vi.unstubAllGlobals();
    throw error;
  }
  return {
    requests, replies, detached, handled, closed,
    send: request => channel.port1.postMessage(request),
    cleanup: async () => {
      try {
        terminateTransformersStt();
        await vi.waitFor(() => expect(closed).toHaveBeenCalled());
        await Promise.allSettled([...tasks]);
      } finally {
        channel.port1.close();
        channel.port2.close();
        vi.unstubAllGlobals();
        _resetTransformersStt();
      }
    },
  };
}

function assertCorrelated(harness: Awaited<ReturnType<typeof actualWorkerHarness>>): void {
  const jobs = harness.requests.filter(request => request.type === 'transcribe');
  expect(jobs.length).toBeGreaterThan(0);
  for (const job of jobs) {
    expect(typeof job.captureId).toBe('string');
    expect(typeof job.jobId).toBe('string');
    const events = harness.replies.filter(reply => reply.jobId === job.jobId);
    expect(events.length).toBeGreaterThanOrEqual(3);
    expect(events.every(event => event.captureId === job.captureId)).toBe(true);
    expect(events.map(event => event.sequence)).toEqual(events.map((_, index) => index + 1));
    expect(events.slice(-1)[0]?.type).toBe('complete');
  }
}

describe('issue1367 actual worker module over MessageChannel', () => {
  it('awaits initialization and preserves transferred identity, source PCM, sibling buffers and final-only delivery', async () => {
    const asr = Object.assign(vi.fn(async (_samples: Float32Array, options: { chunk_callback: (chunk: { text: string }) => void }) => {
      options.chunk_callback({ text: '[BLANK_AUDIO]' });
      options.chunk_callback({ text: '>>' });
      options.chunk_callback({ text: 'partial words' });
      return { text: 'final words' };
    }), { dispose: vi.fn(async () => {}) });
    let resolveInit!: (value: typeof asr) => void;
    hoisted.pipeline.mockReset().mockImplementation(() => new Promise<typeof asr>(resolve => { resolveInit = resolve; }));
    const harness = await actualWorkerHarness();
    try {
      const scoped = vi.fn();
      const legacy = vi.fn();
      const states = vi.fn();
      const scope = Symbol();
      onTransformersTranscript(scoped, scope);
      onTransformersTranscribing(states, scope);
      armTransformersStt(scope);
      const scopedTap = hoisted.captured.handler;
      onTransformersTranscript(legacy);
      armTransformersStt();
      const legacyTap = hoisted.captured.handler;
      const source = new Float32Array([2, 4, 6]);
      for (const tap of [scopedTap, legacyTap]) {
        tap.onSpeechStart(0);
        tap.onFrame(source, 16000);
      }
      scopedTap.onSpeechEnd(1);
      expect(source.byteLength).toBe(12);
      expect(Array.from(source)).toEqual([2, 4, 6]);
      source.fill(9);
      legacyTap.onSpeechEnd(1);
      await vi.waitFor(() => {
        expect(hoisted.pipeline).toHaveBeenCalledTimes(1);
        expect(harness.handled.mock.calls.filter(([type]) => type === 'transcribe')).toHaveLength(2);
      });
      expect(asr).not.toHaveBeenCalled();
      expect(states.mock.calls).toEqual([[true]]);
      expect(harness.detached).toEqual([0, 0]);
      const jobs = harness.requests.filter(request => request.type === 'transcribe');
      expect(jobs.map(job => Array.from(job.samples))).toEqual([[2, 4, 6], [2, 4, 6]]);
      resolveInit(asr);
      await vi.waitFor(() => expect(harness.replies.filter(reply => reply.type === 'complete')).toHaveLength(2));
      expect(asr).toHaveBeenCalledTimes(2);
      expect(scoped.mock.calls).toEqual([['final words']]);
      expect(legacy.mock.calls).toEqual([['partial words'], ['final words']]);
      expect(states.mock.calls).toEqual([[true], [false]]);
      expect(harness.replies.filter(reply => reply.type === 'transcript').map(reply => reply.text)).not.toContain('>>');
      assertCorrelated(harness);
    } finally {
      resolveInit?.(asr);
      await harness.cleanup();
    }
    expect(asr.dispose).toHaveBeenCalledTimes(1);
  });

  it.each(['init-error', 'missing-pipeline', 'inference-error', 'empty'])('terminates %s honestly through the actual handler', async mode => {
    const asr = Object.assign(vi.fn(async () => {
      if (mode === 'inference-error') throw new Error('controlled inference failure');
      return { text: '[BLANK_AUDIO]' };
    }), { dispose: vi.fn(async () => {}) });
    hoisted.pipeline.mockReset().mockImplementation(async () => {
      if (mode === 'init-error') throw new Error('controlled init failure');
      if (mode === 'missing-pipeline') return null;
      return asr;
    });
    const harness = await actualWorkerHarness();
    try {
      const scope = Symbol();
      const transcript = vi.fn();
      const processing = vi.fn();
      onTransformersTranscript(transcript, scope);
      onTransformersTranscribing(processing, scope);
      armTransformersStt(scope);
      const tap = hoisted.captured.handler;
      tap.onSpeechStart(0);
      tap.onFrame(new Float32Array([1, 2]), 16000);
      tap.onSpeechEnd(1);
      await vi.waitFor(() => expect(harness.replies.filter(reply => reply.type === 'complete')).toHaveLength(1));
      expect(hoisted.pipeline).toHaveBeenCalledTimes(1);
      expect(harness.handled).toHaveBeenCalledWith('transcribe');
      expect(asr).toHaveBeenCalledTimes(['init-error', 'missing-pipeline'].includes(mode) ? 0 : 1);
      expect(transcript.mock.calls).toEqual(mode === 'empty' ? [['']] : []);
      expect(processing.mock.calls).toEqual([[true], [false]]);
      expect(harness.replies.find(reply => reply.type === 'complete')?.outcome).toBe(mode === 'empty' ? 'success' : 'error');
      assertCorrelated(harness);
    } finally { await harness.cleanup(); }
  });

  it('validates request data and settles a running job on shutdown without late chunk delivery', async () => {
    let resolveInference!: (output: { text: string }) => void;
    let chunk!: (output: { text: string }) => void;
    const asr = Object.assign(vi.fn((_samples: Float32Array, options: { chunk_callback: typeof chunk }) => {
      chunk = options.chunk_callback;
      return new Promise<{ text: string }>(resolve => { resolveInference = resolve; });
    }), { dispose: vi.fn(async () => {}) });
    hoisted.pipeline.mockReset().mockResolvedValue(asr);
    const harness = await actualWorkerHarness();
    try {
      const listener = vi.fn();
      const scope = Symbol();
      onTransformersTranscript(listener, scope);
      armTransformersStt(scope);
      const tap = hoisted.captured.handler;
      tap.onSpeechStart(0);
      tap.onFrame(new Float32Array([8]), 16000);
      tap.onSpeechEnd(1);
      await vi.waitFor(() => expect(asr).toHaveBeenCalledTimes(1));
      const job = harness.requests.find(request => request.type === 'transcribe')!;
      harness.send({ ...job, jobId: `${job.jobId}-rate`, sampleRate: 48000 });
      harness.send({ ...job, jobId: `${job.jobId}-array`, samples: [1] });
      harness.send({ ...job, jobId: `${job.jobId}-empty`, samples: new Float32Array() });
      harness.send({ ...job, jobId: null });
      await vi.waitFor(() => expect(harness.replies.filter(reply => reply.type === 'complete')).toHaveLength(3));
      expect(asr).toHaveBeenCalledTimes(1);
      terminateTransformersStt();
      await vi.waitFor(() => expect(harness.closed).toHaveBeenCalledTimes(1));
      chunk({ text: 'late partial' });
      resolveInference({ text: 'late final' });
      await vi.waitFor(() => expect(harness.replies.filter(reply => reply.type === 'complete')).toHaveLength(4));
      expect(listener).not.toHaveBeenCalled();
      expect(harness.replies.filter(reply => reply.type === 'transcript')).toHaveLength(0);
      expect(harness.replies.filter(reply => reply.type === 'complete').every(reply => reply.outcome === 'error')).toBe(true);
    } finally {
      resolveInference?.({ text: 'cleanup' });
      await harness.cleanup();
    }
  });
});
