/**
 * AD-562: EntryListView tests.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import EntryListView from '../components/knowledge/EntryListView';
import { useStore } from '../store/useStore';

function reset() {
  useStore.setState({
    knowledgeBrowserEntries: [],
    knowledgeBrowserSelectedPath: null,
    knowledgeBrowserView: 'list',
  });
}

describe('EntryListView (AD-562)', () => {
  beforeEach(reset);
  afterEach(() => { cleanup(); vi.restoreAllMocks(); reset(); });

  it('renders empty state when no entries', () => {
    render(<EntryListView />);
    expect(screen.getByTestId('knowledge-list-empty')).toBeTruthy();
  });

  it('renders entries with dept chip and class badge', () => {
    useStore.setState({
      knowledgeBrowserEntries: [
        { path: 'notebooks/chapel/n1.md', frontmatter: { author: 'chapel', department: 'medical', classification: 'private', created: '2026-05-01' } },
      ],
    });
    render(<EntryListView />);
    expect(screen.getByTestId('knowledge-list-row-notebooks/chapel/n1.md')).toBeTruthy();
    expect(screen.getAllByTestId('row-dept-chip').length).toBeGreaterThan(0);
    expect(screen.getAllByTestId('row-class-badge').length).toBeGreaterThan(0);
  });

  it('clicking a row triggers selectKnowledgeBrowserEntry', async () => {
    const fetchMock = vi.spyOn(global, 'fetch').mockResolvedValue({ ok: true, json: async () => ({}) } as Response);
    useStore.setState({
      knowledgeBrowserEntries: [
        { path: 'a.md', frontmatter: { author: 'x' } },
      ],
    });
    render(<EntryListView />);
    fireEvent.click(screen.getByTestId('knowledge-list-row-a.md'));
    // selectKnowledgeBrowserEntry sets selectedPath synchronously
    expect(useStore.getState().knowledgeBrowserSelectedPath).toBe('a.md');
    expect(fetchMock).toHaveBeenCalled();
  });

  it('shows "more" footer when entries > 200', () => {
    const entries = Array.from({ length: 250 }, (_, i) => ({
      path: `n${i}.md`, frontmatter: { author: 'x' },
    }));
    useStore.setState({ knowledgeBrowserEntries: entries });
    render(<EntryListView />);
    expect(screen.getByTestId('knowledge-list-more')).toBeTruthy();
    expect(screen.getByTestId('knowledge-list-more').textContent).toContain('50 more');
  });

  it('classification defaults to "ship" when missing', () => {
    useStore.setState({
      knowledgeBrowserEntries: [
        { path: 'a.md', frontmatter: { author: 'x' } },
      ],
    });
    render(<EntryListView />);
    const badge = screen.getByTestId('row-class-badge');
    expect(badge.textContent).toBe('ship');
  });
});
