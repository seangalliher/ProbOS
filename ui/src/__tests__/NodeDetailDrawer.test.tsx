/**
 * AD-520: NodeDetailDrawer tests.
 */
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import NodeDetailDrawer from '../components/spatial/NodeDetailDrawer';
import { useStore } from '../store/useStore';

function reset() {
  useStore.setState({
    spatialSelectedNode: null,
  });
}

describe('NodeDetailDrawer (AD-520)', () => {
  beforeEach(reset);
  afterEach(() => { cleanup(); reset(); });

  it('renders nothing when spatialSelectedNode is null', () => {
    render(<NodeDetailDrawer />);
    expect(screen.queryByTestId('node-detail-drawer')).toBeNull();
  });

  it('renders agent payload as 2-column table for kind=agent', () => {
    useStore.setState({
      spatialSelectedNode: {
        kind: 'agent',
        id: 'scout-1',
        payload: { department: 'science', rank: 'ensign', post: 'scout', trust: 0.75, on_watch: true },
      },
    });
    render(<NodeDetailDrawer />);
    expect(screen.getByTestId('node-detail-drawer')).toBeTruthy();
    expect(screen.getByTestId('detail-row-department')).toBeTruthy();
    expect(screen.getByTestId('detail-row-rank')).toBeTruthy();
    expect(screen.getByTestId('detail-row-post')).toBeTruthy();
    expect(screen.getByTestId('detail-row-trust')).toBeTruthy();
    expect(screen.getByTestId('detail-row-on_watch')).toBeTruthy();
    expect(screen.getByText('science')).toBeTruthy();
  });

  it('renders edge payload as 2-column table for kind=edge', () => {
    useStore.setState({
      spatialSelectedNode: {
        kind: 'edge',
        id: 'reports_to:a:b',
        payload: { relation: 'reports_to', weight: 0.9, confidence: 0.8, source: 'a', target: 'b' },
      },
    });
    render(<NodeDetailDrawer />);
    expect(screen.getByTestId('detail-row-relation')).toBeTruthy();
    expect(screen.getByTestId('detail-row-weight')).toBeTruthy();
    expect(screen.getByTestId('detail-row-confidence')).toBeTruthy();
    expect(screen.getByTestId('detail-row-source')).toBeTruthy();
    expect(screen.getByTestId('detail-row-target')).toBeTruthy();
  });

  it('close button clears selection', () => {
    useStore.setState({
      spatialSelectedNode: { kind: 'agent', id: 'a', payload: {} },
    });
    render(<NodeDetailDrawer />);
    fireEvent.click(screen.getByTestId('node-detail-close'));
    expect(useStore.getState().spatialSelectedNode).toBeNull();
  });
});
