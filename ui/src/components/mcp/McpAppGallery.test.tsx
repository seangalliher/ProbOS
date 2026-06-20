/** AD-1024 vitest — McpAppGallery (the inner MCP-app launcher surface).
 *
 * Deps-injected (no global fetch mock, no real network), mirroring the AD-1023
 * WorkspacePanel / AD-1018 McpServersPanel tests. Proves: loading -> list, click
 * -> the app opens into the (stubbed) frame with its resourceUri/external,
 * disabled honest-degrade (both a throw and a reported-disabled result), the
 * enabled-but-empty state, and the HXI no-emoji guard. Uses async findByTestId.
 */
import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';
import { McpAppGallery } from './McpAppGallery';
import type { McpAppsResult } from './mcpAppsApi';
import type { McpAppFrameProps } from '../../mcpApps/types';

const EMOJI = /\p{Extended_Pictographic}/u;

// Stub frame (assignable to typeof McpAppFrame) that surfaces the props it got.
const FakeFrame = (props: McpAppFrameProps) => (
  <div
    data-testid="fake-frame"
    data-resource-uri={props.resourceUri}
    data-tool-name={props.toolName}
    data-external={String(props.external)}
  />
);

function makeApps(): McpAppsResult {
  return {
    apps: [
      { name: 'chess', description: 'Play chess', resource_uri: 'ui://probos/games/chess/index.html', external: false, server_id: '' },
      { name: 'weather', description: 'Weather', resource_uri: 'ui://external/srv-weather/index.html', external: true, server_id: 'srv-weather' },
    ],
    disabled: false,
  };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('AD-1024 McpAppGallery', () => {
  it('loads then lists the apps from the injected fetchApps (no frame until clicked)', async () => {
    const fetchApps = vi.fn(async () => makeApps());
    render(<McpAppGallery deps={{ fetchApps, IframeFrame: FakeFrame }} />);
    expect(await screen.findByTestId('mcp-app-chess')).toBeTruthy();
    expect(screen.getByTestId('mcp-app-weather')).toBeTruthy();
    expect(fetchApps).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId('mcp-app-frame')).toBeNull();
  });

  it('opens the clicked app into the frame with its resourceUri + external', async () => {
    render(<McpAppGallery deps={{ fetchApps: async () => makeApps(), IframeFrame: FakeFrame }} />);
    fireEvent.click(await screen.findByTestId('mcp-app-weather'));
    expect(await screen.findByTestId('mcp-app-frame')).toBeTruthy();
    const inner = screen.getByTestId('fake-frame');
    expect(inner.getAttribute('data-resource-uri')).toBe('ui://external/srv-weather/index.html');
    expect(inner.getAttribute('data-external')).toBe('true');
    expect(inner.getAttribute('data-tool-name')).toBe('weather');
  });

  it('honest-degrades to the disabled state when the fetch throws', async () => {
    render(<McpAppGallery deps={{ fetchApps: async () => { throw new Error('boom'); }, IframeFrame: FakeFrame }} />);
    expect(await screen.findByTestId('mcp-app-disabled')).toBeTruthy();
  });

  it('shows the disabled note when the endpoint reports disabled (GET 404)', async () => {
    render(<McpAppGallery deps={{ fetchApps: async () => ({ apps: [], disabled: true }), IframeFrame: FakeFrame }} />);
    expect(await screen.findByTestId('mcp-app-disabled')).toBeTruthy();
  });

  it('shows the empty state when enabled with no apps', async () => {
    render(<McpAppGallery deps={{ fetchApps: async () => ({ apps: [], disabled: false }), IframeFrame: FakeFrame }} />);
    expect(await screen.findByTestId('mcp-app-empty')).toBeTruthy();
  });

  it('renders no emoji', async () => {
    const { container } = render(<McpAppGallery deps={{ fetchApps: async () => makeApps(), IframeFrame: FakeFrame }} />);
    await screen.findByTestId('mcp-app-chess');
    expect(EMOJI.test(container.textContent || '')).toBe(false);
  });
});
