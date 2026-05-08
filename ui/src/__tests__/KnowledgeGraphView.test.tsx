/**
 * AD-520: KnowledgeGraphView tests.
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
      <div data-testid="mock-force-graph-3d" data-nodes={nodes.length} data-links={links.length}>
        {nodes.map((n: any) => (
          <button
            key={n.id}
            data-testid={`mock-node-${n.id}`}
            data-color={typeof props.nodeColor === 'function' ? props.nodeColor(n) : ''}
            data-val={n.val}
            onClick={() => props.onNodeClick && props.onNodeClick(n)}
          >{n.id}</button>
        ))}
      </div>
    );
  },
}));

import KnowledgeGraphView from '../components/spatial/KnowledgeGraphView';
import { useStore } from '../store/useStore';

function reset() {
  lastProps = null;
  useStore.setState({
    spatialGraphData: null,
    spatialSelectedNode: null,
  });
}

function makeData() {
  return {
    nodes: [
      { id: 'science', label: 'Science', type: 'department' },
      { id: 'medical', label: 'Medical', type: 'department' },
      { id: 'a1', label: 'A1', type: 'agent', department: 'science', trust: 0.8, post: 'scout' },
      { id: 'a2', label: 'A2', type: 'agent', department: 'science', trust: 0.5, post: 'scout' },
      { id: 'b1', label: 'B1', type: 'agent', department: 'medical', trust: 0.6, post: 'medic' },
    ],
    edges: [
      { id: 'm1', source: 'a1', target: 'science', relation: 'member_of', weight: 1 },
      { id: 'm2', source: 'a2', target: 'science', relation: 'member_of', weight: 1 },
      { id: 'r1', source: 'a1', target: 'a2', relation: 'reports_to', weight: 0.7 },
      { id: 'k1', source: 'a1', target: 'b1', relation: 'competent_in', weight: 0.5 },
    ],
    generated_at: 0,
  };
}

describe('KnowledgeGraphView (AD-520)', () => {
  beforeEach(reset);
  afterEach(() => { cleanup(); reset(); });

  it('renders ForceGraph3D with nodes from store', () => {
    useStore.setState({ spatialGraphData: makeData() });
    render(<KnowledgeGraphView />);
    expect(screen.getByTestId('mock-force-graph-3d').getAttribute('data-nodes')).toBe('5');
  });

  it('ORG CHART mode filters edges to reports_to + member_of', () => {
    useStore.setState({ spatialGraphData: makeData() });
    render(<KnowledgeGraphView />);
    // Default mode is 'org'
    expect(screen.getByTestId('mock-force-graph-3d').getAttribute('data-links')).toBe('3');
  });

  it('TRUST NETWORK mode synthesizes trust edges between agents in same department', () => {
    useStore.setState({ spatialGraphData: makeData() });
    render(<KnowledgeGraphView />);
    fireEvent.click(screen.getByTestId('graph-mode-trust'));
    // a1+a2 share science → 1 trust edge; b1 alone in medical → 0
    expect(screen.getByTestId('mock-force-graph-3d').getAttribute('data-links')).toBe('1');
  });

  it('KNOWLEDGE MAP mode shows all relation types', () => {
    useStore.setState({ spatialGraphData: makeData() });
    render(<KnowledgeGraphView />);
    fireEvent.click(screen.getByTestId('graph-mode-knowledge'));
    // All 4 edges present
    expect(screen.getByTestId('mock-force-graph-3d').getAttribute('data-links')).toBe('4');
  });

  it('DEPARTMENT VIEW renders without filtering edges', () => {
    useStore.setState({ spatialGraphData: makeData() });
    render(<KnowledgeGraphView />);
    fireEvent.click(screen.getByTestId('graph-mode-department'));
    expect(screen.getByTestId('mock-force-graph-3d').getAttribute('data-links')).toBe('4');
    // dagMode disabled (only 'org' uses td)
    expect(lastProps.dagMode).toBeUndefined();
  });

  it('department filter chip toggles agent visibility', () => {
    useStore.setState({ spatialGraphData: makeData() });
    render(<KnowledgeGraphView />);
    fireEvent.click(screen.getByTestId('dept-filter-medical'));
    // Only medical department + b1 agent visible
    const nodeCount = parseInt(screen.getByTestId('mock-force-graph-3d').getAttribute('data-nodes') || '0', 10);
    expect(nodeCount).toBe(2);
  });

  it('node click dispatches setSpatialSelectedNode', () => {
    useStore.setState({ spatialGraphData: makeData() });
    render(<KnowledgeGraphView />);
    fireEvent.click(screen.getByTestId('mock-node-a1'));
    const sel = useStore.getState().spatialSelectedNode;
    expect(sel?.kind).toBe('agent');
    expect(sel?.id).toBe('a1');
  });

  it('node color matches department palette', () => {
    useStore.setState({ spatialGraphData: makeData() });
    render(<KnowledgeGraphView />);
    const a1 = screen.getByTestId('mock-node-a1');
    expect(a1.getAttribute('data-color')).toBe('#5ca0d4'); // science
  });

  it('node size scales with trust value (clamped to [3,12])', () => {
    useStore.setState({
      spatialGraphData: {
        nodes: [
          { id: 'low', label: 'L', type: 'agent', department: 'science', trust: 0.1 },
          { id: 'mid', label: 'M', type: 'agent', department: 'science', trust: 0.5 },
          { id: 'hi', label: 'H', type: 'agent', department: 'science', trust: 1.5 },
        ],
        edges: [],
        generated_at: 0,
      },
    });
    render(<KnowledgeGraphView />);
    expect(screen.getByTestId('mock-node-low').getAttribute('data-val')).toBe('3');
    expect(screen.getByTestId('mock-node-mid').getAttribute('data-val')).toBe('5');
    expect(screen.getByTestId('mock-node-hi').getAttribute('data-val')).toBe('12');
  });

  it('empty graphData shows "No graph data" status text', () => {
    useStore.setState({ spatialGraphData: null });
    render(<KnowledgeGraphView />);
    expect(screen.getByTestId('knowledge-graph-empty')).toBeTruthy();
  });

  it('TRUST mode caps synthesized edges at 200 and prefers high-trust pairs (BF #426)', () => {
    // 30 science agents → C(30,2) = 435 pairs (above the 200 cap).
    const agents: any[] = [];
    for (let i = 0; i < 30; i++) {
      // First 15 agents have HIGH trust (0.9), last 15 have LOW trust (0.2).
      const trust = i < 15 ? 0.9 : 0.2;
      agents.push({ id: `a${i}`, label: `A${i}`, type: 'agent', department: 'science', trust });
    }
    useStore.setState({
      spatialGraphData: {
        nodes: [{ id: 'science', label: 'Science', type: 'department' }, ...agents],
        edges: [],
        generated_at: 0,
      },
    });
    render(<KnowledgeGraphView />);
    fireEvent.click(screen.getByTestId('graph-mode-trust'));
    const linkCount = parseInt(
      screen.getByTestId('mock-force-graph-3d').getAttribute('data-links') || '0',
      10,
    );
    expect(linkCount).toBeLessThanOrEqual(200);
    // C(15,2) = 105 high-trust pairs; cap allows all of them. Filter prefers
    // weight >= 0.6, so every kept link must be ≥ 0.6.
    expect(lastProps.graphData.links.length).toBeGreaterThan(0);
    for (const lk of lastProps.graphData.links) {
      expect(typeof lk.weight).toBe('number');
      expect(lk.weight).toBeGreaterThanOrEqual(0.6);
    }
  });
});
