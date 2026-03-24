/* Agent node rendering — instanced spheres with trust+pool color, confidence glow (Fix 2,3,5) */

import { useRef, useMemo, useEffect } from 'react';
import { useFrame, ThreeEvent } from '@react-three/fiber';
import * as THREE from 'three';
import { useStore } from '../store/useStore';
import { poolTintBlend, confidenceToIntensity, agentNodeSize } from './scene';

const _tempObj = new THREE.Object3D();
const _tempColor = new THREE.Color();
const _ringObj = new THREE.Object3D();
const _ringColor = new THREE.Color();

interface AgentNodesProps {
  onPointerMove?: (e: ThreeEvent<PointerEvent>) => void;
  onPointerOut?: () => void;
  onClick?: (e: ThreeEvent<MouseEvent>) => void;
}

export function AgentNodes({ onPointerMove, onPointerOut, onClick }: AgentNodesProps = {}) {
  const agents = useStore((s) => s.agents);
  const meshRef = useRef<THREE.InstancedMesh>(null);
  const ringRef = useRef<THREE.InstancedMesh>(null);

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

  // Ring colors (amber, initial)
  const ringColors = useMemo(() => {
    const arr = new Float32Array(Math.max(count, 1) * 3);
    for (let i = 0; i < count; i++) {
      arr[i * 3] = 0.94;
      arr[i * 3 + 1] = 0.69;
      arr[i * 3 + 2] = 0.38;
    }
    return arr;
  }, [count]);

  // Eagerly populate instance matrices so raycasting works on first frame
  useEffect(() => {
    const mesh = meshRef.current;
    if (!mesh || count === 0) return;

    agentList.forEach((agent, i) => {
      const baseSize = agentNodeSize(agent.tier, agent.confidence);
      _tempObj.position.set(...agent.position);
      _tempObj.scale.setScalar(baseSize);
      _tempObj.updateMatrix();
      mesh.setMatrixAt(i, _tempObj.matrix);
    });
    mesh.instanceMatrix.needsUpdate = true;
    mesh.computeBoundingSphere();

    // Initialize rings as invisible
    const ring = ringRef.current;
    if (ring) {
      for (let i = 0; i < count; i++) {
        _ringObj.scale.setScalar(0);
        _ringObj.updateMatrix();
        ring.setMatrixAt(i, _ringObj.matrix);
      }
      ring.instanceMatrix.needsUpdate = true;
    }
  }, [agentList, count]);

  // Animation: breathing + position + color updates + ring indicators (AD-324, AD-406)
  useFrame((state) => {
    const mesh = meshRef.current;
    if (!mesh || count === 0) return;

    const t = state.clock.elapsedTime;
    const connected = useStore.getState().connected;

    // Build attention set once per frame (AD-324)
    const tasks = useStore.getState().agentTasks;
    const agentConversations = useStore.getState().agentConversations;
    const activeProfileAgent = useStore.getState().activeProfileAgent;
    const notifications = useStore.getState().notifications;
    const attentionSet = new Set(
      tasks?.filter(t => t.requires_action).map(t => t.agent_id) ?? []
    );

    // Build per-agent notification maps: error/action_required → red, info → cyan
    const agentErrorNotifs = new Set<string>();
    const agentInfoNotifs = new Set<string>();
    if (notifications) {
      for (const n of notifications) {
        if (n.acknowledged) continue;
        if (n.notification_type === 'error' || n.notification_type === 'action_required') {
          agentErrorNotifs.add(n.agent_id);
        } else if (n.notification_type === 'info') {
          agentInfoNotifs.add(n.agent_id);
        }
      }
    }

    const ring = ringRef.current;

    // Ring color constants: red (high priority), amber (conversation), cyan (info)
    const RED_R = 0.94, RED_G = 0.30, RED_B = 0.25;
    const AMBER_R = 0.94, AMBER_G = 0.69, AMBER_B = 0.38;
    const CYAN_R = 0.30, CYAN_G = 0.78, CYAN_B = 0.85;

    agentList.forEach((agent, i) => {
      // New agents (< 5 min) pulse faster and brighter
      const isNew = agent.createdAt != null && (Date.now() - agent.createdAt < 300000);
      const needsAttention = attentionSet.has(agent.id);
      const breathAmplitude = needsAttention ? 0.08 : (isNew ? 0.15 : 0.03);
      const breathPhase = t * (isNew ? 4.0 : 1.5) + i * 0.7;
      const breathScale = connected ? (1 + Math.sin(breathPhase) * breathAmplitude) : 1.0;

      // Tier-based sizing (Fix 5)
      const baseSize = agentNodeSize(agent.tier, agent.confidence);
      const size = baseSize * breathScale;

      _tempObj.position.set(...agent.position);
      _tempObj.scale.setScalar(size);
      _tempObj.updateMatrix();
      mesh.setMatrixAt(i, _tempObj.matrix);

      // Update color: dim to near-dark when disconnected
      _tempColor.copy(poolTintBlend(agent.trust, agent.pool));
      const intensity = connected
        ? confidenceToIntensity(agent.confidence) * (isNew ? 1.5 : 1.0)
        : 0.05;
      _tempColor.multiplyScalar(intensity);

      // Activity flash: boost brightness for 500ms after activation (AD-287)
      const timeSinceActive = Date.now() - (agent.activatedAt ?? 0);
      if (timeSinceActive < 500) {
        const flash = 1 + 2 * (1 - timeSinceActive / 500); // 3x -> 1x over 500ms
        _tempColor.multiplyScalar(flash);
      }

      mesh.setColorAt(i, _tempColor);

      // Priority ring indicator (AD-406): red > amber > cyan > hidden
      // Ring consolidates all agent-to-Captain visual cues:
      //   Red:  error/action_required notifications, requires_action tasks
      //   Amber: active conversation, minimized chat (unread or not)
      //   Cyan: informational notifications
      if (ring && connected) {
        const conv = agentConversations.get(agent.id);
        const isProfileOpen = activeProfileAgent === agent.id;
        const hasError = agentErrorNotifs.has(agent.id) || needsAttention;
        const hasConv = isProfileOpen || conv?.minimized;
        const hasInfo = agentInfoNotifs.has(agent.id);

        if (hasError || hasConv || hasInfo) {
          const ringSize = baseSize * 0.7;
          const tiltAngle = 0.6 + Math.sin(t * 0.3 + i) * 0.2; // gentle wobble

          // Determine ring color and spin speed by priority
          let rR: number, rG: number, rB: number;
          let spinSpeed: number;

          if (hasError) {
            // Red — fast spin (3 rev/s), pulsing brightness
            const pulse = 0.7 + 0.3 * Math.sin(t * 6 * Math.PI);
            rR = RED_R * pulse; rG = RED_G * pulse; rB = RED_B * pulse;
            spinSpeed = 6 * Math.PI;
          } else if (hasConv) {
            const hasUnread = conv?.minimized && conv.unreadCount > 0;
            if (hasUnread) {
              // Amber — fast spin (3 rev/s), bright
              rR = AMBER_R; rG = AMBER_G; rB = AMBER_B;
              spinSpeed = 6 * Math.PI;
            } else {
              // Amber — steady spin (0.5 rev/s), dim
              rR = AMBER_R * 0.6; rG = AMBER_G * 0.6; rB = AMBER_B * 0.6;
              spinSpeed = Math.PI;
            }
          } else {
            // Cyan — steady spin (0.5 rev/s)
            rR = CYAN_R; rG = CYAN_G; rB = CYAN_B;
            spinSpeed = Math.PI;
          }

          _ringObj.position.set(...agent.position);
          _ringObj.rotation.set(tiltAngle, t * spinSpeed, 0);
          _ringObj.scale.setScalar(ringSize);
          _ringObj.updateMatrix();
          ring.setMatrixAt(i, _ringObj.matrix);

          _ringColor.setRGB(rR, rG, rB);
          ring.setColorAt(i, _ringColor);
        } else {
          // Hide ring — scale to 0
          _ringObj.scale.setScalar(0);
          _ringObj.updateMatrix();
          ring.setMatrixAt(i, _ringObj.matrix);
        }
      }
    });

    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    mesh.computeBoundingSphere();

    if (ring) {
      ring.instanceMatrix.needsUpdate = true;
      if (ring.instanceColor) ring.instanceColor.needsUpdate = true;
    }
  });

  if (count === 0) return null;

  return (
    <>
      <instancedMesh
        key={`agents-${count}`}
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
      {/* Priority ring indicators: red (error/action) > amber (chat) > cyan (info) */}
      <instancedMesh
        key={`rings-${count}`}
        ref={ringRef}
        args={[undefined, undefined, count]}
        raycast={() => null}
      >
        <torusGeometry args={[1, 0.04, 8, 32]} />
        <meshBasicMaterial
          toneMapped={false}
          transparent
          opacity={0.8}
        />
        <instancedBufferAttribute
          attach="instanceColor"
          args={[ringColors, 3]}
        />
      </instancedMesh>
    </>
  );
}
