/* Animation system — heartbeat, consensus, self-mod, routing, particles (Fix 4,6,7) */
/* All animation components use useFrame + getState() — NEVER reactive useStore subscriptions.
   Reactive subscriptions inside the R3F Canvas cause re-renders that break raycasting/tooltips. */

import { useRef, useMemo } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { useStore } from '../store/useStore';

// Background particle field — depth and atmosphere (Fix 4, 7)
export function BackgroundParticles() {
  const count = 200;
  const positions = useMemo(() => {
    const arr = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      arr[i * 3] = (Math.random() - 0.5) * 40;
      arr[i * 3 + 1] = (Math.random() - 0.5) * 30;
      arr[i * 3 + 2] = (Math.random() - 0.5) * 40;
    }
    return arr;
  }, []);

  const ref = useRef<THREE.Points>(null);

  // Slow upward drift — freeze when disconnected (Fix 7)
  useFrame(() => {
    if (!ref.current) return;
    const connected = useStore.getState().connected;
    if (!connected) return; // particles freeze
    const pos = ref.current.geometry.attributes.position as THREE.BufferAttribute;
    for (let i = 0; i < count; i++) {
      let y = pos.getY(i);
      y += 0.003;
      if (y > 15) y = -15;
      pos.setY(i, y);
    }
    pos.needsUpdate = true;
  });

  return (
    <points ref={ref}>
      <bufferGeometry>
        <bufferAttribute
          attach="attributes-position"
          args={[positions, 3]}
        />
      </bufferGeometry>
      <pointsMaterial
        size={0.04}
        color="#404060"
        transparent
        opacity={0.35}
        sizeAttenuation
      />
    </points>
  );
}

// Heartbeat pulse — compact nucleus at center [0, 0, 0]
export function HeartbeatPulse() {
  const outerRef = useRef<THREE.Mesh>(null);
  const innerRef = useRef<THREE.Mesh>(null);

  useFrame((state) => {
    if (!outerRef.current || !innerRef.current) return;
    const connected = useStore.getState().connected;
    if (!connected) {
      outerRef.current.visible = false;
      innerRef.current.visible = false;
      return;
    }
    const t = state.clock.elapsedTime;
    // Sharp attack, slow decay (like a real heartbeat)
    const raw = Math.sin(t * (Math.PI / 0.6));
    const pulse = Math.pow(Math.max(raw, 0), 3);

    const outerMat = outerRef.current.material as THREE.MeshBasicMaterial;
    outerMat.opacity = pulse * 0.25;
    outerRef.current.scale.setScalar(0.8 + pulse * 0.2);

    const innerMat = innerRef.current.material as THREE.MeshBasicMaterial;
    innerMat.opacity = pulse * 0.35;
    innerRef.current.scale.setScalar(0.45 + pulse * 0.15);

    // Fixed center position
    outerRef.current.position.set(0, 0, 0);
    innerRef.current.position.set(0, 0, 0);
    outerRef.current.visible = true;
    innerRef.current.visible = true;
  });

  return (
    <>
      <mesh ref={outerRef}>
        <sphereGeometry args={[0.8, 16, 16]} />
        <meshBasicMaterial color="#c8a070" transparent opacity={0} side={THREE.BackSide} toneMapped={false} />
      </mesh>
      <mesh ref={innerRef}>
        <sphereGeometry args={[0.5, 16, 16]} />
        <meshBasicMaterial color="#e0b880" transparent opacity={0} toneMapped={false} />
      </mesh>
    </>
  );
}

// Consensus golden flash — non-reactive (reads store in useFrame)
export function ConsensusFlash() {
  const meshRef = useRef<THREE.Mesh>(null);
  const progressRef = useRef(0);
  const activeRef = useRef(false);
  const lastFlashRef = useRef<object | null>(null);

  useFrame((_, delta) => {
    const store = useStore.getState();
    const mesh = meshRef.current;
    if (!mesh) return;

    // Detect new flash trigger (identity comparison — each event is a new object)
    if (store.pendingConsensusFlash && store.pendingConsensusFlash !== lastFlashRef.current) {
      lastFlashRef.current = store.pendingConsensusFlash;
      activeRef.current = true;
      progressRef.current = 0;
    }

    if (!activeRef.current) {
      mesh.visible = false;
      return;
    }

    progressRef.current += delta * 2;
    const p = progressRef.current;

    if (p > 1) {
      activeRef.current = false;
      mesh.visible = false;
      lastFlashRef.current = null;
      store.clearAnimationEvent('pendingConsensusFlash');
      return;
    }

    mesh.visible = true;
    const mat = mesh.material as THREE.MeshBasicMaterial;
    mat.opacity = (1 - p) * 0.6;
    mesh.scale.setScalar(1 + p * 4);
  });

  return (
    <mesh ref={meshRef} visible={false}>
      <sphereGeometry args={[0.5, 16, 16]} />
      <meshBasicMaterial color="#e8c870" transparent opacity={0} toneMapped={false} />
    </mesh>
  );
}

