/** AD-1052 vitest — Browser/Web-App Workstation (embedded-iframe mode + the
 *  unifying mode model).
 *
 * Self-contained component (ignores doc). Asserts: the mode model (Embedded
 * active, Watch/Bridge disabled), URL commit -> sandboxed iframe with the
 * normalized src, the http(s) scheme allowlist (defense-in-depth), the
 * empty/honest-degrade state, data-testids, and the HXI no-emoji guard.
 */
import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor, act, within } from '@testing-library/react';
import { BrowserWorkstation, _normalizeUrl } from './BrowserWorkstation';

const EMOJI = /\p{Extended_Pictographic}/u;

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('AD-1052 BrowserWorkstation', () => {
  it('defaults to Embedded active; Watch and Bridge enabled (the mode model)', () => {
    render(<BrowserWorkstation typeId="browser" />);
    const embedded = screen.getByTestId('browser-mode-embedded') as HTMLButtonElement;
    const watch = screen.getByTestId('browser-mode-watch') as HTMLButtonElement;
    const bridge = screen.getByTestId('browser-mode-bridge') as HTMLButtonElement;
    expect(embedded.disabled).toBe(false);
    expect(embedded.getAttribute('aria-pressed')).toBe('true');
    expect(watch.disabled).toBe(false); // AD-1052a flipped Watch on
    expect(bridge.disabled).toBe(false); // AD-1052b flipped Bridge on
  });

  it('shows the empty / honest-degrade state before any URL (no iframe)', () => {
    render(<BrowserWorkstation typeId="browser" />);
    expect(screen.getByTestId('browser-empty')).toBeTruthy();
    expect(screen.getByTestId('browser-empty').textContent).toContain('X-Frame-Options');
    expect(screen.queryByTestId('browser-frame')).toBeNull();
  });

  it('commits a valid URL -> a sandboxed iframe with the normalized src', () => {
    render(<BrowserWorkstation typeId="browser" />);
    fireEvent.change(screen.getByTestId('browser-url-input'), { target: { value: 'https://example.com' } });
    fireEvent.click(screen.getByTestId('browser-go'));
    const frame = screen.getByTestId('browser-frame') as HTMLIFrameElement;
    expect(frame.getAttribute('src')).toBe('https://example.com');
    expect(frame.getAttribute('sandbox')).toBe('allow-scripts allow-same-origin allow-forms allow-popups');
    expect(frame.getAttribute('referrerpolicy')).toBe('no-referrer');
    expect(screen.queryByTestId('browser-empty')).toBeNull();
  });

  it('prepends https:// for a scheme-less host', () => {
    render(<BrowserWorkstation typeId="browser" />);
    fireEvent.change(screen.getByTestId('browser-url-input'), { target: { value: 'example.com' } });
    fireEvent.click(screen.getByTestId('browser-go'));
    expect((screen.getByTestId('browser-frame') as HTMLIFrameElement).getAttribute('src')).toBe('https://example.com');
    expect(screen.queryByTestId('browser-url-error')).toBeNull();
  });

  it('rejects a javascript: URL -> error notice, no iframe', () => {
    render(<BrowserWorkstation typeId="browser" />);
    fireEvent.change(screen.getByTestId('browser-url-input'), { target: { value: 'javascript:alert(1)' } });
    fireEvent.click(screen.getByTestId('browser-go'));
    expect(screen.getByTestId('browser-url-error').textContent).toContain('http(s)');
    expect(screen.queryByTestId('browser-frame')).toBeNull();
  });

  it('_normalizeUrl enforces the http(s) scheme allowlist', () => {
    expect(_normalizeUrl('file:///etc/passwd')).toBeNull();
    expect(_normalizeUrl('data:text/html,<script>1</script>')).toBeNull();
    expect(_normalizeUrl('about:blank')).toBeNull();
    expect(_normalizeUrl('   ')).toBeNull();
    expect(_normalizeUrl('https://ok.test/path')).toBe('https://ok.test/path');
    expect(_normalizeUrl('ok.test')).toBe('https://ok.test');
  });

  it('clicking Bridge switches to bridge mode and shows the endpoint input', () => {
    render(<BrowserWorkstation typeId="browser" />);
    fireEvent.click(screen.getByTestId('browser-mode-bridge'));
    expect((screen.getByTestId('browser-mode-bridge') as HTMLButtonElement).getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByTestId('browser-bridge-endpoint')).toBeTruthy();
    // The AD-1052 'browser-mode-pending' placeholder div is gone.
    expect(screen.queryByTestId('browser-mode-pending')).toBeNull();
  });

  it('uses no emoji (HXI #3) and exposes data-testids on the interactive controls', () => {
    const { container } = render(<BrowserWorkstation typeId="browser" />);
    expect(EMOJI.test(container.textContent ?? '')).toBe(false);
    expect(screen.getByTestId('browser-url-input')).toBeTruthy();
    expect(screen.getByTestId('browser-go')).toBeTruthy();
    expect(screen.getByTestId('browser-mode-embedded')).toBeTruthy();
  });
});

type _Sessions = {
  enabled: boolean;
  sessions: { session_id: string; agent_id: string; streaming_url: string | null; last_url: string; state?: 'active' }[];
  input_forwarding_enabled?: boolean;
};

describe('BF-694 the embedded URL bar is scoped to embedded mode', () => {
  /* The embedded URL input rendered unconditionally. That was invisible while
     'embedded' was the default mode; AD-1161 made 'watch' the default and the
     Captain saw TWO address bars stacked — this one plus watch's own "Open a
     page". These fail against the pre-fix component. */

  it('hides the embedded URL bar and Go button in watch mode', () => {
    render(<BrowserWorkstation typeId="browser" />);
    fireEvent.click(screen.getByTestId('browser-mode-watch'));
    expect(screen.queryByTestId('browser-url-input')).toBeNull();
    expect(screen.queryByTestId('browser-go')).toBeNull();
  });

  it('hides the embedded URL bar and Go button in bridge mode', () => {
    render(<BrowserWorkstation typeId="browser" />);
    fireEvent.click(screen.getByTestId('browser-mode-bridge'));
    expect(screen.queryByTestId('browser-url-input')).toBeNull();
    expect(screen.queryByTestId('browser-go')).toBeNull();
  });

  it('keeps exactly one URL entry field in watch mode (the Open field)', () => {
    render(<BrowserWorkstation typeId="browser" />);
    fireEvent.click(screen.getByTestId('browser-mode-watch'));
    // The regression the Captain reported: two stacked address bars.
    const textInputs = screen
      .getAllByRole('textbox')
      .filter((el) => (el as HTMLInputElement).type !== 'hidden');
    expect(textInputs.length).toBe(1);
  });

  it('restores the embedded URL bar when switching back to embedded', () => {
    render(<BrowserWorkstation typeId="browser" />);
    fireEvent.click(screen.getByTestId('browser-mode-watch'));
    expect(screen.queryByTestId('browser-url-input')).toBeNull();
    fireEvent.click(screen.getByTestId('browser-mode-embedded'));
    expect(screen.getByTestId('browser-url-input')).toBeTruthy();
    expect(screen.getByTestId('browser-go')).toBeTruthy();
  });

  it('does not carry a stale URL error across a mode switch', () => {
    render(<BrowserWorkstation typeId="browser" />);
    fireEvent.change(screen.getByTestId('browser-url-input'), { target: { value: 'javascript:alert(1)' } });
    fireEvent.click(screen.getByTestId('browser-go'));
    expect(screen.getByTestId('browser-url-error')).toBeTruthy();
    fireEvent.click(screen.getByTestId('browser-mode-watch'));
    expect(screen.queryByTestId('browser-url-error')).toBeNull();
  });
});

