/**
 * AD-520: SpatialExplorerPanel tests.
 *
 * Mocks the heavy graph + R3F view children to keep the test fast and DOM-only.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, act, cleanup, waitFor } from '@testing-library/react';

// Mock the children that pull WebGL / r3f / force-graph
vi.mock('../components/spatial/KnowledgeGraphView', () => ({
  default: () => <div data-testid="mock-knowledge-graph-view" />,
}));
vi.mock('../components/spatial/ShipLayoutView', () => ({
  default: () => <div data-testid="mock-ship-layout-view" />,
}));

import SpatialExplorerPanel from '../components/SpatialExplorerPanel';
import { useStore } from '../store/useStore';
import { RESOURCE_TIMEOUT_MS } from '../utils/resourceState';

function jsonResp(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response;
}

const GRAPH = { nodes: [{ id: 'x' }], edges: [], generated_at: 0 };
const LAYOUT = { schema_version: 1, decks: [{ deck_id: 'a', name: 'A', department_id: null, position: [0, 0, 0], dimensions: [1, 1, 1], accent_color: '#fff', post_offsets: {} }] };

function successfulResponse(url: unknown): Promise<Response> {
  return Promise.resolve(jsonResp(String(url).includes('spatial-layout') ? LAYOUT : GRAPH));
}

function deferredResponse() {
  let resolve!: (response: Response) => void;
  const promise = new Promise<Response>(done => { resolve = done; });
  return { promise, resolve };
}

function reset() {
  useStore.setState({
    spatialExplorerOpen: false,
    spatialViewMode: 'graph',
    spatialSelectedNode: null,
    spatialGraphData: null,
    spatialLayoutData: null,
  });
}

describe('SpatialExplorerPanel (AD-520)', () => {
  beforeEach(reset);
  afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); reset(); });

  it('renders nothing when spatialExplorerOpen=false', () => {
    render(<SpatialExplorerPanel />);
    expect(screen.queryByTestId('spatial-explorer-panel')).toBeNull();
  });

  it('renders panel + view-mode tabs + close button when open=true', async () => {
    vi.spyOn(global, 'fetch').mockImplementation(() => Promise.resolve(jsonResp({ nodes: [], edges: [], generated_at: 0 })));
    useStore.setState({ spatialExplorerOpen: true });
    render(<SpatialExplorerPanel />);
    expect(screen.getByTestId('spatial-explorer-panel')).toBeTruthy();
    expect(screen.getByTestId('spatial-tab-graph')).toBeTruthy();
    expect(screen.getByTestId('spatial-tab-ship')).toBeTruthy();
    expect(screen.getByTestId('spatial-close')).toBeTruthy();
  });

  it('mount triggers fetch of /api/ontology/graph and /api/ontology/spatial-layout', async () => {
    const fetchMock = vi.spyOn(global, 'fetch').mockImplementation((url: any) => {
      if (typeof url === 'string' && url.includes('spatial-layout')) {
        return Promise.resolve(jsonResp({ schema_version: 1, decks: [] }));
      }
      return Promise.resolve(jsonResp({ nodes: [], edges: [], generated_at: 0 }));
    });
    useStore.setState({ spatialExplorerOpen: true });
    await act(async () => {
      render(<SpatialExplorerPanel />);
    });
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith('/api/ontology/graph?include_edges=true', expect.objectContaining({ signal: expect.any(AbortSignal) }));
      expect(fetchMock).toHaveBeenCalledWith('/api/ontology/spatial-layout', expect.objectContaining({ signal: expect.any(AbortSignal) }));
    });
  });

  it('switching from GRAPH to SHIP LAYOUT swaps the rendered child component', async () => {
    vi.spyOn(global, 'fetch').mockImplementation(successfulResponse);
    useStore.setState({ spatialExplorerOpen: true });
    await act(async () => { render(<SpatialExplorerPanel />); });
    expect(screen.getByTestId('mock-knowledge-graph-view')).toBeTruthy();
    fireEvent.click(screen.getByTestId('spatial-tab-ship'));
    expect(screen.getByTestId('mock-ship-layout-view')).toBeTruthy();
    expect(screen.queryByTestId('mock-knowledge-graph-view')).toBeNull();
  });

  it('ESC keypress closes the panel', async () => {
    vi.spyOn(global, 'fetch').mockImplementation(() => Promise.resolve(jsonResp({ nodes: [], edges: [], generated_at: 0 })));
    useStore.setState({ spatialExplorerOpen: true });
    render(<SpatialExplorerPanel />);
    expect(useStore.getState().spatialExplorerOpen).toBe(true);
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(useStore.getState().spatialExplorerOpen).toBe(false);
  });

  it('refresh button re-invokes both fetches', async () => {
    const fetchMock = vi.spyOn(global, 'fetch').mockImplementation(() => Promise.resolve(jsonResp({ nodes: [], edges: [], generated_at: 0 })));
    useStore.setState({ spatialExplorerOpen: true });
    await act(async () => {
      render(<SpatialExplorerPanel />);
    });
    fetchMock.mockClear();
    await act(async () => {
      fireEvent.click(screen.getByTestId('spatial-refresh'));
    });
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith('/api/ontology/graph?include_edges=true', expect.objectContaining({ signal: expect.any(AbortSignal) }));
      expect(fetchMock).toHaveBeenCalledWith('/api/ontology/spatial-layout', expect.objectContaining({ signal: expect.any(AbortSignal) }));
    });
  });

  it('settles graph independently while layout is still loading', async () => {
    const pending = deferredResponse();
    vi.spyOn(global, 'fetch').mockImplementation(url => String(url).includes('spatial-layout')
      ? pending.promise : Promise.resolve(jsonResp(GRAPH)));
    useStore.setState({ spatialExplorerOpen: true });
    await act(async () => { render(<SpatialExplorerPanel />); });
    expect(screen.getByTestId('mock-knowledge-graph-view')).toBeTruthy();
    expect(screen.getByRole('status', { name: 'Ship layout status' }).textContent).toContain('Loading.');
    await act(async () => { pending.resolve(jsonResp({ error: 'Spatial layout not available' }, 503)); });
    expect(screen.getByRole('status', { name: 'Ship layout status' }).textContent).toContain('Unavailable.');
    expect(screen.getByTestId('mock-knowledge-graph-view')).toBeTruthy();
    fireEvent.click(screen.getByTestId('spatial-tab-ship'));
    expect(screen.queryByTestId('mock-ship-layout-view')).toBeNull();
    expect(screen.queryByText(/enable in config|No spatial data/)).toBeNull();
  });

  it('keeps available layout visible when graph fails', async () => {
    vi.spyOn(global, 'fetch').mockImplementation(url => Promise.resolve(String(url).includes('spatial-layout')
      ? jsonResp(LAYOUT) : jsonResp({ error: 'Ontology not initialized' }, 503)));
    useStore.setState({ spatialExplorerOpen: true, spatialViewMode: 'ship' });
    await act(async () => { render(<SpatialExplorerPanel />); });
    expect(screen.getByRole('status', { name: 'Graph status' }).textContent).toContain('Unavailable.');
    expect(screen.getByTestId('mock-ship-layout-view')).toBeTruthy();
  });

  it('distinguishes successful empty snapshots from unavailable resources', async () => {
    vi.spyOn(global, 'fetch').mockImplementation(url => Promise.resolve(jsonResp(String(url).includes('spatial-layout')
      ? { schema_version: 1, decks: [] } : { nodes: [], edges: [], generated_at: 0 })));
    useStore.setState({ spatialExplorerOpen: true });
    await act(async () => { render(<SpatialExplorerPanel />); });
    expect(screen.getByRole('status', { name: 'Graph status' }).textContent).toContain('No results.');
    expect(screen.getByRole('status', { name: 'Ship layout status' }).textContent).toContain('No results.');
    expect(screen.queryByTestId('mock-knowledge-graph-view')).toBeNull();
    expect(screen.queryByText(/enable|unavailable|failed/i)).toBeNull();
  });

  it.each([
    [503, { error: 'Spatial explorer not enabled', availability: { state: 'disabled', code: 'spatial_explorer.disabled', message: 'Spatial explorer disabled', retryable: false } }, 'Disabled.'],
    [401, { detail: 'private diagnostic' }, 'Access denied.'],
    [403, { availability: { state: 'disabled', code: 'spatial_explorer.disabled', message: 'Disabled', retryable: false } }, 'Access denied.'],
    [503, { error: 'private diagnostic' }, 'Unavailable.'],
    [500, { error: 'private diagnostic' }, 'Request failed.'],
    [200, null, 'Request failed.'],
    [200, {}, 'Request failed.'],
    [200, { schema_version: 1, decks: [null] }, 'Request failed.'],
    [200, { ...LAYOUT, decks: [{ ...LAYOUT.decks[0], position: null }] }, 'Request failed.'],
    [200, { ...LAYOUT, decks: [{ ...LAYOUT.decks[0], post_offsets: { captain: [0] } }] }, 'Request failed.'],
  ])('classifies layout response %s without displaying raw diagnostics (%j)', async (status, body, message) => {
    vi.spyOn(global, 'fetch').mockImplementation(url => Promise.resolve(String(url).includes('spatial-layout')
      ? jsonResp(body, status) : jsonResp(GRAPH)));
    useStore.setState({ spatialExplorerOpen: true });
    await act(async () => { render(<SpatialExplorerPanel />); });
    expect(screen.getByRole('status', { name: 'Ship layout status' }).textContent).toContain(message);
    expect(screen.getByTestId('mock-knowledge-graph-view')).toBeTruthy();
    expect(screen.queryByText(/private diagnostic/)).toBeNull();
  });

  it.each([null, {}, { ...GRAPH, nodes: [null] }, { ...GRAPH, edges: [null] }, { ...GRAPH, generated_at: null }])(
    'rejects malformed graph without hiding layout: %j', async body => {
      vi.spyOn(global, 'fetch').mockImplementation(url => Promise.resolve(String(url).includes('spatial-layout')
        ? jsonResp(LAYOUT) : jsonResp(body)));
      useStore.setState({ spatialExplorerOpen: true, spatialViewMode: 'ship' });
      await act(async () => { render(<SpatialExplorerPanel />); });
      expect(screen.getByRole('status', { name: 'Graph status' }).textContent).toContain('Request failed.');
      expect(screen.getByTestId('mock-ship-layout-view')).toBeTruthy();
    },
  );

  it('retains same-identity stale data and recovers on manual refresh', async () => {
    const fetchMock = vi.spyOn(global, 'fetch').mockImplementation(successfulResponse);
    useStore.setState({ spatialExplorerOpen: true });
    await act(async () => { render(<SpatialExplorerPanel />); });
    const observed = screen.getByRole('status', { name: 'Graph status' }).querySelector('time')!.dateTime;
    fetchMock.mockImplementation(() => Promise.resolve(jsonResp({ error: 'private diagnostic' }, 503)));
    const refresh = screen.getByRole('button', { name: 'Refresh' });
    expect(refresh.tagName).toBe('BUTTON');
    refresh.focus();
    expect(document.activeElement).toBe(refresh);
    await act(async () => { fireEvent.click(refresh); });
    expect(screen.getByRole('status', { name: 'Graph status' }).textContent).toContain('Unavailable.');
    expect(screen.getByRole('status', { name: 'Graph status' }).textContent).toContain('Stale snapshot.');
    expect(screen.getByRole('status', { name: 'Graph status' }).querySelector('time')!.dateTime).toBe(observed);
    expect(screen.getByTestId('mock-knowledge-graph-view')).toBeTruthy();
    expect(useStore.getState().spatialGraphData).toEqual(GRAPH);
    fetchMock.mockImplementation(successfulResponse);
    await act(async () => { fireEvent.click(refresh); });
    expect(screen.getByRole('status', { name: 'Graph status' }).textContent).toContain('Available.');
    expect(screen.queryByText(/Stale snapshot/)).toBeNull();
  });

  it('clears cached data and selection after unauthorized refresh', async () => {
    const fetchMock = vi.spyOn(global, 'fetch').mockImplementation(successfulResponse);
    useStore.setState({ spatialExplorerOpen: true });
    await act(async () => { render(<SpatialExplorerPanel />); });
    expect(useStore.getState().spatialGraphData).toEqual(GRAPH);
    fetchMock.mockImplementation(() => Promise.resolve(jsonResp({ detail: 'Access denied' }, 403)));
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Refresh' })); });
    expect(screen.getByRole('status', { name: 'Graph status' }).textContent).toContain('Access denied.');
    expect(useStore.getState().spatialGraphData).toBeNull();
    expect(useStore.getState().spatialLayoutData).toBeNull();
    expect(useStore.getState().spatialSelectedNode).toBeNull();
    expect(screen.queryByTestId('mock-knowledge-graph-view')).toBeNull();
  });

  it('bounds hung reads and never starts background retries', async () => {
    vi.useFakeTimers();
    const signals: AbortSignal[] = [];
    const fetchMock = vi.spyOn(global, 'fetch').mockImplementation((_url, options) => {
      signals.push(options!.signal as AbortSignal);
      return new Promise<Response>(() => {});
    });
    useStore.setState({ spatialExplorerOpen: true });
    await act(async () => { render(<SpatialExplorerPanel />); });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(screen.getByRole('status', { name: 'Graph status' }).textContent).toContain('Loading.');
    await act(async () => { await vi.advanceTimersByTimeAsync(RESOURCE_TIMEOUT_MS); });
    expect(signals.every(signal => signal.aborted)).toBe(true);
    expect(screen.getByRole('status', { name: 'Graph status' }).textContent).toContain('Unavailable.');
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    fetchMock.mockImplementation(successfulResponse);
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Refresh' })); });
    expect(fetchMock).toHaveBeenCalledTimes(4);
    expect(screen.getByTestId('mock-knowledge-graph-view')).toBeTruthy();
  });

  it('aborts replaced reads and ignores late responses after refresh', async () => {
    const pending = deferredResponse();
    const signals: AbortSignal[] = [];
    const fetchMock = vi.spyOn(global, 'fetch').mockImplementation((_url, options) => {
      signals.push(options!.signal as AbortSignal);
      return pending.promise;
    });
    useStore.setState({ spatialExplorerOpen: true });
    await act(async () => { render(<SpatialExplorerPanel />); });
    expect(signals).toHaveLength(2);
    fetchMock.mockImplementation(successfulResponse);
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Refresh' })); });
    expect(signals.every(signal => signal.aborted)).toBe(true);
    await act(async () => { pending.resolve(jsonResp({ error: 'Old failure' }, 503)); });
    expect(useStore.getState().spatialGraphData).toEqual(GRAPH);
    expect(screen.getByRole('status', { name: 'Graph status' }).textContent).toContain('Available.');
  });

  it.each(['close', 'unmount'])('aborts on %s and ignores late data', async action => {
    const pending = deferredResponse();
    const signals: AbortSignal[] = [];
    const fetchMock = vi.spyOn(global, 'fetch').mockImplementation((_url, options) => {
      signals.push(options!.signal as AbortSignal);
      return pending.promise;
    });
    useStore.setState({ spatialExplorerOpen: true });
    const mounted = render(<SpatialExplorerPanel />);
    expect(signals).toHaveLength(2);
    await act(async () => {
      if (action === 'close') fireEvent.click(screen.getByRole('button', { name: 'Close' }));
      else mounted.unmount();
    });
    expect(signals.every(signal => signal.aborted)).toBe(true);
    await act(async () => { pending.resolve(jsonResp(GRAPH)); });
    expect(useStore.getState().spatialGraphData).toBeNull();
    expect(useStore.getState().spatialLayoutData).toBeNull();
    if (action === 'close') {
      fetchMock.mockImplementation(successfulResponse);
      await act(async () => { useStore.setState({ spatialExplorerOpen: true }); });
      expect(screen.getByTestId('mock-knowledge-graph-view')).toBeTruthy();
      expect(fetchMock).toHaveBeenCalledTimes(4);
    }
  });
});
