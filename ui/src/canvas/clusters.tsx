/* Team cluster boundary shells — translucent wireframe spheres per crew team (AD-294) */

import { useStore } from '../store/useStore';
import { Text, Billboard } from '@react-three/drei';
import * as THREE from 'three';

export function TeamClusters() {
  const groupCenters = useStore((s) => s.groupCenters);
  const connected = useStore((s) => s.connected);

  if (!connected || groupCenters.size === 0) return null;

  return (
    <group>
      {Array.from(groupCenters.entries()).map(([name, { center, radius, displayName, tintHex }]) => (
        <group key={name} position={center}>
          {/* Boundary shell — translucent wireframe sphere */}
          <mesh>
            <sphereGeometry args={[radius * 1.15, 16, 12]} />
            <meshBasicMaterial
              color={tintHex}
              transparent
              opacity={0.04}
              wireframe
              toneMapped={false}
              depthWrite={false}
            />
          </mesh>
          {/* Faint solid inner glow */}
          <mesh>
            <sphereGeometry args={[radius * 1.1, 16, 12]} />
            <meshBasicMaterial
              color={tintHex}
              transparent
              opacity={0.015}
              side={THREE.BackSide}
              toneMapped={false}
              depthWrite={false}
            />
          </mesh>
          {/* Team name label — floats above the cluster, always faces camera */}
          <Billboard position={[0, radius * 1.3, 0]} follow>
            <Text
              fontSize={0.25}
              color={tintHex}
              anchorX="center"
              anchorY="bottom"
              fillOpacity={0.5}
            >
              {displayName}
            </Text>
          </Billboard>
        </group>
      ))}
    </group>
  );
}
