/**
 * AD-523b: Crew Notebooks Browser tests.
 * Mirrors WardRoomPanel.test.tsx mocking pattern with fetch stubs per test.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor, act, cleanup } from '@testing-library/react';
import NotebooksPanel from '../components/NotebooksPanel';
import { useStore } from '../store/useStore';

function resetStore() {
  useStore.setState({
    notebooksOpen: false,
    notebooksAuthors: [],
    notebooksEntries: [],
    notebooksSelectedAuthor: null,
    notebooksSelectedEntry: null,
    notebooksSearchQuery: '',
    notebooksSearchResults: null,
    notebooksLoading: false,
  });
}

function jsonResp(body: any, ok = true): Response {
  return {
    ok,
    json: async () => body,
  } as unknown as Response;
}

describe('NotebooksPanel (AD-523b)', () => {
  beforeEach(() => {
    resetStore();
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    resetStore();
  });

  it('renders nothing when notebooksOpen is false', () => {
    render(<NotebooksPanel />);
    expect(screen.queryByTestId('notebooks-panel')).toBeNull();
  });

  it('renders panel and fetches authors on open', async () => {
    const fetchMock = vi.spyOn(global, 'fetch').mockResolvedValue(jsonResp({
      documents: [
        { path: 'notebooks/atlas/topic-a.md', frontmatter: { author: 'atlas', department: 'engineering', topic: 'Topic A' } },
        { path: 'notebooks/atlas/topic-b.md', frontmatter: { author: 'atlas', department: 'engineering', topic: 'Topic B' } },
        { path: 'notebooks/sage/topic-c.md', frontmatter: { author: 'sage', department: 'science', topic: 'Topic C' } },
      ],
    }));
    render(<NotebooksPanel />);
    await act(async () => {
      await useStore.getState().openNotebooks();
    });
    expect(fetchMock).toHaveBeenCalledWith('/api/records/documents?directory=notebooks');
    expect(screen.getByTestId('notebooks-panel')).toBeTruthy();
    expect(screen.getByTestId('notebooks-author-atlas')).toBeTruthy();
    expect(screen.getByTestId('notebooks-author-sage')).toBeTruthy();
    // Department headers
    expect(screen.getByText('engineering')).toBeTruthy();
    expect(screen.getByText('science')).toBeTruthy();
    // Entry count badges (atlas=2, sage=1)
    const atlasRow = screen.getByTestId('notebooks-author-atlas');
    expect(atlasRow.textContent).toContain('2');
    const sageRow = screen.getByTestId('notebooks-author-sage');
    expect(sageRow.textContent).toContain('1');
  });

  it("selecting an author fetches that author's entries sorted newest first", async () => {
    useStore.setState({
      notebooksOpen: true,
      notebooksAuthors: [{ callsign: 'atlas', department: 'engineering', entryCount: 2 }],
    });
    vi.spyOn(global, 'fetch').mockResolvedValue(jsonResp({
      documents: [
        { path: 'notebooks/atlas/old.md', frontmatter: { topic: 'Old', updated: '2026-01-01T00:00:00Z' } },
        { path: 'notebooks/atlas/new.md', frontmatter: { topic: 'New', updated: '2026-05-01T00:00:00Z' } },
        { path: 'notebooks/atlas/mid.md', frontmatter: { topic: 'Mid', updated: '2026-03-01T00:00:00Z' } },
      ],
    }));
    render(<NotebooksPanel />);
    await act(async () => {
      await useStore.getState().selectNotebookAuthor('atlas');
    });
    const entriesCol = screen.getByTestId('notebooks-entries');
    const items = entriesCol.querySelectorAll('[data-testid^="notebooks-entry-"]');
    expect(items.length).toBe(3);
    expect(items[0].getAttribute('data-testid')).toBe('notebooks-entry-notebooks/atlas/new.md');
    expect(items[1].getAttribute('data-testid')).toBe('notebooks-entry-notebooks/atlas/mid.md');
    expect(items[2].getAttribute('data-testid')).toBe('notebooks-entry-notebooks/atlas/old.md');
  });

  it('selecting an entry fetches detail and renders body + frontmatter', async () => {
    useStore.setState({
      notebooksOpen: true,
      notebooksAuthors: [{ callsign: 'atlas', department: 'engineering', entryCount: 1 }],
      notebooksSelectedAuthor: 'atlas',
      notebooksEntries: [{ path: 'notebooks/atlas/topic-a.md', frontmatter: { topic: 'Topic A' } }],
    });
    vi.spyOn(global, 'fetch').mockResolvedValue(jsonResp({
      path: 'notebooks/atlas/topic-a.md',
      frontmatter: { author: 'atlas', department: 'engineering', topic: 'Topic A', classification: 'ship' },
      content: '# Body of Topic A\n\nMarkdown contents here.',
    }));
    render(<NotebooksPanel />);
    await act(async () => {
      await useStore.getState().selectNotebookEntry('notebooks/atlas/topic-a.md');
    });
    const detail = screen.getByTestId('notebooks-detail');
    expect(detail.textContent).toContain('Topic A');
    expect(detail.textContent).toContain('atlas');
    expect(detail.textContent).toContain('engineering');
    expect(detail.textContent).toContain('ship');
    const body = screen.getByTestId('notebooks-detail-body');
    expect(body.textContent).toContain('Body of Topic A');
    expect(body.textContent).toContain('Markdown contents here.');
  });

  it('classification badge uses the correct color per level', async () => {
    useStore.setState({
      notebooksOpen: true,
      notebooksAuthors: [{ callsign: 'atlas', department: 'engineering', entryCount: 1 }],
      notebooksSelectedAuthor: 'atlas',
      notebooksEntries: [
        {
          path: 'notebooks/atlas/secret.md',
          frontmatter: { topic: 'Secret', classification: 'private' },
        },
      ],
    });
    render(<NotebooksPanel />);
    const entry = screen.getByTestId('notebooks-entry-notebooks/atlas/secret.md');
    const badge = Array.from(entry.querySelectorAll('span')).find(
      s => s.textContent === 'PRIVATE'
    );
    expect(badge).toBeTruthy();
    // CLASS_COLORS.private = '#7060a8' — rendered as RGB by jsdom getComputedStyle
    const color = (badge as HTMLElement).style.color;
    expect(color.replace(/\s/g, '').toLowerCase()).toMatch(/#7060a8|rgb\(112,96,168\)/);
  });

  it('search runs against /api/records/search and filters to notebooks/* paths', async () => {
    useStore.setState({ notebooksOpen: true, notebooksSearchQuery: 'reactor' });
    vi.spyOn(global, 'fetch').mockResolvedValue(jsonResp({
      results: [
        { path: 'notebooks/atlas/reactor-a.md', frontmatter: { topic: 'Reactor A', author: 'atlas' }, score: 0.95, snippet: 'reactor coolant' },
        { path: 'notebooks/sage/reactor-b.md', frontmatter: { topic: 'Reactor B', author: 'sage' }, score: 0.81, snippet: 'reactor flux' },
        { path: 'captains-log/2026-05-01.md', frontmatter: { topic: 'Daily log' }, score: 0.6, snippet: 'reactor offline' },
      ],
    }));
    render(<NotebooksPanel />);
    await act(async () => {
      await useStore.getState().runNotebookSearch();
    });
    const entriesCol = screen.getByTestId('notebooks-entries');
    expect(entriesCol.textContent).toContain('2 results');
    expect(screen.getByTestId('notebooks-search-result-notebooks/atlas/reactor-a.md')).toBeTruthy();
    expect(screen.getByTestId('notebooks-search-result-notebooks/sage/reactor-b.md')).toBeTruthy();
    expect(screen.queryByTestId('notebooks-search-result-captains-log/2026-05-01.md')).toBeNull();
  });

  it('clearing search returns to author-selected entries view', async () => {
    useStore.setState({
      notebooksOpen: true,
      notebooksAuthors: [{ callsign: 'atlas', department: 'engineering', entryCount: 1 }],
      notebooksSelectedAuthor: 'atlas',
      notebooksEntries: [{ path: 'notebooks/atlas/topic-a.md', frontmatter: { topic: 'Topic A' } }],
      notebooksSearchQuery: 'reactor',
      notebooksSearchResults: [
        { path: 'notebooks/atlas/reactor.md', frontmatter: { topic: 'Reactor' }, score: 0.5, snippet: 'r' },
      ],
    });
    render(<NotebooksPanel />);
    // In search mode, the author entry is not visible
    expect(screen.queryByTestId('notebooks-entry-notebooks/atlas/topic-a.md')).toBeNull();
    expect(screen.getByTestId('notebooks-search-result-notebooks/atlas/reactor.md')).toBeTruthy();
    await act(async () => {
      fireEvent.click(screen.getByTestId('notebooks-search-clear'));
    });
    await waitFor(() => {
      expect(screen.queryByTestId('notebooks-search-result-notebooks/atlas/reactor.md')).toBeNull();
    });
    expect(screen.getByTestId('notebooks-entry-notebooks/atlas/topic-a.md')).toBeTruthy();
    expect(useStore.getState().notebooksSearchQuery).toBe('');
  });

  it('closing the panel resets selection state', async () => {
    useStore.setState({
      notebooksOpen: true,
      notebooksAuthors: [{ callsign: 'atlas', department: 'engineering', entryCount: 1 }],
      notebooksSelectedAuthor: 'atlas',
      notebooksEntries: [{ path: 'notebooks/atlas/topic-a.md', frontmatter: { topic: 'A' } }],
      notebooksSelectedEntry: {
        path: 'notebooks/atlas/topic-a.md',
        frontmatter: { topic: 'A' },
        content: 'body',
      },
      notebooksSearchQuery: 'q',
      notebooksSearchResults: [],
    });
    render(<NotebooksPanel />);
    await act(async () => {
      fireEvent.click(screen.getByTestId('notebooks-close'));
    });
    const s = useStore.getState();
    expect(s.notebooksOpen).toBe(false);
    expect(s.notebooksSelectedAuthor).toBeNull();
    expect(s.notebooksSelectedEntry).toBeNull();
    expect(s.notebooksEntries).toEqual([]);
    expect(s.notebooksSearchQuery).toBe('');
    expect(s.notebooksSearchResults).toBeNull();
  });
});