// Self-mod bloom — bright cyan-white ring flare when new agent spawns (non-reactive)
export function SelfModBloom() {
  const meshRef = useRef<THREE.Mesh>(null);
  const progressRef = useRef(0);
  const activeRef = useRef(false);
  const currentBloomRef = useRef<string | null>(null);

  useFrame((_, delta) => {
    const store = useStore.getState();
    const mesh = meshRef.current;
    if (!mesh) return;

    // Check for new bloom trigger (non-reactive)
    if (store.pendingSelfModBloom && store.pendingSelfModBloom !== currentBloomRef.current) {
      currentBloomRef.current = store.pendingSelfModBloom;
      activeRef.current = true;
      progressRef.current = 0;
      // Position at new agent
      const bloomId = store.pendingSelfModBloom;
      const target = [...store.agents.values()].find(
        a => a.id === bloomId || a.agentType === bloomId
      );
      if (target) {
        mesh.position.set(target.position[0], target.position[1], target.position[2]);
      }
    }

    if (!activeRef.current) {
      mesh.visible = false;
      return;
    }

    // 800ms total duration (delta * 1.25 → 0..1 in 0.8s)
    progressRef.current += delta * 1.25;
    const p = progressRef.current;

    if (p > 1.0) {
      activeRef.current = false;
      mesh.visible = false;
      currentBloomRef.current = null;
      store.clearAnimationEvent('pendingSelfModBloom');
      return;
    }

    mesh.visible = true;
    const mat = mesh.material as THREE.MeshBasicMaterial;
    // Fast attack, smooth decay — 2x brighter than heartbeat
    const flare = p < 0.15 ? p / 0.15 : Math.max(0, 1 - (p - 0.15) / 0.85);
    mat.opacity = flare * 1.0;
    // Expanding ring effect
    mesh.scale.setScalar(0.2 + flare * 3.0);
  });

  return (
    <mesh ref={meshRef} visible={false}>
      <ringGeometry args={[0.8, 1.0, 32]} />
      <meshBasicMaterial color="#80f0ff" transparent opacity={0} toneMapped={false} side={THREE.DoubleSide} />
    </mesh>
  );
}

// Intent routing pulse — non-reactive
export function RoutingPulse() {
  const meshRef = useRef<THREE.Mesh>(null);
  const progressRef = useRef(0);
  const activeRef = useRef(false);
  const lastPulseRef = useRef<object | null>(null);

  useFrame((_, delta) => {
    const store = useStore.getState();
    const mesh = meshRef.current;
    if (!mesh) return;

    // Detect new pulse trigger (identity comparison)
    if (store.pendingRoutingPulse && store.pendingRoutingPulse !== lastPulseRef.current) {
      lastPulseRef.current = store.pendingRoutingPulse;
      activeRef.current = true;
      progressRef.current = 0;
      // Position at target agent
      const target = [...store.agents.values()].find(a => a.id === store.pendingRoutingPulse!.target);
      if (target && mesh) {
        mesh.position.set(target.position[0], target.position[1], target.position[2]);
      }
    }

    if (!activeRef.current) {
      mesh.visible = false;
      return;
    }

    progressRef.current += delta * 3;
    const p = progressRef.current;

    if (p > 1) {
      activeRef.current = false;
      mesh.visible = false;
      lastPulseRef.current = null;
      store.clearAnimationEvent('pendingRoutingPulse');
      return;
    }

    mesh.visible = true;
    const mat = mesh.material as THREE.MeshBasicMaterial;
    mat.opacity = (1 - p) * 0.6;
    mesh.scale.setScalar(0.1 + p * 0.3);
  });

  return (
    <mesh ref={meshRef} visible={false}>
      <sphereGeometry args={[1, 8, 8]} />
      <meshBasicMaterial color="#f0e8e0" transparent opacity={0} toneMapped={false} />
    </mesh>
  );
}

// Feedback pulse — golden (approve) or cool-blue (reject) radial pulse from center (non-reactive)
export function FeedbackPulse() {
  const meshRef = useRef<THREE.Mesh>(null);
  const progressRef = useRef(0);
  const activeRef = useRef(false);
  const currentFeedbackRef = useRef<string | null>(null);
  const colorRef = useRef('#f0b060');

  useFrame((_, delta) => {
    const store = useStore.getState();
    const mesh = meshRef.current;
    if (!mesh) return;

    // Detect new feedback trigger
    if (store.pendingFeedbackPulse && store.pendingFeedbackPulse !== currentFeedbackRef.current) {
      currentFeedbackRef.current = store.pendingFeedbackPulse;
      activeRef.current = true;
      progressRef.current = 0;
      colorRef.current = store.pendingFeedbackPulse === 'good' ? '#f0b060' : '#4488cc';
    }

    if (!activeRef.current) {
      mesh.visible = false;
      return;
    }

    progressRef.current += delta * 2; // 500ms duration
    const p = progressRef.current;

    if (p > 1) {
      activeRef.current = false;
      mesh.visible = false;
      currentFeedbackRef.current = null;
      store.clearAnimationEvent('pendingFeedbackPulse');
      return;
    }

    mesh.visible = true;
    const mat = mesh.material as THREE.MeshBasicMaterial;
    mat.color.set(colorRef.current);
    mat.opacity = (1 - p) * 0.1; // subtle — opacity 0.1 max
    mesh.scale.setScalar(0.5 + p * 6);
  });

  return (
    <mesh ref={meshRef} visible={false}>
      <sphereGeometry args={[1, 16, 16]} />
      <meshBasicMaterial color="#f0b060" transparent opacity={0} toneMapped={false} />
    </mesh>
  );
}