describe('AD-1052a BrowserWorkstation watch mode', () => {
  it('clicking Watch sets aria-pressed and calls fetchSessions (DD-1 same-origin)', async () => {
    const fetchSessions = vi.fn(async (): Promise<_Sessions> => ({ enabled: true, sessions: [] }));
    render(<BrowserWorkstation typeId="browser" fetchSessions={fetchSessions} />);
    fireEvent.click(screen.getByTestId('browser-mode-watch'));
    expect((screen.getByTestId('browser-mode-watch') as HTMLButtonElement).getAttribute('aria-pressed')).toBe('true');
    await screen.findByTestId('browser-watch-empty');
    // AD-1161 added a mount probe that reuses this same fetch to pick the
    // default mode, so watch-enter is the SECOND call, not the first.
    expect(fetchSessions).toHaveBeenCalledTimes(2);
  });

  it('renders the session list and selecting one mounts the stream <img> with NO token (DD-1)', async () => {
    const fetchSessions = vi.fn(async (): Promise<_Sessions> => ({
      enabled: true,
      sessions: [{ session_id: 's1', agent_id: 'a1', streaming_url: '/api/browser/sessions/s1/stream', last_url: 'https://x.test' }],
    }));
    render(<BrowserWorkstation typeId="browser" fetchSessions={fetchSessions} />);
    fireEvent.click(screen.getByTestId('browser-mode-watch'));
    const row = await screen.findByTestId('browser-watch-session-s1');
    expect(row.textContent).toContain('a1');
    expect(row.textContent).toContain('https://x.test');
    fireEvent.click(row);
    const img = await screen.findByTestId('browser-stream-panel-img');
    const src = img.getAttribute('src') ?? '';
    expect(src).toBe('/api/browser/sessions/s1/stream');
    expect(src.includes('token=')).toBe(false); // DD-1: no token reaches browser JS
  });

  it('a session with no streaming_url honest-degrades to "Streaming not enabled"', async () => {
    const fetchSessions = vi.fn(async (): Promise<_Sessions> => ({
      enabled: true,
      sessions: [{ session_id: 's1', agent_id: 'a1', streaming_url: null, last_url: '' }],
    }));
    render(<BrowserWorkstation typeId="browser" fetchSessions={fetchSessions} />);
    fireEvent.click(screen.getByTestId('browser-mode-watch'));
    fireEvent.click(await screen.findByTestId('browser-watch-session-s1'));
    await screen.findByTestId('browser-stream-panel-unavailable');
    expect(screen.queryByTestId('browser-stream-panel-img')).toBeNull();
  });

  it('honest-degrades to disabled when the tool is off', async () => {
    const fetchSessions = vi.fn(async (): Promise<_Sessions> => ({ enabled: false, sessions: [] }));
    render(<BrowserWorkstation typeId="browser" fetchSessions={fetchSessions} />);
    fireEvent.click(screen.getByTestId('browser-mode-watch'));
    await screen.findByTestId('browser-watch-disabled');
    expect(screen.queryByTestId('browser-watch-empty')).toBeNull();
  });

  it('honest-degrades to empty when enabled with no sessions', async () => {
    const fetchSessions = vi.fn(async (): Promise<_Sessions> => ({ enabled: true, sessions: [] }));
    render(<BrowserWorkstation typeId="browser" fetchSessions={fetchSessions} />);
    fireEvent.click(screen.getByTestId('browser-mode-watch'));
    await screen.findByTestId('browser-watch-empty');
  });

  it('honest-degrades to unavailable when the fetch rejects', async () => {
    const fetchSessions = vi.fn(() => Promise.reject(new Error('boom')));
    render(<BrowserWorkstation typeId="browser" fetchSessions={fetchSessions} />);
    fireEvent.click(screen.getByTestId('browser-mode-watch'));
    await screen.findByTestId('browser-watch-unavailable');
  });

  it('Refresh re-fetches the session list (no auto-poll)', async () => {
    const fetchSessions = vi.fn(async (): Promise<_Sessions> => ({ enabled: true, sessions: [] }));
    render(<BrowserWorkstation typeId="browser" fetchSessions={fetchSessions} />);
    fireEvent.click(screen.getByTestId('browser-mode-watch'));
    await screen.findByTestId('browser-watch-empty');
    // AD-1161 mount probe + watch-enter = 2; the point of this test is that
    // nothing FURTHER fetches until the Captain clicks Refresh.
    await waitFor(() => expect(fetchSessions).toHaveBeenCalledTimes(2));
    const settled = fetchSessions.mock.calls.length;
    fireEvent.click(screen.getByTestId('browser-watch-refresh'));
    await waitFor(() => expect(fetchSessions).toHaveBeenCalledTimes(settled + 1));
  });

  it('the watch surface uses no emoji (HXI #3) and exposes its data-testids', async () => {
    const fetchSessions = vi.fn(async (): Promise<_Sessions> => ({
      enabled: true,
      sessions: [{ session_id: 's1', agent_id: 'a1', streaming_url: '/api/browser/sessions/s1/stream', last_url: 'https://x.test' }],
    }));
    const { container } = render(<BrowserWorkstation typeId="browser" fetchSessions={fetchSessions} />);
    fireEvent.click(screen.getByTestId('browser-mode-watch'));
    await screen.findByTestId('browser-watch-session-s1');
    expect(EMOJI.test(container.textContent ?? '')).toBe(false);
    expect(screen.getByTestId('browser-watch-refresh')).toBeTruthy();
    expect(screen.getByTestId('browser-watch-note')).toBeTruthy();
  });
});

type _Bridge = {
  connected: boolean;
  reason?: string | null;
  session_id?: string | null;
  streaming_url?: string | null;
};

