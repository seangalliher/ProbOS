/**
 * AD-562: RecordsGraphView tests.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';

let lastProps: any = null;
vi.mock('react-force-graph-3d', () => ({
  default: (props: any) => {
    lastProps = props;
    const nodes = props.graphData?.nodes || [];
    const links = props.graphData?.links || [];
    return (
      <div data-testid="mock-force-graph" data-nodes={nodes.length} data-links={links.length}>
        {nodes.map((n: any) => (
          <button
            key={n.id}
            data-testid={`mock-node-${n.id}`}
            data-color={typeof props.nodeColor === 'function' ? props.nodeColor(n) : ''}
            onClick={() => props.onNodeClick && props.onNodeClick(n)}
          >{n.id}</button>
        ))}
      </div>
    );
  },
}));

import RecordsGraphView from '../components/knowledge/RecordsGraphView';
import { useStore } from '../store/useStore';

function reset() {
  lastProps = null;
  useStore.setState({
    knowledgeBrowserGraphData: null,
    knowledgeBrowserSelectedPath: null,
  });
}

describe('RecordsGraphView (AD-562)', () => {
  beforeEach(reset);
  afterEach(() => { cleanup(); vi.restoreAllMocks(); reset(); });

  it('renders empty state when no graph data', () => {
    render(<RecordsGraphView />);
    expect(screen.getByTestId('knowledge-graph-empty')).toBeTruthy();
  });

  it('renders force-graph with nodes from store', () => {
    useStore.setState({
      knowledgeBrowserGraphData: {
        nodes: [{ id: 'a', label: 'A', type: 'notebooks', department: 'science', classification: 'ship', author: 'x', revision_count: 1, is_convergence_hub: false, quality_overlay: null }],
        edges: [],
        generated_at: 0,
        node_count: 1,
        edge_count: 0,
      },
    });
    render(<RecordsGraphView />);
    expect(screen.getByTestId('mock-force-graph')).toBeTruthy();
    expect(screen.getByTestId('mock-node-a')).toBeTruthy();
  });

  it('clicking a node triggers selectKnowledgeBrowserEntry', () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({ ok: true, json: async () => ({}) } as Response);
    useStore.setState({
      knowledgeBrowserGraphData: {
        nodes: [{ id: 'a', label: 'A', type: 'x', department: '', classification: 'ship', author: '', revision_count: 1, is_convergence_hub: false, quality_overlay: null }],
        edges: [], generated_at: 0, node_count: 1, edge_count: 0,
      },
    });
    render(<RecordsGraphView />);
    fireEvent.click(screen.getByTestId('mock-node-a'));
    expect(useStore.getState().knowledgeBrowserSelectedPath).toBe('a');
  });

  it('convergence hub gets gold color, others get dept color', () => {
    useStore.setState({
      knowledgeBrowserGraphData: {
        nodes: [
          { id: 'h', label: 'H', type: 'convergence-reports', department: 'bridge', classification: 'ship', author: '', revision_count: 1, is_convergence_hub: true, quality_overlay: null },
          { id: 'n', label: 'N', type: 'notebooks', department: 'science', classification: 'ship', author: '', revision_count: 1, is_convergence_hub: false, quality_overlay: null },
        ],
        edges: [], generated_at: 0, node_count: 2, edge_count: 0,
      },
    });
    render(<RecordsGraphView />);
    expect(screen.getByTestId('mock-node-h').getAttribute('data-color')).toBe('#e0c070');
    expect(screen.getByTestId('mock-node-n').getAttribute('data-color')).toBe('#50b0a0');
  });

  it('suggested edges get particles, others do not', () => {
    useStore.setState({
      knowledgeBrowserGraphData: {
        nodes: [
          { id: 'a', label: 'A', type: 'x', department: '', classification: 'ship', author: '', revision_count: 1, is_convergence_hub: false, quality_overlay: null },
        ],
        edges: [
          { source: 'a', target: 'a', kind: 'suggested' },
          { source: 'a', target: 'a', kind: 'backlink' },
        ],
        generated_at: 0, node_count: 1, edge_count: 2,
      },
    });
    render(<RecordsGraphView />);
    const fn = lastProps.linkDirectionalParticles;
    expect(fn({ kind: 'suggested' })).toBe(2);
    expect(fn({ kind: 'backlink' })).toBe(0);
  });
});
