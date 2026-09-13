/** AD-1052 vitest — Browser Workstation overlay (HXI #11 middle tier).
 *
 * Mirrors the AD-1021 WorkstationPanel test: store-flag gated (mounted-but-null
 * when closed), Escape + header X close, and the AD-1022 launcher seam (the real
 * `nativeWorkstations` map resolves BrowserWorkstation for the `browser` type,
 * NOT the honest-degrade placeholder). HXI no-emoji guard asserted.
 */
import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest';
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
  vi.unstubAllGlobals();
});

function _sessionFetch(): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn(async () => ({
    ok: true, status: 200,
    json: async () => ({
      enabled: true, input_forwarding_enabled: true, authority_basis: 'single_operator_compatibility',
      sessions: [{
        session_id: 'selected', agent_id: 'captain', owner_id: 'captain',
        streaming_url: '/api/browser/sessions/selected/stream', last_url: 'http://127.0.0.1/',
        state: 'active', sharing_scope: 'legacy_ambient_binding', recording_state: 'disabled',
        recording_scope: 'session_owned', pending_work: 0, expires_at: 4102444800, external_browser: false,
      }],
    }),
  }));
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

describe('AD-1052 BrowserWorkstationPanel', () => {
  it.each(['Escape', 'X'])('withdraws an active overlay viewer via %s without any end request', async (gesture) => {
    const fetchMock = _sessionFetch();
    render(<BrowserWorkstationPanel />);
    fireEvent.click(await screen.findByTestId('browser-watch-session-selected'));
    fireEvent.load(screen.getByTestId('browser-stream-panel-img'));
    expect(screen.getByTestId('browser-stream-panel-img').getAttribute('src')).toContain('/selected/stream');
    if (gesture === 'Escape') fireEvent.keyDown(window, { key: 'Escape' });
    else fireEvent.click(screen.getByTestId('browser-workstation-close'));
    expect(screen.queryByTestId('browser-workstation-panel')).toBeNull();
    expect(fetchMock.mock.calls.length).toBeGreaterThan(0);
    expect(fetchMock.mock.calls.every((call) => call[0] === '/api/browser/sessions' && !call[1]?.method)).toBe(true);
  });

  it('cancels the confirmation with Escape without closing the overlay or sending end', async () => {
    const fetchMock = _sessionFetch();
    render(<BrowserWorkstationPanel />);
    fireEvent.click(await screen.findByTestId('browser-watch-session-selected'));
    fireEvent.click(screen.getByRole('button', { name: 'End session' }));
    expect(screen.getByRole('dialog').textContent).toContain('single operator compatibility');
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.getByTestId('browser-workstation-panel')).toBeTruthy();
    expect(fetchMock.mock.calls.every((call) => !call[1]?.method)).toBe(true);
  });

  it('withdraws the driving viewer on bubbled Escape without ending the session', async () => {
    const fetchMock = _sessionFetch();
    render(<BrowserWorkstationPanel />);
    fireEvent.click(await screen.findByTestId('browser-watch-session-selected'));
    const image = screen.getByTestId('browser-stream-panel-img');
    fireEvent.load(image);
    fireEvent.click(screen.getByRole('button', { name: 'Drive the browser' }));
    expect(image.getAttribute('data-driving')).toBe('true');
    image.focus();
    fireEvent.keyDown(image, { key: 'Escape' });
    expect(screen.queryByTestId('browser-workstation-panel')).toBeNull();
    expect(fetchMock.mock.calls.some((call) => call[0].endsWith('/input'))).toBe(true);
    expect(fetchMock.mock.calls.some((call) => call[0].endsWith('/end'))).toBe(false);
  });

  it('exposes lifecycle controls in the real launcher and unmounts without an end request', async () => {
    const fetchMock = _sessionFetch();
    const fetchTypes = async (): Promise<WorkstationTypeView[]> => [
      { id: 'browser', label: 'Browser', tier: 'oss', available: true, render_kind: 'native' },
    ];
    const view = render(<WorkstationLauncher deps={{ fetchTypes, nativeComponents: nativeWorkstations }} />);
    fireEvent.click(await screen.findByTestId('workstation-type-browser'));
    fireEvent.click(await screen.findByTestId('browser-watch-session-selected'));
    expect(screen.getByRole('button', { name: 'Stop watching' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Hand to crew' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'End session' }));
    expect(screen.getByRole('dialog')).toBeTruthy();
    view.unmount();
    expect(fetchMock.mock.calls.every((call) => !call[1]?.method)).toBe(true);
  });

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
