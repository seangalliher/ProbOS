/* Agent node rendering — instanced spheres with trust+pool color, confidence glow (Fix 2,3,5) */

import { useRef, useMemo, forwardRef } from 'react';
import { useFrame, ThreeEvent } from '@react-three/fiber';
import * as THREE from 'three';
import { useStore } from '../store/useStore';
import { poolTintBlend, confidenceToIntensity, agentNodeSize } from './scene';

const _tempObj = new THREE.Object3D();
const _tempColor = new THREE.Color();

interface AgentNodesProps {
  onPointerMove?: (e: ThreeEvent<PointerEvent>) => void;
  onPointerOut?: () => void;
  onClick?: (e: ThreeEvent<MouseEvent>) => void;
}

export function AgentNodes({ onPointerMove, onPointerOut, onClick }: AgentNodesProps = {}) {
  const agents = useStore((s) => s.agents);
  const meshRef = useRef<THREE.InstancedMesh>(null);

  const agentList = useMemo(() => Array.from(agents.values()), [agents]);
  const count = agentList.length;

  // Per-instance colors (initial)
  const colors = useMemo(() => {
    const arr = new Float32Array(Math.max(count, 1) * 3);
    agentList.forEach((agent, i) => {
      const color = poolTintBlend(agent.trust, agent.pool);
      arr[i * 3] = color.r;
      arr[i * 3 + 1] = color.g;
      arr[i * 3 + 2] = color.b;
    });
    return arr;
  }, [agentList, count]);

  // Animation: breathing + position + color updates
  useFrame((state) => {
    const mesh = meshRef.current;
    if (!mesh || count === 0) return;

    const t = state.clock.elapsedTime;

    agentList.forEach((agent, i) => {
      // Breathing: +/-3% radius oscillation, offset per agent
      const breathPhase = t * 1.5 + i * 0.7;
      const breathScale = 1 + Math.sin(breathPhase) * 0.03;

      // Tier-based sizing (Fix 5)
      const baseSize = agentNodeSize(agent.tier, agent.confidence);
      const size = baseSize * breathScale;

      _tempObj.position.set(...agent.position);
      _tempObj.scale.setScalar(size);
      _tempObj.updateMatrix();
      mesh.setMatrixAt(i, _tempObj.matrix);

      // Update color: trust+pool blend * confidence intensity (Fix 2,3)
      _tempColor.copy(poolTintBlend(agent.trust, agent.pool));
      const intensity = confidenceToIntensity(agent.confidence);
      _tempColor.multiplyScalar(intensity);
      mesh.setColorAt(i, _tempColor);
    });

    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
  });

  if (count === 0) return null;

  return (
    <instancedMesh
      ref={meshRef}
      args={[undefined, undefined, count]}
      onPointerMove={onPointerMove}
      onPointerOut={onPointerOut}
      onClick={onClick}
    >
      <sphereGeometry args={[1, 24, 24]} />
      <meshBasicMaterial
        toneMapped={false}
        transparent
        opacity={0.95}
      />
      <instancedBufferAttribute
        attach="instanceColor"
        args={[colors, 3]}
      />
    </instancedMesh>
  );
}
