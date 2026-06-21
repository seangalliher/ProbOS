/** AD-1052 vitest — Browser Workstation overlay (HXI #11 middle tier).
 *
 * Mirrors the AD-1021 WorkstationPanel test: store-flag gated (mounted-but-null
 * when closed), Escape + header X close, and the AD-1022 launcher seam (the real
 * `nativeWorkstations` map resolves BrowserWorkstation for the `browser` type,
 * NOT the honest-degrade placeholder). HXI no-emoji guard asserted.
 */
import { describe, it, expect, afterEach, beforeEach } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import { BrowserWorkstationPanel } from './BrowserWorkstationPanel';
import { WorkstationLauncher, type WorkstationTypeView } from './WorkstationLauncher';
import { nativeWorkstations } from './nativeWorkstations';
import { useStore } from '../../store/useStore';

const EMOJI = /\p{Extended_Pictographic}/u;

beforeEach(() => {
  useStore.setState({ browserWorkstationOpen: true });
});

afterEach(() => {
  useStore.setState({ browserWorkstationOpen: false });
  cleanup();
});

describe('AD-1052 BrowserWorkstationPanel', () => {
  it('renders nothing when closed', () => {
    useStore.setState({ browserWorkstationOpen: false });
    const { container } = render(<BrowserWorkstationPanel />);
    expect(container.firstChild).toBeNull();
    expect(screen.queryByTestId('browser-workstation-panel')).toBeNull();
  });

  it('renders the overlay + the BrowserWorkstation when open', () => {
    render(<BrowserWorkstationPanel />);
    expect(screen.getByTestId('browser-workstation-panel')).toBeTruthy();
    expect(screen.getByTestId('browser-workstation')).toBeTruthy();
    // The embedded empty-state is the default body (no URL committed yet).
    expect(screen.getByTestId('browser-empty')).toBeTruthy();
  });

  it('closes via Escape (browserWorkstationOpen -> false)', async () => {
    render(<BrowserWorkstationPanel />);
    fireEvent.keyDown(window, { key: 'Escape' });
    await waitFor(() => expect(useStore.getState().browserWorkstationOpen).toBe(false));
    expect(screen.queryByTestId('browser-workstation-panel')).toBeNull();
  });

  it('closes via the header X (browserWorkstationOpen -> false)', async () => {
    render(<BrowserWorkstationPanel />);
    fireEvent.click(screen.getByTestId('browser-workstation-close'));
    await waitFor(() => expect(useStore.getState().browserWorkstationOpen).toBe(false));
    expect(screen.queryByTestId('browser-workstation-panel')).toBeNull();
  });

  it('opens BrowserWorkstation through the AD-1022 launcher seam (nativeWorkstations)', async () => {
    const fetchTypes = async (): Promise<WorkstationTypeView[]> => [
      { id: 'browser', label: 'Browser', tier: 'oss', available: true, render_kind: 'native' },
    ];
    render(<WorkstationLauncher deps={{ fetchTypes, nativeComponents: nativeWorkstations }} />);
    await waitFor(() => screen.getByTestId('workstation-type-browser'));
    fireEvent.click(screen.getByTestId('workstation-type-browser'));
    // The registered OSS component renders — NOT the honest-degrade placeholder.
    expect(screen.getByTestId('browser-workstation')).toBeTruthy();
    expect(screen.queryByTestId('workstation-unavailable')).toBeNull();
  });

  it('uses no emoji (HXI #3)', () => {
    const { container } = render(<BrowserWorkstationPanel />);
    expect(EMOJI.test(container.textContent ?? '')).toBe(false);
  });
});
