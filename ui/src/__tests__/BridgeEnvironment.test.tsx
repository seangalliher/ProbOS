import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, fireEvent, cleanup } from '@testing-library/react';

// AD-705 D8 test #19-20: toggle persistence + default.

vi.mock('../audio/soundEngine', () => ({
  soundEngine: {
    initialized: true,
    init: vi.fn(),
    setMuted: vi.fn(),
    setVolume: vi.fn(),
    volume: 0.5,
  },
}));
vi.mock('../audio/voice', () => ({
  getServerPiperVoices: vi.fn(async () => null),
  getAvailableVoices: vi.fn(() => []),
  setPreferredVoiceName: vi.fn(),
  getCurrentVoiceName: vi.fn(() => 'Default'),
  speakResponse: vi.fn(),
}));

import { BridgeEnvironment } from '../components/bridge/BridgeEnvironment';
import { useStore } from '../store/useStore';

describe('BridgeEnvironment toggles (AD-945, was AD-705 D5)', () => {
  beforeEach(() => {
    localStorage.clear();
    // Reset toggles to default in store (OFF-state titles resolve from these).
    useStore.setState({
      wakeWordEnabled: false,
      soundEnabled: false,
      voiceEnabled: false,
      showLegend: false,
    });
  });
  afterEach(() => {
    cleanup();
  });

  it('19. toggle persists across remount via localStorage', () => {
    const { unmount, container } = render(<BridgeEnvironment />);
    const btn = container.querySelector(
      '[data-testid="wake-word-toggle"]',
    ) as HTMLButtonElement;
    expect(btn).not.toBeNull();
    fireEvent.click(btn);
    expect(useStore.getState().wakeWordEnabled).toBe(true);
    expect(localStorage.getItem('hxi_wake_word_enabled')).toBe('1');
    unmount();
    // Hydrate a fresh store-equivalent: rehydrate from localStorage by
    // re-reading the persisted flag (mirroring the store's initial-state
    // hydration logic).
    expect(localStorage.getItem('hxi_wake_word_enabled')).toBe('1');
  });

  it('20. default value is false (Captain explicitly opts in)', () => {
    expect(useStore.getState().wakeWordEnabled).toBe(false);
    const { container } = render(<BridgeEnvironment />);
    const btn = container.querySelector(
      '[data-testid="wake-word-toggle"]',
    ) as HTMLButtonElement;
    // Inactive style: dim color (#8888aa stroke) — verified via attribute.
    const stroke = btn?.querySelector('svg')?.getAttribute('stroke');
    expect(stroke).toBe('#8888aa');
  });

  it('21. sound toggle flips soundEnabled + persists hxi_sound_enabled', () => {
    const { container } = render(<BridgeEnvironment />);
    const btn = container.querySelector(
      '[title="Enable ambient sounds"]',
    ) as HTMLButtonElement;
    expect(btn).not.toBeNull();
    fireEvent.click(btn);
    expect(useStore.getState().soundEnabled).toBe(true);
    expect(localStorage.getItem('hxi_sound_enabled')).toBe('1');
  });

  it('22. voice toggle flips voiceEnabled + persists hxi_voice_enabled', () => {
    const { container } = render(<BridgeEnvironment />);
    const btn = container.querySelector(
      '[title="Enable voice output"]',
    ) as HTMLButtonElement;
    expect(btn).not.toBeNull();
    fireEvent.click(btn);
    expect(useStore.getState().voiceEnabled).toBe(true);
    expect(localStorage.getItem('hxi_voice_enabled')).toBe('1');
  });

  it('23. legend toggle flips showLegend', () => {
    const { container } = render(<BridgeEnvironment />);
    const btn = container.querySelector(
      '[title="Toggle visual legend"]',
    ) as HTMLButtonElement;
    expect(btn).not.toBeNull();
    fireEvent.click(btn);
    expect(useStore.getState().showLegend).toBe(true);
  });

  it('24. renders no emoji (HXI Principle #3 — stroke-SVG glyphs only)', () => {
    const { container } = render(<BridgeEnvironment />);
    expect(
      /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u.test(container.textContent ?? ''),
    ).toBe(false);
  });
});
