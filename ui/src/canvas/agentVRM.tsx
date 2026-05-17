/** AD-721f: Cognitive-Canvas VRM avatar (one agent, canvas-scale).
 *
 *  Renders a single agent's VRM at its store-driven canvas position.
 *  Reuses the GLTFLoader + VRMLoaderPlugin pipeline from CrewVRM (which is
 *  the popout-grade viewer). This canvas-grade renderer intentionally omits
 *  lip-sync, expression channels, and per-frame morph drivers — those live
 *  in the popout to keep the per-frame canvas cost bounded under the
 *  ``canvas_max_concurrent_vrms`` cap (default 12).
 *
 *  Honest-degrade: if load fails, invokes ``onLoadError(agentId)`` so the
 *  caller (``AgentNodes``) can revert that agent to its orb instance. The
 *  caller maintains a ``failedVrmAgentsRef`` set to avoid retrying.
 */

import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils, type VRM } from '@pixiv/three-vrm';

export interface AgentVRMProps {
  agentId: string;
  position: [number, number, number];
  vrmUrl: string;
  /** Called on load failure so the canvas can fall back to the orb path. */
  onLoadError: (agentId: string) => void;
  /** World-unit scale applied to the loaded VRM root. Defaults to 1.0. */
  scale?: number;
  /** Optional pointer handlers — wired to the agent in the parent canvas. */
  onPointerOver?: () => void;
  onPointerOut?: () => void;
  onClick?: () => void;
}

/** Resolve a bare filename ("Ezri.vrm") against the avatar-serving API.
 *  Absolute / blob / data URLs are passed through. Mirrors the CrewVRM
 *  resolver so both paths consume the same source. */
function _resolveVrmUrl(vrmUrl: string): string {
  return /^(https?:|\/|blob:|data:)/.test(vrmUrl)
    ? vrmUrl
    : `/api/system/avatars/${vrmUrl}`;
}

export function AgentVRM({
  agentId,
  position,
  vrmUrl,
  onLoadError,
  scale = 1.0,
  onPointerOver,
  onPointerOut,
  onClick,
}: AgentVRMProps) {
  const [vrm, setVrm] = useState<VRM | null>(null);
  const errorCalledRef = useRef(false);

  useEffect(() => {
    if (!vrmUrl) {
      // Empty vrmUrl is a soft-skip (caller stays on orb path). Do not
      // call onLoadError here -- the caller already knows there is no VRM
      // to load.
      return;
    }
    let mounted = true;
    errorCalledRef.current = false;
    const loader = new GLTFLoader();
    loader.register((parser) => new VRMLoaderPlugin(parser));
    loader.load(
      _resolveVrmUrl(vrmUrl),
      (gltf: any) => {
        if (!mounted) return;
        const loaded = gltf.userData?.vrm as VRM | undefined;
        if (!loaded) {
          if (!errorCalledRef.current) {
            errorCalledRef.current = true;
            // eslint-disable-next-line no-console
            console.warn(
              `[AD-721f] VRM load returned no userData.vrm for ` +
              `agent=${agentId} url=${vrmUrl}; reverting to orb instance`,
            );
            onLoadError(agentId);
          }
          return;
        }
        try { VRMUtils.rotateVRM0(loaded); } catch (_e) { /* older lib */ }
        loaded.scene.traverse((obj: any) => { obj.frustumCulled = false; });
        setVrm(loaded);
      },
      undefined,
      (_err) => {
        if (!mounted) return;
        if (errorCalledRef.current) return;
        errorCalledRef.current = true;
        // eslint-disable-next-line no-console
        console.warn(
          `[AD-721f] VRM load error for agent=${agentId} url=${vrmUrl}; ` +
          `reverting to orb instance`,
        );
        onLoadError(agentId);
      },
    );
    return () => {
      mounted = false;
    };
  }, [vrmUrl, agentId, onLoadError]);

  if (!vrm) return null;

  return (
    <group
      position={position}
      scale={[scale, scale, scale]}
      onPointerOver={onPointerOver}
      onPointerOut={onPointerOut}
      onClick={onClick}
    >
      <primitive object={vrm.scene} />
    </group>
  );
}

/** Pure helper: pick the closest ``maxCount`` agents within ``lodDistance`` of
 *  the camera position. Exported for unit testing. Stable result order:
 *  closest-first. Agents in ``excluded`` (e.g. already-failed loads) are
 *  filtered out before distance sort. */
export function _pickCloseAgents<
  T extends { id: string; position: [number, number, number] }
>(
  agents: readonly T[],
  cameraPosition: readonly [number, number, number],
  lodDistance: number,
  maxCount: number,
  excluded: ReadonlySet<string> = new Set(),
): T[] {
  if (maxCount <= 0 || lodDistance <= 0) return [];
  const lodDistanceSq = lodDistance * lodDistance;
  const scored: { a: T; dSq: number }[] = [];
  for (const a of agents) {
    if (excluded.has(a.id)) continue;
    const dx = a.position[0] - cameraPosition[0];
    const dy = a.position[1] - cameraPosition[1];
    const dz = a.position[2] - cameraPosition[2];
    const dSq = dx * dx + dy * dy + dz * dz;
    if (dSq <= lodDistanceSq) {
      scored.push({ a, dSq });
    }
  }
  scored.sort((x, y) => x.dSq - y.dSq);
  return scored.slice(0, maxCount).map((s) => s.a);
}
