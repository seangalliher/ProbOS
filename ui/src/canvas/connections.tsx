/* Hebbian connection curves — glowing tubes with intent-hub positioning (Fix 1) */

import { useMemo } from 'react';
import * as THREE from 'three';
import { useStore } from '../store/useStore';

function ConnectionTube({ start, end, weight, connected }: {
  start: [number, number, number];
  end: [number, number, number];
  weight: number;
  connected: boolean;
}) {
  const { geometry, material } = useMemo(() => {
    const s = new THREE.Vector3(...start);
    const e = new THREE.Vector3(...end);
    const mid = new THREE.Vector3(
      (start[0] + end[0]) / 2,
      (start[1] + end[1]) / 2 + 0.6 + weight * 0.4,
      (start[2] + end[2]) / 2,
    );
    const curve = new THREE.QuadraticBezierCurve3(s, mid, e);
    const radius = 0.015 + weight * 0.025;
    const geo = new THREE.TubeGeometry(curve, 16, radius, 6, false);
    const opacity = connected ? Math.min(0.4 + weight * 0.5, 0.9) : 0.05;
    const mat = new THREE.MeshBasicMaterial({
      color: '#00d4ff',
      transparent: true,
      opacity,
      toneMapped: false,
    });
    return { geometry: geo, material: mat };
  }, [start, end, weight, connected]);

  return <primitive object={new THREE.Mesh(geometry, material)} />;
}

// Compute pool center position from agent positions
function poolCenter(
  agents: Map<string, { pool: string; position: [number, number, number] }>,
  poolName: string,
): [number, number, number] {
  let cx = 0, cy = 0, cz = 0, count = 0;
  agents.forEach((a) => {
    if (a.pool === poolName) {
      cx += a.position[0]; cy += a.position[1]; cz += a.position[2];
      count++;
    }
  });
  if (count === 0) return [0, 0, 0];
  return [cx / count, cy / count, cz / count];
}

export function Connections() {
  const connections = useStore((s) => s.connections);
  const agents = useStore((s) => s.agents);
  const connected = useStore((s) => s.connected);

  const validConnections = useMemo(() => {
    return connections
      .filter((c) => c.weight > 0.01)
      .map((c) => {
        const srcAgent = agents.get(c.source);
        const tgtAgent = agents.get(c.target);

        let startPos: [number, number, number] | null = null;
        let endPos: [number, number, number] | null = null;

        if (srcAgent) {
          startPos = srcAgent.position;
        } else if (tgtAgent) {
          // Source is an intent name (not an agent ID) — position at pool center
          startPos = poolCenter(agents, tgtAgent.pool);
        }

        if (tgtAgent) {
          endPos = tgtAgent.position;
        } else if (srcAgent) {
          endPos = poolCenter(agents, srcAgent.pool);
        }

        if (!startPos || !endPos) return null;

        // Skip zero-length connections
        const dx = startPos[0] - endPos[0];
        const dy = startPos[1] - endPos[1];
        const dz = startPos[2] - endPos[2];
        if (dx * dx + dy * dy + dz * dz < 0.01) return null;

        return { ...c, startPos, endPos };
      })
      .filter(Boolean) as Array<{
        source: string; target: string; relType: string; weight: number;
        startPos: [number, number, number]; endPos: [number, number, number];
      }>;
  }, [connections, agents]);

  return (
    <group>
      {validConnections.map((c, i) => (
        <ConnectionTube
          key={`${c.source}-${c.target}-${i}`}
          start={c.startPos}
          end={c.endPos}
          weight={c.weight}
          connected={connected}
        />
      ))}
    </group>
  );
}
