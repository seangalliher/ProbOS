/**
 * AD-520: Spatial Knowledge Explorer — Phase 2 Spatial Ship Layout view.
 *
 * R3F Canvas rendering one wireframe box per deck with agents positioned at
 * deck.position + post_offsets[post]. Click on an agent dispatches
 * setSpatialSelectedNode. Alert-condition prop tints all decks.
 */
import { useMemo, useRef } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { OrbitControls, Text } from '@react-three/drei';
import * as THREE from 'three';
import { useStore } from '../../store/useStore';
import type { SpatialLayoutData } from './types';
import { departmentColor } from './types';

export type AlertLevel = 'CRITICAL' | 'ALERT' | null;

interface ShipLayoutViewProps {
  alertLevel?: AlertLevel;
}

interface AgentPlacement {
  agent_id: string;
  agent_type: string;
  callsign?: string;
  department: string | null;
  post: string;
  deck_id: string;
  position: [number, number, number];
  on_watch: boolean;
  active: boolean;
  payload: Record<string, unknown>;
}

function alertTint(level: AlertLevel): string | null {
  if (level === 'CRITICAL') return '#c84858';
  if (level === 'ALERT') return '#f0b060';
  return null;
}

function computePlacements(
  layout: SpatialLayoutData,
  manifestNodes: Array<Record<string, unknown>>,
  agentsMap: Map<string, any>,
): AgentPlacement[] {
  const common = layout.decks.find(d => d.deck_id === 'common_areas') || layout.decks[layout.decks.length - 1];
  const out: AgentPlacement[] = [];
  for (const n of manifestNodes) {
    if (n.type !== 'agent') continue;
    const dept = typeof n.department === 'string' ? n.department : null;
    const post = typeof n.post === 'string' ? n.post : '';
    const known = layout.decks.find(d => d.department_id === dept);
    const deck = known || common;
    if (!deck) continue;
    const offset = deck.post_offsets?.[post] || [0, 0, 0];
    const id = String(n.id ?? '');
    const liveAgent = agentsMap.get(id);
    out.push({
      agent_id: id,
      agent_type: String((n.label ?? id) as string),
      department: dept,
      post,
      deck_id: deck.deck_id,
      position: [
        deck.position[0] + offset[0],
        deck.position[1] + offset[1],
        deck.position[2] + offset[2],
      ],
      on_watch: known ? Boolean(n.on_watch) : false,
      active: !!(liveAgent && (liveAgent.activity_state === 'active' || liveAgent.state === 'active')),
      payload: n,
    });
  }
  return out;
}

function PulsingSphere({ position, color, active, onClick }: {
  position: [number, number, number];
  color: string;
  active: boolean;
  onClick: () => void;
}) {
  const ref = useRef<THREE.Mesh>(null);
  useFrame((state) => {
    if (!ref.current) return;
    const t = state.clock.elapsedTime;
    const scale = active ? 1 + 0.2 * Math.sin(t * 2) : 1;
    ref.current.scale.set(scale, scale, scale);
  });
  return (
    <mesh ref={ref} position={position} onClick={onClick}>
      <sphereGeometry args={[0.4, 16, 12]} />
      <meshStandardMaterial color={color} emissive={color} emissiveIntensity={active ? 0.4 : 0.1} />
    </mesh>
  );
}

function DeckGroup({ deck, tintColor }: { deck: SpatialLayoutData['decks'][number]; tintColor: string | null }) {
  const color = tintColor || deck.accent_color;
  const edgesGeo = useMemo(
    () => new THREE.EdgesGeometry(new THREE.BoxGeometry(...deck.dimensions)),
    [deck.dimensions],
  );
  return (
    <group position={deck.position} data-deck-id={deck.deck_id}>
      <lineSegments geometry={edgesGeo}>
        <lineBasicMaterial color={color} transparent opacity={0.6} />
      </lineSegments>
      <Text
        position={[0, deck.dimensions[1] / 2 + 0.4, 0]}
        fontSize={0.5}
        color={color}
        anchorX="center"
        anchorY="middle"
      >
        {deck.name}
      </Text>
    </group>
  );
}

export default function ShipLayoutView({ alertLevel = null }: ShipLayoutViewProps) {
  const layout = useStore(s => s.spatialLayoutData);
  const graph = useStore(s => s.spatialGraphData);
  const agentsMap = useStore(s => s.agents);
  const setSelected = useStore(s => s.setSpatialSelectedNode);

  const placements = useMemo<AgentPlacement[]>(() => {
    if (!layout || !graph) return [];
    return computePlacements(layout, graph.nodes, agentsMap as Map<string, any>);
  }, [layout, graph, agentsMap]);

  if (!layout || layout.decks.length === 0) {
    return (
      <div data-testid="ship-layout-empty" style={{
        padding: 24, color: '#8888a0', fontFamily: "'JetBrains Mono', monospace",
        fontSize: 12, textAlign: 'center',
      }}>
        No spatial layout — enable in config
      </div>
    );
  }

  const tint = alertTint(alertLevel);

  return (
    <div data-testid="ship-layout-view" style={{ width: '100%', height: '100%', position: 'relative' }}>
      <Canvas camera={{ position: [16, 12, 16], fov: 50 }} style={{ background: '#0a0a12' }}>
        <ambientLight intensity={0.4} />
        <pointLight position={[10, 10, 10]} intensity={0.8} />
        <OrbitControls />
        {layout.decks.map(deck => (
          <DeckGroup key={deck.deck_id} deck={deck} tintColor={tint} />
        ))}
        {placements.map(p => (
          <PulsingSphere
            key={p.agent_id}
            position={p.position}
            color={tint || departmentColor(p.department)}
            active={p.active}
            onClick={() => setSelected({ kind: 'agent', id: p.agent_id, payload: p.payload })}
          />
        ))}
      </Canvas>
    </div>
  );
}

export { computePlacements, alertTint };
