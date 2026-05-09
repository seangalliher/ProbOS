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
  // Cache which mouth blendshape names this VRM actually exposes — different
  // exporters use different names (preset 'aa', VRoid 'A', VRM0 'Fcl_MTH_A', etc.)
  const mouthShapesRef = useRef<string[]>([]);
  // Direct morph-target driver: many VRoid 0.x exports split the face into
  // multiple meshes (one per material) and the VRM expression bindings only
  // point at the first one. We collect ALL meshes that have Fcl_MTH_A and
  // drive their morphTargetInfluences directly so the entire face animates.
  const directMouthMeshesRef = useRef<{ mesh: any; index: number }[]>([]);

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
        const em: any = vrm.expressionManager;
        const candidates = ['aa', 'a', 'A', 'Fcl_MTH_A', 'mouth_a', 'M_A'];
        const found: string[] = [];
        if (em) {
          // VRM 1.0: em.expressions is a list with name strings.
          // VRM 0.x: em.blendShapeGroups; @pixiv/three-vrm normalises to expressions.
          const known = new Set<string>();
          (em.expressions ?? []).forEach((x: any) => { if (x?.expressionName) known.add(x.expressionName); });
          (em._expressionMap ? Object.keys(em._expressionMap) : []).forEach((n: string) => known.add(n));
          for (const name of candidates) {
            if (known.has(name)) found.push(name);
          }
        }
        mouthShapesRef.current = found;
        // Collect every mesh with a recognised mouth-open morph target so
        // we can drive them all directly (works around incomplete VRM
        // expression bindings on multi-material face meshes).
        const morphCandidates = ['Fcl_MTH_A', 'A', 'a', 'mouth_a', 'M_A', 'aa'];
        const direct: { mesh: any; index: number }[] = [];
        vrm.scene.traverse((o: any) => {
          if (!o.isMesh || !o.morphTargetDictionary) return;
          for (const key of morphCandidates) {
            if (key in o.morphTargetDictionary) {
              direct.push({ mesh: o, index: o.morphTargetDictionary[key] });
              break;
            }
          }
        });
        directMouthMeshesRef.current = direct;
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vrmUrl]);

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
        // Close all detected mouth shapes.
        const em = vrmRef.current?.expressionManager;
        if (em) for (const n of mouthShapesRef.current) em.setValue(n, 0);
        // And the direct morph-driven meshes.
        for (const { mesh, index } of directMouthMeshesRef.current) {
          if (mesh.morphTargetInfluences) mesh.morphTargetInfluences[index] = 0;
        }
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

    if (speakingRef.current) {
      // Compute mouth opening amplitude. If a real analyser is attached use
      // its byte data; otherwise fall back to a synthetic ~6 Hz envelope so
      // the avatar still animates when the browser doesn't expose TTS audio.
      let amp = 0;
      if (analyserRef.current) {
        const buf = new Uint8Array(analyserRef.current.frequencyBinCount);
        analyserRef.current.getByteFrequencyData(buf);
        let sum = 0;
        for (let i = 0; i < buf.length; i++) sum += buf[i];
        amp = sum / buf.length / 255;
      }
      // Synthetic 0→1 mouth open/close envelope at ~4 Hz. Big swing so the
      // motion is unambiguous on stylised VRoid faces; phoneme-accurate
      // lip-sync is AD-721b territory.
      const synth = 0.5 - 0.5 * Math.cos(t * 2 * Math.PI * 4);
      const value = Math.min(1.0, Math.max(amp * 1.4, synth));
      const em = vrm.expressionManager;
      if (em) {
        // Drive every detected mouth shape AND fall back to common names.
        const targets = mouthShapesRef.current.length > 0 ? mouthShapesRef.current : ['aa', 'a', 'A'];
        for (const n of targets) em.setValue(n, value);
      }
    }
    // Run expression manager + bone update first.
    vrm.update(delta);
    // Then direct-write morph influences. Doing this AFTER vrm.update() is
    // critical: VRMExpressionManager.update() resets every morph target on
    // every bound mesh each frame, which would clobber our writes if we did
    // them before. By writing after update we win the last-write race.
    if (speakingRef.current) {
      // Recompute the value (mirrors the formula used above).
      const t2 = (typeof performance !== 'undefined' ? performance.now() : Date.now()) / 1000;
      let amp2 = 0;
      if (analyserRef.current) {
        const buf = new Uint8Array(analyserRef.current.frequencyBinCount);
        analyserRef.current.getByteFrequencyData(buf);
        let sum = 0;
        for (let i = 0; i < buf.length; i++) sum += buf[i];
        amp2 = sum / buf.length / 255;
      }
      const synth2 = 0.5 - 0.5 * Math.cos(t2 * 2 * Math.PI * 4);
      const val2 = Math.min(1.0, Math.max(amp2 * 1.4, synth2));
      for (const { mesh, index } of directMouthMeshesRef.current) {
        if (mesh.morphTargetInfluences) mesh.morphTargetInfluences[index] = val2;
      }
    }
  });

  return vrmRef.current ? <primitive object={vrmRef.current.scene} /> : null;
}

export { applyExpressionsFromSignals as _applyExpressionsFromSignals };
