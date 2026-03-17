/* Cognitive Canvas — Three.js WebGL canvas wrapper (Fix 4,7,10) */

import { useCallback, useRef } from 'react';
import { Canvas, ThreeEvent } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import * as THREE from 'three';
import { AgentNodes } from '../canvas/agents';
import { Connections } from '../canvas/connections';
import { TeamClusters } from '../canvas/clusters';
import { Effects } from '../canvas/effects';
import {
  HeartbeatPulse, ConsensusFlash, SelfModBloom, RoutingPulse, BackgroundParticles, FeedbackPulse,
} from '../canvas/animations';
import { useStore } from '../store/useStore';
import { modeGrading } from '../canvas/scene';
import type { Agent } from '../store/types';

// Raycaster helper — resolve instanceId to agent (Fix 10)
function AgentRaycastLayer() {
  const agents = useStore((s) => s.agents);
  const setHoveredAgent = useStore((s) => s.setHoveredAgent);
  const setPinnedAgent = useStore((s) => s.setPinnedAgent);
  const agentListRef = useRef<Agent[]>([]);

  // Keep a reference-stable ordered agent list
  agentListRef.current = Array.from(agents.values());

  const handlePointerMove = useCallback((e: ThreeEvent<PointerEvent>) => {
    if (e.instanceId !== undefined && e.instanceId < agentListRef.current.length) {
      const agent = agentListRef.current[e.instanceId];
      setHoveredAgent(agent, { x: e.nativeEvent.clientX, y: e.nativeEvent.clientY });
    }
    e.stopPropagation();
  }, [setHoveredAgent]);

  const handlePointerOut = useCallback(() => {
    setHoveredAgent(null);
  }, [setHoveredAgent]);

  const handleClick = useCallback((e: ThreeEvent<MouseEvent>) => {
    if (e.instanceId !== undefined && e.instanceId < agentListRef.current.length) {
      setPinnedAgent(agentListRef.current[e.instanceId]);
    } else {
      setPinnedAgent(null);
    }
    e.stopPropagation();
  }, [setPinnedAgent]);

  return (
    <AgentNodes
      onPointerMove={handlePointerMove}
      onPointerOut={handlePointerOut}
      onClick={handleClick}
    />
  );
}

export function CognitiveCanvas() {
  const systemMode = useStore((s) => s.systemMode);
  const connected = useStore((s) => s.connected);
  const grading = modeGrading(systemMode);

  return (
    <div style={{ position: 'absolute', inset: 0, zIndex: 0 }}>
      {/* Disconnected overlay */}
      {!connected && (
        <div style={{
          position: 'absolute',
          top: '50%', left: '50%',
          transform: 'translate(-50%, -50%)',
          color: 'rgba(200, 56, 72, 0.6)',
          fontSize: 16,
          fontFamily: "'Inter', sans-serif",
          textAlign: 'center',
          zIndex: 15,
          pointerEvents: 'none',
          animation: 'pulse-reconnect 2s ease-in-out infinite',
        }}>
          Connection lost &mdash; reconnecting...
        </div>
      )}
      <style>{`
        @keyframes pulse-reconnect {
          0%, 100% { opacity: 0.4; }
          50% { opacity: 0.8; }
        }
      `}</style>
      <Canvas
        camera={{ position: [0, 5, 16], fov: 50, near: 0.1, far: 100 }}
        gl={{ antialias: true, alpha: false, powerPreference: 'high-performance', depth: true, stencil: false }}
        dpr={[1, 2]}
        style={{ background: '#0a0a12' }}
        onCreated={({ gl }) => {
          gl.setClearColor(grading.tint);
          gl.toneMapping = THREE.ACESFilmicToneMapping;
          gl.toneMappingExposure = 1.0;
        }}
      >
        <ambientLight intensity={0.08} color="#8888a0" />
        <pointLight position={[0, 10, 0]} intensity={0.2} color="#e0dcd4" />

        {/* Fog for depth perception (Fix 4) */}
        <fog attach="fog" args={['#0a0a12', 15, 40]} />

        {/* Background particles (Fix 4, 7) */}
        <BackgroundParticles />

        {/* Agent nodes with raycasting (Fix 10) */}
        <AgentRaycastLayer />
        <TeamClusters />
        <Connections />

        {/* Animations */}
        <HeartbeatPulse />
        <ConsensusFlash />
        <SelfModBloom />
        <RoutingPulse />
        <FeedbackPulse />

        {/* Post-processing */}
        <Effects />

        {/* Camera controls — micro-drift auto-rotate (Fix 7) */}
        <OrbitControls
          enablePan
          enableZoom
          enableRotate
          autoRotate={connected}
          autoRotateSpeed={0.15}
          maxPolarAngle={Math.PI * 0.85}
          minDistance={3}
          maxDistance={30}
          target={[0, 0, 0]}
        />
      </Canvas>
    </div>
  );
}
