/* Animation system — heartbeat, consensus, self-mod, routing, particles (Fix 4,6,7) */

import { useRef, useEffect, useMemo } from 'react';
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

  // Slow upward drift (Fix 7)
  useFrame(() => {
    if (!ref.current) return;
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

// Consensus golden flash
export function ConsensusFlash() {
  const flash = useStore((s) => s.pendingConsensusFlash);
  const clearEvent = useStore((s) => s.clearAnimationEvent);
  const meshRef = useRef<THREE.Mesh>(null);
  const progressRef = useRef(0);
  const activeRef = useRef(false);

  useEffect(() => {
    if (flash) {
      activeRef.current = true;
      progressRef.current = 0;
    }
  }, [flash]);

  useFrame((_, delta) => {
    if (!meshRef.current || !activeRef.current) {
      if (meshRef.current) meshRef.current.visible = false;
      return;
    }

    progressRef.current += delta * 2;
    const p = progressRef.current;

    if (p > 1) {
      activeRef.current = false;
      meshRef.current.visible = false;
      clearEvent('pendingConsensusFlash');
      return;
    }

    meshRef.current.visible = true;
    const mat = meshRef.current.material as THREE.MeshBasicMaterial;
    mat.opacity = (1 - p) * 0.6;
    meshRef.current.scale.setScalar(1 + p * 4);
  });

  return (
    <mesh ref={meshRef} visible={false}>
      <sphereGeometry args={[0.5, 16, 16]} />
      <meshBasicMaterial color="#e8c870" transparent opacity={0} toneMapped={false} />
    </mesh>
  );
}

// Self-mod bloom — rapid bright flare when new agent spawns
export function SelfModBloom() {
  const bloomAgent = useStore((s) => s.pendingSelfModBloom);
  const clearEvent = useStore((s) => s.clearAnimationEvent);
  const meshRef = useRef<THREE.Mesh>(null);
  const progressRef = useRef(0);
  const activeRef = useRef(false);

  useEffect(() => {
    if (bloomAgent) {
      activeRef.current = true;
      progressRef.current = 0;
    }
  }, [bloomAgent]);

  useFrame((_, delta) => {
    if (!meshRef.current || !activeRef.current) {
      if (meshRef.current) meshRef.current.visible = false;
      return;
    }

    progressRef.current += delta * 1.5;
    const p = progressRef.current;

    if (p > 1.5) {
      activeRef.current = false;
      meshRef.current.visible = false;
      clearEvent('pendingSelfModBloom');
      return;
    }

    meshRef.current.visible = true;
    const mat = meshRef.current.material as THREE.MeshBasicMaterial;
    const flare = p < 0.3 ? p / 0.3 : Math.max(0, 1 - (p - 0.3) / 1.2);
    mat.opacity = flare * 0.8;
    meshRef.current.scale.setScalar(0.3 + flare * 2.5);
  });

  return (
    <mesh ref={meshRef} visible={false}>
      <sphereGeometry args={[1, 16, 16]} />
      <meshBasicMaterial color="#f0e0c0" transparent opacity={0} toneMapped={false} />
    </mesh>
  );
}

// Intent routing pulse
export function RoutingPulse() {
  const pulse = useStore((s) => s.pendingRoutingPulse);
  const clearEvent = useStore((s) => s.clearAnimationEvent);
  const meshRef = useRef<THREE.Mesh>(null);
  const progressRef = useRef(0);
  const activeRef = useRef(false);

  useEffect(() => {
    if (pulse) {
      activeRef.current = true;
      progressRef.current = 0;
    }
  }, [pulse]);

  useFrame((_, delta) => {
    if (!meshRef.current || !activeRef.current) {
      if (meshRef.current) meshRef.current.visible = false;
      return;
    }

    progressRef.current += delta * 3;
    const p = progressRef.current;

    if (p > 1) {
      activeRef.current = false;
      meshRef.current.visible = false;
      clearEvent('pendingRoutingPulse');
      return;
    }

    meshRef.current.visible = true;
    const mat = meshRef.current.material as THREE.MeshBasicMaterial;
    mat.opacity = (1 - p) * 0.6;
    meshRef.current.scale.setScalar(0.1 + p * 0.3);
  });

  return (
    <mesh ref={meshRef} visible={false}>
      <sphereGeometry args={[1, 8, 8]} />
      <meshBasicMaterial color="#f0e8e0" transparent opacity={0} toneMapped={false} />
    </mesh>
  );
}

// Feedback pulse — golden (approve) or cool-blue (reject) radial pulse from center
export function FeedbackPulse() {
  const feedbackPulse = useStore((s) => s.pendingFeedbackPulse);
  const clearEvent = useStore((s) => s.clearAnimationEvent);
  const meshRef = useRef<THREE.Mesh>(null);
  const progressRef = useRef(0);
  const activeRef = useRef(false);
  const colorRef = useRef('#f0b060');

  useEffect(() => {
    if (feedbackPulse) {
      activeRef.current = true;
      progressRef.current = 0;
      colorRef.current = feedbackPulse === 'good' ? '#f0b060' : '#4488cc';
    }
  }, [feedbackPulse]);

  useFrame((_, delta) => {
    if (!meshRef.current || !activeRef.current) {
      if (meshRef.current) meshRef.current.visible = false;
      return;
    }

    progressRef.current += delta * 2; // 500ms duration
    const p = progressRef.current;

    if (p > 1) {
      activeRef.current = false;
      meshRef.current.visible = false;
      clearEvent('pendingFeedbackPulse');
      return;
    }

    meshRef.current.visible = true;
    const mat = meshRef.current.material as THREE.MeshBasicMaterial;
    mat.color.set(colorRef.current);
    mat.opacity = (1 - p) * 0.1; // subtle — opacity 0.1 max
    meshRef.current.scale.setScalar(0.5 + p * 6);
  });

  return (
    <mesh ref={meshRef} visible={false}>
      <sphereGeometry args={[1, 16, 16]} />
      <meshBasicMaterial color="#f0b060" transparent opacity={0} toneMapped={false} />
    </mesh>
  );
}
