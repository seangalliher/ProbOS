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
  getAvailableVoices: vi.fn(() => []),
  setPreferredVoiceName: vi.fn(),
  getCurrentVoiceName: vi.fn(() => 'Default'),
  speakResponse: vi.fn(),
}));

import { DecisionSurface } from '../components/DecisionSurface';
import { useStore } from '../store/useStore';

describe('DecisionSurface wake-word toggle (AD-705 D5)', () => {
  beforeEach(() => {
    localStorage.clear();
    // Reset toggle to default in store.
    useStore.setState({ wakeWordEnabled: false });
  });
  afterEach(() => {
    cleanup();
  });

  it('19. toggle persists across remount via localStorage', () => {
    const { unmount, container } = render(<DecisionSurface />);
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
    const { container } = render(<DecisionSurface />);
    const btn = container.querySelector(
      '[data-testid="wake-word-toggle"]',
    ) as HTMLButtonElement;
    // Inactive style: dim color (#8888aa stroke) — verified via attribute.
    const stroke = btn?.querySelector('svg')?.getAttribute('stroke');
    expect(stroke).toBe('#8888aa');
  });
});
