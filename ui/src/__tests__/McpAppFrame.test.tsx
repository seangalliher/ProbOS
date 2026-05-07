/* AD-597a: McpAppFrame component tests. */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, cleanup } from '@testing-library/react';
import { McpAppFrame } from '../components/McpAppFrame';

afterEach(cleanup);

describe('McpAppFrame', () => {
  it('renders an iframe with internal sandbox by default', () => {
    const { container } = render(
      <McpAppFrame resourceUri="ui://probos/games/chess/index.html" toolName="game-state" />,
    );
    const iframe = container.querySelector('iframe');
    expect(iframe).not.toBeNull();
    expect(iframe!.getAttribute('sandbox')).toBe('allow-scripts allow-same-origin');
  });

  it('renders with stricter external sandbox when external=true', () => {
    const { container } = render(
      <McpAppFrame
        resourceUri="ui://external/srv/x.html"
        toolName="ext-tool"
        external
      />,
    );
    const iframe = container.querySelector('iframe');
    expect(iframe!.getAttribute('sandbox')).toBe('allow-scripts');
  });

  it('encodes the resourceUri in the iframe src', () => {
    const { container } = render(
      <McpAppFrame
        resourceUri="ui://probos/games/chess/index.html"
        toolName="game-state"
      />,
    );
    const iframe = container.querySelector('iframe');
    const src = iframe!.getAttribute('src') || '';
    expect(src.startsWith('/api/mcp/resource?uri=')).toBe(true);
    expect(src).toContain(
      encodeURIComponent('ui://probos/games/chess/index.html'),
    );
  });

  it('sets the title from toolName for accessibility', () => {
    const { container } = render(
      <McpAppFrame resourceUri="ui://probos/x" toolName="my-tool" />,
    );
    const iframe = container.querySelector('iframe');
    expect(iframe!.getAttribute('title')).toBe('mcp-app-my-tool');
  });

  it('uses 100% width/height styling', () => {
    const { container } = render(
      <McpAppFrame resourceUri="ui://probos/x" toolName="t" />,
    );
    const iframe = container.querySelector('iframe') as HTMLIFrameElement;
    expect(iframe.style.width).toBe('100%');
    expect(iframe.style.height).toBe('100%');
  });

  it('removes border (border style 0)', () => {
    const { container } = render(
      <McpAppFrame resourceUri="ui://probos/x" toolName="t" />,
    );
    const iframe = container.querySelector('iframe') as HTMLIFrameElement;
    expect(iframe.style.border.replace(/\s|px/g, '')).toContain('0');
  });

  it('cleans up on unmount without error', () => {
    const { unmount, container } = render(
      <McpAppFrame resourceUri="ui://probos/x" toolName="t" />,
    );
    expect(container.querySelector('iframe')).not.toBeNull();
    expect(() => unmount()).not.toThrow();
  });

  it('rerenders with new resourceUri', () => {
    const { container, rerender } = render(
      <McpAppFrame resourceUri="ui://probos/a" toolName="t" />,
    );
    const before = container.querySelector('iframe')!.getAttribute('src');
    rerender(<McpAppFrame resourceUri="ui://probos/b" toolName="t" />);
    const after = container.querySelector('iframe')!.getAttribute('src');
    expect(before).not.toBe(after);
  });

  it('accepts toolInput prop without error', () => {
    expect(() =>
      render(
        <McpAppFrame
          resourceUri="ui://probos/x"
          toolName="t"
          toolInput={{ game_id: 'g1' }}
        />,
      ),
    ).not.toThrow();
  });

  it('accepts toolResult prop without error', () => {
    expect(() =>
      render(
        <McpAppFrame
          resourceUri="ui://probos/x"
          toolName="t"
          toolResult={{ status: 'ok' }}
        />,
      ),
    ).not.toThrow();
  });

  it('encodes special characters in resourceUri', () => {
    const { container } = render(
      <McpAppFrame
        resourceUri="ui://probos/games/chess/index.html?x=1"
        toolName="t"
      />,
    );
    const src = container.querySelector('iframe')!.getAttribute('src') || '';
    expect(src).toContain(encodeURIComponent('?x=1'));
  });

  it('default external=false produces internal sandbox', () => {
    const { container } = render(
      <McpAppFrame
        resourceUri="ui://probos/x"
        toolName="t"
        external={false}
      />,
    );
    expect(container.querySelector('iframe')!.getAttribute('sandbox')).toBe(
      'allow-scripts allow-same-origin',
    );
  });
});
