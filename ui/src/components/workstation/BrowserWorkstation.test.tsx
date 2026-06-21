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
};

describe('AD-1052a BrowserWorkstation watch mode', () => {
  it('clicking Watch sets aria-pressed and calls fetchSessions (DD-1 same-origin)', async () => {
    const fetchSessions = vi.fn(async (): Promise<_Sessions> => ({ enabled: true, sessions: [] }));
    render(<BrowserWorkstation typeId="browser" fetchSessions={fetchSessions} />);
    fireEvent.click(screen.getByTestId('browser-mode-watch'));
    expect((screen.getByTestId('browser-mode-watch') as HTMLButtonElement).getAttribute('aria-pressed')).toBe('true');
    await screen.findByTestId('browser-watch-empty');
    expect(fetchSessions).toHaveBeenCalledTimes(1);
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
    expect(fetchSessions).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByTestId('browser-watch-refresh'));
    await waitFor(() => expect(fetchSessions).toHaveBeenCalledTimes(2));
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
