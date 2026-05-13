import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

// AD-736: mic-permission state-machine tests.

// vi.mock is hoisted; use vi.hoisted so the test can capture callbacks
// passed into startListening.
const _h = vi.hoisted(() => ({
  onError: null as ((err: string) => void) | null,
  onResult: null as ((transcript: string) => void) | null,
  srSupported: true,
}));

vi.mock('../../audio/speechInput', () => ({
  startListening: vi.fn(
    (
      onResult: (transcript: string) => void,
      _onEnd: () => void,
      onError: (err: string) => void,
    ) => {
      _h.onResult = onResult;
      _h.onError = onError;
    },
  ),
  stopListening: vi.fn(),
  isSpeechRecognitionSupported: vi.fn(() => _h.srSupported),
}));
vi.mock('../../audio/voice', () => ({
  onSpeechEvent: vi.fn(() => () => undefined),
}));

import {
  startWakeWordLoop,
  stopWakeWordLoop,
  getMicPermissionState,
  onMicPermissionState,
  _resetForTests,
} from '../wakeWord';

describe('wakeWord mic-permission state machine (AD-736)', () => {
  beforeEach(() => {
    _resetForTests();
    _h.onError = null;
    _h.onResult = null;
    _h.srSupported = true;
    // Default: mediaDevices probe returns at least one audioinput.
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      writable: true,
      value: {
        enumerateDevices: vi.fn(async () => [
          { kind: 'audioinput', deviceId: 'd1', label: 'Default mic' },
        ]),
      },
    });
  });
  afterEach(() => {
    _resetForTests();
    stopWakeWordLoop();
  });

  it('1. initial state is "pending" before startWakeWordLoop is called', () => {
    expect(getMicPermissionState()).toBe('pending');
  });

  it('2. state becomes "unavailable" when SpeechRecognition is not supported', async () => {
    _h.srSupported = false;
    await startWakeWordLoop(() => undefined);
    expect(getMicPermissionState()).toBe('unavailable');
  });

  it('3. state becomes "unavailable" when no audioinput device is enumerated', async () => {
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      writable: true,
      value: {
        enumerateDevices: vi.fn(async () => [
          { kind: 'videoinput', deviceId: 'v1', label: 'Webcam' },
        ]),
      },
    });
    await startWakeWordLoop(() => undefined);
    expect(getMicPermissionState()).toBe('unavailable');
  });

  it('4. state transitions to "denied" when SR emits "not-allowed"', async () => {
    await startWakeWordLoop(() => undefined);
    expect(_h.onError).not.toBeNull();
    _h.onError?.('not-allowed');
    expect(getMicPermissionState()).toBe('denied');
  });

  it('5. state transitions to "granted" on the first transcript', async () => {
    await startWakeWordLoop(() => undefined);
    expect(getMicPermissionState()).toBe('pending');
    _h.onResult?.('hello world');
    expect(getMicPermissionState()).toBe('granted');
  });

  it('6. onMicPermissionState fires the current state synchronously on subscribe', () => {
    const fn = vi.fn();
    const unsub = onMicPermissionState(fn);
    expect(fn).toHaveBeenCalledTimes(1);
    expect(fn.mock.calls[0][0]).toBe('pending');
    unsub();
  });
});
