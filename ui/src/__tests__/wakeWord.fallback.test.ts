import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

// AD-705 D8 test #12-13: fallback paths.

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
  _getStateDetail,
  _simulateTranscript,
  _resetForTests,
} from '../audio/wakeWord';
import { isSpeechRecognitionSupported } from '../audio/speechInput';

describe('wakeWord fallback paths (AD-705 D3 Tier-2 log-and-degrade)', () => {
  beforeEach(() => {
    _resetForTests();
    vi.useFakeTimers();
  });
  afterEach(() => {
    _resetForTests();
    vi.useRealTimers();
  });

  it('12. ONNX load failure -> fallback-armed, substring match drives capturing', async () => {
    const onWake = vi.fn();
    await startWakeWordLoop(onWake);
    expect(getWakeWordState()).toBe('fallback-armed');
    expect(_getStateDetail().fallbackReason).toBe('onnx_load_failed');
    // Substring match against STATIC_WAKE_PHRASES.
    _simulateTranscript('computer please continue');
    expect(getWakeWordState()).toBe('fallback-capturing');
  });

  it('13. SpeechRecognition unsupported -> off with reason="speech_recognition_unavailable"', async () => {
    vi.mocked(isSpeechRecognitionSupported).mockReturnValueOnce(false);
    await startWakeWordLoop(() => undefined);
    expect(getWakeWordState()).toBe('off');
    expect(_getStateDetail().fallbackReason).toBe(
      'speech_recognition_unavailable',
    );
  });
});
