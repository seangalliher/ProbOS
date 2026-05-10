import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  startWakeWordLoop,
  stopWakeWordLoop,
  getWakeWordState,
  isWakeWordActive,
  _simulateWakeFire,
  _simulateTranscript,
  _resetForTests,
} from '../audio/wakeWord';

// AD-705 D8 test #1-5: state-machine transitions.

vi.mock('../audio/speechInput', () => ({
  startListening: vi.fn(),
  stopListening: vi.fn(),
  isSpeechRecognitionSupported: vi.fn(() => true),
}));
vi.mock('../audio/voice', () => ({
  onSpeechEvent: vi.fn(() => () => undefined),
}));

describe('wakeWord state machine (AD-705 D3)', () => {
  beforeEach(() => {
    _resetForTests();
    vi.useFakeTimers();
  });
  afterEach(() => {
    _resetForTests();
    vi.useRealTimers();
  });

  it('1. startWakeWordLoop transitions off -> fallback-armed (no ONNX in test env)', async () => {
    expect(getWakeWordState()).toBe('off');
    await startWakeWordLoop(() => undefined);
    // Without onnxruntime-web installed, the loop falls back. The state
    // machine is still active and isWakeWordActive() returns true.
    expect(isWakeWordActive()).toBe(true);
    expect(getWakeWordState()).toBe('fallback-armed');
  });

  it('2. synthetic wake-fire transitions armed -> capturing', async () => {
    await startWakeWordLoop(() => undefined);
    expect(getWakeWordState()).toBe('fallback-armed');
    _simulateWakeFire({ trigger: 'computer', cleanedText: '' });
    expect(getWakeWordState()).toBe('fallback-capturing');
  });

  it('3. silence timeout commits the captured utterance via onWake', async () => {
    const onWake = vi.fn();
    await startWakeWordLoop(onWake);
    _simulateWakeFire({ trigger: 'computer', cleanedText: '' });
    _simulateTranscript('what is the load right now');
    // SILENCE_TIMEOUT_MS = 1500ms triggers commit.
    vi.advanceTimersByTime(1600);
    expect(onWake).toHaveBeenCalledTimes(1);
    expect(onWake.mock.calls[0][0]).toMatchObject({
      surface: 'system',
      cleanedText: 'what is the load right now',
    });
    expect(getWakeWordState()).toBe('fallback-armed');
  });

  it('4. MAX_DURATION ceiling commits the utterance even if no silence', async () => {
    const onWake = vi.fn();
    await startWakeWordLoop(onWake);
    _simulateWakeFire({ trigger: 'computer', cleanedText: 'still talking' });
    // Push transcripts continuously below the silence threshold so the
    // silence timer keeps resetting; the max-duration ceiling must commit
    // anyway. UTTERANCE_MAX_DURATION_MS = 10000ms.
    for (let t = 0; t < 11; t++) {
      vi.advanceTimersByTime(1000);
      _simulateTranscript('still talking');
    }
    expect(onWake).toHaveBeenCalled();
  });

  it('5. stopWakeWordLoop returns the loop to off from any state', async () => {
    await startWakeWordLoop(() => undefined);
    _simulateWakeFire({ trigger: 'computer', cleanedText: '' });
    expect(getWakeWordState()).not.toBe('off');
    stopWakeWordLoop();
    expect(getWakeWordState()).toBe('off');
    expect(isWakeWordActive()).toBe(false);
  });
});
