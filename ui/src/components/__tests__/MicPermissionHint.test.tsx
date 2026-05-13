import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, fireEvent, cleanup } from '@testing-library/react';

// AD-736: MicPermissionHint component tests.

// Subscriber + setter captured for direct state-machine driving.
let _captured: ((s: 'pending' | 'granted' | 'denied' | 'unavailable') => void)
  | null = null;

vi.mock('../../audio/wakeWord', () => ({
  onMicPermissionState: vi.fn(
    (fn: (s: 'pending' | 'granted' | 'denied' | 'unavailable') => void) => {
      _captured = fn;
      fn('pending');
      return () => {
        _captured = null;
      };
    },
  ),
}));

import { MicPermissionHint } from '../MicPermissionHint';

describe('MicPermissionHint (AD-736)', () => {
  beforeEach(() => {
    _captured = null;
    localStorage.clear();
  });
  afterEach(() => {
    cleanup();
    localStorage.clear();
  });

  it('renders only for denied or unavailable states', () => {
    const { container, rerender } = render(<MicPermissionHint />);
    // pending → nothing
    expect(
      container.querySelector('[data-testid="mic-permission-hint"]'),
    ).toBeNull();

    // granted → still nothing
    _captured?.('granted');
    rerender(<MicPermissionHint />);
    expect(
      container.querySelector('[data-testid="mic-permission-hint"]'),
    ).toBeNull();

    // denied → renders with data-state="denied"
    _captured?.('denied');
    rerender(<MicPermissionHint />);
    const denied = container.querySelector(
      '[data-testid="mic-permission-hint"]',
    );
    expect(denied).not.toBeNull();
    expect(denied?.getAttribute('data-state')).toBe('denied');

    // unavailable → renders with data-state="unavailable"
    _captured?.('unavailable');
    rerender(<MicPermissionHint />);
    const unavail = container.querySelector(
      '[data-testid="mic-permission-hint"]',
    );
    expect(unavail).not.toBeNull();
    expect(unavail?.getAttribute('data-state')).toBe('unavailable');
  });

  it('denied hint dismiss persists across remount via localStorage', () => {
    const first = render(<MicPermissionHint />);
    _captured?.('denied');
    first.rerender(<MicPermissionHint />);

    const dismiss = first.container.querySelector(
      '[data-testid="mic-permission-dismiss"]',
    );
    expect(dismiss).not.toBeNull();
    fireEvent.click(dismiss!);
    first.rerender(<MicPermissionHint />);
    expect(
      first.container.querySelector('[data-testid="mic-permission-hint"]'),
    ).toBeNull();
    first.unmount();

    // Remount; localStorage still says dismissed.
    expect(localStorage.getItem('hxi_mic_hint_dismissed')).toBe('1');
    const second = render(<MicPermissionHint />);
    _captured?.('denied');
    second.rerender(<MicPermissionHint />);
    expect(
      second.container.querySelector('[data-testid="mic-permission-hint"]'),
    ).toBeNull();
  });
});
