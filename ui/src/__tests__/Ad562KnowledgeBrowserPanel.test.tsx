/**
 * AD-562: KnowledgeBrowserPanel tests.
 *
 * Mocks heavy children (RecordsGraphView pulls react-force-graph-3d).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, act, cleanup, waitFor } from '@testing-library/react';

vi.mock('../components/knowledge/RecordsGraphView', () => ({
  default: () => <div data-testid="mock-records-graph-view" />,
}));

import KnowledgeBrowserPanel from '../components/KnowledgeBrowserPanel';
import { useStore } from '../store/useStore';
import { DEFAULT_KNOWLEDGE_BROWSER_FILTERS } from '../components/knowledge/types';

function jsonResp(body: any, ok = true): Response {
  return { ok, json: async () => body } as unknown as Response;
}

function reset() {
  useStore.setState({
    knowledgeBrowserOpen: false,
    knowledgeBrowserView: 'list',
    knowledgeBrowserSelectedPath: null,
    knowledgeBrowserFilters: { ...DEFAULT_KNOWLEDGE_BROWSER_FILTERS },
    knowledgeBrowserEntries: [],
    knowledgeBrowserSelectedDoc: null,
    knowledgeBrowserBacklinks: null,
    knowledgeBrowserGraphData: null,
    knowledgeBrowserTimeline: null,
    knowledgeBrowserLoading: false,
  });
}

describe('KnowledgeBrowserPanel (AD-562)', () => {
  beforeEach(reset);
  afterEach(() => { cleanup(); vi.restoreAllMocks(); reset(); });

  it('renders nothing when knowledgeBrowserOpen=false', () => {
    render(<KnowledgeBrowserPanel />);
    expect(screen.queryByTestId('knowledge-browser-panel')).toBeNull();
  });

  it('renders panel + four view-mode tabs + close button when open', () => {
    useStore.setState({ knowledgeBrowserOpen: true });
    render(<KnowledgeBrowserPanel />);
    expect(screen.getByTestId('knowledge-browser-panel')).toBeTruthy();
    expect(screen.getByTestId('knowledge-tab-list')).toBeTruthy();
    expect(screen.getByTestId('knowledge-tab-reader')).toBeTruthy();
    expect(screen.getByTestId('knowledge-tab-graph')).toBeTruthy();
    expect(screen.getByTestId('knowledge-tab-timeline')).toBeTruthy();
    expect(screen.getByTestId('knowledge-close')).toBeTruthy();
  });

  it('opening triggers fetches of /browse and /graph and /timeline', async () => {
    const fetchMock = vi.spyOn(global, 'fetch').mockImplementation((url: any) => {
      return Promise.resolve(jsonResp({ documents: [], nodes: [], edges: [], buckets: [], total: 0 }));
    });
    await act(async () => {
      await useStore.getState().openKnowledgeBrowser();
    });
    const calls = fetchMock.mock.calls.map(c => String(c[0]));
    expect(calls.some(u => u.startsWith('/api/records/browse'))).toBe(true);
    expect(calls.some(u => u.includes('/api/records/graph?include_quality=true&include_suggested=true'))).toBe(true);
    expect(calls.some(u => u.includes('/api/records/timeline?bucket=day'))).toBe(true);
  });

  it('ESC keypress closes the panel', async () => {
    vi.spyOn(global, 'fetch').mockImplementation(() => Promise.resolve(jsonResp({ documents: [] })));
    useStore.setState({ knowledgeBrowserOpen: true });
    render(<KnowledgeBrowserPanel />);
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(useStore.getState().knowledgeBrowserOpen).toBe(false);
  });

  it('refresh button re-invokes fetches', async () => {
    const fetchMock = vi.spyOn(global, 'fetch').mockImplementation(() => Promise.resolve(jsonResp({ documents: [] })));
    useStore.setState({ knowledgeBrowserOpen: true });
    render(<KnowledgeBrowserPanel />);
    fetchMock.mockClear();
    await act(async () => {
      fireEvent.click(screen.getByTestId('knowledge-refresh'));
    });
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
    });
  });

  it('switching tabs changes the rendered view', () => {
    useStore.setState({ knowledgeBrowserOpen: true, knowledgeBrowserView: 'list' });
    render(<KnowledgeBrowserPanel />);
    expect(screen.getByTestId('knowledge-list-empty')).toBeTruthy();
    fireEvent.click(screen.getByTestId('knowledge-tab-graph'));
    expect(screen.getByTestId('mock-records-graph-view')).toBeTruthy();
  });

  it('backlinks rail hidden when no selection', () => {
    useStore.setState({ knowledgeBrowserOpen: true, knowledgeBrowserView: 'reader', knowledgeBrowserSelectedPath: null });
    render(<KnowledgeBrowserPanel />);
    expect(screen.queryByTestId('knowledge-backlinks-rail')).toBeNull();
  });

  it('backlinks rail visible when reader view + selection', () => {
    useStore.setState({
      knowledgeBrowserOpen: true,
      knowledgeBrowserView: 'reader',
      knowledgeBrowserSelectedPath: 'x.md',
    });
    render(<KnowledgeBrowserPanel />);
    expect(screen.getByTestId('knowledge-backlinks-rail')).toBeTruthy();
  });
});
