/** BF-301 (#775) — transformers.js STT module boundary tests.
 *
 * Tests the public surface of ``../audio/transformersStt`` against a
 * MessageChannel-backed fake Worker. Does NOT load the real
 * @huggingface/transformers package — the worker boundary is the
 * stable contract and is all this module owns.
 *
 * The ``voiceActivity`` module is mocked so we can drive PcmTapHandler
 * callbacks (onSpeechStart / onFrame / onSpeechEnd) deterministically.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const hoisted = vi.hoisted(() => {
  const captured: { handler: any } = { handler: null };
  const subscribePcmMock = vi.fn((handler: any) => {
    captured.handler = handler;
    return () => { captured.handler = null; };
  });
  return { captured, subscribePcmMock };
});

vi.mock('../audio/voiceActivity', () => ({
  subscribePcm: hoisted.subscribePcmMock,
}));

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
} from '../audio/transformersStt';

/** Minimal MessageChannel-backed fake Worker. */
class FakeWorker {
  static instances: FakeWorker[] = [];
  posted: any[] = [];
  terminated = false;
  listeners: Array<(e: MessageEvent) => void> = [];

  constructor() {
    FakeWorker.instances.push(this);
  }

  postMessage(message: any, _transfer?: any[]): void {
    this.posted.push(message);
  }

  addEventListener(_type: string, listener: (e: MessageEvent) => void): void {
    this.listeners.push(listener);
  }

  removeEventListener(_type: string, listener: (e: MessageEvent) => void): void {
    this.listeners = this.listeners.filter((l) => l !== listener);
  }

  terminate(): void {
    this.terminated = true;
  }

  /** Simulate a worker → main thread message. */
  emit(data: any): void {
    const event = { data } as MessageEvent;
    for (const l of this.listeners) l(event);
  }
}

beforeEach(() => {
  FakeWorker.instances = [];
  hoisted.subscribePcmMock.mockClear();
  hoisted.captured.handler = null;
  _resetTransformersStt();
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

    worker.emit({ type: 'transcript', text: 'hello world', isPartial: false });
    expect(received).toEqual(['hello world']);
  });

  it('worker transcribing message dispatches to onTransformersTranscribing subscribers', () => {
    armTransformersStt();
    const worker = FakeWorker.instances[0];
    const states: boolean[] = [];
    onTransformersTranscribing((active) => states.push(active));

    worker.emit({ type: 'transcribing', active: true });
    worker.emit({ type: 'transcribing', active: false });
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

  it('disarmTransformersStt posts shutdown and terminates worker after grace, next arm builds fresh worker', () => {
    vi.useFakeTimers();
    armTransformersStt();
    const first = FakeWorker.instances[0];

    disarmTransformersStt();
    expect(first.posted.some((m) => m.type === 'shutdown')).toBe(true);
    expect(_isArmed()).toBe(false);

    // Grace timer pending — terminate not yet called.
    expect(first.terminated).toBe(false);
    vi.advanceTimersByTime(300);
    expect(first.terminated).toBe(true);

    armTransformersStt();
    expect(FakeWorker.instances).toHaveLength(2);
    expect(FakeWorker.instances[1].posted[0].type).toBe('init');
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
  });
});
