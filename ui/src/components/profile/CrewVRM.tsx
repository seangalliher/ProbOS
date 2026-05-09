/** AD-721 D5: VRM loader + viewer with expression-channel mapping
 *  and TTS-driven mouth animation.
 *
 *  Subscribes to AD-718's `onSpeechEvent` and drives the `aa` blend shape
 *  from a Web Audio analyser (or a synthetic amplitude curve when real-audio
 *  capture is unavailable — see AD-721 D5 / `speechAmplitude.ts`).
 */

import { useEffect, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils, VRMHumanBoneName, type VRM } from '@pixiv/three-vrm';
import { onSpeechEvent } from '../../audio/voice';
import { _attachAnalyserOrSchedule, type FakeAnalyser } from '../../audio/speechAmplitude';
import type { AgentSignals } from './avatarSignals';

interface Props {
  vrmUrl: string;
  agentId: string;
  expressionOverrides: Record<string, number>;
  signals: AgentSignals;
  onLoadError: () => void;
}

/** Set a relaxed A-pose so VRMs without an animation clip don't ship as
 *  T-pose ("arms straight out"). Most VRMs default arms ~90° outward; this
 *  rotates upper arms ~60° down at the shoulder and adds a small elbow bend. */
function applyAPose(vrm: VRM): void {
  const h = vrm.humanoid;
  if (!h) return;
  const set = (name: VRMHumanBoneName, x: number, y: number, z: number) => {
    const node = h.getNormalizedBoneNode(name);
    if (node) node.rotation.set(x, y, z);
  };
  // Z-rotation on shoulders pulls arms down. Sign convention varies by VRM
  // exporter — for VRoid/most VRM 0.x the LEFT upper arm needs negative Z and
  // the RIGHT needs positive Z (the opposite of T-pose intuition).
  set(VRMHumanBoneName.LeftUpperArm, 0, 0, -1.2);
  set(VRMHumanBoneName.RightUpperArm, 0, 0, 1.2);
  set(VRMHumanBoneName.LeftLowerArm, 0, -0.15, -0.1);
  set(VRMHumanBoneName.RightLowerArm, 0, 0.15, 0.1);
  // Slight shoulder relax.
  set(VRMHumanBoneName.LeftShoulder, 0, 0, -0.05);
  set(VRMHumanBoneName.RightShoulder, 0, 0, 0.05);
}

function applyExpressionsFromSignals(vrm: VRM, signals: AgentSignals, overrides: Record<string, number>): void {
  const em = vrm.expressionManager;
  if (!em) return;

  // Reset known channels first to avoid drift.
  for (const name of ['happy', 'sad', 'angry', 'surprised', 'lookUp', 'oh', 'relaxed']) {
    em.setValue(name, 0);
  }

  if (signals.trust_delta > 0) {
    em.setValue('happy', Math.min(1, signals.trust_delta * 2));
  } else if (signals.trust_delta < 0) {
    em.setValue('sad', Math.min(1, -signals.trust_delta * 2));
  }
  if (signals.load > 0.5) {
    em.setValue('lookUp', 0.3);
    em.setValue('oh', 0.3);
  }
  if (signals.working_state === 'blocked') {
    em.setValue('angry', 0.4);
  }
  if (signals.tier3_alert) {
    em.setValue('surprised', 0.6);
  }

  // Overrides bias the baseline AFTER signal-driven weights.
  for (const [name, weight] of Object.entries(overrides)) {
    try {
      em.setValue(name, weight);
    } catch (_err) {
      // Unknown blend-shape names degrade silently — the VRM might not implement them.
    }
  }
}

