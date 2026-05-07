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

function jsonResp(body: any, ok = true): Response {
  return { ok, json: async () => body } as unknown as Response;
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
  afterEach(() => { cleanup(); vi.restoreAllMocks(); reset(); });

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
      expect(fetchMock).toHaveBeenCalledWith('/api/ontology/graph?include_edges=true');
      expect(fetchMock).toHaveBeenCalledWith('/api/ontology/spatial-layout');
    });
  });

  it('switching from GRAPH to SHIP LAYOUT swaps the rendered child component', async () => {
    vi.spyOn(global, 'fetch').mockImplementation(() => Promise.resolve(jsonResp({ nodes: [{ id: 'x' }], edges: [], generated_at: 0 })));
    useStore.setState({
      spatialExplorerOpen: true,
      spatialGraphData: { nodes: [{ id: 'x' }], edges: [], generated_at: 0 },
      spatialLayoutData: { schema_version: 1, decks: [{ deck_id: 'a', name: 'A', department_id: null, position: [0, 0, 0], dimensions: [1, 1, 1], accent_color: '#fff', post_offsets: {} }] },
    });
    render(<SpatialExplorerPanel />);
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
      expect(fetchMock).toHaveBeenCalledWith('/api/ontology/graph?include_edges=true');
      expect(fetchMock).toHaveBeenCalledWith('/api/ontology/spatial-layout');
    });
  });
});
