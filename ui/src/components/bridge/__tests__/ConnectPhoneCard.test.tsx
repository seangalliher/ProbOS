/**
 * AD-708f: ConnectPhoneCard tests.
 *
 * BF-287: real ``useSettingsStore`` slice (not MagicMock). The store is seeded
 * directly; nothing else is mocked beyond `window.location.port` (to make the
 * client-side URL deterministic) and `navigator.clipboard` (cases 4 & 5).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';

import ConnectPhoneCard from '../ConnectPhoneCard';
import { useSettingsStore } from '../../../store/useSettingsStore';

const ORIGINAL_LOCATION = window.location;
const ORIGINAL_CLIPBOARD = navigator.clipboard;

function seed(snapshot: any): void {
  useSettingsStore.setState({ snapshot, loaded: true } as any);
}

beforeEach(() => {
  useSettingsStore.setState({ snapshot: null, loaded: false } as any);
  // Stub the port so the client-side URL is deterministic (the component only
  // reads `window.location.port`).
  Object.defineProperty(window, 'location', {
    value: { ...window.location, port: '18900' },
    configurable: true,
    writable: true,
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  Object.defineProperty(window, 'location', {
    value: ORIGINAL_LOCATION,
    configurable: true,
    writable: true,
  });
  Object.defineProperty(navigator, 'clipboard', {
    value: ORIGINAL_CLIPBOARD,
    configurable: true,
    writable: true,
  });
  useSettingsStore.setState({ snapshot: null, loaded: false } as any);
});

describe('ConnectPhoneCard (AD-708f)', () => {
  it('renders the .local address when discovery is enabled', () => {
    seed({ config: { discovery: { enabled: true, hostname: 'probos' } } });
    render(<ConnectPhoneCard />);
    expect(screen.getByTestId('connect-phone-card')).toBeTruthy();
    const url = screen.getByTestId('connect-phone-url').textContent ?? '';
    expect(url).toContain('http://probos.local');
    expect(url).toContain(':18900');
  });

  it('is absent when discovery is disabled', () => {
    seed({ config: { discovery: { enabled: false, hostname: 'probos' } } });
    render(<ConnectPhoneCard />);
    expect(screen.queryByTestId('connect-phone-card')).toBeNull();
  });

  it('is absent when the snapshot is null (byte-identical-off)', () => {
    useSettingsStore.setState({ snapshot: null, loaded: false } as any);
    render(<ConnectPhoneCard />);
    expect(screen.queryByTestId('connect-phone-card')).toBeNull();
  });

  it('copy button writes the URL to the clipboard', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
      writable: true,
    });
    seed({ config: { discovery: { enabled: true, hostname: 'probos' } } });
    render(<ConnectPhoneCard />);
    fireEvent.click(screen.getByTestId('connect-phone-copy'));
    // onCopy is async; flush the microtask queue before asserting.
    await Promise.resolve();
    expect(writeText).toHaveBeenCalledWith('http://probos.local:18900');
  });

  it('does not throw when navigator.clipboard is undefined', () => {
    Object.defineProperty(navigator, 'clipboard', {
      value: undefined,
      configurable: true,
      writable: true,
    });
    seed({ config: { discovery: { enabled: true, hostname: 'probos' } } });
    render(<ConnectPhoneCard />);
    expect(() => fireEvent.click(screen.getByTestId('connect-phone-copy'))).not.toThrow();
  });
});
