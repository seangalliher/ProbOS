/** AD-1052c vitest — BrowserStreamPanel input-capture (the human DRIVES).
 *
 * Asserts the pure `_normalizePointer` mapper (midpoint / clamp / zero-area
 * null), the drive-mode <img> (tabIndex + data-driving + click/wheel/keydown
 * forwarding), the byte-identical read-only <img> when the capture props are
 * absent (DD-5), the backend-mirrored key allowlist, and the HXI no-emoji rule.
 */
import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';
import { BrowserStreamPanel, _normalizePointer, _FORWARD_KEY_ALLOWLIST } from './BrowserStreamPanel';

const EMOJI = /\p{Extended_Pictographic}/u;

const _RECT_1280x720 = (): DOMRect =>
  ({ left: 0, top: 0, width: 1280, height: 720, right: 1280, bottom: 720, x: 0, y: 0, toJSON: () => ({}) }) as DOMRect;

afterEach(() => {
  cleanup();
});

describe('AD-1052c _normalizePointer', () => {
  it('maps the midpoint of a rect to {0.5, 0.5}', () => {
    expect(_normalizePointer(640, 360, { left: 0, top: 0, width: 1280, height: 720 })).toEqual({ nx: 0.5, ny: 0.5 });
  });

  it('clamps out-of-bounds coords to [0,1]', () => {
    expect(_normalizePointer(-100, 2000, { left: 0, top: 0, width: 1280, height: 720 })).toEqual({ nx: 0, ny: 1 });
  });

  it('honors a non-zero rect origin (offset)', () => {
    expect(_normalizePointer(100, 50, { left: 100, top: 50, width: 200, height: 100 })).toEqual({ nx: 0, ny: 0 });
  });

  it('returns null for a zero-area rect (jsdom not-laid-out)', () => {
    expect(_normalizePointer(5, 5, { left: 0, top: 0, width: 0, height: 0 })).toBeNull();
  });
});

describe('AD-1052c BrowserStreamPanel drive capture', () => {
  it('without driveEnabled the <img> has no tabIndex / data-driving and never forwards (DD-5)', () => {
    const onForwardInput = vi.fn();
    render(<BrowserStreamPanel sessionId="s1" streamingUrl="/api/browser/sessions/s1/stream" onForwardInput={onForwardInput} />);
    const img = screen.getByTestId('browser-stream-panel-img');
    expect(img.getAttribute('tabindex')).toBeNull();
    expect(img.getAttribute('data-driving')).toBeNull();
    fireEvent.click(img, { clientX: 10, clientY: 10 });
    expect(onForwardInput).not.toHaveBeenCalled();
  });

  it('with driveEnabled the <img> gains tabIndex=0 + data-driving and forwards a click', () => {
    const onForwardInput = vi.fn();
    render(<BrowserStreamPanel sessionId="s1" streamingUrl="/api/browser/sessions/s1/stream" driveEnabled onForwardInput={onForwardInput} />);
    const img = screen.getByTestId('browser-stream-panel-img') as HTMLImageElement;
    expect(img.getAttribute('tabindex')).toBe('0');
    expect(img.getAttribute('data-driving')).toBe('true');
    img.getBoundingClientRect = _RECT_1280x720;
    fireEvent.click(img, { clientX: 640, clientY: 360 });
    expect(onForwardInput).toHaveBeenCalledWith({ kind: 'click', nx: 0.5, ny: 0.5, button: 'left' });
  });

  it('a zero-area rect skips the click emit (no bogus 0,0)', () => {
    const onForwardInput = vi.fn();
    render(<BrowserStreamPanel sessionId="s1" streamingUrl="/api/browser/sessions/s1/stream" driveEnabled onForwardInput={onForwardInput} />);
    // jsdom default getBoundingClientRect is 0x0 -> _normalizePointer returns null.
    fireEvent.click(screen.getByTestId('browser-stream-panel-img'), { clientX: 10, clientY: 10 });
    expect(onForwardInput).not.toHaveBeenCalled();
  });

  it('forwards a single-character keydown as a type event', () => {
    const onForwardInput = vi.fn();
    render(<BrowserStreamPanel sessionId="s1" streamingUrl="/s" driveEnabled onForwardInput={onForwardInput} />);
    fireEvent.keyDown(screen.getByTestId('browser-stream-panel-img'), { key: 'a' });
    expect(onForwardInput).toHaveBeenCalledWith({ kind: 'type', text: 'a' });
  });

  it('forwards an allowlisted keydown as a key event and ignores a non-allowlisted one', () => {
    const onForwardInput = vi.fn();
    render(<BrowserStreamPanel sessionId="s1" streamingUrl="/s" driveEnabled onForwardInput={onForwardInput} />);
    const img = screen.getByTestId('browser-stream-panel-img');
    fireEvent.keyDown(img, { key: 'Enter' });
    expect(onForwardInput).toHaveBeenCalledWith({ kind: 'key', key: 'Enter' });
    onForwardInput.mockClear();
    fireEvent.keyDown(img, { key: 'F5' });
    expect(onForwardInput).not.toHaveBeenCalled();
  });

  it('forwards a wheel event as a scroll', () => {
    const onForwardInput = vi.fn();
    render(<BrowserStreamPanel sessionId="s1" streamingUrl="/s" driveEnabled onForwardInput={onForwardInput} />);
    const img = screen.getByTestId('browser-stream-panel-img') as HTMLImageElement;
    img.getBoundingClientRect = _RECT_1280x720;
    fireEvent.wheel(img, { clientX: 640, clientY: 360, deltaX: 0, deltaY: 120 });
    expect(onForwardInput).toHaveBeenCalledWith({ kind: 'scroll', nx: 0.5, ny: 0.5, dx: 0, dy: 120 });
  });

  it('the exported allowlist mirrors the backend (v1 keys, no modifier combos)', () => {
    expect(_FORWARD_KEY_ALLOWLIST.has('Enter')).toBe(true);
    expect(_FORWARD_KEY_ALLOWLIST.has('ArrowLeft')).toBe(true);
    expect(_FORWARD_KEY_ALLOWLIST.has('PageDown')).toBe(true);
    expect(_FORWARD_KEY_ALLOWLIST.has('Control+w')).toBe(false);
  });

  it('uses no emoji (HXI #3)', () => {
    const { container } = render(<BrowserStreamPanel sessionId="s1" streamingUrl="/s" driveEnabled onForwardInput={vi.fn()} />);
    expect(EMOJI.test(container.textContent ?? '')).toBe(false);
  });
});
