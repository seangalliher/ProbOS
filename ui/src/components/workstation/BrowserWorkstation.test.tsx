/** AD-1052 vitest — Browser/Web-App Workstation (embedded-iframe mode + the
 *  unifying mode model).
 *
 * Self-contained component (ignores doc). Asserts: the mode model (Embedded
 * active, Watch/Bridge disabled), URL commit -> sandboxed iframe with the
 * normalized src, the http(s) scheme allowlist (defense-in-depth), the
 * empty/honest-degrade state, data-testids, and the HXI no-emoji guard.
 */
import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';
import { BrowserWorkstation, _normalizeUrl } from './BrowserWorkstation';

const EMOJI = /\p{Extended_Pictographic}/u;

afterEach(() => {
  cleanup();
});

describe('AD-1052 BrowserWorkstation', () => {
  it('defaults to Embedded active with Watch + Bridge disabled (the mode model)', () => {
    render(<BrowserWorkstation typeId="browser" />);
    const embedded = screen.getByTestId('browser-mode-embedded') as HTMLButtonElement;
    const watch = screen.getByTestId('browser-mode-watch') as HTMLButtonElement;
    const bridge = screen.getByTestId('browser-mode-bridge') as HTMLButtonElement;
    expect(embedded.disabled).toBe(false);
    expect(embedded.getAttribute('aria-pressed')).toBe('true');
    expect(watch.disabled).toBe(true);
    expect(bridge.disabled).toBe(true);
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

  it('keeps Embedded active when a disabled mode segment is clicked', () => {
    render(<BrowserWorkstation typeId="browser" />);
    // A disabled button does not dispatch click in jsdom; the guard also no-ops.
    fireEvent.click(screen.getByTestId('browser-mode-watch'));
    expect((screen.getByTestId('browser-mode-embedded') as HTMLButtonElement).getAttribute('aria-pressed')).toBe('true');
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
