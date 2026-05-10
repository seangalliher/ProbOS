import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

// AD-705 D8 test #14-15: Escape semantics.

vi.mock('../audio/speechInput', () => ({
  startListening: vi.fn(),
  stopListening: vi.fn(),
  isSpeechRecognitionSupported: vi.fn(() => true),
}));
vi.mock('../audio/voice', () => ({
  onSpeechEvent: vi.fn(() => () => undefined),
}));

import {
  startWakeWordLoop,
  getWakeWordState,
  _simulateWakeFire,
  _cancelCurrentCapture,
  _resetForTests,
} from '../audio/wakeWord';

describe('wakeWord Escape semantics (AD-705 D8)', () => {
  beforeEach(() => {
    _resetForTests();
    vi.useFakeTimers();
  });
  afterEach(() => {
    _resetForTests();
    vi.useRealTimers();
  });

  it('14. Escape during capturing cancels utterance, no onWake, returns to armed', async () => {
    const onWake = vi.fn();
    await startWakeWordLoop(onWake);
    _simulateWakeFire({ trigger: 'computer', cleanedText: 'do something' });
    expect(getWakeWordState()).toBe('fallback-capturing');
    _cancelCurrentCapture();
    expect(onWake).not.toHaveBeenCalled();
    expect(getWakeWordState()).toBe('fallback-armed');
  });

  it('15. Escape during armed (via cancel helper) is a no-op on capture state', async () => {
    await startWakeWordLoop(() => undefined);
    expect(getWakeWordState()).toBe('fallback-armed');
    _cancelCurrentCapture();
    // Cancel only acts on capturing states; armed remains armed.
    expect(getWakeWordState()).toBe('fallback-armed');
  });
});
