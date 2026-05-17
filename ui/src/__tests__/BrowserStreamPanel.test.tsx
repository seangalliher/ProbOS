/**
 * AD-706a: BrowserStreamPanel tests.
 */
import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { BrowserStreamPanel } from '../components/browser/BrowserStreamPanel';

describe('BrowserStreamPanel (AD-706a)', () => {
  afterEach(() => cleanup());

  it('renders_no_stream_glyph_when_url_null', () => {
    render(<BrowserStreamPanel sessionId="sess-1" streamingUrl={null} />);
    expect(screen.getByTestId('browser-stream-panel-unavailable')).toBeTruthy();
    expect(screen.queryByTestId('browser-stream-panel-img')).toBeNull();
  });

  it('renders_img_with_url_when_provided', () => {
    render(
      <BrowserStreamPanel
        sessionId="sess-1"
        streamingUrl="/api/browser/sessions/sess-1/stream"
      />,
    );
    const img = screen.getByTestId('browser-stream-panel-img') as HTMLImageElement;
    expect(img.getAttribute('src')).toBe('/api/browser/sessions/sess-1/stream');
  });

  it('appends_token_query_param_when_token_present', () => {
    render(
      <BrowserStreamPanel
        sessionId="sess-1"
        streamingUrl="/api/browser/sessions/sess-1/stream"
        token="abc123"
      />,
    );
    const img = screen.getByTestId('browser-stream-panel-img') as HTMLImageElement;
    expect(img.getAttribute('src')).toBe(
      '/api/browser/sessions/sess-1/stream?token=abc123',
    );
  });

  it('omits_token_query_param_when_token_empty_string', () => {
    render(
      <BrowserStreamPanel
        sessionId="sess-1"
        streamingUrl="/api/browser/sessions/sess-1/stream"
        token=""
      />,
    );
    const img = screen.getByTestId('browser-stream-panel-img') as HTMLImageElement;
    expect(img.getAttribute('src')).toBe('/api/browser/sessions/sess-1/stream');
  });
});
