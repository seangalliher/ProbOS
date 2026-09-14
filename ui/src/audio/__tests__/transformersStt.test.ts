/**
 * BF-320 (GH #789) — transformersStt worker-warm regression tests.
 *
 * Verifies that the Worker + whisper pipeline survives across
 * arm/disarm/arm cycles so PTT clicks don't pay the ~2-4s
 * whisper-medium.en re-init cost on every press.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  _isArmed,
  _resetTransformersStt,
  _setTransformersWorkerOverride,
  armTransformersStt,
  disarmTransformersStt,
  terminateTransformersStt,
} from '../transformersStt';
import { _resetPcmSubscribers, _peekPcmSubscriberCount as _pcmSubscriberCount, subscribePcm } from '../voiceActivity';

interface FakeWorker {
  postMessage: ReturnType<typeof vi.fn>;
  terminate: ReturnType<typeof vi.fn>;
  addEventListener: ReturnType<typeof vi.fn>;
  removeEventListener: ReturnType<typeof vi.fn>;
}

function makeFakeWorker(): FakeWorker {
  return {
    postMessage: vi.fn(),
    terminate: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  };
}

beforeEach(() => {
  _resetTransformersStt();
  _resetPcmSubscribers();
});

afterEach(() => {
  _resetTransformersStt();
  _resetPcmSubscribers();
});

describe('BF-320: worker survives across arm/disarm cycles', () => {
  it('does not re-create the worker on re-arm after disarm', () => {
    const factory = vi.fn(() => makeFakeWorker() as unknown as Worker);
    _setTransformersWorkerOverride(factory);

    armTransformersStt();
    expect(_isArmed()).toBe(true);
    expect(factory).toHaveBeenCalledTimes(1);

    disarmTransformersStt();
    expect(_isArmed()).toBe(false);
    // Crucially: factory NOT called again, worker NOT terminated.
    expect(factory).toHaveBeenCalledTimes(1);

    armTransformersStt();
    expect(_isArmed()).toBe(true);
    // Still exactly one factory call — the worker was reused.
    expect(factory).toHaveBeenCalledTimes(1);
  });

  it('disarm does not post shutdown and does not terminate the worker', () => {
    const fake = makeFakeWorker();
    _setTransformersWorkerOverride(() => fake as unknown as Worker);

    armTransformersStt();
    // init was posted at arm-time.
    expect(fake.postMessage).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'init' }),
    );
    const postMessageCallsAfterInit = fake.postMessage.mock.calls.length;

    disarmTransformersStt();

    // No further postMessage (no shutdown), no terminate.
    expect(fake.postMessage).toHaveBeenCalledTimes(postMessageCallsAfterInit);
    expect(fake.terminate).not.toHaveBeenCalled();
  });

  it('terminateTransformersStt shuts down the worker after a grace period', async () => {
    vi.useFakeTimers();
    try {
      const fake = makeFakeWorker();
      _setTransformersWorkerOverride(() => fake as unknown as Worker);

      armTransformersStt();
      terminateTransformersStt();

      expect(fake.postMessage).toHaveBeenCalledWith({ type: 'shutdown' });
      // terminate is deferred by 250 ms grace.
      expect(fake.terminate).not.toHaveBeenCalled();
      vi.advanceTimersByTime(260);
      expect(fake.terminate).toHaveBeenCalledTimes(1);
      expect(_isArmed()).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });

  it('re-arm after terminate creates a fresh worker', () => {
    const factory = vi.fn(() => makeFakeWorker() as unknown as Worker);
    _setTransformersWorkerOverride(factory);

    armTransformersStt();
    terminateTransformersStt();
    armTransformersStt();

    expect(factory).toHaveBeenCalledTimes(2);
  });

  it('armTransformersStt is idempotent while already armed', () => {
    const factory = vi.fn(() => makeFakeWorker() as unknown as Worker);
    _setTransformersWorkerOverride(factory);

    armTransformersStt();
    armTransformersStt();
    armTransformersStt();

    expect(factory).toHaveBeenCalledTimes(1);
    expect(_isArmed()).toBe(true);
  });

  it('scoped and legacy PCM subscriptions coexist with an independent App tap and resident worker', () => {
    const fake = makeFakeWorker();
    const factory = vi.fn(() => fake as unknown as Worker);
    _setTransformersWorkerOverride(factory);
    const releaseApp = subscribePcm({ onFrame: vi.fn() });
    try {
      const scope = Symbol();
      const cancel = armTransformersStt(scope);
      const siblingCancel = armTransformersStt(Symbol());
      armTransformersStt();
      expect(_pcmSubscriberCount()).toBe(4);
      disarmTransformersStt();
      expect(_pcmSubscriberCount()).toBe(3);
      cancel();
      cancel();
      expect(_pcmSubscriberCount()).toBe(2);
      armTransformersStt(scope);
      cancel();
      expect(_pcmSubscriberCount()).toBe(3);
      siblingCancel();
      expect(_pcmSubscriberCount()).toBe(2);
      expect(factory).toHaveBeenCalledTimes(1);
      expect(fake.postMessage).toHaveBeenCalledTimes(1);
      expect(fake.terminate).not.toHaveBeenCalled();
      terminateTransformersStt();
      expect(_pcmSubscriberCount()).toBe(1);
    } finally { releaseApp(); }
  });

  it.each(['error', 'messageerror'])('%s releases STT taps but preserves independent PCM and permits replacement', eventType => {
    const first = makeFakeWorker();
    const next = makeFakeWorker();
    const factory = vi.fn().mockReturnValueOnce(first).mockReturnValue(next);
    _setTransformersWorkerOverride(factory);
    const releaseApp = subscribePcm({ onFrame: vi.fn() });
    try {
      armTransformersStt(Symbol());
      armTransformersStt();
      expect(_pcmSubscriberCount()).toBe(3);
      const callback = first.addEventListener.mock.calls.find(([type]) => type === eventType)![1];
      callback(new Event(eventType));
      expect(_pcmSubscriberCount()).toBe(1);
      expect(_isArmed()).toBe(false);
      expect(first.terminate).toHaveBeenCalledTimes(1);
      expect(first.removeEventListener).toHaveBeenCalledTimes(3);
      armTransformersStt(Symbol());
      expect(_pcmSubscriberCount()).toBe(2);
      expect(factory).toHaveBeenCalledTimes(2);
    } finally { releaseApp(); }
  });

  it('old-worker grace termination cannot terminate a replacement and reset releases only STT subscriptions', () => {
    vi.useFakeTimers();
    const releaseApp = subscribePcm({ onFrame: vi.fn() });
    try {
      const first = makeFakeWorker();
      const next = makeFakeWorker();
      const factory = vi.fn().mockReturnValueOnce(first).mockReturnValue(next);
      _setTransformersWorkerOverride(factory);
      armTransformersStt(Symbol());
      terminateTransformersStt();
      armTransformersStt(Symbol());
      vi.advanceTimersByTime(260);
      expect(first.terminate).toHaveBeenCalledTimes(1);
      expect(next.terminate).not.toHaveBeenCalled();
      expect(_pcmSubscriberCount()).toBe(2);
      _resetTransformersStt();
      expect(next.terminate).toHaveBeenCalledTimes(1);
      expect(_pcmSubscriberCount()).toBe(1);
      expect(_isArmed()).toBe(false);
    } finally {
      releaseApp();
      vi.useRealTimers();
    }
  });
});
