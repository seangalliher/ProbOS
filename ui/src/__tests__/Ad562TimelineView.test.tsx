/**
 * AD-562: TimelineView tests.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import TimelineView from '../components/knowledge/TimelineView';
import { useStore } from '../store/useStore';

function reset() {
  useStore.setState({ knowledgeBrowserTimeline: null });
}

describe('TimelineView (AD-562)', () => {
  beforeEach(reset);
  afterEach(() => { cleanup(); vi.restoreAllMocks(); reset(); });

  it('renders empty state when total=0', () => {
    useStore.setState({ knowledgeBrowserTimeline: { buckets: [], total: 0, bucket: 'day' } });
    render(<TimelineView />);
    expect(screen.getByTestId('knowledge-timeline-empty')).toBeTruthy();
  });

  it('renders empty state when timeline is null', () => {
    render(<TimelineView />);
    expect(screen.getByTestId('knowledge-timeline-empty')).toBeTruthy();
  });

  it('renders bars per bucket', () => {
    useStore.setState({
      knowledgeBrowserTimeline: {
        buckets: [
          { date: '2026-05-01', count: 2, by_department: { science: 1, medical: 1 } },
          { date: '2026-05-02', count: 1, by_department: { science: 1 } },
        ],
        total: 3, bucket: 'day',
      },
    });
    render(<TimelineView />);
    expect(screen.getByTestId('timeline-bar-2026-05-01')).toBeTruthy();
    expect(screen.getByTestId('timeline-bar-2026-05-02')).toBeTruthy();
    expect(screen.getByTestId('timeline-bar-2026-05-01-science')).toBeTruthy();
    expect(screen.getByTestId('timeline-bar-2026-05-01-medical')).toBeTruthy();
  });

  it('hover surfaces a tooltip with breakdown', () => {
    useStore.setState({
      knowledgeBrowserTimeline: {
        buckets: [{ date: '2026-05-01', count: 2, by_department: { science: 1, medical: 1 } }],
        total: 2, bucket: 'day',
      },
    });
    render(<TimelineView />);
    fireEvent.mouseEnter(screen.getByTestId('timeline-bar-2026-05-01-science'));
    const tt = screen.getByTestId('timeline-tooltip');
    expect(tt.textContent).toContain('2026-05-01');
    expect(tt.textContent).toContain('science:1');
  });
});
