import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

// AD-705 D8 test #10-11: barge-in suppression.

let _speechListener: ((e: { type: 'start' | 'end'; agent_id?: string; utterance?: unknown }) => void) | null = null;

vi.mock('../audio/speechInput', () => ({
  startListening: vi.fn(),
  stopListening: vi.fn(),
  isSpeechRecognitionSupported: vi.fn(() => true),
}));
vi.mock('../audio/voice', () => ({
  flushSpeechQueue: vi.fn(),
  getServerPiperVoices: vi.fn(async () => null),
  onSpeechEvent: vi.fn((fn: (e: { type: 'start' | 'end' }) => void) => {
    _speechListener = fn;
    return () => {
      _speechListener = null;
    };
  }),
}));

import {
  startWakeWordLoop,
  getWakeWordState,
  _simulateTranscript,
  _resetForTests,
} from '../audio/wakeWord';

describe('wakeWord barge-in suppression (AD-705 D6)', () => {
  beforeEach(async () => {
    _resetForTests();
    vi.useFakeTimers();
    await startWakeWordLoop(() => undefined);
  });
  afterEach(() => {
    _resetForTests();
    vi.useRealTimers();
  });

  it('10. speech "start" gates ingestion: transcript dropped during TTS', () => {
    expect(_speechListener).toBeTruthy();
    // Simulate TTS start.
    _speechListener!({ type: 'start' } as { type: 'start' });
    // Push a transcript that would normally trigger a wake fire.
    _simulateTranscript('computer make a sandwich');
    // Loop should remain in armed state — ingestion was gated.
    expect(getWakeWordState()).toBe('fallback-armed');
  });

  it('11. speech "end" clears the gate: transcript ingested again', () => {
    _speechListener!({ type: 'start' } as { type: 'start' });
    _simulateTranscript('computer ignored');
    expect(getWakeWordState()).toBe('fallback-armed');
    _speechListener!({ type: 'end' } as { type: 'end' });
    _simulateTranscript('computer accepted now');
    expect(getWakeWordState()).toBe('fallback-capturing');
  });
});
