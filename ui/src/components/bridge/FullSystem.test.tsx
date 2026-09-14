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
import { render, screen, cleanup, waitFor, act, fireEvent, within } from '@testing-library/react';
import { FullSystem } from './FullSystem';
import { BridgeSystem, ServiceReadiness } from './BridgeSystem';
import { RESOURCE_TIMEOUT_MS, idleResource } from '../../utils/resourceState';
import type { ServiceStatusResult } from '../../hooks/useServiceStatus';
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

function servicePayload(nats: 'ready' | 'unavailable' = 'ready') {
  return {
    services: ['Ward Room', 'Episodic Memory', 'Trust Network', 'Knowledge Store', 'Cognitive Journal',
      'Codebase Index', 'Skill Framework', 'Skill Service', 'ACM', 'Hebbian Router', 'Intent Bus', 'LLM Proxy']
      .map(name => ({ name, status: 'online' })),
    integrations: ['records', 'knowledge_browser', 'skill_requests', 'ontology_graph', 'spatial_layout', 'nats'].map(id => ({
      id, state: id === 'nats' ? nats : 'initialized',
      scope: id === 'nats' ? 'connection' : 'initialization',
      code: id === 'nats' ? (nats === 'ready' ? 'nats.connected' : 'nats.disconnected') : `${id}.initialized`,
      message: id === 'nats' ? (nats === 'ready' ? 'Connected. JetStream operations have not been checked.' : 'Connection unavailable. Retry the request.')
        : 'Initialized. Read operations have not been checked.',
      retryable: id === 'nats' && nats === 'unavailable',
    })),
    startup_warnings: ['Historical warning remains unchanged'],
  };
}

