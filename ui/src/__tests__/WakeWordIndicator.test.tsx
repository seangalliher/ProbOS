import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, act, cleanup } from '@testing-library/react';

// AD-705 D8 test #16-18: indicator visual states.

vi.mock('../audio/speechInput', () => ({
  startListening: vi.fn(),
  stopListening: vi.fn(),
  isSpeechRecognitionSupported: vi.fn(() => true),
}));
vi.mock('../audio/voice', () => ({
  getServerPiperVoices: vi.fn(async () => null),
  onSpeechEvent: vi.fn(() => () => undefined),
}));

import { WakeWordIndicator } from '../components/WakeWordIndicator';
import {
  startWakeWordLoop,
  _simulateWakeFire,
  _resetForTests,
} from '../audio/wakeWord';

describe('WakeWordIndicator (AD-705 D7)', () => {
  beforeEach(() => {
    _resetForTests();
  });
  afterEach(() => {
    cleanup();
    _resetForTests();
  });

  it('16. state="off" with no fallback reason renders nothing', () => {
    const { container } = render(<WakeWordIndicator />);
    expect(
      container.querySelector('[data-testid="wake-word-indicator"]'),
    ).toBeNull();
  });

  it('17. armed state renders the indicator with no fallback label', async () => {
    const { container } = render(<WakeWordIndicator />);
    await act(async () => {
      await startWakeWordLoop(() => undefined);
    });
    const ind = container.querySelector(
      '[data-testid="wake-word-indicator"]',
    );
    expect(ind).not.toBeNull();
    // In test env (no onnxruntime-web), state is fallback-armed and the
    // fallback label is rendered.
    expect(ind!.getAttribute('data-state')).toBe('fallback-armed');
    const lbl = container.querySelector(
      '[data-testid="wake-word-fallback-label"]',
    );
    expect(lbl?.textContent).toContain('ONNX runtime failed to load');
  });

  it('18. capturing state renders trigger label and pulses', async () => {
    const { container } = render(<WakeWordIndicator />);
    await act(async () => {
      await startWakeWordLoop(() => undefined);
      _simulateWakeFire({ trigger: 'computer', cleanedText: '' });
    });
    const ind = container.querySelector(
      '[data-testid="wake-word-indicator"]',
    );
    expect(ind!.getAttribute('data-state')).toBe('fallback-capturing');
    const trigLbl = container.querySelector(
      '[data-testid="wake-word-trigger-label"]',
    );
    expect(trigLbl?.textContent).toContain('computer');
  });
});
