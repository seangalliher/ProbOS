/**
 * AD-706a: Captain-watch streaming panel.
 *
 * Renders the BrowserSession MJPEG stream as a stroke-based "stream
 * unavailable" glyph (when null) or a plain ``<img>`` tag (when populated).
 * HXI Design Principle #3: stroke-based SVG icons, no emoji.
 *
 * Not yet wired into the parent agent-detail panel - that is forward-marked
 * as AD-706a-parent-wire.
 */
import React from 'react';

/** AD-1052c: a single human-forwarded input event (DD-2 v1 vocabulary). */
export type ForwardInputEvent =
  | { kind: 'click'; nx: number; ny: number; button: 'left' | 'right' | 'middle' }
  | { kind: 'scroll'; nx: number; ny: number; dx: number; dy: number }
  | { kind: 'type'; text: string }
  | { kind: 'key'; key: string };

/** AD-1052c: non-destructive single keys mirrored from the backend
 *  `_FORWARD_KEY_ALLOWLIST` (DD-6). No modifier combos in v1. */
export const _FORWARD_KEY_ALLOWLIST: ReadonlySet<string> = new Set<string>([
  'Enter', 'Tab', 'Backspace', 'Delete', 'Escape',
  'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight',
  'Home', 'End', 'PageUp', 'PageDown',
]);

/** AD-1052c / DD-1: pure, unit-testable mapper — img-relative client coords ->
 *  normalized [0,1]. Returns null for a zero-area rect (jsdom layout / not yet
 *  laid out) so the caller can skip emitting a bogus (0,0). */
export function _normalizePointer(
  clientX: number, clientY: number,
  rect: { left: number; top: number; width: number; height: number },
): { nx: number; ny: number } | null {
  if (rect.width <= 0 || rect.height <= 0) return null;
  const clamp01 = (v: number): number => (v < 0 ? 0 : v > 1 ? 1 : v);
  return {
    nx: clamp01((clientX - rect.left) / rect.width),
    ny: clamp01((clientY - rect.top) / rect.height),
  };
}

export type BrowserStreamPanelProps = {
  sessionId: string;
  streamingUrl: string | null;
  token?: string;
  /** AD-1052c: when true AND onForwardInput is set, the <img> captures human
   *  input and forwards it (tabIndex + crosshair + handlers). Absent => the
   *  panel is byte-identical to the AD-706a read-only element. */
  driveEnabled?: boolean;
  /** AD-1052c: sink for captured input events (injected by the workstation). */
  onForwardInput?: (evt: ForwardInputEvent) => void;
};

export function BrowserStreamPanel({
  sessionId,
  streamingUrl,
  token,
  driveEnabled,
  onForwardInput,
}: BrowserStreamPanelProps): React.ReactElement {
  if (streamingUrl == null) {
    return (
      <div
        data-testid="browser-stream-panel-unavailable"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '0.5em',
          color: '#666680',
          padding: '0.5em',
        }}
      >
        <svg
          width="16"
          height="16"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <circle cx="8" cy="8" r="6.25" />
          <path d="M3.5 12.5 L12.5 3.5" />
        </svg>
        <span>Streaming not enabled</span>
      </div>
    );
  }

  // AD-706a query-param fallback on require_crew_scope: append ?token=
  // ONLY when a non-empty token is provided. Empty string omits the query.
  let fullUrl = streamingUrl;
  if (typeof token === 'string' && token.length > 0) {
    const sep = streamingUrl.includes('?') ? '&' : '?';
    fullUrl = `${streamingUrl}${sep}token=${encodeURIComponent(token)}`;
  }

  // AD-1052c: DRIVE branch — capture pointer/keyboard input and forward it.
  // Only when BOTH the toggle is on AND a sink is injected; otherwise the
  // <img> below is byte-identical to the AD-706a read-only element (DD-5).
  if (driveEnabled === true && onForwardInput) {
    const emit = onForwardInput;
    return (
      <img
        data-testid="browser-stream-panel-img"
        data-driving="true"
        src={fullUrl}
        alt={`Browser session ${sessionId}`}
        tabIndex={0}
        style={{ maxWidth: '100%', display: 'block', cursor: 'crosshair' }}
        onClick={(e) => {
          const norm = _normalizePointer(
            e.clientX, e.clientY, e.currentTarget.getBoundingClientRect(),
          );
          if (norm === null) return;
          emit({ kind: 'click', nx: norm.nx, ny: norm.ny, button: 'left' });
        }}
        onWheel={(e) => {
          const norm = _normalizePointer(
            e.clientX, e.clientY, e.currentTarget.getBoundingClientRect(),
          );
          if (norm === null) return;
          e.preventDefault();
          emit({ kind: 'scroll', nx: norm.nx, ny: norm.ny, dx: e.deltaX, dy: e.deltaY });
        }}
        onKeyDown={(e) => {
          if (e.key.length === 1) {
            e.preventDefault();
            emit({ kind: 'type', text: e.key });
          } else if (_FORWARD_KEY_ALLOWLIST.has(e.key)) {
            e.preventDefault();
            emit({ kind: 'key', key: e.key });
          }
        }}
      />
    );
  }

  return (
    <img
      data-testid="browser-stream-panel-img"
      src={fullUrl}
      alt={`Browser session ${sessionId}`}
      style={{ maxWidth: '100%', display: 'block' }}
    />
  );
}

export default BrowserStreamPanel;