describe.each([['BridgeSystem', BridgeSystem], ['FullSystem', FullSystem]] as const)('%s service readiness (#1368)', (_name, View) => {
  let originalFetch: typeof global.fetch;
  let serviceFetch: ReturnType<typeof vi.fn<typeof fetch>>;

  beforeEach(() => {
    vi.useFakeTimers();
    originalFetch = global.fetch;
    serviceFetch = vi.fn<typeof fetch>().mockImplementation(() => Promise.resolve(res(servicePayload())));
    const otherFetch = makeRouter();
    global.fetch = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes('/api/system/services')) return serviceFetch(input, init);
      return otherFetch(input);
    }) as typeof fetch;
  });

  afterEach(() => {
    cleanup();
    vi.clearAllTimers();
    vi.useRealTimers();
    global.fetch = originalFetch;
  });

  async function advance(milliseconds = 0): Promise<void> {
    await act(async () => { await vi.advanceTimersByTimeAsync(milliseconds); });
  }

  function region(): HTMLElement {
    return screen.getByRole('region', { name: 'System services' });
  }

  it('labels initialized population and scoped observations, preserving healthy cadence', async () => {
    render(<View />);
    expect(within(region()).getByRole('status')).toHaveTextContent('Loading.');
    await advance();
    expect(serviceFetch).toHaveBeenCalledTimes(1);
    expect(region()).toHaveTextContent('12/12 initialized components (legacy population)');
    expect(region()).toHaveTextContent('5 initialization checks, 1 current connection check');
    expect(within(region()).getAllByRole('listitem')).toHaveLength(6);
    expect(region()).not.toHaveTextContent(/services operational|12\/12 online|all ready/i);
    expect(within(region()).getByRole('listitem', { name: 'NATS connection' })).toHaveTextContent('JetStream operations have not been checked');
    await advance(9999);
    expect(serviceFetch).toHaveBeenCalledTimes(1);
    await advance(1);
    expect(serviceFetch).toHaveBeenCalledTimes(2);
  });

  it.each([null, {}, { services: null }, { services: [{}] }, { services: [{ name: '', status: 'online' }] }])('rejects malformed successful payload %j', async body => {
    serviceFetch.mockResolvedValue(res(body));
    render(<View />);
    await advance();
    expect(within(region()).getByRole('status')).toHaveTextContent('Request failed.');
    expect(region()).not.toHaveTextContent('No components reported.');
  });

  it.each([undefined, [], [{ id: 'nats', state: 'ready' }], servicePayload().integrations.map(entry => ({ ...entry, scope: 'invalid' }))])('keeps absent or malformed metadata unknown (%j)', async integrations => {
    serviceFetch.mockResolvedValue(res({ services: servicePayload().services, integrations }));
    render(<View />);
    await advance();
    expect(region()).toHaveTextContent('12/12 initialized components');
    expect(within(region()).getByRole('status')).toHaveTextContent('Integration readiness unknown.');
    expect(region()).toHaveTextContent('Integration observations unavailable.');
    expect(region()).not.toHaveTextContent('5 initialization checks, 1 current connection check');
    for (const row of within(region()).getAllByRole('listitem')) expect(row).toHaveTextContent('Readiness unknown.');
  });

  it('accepts zero legacy population without claiming healthy integrations', async () => {
    serviceFetch.mockResolvedValue(res({ services: [] }));
    render(<View />);
    await advance();
    expect(region()).toHaveTextContent('0/0 initialized components');
    expect(region()).toHaveTextContent('No components reported.');
    expect(region()).toHaveTextContent('Integration readiness unknown.');
  });

  it.each([500, 503])('classifies HTTP %i without exposing diagnostics', async code => {
    serviceFetch.mockResolvedValue(res({ error: 'secret internal diagnostic' }, false, code));
    render(<View />);
    await advance();
    expect(within(region()).getByRole('status')).toHaveTextContent(code === 503 ? 'Unavailable.' : 'Request failed.');
    expect(region()).not.toHaveTextContent('secret internal diagnostic');
  });

  it.each(['disabled', 'unauthorized', 'unavailable', 'failed'])(
    'keeps successful status reads current when an integration is %s', async state => {
      const payload = servicePayload();
      serviceFetch.mockResolvedValue(res({
        ...payload,
        integrations: payload.integrations.map(entry => entry.id === 'knowledge_browser'
          ? { ...entry, state, retryable: state === 'unavailable' || state === 'failed' } : entry),
      }));
      render(<View />);
      await advance();
      expect(serviceFetch).toHaveBeenCalledTimes(1);
      expect(region()).not.toHaveTextContent('Automatic refresh paused.');
      await advance(40_000);
      expect(serviceFetch).toHaveBeenCalledTimes(5);
      expect(region()).not.toHaveTextContent('Automatic refresh paused.');
    },
  );

  it('classifies invalid JSON as failed', async () => {
    serviceFetch.mockResolvedValue(new Response('secret invalid JSON', { status: 200 }));
    render(<View />);
    await advance();
    expect(within(region()).getByRole('status')).toHaveTextContent('Request failed.');
    expect(region()).not.toHaveTextContent('secret');
  });

  it('keeps the healthy cadence after a delayed successful degraded observation', async () => {
    let resolveRead!: (response: Response) => void;
    serviceFetch.mockImplementationOnce(() => new Promise<Response>(resolve => { resolveRead = resolve; }));
    render(<View />);
    await advance(4_000);
    expect(serviceFetch).toHaveBeenCalledTimes(1);
    await act(async () => { resolveRead(res(servicePayload('unavailable'))); });
    expect(region()).toHaveTextContent('Integration checks degraded.');
    await advance(9_999);
    expect(serviceFetch).toHaveBeenCalledTimes(1);
    await advance(1);
    expect(serviceFetch).toHaveBeenCalledTimes(2);
    expect(region()).not.toHaveTextContent('Automatic refresh paused.');
  });

  it('retains a stale snapshot during failure and refresh, then recovers manually', async () => {
    render(<View />);
    await advance();
    serviceFetch.mockResolvedValue(res({ error: 'Unavailable' }, false, 503));
    await advance(10_000);
    expect(region()).toHaveTextContent('Stale snapshot.');
    expect(region()).toHaveTextContent('Last known: 12/12 initialized components');
    let resolveRefresh!: (response: Response) => void;
    serviceFetch.mockImplementation(() => new Promise<Response>(resolve => { resolveRefresh = resolve; }));
    fireEvent.click(within(region()).getByRole('button', { name: 'Refresh service status' }));
    expect(region()).toHaveTextContent('Stale snapshot. Refreshing.');
    expect(within(region()).getByRole('button', { name: 'Refresh service status' })).toBeDisabled();
    await act(async () => { resolveRefresh(res(servicePayload())); });
    await advance();
    expect(region()).not.toHaveTextContent('Stale snapshot.');
    expect(region()).not.toHaveTextContent('Refreshing.');
  });

  it.each([401, 403])('removes cached content and stops on HTTP %i', async code => {
    render(<View />);
    await advance();
    serviceFetch.mockResolvedValue(res({ detail: 'secret' }, false, code));
    await advance(10_000);
    expect(region()).toHaveTextContent('Access denied. Request appropriate access.');
    expect(region()).not.toHaveTextContent('12/12');
    expect(region()).not.toHaveTextContent('Ward Room');
    await advance(120_000);
    expect(serviceFetch).toHaveBeenCalledTimes(2);
    serviceFetch.mockResolvedValue(res(servicePayload()));
    fireEvent.click(within(region()).getByRole('button', { name: 'Refresh service status' }));
    await advance();
    expect(region()).toHaveTextContent('12/12 initialized components');
  });

  it('stops immediately for authoritative disabled metadata, unlike legacy 503', async () => {
    serviceFetch.mockResolvedValue(res({ error: 'not available', availability: {
      state: 'disabled', code: 'records.disabled', message: 'secret', retryable: false,
    } }, false, 503));
    render(<View />);
    await advance();
    expect(region()).toHaveTextContent('Disabled. Review configuration with the operator.');
    expect(region()).not.toHaveTextContent('secret');
    await advance(120_000);
    expect(serviceFetch).toHaveBeenCalledTimes(1);
  });

  it('retries at 10 and 30 seconds only, survives rerenders, and resets on manual success', async () => {
    serviceFetch.mockResolvedValue(res({ error: 'Unavailable' }, false, 503));
    const view = render(<View />);
    await advance();
    expect(serviceFetch).toHaveBeenCalledTimes(1);
    await advance(9999);
    expect(serviceFetch).toHaveBeenCalledTimes(1);
    view.rerender(<View />);
    await advance(1);
    expect(serviceFetch).toHaveBeenCalledTimes(2);
    await advance(19_999);
    expect(serviceFetch).toHaveBeenCalledTimes(2);
    await advance(1);
    expect(serviceFetch).toHaveBeenCalledTimes(3);
    expect(region()).toHaveTextContent('Automatic refresh paused.');
    view.rerender(<View />);
    await advance(120_000);
    expect(serviceFetch).toHaveBeenCalledTimes(3);
    serviceFetch.mockResolvedValue(res(servicePayload()));
    fireEvent.click(within(region()).getByRole('button', { name: 'Refresh service status' }));
    await advance();
    expect(serviceFetch).toHaveBeenCalledTimes(4);
    await advance(10_000);
    expect(serviceFetch).toHaveBeenCalledTimes(5);
    serviceFetch.mockResolvedValue(res({}, false, 503));
    await advance(10_000);
    await advance(30_000);
    expect(serviceFetch).toHaveBeenCalledTimes(8);
    await advance(60_000);
    expect(serviceFetch).toHaveBeenCalledTimes(8);
  });

  it('bounds hung reads, prevents overlap, and ignores late completion', async () => {
    let resolveOld!: (response: Response) => void;
    let oldSignal: AbortSignal | undefined;
    serviceFetch.mockImplementationOnce((_input, init) => {
      oldSignal = init?.signal ?? undefined;
      return new Promise<Response>(resolve => { resolveOld = resolve; });
    });
    render(<View />);
    await advance(10_000);
    expect(serviceFetch).toHaveBeenCalledTimes(1);
    fireEvent.click(within(region()).getByRole('button', { name: 'Refresh service status' }));
    expect(serviceFetch).toHaveBeenCalledTimes(1);
    await advance(RESOURCE_TIMEOUT_MS - 10_000);
    expect(oldSignal?.aborted).toBe(true);
    expect(region()).toHaveTextContent('Unavailable.');
    await advance(10_000);
    expect(serviceFetch).toHaveBeenCalledTimes(2);
    expect(region()).toHaveTextContent('12/12 initialized components');
    await act(async () => { resolveOld(res({ services: [] })); });
    expect(region()).toHaveTextContent('12/12 initialized components');
  });

  it('aborts on unmount, ignores late publication, and reloads on reentry', async () => {
    let resolveOld!: (response: Response) => void;
    let oldSignal: AbortSignal | undefined;
    serviceFetch.mockImplementationOnce((_input, init) => {
      oldSignal = init?.signal ?? undefined;
      return new Promise<Response>(resolve => { resolveOld = resolve; });
    });
    const first = render(<View />);
    expect(serviceFetch).toHaveBeenCalledTimes(1);
    first.unmount();
    expect(oldSignal?.aborted).toBe(true);
    await act(async () => { resolveOld(res({ services: [] })); });
    await advance(120_000);
    expect(serviceFetch).toHaveBeenCalledTimes(1);
    render(<View />);
    await advance();
    expect(serviceFetch).toHaveBeenCalledTimes(2);
    expect(region()).toHaveTextContent('12/12 initialized components');
  });

  it('uses current NATS connection with unchanged other rows and historical warnings', async () => {
    const ready = servicePayload();
    const unavailable = servicePayload('unavailable');
    expect(unavailable.services).toEqual(ready.services);
    expect(unavailable.startup_warnings).toEqual(ready.startup_warnings);
    expect(unavailable.integrations.slice(0, 5)).toEqual(ready.integrations.slice(0, 5));
    serviceFetch.mockResolvedValueOnce(res(ready)).mockResolvedValueOnce(res(unavailable)).mockResolvedValue(res(ready));
    render(<View />);
    await advance();
    const row = (): HTMLElement => within(region()).getByRole('listitem', { name: 'NATS connection' });
    expect(row()).toHaveTextContent('Connected.');
    const otherRows = within(region()).getAllByRole('listitem').slice(0, 5).map(entry => entry.textContent);
    await advance(10_000);
    expect(serviceFetch).toHaveBeenCalledTimes(2);
    expect(row()).toHaveTextContent('Unavailable.');
    expect(region()).toHaveTextContent('Integration checks degraded.');
    expect(within(region()).getAllByRole('listitem').slice(0, 5).map(entry => entry.textContent)).toEqual(otherRows);
    await advance(10_000);
    expect(serviceFetch).toHaveBeenCalledTimes(3);
    expect(row()).toHaveTextContent('Connected.');
    expect(region()).not.toHaveTextContent('Integration checks degraded.');
  });
});

