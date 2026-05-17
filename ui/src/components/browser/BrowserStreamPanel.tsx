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

export type BrowserStreamPanelProps = {
  sessionId: string;
  streamingUrl: string | null;
  token?: string;
};

export function BrowserStreamPanel({
  sessionId,
  streamingUrl,
  token,
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
