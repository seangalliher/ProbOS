/* Agent node rendering — instanced spheres with trust+pool color, confidence glow (Fix 2,3,5) */

import { useRef, useMemo, useEffect, useState, useCallback } from 'react';
import { useFrame, useThree, ThreeEvent } from '@react-three/fiber';
import * as THREE from 'three';
import { useStore } from '../store/useStore';
import { poolTintBlend, confidenceToIntensity, agentNodeSize } from './scene';
import { AgentVRM, _pickCloseAgents } from './agentVRM';
import type { Agent } from '../store/types';

// AD-721f: Cognitive-Canvas VRM avatar config (default OFF; opt-in via
// parent <CognitiveCanvas vrmConfig=...>). When ``enabled`` is false the
// orb instanced-mesh path is bit-for-bit equivalent to the pre-AD-721f path.
export interface CanvasVrmConfig {
  enabled: boolean;
  maxConcurrent: number;
  lodDistance: number;
  /** Resolve an agent to its VRM URL (bare filename or absolute). Return
   *  null/empty to keep that agent on the orb path. The default resolver
   *  returns null for every agent, which means the canvas stays orb-only
   *  even when ``enabled`` is true until a resolver is provided. */
  resolveVrmUrl?: (agent: Agent) => string | null;
  /** Optional world-unit scale applied to every mounted VRM. Defaults to
   *  ``agentNodeSize(agent.tier, agent.confidence)`` so VRMs match the orb
   *  size envelope. */
  vrmScale?: (agent: Agent) => number;
}

const DEFAULT_VRM_CONFIG: CanvasVrmConfig = {
  enabled: false,
  maxConcurrent: 12,
  lodDistance: 15.0,
  resolveVrmUrl: () => null,
};

const _tempObj = new THREE.Object3D();
const _tempColor = new THREE.Color();
const _ringObj = new THREE.Object3D();
const _ringColor = new THREE.Color();

// AD-436: Orbital notification electron math
const _electronEulers = [
  new THREE.Euler(0.35, 0, 0),           // Tier 0 (RED): 20° tilt
  new THREE.Euler(1.05, 0.52, 0),        // Tier 1 (AMBER): 60° + 30° tilt
  new THREE.Euler(-0.52, 1.05, 0),       // Tier 2 (CYAN): -30° + 60° tilt
];
const _orbitQuat = new THREE.Quaternion();
const _orbitVec = new THREE.Vector3();

const GOLDEN_ANGLE = 2.399963; // 137.5° in radians — prevents visual clustering

interface AgentNodesProps {
  onPointerMove?: (e: ThreeEvent<PointerEvent>) => void;
  onPointerOut?: () => void;
  onClick?: (e: ThreeEvent<MouseEvent>) => void;
  /** AD-721f: optional canvas-VRM configuration. When omitted or
   *  ``enabled=false``, the orb path is used for every agent (unchanged). */
  vrmConfig?: CanvasVrmConfig;
}