describe('AD-1052b BrowserWorkstation bridge mode', () => {
  it('clicking Bridge shows the endpoint input (default), the consent note, and Connect', () => {
    render(<BrowserWorkstation typeId="browser" />);
    fireEvent.click(screen.getByTestId('browser-mode-bridge'));
    const ep = screen.getByTestId('browser-bridge-endpoint') as HTMLInputElement;
    expect(ep.value).toBe('http://127.0.0.1:9222');
    expect(screen.getByTestId('browser-bridge-consent-note').textContent).toContain('logged-in sessions');
    expect(screen.getByTestId('browser-bridge-connect')).toBeTruthy();
  });

  it('Connect calls connectBridge(endpoint) and mounts the stream <img> with NO token (DD-1)', async () => {
    const connectBridge = vi.fn(async (): Promise<_Bridge> => ({
      connected: true, session_id: 's9', streaming_url: '/api/browser/sessions/s9/stream',
    }));
    render(<BrowserWorkstation typeId="browser" connectBridge={connectBridge} fetchSessions={async () => _listing([_session('s9', { external_browser: true })])} />);
    fireEvent.click(screen.getByTestId('browser-mode-bridge'));
    fireEvent.click(screen.getByTestId('browser-bridge-connect'));
    const img = await screen.findByTestId('browser-stream-panel-img');
    expect(connectBridge).toHaveBeenCalledWith('http://127.0.0.1:9222');
    const src = img.getAttribute('src') ?? '';
    expect(src).toBe('/api/browser/sessions/s9/stream');
    expect(src.includes('token=')).toBe(false); // DD-1: no token reaches browser JS
  });

  it('connected with streaming_url:null honest-degrades to "Streaming not enabled"', async () => {
    const connectBridge = vi.fn(async (): Promise<_Bridge> => ({
      connected: true, session_id: 's9', streaming_url: null,
    }));
    render(<BrowserWorkstation typeId="browser" connectBridge={connectBridge} fetchSessions={async () => _listing([_session('s9', { external_browser: true, streaming_url: null })])} />);
    fireEvent.click(screen.getByTestId('browser-mode-bridge'));
    fireEvent.click(screen.getByTestId('browser-bridge-connect'));
    await screen.findByTestId('browser-stream-panel-unavailable');
    expect(screen.queryByTestId('browser-stream-panel-img')).toBeNull();
  });

  it('refused (connected:false) -> browser-bridge-reason shows the backend reason', async () => {
    const connectBridge = vi.fn(async (): Promise<_Bridge> => ({
      connected: false, reason: 'Bridge mode is disabled.',
    }));
    render(<BrowserWorkstation typeId="browser" connectBridge={connectBridge} />);
    fireEvent.click(screen.getByTestId('browser-mode-bridge'));
    fireEvent.click(screen.getByTestId('browser-bridge-connect'));
    const reason = await screen.findByTestId('browser-bridge-reason');
    expect(reason.textContent).toContain('Bridge mode is disabled.');
    expect(screen.queryByTestId('browser-stream-panel-img')).toBeNull();
  });

  it('connectBridge rejects -> browser-bridge-reason shows "Could not connect…"', async () => {
    const connectBridge = vi.fn(() => Promise.reject(new Error('boom')));
    render(<BrowserWorkstation typeId="browser" connectBridge={connectBridge} />);
    fireEvent.click(screen.getByTestId('browser-mode-bridge'));
    fireEvent.click(screen.getByTestId('browser-bridge-connect'));
    const reason = await screen.findByTestId('browser-bridge-reason');
    expect(reason.textContent).toContain('Could not connect');
  });

  it('the bridge surface uses no emoji (HXI #3), exposes its testids + the consent note (DD-2)', () => {
    const { container } = render(<BrowserWorkstation typeId="browser" />);
    fireEvent.click(screen.getByTestId('browser-mode-bridge'));
    expect(EMOJI.test(container.textContent ?? '')).toBe(false);
    expect(screen.getByTestId('browser-bridge-endpoint')).toBeTruthy();
    expect(screen.getByTestId('browser-bridge-connect')).toBeTruthy();
    expect(screen.getByTestId('browser-bridge-consent-note')).toBeTruthy();
  });
});

const _RECT_1280x720 = (): DOMRect =>
  ({ left: 0, top: 0, width: 1280, height: 720, right: 1280, bottom: 720, x: 0, y: 0, toJSON: () => ({}) }) as DOMRect;

