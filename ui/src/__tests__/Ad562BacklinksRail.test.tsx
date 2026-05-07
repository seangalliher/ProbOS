/**
 * AD-562: BacklinksRail tests.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import BacklinksRail from '../components/knowledge/BacklinksRail';
import { useStore } from '../store/useStore';

function reset() {
  useStore.setState({
    knowledgeBrowserBacklinks: null,
    knowledgeBrowserSelectedPath: null,
  });
}

describe('BacklinksRail (AD-562)', () => {
  beforeEach(reset);
  afterEach(() => { cleanup(); vi.restoreAllMocks(); reset(); });

  it('renders three labelled sections when data present', () => {
    useStore.setState({
      knowledgeBrowserBacklinks: {
        path: 'x.md',
        references: [{ kind: 'callsign', target: 'chapel', raw_match: '@chapel' }],
        referenced_by: ['y.md'],
        suggested: [{ path: 'z.md', similarity: 0.5 }],
      },
    });
    render(<BacklinksRail />);
    const rail = screen.getByTestId('knowledge-backlinks-rail');
    expect(rail.textContent).toContain('Referenced by');
    expect(rail.textContent).toContain('References');
    expect(rail.textContent).toContain('Suggested');
    expect(screen.getByTestId('backlink-incoming').textContent).toBe('y.md');
    expect(screen.getByTestId('backlink-suggested').textContent).toContain('z.md');
  });

  it('shows em-dash for empty sections', () => {
    useStore.setState({
      knowledgeBrowserBacklinks: {
        path: 'x.md', references: [], referenced_by: [], suggested: [],
      },
    });
    render(<BacklinksRail />);
    const rail = screen.getByTestId('knowledge-backlinks-rail');
    // 3 sections → 3 em-dashes
    expect(rail.textContent?.split('—').length).toBeGreaterThanOrEqual(4);
  });

  it('clicking an incoming backlink calls selectKnowledgeBrowserEntry', () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ path: 'y.md', references: [], referenced_by: [], suggested: [] }),
    } as Response);
    useStore.setState({
      knowledgeBrowserBacklinks: {
        path: 'x.md', references: [], referenced_by: ['y.md'], suggested: [],
      },
    });
    render(<BacklinksRail />);
    fireEvent.click(screen.getByTestId('backlink-incoming'));
    expect(useStore.getState().knowledgeBrowserSelectedPath).toBe('y.md');
  });
});
