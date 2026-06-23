/** AD-841a vitest — FullSystem host mount of the AD-841 DesktopConsole.
 *
 * The thin mount surfaces the read-only Desktop Console inside the System
 * Management view, beside ServicesGrid. FullSystem renders <DesktopConsole/>
 * with NO fetchImpl, so the console uses the global `fetch` — these tests stub
 * `global.fetch` with a deterministic URL router (desktop OFF payload + empty
 * host shapes) and restore it in afterEach. Also verifies the existing System
 * view (heading + ServicesGrid header) is unaffected, and that the System view
 * stays reachable via the engineering-system station launch.
 */
import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest';
import { render, screen, cleanup, waitFor } from '@testing-library/react';
import { FullSystem } from './FullSystem';
import { buildBridgeStations } from './stations';
import { useStore } from '../../store/useStore';

// The GET /api/desktop/status OFF payload (mirrors DesktopStatusView). The calm
// "Off" readout still wraps in the desktop-console panelShell, so the mount is
// observable via the desktop-console testid.
const DESKTOP_OFF = {
  enabled: false,
  active: false,
  tray: { active: false, autostart: false },
  hotkey: { active: false, binding: '' },
  notifications: { active: false, timeout_sec: 0 },
  quiet_hours: { start: '', end: '' },
  autostart_enabled: false,
  lock: { name: '', present: false },
};

function res(body: unknown, ok = true, status = 200) {
  return { ok, status, json: async () => body } as Response;
}

// Deterministic URL router for the host fetches: desktop status → OFF, the
// ServicesGrid + ThreadTable host fetches → empty, everything else → {}.
function makeRouter() {
  return vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input.toString();
    if (url.includes('/api/desktop/status')) return Promise.resolve(res(DESKTOP_OFF));
    if (url.includes('/api/system/services')) return Promise.resolve(res({ services: [] }));
    if (url.includes('/api/wardroom/activity')) return Promise.resolve(res({ threads: [] }));
    return Promise.resolve(res({}));
  });
}

describe('FullSystem (AD-841a desktop console mount)', () => {
  let originalFetch: typeof global.fetch;

  beforeEach(() => {
    originalFetch = global.fetch;
    global.fetch = makeRouter() as unknown as typeof fetch;
  });

  afterEach(() => {
    cleanup();
    global.fetch = originalFetch;
    useStore.setState({ mainViewer: 'canvas' });
  });

  it('mounts_desktop_console_in_system_view', async () => {
    render(<FullSystem />);
    await waitFor(() =>
      expect(screen.getByTestId('desktop-console')).toBeInTheDocument(),
    );
  });

  it('host_view_unaffected', async () => {
    render(<FullSystem />);
    await waitFor(() =>
      expect(screen.getByTestId('desktop-console')).toBeInTheDocument(),
    );
    // The System Management heading and the ServicesGrid header both survive.
    expect(screen.getByText('System Management')).toBeInTheDocument();
    expect(screen.getByText('SERVICES')).toBeInTheDocument();
  });

  it('reachable_via_engineering_system_launch', () => {
    const stations = buildBridgeStations({
      dmChannelCount: 0,
      kanbanCount: 0,
      totalUnread: 0,
    });
    const engineering = stations.find((s) => s.id === 'engineering');
    expect(engineering).toBeDefined();
    const action = engineering!.actions.find((a) => a.id === 'engineering-system');
    expect(action).toBeDefined();

    action!.onInvoke();
    expect(useStore.getState().mainViewer).toBe('system');
  });
});