describe('AD-1052c BrowserWorkstation drive toggle', () => {
  it('hides the Drive toggle when input_forwarding_enabled is false (DD-4/DD-5)', async () => {
    const fetchSessions = vi.fn(async (): Promise<_Sessions> => ({
      enabled: true,
      input_forwarding_enabled: false,
      sessions: [{ session_id: 's1', agent_id: 'a1', streaming_url: '/api/browser/sessions/s1/stream', last_url: 'https://x.test' }],
    }));
    render(<BrowserWorkstation typeId="browser" fetchSessions={fetchSessions} />);
    fireEvent.click(screen.getByTestId('browser-mode-watch'));
    await screen.findByTestId('browser-watch-session-s1');
    expect(screen.queryByTestId('browser-watch-drive')).toBeNull();
  });

  it('shows the Drive toggle when the flag is on and flips aria-pressed', async () => {
    const fetchSessions = vi.fn(async (): Promise<_Sessions> => ({
      enabled: true,
      input_forwarding_enabled: true,
      sessions: [{ session_id: 's1', agent_id: 'a1', streaming_url: '/api/browser/sessions/s1/stream', last_url: 'https://x.test', state: 'active' }],
    }));
    render(<BrowserWorkstation typeId="browser" fetchSessions={fetchSessions} />);
    fireEvent.click(screen.getByTestId('browser-mode-watch'));
    const drive = await screen.findByTestId('browser-watch-drive');
    expect(drive.getAttribute('aria-pressed')).toBe('false');
    expect((drive as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(await screen.findByTestId('browser-watch-session-s1'));
    fireEvent.click(drive);
    expect(screen.getByTestId('browser-watch-drive').getAttribute('aria-pressed')).toBe('true');
  });

  it('with Drive on, clicking the stream <img> forwards a click via the injected forwardInput', async () => {
    const fetchSessions = vi.fn(async (): Promise<_Sessions> => ({
      enabled: true,
      input_forwarding_enabled: true,
      sessions: [{ session_id: 's1', agent_id: 'a1', streaming_url: '/api/browser/sessions/s1/stream', last_url: 'https://x.test', state: 'active' }],
    }));
    const forwardInput = vi.fn(async () => ({ forwarded: true }));
    render(<BrowserWorkstation typeId="browser" fetchSessions={fetchSessions} forwardInput={forwardInput} />);
    fireEvent.click(screen.getByTestId('browser-mode-watch'));
    fireEvent.click(await screen.findByTestId('browser-watch-session-s1'));
    fireEvent.click(await screen.findByTestId('browser-watch-drive'));
    const img = (await screen.findByTestId('browser-stream-panel-img')) as HTMLImageElement;
    img.getBoundingClientRect = _RECT_1280x720;
    fireEvent.click(img, { clientX: 640, clientY: 360 });
    expect(forwardInput).toHaveBeenCalledWith('s1', { kind: 'click', nx: 0.5, ny: 0.5, button: 'left' });
  });

  it('the Drive toggle uses no emoji (HXI #3) and exposes its data-testid', async () => {
    const fetchSessions = vi.fn(async (): Promise<_Sessions> => ({
      enabled: true,
      input_forwarding_enabled: true,
      sessions: [],
    }));
    const { container } = render(<BrowserWorkstation typeId="browser" fetchSessions={fetchSessions} />);
    fireEvent.click(screen.getByTestId('browser-mode-watch'));
    await screen.findByTestId('browser-watch-empty');
    expect(screen.getByTestId('browser-watch-drive')).toBeTruthy();
    expect(EMOJI.test(container.textContent ?? '')).toBe(false);
  });
});

type _LifecycleProps = Parameters<typeof BrowserWorkstation>[0];
type _LifecycleListing = Awaited<ReturnType<NonNullable<_LifecycleProps['fetchSessions']>>>;
type _LifecycleRow = _LifecycleListing['sessions'][number];
type _LifecycleResult = Awaited<ReturnType<NonNullable<_LifecycleProps['changeLifecycle']>>>;

function _session(sessionId: string, overrides: Partial<_LifecycleRow> = {}): _LifecycleRow {
  return {
    session_id: sessionId, agent_id: 'captain', owner_id: 'captain', state: 'active',
    streaming_url: `/api/browser/sessions/${sessionId}/stream`, last_url: 'http://127.0.0.1/',
    sharing_scope: 'legacy_ambient_binding', recording_state: 'recording', recording_scope: 'session_owned',
    pending_work: 0, expires_at: 4102444800, external_browser: false, ...overrides,
  };
}

function _listing(sessions = [_session('first'), _session('second')]): _LifecycleListing {
  return { enabled: true, input_forwarding_enabled: true, authority_basis: 'shared_crew_scope', sessions };
}

function _deferred<Value>(): { promise: Promise<Value>; resolve: (value: Value) => void; reject: (error: Error) => void } {
  let resolve!: (value: Value) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<Value>((accept, refuse) => { resolve = accept; reject = refuse; });
  return { promise, resolve, reject };
}

async function _mountSelected(props: Partial<_LifecycleProps> = {}): Promise<ReturnType<typeof render>> {
  const view = render(<BrowserWorkstation typeId="browser" fetchSessions={async () => _listing()} {...props} />);
  fireEvent.click(await screen.findByTestId('browser-watch-session-first'));
  expect(screen.getByTestId('browser-stream-panel-img').getAttribute('src')).toContain('/first/stream');
  return view;
}

describe('Selected browser lifecycle', () => {
  it('Release control and Stop watching affect only this viewer and never request end', async () => {
    const changeLifecycle = vi.fn();
    const forwardInput = vi.fn(async () => ({ forwarded: true }));
    const view = await _mountSelected({ changeLifecycle, forwardInput });
    fireEvent.click(screen.getByRole('button', { name: 'Drive the browser' }));
    fireEvent.keyDown(screen.getByTestId('browser-stream-panel-img'), { key: 'a' });
    expect(forwardInput).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole('button', { name: 'Release control' }));
    fireEvent.keyDown(screen.getByTestId('browser-stream-panel-img'), { key: 'b' });
    expect(forwardInput).toHaveBeenCalledOnce();
    expect(screen.getByTestId('browser-stream-panel-img')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Stop watching' }));
    expect(screen.queryByTestId('browser-stream-panel-img')).toBeNull();
    expect(screen.getByText('Not watching. The browser session remains open.')).toBeTruthy();
    view.unmount();
    expect(changeLifecycle).not.toHaveBeenCalled();
  });

  it('requires selected metadata and explicit confirmation, supports cancellation and preserves the other session', async () => {
    const request = _deferred<_LifecycleResult>();
    const changeLifecycle = vi.fn(() => request.promise);
    await _mountSelected({ changeLifecycle });
    fireEvent.click(screen.getByRole('button', { name: 'End session' }));
    const dialog = screen.getByRole('dialog', { name: 'End selected session' });
    expect(dialog.textContent).toContain('first');
    expect(dialog.textContent).toContain('captain');
    expect(dialog.textContent).toContain('legacy ambient binding');
    expect(dialog.textContent).toContain('recording');
    expect(dialog.textContent).toContain('Pending browser work');
    expect(dialog.textContent).toContain('2100-01-01T00:00:00.000Z');
    expect(dialog.textContent).toContain('shared crew scope');
    expect(document.activeElement).toBe(dialog);
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    expect(changeLifecycle).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'End session' }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm end session' }));
    expect(changeLifecycle).toHaveBeenCalledWith('first', 'end');
    expect(screen.getByText(/Session request pending/)).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Drive the browser' }) as HTMLButtonElement).disabled).toBe(true);
    await act(async () => request.resolve({ outcome: 'completed', reason: 'operator_ended', status_code: 200, session: _session('first', { state: 'ended' }) }));
    expect(screen.queryByTestId('browser-stream-panel-img')).toBeNull();
    expect(screen.getByText('Session ended. Recordings retained.')).toBeTruthy();
    fireEvent.click(screen.getByTestId('browser-watch-session-second'));
    expect(screen.getByTestId('browser-stream-panel-img').getAttribute('src')).toContain('/second/stream');
  });

  it('posts exact confirmation without an actor or ownership payload', async () => {
    const fetchMock = vi.fn(async (url: string, options?: RequestInit) => {
      if (options?.method === 'POST') return { ok: true, status: 200, json: async () => ({ outcome: 'completed', reason: 'operator_ended', session: _session('first', { state: 'ended' }) }) };
      expect(url).toBe('/api/browser/sessions');
      return { ok: true, status: 200, json: async () => _listing() };
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<BrowserWorkstation typeId="browser" />);
    fireEvent.click(await screen.findByTestId('browser-watch-session-first'));
    fireEvent.click(screen.getByRole('button', { name: 'End session' }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm end session' }));
    await screen.findByText('Session ended. Recordings retained.');
    const posts = fetchMock.mock.calls.filter((call) => call[1]?.method === 'POST');
    expect(posts).toHaveLength(1);
    expect(posts[0][0]).toBe('/api/browser/sessions/first/end');
    expect(JSON.parse(posts[0][1]?.body as string)).toEqual({ confirm: true });
  });

  it('hands the exact session to crew with consent and releases local capture without ending', async () => {
    const changeLifecycle = vi.fn(async () => ({ outcome: 'completed', reason: 'selected_for_crew', status_code: 200, session: _session('first', { sharing_scope: 'explicit_crew_binding' }) }));
    await _mountSelected({ changeLifecycle });
    fireEvent.click(screen.getByRole('button', { name: 'Drive the browser' }));
    fireEvent.click(screen.getByRole('button', { name: 'Hand to crew' }));
    expect(screen.getByTestId('browser-stream-panel-img').getAttribute('data-driving')).toBeNull();
    expect(screen.getByRole('dialog').textContent).toContain('does not change ownership or permissions');
    fireEvent.click(screen.getByRole('button', { name: 'Confirm hand to crew' }));
    await screen.findByText(/No crew job started/);
    expect(changeLifecycle).toHaveBeenCalledExactlyOnceWith('first', 'handoff');
    expect(screen.getByTestId('browser-session-metadata').textContent).toContain('explicit crew binding');
    expect(screen.getByTestId('browser-stream-panel-img').getAttribute('data-driving')).toBeNull();
  });

  it.each([
    [{ owner_id: null }, 'Ownership is unknown.'],
    [{ pending_work: null }, 'Pending browser work is unknown.'],
    [{ pending_work: 2 }, 'Pending browser work must settle before retrying.'],
    [{ state: 'ending' }, 'Session is not available for this action.'],
  ] as [Partial<_LifecycleRow>, string][])('blocks unsafe confirmation for %j', async (overrides, reason) => {
    const changeLifecycle = vi.fn();
    render(<BrowserWorkstation typeId="browser" fetchSessions={async () => _listing([_session('first', overrides)])} changeLifecycle={changeLifecycle} />);
    fireEvent.click(await screen.findByTestId('browser-watch-session-first'));
    expect(screen.getByText(reason)).toBeTruthy();
    expect((screen.getByRole('button', { name: 'End session' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'End session' }));
    expect(changeLifecycle).not.toHaveBeenCalled();
  });

  it.each(['conflict', 'failed', 'rejected'])('keeps a %s result visible and refreshes pending work for retry', async (outcome) => {
    const changeLifecycle = vi.fn(async () => ({ outcome, reason: 'pending_or_unknown_work', status_code: 409, session: _session('first', { pending_work: 1 }) }));
    await _mountSelected({ changeLifecycle });
    fireEvent.click(screen.getByRole('button', { name: 'End session' }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm end session' }));
    expect(await screen.findByText(new RegExp(`${outcome}: pending or unknown work`))).toBeTruthy();
    expect(screen.queryByText('Session ended. Recordings retained.')).toBeNull();
    expect((screen.getByRole('button', { name: 'End session' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Refresh sessions' }));
    await waitFor(() => expect((screen.getByRole('button', { name: 'End session' }) as HTMLButtonElement).disabled).toBe(false));
    expect(screen.getByTestId('browser-watch-session-first').getAttribute('aria-pressed')).toBe('true');
  });

  it('shows lifecycle transport failure without claiming the session ended', async () => {
    await _mountSelected({ changeLifecycle: async () => { throw new Error('offline'); } });
    fireEvent.click(screen.getByRole('button', { name: 'End session' }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm end session' }));
    await screen.findByText('Session request failed. Refresh session details before retrying.');
    expect(screen.getByTestId('browser-stream-panel-img')).toBeTruthy();
  });

  it.each(['end', 'handoff'] as const)('ignores a stale %s response after a new selection', async (action) => {
    const request = _deferred<_LifecycleResult>();
    const changeLifecycle = vi.fn(() => request.promise);
    await _mountSelected({ changeLifecycle });
    fireEvent.click(screen.getByRole('button', { name: action === 'end' ? 'End session' : 'Hand to crew' }));
    fireEvent.click(screen.getByRole('button', { name: action === 'end' ? 'Confirm end session' : 'Confirm hand to crew' }));
    expect(changeLifecycle).toHaveBeenCalledWith('first', action);
    fireEvent.click(screen.getByTestId('browser-watch-session-second'));
    await act(async () => request.resolve({ outcome: 'completed', reason: 'done', status_code: 200, session: _session('first', { state: 'ended' }) }));
    expect(screen.getByTestId('browser-stream-panel-img').getAttribute('src')).toContain('/second/stream');
    expect(screen.queryByText(/Session ended. Recordings retained/)).toBeNull();
    expect(screen.queryByText(/No crew job started/)).toBeNull();
    expect(screen.getByTestId('browser-session-metadata').textContent).toContain('second');
  });

  it('fences in-flight input across session selection and shows a current rejected input', async () => {
    const old = _deferred<{ forwarded: boolean; reason?: string }>();
    const forwardInput = vi.fn().mockReturnValueOnce(old.promise).mockResolvedValueOnce({ forwarded: false, reason: 'session_ending' });
    await _mountSelected({ forwardInput });
    fireEvent.click(screen.getByRole('button', { name: 'Drive the browser' }));
    fireEvent.keyDown(screen.getByTestId('browser-stream-panel-img'), { key: 'a' });
    expect(forwardInput).toHaveBeenCalledWith('first', { kind: 'type', text: 'a' });
    fireEvent.click(screen.getByTestId('browser-watch-session-second'));
    expect(screen.getByTestId('browser-stream-panel-img').getAttribute('data-driving')).toBeNull();
    await act(async () => old.reject(new Error('stale input')));
    expect(screen.queryByRole('alert')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Drive the browser' }));
    fireEvent.keyDown(screen.getByTestId('browser-stream-panel-img'), { key: 'b' });
    await screen.findByText(/Input rejected: session_ending/);
    expect(screen.queryByTestId('browser-stream-panel-img')).toBeNull();
    expect((screen.getByRole('button', { name: 'Drive the browser' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('reconnects only after a fresh active snapshot and never resets the session expiry', async () => {
    const fetchSessions = vi.fn(async () => _listing());
    const changeLifecycle = vi.fn();
    await _mountSelected({ fetchSessions, changeLifecycle });
    const expiry = screen.getByTestId('browser-session-metadata').textContent;
    fireEvent.click(screen.getByRole('button', { name: 'Drive the browser' }));
    fireEvent.error(screen.getByTestId('browser-stream-panel-img'));
    expect(screen.queryByTestId('browser-stream-panel-img')).toBeNull();
    const before = fetchSessions.mock.calls.length;
    fireEvent.click(screen.getByRole('button', { name: 'Reconnect viewer' }));
    await screen.findByTestId('browser-stream-panel-img');
    expect(fetchSessions).toHaveBeenCalledTimes(before + 1);
    expect(screen.getByTestId('browser-stream-panel-img').getAttribute('data-driving')).toBeNull();
    expect(screen.getByTestId('browser-session-metadata').textContent).toBe(expiry);
    expect(changeLifecycle).not.toHaveBeenCalled();
  });

  it('refuses reconnect when the selected session disappeared', async () => {
    const fetchSessions = vi.fn(async () => _listing());
    await _mountSelected({ fetchSessions });
    fireEvent.error(screen.getByTestId('browser-stream-panel-img'));
    fetchSessions.mockResolvedValueOnce(_listing([_session('second')]));
    fireEvent.click(screen.getByRole('button', { name: 'Reconnect viewer' }));
    await waitFor(() => expect(screen.queryByTestId('browser-stream-panel-img')).toBeNull());
    await waitFor(() => expect(screen.queryByTestId('browser-watch-session-first')).toBeNull());
    expect((screen.getByRole('button', { name: 'Drive the browser' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('keeps two viewers independent when one releases control and stops watching', async () => {
    const forwardInput = vi.fn(async () => ({ forwarded: true }));
    const changeLifecycle = vi.fn();
    const first = render(<BrowserWorkstation typeId="browser" fetchSessions={async () => _listing()} forwardInput={forwardInput} changeLifecycle={changeLifecycle} />);
    const second = render(<BrowserWorkstation typeId="browser" fetchSessions={async () => _listing()} forwardInput={forwardInput} changeLifecycle={changeLifecycle} />);
    for (const view of [first, second]) {
      const scope = within(view.container);
      fireEvent.click(await scope.findByTestId('browser-watch-session-first'));
      fireEvent.click(scope.getByRole('button', { name: 'Drive the browser' }));
      fireEvent.load(scope.getByTestId('browser-stream-panel-img'));
      fireEvent.keyDown(scope.getByTestId('browser-stream-panel-img'), { key: 'a' });
    }
    expect(forwardInput).toHaveBeenCalledTimes(2);
    fireEvent.click(within(first.container).getByRole('button', { name: 'Release control' }));
    fireEvent.click(within(first.container).getByRole('button', { name: 'Stop watching' }));
    expect(within(first.container).queryByTestId('browser-stream-panel-img')).toBeNull();
    expect(within(second.container).getByTestId('browser-stream-panel-img').getAttribute('data-driving')).toBe('true');
    fireEvent.keyDown(within(second.container).getByTestId('browser-stream-panel-img'), { key: 'b' });
    expect(forwardInput).toHaveBeenCalledTimes(3);
    expect(changeLifecycle).not.toHaveBeenCalled();
  });

  it('shows bridge disconnect semantics and resets Drive across Watch and Bridge', async () => {
    const fetchSessions = async () => _listing([_session('first', { external_browser: true, recording_scope: 'external_unmanaged' })]);
    const changeLifecycle = vi.fn(async () => ({ outcome: 'completed', reason: 'operator_ended', status_code: 200, session: _session('first', { state: 'ended', external_browser: true }) }));
    await _mountSelected({ fetchSessions, changeLifecycle, connectBridge: async () => ({ connected: true, session_id: 'first', streaming_url: '/api/browser/sessions/first/stream' }) });
    fireEvent.click(screen.getByRole('button', { name: 'Drive the browser' }));
    fireEvent.click(screen.getByTestId('browser-mode-bridge'));
    fireEvent.click(screen.getByTestId('browser-bridge-connect'));
    await screen.findByTestId('browser-stream-panel-img');
    await waitFor(() => expect((screen.getByRole('button', { name: 'Drive the browser' }) as HTMLButtonElement).disabled).toBe(false));
    expect(screen.getByTestId('browser-stream-panel-img').getAttribute('data-driving')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'End session' }));
    expect(screen.getByRole('dialog').textContent).toContain('external browser, pages and contexts remain open');
    expect(screen.getByRole('dialog').textContent).toContain('external unmanaged');
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
    expect(changeLifecycle).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Drive the browser' }));
    fireEvent.click(screen.getByTestId('browser-mode-watch'));
    await screen.findByTestId('browser-stream-panel-img');
    expect(screen.getByTestId('browser-stream-panel-img').getAttribute('data-driving')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'End session' }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm end session' }));
    await screen.findByText('ProbOS disconnected. The external browser remains open.');
  });

  it('ignores stale list results and a delayed mount probe after a manual mode choice', async () => {
    const initial = _deferred<_LifecycleListing>();
    const old = _deferred<_LifecycleListing>();
    const fetchSessions = vi.fn().mockReturnValueOnce(initial.promise).mockReturnValueOnce(old.promise).mockResolvedValue(_listing());
    render(<BrowserWorkstation typeId="browser" fetchSessions={fetchSessions} />);
    fireEvent.click(screen.getByTestId('browser-mode-bridge'));
    await act(async () => initial.resolve(_listing()));
    expect(screen.getByTestId('browser-mode-bridge').getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(screen.getByTestId('browser-mode-watch'));
    fireEvent.click(await screen.findByTestId('browser-watch-session-second'));
    await act(async () => old.resolve(_listing([_session('obsolete')])));
    expect(screen.queryByTestId('browser-watch-session-obsolete')).toBeNull();
    expect(screen.getByTestId('browser-stream-panel-img').getAttribute('src')).toContain('/second/stream');
  });

  it('ignores an opened session response after another selection', async () => {
    const opened = _deferred<{ opened: boolean; session_id: string }>();
    const openSession = vi.fn(() => opened.promise);
    await _mountSelected({ openSession });
    fireEvent.change(screen.getByTestId('browser-watch-open-url'), { target: { value: 'http://127.0.0.1/' } });
    fireEvent.click(screen.getByTestId('browser-watch-open'));
    expect(openSession).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByTestId('browser-watch-session-second'));
    await act(async () => opened.resolve({ opened: true, session_id: 'late' }));
    expect(screen.getByTestId('browser-stream-panel-img').getAttribute('src')).toContain('/second/stream');
  });

  it('refreshes at absolute expiry and removes capture without extending TTL', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-09-12T12:00:00Z'));
    const expires = Date.now() / 1000 + 1;
    const fetchSessions = vi.fn(async () => _listing([_session('first', { expires_at: expires })]));
    await act(async () => { render(<BrowserWorkstation typeId="browser" fetchSessions={fetchSessions} />); });
    fireEvent.click(screen.getByTestId('browser-watch-session-first'));
    fireEvent.click(screen.getByRole('button', { name: 'Drive the browser' }));
    expect(screen.getByTestId('browser-stream-panel-img').getAttribute('data-driving')).toBe('true');
    const before = fetchSessions.mock.calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(1001); });
    expect(fetchSessions).toHaveBeenCalledTimes(before + 1);
    expect(screen.queryByTestId('browser-stream-panel-img')).toBeNull();
    expect(screen.getByTestId('browser-session-metadata').textContent).toContain('2026-09-12T12:00:01.000Z (expired)');
    expect((screen.getByRole('button', { name: 'Drive the browser' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('observes another operator ending the selected session and removes input capture', async () => {
    vi.useFakeTimers();
    const fetchSessions = vi.fn(async () => _listing());
    const forwardInput = vi.fn(async () => ({ forwarded: true }));
    await act(async () => { render(<BrowserWorkstation typeId="browser" fetchSessions={fetchSessions} forwardInput={forwardInput} />); });
    fireEvent.click(screen.getByTestId('browser-watch-session-first'));
    fireEvent.click(screen.getByRole('button', { name: 'Drive the browser' }));
    fireEvent.keyDown(screen.getByTestId('browser-stream-panel-img'), { key: 'a' });
    expect(forwardInput).toHaveBeenCalledOnce();
    fetchSessions.mockResolvedValue(_listing([_session('first', { state: 'ended' }), _session('second')]));
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(screen.queryByTestId('browser-stream-panel-img')).toBeNull();
    expect(screen.getByText('Session ended. Control released.')).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Drive the browser' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByTestId('browser-watch-session-second'));
    expect(screen.getByTestId('browser-stream-panel-img').getAttribute('src')).toContain('/second/stream');
    expect(forwardInput).toHaveBeenCalledOnce();
  });

  it('shows reconnect verification failure and keeps capture disabled', async () => {
    const fetchSessions = vi.fn(async () => _listing());
    await _mountSelected({ fetchSessions });
    fireEvent.error(screen.getByTestId('browser-stream-panel-img'));
    fetchSessions.mockRejectedValueOnce(new Error('offline'));
    fireEvent.click(screen.getByRole('button', { name: 'Reconnect viewer' }));
    await screen.findByText('Could not verify session state. Viewer remains disconnected.');
    expect(screen.queryByTestId('browser-stream-panel-img')).toBeNull();
    expect((screen.getByRole('button', { name: 'Drive the browser' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('ignores a rejected in-flight input after Release control without recapturing', async () => {
    const input = _deferred<{ forwarded: boolean }>();
    const forwardInput = vi.fn(() => input.promise);
    await _mountSelected({ forwardInput });
    fireEvent.click(screen.getByRole('button', { name: 'Drive the browser' }));
    fireEvent.keyDown(screen.getByTestId('browser-stream-panel-img'), { key: 'a' });
    expect(forwardInput).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole('button', { name: 'Release control' }));
    await act(async () => input.reject(new Error('late rejection')));
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.getByTestId('browser-stream-panel-img').getAttribute('data-driving')).toBeNull();
    fireEvent.keyDown(screen.getByTestId('browser-stream-panel-img'), { key: 'b' });
    expect(forwardInput).toHaveBeenCalledOnce();
  });

  it('allows a known idle crew session to end but not to enter the Captain handoff binding', async () => {
    await _mountSelected({ fetchSessions: async () => _listing([_session('first', { owner_id: 'crew-one', agent_id: 'crew-one', sharing_scope: 'not_shared' })]) });
    expect((screen.getByRole('button', { name: 'End session' }) as HTMLButtonElement).disabled).toBe(false);
    expect((screen.getByRole('button', { name: 'Hand to crew' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('does not capture an already expired selection', async () => {
    render(<BrowserWorkstation typeId="browser" fetchSessions={async () => _listing([_session('first', { expires_at: 1 })])} />);
    fireEvent.click(await screen.findByTestId('browser-watch-session-first'));
    expect(screen.queryByTestId('browser-stream-panel-img')).toBeNull();
    expect((screen.getByRole('button', { name: 'Drive the browser' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Hand to crew' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('fences a delayed bridge response after changing modes', async () => {
    const bridge = _deferred<_Bridge>();
    const connectBridge = vi.fn(() => bridge.promise);
    await _mountSelected({ connectBridge });
    fireEvent.click(screen.getByTestId('browser-mode-bridge'));
    fireEvent.click(screen.getByTestId('browser-bridge-connect'));
    expect(connectBridge).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByTestId('browser-mode-watch'));
    fireEvent.click(await screen.findByTestId('browser-watch-session-second'));
    await act(async () => bridge.resolve({ connected: true, session_id: 'late', streaming_url: '/late' }));
    expect(screen.getByTestId('browser-stream-panel-img').getAttribute('src')).toContain('/second/stream');
    fireEvent.click(screen.getByTestId('browser-mode-bridge'));
    expect(screen.queryByTestId('browser-stream-panel-img')).toBeNull();
  });

  it('refreshes the new selection instead of stranding loading when an older list is in flight', async () => {
    const old = _deferred<_LifecycleListing>();
    const fetchSessions = vi.fn(async () => _listing());
    await _mountSelected({ fetchSessions });
    fetchSessions.mockReturnValueOnce(old.promise);
    fireEvent.click(screen.getByRole('button', { name: 'Refresh sessions' }));
    fireEvent.click(screen.getByTestId('browser-watch-session-second'));
    await waitFor(() => expect((screen.getByRole('button', { name: 'Drive the browser' }) as HTMLButtonElement).disabled).toBe(false));
    await act(async () => old.resolve(_listing([_session('obsolete')])));
    expect(screen.queryByTestId('browser-watch-session-obsolete')).toBeNull();
    expect(screen.getByTestId('browser-stream-panel-img').getAttribute('src')).toContain('/second/stream');
  });
});

type _Open = {
  opened: boolean;
  reason?: string | null;
  session_id?: string | null;
  streaming_url?: string | null;
  url?: string | null;
  page_title?: string | null;
};

/** AD-1161: the Captain opens the browser, signs in by hand, and only then hands
 *  the session to an agent. Before this, nothing CREATED a session. */
describe('AD-1161 BrowserWorkstation Captain-opened session', () => {
  const _row = (id: string) => ({
    session_id: id, agent_id: 'captain',
    streaming_url: `/api/browser/sessions/${id}/stream`, last_url: 'https://x.test',
  });

  it('defaults to watch mode when the backend reports the tool enabled', async () => {
    const fetchSessions = vi.fn(async (): Promise<_Sessions> => ({ enabled: true, sessions: [] }));
    render(<BrowserWorkstation typeId="browser" fetchSessions={fetchSessions} />);
    await waitFor(() =>
      expect((screen.getByTestId('browser-mode-watch') as HTMLButtonElement).getAttribute('aria-pressed')).toBe('true'),
    );
    expect((screen.getByTestId('browser-mode-embedded') as HTMLButtonElement).getAttribute('aria-pressed')).toBe('false');
    // The X-Frame-Options iframe is NOT what the Captain lands on.
    expect(screen.queryByTestId('browser-frame')).toBeNull();
  });

  it('stays on embedded mode when the backend reports the tool disabled', async () => {
    const fetchSessions = vi.fn(async (): Promise<_Sessions> => ({ enabled: false, sessions: [] }));
    render(<BrowserWorkstation typeId="browser" fetchSessions={fetchSessions} />);
    await waitFor(() => expect(fetchSessions).toHaveBeenCalled());
    expect((screen.getByTestId('browser-mode-embedded') as HTMLButtonElement).getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByTestId('browser-empty')).toBeTruthy();
  });

  it('stays on embedded mode when the sessions probe rejects (honest-degrade)', async () => {
    const fetchSessions = vi.fn(() => Promise.reject(new Error('boom')));
    render(<BrowserWorkstation typeId="browser" fetchSessions={fetchSessions} />);
    await waitFor(() => expect(fetchSessions).toHaveBeenCalled());
    expect((screen.getByTestId('browser-mode-embedded') as HTMLButtonElement).getAttribute('aria-pressed')).toBe('true');
  });

  it('Open posts the normalized URL and auto-selects the returned session', async () => {
    let opened = false;
    const fetchSessions = vi.fn(async (): Promise<_Sessions> => ({
      enabled: true, sessions: opened ? [_row('s7')] : [],
    }));
    const openSession = vi.fn(async (): Promise<_Open> => {
      opened = true;
      return { opened: true, session_id: 's7', streaming_url: '/api/browser/sessions/s7/stream', url: 'https://word.test' };
    });
    render(<BrowserWorkstation typeId="browser" fetchSessions={fetchSessions} openSession={openSession} />);
    await screen.findByTestId('browser-watch-open');

    fireEvent.change(screen.getByTestId('browser-watch-open-url'), { target: { value: 'word.test' } });
    fireEvent.click(screen.getByTestId('browser-watch-open'));

    // Auto-selected: the stream appears with NO second click on the picker row.
    const img = await screen.findByTestId('browser-stream-panel-img');
    expect(img.getAttribute('src')).toBe('/api/browser/sessions/s7/stream');
    expect(openSession).toHaveBeenCalledWith('https://word.test'); // scheme prepended
    expect(screen.queryByTestId('browser-watch-open-reason')).toBeNull();
  });

  it('Open is reachable from the empty state (the state it exists to fix)', async () => {
    const fetchSessions = vi.fn(async (): Promise<_Sessions> => ({ enabled: true, sessions: [] }));
    render(<BrowserWorkstation typeId="browser" fetchSessions={fetchSessions} />);
    await screen.findByTestId('browser-watch-empty');
    expect(screen.getByTestId('browser-watch-open')).toBeTruthy();
    expect(screen.getByTestId('browser-watch-open-url')).toBeTruthy();
  });

  it('{opened:false} renders the backend reason and selects nothing', async () => {
    const fetchSessions = vi.fn(async (): Promise<_Sessions> => ({ enabled: true, sessions: [] }));
    const openSession = vi.fn(async (): Promise<_Open> => ({
      opened: false, reason: 'Domain policy denied: in denylist',
    }));
    render(<BrowserWorkstation typeId="browser" fetchSessions={fetchSessions} openSession={openSession} />);
    await screen.findByTestId('browser-watch-open');

    fireEvent.change(screen.getByTestId('browser-watch-open-url'), { target: { value: 'https://evil.test' } });
    fireEvent.click(screen.getByTestId('browser-watch-open'));

    const reason = await screen.findByTestId('browser-watch-open-reason');
    expect(reason.textContent).toContain('in denylist');
    expect(screen.queryByTestId('browser-stream-panel-img')).toBeNull();
    // No spinner left running.
    expect((screen.getByTestId('browser-watch-open') as HTMLButtonElement).disabled).toBe(false);
  });

  it('openSession rejecting degrades honestly instead of throwing', async () => {
    const fetchSessions = vi.fn(async (): Promise<_Sessions> => ({ enabled: true, sessions: [] }));
    const openSession = vi.fn(() => Promise.reject(new Error('boom')));
    render(<BrowserWorkstation typeId="browser" fetchSessions={fetchSessions} openSession={openSession} />);
    await screen.findByTestId('browser-watch-open');

    fireEvent.change(screen.getByTestId('browser-watch-open-url'), { target: { value: 'https://x.test' } });
    fireEvent.click(screen.getByTestId('browser-watch-open'));

    const reason = await screen.findByTestId('browser-watch-open-reason');
    expect(reason.textContent).toContain('Could not open');
    expect((screen.getByTestId('browser-watch-open') as HTMLButtonElement).disabled).toBe(false);
  });

  it('rejects a dangerous scheme locally without calling openSession', async () => {
    const fetchSessions = vi.fn(async (): Promise<_Sessions> => ({ enabled: true, sessions: [] }));
    const openSession = vi.fn(async (): Promise<_Open> => ({ opened: true, session_id: 's1' }));
    render(<BrowserWorkstation typeId="browser" fetchSessions={fetchSessions} openSession={openSession} />);
    await screen.findByTestId('browser-watch-open');

    fireEvent.change(screen.getByTestId('browser-watch-open-url'), { target: { value: 'javascript:alert(1)' } });
    fireEvent.click(screen.getByTestId('browser-watch-open'));

    expect(screen.getByTestId('browser-watch-open-reason').textContent).toContain('http(s)');
    expect(openSession).not.toHaveBeenCalled();
  });

  it('an empty URL degrades locally without calling openSession', async () => {
    const fetchSessions = vi.fn(async (): Promise<_Sessions> => ({ enabled: true, sessions: [] }));
    const openSession = vi.fn(async (): Promise<_Open> => ({ opened: true, session_id: 's1' }));
    render(<BrowserWorkstation typeId="browser" fetchSessions={fetchSessions} openSession={openSession} />);
    await screen.findByTestId('browser-watch-open');

    fireEvent.click(screen.getByTestId('browser-watch-open'));

    expect(screen.getByTestId('browser-watch-open-reason')).toBeTruthy();
    expect(openSession).not.toHaveBeenCalled();
  });

  it('Enter in the URL field opens, and the affordance uses no emoji (HXI #3)', async () => {
    const fetchSessions = vi.fn(async (): Promise<_Sessions> => ({ enabled: true, sessions: [] }));
    const openSession = vi.fn(async (): Promise<_Open> => ({ opened: true, session_id: 's3' }));
    const { container } = render(
      <BrowserWorkstation typeId="browser" fetchSessions={fetchSessions} openSession={openSession} />,
    );
    await screen.findByTestId('browser-watch-open');

    const input = screen.getByTestId('browser-watch-open-url');
    fireEvent.change(input, { target: { value: 'https://x.test' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    await waitFor(() => expect(openSession).toHaveBeenCalledWith('https://x.test'));
    expect(EMOJI.test(container.textContent ?? '')).toBe(false);
  });
});