export function AgentNodes({ onPointerMove, onPointerOut, onClick, vrmConfig }: AgentNodesProps = {}) {
  const agents = useStore((s) => s.agents);
  const meshRef = useRef<THREE.InstancedMesh>(null);
  const ringRef = useRef<THREE.InstancedMesh>(null);

  // AD-721f: agents whose VRM load failed -- never retried this session;
  // they stay on the orb path. Reset by a remount of <AgentNodes />.
  const [failedVrmAgentIds, setFailedVrmAgentIds] = useState<ReadonlySet<string>>(
    () => new Set<string>(),
  );
  const onVrmLoadError = useCallback((agentId: string) => {
    setFailedVrmAgentIds((prev) => {
      if (prev.has(agentId)) return prev;
      const next = new Set(prev);
      next.add(agentId);
      // eslint-disable-next-line no-console
      console.warn(
        `[AD-721f] agent=${agentId} VRM load failed; orb instance restored`,
      );
      return next;
    });
  }, []);

  const cfg: CanvasVrmConfig = vrmConfig ?? DEFAULT_VRM_CONFIG;
  const vrmEnabled = cfg.enabled === true;
  // useThree hook must be called unconditionally to satisfy React rules;
  // its result is only consulted when vrmEnabled is true.
  const three = useThree();

  const agentList = useMemo(() => Array.from(agents.values()), [agents]);
  const count = agentList.length;

  // AD-721f: compute the set of agents currently rendered as VRMs (camera-
  // distance closest N within lodDistance, excluding load-failed agents and
  // agents whose resolver returns null). Updated on a frame-throttled cadence
  // to avoid React re-renders every frame; the orb path stays smooth.
  const [vrmAgentIds, setVrmAgentIds] = useState<ReadonlySet<string>>(
    () => new Set<string>(),
  );
  const vrmCullTickRef = useRef(0);
  useFrame(() => {
    if (!vrmEnabled) {
      if (vrmAgentIds.size > 0) setVrmAgentIds(new Set<string>());
      return;
    }
    vrmCullTickRef.current = (vrmCullTickRef.current + 1) % 15;
    if (vrmCullTickRef.current !== 0) return;
    const cam = three.camera?.position;
    const camPos: [number, number, number] = cam
      ? [cam.x, cam.y, cam.z]
      : [0, 0, 0];
    const eligible = cfg.resolveVrmUrl
      ? agentList.filter((a) => {
          const url = cfg.resolveVrmUrl!(a);
          return typeof url === 'string' && url.length > 0;
        })
      : [];
    const picked = _pickCloseAgents(
      eligible,
      camPos,
      cfg.lodDistance,
      cfg.maxConcurrent,
      failedVrmAgentIds,
    );
    const next = new Set(picked.map((a) => a.id));
    // Cheap set-equality check before triggering a re-render.
    if (next.size !== vrmAgentIds.size) {
      setVrmAgentIds(next);
      return;
    }
    for (const id of next) {
      if (!vrmAgentIds.has(id)) {
        setVrmAgentIds(next);
        return;
      }
    }
  });

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
    const arr = new Float32Array(Math.max(count * 6, 1) * 3);
    // Initialize all to zero (hidden electrons start black)
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
      for (let i = 0; i < count * 6; i++) {
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

      // AD-721f: when this agent is mounted as a VRM, hide its orb instance
      // by zeroing the scale. Raycaster on the orb mesh ignores zero-scaled
      // instances; the VRM root group carries pointer handlers instead.
      const renderedAsVrm = vrmEnabled && vrmAgentIds.has(agent.id);
      const effectiveSize = renderedAsVrm ? 0 : size;

      _tempObj.position.set(...agent.position);
      _tempObj.scale.setScalar(effectiveSize);
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

      // AD-436: Orbital electron notification dots
      // For each agent, populate up to 6 electron instances (2 per tier, 3 tiers)
      // Instance index = agentIndex * 6 + tierIndex * 2 + dotIndex
      if (ring && connected) {
        const conv = agentConversations.get(agent.id);
        const isProfileOpen = activeProfileAgent === agent.id;
        const hasError = agentErrorNotifs.has(agent.id) || needsAttention;
        const hasConv = isProfileOpen || conv?.minimized;
        const hasInfo = agentInfoNotifs.has(agent.id);

        // Determine active tiers and their params
        const tiers: Array<{
          active: boolean;
          dots: number;
          r: number; g: number; b: number;
          orbitRadius: number;
          speed: number;
          pulse: boolean;
        }> = [
          // Tier 0: RED (error/action)
          {
            active: hasError,
            dots: hasError ? 2 : 0,
            r: RED_R, g: RED_G, b: RED_B,
            orbitRadius: baseSize * 1.3,
            speed: 3,  // 3 rev/s
            pulse: true,
          },
          // Tier 1: AMBER (conversation)
          {
            active: !!hasConv,
            dots: hasConv ? 2 : 0,
            r: AMBER_R, g: AMBER_G, b: AMBER_B,
            orbitRadius: baseSize * 1.6,
            speed: (conv?.minimized && conv.unreadCount > 0) ? 3 : 0.5,
            pulse: false,
          },
          // Tier 2: CYAN (info)
          {
            active: hasInfo,
            dots: hasInfo ? 2 : 0,
            r: CYAN_R, g: CYAN_G, b: CYAN_B,
            orbitRadius: baseSize * 1.9,
            speed: 0.5,
            pulse: false,
          },
        ];

        for (let tier = 0; tier < 3; tier++) {
          const cfg = tiers[tier];
          for (let dot = 0; dot < 2; dot++) {
            const instanceIdx = i * 6 + tier * 2 + dot;

            if (cfg.active && dot < cfg.dots) {
              // Phase offset: golden angle per agent + 180° between dots
              const phase = i * GOLDEN_ANGLE + dot * Math.PI;
              const angle = t * cfg.speed * 2 * Math.PI + phase;

              // Circular orbit in XZ plane
              _orbitVec.set(
                Math.cos(angle) * cfg.orbitRadius,
                0,
                Math.sin(angle) * cfg.orbitRadius,
              );

              // Apply tier-specific tilt
              _orbitQuat.setFromEuler(_electronEulers[tier]);
              _orbitVec.applyQuaternion(_orbitQuat);

              // Translate to agent world position
              _ringObj.position.set(
                agent.position[0] + _orbitVec.x,
                agent.position[1] + _orbitVec.y,
                agent.position[2] + _orbitVec.z,
              );

              // Electron scale — pulse for RED tier
              const electronScale = cfg.pulse
                ? 0.12 + 0.06 * Math.sin(t * 8)
                : 0.15;
              _ringObj.scale.setScalar(electronScale);
              _ringObj.updateMatrix();
              ring.setMatrixAt(instanceIdx, _ringObj.matrix);

              // Dim amber when no unread
              const dimFactor = (tier === 1 && !(conv?.minimized && conv.unreadCount > 0)) ? 0.6 : 1.0;
              _ringColor.setRGB(cfg.r * dimFactor, cfg.g * dimFactor, cfg.b * dimFactor);
              ring.setColorAt(instanceIdx, _ringColor);
            } else {
              // Hide: scale to 0
              _ringObj.scale.setScalar(0);
              _ringObj.updateMatrix();
              ring.setMatrixAt(instanceIdx, _ringObj.matrix);
            }
          }
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

  // AD-721f: VRM siblings (one per agent currently in the VRM set).
  const vrmAgents = vrmEnabled
    ? agentList.filter((a) => vrmAgentIds.has(a.id))
    : [];

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
      {/* Orbital electron notification dots (AD-436) */}
      <instancedMesh
        key={`electrons-${count}`}
        ref={ringRef}
        args={[undefined, undefined, count * 6]}
        raycast={() => null}
      >
        <sphereGeometry args={[1, 8, 8]} />
        <meshBasicMaterial
          toneMapped={false}
          transparent
          opacity={0.9}
        />
        <instancedBufferAttribute
          attach="instanceColor"
          args={[ringColors, 3]}
        />
      </instancedMesh>
      {/* AD-721f: canvas-scale VRMs for the close-N set when enabled. */}
      {vrmAgents.map((agent) => {
        const url = cfg.resolveVrmUrl?.(agent);
        if (!url) return null;
        const scale = cfg.vrmScale
          ? cfg.vrmScale(agent)
          : agentNodeSize(agent.tier, agent.confidence);
        const setHovered = useStore.getState().setHoveredAgent;
        const openProfile = useStore.getState().openAgentProfile;
        return (
          <AgentVRM
            key={`vrm-${agent.id}`}
            agentId={agent.id}
            position={agent.position}
            vrmUrl={url}
            scale={scale}
            onLoadError={onVrmLoadError}
            onPointerOver={() => setHovered?.(agent, { x: 0, y: 0 })}
            onPointerOut={() => setHovered?.(null, { x: 0, y: 0 })}
            onClick={() => openProfile?.(agent.id)}
          />
        );
      })}
    </>
  );
}
