/**
 * AD-562: EntryReader tests.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import EntryReader from '../components/knowledge/EntryReader';
import { useStore } from '../store/useStore';

function reset() {
  useStore.setState({
    knowledgeBrowserSelectedDoc: null,
    knowledgeBrowserSelectedPath: null,
  });
}

describe('EntryReader (AD-562)', () => {
  beforeEach(reset);
  afterEach(() => { cleanup(); vi.restoreAllMocks(); reset(); });

  it('renders empty state when no doc selected', () => {
    render(<EntryReader />);
    expect(screen.getByTestId('knowledge-reader-empty')).toBeTruthy();
  });

  it('renders frontmatter sidebar fields', () => {
    useStore.setState({
      knowledgeBrowserSelectedDoc: {
        path: 'x.md',
        content: '',
        frontmatter: { author: 'chapel', department: 'medical', classification: 'private', created: '2026-05-01', updated: '2026-05-02', revision_count: 3, tags: ['trust'] },
      },
    });
    render(<EntryReader />);
    const fm = screen.getByTestId('reader-frontmatter');
    expect(fm.textContent).toContain('chapel');
    expect(fm.textContent).toContain('medical');
    expect(fm.textContent).toContain('private');
    expect(screen.getByTestId('reader-tags')).toBeTruthy();
  });

  it('renders headings and bold and wikilinks', () => {
    useStore.setState({
      knowledgeBrowserSelectedDoc: {
        path: 'x.md',
        content: '# Heading\n\nThis is **bold** and a [[wikilink]] reference.',
        frontmatter: {},
      },
    });
    render(<EntryReader />);
    expect(screen.getByText('Heading')).toBeTruthy();
    expect(screen.getByText('bold').tagName).toBe('B');
    expect(screen.getByTestId('reader-wikilink').textContent).toBe('wikilink');
  });

  it('clicking a wikilink calls selectKnowledgeBrowserEntry', () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({ ok: true, json: async () => ({}) } as Response);
    useStore.setState({
      knowledgeBrowserSelectedDoc: {
        path: 'x.md',
        content: 'see [[target.md]] for details',
        frontmatter: {},
      },
    });
    render(<EntryReader />);
    fireEvent.click(screen.getByTestId('reader-wikilink'));
    expect(useStore.getState().knowledgeBrowserSelectedPath).toBe('target.md');
  });

  it('renders empty-content sentinel when content is empty', () => {
    useStore.setState({
      knowledgeBrowserSelectedDoc: { path: 'x.md', content: '', frontmatter: {} },
    });
    render(<EntryReader />);
    expect(screen.getByTestId('reader-empty-content')).toBeTruthy();
  });
});