export function CrewVRM({ vrmUrl, agentId, expressionOverrides, signals, onLoadError }: Props) {
  const vrmRef = useRef<VRM | null>(null);
  const analyserRef = useRef<AnalyserNode | FakeAnalyser | null>(null);
  const speakingRef = useRef(false);

  // Load the VRM once per URL change.
  useEffect(() => {
    if (!vrmUrl) return;
    let mounted = true;
    // Resolve bare filenames (e.g. "Ezri.vrm") against the avatar-serving API.
    // Absolute / root-relative URLs are passed through.
    const resolvedUrl =
      /^(https?:|\/|blob:|data:)/.test(vrmUrl) ? vrmUrl : `/api/system/avatars/${vrmUrl}`;
    const loader = new GLTFLoader();
    loader.register((parser) => new VRMLoaderPlugin(parser));
    loader.load(
      resolvedUrl,
      (gltf: any) => {
        if (!mounted) return;
        const vrm = gltf.userData.vrm as VRM | undefined;
        if (!vrm) {
          onLoadError();
          return;
        }
        // VRM 0.x models face -Z; rotate so they face the camera (+Z).
        // No-op for VRM 1.0 models, which already face +Z.
        try { VRMUtils.rotateVRM0(vrm); } catch (_e) { /* older lib versions */ }
        // Disable frustum culling — tight camera + skinned meshes can clip otherwise.
        vrm.scene.traverse((obj: any) => { obj.frustumCulled = false; });
        // Lower the arms — VRMs ship in T-pose by default.
        applyAPose(vrm);
        // AD-721 diagnostics: log material + texture status to console so we
        // can tell whether a "white blob" is a lighting issue vs a texture
        // decode / MToon-default-color issue.
        const matSummary: { name: string; type: string; map: boolean; color?: string }[] = [];
        vrm.scene.traverse((obj: any) => {
          if (obj.isMesh && obj.material) {
            const mats = Array.isArray(obj.material) ? obj.material : [obj.material];
            for (const m of mats) {
              matSummary.push({
                name: obj.name,
                type: m.type || m.constructor?.name,
                map: !!m.map,
                color: m.color?.getHexString?.(),
              });
            }
          }
        });
        // eslint-disable-next-line no-console
        console.log('[AD-721 VRM loaded]', { url: vrmUrl, meta: vrm.meta, materials: matSummary });
        vrmRef.current = vrm;
      },
      undefined,
      (err: unknown) => {
        // eslint-disable-next-line no-console
        console.warn('[AD-721 VRM load failed]', { url: resolvedUrl, err });
        onLoadError();
      },
    );
    return () => { mounted = false; };
  }, [vrmUrl, onLoadError]);

  // Subscribe to TTS events for mouth animation.
  useEffect(() => {
    const off = onSpeechEvent((e) => {
      if (e.agent_id !== agentId) return;
      if (e.type === 'start') {
        analyserRef.current = _attachAnalyserOrSchedule(e.utterance);
        speakingRef.current = true;
      } else if (e.type === 'end') {
        speakingRef.current = false;
        analyserRef.current = null;
        vrmRef.current?.expressionManager?.setValue('aa', 0);
      }
    });
    return off;
  }, [agentId]);

  useFrame((_state, delta) => {
    const vrm = vrmRef.current;
    if (!vrm) return;
    applyExpressionsFromSignals(vrm, signals, expressionOverrides);

    // Idle body animation: breathing + gentle sway. Adds life when no clip exists.
    const t = (typeof performance !== 'undefined' ? performance.now() : Date.now()) / 1000;
    const h = vrm.humanoid;
    const head = h?.getNormalizedBoneNode(VRMHumanBoneName.Head);
    const chest = h?.getNormalizedBoneNode(VRMHumanBoneName.Chest)
                ?? h?.getNormalizedBoneNode(VRMHumanBoneName.UpperChest)
                ?? h?.getNormalizedBoneNode(VRMHumanBoneName.Spine);
    if (head) {
      const sway = Math.sin(t * 0.6) * 0.03;
      const bob = Math.sin(t * 1.4) * 0.015;
      const speakBob = speakingRef.current ? Math.sin(t * 5) * 0.04 : 0;
      head.rotation.y = sway;
      head.rotation.x = bob + speakBob;
    }
    if (chest) {
      // Subtle breathing — 0.25 Hz, ±1.5%.
      const breathe = 1 + Math.sin(t * 2 * Math.PI * 0.25) * 0.015;
      chest.scale.set(breathe, breathe, breathe);
    }

    if (speakingRef.current && analyserRef.current) {
      const buf = new Uint8Array(analyserRef.current.frequencyBinCount);
      analyserRef.current.getByteFrequencyData(buf);
      let sum = 0;
      for (let i = 0; i < buf.length; i++) sum += buf[i];
      const amp = sum / buf.length / 255;
      vrm.expressionManager?.setValue('aa', Math.min(0.9, amp * 1.4));
    }
    vrm.update(delta);
  });

  return vrmRef.current ? <primitive object={vrmRef.current.scene} /> : null;
}

export { applyExpressionsFromSignals as _applyExpressionsFromSignals };
