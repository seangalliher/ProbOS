/* AD-708c-2: MobileMesh — standalone 2D SVG mesh for the PADD mobile shell
   (#484 / AD-708). Consumes the AD-708c-1 pure projection (selectMeshAgents ->
   computeMeshLayout -> computeMeshEdges) and renders curated nodes (<circle>)
   over connection edges (<line>) as plain SVG. THE LOAD-BEARING CONSTRAINT:
   imports ONLY mesh2d/meshProjection + the store — NEVER canvas/scene, canvas/*,
   or three (a phone must never load three.js). Static (animation is AD-708c-4).
   Wired NOWHERE in this AD (rendered only by its test) -> byte-identical app.
   NO emoji (HXI #3). A `viewport` prop (default 360x360) keeps it dumb + testable;
   the AD-708c-3 shell wiring passes the real measured size. */
import { useMemo } from 'react';
import { useStore } from '../../store/useStore';
import {
  selectMeshAgents,
  computeMeshLayout,
  computeMeshEdges,
  type MeshViewport,
} from '../../mesh2d/meshProjection';

const BG = '#0a0a14';
const EDGE_STROKE = '#3a4660';
const DEFAULT_VIEWPORT: MeshViewport = { width: 360, height: 360 };

interface MobileMeshProps {
  viewport?: MeshViewport;
}

export default function MobileMesh({ viewport = DEFAULT_VIEWPORT }: MobileMeshProps) {
  const agents = useStore((s) => s.agents);
  const connections = useStore((s) => s.connections);

  const nodes = useMemo(
    () => computeMeshLayout(selectMeshAgents([...agents.values()]), viewport),
    [agents, viewport],
  );
  const edges = useMemo(() => computeMeshEdges(nodes, connections), [nodes, connections]);

  return (
    <svg
      data-testid="mobile-mesh"
      width={viewport.width}
      height={viewport.height}
      viewBox={`0 0 ${viewport.width} ${viewport.height}`}
      style={{ background: BG, display: 'block' }}
    >
      {edges.map((e, i) => (
        <line
          key={`edge-${i}`}
          x1={e.x1}
          y1={e.y1}
          x2={e.x2}
          y2={e.y2}
          stroke={EDGE_STROKE}
          strokeWidth={1}
          opacity={e.opacity}
        />
      ))}
      {nodes.map((n) => (
        <circle
          key={n.id}
          data-testid="mobile-mesh-node"
          cx={n.x}
          cy={n.y}
          r={n.radius}
          fill={n.color}
          opacity={n.opacity}
        />
      ))}
    </svg>
  );
}