describe('ServiceReadiness scope population', () => {
  afterEach(() => cleanup());

  const status: ServiceStatusResult = {
    resource: idleResource('/api/system/services'), services: [], summary: 'Scoped observations.',
    population: '0/0 initialized components', paused: false, refresh: () => {},
    integrations: [
      { id: 'records', label: 'Records access', state: 'initialized', scope: 'initialization', message: 'Initialized.' },
      { id: 'knowledge_browser', label: 'Knowledge Browser', state: 'disabled', scope: 'initialization', message: 'Disabled.' },
      { id: 'nats', label: 'NATS', state: 'unavailable', scope: 'connection', message: 'Unavailable.' },
    ],
  };

  it('derives scope counts from supplied validated rows, including unavailable observations', () => {
    const view = render(<ServiceReadiness status={status} />);
    expect(view.container).toHaveTextContent('2 initialization checks, 1 current connection check.');
    expect(view.container).not.toHaveTextContent('5 initialization checks');
    view.rerender(<ServiceReadiness status={{ ...status, integrations: status.integrations.slice(0, 2) }} />);
    expect(view.container).toHaveTextContent('2 initialization checks, 0 current connection checks.');
  });

  it.each([{ integrations: [] }, { integrations: [{ ...status.integrations[0], state: 'unknown' as const }] }])('keeps empty or unknown scopes unknown (%j)', ({ integrations }) => {
    const view = render(<ServiceReadiness status={{ ...status, integrations }} />);
    expect(view.container).toHaveTextContent('Integration observations unavailable.');
    expect(view.container).not.toHaveTextContent('initialization checks');
  });
});
