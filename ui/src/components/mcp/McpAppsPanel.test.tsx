/** AD-1024 vitest — McpAppsPanel (the store-flag overlay hosting the gallery).
 *
 * Mirrors the AD-1018 McpServersPanel test: store-flag gated (mounted-but-null
 * when closed -> no fetch), deps forwarded to the gallery (no global fetch mock),
 * close via the header X and via Escape, and the HXI no-emoji guard.
 */
import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';
import { McpAppsPanel } from './McpAppsPanel';
import { useStore } from '../../store/useStore';
import type { McpAppGalleryDeps } from './McpAppGallery';

const EMOJI = /\p{Extended_Pictographic}/u;

const stubDeps: McpAppGalleryDeps = {
  fetchApps: async () => ({ apps: [], disabled: false }),
};

beforeEach(() => {
  useStore.setState({ mcpAppsOpen: true });
});

afterEach(() => {
  useStore.setState({ mcpAppsOpen: false });
  cleanup();
  vi.restoreAllMocks();
});

describe('AD-1024 McpAppsPanel', () => {
  it('renders nothing when closed and does not fetch', () => {
    useStore.setState({ mcpAppsOpen: false });
    const fetchApps = vi.fn(async () => ({ apps: [], disabled: false }));
    const { container } = render(<McpAppsPanel deps={{ fetchApps }} />);
    expect(container.firstChild).toBeNull();
    expect(fetchApps).not.toHaveBeenCalled();
  });

  it('renders the overlay (and the gallery) when open', async () => {
    render(<McpAppsPanel deps={stubDeps} />);
    expect(await screen.findByTestId('mcp-apps-panel')).toBeTruthy();
    expect(screen.getByTestId('mcp-app-gallery')).toBeTruthy();
  });

  it('closes on the header X (mcpAppsOpen -> false)', async () => {
    render(<McpAppsPanel deps={stubDeps} />);
    await screen.findByTestId('mcp-apps-panel');
    fireEvent.click(screen.getByTestId('mcp-apps-close'));
    expect(useStore.getState().mcpAppsOpen).toBe(false);
  });

  it('closes on Escape', async () => {
    render(<McpAppsPanel deps={stubDeps} />);
    await screen.findByTestId('mcp-apps-panel');
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(useStore.getState().mcpAppsOpen).toBe(false);
  });

  it('renders no emoji', async () => {
    const { container } = render(<McpAppsPanel deps={stubDeps} />);
    await screen.findByTestId('mcp-apps-panel');
    expect(EMOJI.test(container.textContent || '')).toBe(false);
  });
});
