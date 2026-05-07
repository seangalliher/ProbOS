/**
 * AD-562: RecordsGraphView — 3D force-directed knowledge graph.
 *
 * Reuses react-force-graph-3d (in-tree). Nodes = records, edges = backlinks +
 * convergence membership + (optional) Jaccard suggestions.
 */
import { useMemo } from 'react';
import ForceGraph3D from 'react-force-graph-3d';
import { useStore } from '../../store/useStore';
import { deptColor } from './colors';
import type { KnowledgeGraphNode, KnowledgeGraphEdge } from './types';

function linkColor(l: KnowledgeGraphEdge): string {
  if (l.kind === 'suggested') return 'rgba(136,132,168,0.4)';
  if (l.kind === 'convergence') return '#7060a8';
  return '#f0b060';
}

export default function RecordsGraphView() {
  const data = useStore(s => s.knowledgeBrowserGraphData);
  const selectEntry = useStore(s => s.selectKnowledgeBrowserEntry);

  const graphData = useMemo(() => {
    if (!data) return { nodes: [], links: [] };
    return {
      nodes: data.nodes.map(n => ({ ...n })),
      links: data.edges.map(e => ({ ...e })),
    };
  }, [data]);

  if (!data || data.nodes.length === 0) {
    return (
      <div data-testid="knowledge-graph-empty" style={{
        padding: 24, color: '#8888a0', fontSize: 12, textAlign: 'center',
      }}>
        No graph data — adjust filters or check Knowledge Browser config
      </div>
    );
  }

  return (
    <div data-testid="knowledge-graph-view" style={{ width: '100%', height: '100%' }}>
      <ForceGraph3D
        graphData={graphData}
        nodeColor={(n: KnowledgeGraphNode) => n.is_convergence_hub ? '#e0c070' : deptColor(n.department)}
        nodeVal={(n: KnowledgeGraphNode) => 1 + Math.log((n.revision_count || 1) + 1)}
        nodeLabel={(n: KnowledgeGraphNode) => n.label || n.id}
        linkColor={linkColor as any}
        linkDirectionalParticles={(l: KnowledgeGraphEdge) => l.kind === 'suggested' ? 2 : 0}
        linkDirectionalParticleSpeed={0.005}
        backgroundColor="rgba(0,0,0,0)"
        onNodeClick={(node: any) => { void selectEntry(node.id); }}
      />
    </div>
  );
}
