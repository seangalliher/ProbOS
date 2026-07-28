/** AD-1052 vitest — Browser/Web-App Workstation (embedded-iframe mode + the
 *  unifying mode model).
 *
 * Self-contained component (ignores doc). Asserts: the mode model (Embedded
 * active, Watch/Bridge disabled), URL commit -> sandboxed iframe with the
 * normalized src, the http(s) scheme allowlist (defense-in-depth), the
 * empty/honest-degrade state, data-testids, and the HXI no-emoji guard.
 */
import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import { BrowserWorkstation, _normalizeUrl } from './BrowserWorkstation';

const EMOJI = /\p{Extended_Pictographic}/u;

afterEach(() => {
  cleanup();
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
  sessions: { session_id: string; agent_id: string; streaming_url: string | null; last_url: string }[];
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
    render(<BrowserWorkstation typeId="browser" connectBridge={connectBridge} />);
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
    render(<BrowserWorkstation typeId="browser" connectBridge={connectBridge} />);
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
      sessions: [{ session_id: 's1', agent_id: 'a1', streaming_url: '/api/browser/sessions/s1/stream', last_url: 'https://x.test' }],
    }));
    render(<BrowserWorkstation typeId="browser" fetchSessions={fetchSessions} />);
    fireEvent.click(screen.getByTestId('browser-mode-watch'));
    const drive = await screen.findByTestId('browser-watch-drive');
    expect(drive.getAttribute('aria-pressed')).toBe('false');
    fireEvent.click(drive);
    expect(screen.getByTestId('browser-watch-drive').getAttribute('aria-pressed')).toBe('true');
  });

  it('with Drive on, clicking the stream <img> forwards a click via the injected forwardInput', async () => {
    const fetchSessions = vi.fn(async (): Promise<_Sessions> => ({
      enabled: true,
      input_forwarding_enabled: true,
      sessions: [{ session_id: 's1', agent_id: 'a1', streaming_url: '/api/browser/sessions/s1/stream', last_url: 'https://x.test' }],
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
